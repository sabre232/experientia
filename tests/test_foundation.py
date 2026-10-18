"""基础层契约回归（`docs/落地任务/_基础层.md` /）。

只验证**冻结接口**本身，不碰任何页面业务逻辑：
- 契约符号存在且签名一致；
- `md_view` 富文本渲染 + fail-open；
- `provenance_bar` 三态；
- `skeleton_column` / `SkeletonBlock`；
- `AnimatedStack` reduced-motion 瞬时切换且新页可见；
- `DetailDrawer.open_detail` 对缺字段 payload 容错；
- 图表 `progress` fail-open（初值 1.0）；
- `fetch_and_render(skeleton=)` 骨架挂载/移除；
- `require_model` / `model_state` 门禁口径；
- `APP_STYLESHEET()` 按色板缓存。

沿用仓库手动 QApplication 模式（不引 pytest-qt）：离屏渲染，零网络。
"""

import inspect
import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QTextBrowser, QWidget  # noqa: E402

from app.gui import i18n, qt_theme, qt_widgets  # noqa: E402
from app.gui.api_client import LocalApi  # noqa: E402
from app.gui.page_base import PageBase  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    i18n.load_catalog("zh")
    return QApplication.instance() or QApplication([])


def _spin(app, n=8):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


def _labels_text(widget) -> str:
    return "\n".join(lab.text() for lab in widget.findChildren(QLabel))


class _ModelApi(LocalApi):
    """零网络：/api/models 返回固定路由，其余只记录。"""

    def __init__(self, routes):
        super().__init__(base_url="http://fake")
        self._routes = routes
        self.calls: list[str] = []

    def _request(self, method, path, json=None, params=None, timeout=None):
        self.calls.append(path)
        if path.split("?")[0] == "/api/models":
            return {"routes": self._routes, "default_model": None}
        return {}


def _bare_page(api) -> PageBase:
    """轻量实例：跳过 _build/refresh，只挂 PageBase 公共能力（同 test_qt_pages）。"""
    page = PageBase.__new__(PageBase)
    PageBase.__init__(page, api)
    return page


# ----------  契约符号与签名 ----------

def test_contract_symbols_exist_and_signatures():
    """/ 全部符号存在、签名一致（并行波次的消费前提）。"""
    p = inspect.signature(qt_theme.md_view).parameters
    assert list(p) == ["md", "compact", "selectable"]
    assert p["compact"].kind is inspect.Parameter.KEYWORD_ONLY
    assert p["compact"].default is False and p["selectable"].default is True

    assert list(inspect.signature(qt_theme.provenance_bar).parameters) == ["state"]

    sp = inspect.signature(qt_widgets.SkeletonBlock.__init__).parameters
    assert sp["height"].default == qt_theme.F.body
    assert sp["width"].default is None
    assert sp["height"].kind is inspect.Parameter.KEYWORD_ONLY

    assert list(inspect.signature(qt_widgets.skeleton_column).parameters) == ["heights"]

    sw = inspect.signature(qt_widgets.AnimatedStack.setCurrentWidget).parameters
    assert list(sw) == ["self", "w", "animate"] and sw["animate"].default is True

    od = inspect.signature(qt_widgets.DetailDrawer.open_detail).parameters
    assert list(od) == ["self", "kind", "payload"] and od["payload"].default is None

    hl = inspect.signature(qt_widgets.hover_lift).parameters
    assert list(hl) == ["widget", "rise"] and hl["rise"].default == 2

    fr = inspect.signature(PageBase.fetch_and_render).parameters
    assert "skeleton" in fr and fr["skeleton"].kind is inspect.Parameter.KEYWORD_ONLY
    assert fr["skeleton"].default is None

    assert list(inspect.signature(PageBase.require_model).parameters) == ["self", "action"]
    assert list(inspect.signature(PageBase.model_state).parameters) == ["self"]

    # 旧门禁必须删除，不得留兼容壳
    assert not hasattr(PageBase, "confirm_builtin_summary")
    assert not hasattr(PageBase, "guide_connect_ai")

    # 新组件进 __all__（消费方 from .qt_theme import * 才能拿到）
    assert {"md_view", "provenance_bar"} <= set(qt_theme.__all__)


