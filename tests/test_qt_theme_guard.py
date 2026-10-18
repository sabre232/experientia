"""Qt 侧设计护栏（test_theme_guard 的 Qt 版，迁移清单）。

原护栏针对 Flet（ft.Icon / ft.Text / text_align）；Qt 迁移后等价红线：
- R10：Qt 文件禁止裸 hex 颜色（一切走 theme.C）
- 字号表：font-size:Npx / setPixelSize(N) 的字面量必须是 F token 值
#   （28/20/16/14/12；设计家族 ——R9 禁 <12px，10 档已废除）；变量/f-string 插值放行
- 级联作用域：setStyleSheet 字符串禁止裸 ``QWidget {`` / ``QWidget:``
  选择器——Qt 样式表沿子控件级联，会把按钮品牌底/label 透明底顶掉
  （hooks 空态主按钮白底 bug 的根因）。一律用 ``QWidget#objectName``。
  全局 APP_STYLESHEET 是模块常量不走 setStyleSheet 调用，天然豁免。

Qt 文件判定：app/gui/*.py 中 import PySide6 者（Flet 遗留
ui/shell/layout/tray 与 token 定义 theme.py、_mdi_map.py 不在内）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

GUI = Path(__file__).resolve().parents[1] / "app" / "gui"

_SKIP = {"theme.py", "_mdi_map.py"}

HEX_RE = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
F_TOKEN_SIZES = {28, 20, 16, 14, 12}
PX_FONT_RE = re.compile(r"font-size:\s*(\d+)px")
SETPIXEL_RE = re.compile(r"setPixelSize\(\s*(\d+)\s*\)")
SETPOINTSIZE_RE = re.compile(r"setPointSizeF\(\s*(\d+(?:\.\d+)?)\s*\)")
# 裸 QWidget 选择器：QWidget 后直接 { 或:（#id / 类名限定均不匹配）
BARE_QWIDGET_RE = re.compile(r"QWidget\s*[{:]")


def _qt_sources() -> list[tuple[str, str, ast.AST]]:
    out = []
    for p in sorted(GUI.glob("*.py")):
        if p.name in _SKIP:
            continue
        src = p.read_text(encoding="utf-8")
        if "PySide6" not in src:
            continue
        out.append((p.name, src, ast.parse(src)))
    assert out, "未找到任何 Qt 文件（判定逻辑失效？）"
    return out


def _string_constants(node: ast.AST):
    """收集节点子树内所有字符串常量（覆盖 JoinedStr 的 f-string 片段）。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            yield sub.value


def test_no_raw_hex_in_qt_files() -> None:
    """R10：颜色一律走 theme.C token（注释里出现 hex 也算违规——防止
    「先写死再改」的残留）。"""
    for name, src, _tree in _qt_sources():
        for i, line in enumerate(src.splitlines(), 1):
            if HEX_RE.search(line):
                raise AssertionError(
                    f"{name}:{i} 裸 hex 颜色（R10：走 theme.C）: {line.strip()}")


def test_font_sizes_use_tokens() -> None:
    """字号字面量必须是 F token 值（display/h1/h2/body/caption/micro）。"""
    for name, _src, tree in _qt_sources():
        for lineno, s in ((getattr(n, "lineno", 0), c)
                          for n in ast.walk(tree)
                          for c in _string_constants(n)):
            for m in PX_FONT_RE.finditer(s):
                size = int(m.group(1))
                if size not in F_TOKEN_SIZES:
                    raise AssertionError(
                        f"{name}:{lineno} 表外字号 font-size:{size}px"
                        f"（F token: {sorted(F_TOKEN_SIZES)}）")
        # setPixelSize / setPointSizeF 是绕过 txt() 字阶的同一出口
        # （自绘图表/图标也归表内 token，见 qt_widgets.py 柱顶 micro 修复）
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("setPixelSize", "setPointSizeF")
                    and node.args):
                a0 = node.args[0]
                if isinstance(a0, ast.Constant):
                    try:
                        v = int(a0.value)
                    except (TypeError, ValueError):
                        continue
                    if v not in F_TOKEN_SIZES:
                        raise AssertionError(
                            f"{name}:{node.lineno} 表外字号"
                            f" {node.func.attr}({a0.value})"
                            f"（F token: {sorted(F_TOKEN_SIZES)}）")


