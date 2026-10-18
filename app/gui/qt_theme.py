"""Qt 样式表 + 组件工厂（迁移清单 -）。

theme.py 的 Qt 等效实现。所有 token 值（C / R / S / F / D / SIZES）从 theme.py
导入复用，不改值。页面禁止裸 hex / 图标混族 / 表外字号（沿用原护栏纪律）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetrics,
                           QIcon, QPainter, QPixmap, QTextLayout)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QSizePolicy, QTextBrowser,
                               QVBoxLayout, QWidget)

from .theme import C, D, F, R, S, SIZES, FONT
from .i18n import t

_logger = logging.getLogger("experientia.gui.qt_theme")

if TYPE_CHECKING:  # 仅注解用（qt_widgets 反向依赖本模块，运行时不能导入）
    from .qt_widgets import Drawer

# Manrope 内嵌字体注册（CJK 走系统回退，只按名引用）
# 需要 QApplication 已存在。qt_theme 可能先于 QApplication 被导入（测试/工具
# 脚本），一次性注册会永久漏掉：字体库为空 → 全部文本度量归零 → 省略判定失效。
# 故做成幂等函数，在组件构建路径上再兜一次（与 qt_icons 同款写法）。
_FONT_PATH = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "Manrope-Medium.ttf"
_FONT_ID: int | None = None


def ensure_fonts() -> None:
    """幂等注册内嵌字体；QApplication 尚未就绪时本轮跳过，留待下次调用。"""
    global _FONT_ID, FONT
    if _FONT_ID is not None:
        return
    try:
        from PySide6.QtWidgets import QApplication

        if not _FONT_PATH.exists() or QApplication.instance() is None:
            return
        _FONT_ID = -1  # 标记已尝试，避免反复加载
        fid = QFontDatabase.addApplicationFont(str(_FONT_PATH))
        families = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        if families:
            FONT = families[0]
    except Exception:
        pass


ensure_fonts()

_FONT_STACK = f'"{FONT}", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif'

# ======== 全局样式表 ========
# 亮/暗双色板下必须每次现取 C token（见  dark mode），故做成函数而非模块常量：
# 模块导入时冻结亮色，切暗色后重应用仍会是亮色样式表。
#
# 结果按激活色板名缓存（模块级 dict，键 = C.current_mode()），主题切换
# 才重算。字体栈可能在首次调用后才注册完成（ensure_fonts 幂等、QApplication 就绪
# 才生效），故额外用 _STYLESHEET_FONT 记录生成时的字体栈，字体一变即整体作废——
# 否则会缓存住回退字体栈的样式表。

_STYLESHEET_CACHE: dict[str, str] = {}
_STYLESHEET_FONT: str | None = None


def APP_STYLESHEET() -> str:
    global _STYLESHEET_FONT
    ensure_fonts()
    if _STYLESHEET_FONT != _FONT_STACK:
        _STYLESHEET_CACHE.clear()
        _STYLESHEET_FONT = _FONT_STACK
    mode = C.current_mode()
    cached = _STYLESHEET_CACHE.get(mode)
    if cached is not None:
        return cached
    css = f"""
QWidget {{
    font-family: {_FONT_STACK};
    font-size: {F.body}px;
    color: {C.ink_900};
    background: transparent;
}}
QMainWindow, QDialog {{
    background: {C.surface};
}}
QScrollArea {{
    background: {C.surface};
    border: none;
}}
/* 滚动区 viewport：QScrollArea 背景只作用于边框区，内部 viewport 是独立
   QWidget，必须用后代选择器命中——否则滚动页露出系统灰底（脏） */
QScrollArea > QWidget > QWidget {{
    background: {C.surface};
}}
QToolTip {{
    background: {C.surface_2};
    color: {C.ink_900};
    border: 1px solid {C.line};
    padding: 4px 8px;
}}
QPushButton {{
    border: 1px solid {C.line_strong};  /* 交互控件描边：line 在米白底上过浅（用户反馈"边缘线太浅"） */
    border-radius: {R.md}px;
    padding: 6px 16px;
    background: {C.surface};
    color: {C.ink_900};
    font-size: {F.body}px;
}}
QPushButton:hover {{
    background: {C.surface_2};
}}
QPushButton:pressed {{
    background: {C.surface_3};
}}
QPushButton:disabled {{
    color: {C.ink_300};
    background: {C.surface_2};
    border-color: {C.line};
}}
QPushButton.primary {{
    background: {C.primary_fill};
    color: {C.on_brand};
    border: 1px solid {C.brand_600};  /* 同色系细描边：胶囊轮廓扎实，hover 不露毛边 */
    font-weight: 600;
}}
QPushButton.primary:hover {{
    background: {C.primary_fill_hover};
}}
/* M4 按下反馈：主 CTA 明确"按下去"（比 hover 更深一档）。
   QSS 伪态是即时的（按下本就该即时回执），零动画开销——不引动效到刚优化掉的路径。 */
QPushButton.primary:pressed {{
    background: {C.primary_fill_pressed};
}}
QPushButton.danger {{
    color: {C.err_fg};
    border-color: {C.err_fg};
}}
QPushButton.danger:hover {{
    background: {C.err_bg};
}}
QPushButton.danger:pressed {{
    background: {C.err_bg};
    border-color: {C.err_fg};
}}
QPushButton.secondary {{
    color: {C.brand_700};
    font-weight: 600;  /* 边框继承基础 QPushButton（line_strong）；走类选择器，勿用 widget 级 setStyleSheet（会压掉描边） */
}}
QPushButton.secondary:hover {{
    background: {C.brand_50};
}}
QPushButton.secondary:pressed {{
    background: {C.brand_100};
}}
QPushButton.flat {{
    border: none;
    background: transparent;
    color: {C.brand_700};
    font-weight: 600;
}}
QPushButton.flat:hover {{
    background: {C.surface_2};
}}
QPushButton.flat:pressed {{
    background: {C.surface_3};
}}
/* 胶囊按钮（次级但需被看见的入口，如总况条「去管理」）：无硬边框，brand_50 底
   + brand_700 字；全圆角 999px（Qt 自动夹到高/2，恒为真胶囊，不随按钮高变方）。
   视觉可见但弱于实心主 CTA（.primary）。 */