# ----------  md_view ----------

_MD_SAMPLE = (
    "# 标题一\n\n"
    "一段正文。\n\n"
    "- 列表项 A\n"
    "- 列表项 B\n\n"
    "| 列1 | 列2 |\n|---|---|\n| a | b |\n\n"
    "```python\nprint('hi')\n```\n\n"
    "> 引用一句话\n"
)


def test_md_view_renders_markdown(qapp):
    """含标题/列表/表格/代码块的 Markdown → 非空 QTextBrowser。"""
    view = qt_theme.md_view(_MD_SAMPLE)
    assert isinstance(view, QTextBrowser)
    plain = view.toPlainText()
    assert plain.strip()
    for token in ("标题一", "列表项 A", "列1", "print('hi')", "引用一句话"):
        assert token in plain, token


def test_md_view_compact_and_empty_fail_open(qapp):
    """compact 不抛；空串/None 也返回控件（fail-open，绝不抛给调用方）。"""
    assert isinstance(qt_theme.md_view("", compact=True), QTextBrowser)
    assert isinstance(qt_theme.md_view(""), QTextBrowser)
    # 破坏性输入也必须 fail-open（回退纯文本或留空）
    assert isinstance(qt_theme.md_view("\x00\x01# 坏"), QTextBrowser)


def test_md_view_not_selectable(qapp):
    from PySide6.QtCore import Qt

    view = qt_theme.md_view("# x", selectable=False)
    assert view.textInteractionFlags() == Qt.NoTextInteraction


# ----------  provenance_bar ----------

def test_provenance_bar_three_states(qapp):
    """model / ""（未知）/ none+无内容 → None；none+有内容 → 提示条。"""
    assert qt_theme.provenance_bar(
        {"content_source": "model", "has_content": True}) is None
    assert qt_theme.provenance_bar(
        {"content_source": "", "has_content": True}) is None
    assert qt_theme.provenance_bar(
        {"content_source": "none", "has_content": False}) is None
    assert qt_theme.provenance_bar({}) is None

    bar = qt_theme.provenance_bar(
        {"content_source": "none", "has_content": True,
         "generated_at": "2026-09-26T10:00:00"})
    assert isinstance(bar, QWidget)
    text = _labels_text(bar)
    assert "未接入模型" in text and "2026-09-26T10:00:00" in text


def test_provenance_bar_without_timestamp(qapp):
    """取不到 generated_at → 省略时间部分，用"上次生成"兜底文案。"""
    bar = qt_theme.provenance_bar(
        {"content_source": "none", "has_content": True})
    assert isinstance(bar, QWidget)
    assert "上次生成" in _labels_text(bar)


# ----------  骨架屏 ----------

def test_skeleton_block_and_column(qapp):
    blk = qt_widgets.SkeletonBlock(height=12)
    assert blk.height() == 12
    col = qt_widgets.skeleton_column([12, 20, 16])
    assert isinstance(col, QWidget)
    assert len(col.findChildren(qt_widgets.SkeletonBlock)) == 3
    assert qt_widgets.skeleton_column([]).findChildren(
        qt_widgets.SkeletonBlock) == []


def test_skeleton_block_static_when_reduced_motion(qapp, monkeypatch):
    """reduced-motion：不启动扫光动画（静态灰块）。"""
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    blk = qt_widgets.SkeletonBlock(height=12)
    assert blk._anim.state().name in ("Stopped", "Paused")


# ----------  AnimatedStack ----------

def test_animated_stack_instant_switch_reduced_motion(qapp, monkeypatch):
    """reduced-motion：瞬时切换、无覆盖层残留、新页可见。"""
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    stack = qt_widgets.AnimatedStack()
    a, b = QWidget(), QWidget()
    stack.addWidget(a)
    stack.addWidget(b)
    stack.setCurrentWidget(a)
    stack.setCurrentWidget(b)
    _spin(qapp)
    assert stack.currentWidget() is b
    assert stack._overlay is None
    assert not b.isHidden()


