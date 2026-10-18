"""归属测试：首页双档 / 协作页取数（任务书）。

三条口径：
1. 首页**无模型**时仍渲染「本机已整理 …」与账本数字，且全页不出现「解锁」
   字样（双档：先报本机已产出的量，再说接模型能更好；不再演"整页空"）；
2. 首页生成类按钮走 `require_model`，无模型时**不发蒸馏请求**（不假装已生成）；
3. `hooks_page.refresh()` 主线程零 HTTP（取数整体在工作线程，取数方式未改）。

离屏渲染（QT_QPA_PLATFORM=offscreen），零网络（桩 API 立即返回，不发请求）。
"""

from __future__ import annotations

import threading

import pytest

from PySide6.QtWidgets import QApplication, QLabel

pytest.importorskip("PySide6")

from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApi  # noqa: E402


def _on_main(calls: list[tuple[str, str]]) -> list[str]:
    main = threading.main_thread().name
    return [name for name, tn in calls if tn == main]


def _labels_text(page) -> str:
    return " ".join(l.text() for l in page.findChildren(QLabel))


# ---------- 首页：双档文案 + 生成门禁 ----------

LEDGER = {"sessions": 6, "rounds": 12, "tokens": 900, "cost_usd_est": 1.75,
          "cost_priced_share": 1.0, "rule_cards": 3, "rule_injectable": 2,
          "pending_fragments": 2}


class _HomeApi(LocalApi):
    """首页桩：无模型/有模型两态；记录取数线程与蒸馏请求数。"""

    def __init__(self, model_connected: bool = False):
        super().__init__(base_url="http://fake")
        self.calls: list[tuple[str, str]] = []
        self.model_connected = model_connected
        self.distill_posts = 0

    def _note(self, name: str) -> None:
        self.calls.append((name, threading.current_thread().name))

    def _request(self, method, path, json=None, params=None, timeout=None):
        p = path.split("?")[0]
        self._note(p)
        if p == "/api/status":
            return {"agents": {"codex": {"running": True}}, "default_model": ""}
        if p == "/api/models":
            routes = ([{"name": "m", "endpoint": "http://x/v1"}]
                      if self.model_connected else [])
            return {"routes": routes}
        if p == "/api/capture/status":
            return {"agents": {"codex": {"hits_24h": 9}}}
        if p == "/api/growth":
            return {"affinity": {}}
        if p == "/api/insights":
            return {"items": [], "total": 0}
        if p == "/api/experience-drafts":
            return {"count": 0, "items": []}
        if p == "/api/ledger":
            return dict(LEDGER)
        if p == "/api/rule-cards":
            return {"items": [], "total": 0}
        if p == "/api/experiences":
            return {"items": [], "count": 0}
        if p == "/api/skills/distill":
            self.distill_posts += 1
            return {"status": "ok"}
        return {}


def _open_home(qapp, pump_page, api, monkeypatch):
    from app.gui.home import HomePage
    # 进程探测（tasklist）走后台子进程，与本 WS 口径无关——桩掉，避免真起进程
    monkeypatch.setattr("app.gui.home.running_agents", lambda: [])
    page = HomePage(api)
    page.resize(1000, 900)
    page.show()
    page.refresh()
    assert pump_page(page, qapp), "首页后台取数未在超时内完成"
    return page


def test_home_dual_tier_without_model(qapp, pump_page, monkeypatch):
    """：无模型时先报本机已产出的量，且全页无「解锁」措辞。"""
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")  # 关数字滚动 → 同步断言
    page = _open_home(qapp, pump_page, _HomeApi(model_connected=False),
                      monkeypatch)
    try:
        # 上半「本机已可用」：账本数字真实报量（坑/记录）
        assert page._local_card.isVisible()
        assert "本机已整理 3 条坑、6 场记录" in page._local_body.text()
        assert page._stat_values["sessions"].text() == "6"
        assert page._stat_values["pitfalls"].text() == "3"
        # 下半「接入模型后更强」：未接模型时亮（接模型是增强而非前提）
        assert page._enhance_card.isVisible()
        # 旧锁定口径已废：不得出现「解锁」字样
        assert "解锁" not in _labels_text(page)
    finally:
        page.deleteLater()


