"""记忆纪律总收口 + System1/System2 编排测试（P1-1/P1-2）。

重点验三件事：注意力闸真的会拦、拦完流向正确、慢路径每步失败互不拖累。
"""

import pytest

from app import memory_discipline as md
from app.distill import pipeline
from app.distill import value_gate as vg
from app.store.store import Store

SESSION = {
    "agent": "codebuddy", "session_id": "s1", "trunk": "前端",
    "category": "页面性能", "req_count": 6, "correction_hits": 0,
    "user_messages": ["首屏很慢", "先这样吧"],
    "assistant_messages": ["我把图片转成了 WebP"],
}


def _store(tmp_path):
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


# ---------- 注意力闸（D1） ----------

@pytest.mark.parametrize("text,route", [
    ("fetch failed: connection refused", md.ADMIT_REJECT),
    ("except ImportError:", md.ADMIT_REJECT),
    ("llama-server not found", md.ADMIT_REJECT),
    ("String to replace not found", md.ADMIT_ADVICE),
    ("Command blocked for security", md.ADMIT_ADVICE),
    ("has not been read yet", md.ADMIT_ADVICE),
    ("ModuleNotFoundError: No module named 'x'", md.ADMIT_EXPERIENCE),
    ("TypeError: expected str, got int", md.ADMIT_EXPERIENCE),
])
def test_admit_routes(text, route):
    out = md.admit({"state": text, "task": text, "action": "x"})
    assert out["route"] == route, (text, out)


def test_admit_accepts_plain_string():
    assert md.admit("这是个正常教训")["route"] == md.ADMIT_EXPERIENCE


def test_admit_fails_open_on_broken_classifier(monkeypatch):
    """分类器自身异常 → 放行（宁漏勿拦）。闸不能有打死主流程的能力。"""
    def boom(_):
        raise RuntimeError("classifier exploded")

    monkeypatch.setattr(vg, "classify", boom)
    out = md.admit("anything")
    assert out["route"] == md.ADMIT_EXPERIENCE
    assert "fail-open" in out["reason"]


# ---------- 纪律门面 ----------

def test_policy_table_covers_seven_disciplines():
    assert set(md.POLICY) == {"D1", "D2", "D3", "D4", "D5", "D6", "D7"}
    for key, row in md.POLICY.items():
        assert row["name"] and row["impl"] and row["entry"]


def test_assign_layer_through_facade():
    assert md.assign_layer("pref") == "L3"
    assert md.assign_layer({"kind": "failure"}) == "L5"
    assert md.assign_layer({"kind": "", "task": "x"}) == "L2"


def test_conflict_winner_prefers_user_and_stays_put_on_tie():
    user = {"g_source": "user", "G": 1.0}
    auto = {"g_source": "auto", "G": 0.7}
    assert md.conflict_winner(auto, user) == "new"
    assert md.conflict_winner(user, auto) == "old"
    # 同强度 → 保留旧版（已沉淀资产不被后来者轻意改写）
    assert md.conflict_winner(auto, dict(auto)) == "old"


def test_should_decay_flags_long_idle():
    now = __import__("datetime").datetime(2026, 10, 18, tzinfo=__import__(
        "datetime").timezone.utc)
    stale = {"ts": "2026-01-01T00:00:00Z"}
    fresh = {"ts": "2026-10-17T00:00:00Z"}
    assert md.should_decay(stale, now) == md.DECAY_RETIRE
    assert md.should_decay(fresh, now) == md.DECAY_NONE
    assert md.should_decay({"tombstone": 1}, now) == md.DECAY_FORGET
    assert md.should_decay({}, now) == md.DECAY_NONE     # 无时间戳不误杀


def test_explain_gives_a_records_id_card():
    card = md.explain({"kind": "pref", "G": 0.9, "g_source": "user",
                       "evidence": "原话一句", "revision": 2})
    assert card["layer"] == "L3"
    assert card["injectable"] is True
    assert card["evidence"] == "原话一句"
    assert card["revision"] == 2
    assert card["decay"] in {md.DECAY_NONE, md.DECAY_RETIRE, md.DECAY_FORGET}


def test_explain_low_g_not_injectable():
    assert md.explain({"G": 0.2})["injectable"] is False


def test_retrieve_weight_matches_layers():
    assert md.retrieve_weight("L3") > md.retrieve_weight("L6")
    assert md.retrieve_weight("pref") == md.retrieve_weight("L3")
    assert md.retrieve_weight("不存在的层") == 0.0


# ---------- 注意力闸接进写入入口 ----------

def test_commit_candidate_rejects_env_noise(tmp_path):
    """P1-2 之前这条根本进不了闸门——value_class 只有 rule 挖掘会设。"""
    from app.distill import review

    store = _store(tmp_path)
    rec = review._process_candidate(
        {"task": "调接口", "state": "fetch failed: connection refused",
         "action": "重试", "outcome": "报错"}, dict(SESSION), store)
    stored, route = review.commit_candidate(rec, store)
    assert route == "rejected"
    assert stored is None
    assert list(store.iter_experiences(include_distilled=True)) == []
    assert store.draft_count("pending") == 0


