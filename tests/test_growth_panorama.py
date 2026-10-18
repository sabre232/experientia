"""成长页重构思口径护栏。

防四类复发（设计走查 findings 的落点）：
1. 时间轴又去吃 experience.jsonl 的 ts（回灌后全同一天 → "最近活跃 1 天"）；
2. sessions 追加行 started_at=null 靠 `str(get(k,""))` 比较顶掉有时间戳的行
   （真机 1645 行里 159 行，257 会话被压成 98）；
3. 资产计数又回到"累计经验 82 条"混数，把 AI 手滑（agent_friction）算进用户成长；
4. 零纠正的助手被渲染成黄色"低"熟练度（产品自认没用）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.gui import growth as growth_mod, i18n  # noqa: E402
from app.store.store import Store  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    i18n.load_catalog("zh")
    return QApplication.instance() or QApplication([])


def _store(tmp_path) -> Store:
    store = Store(Path(tmp_path))
    store.ensure_layout()
    return store


def _session(store, sid, started, corr=0, agent="workbuddy", req=3,
             project="/p/demo"):
    store.record_session({
        "agent": agent, "session_id": sid, "trunk": "其他", "category": "未分类",
        "req_count": req, "correction_hits": corr, "project": project,
        "started_at": started, "ended_at": started,
    })


# ---------- 1. 时间轴吃 sessions ----------

def test_stage_timeline_reads_sessions_not_experience_ts(tmp_path):
    """经验 ts 全在同一天也要给出真实活跃天数（旧版此处显示"最近活跃 1 天"）。"""
    store = _store(tmp_path)
    for i, day in enumerate(("2026-07-06", "2026-08-10", "2026-09-14")):
        _session(store, f"s{i}", f"{day}T08:00:00Z", corr=1)
    store.append_experience({"task": "同一天的经验", "action": "a", "agent": "wb",
                             "ts": "2026-09-20T01:00:00Z", "G": 0.8})
    st = store.growth_summary(days=30)["stage"]
    assert st["sessions"] == 3
    assert st["active_days"] == 3
    assert (st["start"], st["end"]) == ("2026-07-06", "2026-09-14")
    assert st["weeks"] >= 11  # 7/6 → 9/14 跨 11 个自然周


# ---------- 2. 丢时间戳的追加行不得顶掉有时间戳的行 ----------

def test_undated_append_line_does_not_win_dedup(tmp_path):
    store = _store(tmp_path)
    _session(store, "s1", "2026-09-01T08:00:00Z", corr=2)
    line = json.dumps({"agent": "workbuddy", "session_id": "s1", "trunk": "其他",
                       "category": "未分类", "req_count": 9, "correction_hits": 0,
                       "started_at": None, "ended_at": None}, ensure_ascii=False)
    with (Path(tmp_path) / "sessions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    g = Store(Path(tmp_path)).growth_summary(days=30)
    assert g["stage"]["sessions"] == 1, "同一会话的两行必须合成一条"
    assert g["stage"]["start"] == "2026-09-01", "代表行须是有时间戳的那条"


# ---------- 3. 资产分区与首页价值闸门同源 ----------

def test_assets_partition_matches_value_gate(tmp_path):
    store = _store(tmp_path)
    store.append_experience({"task": "AI 判过的真经验", "action": "a",
                             "g_source": "judge", "importance": 9, "G": 0.9})
    store.append_experience({"task": "sig:Error: File has not been read yet",
                             "action": "recurring-error-signature",
                             "g_source": "rule", "rule_kind": "error_sig",
                             "value_class": "agent_friction", "count": 44, "G": 0.6})
    store.append_experience({"task": "改两次才过的做法", "action": "a",
                             "g_source": "rule", "rule_kind": "retry_pair", "G": 0.6})
    a = store.growth_summary(days=30)["assets"]
    assert a["total"] == 3
    assert a["experience"] + a["advice"] == a["total"], "分区必须求和闭合"
    assert a["advice"] == 1 and a["experience"] == 2
    assert a["advice_hits"] == 44, "避坑累计次数取 count，不是条目数"
    assert a["high"] == 1 and a["top"] == 1


def test_ledger_excludes_agent_friction(tmp_path):
    """AI 手滑不许进"你的经验账本"。"""
    store = _store(tmp_path)
    store.append_experience({"task": "真经验", "action": "a", "g_source": "judge",
                             "importance": 7, "G": 0.9})
    store.append_experience({"task": "sig:Error: String to replace not found",
                             "action": "recurring-error-signature",
                             "g_source": "rule", "rule_kind": "error_sig",
                             "value_class": "agent_friction", "count": 15, "G": 0.6})
    g = store.growth_summary(days=30)
    tasks = [it["task"] for it in g["ledger"]]
    assert "真经验" in tasks
    assert not any("String to replace" in t for t in tasks)
    assert [it["task"] for it in g["advice_items"]][0].startswith("sig:Error")


# ---------- 4. 返工对比窗口：样本不足就不给数字 ----------

def _weeks(store, spec):
    """spec = [(周一日期, [(corr, n)...]), ...]"""
    for wk, groups in spec:
        i = 0
        for corr, n in groups:
            for j in range(n):
                i += 1
                _session(store, f"{wk}-{i}", f"{wk}T08:00:00Z", corr=corr)


def test_rework_not_comparable_with_few_live_weeks(tmp_path):
    store = _store(tmp_path)
    _weeks(store, [("2026-09-07", [(2, 4)]), ("2026-09-14", [(1, 3)])])
    rw = store.growth_summary(days=30)["rework"]
    assert rw["comparable"] is False
    assert rw["early"] is None and rw["drop_pct"] is None


def test_rework_window_math(tmp_path):
    store = _store(tmp_path)
    _weeks(store, [
        ("2026-06-01", [(10, 3)]), ("2026-06-08", [(10, 2)]),      # 早两窗 5 次 50 纠正
        ("2026-06-15", [(0, 2)]), ("2026-06-22", [(0, 2)]),        # 中间凑周数
        ("2026-06-29", [(0, 5)]), ("2026-07-06", [(0, 5)]),        # 近三窗 12 次 0 纠正
    ])
    rw = store.growth_summary(days=30)["rework"]
    assert rw["comparable"] is True
    assert rw["early"] == 10.0 and rw["recent"] == 0.0
    assert rw["drop_pct"] == 100


def test_weekly_keeps_empty_weeks(tmp_path):
    """空周要留在序列里（rate=None），页面据此断开折线，不跨零样本连线。"""
    store = _store(tmp_path)
    _weeks(store, [("2026-08-03", [(1, 1)]), ("2026-09-07", [(1, 1)])])
    weekly = store.growth_summary(days=30)["weekly"]
    assert len(weekly) == 6, "8/3 → 9/7 共 6 个自然周"
    assert [w["rate"] for w in weekly] == [1.0, None, None, None, None, 1.0]


# ---------- 5-7. 页面渲染口径 ----------

def _payload(**over) -> dict:
    base = {
        "days": 30, "cumulative": {}, "heatmap": {"trunks": [], "grid": {}},
        "affinity": {}, "changelog": [], "maintenance": [],
        "stage": {"start": "2026-07-04", "end": "2026-09-20", "weeks": 12,
                  "active_days": 39, "sessions": 257, "agents": 4, "projects": 59},
        "assets": {"experience": 52, "advice": 30, "corrected": 14, "judged": 51,
                   "top": 10, "high": 31, "feedback": 0, "total": 82,
                   "advice_hits": 172},
        "flywheel": {"collected": 257, "distilled": 82, "judged": 51,
                     "injected": 0, "improved": None},
        "rework": {"early": 2.14, "recent": 0.35, "drop_pct": 84, "early_n": 14,
                   "recent_n": 199, "comparable": True},
        "weekly": [{"week": "2026-08-31", "sessions": 107, "corrections": 28,
                    "rate": 0.26},
                   {"week": "2026-09-07", "sessions": 65, "corrections": 31,
                    "rate": 0.48}],
        "phases": [{"month": "2026-09", "sessions": 199, "corrections": 69,
                    "days": 20}],
        "agents": [{"agent": "qclaw", "n": 10, "corrections": 0, "projects": 1,
                    "last": "2026-08-14", "early": None, "recent": None,
                    "state": "smooth"},
                   {"agent": "hermes", "n": 3, "corrections": 0, "projects": 2,
                    "last": "2026-08-14", "early": None, "recent": None,
                    "state": "few"}],
        "ledger": [{"id": "e1", "task": "跨会话延续长链路排查任务",
                    "action": "先写自包含交接单", "importance": 9,
                    "agent": "workbuddy", "corrected": True, "seen": 0,
                    "count": 1, "session_id": "s9"}],
        "advice_items": [{"id": "e2", "task": "sig:Error: File has not been read yet",
                          "state": "Error: File has not been read yet",
                          "count": 44, "seen": 23}],
    }
    base.update(over)
    return base


class _FakeApi:
    def __init__(self, payload):
        self._p = payload

    def growth(self, days=30):
        return self._p

    def skills(self):
        return {"items": []}

    def models(self):
        return {"routes": [{"endpoint": ""}]}   # 未接模型 → 熔断提示该出现

    def hooks_config(self):
        return {}


def _page(payload) -> growth_mod.GrowthPage:
    """走真实入口 refresh()（H3 后取数在后台线程）：泵到渲染落地再交还。"""
    from PySide6.QtWidgets import QApplication

    from tests.conftest import pump_until

    page = growth_mod.GrowthPage(_FakeApi(payload))
    page.refresh()
    qapp = QApplication.instance()
    assert pump_until(lambda: not page._fetches, qapp), "后台取数未在超时内完成"
    return page


def _texts(page) -> str:
    return "\n".join(l.text() for l in page.findChildren(QLabel))


def test_zero_correction_agent_not_rendered_as_low(qapp):
    """零纠正 = "本来就顺"，不许出现"低"档徽标（走查 major：把证明不了演成没用）。"""
    body = _texts(_page(_payload()))
    assert "本来就顺" in body
    assert "样本不够" in body
    assert "低" not in body, "旧版按等级徽标发低的口径不得复发"


def test_flywheel_step4_zero_is_first_class(qapp):
    """injection.log 缺失 → 第④格明写 0 并给行动入口，不再静默。"""
    page = _page(_payload())
    body = _texts(page)
    assert "经验飞轮转到哪一格了" in body
    assert "④ 带回给 AI" in body
    assert "还没接到你的助手会话里" in body
    assert page._model_ok is False, "models() 无 endpoint → 判定未接模型"
    assert "当前模型端点连不上" in body


def test_assets_partition_shown_on_page(qapp):
    body = _texts(_page(_payload()))
    assert "你的经验" in body and "助手替你挡的坑" in body
    assert "累计经验" not in body, "不许再报把 friction 算进去的混数"
    assert "累计撞见 172 次" in body


def test_ledger_row_and_drilldown_buttons(qapp):
    page = _page(_payload())
    body = _texts(page)
    assert "跨会话延续长链路排查任务" in body
    assert "你纠正后定下" in body
    assert "同类情况遇到" not in body, "seen=0 不许挂重复次数徽标"


def test_process_record_folded_but_built(qapp):
    """过程记录默认收起，但 widgets 照建（时间线可检视、不丢节点）。"""
    payload = _payload(changelog=[
        {"idx": 0, "ts": "2026-09-20T10:00:00Z",
         "text": "复盘 workbuddy 会话 abc123… → 其他/未分类 新增 2 条候选经验 [auto]",
         "tag": {"kind": "review", "agent": "workbuddy", "sid": "abc123",
                 "n": "2", "times": "1"}}])
    page = _page(payload)
    assert page._proc_open is False
    assert page._tl_box is not None and page._tl_box.findChildren(QLabel), \
        "折叠不等于不渲染：节点必须仍在树里"


def test_empty_store_falls_back_to_empty_state(qapp):
    page = _page(_payload(stage={"start": "", "end": "", "weeks": 0,
                                 "active_days": 0, "sessions": 0, "agents": 0,
                                 "projects": 0}, weekly=[], agents=[],
                         ledger=[], advice_items=[], phases=[]))
    assert "数据积累中" in _texts(page)


# ---------- 8. 图表件不许把滚动区撑出横向滚动条 ----------

def test_rework_chart_min_width_fits_content_column(qapp):
    from app.gui.qt_widgets import ReworkChart
    from app.gui.theme import SIZES

    chart = ReworkChart([{"week": f"2026-{m:02d}-01", "sessions": m,
                          "corrections": 1, "rate": 0.5} for m in range(1, 13)])
    assert chart.minimumWidth() <= SIZES.CONTENT_HOME, \
        "折柱图最小宽超过内容列会复发横向滚动条"
