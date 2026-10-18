"""报告数据模型单测：playbook md 解析 + growth_summary → 报告结构。

弹层（report_view）与 md 导出（distill/export.py）共用这套抽取口径；
这里只测确定性抽取与排序，不碰 Flet。
"""

import pytest

from app.gui.report_model import (growth_report_model, method_sections,
                                  parse_playbook)

PLAYBOOK_MD = (
    "# 营销 / 文案写作 · playbook\n\n"
    "> name: 投放标题方法\n"
    "> name_source: ai\n"
    "> created: 2026-06-11\n"
    "> version: 3\n"
    "> updated: 2026-08-21T09:00:00Z\n"
    "> source_exps: e1, e2, e3\n"
    "> confidence: high\n\n"
    "## 方法名\n投放标题方法\n\n"
    "## 标准流程\n1. 确认投放目标\n2. 利益点前置\n\n"
    "## 成功要点\n- 两版 A/B\n\n"
    "## 失败模式\n（无）\n\n"
    "## 偏好增量\n- 结论先行\n"
)


def test_parse_playbook_head_and_source_n():
    m = parse_playbook(PLAYBOOK_MD)
    assert m["head"]["name"] == "投放标题方法"
    assert m["head"]["version"] == "3"
    assert m["head"]["created"] == "2026-06-11"
    assert m["head"]["confidence"] == "high"
    assert m["source_n"] == 3


def test_parse_playbook_sections_strip_markers_and_empty():
    m = parse_playbook(PLAYBOOK_MD)
    assert m["sections"]["标准流程"] == ["确认投放目标", "利益点前置"]
    assert m["sections"]["成功要点"] == ["两版 A/B"]
    assert m["sections"]["失败模式"] == []  # （无）→ 空
    assert m["sections"]["偏好增量"] == ["结论先行"]


def test_method_sections_order_and_skip_empty():
    m = parse_playbook(PLAYBOOK_MD)
    out = method_sections(m)
    # 展示序：流程/要点/坑在前，治理性两节垫底；失败模式为空不出现
    assert [name for name, _ in out] == ["标准流程", "成功要点", "偏好增量"]


def test_parse_playbook_missing_head_keys_none():
    m = parse_playbook("# x\n\n## 标准流程\n- a\n")
    assert m["head"]["created"] is None
    assert m["head"]["confidence"] is None
    assert m["source_n"] == 0


GROWTH = {
    "days": 30,
    "cumulative": {
        "营销/文案写作": [["2026-08-01", 1], ["2026-08-15", 5], ["2026-08-28", 9]],
        "营销/投放": [["2026-08-10", 1], ["2026-08-28", 2]],
        "工程/修服务": [["2026-08-28", 1]],
    },
    "heatmap": {
        "trunks": ["营销", "工程"],
        "grid": {"营销": [0.0] * 12 + [1.6, 0.8],
                 "工程": [0.0] * 13 + [0.4]},
        "dates": [f"2026-08-{d:02d}" for d in range(15, 29)],
    },
    "affinity": {
        "营销/文案写作": {"n": 3, "level": "高", "rounds_pct": -50,
                         "corrections_pct": -75,
                         "first": {"req_count": 10, "correction_hits": 4,
                                   "tokens": 12000, "at": "2026-08-20"},
                         "last": {"req_count": 5, "correction_hits": 1,
                                  "tokens": 9000, "at": "2026-08-28"}},
        "营销/投放": {"n": 4, "level": "低", "rounds_pct": -4,
                     "corrections_pct": None,
                     "first": {"req_count": 6, "correction_hits": 2,
                               "tokens": 0, "at": "2026-08-19"},
                     "last": {"req_count": 6, "correction_hits": 1,
                              "tokens": 0, "at": "2026-08-27"}},
        "工程/修服务": {"n": 1, "level": "待积累", "rounds_pct": None,
                       "corrections_pct": None,
                       "first": None, "last": None},
    },
}


def test_growth_model_affinity_order():
    m = growth_report_model(GROWTH)
    keys = [a["key"] for a in m["affinity"]]
    # 有对比数据的按磨合度高→低，待积累垫底
    assert keys == ["营销/文案写作", "营销/投放", "工程/修服务"]
    assert m["affinity"][0]["first"]["req_count"] == 10


def test_growth_model_totals_and_trunk_split():
    m = growth_report_model(GROWTH)
    assert m["total"] == 12
    assert m["trunk_split"] == [("营销", 11), ("工程", 1)]
    # curves 按总量降序
    assert [c["key"] for c in m["curves"]] == [
        "营销/文案写作", "营销/投放", "工程/修服务"]
    assert m["curves"][0]["total"] == 9


def test_growth_model_heat_vals_daily_sum():
    m = growth_report_model(GROWTH)
    assert len(m["heat_vals"]) == 14
    assert m["heat_vals"][12] == pytest.approx(1.6)  # 只营销
    assert m["heat_vals"][13] == pytest.approx(1.2)  # 营销 0.8 + 工程 0.4


def test_growth_model_avg_rounds_pct_only_improving():
    m = growth_report_model(GROWTH)
    # 只取负向（变好）的 rounds_pct：(-50 + -5) / 2
    assert m["avg_rounds_pct"] == -27


def test_growth_model_empty():
    m = growth_report_model({"days": 30})
    assert m["total"] == 0
    assert m["affinity"] == []
    assert m["curves"] == []
    assert m["heat_vals"] == []
    assert m["avg_rounds_pct"] is None
