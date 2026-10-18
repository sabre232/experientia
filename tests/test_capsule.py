"""有上限上下文胶囊测试（P0-1，纪律 D2 归位 / D7 取用）。

口径与 `tests/test_inject.py` 对齐：胶囊不发明新条目来源，只重组 `inject` 那同一份，
所以"预览看到的 = 召回的"这两处语义必须一致（固化才召回、覆盖层生效、新要点降权）。
"""

from app.distill import capsule
from app.store.store import Store

PLAYBOOK = """# 前端 / 页面性能 · playbook

> version: 1

## 失败模式
- [Solidified] 首屏图片不压缩，LCP 超 3 秒（出现 4 次）
- [Watching] 字体文件没有预加载（出现 2 次）

## 标准流程
1. 先测 Lighthouse 基线
2. 改一处测一处

## 成功要点
- 大图一律转 WebP
- [NewPoint] 关键 CSS 内联提速（出现 1 次）
"""

FIXES = """# 纠正补丁

## 纠正补丁
- 改完必须跑 run build 再上线，别只跑 lint
"""

PREFS = "- 结论先行，先给数字再给推理\n- 少说废话"


def _store(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("前端", "页面性能", PLAYBOOK)
    store.write_fixes("前端", "页面性能", FIXES)
    store.write_preferences("前端", PREFS)
    return store


def test_layer_order_pref_failure_fix_flow_insight(tmp_path):
    store = _store(tmp_path)
    cap = capsule.build_capsule(store, "前端", "页面性能")
    # 同层多条 → 断言"层出现的先后次序"（去重后的层序），不是逐条列表
    seen: list[str] = []
    for kind in [it["kind"] for it in cap["items"]]:
        if not seen or seen[-1] != kind:
            seen.append(kind)
    assert seen == ["pref", "failure", "fix", "flow", "insight"], seen
    # 每条都带来源 id（D7）
    assert all(it["id"] for it in cap["items"])


def test_watching_failure_not_recalled(tmp_path):
    """观察中的失败模式不入胶囊——与注入口径一致。"""
    store = _store(tmp_path)
    cap = capsule.build_capsule(store, "前端", "页面性能")
    text = cap["text"]
    assert "首屏图片不压缩" in text
    assert "字体文件没有预加载" not in text


def test_budget_is_hard_cap(tmp_path):
    store = _store(tmp_path)
    budget = 20
    cap = capsule.build_capsule(store, "前端", "页面性能", budget)
    assert cap["budget"] == budget
    assert cap["tokens"] <= budget
    assert cap["truncated"] is True


def test_new_point_costs_double(tmp_path):
    """新要点·待复现权重降半（成本 ×2）→ 同层里排在已复现要点之后。"""
    store = _store(tmp_path)
    cap = capsule.build_capsule(store, "前端", "页面性能")
    insight = [it for it in cap["items"] if it["kind"] == "insight"]
    assert [it["text"] for it in insight] == [
        "大图一律转 WebP", "关键 CSS 内联提速（出现 1 次）"]
    assert insight[0]["cost"] < insight[1]["cost"]


def test_override_disable_is_respected(tmp_path):
    store = _store(tmp_path)
    items = capsule.prepare_items(store, "前端", "页面性能")
    target = next(it for it in items if it["kind"] == "pref")
    store.upsert_override(target["id"], enabled=False)
    cap = capsule.build_capsule(store, "前端", "页面性能")
    assert target["id"] not in [it["id"] for it in cap["items"]]


def test_override_text_is_used(tmp_path):
    store = _store(tmp_path)
    items = capsule.prepare_items(store, "前端", "页面性能")
    target = next(it for it in items if it["kind"] == "failure")
    store.upsert_override(target["id"], text="用户改过的措辞")
    cap = capsule.build_capsule(store, "前端", "页面性能")
    assert "用户改过的措辞" in cap["text"]
    assert "首屏图片不压缩" not in cap["text"]


def test_order_key_layer_first_then_within_layer(tmp_path):
    """层序是权威：层内才排"受限垫底"。受限永远不能把条目抬到更高层去。"""
    rows = [
        {"kind": "insight", "new_point": False, "restricted": False},
        {"kind": "insight", "new_point": True, "restricted": False},
        {"kind": "insight", "new_point": True, "restricted": True},
        {"kind": "pref", "new_point": False, "restricted": True},
    ]
    ordered = sorted(rows, key=capsule._order_key)
    assert [r["kind"] for r in ordered] == ["pref", "insight", "insight", "insight"]
    # pref 那一行即使受限也排最前（层权 1.0 最高）
    assert ordered[0]["restricted"] is True
    # insight 层内：已复现 → 待复现 → 待复现且受限
    assert ordered[3]["restricted"] is True


def test_cost_of_doubles_downweighted(tmp_path):
    """新要点 / 受限都按"权重降半"计费 = 成本 ×2。"""
    base = {"text": "一段中文写成的条目文本", "new_point": False, "restricted": False}
    plain = capsule._cost_of(base)
    assert plain >= 1
    assert capsule._cost_of({**base, "restricted": True}) == 2 * plain
    assert capsule._cost_of({**base, "new_point": True}) == 2 * plain


def test_empty_assets_empty_capsule(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    cap = capsule.build_capsule(store, "不存在", "也没有")
    assert cap["items"] == []
    assert cap["text"] == ""
    assert cap["tokens"] == 0
    assert cap["truncated"] is False


def test_budget_none_defaults(tmp_path):
    store = _store(tmp_path)
    cap = capsule.build_capsule(store, "前端", "页面性能", None)
    assert cap["budget"] == capsule.DEFAULT_BUDGET_TOKENS


def test_resolve_scope_given_wins(tmp_path):
    store = _store(tmp_path)
    assert capsule.resolve_scope(store, "随便写点啥", "前端", "页面性能") \
        == ("前端", "页面性能", False)


def test_resolve_scope_no_task_fallback(tmp_path):
    store = _store(tmp_path)
    trunk, category, detected = capsule.resolve_scope(store, None, None, None)
    assert (trunk, category, detected) == ("其他", "未分类", False)


def test_resolve_scope_detects_from_history(tmp_path):
    """有历史经验时能从任务文本路由到对应类别。"""
    store = _store(tmp_path)
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
        "task": "网页首屏加载很慢", "action": "压缩图片", "outcome": "LCP 降了",
        "G": 0.9,
    })
    trunk, category, detected = capsule.resolve_scope(
        store, "网页首屏加载很慢怎么办", None, None)
    assert detected is True
    assert (trunk, category) == ("前端", "页面性能")


