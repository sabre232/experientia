"""启动自动迁移护栏：版本门控、轻重两相、幂等、回采旗标。"""

import json

from app.store import migrations as mig
from app.store.store import Store


def _store(tmp_path):
    s = Store(tmp_path)
    s.ensure_layout()
    return s


def _codex_archive(store, sid="abc123", fail_cmd="pytest"):
    """在 sessions/codex/ 放一份 codex 格式归档原件（连败一次无成功）。"""
    d = store.data_dir / "sessions" / "codex"
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        {"type": "session_meta",
         "payload": {"session_id": sid, "cwd": "C:/p",
                     "timestamp": "2026-09-15T00:00:00Z"}},
        {"type": "response_item", "timestamp": "2026-09-15T00:00:01Z",
         "payload": {"type": "function_call", "name": "exec_command",
                     "call_id": "c1",
                     "arguments": json.dumps({"cmd": fail_cmd})}},
        {"type": "response_item", "timestamp": "2026-09-15T00:00:02Z",
         "payload": {"type": "function_call_output", "call_id": "c1",
                     "output": "FAILED a.py\nProcess exited with code 1"}},
    ]
    (d / f"{sid}.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lines),
        encoding="utf-8")


def _legacy_session(store, sid="s-legacy", hits=1):
    store.record_session({
        "agent": "workbuddy", "session_id": sid, "req_count": 3,
        "correction_hits": hits, "trunk": "营销", "category": "文案写作",
        "started_at": "2026-09-15T00:00:00Z",
        "user_messages": ["写标题", "不对，利益点没前置"],
        "assistant_messages": ["标题A"]})


def test_fresh_install_only_stamps_version(tmp_path):
    store = _store(tmp_path)
    out = mig.run_startup_migrations(store)
    assert out.get("skipped") is False
    assert store.load_meta().get("data_version") == mig.DATA_VERSION
    assert not (store.data_dir / "deprecated").exists() or \
        not list((store.data_dir / "deprecated").rglob("experience_reset.jsonl"))
    assert not store.load_meta().get("backfill_pending")


def test_legacy_clears_snapshots_and_enqueues(tmp_path):
    store = _store(tmp_path)
    # 旧逐字兜底垃圾 ×2 + 死锁门时代的 [Solidified] playbook
    store.append_experience({"task": "t1", "action": "429 您的使用量已超出频率限制",
                             "G": 0.3, "g_source": "auto", "corrected": True,
                             "agent": "workbuddy", "session_id": "s-legacy",
                             "trunk": "营销", "category": "文案写作"})
    store.append_experience({"task": "t2", "action": "另一条垃圾", "G": 0.3,
                             "g_source": "auto", "corrected": True,
                             "agent": "workbuddy", "trunk": "营销",
                             "category": "文案写作"})
    store.write_skill("营销", "文案写作",
                      "# x\n## 失败模式\n- [Solidified] 垃圾行（出现 9 次）\n")
    _legacy_session(store)
    out = mig.run_startup_migrations(store)
    assert out["cleared"] == 2 and out["assets_reset"] >= 1
    assert out["enqueued"] == 1
    assert list(store.iter_experiences(include_distilled=True)) == []
    assert store.read_skill("营销", "文案写作") in (None, "")
    pend = store.load_pending_review_records()
    assert pend and any("不对" in s for s in pend[0]["snippets"])
    # 快照可恢复（30 天治理前原样在 deprecated）
    snaps = list((store.data_dir / "deprecated").rglob("experience_reset.jsonl"))
    assert snaps and len(snaps[0].read_text(encoding="utf-8").splitlines()) == 2


def test_migration_idempotent_second_run_skips(tmp_path):
    store = _store(tmp_path)
    store.append_experience({"task": "t", "action": "a", "G": 0.3,
                             "g_source": "auto", "agent": "codex",
                             "trunk": "其他", "category": "未分类"})
    first = mig.run_startup_migrations(store)
    assert first.get("skipped") is False
    second = mig.run_startup_migrations(store)
    assert second.get("skipped") is True
    # 快照不被重复合并追加
    snaps = list((store.data_dir / "deprecated").rglob("experience_reset.jsonl"))
    assert sum(len(s.read_text(encoding="utf-8").splitlines()) for s in snaps) == 1


