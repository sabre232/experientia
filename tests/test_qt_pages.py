"""Qt 迁移后页面回归测试（替代迁移前的 Flet 渲染测试 test_gui_pages.py）。

策略：_DeadApi 覆写 _request 立即抛 LocalApiError（模拟"引擎未运行"）。
所有页面把 LocalApiError 优雅降级，因此本测试验证：7 个页面 + 主窗口在
API 不可用时，构建与 refresh 均不崩溃（迁移后最主要的回归面——构造/导入/刷新异常）。

不依赖真实网络（本机沙箱对 localhost 死端口每请求 ~2s 延迟，会拖慢测试）：
_DeadApi 直接抛错，零网络开销，确定性。
要求离屏渲染：无显示环境也能跑（QT_QPA_PLATFORM=offscreen）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")

from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApiError  # noqa: E402
from conftest import OfflineApi  # noqa: E402


# 生成类入口的门禁统一走 require_model（起 confirm_builtin_summary /
# guide_connect_ai 已删除）。本文件的门禁用例曾用 xfail 垫住未迁移的页面，
# 现各页均已迁移，全部转为普通通过用例。


class _DeadApi(OfflineApi):
    """一切请求立即失败（模拟引擎未运行），不碰网络。

    实现在 conftest.OfflineApi——所有页面桩必须走同一份，避免漏覆写 `_request`
    的桩把请求真打到 8101。"""


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    i18n.load_catalog("zh")
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _flush_pending_deletes(qapp):
    """隔离加固：session 级共享 qapp 下，前一 test 的 `deleteLater()` 生成的
    DeferredDelete 事件会遗留到下一 test 的 processEvents 才处理，偶发造成
    跨 test 的 widget 计数污染（如 keyCopyBtn 预览 10 + 全量 15 = 25 抖动）。
    每个 test 前后各 flush 一次 pending 删除，让起点与收尾都确定化。"""
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    yield
    # 注意：嵌套/连接期间 deleteLater 可能需多轮才真正析构，主动 sendPosted 两遍
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture(scope="session")
def dead_api() -> _DeadApi:
    return _DeadApi(base_url="http://127.0.0.1:8101")


class _Store:
    """MainWindow 所需的最小 store 桩（可变 cfg：语言切换测试模拟持久化）。"""

    def __init__(self, cfg: dict | None = None):
        self.data_dir = str(Path(__file__).resolve().parent / "data-test-tmp")
        self.cfg = cfg or {"locale": "zh"}

    def load_config(self) -> dict:
        return self.cfg

    def ensure_layout(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _dead_api_for_main_window(dead_api):
    """MainWindow.__init__ 内部 `self.api = CachedApi()` 指向真实 8101（每请求
    在沙箱里 ~2s 延迟）。把 main_window 模块里的 CachedApi 换成 _DeadApi，
    让测试零网络、确定性。"""
    import app.gui.main_window as mw

    orig = mw.CachedApi
    mw.CachedApi = lambda *a, **k: dead_api
    yield
    mw.CachedApi = orig


def _build_window():
    from app.gui.main_window import MainWindow

    win = MainWindow(_Store())
    return win


def _close(win) -> None:
    win._allow_quit = True
    win.close()


def test_main_window_builds_all_pages(qapp, dead_api):
    from app.gui.main_window import PAGES

    win = _build_window()
    try:
        # 懒加载：启动只建首页，其余页首次导航时才构建
        assert list(win._pages.keys()) == ["home"]
        assert win._stack.count() == 1
        for key in PAGES[1:]:
            win._select_page(key)
        assert list(win._pages.keys()) == list(PAGES)
        assert win._stack.count() == len(PAGES)
    finally:
        _close(win)


def test_all_pages_refresh_without_crash(qapp, dead_api):
    from app.gui.main_window import PAGES

    win = _build_window()
    try:
        for key in PAGES:
            win._select_page(key)  # 懒加载：先构建该页
            win._pages[key].refresh()  # API 不可用：优雅降级，不抛异常
    finally:
        _close(win)


def test_page_navigation(qapp, dead_api):
    from app.gui.main_window import PAGES

    win = _build_window()
    try:
        for i, key in enumerate(PAGES):
            win._select_page(key)
            # 懒加载：currentWidget 按对象身份断言（堆栈顺序未必等于 PAGES 序）
            assert win._stack.currentWidget() is win._pages[key]
            assert win._nav_buttons[i].isChecked()
    finally:
        _close(win)


class _HookOfferApi(_DeadApi):
    """返回可控的 hooks_admin_overview + config，驱动主窗口「可一键接入」横幅分支。

    config() 覆写为立即返回（避免 __init__ 里 config() 走真实 8101 的 ~2s 沙箱延迟）。"""

    def __init__(self, overview: dict):
        super().__init__(base_url="http://127.0.0.1:8101")
        self._ov = overview

    def config(self):
        return {"onboarded": True, "locale": "zh"}

    def hooks_admin_overview(self):
        return self._ov


def _window_with_api(api):
    import app.gui.main_window as mw
    from app.gui.main_window import MainWindow

    orig = mw.CachedApi
    mw.CachedApi = lambda *a, **k: api
    return MainWindow(_Store()), orig


def test_hook_offer_only_installable_agents(qapp):
    """回归：主窗口横幅只提「有一键接入配方」的 agent（= install_all 覆盖集）。

    表外 agent（workbuddy/codex）没有注入配方（codex 还是 toml v1 只读）——
    提了"可一键接入"但点"全部接入"也不生效，属误导。修复后不得进横幅，
    只留 hermes/cursor/windsurf 里"存在且未接入且可写"的。"""
    ov = {
        "workbuddy": {"exists": True, "installed": False, "writable": True,
                      "label": "WorkBuddy", "kind": "json"},
        "codex": {"exists": True, "installed": False, "writable": True,
                  "label": "Codex", "kind": "toml"},
        "cursor": {"exists": True, "installed": False, "writable": True,
                   "label": "Cursor", "kind": "json"},
    }
    win, orig = _window_with_api(_HookOfferApi(ov))
    try:
        win._check_hook_offer()
        # 横幅探查已挪后台线程——泵到在飞 worker 收尾再断言渲染结果
        from tests.conftest import pump_until
        assert pump_until(lambda: not win._shell_workers, qapp)
        assert win._hook_offer_agents == ["cursor"]
        assert "workbuddy" not in win._hook_offer_agents
        assert "codex" not in win._hook_offer_agents
        # isHidden() 查控件自身隐藏标志（isVisible() 还要求顶层窗口已 show，
        # 离屏测试窗口未 show，恒为 False，不适用）
        assert not win._hook_offer_banner.isHidden()
    finally:
        import app.gui.main_window as mw

        mw.CachedApi = orig
        _close(win)


def test_hook_offer_hidden_when_only_out_of_table(qapp):
    """只有表外 agent（无一键接入配方）时，横幅应隐藏——不承诺做不到的事。

    对应用户实际场景：本机只装了 WorkBuddy + Codex，旧逻辑会弹
    "发现 2 个 AI 工具可一键接入实时捕获"，点了却不生效。"""
    ov = {
        "workbuddy": {"exists": True, "installed": False, "writable": True,
                      "label": "WorkBuddy", "kind": "json"},
        "codex": {"exists": True, "installed": False, "writable": True,
                  "label": "Codex", "kind": "toml"},
    }
    win, orig = _window_with_api(_HookOfferApi(ov))
    try:
        win._check_hook_offer()
        from tests.conftest import pump_until
        assert pump_until(lambda: not win._shell_workers, qapp), \
            "后台探查未在超时内收尾（防假通过：空断言可能只是没渲染）"
        assert win._hook_offer_agents == []
        assert win._hook_offer_banner.isHidden()  # 无一键接入配方 → 横幅保持隐藏
    finally:
        import app.gui.main_window as mw

        mw.CachedApi = orig
        _close(win)


def test_no_qcombobox_under_any_scroll_area(qapp, dead_api):
    """-fix-2 滚动护栏：QComboBox 一律不得位于任何 QScrollArea 的子孙树里。

    全局样式表下 QComboBox 的下拉容器在 QScrollArea 中会被当成 viewport 子控件，
    页面滚动时弹层跟着滚（曾表现为模板筛选被“滚下去的下拉”挡住）。页面整滚区内
    的选择器必须用 qt_widgets.SelectButton（QMenu 顶层弹层）；QComboBox 只允许
    出现在 QDialog（独立窗口，不在本测试的 widget 树中）内部。
    """
    from PySide6.QtWidgets import QComboBox, QScrollArea

    from app.gui.main_window import PAGES

    win = _build_window()
    try:
        for key in PAGES:
            win._select_page(key)  # 懒加载：全部实例化后再全树巡检
        qapp.processEvents()
        bad: list[QComboBox] = []
        for cb in win.findChildren(QComboBox):
            p = cb.parent()
            while p is not None:
                if isinstance(p, QScrollArea):
                    bad.append(cb)
                    break
                p = p.parent()
        assert not bad, (
            "QComboBox 不得位于 QScrollArea 内（会随滚动条滚走），请改用 SelectButton：\n"
            + "\n".join(f"- {b.objectName() or type(b).__name__} @ {b}" for b in bad)
        )
    finally:
        _close(win)


def test_language_switch_rebuilds(qapp, dead_api):
    from app.gui.main_window import MainWindow

    store = _Store()
    win = MainWindow(store)
    zh = [b.label_text() for b in win._nav_buttons]
    assert zh[0] == "首页"
    store.cfg["locale"] = "en"  # 模拟配置已持久化
    win.switch_language("en")
    qapp.processEvents()  # 确保 UI 重建完成
    try:
        en = [b.label_text() for b in win._nav_buttons]
        assert en[0] == "Home"
        assert zh != en
        assert win.windowTitle() == "Experientia"
    finally:
        _close(win)


def test_connect_probe_keys_section_renders(qapp, dead_api):
    """「收到的钥匙」状态卡：keys 数据会渲染出对应连接码（M3 只读展示）。"""
    from PySide6.QtWidgets import QLabel

    from app.gui.connect_page import ConnectPage

    page = ConnectPage(dead_api)
    try:
        data = {
            "self_reported": {
                "hermes": {"mode": "scan_covered", "at": "2026-09-05T10:00:00Z"}},
            "ide_hooks": {"cursor": {"installed": False},
                          "windsurf": {"installed": False}},
            "hermes_hook": {"installed": False},
            "draft_pending": 0,
        }
        keys = [{"code": "HMS-P-1A2B3C4D-9F01", "agent": "hermes",
                 "at": "2026-09-05T10:00:00Z", "mode": "scan_covered"}]
        page.refresh_probe(data, keys)
        qapp.processEvents()
        texts = [l.text() for l in page._probe_list.findChildren(QLabel)]
        assert any("HMS-P-1A2B3C4D-9F01" in s for s in texts), \
            f"钥匙连接码未渲染: {texts[:6]}"
    finally:
        page.deleteLater()


def test_connect_keys_no_inline_hook_inject_button(qapp, dead_api):
    """钥匙行不再内联「接入」按钮（hooks_redesign：实时 Hook 接入统一到 Hooks 页，
    connect 页只保留复制/删除）。防止旧的重复入口回潮。"""
    from PySide6.QtWidgets import QPushButton

    from app.gui.connect_page import ConnectPage

    page = ConnectPage(dead_api)
    try:
        base = {"self_reported": {},
                "ide_hooks": {"cursor": {"installed": False},
                              "windsurf": {"installed": False}},
                "hermes_hook": {"installed": False},
                "draft_pending": 0}
        # 可写未注入 → connect 钥匙行不再给注入按钮（入口在 Hooks 页）
        page.refresh_probe(base, [{
            "code": "HMS-P-AAAA0000-1111", "agent": "hermes",
            "mode": "hook_ready", "at": "2026-09-05T10:00:00Z",
            "hook": {"supported": True, "writable": 1,
                     "already_injected": False, "installer_supported": True}}])
        qapp.processEvents()
        names = [b.objectName() for b in page._probe_list.findChildren(QPushButton)]
        assert "keyHookInjectBtn" not in names, \
            "connect 页钥匙行不应再有注入按钮（hooks_redesign 已统一到 Hooks 页）"
        # 复制仍在（主操作平铺）；删除收进 ⋯ 菜单，不再是裸行按钮
        assert "keyCopyBtn" in names, names
        assert "keyDeleteBtn" not in names and "keyMenuBtn" in names, names
        from PySide6.QtGui import QAction

        act_names = [a.objectName()
                     for a in page._probe_list.findChildren(QAction)]
        assert "keyDeleteAction" in act_names, \
            f"删除动作应经由 ⋯ 菜单提供: {act_names}"
    finally:
        page.deleteLater()


def test_connect_keys_row_actions_present(qapp, dead_api):
    """钥匙行完整操作：每把钥匙带复制（平铺）+ 删除（⋯ 菜单），生命周期不被改名只读。"""
    from PySide6.QtWidgets import QPushButton

    from app.gui.connect_page import ConnectPage

    page = ConnectPage(dead_api)
    try:
        base = {"self_reported": {},
                "ide_hooks": {"cursor": {"installed": False},
                              "windsurf": {"installed": False}},
                "hermes_hook": {"installed": False},
                "draft_pending": 0}
        page.refresh_probe(base, [{
            "code": "HMS-P-AAAA0000-1111", "agent": "hermes",
            "mode": "scan_covered", "at": "2026-09-05T10:00:00Z",
            "hook": {"supported": False, "writable": 0,
                     "already_injected": False, "installer_supported": False}}])
        qapp.processEvents()
        names = [b.objectName() for b in page._probe_list.findChildren(QPushButton)]
        assert "keyCopyBtn" in names and "keyMenuBtn" in names, names
        from PySide6.QtGui import QAction

        act_names = [a.objectName()
                     for a in page._probe_list.findChildren(QAction)]
        assert "keyDeleteAction" in act_names, \
            f"删除入口应存在于 ⋯ 菜单: {act_names}"
    finally:
        page.deleteLater()


def test_connect_keys_grouped_not_flat(qapp, dead_api):
    """同一工具的 28 把钥匙**不逐行平铺**（用户痛点）：聚成一个折叠栏，默认收起；
    展开给 10 把预览，「展开全部」才列出全部。"""
    from PySide6.QtWidgets import QLabel, QPushButton, QWidget

    from app.gui.connect_page import ConnectPage

    page = ConnectPage(dead_api)
    try:
        base = {"self_reported": {},
                "ide_hooks": {"cursor": {"installed": False},
                              "windsurf": {"installed": False}},
                "hermes_hook": {"installed": False},
                "draft_pending": 0}
        keys = [{"code": f"HMS-H-{i:08X}-9F01", "agent": "hermes",
                 "mode": "scan_covered",
                 "at": f"2026-09-0{1 + i // 1}T10:00:00Z"} for i in range(15)]
        page.refresh_probe(base, keys)
        qapp.processEvents()

        # ① 分组：只 1 个折叠栏，默认收起（body 隐藏）；工具名不再逐行重复
        headers = [w for w in page._probe_list.findChildren(QWidget)
                   if w.objectName() == "keyGroupHeader"]
        bodies = [w for w in page._probe_list.findChildren(QWidget)
                  if w.objectName() == "keyGroupBody"]
        assert len(headers) == 1 and len(bodies) == 1, \
            f"应只有 1 个 Hermes 分组，实际 {len(headers)}/{len(bodies)}"
        assert bodies[0].isHidden(), ">10 把的组默认应收起"
        labels = [l.text() for l in page._probe_list.findChildren(QLabel)]
        assert labels.count("Hermes") == 1, \
            f"工具名应只出现 1 次（收敛到分组表头），实际 {labels}"
        header_labels = [l.text() for l in headers[0].findChildren(QLabel)]
        assert any("15" in s for s in header_labels), \
            f"分组表头应带数量 chip，实际 {header_labels}"

        # ② 展开：先给 10 把预览 + 「展开全部」
        headers[0].mousePressEvent(None)
        qapp.processEvents()
        assert not bodies[0].isHidden(), "点击表头应展开"
        copy_btns = [b for b in page._probe_list.findChildren(QPushButton)
                     if b.objectName() == "keyCopyBtn"]
        assert len(copy_btns) == 10, f"预览应为 10 把，实际 {len(copy_btns)}"
        expand_all = [b for b in page._probe_list.findChildren(QPushButton)
                      if b.objectName() == "keyExpandAllBtn"]
        assert len(expand_all) == 1, "应出现「展开全部」"

        # ③ 展开全部：15 把全列出，「展开全部」按钮消失
        expand_all[0].click()
        qapp.processEvents()
        copy_btns = [b for b in page._probe_list.findChildren(QPushButton)
                     if b.objectName() == "keyCopyBtn"]
        assert len(copy_btns) == 15, f"展开全部后应为 15 把，实际 {len(copy_btns)}"
        assert not any(b.objectName() == "keyExpandAllBtn"
                       for b in page._probe_list.findChildren(QPushButton))
    finally:
        page.deleteLater()


def test_connect_probe_export_button_present(qapp, dead_api):
    """接入页“上报技能”一键导出入口存在（此前只有说明文字、用户拿不到包）。"""
    from app.gui.connect_page import ConnectPage

    page = ConnectPage(dead_api)
    try:
        btn = page._probe_export_btn
        assert btn is not None and btn.isEnabled()
        # 提示文案随按钮出现（此前只有说明、没有真的出口）
        hint = page._probe_export_hint.text()
        assert hint and "experientia-report" in hint
    finally:
        page.deleteLater()


def test_connect_models_card_resident_not_in_collapse(qapp, dead_api):
    """模型与接入 = 常驻卡（接 API/本地模型入口不能再藏）：
    不得回潮塞进高级设置折叠区；高级设置本身仍默认折叠（只剩分工具说明/注入预览）。"""
    from app.gui import i18n as _i18n
    from app.gui.connect_page import ConnectPage
    from app.gui.models_page import ModelsPage

    _i18n.load_catalog("zh")  # 前面语言测试可能改动全局目录，钉住 zh 再断言中文
    page = ConnectPage(dead_api)
    try:
        assert page.findChildren(ModelsPage), "接入页应内嵌模型页"
        assert not page._tools_body.findChildren(ModelsPage), \
            "模型卡不得收在高级设置折叠区内"
        assert "模型与接入" in page._models._head_text.text()
        assert page._tools_body.isHidden()  # 常驻提上来的同时，折叠区保持默认收起
        # 空壳护栏（事故）：内嵌子页若照旧 _wrap_scroll，布局会被
        # 搬进挂在不可见页根上的内部滚动区，外层拿到的 content 是空壳——
        # 必须断言真实控件在 content 里，而不是只查 findChildren 可达。
        assert page._models.content.layout() is not None, "模型页 content 空壳"
        assert page._models.content.isAncestorOf(page._models._head_text), \
            "模型页标题应在交给外层的 content 容器内"
        assert page._inject.content.isAncestorOf(page._inject._head_text), \
            "注入预览子页同样不得空壳"
    finally:
        page.deleteLater()


def test_connect_tool_guide_split(qapp, dead_api):
    """分工具向导（样板 C 左右分栏）：左列 10 行（8 可配 +
    2 仅官方标「免配」），右列选中工具的三步 + 可复制配置片段。护栏：
    ① _TOOL_GUIDE 与 _ONLY_OFFICIAL 对 _TOOL_DESC 严格互补（一个工具不落空）；
    ② 换选重建详情、代码内容跟选中走；③ 仅官方无代码块；
    ④ 「可复制」有复制钮；⑤ 原长句降级为补充说明不丢；
    ⑥ 语言切换整卡重建保留选中。"""
    from PySide6.QtWidgets import QLabel, QPlainTextEdit

    from app.gui import i18n as _i18n
    from app.gui.connect_page import (_CODING_TOOLS, _HARNESS_TOOLS,
                                      _ONLY_OFFICIAL, _TOOL_DESC,
                                      _TOOL_GUIDE, ConnectPage)

    _i18n.load_catalog("zh")
    all_tools = set(_CODING_TOOLS) | set(_HARNESS_TOOLS)
    assert set(_TOOL_DESC) == all_tools
    assert set(_TOOL_GUIDE) == all_tools - set(_ONLY_OFFICIAL), \
        "向导覆盖与仅官方必须严格互补，一个工具不落空"
    page = ConnectPage(dead_api)
    try:
        assert set(page._guide_btns) == all_tools
        assert page._guide_sel == _CODING_TOOLS[0]
        boxes = page._tools_card.findChildren(QPlainTextEdit)
        assert boxes and "127.0.0.1:8100" in boxes[0].toPlainText()
        # 换选配置文件工具：代码块跟着走
        page._select_guide("Codex")
        boxes = page._tools_card.findChildren(QPlainTextEdit)
        assert len(boxes) == 1 and "model_providers" in boxes[0].toPlainText()
        labels = [l.text() for l in page._tools_card.findChildren(QLabel)]
        assert "复制" in labels, "可复制承诺要真有按钮"
        # 仅官方：无代码块、清单行标「免配」、长句解释保留
        page._select_guide("Cursor")
        assert not page._tools_card.findChildren(QPlainTextEdit)
        labels = [l.text() for l in page._tools_card.findChildren(QLabel)]
        assert any("免配" in s for s in labels)
        assert any("暂不支持自定义地址" in s for s in labels), \
            "原长句要留在详情里，信息零丢失"
        # 语言切换整卡重建：选中保留、行数不变、详情重渲
        page._select_guide("Hermes")
        page._rebuild_tools_inner()
        assert page._guide_sel == "Hermes"
        assert len(page._guide_btns) == 10
        boxes = page._tools_card.findChildren(QPlainTextEdit)
        assert boxes and "OPENAI_BASE_URL" in boxes[0].toPlainText()
    finally:
        page.deleteLater()


class _ModelsApi(_DeadApi):
    """models() 返回可变路由表的桩（引导块亮灭测试用）。"""

    def __init__(self, routes):
        super().__init__(base_url="http://127.0.0.1:8101")
        self._routes = routes

    def models(self):
        return {"routes": self._routes, "distill_model": None}


def test_models_guide_toggles_with_routes(qapp):
    """未接任何模型 → 小白双路径大白话引导亮出；接上 → 自动收起不打扰。"""
    from app.gui import i18n as _i18n
    from app.gui.models_page import ModelsPage

    _i18n.load_catalog("zh")
    api = _ModelsApi([])
    page = ModelsPage(api)
    from tests.conftest import pump_until  # 模型页取数已走 fetch_and_render（异步）
    try:
        page.refresh()
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        assert not page._guide_box.isHidden(), "没接模型时应显示引导"
        texts = [lbl.text() for lbl in page._guide_lbls]
        assert any("Ollama" in s for s in texts), texts
        assert any("云端 API" in s for s in texts), texts
        api._routes = [{"name": "n1", "type": "cloud", "endpoint": "http://x/v1",
                        "model": "m", "is_default": True, "is_distill": False,
                        "key_source": "keyring"}]
        page.refresh()
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        assert page._guide_box.isHidden(), "接上模型后引导应收起"
    finally:
        page.deleteLater()


def test_models_add_dialog_type_hint(qapp, dead_api, monkeypatch):
    """添加模型弹窗的类型解释行随选随变：默认云端提 API Key；切本地模型改提
    Ollama/LM Studio 且藏起 Key 输入（小白靠解释行决定选哪个）。"""
    from PySide6.QtWidgets import QComboBox, QDialog, QLabel, QLineEdit

    from app.gui.models_page import ModelsPage

    page = ModelsPage(dead_api)
    try:
        captured: dict = {}
        monkeypatch.setattr(QDialog, "exec",
                            lambda self: captured.update(d=self) or 0)
        page._open_add()
        dlg = captured["d"]
        combo = next(c for c in dlg.findChildren(QComboBox))
        pw = next(e for e in dlg.findChildren(QLineEdit)
                  if e.echoMode() == QLineEdit.EchoMode.Password)
        hint_texts = lambda: " ".join(l.text() for l in dlg.findChildren(QLabel))
        assert "DeepSeek" in hint_texts(), "云端类型应有 API Key 大白话解释"
        assert not pw.isHidden(), "云端类型应显示 Key 输入"
        combo.setCurrentIndex(0)  # local
        qapp.processEvents()
        assert "Ollama" in hint_texts(), "本地类型应解释为 Ollama/LM Studio"
        assert pw.isHidden(), "本地类型不需要 Key"
    finally:
        page.deleteLater()


def test_connect_tools_collapse_rotation(qapp, dead_api, monkeypatch):
    """折叠头：箭头随展开/收起旋转（reduced-motion 下直接落目标角，确定性）。"""
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")  # 关动画 → 同步断言
    from app.gui.connect_page import ConnectPage

    page = ConnectPage(dead_api)
    try:
        icon = page._expand_icon
        body = page._tools_body
        # 页未 show（offscreen），isVisible() 恒 False；用 isHidden() 断言显隐
        assert not page._tools_expanded and body.isHidden()  # 默认折叠
        assert icon.rotation == 0.0   # chevron-down 0°
        page._toggle_tools()          # 展开
        assert page._tools_expanded and not body.isHidden()
        assert icon.rotation == 180.0  # 转 180° 即 chevron-up
        page._toggle_tools()          # 折叠
        assert not page._tools_expanded and body.isHidden()
        assert icon.rotation == 0.0
    finally:
        page.deleteLater()


def test_first_launch_shows_onboarding_when_not_onboarded(qapp, dead_api,
                                                          monkeypatch):
    """首次启动：config.onboarded 为假 → 进欢迎页而非首页（回归护栏）。"""
    from app.gui.main_window import MainWindow
    from app.gui.onboarding import OnboardingPage

    store = _Store()
    import app.gui.main_window as mw

    win = MainWindow(store)  # _DeadApi.config 抛错 → onboarded 兜底 True → 首页
    try:
        assert win._stack.currentWidget() is win._pages["home"]
    finally:
        _close(win)

    # 正常未 onboarding 配置 → 欢迎页（页面 API 走 _DeadApi 优雅降级）
    class _FakeCfgApi(_DeadApi):
        def config(self):
            return {"onboarded": False}

    orig = mw.CachedApi
    mw.CachedApi = lambda *a, **k: _FakeCfgApi(base_url="http://127.0.0.1:8101")
    # MainWindow 取启动配置前会先用真实 socket 探测 8101 有没有人在听（省掉引擎
    # 未起时主线程白等的 2s），没在听就直接兜底进首页、根本不走下面的 FakeApi。
    # 探测结果取决于本机守护进程开没开——红绿随宿主机状态漂移，桩掉以保证确定性。
    monkeypatch.setattr(mw, "local_api_listening", lambda base: True)
    try:
        win2 = MainWindow(store)
        try:
            cur = win2._stack.currentWidget()
            assert isinstance(cur, OnboardingPage)
            # 懒加载：启动只建首页，加上欢迎页 = 2 页（不再 7 页全建）
            assert win2._stack.count() == 2
        finally:
            _close(win2)
    finally:
        mw.CachedApi = orig


# ----------  回归 ----------

class _SettingsApi(_DeadApi):
    """设置页数据桩：status/config 可用 + 通知列表与已读打点。"""

    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8101")
        self.read_calls = 0

    def status(self):
        return {"agents": {}, "data_dir": "D:/data", "data_dir_fallback": False}

    def config(self):
        return {}

    def notifications(self, unread: bool = False, limit: int = 50):
        return {"items": [{"id": "n1", "type": "method_update", "title": "t",
                           "body": "b", "ts": "2026-09-19T10:00:00Z",
                           "read": False}]}

    def notifications_read(self, ids=None):
        self.read_calls += 1
        return {"changed": 1}


def test_settings_notifications_block_marks_read(qapp):
    """M20：通知卡内「最近通知」列表渲染；进入设置页即调 notifications_read
    清未读（历史通知有处可看、未读不再只增不减）。"""
    from PySide6.QtWidgets import QLabel

    from app.gui.settings_page import SettingsPage

    api = _SettingsApi()
    page = SettingsPage(api)
    try:
        page.refresh()
        from tests.conftest import pump_until  # 设置页取数已走 fetch_and_render（异步）
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        qapp.processEvents()
        assert api.read_calls == 1, "进入设置页应标记通知已读一次"
        texts = [l.text() for l in page._notif_box.findChildren(QLabel)]
        assert any("方法动态" in x for x in texts), f"通知列表未渲染: {texts}"
    finally:
        page.deleteLater()


def test_settings_notification_row_click_navigates(qapp, monkeypatch):
    """通知行可点击跳 target 对应页（手型光标）；
    target 为空/未知 → 行不挂点击（普通 QWidget、箭头光标）。"""
    from PySide6.QtCore import Qt

    from app.gui import settings_page as sp
    from app.gui.settings_page import SettingsPage

    class _Api(_SettingsApi):
        def notifications(self, unread: bool = False, limit: int = 50):
            return {"items": [
                {"id": "n1", "type": "method_update", "title": "t", "body": "b",
                 "ts": "2026-09-19T10:00:00Z", "target": "growth", "read": False},
                {"id": "n2", "type": "system_notice", "title": "x", "body": "",
                 "ts": "2026-09-19T11:00:00Z", "target": "", "read": False},
                {"id": "n3", "type": "system_notice", "title": "y", "body": "",
                 "ts": "2026-09-19T12:00:00Z", "target": "nowhere", "read": False},
            ]}

    page = SettingsPage(_Api())
    try:
        page.refresh()
        from tests.conftest import pump_until  # 设置页取数已走 fetch_and_render（异步）
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        qapp.processEvents()
        rows = page._notif_rows
        assert [r[1] for r in rows] == ["growth", None, None]
        # 可跳行手型光标；不可跳行箭头
        from PySide6.QtWidgets import QWidget
        assert rows[0][0].cursor().shape() == Qt.PointingHandCursor
        assert isinstance(rows[1][0], QWidget) and not isinstance(rows[1][0], sp._NotifRow)
        assert not isinstance(rows[2][0], sp._NotifRow)
        # 点击 → 经 go 跳页（旧名映射在主窗 _select_page 内，此处只验转发）
        got: list[str] = []
        monkeypatch.setattr(page, "go", lambda name: got.append(name))
        rows[0][0].clicked.emit()
        assert got == ["growth"]
    finally:
        page.deleteLater()


def test_models_add_dialog_inline_validation(qapp, dead_api, monkeypatch):
    """L13：名称留空提交 → 对话框内联红字提示、不调 API、对话框不通过。"""
    from PySide6.QtWidgets import QDialog, QLabel, QPushButton

    from app.gui.models_page import ModelsPage

    page = ModelsPage(dead_api)
    try:
        captured: dict = {}
        monkeypatch.setattr(QDialog, "exec",
                            lambda self: captured.update(d=self) or 0)
        page._open_add()
        dlg = captured["d"]
        saved: list = []
        save_btn = None
        for b in dlg.findChildren(QPushButton):
            lab = [l.text() for l in b.findChildren(QLabel)]
            if b.text() == "保存" or "保存" in lab:
                save_btn = b
        assert save_btn is not None, "找不到「保存」按钮"
        save_btn.click()
        qapp.processEvents()
        texts = [l.text() for l in dlg.findChildren(QLabel)]
        assert any("请填写名称" in x for x in texts), \
            f"应内联提示必填名称: {texts}"
        assert not saved
    finally:
        page.deleteLater()




class _GovApi(_DeadApi):
    """返回治理条目的 stub：refutation 有数据，restore 记录调用。"""

    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8101")
        self.restored: list[tuple[str, str, str]] = []

    def refutation(self):
        return {"items": [
            {"trunk": "经验", "category": "投标",
             "id": "i1", "text": "先估算成本再报价",
             "corroborated": 1, "refuted": 3,
             "restricted": 1, "excluded": 0},
            {"trunk": "方法", "category": "调研",
             "id": "i2", "text": "先看竞品再写",
             "corroborated": 0, "refuted": 5,
             "restricted": 0, "excluded": 1},
        ]}

    def refutation_restore(self, trunk, category, item_id):
        self.restored.append((trunk, category, item_id))
        return {"restored": True}


def test_refutation_page_empty_state(qapp, dead_api):
    """临界：无治理项（API 报错也降级为空态）不崩溃。"""
    from app.gui.refutation import RefutationPage

    page = RefutationPage(dead_api)
    from tests.conftest import pump_until  # 治理页取数已走 fetch_and_render（异步）
    try:
        page.refresh()
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        # 异常降级为空态：只有 empty_state 一个直系 widget
        assert page._groups.count() == 1
        assert page._groups.itemAt(0).widget() is not None
    finally:
        page.deleteLater()


def test_refutation_page_governed_render(qapp):
    """治理渲染：受限/移出两组各自出卡（取数异步，泵事件等渲染落地）。"""
    from app.gui.refutation import RefutationPage

    page = RefutationPage(_GovApi())
    from tests.conftest import pump_until  # 取数已走 fetch_and_render（异步）
    try:
        page.refresh()
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        # 受限段头 + i1 卡 + 移出段头 + i2 卡 = 4 个直系 widget
        assert page._groups.count() == 4
    finally:
        page.deleteLater()


def test_refutation_page_restore_calls_api(qapp, monkeypatch):
    """恢复动作：触发后端 restore 并回到刷新（render 同步，restore 注入将
    run_async 压成同步回调，避免 offscreen 下 QThread 竞态）。"""
    from PySide6.QtWidgets import QPushButton, QVBoxLayout

    from app.gui.refutation import RefutationPage

    api = _GovApi()
    page = RefutationPage(api)
    try:
        page._groups = QVBoxLayout()  # 隔离：restore 的 refresh_all 独立重绘
        page.run_async = lambda fn, on_done=None, on_error=None: on_done(fn())
        btn = QPushButton("恢复使用")
        page._restore(btn, {"trunk": "方法", "category": "调研", "id": "i2"})
        assert api.restored == [("方法", "调研", "i2")]  # 后端收到恢复请求
    finally:
        page.deleteLater()

def test_theme_switch_10_cycles_no_crash(qapp, dead_api, monkeypatch):
    """主题快速切换 10 次（亮/暗交替）——原 _rebuild_rail deleteLater 竞态回归护栏。"""
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")  # 关动画 → 同步落角
    win = _build_window()
    try:
        for i in range(10):
            win.switch_theme("dark" if i % 2 else "light")
            qapp.processEvents()  # 冲刷 singleShot(_restyle_rail)
    finally:
        _close(win)


def test_theme_switch_rebuilds_visited_pages(qapp, dead_api, monkeypatch):
    """深色彻底化：已访问页面（含设置/首页）切主题后换成新色板构建的新实例。

    页面内联 QSS 的 token 在构建时冻结，不重建则残留亮色；护栏断言实例被替换、
    无崩溃、旧实例可安全延迟删除、当前页仍是有效页面。
    """
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    win = _build_window()
    try:
        for name in ("home", "mine", "growth", "settings"):
            win._select_page(name)
            qapp.processEvents()
        olds = [(n, p) for n, p in win._pages.items()]
        win.switch_theme("dark")
        qapp.processEvents()
        qapp.processEvents()  # 冲刷主题收尾 + 删除旧实例
        assert set(win._pages) == {n for n, _p in olds}
        for name, old in olds:
            new_page = win._pages[name]
            assert new_page is not old, f"{name} 主题后未重建（残留亮色 token）"
            assert new_page.parent() is not None or new_page is win._stack.currentWidget()
        assert win._stack.currentWidget() in win._pages.values()
        assert win._pages["settings"] is not win._pages["home"]
    finally:
        _close(win)


def test_theme_switch_retints_chrome_text(qapp, dead_api, monkeypatch):
    """深色遗漏护栏：导航按钮文字/状态栏文字也随色板换色（txt() 内联冻结，
    不重刷会留浅色旧 token 在暗底上不可读）。"""
    from app.gui.theme import C

    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    win = _build_window()
    try:
        win.switch_theme("dark")
        qapp.processEvents()
        qapp.processEvents()
        assert C.current_mode() == "dark"
        # 引擎离线时页面刷新失败会把状态行涂成 err 红，先复位再验证色板已接入
        win._restyle_status_label()
        assert C.ink_500 in win._status_label.styleSheet(), \
            "状态栏文字色未随深色重刷"
        for btn in win._nav_buttons:
            if getattr(btn, "_label", None) is None:
                continue
            # 胶囊浮起方案：未选文字从 ink_500 抬到 ink_700（设计）
            expect = C.brand_700 if btn.isChecked() else C.ink_700
            assert expect in btn._label.styleSheet(), \
                f"导航按钮 {btn._text_key} 文字色未随深色重刷"
    finally:
        _close(win)


def test_language_switch_5_cycles_no_crash(qapp, dead_api, monkeypatch):
    """语言快速切换 5 语（原地 retranslateUi，不重建 widget）。"""
    from app.gui.main_window import MainWindow

    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    store = _Store()
    win = MainWindow(store)
    try:
        for lang in ("en", "ja", "de", "fr", "ko"):
            store.cfg["locale"] = lang  # 模拟配置已持久化
            win.switch_language(lang)
            qapp.processEvents()
            assert all(len(b.label_text()) > 0 for b in win._nav_buttons)
    finally:
        _close(win)


def test_language_switch_rebuilds_connect_export(qapp, dead_api, monkeypatch):
    """接入/导出页切语言后整体重建：内嵌子页（Models/Inject/Skill）不入主窗 _pages，
    原地 retranslateUi 覆盖不到，切 en 后不得再滞留中文（回归护栏）。"""
    import re

    cjk = re.compile(r"[\u4e00-\u9fff]")
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    win = _build_window()
    try:
        for name in ("connect", "export"):
            win._select_page(name)
            qapp.processEvents()
        old_connect = win._pages["connect"]
        old_export = win._pages["export"]
        old_model_head = old_connect._models._head_text.text()
        assert cjk.search(old_model_head), "默认 zh 的模型页标题应含中文"

        win.switch_language("en")
        qapp.processEvents()
        qapp.processEvents()  # 冲刷语言重建 + 删除旧实例

        new_connect = win._pages["connect"]
        assert new_connect is not old_connect, "接入页语言切换后未重建"
        assert win._pages["export"] is not old_export, "导出页语言切换后未重建"
        model_head = new_connect._models._head_text.text()
        assert model_head and not cjk.search(model_head), \
            f"切 en 后模型区仍滞留中文: {model_head}"
        inject_head = new_connect._inject._head_text.text()
        assert inject_head and not cjk.search(inject_head), \
            f"切 en 后注入预览仍滞留中文: {inject_head}"
        assert win._stack.currentWidget() in win._pages.values()
    finally:
        from app.gui import i18n as _i18n
        _i18n.load_catalog("zh")  # 恢复默认目录，避免污染后续测试
        _close(win)


def test_splash_pixmap_generates_in_both_modes(qapp):
    """启动闪屏资产：明/暗色板下都能出非空位图（体验优化回归护栏）。"""
    from app.gui.qt_splash import SPLASH_CYCLE, make_splash_pixmap
    from app.gui.theme import C

    for mode in ("light", "dark"):
        C.set_mode(mode)
        pm = make_splash_pixmap()
        assert not pm.isNull()
        assert pm.size().width() == 480 and pm.size().height() == 320
    # 表情包轮播帧全部可渲染（动画不缺素材）
    for name in SPLASH_CYCLE:
        pm = make_splash_pixmap(name)
        assert not pm.isNull(), f"闪屏表情帧缺失: {name}"
    C.set_mode("light")


def test_rapid_page_navigation_20_rounds_no_crash(qapp, dead_api):
    """快速连续切页 20 轮（导航双触发 + 懒加载 + 轮询计时器共存的历史崩溃场景）。"""
    from app.gui.main_window import PAGES

    win = _build_window()
    try:
        for _ in range(20):
            for key in PAGES:
                win._select_page(key)
                assert win._stack.currentWidget() is win._pages[key]
    finally:
        _close(win)


# ---------- SYS-5：加载失败不再静默/误导 ----------

def test_connect_hooks_failure_not_misleading(qapp, dead_api):
    """引擎不可用：hook 状态区显示"配置失败"而非假装"未配置"。"""
    from app.gui.connect_page import ConnectPage

    page = ConnectPage(dead_api)
    try:
        page.refresh_hooks()
        qapp.processEvents()
        assert page._last_error, "hook 状态读取失败必须留痕"
        assert "未配置" not in page._hook_status_txt.text()
        assert "配置失败" in page._hook_status_txt.text()
    finally:
        page.deleteLater()


def test_connect_plugin_generate_failure_shown(qapp, dead_api):
    """C-2b：引擎不可用时点"插件包"→ 显示生成失败（非静默）。"""
    import time

    from app.gui.connect_page import ConnectPage

    page = ConnectPage(dead_api)
    try:
        page.do_plugin_generate()
        deadline = time.time() + 3.0
        while time.time() < deadline and "生成失败" not in page._hook_msg.text():
            qapp.processEvents()
            time.sleep(0.02)
        assert "生成失败" in page._hook_msg.text()
    finally:
        page.deleteLater()


# ---------- Hooks 页：数据填充渲染（防"有数据时崩"回归——dead_api 只覆盖降级路径） ----------

class _HooksRichApi(_DeadApi):
    """返回真实形状的 overview/rules/templates，驱动 Hooks 页各渲染分支。"""

    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8101")

    def hooks_admin_overview(self):
        return {
            "hermes": {"installed": True, "exists": True, "kind": "json_hooks",
                       "writable": True, "path": "~/.hermes/hooks.json",
                       "entries": [{"id": "h1", "event": "PreToolUse",
                                    "text": "跑测试", "enabled": True}]},
            "cursor": {"installed": False, "exists": True, "kind": "json_hooks",
                       "writable": True, "path": "~/.cursor/hooks.json", "entries": []},
            "claude-code": {"installed": False, "exists": True, "kind": "toml",
                            "writable": False, "path": "~/.claude/settings.toml",
                            "entries": [{"id": "c1", "event": "PreToolUse",
                                         "text": "ro", "enabled": True}]},
            "codex": {"installed": False, "exists": False, "kind": "none",
                      "writable": False, "path": "", "entries": []},
        }

    def models(self):
        return {"routes": {"chat": "ok"}}

    def rules(self):
        return {"items": [
            {"id": "r1", "name": "公文格式", "enabled": True, "trigger": "smart",
             "text": "输出用公文格式", "agents": ["*"], "conflict": False,
             "scope": "all", "hit_count": 42, "hit_7d": 5,
             "last_hit": "2026-09-07 10:00", "stale": False,
             "template_id": None, "priority": "p2"},
            {"id": "r2", "name": "部署前检查", "enabled": False, "trigger": "manual",
             "keyword": "部署", "text": "部署前跑完整测试", "agents": ["hermes"],
             "conflict": False, "scope": "glob", "globs": ["src/**/*.py"],
             "hit_count": 0, "hit_7d": 0, "last_hit": None, "stale": True,
             "template_id": "tpl1", "priority": "p1"},
            {"id": "r3", "name": "红线禁删库", "enabled": True, "trigger": "hard-hook",
             "text": "绝不删库", "agents": ["*"], "conflict": True, "scope": "all",
             "hit_count": 3, "hit_7d": 1, "last_hit": "2026-09-05 08:00",
             "stale": False, "template_id": None, "priority": "p0"},
        ], "budget_used": 395, "budget": 400, "stale_days": 30}

    def rule_agents(self):
        return {"agents": ["hermes", "cursor", "claude-code"]}

    def templates(self, lang):
        return {"categories": [
            {"label_key": "安全与合规", "templates": [
                {"id": "tpl1", "name": "部署前检查", "description": "部署前跑测试",
                 "keywords": ["部署"], "tags": ["工作流与流程"], "priority": "p1",
                 "trigger": "manual", "text": "部署前跑完整测试"},
                {"id": "tpl2", "name": "禁删库", "description": "红线",
                 "keywords": ["drop"], "tags": ["安全与合规"], "priority": "p0",
                 "trigger": "hard-hook", "text": "绝不删库"}]},
        ]}

    def config(self):
        return {"hook_stale_days": 30}

    def update_config(self, d):
        return {}

    def hooks_admin(self, agent):
        return {"entries": self.hooks_admin_overview().get(agent, {})
                .get("entries", [])}


def test_hooks_page_data_rich_render(qapp):
    """有数据时全页渲染不崩（区一各工具态 / 横幅 / 规则卡 / 预算 / 信号 / 模板 / 按工具视图）。"""
    from app.gui.hooks_page import HooksPage

    page = HooksPage(_HooksRichApi())
    try:
        page.resize(1200, 800)
        page.refresh()
        # 整页取数在后台线程，processEvents 一次不够——泵到收尾
        from tests.conftest import pump_until
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        qapp.processEvents()
        # 区一：4 个工具都应生成行（含 codex 的纯文本行）
        assert len(page._agent_row_bodies) >= 3, "工具行未渲染"
        # 已接入 → chip 出现；cursor 可写未接入 → 横幅 + offer
        assert page._hooks_offer, "可接入工具未触发横幅"
        # 区二：3 张规则卡
        assert len(page._rules_cache) == 3
        assert page._list_lay.count() == 3, "规则卡数量不符"
        # 区三：模板类目 + 列表
        assert len(page._tpl_holder) == 1
        assert page._tpl_list_lay.count() >= 1, "模板未渲染"
        # 预算超限 + 冲突 → warn（sweat 吉祥物分支）
        assert page._hooks_warn, "预算超限未触发 warn"
        # 切按工具视图（工具规则卡 + 三档操作）
        page._view_state = "tools"
        page._tool_state["agent"] = "hermes"
        page._refresh_tools()
        qapp.processEvents()
        assert page._tool_list_lay.count() >= 1, "按工具视图未渲染"
        # 语言重译不崩
        page.retranslateUi()
        qapp.processEvents()
    finally:
        page.deleteLater()


# ---------- 经验库页：同 task 多做法聚合成一张卡（防重复标题回归） ----------
#
# 用户真实场景：modelscope 登录状态检测这一 task 有 2 条经验（subprocess.run
# 方案 + os.popen 方案），旧实现一条经验出一张卡、卡标题取「类别 - task」，
# 于是渲出两张同标题卡、第二做法被埋。修复：按 (类别, task) 聚合，一 task 一卡，
# 卡内逐行列出全部不同做法。


def test_group_by_task_merges_same_task():
    """纯逻辑：同 (类别, task) 的多条经验（不同做法）收为一组，组序=首现序。"""
    from app.gui.experiences import _group_by_task

    items = [
        {"category": "模型", "task": "modelscope 登录状态检测", "action": "subprocess.run", "id": "a1"},
        {"category": "模型", "task": "modelscope 登录状态检测", "action": "os.popen", "id": "a2"},
        {"category": "基础设施", "task": "修端口", "action": "改端口", "id": "b1"},
    ]
    groups = _group_by_task(items)
    assert len(groups) == 2, f"应聚合为 2 组（同 task 合并），实际 {len(groups)}"
    # 同 task 两条合并、保序；不同 task 单独成组
    assert [r["id"] for r in groups[0]] == ["a1", "a2"], groups[0]
    assert [r["id"] for r in groups[1]] == ["b1"], groups[1]
    # 组顺序 = 各 task 首次出现顺序
    assert groups[0][0]["task"] == "modelscope 登录状态检测"
    assert groups[1][0]["task"] == "修端口"
    # 空输入 → 空输出
    assert _group_by_task([]) == []


class _ExperiencesApi(_DeadApi):
    """返回同 task 的多条经验（不同做法）+ 一条独立经验，驱动经验库聚合渲染。"""

    ITEMS = [
        {"id": "e1", "category": "模型", "task": "modelscope 登录状态检测（无浏览器环境）",
         "agent": "hermes", "model": "Qwen3-8B", "ts": "2026-09-04T10:00:00",
         "trunk": "模型", "state": "curl 直接访问超时",
         "action": "subprocess.run 调 curl --head 拿状态码", "outcome": "拿到 200",
         "distilled": True, "G": 0.8},
        {"id": "e2", "category": "模型", "task": "modelscope 登录状态检测（无浏览器环境）",
         "agent": "hermes", "model": "Qwen3-8B", "ts": "2026-09-04T11:00:00",
         "trunk": "模型", "state": "",
         "action": "os.popen 调 curl（兼容老脚本）", "outcome": "",
         "distilled": False, "G": 0.6},
        {"id": "e3", "category": "基础设施", "task": "llama-server 端口被占用",
         "agent": "cursor", "model": "Qwen3-8B", "ts": "2026-09-03T09:00:00",
         "trunk": "基础设施", "state": "8080 被占用", "action": "换端口 8081",
         "outcome": "启动成功", "distilled": True, "G": 0.7},
    ]

    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8101")
        self.items = [dict(x) for x in self.ITEMS]

    def experiences(self, trunk=None, category=None, agent=None, q=None,
                    include_distilled=True, limit=300):
        items = [x for x in self.items if not x.get("dismissed")]
        return {"items": items, "count": len(items)}

    def experience_drafts(self, status="pending"):
        return {"items": []}

    def experience_categories(self):
        return {"categories": sorted({str(x.get("category") or "未分类")
                                      for x in self.items})}

    def _patch(self, exp_id, **kw):
        for x in self.items:
            if x.get("id") == exp_id:
                x.update(kw)
                return x
        return None

    def categorize_experience(self, exp_id, category, trunk=None):
        self._patch(exp_id, category=category)
        return {"message": "ok"}

    def dismiss_experience(self, exp_id):
        self._patch(exp_id, dismissed=True)
        return {"message": "ok"}

    def restore_experience(self, exp_id):
        self._patch(exp_id, dismissed=False)
        return {"message": "ok"}


def test_experiences_same_task_one_card(qapp):
    """回归：同 task 的多条经验聚合为一张卡，不再撞出重复标题、第二做法可见。

    3 条经验（2 条同 task + 1 条独立 task）→ 2 张卡（旧实现逐条渲 3 张、
    同 task 的两张标题完全相同）。合并卡内两种做法都逐行列出。"""
    from PySide6.QtWidgets import QLabel

    from app.gui.experiences import ExperiencesPage

    page = ExperiencesPage(_ExperiencesApi())
    try:
        page.resize(1200, 800)
        page.refresh()
        from tests.conftest import pump_until  # 经验库取数已走 fetch_and_render（异步）
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        qapp.processEvents()
        # 2 个 (类别, task) → 2 张卡（旧实现会渲 3 张）
        assert page._list_layout.count() == 2, \
            f"卡片数应为 2（同 task 合并），实际 {page._list_layout.count()}"
        # 第一张 = 合并的 modelscope 卡：两种做法都可见
        card = page._list_layout.itemAt(0).widget()
        joined = "\n".join(l.text() for l in card.findChildren(QLabel))
        assert "subprocess.run" in joined, f"做法一缺失: {joined}"
        assert "os.popen" in joined, f"做法二缺失: {joined}"
        # 标题只出现一次（不再重复）
        titles = [l.text() for l in card.findChildren(QLabel)
                  if "modelscope" in l.text()]
        assert len(titles) == 1, f"标题重复: {titles}"
        # 语言重译不崩（分组卡走 t() 键路径）
        page.retranslateUi()
        qapp.processEvents()
    finally:
        page.deleteLater()


def test_experiences_dismiss_undo_surgical(qapp):
    """回归：不采纳 → 手术式移除不崩，撤销回位，不塌成"页中间某处"。

    2 张卡开始；对首张卡（modelscope 组 e1,e2）不采纳 → 该卡被 takeAt 移除
    并在原位插一条撤销条（count 仍 2）；点撤销 → 卡回位、撤销条消失。"""
    from app.gui.experiences import ExperiencesPage

    api = _ExperiencesApi()
    page = ExperiencesPage(api)
    try:
        page.resize(1200, 800)
        page.refresh()
        from tests.conftest import pump_until  # 经验库取数已走 fetch_and_render（异步）
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        qapp.processEvents()
        assert page._list_layout.count() == 2
        card0 = page._list_layout.itemAt(0).widget()
        # 整组 ids（card0 = modelscope 合并卡）
        ids = ["e1", "e2"]
        page._dismiss_group(card0, ids, "modelscope 登录")
        qapp.processEvents()
        # 手术移除：1 卡 + 1 撤销条 = 2；且在 (0,2) 之间，撤销条占原位
        assert page._list_layout.count() == 2, \
            f"移除后应 1卡+1撤销条=2，实际 {page._list_layout.count()}"
        assert page._pending_undo, "应有 1 条待撤销"
        assert card0.isHidden(), "被移出的卡应隐藏（保留 alive 供撤销）"
        # 数据层：e1/e2 已 dismissed
        assert all(x.get("dismissed") for x in api.items if x["id"] in ids)
        # 撤销 → 卡回位、撤销条消失
        page._undo_dismiss(0)
        qapp.processEvents()
        assert page._list_layout.count() == 2
        assert not page._pending_undo, "撤销后不应再有待撤销"
        assert not card0.isHidden(), "撤销后卡应可见"
        assert all(not x.get("dismissed") for x in api.items if x["id"] in ids)
        # 再走一遍不采纳 + 3 秒过期路径（不触发撤销），验证过期释放不崩
        page._dismiss_group(card0, ids, "x")
        qapp.processEvents()
        page._expire_undo(1)
        qapp.processEvents()
        assert not page._pending_undo
    finally:
        page.deleteLater()


def test_experiences_categorize_rebuild_no_crash(qapp):
    """回归：归类 → 整表重建不崩且分组正确（连带数据层 category 变更）。"""
    from app.gui.experiences import ExperiencesPage

    api = _ExperiencesApi()
    page = ExperiencesPage(api)
    try:
        page.resize(1200, 800)
        page.refresh()
        from tests.conftest import pump_until  # 经验库取数已走 fetch_and_render（异步）
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        qapp.processEvents()
        card0 = page._list_layout.itemAt(0).widget()
        page._categorize_group(card0, ["e1", "e2"], "测试类", "x")
        # 归类走 _rebuild_preserve_scroll → refresh()（异步整表重建），需再等一次
        assert pump_until(lambda: not page._fetches, qapp), "重建取数未收尾"
        qapp.processEvents()
        # e3(基础设施/llama) 一张 + 测试类(modelscope) 一张 = 2
        assert page._list_layout.count() == 2, \
            f"归类后应 2 张，实际 {page._list_layout.count()}"
        assert all(x.get("category") == "测试类" for x in api.items
                   if x["id"] in ("e1", "e2"))
    finally:
        page.deleteLater()


class _SkillApi(_DeadApi):
    """技能导出页数据桩：131 条经验（130 同组 + 1 跨组），触发分页。"""

    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8101")

    def _request(self, method, path, json=None, params=None, timeout=None):
        raise LocalApiError(0, "本地 API 未连接")

    def experiences(self, trunk=None, category=None, agent=None, q=None,
                    include_distilled=True, limit=300):
        items = [
            {"id": f"e{i}", "task": f"样本经验 {i} 的任务标题", "trunk": "研发",
             "category": "工程实践", "agent": "workbuddy", "G": 0.6,
             "ts": "2026-09-01T08:00:00Z", "action": "最小可运行版本优先"}
            for i in range(130)
        ]
        items.append({"id": "cross", "task": "跨范围经验", "trunk": "产品",
                      "category": "决策", "agent": "claude", "G": 0.9,
                      "ts": "2026-09-02T08:00:00Z"})
        return {"items": items[:limit]}

    def skills(self):
        return {"items": []}


def test_skill_export_pagination_and_scope_count(qapp):
    """技能导出：分页加载更多、加载后按钮消失、筛选态计数口径、清空按钮。"""
    from PySide6.QtWidgets import QPushButton

    from app.gui.skill_organize import SkillOrganizePage

    page = SkillOrganizePage(_SkillApi())
    try:
        page.resize(880, 900)
        page.refresh()
        from tests.conftest import pump_until  # 整理页取数已走 fetch_and_render（异步）
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        qapp.processEvents()

        def layout_btn_texts():
            out = []
            for i in range(page._list_lay.count()):
                w = page._list_lay.itemAt(i).widget()
                if isinstance(w, QPushButton):
                    out.append(w.text())
                elif w is not None:
                    for b in w.findChildren(QPushButton):
                        out.append(b.text())
            return out

        # 1) 131 条 → 渲染上限 100 → 「加载更多（还有 31 条）」
        more_texts = [x for x in layout_btn_texts() if "加载更多" in x]
        assert more_texts and "还有 31 条" in more_texts[0], \
            f"分页按钮缺失或剩余数错：{more_texts}"

        # 2) 点击 → 上限 200，按钮消失
        more = [b for b in page._list_box.findChildren(QPushButton)
                if "加载更多" in b.text()][0]
        more.click()
        for _ in range(4):
            qapp.processEvents()
        assert page._page_size == 200
        assert not any("加载更多" in x for x in layout_btn_texts())

        # 3) 未筛选：勾两条（不同类）→ 简单口径
        page._check({"id": "e0", "trunk": "研发", "category": "工程实践"}, True)
        page._check({"id": "cross", "trunk": "产品", "category": "决策"}, True)
        qapp.processEvents()
        assert page._count_line.text() == "已选 2 条（跨 2 个类别）"
        assert not page._clear_btn.isHidden(), "有选中时清空按钮应显示"

        # 4) 切到「研发/工程实践」→ 范围口径：2 选中，范围内 1
        page.cat_sel.setCurrentIndex(1)
        qapp.processEvents()
        assert "已选 2 条，范围内 1 条" in page._count_line.text()

        # 5) 清空 → 归零、按钮隐藏
        page._clear_btn.click()
        qapp.processEvents()
        assert not page.selected
        assert page._clear_btn.isHidden()
    finally:
        page.deleteLater()


def test_skill_confirm_dialog_builds(qapp, monkeypatch):
    """导出前确认弹层可构建且返回确认结果（monkeypatch 掉模态 exec）。"""
    from app.gui import qt_dialogs

    calls = []
    monkeypatch.setattr(qt_dialogs.QDialog, "exec", lambda self: (
        calls.append(self), qt_dialogs.QDialog.DialogCode.Accepted)[1])

    ok = qt_dialogs.confirm_skill_export(
        None, scope=None,
        items=[{"id": "a", "trunk": "研发", "category": "工程实践"},
               {"id": "b", "trunk": "产品", "category": "决策"}],
        name="测试 Skill", description="一句话", out_of_scope=1)
    assert ok is True
    assert calls and calls[0].windowTitle() == "导出 Skill"


def test_skill_export_groups_collapse_default(qapp, monkeypatch):
    """类别多时默认只展开条数前 3 组，其余折叠为一行组头；
    折叠组头保留「导出 Skill」一键；点击组头展开/收起并记住状态。"""
    from PySide6.QtWidgets import QPushButton

    from app.gui.skill_organize import SkillOrganizePage
    from app.gui.qt_widgets import RotatingIcon

    page = SkillOrganizePage(_SkillApi())
    try:
        items: list[dict] = []
        for trunk, cat, n in (("研发", "工程实践", 40), ("产品", "决策", 30),
                              ("设计", "规范", 20), ("其他", "未分类", 10)):
            items += [{"id": f"x{trunk}{cat}{j}", "trunk": trunk,
                       "category": cat, "agent": "w", "G": 0.6,
                       "ts": "2026-09-01T08:00:00Z"} for j in range(n)]
        monkeypatch.setattr(page, "_exps_filtered", lambda q="": items)

        def laid() -> list:
            return [page._list_lay.itemAt(i).widget()
                    for i in range(page._list_lay.count())]

        def rows() -> list:
            return [w for w in laid() if w.objectName() == "skillExpRow"]

        def headers() -> list:
            return [w for w in laid() if w.objectName() == "skillGroupHeader"]

        page.refresh()
        from tests.conftest import pump_until  # 整理页取数已走 fetch_and_render（异步）
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        qapp.processEvents()

        # 默认展开前 3 大组（40+30+20=90 条），最小一组（10 条）折叠不建条目
        assert len(rows()) == 90, len(rows())
        assert len(headers()) == 4
        assert page._collapsed == set()  # 未手动碰过

        # 折叠组头仍保留导出按钮：4 个组头各一个「导出 Skill」
        n_btn = sum(1 for h in headers()
                    for b in h.findChildren(QPushButton) if "导出 Skill" in b.text())
        assert n_btn == 4

        # chevron 表达展开态：1 个折叠组朝下（0°），3 个展开组朝上（180°）
        rot = [h.findChild(RotatingIcon).rotation for h in headers()]
        assert rot.count(0) == 1 and rot.count(180) == 3, rot

        # 点击最小一组 → 展开，条目 90+10=100，状态记住
        page._toggle_group(("其他", "未分类"))
        qapp.processEvents()
        assert ("其他", "未分类") in page._touched
        assert ("其他", "未分类") not in page._collapsed
        assert len(rows()) == 100

        # 点击 40 条大组 → 折叠，条目 100-40=60，状态记住（不因重建重置）
        page._toggle_group(("研发", "工程实践"))
        qapp.processEvents()
        assert ("研发", "工程实践") in page._collapsed
        assert len(rows()) == 60, len(rows())
        page._toggle_group(("研发", "工程实践"))  # 再展开
        page._toggle_group(("其他", "未分类"))    # 再折叠
        qapp.processEvents()
        assert len(rows()) == 90  # 回到 40+30+20
    finally:
        page.deleteLater()


def test_skill_confirm_scope_consistency(qapp, monkeypatch):
    """确认弹窗口径：A 路径展示该类实际打包数（不受筛选影响）；
    B 路径展示范围内选中数 + 范围外提示数。"""
    import app.gui.skill_organize as so

    # _generate 前置 require_model 门禁——本测试聚焦确认弹窗口径，
    # 垫掉门禁弹窗（无模型环境下模态框会挂住 headless 跑批）
    monkeypatch.setattr(so.SkillOrganizePage, "require_model",
                        lambda self, action: True)
    calls = []
    monkeypatch.setattr(
        so, "confirm_skill_export",
        lambda parent, scope=None, items=None, name=None,
               description=None, out_of_scope=0: (
            calls.append((scope, len(items or []), out_of_scope)),
            False)[1])

    page = so.SkillOrganizePage(_SkillApi())
    try:
        page.refresh()
        from tests.conftest import pump_until  # 整理页取数已走 fetch_and_render（异步）
        assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
        qapp.processEvents()

        # A 路径：未筛选 → 该类 130 条（与后端按类打包一致）
        page._generate("研发", "工程实践", False)
        assert calls[-1] == ("研发 / 工程实践", 130, 0), calls[-1]

        # A 路径：筛选切到另一类 → 弹窗仍展示该类 130 条，不受当前筛选影响
        page.cat_sel.setCurrentIndex(2)  # 产品/决策
        qapp.processEvents()
        page._generate("研发", "工程实践", False)
        assert calls[-1] == ("研发 / 工程实践", 130, 0), calls[-1]
        page.cat_sel.setCurrentIndex(0)  # 回全部
        qapp.processEvents()

        # B 路径：勾 1 条范围内 + 1 条范围外 → 弹窗 1 条 + 范围外提示 1
        page._check({"id": "e0", "trunk": "研发", "category": "工程实践"}, True)
        page._check({"id": "cross", "trunk": "产品", "category": "决策"}, True)
        page.cat_sel.setCurrentIndex(1)  # 研发/工程实践
        qapp.processEvents()
        page._generate(None, None, True)
        assert calls[-1] == (None, 1, 1), calls[-1]
    finally:
        page.deleteLater()


# ---------- 「总结成方法」：未接 AI 前置确认门禁 ----------

class _GateApi(OfflineApi):
    """零网络 API 桩：/api/models 返回固定路由，其余请求只记录不报错。"""

    def __init__(self, routes: list[dict]):
        super().__init__(base_url="http://127.0.0.1:8101")
        self._routes = routes
        self.calls: list[tuple] = []

    def _request(self, method, path, json=None, params=None, timeout=None):
        self.calls.append((method, path, json))
        if path == "/api/models":
            return {"routes": self._routes, "default_model": None}
        return {}


def _gate_page(cls, api):
    """轻量实例化：跳过 _build/refresh，只挂 PageBase 公共能力（门禁测试专用）。"""
    from app.gui.page_base import PageBase

    page = cls.__new__(cls)
    PageBase.__init__(page, api)
    return page


def _patch_confirm_exec(monkeypatch, accept: bool, sink: list):
    """拦截 confirm_dialog 的模态 exec：记录窗口标题，返回 Accepted/Rejected。"""
    from app.gui import qt_dialogs

    code = (qt_dialogs.QDialog.DialogCode.Accepted if accept
            else qt_dialogs.QDialog.DialogCode.Rejected)

    def fake_exec(self):
        sink.append(self.windowTitle())
        return code

    monkeypatch.setattr(qt_dialogs.QDialog, "exec", fake_exec)


def _distilled_posts(api: _GateApi) -> list:
    return [c for c in api.calls
            if c[0] == "POST" and c[1] == "/api/skills/distill"]


def _sync_run_async(monkeypatch, page) -> None:
    """run_async 同步化：执行任务并把结果喂给 on_done（错误喂 on_error），
    让「提案→弹预览」的回调链在测试里跑通。"""

    def sync(fn, on_done=None, on_error=None):
        try:
            r = fn()
        except Exception as exc:  # noqa: BLE001 与 ApiWorker 同口径收口
            if on_error:
                on_error(str(exc))
            return
        if on_done:
            on_done(r)

    monkeypatch.setattr(page, "run_async", sync)


def test_home_distill_cancel_without_model(qapp, monkeypatch):
    """首页：未接 AI 弹窗 → 取消 = 只关窗，不蒸馏。"""
    from PySide6.QtWidgets import QPushButton

    from app.gui.home import HomePage

    api = _GateApi(routes=[])
    page = _gate_page(HomePage, api)
    seen: list[str] = []
    _patch_confirm_exec(monkeypatch, accept=False, sink=seen)
    _sync_run_async(monkeypatch, page)

    page._distill("研发", "工程实践", QPushButton())
    assert seen == ["需要接入模型"]
    assert _distilled_posts(api) == []


def test_home_distill_confirm_goes_connect_without_model(qapp, monkeypatch):
    """首页：未接 AI 弹窗 → 确认 = 引导去「接入」页，仍不蒸馏（无本机兜底）。"""
    from PySide6.QtWidgets import QPushButton

    from app.gui.home import HomePage

    api = _GateApi(routes=[])
    page = _gate_page(HomePage, api)
    seen: list[str] = []
    _patch_confirm_exec(monkeypatch, accept=True, sink=seen)
    _sync_run_async(monkeypatch, page)
    went: list[str] = []
    monkeypatch.setattr(page, "go", lambda name: went.append(name))

    page._distill("研发", "工程实践", QPushButton())
    assert seen == ["需要接入模型"]
    assert went == ["connect"]
    assert _distilled_posts(api) == []


def test_home_distill_passthrough_when_model(qapp, monkeypatch):
    """首页：已接 AI（任一路由配了 endpoint）→ 不打扰，直接蒸馏。"""
    from PySide6.QtWidgets import QPushButton

    from app.gui.home import HomePage

    api = _GateApi(routes=[{"name": "local", "endpoint": "http://127.0.0.1:11434"}])
    page = _gate_page(HomePage, api)
    seen: list[str] = []
    _patch_confirm_exec(monkeypatch, accept=False, sink=seen)
    _sync_run_async(monkeypatch, page)

    page._distill("研发", "工程实践", QPushButton())
    assert seen == []  # 未弹窗
    assert len(_distilled_posts(api)) == 1


def test_methods_distill_cancel_without_model(qapp, monkeypatch):
    """「我的方法」页：同一门禁口径——未接 AI 取消后不蒸馏。"""
    from PySide6.QtWidgets import QPushButton

    from app.gui.methods import MethodsPage

    api = _GateApi(routes=[])
    page = _gate_page(MethodsPage, api)
    seen: list[str] = []
    _patch_confirm_exec(monkeypatch, accept=False, sink=seen)
    _sync_run_async(monkeypatch, page)

    page._distill(QPushButton(), "研发", "工程实践")
    assert seen == ["需要接入模型"]
    assert _distilled_posts(api) == []


def test_methods_distill_passthrough_when_model(qapp, monkeypatch):
    """「我的方法」页：已接 AI 不弹直达蒸馏；路由存在但 endpoint 空仍弹窗。"""
    from PySide6.QtWidgets import QPushButton

    from app.gui.methods import MethodsPage

    page = _gate_page(MethodsPage, _GateApi(
        routes=[{"name": "local", "endpoint": "http://x/v1"}]))
    seen: list[str] = []
    _patch_confirm_exec(monkeypatch, accept=False, sink=seen)
    _sync_run_async(monkeypatch, page)
    # 轻量实例没有 _build 出来的行内状态行，打桩掉（门禁测试只关心是否蒸馏）
    monkeypatch.setattr(page, "_set_status", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(page, "refresh_all", lambda: None)
    page._distill(QPushButton(), "研发", "工程实践")
    assert seen == []

    # endpoint 全空 = 没接可用模型 → 仍弹窗
    page2 = _gate_page(MethodsPage, _GateApi(routes=[{"name": "a", "endpoint": ""}]))
    seen2: list[str] = []
    _patch_confirm_exec(monkeypatch, accept=False, sink=seen2)
    _sync_run_async(monkeypatch, page2)
    page2._distill(QPushButton(), "研发", "工程实践")
    assert seen2 == ["需要接入模型"]


# ---------- 「重建」空方法卡：只在空卡出现 + 点了走 force ----------

# 三节"（无）"= 真机被写坏的空卡现场
_EMPTY_SKILL_MD = ("# 其他 / 未分类 · playbook\n\n"
                   "> name: 常见报错排查\n> version: 3\n"
                   "> confidence: high\n\n"
                   "## 标准流程\n（无）\n## 成功要点\n（无）\n## 失败模式\n（无）\n")
_HEALTHY_SKILL_MD = ("# 营销 / 文案写作 · playbook\n\n"
                     "> name: 投放标题\n> version: 2\n"
                     "> confidence: medium\n\n"
                     "## 标准流程\n1. 确认投放目标\n\n"
                     "## 成功要点\n- 利益点前置\n\n"
                     "## 失败模式\n- [Solidified] 纯情绪文案点击率低\n")


class _RebuildApi(_GateApi):
    """read_skill 按 (trunk, category) 回可控 md；其余与 _GateApi 一致（零网络）。"""

    def __init__(self, cards: dict[tuple[str, str], str], routes=None):
        super().__init__(routes=routes if routes is not None
                         else [{"name": "local", "endpoint": "http://x/v1"}])
        self._cards = cards

    def _request(self, method, path, json=None, params=None, timeout=None):
        parts = path.split("/")
        if method == "GET" and len(parts) == 5 and parts[2] == "skills":
            self.calls.append((method, path, json))
            return {"md": self._cards.get((parts[3], parts[4]), "")}
        return super()._request(method, path, json=json, params=params,
                                timeout=timeout)


def _rebuild_buttons(widget) -> list:
    from PySide6.QtWidgets import QPushButton

    return [b for b in widget.findChildren(QPushButton) if b.text() == "重建"]


def _card_for(page, trunk: str, category: str):
    return page._skill_card({"trunk": trunk, "category": category, "name": None})


def test_methods_list_body_is_plain_excerpt(qapp):
    """：列表卡正文走纯文本摘录——去 Markdown 标记、取前若干行、超长截断。

    完整排版正文只在详情抽屉渲染；列表不再逐张 md_view（setMarkdown 是入页
    构建的主要成本）。
    """
    from app.gui.methods import _md_excerpt

    md = ("## 结论\n\n把**先写测试**当成默认动作。\n\n"
          "1. 复现问题\n2. 只写刚好通过的实现\n\n"
          "```python\nCODE_SHOULD_NOT_APPEAR = 1\n```\n\n"
          "- [文档](http://example.com) 见 *此处*\n")
    out = _md_excerpt(md)
    assert out == "结论 把先写测试当成默认动作。 复现问题 只写刚好通过的实现"
    # 代码围栏内内容不出现；Markdown 语法标记不残留
    assert "CODE_SHOULD_NOT_APPEAR" not in out
    assert "```" not in out and "##" not in out and "**" not in out
    # 超长截断：不超过上限 + 省略号收尾
    long_out = _md_excerpt("正文" * 500)
    assert len(long_out) <= 201 and long_out.endswith("…")
    # 空正文 → 空串（由调用方决定不渲染）
    assert _md_excerpt("") == ""


def test_methods_rebuild_button_only_on_empty_card(qapp, monkeypatch):
    """空卡才有「重建」（自救路），健康卡不添按钮（否则按钮堆里多一个没人按的）。"""
    from app.gui.methods import MethodsPage

    api = _RebuildApi({("其他", "未分类"): _EMPTY_SKILL_MD,
                       ("营销", "文案写作"): _HEALTHY_SKILL_MD})
    page = _gate_page(MethodsPage, api)
    _sync_run_async(monkeypatch, page)

    empty = _card_for(page, "其他", "未分类")
    assert len(_rebuild_buttons(empty)) == 1, "空卡必须给出自救入口"
    healthy = _card_for(page, "营销", "文案写作")
    assert _rebuild_buttons(healthy) == [], "健康卡不该多一个按钮"


def test_methods_rebuild_click_posts_force(qapp, monkeypatch):
    """点「重建」= 走 force 蒸馏（非强制那条路 pending=0 时只会 409，修不回来）。"""
    from app.gui.methods import MethodsPage

    api = _RebuildApi({("其他", "未分类"): _EMPTY_SKILL_MD})
    page = _gate_page(MethodsPage, api)
    seen: list[str] = []
    _patch_confirm_exec(monkeypatch, accept=True, sink=seen)
    _sync_run_async(monkeypatch, page)
    monkeypatch.setattr(page, "_set_status", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(page, "refresh_all", lambda: None)

    card = _card_for(page, "其他", "未分类")  # 必须留住卡：临时对象一释放按钮就没了
    _rebuild_buttons(card)[0].click()

    posts = _distilled_posts(api)
    assert len(posts) == 1, posts
    assert posts[-1][2] == {"trunk": "其他", "category": "未分类", "force": True}
    assert seen == []  # 已接 AI：不打扰，直达


def test_methods_rebuild_confirm_without_model_sends_nothing(qapp, monkeypatch):
    """未接 AI 时同一门禁：确认 = 引导去「接入」页，不重建（无本机兜底）。"""
    from app.gui.methods import MethodsPage

    api = _RebuildApi({("其他", "未分类"): _EMPTY_SKILL_MD}, routes=[])
    page = _gate_page(MethodsPage, api)
    seen: list[str] = []
    _patch_confirm_exec(monkeypatch, accept=True, sink=seen)
    _sync_run_async(monkeypatch, page)
    monkeypatch.setattr(page, "_set_status", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(page, "refresh_all", lambda: None)
    went: list[str] = []
    monkeypatch.setattr(page, "go", lambda name: went.append(name))

    card = _card_for(page, "其他", "未分类")  # 必须留住卡：临时对象一释放按钮就没了
    _rebuild_buttons(card)[0].click()

    assert seen == ["需要接入模型"]
    assert went == ["connect"]
    assert _distilled_posts(api) == []


def test_methods_rebuild_cancel_sends_nothing(qapp, monkeypatch):
    """确认弹窗取消 = 什么都不做（与「总结成方法」同一门禁口径）。"""
    from app.gui.methods import MethodsPage

    api = _RebuildApi({("其他", "未分类"): _EMPTY_SKILL_MD}, routes=[])
    page = _gate_page(MethodsPage, api)
    seen: list[str] = []
    _patch_confirm_exec(monkeypatch, accept=False, sink=seen)
    _sync_run_async(monkeypatch, page)
    monkeypatch.setattr(page, "_set_status", lambda *a, **k: None, raising=False)

    card = _card_for(page, "其他", "未分类")  # 必须留住卡：临时对象一释放按钮就没了
    _rebuild_buttons(card)[0].click()

    assert seen == ["需要接入模型"]
    assert _distilled_posts(api) == []


# ---------- AI 重写（第二项蒸馏）：门禁 + 预览→采纳接线 ----------

class _RewriteApi(_GateApi):
    """在 _GateApi 基础上给 AI 重写端点回罐头提案。"""

    def _request(self, method, path, json=None, params=None, timeout=None):
        self.calls.append((method, path, json))
        if path == "/api/models":
            return {"routes": self._routes, "default_model": None}
        if path == "/api/experiences/ai-polish":
            return {"proposals": [{"id": "e1", "task": "新结论",
                                   "action": "新做法", "state": "", "outcome": ""}]}
        if path.endswith("/ai-polish") and "/failure-modes/" in path:
            return {"old_text": "旧坑", "new_text": "新坑的说法"}
        if path == "/api/skills/rewrite-preview":
            return {"md": "# new playbook\n", "old_md": "# old playbook\n",
                    "count": 3}
        return {}


def _patch_dialog_result(monkeypatch, result: int, sink: list):
    """统一拦截所有 QDialog.exec（confirm/预览弹层共用同一个 QDialog 类）。"""
    from app.gui import qt_dialogs

    def fake_exec(self):
        sink.append(self.windowTitle())
        return result

    monkeypatch.setattr(qt_dialogs.QDialog, "exec", fake_exec)


def test_guide_connect_ai_blocks_without_model(qapp, monkeypatch):
    """未接 AI：重写类功能弹窗引导、返回 False，且不发起任何 polish 请求。"""
    from app.gui.experiences import ExperiencesPage

    api = _RewriteApi(routes=[])
    page = _gate_page(ExperiencesPage, api)
    seen: list[str] = []
    _patch_dialog_result(monkeypatch, 0, seen)

    page._ai_rewrite_group([{"id": "e1", "task": "写标题"}])
    assert seen == ["需要接入模型"]
    assert [c for c in api.calls if "ai-polish" in str(c[1])] == []


def test_experience_rewrite_adopt_writes_back(qapp, monkeypatch):
    """已接 AI：提案→预览（采纳）→逐条 ai-apply；不采纳路径零写库。"""
    from app.gui.experiences import ExperiencesPage

    api = _RewriteApi(routes=[{"name": "m", "endpoint": "http://x/v1"}])
    page = _gate_page(ExperiencesPage, api)
    seen: list[str] = []
    _patch_dialog_result(monkeypatch, 1, seen)  # 预览弹 accept
    _sync_run_async(monkeypatch, page)
    monkeypatch.setattr(page, "_rebuild_preserve_scroll", lambda: None)

    page._ai_rewrite_group([{"id": "e1", "task": "写标题", "action": "利益点前置"}])
    assert seen == ["AI 重写预览"]
    applies = [c for c in api.calls
               if c[0] == "POST" and c[1] == "/api/experiences/e1/ai-apply"]
    assert applies and applies[0][2]["task"] == "新结论"

    # 不采纳路径
    api2 = _RewriteApi(routes=[{"name": "m", "endpoint": "http://x/v1"}])
    page2 = _gate_page(ExperiencesPage, api2)
    seen2: list[str] = []
    _patch_dialog_result(monkeypatch, 0, seen2)  # 预览弹 reject
    _sync_run_async(monkeypatch, page2)
    monkeypatch.setattr(page2, "_rebuild_preserve_scroll", lambda: None)
    page2._ai_rewrite_group([{"id": "e1", "task": "写标题"}])
    assert not [c for c in api2.calls if c[1].endswith("/ai-apply")]


def test_failure_rewrite_adopt_flow(qapp, monkeypatch):
    """坑条目：已接 AI → polish → 预览采纳 → ai-apply 换行。"""
    from app.gui.failure_modes import FailureModesPage

    api = _RewriteApi(routes=[{"name": "m", "endpoint": "http://x/v1"}])
    page = _gate_page(FailureModesPage, api)
    seen: list[str] = []
    _patch_dialog_result(monkeypatch, 1, seen)
    _sync_run_async(monkeypatch, page)
    monkeypatch.setattr(page, "refresh", lambda: None)

    page._ai_rewrite("营销", "文案写作", "旧坑")
    assert seen == ["AI 重写预览"]
    applies = [c for c in api.calls if c[1].endswith("/failure-modes/营销/文案写作/ai-apply")
               or c[1] == "/api/failure-modes/营销/文案写作/ai-apply"]
    assert applies and applies[0][2] == {"old_text": "旧坑",
                                         "new_text": "新坑的说法"}


def test_methods_skill_rewrite_apply_flow(qapp, monkeypatch):
    """整方法：rewrite-preview → 预览采纳 → rewrite-apply 逐字落盘请求。"""
    from app.gui.methods import MethodsPage

    api = _RewriteApi(routes=[{"name": "m", "endpoint": "http://x/v1"}])
    page = _gate_page(MethodsPage, api)
    seen: list[str] = []
    _patch_dialog_result(monkeypatch, 1, seen)
    _sync_run_async(monkeypatch, page)
    monkeypatch.setattr(page, "_set_status", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(page, "refresh_all", lambda: None)

    page._ai_rewrite_skill("营销", "文案写作")
    assert seen == ["AI 重写预览"]
    applies = [c for c in api.calls if c[1] == "/api/skills/rewrite-apply"]
    assert applies and applies[0][2] == {"trunk": "营销", "category": "文案写作",
                                         "md": "# new playbook\n"}


# ---------- 报告弹层：导出后能打开产物所在文件夹 ----------

class _Signal:
    def __init__(self):
        self._fns: list = []

    def connect(self, fn):
        self._fns.append(fn)

    def emit(self, *args):
        for fn in list(self._fns):
            fn(*args)


class _SyncWorker:
    """把 ApiWorker 的 QThread 收成同步：connect 即 emit，测试可确定性断言。"""

    def __init__(self, fn, parent=None):
        self._fn = fn
        self.finished = _Signal()
        self.error = _Signal()

    def deleteLater(self):  # no-op：对齐真 ApiWorker（QThread）接口——
        # page_base.run_async / report_view._run 都会连它
        pass

    def start(self):
        try:
            r = self._fn()
        except Exception as exc:  # noqa: BLE001 与 ApiWorker 同口径收口
            self.error.emit(str(exc))
            return
        self.finished.emit(r)


class _ExportApi:
    def __init__(self, out_dir):
        self._out = out_dir

    def export(self, kind, **kw):
        return {"path": str(self._out / "成长报告-30天.md")}

    def status(self):
        return {"data_dir": str(self._out)}


def _dlg_buttons(dlg) -> dict:
    from PySide6.QtWidgets import QPushButton

    return {b.text(): b for b in dlg.findChildren(QPushButton)}


def test_report_dialog_folder_button_after_export(qapp, monkeypatch, tmp_path):
    """没导出过 → 「打开文件夹」禁用；导出成功 → 可用，且打开的是产物所在目录。"""
    from PySide6.QtWidgets import QWidget

    from app.gui import report_view, settings_page

    api = _ExportApi(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(report_view, "ApiWorker", _SyncWorker)
    monkeypatch.setattr(settings_page, "_open_folder", opened.append)

    dlg = report_view._report_dialog(
        api, "成长报告", QWidget(), (("growth",), {"days": 30}),
        {"title": "成长报告", "blocks": []}, "growth")

    btns = _dlg_buttons(dlg)
    assert set(btns) >= {"关闭", "打开文件夹", "导出 PNG", "导出 md"}
    assert not btns["打开文件夹"].isEnabled(), "还没导出就不该能打开"

    btns["导出 md"].click()
    assert btns["打开文件夹"].isEnabled(), "导出成功后应能立刻打开文件夹"

    btns["打开文件夹"].click()
    assert opened == [str(tmp_path)], opened


def test_report_dialog_folder_button_without_export(qapp, monkeypatch, tmp_path):
    """没导出过却硬点（比如键盘激活）：给一句「先导出一次」，不静默、不误开别的目录。"""
    from PySide6.QtWidgets import QLabel, QWidget

    from app.gui import report_view, settings_page

    opened: list[str] = []
    monkeypatch.setattr(settings_page, "_open_folder", opened.append)
    api = _ExportApi(tmp_path)
    dlg = report_view._report_dialog(
        api, "成长报告", QWidget(), (("growth",), {"days": 30}),
        {"title": "成长报告", "blocks": []}, "growth")

    btns = _dlg_buttons(dlg)
    btns["打开文件夹"].setEnabled(True)  # 绕过禁用，直接点回调
    btns["打开文件夹"].click()
    assert opened == []
    assert any("先导出一次" in l.text() for l in dlg.findChildren(QLabel))
