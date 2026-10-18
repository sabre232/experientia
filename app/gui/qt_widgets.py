"""Qt 自定义控件（迁移清单）：热力图、柱状图、横条、旋转箭头、导航按钮、
SelectButton（页面滚动区内的选择器）。

滚动/弹层规范：
- 页面只保留一个外层 QScrollArea（统一入口 build_centered_scroll）；
- 页面整滚区内需要“下拉选择”一律用 SelectButton（QMenu 顶层弹层）——
  QComboBox 的下拉容器在全局样式表下会被 QScrollArea 当作 viewport 子控件，
  页面一滚动弹层就跟着滚（曾表现为“模板区被滚下来的下拉挡住”）；
- QComboBox 只允许出现在 QDialog（独立窗口）内，否则视为违规。
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import (QEasingCurve, QEvent, QObject,
                            QParallelAnimationGroup, QPoint, QPointF,
                            QPropertyAnimation, Property, QRect, QRectF, QSize,
                            Qt, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter,
                           QPen, QPixmap)
from PySide6.QtWidgets import (QFrame, QGraphicsBlurEffect,
                               QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
                               QGraphicsPixmapItem, QGraphicsScene, QHBoxLayout,
                               QLabel, QLayout, QMenu, QPushButton, QScrollArea,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from .qt_icons import FT, icon_glyph, icon_font, icon_widget

from .theme import (ANIMATION, C, D, F, R, S, SIZES, THRESHOLDS,
                    CHART_AXIS_COLOR, HEAT_SCALE, low_fx, motion_ok)
from .i18n import t
from .qt_theme import chip, icon_button, md_view, txt

_logger = logging.getLogger("experientia.gui.qt_widgets")


def _heat_color(v: float, mx: float) -> str:
    """格值 → 6 档色阶（与 theme._heat_color 同口径）。"""
    if v <= 0:
        return C.surface_2
    idx = min(len(HEAT_SCALE) - 1, int(v / mx * (len(HEAT_SCALE) - 1) + 0.5))
    return HEAT_SCALE[idx]


def _ease(name: str) -> QEasingCurve:
    """缓动令牌（``QEasingCurve`` 枚举名字符串）→ ``QEasingCurve`` 实例。

    Qt 的 ``QEasingCurve`` 不接受字符串构造（``QEasingCurve("OutCubic")`` 抛
    TypeError），必须按枚举名取 ``Type``；令牌拼错或缺失时回退 ``Linear``
    ——动效参数错误不该让调用方崩。
    """
    try:
        return QEasingCurve(getattr(QEasingCurve.Type, str(name)))
    except Exception:  # noqa: BLE001 令牌非法也回退，不抛
        return QEasingCurve(QEasingCurve.Type.Linear)


def _animate_progress(widget, duration: float | None = None) -> None:
    """自绘图表入场动画共用件：把 ``widget.progress`` 从 0 动到 1。

    fail-open 硬要求：``progress`` 初值必须是 1.0（未调用就是终态，绝不留白）；
    ``motion_ok()`` 为假 → 不启动动画（保持 1.0）；动画异常 → 直落 1.0。
    调用方类需自备 ``progress`` 属性（Property(float)）。
    """
    if not motion_ok():
        return
    try:
        secs = ANIMATION.DURATION_DIALOG if duration is None else float(duration)
        anim = QPropertyAnimation(widget, b"progress", widget)
        anim.setDuration(int(secs * 1000))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(_ease(ANIMATION.EASE_OUT_QUART))
        widget._enter_anim = anim  # 保引用，防 GC 提前回收
        anim.start()
    except Exception as exc:  # noqa: BLE001 fail-open：动画异常也必须到终态
        _logger.warning("图表入场动画失败，直落终态: %s", exc)
        try:
            widget._progress = 1.0
            widget.update()
        except Exception:
            pass


class SkeletonBlock(QWidget):
    """骨架屏灰块：圆角矩形 + 扫光，占位未到位的真实内容。

    扫光用 ``QPropertyAnimation`` 驱动 ``phase`` 属性（0→1 循环），
    ``paintEvent`` 里 ``QLinearGradient`` 的位置随 phase 从左移到右。
    ``motion_ok()`` 为假 → 不启动动画，静态灰块（reduced-motion 下不闪）。
    """

    def __init__(self, *, height: int = F.body, width: int | None = None,
                 parent=None):
        super().__init__(parent)
        self._block_h = int(height)
        self._phase = 0.0
        self.setFixedHeight(self._block_h)
        if width is not None:
            self.setFixedWidth(int(width))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._anim = QPropertyAnimation(self, b"phase", self)
        self._anim.setDuration(int(ANIMATION.DURATION_SKELETON * 1000))
        self._anim.setLoopCount(-1)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Linear)
        if motion_ok():
            self._anim.start()

    # 扫光进度（0→1 一个周期），由动画驱动
    def _get_phase(self) -> float:
        return self._phase

    def _set_phase(self, v: float) -> None:
        self._phase = float(v)
        self.update()

    phase = Property(float, _get_phase, _set_phase)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        radius = min(R.sm, self.height() / 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C.surface_2))
        p.drawRoundedRect(rect, radius, radius)
        if motion_ok():
            band = max(S.s8, self.width() * 0.35)
            x = -band + self._phase * (self.width() + band)
            grad = QLinearGradient(x, 0, x + band, 0)
            # 扫光用 on_brand（两模恒为白）加 alpha 渐变，亮/暗底都表现为"提亮"
            hi = QColor(C.on_brand)
            lo = QColor(C.on_brand)
            lo.setAlphaF(0.0)
            hi.setAlphaF(0.5)
            grad.setColorAt(0.0, lo)
            grad.setColorAt(0.5, hi)
            grad.setColorAt(1.0, lo)
            p.setBrush(grad)
            p.drawRoundedRect(rect, radius, radius)
        p.end()


def skeleton_column(heights: list[int]) -> QWidget:
    """一列骨架块的便捷封装：竖向排列，间距 S.s3。

    heights 为各块的像素高度序列（页面按内容形状给：标题矮、正文高）。
    """
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(S.s3)
    for h in heights or []:
        lay.addWidget(SkeletonBlock(height=h))
    return box


# ----------  档 2：自绘投影卡片（替代逐控件 QGraphicsDropShadowEffect） ----------
# 量测：300 张卡挂 effect 后整控件绘制 13 ms → 54 ms（约 5×，CPU 逐控件合成）。
# 自绘 = 把圆角矩形**一次性模糊成图**（`_shadow_pixmap`，按尺寸+浓度缓存），
# 绘制时只 drawPixmap，零模糊计算；卡片本体（圆角/描边/米底）同一次 paintEvent 画完。
# 代价：外投影必须画在卡片之外 → 控件为阴影**留边** `SHADOW_MARGIN`（内容区相应变窄）。
SHADOW_BLUR = S.s1                  # 4px（比原 effect 的 S.s2 更紧凑，换取更小留边）
SHADOW_MARGIN = SHADOW_BLUR * 2     # 8px 留边（够容纳模糊扩散、不被裁）
_SHADOW_ALPHA_REST = 0.10
_SHADOW_ALPHA_HOVER = 0.17
_SHADOW_PM_CACHE: dict[tuple, QPixmap] = {}


def _shadow_pixmap(w: int, h: int, alpha: float, radius: int,
                   base: QColor | None = None) -> QPixmap:
    """按（宽, 高, 浓度, 圆角, **基色**）缓存一张模糊投影图（首次生成才付模糊成本）。

    基色必须进 key：投影以 `C.ink_900` 为基色，而该 token 随色板翻转（亮色是深棕、
    暗色是近白——暗色下投影实为"浅色浮起"）。本缓存是**模块级**、跨页面重建与切肤
    存活，若不含颜色，切肤后会复用旧色投影（亮色深影出现在暗色界面上）。
    """
    base = base or QColor(C.ink_900)
    key = (w, h, round(alpha, 3), radius, base.rgba())
    hit = _SHADOW_PM_CACHE.get(key)
    if hit is not None:
        return hit
    m = SHADOW_MARGIN
    iw, ih = max(1, w + 2 * m), max(1, h + 2 * m)
    src = QImage(iw, ih, QImage.Format_ARGB32_Premultiplied)
    src.fill(0)
    p = QPainter(src)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(base.red(), base.green(), base.blue(),
                      int(255 * max(0.0, min(1.0, alpha)))))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(m, m, w, h), radius, radius)
    p.end()
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(src))
    eff = QGraphicsBlurEffect()
    eff.setBlurRadius(SHADOW_BLUR)
    item.setGraphicsEffect(eff)
    scene.addItem(item)
    out = QImage(iw, ih, QImage.Format_ARGB32_Premultiplied)
    out.fill(0)
    p2 = QPainter(out)
    scene.render(p2)
    p2.end()
    pm = QPixmap.fromImage(out)
    _SHADOW_PM_CACHE[key] = pm
    return pm


class ShadowCard(QFrame):
    """自绘柔和投影的卡片（档 2），与 ``qt_theme.card()`` 同接口的替身。

    ``card()`` 的调用方只用 ``.layout()`` 追加内容，故这里保持同样的 QVBoxLayout
    契约（``title`` / ``padding`` / ``secondary`` / ``visible`` 参数同义）。
    投影浓度由 ``set_shadow_strength(0..1)`` 驱动（hover 用，配合 ``hover_lift``）。
    """

    def __init__(self, content: QWidget | None = None, title: str | None = None,
                 padding: int = S.s4, secondary: bool = False,
                 visible: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._alpha = _SHADOW_ALPHA_REST
        self._body_bg = C.surface_2 if secondary else C.surface
        m = SHADOW_MARGIN
        lay = QVBoxLayout(self)
        lay.setContentsMargins(padding + m, padding + m, padding + m, padding + m)
        lay.setSpacing(S.s3)
        if title:
            lay.addWidget(txt(title, F.h2, 600, C.ink_700))
        if content is not None:
            lay.addWidget(content)
        # 同 qt_theme.card()：构造期无父，setVisible(True) 会开出一个真顶层窗口。
        # 显示交给入布局时的父控件，这里只处理「需要隐藏」。
        if not visible:
            self.hide()

    def set_shadow_strength(self, v: float) -> None:
        """0 = 静止浓度，1 = hover 浓度（供 hover_lift 驱动）。"""
        t = max(0.0, min(1.0, float(v)))
        self._alpha = _SHADOW_ALPHA_REST + (_SHADOW_ALPHA_HOVER
                                           - _SHADOW_ALPHA_REST) * t
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802 (Qt 命名)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = SHADOW_MARGIN
        w = max(1, self.width() - 2 * m)
        h = max(1, self.height() - 2 * m)
        p.drawPixmap(0, D.BORDER_W,
                     _shadow_pixmap(w, h, self._alpha, R.lg))   # 投影（含 1px 下偏）
        p.setPen(QPen(QColor(C.line_strong), D.BORDER_W))
        p.setBrush(QColor(self._body_bg))
        p.drawRoundedRect(QRectF(m, m, w, h), R.lg, R.lg)
        p.end()


class _HoverLiftFilter(QObject):
    """hover_lift 的事件过滤器：enter/leave 驱动位移 + 阴影深浅。

    **不持 widget 的 Python 回引**（改用 ``eventFilter`` 传入的 ``obj``）：
    ``self._w = widget`` 会形成 ``widget ↔ filter`` 引用环，无父控件（如测试里
    ``_card_for`` 造的临时卡）经 Python GC 销毁时，环的回收顺序会让 C++ 控件
    与其子 QObject 被释放两次 → 堆损坏（``0xC0000374``/``0xC0000005``）。
    由 ``obj`` 取控件即断开该环。
    """

    def __init__(self, widget: QWidget, rise: int,
                 shadow: QGraphicsDropShadowEffect | None = None,
                 on_strength=None) -> None:
        """shadow = effect 卡片；on_strength = 自绘卡片（档 2，收 0..1 浓度）。"""
        super().__init__(widget)
        self._rise = int(rise)
        self._shadow = shadow
        self._on_strength = on_strength
        self._base: QPoint | None = None
        self._lifted = False
        self._pos_anim = QPropertyAnimation(widget, b"pos", widget)
        self._pos_anim.setDuration(int(ANIMATION.DURATION_HOVER * 1000))
        self._pos_anim.setEasingCurve(_ease(ANIMATION.EASE_OUT_CUBIC))
        if shadow is not None:
            self._shadow_anim = QPropertyAnimation(shadow, b"blurRadius", widget)
        else:
            self._shadow_anim = QVariantAnimation(widget)
            self._shadow_anim.valueChanged.connect(
                lambda v: on_strength(float(v)) if on_strength else None)
        self._shadow_anim.setDuration(int(ANIMATION.DURATION_HOVER * 1000))
        self._shadow_anim.setEasingCurve(_ease(ANIMATION.EASE_OUT_CUBIC))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt 命名)
        et = event.type()
        if et == QEvent.Enter:
            if not self._lifted:
                self._base = obj.pos()
            self._lifted = True
            self._to(obj, lifted=True)
        elif et == QEvent.Leave:
            self._lifted = False
            self._to(obj, lifted=False)
        return False

    def _to(self, widget, *, lifted: bool) -> None:
        if not motion_ok():
            return
        try:
            base = self._base if self._base is not None else widget.pos()
            target = (QPoint(base.x(), base.y() - self._rise) if lifted else base)
            self._pos_anim.stop()
            self._pos_anim.setStartValue(widget.pos())
            self._pos_anim.setEndValue(target)
            self._pos_anim.start()
            self._shadow_anim.stop()
            if self._shadow is not None:
                self._shadow_anim.setStartValue(self._shadow.blurRadius())
                self._shadow_anim.setEndValue(S.s4 if lifted else S.s2)
            else:  # 自绘卡片：0 = 静止浓度，1 = hover 浓度
                self._shadow_anim.setStartValue(0.0 if lifted else 1.0)
                self._shadow_anim.setEndValue(1.0 if lifted else 0.0)
            self._shadow_anim.start()
        except Exception as exc:  # noqa: BLE001 fail-open：动画失败不影响交互
            _logger.warning("hover_lift 动画失败: %s", exc)


def hover_lift(widget: QWidget, *, rise: int = 2) -> None:
    """卡片 hover 抬升 + 阴影：全项目此前唯一缺的"层次"手段。

    ``enterEvent``/``leaveEvent`` 驱动 ``pos`` 上移 ``rise`` 像素 + 阴影加深
    （``DURATION_HOVER`` + ``EASE_OUT_CUBIC``）。用事件过滤器实现，不改控件类。

    ``motion_ok()`` 为假 → 只挂静态阴影，不做位移动画（reduced-motion 下不位移）。

    ``low_fx()`` 为真（档 1）→ **整体跳过**（不挂 effect、不装过滤器、不动画）：
    投影是 CPU 合成的逐控件开销，实测 300 张卡的绘制 11 ms → 53 ms（约 5×），
    低性能平台可整体关掉。纯装饰 → fail-open，内容与交互不变。
    """
    if widget is None or low_fx():
        return
    if isinstance(widget, ShadowCard):
        # 档 2：自绘投影卡片——不加 effect，hover 只调投影浓度
        flt = _HoverLiftFilter(widget, rise, on_strength=widget.set_shadow_strength)
    else:
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(S.s2)
        shadow.setOffset(0, D.BORDER_W)
        col = QColor(C.ink_900)
        col.setAlphaF(0.10)
        shadow.setColor(col)
        widget.setGraphicsEffect(shadow)
        flt = _HoverLiftFilter(widget, rise, shadow=shadow)
    widget.installEventFilter(flt)
    widget._hover_lift_filter = flt  # 保引用，防 GC 提前回收


class AnimatedStack(QStackedWidget):
    """页面切换过渡栈。

    切页时抓新页快照做覆盖层 ``QLabel``，覆盖层 ``opacity`` 1→0 + 上移
    ``S.s3`` 像素，结束后删除——**不对整页复杂控件树施加
    ``QGraphicsOpacityEffect``**（开销大且易与子控件绘制冲突；本项目页面
    控件密度高）。

    ``motion_ok()`` 为假 / ``animate=False`` / 任何异常 → 瞬时切换，且保证
    新页可见（无残留 effect / 覆盖层）。与 ``main_window.py`` 的接线由 
    完成，本 WS 只提供组件。
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._overlay: QLabel | None = None
        self._overlay_group: QParallelAnimationGroup | None = None

    def setCurrentWidget(self, w, *, animate: bool = True) -> None:  # noqa: N802
        if w is None:
            return
        self._clear_overlay()
        if not animate or not motion_ok() or self.currentWidget() is w:
            try:
                super().setCurrentWidget(w)
                w.setVisible(True)
            except Exception as exc:  # noqa: BLE001 fail-open
                _logger.warning("页面切换失败: %s", exc)
            return
        try:
            super().setCurrentWidget(w)
            w.setVisible(True)
            w.raise_()
            overlay = QLabel(self)
            overlay.setPixmap(w.grab())
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            overlay.setGeometry(0, 0, self.width(), self.height())
            overlay.show()
            overlay.raise_()
            eff = QGraphicsOpacityEffect(overlay)
            eff.setOpacity(1.0)
            overlay.setGraphicsEffect(eff)
            grp = QParallelAnimationGroup(overlay)
            fade = QPropertyAnimation(eff, b"opacity", grp)
            fade.setDuration(int(ANIMATION.DURATION_PAGE * 1000))
            fade.setStartValue(1.0)
            fade.setEndValue(0.0)
            fade.setEasingCurve(_ease(ANIMATION.EASE_OUT_QUART))
            rise = QPropertyAnimation(overlay, b"pos", grp)
            rise.setDuration(int(ANIMATION.DURATION_PAGE * 1000))
            rise.setStartValue(QPoint(0, 0))
            rise.setEndValue(QPoint(0, -S.s3))
            rise.setEasingCurve(_ease(ANIMATION.EASE_OUT_QUART))
            grp.addAnimation(fade)
            grp.addAnimation(rise)
            self._overlay = overlay
            self._overlay_group = grp
            grp.finished.connect(self._clear_overlay)
            grp.start()
        except Exception as exc:  # noqa: BLE001 fail-open：动画失败也必须切过去
            _logger.warning("页面过渡动画失败，瞬时切换: %s", exc)
            self._clear_overlay()
            try:
                super().setCurrentWidget(w)
                w.setVisible(True)
            except Exception:
                pass

    def _clear_overlay(self) -> None:
        grp = self._overlay_group
        self._overlay_group = None
        if grp is not None:
            try:
                grp.stop()
            except Exception:
                pass
        ov = self._overlay
        self._overlay = None
        if ov is not None:
            try:
                ov.hide()
                ov.setGraphicsEffect(None)
                ov.setParent(None)
                ov.deleteLater()
            except Exception:
                pass