def test_backfill_flag_and_execution(tmp_path):
    store = _store(tmp_path)
    _legacy_session(store)          # 无事件行的落库会话
    _codex_archive(store)           # 有归档原件 → 需要回采
    out = mig.run_startup_migrations(store)
    assert out.get("backfill_pending") is True
    assert store.load_meta().get("backfill_pending") is True
    sess_n, cards_n = mig.backfill_from_archive(store)
    assert sess_n >= 1
    rec = next(s for s in store.list_sessions() if s.get("agent") == "codex")
    assert rec.get("events"), "回采后事件行必须落库"
    assert rec["events"][0]["ex"] == 1
    mig._run_backfill_task(store)   # 任务包装器负责清旗标
    assert store.load_meta().get("backfill_pending") is False


# ---------- ② 归档回采分片 + 断点续跑 ----------

def test_backfill_batch_shards_by_byte_budget(tmp_path):
    """分片：按字节预算一批只吃这么多档，进度落 meta['backfill_done']，可续跑。"""
    store = _store(tmp_path)
    for i in range(5):
        _codex_archive(store, sid=f"s{i}")
    # 预算小到只够 1 档（每档约 500B）→ 每批推进 1 档
    rep = mig.backfill_batch(store, byte_budget=600)
    assert rep["units_total"] == 5
    assert rep["units_done"] == 1 and rep["remaining"] == 4
    assert store.load_meta().get("backfill_done") == {"codex": ["s0"]}

    # 续跑：下一批接着 s1（不重复 s0）
    rep2 = mig.backfill_batch(store, byte_budget=600)
    assert rep2["units_done"] == 2 and rep2["remaining"] == 3
    assert store.load_meta()["backfill_done"] == {"codex": ["s0", "s1"]}

    # 大预算一次清空
    rep3 = mig.backfill_batch(store, byte_budget=10 ** 9)
    assert rep3["remaining"] == 0 and rep3["units_done"] == 5
    assert len(store.load_meta()["backfill_done"]["codex"]) == 5


def test_backfill_identity_survives_zst_rename(tmp_path):
    """identity = (agent, sid)：归档压缩改名 x.jsonl → x.jsonl.zst 后**不得**重采。"""
    store = _store(tmp_path)
    _codex_archive(store, sid="z1")
    assert mig.backfill_batch(store, byte_budget=10 ** 9)["remaining"] == 0
    src = store.data_dir / "sessions" / "codex" / "z1.jsonl"
    src.rename(src.with_name("z1.jsonl.zst"))     # 模拟 ② 归档压缩
    rep = mig.backfill_batch(store, byte_budget=10 ** 9)
    assert rep["units_total"] == 1 and rep["units_done"] == 1
    assert rep["remaining"] == 0 and rep["processed"] == 0, "压缩改名不应触发重采"


def test_backfill_task_resumes_and_clears_progress(tmp_path, monkeypatch):
    """执行体：分批跑完 → 清旗标与进度；中断（异常）→ 旗标与进度都保留。"""
    store = _store(tmp_path)
    for i in range(3):
        _codex_archive(store, sid=f"r{i}")
    store.save_meta({"backfill_pending": True})
    monkeypatch.setattr(mig, "BACKFILL_BATCH_BYTES", 600)     # 逼出多批
    monkeypatch.setattr(mig, "BACKFILL_BATCH_PAUSE_S", 0)     # 测试不真等
    mig._run_backfill_task(store)
    meta = store.load_meta()
    assert meta.get("backfill_pending") is False
    assert meta.get("backfill_done") == {}                   # 收尾后清进度
    assert {s["session_id"] for s in store.list_sessions()} >= {"r0", "r1", "r2"}

    # 中断场景：checkpoint 写盘失败（模拟崩溃）→ 旗标保留，下轮从断点续
    store2 = _store(tmp_path / "b")
    for i in range(2):
        _codex_archive(store2, sid=f"e{i}")
    store2.save_meta({"backfill_pending": True})

    def _boom(*_a, **_k):
        raise RuntimeError("checkpoint 写盘失败")

    monkeypatch.setattr(mig, "_save_backfill_done", _boom)
    mig._run_backfill_task(store2)
    assert store2.load_meta().get("backfill_pending") is True, "中断必须保留旗标"