# P0-3 整改页范围（桌面端UI优化任务清单 -3）：这些页面里的按钮一律
# 走 qt_theme 的 btn_* 工厂；QPushButton(构造器出现即视为"裸按钮"回潮。
# 工厂本体（qt_theme/qt_widgets）、主窗口 chrome、对话框（qt_dialogs）不在范围。
_NO_RAW_BUTTON_FILES = {
    "settings_page.py", "my_experience.py", "experiences.py", "methods.py",
    "failure_modes.py", "preferences_page.py", "connect_page.py",
    "models_page.py", "inject_preview.py", "skill_organize.py", "export_page.py",
}


def test_no_raw_qpushbutton_in_scoped_pages() -> None:
    """P0-3：整改页内禁止裸 QPushButton(——按钮必须来自 btn_* 工厂。"""
    for name, _src, tree in _qt_sources():
        if name not in _NO_RAW_BUTTON_FILES:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "QPushButton"):
                raise AssertionError(
                    f"{name}:{node.lineno} 裸 QPushButton（P0-3：走 qt_theme "
                    f"的 btn_primary/btn_secondary/btn_flat/btn_danger/"
                    f"icon_button 工厂）")


def test_no_bare_qwidget_selector_in_setstylesheet() -> None:
    """setStyleSheet 禁裸 QWidget{} 选择器（级联污染子控件）。

    必须用 QWidget#objectName（或 QFrame/QLabel 等更窄类型）限定作用域。
    """
    for name, _src, tree in _qt_sources():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "setStyleSheet" and node.args):
                continue
            for s in _string_constants(node.args[0]):
                if BARE_QWIDGET_RE.search(s):
                    raise AssertionError(
                        f"{name}:{node.lineno} setStyleSheet 裸 QWidget 选择器"
                        f"（会级联到子控件；用 QWidget#objectName 限定）: "
                        f"{s.strip()[:60]}")


# ---------- 运行时护栏：占位符/禁用文字色（P2-1） ----------

import os  # noqa: E402  （运行时护栏需要 QT_QPA_PLATFORM）

import pytest  # noqa: E402

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def _qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_low_fx_skips_card_shadow(_qapp, monkeypatch) -> None:
    """档 1：`EXPERIENTIA_LOW_FX=1` → 卡片整体跳过投影（纯装饰，fail-open）。

    投影是 CPU 合成的逐控件开销（实测 300 张卡绘制 11 ms → 53 ms，约 5×）；
    默认模式必须保持不变（仍挂 effect），开关只在显式设置时生效。
    """
    from PySide6.QtWidgets import QFrame

    from app.gui import qt_widgets
    from app.gui.theme import low_fx

    monkeypatch.delenv("EXPERIENTIA_LOW_FX", raising=False)
    assert low_fx() is False
    on = QFrame()
    qt_widgets.hover_lift(on)
    assert on.graphicsEffect() is not None, "默认模式必须保留卡片投影"

    monkeypatch.setenv("EXPERIENTIA_LOW_FX", "1")
    assert low_fx() is True
    off = QFrame()
    qt_widgets.hover_lift(off)
    assert off.graphicsEffect() is None, "低特效模式不得挂投影"
    assert not hasattr(off, "_hover_lift_filter"), "低特效模式不得装事件过滤器"