class HeatBar(QWidget):
    """热力图：一格条活跃度条（对应 theme.heat_bar）。

    空白格 = 休整（中性浅灰）：区别于"有数据"的深浅阶梯，
    hover 提示"这天没有记录到同类任务"——空白不惩罚（GitHub 贡献图 issue 627）。"""

    def __init__(self, values, dates=None, parent=None):
        super().__init__(parent)
        self._values = [float(v) for v in values]
        self._dates = [str(d) for d in (dates or [])][:len(self._values)]
        self._progress = 1.0  # fail-open：未调用 animate_in 时就是终态
        self.setFixedHeight(D.CHART_CELL_H)
        self.setMinimumWidth(len(self._values) * (D.CHART_CELL + D.CHART_GAP))

    # 入场动画进度（0→1）；初值 1.0，见 _animate_progress 的 fail-open 约定
    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, v: float) -> None:
        self._progress = max(0.0, min(1.0, float(v)))
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def animate_in(self, duration: float | None = None) -> None:
        """入场动画：格条高度从 0 长到终值。"""
        _animate_progress(self, duration)

    def _cell_at(self, pos: QPoint) -> int | None:
        i = int(pos.x() // (D.CHART_CELL + D.CHART_GAP))
        if 0 <= i < len(self._values):
            return i
        return None

    def mouseMoveEvent(self, event):
        i = self._cell_at(event.position().toPoint())
        if i is None:
            self.setToolTip("")
            return
        v = self._values[i]
        date = self._dates[i] if i < len(self._dates) else ""
        if v > 0:
            self.setToolTip(f"{date} · {v:g}")
        else:
            self.setToolTip(f"{date} · {t('休整：这天没有记录到同类任务')}")
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.setToolTip("")
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        mx = max(self._values) or 0.001
        # 入场动画：格条自底部生长（progress=1 时与终态完全一致）
        h = D.CHART_CELL_H * self._progress
        radius = min(D.CHART_CELL_H // 2, h / 2)
        y = D.CHART_CELL_H - h
        x = 0.0
        for v in self._values:
            painter.setBrush(QColor(_heat_color(v, mx)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(
                QRectF(x, y, D.CHART_CELL, h), radius, radius)
            x += D.CHART_CELL + D.CHART_GAP
        painter.end()


class ColumnsChart(QWidget):
    """近 14 天柱状图（对应 theme.columns_chart）。

    柱高 ∝ 值（D.POSTER_COL_H 封顶），柱顶标数值（0 不标），颜色 = 热力 6 档色阶，
    含网格线 + 平均虚线 + 峰值柱高亮。
    """

    def __init__(self, values, parent=None):
        super().__init__(parent)
        self._values = [float(v) for v in values]
        self._mx = max(self._values) or 0.001
        self._avg = sum(self._values) / len(self._values) if self._values else 0
        self._progress = 1.0  # fail-open：未调用 animate_in 时就是终态
        n = len(self._values)
        w = n * (D.CHART_CELL + D.POSTER_COL_GAP) + D.POSTER_COL_GAP
        h = D.POSTER_COL_H + F.caption + D.CHART_GAP + 8
        self.setMinimumSize(int(w), int(h))
        self.setFixedHeight(int(h))

    # 入场动画进度（0→1）；初值 1.0，见 _animate_progress 的 fail-open 约定
    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, v: float) -> None:
        self._progress = max(0.0, min(1.0, float(v)))
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def animate_in(self, duration: float | None = None) -> None:
        """入场动画：柱高从 0 长到终值。"""
        _animate_progress(self, duration)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()

        # 水平网格线（背景层）
        pen = QPen(QColor(CHART_AXIS_COLOR), SIZES.CHART_AXIS_WIDTH)
        painter.setPen(pen)
        for i in range(THRESHOLDS.CHART_GRID_LINES):
            y = (i + 1) * (D.POSTER_COL_H / (THRESHOLDS.CHART_GRID_LINES + 1))
            painter.drawLine(0, int(y), w, int(y))

        # 平均线（虚线）
        if self._avg > 0:
            avg_y = (self._avg / self._mx) * D.POSTER_COL_H
            pen2 = QPen(QColor(C.ink_300), SIZES.CHART_AXIS_WIDTH)
            pen2.setStyle(Qt.DashLine)
            painter.setPen(pen2)
            painter.drawLine(0, int(avg_y), w, int(avg_y))

        x = float(D.POSTER_COL_GAP)
        for v in self._values:
            target = D.CHART_CELL if v <= 0 else max(
                D.CHART_CELL, int(round(v / self._mx * D.POSTER_COL_H)))
            hbar = target * self._progress  # 入场动画：柱高插值（progress=1 为终态）
            color = QColor(_heat_color(v, self._mx))
            is_peak = v > self._avg * THRESHOLDS.CHART_PEAK_PROMINENCE and v > 0
            y = D.POSTER_COL_H - hbar + F.caption + D.CHART_GAP
            radius = min(D.CHART_CELL // 2, hbar / 2)
            painter.setBrush(color)
            painter.setPen(QPen(QColor(C.brand_900), 1) if is_peak else Qt.NoPen)
            painter.drawRoundedRect(
                QRectF(x, y, D.CHART_CELL, hbar), radius, radius)
            # 柱顶数值：表内 token 字号（F.micro），不走 0.75× 非表值
            # 动画期间不标（否则数字先堆在基线，观感像出错）
            if v > 0 and self._progress >= 1.0:
                painter.setPen(QColor(C.ink_500))
                font = QFont()
                font.setPointSizeF(F.micro)
                painter.setFont(font)
                painter.drawText(
                    QRectF(x, y - F.caption, D.CHART_CELL, F.caption),
                    Qt.AlignCenter, f"{v:g}")
            x += D.CHART_CELL + D.POSTER_COL_GAP
        painter.end()


class HBarRow(QWidget):
    """累积横条（对应 theme.hbar_row）：条宽 ∝ 值，右端标数值。"""

    def __init__(self, label: str, value: int, mx: int, label_w: int,
                 parent=None):
        super().__init__(parent)
        self._label = label
        self._value = int(value)
        self._mx = int(mx) or 1
        self._label_w = int(label_w)
        self.setFixedHeight(max(D.CHART_BAR_H, F.body) + 8)
        self.setMinimumWidth(int(label_w) + D.CHART_BAR_MAX + 60)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 标签
        painter.setPen(QColor(C.ink_700))
        font = QFont()
        font.setPointSizeF(F.caption)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, self._label_w, self.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, self._label)
        # 条
        w = D.CHART_BAR_MIN if self._mx <= 0 else max(
            D.CHART_BAR_MIN, int(self._value / self._mx * D.CHART_BAR_MAX))
        bar_x = self._label_w + S.s2
        y = (self.height() - D.CHART_BAR_H) / 2
        grad = QLinearGradient(bar_x, 0, bar_x + w, 0)
        grad.setColorAt(0, QColor(C.brand_400))
        grad.setColorAt(1, QColor(C.brand_600))
        painter.setPen(Qt.NoPen)
        painter.setBrush(grad)
        painter.drawRoundedRect(QRectF(bar_x, y, w, D.CHART_BAR_H),
                                D.CHART_BAR_H // 2, D.CHART_BAR_H // 2)
        show_overlay = w > SIZES.CHART_BAR_H * 4
        if show_overlay:
            painter.setPen(QColor(C.on_brand))
            painter.drawText(QRectF(bar_x + S.s1, y, w - S.s1, D.CHART_BAR_H),
                             Qt.AlignVCenter | Qt.AlignLeft, str(self._value))
        else:
            painter.setPen(QColor(C.ink_900))
            f2 = QFont()
            f2.setPixelSize(F.body)
            painter.setFont(f2)
            painter.drawText(
                QRectF(bar_x + w + S.s2, 0, self.width() - bar_x - w - S.s2,
                       self.height()),
                Qt.AlignVCenter | Qt.AlignLeft, str(self._value))
        painter.end()


class RotatingIcon(QWidget):
    """可旋转 MDI 图标（折叠头箭头用，对应 connect 页展开/收起）。

    QLabel 没有可动画的 rotation 属性（QPropertyAnimation 动不了它），
    改用 QWidget + paintEvent 自绘 glyph，暴露 rotation 属性供动画驱动。
    glyph 不随旋转换字——chevron-down 转 180° 即 chevron-up，展开/收起
    语义由角度表达（reduced-motion 时直接落到目标角，不播动画）。
    """

    def __init__(self, name: str, size: int = 18, color: str | None = None,
                 parent=None):
        super().__init__(parent)
        self._glyph = icon_glyph(FT.get(name, name))
        self._size = size
        self._color = color or C.ink_500
        self._rotation = 0.0
        self.setFixedSize(size + 4, size + 4)

    def rotation(self) -> float:
        return self._rotation

    def setRotation(self, deg: float) -> None:
        self._rotation = deg
        self.update()

    rotation = Property(float, rotation, setRotation)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(self._color))
        font = icon_font(self._size)
        font.setPixelSize(self._size)
        p.setFont(font)
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(self._rotation)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(self._glyph)
        h = fm.height()
        p.drawText(QRectF(-w / 2, -h / 2, w, h), Qt.AlignCenter, self._glyph)
        p.end()


class NavButton(QPushButton):
    """导航项按钮：可选中（checkable），图标 + 文字，选中态浅杏底 + brand 色。

    支持 outline / filled 双图标名：选中时自动切换到 filled glyph（设计方案 V-A5）。
    支持 retranslateUi() 原地更新语言文字（语言切换不重建，Qt 标准做法）。
    """

    def __init__(self, text: str, icon_name: str | None = None,
                 icon_filled: str | None = None, parent=None):
        """text 是翻译键（raw key），初始显示调 t(text) 得到翻译值。"""
        from .i18n import t as _t

        super().__init__("", parent)  # 空文本，由子 QLabel 渲染
        self._text_key = text  # 翻译键（raw key），retranslateUi 时重查
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoExclusive(False)
        self._label: QLabel | None = None
        self._icon_widget: QLabel | None = None
        self._icon_outline = icon_name
        self._icon_filled = icon_filled or icon_name
        if icon_name:
            from .qt_icons import MDI, FT

            if FT.get(icon_name, icon_name) in MDI:
                from .theme import S as _S, SIZES as _SIZES, C as _C

                # 解剖：左缘 12 + 图标定宽格 32（glyph 居中
                # 其中）+ 间距 12 + 文字吃剩余宽度 → 全部行共享同一条图标轴和
                # 文字轴，宽度派生再也不会逐行漂移（曾把按钮宽均分给两格，
                # 图标浮在半空、各行 x 坐标不一致）
                lay = QHBoxLayout(self)
                lay.setContentsMargins(_S.s3, 0, _S.s3, 0)
                lay.setSpacing(_S.s3)
                ic = icon_widget(icon_name, 20, _C.ink_500)
                ic.setFixedWidth(_SIZES.LIST_ICON_BOX)
                lab = txt(_t(text), F.body, 400, _C.ink_700)
                lay.addWidget(ic, 0, Qt.AlignVCenter)
                lay.addWidget(lab, 1, Qt.AlignVCenter)
                self._icon_widget = ic
                self._label = lab
        self.setFixedHeight(D.NAV_ROW_H)
        self._apply_icon()

    def retranslateUi(self) -> None:
        """语言切换时原地更新按钮文字（不重建 widget）。"""
        from .i18n import t

        if self._label is not None:
            self._label.setText(t(self._text_key))

    def _retint_label(self) -> None:
        """主题/选中态：子标签文字色与当前色板同步（选中 brand_700 / 未选 ink_700）。

        txt() 把颜色在构建时冻结成具体 hex，切主题后不更新会留旧 token
        （浅色深灰字落在暗色 rail 上不可读）——rail 重刷与 setChecked 都要调。
        """
        if self._label is None:
            return
        from .theme import C as _C, F as _F

        color = _C.brand_700 if self.isChecked() else _C.ink_700
        self._label.setStyleSheet(
            f"color: {color}; background: transparent; border: none;"
            f" font-size: {_F.body}px;")

    def _apply_icon(self) -> None:
        """根据选中状态切换图标 glyph 和颜色（原地重绘，不重建 widget）。

        注意：此方法可能在 __init__（布局构建中）和 setChecked（切换后）被调用。
        幂等短路：glyph 名与颜色都一致时跳过。
        原地 restyle 替代旧的 insert/removeWidget/deleteLater 交换式替换——
        主题/语言切换会重刷全部导航按钮，deleteLater 旧图标与 paint/定时器
        事件竞争是 -805306369 use-after-free 的历史根因族（详见 main_window.switch_theme）。
        """
        if self._icon_widget is None:
            return
        from .theme import C as _C
        from .qt_icons import restyle_icon as _restyle

        name = self._icon_filled if self.isChecked() else self._icon_outline
        color = _C.brand_700 if self.isChecked() else _C.ink_500
        if getattr(self, "_last_icon", None) == (name, color):
            return
        _restyle(self._icon_widget, name, color, 20)
        self._last_icon = (name, color)

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        self._apply_icon()
        self._retint_label()

    def label_text(self) -> str:
        """渲染中的导航文字（text() 因双绘修复被清空，读子标签）。"""
        if self._label is not None:
            return self._label.text()
        return self.text()


class SelectButton(QWidget):
    """页面整滚区内的下拉选择器（替代 QComboBox；-fix-2）。

    背景：全局样式表下 QComboBox 的下拉容器在 QScrollArea 里会被当成 viewport
    子控件，页面滚动时弹层跟着滚（表现为“选择器跟着滚动条滑走”）。QMenu 的
    弹层是独立顶层窗口，不受父级滚动影响——因此整页滚动区内一律用 SelectButton；
    QComboBox 只允许用于 QDialog（独立窗口）内部。

    API 覆盖现有 QComboBox 常用面：
    addItem/clear/count/itemText/setItemText/currentData/findData/setCurrentIndex/
    currentIndex()；信号 currentIndexChanged(int)（选中项变化，尊重 blockSignals）
    与 activated(int)（用户手动点选，与 QComboBox.activated 语义一致）。
    鼠标滚轮在控件上不改变选中值，滚动事件冒泡给外层页面滚动。
    """

    currentIndexChanged = Signal(int)
    activated = Signal(int)

    def __init__(self, width: int | None = None, height: int | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)  # 纯 QWidget 子类须声明，否则样式表的 background/border 不绘制
        self._items: list[tuple[str, Any]] = []
        self._cur = -1
        self.setObjectName("SelectButton")
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(6)
        self._label = txt("", F.body, 400, C.ink_900)
        self._label.setMinimumWidth(0)
        lay.addWidget(self._label, 1)
        self._arrow = icon_widget("EXPAND_MORE_OUTLINED", 16, C.ink_500)
        lay.addWidget(self._arrow, 0, Qt.AlignVCenter)
        self.setFixedHeight(height or D.BTN_H_SM)
        if width is not None:
            self.setFixedWidth(width)
        self.setStyleSheet(
            f"QWidget#SelectButton {{ background: {C.surface};"
            f" border: 1px solid {C.line_strong}; border-radius: {R.sm}px; }}"
            f"QWidget#SelectButton:hover {{ border: 1px solid {C.brand_400}; }}")
        self._menu = QMenu(self)
        self._menu.setObjectName("SelectMenu")
        self._menu.aboutToShow.connect(self._sync_menu)
        self._menu.triggered.connect(self._on_pick)

    # ---------- 仿 QComboBox API ----------

    def addItem(self, text: str, data: Any = None) -> None:
        """追加一项；首个自动成为当前项（不触发 currentIndexChanged，同 QComboBox）。"""
        self._items.append((str(text), data))
        if self._cur < 0 and len(self._items) == 1:
            self._cur = 0
            self._update_label()

    def clear(self) -> None:
        self._items.clear()
        self._cur = -1
        self._update_label()

    def count(self) -> int:
        return len(self._items)

    def itemText(self, index: int) -> str:
        return self._items[index][0] if 0 <= index < len(self._items) else ""

    def setItemText(self, index: int, text: str) -> None:
        if 0 <= index < len(self._items):
            self._items[index] = (str(text), self._items[index][1])
            if index == self._cur:
                self._update_label()

    def currentData(self) -> Any:
        return self._items[self._cur][1] if 0 <= self._cur < len(self._items) else None

    def currentIndex(self) -> int:
        return self._cur

    def findData(self, data: Any) -> int:
        for i, (_, d) in enumerate(self._items):
            if d == data:
                return i
        return -1

    def setCurrentIndex(self, index: int) -> None:
        if index < 0 or index >= len(self._items):
            index = -1
        if index != self._cur:
            self._cur = index
            self._update_label()
            if not self.signalsBlocked():
                self.currentIndexChanged.emit(index)

    # ---------- 内部 ----------

    def _sync_menu(self) -> None:
        """弹出前按当前选项重建菜单（addItem/clear 只改内部表，弹出时才建 QAction）。"""
        self._menu.clear()
        for i, (text, _) in enumerate(self._items):
            act = self._menu.addAction(text)
            act.setData(i)

    def _on_pick(self, act) -> None:
        i = act.data()
        if not isinstance(i, int) or not (0 <= i < len(self._items)):
            return
        self._cur = i
        self._update_label()
        if not self.signalsBlocked():
            self.currentIndexChanged.emit(i)
        self.activated.emit(i)  # 用户点选（含重选同一项）都会触发

    def _update_label(self) -> None:
        """当前项文字（过长省略号 + tooltip），长度随 resize 变化时重算。"""
        if not hasattr(self, "_label"):
            return
        if 0 <= self._cur < len(self._items):
            full = self._items[self._cur][0]
            avail = max(8, self.width() - 46)
            el = self._label.fontMetrics().elidedText(full, Qt.ElideRight, avail)
            self._label.setText(el)
            self.setToolTip(full if el != full else "")
        else:
            self._label.setText("")
            self.setToolTip("")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_label()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self._menu.popup(self.mapToGlobal(QPoint(0, self.height())))
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:
        event.ignore()  # 不把滚轮变成“换选项”，冒泡给外层页面滚动


class ToggleSwitch(QWidget):
    """启停开关（一元素一职：卡片右上角只留启停 + ⋯）。

    QCheckBox 的方框勾选态在规则卡里和“选择”复选框撞形（两排小方框分不清），
    这里用自绘轨道+旋钮的开关形态替代；toggled(bool) 信号与 QCheckBox 同签名。
    """

    toggled = Signal(bool)

    W, H, KNOB = 36, 20, 14
    PAD = 3
    # P2-4：开关过渡复用设计系统动效语言（150-200ms），与折叠头箭头同源
    ANIM_MS = int(ANIMATION.DURATION_NORMAL * 1000)

    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._checked = bool(checked)
        self._hover = False
        # 旋钮进度 0.0(关)→1.0(开)；paint 据此插值 x 与轨道色，动画驱动它
        self._progress = 1.0 if self._checked else 0.0
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)

    # QPropertyAnimation 驱动的进度属性（0.0 关 → 1.0 开）
    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, v: float) -> None:
        self._progress = float(v)
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def setChecked(self, on: bool) -> None:
        on = bool(on)
        if on != self._checked:
            self._checked = on
            if not self.signalsBlocked():
                self.toggled.emit(self._checked)
            self._animate_to(1.0 if on else 0.0)

    def _animate_to(self, target: float) -> None:
        """旋钮进度过渡到目标态；reduced-motion 时直落（无动画，P2-4）。

        reduced-motion 判定走设计系统 motion_ok()（env 覆盖 + Windows MinAnimate），
        与折叠头箭头同一套口径。"""
        if not motion_ok():
            self._progress = target
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.start()

    def isChecked(self) -> bool:
        return self._checked

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.setChecked(not self._checked)
            return
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    @staticmethod
    def _blend(a: str, b: str, t: float) -> QColor:
        """两 hex 色按 t∈[0,1] 线性插值（轨道关→开着色过渡）。"""
        ca, cb = QColor(a), QColor(b)
        return QColor(int(ca.red() + (cb.red() - ca.red()) * t),
                      int(ca.green() + (cb.green() - ca.green()) * t),
                      int(ca.blue() + (cb.blue() - ca.blue()) * t))

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QRectF(0, 0, self.W, self.H)
        t = self._progress  # 0 关 → 1 开
        # 轨道底色：关(中性)→开(品牌) 按进度插值；hover 各取对应加深档
        off = C.surface if self._hover else C.surface_3
        on = C.brand_800 if self._hover else C.brand_700
        fill = self._blend(off, on, t)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(track, self.H / 2, self.H / 2)
        # 边框仅关态可见，随进度淡出（避免开/关边框跳变）
        if t < 0.999:
            # Qt 6.11 移除了 QPen/QBrush.setOpacity()，透明度改走颜色 alpha
            col = QColor(C.line_strong)
            col.setAlphaF(1.0 - t)
            pen = QPen(col, 1)
            p.setPen(pen)
            p.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5),
                              self.H / 2, self.H / 2)
        # 旋钮 x 按进度插值：PAD → W-KNOB-PAD
        kx = self.PAD + t * (self.W - self.KNOB - 2 * self.PAD)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C.on_brand))
        p.drawEllipse(QRectF(kx, self.PAD, self.KNOB, self.KNOB))
        p.end()