def test_spawn_backfill_starts_once(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save_meta({"backfill_pending": True})
    calls = []
    monkeypatch.setattr(mig, "_run_backfill_task",
                        lambda st: calls.append(1))
    assert mig.spawn_backfill_if_pending(store) is True
    mig._backfill_thread.join(timeout=5)
    assert calls == [1]
    # 旗标已被任务清除后不再拉起
    store.save_meta({"backfill_pending": False})
    assert mig.spawn_backfill_if_pending(store) is False


def test_daemon_scan_loop_wires_migrations(monkeypatch, tmp_path):
    """scan_loop 顶部必须挂启动迁移 + 旗标回采（发版链断点防护）。"""
    import daemon

    seen = {}
    monkeypatch.setattr(mig, "run_startup_migrations",
                        lambda st: seen.setdefault("mig", True) or {"skipped": True})
    monkeypatch.setattr(mig, "spawn_backfill_if_pending",
                        lambda st: seen.setdefault("spawn", True))
    monkeypatch.setattr(daemon, "_drain_pending_reviews", lambda st: None)

    def _stop(*a, **k):  # BaseException：不被循环 except Exception 吞，单轮即出
        raise KeyboardInterrupt

    monkeypatch.setattr(daemon.capture_scan, "run_scan", _stop)
    try:
        daemon.scan_loop(_store(tmp_path))
    except KeyboardInterrupt:
        pass
    assert seen.get("mig") and seen.get("spawn")


def test_v4_sqlite_source_switch_and_no_rebuild_from_stale_jsonl(tmp_path):
    """：v4 把 experience.db 升为唯一事实源——重启**绝不**按（陈旧）JSONL 重建，
    否则会用低频快照覆盖库、丢掉尚未导出的更新（数据丢失）；原 JSONL 复制留档不删除。"""
    store = _store(tmp_path)
    r = store.append_experience({"agent": "a", "task": "t", "action": "x", "G": 0.9})
    store.save_meta({"data_version": 3})  # 模拟升级前的旧版本
    out = mig.run_startup_migrations(store)
    assert not out.get("skipped")
    assert store._expdb.is_sqlite_source, "v4 应盖上 experience_source=sqlite"
    assert (tmp_path / "experience.jsonl.pre-sqlite.bak").exists(), "原 JSONL 应留档"

    # 一条更新：只落 SQLite，JSONL 仍是旧值（低频导出尚未跟上）
    store.update_experience(r["id"], {"G": 0.1})
    store2 = Store(tmp_path)  # 重启：若按陈旧 JSONL 重建，G 会退回 0.9（数据丢失）
    row = next(e for e in store2.iter_experiences(include_distilled=True)
               if e["id"] == r["id"])
    assert row["G"] == 0.1, "重启重建了陈旧 JSONL —— T2.5 事实源被破坏（数据丢失）"
    assert store2._expdb.is_sqlite_source


def test_maybe_export_snapshot_reconciles_jsonl(tmp_path):
    """：导出快照把 SQLite 全量原子写回 JSONL（备份/回退格式）。"""
    store = _store(tmp_path)
    store.save_meta({"data_version": mig.DATA_VERSION})
    r = store.append_experience({"agent": "a", "task": "t", "action": "x", "G": 0.9})
    store.update_experience(r["id"], {"G": 0.2})
    n = store.export_experience_snapshot()
    assert n == 1
    line = (tmp_path / "experience.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(line)["G"] == 0.2, "快照应反映 SQLite 的最新值"
