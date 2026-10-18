"""切页闪现护栏：禁止「无父控件被显示成真顶层窗口」。

现象：切页快时闪出一个带原生标题栏（App 图标 + 关闭按钮）的小窗，内容是一张
还没排版、只有标题的卡片。

根因：`card()` / `ShadowCard()` / 模板库展开体在**还没有父控件**时就调用
`setVisible(True)`。Qt 规则：无父控件被显式显示 = 立刻成为一个**真实顶层窗口**；
直到调用方 `addWidget` 把它 reparent 进布局，才变回普通子控件。这段间隔平时
在同一个调用栈内（微秒级，合成器来不及画）；切页快 / 一次渲染连造很多张卡 /
事件循环中途让出时，Windows 就会把它 map + 绘制一帧 → 用户看到小窗闪一下。

三层护栏：
1. 工厂层——`card()` / `ShadowCard()` 构造完（未入布局）不得 `isWindow()`；
2. 反方向——入布局后必须随父正常显示（防"为了不闪窗把卡片改成永不显示"）；
3. 整窗层——逐页切换期间，任何 `QEvent.Show` 落到 `isWindow()` 为真的控件上
   即失败。

第 3 层**必须用事件过滤器，不能轮询** `topLevelWidgets()`：闪窗只存在一帧，
轮询抓不住（实测的命中全靠过滤器拿到）。过滤器还要装在
**QApplication 实例**上——装在主窗树上会漏掉「还没插进控件树」的无父控件，
而它们正是肇事者。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QObject  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from app.gui import i18n  # noqa: E402
from conftest import OfflineApi  # noqa: E402


class _Store:
    """MainWindow 所需的最小 store 桩。"""

    def __init__(self):
        self.data_dir = str(Path(__file__).resolve().parent / "data-test-tmp")

    def load_config(self) -> dict:
        return {"locale": "zh"}

    def ensure_layout(self) -> None:
        pass


class _GhostWindowTrap(QObject):
    """装在 QApplication 上：记录「Show 事件落到窗口上」的瞬间。

    只存字符串摘要，不持有控件引用（避免给待析构控件延命）。
    """

    def __init__(self, allowed) -> None:
        super().__init__()
        self._allowed = {id(w) for w in allowed}
        self.ghosts: list[str] = []

    def eventFilter(self, obj, ev):
        # QApplication 级过滤器连 QWindow（无 isWindow()）也会送进来，先挡掉
        if not isinstance(obj, QWidget):
            return False
        if ev.type() == QEvent.Type.Show:
            try:
                if obj.isWindow() and id(obj) not in self._allowed:
                    self.ghosts.append(f"{type(obj).__name__}"
                                       f"(size={obj.size().toTuple()})")
            except RuntimeError:
                pass  # C++ 侧已析构的包装器
        return False


# ---------- 1. 工厂层：构造期不得开窗 ----------

def _card_makers():
    from app.gui.qt_theme import card
    from app.gui.qt_widgets import ShadowCard

    return {
        "card()": lambda: card(),
        "card(title=)": lambda: card(title="标题"),
        "card(secondary=True)": lambda: card(secondary=True),
        "card(visible=False)": lambda: card(visible=False),
        "ShadowCard()": lambda: ShadowCard(),
        "ShadowCard(title=)": lambda: ShadowCard(title="标题"),
        "ShadowCard(visible=False)": lambda: ShadowCard(visible=False),
    }


def test_card_factories_never_create_a_window(qapp):
    """构造完、还没入布局的卡片不得「无父且可见」。

    判据是**可见性**而非 `isWindow()`：Qt 里任何无父控件 `isWindow()` 都为真
    （"无父即顶层"是定义），未显示的卡片也是 True，区分不出问题。真正会闪的
    只有「无父 **且** 可见」——那一刻它就作为一扇真窗口被 map 出来。
    """
    bad: list[str] = []
    for name, make in _card_makers().items():
        w = make()
        try:
            if w.isVisible():
                bad.append(f"{name}: 未入布局就 isVisible=True（无父可见 = 真顶层窗口）")
            if w.parent() is not None:
                bad.append(f"{name}: 构造完竟然已有父控件——判据失效")
        finally:
            w.deleteLater()
    assert not bad, ("卡片工厂在构造期把无父控件显示成了窗口；"
                     "应改为「只在 visible=False 时 hide()」，显示交给入布局时的父控件：\n  "
                     + "\n  ".join(bad))


# ---------- 2. 反方向：入布局后必须能显示 ----------

def test_card_shows_normally_once_parented(qapp):
    """防过纠：入布局后随父显示，visible=False 的保持隐藏且之后可显。"""
    from app.gui.qt_theme import card
    from app.gui.qt_widgets import ShadowCard

    host = QWidget()
    lay = QVBoxLayout(host)
    auto = card(title="默认显示")
    hidden = card(title="先藏后显", visible=False)
    shadow = ShadowCard(title="投影卡")
    for w in (auto, hidden, shadow):
        lay.addWidget(w)
    host.resize(360, 240)
    host.show()
    qapp.processEvents()
    try:
        assert auto.isVisible(), "默认 visible=True 的卡片入布局后应随父显示"
        assert shadow.isVisible(), "ShadowCard 入布局后应随父显示"
        assert not hidden.isVisible(), "visible=False 的卡片必须保持隐藏（语义不变）"
        hidden.setVisible(True)
        qapp.processEvents()
        assert hidden.isVisible(), "隐藏过的卡片之后 setVisible(True) 应能正常显示"
    finally:
        host.close()
        host.deleteLater()


# ---------- 3. 整窗层：切页期间不得有窗口被显示 ----------

def _switch_all_pages(win, qapp, rounds: int = 3) -> None:
    from app.gui.main_window import PAGES

    for _ in range(rounds):
        for key in PAGES:
            win._select_page(key)
            qapp.processEvents()


def test_page_switching_opens_no_ghost_window(qapp, monkeypatch):
    """逐页切换期间，任何控件不得以真顶层窗口形式被显示。"""
    import app.gui.main_window as mw

    monkeypatch.setattr(mw, "CachedApi",
                        lambda *a, **k: OfflineApi(base_url="http://127.0.0.1:8101"))
    win = mw.MainWindow(_Store())
    trap = _GhostWindowTrap([win])
    try:
        win.resize(1180, 800)
        win.show()
        qapp.processEvents()
        # 装机后再装陷阱：只看切页段（启动期的主窗自身 Show 不算）
        qapp.installEventFilter(trap)
        _switch_all_pages(win, qapp)
        # 快切复刻"切页快"的时序：中间不泵满事件循环就继续切
        for _ in range(3):
            win._select_page("mine")
            win._select_page("home")
        qapp.processEvents()
        assert not trap.ghosts, (
            "切页期间有控件以真顶层窗口形式被显示（会一闪而过）——"
            "排查 `setVisible(True)` 落在无父控件上的调用点："
            + ", ".join(sorted(set(trap.ghosts))))
    finally:
        qapp.removeEventFilter(trap)
        win._allow_quit = True
        win.close()
