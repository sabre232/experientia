"""归属测试：成长页去空壳 / 图表入场动画 / 无数据不画假图。

对应任务书三条：
1. **无模型**（`llm.model_available` → False）时，给定若干条带 `trunk/category`
   的经验记录，成长页三块聚合（日柱 / 热力条 / 累积横条）**非空**；
2. `_TlRail.animate_in()` 在 `EXPERIENTIA_REDUCE_MOTION=1` 下不启动动画且
   `progress == 1`；
3. 图表无数据时不绘制图形（走空状态）。

口径关键：聚合卡的数据来自 `store.growth_summary` 对 experience.jsonl 自身
`trunk/category` 的现算，所以本测试**先用真 Store 写经验记录再取
payload**，而不是手搓 payload——否则证明不了"去空壳"。

离屏渲染（QT_QPA_PLATFORM=offscreen），零网络（桩 API 立即返回，不发请求）。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.distill import llm  # noqa: E402
from app.gui import growth as growth_mod, i18n  # noqa: E402
from app.gui.qt_widgets import ColumnsChart, HeatBar  # noqa: E402
from app.store.store import Store  # noqa: E402


def _store(tmp_path) -> Store:
    store = Store(Path(tmp_path))
    store.ensure_layout()
    return store


def _recent_ts(days_ago: int) -> str:
    """近 N 天的 UTC 时间戳（heatmap 只统计最近 14 天，不能写死日期）。"""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _seed_experience(store: Store) -> None:
    """三条不同 trunk/category 的近期经验（无任何会话）。"""
    for i, (trunk, cat, g) in enumerate((("写作", "长文", 0.9),
                                         ("写作", "短评", 0.8),
                                         ("编程", "重构", 0.7))):
        store.append_experience({
            "task": f"任务{i}", "action": "做法", "agent": "workbuddy",
            "trunk": trunk, "category": cat, "G": g, "ts": _recent_ts(i),
        })


class _FakeApi:
    """桩 API：growth/skills/hooks 立即返回；models 无 endpoint = 未接模型。"""

    def __init__(self, payload: dict):
        self._p = payload

    def growth(self, days=30):
        return self._p

    def skills(self):
        return {"items": []}

    def models(self):
        return {"routes": [{"endpoint": ""}]}   # 未接模型 → 门禁口径 False

    def hooks_config(self):
        return {}


def _page(payload: dict) -> growth_mod.GrowthPage:
    """走真实入口 refresh()（H3 后取数在后台线程）：泵到渲染落地再交还。"""
    from tests.conftest import pump_until

    page = growth_mod.GrowthPage(_FakeApi(payload))
    page.refresh()
    qapp = QApplication.instance()
    assert pump_until(lambda: not page._fetches, qapp), "后台取数未在超时内完成"
    return page


def _texts(page) -> str:
    return "\n".join(l.text() for l in page.findChildren(QLabel))


# ---------- 1. 无模型时三块聚合仍非空（去空壳） ----------

def test_no_model_aggregate_blocks_not_empty(tmp_path, qapp, monkeypatch):
    """零模型 + 只有经验记录（无会话）→ 三块聚合图照出，不是空壳。

    这是的核心判据：旧版聚合口径取自蒸馏产物（无模型不产出）→ 必然空；
    改按经验记录自身 trunk/category 后，零模型也有数。
    """
    # 显式钉死"无模型"（任务书要求）：引擎层判定 + GUI 门禁口径双落
    monkeypatch.setattr(llm, "model_available", lambda *a, **k: False)

    store = _store(tmp_path)
    _seed_experience(store)
    payload = store.growth_summary(days=30)

    # 前提断言：聚合原料确实由经验记录现算出来（不靠手搓 payload 蒙混）
    assert payload["cumulative"], "经验记录应派生出按类累积序列"
    assert payload["heatmap"]["grid"], "近 14 天经验应派生出热力格"
    assert payload["stage"]["sessions"] == 0, "本场景刻意没有会话"

    page = _page(payload)
    try:
        assert page._model_ok is False, "models() 无 endpoint → 判定未接模型"
        body = _texts(page)
        # 空壳判据：不许走"数据积累中"
        assert "数据积累中" not in body
        # 三块聚合图各自的标题都在
        assert "你的经验按任务类型长出来" in body
        assert "近 14 天每天收进多少条" in body
        assert "近 14 天活跃度" in body
        assert "按任务类型攒下的条数" in body
        # 真画了图形（不是只有标题）
        assert page.findChildren(ColumnsChart), "日柱图未绘制"
        assert page.findChildren(HeatBar), "热力条未绘制"
    finally:
        page.deleteLater()


def test_no_sessions_but_experience_keeps_ledger(tmp_path, qapp):
    """只有经验记录时账本（事实层）仍在——不能被"还没有会话"一起清空。"""
    store = _store(tmp_path)
    store.append_experience({"task": "跨会话延续任务", "action": "先写交接单",
                             "agent": "workbuddy", "trunk": "写作",
                             "category": "长文", "G": 0.9,
                             "ts": _recent_ts(0)})
    page = _page(store.growth_summary(days=30))
    try:
        assert "跨会话延续任务" in _texts(page)
    finally:
        page.deleteLater()


def test_explain_gate_migrated_off_guide_connect_ai(tmp_path, qapp, monkeypatch):
    """「讲人话」门禁须走 require_model—— 删了 guide_connect_ai，
    旧调用点会 AttributeError。"""
    store = _store(tmp_path)
    _seed_experience(store)
    page = _page(store.growth_summary(days=30))
    try:
        assert not hasattr(page, "guide_connect_ai"), "该门禁已删除"
        seen: dict = {}

        def _gate(self, action):
            seen["action"] = action
            return False

        monkeypatch.setattr(type(page), "require_model", _gate)
        page._explain({"id": "e1"})   # 门禁 False → 直接返回；旧码此处会崩
        assert seen.get("action") == "让 AI 讲人话"
    finally:
        page.deleteLater()


# ---------- 2. _TlRail 入场动画的 reduced-motion 行为 ----------

def test_tl_rail_reduced_motion_stays_terminal(qapp, monkeypatch):
    """EXPERIENTIA_REDUCE_MOTION=1 → animate_in 不启动动画，progress 保持 1。"""
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    rail = growth_mod._TlRail("#888888", last=False)
    try:
        assert rail.progress == 1.0, "未调用即终态（fail-open）"
        rail.animate_in()
        assert rail.progress == 1.0, "reduced-motion 下不得动"
        anim = getattr(rail, "_enter_anim", None)
        assert anim is None or not anim.state(), "不得启动 QPropertyAnimation"
    finally:
        rail.deleteLater()


def test_tl_rail_animates_when_motion_ok(qapp, monkeypatch):
    """动效开启时 animate_in 挂上动画（progress 属性驱动）。"""
    monkeypatch.delenv("EXPERIENTIA_REDUCE_MOTION", raising=False)
    monkeypatch.setattr("app.gui.qt_widgets.motion_ok", lambda: True)
    rail = growth_mod._TlRail("#888888", last=False)
    try:
        rail.animate_in()
        anim = getattr(rail, "_enter_anim", None)
        assert anim is not None, "动效开启应挂上入场动画"
    finally:
        rail.deleteLater()


# ---------- 3. 无数据不画假图（走空状态） ----------

def test_no_experience_shows_empty_state_without_charts(tmp_path, qapp):
    """真的没有任何经验记录 → 空状态，且不画聚合图形（不造假图）。"""
    store = _store(tmp_path)   # 空 store：无经验、无会话
    payload = store.growth_summary(days=30)
    assert not payload["cumulative"] and not payload["heatmap"]["grid"]

    page = _page(payload)
    try:
        assert "数据积累中" in _texts(page)
        assert not page.findChildren(ColumnsChart), "无数据不得画日柱"
        assert not page.findChildren(HeatBar), "无数据不得画热力条"
    finally:
        page.deleteLater()

def test_growth_blocks_reused_when_data_unchanged(qapp, tmp_path):
    """成长页按块增量复用：同数据再渲一轮，块控件对象必须恒等。

    本页在 LIVE_PAGES 里（每 30s 轮询一次），整块「清空 + 全建」等于每半分钟
    把七大块连同子控件全部销毁重建——既浪费，也会丢掉过程记录的折叠状态与
    hover。改为 sync_tracked 后，数据没变的块原地不动。
    """
    store = _store(tmp_path)
    _seed_experience(store)
    payload = store.growth_summary(days=30)

    page = _page(payload)
    ids1 = {k: id(v["w"]) for k, v in page._blocks.items()}
    assert ids1, "至少一个数据块应被渲染（否则测不到复用）"

    # 同数据再渲一轮（模拟 30s 轮询取回相同数据）
    page._render(payload, [])
    ids2 = {k: id(v["w"]) for k, v in page._blocks.items()}
    rebuilt = sorted(k for k in ids1 if ids1[k] != ids2.get(k))
    assert rebuilt == [], f"数据未变却重建了这些块：{rebuilt}"
