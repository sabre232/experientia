"""策展守卫+ 第⑤环反馈接线行为测试。

- curation_guard：逐句来源映射 + 保真守卫（无源臆造/坍缩丢长尾 → suspicious）
- store.append_experience 锁外统一接 apply_injection_feedback：
  佐证/反驳/中性跳过；无注入文件静默。
"""

from app.distill import curation_guard, gsignal
from app.store.store import Store

_ITEM_TEXT = "做方案时先估算成本和市场价位，避免中途改价返工"


def _seed_injection(store: Store, item: str = _ITEM_TEXT) -> str:
    store.ensure_layout()
    store.record_injection("方法", "投标", "s1", tokens=100,
                           items=[{"id": "i1", "text": item}])
    return "i1"


def _hits(store: Store) -> dict:
    return store.load_injection_hits()["方法/投标"]["items"]["i1"]


def _exp(action: str, g: float, **kw) -> dict:
    return {"trunk": "方法", "category": "投标", "action": action,
            "G": g, **(kw or {})}


# ---------- curation_guard：逐句来源映射 ----------

def test_line_sources_maps_supported_ids():
    experiences = [{"id": "e1", "action": "给标题写利益点前置，突出对用户的好处"},
                   {"id": "e2", "action": "投放前先做 A/B 两版对比"}]
    asset = ("## 成功要点\n- 给标题写利益点前置，突出对用户的好处\n"
             "## 失败模式\n- [Solidified] 纯情绪文案不做利益承诺，点击率低\n"
             "## 偏好增量\n- 结论先行\n")
    rows = curation_guard.line_sources(asset, experiences)
    ok = next(r for r in rows if "利益点前置" in r["line"])
    assert ok["section"] == "成功要点"
    assert ok["supported"] is True
    assert "e1" in ok["source_ids"]
    orphan = next(r for r in rows if "纯情绪文案" in r["line"])
    assert orphan["supported"] is False
    assert orphan["source_ids"] == []


# ---------- curation_guard：保真 / 坍缩 ----------

def test_old_solidified_lost_without_declare_is_suspicious():
    old = "## 失败模式\n- [Solidified] 未按规范提交导致审核被打回\n"
    keep = "## 失败模式\n- [Solidified] 未按规范提交导致审核被打回\n## 过时项标记\n（无）\n"
    assert curation_guard.check_distill(keep, old, [])["verdict"] == "ok"
    dropped = "## 失败模式\n（无）\n## 过时项标记\n（无）\n"
    rep = curation_guard.check_distill(dropped, old, [])
    assert rep["verdict"] == "suspicious"
    assert any("未按规范提交" in x for x in rep["lost_solidified"])
    declared = "## 失败模式\n（无）\n## 过时项标记\n- 不再需要，流程已改\n"
    assert curation_guard.check_distill(declared, old, [])["verdict"] == "ok"


def test_unsupported_hallucination_is_suspicious():
    experiences = [{"id": "e1", "action": "给标题写利益点前置"}]
    good = "## 成功要点\n- 给标题写利益点前置\n"
    assert curation_guard.check_distill(good, None, experiences)["verdict"] == "ok"
    bad = "## 成功要点\n- 买彩票碰运气\n- 做梦就能发财\n"
    rep = curation_guard.check_distill(bad, None, experiences)
    assert rep["verdict"] == "suspicious"
    assert rep["unsupported_ratio"] == 1.0


# ---------- 第⑤环：append_experience 锁外反馈接线 ----------

def test_append_success_corroborates_injected_item(tmp_path):
    store = Store(tmp_path)
    _seed_injection(store)
    store.append_experience(_exp(_ITEM_TEXT, 0.8, g_source="user"))
    assert _hits(store)["corroborated"] == 1
    assert _hits(store)["refuted"] == 0


def test_append_corrected_refutes_injected_item(tmp_path):
    store = Store(tmp_path)
    _seed_injection(store)
    store.append_experience(_exp(_ITEM_TEXT, gsignal.L2_CORRECTED, corrected=True))
    assert _hits(store)["refuted"] == 1
    assert _hits(store)["corroborated"] == 0


def test_append_neutral_skips_feedback(tmp_path):
    store = Store(tmp_path)
    _seed_injection(store)
    store.append_experience(_exp(_ITEM_TEXT, 0.4, neutral=True))
    it = _hits(store)
    assert it["corroborated"] == 0 and it["refuted"] == 0  # 中性不凿佐证/反驳


def test_append_no_injection_file_is_silent(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.append_experience(_exp("没有注入记录的经验照常落库，不炸", 0.7))
    assert sum(1 for _ in store.iter_experiences()) == 1


# ---------- 注入路径：selected_experience_items 与 record_injection 联动 ----------

def test_selected_items_matches_assembled_block(tmp_path):
    from app.proxy import inject

    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作",
                      "# 营销 / 文案写作 · playbook\n"
                      "## 成功要点\n- 标题用利益点前置句式，突出对用户的好处\n"
                      "## 失败模式\n"
                      "- [Solidified] 纯情绪文案不做利益承诺，点击率低（出现 3 次）\n"
                      "## 标准流程\n1. 产出 ≥2 版标题\n")
    store.write_preferences("营销", "- 结论先行")
    items = inject.selected_experience_items(store, "营销", "文案写作")
    texts = [it["text"] for it in items]
    # 偏好 / 固化失败 / 标准流程都进入注入块，且文本带条目 id
    assert any("结论先行" in t for t in texts)
    assert any("利益点前置" in t for t in texts)
    assert any("≥2 版标题" in t for t in texts)
    assert all(it["id"] for it in items)


def test_record_injection_with_items_feeds_aging_and_feedback(tmp_path):
    """真实注入落 items 后：age 的匹配锚点 + feedback 的佐证对象都可用。"""
    from app.proxy import inject

    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("方法", "投标",
                      "# 方法 / 投标 · playbook\n"
                      "## 标准流程\n1. 先估算成本与市场价位再报价\n")
    items = inject.selected_experience_items(store, "方法", "投标")
    store.record_injection("方法", "投标", "s1", tokens=50, items=items)
    assert store.injected_items("方法", "投标"), "注入条目应落库"
    # 佐证：落一条与该注入条目近重复的高 G 经验 → 该条目 corroborated
    store.append_experience(_exp("先估算成本与市场价位再报价", 0.9))
    entry = store.load_injection_hits()["方法/投标"]["items"]
    assert any(e["corroborated"] == 1 for e in entry.values())