def test_home_enhance_button_gated_without_model(qapp, pump_page, monkeypatch):
    """：生成类入口走 require_model；无模型时不发蒸馏请求。"""
    page = _open_home(qapp, pump_page, _HomeApi(model_connected=False),
                      monkeypatch)
    try:
        # 有料可蒸馏，门禁才是唯一拦点（防"因为没料所以没请求"的假绿）
        page._pending_groups = [("研发", "工程实践")]
        gates: list[str] = []
        monkeypatch.setattr(
            page, "require_model",
            lambda action: (gates.append(action), False)[1])
        page._enhance_summarize()
        assert gates == ["总结成方法"]
        assert page.api.distill_posts == 0, "无模型不得发蒸馏请求"
    finally:
        page.deleteLater()


# ---------- 协作页：取数仍整体在后台线程 ----------

class _HooksApi(LocalApi):
    """协作页桩：记录每次取数所在线程；返回空规则/空模板。"""

    def __init__(self):
        super().__init__(base_url="http://fake")
        self.calls: list[tuple[str, str]] = []

    def _request(self, method, path, json=None, params=None, timeout=None):
        p = path.split("?")[0]
        self.calls.append((p, threading.current_thread().name))
        if p == "/api/hooks/admin/overview":
            return {}
        if p == "/api/models":
            return {"routes": []}
        if p == "/api/rules":
            return {"items": [], "budget_used": 0, "budget": 400,
                    "stale_days": 30}
        if p == "/api/config":
            return {"hook_stale_days": 30, "hooks_agents_expanded": []}
        if p == "/api/rules/templates":
            return {"categories": []}
        return {}


def test_hooks_refresh_http_off_main_thread(qapp, pump_page):
    """：协作页取数方式不变——refresh() 主线程零 HTTP。"""
    from app.gui.hooks_page import HooksPage

    api = _HooksApi()
    page = HooksPage(api)
    try:
        page.resize(1200, 900)
        page.show()
        api.calls.clear()  # 构造期的取数不计入本轮
        page.refresh()
        assert pump_page(page, qapp), "协作页后台取数未在超时内完成"
        assert api.calls, "refresh() 应触发取数"
        assert not _on_main(api.calls), \
            f"主线程发生了 HTTP：{_on_main(api.calls)}（全部：{api.calls}）"
    finally:
        page.deleteLater()


def test_hooks_render_all_completes_and_updates_mascot(qapp, pump_page):
    """回归：``HooksPage._render_all`` 必须跑到底（含末尾的 ``_update_mascot``）。

    曾漏取页头吉祥物引用（``_hooks_mascot``）→ ``_update_mascot`` 抛
    ``AttributeError`` → 渲染在最后一步中断、``_content_ready`` 恒假 →
    每次打开该页都重放骨架屏（看着像空白）。"""
    from app.gui.hooks_page import HooksPage

    api = _HooksApi()
    page = HooksPage(api)
    try:
        page.resize(1200, 900)
        page.show()
        page.refresh()
        assert pump_page(page, qapp), "协作页后台取数未在超时内完成"
        assert page._hooks_mascot is not None, "页头应暴露吉祥物引用供换表情"
        assert page._content_ready is True, "render 跑到底后内容应标记为已落地"
    finally:
        page.deleteLater()


def test_template_filter_row_is_flow_layout(qapp, pump_page):
    """模板库筛选行必须是 FlowLayout（可换行），不能是 QHBoxLayout。

    回归（多语言横向溢出）：该行 = 优先级 chip 组(≈338，按钮不可压缩) + 领域下拉
    (固定 140) + 搜索框(固定 220)，合计 ≈714px。中文下内容区够宽看不出问题，但
    德语等导航栏更宽（实测 234px）→ 内容区只剩 ~765，该行撑爆列宽 → **横向滚动条**。
    QHBoxLayout 的最小宽 = 子项之和（不可换行）；FlowLayout 的最小宽 = 最宽子项，
    放不下自动换行。故此处必须锁定为 FlowLayout。
    """
    from app.gui.hooks_page import HooksPage
    from app.gui.qt_widgets import FlowLayout

    page = HooksPage(_HooksApi())
    try:
        page.resize(1200, 900)
        page.show()
        page.refresh()
        assert pump_page(page, qapp), "协作页后台取数未在超时内完成"
        assert isinstance(page._filter_row, FlowLayout), (
            "模板库筛选行必须是 FlowLayout（QHBoxLayout 会在德语等宽导航栏下溢出）")
        # 三项（优先级组 / 领域下拉 / 搜索框）都在行内 → 证明筛选行确实建好了
        assert page._filter_row.count() >= 3, (
            f"筛选行应有 优先级组/领域下拉/搜索框 三项，实际 "
            f"{page._filter_row.count()} 项")
    finally:
        page.deleteLater()