def test_animated_stack_switch_lands_on_target(qapp, monkeypatch):
    """默认动效：无论动画如何，收尾必须停在目标页且不留覆盖层。"""
    monkeypatch.delenv("EXPERIENTIA_REDUCE_MOTION", raising=False)
    stack = qt_widgets.AnimatedStack()
    a, b = QWidget(), QWidget()
    stack.addWidget(a)
    stack.addWidget(b)
    stack.setCurrentWidget(a)
    stack.setCurrentWidget(b)
    assert stack.currentWidget() is b
    assert not b.isHidden()
    # 动画收尾：覆盖层清理（pump 到 finished）
    for _ in range(60):
        qapp.processEvents()
        if stack._overlay is None:
            break
        time.sleep(0.01)
    assert stack._overlay is None


def test_animated_stack_animate_false_is_instant(qapp):
    stack = qt_widgets.AnimatedStack()
    a, b = QWidget(), QWidget()
    stack.addWidget(a)
    stack.addWidget(b)
    stack.setCurrentWidget(a)
    stack.setCurrentWidget(b, animate=False)
    assert stack.currentWidget() is b
    assert stack._overlay is None


# ----------  DetailDrawer ----------

def test_detail_drawer_tolerates_missing_fields(qapp):
    """payload 缺字段一律容错跳过，不抛异常（字段约定未定齐前）。"""
    host = QWidget()
    drawer = qt_widgets.DetailDrawer(host)
    for kind in ("experience", "method", "failure", "preference", "session"):
        drawer.open_detail(kind, {})
        drawer.open_detail(kind, None)
    drawer.open_detail("method", {"title": "标题", "body": "# 正文",
                                  "status": "可用", "experience_ids": ["e1", "e2"],
                                  "agents": {"codex": 2}})
    _spin(qapp)
    assert drawer._kind == "method"
    drawer.deleteLater()
    host.deleteLater()


def test_detail_drawer_set_actions(qapp):
    host = QWidget()
    drawer = qt_widgets.DetailDrawer(host)
    from PySide6.QtWidgets import QPushButton

    drawer.set_actions([QPushButton("采纳"), QPushButton("忽略")])
    assert drawer._actions.isVisible() or not drawer._actions.isHidden()
    drawer.set_actions([])
    assert drawer._actions.isHidden()
    drawer.deleteLater()
    host.deleteLater()


# ----------  hover_lift ----------

def test_hover_lift_installs_shadow_and_filter(qapp):
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    w = QWidget()
    qt_widgets.hover_lift(w, rise=2)
    assert isinstance(w.graphicsEffect(), QGraphicsDropShadowEffect)
    assert getattr(w, "_hover_lift_filter", None) is not None
    w.deleteLater()


# ----------  图表入场 fail-open ----------

def test_charts_progress_defaults_to_terminal(qapp):
    """progress 初值必须 1.0（未调用 animate_in 就是终态，绝不留白）。"""
    assert qt_widgets.HeatBar([1, 2, 3]).progress == 1.0
    assert qt_widgets.ColumnsChart([1, 2, 3]).progress == 1.0
    assert qt_widgets.ReworkChart([{"week": "W1", "count": 3,
                                    "rate": 1.0}]).progress == 1.0


def test_charts_animate_in_reduced_motion_stays_terminal(qapp, monkeypatch):
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    for chart in (qt_widgets.HeatBar([1, 2, 3]),
                  qt_widgets.ColumnsChart([1, 2, 3]),
                  qt_widgets.ReworkChart([{"week": "W1", "count": 3,
                                           "rate": 1.0}])):
        chart.animate_in()
        assert chart.progress == 1.0


# ----------  fetch_and_render(skeleton=) ----------