QPushButton.pill {{
    border: none;
    background: {C.brand_50};
    color: {C.brand_700};
    font-weight: 600;
    border-radius: 999px;
    padding: 6px 16px;
}}
QPushButton.pill:hover {{
    background: {C.brand_100};
}}
QPushButton.pill:pressed {{
    background: {C.brand_100};
}}
QLineEdit, QComboBox, QTextEdit, QPlainTextEdit {{
    border: 1px solid {C.line_strong};  /* 交互控件描边（同按钮口径） */
    border-radius: {R.sm}px;
    padding: 6px 12px;
    background: {C.surface};
    color: {C.ink_900};
    font-size: {F.body}px;
    selection-background-color: {C.brand_100};
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {C.brand_400};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background: {C.surface};
    color: {C.ink_900};
    border: 1px solid {C.line};
    selection-background-color: {C.brand_100};
    selection-color: {C.ink_900};
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {C.line_strong};  /* 复选框是选项控件，同按钮口径 */
    border-radius: 3px;
    background: {C.surface};
}}
QCheckBox::indicator:hover {{
    border-color: {C.brand_400};
}}
QCheckBox::indicator:checked {{
    background: {C.primary_fill};
    border-color: {C.primary_fill};
}}
QCheckBox::indicator:checked:hover {{
    background: {C.primary_fill_hover};
    border-color: {C.primary_fill_hover};
}}
QCheckBox::indicator:disabled {{
    background: {C.surface_2};
    border-color: {C.ink_300};
}}
QTabWidget::pane {{
    border: 1px solid {C.line};
    border-radius: {R.md}px;
    top: -1px;
}}
QTabBar::tab {{
    padding: 8px 18px;
    border: 1px solid {C.line};
    border-bottom: none;
    background: {C.surface_2};
    color: {C.ink_500};
    border-top-left-radius: {R.sm}px;
    border-top-right-radius: {R.sm}px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {C.surface};
    color: {C.brand_700};
    font-weight: 600;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {C.line};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C.ink_300};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {C.line};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QMenu {{
    background: {C.surface};
    color: {C.ink_900};
    border: 1px solid {C.line};
    border-radius: {R.md}px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 24px 6px 16px;
    border-radius: {R.sm}px;
}}
QMenu::item:selected {{
    background: {C.brand_100};
}}
QStatusBar {{
    background: {C.surface_2};
    color: {C.ink_500};
    border-top: 1px solid {C.line};
}}
QPushButton:focus {{
    outline: none;
    border: 1px solid {C.brand_400};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {C.brand_400};
}}
"""
    _STYLESHEET_CACHE[mode] = css
    return css


def apply_text_palette() -> None:
    """占位符/禁用文字色：QPalette → ink_500（P2-1 红线：正文/占位位置 5.33:1）。

    Qt 的 placeholder 文字不走样式表（无::placeholder 伪元素），唯一出口是
    应用级 QPalette；必须在每次取 C token 后调用（切亮/暗色板后重取，
    模块导入时冻结的亮色值在暗色下会失配）。
    """
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    pal = app.palette()
    pal.setColor(QPalette.PlaceholderText, QColor(C.ink_500))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(C.ink_500))
    app.setPalette(pal)


def NAV_BUTTON_STYLE() -> str:
    """导航按钮样式（设计方案六态矩阵 + 胶囊浮起改版）。

    默认→透明底 C.ink_700；hover→C.surface_2 胶囊 C.ink_900；按下→C.surface_3；
    选中→C.brand_50 底 C.brand_700 W600；焦点→1px C.brand_400 描边不跳版。
    背景收腰成胶囊（radius 20 = 导航行高 40 的一半），左右 8px 呼吸边，
    橙色只出现在选中胶囊（「橙只表活跃」铁律）。文字由子 QLabel 渲染
    （NavButton 清空自身 text）；对齐由 NavButton 子布局的 margins 决定。"""
    return f"""
QPushButton {{
    padding: 0 8px;
    border: 1px solid transparent;
    border-radius: {20}px;
    font-size: {F.body}px;
    color: {C.ink_700};
    background: transparent;
}}
QPushButton:hover {{
    background: {C.surface_2};
    border-radius: {20}px;
    color: {C.ink_900};
}}
QPushButton:pressed {{
    background: {C.surface_3};
}}
QPushButton:checked {{
    background: {C.brand_50};
    color: {C.brand_700};
    font-weight: 600;
}}
QPushButton:focus {{
    border: 1px solid {C.brand_400};
}}
"""


def DIVIDER_STYLE() -> str:
    return (f"QFrame {{ border: none; border-top: {D.BORDER_W}px solid {C.line};"
            f" margin: {S.s1}px {S.s3}px; }}")


# ======== 文本 ========

def txt(content: str, size: int = F.body, weight: int = 400,
        color: str | None = None, **kw) -> QLabel:
    """全部文本的唯一出口（对应 theme.txt）。

    weight 用 QFont.Weight 数值（400/500/600/700/800）。
    color 缺省在**调用时**解析为 C.ink_900（签名默认值会冻结亮色，
    暗色模式下默认文字会失配——见  dark mode）。
    """
    if color is None:
        color = C.ink_900
    if size not in (F.display, F.h1, F.h2, F.body, F.caption, F.micro):
        raise ValueError(f"字号 {size} 不在家族表内（{F.__dict__}）")
    ensure_fonts()  # 构建文本即兜一次字体注册（QApplication 已存在的场合）
    label = QLabel(content)
    font = QFont(FONT, size)
    font.setWeight(QFont.Weight(int(weight)))  # PySide6 6.11: setWeight 只收 enum
    label.setFont(font)
    selectable = bool(kw.pop("selectable", False))
    if selectable:
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    # font-size 必须走内联样式表：全局 QWidget{font-size} 优先级高于 setFont，
    # 只 setFont 会被压回 body 14px（六级字阶塌成一级）。内联样式优先级最高。
    label.setStyleSheet(
        f"color: {color}; border: none; background: transparent;"
        f" font-size: {size}px;")
    if kw.get("italic"):
        font.setItalic(True)
        label.setFont(font)
    if kw.get("wrap"):
        label.setWordWrap(True)
    return label


class ClampedLabel(QLabel):
    """N 行省略文本（Qt 官方 ElidedLabel 套路的 PySide6 移植）。

    继承 QLabel（与 txt() 同族：文本控件即 QLabel），findChildren(QLabel)/.text()
    能直接取到标题全文。内部不设 QLabel 文本（保持空→sizeHint 紧凑），由
    paintEvent 用 QTextLayout 自绘省略文本；text() 返回全文供外部检视。

        QLabel 只支持单行 elide；这里在 paintEvent 用 QTextLayout 按控件宽度折行，
    前 (max_lines-1) 行整行画，最后一行若仍溢出则走 QFontMetrics.elidedText
    (…, ElideRight) 收尾补 "…"。CJK 由 QTextLayout 按字断行（中文无空格，
    QFontMetrics 贪心切词会切错）。高度按实际占用的行数算、max_lines 只作上限，
    短文本不留空行；同一张卡里各条高度各自贴合内容。

    兜底机制（结构性，不依赖调用方是否传来 *_raw）：只要展示文本被省略，或
    另给了更长的全文（full），本控件自动可点——手型光标 + "点击展开全文"，
    点一下展开显示全文、再点收起；展开高度按实际行数自适应，卡片跟着长高。
    没被省略且无更长全文时纯静态，无光标变化。宽度变化（窗口缩放）会重新
    判定，省略状态不会漏。文本永不"只剩前几行且无出路"。
    字体走 self.font()（QLabel 同款解析），字号/字重由工厂内联样式表锁像素
    ——与 txt() 完全同口径，CJK 回退一致，标题不再比正文大一截、字体不同。
    """

    def __init__(self, max_lines: int = 2, parent: QWidget | None = None):
        super().__init__(parent)
        self._max_lines = max(1, max_lines)
        self._display = ""     # 默认展示文本（可能被省略）
        self._full = ""        # 展开后显示的全文
        self._color: str | None = None
        self._expanded = False
        self._overflow = False
        self._expandable = False
        self._line_spacing = 0
        self._refreshing = False
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_content(self, text: str, full: str | None = None) -> None:
        """展示文本 text（超出 max_lines 时省略）；full 为展开后显示的全文，
        缺省同 text（此时"展开"即看全同一段被省略的文字）。"""
        self._display = text or ""
        self._full = (full if full is not None else text) or ""
        self._expanded = False
        self._refresh()

    def text(self) -> str:
        return self._display

    def full_text(self) -> str:
        return self._full

    def is_expanded(self) -> bool:
        return self._expanded

    def is_expandable(self) -> bool:
        """当前是否有被藏起来的文字（省略了 display，或另有更长的 full）。"""
        return self._expandable

    def is_omitted(self) -> bool:
        """展示文本是否真的超出行数上限（被省略）。省略必可展开 = 硬不变量。"""
        return self._overflow

    def _line_count(self, text: str, width: int) -> int:
        """按 width 折行算实际行数（与 paintEvent 同口径的 QTextLayout）。"""
        if not text or width <= 0:
            return 0
        layout = QTextLayout(text, self.font())
        layout.beginLayout()
        n = 0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            n += 1
            if n >= 500:  # 病态超长文本的保险丝，别卡住 UI 线程
                break
        layout.endLayout()
        return n

    def _refresh(self) -> None:
        """重算省略 / 可展开状态并同步高度、光标、提示。"""
        if self._refreshing:
            return
        self._refreshing = True
        try:
            fm = QFontMetrics(self.font())
            self._line_spacing = fm.lineSpacing()
            width = self.width()
            self._overflow = self._line_count(self._display, width) > self._max_lines
            has_longer_full = (self._full.strip() != self._display.strip())
            self._expandable = self._overflow or has_longer_full
            if self._expanded:
                lines = max(1, self._line_count(self._full, width))
            else:
                # max_lines 是上限而非固定高：只按实际占用的行数占高，
                # 短标题/短字段不留空行（否则卡片里出现大片空白）。
                lines = min(max(1, self._line_count(self._display, width)),
                            self._max_lines)
            self.setFixedHeight(lines * self._line_spacing)
            if self._expandable:
                self.setCursor(Qt.PointingHandCursor)
                self.setToolTip(t("点击收起") if self._expanded
                                else t("点击展开全文"))
            else:
                self.setCursor(Qt.ArrowCursor)
                self.setToolTip("")
            self.update()
        finally:
            self._refreshing = False

    def _apply(self, font: QFont, color: str, size: int, weight: int) -> None:
        ensure_fonts()
        self._color = color
        self.setFont(font)
        # 与 txt() 同口径：内联样式表锁像素字号 + 字重（样式表只改 size/weight，
        # 字体族仍走 setFont 的 Manrope）。CJK 回退因此与正文 QLabel 完全一致。
        self.setStyleSheet(
            f"color: {color}; border: none; background: transparent;"
            f" font-size: {size}px; font-weight: {int(weight)};")
        self._refresh()

    def resizeEvent(self, event) -> None:
        """宽度变了，省略行数跟着变——重新判定，省略状态不漏。"""
        super().resizeEvent(event)
        self._refresh()

    def mousePressEvent(self, event) -> None:
        if self._expandable and event.button() == Qt.LeftButton:
            self._expanded = not self._expanded
            self._refresh()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        text = self._full if self._expanded else self._display
        if not text:
            return
        font = self.font()  # 走 QLabel 同款字体解析，CJK 回退与正文一致
        painter = QPainter(self)
        painter.setFont(font)
        if self._color:
            painter.setPen(QColor(self._color))
        fm = painter.fontMetrics()
        line_spacing = fm.lineSpacing()
        layout = QTextLayout(text, font)
        layout.beginLayout()
        y = 0
        i = 0
        # 展开态不设行上限（画到文本结束）；收起态最后一行溢出则以 … 收尾
        limit = None if self._expanded else self._max_lines
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(self.width())
            if limit is None or i < limit - 1:
                line.draw(painter, QPoint(0, y))
                y += line_spacing
                i += 1
            else:
                start = line.textStart()
                overflow = layout.createLine().isValid()
                if overflow:
                    elided = fm.elidedText(text[start:],
                                           Qt.ElideRight, self.width())
                    painter.drawText(QPoint(0, y + fm.ascent()), elided)
                else:
                    line.draw(painter, QPoint(0, y))
                break
        layout.endLayout()
        painter.end()


def txt_clamped(content: str, size: int = F.h2, weight: int = 600,
                color: str | None = None, max_lines: int = 2,
                full: str | None = None) -> ClampedLabel:
    """N 行省略标题的唯一出口（ClampedLabel 工厂，对应 txt()）。

    字体与 txt() 完全同口径：Manrope 族 + 内联样式表锁像素字号/字重；
    setPixelSize 锁像素（QFont 第二参是 point size，直接用会偏大 ~1/3），
    CJK 回退与正文一致。被省略即自动可点展开（看全同一段文字）；full 更长时
    展开显示 full（下钻原文）。
    """
    if color is None:
        color = C.ink_900
    if size not in (F.display, F.h1, F.h2, F.body, F.caption, F.micro):
        raise ValueError(f"字号 {size} 不在家族表内（{F.__dict__}）")
    ensure_fonts()
    font = QFont(FONT, size)
    font.setPixelSize(size)  # QFont(FONT, size) 的 size 是 point size，锁回像素
    font.setWeight(QFont.Weight(int(weight)))
    lab = ClampedLabel(max_lines=max_lines)
    lab._apply(font, color, size, weight)
    lab.set_content(content, full)
    return lab


def expandable_clamped(short: str, full: str, size: int = F.h2, weight: int = 600,
                       color: str | None = None, max_lines: int = 2) -> QWidget:
    """可展开省略文本：默认按 max_lines 展示 short（蒸馏压出的一句结论）；
    short 被省略、或 full 比 short 长（原文更长）时整块可点——点击展开显示
    full（换行、自适应高），再点收起。解决"两行显示不全"。

    展开判定、光标与高度全在 ClampedLabel 内维护：调用方就算没传 *_raw
    （老数据），只要 short 被省略一样能点开看全。"""
    if color is None:
        color = C.ink_900
    full_text = (full or "").strip() or short
    return txt_clamped(short, size, weight, color, max_lines, full=full_text)


def status_text(msg: str = "", tone: str = "err") -> QLabel:
    """行内状态行（caption 级、语义色）。"""
    colors = {"ok": C.ok_fg, "err": C.err_fg, "warn": C.warn_fg, "info": C.info_fg}
    return txt(msg, F.caption, color=colors[tone])


def status_tone(label: QLabel, color: str) -> None:
    """状态文本改色：保留 txt() 内联字号。

    setStyleSheet 是整表覆写，只传 color 会把内联 font-size 冲掉塌回 14px；
    状态文本统一走本函数改色（维护 caption 级字阶）。
    """
    label.setStyleSheet(
        f"color: {color}; background: transparent; border: none;"
        f" font-size: {F.caption}px;")


def mono(content: str, color: str | None = None) -> QLabel:
    """等宽数据块文本（monospace 功能字体，豁免 txt 工厂）。

    color 缺省在调用时解析（避免冻结亮色，见  dark mode）。
    """
    if color is None:
        color = C.ink_700
    label = QLabel(content)
    # QFont 不解析逗号分隔字体族列表（整串当一个名字），只能给单一族名；
    # 族名回退链交给样式表（那里 "Consolas", "Menlo", monospace 是合法语法）。
    label.setStyleSheet(
        f"color: {color}; background: transparent; border: none;"
        f' font-family: "Consolas", "Menlo", monospace; font-size: {F.caption}px;')
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


# ======== Markdown 富文本 ========

class _MarkdownView(QTextBrowser):
    """只读 Markdown 视图：高度随内容自适应（卡片内嵌不截断、不出滚动条）。

    QTextBrowser 默认带视口与滚动条，嵌进卡片会撑出固定高或截断正文；
    这里关掉双向滚动条、按 document 实际高度锁高，内容多高卡片多高。
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setStyleSheet("background: transparent; border: none;")
        self.document().documentLayout().documentSizeChanged.connect(
            self._sync_height)

    def _sync_height(self, *_args) -> None:
        w = self.viewport().width()
        if w <= 0:
            return
        doc = self.document()
        doc.setTextWidth(w)
        self.setFixedHeight(int(doc.size().height()) + S.s1)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._sync_height()


_MD_CSS_CACHE: dict[tuple[str, bool], str] = {}


def _md_css(compact: bool) -> str:
    """Markdown 正文样式串（按「激活色板 + compact」缓存，同 ``APP_STYLESHEET`` 口径）。

    同一模式下每次 ``md_view`` 拼出的串完全相同，却要交给 Qt 重新解析一次；
    列表页每张卡一个 ``md_view``，方法/经验卡一多就是几十次重复解析。故按
    ``(C.current_mode(), compact)`` 缓存，主题切换时自然换键。
    """
    key = (C.current_mode(), compact)
    cached = _MD_CSS_CACHE.get(key)
    if cached is not None:
        return cached
    h1 = F.h2 if compact else F.h1
    h2 = F.body if compact else F.h2
    h3 = F.body
    body = F.caption if compact else F.body
    css = f"""
    h1 {{ font-size: {h1}px; color: {C.ink_900}; margin: {S.s2}px 0; }}
    h2 {{ font-size: {h2}px; color: {C.ink_900}; margin: {S.s2}px 0; }}
    h3 {{ font-size: {h3}px; color: {C.ink_700}; margin: {S.s1}px 0; }}
    p, li {{ font-size: {body}px; color: {C.ink_700}; }}
    code, pre {{
        font-family: "Consolas", "Menlo", monospace;
        font-size: {body}px;
        background: {C.surface_2};
        color: {C.ink_700};
        border: 1px solid {C.line};
        border-radius: {R.sm}px;
        padding: {S.s1}px {S.s2}px;
    }}
    blockquote {{
        border-left: {SIZES.EXPORT_ACCENT_WIDTH}px solid {C.brand_500};
        margin: {S.s1}px 0;
        padding-left: {S.s3}px;
        color: {C.ink_500};
    }}
    table {{ border-collapse: collapse; }}
    th, td {{
        border: 1px solid {C.line};
        padding: {S.s1}px {S.s2}px;
        font-size: {body}px;
    }}
    a {{ color: {C.brand_700}; text-decoration: none; }}
    """
    _MD_CSS_CACHE[key] = css
    return css


def md_view(md: str, *, compact: bool = False,
            selectable: bool = True) -> QTextBrowser:
    """Markdown 富文本只读视图（阅读态正文的唯一出口）。

    关键顺序：**先** ``document().setDefaultStyleSheet(css)``，**再** ``setMarkdown``
    ——顺序反了样式不生效（Qt 在解析时套用默认样式表）。CSS 全令牌化，
    禁裸 hex / 表外字号。

    fail-open（硬要求）：``setMarkdown`` 抛异常 → 回退 ``setPlainText(md)``；
    再失败 → 保持空文本并记 warning，**绝不把异常抛给调用方**（阅读态渲染
    失败不该拖垮整页）。

    compact=True 整体降一档字号（卡片内嵌用）。

     的编辑态仍用 ``code_box()``（纯文本编辑器，可编辑）；本函数只服务
    阅读态。
    """
    browser = _MarkdownView()
    if not selectable:
        browser.setTextInteractionFlags(Qt.NoTextInteraction)
    css = _md_css(compact)
    text = md or ""
    try:
        browser.document().setDefaultStyleSheet(css)
        browser.setMarkdown(text)
    except Exception as exc:  # noqa: BLE001 阅读态渲染失败必须 fail-open
        _logger.warning("md_view: setMarkdown 失败，回退纯文本: %s", exc)
        try:
            browser.setPlainText(text)
        except Exception as exc2:  # noqa: BLE001 连纯文本都失败 → 留空不抛
            _logger.warning("md_view: 纯文本回退也失败，留空: %s", exc2)
            try:
                browser.clear()
            except Exception:
                pass
    return browser


# ======== 内容溯源条 ========

def provenance_bar(state: dict) -> QWidget | None:
    """内容溯源/降级提示条：无模型时告知"内容为上次生成、接入后可更新"。

    state = {"content_source": "model"|"none"|"", "generated_at": str,
             "has_content": bool}

    - ``content_source`` 为 "model"（模型生成）或 ""（旧数据、来源未知）→ None
      （不挂条；：旧卡无字段视为未知，不打扰）。
    - "none" 且无内容 → None（空状态由页面自己渲染）。
    - "none" 且有内容 → 返回提示条：``未接入模型 · 内容为 {时间} 生成 · 接入后可更新``
      （取不到 generated_at 则省略时间部分）。

    视觉：次级底 + 左侧 3px 语义色条（口径同 EXPORT_ACCENT_WIDTH），caption 字号。
    """
    src = str((state or {}).get("content_source") or "")
    if src != "none":
        return None
    if not bool((state or {}).get("has_content")):
        return None
    generated_at = str((state or {}).get("generated_at") or "").strip()
    if generated_at:
        # 占位符名 at 而非 t：t 是翻译函数名，同名占位符被误写成位置传参时
        # 会把函数本身格式化进正文。
        text = t("未接入模型 · 内容为 {at} 生成 · 接入后可更新").format(
            at=generated_at)
    else:
        text = t("未接入模型 · 内容为上次生成 · 接入后可更新")
    bar = QFrame()
    bar.setObjectName("provenanceBar")
    bar.setStyleSheet(
        f"QFrame#provenanceBar {{ background: {C.surface_2}; border: none;"
        f" border-left: {SIZES.EXPORT_ACCENT_WIDTH}px solid {C.warn_fg};"
        f" border-radius: {R.sm}px; }}")
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(S.s3, S.s2, S.s3, S.s2)
    lay.setSpacing(S.s2)
    lay.addWidget(txt(text, F.caption, color=C.ink_700), 1)
    return bar


# ======== 图标 ========

def icon_widget(name: str, size: int = 24, color: str | None = None) -> QLabel:
    """线性图标唯一出口（对应 theme.icon）。见 qt_icons.py。"""
    from .qt_icons import icon_widget as _iw

    return _iw(name, size, color)


def _three_dot_icon(size: int = 16, color: str | None = None) -> QIcon:
    """用 QPainter 画可靠的 3 点"更多"图标（字体字形 U+22EF 在某些字体下缺失，
    改像素绘制保证渲染；对应卡片右上「⋯」）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color or C.ink_500))
    r = size * 0.09
    cx, cy = size / 2.0, size / 2.0
    gap = size * 0.28
    for dx in (-gap, 0.0, gap):
        p.drawEllipse(QPointF(cx + dx, cy), r, r)
    p.end()
    return QIcon(pm)


def ellipsis_button(tooltip: str = "", size: int = 32) -> QPushButton:
    """卡片右上「⋯」操作按钮：真实 3 点图标 + 常驻可见底（不依赖悬浮才暴露），
    回应"⋮ 不够显眼"。hover 加深背景。"""
    b = QPushButton()
    b.setFixedSize(size, size)
    b.setCursor(Qt.PointingHandCursor)
    b.setIcon(_three_dot_icon(size - 10))
    b.setIconSize(QSize(size - 10, size - 10))
    if tooltip:
        b.setToolTip(tooltip)
    radius = max(6, int(size * 0.3))
    b.setStyleSheet(
        f"QPushButton {{ background: {C.surface_2};"
        f" border: 1px solid {C.line}; border-radius: {radius}px; }}"
        f" QPushButton:hover {{ background: {C.surface_3};"
        f" border-color: {C.line_strong}; }}"
        f" QPushButton:pressed {{ background: {C.surface}; }}")
    return b


# ======== 容器 ========

def chip(label: str, tone: str = "brand", icon_name: str | None = None) -> QFrame:
    """chip 标签（对应 theme.chip）。"""
    bg_map = {"brand": C.brand_100, "ok": C.ok_bg, "warn": C.warn_bg,
              "err": C.err_bg, "info": C.info_bg, "ink": C.surface_2}
    fg_map = {"brand": C.ink_700, "ok": C.ok_fg, "warn": C.warn_fg,
              "err": C.err_fg, "info": C.info_fg, "ink": C.ink_500}
    bg, fg = bg_map[tone], fg_map[tone]
    frame = QFrame()
    frame.setStyleSheet(
        f"QFrame {{ background: {bg}; border: none; border-radius: {R.sm}px; }}")
    lay = QHBoxLayout(frame)
    lay.setContentsMargins(D.CHIP_PAD_X, D.CHIP_PAD_Y, D.CHIP_PAD_X, D.CHIP_PAD_Y)
    lay.setSpacing(S.s1)
    if icon_name:
        lay.addWidget(icon_widget(icon_name, 18, fg))
    lay.addWidget(txt(label, F.caption, 600, fg))
    # 不随父布局拉伸：chip 是自适应内容尺寸的小标签，禁止被 setWidgetResizable
    # 的视口多余空间撑成巨条（P0 首页根因之一）
    frame.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
    return frame


def status_dot(tone: str = "ok", size: int | None = None) -> QLabel:
    """语义状态圆点（D.DOT 正圆 + 语义色）。

    接入页设计优化方案：三色语义圆点 + 文字标签。圆点**必须**与文字
    标签/chip 搭配出现（可访问性：不能只靠颜色）。tone ∈
    ok(正常绿) / warn(需注意黄) / err(错误红) / info(蓝) / brand(橙=活跃) /
    ink(中性灰)。橙色只表活跃（Orange-as-live-only 铁律），需注意用 warn 黄。
    """
    colors = {"ok": C.ok_fg, "warn": C.warn_fg, "err": C.err_fg,
              "info": C.info_fg, "brand": C.brand_700, "ink": C.ink_500}
    s = size or D.DOT
    dot = QLabel()
    dot.setFixedSize(s, s)
    dot.setStyleSheet(
        f"background: {colors.get(tone, C.ink_500)};"
        f" border-radius: {s // 2}px; border: none;")
    return dot


def drawer(title: str, parent: QWidget, on_close=None) -> "Drawer":
    """右侧详情抽屉工厂。

    返回 qt_widgets.Drawer（parent 的子控件，覆盖其右缘）；调用方
    ``set_content`` 填详情、``show_open`` 滑入、``close_drawer`` 滑出。
    父容器必须已入窗（有真实尺寸）才能正确贴右缘定位。
    """
    from .qt_widgets import Drawer

    return Drawer(title, parent, on_close)


def card(content: QWidget | None = None, title: str | None = None,
         padding: int = S.s4, secondary: bool = False,
         visible: bool = True) -> QFrame:
    """标准卡片：米底 + 1px 暖描边 + 圆角 16（对应 theme.card）。

    返回 QFrame，用 frame.layout().addWidget(...) 追加内容。
    """
    frame = QFrame()
    frame.setStyleSheet(f"""
        QFrame {{
            background: {C.surface_2 if secondary else C.surface};
            border: 1px solid {C.line_strong};
            border-radius: {R.lg}px;
        }}
    """)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(padding, padding, padding, padding)
    lay.setSpacing(S.s3)
    if title:
        lay.addWidget(txt(title, F.h2, 600, C.ink_700))
    if content is not None:
        lay.addWidget(content)
    # 只在「要隐藏」时显式隐藏：构造期尚未入布局，此时 setVisible(True) 会把
    # 无父控件显示成真正的顶层窗口（闪窗来源）。默认显示交给入布局时的父控件。
    if not visible:
        frame.hide()
    return frame


def divider() -> QFrame:
    """水平分隔线。"""
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("color: %s; background: %s;" % (C.line, C.line))
    line.setFixedHeight(D.BORDER_W)
    return line


# ======== 按钮 ========

def _apply_btn_icon(btn: QPushButton, icon_name: str | None,
                    icon_color: str | None) -> None:
    """给按钮装真图标：MDI 字体图标不能走 setIcon（需 QIcon），
    用按钮内 QHBoxLayout（图标 + 文本）渲染。icon_name 支持
    Flet 常量名（自动经 FT 映射）或 MDI kebab-case 名；未命中字体则退回纯文本。"""
    from .qt_icons import FT, MDI

    if not icon_name:
        return
    if FT.get(icon_name, icon_name) not in MDI:
        return
    lay = QHBoxLayout(btn)
    lay.setContentsMargins(S.s2, 0, S.s3, 0)
    lay.setSpacing(S.s1)
    color = icon_color or C.ink_900
    ic = icon_widget(icon_name, 18, color)  # 18 ∈ ICON_SIZES；内部经 FT 映射
    text = btn.text()
    lab = QLabel(text)
    lab.setStyleSheet(f"color: {color}; background: transparent; border: none;")
    lay.addWidget(ic, 0, Qt.AlignVCenter)
    lay.addWidget(lab, 0, Qt.AlignVCenter)
    lay.setAlignment(Qt.AlignCenter)
    # 文字改由子 QLabel 渲染：清掉按钮自身 text，消除"按钮绘一遍 + 子标签
    # 再绘一遍"的双绘重影
    btn.setText("")
    # QPushButton.sizeHint 只按自身 text 算宽，清空后会忽略子布局里的文本；
    # 父布局按偏小的 sizeHint 分配宽度 → 子 QLabel 被挤压、文字被裁。
    # 按内容宽度补最小宽：图标 + 间距 + 文本 + 左右内边距。
    fm = lab.fontMetrics()
    btn.setMinimumWidth(
        S.s2 + 18 + S.s1 + fm.horizontalAdvance(text) + S.s3)


def btn_primary(label: str, icon_name: str | None = None,
                on_click=None) -> QPushButton:
    """主按钮：brand-700 底白字，每屏最多一个（deck）。"""
    btn = QPushButton(label)
    btn.setProperty("class", "primary")
    btn.setFixedHeight(D.BTN_H)
    _apply_btn_icon(btn, icon_name, C.on_brand)
    if on_click:
        btn.clicked.connect(on_click)
    return btn


def btn_secondary(label: str, icon_name: str | None = None,
                  on_click=None) -> QPushButton:
    """次按钮：描边 + brand-700 文字。

    用 setProperty("class","secondary") 走应用级类选择器取样式——边框继承
    基础 QPushButton（line_strong）。若改用 widget 级 setStyleSheet，Qt 会用
    widget 样式压掉应用级 QPushButton 的 border，导致描边丢失（"按键框线没了"）。
    """
    btn = QPushButton(label)
    btn.setProperty("class", "secondary")
    btn.setFixedHeight(D.BTN_H)
    _apply_btn_icon(btn, icon_name, C.brand_700)
    if on_click:
        btn.clicked.connect(on_click)
    return btn


def btn_danger(label: str, icon_name: str | None = None,
               on_click=None) -> QPushButton:
    """危险按钮：描边 + err 色文字。"""
    btn = QPushButton(label)
    btn.setProperty("class", "danger")
    btn.setFixedHeight(D.BTN_H)
    _apply_btn_icon(btn, icon_name, C.err_fg)
    if on_click:
        btn.clicked.connect(on_click)
    return btn


def btn_flat(label: str, on_click=None) -> QPushButton:
    """文字按钮（对应 ft.TextButton）。"""
    btn = QPushButton(label)
    btn.setProperty("class", "flat")
    if on_click:
        btn.clicked.connect(on_click)
    return btn


def btn_pill(label: str, icon_name: str | None = None,
             on_click=None) -> QPushButton:
    """胶囊按钮：全圆角 + brand_50 底 + brand_700 字，无硬边框。

    用于"次级但需被看见"的入口（如总况条「去管理」）：比 flat 文字链醒目，
    又弱于实心 .primary 主 CTA（每屏仍只有一个实心主按钮）。"""
    btn = QPushButton(label)
    btn.setProperty("class", "pill")
    btn.setFixedHeight(D.BTN_H_SM)
    if icon_name:
        _apply_btn_icon(btn, icon_name, C.brand_700)
    if on_click:
        btn.clicked.connect(on_click)
    return btn


def btn_ghost(label: str, icon_name: str | None = None,
              icon_color: str | None = None, on_click=None) -> QPushButton:
    """ghost 按钮：透明底 + 1px 描边 + ink_700 字 + 语义小图标。

    用于经验卡「有效/纠正」：语义色只落在图标（有效=绿勾、纠正=红笔），文字
    保持 ink_700，把橙从卡片里清出去。图标与文字颜色解耦——不走 _apply_btn_
    icon（那个把图标和文字绑成同色），故手装子 QLabel。
    """
    if icon_color is None:
        icon_color = C.ink_500
    btn = QPushButton()
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedHeight(D.BTN_H_SM)
    btn.setStyleSheet(
        f"QPushButton {{ background: transparent;"
        f" border: 1px solid {C.line_strong}; border-radius: {R.md}px;"
        f" color: {C.ink_700}; font-size: {F.body}px; padding: 4px 12px; }}"
        f"QPushButton:hover {{ background: {C.surface_2}; }}"
        f"QPushButton:pressed {{ background: {C.surface_3}; }}")
    if icon_name:
        from .qt_icons import FT, MDI
        lay = QHBoxLayout(btn)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S.s1)
        if FT.get(icon_name, icon_name) in MDI:
            lay.addWidget(icon_widget(icon_name, 16, icon_color),
                          0, Qt.AlignVCenter)
        lab = QLabel(label)
        lab.setStyleSheet(
            f"color: {C.ink_700}; background: transparent; border: none;"
            f" font-size: {F.body}px;")
        lay.addWidget(lab, 0, Qt.AlignVCenter)
        lay.setAlignment(Qt.AlignCenter)
        btn.setText("")
    else:
        btn.setText(label)
    if on_click:
        btn.clicked.connect(on_click)
    return btn


def switch(checked: bool = False, on_toggled=None) -> QWidget:
    """启停开关（自绘轨道+旋钮；toggled(bool) 信号与 QCheckBox 同签名）。

    卡片/列表行的"单点启停"用它，和"选择"方框复选框不撞形。
    """
    from .qt_widgets import ToggleSwitch

    sw = ToggleSwitch(checked=checked)
    if on_toggled:
        sw.toggled.connect(on_toggled)
    return sw


def icon_button(name: str, tooltip: str, on_click=None,
                color: str | None = None, box: int | None = None) -> QPushButton:
    """行内图标按钮（纯图标无文字）：flat 无边框 + 固定图标盒（默认 D.ICON_BOX）。

    行操作图标（复制/删除/改名/恢复默认）的唯一出口，视觉与 list_row 图标盒同口径；
    替代各页自留的 _icon_btn 重复实现（迁移清单工厂收口）。
    """
    if color is None:
        color = C.ink_500
    box = box or D.ICON_BOX
    btn = QPushButton()
    btn.setToolTip(tooltip)
    btn.setFixedSize(box, box)
    btn.setFlat(True)
    btn.setCursor(Qt.PointingHandCursor)
    ic = icon_widget(name, SIZES.ICON_LIST, color)
    ic.setParent(btn)
    ic.setGeometry(0, 0, box, box)
    if on_click:
        btn.clicked.connect(on_click)
    return btn


def seg_button(label: str, on_click=None) -> QPushButton:
    """分段开关按钮（下划线式，hooks 页"按规则/按工具"与经验页 Tab 行共用）。

    概念图口径：无底色块，选中项品牌橙加粗 + 底部 2px 下划线，未选中中性 ink——
    橙只给"正在这一档"。选中态样式由 seg_style(btn, active) 驱动。
    """
    btn = QPushButton(label)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedHeight(D.BTN_H_SM)
    if on_click:
        btn.clicked.connect(on_click)
    return btn


def seg_style(btn: QPushButton, active: bool) -> None:
    """分段开关选中态：active 时 brand_700 加粗 + 2px 下划线，否则 ink_500。"""
    hover = (f"QPushButton:hover {{ color: {C.ink_900}; }}"
             if not active else "")
    btn.setStyleSheet(
        f"QPushButton {{ background: transparent; "
        f"color: {C.brand_700 if active else C.ink_500}; "
        f"border: none; border-bottom: 2px solid "
        f"{C.brand_700 if active else 'transparent'}; "
        f"padding: 0 {S.s4}px {D.CHIP_PAD_Y}px; "
        f"font-weight: {'600' if active else '400'}; }} {hover}")


def row_select_button(height: int = 34) -> QPushButton:
    """可选中行按钮（接入页分工具向导左列等清单用）：空按钮，图标+文字
    由调用方塞布局。P0-3 工厂收口——页面文件禁裸 QPushButton()，样式走
    row_select_style（与 seg_button/seg_style 同口径的"工厂+选中态函数"对）。
    """
    btn = QPushButton()
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedHeight(height)
    return btn


def row_select_style(btn: QPushButton, sel: bool) -> None:
    """行选中态：brand_100 底 + 左侧 3px 品牌橙竖条（与侧导航选中语一致）；
    未选中透明、hover 暖底。"""
    btn.setStyleSheet(
        f"QPushButton {{ background:"
        f" {C.brand_100 if sel else 'transparent'}; border: none;"
        f" border-left: 3px solid"
        f" {C.brand_700 if sel else 'transparent'};"
        f" border-radius: {R.sm}px; text-align: left; }}"
        f" QPushButton:hover {{ background:"
        f" {C.brand_100 if sel else C.surface_3}; }}")


def collapse_header(title: str, expanded: bool = False,
                    on_toggle=None) -> tuple:
    """可折叠分区头：标题（F.body 600）+ 可旋转 chevron + hover 暖底。

    收敛接入页"分工具接入说明"的 inline hover 样式（#id 限定防级联）；
    返回 (header, icon)：icon 是 RotatingIcon，调用方驱动旋转动画
    （reduced-motion 时直落目标角）。
    """
    from .qt_widgets import RotatingIcon

    header = QWidget()
    header.setObjectName("collapseHeader")
    header.setAttribute(Qt.WA_Hover, True)
    header.setCursor(Qt.PointingHandCursor)
    h_lay = QHBoxLayout(header)
    h_lay.setContentsMargins(S.s2, S.s1, S.s2, S.s1)
    h_lay.addWidget(txt(title, F.body, 600))
    h_lay.addStretch(1)
    icon = RotatingIcon("EXPAND_MORE_OUTLINED", 18, C.ink_500)
    if expanded:
        icon.setRotation(180)
    h_lay.addWidget(icon)
    # #id 限定：裸 QWidget 选择器会级联到子控件（护栏第 3 条）
    header.setStyleSheet(
        f"QWidget#collapseHeader {{ border-radius: {R.sm}px;"
        f" background: transparent; }}"
        f"QWidget#collapseHeader:hover {{ background: {C.surface_2}; }}")
    if on_toggle:
        header.mousePressEvent = lambda e: on_toggle()
    return header, icon


# ======== 列表行 ========

def list_row(icon_name: str, title: str, sub: str | None = None,
             trailing: QWidget | None = None, on_click=None,
             icon_color: str | None = None) -> QWidget:
    """列表行：高 56、hover 暖底、左图标、标题+副标题、右侧辅助（deck）。

    hover 通过 installEventFilter 或样式伪态：此处用动态样式（hover 基色），
    on_click 触发时整体可点击。icon_color 缺省在调用时解析（避免冻结亮色）。
    """
    if icon_color is None:
        icon_color = C.brand_700
    row = QWidget()
    row.setObjectName("listRow")
    row.setFixedHeight(SIZES.LIST_ROW_HEIGHT)
    row.setCursor(Qt.PointingHandCursor if on_click else Qt.ArrowCursor)
    # #id 限定：裸 QWidget 选择器会级联到 trailing 按钮，污染其 hover 底色
    row.setStyleSheet(f"""
        QWidget#listRow {{ background: transparent; border-radius: {R.md}px; }}
        QWidget#listRow:hover {{ background: {C.surface_2}; }}
    """)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(S.s2, 0, S.s2, 0)
    lay.setSpacing(S.s3)
    icon_box = QLabel()
    icon_box.setFixedSize(SIZES.LIST_ICON_BOX, SIZES.LIST_ICON_BOX)
    icon_box.setAlignment(Qt.AlignCenter)
    icon_box.setStyleSheet(
        f"background: transparent; border-radius: {R.sm}px;")
    _ic = icon_widget(icon_name, SIZES.ICON_LIST, icon_color)
    _ic.setParent(icon_box)
    _ic.setGeometry(0, 0, SIZES.LIST_ICON_BOX, SIZES.LIST_ICON_BOX)
    lay.addWidget(icon_box)
    text_col = QVBoxLayout()
    text_col.setSpacing(0)
    text_col.addWidget(txt(title, F.body))
    if sub:
        text_col.addWidget(txt(sub, F.caption, color=C.ink_500))
    lay.addLayout(text_col, 1)
    if trailing:
        lay.addWidget(trailing, 0, Qt.AlignVCenter)
    if on_click:
        row.mousePressEvent = lambda e, f=on_click: f()
    return row


def field_row(label: str, tone: str, value: str, full: str | None = None) -> QWidget:
    """「色点 + label + 值」定义行（经验卡踩坑/做法/结果用）。

    色点 tone 定色（踩坑=err/做法=brand/结果=ok），label caption/ink_500，
    值 body/ink_700 占剩余宽。value 是蒸馏压出的一句结论（默认两行省略）；
    full 为原文——full 比 value 长时值可点展开看全（expandable_clamped），
    否则两行省略 + tooltip 兜底。色点与 label 贴顶对齐。
    """
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(S.s2)
    left = QWidget()
    ll = QHBoxLayout(left)
    ll.setContentsMargins(0, 0, 0, 0)
    ll.setSpacing(S.s1)
    ll.addWidget(status_dot(tone))
    ll.addWidget(txt(label, F.caption, color=C.ink_500))
    val = expandable_clamped(value, full if full is not None else value,
                             size=F.body, weight=400, color=C.ink_700, max_lines=2)
    val.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    lay.addWidget(left, 0, Qt.AlignTop)
    lay.addWidget(val, 1, Qt.AlignTop)
    return row


# ======== 代码框 / URL 条 ========

def code_box(content: str, height: int = D.CODE_BOX_H,
             width: int | None = None) -> QPlainTextEdit:
    """等宽内容块（monospace 功能字体，豁免 txt 工厂），只读。

    编辑态/需纯文本的场合用它；**阅读态正文请用 ``md_view``**（Markdown 富文本，
    标题/列表/表格/代码块按令牌化 CSS 渲染）。
    """
    edit = QPlainTextEdit(content)
    edit.setReadOnly(True)
    edit.setStyleSheet(f"""
        QPlainTextEdit {{
            font-family: "Consolas", "Menlo", monospace;
            font-size: {F.caption}px;
            background: {C.surface_2};
            color: {C.ink_700};
            border: 1px solid {C.line};
            border-radius: {R.md}px;
            padding: {S.s3}px;
        }}
    """)
    edit.setFixedHeight(height)
    if width:
        edit.setFixedWidth(width)
    return edit


def url_bar(url: str) -> QLabel:
    """单行 monospace 地址条（高 D.URL_BAR_H）。"""
    label = QLabel(url)
    label.setStyleSheet(f"""
        QLabel {{
            font-family: "Consolas", "Menlo", monospace;
            font-size: {F.body}px;
            color: {C.ink_700};
            background: {C.surface_2};
            border: 1px solid {C.line};
            border-radius: {R.md}px;
            padding: 0 12px;
        }}
    """)
    label.setFixedHeight(D.URL_BAR_H)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


# ======== 吉祥物 ========

# 图片解码缓存（namespace, key...）→ QPixmap。assets 的吉祥物是 1024×1024 PNG，
# 全量解码约 15ms/次；建页/换表情/轮询重绘会反复用到同一张图，逐次解码纯浪费，
# 缓存后第二次起零开销（QPixmap 隐式共享）。
_PM_CACHE: dict[tuple, QPixmap] = {}
_PM_CACHE_APP = None


def cached_pixmap(namespace: str, key: tuple, build):
    """全进程 QPixmap 缓存：命中直接返回，未命中调 build() 生成后缓存。

    build 返回 None（文件缺失等）不写缓存。缓存随 QApplication 代次失效——
    测试/工具脚本会重建 app，旧 app 的 QPixmap 析构后再用属 use-after-free，
    故 app 换实例即整体清空（生产只有一个 app，永不触发）。
    """
    global _PM_CACHE_APP
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not _PM_CACHE_APP:
        _PM_CACHE.clear()
        _PM_CACHE_APP = app
    full_key = (namespace,) + tuple(key)
    hit = _PM_CACHE.get(full_key)
    if hit is not None:
        return hit
    pm = build()
    if pm is not None:
        _PM_CACHE[full_key] = pm
    return pm


def mascot_pixmap(name: str, size: int) -> QPixmap | None:
    """按目标尺寸取吉祥物图（带缓存）；表情名未知/文件缺失返回 None。"""
    from .theme import MASCOTS

    def _build():
        p = MASCOTS.get(name)
        if not p or not p.exists():
            return None
        pm = QPixmap(str(p))
        if pm.isNull():
            return None
        return pm.scaled(size, size, Qt.KeepAspectRatio,
                         Qt.SmoothTransformation)

    return cached_pixmap("mascot", (name, size), _build)


def mascot_image(name: str, size: int) -> QLabel:
    """宇航员表情图片（对应 theme.mascot_src + ft.Image 组合）。"""
    label = QLabel()
    label.setFixedSize(size, size)
    pm = mascot_pixmap(name, size)
    if pm is not None:
        label.setPixmap(pm)
    label.setAlignment(Qt.AlignCenter)
    return label


def empty_state(title: str, body: str, button: QWidget | None = None,
                mascot: str = "think") -> QWidget:
    """空状态（软脸区）：宇航员 + 口语化文案 + 一个按钮（deck）。"""
    from .theme import MASCOTS

    box = QWidget()
    # 用 #id 限定作用域：裸 QWidget{} 会级联到子按钮，把 primary 品牌底顶成白底
    box.setObjectName("emptyStateBox")
    box.setStyleSheet(f"""
        QWidget#emptyStateBox {{ background: {C.surface};
                    border: 1px solid {C.line}; border-radius: {R.xl}px; }}
    """)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(S.s8, S.s8, S.s8, S.s8)
    lay.setSpacing(S.s3)
    lay.setAlignment(Qt.AlignCenter)
    if mascot in MASCOTS:
        img = QLabel()
        img.setFixedSize(SIZES.MASCOT_EMPTY, SIZES.MASCOT_EMPTY)
        pm = mascot_pixmap(mascot, SIZES.MASCOT_EMPTY)
        if pm is not None:
            img.setPixmap(pm)
        img.setAlignment(Qt.AlignCenter)
        lay.addWidget(img, 0, Qt.AlignHCenter)
    lay.addWidget(txt(title, F.h2, 600, C.ink_700), 0, Qt.AlignHCenter)
    # 正文必须换行：空态文案是整句散文，非中文译文明显更长（实测同句德/法可达
    # 1378~1545px，中文仅 ~480px）——不换行会撑爆内容列最小宽、句尾被截断。
    # 同时给标签本身设居中对齐：wrap 后标签会占满可用宽，只靠布局项 AlignHCenter
    # 会让文字变成左对齐（CenteredWidget ≠ 居中文本）。
    body_lbl = txt(body, F.body, color=C.ink_500, wrap=True)
    body_lbl.setAlignment(Qt.AlignCenter)
    lay.addWidget(body_lbl, 0, Qt.AlignHCenter)
    if button:
        lay.addWidget(button, 0, Qt.AlignHCenter)
    return box


# ======== 图表（实现见 qt_widgets.py） ========

def heat_bar(vals, dates=None) -> QWidget:
    """热力图：14 格活跃度条（对应 theme.heat_bar）。空白格 = 休整样式。"""
    from .qt_widgets import HeatBar

    return HeatBar(vals, dates=dates)


def columns_chart(vals) -> QWidget:
    """近 14 天柱状图（对应 theme.columns_chart）。"""
    from .qt_widgets import ColumnsChart

    return ColumnsChart(vals)


def hbar_row(label: str, value: int, mx: int, label_w: int) -> QWidget:
    """累积横条（对应 theme.hbar_row）。"""
    from .qt_widgets import HBarRow

    return HBarRow(label, value, mx, label_w)


def rework_chart(weekly: list[dict]) -> QWidget:
    """周柱 + 返工率折线复合图（成长页磨合度时间轴，重构思）。"""
    from .qt_widgets import ReworkChart

    return ReworkChart(weekly)


__all__ = [
    "APP_STYLESHEET", "NAV_BUTTON_STYLE", "DIVIDER_STYLE",
    "txt", "txt_clamped", "ClampedLabel", "status_text", "status_dot",
    "mono", "icon_widget", "chip", "md_view", "provenance_bar",
    "drawer", "card", "divider",
    "btn_primary", "btn_secondary", "btn_danger", "btn_flat", "btn_pill",
    "btn_ghost", "field_row",
    "switch",
    "icon_button", "seg_button", "seg_style", "collapse_header",
    "list_row", "code_box", "url_bar", "mascot_image", "empty_state",
    "heat_bar", "columns_chart", "hbar_row", "rework_chart",
]
