"""第二批护栏：H3 后台取数 + M15 增量 diff + M14 缓存 TTL。

锁住三件事，防回归到旧行为：
- M15：数据没变的第二次刷新不得销毁重建 widget（对象恒等），变更/增删/
  重排只动涉及的那一行，其余原地不动；
- H3：fetch_and_render 的取数跑在工作线程（主线程零 HTTP）、同名在飞去重、
  收尾后允许下一轮、fetch 抛异常渲染端收到 None 自行降级；
- M14：轮询端点必须在其 TTL ≥ 轮询周期的白名单里。

桩复用 tests/test_qt_pages 的 _ExperiencesApi / _HooksRichApi（口径一致）。
"""

import os
import threading

import pytest
from PySide6.QtWidgets import QApplication

from app.gui import i18n
from app.gui.api_client import _COUPLED, _GET_TTL
from tests.conftest import pump_until
from tests.test_qt_pages import _ExperiencesApi, _HooksRichApi


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    i18n.load_catalog("zh")
    app = QApplication.instance() or QApplication([])
    yield app


def _layout_widgets(lay):
    return [lay.itemAt(i).widget() for i in range(lay.count())]


def _refresh_and_wait(page, qapp) -> None:
    """refresh() + 等后台取数收尾。

     起 ``experiences.refresh()`` 改走 ``fetch_and_render``（取数在工作
    线程），同步 ``processEvents()`` 已不足以等到渲染落地——必须泵到 ``_fetches``
    清空（原用例写于主线程同步取数时期，此处按接口变更调整）。"""
    page.refresh()
    assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
    qapp.processEvents()


# ---------- M15 · 经验库卡片列表 ----------

def test_experiences_unchanged_refresh_keeps_cards(qapp):
    """数据没变 → 第二次 refresh 卡片零重建（widget 对象恒等、顺序不变）。"""
    from app.gui.experiences import ExperiencesPage

    page = ExperiencesPage(_ExperiencesApi())
    try:
        page.resize(1200, 800)
        _refresh_and_wait(page, qapp)
        before = _layout_widgets(page._list_layout)
        assert len(before) == 2 and all(w is not None for w in before)
        _refresh_and_wait(page, qapp)
        after = _layout_widgets(page._list_layout)
        assert [id(w) for w in after] == [id(w) for w in before], \
            "数据未变卡片应原地不动——回到整表重建就是 M15 回归"
    finally:
        page.deleteLater()


def test_experiences_changed_group_replaces_only_its_card(qapp):
    """仅一个组的数据变了 → 只换那张卡，另一张恒等；位置不变。"""
    from app.gui.experiences import ExperiencesPage

    api = _ExperiencesApi()
    page = ExperiencesPage(api)
    try:
        page.resize(1200, 800)
        _refresh_and_wait(page, qapp)
        before = _layout_widgets(page._list_layout)
        api.items[2]["G"] = 0.95  # 只动 e3（基础设施组）
        _refresh_and_wait(page, qapp)
        after = _layout_widgets(page._list_layout)
        assert len(after) == 2
        assert after[0] is before[0], "未变的 modelscope 合并卡不应被动"
        assert after[1] is not before[1], "数据变更的卡应被原地替换"
    finally:
        page.deleteLater()


def test_experiences_reorder_reuses_widgets(qapp):
    """组顺序变了 → takeAt/insertWidget 归位，widget 对象不销毁。"""
    from app.gui.experiences import ExperiencesPage

    api = _ExperiencesApi()
    page = ExperiencesPage(api)
    try:
        page.resize(1200, 800)
        _refresh_and_wait(page, qapp)
        before = _layout_widgets(page._list_layout)
        # 只换组顺序（e3 组移到最前），组内成员序不动——组序变化才走重排分支
        api.items = [api.items[2], api.items[0], api.items[1]]
        _refresh_and_wait(page, qapp)
        after = _layout_widgets(page._list_layout)
        assert {id(w) for w in after} == {id(w) for w in before}, \
            "重排只应移动，不应销毁重建"
        assert after[0] is before[1] and after[1] is before[0]
    finally:
        page.deleteLater()


# ---------- M15 · Hooks 页工具行 ----------