def test_shadow_card_self_draws_without_effect(_qapp, monkeypatch) -> None:
    """档 2：`ShadowCard` 自绘投影——**不挂 QGraphicsDropShadowEffect**
    （省掉 CPU 合成，实测 300 张卡绘制 13 ms → 54 ms），hover 走浓度动画。"""
    from PySide6.QtWidgets import QLabel

    from app.gui import qt_widgets
    from app.gui.qt_widgets import ShadowCard

    monkeypatch.delenv("EXPERIENTIA_LOW_FX", raising=False)
    c = ShadowCard()
    c.layout().addWidget(QLabel("x"))
    qt_widgets.hover_lift(c)
    assert c.graphicsEffect() is None, "档 2 不得挂 effect"
    assert getattr(c, "_hover_lift_filter", None) is not None, "hover 仍须装过滤器"

    c.set_shadow_strength(1.0)
    hi = c._alpha
    c.set_shadow_strength(0.0)
    assert hi > c._alpha, "hover 投影浓度必须大于静止浓度"

    c.resize(240, 80)                      # 走一次真实绘制（含预渲染模糊图）
    assert not c.grab().isNull()
    assert not qt_widgets._shadow_pixmap(240, 80, 0.1, 16).isNull()

    # 低特效开关仍整体跳过（档 1 与档 2 不互斥）
    monkeypatch.setenv("EXPERIENTIA_LOW_FX", "1")
    c2 = ShadowCard()
    qt_widgets.hover_lift(c2)
    assert not hasattr(c2, "_hover_lift_filter")


def test_shadow_pixmap_cache_keys_on_color(_qapp) -> None:
    """档 2：投影图缓存必须把**颜色**计入 key。

    投影基色是 `C.ink_900`，亮色 `#2A1A12` / 暗色 `#F3ECE3`（暗色下投影是"浅色
    浮起"）。缓存是模块级的、跨切肤存活——不含颜色就会在切肤后复用旧色投影。
    """
    from PySide6.QtGui import QColor

    from app.gui import qt_widgets as W

    W._SHADOW_PM_CACHE.clear()
    light = W._shadow_pixmap(60, 30, 0.1, 16, QColor("#2A1A12"))
    dark = W._shadow_pixmap(60, 30, 0.1, 16, QColor("#F3ECE3"))
    assert not light.isNull() and not dark.isNull()
    assert len(W._SHADOW_PM_CACHE) == 2, "颜色未进缓存 key → 切肤后会复用旧色投影"
    # 同色同参复用同一张（缓存生效）
    again = W._shadow_pixmap(60, 30, 0.1, 16, QColor("#2A1A12"))
    assert again is light and len(W._SHADOW_PM_CACHE) == 2


# ---------- UI 统一化第 1 波：共享页头 / 页面骨架（S1/S2）----------

def test_page_header_scale_and_single_padding_source(_qapp) -> None:
    """S1：页头字号只走家族表两档（h1 常规 / h2 嵌入）；title/subtitle 可被重译取回。"""
    from PySide6.QtWidgets import QLabel

    from app.gui.qt_widgets import page_header
    from app.gui.theme import F

    normal = page_header("标题", "副标题")
    t_lbl = normal.findChild(QLabel, "pageTitle")
    assert t_lbl is not None and t_lbl.text() == "标题"
    assert normal.findChild(QLabel, "pageSubtitle").text() == "副标题"
    assert f"font-size: {F.h1}px" in t_lbl.styleSheet(), "常规档须为 h1"

    dense = page_header("标题", dense=True)
    d_lbl = dense.findChild(QLabel, "pageTitle")
    assert f"font-size: {F.h2}px" in d_lbl.styleSheet(), "嵌入档须为 h2"


def test_page_scaffold_owns_padding_not_the_header(_qapp) -> None:
    """S1+S2：「我的经验」64px 叠加留白的根治——顶边留白只由**一处**提供。

    口径：`page_scaffold` 顶边默认 0，顶边 32px 由 `page_header(top=S.s8)` 给。
    两者各加 32 就会叠成 64（历史缺陷）。
    """
    from PySide6.QtWidgets import QVBoxLayout

    from app.gui.page_base import PAGE_SIDE_PAD, page_scaffold
    from app.gui.theme import S

    assert PAGE_SIDE_PAD == S.s8

    lay = QVBoxLayout()
    scroll = page_scaffold(lay)  # 无页头 → 顶边 0（持 scroll 引用，防布局随临时父被回收）
    assert scroll is not None
    m = lay.contentsMargins()
    assert (m.top(), m.left(), m.bottom()) == (0, S.s8, S.s8)

    lay2 = QVBoxLayout()
    scroll2 = page_scaffold(lay2, top=PAGE_SIDE_PAD)  # 无页头的页面显式补顶边
    assert scroll2 is not None
    assert lay2.contentsMargins().top() == S.s8


