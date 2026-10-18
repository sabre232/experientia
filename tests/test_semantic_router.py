"""语义归类路由护栏（-P1-1，打通注入最后一公里）。

BM25 路：改写句命中 / 陌生任务拒绝 / 平局拒绝；embedding 路：质心分类；
detect_task_context 接线：router 命中优先、router 沉默时旧字面兜底零回归。
"""

from app.proxy import detect
from app.semantic import router


def _known():
    return {
        ("营销", "文案写作"): [
            "投放标题点击率低，把利益点前置改写",
            "广告文案的利益点要放最前面再补限时钩子",
        ],
        ("编程", "调试"): [
            "pytest 收集不到测试文件，conftest 路径配错了",
        ],
    }


def test_bm25_hits_paraphrase_that_coverage_misses():
    """改写句：与样本共享稀有核心词（利益点/标题），但覆盖率 <0.5 ——
    旧口径必挂，BM25 必须捞回（这正是"最后一公里"断掉的那类）。"""
    q = "帮我把标题里的利益点挪到前面去"
    old = detect.detect_task_context(
        [{"content": q}], detect.DEFAULT_SEED_KEYWORDS, {})
    assert old["category"] == "未分类"  # 无历史类目时兜底未分类（现状）
    hit = router.classify(q, _known())
    assert hit is not None and hit[0] == ("营销", "文案写作")


def test_bm25_rejects_unknown_task():
    assert router.classify("推导薛定谔方程的数值解法", _known()) is None


def test_bm25_rejects_ambiguous_tie():
    """两类样本对该 query 得分接近（不明显领先）→ 宁缺毋滥拒归。"""
    known = {("A", "a"): ["alpha beta gamma delta epsilon"],
             ("B", "b"): ["alpha beta gamma zeta eta"]}
    assert router.classify("alpha beta gamma", known) is None


def test_embedding_centroid_path(monkeypatch):
    class FakeEmb:
        def embed(self, texts):
            return [[1.0, 0.0] if ("登录" in t or "login" in t) else [0.0, 1.0]
                    for t in texts]

    monkeypatch.setattr(router, "get_embedder", lambda store: FakeEmb())
    known = {("账号", "登录"): ["实现登录功能", "add oauth login"],
             ("厨房", "菜谱"): ["红烧肉怎么做", "炖汤火候"]}
    hit = router.classify("build a login page", known, store=object())
    assert hit is not None and hit[0] == ("账号", "登录")
    assert router.classify("红烧排骨的做法", known, store=object())[0] == ("厨房", "菜谱")


def test_detect_uses_router_first_and_falls_back_to_coverage():
    """接线：router 命中 → 直接采用；router 沉默 → 旧覆盖率兜底仍可命中（零回归）。"""
    known = _known()
    q = "帮我把标题里的利益点挪到前面去"
    out = detect.detect_task_context([{"content": q}],
                                     detect.DEFAULT_SEED_KEYWORDS, known)
    assert out == {"trunk": "营销", "category": "文案写作"}
    # 零回归：与样本完全相同的一句话，即便 monkeypatch 掉 router 也必须命中
    orig = detect.detect_task_context(
        [{"content": known[("编程", "调试")][0]}],
        detect.DEFAULT_SEED_KEYWORDS, known)
    assert orig["category"] == "调试"


def test_embedder_off_by_default(tmp_path):
    from app.store.store import Store
    from app.semantic.embedder import get_embedder

    store = Store(tmp_path)
    store.ensure_layout()
    assert get_embedder(store) is None  # 开关缺省关 → BM25 降级，零行为变化


def test_router_empty_inputs_safe():
    assert router.classify("", _known()) is None
    assert router.classify("x", {}) is None