def test_hooks_live_rows_incremental_diff(qapp):
    """30s 轮询重渲染：未变行恒等；变更行容器复用最内重建；消失行只删自己。"""
    from app.gui.hooks_page import HooksPage

    api = _HooksRichApi()
    page = HooksPage(api)
    try:
        page.resize(1200, 800)
        page.refresh()
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        qapp.processEvents()
        rows = {a: e["w"] for a, e in page._live_rows.items()}
        assert len(rows) == 4, f"应 4 行（3 工具行 + codex plain 行）: {rows}"

        # ① 同样的 overview 再渲染一轮：一切恒等
        page._render_live(api.hooks_admin_overview(), api.models())
        for a, w in rows.items():
            assert page._live_rows[a]["w"] is w, f"{a} 行数据未变应原地不动"

        # ② hermes 条目文本变了 → 容器同一对象（复用 + 内部原地重建）
        ov = api.hooks_admin_overview()
        ov["hermes"]["entries"][0]["text"] = "先跑 lint"
        sig_before = page._live_rows["hermes"]["sig"]
        page._render_live(ov, api.models())
        assert page._live_rows["hermes"]["w"] is rows["hermes"]
        assert page._live_rows["hermes"]["sig"] != sig_before
        for a in ("cursor", "claude-code", "codex"):
            assert page._live_rows[a]["w"] is rows[a], "无关行不应被重建"

        # ③ cursor 从 overview 消失 → 只删那一行，其余恒等
        ov2 = api.hooks_admin_overview()
        del ov2["cursor"]
        page._render_live(ov2, api.models())
        assert "cursor" not in page._live_rows
        for a in ("hermes", "claude-code", "codex"):
            assert page._live_rows[a]["w"] is rows[a], "删行不应牵连其余"
    finally:
        page.deleteLater()


# ---------- H3 · fetch_and_render ----------

def test_fetch_and_render_offloads_and_dedups(qapp):
    """取数跑在非主线程；在飞期间同名调用被去重；收尾后可再触发。"""
    from app.gui.page_base import PageBase

    release = threading.Event()
    seen = {}
    renders = []

    def fetch():
        seen["thread"] = threading.current_thread().name
        release.wait(5)
        return {"ok": True}

    page = PageBase(api=None)
    try:
        page.fetch_and_render(fetch, renders.append)
        # 等工作线程真正开跑（isRunning 有极短的启动窗口）
        assert pump_until(
            lambda: "thread" in seen
            and page._fetches["refresh"].isRunning(), qapp)
        worker = page._fetches["refresh"]
        page.fetch_and_render(fetch, renders.append)  # 撞在飞 → 去重
        assert page._fetches["refresh"] is worker, "在飞期间不应起第二个 worker"
        assert len(seen) == 1, "去重失败：fetch 被跑了两次"

        release.set()
        assert pump_until(lambda: not page._fetches, qapp)
        assert seen["thread"] != "MainThread", "取数不得跑在主线程"
        assert renders == [{"ok": True}], f"渲染应恰好一次: {renders}"

        # 收尾后下一轮轮询能正常触发
        page.fetch_and_render(lambda: {"ok": 2}, renders.append)
        assert pump_until(lambda: not page._fetches, qapp)
        assert renders[-1] == {"ok": 2}
    finally:
        page.deleteLater()


def test_fetch_error_renders_none(qapp):
    """fetch 整体抛异常 → worker 收敛为 None，渲染端按降级路径走。"""
    from app.gui.experiences import ExperiencesPage  # noqa: F401（触发模块导入）
    from app.gui.page_base import PageBase

    renders = []
    page = PageBase(api=None)

    def boom():
        raise RuntimeError("网络断了")

    try:
        page.fetch_and_render(boom, renders.append)
        assert pump_until(lambda: not page._fetches, qapp)
        assert renders == [None], f"异常应收敛为 None 交给渲染端: {renders}"
    finally:
        page.deleteLater()


# ---------- M14 · 轮询端点 TTL 白名单 ----------

def test_polled_endpoints_have_cache_ttl():
    """M14：30s 轮询命中的端点必须在 _GET_TTL 白名单且 TTL ≥ 轮询周期，
    否则每轮都真打 HTTP（缓存形同虚设）。"""
    polled = ("/api/hooks/admin/overview", "/api/ledger", "/api/notifications",
              "/api/workspaces")
    for p in polled:
        assert p in _GET_TTL, f"{p} 缺 TTL 白名单条目"
        assert _GET_TTL[p] >= 20.0, f"{p} TTL {_GET_TTL[p]} 短于轮询周期"
    # 写失效耦合：overview 是 /api/hooks* 写操作的下游视图
    for root in ("/api/hooks", "/api/hooks/admin"):
        assert "/api/hooks/admin/overview" in _COUPLED.get(root, ()), \
            f"{root} 写后应失效 {root}/overview 视图缓存"
