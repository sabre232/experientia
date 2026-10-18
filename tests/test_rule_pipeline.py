"""经验链路修复护栏：rule 源口径 / 死锁门不回潮 / T1 挖掘 /
事件行预算 / 兜底只挂队 / 重放出队。对应方案 - 验收标准。"""

import asyncio
import json

from app.capture.events import EVENTS_MAX_BYTES, derive_events
from app.distill import gate, gsignal, mining, review
from app.store import store as store_mod
from app.store.store import Store


def _store(tmp_path) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    return s


# ---------- 口径一致性（store 与 distill 双份常量的红线） ----------

def test_store_and_gsignal_constants_aligned():
    assert store_mod._RULE_PROMOTED_G == gsignal.RULE_PROMOTED
    assert store_mod._RULE_PROMOTE_SESSIONS == gsignal.RULE_PROMOTE_SESSIONS
    assert store_mod._RULE_PROMOTE_SESSIONS == gsignal.FAILURE_SOLIDIFY_COUNT
    assert gsignal.RULE_SINGLE < gsignal.G_MIN_INJECT  # 单次不越红线
    assert gsignal.RULE_PROMOTED >= gsignal.G_MIN_INJECT


def test_rule_effective_g_promotes_after_3_sessions(tmp_path):
    store = _store(tmp_path)
    rec = {"task": "cmd:x", "action": "fix:retry-with-changed-args", "state": "",
           "outcome": "exit0", "G": gsignal.RULE_SINGLE, "g_source": "rule",
           "rule_kind": "retry_pair", "corrected": False, "agent": "codex",
           "trunk": "其他", "category": "未分类"}
    for i in ("s1", "s2"):
        store.append_experience({**rec, "session_id": i})
    e = list(store.iter_experiences(include_distilled=True))[0]
    assert e["G"] == gsignal.RULE_SINGLE  # 2 个会话还不够
    store.append_experience({**rec, "session_id": "s3"})
    e = list(store.iter_experiences(include_distilled=True))[0]
    assert e["G"] == gsignal.RULE_PROMOTED  # 3 个独立会话 → 升注入档
    assert gsignal.effective_g(e) >= gsignal.G_MIN_INJECT
    # 落库快照不被读取侧污染
    raw = [json.loads(l) for l in
           (store.data_dir / "experience.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert all(r["G"] == gsignal.RULE_SINGLE for r in raw)


# ---------- 死锁门不回潮 + rule 复现即铁证（gate 三态） ----------

def _gate_store_with_row(tmp_path, seen_in: list[str], desc: str):
    store = _store(tmp_path)
    exp = {
        "task": "cmd:deploy", "action": desc, "state": "", "outcome": "",
        "G": gsignal.RULE_SINGLE, "g_source": "rule", "rule_kind": "error_sig",
        "corrected": False, "agent": "codex", "session_id": seen_in[0],
        "trunk": "其他", "category": "未分类", "seen_in": seen_in,
        "count": len(seen_in),
    }
    store.append_experience(exp)
    # playbook 行正文 = 写路径实际会落的模板句（mining.rule_line_text 口径）
    line = mining.rule_line_text(exp)
    md = (f"# 其他/未分类 · playbook\n## 标准流程\n（无）\n## 成功要点\n（无）\n"
          f"## 失败模式\n- [Watching] {line}（出现 {len(seen_in)} 次）\n")
    store.write_skill("其他", "未分类", md)
    return store


def test_deadlock_gate_removed_counts_alone_never_solid(tmp_path):
    # 老死锁口径：G=0.3/0.4 的噪音数到 6 次自动固化 → 修复后必须仍 pending
    store = _store(tmp_path)
    store.append_experience({
        "task": "t", "action": "校验脚本里有个引号笔误，修一下重跑", "state": "s",
        "outcome": "", "G": 0.3, "g_source": "auto", "corrected": True,
        "agent": "codex", "session_id": "s1", "trunk": "其他", "category": "未分类",
        "count": 9,
    })
    md = ("# x\n## 失败模式\n- [Watching] 校验脚本里有个引号笔误，修一下重跑"
          "（出现 9 次）\n")
    store.write_skill("其他", "未分类", md)
    states = gate.failure_mode_states(store, "其他", "未分类")
    st = next(iter(states.values()))
    assert st["state"] == "pending"  # 次数再多也不直通 solid


def test_rule_repro_solidifies(tmp_path):
    desc = "cmd:deploy 连败后改参成功"
    store = _gate_store_with_row(tmp_path, ["s1", "s2", "s3"], desc)
    states = gate.failure_mode_states(store, "其他", "未分类")
    st = next(iter(states.values()))
    assert st["state"] == "solid"  # 跨 3 独立会话复现 = 结构事实铁证


def test_rule_card_never_high_value():
    e = {"G": 0.9, "g_source": "rule"}
    assert not gsignal.high_value_eligible(e)  # 升了档也不进成功要点
    assert gsignal.high_value_eligible({"G": 0.9, "g_source": "auto"})


# ---------- R0 事件行派生与预算 ----------

def _bash(cid, cmd, out, ts):
    return ([{"role": "assistant", "tool_use": {"name": "Bash",
             "arguments": json.dumps({"cmd": cmd}), "call_id": cid}, "ts": ts},
            {"role": "tool", "tool_result": {"call_id": cid, "output": out}, "ts": ts}])


def test_derive_events_exit_and_sig():
    msgs = _bash("c1", "pytest tests", "FAILED a.py\nProcess exited with code 1", "2026-01-01T00:00:00Z")
    evs = derive_events(msgs)
    assert len(evs) == 1
    ev = evs[0]
    assert ev["ex"] == 1 and ev["e"] == 1 and ev["sig"]
    assert "FAILED" in ev["sig"]


def test_derive_events_budget_keeps_tail():
    msgs = []
    for i in range(400):
        msgs += _bash(f"c{i}", f"tool --run {i} " + "x" * 100, "ok", f"2026-01-01T00:{i % 60}:00Z")
    evs = derive_events(msgs, max_bytes=2048)
    blob = len(json.dumps(evs, ensure_ascii=False).encode("utf-8"))
    assert blob <= 2048 and len(evs) < 400
    assert evs[-1]["cmd"].startswith("tool --run 399")  # 保尾
    assert EVENTS_MAX_BYTES >= 2048  # 默认预算远大于测试值


def test_record_session_persists_events(tmp_path):
    store = _store(tmp_path)
    sess = {"agent": "codex", "session_id": "s1", "messages":
            _bash("c1", "git push", "fatal: not found\nProcess exited with code 128",
                  "2026-01-01T00:00:00Z"),
            "user_messages": ["推一下"], "assistant_messages": []}
    store.record_session(sess)
    rec = store.list_sessions()[0]
    assert rec.get("events") and rec["events"][0]["ex"] == 128
    assert "messages" not in rec  # 原始消息仍恒不落库（431MB 防线不松）


# ---------- T1 挖掘四类 ----------

def _sess(events_sid="s1", extra=None):
    d = {"agent": "codex", "session_id": events_sid, "trunk": "其他",
         "category": "未分类", "project": None, "req_count": 3,
         "correction_hits": 0, "user_messages": ["x"], "assistant_messages": []}
    return d


def test_mine_retry_pair(tmp_path):
    store = _store(tmp_path)
    msgs = (_bash("c1", "python t.py --case 1", "boom\nProcess exited with code 1", "2026-01-01T00:00:01Z")
            + _bash("c2", "python t.py --case 1", "boom\nProcess exited with code 1", "2026-01-01T00:00:02Z")
            + _bash("c3", "python t.py --case 1 --fix", "ok\nProcess exited with code 0", "2026-01-01T00:00:03Z"))
    sess = _sess()
    sess["messages"] = msgs
    store.record_session(sess)
    rec = store.list_sessions()[0]
    n = mining.mine_session_dicts(store, [rec])
    kinds = {e.get("rule_kind") for e in store.iter_experiences(include_distilled=True)}
    assert n >= 1 and "retry_pair" in kinds


def test_mine_no_pair_without_success(tmp_path):
    store = _store(tmp_path)
    sess = _sess()
    sess["messages"] = (_bash("c1", "go build", "err\nProcess exited with code 2", "2026-01-01T00:00:01Z")
                        + _bash("c2", "go build", "err\nProcess exited with code 2", "2026-01-01T00:00:02Z"))
    store.record_session(sess)
    rec = store.list_sessions()[0]
    mining.mine_session_dicts(store, [rec])
    kinds = {e.get("rule_kind") for e in store.iter_experiences(include_distilled=True)}
    assert "retry_pair" not in kinds  # 没成功过不配"改了才通"


def test_mine_revert(tmp_path):
    store = _store(tmp_path)

    def edit(cid, old, new, ts):
        return [{"role": "assistant", "tool_use": {"name": "Edit", "call_id": cid,
                 "arguments": json.dumps({"file_path": "C:/p/a.py", "old_string": old,
                                          "new_string": new})}, "ts": ts},
                {"role": "tool", "tool_result": {"call_id": cid, "output": "ok"}, "ts": ts}]
    sess = _sess()
    sess["messages"] = (edit("e1", "AAA", "BBB", "2026-01-01T00:00:01Z")
                        + edit("e2", "BBB", "AAA", "2026-01-01T00:00:02Z"))
    store.record_session(sess)
    rec = store.list_sessions()[0]
    mining.mine_session_dicts(store, [rec])
    kinds = {e.get("rule_kind") for e in store.iter_experiences(include_distilled=True)}
    assert "revert" in kinds


def test_mine_pivot(tmp_path):
    store = _store(tmp_path)
    read = (lambda cid, path, out, ts: [
        {"role": "assistant", "tool_use": {"name": "Read", "call_id": cid,
         "arguments": json.dumps({"file_path": path})}, "ts": ts},
        {"role": "tool", "tool_result": {"call_id": cid, "output": out}, "ts": ts}])
    sess = _sess()
    sess["messages"] = (read("r1", "D:/x/report.csv", "Error: no such file or directory",
                            "2026-01-01T00:00:01Z")
                        + read("r2", "D:/x/data/report.csv", "col1,col2", "2026-01-01T00:00:02Z"))
    store.record_session(sess)
    rec = store.list_sessions()[0]
    mining.mine_session_dicts(store, [rec])
    kinds = {e.get("rule_kind") for e in store.iter_experiences(include_distilled=True)}
    assert "pivot" in kinds


def test_mine_all_idempotent_no_flood(tmp_path):
    """同库重复全量挖：seen_in 不涨出 3 会话门槛之外不新增注入资格。"""
    store = _store(tmp_path)
    sess = _sess("s1")
    sess["messages"] = (_bash("c1", "run a", "e\nProcess exited with code 1", "2026-01-01T00:00:01Z")
                        + _bash("c2", "run a", "e\nProcess exited with code 1", "2026-01-01T00:00:02Z")
                        + _bash("c3", "run a --ok", "ok\nProcess exited with code 0", "2026-01-01T00:00:03Z"))
    store.record_session(sess)
    n1 = mining.mine_all(store)
    assert n1 >= 1
    n2 = mining.mine_all(store)  # 再全量挖一次（模拟重复触发）
    assert n2 >= 1
    e = list(store.iter_experiences(include_distilled=True))[0]
    assert len(e.get("seen_in") or []) == 1  # 同会话重挖不虚构跨会话复现
    assert e["G"] == gsignal.RULE_SINGLE     # 因此也不获得注入资格


# ---------- 兜底只挂队 + 重放出队 ----------

def _session(hits=1):
    return {"agent": "codex", "session_id": "s-1", "model": "qwen",
            "trunk": "营销", "category": "文案写作", "project": None,
            "req_count": 2, "correction_hits": hits,
            "user_messages": ["写标题", "不对，利益点没有前置"],
            "assistant_messages": ["标题 A", "429 您的使用量已超出频率限制"]}


def test_fallback_enqueues_evidence_not_experience(tmp_path):
    store = _store(tmp_path)  # 无模型
    added = asyncio.run(review.maybe_review_session(store, _session()))
    assert added == 0
    assert list(store.iter_experiences(include_distilled=True)) == []  # 零逐字经验
    pend = store.load_pending_review_records()
    assert len(pend) == 1 and pend[0]["agent"] == "codex"
    assert any("不对" in s for s in pend[0]["snippets"])
    assert pend[0]["trunk"] == "营销"
    # 429 报错原文没有进经验库（对照旧事故样本）
    blob = json.dumps(list(store.iter_experiences(include_distilled=True)), ensure_ascii=False)
    assert "429" not in blob


def test_fallback_no_correction_no_enqueue(tmp_path):
    store = _store(tmp_path)
    assert asyncio.run(review.maybe_review_session(store, _session(0))) == 0
    assert store.load_pending_reviews() == []


def test_replay_pending_requires_model(tmp_path, monkeypatch):
    store = _store(tmp_path)
    sess = _session()
    store.record_session(dict(sess, messages=[]))  # 重放靠落库记录重建
    review._enqueue_correction_evidence(store, sess)
    assert len(store.load_pending_reviews()) == 1
    assert review.replay_pending(store) == 0  # 无模型不动队列
    assert len(store.load_pending_reviews()) == 1

    from app.distill import llm
    monkeypatch.setattr(llm, "model_available", lambda s: True)
    monkeypatch.setattr(llm, "circuit_open", lambda s: False)
    from app.capture import scan
    calls = []
    monkeypatch.setattr(scan, "review_sessions",
                        lambda s, dicts: calls.append(len(dicts)) or 1)
    # replay_pending 懒导入的是模块属性——重导入路径挂 scan.review_sessions 已生效
    assert review.replay_pending(store) == 1
    assert len(store.load_pending_reviews()) == 0
    assert calls == [1]


# ---------- ledger（账本，钱是估算） ----------

def test_ledger_cost_estimate_and_local_free(tmp_path):
    from app import ledger
    store = _store(tmp_path)
    store.record_session({"agent": "codex", "session_id": "s1", "model": "claude-sonnet-4-5",
                          "tokens_in": 1_000_000, "tokens_out": 100_000, "req_count": 3})
    store.record_session({"agent": "workbuddy", "session_id": "s2",
                          "model": "C:\\models\\Qwen3-27B.gguf",
                          "tokens_in": 400_000, "tokens_out": 100_000})
    led = ledger.compute(store)
    assert led["sessions"] == 2 and led["rounds"] == 3
    assert led["cost_usd_est"] > 3.0  # sonnet 1M in + 100K out ≈ 18 美元
    assert led["cost_priced_share"] == 1.0  # gguf 记 0 但算"已计价"


def test_pending_review_backward_compat(tmp_path):
    store = _store(tmp_path)
    assert store.append_pending_review("a", "s") == 1
    assert store.append_pending_review("a", "s") == 0  # 同键去重
    assert store.load_pending_reviews() == [("a", "s")]


# ---------- 真机数据实证驱动的三条质量护栏（双视角） ----------

def test_sig_quality_rejects_junk():
    from app.capture.events import normalize_error_line
    # 无错字特征行 → 不产签名（旧版回退首行造出 "Chunk ID: <h>" 垃圾聚类）
    assert normalize_error_line("Chunk ID: 4f2a91\nsome ok output") == ""
    # 纯退出码回声不配当签名
    assert normalize_error_line("Error: command completed with exit code 1") != ""
    assert normalize_error_line("Command completed with exit code 1") == ""
    # 掩码后无实义词元（全是占位符）→ 拒
    assert normalize_error_line("Error: /a/b/1234567890abcdef") == ""
    # 真错误正常通过
    sig = normalize_error_line("Error: File has not been read yet: C:/x/y.py")
    assert "File has not been read yet" in sig


def test_mine_all_global_sig_clusters_cross_session(tmp_path):
    """每会话只出现 1-2 次的高频坑：逐会话门槛挡掉，全局 pass 必须捞回并
    跨会话复现直接够注入门槛（真机 "Edit 未先 Read" x16/11 会话实证）。"""
    store = _store(tmp_path)
    for sid in ("s1", "s2", "s3"):
        sess = _sess(sid)
        sess["messages"] = _bash("c1", "edit x",
                                 "Error: File has not been read yet: C:/p/a.py",
                                 f"2026-01-0{sid[-1]}T00:00:01Z")
        store.record_session(sess)
    assert mining.mine_all(store) >= 1
    cards = [e for e in store.iter_experiences(include_distilled=True)
             if e.get("rule_kind") == "error_sig"]
    assert len(cards) == 1
    c = cards[0]
    assert c["count"] == 3
    assert gsignal.effective_g(c) >= gsignal.G_MIN_INJECT  # 3 会话复现 → 可注入


def test_append_merges_incoming_seen_in(tmp_path):
    store = _store(tmp_path)
    base = {"task": "cmd:x", "action": "a", "state": "", "outcome": "",
            "G": 0.4, "g_source": "rule", "rule_kind": "retry_pair",
            "corrected": False, "agent": "codex", "trunk": "其他",
            "category": "未分类"}
    store.append_experience({**base, "session_id": "s1", "seen_in": ["s1"]})
    # 全局 pass 一次携带多会话：合并后 seen_in 并集、count 取聚合总数
    store.append_experience({**base, "session_id": "s2",
                             "seen_in": ["s2", "s3"], "count": 9})
    e = list(store.iter_experiences(include_distilled=True))[0]
    assert set(e["seen_in"]) == {"s1", "s2", "s3"}
    assert e["count"] == 9
    assert e["G"] == 0.55  # 3 会话 → 读取视图升档


# ---------- 自查补漏：rule 卡进 playbook/注入必须是人话模板句 ----------

def test_rule_line_text_all_kinds():
    line = mining.rule_line_text({"rule_kind": "retry_pair",
                                  "task": "cmd:npm run build", "state": "ERR! Module not found"})
    assert "npm run build" in line and "反复失败" in line
    assert "fix:retry-with-changed-args" not in line
    assert "反复出现的报错" in mining.rule_line_text(
        {"rule_kind": "error_sig", "task": "sig:boom", "state": "boom"})
    assert "回滚推翻" in mining.rule_line_text(
        {"rule_kind": "revert", "task": "file:app.py", "state": ""})
    assert "换途径" in mining.rule_line_text(
        {"rule_kind": "pivot", "task": "file:report.csv", "state": "path-not-found"})


def test_distill_playbook_human_line_and_solidifies(tmp_path, monkeypatch):
    """端到端：3 会话同坑 → 模型蒸馏 → playbook 行是模板句（非指纹）且
    经 rule 复现门标 [Solidified]（注入内容必须对 agent 说人话）。

     起无模型不再蒸馏（`model_required`），所以这里显式配模型并 mock 产出。
    **正文必须与素材同源**：失败模式行取 `mining.rule_line_text(card)`——模型若
    自由缩写/抽象成别的说法，再次蒸馏时会被 gate 保守判 `pending`、进不了固化
    。

    标记分工同样按：首次蒸馏盘上无旧卡，gate 的机器复标是空转，
    `[Solidified]` 由**模型按 prompt 契约自己写**；再次蒸馏才由 gate 实时复算。
    所以这里 mock 的产出要带标记。
    """
    from app.distill import engine_curation, llm

    store = _store(tmp_path)
    store.save_config({"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                            "type": "local", "model": "qwen"}},
                       "default_model": "local"})
    dicts = []
    for sid in ("s1", "s2", "s3"):
        sess = _sess(sid)
        sess["messages"] = (
            _bash("c1", "npm run build", "ERR! Module not found\nProcess exited with code 1", "2026-01-01T00:00:01Z")
            + _bash("c2", "npm run build", "ERR! Module not found\nProcess exited with code 1", "2026-01-01T00:00:02Z")
            + _bash("c3", "npm install", "installed\nProcess exited with code 0", "2026-01-01T00:00:03Z")
            + _bash("c4", "npm run build", "done\nProcess exited with code 0", "2026-01-01T00:00:04Z"))
        store.record_session(sess)
        dicts.append(store.list_sessions()[-1])
    assert mining.mine_session_dicts(store, dicts) >= 1

    # 正文取素材同源模板句，而不是模型自由发挥的说法
    rule_cards = [e for e in store.iter_experiences(include_distilled=True)
                  if e.get("g_source") == "rule"]
    assert rule_cards, "挖掘应产出 rule 源坑卡"
    line = mining.rule_line_text(rule_cards[0])
    playbook = (f"## 标准流程\n1. 先确认报错再重跑\n\n"
                f"## 成功要点\n- 改参重试后通过\n\n"
                f"## 失败模式\n- [Solidified] {line}（出现 3 次）\n")
    monkeypatch.setattr(llm, "call_model", lambda s, msgs, **k: playbook)

    r = engine_curation.distill(store, "其他", "未分类")
    assert r["status"] == "success", r
    md = store.read_skill("其他", "未分类")
    assert "反复失败，改参重试后才通过" in md
    assert "fix:retry-with-changed-args" not in md  # 指纹绝不进人读资产
    assert "[Solidified]" in md  # 跨 3 会话复现 → 过固化门


# ---------- 第 7 项：rule 卡 L1 反馈语义（不翻身份）+ 第 8 项自动蒸馏触发 ----------

def _rule_card(store, sid="s1", **extra):
    return store.append_experience({
        "task": "cmd:x", "action": "fix:retry-with-changed-args", "state": "",
        "outcome": "exit0", "G": 0.4, "g_source": "rule",
        "rule_kind": "retry_pair", "corrected": False, "agent": "codex",
        "session_id": sid, "trunk": "其他", "category": "未分类", **extra})


def test_rule_feedback_valid_preserves_failure_domain(tmp_path):
    """「有效」= user_valid 过固化门，但 g_source 保持 rule：
    坑确认了还是坑（不许混进成功要点），证据强度升 L1。"""
    store = _store(tmp_path)
    card = _rule_card(store)
    store.update_experience(card["id"], {"user_valid": True, "distilled": False})
    e = next(store.iter_experiences(include_distilled=True))
    assert e["g_source"] == "rule" and e["user_valid"] is True
    assert gsignal.effective_g(e) >= gsignal.G_MIN_INJECT
    assert not gsignal.high_value_eligible(e)      # 恒属失败域
    assert gsignal.evidence_strength(e) == "l1"    # 用户确认 = 最强证据


def test_rule_feedback_rejected_caps_below_inject(tmp_path):
    store = _store(tmp_path)
    card = _rule_card(store, seen_in=["s1", "s2", "s3"])  # 本已复现升档
    store.update_experience(card["id"], {"user_rejected": True})
    e = next(store.iter_experiences(include_distilled=True))
    assert e["G"] == gsignal.RULE_SINGLE           # 读取视图压回（含 store 镜像）
    assert gsignal.effective_g(e) < gsignal.G_MIN_INJECT
    assert gsignal.evidence_strength(e) == "none"


def test_reproduced_rule_cards_trigger_auto_distill():
    """第 8 项：纯 rule 小类目不再等"凑满 10 张"——2 张复现坑卡即值得蒸馏，
    1 张用户确认坑卡（l1）即触发；单次未复现的 0.4 卡不促。"""
    from app.distill.engine_curation import _should_auto_distill

    repro = [{"G": 0.55, "g_source": "rule", "rule_kind": "retry_pair",
              "session_id": f"s{i}"} for i in (1, 2)]
    assert _should_auto_distill(repro) is True
    assert _should_auto_distill(
        [{"G": 0.55, "g_source": "rule", "user_valid": True,
          "session_id": "s1"}]) is True
    assert _should_auto_distill(
        [{"G": 0.4, "g_source": "rule", "session_id": "s1"}]) is False


def test_remark_playbooks_refreshes_stale_marks(tmp_path):
    """新鲜度：蒸馏时 [Watching] 的坑卡事后升档（seen_in 到 3），
    档 C1 重标必须把落盘标记翻新为 [Solidified]（注入读的就是它）。"""
    from app.distill import maintenance

    store = _store(tmp_path)
    card = _rule_card(store, seen_in=["s1"], count=1)
    store.update_experience(card["id"], {"distilled": True})
    line = mining.rule_line_text(card)
    store.write_skill("其他", "未分类",
                      f"# x\n## 失败模式\n- [Watching] {line}（出现 1 次）\n")
    assert maintenance._remark_playbooks(store) == 0  # 未升档，不动
    store.update_experience(card["id"],
                            {"seen_in": ["s1", "s2", "s3"], "count": 3})
    assert maintenance._remark_playbooks(store) == 1
    md = store.read_skill("其他", "未分类")
    assert "[Solidified]" in md and "[Watching]" not in md
