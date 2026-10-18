"""归档容量三闸：保留期挡时间、容量闸挡速率，两个维度都要设。

对标 OpenClaw session.maintenance（maxDiskBytes / highWaterBytes / maxEntries）：
- 只设保留期 → 高频用户的 90 天内照样能把磁盘撑满；
- 触发用上限、目标用 high_water（留 20% 滞回），否则退化成"每天削一点点"；
- 裁剪顺序：孤儿优先 → 其余最旧优先；只删副本，源文件不动。
"""

import json
import os
import time

from app.capture import archive
from app.capture.models import Session, SessionRef
from app.distill import maintenance
from app.store.store import SESSION_ARCHIVE_MAX_FILE_BYTES, Store

DAY = 86400


def _mk_file(store, agent: str, name: str, data: bytes, age_days: float):
    """在 sessions/<agent>/ 造一个内容为 data、mtime 为 age_days 天前的文件。"""
    d = store.dir("sessions") / agent
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_bytes(data)
    ts = time.time() - age_days * DAY
    os.utime(f, (ts, ts))
    return f


def _mk(store, agent: str, name: str, size: int, age_days: float) -> str:
    """在 sessions/<agent>/ 造一个 size 字节、mtime 为 age_days 天前的文件。"""
    d = store.dir("sessions") / agent
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_bytes(b"x" * size)
    ts = time.time() - age_days * DAY
    os.utime(f, (ts, ts))
    return f.name


def test_disk_gate_evicts_oldest_to_high_water(tmp_path):
    """总量超上限 → 按最旧优先裁，削到 high_water 即停（不是削到刚好够一个文件）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    _mk(store, "claude", "old-1.jsonl", 400, 80)
    _mk(store, "claude", "old-2.jsonl", 400, 70)
    _mk(store, "claude", "new-1.jsonl", 400, 5)
    _mk(store, "claude", "new-2.jsonl", 400, 1)
    rep = maintenance._session_archive_cleanup(
        store, max_bytes=1000, high_water=800, max_files=99)
    assert rep["triggers"] == ["disk"]
    assert rep["evicted_files"] == 2
    assert [p.split(os.sep)[-1] for p in rep["evicted"]] == ["old-1.jsonl", "old-2.jsonl"]
    assert rep["kept_bytes"] == 800          # 削到 high_water 就停
    assert rep["removed"] == 2
    assert sorted(p.name for p in (store.dir("sessions") / "claude").iterdir()) == [
        "new-1.jsonl", "new-2.jsonl"]


def test_hysteresis_no_eviction_between_high_water_and_max(tmp_path):
    """总量落在 high_water 与 max 之间 → 一动不动（滞回，避免每天削一点）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    _mk(store, "claude", "a.jsonl", 450, 10)
    _mk(store, "claude", "b.jsonl", 450, 9)
    rep = maintenance._session_archive_cleanup(
        store, max_bytes=1000, high_water=800, max_files=99)
    assert rep["triggers"] == []
    assert rep["evicted_files"] == 0
    assert rep["removed"] == 0