def test_fetch_and_render_mounts_and_drops_skeleton(qapp, pump_page):
    """skeleton 挂到内容区、render 前移除；取数快则不显示（保持隐藏）。"""
    page = _bare_page(_ModelApi([]))
    results: list = []
    try:
        page.fetch_and_render(lambda: {"ok": 1}, results.append, "sk",
                              skeleton=[12, 20])
        blocks = page.findChildren(qt_widgets.SkeletonBlock)
        assert len(blocks) == 2
        assert page._layout.count() == 1
        # 未到最短阈值前整列不可见（取数够快就根本不显示）
        assert not page._layout.itemAt(0).widget().isVisible()
        assert pump_page(page, qapp)
        assert results == [{"ok": 1}]
        assert page._layout.count() == 0  # render 前已移除
    finally:
        page.deleteLater()


def test_fetch_and_render_without_skeleton(qapp, pump_page):
    page = _bare_page(_ModelApi([]))
    results: list = []
    try:
        page.fetch_and_render(lambda: [1, 2], results.append, "n")
        assert pump_page(page, qapp)
        assert results == [[1, 2]]
        assert page.findChildren(qt_widgets.SkeletonBlock) == []
    finally:
        page.deleteLater()


def test_fetch_and_render_fetch_error_yields_none(qapp, pump_page):
    """fetch 抛异常 → result=None（页面自行降级），且骨架仍被移除。"""
    page = _bare_page(_ModelApi([]))
    results: list = []
    try:
        def boom():
            raise RuntimeError("nope")

        page.fetch_and_render(boom, results.append, "e", skeleton=[12])
        assert pump_page(page, qapp)
        assert results == [None]
        assert page._layout.count() == 0
    finally:
        page.deleteLater()


def test_fetch_and_render_render_error_does_not_stick_page(qapp, pump_page):
    """render 抛异常：不外泄、骨架移除、且 ``_content_ready`` 仍置真。

    回归：渲染异常若逃出槽函数，页面会被当成"永远没加载过"——每次刷新重放骨架屏
    （看着一直空白/加载中），且异常在打包态（无控制台）不可见。故此处置真后收尾。
    """
    page = _bare_page(_ModelApi([]))
    try:
        def render_boom(_res):
            raise RuntimeError("render boom")

        page.fetch_and_render(lambda: {"ok": 1}, render_boom, "r", skeleton=[12])
        assert pump_page(page, qapp)
        assert page._content_ready is True  # 关键：不再恒假 → 后续刷新不重放骨架
        assert page._layout.count() == 0    # 骨架已移除
        assert page.findChildren(qt_widgets.SkeletonBlock) == []
    finally:
        page.deleteLater()


def test_skeleton_lands_in_scroll_content_not_page_layout(qapp):
    """骨架必须插进**滚动区的内容列**，不得当页面布局的兄弟控件。

    回归（多页空白根因）：骨架块是 Fixed 高度、合计常 400~550px；作为页面布局
    兄弟会与唯一的 ``QScrollArea`` 争高——实测页面 678px 时滚动区被挤到 122px
    （82% 版面被几道灰条盖住）→ 任何页面每次加载都长得像"整页空白"。放进内容列
    后滚动区保持满高，且页头在骨架之前（先看到标题）。
    """
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout

    from app.gui.page_base import page_scaffold

    class _P(PageBase):
        def __init__(self, api):
            super().__init__(api)
            self._build()

        def _build(self):
            cl = QVBoxLayout()
            cl.addWidget(qt_widgets.page_header("标题", "副题"))
            cl.addWidget(QLabel("正文"))
            self._layout.addWidget(page_scaffold(cl, top=0))

    page = _P(_ModelApi([]))
    try:
        page.resize(900, 600)
        page.show()
        _spin(qapp)
        page.fetch_and_render(lambda: {}, lambda _r: None, "s", skeleton=[24, 72])
        blocks = page.findChildren(qt_widgets.SkeletonBlock)
        assert len(blocks) == 2
        scroll = page.findChild(QScrollArea)
        assert scroll is not None
        # 骨架在滚动区内（祖先链上），不是页面布局的兄弟
        assert scroll.isAncestorOf(blocks[0]), "骨架必须落在滚动区内容列里"
        assert page._layout.count() == 1, "页面布局应仍只有滚动区一个子项"
        # 滚动区未被骨架挤扁
        assert scroll.height() >= page.height() - 4
        # 页头在骨架之前
        col = page._skeleton_host_layout()
        assert col is not None
        assert col.indexOf(blocks[0].parentWidget()) == 1
    finally:
        page._wait_inflight()
        page.deleteLater()


