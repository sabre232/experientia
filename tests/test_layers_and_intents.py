"""六层记忆模型 / L6 前瞻意图测试（P1-1）。

覆盖三件事：分层映射准不准、意图的封顶与过期守不守、以及"意图绝不进注入链路"
这条红线有没有回归。
"""

import json
from datetime import datetime, timedelta, timezone

from app.distill import capsule, intents, layers
from app.store.store import Store

PLAYBOOK = """# 前端 / 页面性能 · playbook

## 失败模式
- [Solidified] 首屏图片不压缩，LCP 超 3 秒（出现 4 次）

## 成功要点
- 大图一律转 WebP
"""


def _store(tmp_path):
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


def _mcp_capsule(store, trunk, category, **extra):
    """走 MCP 协议层构建胶囊——只读代理在被测路径上。"""
    from app.mcp_server import McpServer

    resp = McpServer(store).handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "experientia_context_capsule",
                   "arguments": {"trunk": trunk, "category": category,
                                 **extra}}})
    assert "error" not in resp, resp
    return json.loads(resp["result"]["content"][0]["text"])


# ---------- 六层映射 ----------

def test_layer_mapping_covers_inject_kinds():
    assert layers.LAYER_ORDER == ("L1", "L2", "L3", "L4", "L5", "L6")
    for kind in ("pref", "failure", "fix", "flow", "insight"):
        assert layers.layer_of_kind(kind) in layers.LAYERS
    # 偏好 = 画像层；playbook 全家 = 心智模型层
    assert layers.layer_of_kind("pref") == "L3"
    assert {layers.layer_of_kind(k) for k in
            ("failure", "fix", "flow", "insight")} == {"L5"}
    # 未知 kind 回落 L2，不许冒充 L5
    assert layers.layer_of_kind("外星人") == "L2"
    assert layers.weight_of_layer("不存在的层") == 0.0


def test_capsule_layer_weights_follow_layers_module():
    """胶囊的层权重来自 layers.py——只改一处，不会两处分叉。"""
    for kind, weight in capsule.LAYER_WEIGHT.items():
        assert weight == layers.weight_of_kind(kind)
    assert capsule.LAYER_WEIGHT["pref"] > capsule.LAYER_WEIGHT["insight"]


def test_inventory_counts_each_layer(tmp_path):
    store = _store(tmp_path)
    store.write_skill("前端", "页面性能", PLAYBOOK)
    store.write_preferences("前端", "- 结论先行")
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
        "task": "首屏慢", "action": "压图", "outcome": "快了", "G": 0.9})
    store.add_intention("整理优化流程", "前端", "页面性能")

    inv = layers.inventory(store)
    assert inv["L2"]["count"] == 1
    assert inv["L3"]["count"] == 1
    assert inv["L5"]["count"] == 1
    assert inv["L6"]["count"] == 1
    assert inv["L1"]["count"] == inv["L4"]["count"]   # 同源
    assert {d["count"] for d in inv.values()} != {0}


def test_inventory_never_raises_on_broken_store(tmp_path):
    class Broken:
        data_dir = tmp_path

        def __getattr__(self, name):
            raise RuntimeError("boom")

    inv = layers.inventory(Broken())
    assert all(v["count"] == 0 for v in inv.values())


# ---------- L6 前瞻意图 ----------

def test_add_intention_dedupes_and_merges_evidence(tmp_path):
    store = _store(tmp_path)
    first = store.add_intention("整理优化流程", "前端", "页面性能",
                                evidence_ids=["a"])
    assert first["count"] == 1
    again = store.add_intention("整理优化流程", "前端", "页面性能",
                                evidence_ids=["b"])
    assert again["id"] == first["id"]        # 不是新造一条
    assert again["count"] == 2
    assert set(again["evidence_ids"]) == {"a", "b"}
    assert len(store.list_intentions()) == 1