def test_my_experience_single_top_padding(_qapp) -> None:
    """S6：容器页头给 32px 顶边，子页内容列顶边必须归 0（否则叠成 64px）。"""
    import os

    from PySide6.QtWidgets import QScrollArea

    from app.gui import i18n
    from app.gui.my_experience import MyExperiencePage

    os.environ.setdefault("EXPERIENTIA_HOME", os.path.expanduser("~/.experientia"))
    i18n.load_catalog("zh")

    class _NoApi:
        base = "http://127.0.0.1:8101"

        def __getattr__(self, _n):
            from app.gui.api_client import LocalApiError
            raise LocalApiError("no engine")

    page = MyExperiencePage(_NoApi())
    try:
        checked = 0
        for sub in page._subpages:
            scroll = sub.findChild(QScrollArea)
            assert scroll is not None, f"{type(sub).__name__} 未包滚动区"
            # 结构：inner(QWidget) → outer(QHBoxLayout) → [stretch, content, stretch]
            content = scroll.widget().layout().itemAt(1).widget()
            assert content.layout().contentsMargins().top() == 0, (
                f"{type(sub).__name__} 内容列顶边应为 0（容器页头已给 32px，"
                f"两处各加会叠成 64px）")
            checked += 1
        assert checked >= 5, "应覆盖全部 5 个子页"
    finally:
        page.deleteLater()


# 顶层页页头覆盖率：允许"未接共享页头"的**白名单**（必须写明理由）。
# 用途：防止"只改了一个页面就当全站统一了"这类覆盖缺口悄悄回来。
_PAGE_HEADER_EXEMPT = {
    "home": "首页是「状态面板」不是「功能区」，头部保持状态行形态"
            "（●运行中 + 助手 chip + 最近记录）——一进来先看到"
            "「它在替我干活」，比先看到零信息量的「首页」二字有价值。"
            "保留（配套 A/B 对比见设计说明）。"
            "**这是有意的例外，不是漏做**。",
}


def test_all_top_level_pages_use_shared_page_header(_qapp) -> None:
    """S1 覆盖率：除白名单外，每个顶层页都必须用 `page_header`（有 pageTitle），
    且内容列顶边留白为 0（顶边由页头给，不得两处各加 32）。"""
    import os

    from PySide6.QtWidgets import QLabel, QScrollArea

    from app.gui import i18n
    from conftest import OfflineApi

    os.environ.setdefault("EXPERIENTIA_HOME", os.path.expanduser("~/.experientia"))
    i18n.load_catalog("zh")

    from app.gui import (connect_page, export_page, growth, home, hooks_page,
                         my_experience, settings_page)

    api = OfflineApi(base_url="http://127.0.0.1:8101")
    factories = {
        "home": home.HomePage,
        "mine": my_experience.MyExperiencePage,
        "growth": growth.GrowthPage,
        "hooks": hooks_page.HooksPage,
        "export": export_page.ExportPage,
        "connect": connect_page.ConnectPage,
        "settings": settings_page.SettingsPage,
    }
    missing = []
    for name, cls in factories.items():
        page = cls(api)
        try:
            if name in _PAGE_HEADER_EXEMPT:
                continue
            lbl = page.findChild(QLabel, "pageTitle")
            if lbl is None:
                missing.append(name)
                continue
            from app.gui.theme import F
            assert f"font-size: {F.h1}px" in lbl.styleSheet(), (
                f"{name} 顶层页页头必须是 h1（嵌入档才用 h2）")
            sc = page.findChild(QScrollArea)
            assert sc is not None, f"{name} 未包滚动区"
            content = sc.widget().layout().itemAt(1).widget()
            assert content.layout().contentsMargins().top() == 0, (
                f"{name} 内容列顶边应为 0（顶边由页头给，两处各加会叠成 64px）")
        finally:
            page.deleteLater()
    assert not missing, (
        f"这些顶层页还没接共享页头（应迁移到 page_header，或显式加入白名单并写明理由）："
        f"{missing}")


# ---------- 第 2 波动效：性能纪律守卫（M1/M4）----------