class FlowLayout(QLayout):
    """流式布局：放不下的子项自动换行（模板类目 chips 不再横向溢出）。

    Qt 官方 FlowLayout 示例的简化版；heightForWidth 让外层 QVBoxLayout
    按折行后的实际高度排布，chips 少一行时不留竖白。
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = 4):
        super().__init__(parent)
        self._spacing = spacing
        self._items: list = []

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_h = 0
        right = rect.right() - m.right()
        for it in self._items:
            hint = it.sizeHint()
            if x + hint.width() > right and x > rect.x() + m.left():
                x = rect.x() + m.left()
                y += line_h + self._spacing
                line_h = 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class Drawer(QWidget):
    """右侧详情抽屉（接入页错误详情，接入页设计优化方案  /  唯一新组件）。

    设计：
    - 作为父容器（接入页根 QWidget）的子控件，覆盖其右侧 D.DRAWER_W 宽区域，
      随父容器重建（主题/语言切换重页面时自动换新实例，无跨重建悬空引用）。
    - 打开自右缘滑入、关闭滑出（DURATION_NORMAL 150ms；reduced-motion 直落端点）。
      滑动用自定义 ``offset`` 属性（0=全开，1=全出屏右），在 setter 里重算几何，
      不直接动画 ``pos``（QWidget.pos 非可写属性）。
    - ``set_content(widget)`` 填充正文；主列表保持干净，详情只进抽屉。
    - 高度跟随父容器（resizeEvent 同步），始终贴右缘。
    """

    closed = Signal()

    def __init__(self, title: str, parent: QWidget,
                 on_close=None) -> None:
        super().__init__(parent)
        self.setObjectName("detailDrawer")
        self._title = title
        self._offset = 1.0  # 初始全出屏（隐藏态）
        self._on_close = on_close
        self.setFixedWidth(D.DRAWER_W)
        # 抽屉本体只负责滑入滑出的几何（贴右缘），背景透明；真正可视的是内部
        # _panel 浮层卡——完整 1px 边框 + 四角圆角 + 次级底，四周留白让边框
        # 完整可见（不再贴窗边、不再与页面同色"融为一体"）。
        self.setStyleSheet("QWidget#detailDrawer { background: transparent; }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(S.s3, S.s3, S.s3, S.s3)
        outer.setSpacing(0)
        self._panel = QFrame()
        self._panel.setObjectName("detailDrawerPanel")
        self._panel.setStyleSheet(
            f"QFrame#detailDrawerPanel {{ background: {C.surface_2};"
            f" border: 1px solid {C.line_strong};"
            f" border-radius: {R.lg}px; }}")
        lay = QVBoxLayout(self._panel)
        lay.setContentsMargins(S.s4, S.s4, S.s4, S.s4)
        lay.setSpacing(S.s3)
        head = QHBoxLayout()
        head.setSpacing(S.s2)
        self._title_label = txt(title, F.h1, 700, C.ink_900)
        head.addWidget(self._title_label)
        head.addStretch(1)
        close_btn = icon_button("close", t("关闭"), on_click=self._do_close,
                                color=C.ink_500)
        head.addWidget(close_btn)
        lay.addLayout(head)
        # 标题与正文之间一道细分隔线（留白/细线分层，替代无边界）
        head_div = QFrame()
        head_div.setFrameShape(QFrame.Shape.HLine)
        head_div.setStyleSheet(f"color: {C.line}; background: {C.line};")
        head_div.setFixedHeight(D.BORDER_W)
        lay.addWidget(head_div)
        self._body = QScrollArea()
        self._body.setWidgetResizable(True)
        self._body.setFrameShape(QFrame.Shape.NoFrame)
        self._body_widget = QWidget()
        self._body_widget.setStyleSheet("background: transparent;")
        self._body_layout = QVBoxLayout(self._body_widget)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(S.s3)
        self._body.setWidget(self._body_widget)
        lay.addWidget(self._body, 1)
        outer.addWidget(self._panel)
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(int(ANIMATION.DURATION_NORMAL * 1000))
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.hide()

    # ---------- offset 动画属性（0=全开贴右缘，1=全出屏右） ----------

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, v: float) -> None:
        self._offset = float(v)
        self._reposition()

    offset = Property(float, _get_offset, _set_offset)

    def _reposition(self) -> None:
        """按 offset 计算几何：贴父容器右缘，x 从 (父宽-抽屉宽)(全开)→父宽(全出右)。

        offset=0 全开贴右缘（x=父宽-抽屉宽）；offset=1 全出屏向右（x=父宽）。
        旧式 (父宽-抽屉宽)*(1-offset) 会在 offset=1 时落到 x=0（左缘），
        使右抽屉打开瞬间先闪现左缘再滑到右缘——方向反了。
        """
        p = self.parentWidget()
        if p is None:
            return
        pw = max(p.width(), 0)
        ph = max(p.height(), 0)
        x = int(round((pw - self.width()) + self._offset * self.width()))
        self.setGeometry(x, 0, self.width(), ph)

    def set_title(self, title: str) -> None:
        self._title = title
        if getattr(self, "_title_label", None) is not None:
            self._title_label.setText(title)

    def set_content(self, widget: QWidget) -> None:
        """替换正文（旧内容 deleteLater）；正文超宽由内部滚动兜底。"""
        lay = self._body_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if widget is not None:
            lay.addWidget(widget)

    # ---------- 开 / 关 ----------

    def show_open(self) -> None:
        """滑入打开（reduced-motion 直落）。"""
        self.raise_()
        self._reposition()
        self.show()
        if not motion_ok():
            self._offset = 0.0
            self._reposition()
            return
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _do_close(self) -> None:
        if not motion_ok():
            self._offset = 1.0
            self._reposition()
            self.hide()
        else:
            self._anim.stop()
            self._anim.setStartValue(self._offset)
            self._anim.setEndValue(1.0)
            self._anim.finished.connect(self._finish_close)
        if self._on_close is not None:
            self._on_close()

    def _finish_close(self) -> None:
        try:
            self._anim.finished.disconnect(self._finish_close)
        except (RuntimeError, TypeError):
            pass
        self.hide()
        self.closed.emit()

    def close_drawer(self) -> None:
        """外部关闭入口（等价点 × / 按 Esc）。"""
        self._do_close()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._reposition()


class DetailDrawer(Drawer):
    """统一下钻抽屉：标题 + 状态徽标 + 正文 + 来源区 + 操作槽。

    ``kind ∈ {"experience","method","failure","preference","session"}``；
    ``payload`` 字段缺失一律容错跳过，**绝不抛异常**（各调用方字段约定见
