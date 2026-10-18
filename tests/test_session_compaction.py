"""会话记录的字段级合并与 key 级 compaction。

背景（实测）：同一会话在 sessions.jsonl 里会累积成多行，其中不少键
同时存在"带 started_at"和"null started_at"两种版本。三个 bug 串在一起：

1. 整行替换模型不对——两版互补（扫描通道有 started_at 没 req_count，代理通道
   相反），二选一必然丢一半。改用字段级合并（CDC/MERGE 口径）。
2. 加固免疫 dimensions 试过一次但不彻底：只比 req_count 挡不住，因为代理通道
   那条有 req_count 却丢了时间戳，rank 照样更高。
3. compaction 与 retention 耦合——压缩只在"有记录被删"时发生，于是 90 天内没人
   超期（活跃用户的常态）就永远不压缩（Kafka：retention 与 compaction 各自
   有自己的触发条件）。
"""

from datetime import datetime, timedelta, timezone

from app.store.store import Store, _merge_session_record


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def test_merge_keeps_both_sides_best_fields():
    """代理通道的 req_count + 扫描通道的 started_at，合并后两个都有。"""
    base = {"agent": "wb", "session_id": "s1", "req_count": 6, "started_at": None}
    incoming = {"agent": "wb", "session_id": "s1", "started_at": _iso(1)}
    merged, changed = _merge_session_record(base, incoming)
    assert changed
    assert merged["req_count"] == 6
    assert merged["started_at"]


def test_merge_is_order_independent():
    """合并结果不依赖谁先到——不能让到达顺序决定最终状态。"""
    a = {"session_id": "s", "started_at": _iso(1)}
    b = {"session_id": "s", "req_count": 3}
    m1, _ = _merge_session_record(a, b)
    m2, _ = _merge_session_record(b, a)
    assert m1 == m2


def test_merge_keeps_longer_transcript():
    """转录列表取更长的一版（后一轮扫描通常更全），不做拼接也不做缩短。"""
    short = {"user_messages": ["a"], "assistant_messages": ["x"]}
    long_ = {"user_messages": ["a", "b"], "assistant_messages": ["x"]}
    merged, _ = _merge_session_record(short, long_)
    assert merged["user_messages"] == ["a", "b"]
    merged2, changed2 = _merge_session_record(long_, short)
    assert merged2["user_messages"] == ["a", "b"]
    assert not changed2


def test_merge_reports_no_change_when_nothing_new():
    base = {"session_id": "s", "started_at": _iso(1), "req_count": 1}
    merged, changed = _merge_session_record(base, dict(base))
    assert merged == base
    assert not changed


def test_identical_rewrite_does_not_grow_file(tmp_path):
    """核心防冗余：内容没变化就不重复 append。"""
    store = Store(tmp_path)
    store.ensure_layout()
    rec = {"agent": "a", "session_id": "s1", "started_at": _iso(1), "req_count": 1}
    for _ in range(5):
        store.record_session(dict(rec))
    lines = [l for l in (store.data_dir / "sessions.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1


def test_counter_growth_still_appends(tmp_path):
    """req_count 累加是真信息，仍然要落盘（不能为了省空间丢实时计数）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    for i in range(1, 4):
        store.record_session({"agent": "a", "session_id": "s1",
                              "started_at": _iso(1), "req_count": i})
    rec = store.list_sessions()[0]
    assert rec["req_count"] == 3


def test_missing_timestamp_does_not_demote_existing(tmp_path):
    """后写入的残缺行不能替掉先写入的完整行——started_at 是保留期的唯一依据。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session({"agent": "wb", "session_id": "s1",
                          "started_at": _iso(1), "req_count": 2})
    store.record_session({"agent": "wb", "session_id": "s1", "req_count": 3})
    rec = store.list_sessions()[0]
    assert rec["started_at"]     # 没被后来的残缺行抹掉
    assert rec["req_count"] == 3  # 计数器仍然更新


def test_rebuild_index_merges_regardless_of_file_order(tmp_path):
    """文件重建路径同语义：残缺行在文件的什么位置都不会胜出。"""
    import json
    store = Store(tmp_path)
    store.ensure_layout()
    rows = [
        {"agent": "wb", "session_id": "s1", "started_at": _iso(1), "req_count": 2},
        {"agent": "wb", "session_id": "s1", "req_count": 4},
        {"agent": "wb", "session_id": "s2", "req_count": 2},
        {"agent": "wb", "session_id": "s2", "started_at": _iso(2), "req_count": 5},
    ]
    (store.data_dir / "sessions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    idx = store._build_session_index()
    assert idx[("wb", "s1")]["started_at"]
    assert idx[("wb", "s1")]["req_count"] == 4
    assert idx[("wb", "s2")]["started_at"]
    assert idx[("wb", "s2")]["req_count"] == 5


def test_prune_compacts_without_anything_expiring(tmp_path):
    """没有任何记录超期时也要压缩——这是 retention 触发不到 compaction 的原 bug。"""
    store = Store(tmp_path)
    store.ensure_layout()
    for i in range(1, 6):  # 会话内容逐轮增长 → append-only 冗余
        store.record_session({"agent": "a", "session_id": "s1",
                              "started_at": _iso(1), "req_count": i})
    lines = lambda: sum(1 for l in (store.data_dir / "sessions.jsonl").read_text(
        encoding="utf-8").splitlines() if l.strip())
    assert lines() == 5
    assert store.prune_sessions() == 0          # 没人超期
    assert lines() == 1                          # 但仍然压缩了
    assert len(store.list_sessions()) == 1
    assert store.list_sessions()[0]["req_count"] == 5  # 压的是最新合并值


def test_prune_is_noop_when_nothing_to_gain(tmp_path):
    """已压缩过就别天天重写——无收益不落盘（幂等 + 省一次全量写）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session({"agent": "a", "session_id": "s1",
                          "started_at": _iso(1), "req_count": 1})
    before = (store.data_dir / "sessions.jsonl").stat().st_mtime_ns
    assert store.prune_sessions() == 0
    assert (store.data_dir / "sessions.jsonl").stat().st_mtime_ns == before


def test_prune_still_keeps_unknown_ts_and_drops_expired(tmp_path):
    """原有语义不回归：超期删掉、无时间戳保留。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session({"agent": "a", "session_id": "old",
                          "started_at": _iso(200)})
    store.record_session({"agent": "a", "session_id": "nots"})
    assert store.prune_sessions() == 1
    ids = {s["session_id"] for s in store.list_sessions()}
    assert ids == {"nots"}