def test_stagger_in_only_moves_pos_and_respects_reduced_motion(_qapp,
                                                              monkeypatch) -> None:
    """M1：错峰入场**只动 pos**（绝不挂 graphicsEffect / 不动模糊），且降级即直出终态。

    `motion_ok()` 在 Windows 读注册表 MinAnimate、在无桌面会话的 CI 上可能为假
    ——故①显式把它钉成 True，否则该用例会"因为宿主静音动效"而假通过。
    """
    from PySide6.QtWidgets import QFrame

    from app.gui import qt_widgets as W

    # ① 正常模式：动画只改 pos，不引入任何 graphicsEffect（刚省掉的开销）
    def _motion() -> bool:
        """与真实 motion_ok 同语义（只看 reduced-motion 开关），保证用例确定。"""
        import os
        return os.environ.get("EXPERIENTIA_REDUCE_MOTION") not in ("1", "true", "on")

    monkeypatch.setattr(W, "motion_ok", _motion)
    monkeypatch.delenv("EXPERIENTIA_REDUCE_MOTION", raising=False)
    monkeypatch.delenv("EXPERIENTIA_LOW_FX", raising=False)
    cards = [QFrame() for _ in range(4)]
    before = [c.pos() for c in cards]
    W.stagger_in(cards, step_ms=0)  # step=0 → 立即起播，测试无需等待
    for c in cards:
        assert c.graphicsEffect() is None, "入场动画不得给控件挂 graphicsEffect"
    assert any(c.pos() != b for c, b in zip(cards, before)), \
        "step=0 时首项应立即被位移（证明动画确实在动 pos）"

    # ② reduced-motion：直接返回，控件原封不动（fail-open：终态呈现）
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    still = [QFrame() for _ in range(3)]
    base = [c.pos() for c in still]
    W.stagger_in(still, step_ms=0)
    assert [c.pos() for c in still] == base, "reduced-motion 下不得位移"
    monkeypatch.delenv("EXPERIENTIA_REDUCE_MOTION", raising=False)

    # ③ low_fx：同样直接返回
    monkeypatch.setenv("EXPERIENTIA_LOW_FX", "1")
    dry = [QFrame() for _ in range(3)]
    base = [c.pos() for c in dry]
    W.stagger_in(dry, step_ms=0)
    assert [c.pos() for c in dry] == base, "低特效模式下不得位移"


def test_primary_and_secondary_buttons_have_hover_and_pressed(_qapp) -> None:
    """M4 + 既有硬约束：交互元素必须同时有 hover 与 pressed 态。

    主 CTA（.primary）此前只有 hover、**没有 pressed**（按下去毫无回执）；
    secondary/flat/danger 更连 hover 都没有——本测试把这两态锁死。
    """
    from app.gui.qt_theme import APP_STYLESHEET

    style = APP_STYLESHEET()
    for cls_name in ("primary", "secondary", "flat", "danger"):
        assert f"QPushButton.{cls_name}:hover" in style, \
            f".{cls_name} 缺 hover 态（违反交互元素 hover 硬约束）"
        assert f"QPushButton.{cls_name}:pressed" in style, \
            f".{cls_name} 缺 pressed 态（按下无回执，M4）"


def test_list_pages_call_stagger_cards_first_screen_only(_qapp,
                                                        monkeypatch) -> None:
    """M1 覆盖：列表页必须调 `stagger_cards`，且**只首屏**触发（轮询刷新不重放）。

    机制验证：`_content_ready` 为假（首屏）→ 卡片被位移（入场生效）；
    置真（已有内容，如 30s 轮询）→ 再调一次**不得**再位移（不重放）。

    `motion_ok()` 在 Windows 读注册表、CI 上可能为假（会让本用例假通过），
    故显式钉成确定语义。
    """
    from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

    from app.gui import qt_widgets as W
    from app.gui.page_base import PageBase

    monkeypatch.setattr(W, "motion_ok", lambda: True)
    monkeypatch.delenv("EXPERIENTIA_LOW_FX", raising=False)

    class _P(PageBase):
        def __init__(self):
            super().__init__(api=None)
            self.rows = QVBoxLayout()
            self.box = QWidget()
            self.box.setLayout(self.rows)

    page = _P()
    page2 = _P()
    try:
        # ① 首屏（_content_ready 默认 False）→ 触发：首项立即被下移一档
        for _ in range(3):
            page.rows.addWidget(QFrame())
        assert page._content_ready is False
        page.stagger_cards(page.rows)
        moved = [page.rows.itemAt(i).widget().pos()
                 for i in range(page.rows.count())]
        assert any(p.y() != 0 for p in moved), "首屏应触发行位移（入场生效）"

        # ② 已渲染过一轮（_content_ready=True）→ 不触发。
        # 用**独立页面**验证，避免①的在飞定时器污染本断言。
        for _ in range(3):
            page2.rows.addWidget(QFrame())
        page2._content_ready = True
        page2.stagger_cards(page2.rows)
        still = [page2.rows.itemAt(i).widget().pos()
                 for i in range(page2.rows.count())]
        assert all(p.y() == 0 for p in still), \
            "已有内容时不得重放入场（否则 30s 轮询整列表重放 = 骚扰）"
    finally:
        page.deleteLater()
        page2.deleteLater()


