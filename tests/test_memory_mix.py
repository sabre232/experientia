"""首页「记忆构成」卡（六层存量 P1-1 的用户可见出口）。

三条口径：

1. 有料时六格按层报数，卡片可见，六个**平实名**齐全（原始痕迹 / 原子事实 /
   身份画像 / 心智模型是引擎内部术语，UI 不露）；
2. 全 0 或取数失败时整卡隐藏——补充信息不该在空库时占一块位置，更不该报假的 0；
3. 提示句只服务唯一可行的判断（经验攒够而方法卡为空），其余情况留白。

离屏渲染（QT_QPA_PLATFORM=offscreen），零网络（桩 API 立即返回，不发请求）。
"""

from __future__ import annotations


import pytest

from PySide6.QtWidgets import QApplication, QLabel

pytest.importorskip("PySide6")

from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApi  # noqa: E402

LEDGER = {"sessions": 6, "rounds": 12, "rule_cards": 3}


def _layers(**counts) -> dict:
    base = {f"L{i}": 0 for i in range(1, 7)}
    base.update(counts)
    return {"layers": {k: {"name": k, "count": v} for k, v in base.items()}}


class _HomeApi(LocalApi):
    """首页桩：只喂账本与六层快照，其余端点按首页取数清单给空。"""

    def __init__(self, layers: dict):
        super().__init__(base_url="http://fake")
        self._layers = layers

    def _request(self, method, path, json=None, params=None, timeout=None):
        p = path.split("?")[0]
        if p == "/api/status":
            return {"agents": {}, "default_model": ""}
        if p == "/api/ledger":
            return dict(LEDGER)
        if p == "/api/layers":
            return dict(self._layers)
        if p == "/api/growth":
            return {"affinity": {}}
        if p == "/api/capture/status":
            return {"agents": {}}
        if p == "/api/insights":
            return {"items": [], "total": 0}
        if p == "/api/experience-drafts":
            return {"count": 0, "items": []}
        if p == "/api/rule-cards":
            return {"items": [], "total": 0}
        if p == "/api/experiences":
            return {"items": [], "count": 0}
        if p == "/api/models":
            return {"routes": []}
        return {}


def _open(qapp, pump_page, api, monkeypatch):
    from app.gui.home import HomePage

    monkeypatch.setattr("app.gui.home.running_agents", lambda: [])
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")  # 关数字滚动 → 同步断言
    page = HomePage(api)
    page.resize(1000, 900)
    page.show()
    page.refresh()
    assert pump_page(page, qapp), "首页后台取数未在超时内完成"
    return page


def _mix_labels(page) -> str:
    return " ".join(l.text() for l in page._mix_card.findChildren(QLabel))


def test_memory_mix_reports_all_six_layers(qapp, pump_page, monkeypatch):
    """六格按层报数；层名一律用平实名，不露引擎内部术语。"""
    page = _open(qapp, pump_page,
                 _HomeApi(_layers(L1=6, L2=14, L3=2, L4=6, L5=3, L6=1)),
                 monkeypatch)
    try:
        assert page._mix_card.isVisible()
        assert page._mix_values["L1"].text() == "6"
        assert page._mix_values["L2"].text() == "14"
        assert page._mix_values["L3"].text() == "2"
        assert page._mix_values["L4"].text() == "6"
        assert page._mix_values["L5"].text() == "3"
        assert page._mix_values["L6"].text() == "1"
        labels = _mix_labels(page)
        for name in ("会话原话", "经验", "偏好", "会话摘要", "方法卡", "意图"):
            assert name in labels, f"缺平实层名: {name}"
        for jargon in ("原始痕迹", "原子事实", "身份画像", "心智模型",
                       "前瞻意图"):
            assert jargon not in labels, f"UI 露了引擎内部术语: {jargon}"
    finally:
        page.deleteLater()


def test_memory_mix_hidden_when_nothing_stored(qapp, pump_page, monkeypatch):
    """全 0 / 取数失败 → 整卡不出现（不占位、不报假 0）。"""
    page = _open(qapp, pump_page, _HomeApi({"layers": {}}), monkeypatch)
    try:
        assert not page._mix_card.isVisibleTo(page)
    finally:
        page.deleteLater()


def test_memory_mix_hint_only_when_distill_is_due(qapp, pump_page,
                                                  monkeypatch):
    """提示句只在「经验攒够 + 方法卡为空」时出现；其余留白。"""
    cases = (
        (_layers(L2=5), True),            # 攒够 3 条且方法卡空 → 提示
        (_layers(L2=5, L5=1), False),     # 已有方法卡 → 不提示
        (_layers(L2=2), False),           # 不足 3 条 → 不提示
        (_layers(L1=9, L3=4), False),     # 没有经验也别提示
    )
    for payload, want in cases:
        page = _open(qapp, pump_page, _HomeApi(payload), monkeypatch)
        try:
            assert page._mix_hint.isVisibleTo(page) is want, \
                f"提示句显隐不符: {payload['layers']}"
            if want:
                assert page._mix_hint.text() == "经验攒够了，可以总结成方法"
        finally:
            page.deleteLater()
