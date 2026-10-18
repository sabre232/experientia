"""蒸馏层测试：G 信号 + 会话复盘 + 增量策展（LLM 用 mock）。"""

import json

from app.distill import engine_curation, gsignal, review
from app.store.store import Store


# 蒸馏/复盘模型路径需要配置（switcher：没配走确定性降级，mock 的模型不会生效）
MODEL_CONFIG = {"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                     "type": "local", "model": "qwen"}},
                "default_model": "local"}


def _store_with_exps(tmp_path, exps):
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_config(dict(MODEL_CONFIG))
    for e in exps:
        store.append_experience(e)
    return store


EXP_HIGH = {"agent": "codex", "task": "写投放标题", "action": "利益点前置 + A/B 两版",
            "G": 0.8, "g_source": "judge", "trunk": "营销", "category": "文案写作",
            "outcome": "点击率 +30%"}
EXP_LOW = {"agent": "codex", "task": "写投放标题", "action": "纯情绪文案",
           "G": 0.3, "g_source": "auto", "corrected": True,
           "trunk": "营销", "category": "文案写作", "state": "点击率低"}


def test_gsignal_levels():
    assert gsignal.score_l1("valid") == (1.0, False)
    assert gsignal.score_l1("corrected") == (0.2, True)
    assert gsignal.score_l2({"correction_hits": 2}) == gsignal.L2_CORRECTED
    # 无否定也无明确成功收尾 = 中性收尾，不再记成成功
    assert gsignal.score_l2({"correction_hits": 0}) == gsignal.L2_NEUTRAL
    # 明确成功收尾（短、无否定、含接受词的末条用户消息）才是确定性成功
    assert gsignal.score_l2({"correction_hits": 0,
                             "user_messages": ["可以了"]}) == gsignal.L2_CLEAN
    assert gsignal.score_l3(True) == gsignal.L3_CAUSAL
    assert gsignal.score_l3(False) == gsignal.L3_WEAK
    assert gsignal.should_inject(0.5) and not gsignal.should_inject(0.49)


def test_distill_first_write_and_mark(tmp_path, monkeypatch):
    store = _store_with_exps(tmp_path, [dict(EXP_HIGH), dict(EXP_LOW)])

    canned = """## 标准流程
1. 确认投放目标与人群
2. 产出 ≥2 版标题（利益点前置）

## 成功要点
- 利益点前置句式有效

## 失败模式
- [Watching] 纯情绪文案点击率低（出现 1 次）

## 过时项标记
（无）

## 偏好增量
- 结论先行
"""
    monkeypatch.setattr("app.distill.llm.call_model", lambda store, messages, **kw: canned)

    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["status"] == "success" and r["count"] == 2 and r["version"] == 1
    md = store.read_skill("营销", "文案写作")
    assert "确认投放目标与人群" in md
    assert "纯情绪文案点击率低" in md
    # 经验全部打标已蒸馏
    assert store.pending_experiences("营销", "文案写作") == []
    # 偏好合并
    assert "结论先行" in (store.read_preferences("营销") or "")
    # changelog
    assert "蒸馏" in (store.data_dir / "changelog.md").read_text(encoding="utf-8")


def test_distill_no_pending(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.ensure_layout()
    r = engine_curation.distill(store, "x", "y")
    assert r["status"] == "no_pending"


def test_distill_writes_created_and_preserves(tmp_path, monkeypatch):
    """溯源：首次蒸馏写 `> created:`（今天）；再蒸馏沿用原日期（溯源节）。"""
    import re as _re
    from datetime import datetime, timezone

    store = _store_with_exps(tmp_path, [dict(EXP_HIGH)])
    canned = ("## 标准流程\n- 步骤\n\n## 成功要点\n- 要点\n\n"
              "## 失败模式\n（无）\n\n## 过时项标记\n（无）\n\n## 偏好增量\n（无）\n")
    monkeypatch.setattr("app.distill.llm.call_model", lambda store, messages, **kw: canned)

    engine_curation.distill(store, "营销", "文案写作")
    md1 = store.read_skill("营销", "文案写作")
    m = _re.search(r"^>\s*created:\s*(\S+)", md1, _re.M)
    assert m, "首次蒸馏必须写 created（溯源用）"
    # created 按 UTC 写（engine_curation）；本地跨午夜时 date.today() 差一天会误报
    assert m.group(1) == datetime.now(timezone.utc).date().isoformat()

    # 再蒸馏（新经验）→ v2 必须沿用原 created，而不是更新成今天
    store.append_experience(dict(EXP_HIGH, task="第二个标题"))
    engine_curation.distill(store, "营销", "文案写作")
    md2 = store.read_skill("营销", "文案写作")
    m2 = _re.search(r"^>\s*created:\s*(\S+)", md2, _re.M)
    assert m2 and m2.group(1) == m.group(1)


def test_auto_check_threshold(tmp_path, monkeypatch):
    # 证据加权门槛：≥4 条 L3（judge）且来自 ≥2 个 session 才触发
    exps = [dict(EXP_HIGH, task=f"任务{i}", session_id=f"s{i % 2}")
            for i in range(4)]
    store = _store_with_exps(tmp_path, exps)
    monkeypatch.setattr("app.distill.llm.call_model", lambda store, messages, **kw: "## 标准流程\n1. 步骤")
    results = engine_curation.auto_check(store)
    assert any(r.get("status") == "success" for r in results)

    # 低于阈值不触发
    store2 = _store_with_exps(tmp_path, [dict(EXP_HIGH, task="只有一个")])
    monkeypatch.setattr("app.distill.llm.call_model",
                        lambda store, messages, **kw: (_ for _ in ()).throw(AssertionError("不应调用")))
    assert engine_curation.auto_check(store2) == []


def test_review_session_produces_experiences(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_config(dict(MODEL_CONFIG))
    session = {
        "agent": "codex", "session_id": "s1", "model": "test",
        "trunk": "营销", "category": "文案写作",
        "req_count": 4, "correction_hits": 1,
        "user_messages": ["写投放标题", "不对，要利益点前置"],
        # 模型引用的 evidence 必须真能在会话里定位到（D3 证据闸）——测试数据也不例外
        "assistant_messages": ["标题A", "标题B（利益点前置）",
                               "初版纯情绪文案点击率低，改利益点前置后 +30%"],
    }

    async def fake_call(store_, messages, **kw):
        return json.dumps([
            {"task": "写投放标题", "state": "初版点击率低", "action": "利益点前置 + A/B",
             "outcome": "+30%", "corrected": False, "causal": True,
             "evidence": "初版纯情绪文案点击率低，改利益点前置后 +30%"}
        ], ensure_ascii=False)

    monkeypatch.setattr("app.distill.llm.call_model_async", fake_call)
    import asyncio
    n = asyncio.run(review.maybe_review_session(store, session))
    assert n == 1
    exps = list(store.iter_experiences(trunk="营销", category="文案写作", include_distilled=True))
    assert len(exps) == 1
    assert exps[0]["G"] == gsignal.L3_CAUSAL  # causal → 0.8


def test_review_skips_idle_session(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.ensure_layout()
    session = {"agent": "codex", "req_count": 1, "correction_hits": 0,
               "user_messages": ["hi"], "assistant_messages": ["hello"]}
    import asyncio
    assert asyncio.run(review.maybe_review_session(store, session)) == 0