def test_skeleton_lands_in_embedded_content_container(qapp):
    """内嵌页（内容包在 ``self.content`` 里、根 ``_layout`` 为空）的骨架必须落进
    ``content`` 容器——此前会被插进**看不见**的根布局，占位等于没挂。

    同时验证插入下表：骨架应排在首行静态外壳（页头/筛选行）**之后**，不与外壳争位。
    """
    from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

    class _Embedded(PageBase):
        def __init__(self, api):
            super().__init__(api)
            # 内嵌页约定：可见内容都在 self.content 里（ModelsPage/InjectPreviewPage）
            self.content = QWidget()
            cl = QVBoxLayout(self.content)
            head = QHBoxLayout()          # 首行外壳：标题 + 右侧操作（含 stretch）
            head.addWidget(QLabel("模型与接入"))
            head.addStretch(1)
            head_box = QWidget()
            head_box.setLayout(head)
            cl.addWidget(head_box)
            cl.addWidget(QLabel("正文"))

        def refresh(self):
            self.fetch_and_render(lambda: {}, lambda _r: None, "e",
                                  skeleton=[24, 72])

    host = QWidget()
    outer = QVBoxLayout(host)
    page = _Embedded(_ModelApi([]))
    outer.addWidget(page.content)   # 宿主只挂 content（与真实内嵌方式一致）
    host.resize(800, 600)
    host.show()
    try:
        _spin(qapp)
        page.refresh()
        blocks = page.content.findChildren(qt_widgets.SkeletonBlock)
        assert len(blocks) == 2, "骨架必须挂在可见的 content 容器里"
        col = page.content.layout()
        idx = col.indexOf(blocks[0].parentWidget())
        assert idx == 1, "骨架应排在首行外壳之后（外壳不被下推）"
        # 根 _layout（不可见）不得被塞进骨架
        assert page._layout.count() == 0
    finally:
        page._wait_inflight()
        host.deleteLater()


def test_skeleton_insert_index_skips_leading_shell_row(qapp):
    """``_skeleton_insert_index``：首项是页头/筛选行 → 1；否则 → 0。"""
    from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

    # 首项 = 含 addStretch 的横向行（筛选行/页头形状）
    col = QVBoxLayout()
    row = QHBoxLayout()
    row.addWidget(QLabel("筛选"))
    row.addStretch(1)
    col.addLayout(row)
    col.addWidget(QLabel("内容"))
    assert PageBase._skeleton_insert_index(col) == 1

    # 首项 = 无拉伸的普通控件（纯内容列）→ 仍插到最前
    col2 = QVBoxLayout()
    col2.addWidget(QLabel("正文"))
    assert PageBase._skeleton_insert_index(col2) == 0


# ----------  require_model / model_state ----------

def test_model_state_three_cases(qapp):
    assert _bare_page(_ModelApi([])).model_state() == {
        "available": False, "endpoint": ""}
    assert _bare_page(_ModelApi([{"name": "a", "endpoint": ""}])).model_state() == {
        "available": False, "endpoint": ""}
    got = _bare_page(_ModelApi(
        [{"name": "a", "endpoint": ""},
         {"name": "b", "endpoint": "http://x/v1"}])).model_state()
    assert got == {"available": True, "endpoint": "http://x/v1"}


def test_model_state_engine_unreachable(qapp):
    from app.gui.api_client import LocalApiError

    class _Dead(LocalApi):
        def _request(self, *a, **k):
            raise LocalApiError(0, "本地 API 未连接")

    assert _bare_page(_Dead(base_url="http://fake")).model_state() == {
        "available": False, "endpoint": ""}