def test_count_up_writes_final_and_only_uses_text(_qapp, monkeypatch) -> None:
    """M2：数字滚动只改文本（零 graphicsEffect），且降级/异常都**必须落到终值**。

    "绝不把数字留在 0"是本项的 fail-open 底线——降级时若只 setText(start) 就成了
    显示错误数据。
    """
    from app.gui import qt_widgets as W

    def _label():
        from PySide6.QtWidgets import QLabel
        lb = QLabel("0")
        return lb

    def _motion() -> bool:
        import os
        return os.environ.get("EXPERIENTIA_REDUCE_MOTION") not in ("1", "true", "on")

    monkeypatch.setattr(W, "motion_ok", _motion)
    monkeypatch.delenv("EXPERIENTIA_REDUCE_MOTION", raising=False)
    monkeypatch.delenv("EXPERIENTIA_LOW_FX", raising=False)

    # ① reduced-motion：直接写终值（不得停在 0）
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    lb = _label()
    W.count_up(lb, 128)
    assert lb.text() == "128", "降级时必须直接落终值，不能留在 0"
    assert lb.graphicsEffect() is None
    monkeypatch.delenv("EXPERIENTIA_REDUCE_MOTION", raising=False)

    # ② low_fx：同上
    monkeypatch.setenv("EXPERIENTIA_LOW_FX", "1")
    lb2 = _label()
    W.count_up(lb2, 7)
    assert lb2.text() == "7"
    monkeypatch.delenv("EXPERIENTIA_LOW_FX", raising=False)

    # ③ 正常模式：起播后不挂 effect；动画对象挂在 label 上（自回收）
    lb3 = _label()
    W.count_up(lb3, 42)
    assert lb3.graphicsEffect() is None, "数字滚动不得给控件挂 graphicsEffect"
    assert hasattr(lb3, "_count_anim"), "动画对象应挂在 label 上（随控件回收）"

    # ④ 目标非正：直接写终值，不起动画
    lb4 = _label()
    W.count_up(lb4, 0)
    assert lb4.text() == "0"


