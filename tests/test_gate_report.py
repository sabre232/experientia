"""闸门回测报告测试（收尾工具）。

报告的契约只有两条：**任何一项统计失败都不能让整份报告挂掉**，以及
**只读**（跑完数据目录一个字节都不许变）。这两条是它的全部价值所在。
"""

import json

from scripts import gate_report as gr
from app.store.store import Store


def _store(tmp_path):
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


def _seed(store):
    """造一份成分复杂的库：真教训 / 环境噪音 / 助手摩擦 / 无证据 / 已换代。"""
    base = {"agent": "codebuddy", "trunk": "前端", "category": "页面性能"}
    store.append_experience({**base, "task": "优化首屏", "state": "LCP 慢",
                             "action": "图片转 WebP", "outcome": "快了",
                             "G": 0.8,
                             "evidence": {"quote": "我把图片转成了 WebP",
                                          "source": "session",
                                          "locatable": True}})
    store.append_experience({**base, "task": "调接口", "state": "连接被拒",
                             "action": "重试", "outcome": "还是不行", "G": 0.4})
    store.append_experience({**base, "task": "改文件",
                             "state": "String to replace not found",
                             "action": "先读再改", "outcome": "改上了", "G": 0.7})
    store.append_experience({**base, "task": "老数据", "action": "一条老经验",
                             "outcome": "有结果", "G": 0.8,
                             "evidence": "一条老格式的字符串证据"})
    a = store.append_experience({**base, "task": "会换代的经验",
                                 "action": "第一版做法", "outcome": "成了", "G": 0.9})
    store.supersede_experience(a["id"], {"action": "第二版做法"})
    store.write_skill("前端", "页面性能", """# p

## 失败模式
- [Solidified] 首屏图片不压缩（出现 4 次）

## 成功要点
- 大图一律转 WebP
""")
    store.write_preferences("前端", "- 结论先行")
    store.add_intention("整理优化流程", "前端", "页面性能")
    return store


def test_report_shape_on_populated_store(tmp_path):
    store = _seed(_store(tmp_path))
    rep = gr.build_report(store, budget=800)
    for key in ("data_dir", "layers", "attention_gate", "evidence",
                "chain", "forget", "retrieval"):
        assert key in rep
    assert rep["layers"]["L2"]["count"] >= 6
    assert rep["layers"]["L5"]["count"] == 1
    assert rep["layers"]["L6"]["count"] == 1


def test_attention_gate_backtest_classifies_all_routes(tmp_path):
    store = _seed(_store(tmp_path))
    g = gr.gate_backtest(store)
    routes = g["routes"]
    assert routes.get("experience", 0) >= 3
    # 库里那条"连接被拒"按今天口径会被拒
    assert routes.get("reject", 0) >= 1
    # 那条"String to replace not found"会转避坑通道
    assert routes.get("advice", 0) >= 1
    assert g["total"] == sum(routes.values())


def test_evidence_coverage_counts(tmp_path):
    store = _seed(_store(tmp_path))
    e = gr.evidence_coverage(store)
    assert e.get("has_quote", 0) >= 2
    assert e.get("structured", 0) >= 1      # 新格式
    assert e.get("legacy_string", 0) >= 1   # 老格式
    assert e.get("locatable", 0) >= 1
    assert e.get("no_quote", 0) >= 2


def test_chain_and_forget_stats(tmp_path):
    store = _seed(_store(tmp_path))
    c = gr.chain_stats(store)
    assert c["superseded"] == 1
    assert c["max_chain_depth"] >= 2
    assert c["revisions"].get("2") == 1
    # 遗忘一条再统计
    head_id = next(iter(store.iter_experiences(
        include_distilled=True)))["id"]
    head = store.experience_chain(head_id)["current"]
    store.forget_experience(head["id"])
    assert gr.forget_stats(store)["tombstoned"] == 1
    assert gr.forget_stats(store)["archived_in_deprecated"] >= 1


def test_retrieval_stats_within_budget(tmp_path):
    store = _seed(_store(tmp_path))
    r = gr.retrieval_stats(store, 800)
    assert r["sampled_categories"] == 1
    assert r["over_budget"] == 0
    assert r["worst_cost"] <= 800


def test_report_is_read_only(tmp_path):
    """跑完报告，数据资产一个字节都不许变（SQLite 记账文件除外）。"""
    store = _seed(_store(tmp_path))

    def _snapshot(root):
        out = {}
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.name.endswith(("-wal", "-shm", "-journal")):
                continue
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_mtime_ns, st.st_size)
        return out

    before = _snapshot(store.data_dir)
    gr.build_report(store, budget=800)
    assert _snapshot(store.data_dir) == before


def test_report_never_raises_on_broken_store(tmp_path):
    class Broken:
        data_dir = tmp_path
        _expdb = None

        def __getattr__(self, name):
            raise RuntimeError("boom")

        def iter_experiences(self, **kw):
            raise RuntimeError("boom")

        def list_skills(self):
            raise RuntimeError("boom")

        def list_preference_trunks(self):
            raise RuntimeError("boom")

        def list_intentions(self):
            raise RuntimeError("boom")

    rep = gr.build_report(Broken(), budget=800)
    # layers.inventory 的契约就是"永不抛"→ 全层记 0，报告照样完整出得来
    assert set(rep["layers"]) == {"L1", "L2", "L3", "L4", "L5", "L6"}
    assert all(v["count"] == 0 for v in rep["layers"].values())
    # 其余各项失败后退化为空，但键必须在（调用方按键取值不 KeyError）
    assert rep["attention_gate"] == {}
    assert rep["evidence"] == {}
    assert rep["retrieval"]["sampled_categories"] == 0


def test_json_dump_is_serializable(tmp_path):
    store = _seed(_store(tmp_path))
    out = tmp_path / "report.json"
    gr.build_report(store, budget=800)
    out.write_text(json.dumps(gr.build_report(store, 800), ensure_ascii=False),
                   encoding="utf-8")
    assert json.loads(out.read_text(encoding="utf-8"))["data_dir"]


# ---------- L1：召回延迟（协议层 p95）----------

def test_latency_zero_queries_returns_empty(tmp_path):
    """`--latency 0` = 不测：直接给空 dict，不空跑一遍再丢掉。"""
    assert gr.retrieval_latency(_seed(_store(tmp_path)), 0) == {}


def test_latency_reports_numeric_percentiles(tmp_path):
    """有库时给出 p50/p95/max。

    只断言形状与单调性，不断言具体毫秒——用计时长短做判据的测试在 CI 上会抖。
    """
    store = _seed(_store(tmp_path))
    out = gr.retrieval_latency(store, 3)
    assert out["queries"] >= 1, "库里至少有一条够长的 task 可当查询"
    for k in ("p50_ms", "p95_ms", "max_ms"):
        assert isinstance(out[k], float) and out[k] >= 0.0
    assert out["p50_ms"] <= out["p95_ms"] <= out["max_ms"]
    assert out["library"] >= out["queries"] >= 1
    assert out["target_ms"] == gr.LATENCY_TARGET_MS


def test_build_report_skips_latency_when_disabled(tmp_path):
    """总报告里 latency 键恒在；关了就是 {}，开了才有数。"""
    store = _seed(_store(tmp_path))
    assert gr.build_report(store, 800, 0)["latency"] == {}
    assert gr.build_report(store, 800, 2)["latency"]["queries"] >= 1