def test_require_model_passes_when_available(qapp, monkeypatch):
    import app.gui.qt_dialogs as qd

    called: list = []
    monkeypatch.setattr(qd, "confirm_dialog",
                        lambda *a, **k: called.append(a) or True)
    page = _bare_page(_ModelApi([{"name": "m", "endpoint": "http://x/v1"}]))
    assert page.require_model("总结成方法") is True
    assert called == []  # 有模型不打扰


def test_require_model_blocks_and_offers_connect(qapp, monkeypatch):
    import app.gui.qt_dialogs as qd

    seen: list = []
    monkeypatch.setattr(qd, "confirm_dialog",
                        lambda title, msg, parent=None: (
                            seen.append((title, msg)), True)[1])
    page = _bare_page(_ModelApi([]))
    nav: list = []
    monkeypatch.setattr(page, "go", lambda name: nav.append(name))

    assert page.require_model("AI 重写") is False  # 门禁不因确认而放行
    assert nav == ["connect"]  # 确认后引导去「接入」页
    assert seen and seen[0][0] == "需要接入模型"
    assert "AI 重写" in seen[0][1]


def test_require_model_blocks_without_navigation_on_cancel(qapp, monkeypatch):
    import app.gui.qt_dialogs as qd

    monkeypatch.setattr(qd, "confirm_dialog", lambda *a, **k: False)
    page = _bare_page(_ModelApi([]))
    nav: list = []
    monkeypatch.setattr(page, "go", lambda name: nav.append(name))

    assert page.require_model("AI 重写") is False
    assert nav == []  # 取消则不跳转


# ----------  样式串缓存 ----------

def test_app_stylesheet_cached_by_mode(qapp):
    css1 = qt_theme.APP_STYLESHEET()
    css2 = qt_theme.APP_STYLESHEET()
    assert isinstance(css1, str) and css1
    assert css1 is css2  # 同色板命中缓存（同一对象）
    assert qt_theme.C.current_mode() in qt_theme._STYLESHEET_CACHE

# ----------  取数线程回收 / 骨架仅首屏 ----------

def test_fetch_and_render_releases_threads(qapp):
    """每次刷新的取数线程必须回收——否则轮询页每次刷新累积一个僵尸 QThread。"""
    page = _bare_page(_ModelApi([]))
    rendered: list = []
    for i in range(12):
        page.fetch_and_render(lambda v=i: {"v": v}, rendered.append, f"c{i}")
        w = page._fetches.get(f"c{i}")
        if w is not None:
            w.wait(5000)
        _spin(qapp, 3)
    _spin(qapp, 6)  # 让 DeferredDelete 真正走完
    from PySide6.QtCore import QThread

    leaked = [c for c in page.children() if isinstance(c, QThread)]
    assert len(leaked) <= 1, f"取数线程未回收：残留 {len(leaked)} 个"
    assert len(rendered) == 12


def test_skeleton_only_on_first_load(qapp):
    """骨架只在内容还没落地过（首屏）时插入。

    已有正文时再插会把内容整体顶下去、取数结束再弹回——首页每 30s 轮询一次，
    等于每半分钟整页下跳。
    """
    page = _bare_page(_ModelApi([]))
    content = QLabel("正文")
    page._layout.addWidget(content)

    def _content_index():
        for i in range(page._layout.count()):
            if page._layout.itemAt(i).widget() is content:
                return i
        return -1

    def slow():
        time.sleep(0.25)  # 超过 THRESHOLDS.SKELETON_MIN_MS，骨架会真的显示
        return {"ok": True}

    assert page._content_ready is False
    page.fetch_and_render(slow, lambda _r: None, "first", skeleton=[24, 72])
    _spin(qapp, 12)  # ≈0.1s：仍在取数中，骨架已挂且已显示
    assert _content_index() == 1, "首屏应挂骨架（正文被置到第 1 位）"

    _spin(qapp, 40)  # 等取数完成
    assert page._content_ready is True
    assert _content_index() == 0

    # 二次刷新（模拟轮询）：不得再把正文顶下去
    page.fetch_and_render(slow, lambda _r: None, "poll", skeleton=[24, 72])
    _spin(qapp, 12)
    assert _content_index() == 0, "轮询刷新不应再插入骨架"
    assert page._layout.count() == 1