def test_add_intention_rejects_empty(tmp_path):
    store = _store(tmp_path)
    assert store.add_intention("", "前端", "x") is None
    assert store.add_intention("   ", "前端", "x") is None


def test_intention_expires_after_14_days(tmp_path):
    """意图 14 天过期：TTL 常量钉住，过期即从读路径消失（物理清靠 prune）。"""
    from app.store.intentions import INTENTIONS_EXPIRE_DAYS

    assert INTENTIONS_EXPIRE_DAYS == 14
    store = _store(tmp_path)
    store.add_intention("整理优化流程", "前端", "页面性能")
    assert len(store.list_intentions()) == 1

    # 模拟"已经过了保质期"：把这条的 expires_at 拨到 TTL 之前（读侧只认这个字段）
    past = (datetime.now(timezone.utc)
            - timedelta(days=INTENTIONS_EXPIRE_DAYS, seconds=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    rows = [json.loads(x) for x in
            (store.data_dir / "intentions.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        r["expires_at"] = past
    store._write_intentions(rows)

    assert store.list_intentions() == []
    assert store.list_intentions(include_expired=True)
    assert store.prune_expired_intentions() == 1
    assert store.list_intentions(include_expired=True) == []


def test_intention_capped_per_trunk(tmp_path, monkeypatch):
    store = _store(tmp_path)
    from app.store.intentions import INTENTIONS_MAX_PER_TRUNK

    clock = [0]

    def fake_utcnow():
        clock[0] += 1
        base = datetime(2026, 10, 18, tzinfo=timezone.utc)
        return (base + timedelta(seconds=clock[0])).strftime(
            "%Y-%m-%dT%H:%M:%SZ")

    import app.store.intentions as im
    monkeypatch.setattr(im, "utcnow", fake_utcnow)

    for i in range(INTENTIONS_MAX_PER_TRUNK + 10):
        store.add_intention(f"意图 {i}", "前端", "页面性能")
    rows = store.list_intentions(include_expired=True)
    assert len(rows) == INTENTIONS_MAX_PER_TRUNK
    # 最旧的被丢掉
    assert all(f"意图 {i}" != rows[-1]["intent"]
               for i in range(10))


def test_dismiss_intention(tmp_path):
    store = _store(tmp_path)
    rec = store.add_intention("整理优化流程", "前端", "页面性能")
    assert store.dismiss_intention(rec["id"]) is True
    assert store.list_intentions() == []
    assert store.dismiss_intention(rec["id"]) is False   # 幂等
    # 忽略与过期都由 prune 物理清除
    assert store.prune_expired_intentions() == 1


def test_intention_counts(tmp_path):
    store = _store(tmp_path)
    store.add_intention("甲", "前端", "a")
    store.add_intention("乙", "前端", "b")
    store.add_intention("丙", "后端", "c")
    counts = store.intention_counts()
    assert counts["total"] == 3
    assert counts["per_trunk"]["前端"] == 2


# ---------- 从模式沉淀意图 ----------

_PATTERNS = [
    {"type": "frequency", "trunk": "前端", "category": "页面性能",
     "example": "图片转 WebP", "occurrences": 5, "evidence": ["e1"]},
    {"type": "path", "trunk": "前端", "category": "构建",
     "example": "改完先跑构建再上线", "occurrences": 3, "evidence": ["e2"]},
    {"type": "correction", "trunk": "Python", "category": "修复",
     "example": "改前没读文件", "occurrences": 4, "evidence": ["e3"]},
]


def test_derive_intentions_from_patterns(tmp_path):
    store = _store(tmp_path)
    added = intents.derive_intentions(store, patterns=_PATTERNS)
    assert added == 3          # 单轮上限 3
    ints = store.list_intentions()
    assert {i["category"] for i in ints} == {"页面性能", "构建", "修复"}
    # 幂等：同样的模式再跑一遍不新增
    assert intents.derive_intentions(store, patterns=_PATTERNS) == 0
    assert len(store.list_intentions()) == 3


def test_derive_ignores_single_occurrence(tmp_path):
    store = _store(tmp_path)
    added = intents.derive_intentions(store, patterns=[
        {"type": "frequency", "trunk": "前端", "category": "x",
         "example": "只出现一次", "occurrences": 1}])
    assert added == 0
    assert store.list_intentions() == []


def test_derive_skips_unknown_pattern_type(tmp_path):
    store = _store(tmp_path)
    assert intents.derive_intentions(store, patterns=[
        {"type": "外星类型", "trunk": "x", "example": "y",
         "occurrences": 9}]) == 0


def test_derive_never_raises(tmp_path):
    """附加层失败只记日志——不能拖垮主路径。"""
    store = _store(tmp_path)
    assert intents.derive_intentions(store, patterns=[
        {"type": "frequency"}]) == 0        # 缺 example → None，不抛


# ---------- 红线：意图不进注入链路 ----------

def test_inject_path_does_not_consume_intentions(tmp_path):
    """注入链路（proxy/inject）只吃 playbook 与偏好，绝不读 intentions.jsonl。"""
    from app.proxy import inject

    store = _store(tmp_path)
    store.write_skill("前端", "页面性能", PLAYBOOK)
    store.write_preferences("前端", "- 结论先行")
    store.add_intention("整理优化流程", "前端", "页面性能")

    block = inject.assemble_experience_block(store, "前端", "页面性能")
    assert "整理优化流程" not in block
    items = {i["kind"] for i in inject.iter_injection_items(
        store, "前端", "页面性能")}
    assert "intention" not in items


def test_capsule_intents_are_opt_in_and_lowest(tmp_path):
    store = _store(tmp_path)
    store.write_skill("前端", "页面性能", PLAYBOOK)
    store.write_preferences("前端", "- 结论先行")
    store.add_intention("整理优化流程", "前端", "页面性能")

    plain = capsule.build_capsule(store, "前端", "页面性能")
    assert not any(i["kind"] == "intention" for i in plain["items"])

    # 经 MCP 协议层再验一遍：只读代理在白名单内，include_intents 显式开才垫底带入
    # （白名单漏 list_intentions 时协议层整节静默丢失）
    with_intents = _mcp_capsule(store, "前端", "页面性能",
                                include_intents=True)
    kinds = [i["kind"] for i in with_intents["items"]]
    assert "intention" in kinds
    assert kinds[-1] == "intention"          # 永远垫底
    assert "前瞻意图" in with_intents["text"]


def test_mcp_capsule_respects_excluded_state(tmp_path):
    """回炉治理状态：移出的条目，MCP 召回通道同样不放行。"""
    from app.proxy import inject

    store = _store(tmp_path)
    store.write_skill("前端", "页面性能", PLAYBOOK)
    items = inject.iter_injection_items(store, "前端", "页面性能")
    target = next(it for it in items if it["kind"] == "failure")
    # 条目先随一次真实注入进 hits（set_injection_item_state 只改已存在条目）
    store.record_injection("前端", "页面性能", "s1", tokens=50,
                           items=[{"id": it["id"], "text": it["text"]}
                                  for it in items])
    store.set_injection_item_state("前端", "页面性能", target["id"],
                                   excluded=True)

    cap = _mcp_capsule(store, "前端", "页面性能")
    assert target["text"] not in [i["text"] for i in cap["items"]]


def test_capsule_intents_budget_capped(tmp_path):
    store = _store(tmp_path)
    store.add_intention("一条很长很长的意图内容" * 20, "前端", "页面性能")
    cap = capsule.build_capsule(store, "前端", "页面性能", budget_tokens=10,
                                include_intents=True)
    # 加权成本与真实 token 双双守住预算（意图倍率 2，字符额度只有一半）
    assert cap["cost"] <= 10
    assert cap["tokens"] <= 10
    assert all(i["kind"] == "intention" for i in cap["items"])
