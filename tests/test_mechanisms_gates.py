"""断链修复方案机制验收件：P1a 落库瘦身 + M1 字段契约/断路器 + M3 生命周期/内存预算。

覆盖方案回归测试（契约/断路器/存储自检）与回归测试
（队列背压/入队瘦身/TrackedSession 封顶/归档保留/第二老化钟/各封顶/熔断器）。
"""

import asyncio
import json
import time

import pytest

import app.distill.llm as llm
from app.store.store import (
    CHANGELOG_MAX_LINES,
    NOTIFICATIONS_MAX_LINES,
    SESSION_MSG_KEEP,
    SESSION_MSG_MAX_CHARS,
    SESSION_RECORD_MAX_BYTES,
    Store,
)


def _read_lines(store: Store, name: str) -> list[str]:
    p = store.data_dir / name
    if not p.exists():
        return []
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------- P1a：落库瘦身 ----------

def test_record_session_pops_raw_messages(tmp_path):
    """落库后文件无 messages 键；user_messages 有界（20 条 × 200 字）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session({
        "agent": "workbuddy", "session_id": "s1",
        "started_at": "2026-09-01T00:00:00Z",
        "messages": [{"role": "assistant", "tool_use": {"name": "Read",
                    "arguments": "x" * 5_000_000}, "ts": 1}],
        "user_messages": [f"u{i}-" + "字" * 400 for i in range(50)],
        "assistant_messages": ["a" * 400],
    })
    lines = _read_lines(store, "sessions.jsonl")
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert "messages" not in rec
    assert len(rec["user_messages"]) == SESSION_MSG_KEEP
    assert all(len(m) <= SESSION_MSG_MAX_CHARS for m in rec["user_messages"])
    assert len(lines[0].encode("utf-8")) < SESSION_RECORD_MAX_BYTES


def test_record_session_derives_from_raw_messages(tmp_path):
    """hook 形态记录（只有原始 messages）也能派生出 user_messages。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session({
        "agent": "claude-code", "session_id": "hook-1",
        "channel": "hook",
        "started_at": "2026-09-01T00:00:00Z",
        "messages": [
            {"role": "user", "content": "帮我写个标题", "ts": "t1"},
            {"role": "assistant", "content": "好的，标题如下……", "ts": "t2"},
            {"role": "assistant", "tool_use": {"name": "Write", "arguments": {},
             "call_id": "c1"}, "ts": "t3"},
            {"role": "tool", "tool_result": {"call_id": "c1", "output": "ok"},
             "ts": "t4"},
            {"role": "user", "content": "不对，再来", "ts": "t5"},
        ],
    })
    rec = store.list_sessions()[0]
    assert "messages" not in rec
    assert rec["user_messages"] == ["帮我写个标题", "不对，再来"]
    assert rec["assistant_messages"] == ["好的，标题如下……"]


# ---------- M1：字段契约 ----------

def test_record_session_drops_out_of_contract_fields(tmp_path, caplog):
    """塞入未知字段 → 丢弃且有 warning（不静默）；原始 messages 恒丢。"""
    store = Store(tmp_path)
    store.ensure_layout()
    with caplog.at_level("WARNING", logger="experientia.store"):
        store.record_session({
            "agent": "a", "session_id": "s1",
            "some_unknown_field": "x" * 100,
            "messages": [{"role": "user", "content": "hi"}],
        })
    rec = store.list_sessions()[0]
    assert "some_unknown_field" not in rec
    assert "messages" not in rec
    assert any("some_unknown_field" in r.message for r in caplog.records)


