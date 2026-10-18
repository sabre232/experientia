"""第⑤环「反驳→回炉」行为测试：受限→移出→回归 + 注入侧排除/降权 + session 去重。

口径：refuted≥2 且 refuted>corroborated → 受限；受限后再涨到 ≥4 → 移出；
证真追平/反超 → 回归。
"""

from app.distill import maintenance
from app.proxy import inject
from app.store.store import Store

TEXT = "做出方案先估算成本与市场价位再报价，避免中途改价返工"


def _seed(store: Store):
    store.ensure_layout()
    store.record_injection("方法", "投标", "seed", tokens=10,
                           items=[{"id": "i1", "text": TEXT}])
    # -P2-6：新条目默认进 3 次试用期（期内被反驳 = 直接移出，不走两步流）。
    # 本文件测转正后的"反驳→受限→移出→回归"，先让条目平安度过试用期。
    for i in range(3):
        store.record_injection("方法", "投标", f"promo{i}", tokens=10,
                               items=[{"id": "i1", "text": TEXT}])
    assert store.load_injection_hits()["方法/投标"]["items"]["i1"] \
        .get("probation_left") is None


def _entry(store: Store) -> dict:
    return store.load_injection_hits()["方法/投标"]["items"]["i1"]


def _exp(action: str, g: float, **kw) -> dict:
    return {"trunk": "方法", "category": "投标", "action": action, "G": g, **(kw or {})}


def _refute(store: Store, sid: str):
    store.append_experience(_exp(TEXT, 0.3, corrected=True, session_id=sid))


def _corroborate(store: Store, sid: str):
    store.append_experience(_exp(TEXT, 0.9, session_id=sid))


# ---------- 触发链路：受限 → 移出 → 回归 ----------

def test_downgrade_then_exclude_then_restore(tmp_path):
    store = Store(tmp_path)
    _seed(store)
    _refute(store, "s1")
    _refute(store, "s2")
    assert maintenance._evaluate_refutation(store) == (1, 0, 0)   # 达标受限
    assert _entry(store)["restricted"] == 1
    _refute(store, "s3")
    _refute(store, "s4")
    assert maintenance._evaluate_refutation(store) == (0, 1, 0)   # 再涨 → 移出
    assert _entry(store)["excluded"] == 1 and _entry(store)["restricted"] == 0
    # 证真追平 → 回归，恢复注入
    for s in ("s5", "s6", "s7", "s8"):
        _corroborate(store, s)
    assert maintenance._evaluate_refutation(store) == (0, 0, 1)
    assert _entry(store).get("restricted") == 0
    assert _entry(store).get("excluded") == 0


def test_single_refute_not_enough(tmp_path):
    store = Store(tmp_path)
    _seed(store)
    _refute(store, "s1")
    assert maintenance._evaluate_refutation(store) == (0, 0, 0)
    assert not _entry(store).get("restricted")
    # 被证真抵消 → 永不回炉
    _corroborate(store, "s2")
    assert maintenance._evaluate_refutation(store) == (0, 0, 0)


# ---------- 注入侧：移出跳过 / 受限排末降权 ----------

def _skill_store(tmp_path) -> tuple[Store, str]:
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("方法", "投标",
                      "# 方法 / 投标 · playbook\n"
                      "## 成功要点\n"
                      "- 做出方案先估算成本与市场价位再报价，避免中途改价返工\n"
                      "- 做调研先看竞品再写，别闭门造车\n"
                      "- 结论先行，再给推理\n")
    sel = inject.selected_experience_items(store, "方法", "投标")
    store.record_injection("方法", "投标", "seed", tokens=10, items=sel)
    target = next(it for it in sel if "估算成本" in it["text"])
    return store, target["id"]


def test_inject_excludes_restricted_item(tmp_path):
    store, iid = _skill_store(tmp_path)
    store.set_injection_item_state("方法", "投标", iid, excluded=1)
    block = inject.assemble_experience_block(store, "方法", "投标")
    assert "估算成本" not in block  # 移出 → 不进注入块
    # 证真恢复
    store.set_injection_item_state("方法", "投标", iid, excluded=0)
    assert "估算成本" in inject.assemble_experience_block(store, "方法", "投标")


def test_inject_restricted_goes_last_with_marker(tmp_path):
    store, iid = _skill_store(tmp_path)
    store.set_injection_item_state("方法", "投标", iid, restricted=1)
    block = inject.assemble_experience_block(store, "方法", "投标")
    assert "受限" in block and "估算成本" in block
    # 受限条目被挪到独立"·受限"块、排最末（正常要点在前）
    assert block.index("竞品") < block.index("·受限")
    assert block.index("估算成本") > block.index("结论先行")


# ---------- 反馈 session 去重 ----------

def test_feedback_session_dedup(tmp_path):
    store = Store(tmp_path)
    _seed(store)
    _refute(store, "s1")
    _refute(store, "s1")   # 同 session 反复纠正 → 只计一次
    assert _entry(store)["refuted"] == 1
    _refute(store, "s2")
    assert _entry(store)["refuted"] == 2


# ---------- 治理只读视图（GUI 回炉 tab 数据源） ----------

def _seed_multi(store: Store):
    store.ensure_layout()
    store.record_injection("方法", "投标", "seed", tokens=10, items=[
        {"id": "i1", "text": "先估算成本再报价，避免中途改价返工", },  # 受限
        {"id": "i2", "text": "做调研先看竞品再写", },                 # 移出
        {"id": "i3", "text": "结论先行，再给推理", },                 # 正常
    ])


def test_governed_view_groups_and_sorts(tmp_path):
    store = Store(tmp_path)
    _seed_multi(store)
    assert store.injection_governed_items() == []  # 无治理项时为空

    store.set_injection_item_state("方法", "投标", "i1", restricted=1)
    store.set_injection_item_state("方法", "投标", "i2", excluded=1)
    store.set_injection_item_state("方法", "投标", "i1", refuted=5)
    store.set_injection_item_state("方法", "投标", "i2", refuted=6)

    items = store.injection_governed_items()
    ids = [it["id"] for it in items]
    assert ids == ["i1", "i2"]            # 正常项不出现；受限在前
    assert {it["trunk"] for it in items} == {"方法"}
    assert {it["category"] for it in items} == {"投标"}
    assert items[0]["restricted"] == 1 and items[0]["excluded"] == 0
    assert items[1]["excluded"] == 1 and items[1]["restricted"] == 0
    # 组内按反驳次数降序：同组内 refuted 高的在前（移出组仍排前面组之后）
    store.set_injection_item_state("方法", "投标", "i3", restricted=1, refuted=8)
    ids = [it["id"] for it in store.injection_governed_items()]
    assert ids == ["i3", "i1", "i2"]      # 受限组(i3,i1 refuted 降序) → 移出组(i2)


def test_governed_restore_clears_state(tmp_path):
    store = Store(tmp_path)
    _seed_multi(store)
    store.set_injection_item_state("方法", "投标", "i2", excluded=1,
                                   excluded_since="2026-09-18T00:00:00+00:00")
    assert any(it["id"] == "i2" for it in store.injection_governed_items())
    store.set_injection_item_state("方法", "投标", "i2",
                                   restricted=0, excluded=0,
                                   restricted_since=None, excluded_since=None)
    assert [it["id"] for it in store.injection_governed_items()] == []