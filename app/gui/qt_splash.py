"""品牌启动闪屏（Qt QSplashScreen）。

体验优化：窗口构建/引擎热身期间先显示 mascot 启动图，避免"点开图标后
桌面几秒无反应"的观感。配色全部走当前色板 token（C.surface 底 +
brand_700 品牌字），明暗模式自动跟随。背景资产 assets/mascot_smile.png
由 make_icons.py 派生（与 icon/splash 同一母版）。
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

from .theme import C, FONT, MASCOTS

# 启动动画循环（表情包轮播，均是 assets/mascot_*.png 现成表情）
SPLASH_CYCLE = ("smile", "think", "search", "write", "peace", "love")


def make_splash_pixmap(mascot: str = "smile", caption: str = "",
                       width: int = 480, height: int = 320) -> QPixmap:
    """绘制一帧闪屏：surface 底 + 指定吉祥物表情 + 品牌字 + 阶段文字。

    mascot 取 theme.MASCOTS 的键（smile/think/search/write/peace…）；
    由调用方每帧换表情拼动画；caption 为阶段文案（启动引擎/加载首页…）。
    尺寸按设备像素出图，Windows 高 DPI 下由 Qt 缩放。

    帧缓存：同一 (表情, 文案, 尺寸, 色板) 只绘制一次。闪屏每 450ms 换一帧，
    不做缓存时每帧都要重新解码吉祥物源图再整帧重绘，全压在启动主线程上；
    缓存后除首帧外每帧直接取现成的 QPixmap（配合 qt_theme 的解码缓存）。
    """
    from .qt_theme import cached_pixmap

    name = mascot if mascot in MASCOTS else "smile"
    # 色板进 key：明暗主题切换后旧帧作废
    key = (name, caption, width, height, C.surface, C.brand_700, C.ink_500)
    return cached_pixmap("splash", key,
                         lambda: _draw_splash(name, caption, width, height))


def _draw_splash(name: str, caption: str, width: int, height: int) -> QPixmap:
    """真正绘制一帧闪屏（缓存未命中时调用，见 make_splash_pixmap）。"""
    from .qt_theme import mascot_pixmap

    pm = QPixmap(width, height)
    pm.fill(QColor(C.surface))
    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # 表情走带缓存的目标尺寸取图：不整张解码源图再缩（源图 1024×1024）
        avail_h = int(height * 0.60)
        mascot_pm = mascot_pixmap(name, max(1, avail_h))
        if mascot_pm is not None and mascot_pm.height() > 0:
            top = int(height * 0.04)
            x = (width - mascot_pm.width()) // 2
            painter.drawPixmap(x, top, mascot_pm)

        painter.setPen(QColor(C.brand_700))
        font = QFont(FONT, 22)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            QRect(0, int(height * 0.70), width, int(height * 0.16)),
            Qt.AlignmentFlag.AlignCenter, "Experientia")
        if caption:
            painter.setPen(QColor(C.ink_500))
            cap_font = QFont(FONT, 14)
            painter.setFont(cap_font)
            painter.drawText(
                QRect(0, int(height * 0.82), width, int(height * 0.12)),
                Qt.AlignmentFlag.AlignCenter, caption)
    finally:
        painter.end()
    return pm