def test_commit_candidate_routes_friction_to_advice(tmp_path):
    from app.distill import review

    store = _store(tmp_path)
    rec = review._process_candidate(
        {"task": "改文件", "state": "String to replace not found",
         "action": "重新读文件再改", "outcome": "改上了"}, dict(SESSION), store)
    stored, route = review.commit_candidate(rec, store)
    assert route == "advice"
    assert stored is not None
    # 进了库，但展示面是避坑栏（不占经验墙）
    assert vg.surface_of(stored) == vg.SURFACE_ADVICE


def test_commit_candidate_keeps_lessons(tmp_path):
    from app.distill import review

    store = _store(tmp_path)
    rec = review._process_candidate(
        {"task": "优化首屏", "state": "LCP 慢",
         "action": "图片转 WebP", "outcome": "LCP 降到 1.8s"},
        dict(SESSION), store)
    stored, route = review.commit_candidate(rec, store)
    assert route == "experience"
    assert vg.surface_of(stored) == vg.SURFACE_EXPERIENCE


# ---------- System1 / System2 ----------

def test_system1_intake_only_enqueues_when_signal(tmp_path):
    store = _store(tmp_path)
    idle = {"agent": "a", "session_id": "s", "req_count": 1,
            "correction_hits": 0, "user_messages": ["嗯"]}
    assert pipeline.system1_intake(store, idle) == {"queued": 0, "signals": False}
    assert pipeline.system1_intake(store, dict(SESSION))["signals"] is True


def test_system1_intake_never_raises(tmp_path):
    class Broken:
        def append_pending_review(self, *a, **kw):
            raise RuntimeError("磁盘炸了")

    out = pipeline.system1_intake(Broken(), dict(SESSION))
    assert out["queued"] == 0


def test_system1_intake_enqueues_clean_long_session(tmp_path):
    """：`req_count≥6`、无纠正的干净会话，无模型时也必须挂起。

    旧 `_enqueue_correction_evidence` 要求「有纠正且摘得出否定词片段」，
    这类会话被判"有信号"后却挂不进去；调用方紧接着 `settle_reviewed`，
    该会话从此永不重来——System1「没模型也不丢数据」的承诺落空。
    """
    store = _store(tmp_path)
    assert pipeline.system1_intake(store, dict(SESSION))["queued"] == 1
    recs = store.load_pending_review_records()
    assert [(r["agent"], r["session_id"]) for r in recs] == [("codebuddy", "s1")]
    assert not recs[0].get("snippets")  # 无否定词 → 片段留空，不影响挂起


def test_maybe_review_session_routes_through_system1(tmp_path, monkeypatch):
    """M5 接线守卫：无模型收尾必须经 System1 编排，而不是各写一套入队。

    行为断言看不出退化（绕过编排直接 `append_pending_review` 结果一样），
    所以数调用次数。
    """
    import asyncio

    from app.distill import review

    store = _store(tmp_path)
    calls: list = []

    def _spy(st, session_dict):
        calls.append(session_dict.get("session_id"))
        return {"queued": 1, "signals": True}

    monkeypatch.setattr(pipeline, "system1_intake", _spy)
    assert asyncio.run(review.maybe_review_session(store, dict(SESSION))) == 0
    assert calls == ["s1"]


def test_system2_runs_all_three_steps(tmp_path, monkeypatch):
    store = _store(tmp_path)
    calls = []
    monkeypatch.setattr("app.distill.engine_curation.auto_check",
                        lambda st, verbose=False: calls.append("distill") or [])
    monkeypatch.setattr("app.distill.intents.derive_intentions",
                        lambda st, **kw: calls.append("intents") or 2)
    out = pipeline.system2_consolidate(store)
    assert calls == ["distill", "intents"]     # 顺序固定
    assert out == {"distilled": [], "intents": 2, "pruned": 0}


def test_system2_isolates_step_failures(tmp_path, monkeypatch):
    """蒸馏失败（模型不可用）不拖累意图沉淀——沉淀不该被模型绑票。"""
    store = _store(tmp_path)

    def boom(st, verbose=False):
        raise RuntimeError("模型挂了")

    monkeypatch.setattr("app.distill.engine_curation.auto_check", boom)
    monkeypatch.setattr("app.distill.intents.derive_intentions",
                        lambda st, **kw: 1)
    out = pipeline.system2_consolidate(store)
    assert out["distilled"] == []
    assert out["intents"] == 1
    assert out["pruned"] == 0


def test_system2_prunes_intentions(tmp_path, monkeypatch):
    import json

    store = _store(tmp_path)
    store.add_intention("要处理的事", "前端", "x")
    monkeypatch.setattr("app.distill.engine_curation.auto_check",
                        lambda st, verbose=False: [])
    rows = [json.loads(x) for x in
            (store.data_dir / "intentions.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        r["expires_at"] = "2020-01-01T00:00:00Z"
    store._write_intentions(rows)

    out = pipeline.system2_consolidate(store)
    assert out["pruned"] == 1
    assert store.list_intentions() == []


def test_layer_summary(tmp_path):
    store = _store(tmp_path)
    store.write_preferences("前端", "- 结论先行")
    summary = pipeline.layer_summary(store)
    assert summary["L3"]["count"] == 1
    assert {k for k in summary} == set(md.POLICY["D2"]["impl"] and
                                       {"L1", "L2", "L3", "L4", "L5", "L6"})
