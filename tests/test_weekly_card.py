"""本周结算卡 + 成长叙事落地护栏（海报/周报重做）。

四条"复发就难看"的锁：
1. 滚动区里的折行标签不得塌成 0 高（首跑真机就踩到：四问正文全部看不见）；
2. 结算卡 / 周报正文不得漏出内部串（"未分类"、agent 键、sig: 前缀）；
3. injection.log 缺失时"哪条经验在变强"必须显式说话，不许静默消失
   （旧周报四问被吞掉三问就是这么来的）；
4. 空周不连线（rate=None 保留在序列里）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.distill import growth_story as gs  # noqa: E402
from app.gui import i18n  # noqa: E402


G = {
    "days": 30, "cumulative": {}, "heatmap": {"trunks": [], "grid": {}},
    "affinity": {"codex/营销/文案写作": {"n": 5, "level": "中", "diff": 1,
                                     "excluded": False}},
    "stage": {"start": "2026-07-04", "end": "2026-09-20", "weeks": 12,
              "active_days": 39, "sessions": 257, "agents": 4, "projects": 59},
    "flywheel": {"collected": 257, "distilled": 82, "judged": 51,
                 "injected": 0, "improved": None},
    "assets": {"experience": 52, "advice": 30, "corrected": 14, "judged": 51,
               "top": 10, "high": 31, "feedback": 0, "total": 82,
               "advice_hits": 172},
    "rework": {"early": 2.14, "recent": 0.35, "drop_pct": 84, "early_n": 14,
               "recent_n": 199, "early_corr": 30, "recent_corr": 69,
               "comparable": True},
    "weekly": [{"week": "2026-06-29", "sessions": 8, "corrections": 0,
                "rate": 0.0},
               {"week": "2026-07-06", "sessions": 0, "corrections": 0,
                "rate": None},
               {"week": "2026-09-14", "sessions": 27, "corrections": 10,
                "rate": 0.37}],
    "agents": [{"agent": "workbuddy", "n": 236, "corrections": 112,
                "projects": 56, "last": "2026-09-20", "early": 5.0,
                "recent": 0.35, "state": "improved"},
               {"agent": "hermes", "n": 3, "corrections": 0, "projects": 2,
                "last": "2026-08-14", "early": None, "recent": None,
                "state": "few"}],
    "ledger": [{"id": "e1", "task": "跨会话先写交接单", "importance": 9}],
    "advice_items": [{"id": "e2", "task": "sig:Error: File has not been read yet",
                      "count": 44}],
}


def _loc():
    return gs.localize(gs.build(G), i18n.t)


# ---------- 1. 布局塌陷 ----------

def test_weekly_card_has_no_collapsed_labels(qapp):
    """结算卡：有文字的标签高度必须 >0（滚动区内折行标签会被算成 0 高）。"""
    from app.gui.weekly_card import WeeklyCard

    w = WeeklyCard({"week": "2026-09-14", "story": _loc(), "sections": {}})
    w.resize(560, 720)
    w.show()
    for _ in range(3):
        qapp.processEvents()
    flat = "\n".join(l.text() for l in w.findChildren(QLabel))
    assert "做对了吗" in flat and "更快了吗" in flat
    collapsed = [l.text()[:24] for l in w.findChildren(QLabel)
                 if l.text().strip() and l.height() < 8]
    assert not collapsed, f"标签塌陷（字在但看不见）: {collapsed}"
    w.close()


# ---------- 2. 内部串不外泄 ----------

def test_weekly_sections_free_of_internal_labels():
    """周报正文不得出现"未分类" / sig: / 机器键。"""
    g = dict(G, affinity={"workbuddy/其他/未分类": {"n": 9, "level": "低",
                                                "diff": 0, "excluded": True}})
    text = "\n".join(ln for v in gs.sections_text(gs.build(g)).values()
                     for ln in v)
    for bad in ("未分类", "sig:", "pit_avoider", "agent_friction"):
        assert bad not in text, bad


def test_milestone_names_are_plain_words():
    """成就展示走人话名（旧版把 pit_avoider 原样推给用户）。"""
    g = dict(G, affinity={"workbuddy/其他/未分类": {"n": 9, "level": "低",
                                             "diff": 0, "excluded": True}})
    ms = gs.localize(gs.build(g, unlocked=[
        {"type": "pit_avoider", "scope": "workbuddy/营销/文案写作"}]),
        i18n.t)["milestones"]
    line = ms["unlocked"][0]
    assert "避坑达人" in line and "文案写作" in line
    assert "pit_avoider" not in line
    # 类别还没长出来时不拿"未分类"糊用户：降级到只说助手名
    ms2 = gs.localize(gs.build(g, unlocked=[
        {"type": "legacy", "scope": "global"}]), i18n.t)["milestones"]
    assert "传承" in ms2["unlocked"][0] and "global" not in ms2["unlocked"][0]


# ---------- 3. 缺数据必须显式说话 ----------

def test_missing_injection_is_stated_not_dropped():
    """injection.log 缺失 → "哪条经验在变强"仍要在，且说清为什么没有。"""
    qs = _loc()["questions"]
    stronger = next(q for q in qs if q["id"] == "stronger")
    assert "还没开始" in stronger["body"]
    assert stronger["action"], "断链要给行动入口，不能只报告诉用户没有"
    assert len(qs) == 4, "四问一问都不能少（旧版被静默吞掉三问）"


def test_zero_correction_agent_is_not_low():
    """零纠正 = 本来就顺，不是"低"熟练度。"""
    rows = gs.agent_rows(G)
    chips = {r["name"]: r["chip"] for r in rows}
    assert chips["workbuddy"] == "明显变顺"
    assert chips["hermes"] == "样本不够"
    assert all("低" != c for c in chips.values())


# ---------- 4. 空周留洞 ----------

def test_empty_weeks_keep_null_rate():
    spark = _loc()["spark"]
    assert [s["rate"] for s in spark] == [0.0, None, 0.37]


# ---------- 5. t() 目录未加载也要格式化 ----------

def test_t_formats_without_catalog(monkeypatch):
    """占位符不得因为目录没加载而漏到界面上（早先直接 return key）。"""
    from app.gui import i18n as I

    monkeypatch.setattr(I, "_catalog", None)
    assert I.t("共 {n} 条", n=7) == "共 7 条"
    assert I.t("无参串") == "无参串"


# ---------- 6. 无模型：引导卡 + 统计不抹成 0 ----------

def test_weekly_card_no_model_shows_guidance_and_real_counts(qapp):
    """无模型时主句位置放引导卡（不是空壳），统计照给真值（不是 0）。"""
    from PySide6.QtWidgets import QPushButton

    from app.gui.weekly_card import WeeklyCard

    story = gs.localize(gs.build(G, model_state="unconfigured"), i18n.t)
    w = WeeklyCard({"week": "2026-09-14", "story": story, "sections": {}})
    w.resize(560, 720)
    w.show()
    for _ in range(3):
        qapp.processEvents()
    flat = "\n".join(l.text() for l in w.findChildren(QLabel))
    acts = [b.text() for b in w.findChildren(QPushButton)]
    # 统计是真数（G 里 4 助手 / 59 项目 / 39 活跃日），不是清零后的"0 个助手"
    assert "4 个助手" in flat and "39 个活跃日" in flat
    # 引导段：正向标题 + 单一主操作
    assert gs.GATE_TITLE_UNCONFIGURED in flat
    assert gs.GATE_ACTION_UNCONFIGURED in acts
    assert len([a for a in acts if a == gs.GATE_ACTION_UNCONFIGURED]) == 1
    # 只有一个标题的空卡不渲染
    assert "四个问题" not in flat
    w.close()


def test_weekly_card_unreachable_names_the_endpoint(qapp):
    """配了连不上：文案点名是哪个端点（写死本机地址对云端 API 是假话）。"""
    from app.gui.weekly_card import WeeklyCard

    story = gs.localize(gs.build(G, model_state="unreachable",
                                 endpoint="http://127.0.0.1:8080/v1"), i18n.t)
    w = WeeklyCard({"week": "2026-09-14", "story": story, "sections": {}})
    w.resize(560, 720)
    w.show()
    for _ in range(3):
        qapp.processEvents()
    flat = "\n".join(l.text() for l in w.findChildren(QLabel))
    assert "127.0.0.1:8080" in flat
    assert gs.GATE_TITLE_UNCONFIGURED not in flat   # 两种处境说不同的话
    w.close()


# ---------- 7. 结算卡里的「拼成一张海报」口径跟随成长页 ----------

def test_weekly_poster_follows_parent_span(qapp, monkeypatch):
    """海报窗口跟成长页当前阶段跨度走——此前写死 30 天，两处口径对不上。"""
    from app.gui import report_view, weekly_card

    calls: list[int] = []

    class _FakeCard:
        def __init__(self, data, parent=None, on_poster=None):
            self._on_poster = on_poster

        def exec(self):
            self._on_poster()  # 模拟用户点了「拼成一张海报」
            return 1

    class _Api:
        def weekly_report(self):
            return {"story": {}}

    class _Parent:
        _poster_days = 84  # 页面上是 12 周阶段

        def set_status(self, *a, **k):
            pass

    monkeypatch.setattr(weekly_card, "WeeklyCard", _FakeCard)
    monkeypatch.setattr(report_view, "open_growth_report",
                        lambda api, days=30, parent=None: calls.append(days))

    weekly_card.open_weekly_card(_Api(), _Parent())
    assert calls == [84], f"海报窗口没跟随页面跨度：{calls}"


def test_open_weekly_card_uses_host_run_async(qapp, monkeypatch):
    """：周卡取数必须走宿主页 run_async（后台线程）。

    旧实现 `api.weekly_report()` 同步跑在 UI 线程（api_client 侧 15s 超时）——
    引擎未起/卡住时点开周卡冻结界面最长 15 秒。"""
    from app.gui import weekly_card

    seen = []

    class _Api:
        def weekly_report(self):
            seen.append("sync")  # 走了同步就说明退化
            return {"story": {}}

    class _Host:
        _poster_days = 30

        def set_status(self, *_a, **_k):
            pass

        def run_async(self, work, on_ok=None, on_err=None, **_k):
            seen.append("runner")
            # 不真正执行 → 不弹模态框；只证明取数走了后台通道

    weekly_card.open_weekly_card(_Api(), _Host())
    assert seen == ["runner"], \
        f"周卡取数没有走宿主页后台执行（会冻结 UI）：{seen}"


def test_open_weekly_card_sync_fallback_without_runner(qapp, monkeypatch):
    """无宿主 run_async（非页面上下文调用）→ 退回同步，功能不丢。"""
    from app.gui import report_view, weekly_card

    opened = []

    class _FakeCard:
        def __init__(self, data, parent=None, on_poster=None):
            opened.append(data)

        def exec(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr(weekly_card, "WeeklyCard", _FakeCard)

    class _Api:
        def weekly_report(self):
            return {"story": {"ok": True}}

    class _Parent:
        _poster_days = 30

        def set_status(self, *_a, **_k):
            pass

    weekly_card.open_weekly_card(_Api(), _Parent())
    assert opened, "同步回退没有弹卡（功能丢了）"
    assert isinstance(opened[0].get("story"), dict) and "ok" in opened[0]["story"], \
        f"同步回退丢了数据：{opened[0].get('story')}"


def test_open_weekly_card_failure_reports_to_status(qapp, monkeypatch):
    """取数失败 → 写宿主页状态行，不静默、不崩（入口兜底口径不变）。"""
    from app.gui import weekly_card

    msgs = []

    class _Api:
        def weekly_report(self):
            raise RuntimeError("engine down")

    class _Host:
        _poster_days = 30

        def set_status(self, msg, *_a, **_k):
            msgs.append(msg)

        def run_async(self, work, on_ok=None, on_err=None, **_k):
            on_err(RuntimeError("engine down"))  # 模拟后台失败回调

    weekly_card.open_weekly_card(_Api(), _Host())
    assert msgs and "engine down" in msgs[0], f"失败没有留痕：{msgs}"