def test_skeleton_fade_never_effects_the_page(_qapp, monkeypatch) -> None:
    """M3：骨架→内容的交叉过渡**只给骨架那一个控件**挂 opacity effect；
    **整页/滚动区永远不许挂** effect（项目明令禁止的用法），且降级时不留残留浮层。
    """
    import time

    from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

    from app.gui import qt_widgets as W
    from app.gui.page_base import PageBase

    def _motion() -> bool:
        import os
        return os.environ.get("EXPERIENTIA_REDUCE_MOTION") not in ("1", "true", "on")

    monkeypatch.setattr(W, "motion_ok", _motion)
    monkeypatch.delenv("EXPERIENTIA_REDUCE_MOTION", raising=False)
    monkeypatch.delenv("EXPERIENTIA_LOW_FX", raising=False)

    class _P(PageBase):
        def __init__(self):
            super().__init__(api=None)
            self.body = QVBoxLayout()
            self._layout.addLayout(self.body)

    def _run() -> "_P":
        """跑一轮带骨架的取数，**等 render 回调真的执行**（否则骨架还没被处理）。"""
        page = _P()
        fired: list = []
        page.fetch_and_render(lambda: None, lambda _r: fired.append(1),
                              "t", skeleton=[24, 72])
        deadline = time.time() + 5
        while not fired and time.time() < deadline:
            _qapp.processEvents()
            time.sleep(0.01)
        assert fired, "取数回调未执行（骨架路径未走通）"
        for _ in range(4):
            _qapp.processEvents()
        return page

    page = _run()
    page2 = None
    try:
        # 硬要求：整页与任何滚动区都不得挂 effect
        assert page.graphicsEffect() is None, "整页不得挂 graphicsEffect"
        for sc in page.findChildren(QScrollArea):
            assert sc.graphicsEffect() is None, "滚动区不得挂 graphicsEffect"

        # 降级（reduced-motion）时必须瞬时移除、不留残留骨架浮层
        monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
        page2 = _run()
        for _ in range(4):
            _qapp.processEvents()
        leftovers = [w for w in page2.findChildren(QWidget)
                     if w.__class__.__name__ == "SkeletonBlock"]
        assert not leftovers, f"降级时不得残留骨架浮层（剩 {len(leftovers)} 块）"
        assert page2.graphicsEffect() is None
    finally:
        page.deleteLater()
        if page2 is not None:
            page2.deleteLater()


def test_section_title_spec_matches_card(_qapp) -> None:
    """S4：`section()` 的节标题规格必须与 `card(title=…)` **完全一致**。

    全站"节标题"只有一种规格（h2 / 600 / ink_700）——`card(title=)`（约 25 处）与
    各页手写的节标题（hooks/settings/growth/connect）**本来就是这个规格**。
    本用例把新组件与既有约定锁死，防止它引入第 4 种变体（我第一版就误写成 700）。
    """
    from PySide6.QtWidgets import QLabel

    from app.gui.qt_theme import card
    from app.gui.qt_widgets import section

    # 持有容器引用：临时 QFrame 会被 GC 连带释放其 layout（否则读 itemAt 直接炸）
    box_c = card(title="节标题")
    box_s = section(title="节标题")
    card_title = box_c.layout().itemAt(0).widget()
    sec_title = box_s.layout().itemAt(0).widget()
    assert isinstance(card_title, QLabel) and isinstance(sec_title, QLabel)
    assert card_title.styleSheet() == sec_title.styleSheet(), (
        "section() 节标题与 card(title=…) 规格不一致："
        f"\ncard   = {card_title.styleSheet()}"
        f"\nsection= {sec_title.styleSheet()}")
    assert card_title.font().weight() == sec_title.font().weight(), \
        "section() 节标题字重与 card(title=…) 不一致"


def test_placeholder_and_disabled_text_use_ink_500(_qapp) -> None:
    """P2-1：占位符/禁用文字色必须 = ink_500（5.33:1）。

    Qt 的 placeholder 不走样式表（无::placeholder 伪元素），唯一出口是
    应用级 QPalette；apply_text_palette() 是唯一写入点。ink_300（2.34:1）
    禁止出现在正文/占位位置。
    """
    from PySide6.QtGui import QPalette

    from app.gui.qt_theme import apply_text_palette
    from app.gui.theme import C

    apply_text_palette()
    pal = _qapp.palette()
    ph = pal.color(QPalette.PlaceholderText).name().lower()
    assert ph == C.ink_500.lower(), (
        f"占位符文字色应为 ink_500（{C.ink_500}），实际 {ph}（P2-1 红线）")
    dis = pal.color(QPalette.Disabled, QPalette.Text).name().lower()
    assert dis == C.ink_500.lower(), (
        f"禁用文字色应为 ink_500（{C.ink_500}），实际 {dis}（P2-1 红线）")


# ---------- 长文本必须换行（多语言布局红线） ----------

# 内容列可用宽：最小窗口 1000px − 导航栏 − 卡片内边距 ≈ 780px。
# 不换行的 QLabel 会把所在布局的最小宽撑到"整句像素宽"，超过这个值就会
# 出现横向滚动条 + 句尾被省略号截断。
_WRAP_BUDGET_PX = 780

_LOCALES = GUI / "locales"