def test_record_session_contract_keeps_proxy_fields(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session({
        "agent": "zcode", "session_id": "s1", "channel": "proxy",
        "project": "/w", "started_at": "2026-09-01T00:00:00Z",
        "ended_at": "2026-09-01T01:00:00Z",
        "req_count": 5, "correction_hits": 1, "tokens_in": 10, "tokens_out": 20,
        "trunk": "t", "category": "c", "model": "m",
        "user_messages": ["u"], "assistant_messages": ["a"],
    })
    rec = store.list_sessions()[0]
    for k in ("agent", "session_id", "channel", "project", "started_at",
              "ended_at", "req_count", "correction_hits", "tokens_in",
              "tokens_out", "trunk", "category", "model", "user_messages",
              "assistant_messages"):
        assert k in rec, k


def test_record_session_5mb_messages_bounded(tmp_path):
    """5MB 原始 messages 塞入 → 派生有界 user_messages 后落库行 <32KB。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session({
        "agent": "workbuddy", "session_id": "big",
        "started_at": "2026-09-01T00:00:00Z",
        "messages": [{"role": "user", "content": "字" * 5_000_000}],
    })
    lines = _read_lines(store, "sessions.jsonl")
    assert len(lines[0].encode("utf-8")) < SESSION_RECORD_MAX_BYTES
    rec = json.loads(lines[0])
    assert "messages" not in rec
    # 派生后受 trim 上界约束（20 条×200 字），复盘仍有料
    assert rec.get("user_messages")
    assert len(rec["user_messages"]) <= 20
    assert all(len(m) <= 200 for m in rec["user_messages"])


def test_compress_session_record_two_stage(tmp_path):
    """断路器直接单测：trim 上界之外的超量记录 → 二阶段压缩至 32KB 内。"""
    store = Store(tmp_path)
    store.ensure_layout()
    rec = {
        "agent": "workbuddy", "session_id": "c",
        "started_at": "2026-09-01T00:00:00Z",
        "req_count": 5,
        "user_messages": ["字" * 1000] * 100,  # 300KB，超预算
        "assistant_messages": ["a" * 1000] * 100,
    }
    assert len(json.dumps(rec, ensure_ascii=False).encode("utf-8")) \
        > SESSION_RECORD_MAX_BYTES
    out = store._compress_session_record(rec)
    assert len(json.dumps(out, ensure_ascii=False).encode("utf-8")) \
        <= SESSION_RECORD_MAX_BYTES
    # 阶段1（5 条×100 字）即达标：身份与指标字段原样保留
    assert len(out["user_messages"]) == 5
    assert all(len(m) == 100 for m in out["user_messages"])
    assert out["req_count"] == 5


# ---------- M3：写点封顶 ----------

def test_notifications_capped_at_500(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_notifications(
        [{"id": f"n{i}", "ts": "2026-09-01T00:00:00Z"} for i in range(501)])
    recs = store.load_notifications()
    assert len(recs) == NOTIFICATIONS_MAX_LINES == 500
    # 封顶留输入尾部（调用方按新在后传入，尾部=最新）
    assert recs[0]["id"] == "n1" and recs[-1]["id"] == "n500"


def test_changelog_capped_at_1000(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    for i in range(CHANGELOG_MAX_LINES + 1):
        store.append_changelog(f"entry {i}")
    lines = _read_lines(store, "changelog.md")
    assert len(lines) == CHANGELOG_MAX_LINES
    assert "entry 1000" in lines[-1] and "entry 0" not in "\n".join(lines)


def test_drafts_capped_at_200(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    for i in range(201):
        store.append_experience_draft({"task": f"d{i}"})
    assert len(store.list_drafts()) == 200


# ---------- M3：复盘队列背压 + 入队瘦身 ----------

@pytest.fixture()
def frozen_review_queue(monkeypatch):
    """daemon 队列/worker 是模块级全局：worker 换成空转循环（不消费），
    测试前后清空队列，防跨测试串味与消费竞争。"""
    import daemon

    def _spin():
        while True:
            time.sleep(3600)

    monkeypatch.setattr(daemon, "_review_worker_loop", _spin)
    while not daemon._review_queue.empty():
        try:
            daemon._review_queue.get_nowait()
        except Exception:
            break
    yield
    while not daemon._review_queue.empty():
        try:
            daemon._review_queue.get_nowait()
        except Exception:
            break


def test_review_queue_backpressure_and_recovery(tmp_path, frozen_review_queue, monkeypatch):
    """塞满 16 条后再 put → 不阻塞不抛，转 pending；下轮从落库记录重建后清零。

    修复方案：排水改为模型感知——无模型时条目留队（未提炼片段），
    本测试先断言不排水，再 mock 模型在场验证恢复路径。"""
    import daemon

    store = Store(tmp_path)
    store.ensure_layout()
    # 16 个已落库的 review dict（pending 恢复依赖落库记录存在）
    dicts = []
    for i in range(daemon.REVIEW_QUEUE_MAX):
        d = {"agent": "workbuddy", "session_id": f"s{i}", "req_count": 3,
             "trunk": "t", "category": "c",
             "user_messages": [f"u{i}"], "assistant_messages": ["a"]}
        store.record_session(d)
        dicts.append(d)
    daemon._spawn_review(store, dicts)
    assert daemon._review_queue.qsize() == daemon.REVIEW_QUEUE_MAX
    # 第 17 条：队列满 → 不阻塞、不抛、转 pending（qsize 不变）
    d17 = {"agent": "workbuddy", "session_id": "s17", "req_count": 3,
           "trunk": "t", "category": "c",
           "user_messages": ["u17"], "assistant_messages": ["a"]}
    store.record_session(d17)
    daemon._spawn_review(store, [d17])
    assert store.load_pending_reviews() == [("workbuddy", "s17")]
    assert daemon._review_queue.qsize() == daemon.REVIEW_QUEUE_MAX
    # worker 处理完 16 条（模拟：worker 已消费）
    for _ in range(daemon.REVIEW_QUEUE_MAX):
        daemon._review_queue.get_nowait()
    # 无模型：不排水（防证据队列空转 churn）
    daemon._drain_pending_reviews(store)
    assert store.load_pending_reviews() == [("workbuddy", "s17")]
    # 模型在场：下轮扫描开头从落库记录重建再入队，pending 清零
    from app.distill import llm
    monkeypatch.setattr(llm, "model_available", lambda s: True)
    monkeypatch.setattr(llm, "circuit_open", lambda s: False)
    daemon._drain_pending_reviews(store)
    assert store.load_pending_reviews() == []
    _, got_dict = daemon._review_queue.get(timeout=5)
    assert got_dict.get("session_id") == "s17"
    assert "messages" not in got_dict  # 落库记录已 pop 原始字段


def test_enqueued_object_is_bounded_dict(tmp_path, frozen_review_queue):
    """入队对象断言为 dict 且无 messages 键、序列化 <32KB。"""
    import daemon

    store = Store(tmp_path)
    store.ensure_layout()
    d = {"agent": "workbuddy", "session_id": "s1", "req_count": 2,
         "trunk": "t", "category": "c",
         "user_messages": [f"u{i}" for i in range(30)],
         "assistant_messages": [f"a{i}" for i in range(30)]}
    store.record_session(d)  # 落库截断（20×200）
    daemon._spawn_review(store, [store.list_sessions()[0]])
    _, got = daemon._review_queue.get(timeout=5)
    assert isinstance(got, dict)
    assert "messages" not in got
    assert len(json.dumps(got, ensure_ascii=False).encode("utf-8")) \
        < SESSION_RECORD_MAX_BYTES


# ---------- M3：TrackedSession 内存封顶 ----------

def test_tracked_session_bounded_after_200_exchanges(tmp_path):
    """连续 200 轮 exchange 后：列表 ≤20、计数器准确、to_dict 口径一致。"""
    from app.proxy.server import SessionTracker, TrackedSession

    store = Store(tmp_path)
    store.ensure_layout()
    tracker = SessionTracker(store)
    s = TrackedSession(session_id="p1", agent="zcode", model="m")
    for i in range(200):
        tracker.record_exchange(s, f"user msg {i}", f"assistant msg {i}",
                                ["不对"])
        s.req_count += 1
    assert len(s.user_messages) == SESSION_MSG_KEEP == 20
    assert len(s.assistant_messages) == SESSION_MSG_KEEP == 20
    assert s.user_messages[0] == "user msg 180"  # 最近 20 条
    assert s.req_count == 200  # 计数器不受截断影响
    d = tracker.to_dict(s)
    assert len(d["user_messages"]) == 20
    assert d["req_count"] == 200


# ---------- M3：归档 90 天保留 ----------

def test_archive_retention_prunes_old_keeps_new(tmp_path):
    """mtime 100 天前的归档被 C1 清、10 天的在。"""
    from app.distill import maintenance

    store = Store(tmp_path)
    store.ensure_layout()
    agent_dir = store.dir("sessions") / "workbuddy"
    agent_dir.mkdir(parents=True, exist_ok=True)
    old_f = agent_dir / "old-session.jsonl"
    new_f = agent_dir / "new-session.jsonl"
    old_f.write_text("old", encoding="utf-8")
    new_f.write_text("new", encoding="utf-8")
    old_ts = time.time() - 100 * 86400
    new_ts = time.time() - 10 * 86400
    import os
    os.utime(old_f, (old_ts, old_ts))
    os.utime(new_f, (new_ts, new_ts))
    removed = maintenance._prune_session_archives(store)
    assert removed == 1
    assert not old_f.exists()
    assert new_f.exists()


# ---------- M3：经验第二老化钟 ----------

def _days_ago_iso(days: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def test_never_hit_aging_clock(tmp_path):
    """从未命中 + ts 190 天 → deprecated；同 ts 失败池经验不动；新经验不动。"""
    from app.distill import maintenance

    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案", "# playbook")  # 有 playbook 的冷类别
    store.append_experience({"task": "老经验", "action": "老做法", "G": 0.8,
                             "trunk": "营销", "category": "文案",
                             "agent": "a", "ts": _days_ago_iso(190)})
    store.append_experience({"task": "老坑", "action": "被纠正的做法", "G": 0.3,
                             "trunk": "营销", "category": "文案",
                             "agent": "a", "ts": _days_ago_iso(190)})
    store.append_experience({"task": "新经验", "action": "新做法", "G": 0.8,
                             "trunk": "营销", "category": "文案",
                             "agent": "a", "ts": _days_ago_iso(10)})
    # 从未被注入命中（injection_hits 为空）
    demoted, retired = maintenance._age_experiences(store)
    assert retired == 1 and demoted == 0
    remaining = {e["task"] for e in store.iter_experiences(include_distilled=True)}
    assert remaining == {"老坑", "新经验"}  # 失败池（G<0.5）双钟免疫


# ---------- M1③：C1 存储自检 ----------

def test_storage_health_entries(tmp_path):
    """健康/膨胀两种状态下产出正确条目。"""
    from app.distill import maintenance

    store = Store(tmp_path)
    store.ensure_layout()
    h = maintenance._storage_health(store)
    assert h["sessions.jsonl"]["bytes"] == 0
    assert h["sessions_no_ts"] == 0
    # 膨胀：无时间戳记录 + 超 32KB 行
    store.record_session({"agent": "a", "session_id": "s1"})  # 无 started_at
    with (store.data_dir / "sessions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"agent": "b", "session_id": "s2",
                             "user_messages": ["字" * 40000]}) + "\n")
    h = maintenance._storage_health(store)
    assert h["sessions_no_ts"] == 1
    assert h["sessions.jsonl"]["oversized"] == 1
    assert h["sessions.jsonl"]["max_line_bytes"] > SESSION_RECORD_MAX_BYTES


# ---------- M3：模型熔断器 ----------

def test_circuit_breaker_open_half_open_closed(tmp_path, monkeypatch):
    """3 连败 → open（冷却期内不实际调模型）；到期 half-open 试探成功 → closed。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_config({
        "models": {"m1": {"endpoint": "http://127.0.0.1:9/v1", "model": "x"}},
        "default_model": "m1",
    })
    calls = {"n": 0}

    async def fake_impl(*a, **k):
        calls["n"] += 1
        raise RuntimeError("upstream dead")

    monkeypatch.setattr(llm, "_call_model_async_impl", fake_impl)
    for _ in range(llm.CB_FAILURE_THRESHOLD):
        with pytest.raises(RuntimeError):
            asyncio.run(llm.call_model_async(store, [{"role": "user",
                                                       "content": "hi"}]))
    st = store.load_config()["model_breaker"]
    assert st["state"] == "open" and st["fail_count"] == llm.CB_FAILURE_THRESHOLD
    # 冷却期内：circuit_open=True，调用抛 CircuitOpenError 且不碰 impl
    assert llm.circuit_open(store) is True
    with pytest.raises(llm.CircuitOpenError):
        asyncio.run(llm.call_model_async(store, [{"role": "user",
                                                   "content": "hi"}]))
    assert calls["n"] == llm.CB_FAILURE_THRESHOLD  # 无网络调用发生
    # 冷却到期 → half-open 放一次试探
    cfg = store.load_config()
    cfg["model_breaker"]["opened_at"] = time.time() - cfg["model_breaker"]["cooldown"] - 1
    store.save_config(cfg)
    assert llm.circuit_open(store) is False

    async def ok_impl(*a, **k):
        return "ok"

    monkeypatch.setattr(llm, "_call_model_async_impl", ok_impl)
    assert asyncio.run(llm.call_model_async(
        store, [{"role": "user", "content": "hi"}])) == "ok"
    st = store.load_config()["model_breaker"]
    assert st["state"] == "closed" and st["fail_count"] == 0


def test_circuit_breaker_half_open_failure_reopens_with_longer_cooldown(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_config({
        "models": {"m1": {"endpoint": "http://127.0.0.1:9/v1", "model": "x"}},
        "default_model": "m1",
        "model_breaker": {"state": "half_open", "fail_count": 3,
                          "cooldown": llm.CB_COOLDOWN_SECONDS,
                          "opened_at": time.time() - llm.CB_COOLDOWN_SECONDS - 1},
    })

    async def dead_impl(*a, **k):
        raise RuntimeError("still dead")

    monkeypatch.setattr(llm, "_call_model_async_impl", dead_impl)
    with pytest.raises(RuntimeError):
        asyncio.run(llm.call_model_async(store, [{"role": "user",
                                                   "content": "hi"}]))
    st = store.load_config()["model_breaker"]
    assert st["state"] == "open"
    assert st["cooldown"] == llm.CB_COOLDOWN_SECONDS * 2  # 重开延长冷却


# ---------- 学习历程信息量控制（阀门一：会话级 upsert + 阀门二：固化后降级） ----------

_REVIEW_TEXT = ("复盘 workbuddy 会话 00000000-000… "
                "→ 其他/未分类 新增 1 条候选经验 [auto]")


def test_review_upsert_same_session_single_line(tmp_path):
    """同会话两次复盘 → 1 行，n=2、times=2，文本段与首次字节一致。"""
    store = Store(tmp_path)
    store.ensure_layout()
    i1 = store.upsert_review_node("workbuddy", "sid-1", 1, _REVIEW_TEXT)
    i2 = store.upsert_review_node("workbuddy", "sid-1", 1, "SHOULD NOT BE USED")
    recs = store.list_changelog()
    assert len(recs) == 1 and i1 == i2 == 0
    tag = recs[0]["tag"]
    assert tag["kind"] == "review" and tag["agent"] == "workbuddy"
    assert tag["sid"] == "sid-1" and tag["n"] == "2" and tag["times"] == "2"
    assert recs[0]["text"] == _REVIEW_TEXT  # 文本段字节不动


def test_review_upsert_preserves_user_edit(tmp_path):
    """用户编辑过标记行文本后第三次复盘 → 标记保留、n=3、用户文本不动。"""
    store = Store(tmp_path)
    store.ensure_layout()
    idx = store.upsert_review_node("workbuddy", "sid-1", 1, _REVIEW_TEXT)
    store.upsert_review_node("workbuddy", "sid-1", 1, "SHOULD NOT BE USED")
    assert store.edit_changelog(idx, "用户改写的文本")
    store.upsert_review_node("workbuddy", "sid-1", 1, "SHOULD NOT BE USED")
    rec = store.list_changelog()[0]
    assert rec["text"] == "用户改写的文本"
    assert rec["tag"]["n"] == "3" and rec["tag"]["times"] == "3"
    assert rec["tag"]["agent"] == "workbuddy" and rec["tag"]["sid"] == "sid-1"


def test_review_upsert_after_delete_appends_new_line(tmp_path):
    """用户删除该节点后再复盘 → append 新行，旧行进 deprecated/。"""
    store = Store(tmp_path)
    store.ensure_layout()
    idx = store.upsert_review_node("workbuddy", "sid-1", 1, _REVIEW_TEXT)
    assert store.delete_changelog(idx)
    new_idx = store.upsert_review_node("workbuddy", "sid-1", 1, _REVIEW_TEXT)
    recs = store.list_changelog()
    assert len(recs) == 1 and new_idx == 0
    assert recs[0]["tag"]["n"] == "1" and recs[0]["tag"]["times"] == "1"
    dep_files = list((store.data_dir / "deprecated").glob("*/changelog"))
    assert dep_files, "删除的旧行应进 deprecated/"
    assert any(_REVIEW_TEXT in f.read_text(encoding="utf-8")
               for f in dep_files)


def test_changelog_idx_stable_with_user_blank_lines(tmp_path):
    """用户手掺空行后，append 返回的 idx 与 list/delete 定位必须仍一致
    （原 list/edit/delete 用原始行号、append/upsert 用
    非空行序号，含空行即错位——delete 会静默失败或归档错行）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.append_changelog("第一行")
    store.append_changelog("第二行")
    # 用户手动编辑 changelog.md，两行之间掺一个空行
    p = store.data_dir / "changelog.md"
    lines = p.read_text(encoding="utf-8").splitlines()
    p.write_text("\n".join([lines[0], "", lines[1]]) + "\n", encoding="utf-8")
    recs = store.list_changelog()
    assert [r["text"] for r in recs] == ["第一行", "第二行"]
    assert [r["idx"] for r in recs] == [0, 1]  # 非空行序号，不被空行顶偏
    # 新 append 的返回值与 list 口径一致
    idx2 = store.append_changelog("第三行")
    recs = store.list_changelog()
    assert [r["text"] for r in recs] == ["第一行", "第二行", "第三行"]
    assert recs[2]["idx"] == idx2 == 2
    # delete 用 list 给出的 idx → 删的就是"第二行"（错位时会删错/归档错行）
    assert store.delete_changelog(recs[1]["idx"])
    assert [r["text"] for r in store.list_changelog()] == ["第一行", "第三行"]
    dep = list((store.data_dir / "deprecated").glob("*/changelog"))
    assert any("第二行" in f.read_text(encoding="utf-8") for f in dep)


def test_distill_solidify_backfill(tmp_path):
    """蒸馏消费 2 个会话的经验 → 2 个源 review 节点获 solidified=v3，
    蒸馏节点带 ver 标记；空 session_id 跳过不报错。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.upsert_review_node("workbuddy", "sid-1", 2, _REVIEW_TEXT)
    store.upsert_review_node(
        "claude-code", "sid-2", 1,
        "复盘 claude-code 会话 sid-2… → 其他/未分类 新增 1 条候选经验 [auto]")
    assert store.mark_solidified("workbuddy", "sid-1", "v3")
    assert store.mark_solidified("claude-code", "sid-2", "v3")
    assert store.mark_solidified("workbuddy", "", "v3") is False  # 空 sid 静默
    store.append_event("distill",
                       "蒸馏 其他/未分类（review）：3 条经验 → v3",
                       path="其他/未分类", ver="v3", src="review", n=3)
    recs = store.list_changelog()
    reviews = {r["tag"]["sid"]: r["tag"] for r in recs
               if r["tag"] and r["tag"]["kind"] == "review"}
    assert reviews["sid-1"]["solidified"] == "v3"
    assert reviews["sid-2"]["solidified"] == "v3"
    distill = next(r for r in recs if r["tag"]["kind"] == "distill")
    assert distill["tag"]["ver"] == "v3" and distill["tag"]["n"] == "3"
    assert distill["tag"]["path"] == "其他/未分类"


def test_mark_solidified_missing_node_silent(tmp_path):
    """mark_solidified 找不到节点（未存在/已删/已封顶裁掉）→ False，不抛错。"""
    store = Store(tmp_path)
    store.ensure_layout()
    assert store.mark_solidified("workbuddy", "sid-x", "v3") is False
    store.upsert_review_node("workbuddy", "sid-1", 1, _REVIEW_TEXT)
    assert store.mark_solidified("workbuddy", "sid-1", "v3")
    store.delete_changelog(store.list_changelog()[0]["idx"])
    assert store.mark_solidified("workbuddy", "sid-1", "v3") is False
    # 封顶裁掉：复盘行先落，再用 1000 行封顶把它挤出
    store.upsert_review_node("workbuddy", "sid-1", 1, _REVIEW_TEXT)
    for i in range(CHANGELOG_MAX_LINES):
        store.append_changelog(f"filler {i}")
    recs = store.list_changelog()
    assert len(recs) == CHANGELOG_MAX_LINES
    assert not any(r["tag"] and r["tag"].get("sid") == "sid-1" for r in recs)
    assert store.mark_solidified("workbuddy", "sid-1", "v3") is False


def test_legacy_changelog_lines_read_as_none(tmp_path):
    """legacy 行（无标记）读取 → tag=None；未知 kind 标记同按 legacy，不抛错。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.append_changelog(_REVIEW_TEXT)
    store.append_changelog("普通行 [auto]")
    with (store.data_dir / "changelog.md").open("a", encoding="utf-8") as fh:
        fh.write("- [2026-09-01T00:00:00Z] [note k=v] 未知 kind 行\n")
    recs = store.list_changelog()
    assert [r["tag"] for r in recs] == [None, None, None]
    assert recs[0]["text"] == _REVIEW_TEXT
    assert recs[2]["text"] == "[note k=v] 未知 kind 行"


def test_upsert_keeps_idx_stable(tmp_path):
    """upsert/mark_solidified 原地改标记不改变其他行的行号（idx 定位不漂移）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    a = store.append_changelog("节点 A")
    b = store.upsert_review_node("workbuddy", "sid-1", 1, _REVIEW_TEXT)
    c = store.append_changelog("节点 C")
    assert (a, b, c) == (0, 1, 2)
    store.upsert_review_node("workbuddy", "sid-1", 1, "x")  # 命中 → 原地
    store.mark_solidified("workbuddy", "sid-1", "v2")       # 命中 → 原地
    recs = store.list_changelog()
    assert [r["idx"] for r in recs] == [0, 1, 2]
    assert recs[1]["tag"]["n"] == "2" and recs[1]["tag"]["solidified"] == "v2"


def test_changelog_capped_with_tagged_lines(tmp_path):
    """1000 行封顶行为不变：upsert 命中不增行；未命中 append 触发封顶。"""
    store = Store(tmp_path)
    store.ensure_layout()
    for i in range(CHANGELOG_MAX_LINES - 1):
        store.append_changelog(f"filler {i}")
    idx = store.upsert_review_node("workbuddy", "sid-1", 1, _REVIEW_TEXT)
    assert idx == CHANGELOG_MAX_LINES - 1
    assert len(_read_lines(store, "changelog.md")) == CHANGELOG_MAX_LINES
    store.upsert_review_node("workbuddy", "sid-1", 1, "x")  # 命中，不增行
    assert len(_read_lines(store, "changelog.md")) == CHANGELOG_MAX_LINES
    store.upsert_review_node(  # 未命中 → append + 封顶裁掉最旧
        "workbuddy", "sid-2", 1,
        "复盘 workbuddy 会话 sid-2… → 其他/未分类 新增 1 条候选经验 [auto]")
    lines = _read_lines(store, "changelog.md")
    assert len(lines) == CHANGELOG_MAX_LINES
    assert "filler 0" not in "\n".join(lines)
    assert "sid-2" in lines[-1]