def test_files_gate_triggers_without_volume_pressure(tmp_path):
    """条数闸独立生效：体积远低于预算，但文件数超上限照样裁（高频小会话）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    for i in range(6):
        _mk(store, "claude", f"s-{i}.jsonl", 10, 20 - i)
    rep = maintenance._session_archive_cleanup(
        store, max_bytes=10 ** 9, high_water=10 ** 9, max_files=3)
    assert rep["triggers"] == ["files"]
    assert rep["evicted_files"] == 3
    assert rep["kept_files"] == 3
    assert [p.split(os.sep)[-1] for p in rep["evicted"]] == [
        "s-0.jsonl", "s-1.jsonl", "s-2.jsonl"]  # mtime 最旧的三份（20-i 天）


def test_orphans_evicted_first(tmp_path):
    """孤儿（无 sessions.jsonl 索引）先于有索引的归档被裁。"""
    store = Store(tmp_path)
    store.ensure_layout()
    for sid in ("indexed", "keep"):
        store.record_session({"agent": "claude", "session_id": sid,
                              "started_at": "2026-09-01T00:00:00Z"})
    _mk(store, "claude", "indexed.jsonl", 400, 3)      # 有索引，且更新
    _mk(store, "claude", "orphan.jsonl", 400, 90)      # 无索引，且更旧
    _mk(store, "claude", "keep.jsonl", 400, 2)
    store._session_index = None  # 让 list_sessions 重读，吃到刚落库的记录
    rep = maintenance._session_archive_cleanup(
        store, max_bytes=1000, high_water=800, max_files=99)
    assert rep["orphans"] == 1
    assert [p.split(os.sep)[-1] for p in rep["evicted"]] == ["orphan.jsonl"]
    assert (store.dir("sessions") / "claude" / "indexed.jsonl").exists()


def test_empty_index_skips_orphan_detection(tmp_path):
    """索引读不出会话时整段跳过孤儿判定——宁可不裁，也不在索引异常时批量删。"""
    store = Store(tmp_path)
    store.ensure_layout()
    _mk(store, "claude", "a.jsonl", 400, 30)
    _mk(store, "claude", "b.jsonl", 400, 20)
    rep = maintenance._session_archive_cleanup(
        store, max_bytes=400, high_water=400, max_files=99)
    assert rep["orphans"] == 0
    assert rep["evicted_files"] == 1  # 仍按最旧裁，只是不按"孤儿"标签


def test_container_archive_not_treated_as_orphan(tmp_path):
    """容器库副本（文件名 ≠ session_id）不按名字判孤儿，避免整片误杀。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session({"agent": "cursor", "session_id": "conv-1",
                          "started_at": "2026-09-01T00:00:00Z"})
    _mk(store, "cursor", "state.vscdb", 400, 90)   # 最旧，但不是孤儿
    _mk(store, "cursor", "conv-1.jsonl", 400, 3)
    store._session_index = None
    rep = maintenance._session_archive_cleanup(
        store, max_bytes=400, high_water=400, max_files=99)
    assert rep["orphans"] == 0
    # 按最旧裁 → 容器库副本确实先走（它最旧），但走的是"最旧"规则不是"孤儿"规则
    assert [p.split(os.sep)[-1] for p in rep["evicted"]] == ["state.vscdb"]