def _po_map(lang: str) -> dict:
    """读 apps/gui/locales/<lang>/LC_MESSAGES/messages.po → {msgid: msgstr}。"""
    path = _LOCALES / lang / "LC_MESSAGES" / "messages.po"
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    key = val = None
    cur = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("msgid "):
            cur, key, val = "id", raw[6:].strip(), None
        elif raw.startswith("msgstr "):
            cur, val = "str", raw[7:].strip()
        elif raw.startswith('"') and cur:
            if cur == "id":
                key += raw.strip()
            else:
                val = (val or "") + raw.strip()
        elif raw == "" and key is not None:
            out[_unquote(key)] = _unquote(val)
            key = val = None
    return out


def _unquote(s: str | None) -> str:
    if not s:
        return ""
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s.replace('\\"', '"')


def _literal(node) -> str | None:
    """从 AST 抽字面量文本（含 t("…") 包装与 f-string 的字面部分）。"""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call):
        fn = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fn in ("t", "_", "tr") and node.args:
            return _literal(node.args[0])
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant)
                       and isinstance(v.value, str))
    return None


def test_long_prose_labels_wrap_in_all_locales(_qapp) -> None:
    """长散文 `txt()` 必须 `wrap=True`（跨语言布局红线）。

    回归（多页空白/截断的余党）：`txt()` 的 `wrap` 默认**关**。整句散文不换行时，
    标签的最小宽 = 整句像素宽；中文下大多够宽，但**非中文译文明显更长**——实测
    同一句法语/德语可达 1378~1545px（中文仅 ~480px），远超内容列可用宽，表现为
    **横向滚动条 + 句尾被省略号截断**。故按"最长语言译文"设閾值，一次性拦住。
    """
    from PySide6.QtGui import QFont, QFontMetrics

    from app.gui.qt_theme import FONT, ensure_fonts

    ensure_fonts()
    po = {lang: _po_map(lang) for lang in
          (["zh"] + [p.name for p in _LOCALES.glob("*") if p.is_dir()])}
    langs = [k for k in po if k != "zh"]

    def width(text: str, px: int) -> int:
        f = QFont(FONT)
        f.setPixelSize(int(px))   # QSS 的 font-size 单位是 px（不是 pt）
        return QFontMetrics(f).horizontalAdvance(text)

    offenders: list[str] = []
    for fname, _src, tree in _qt_sources():
        # 该文件里"字面量 → 已换行"的变量（含 self.X）
        wrapped: set = set()
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "setWordWrap"
                    and n.args
                    and isinstance(n.args[0], ast.Constant)
                    and n.args[0].value):
                v = n.func.value
                wrapped.add(getattr(v, "id", None) or getattr(v, "attr", None))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = getattr(n.func, "id", None)
            if fn != "txt":
                continue
            # wrap=False 形同没写；只有真值才算已换行
            if any(k.arg == "wrap"
                   and not (isinstance(k.value, ast.Constant)
                            and k.value.value is False)
                   for k in n.keywords):
                continue
            var = None
            for a in ast.walk(tree):
                if isinstance(a, ast.Assign) and a.value is n:
                    tg = a.targets[0]
                    var = getattr(tg, "id", None) or getattr(tg, "attr", None)
                    break
            if var and var in wrapped:
                continue
            zh = _literal(n.args[0] if n.args else None)
            if not zh:
                continue
            px = 14
            if len(n.args) >= 2 and isinstance(n.args[1], ast.Attribute):
                px = getattr(__import__("app.gui.theme", fromlist=["F"]).F,
                             n.args[1].attr, 14)
            worst = width(zh, px)
            worst_lang = "zh"
            for lang in langs:
                tr = po[lang].get(zh)
                if tr and width(tr, px) > worst:
                    worst, worst_lang = width(tr, px), lang
            if worst >= _WRAP_BUDGET_PX:
                offenders.append(
                    f"{fname}:{n.lineno} 最长={worst_lang}:{worst}px "
                    f"(预算 {_WRAP_BUDGET_PX}) «{zh[:30]}»")
    assert not offenders, (
        "以下长散文标签缺 wrap=True，非中文语言下会截断/撑出横向滚动条：\n  "
        + "\n  ".join(offenders))