# ---------- P1-3 补捞（首轮太薄时再捞一轮 L2） ----------

def _thin_store(tmp_path, g=0.9):
    """只有经验、没有方法卡的类别——"方法卡还没总结出来"是补捞的真实场景。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "构建报错",
        "task": "npm run build 报 Module not found",
        "action": "删掉 node_modules 重装", "outcome": "构建通过", "G": g,
    })
    return store


def test_refill_brings_experiences_when_nothing_else(tmp_path):
    """没有方法卡时，补捞把高可信经验顶上来（默认关：行为零变化）。"""
    store = _thin_store(tmp_path)
    assert capsule.build_capsule(store, "前端", "构建报错")["items"] == []
    cap = capsule.build_capsule(store, "前端", "构建报错", refill=True)
    assert [it["kind"] for it in cap["items"]] == ["experience"]
    assert cap["refilled"] is True
    assert "删掉 node_modules 重装" in cap["text"]
    assert all(it["id"] for it in cap["items"])  # D7：每条带来源 id


def test_refill_respects_g_gate(tmp_path):
    """G < 0.5 永不入（红线）——补捞不绕过注入可信门槛。"""
    store = _thin_store(tmp_path, g=0.3)
    cap = capsule.build_capsule(store, "前端", "构建报错", refill=True)
    assert cap["items"] == []
    assert cap["refilled"] is False


def test_refill_shares_one_budget(tmp_path):
    """补捞与首轮共用同一预算：装不下就停，不把预算撑破。"""
    store = _thin_store(tmp_path)
    cap = capsule.build_capsule(store, "前端", "构建报错", 12, refill=True)
    assert cap["cost"] <= 12
    assert cap["tokens"] <= 12
    assert len(cap["items"]) == 1      # 第二条装不下 → 停


def test_refill_idle_when_first_round_is_rich(tmp_path):
    """首轮已经够厚时不补——不把经验塞进已经有方法卡的胶囊里。"""
    store = _store(tmp_path)
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
        "task": "首屏慢", "action": "压缩图片", "outcome": "LCP 降了", "G": 0.9,
    })
    cap = capsule.build_capsule(store, "前端", "页面性能", refill=True)
    assert cap["refilled"] is False
    assert all(it["kind"] != "experience" for it in cap["items"])
    assert "压缩图片" not in cap["text"]