）。位置/动效沿用 Drawer 的右侧滑入；``open_detail`` 用
    ``DURATION_DIALOG`` + ``EASE_OUT_QUART``（比 Drawer 默认更缓）。
    """

    def __init__(self, parent: QWidget, on_close=None) -> None:
        super().__init__("", parent, on_close=on_close)
        self._kind = ""
        self._actions = QWidget()
        self._actions_lay = QHBoxLayout(self._actions)
        self._actions_lay.setContentsMargins(0, 0, 0, 0)
        self._actions_lay.setSpacing(S.s2)
        self._actions_lay.addStretch(1)
        self._actions.setVisible(False)
        self._panel.layout().addWidget(self._actions)

    # ---------- 打开 ----------

    def open_detail(self, kind: str, payload: dict | None = None) -> None:
        """按 kind + payload 组装并滑入；任何组装异常降级为空正文，不抛。"""
        data = dict(payload or {})
        self._kind = str(kind or "")
        try:
            self._build_detail(data)
        except Exception as exc:  # noqa: BLE001 fail-open：详情渲染失败降级
            _logger.warning("DetailDrawer 渲染 %s 失败，降级空正文: %s", kind, exc)
            self.set_title(self._kind_label())
            self.set_content(txt(t("暂无详情"), F.body, color=C.ink_500))
        self._anim.setDuration(int(ANIMATION.DURATION_DIALOG * 1000))
        self._anim.setEasingCurve(_ease(ANIMATION.EASE_OUT_QUART))
        self.show_open()

    # ---------- 组装 ----------

    def _build_detail(self, payload: dict) -> None:
        self.set_title(str(payload.get("title") or self._kind_label()))
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S.s3)
        badge = str(payload.get("status") or "")
        if badge:
            lay.addWidget(chip(badge, str(payload.get("status_tone") or "ink")))
        md = str(payload.get("body") or payload.get("content") or "")
        if md.strip():
            lay.addWidget(md_view(md))
        src = self._source_section(payload)
        if src is not None:
            lay.addWidget(src)
        lay.addStretch(1)
        self.set_content(body)

    def _kind_label(self) -> str:
        return {"experience": t("经验"), "method": t("方法"),
                "failure": t("踩过的坑"), "preference": t("偏好"),
                "session": t("任务记录")}.get(self._kind, t("详情"))

    def _source_section(self, payload: dict) -> QWidget | None:
        """来源区（经验 id 链 / agent 分布 / 时间轨迹）：三者皆无则返回 None。"""
        rows: list[str] = []
        ids = payload.get("experience_ids") or payload.get("ids") or []
        if ids:
            rows.append(t("来源经验：") + "、".join(str(x) for x in ids))
        agents = payload.get("agents") or payload.get("agent_dist") or {}
        if isinstance(agents, dict) and agents:
            rows.append(t("记录来源：") + "、".join(
                f"{k} {v}" for k, v in agents.items()))
        timeline = payload.get("time_range") or payload.get("timeline") or ""
        if timeline:
            rows.append(t("时间轨迹：") + str(timeline))
        if not rows:
            return None
        box = QFrame()
        box.setObjectName("detailSource")
        box.setStyleSheet(
            f"QFrame#detailSource {{ background: {C.surface_2}; border: none;"
            f" border-left: {SIZES.EXPORT_ACCENT_WIDTH}px solid {C.line_strong};"
            f" border-radius: {R.sm}px; }}")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(S.s3, S.s2, S.s3, S.s2)
        bl.setSpacing(S.s1)
        for line in rows:
            bl.addWidget(txt(line, F.caption, color=C.ink_500, wrap=True))
        return box

    # ---------- 操作槽 ----------

    def set_actions(self, buttons: list) -> None:
        """底部操作槽：调用方注入按钮（先清空旧的）；空列表则隐藏槽位。"""
        lay = self._actions_lay
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        lay.addStretch(1)
        for b in buttons or []:
            if b is not None:
                lay.addWidget(b)
        self._actions.setVisible(bool(buttons))


class ReworkChart(QWidget):
    """周柱 + 返工率折线复合图（成长页重构思 ，磨合度时间轴）。

    柱 = 每周任务数（brand_500，峰值周 brand_600）；线 = 平均每个任务被
    纠正几回（info_fg，右轴）。三条刻意的口径纪律：

    - **空周不连线**：没有记录的周（rate=None）两侧断开，绝不跨空周画直线
      ——真机 7 月中间 4 周无记录，连线会把"零样本"读成"从零涨到 5"。
    - **峰值柱顶标数值**（0 不标），其余周靠 hover tooltip 读数。
    - **宽度自适应**：柱位按可用宽均分（不写死总宽），避免把外层滚动区
      撑出横向滚动条（QScrollArea 最小宽撑破的老坑）。
    """

    def __init__(self, weekly: list[dict], parent=None):
        super().__init__(parent)
        self._rows = list(weekly)
        self._hover = -1
        self._progress = 1.0  # fail-open：未调用 animate_in 时就是终态
        self.setMouseTracking(True)
        n = max(1, len(self._rows))
        self.setMinimumSize(D.CHART_COMBO_GUTTER * 2 + D.CHART_COMBO_COL_W,
                            D.CHART_COMBO_H + D.CHART_COMBO_AXIS_H)
        self.setMaximumHeight(D.CHART_COMBO_H + D.CHART_COMBO_AXIS_H)
        self._n = n

    # 入场动画进度（0→1）；初值 1.0，见 _animate_progress 的 fail-open 约定
    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, v: float) -> None:
        self._progress = max(0.0, min(1.0, float(v)))
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def animate_in(self, duration: float | None = None) -> None:
        """入场动画：柱高与折线点自基线生长。"""
        _animate_progress(self, duration)

    # ---------- 几何 ----------

    def _slot(self, i: int) -> QRectF:
        """第 i 个周槽位（左右各留一条数值 gutter，标签不被柱挤出画布）。"""
        left = D.CHART_COMBO_GUTTER
        usable = max(D.CHART_COMBO_COL_W,
                     self.width() - left - D.CHART_COMBO_GUTTER)
        step = usable / self._n
        return QRectF(left + step * i, 0, step, self.height())

    def _y_of(self, v: float, mx: float) -> float:
        """值 → 绘图区 y（0 线在 CHART_COMBO_H − caption，顶线在 caption）。"""
        plot = D.CHART_COMBO_H - F.caption * 2
        return D.CHART_COMBO_H - F.caption - (v / max(mx, 0.001)) * plot

    # ---------- 交互 ----------

    def _index_at(self, pos: QPoint) -> int:
        left = D.CHART_COMBO_GUTTER
        usable = max(D.CHART_COMBO_COL_W, self.width() - left - S.s2)
        i = int((pos.x() - left) / (usable / self._n))
        return i if 0 <= i < self._n else -1

    def mouseMoveEvent(self, event):
        i = self._index_at(event.position().toPoint())
        if i != self._hover:
            self._hover = i
            self.update()
        if i >= 0:
            self.setToolTip(self._tip(self._rows[i]))
        else:
            self.setToolTip("")
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover = -1
        self.setToolTip("")
        self.update()
        super().leaveEvent(event)

    def _tip(self, row: dict) -> str:
        rate = row.get("rate")
        week = str(row.get("week") or "")[5:]
        if not row.get("sessions"):
            return f"{week} · {t('这一周没有记录')}"
        if rate is None:
            return f"{week} · {row['sessions']} {t('次任务')}"
        return (f"{week} · {row['sessions']} {t('次任务')} · "
                f"{t('平均每个任务纠正 {n} 回', n=rate)}")

    # ---------- 绘制 ----------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._rows:
            p.end()
            return
        w = self.width()
        base = self._y_of(0, 1)                     # 0 线
        top = self._y_of(1, 1)                      # 顶线
        mx_sess = max([float(r.get("sessions") or 0) for r in self._rows] + [1.0])
        rates = [float(r["rate"]) for r in self._rows if r.get("rate") is not None]
        mx_rate = max(rates + [1.0])

        # 网格线 + 左轴（任务数）/ 右轴（返工率）刻度
        p.setPen(QPen(QColor(CHART_AXIS_COLOR), SIZES.CHART_AXIS_WIDTH))
        for i in range(THRESHOLDS.CHART_GRID_LINES + 1):
            y = top + (base - top) * i / THRESHOLDS.CHART_GRID_LINES
            p.drawLine(int(D.CHART_COMBO_GUTTER - S.s2), int(y),
                       int(w - D.CHART_COMBO_GUTTER + S.s2), int(y))
        f = QFont(self.font())
        f.setPixelSize(F.caption)
        p.setFont(f)
        p.setPen(QPen(QColor(C.ink_500)))
        for i in range(THRESHOLDS.CHART_GRID_LINES + 1):
            y = top + (base - top) * i / THRESHOLDS.CHART_GRID_LINES
            share = 1 - i / THRESHOLDS.CHART_GRID_LINES
            # 左轴取整（任务数是整数，107/3 这种小数既难看又挤爆 gutter）
            p.drawText(QRectF(0, y - F.caption, D.CHART_COMBO_GUTTER - S.s2,
                              F.caption * 2),
                       Qt.AlignRight | Qt.AlignVCenter,
                       f"{round(mx_sess * share)}")
            p.drawText(QRectF(w - D.CHART_COMBO_GUTTER + S.s2, y - F.caption,
                              D.CHART_COMBO_GUTTER - S.s2 * 2, F.caption * 2),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       f"{mx_rate * share:.1f}")

        # 柱 = 每周任务数（峰值周加深一档）；入场动画自基线生长
        for i, r in enumerate(self._rows):
            n = float(r.get("sessions") or 0)
            if n <= 0:
                continue
            slot = self._slot(i)
            bw = min(D.CHART_COMBO_COL_W, slot.width() - S.s2)
            y0 = self._y_of(n, mx_sess)
            yt = base + (y0 - base) * self._progress
            rect = QRectF(slot.center().x() - bw / 2, yt, bw, base - yt)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(C.brand_600 if n >= mx_sess else C.brand_500))
            p.drawRoundedRect(rect, D.BORDER_W * 2, D.BORDER_W * 2)
            if i == self._hover:
                p.setBrush(QColor(C.ink_900))
                p.drawRoundedRect(rect, D.BORDER_W * 2, D.BORDER_W * 2)
            # 动画期间不标数值（避免数字先堆在基线）
            if (n >= mx_sess or i == self._hover) and self._progress >= 1.0:
                p.setPen(QPen(QColor(C.ink_700)))
                p.drawText(QRectF(slot.left(), yt - F.caption * 2,
                                  slot.width(), F.caption * 2),
                           Qt.AlignHCenter | Qt.AlignBottom, f"{n:g}")
                p.setFont(f)

        # 折线 = 返工率（空周断开，不跨零样本连线）；点位置同步插值
        line = QPen(QColor(C.info_fg), SIZES.CHART_AXIS_WIDTH * 2)
        seg: list[QPointF] = []
        for i, r in enumerate(self._rows):
            rate = r.get("rate")
            if rate is None:
                self._stroke(p, line, seg)
                seg = []
                continue
            y_rate = self._y_of(float(rate), mx_rate)
            seg.append(QPointF(self._slot(i).center().x(),
                               base + (y_rate - base) * self._progress))
        self._stroke(p, line, seg)
        p.setPen(QPen(QColor(C.info_fg), SIZES.CHART_AXIS_WIDTH * 2))
        p.setBrush(QColor(C.surface))
        rad = D.CHART_COMBO_DOT / 2
        for i, r in enumerate(self._rows):
            if r.get("rate") is None:
                continue
            y_rate = self._y_of(float(r["rate"]), mx_rate)
            p.drawEllipse(QPointF(self._slot(i).center().x(),
                                  base + (y_rate - base) * self._progress),
                          rad, rad)

        # 周标签（M/D）
        p.setPen(QPen(QColor(C.ink_500)))
        for i, r in enumerate(self._rows):
            slot = self._slot(i)
            p.drawText(QRectF(slot.left(), base + S.s1, slot.width(),
                              D.CHART_COMBO_AXIS_H),
                       Qt.AlignHCenter | Qt.AlignTop,
                       str(r.get("week") or "")[5:].replace("-", "/"))
        p.end()

    @staticmethod
    def _stroke(p: QPainter, pen: QPen, pts: list) -> None:
        if len(pts) >= 2:
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)


def page_header(title: str, subtitle: str | None = None,
                actions: list[QWidget] | None = None, *,
                dense: bool = False, mascot: str | None = None,
                top: int = S.s8, side: int = 0) -> QWidget:
    """统一页头（UI 统一化第 1 波 S1）：标题 + 可选副标题 + 可选操作行。

    收敛此前 10 个页面各写各的页头（有的 `S.s1` 有的 `S.s2` 间距、有的有副标题
    有的没有、有的带吉祥物、外边距兜底也不一致）。一处改动全站生效。

    - ``dense=True``（嵌入档）：标题降为 ``F.h2``（节标题档）——**注意字阶表只有
      28/20/16/14/12 六档**（`txt()` 对表外字号直接 raise），没有 17px 这一档，
      故"嵌入档"就是 h2；嵌套在宿主页标题之下时 h2 也是语义正确的那一档。
    - **顶边留白由本组件提供**（缺省 `S.s8`=32），配 `page_scaffold(top=0)` 使用，
      避免"骨架 + 页头"两处各加 32 叠成 64px（「我的经验」历史上就是这么叠出来的）。
    - ``side``：左右留白。默认 0——页头作为滚动列的子控件时，左右由 `page_scaffold`
      给；**页头在滚动区之外**（如「我的经验」容器页的固定头部）时才需显式传
      `side=S.s8` 以与滚动列对齐。
    - ``actions`` 依次排到标题行右侧（间距 `S.s2`）。
    - 标题/副标题带 ``objectName``（``pageTitle`` / ``pageSubtitle``）——语言切换时
      页面用 ``findChild(QLabel, "pageTitle")`` 取回原地重译，不必各自持引用。
    """
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(side, top, side, 0)
    lay.setSpacing(S.s2)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(S.s2)
    if mascot:
        from .qt_theme import mascot_image
        m = mascot_image(mascot, SIZES.MASCOT_DIALOG_TITLE)
        m.setObjectName("pageMascot")   # 供调用方 findChild 取回（如接入页换表情）
        row.addWidget(m)
    title_lbl = txt(title, F.h2 if dense else F.h1, 800, C.ink_900)
    title_lbl.setObjectName("pageTitle")
    row.addWidget(title_lbl)
    row.addStretch(1)
    for w in (actions or ()):
        if w is not None:
            row.addWidget(w)
    lay.addLayout(row)

    if subtitle:
        sub = txt(subtitle, F.caption, color=C.ink_500)
        sub.setWordWrap(True)
        sub.setObjectName("pageSubtitle")
        lay.addWidget(sub)
    return box


def section(title: str | None = None, subtitle: str | None = None, *,
            content: QWidget | None = None, padding: int = S.s4,
            secondary: bool = False) -> QFrame:
    """统一"分节"容器（UI 统一化第 1 波 S4）：卡片底 + 节标题 + 可选副标题。

    **节标题规格与 `qt_theme.card(title=…)` 完全一致**（`F.h2` / 600 / `C.ink_700`）
    ——全站"节标题"只有这一种规格；本组件只是把它显式化，供需要"标题 + 副标题"的
    分节使用。两者**不得漂移**，由 `test_section_title_spec_matches_card` 锁定。
    """
    from .qt_theme import card as _card

    box = _card(content=content, title=None, padding=padding, secondary=secondary)
    lay = box.layout()
    if title:
        lay.insertWidget(0, txt(title, F.h2, 600, C.ink_700))
    if subtitle:
        idx = 1 if title else 0
        sub = txt(subtitle, F.caption, color=C.ink_500)
        sub.setWordWrap(True)
        lay.insertWidget(idx, sub)
    return box


def stagger_in(widgets, *, rise: int | None = None,
               step_ms: int | None = None, max_ms: int | None = None) -> None:
    """列表/网格**首屏**「错峰入场」：逐项从下方 `rise` 像素滑回最终位。

    消费早已定义但一直未接线的 `STAGGER_STEP_MS` / `MAX_STAGGER_MS`。

    **性能纪律（与对齐，硬要求）**：
    - **只动 `pos`**——绝不挂 `QGraphicsOpacityEffect`、绝不动 `blurRadius`/模糊。
      这两者正是刚从卡片上省掉的逐控件 CPU 合成开销（300 卡 11→53ms）；
      为"入场"把它们加回来等于把优化成果吃回去。
    - `motion_ok()` 为假 **或** `low_fx()` 为真 → **直接返回**：内容以终态瞬时呈现
      （fail-open，不因降级丢信息、也不留半截动画）。
    - 单项异常只记日志，不影响其余项，更不影响渲染结果。
    - **只用于首屏新插入**的项；轮询刷新（`sync_tracked` 原地复用）**不得**调用，
      否则每轮轮询整个列表重放一次入场。

    延迟 = ``min(idx * step_ms, max_ms)``（首项不延迟，逐项递增，封顶）。
    """
    if not motion_ok() or low_fx():
        return
    items = [w for w in widgets if w is not None]
    if not items:
        return
    step = ANIMATION.STAGGER_STEP_MS if step_ms is None else int(step_ms)
    cap = ANIMATION.MAX_STAGGER_MS if max_ms is None else int(max_ms)
    offset = S.s1 if rise is None else int(rise)
    keep: list = []  # 保引用：动画对象需活到播完
    for idx, w in enumerate(items):
        try:
            base = w.pos()
        except Exception:  # noqa: BLE001 控件已销毁 → 跳过该项
            continue

        def _play(w=w, base=base, delay=min(idx * step, cap)) -> None:
            try:
                if not motion_ok() or low_fx():
                    return
                anim = QPropertyAnimation(w, b"pos", w)
                anim.setDuration(int(ANIMATION.DURATION_HOVER * 1000))
                anim.setEasingCurve(_ease(ANIMATION.EASE_OUT_CUBIC))
                anim.setStartValue(QPoint(base.x(), base.y() + offset))
                anim.setEndValue(base)
                anim.start()
                keep.append(anim)
            except Exception as exc:  # noqa: BLE001 单项失败不影响其余
                _logger.warning("stagger_in 单项动画失败: %s", exc)

        try:
            w.move(base.x(), base.y() + offset)  # 先下移一档，再滑回
            if idx == 0 and step == 0:
                _play()
            else:
                QTimer.singleShot(min(idx * step, cap), _play)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("stagger_in 布点失败: %s", exc)
    # 动画播完即释放引用（用一个短命定时器兜住，避免 keep 泄漏）
    QTimer.singleShot(cap + int(ANIMATION.DURATION_HOVER * 1000) + 50, keep.clear)


def count_up(label, target: int, *, start: int = 0,
             duration: float | None = None, size: int | None = None) -> None:
    """数字滚动：把 `label` 上的数字从 `start` 滚到 `target`。

    **性能纪律**：
    - **只改文本**（`setText`），零 `graphicsEffect`、零模糊——不动刚省掉的
      逐控件 CPU 合成路径；
    - 起步时按**终值**给 label 设最小宽（用全站唯一的 `layout.text_width` 测量；
      `size` 传该 label 的实际字号，缺省按 `F.display`），避免"数字变长 → 控件变宽
      → 整行重排"的抖动（CLS 那类问题）；
    - `motion_ok()` 为假 / `low_fx()` 为真 / 目标非正 / 任何异常 → **直接写终值**
      （fail-open：绝不把数字留在 0）；
    - 动画对象挂 `label` 上，随控件销毁自然回收，无需额外清理。
    """
    try:
        final = int(target)
    except (TypeError, ValueError):
        return
    text = str(final)
    if not motion_ok() or low_fx() or final <= start:
        label.setText(text)
        return
    try:
        from .layout import text_width
        label.setMinimumWidth(
            int(text_width(text, size or F.display, 800)) + S.s1)
    except Exception:  # noqa: BLE001 测宽失败不影响滚动
        pass
    try:
        anim = QVariantAnimation(label)
        anim.setDuration(int((ANIMATION.DURATION_NORMAL * 2 if duration is None
                              else duration) * 1000))
        anim.setStartValue(float(start))
        anim.setEndValue(float(final))
        anim.setEasingCurve(_ease(ANIMATION.EASE_OUT_CUBIC))
        anim.valueChanged.connect(
            lambda v, lb=label: lb.setText(str(int(round(float(v))))))
        anim.finished.connect(lambda lb=label: lb.setText(text))
        anim.start()
        label._count_anim = anim  # 保引用（随 label 销毁回收）
    except Exception as exc:  # noqa: BLE001 fail-open：动画失败就写终值
        _logger.warning("数字滚动失败，写终值: %s", exc)
        label.setText(text)


__all__ = ["HeatBar", "ColumnsChart", "HBarRow", "RotatingIcon", "NavButton",
           "SelectButton", "ToggleSwitch", "FlowLayout", "Drawer", "ReworkChart",
           "SkeletonBlock", "skeleton_column", "AnimatedStack", "DetailDrawer",
           "hover_lift", "ShadowCard", "page_header", "section", "stagger_in",
           "count_up"]