def test_dry_run_reports_without_touching_files(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    _mk(store, "claude", "old.jsonl", 400, 80)
    _mk(store, "claude", "new.jsonl", 400, 1)
    before = sorted(p.name for p in (store.dir("sessions") / "claude").iterdir())
    rep = maintenance._session_archive_cleanup(
        store, dry_run=True, max_bytes=400, high_water=400, max_files=99)
    assert rep["dry_run"] is True
    assert rep["evicted_files"] == 1
    assert rep["removed"] == 0
    assert sorted(p.name for p in (store.dir("sessions") / "claude").iterdir()) == before


def test_enforce_uses_module_defaults(tmp_path, monkeypatch):
    """档 C 入口走模块默认常量（体积 2GB / 条数 4000），可被 monkeypatch 覆盖。"""
    store = Store(tmp_path)
    store.ensure_layout()
    for i in range(4):
        _mk(store, "claude", f"s-{i}.jsonl", 100, 10 - i)
    monkeypatch.setattr(maintenance, "ARCHIVE_MAX_FILES", 2)
    rep = maintenance.enforce_session_archive_budget(store)
    assert rep["triggers"] == ["files"]
    assert rep["removed"] == 2
    assert rep["kept_files"] == 2


# 单文件闸用打桩的小阈值（真实阈值 100MB，造真文件太慢）；
# 常量本体由 store 单点导出，测试只验证 archive 模块对它的响应行为。
CAP = 50


def test_oversized_source_not_archived(tmp_path, monkeypatch):
    """单文件闸：容器库整库拷贝超限 → 不落盘，返回 None。"""
    monkeypatch.setattr(archive, "SESSION_ARCHIVE_MAX_FILE_BYTES", CAP)
    src = tmp_path / "state.vscdb"
    src.write_bytes(b"x" * (CAP + 1))
    ref = SessionRef(agent="cursor", session_id="conv-1", path=src,
                     size=src.stat().st_size, mtime=src.stat().st_mtime)
    dest_dir = tmp_path / "data" / "sessions"
    out = archive.archive_ref(ref, [Session(agent="cursor", session_id="conv-1")],
                              dest_dir)
    assert out is None
    assert not (dest_dir / "cursor").exists()


def test_oversized_hook_transcript_not_archived(tmp_path, monkeypatch):
    """同一道闸也管 hook 通道（1:1 transcript 同样可能涨到几百 MB）。"""
    monkeypatch.setattr(archive, "SESSION_ARCHIVE_MAX_FILE_BYTES", CAP)
    src = tmp_path / "big.jsonl"
    src.write_bytes(b"x" * (CAP + 1))
    ref = SessionRef(agent="claude", session_id="sid-1", path=src,
                     size=src.stat().st_size, mtime=src.stat().st_mtime)
    out = archive.archive_session(ref, Session(agent="claude", session_id="sid-1"),
                                  tmp_path / "data" / "sessions")
    assert out is None


def test_existing_oversized_copy_left_alone(tmp_path, monkeypatch):
    """单文件闸只拦新拷贝：已存在的超限副本不主动删（删除交给档 C 按最旧优先）。"""
    monkeypatch.setattr(archive, "SESSION_ARCHIVE_MAX_FILE_BYTES", CAP)
    dest_dir = tmp_path / "data" / "sessions" / "cursor"
    dest_dir.mkdir(parents=True)
    keep = dest_dir / "state.vscdb"
    keep.write_bytes(b"OLD")
    src = tmp_path / "state.vscdb"
    src.write_bytes(b"y" * (CAP + 1))
    ref = SessionRef(agent="cursor", session_id="state.vscdb", path=src,
                     size=src.stat().st_size, mtime=src.stat().st_mtime)
    out = archive.archive_ref(ref, [Session(agent="cursor", session_id="conv-1")],
                              tmp_path / "data" / "sessions")
    assert out is None
    assert keep.read_bytes() == b"OLD"


def test_under_limit_still_copies(tmp_path, monkeypatch):
    """未超限的容器库照旧归档（单文件闸不能误伤正常路径）。"""
    monkeypatch.setattr(archive, "SESSION_ARCHIVE_MAX_FILE_BYTES", CAP)
    src = tmp_path / "state.vscdb"
    src.write_bytes(b"DB" * 10)
    ref = SessionRef(agent="cursor", session_id="state.vscdb", path=src,
                     size=src.stat().st_size, mtime=src.stat().st_mtime)
    out = archive.archive_ref(ref, [Session(agent="cursor", session_id="conv-1")],
                              tmp_path / "data" / "sessions")
    assert out is not None and out.read_bytes() == b"DB" * 10


def test_default_cap_is_100mb():
    """默认单文件闸 = 100MB（store 单点常量，防止有人改坏）。"""
    assert SESSION_ARCHIVE_MAX_FILE_BYTES == 100 * 1024 ** 2


# ---------- ② 归档压缩（旧 .jsonl → .zst，省盘不丢数据） ----------

def _jsonl_bytes(n: int) -> bytes:
    return ("\n".join(json.dumps({"i": i, "t": "内容" * 20}) for i in range(n))
            + "\n").encode("utf-8")


def test_compress_old_archive_roundtrip(tmp_path):
    """压缩：原件删、.zst 在、解压逐字节一致；新档与小档不动。"""
    import zstandard

    store = Store(tmp_path)
    store.ensure_layout()
    payload = _jsonl_bytes(300)                     # ~ 60KB，够压出收益
    old = _mk_file(store, "claude", "old.jsonl", payload, 30)
    fresh = _mk_file(store, "claude", "fresh.jsonl", payload, 1)   # 没超龄
    small = _mk_file(store, "claude", "small.jsonl", b"tiny", 30)  # 太小
    rep = maintenance._archive_compression(store, after_days=14, min_bytes=4096)
    assert rep["candidates"] == 1 and rep["compressed"] == 1
    assert rep["errors"] == 0 and rep["saved"] > 0
    assert rep["bytes_after"] < rep["bytes_before"]
    z = old.parent / (old.name + ".zst")
    assert z.exists() and not old.exists()
    with z.open("rb") as fh:
        assert zstandard.ZstdDecompressor().stream_reader(fh).read() == payload
    assert fresh.exists() and small.exists()
    assert not (fresh.parent / (fresh.name + ".zst")).exists()


def test_compress_preserves_mtime(tmp_path):
    """压缩后 .zst 的 mtime = 原档 mtime——它是 90 天保留与「最旧优先」裁剪的唯一依据，
    不能被刷成"现在"（否则保留期被无意延长、裁剪顺序反转）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    old = _mk_file(store, "claude", "old.jsonl", b"x" * 70000, 40)
    before = old.stat().st_mtime
    rep = maintenance._archive_compression(store, after_days=14, min_bytes=4096)
    assert rep["compressed"] == 1
    z = old.parent / (old.name + ".zst")
    assert z.exists() and abs(z.stat().st_mtime - before) < 2


def test_compress_dry_run_touches_nothing(tmp_path):
    """dry-run 只报候选与总体积，一个文件都不动（走模块默认阈值）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    old = _mk_file(store, "claude", "old.jsonl", b"x" * (70 * 1024), 30)
    rep = maintenance.plan_archive_compression(store)
    assert rep["dry_run"] is True
    assert rep["candidates"] == 1 and rep["bytes_before"] == 70 * 1024
    assert old.exists()
    assert not (old.parent / (old.name + ".zst")).exists()


def test_compress_verify_failure_keeps_original(tmp_path, monkeypatch):
    """回读校验失败 → 原件一律保留、不留 .zst、不留 .tmp（宁可不压，绝不丢数据）。"""
    import zstandard

    store = Store(tmp_path)
    store.ensure_layout()
    f = _mk_file(store, "claude", "old.jsonl", b"x" * 70000, 30)

    class _BadCompressor:
        def __init__(self, *a, **k):
            pass

        def copy_stream(self, src, dst):
            dst.write(b"not-a-zstd-frame")   # 解压必炸 → 校验失败

    monkeypatch.setattr(zstandard, "ZstdCompressor", _BadCompressor)
    rep = maintenance.compress_old_archives(store)
    assert rep["errors"] == 1 and rep["compressed"] == 0
    assert f.exists(), "校验失败必须保留原件"
    assert not (f.parent / (f.name + ".zst")).exists()
    assert not (f.parent / (f.name + ".zst.tmp")).exists()


def test_compressed_archive_readable_by_adapter(tmp_path):
    """闭环：本仓压出的 .zst（带内容校验帧）能被适配器基类透明读回。"""
    from app.capture.adapters.codex import CodexAdapter

    store = Store(tmp_path)
    store.ensure_layout()
    events = [
        {"type": "session_meta",
         "payload": {"session_id": "rollout-x", "cwd": "/p",
                     "timestamp": "2026-08-28T10:00:00Z"},
         "timestamp": "2026-08-28T10:00:00Z"},
        {"type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "修 bug"}]},
         "timestamp": "2026-08-28T10:00:01Z"},
    ]
    data = ("\n".join(json.dumps(e) for e in events) + "\n").encode("utf-8")
    f = _mk_file(store, "codex", "rollout-x.jsonl", data, 30)
    rep = maintenance._archive_compression(store, after_days=14, min_bytes=1)
    assert rep["compressed"] == 1 and rep["errors"] == 0
    z = f.parent / (f.name + ".zst")
    assert z.exists() and not f.exists()
    ref = SessionRef(agent="codex", session_id="rollout-x", path=z,
                     size=z.stat().st_size, mtime=z.stat().st_mtime)
    s = CodexAdapter().parse(ref)
    assert s is not None and [m.role for m in s.messages] == ["user"]
    assert s.messages[0].content == "修 bug"


# ---------- 大档快速通道 ----------
#
# 动机：常规腿要满 14 天才压，一个 84MB 的会话档就裸着两周——这是"看着像缓存
# 失控"的主因。实测 zstd 对 JSONL 会话档约 7×（24MB 切片实测 6.9~7.7×）。
# 小档仍走 14 天：频繁改写小文件只添 churn，省不到多少体积。


def test_big_archive_compressed_before_14_days(tmp_path):
    """单体够大且龄 ≥1 天 → 立刻入选，不必等满 14 天（小档仍不入选）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    big = _mk_file(store, "qoder", "big.jsonl", b"x" * 8000, 2)
    _mk_file(store, "qoder", "small.jsonl", b"x" * 800, 2)   # 同龄、体积不够
    rep = maintenance._archive_compression(
        store, after_days=14, min_bytes=1, big_bytes=4096, big_after_days=1)
    assert rep["candidates"] == 1
    assert rep["bytes_before"] == 8000
    assert rep["sample"] == [str(big)]


def test_big_archive_still_waits_one_day(tmp_path):
    """大档也要满 1 天：刚写完的档可能还在追加，压了就得反复解压重压。"""
    store = Store(tmp_path)
    store.ensure_layout()
    _mk_file(store, "qoder", "hot.jsonl", b"x" * 8000, 0.5)
    rep = maintenance._archive_compression(
        store, after_days=14, min_bytes=1, big_bytes=4096, big_after_days=1)
    assert rep["candidates"] == 0


def test_big_lane_wired_to_module_defaults(tmp_path, monkeypatch):
    """默认阈值真的接进了筛选（不是只放在常量里好看）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    _mk_file(store, "qoder", "big.jsonl", b"x" * 8000, 2)
    monkeypatch.setattr(maintenance, "ARCHIVE_COMPRESS_MIN_BYTES", 1)
    monkeypatch.setattr(maintenance, "ARCHIVE_COMPRESS_BIG_BYTES", 4096)
    monkeypatch.setattr(maintenance, "ARCHIVE_COMPRESS_BIG_AFTER_DAYS", 1)
    rep = maintenance.plan_archive_compression(store)   # 全部走模块默认
    assert rep["candidates"] == 1
    assert rep["big_bytes"] == 4096 and rep["big_after_days"] == 1
    assert rep["after_days"] == 14
