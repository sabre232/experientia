"""Qt 图标系统（迁移清单）。

使用 Material Design Icons 字体（.ttf，assets/fonts/），通过 QFontDatabase 加载。
- MDI 名 → Unicode 码点表在 _mdi_map.py（由 scripts/gen_mdi_map.py 生成）。
- Flet 图标名 → MDI 名映射在 FT（迁移页面对照用）。
- icon_widget(name, size, color) → QLabel 图标（对应 theme.icon）。
字体缺失/名未命中 → 中性圆点占位，绝不抛。
"""

from __future__ import annotations

import importlib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QLabel

_MDI_PATH = (Path(__file__).resolve().parents[2] / "assets" / "fonts"
             / "materialdesignicons-webfont.ttf")

# MDI 名 → 码点表（_mdi_map.py，233KB 字典字面量）改为惰性加载。
# 顶层 `from ._mdi_map import MDI` 会让每个 import 本模块的 GUI 模块在导入期
# 整表解析（实测 ~2.7ms，且落在启动首帧之前的主线程上）；改为首个图标名落地
# 时才加载并缓存，对外行为不变（同样的名字返回同样的字形）。
_MDI: dict | None = None


def _mdi() -> dict:
    """取 MDI 名 → 码点表（首次调用加载 `_mdi_map` 并缓存）。"""
    global _MDI
    if _MDI is None:
        _MDI = importlib.import_module(f"{__package__}._mdi_map").MDI
    return _MDI


def __getattr__(name: str):
    """PEP 562 兜底：`from .qt_icons import MDI` 仍可用（qt_theme / qt_widgets 既有
    调用点，本 WS 禁改）。取到的是同一份惰性缓存表，惰性不被破坏。"""
    if name == "MDI":
        return _mdi()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Flet ft.Icons 常量名 → MDI 图标名（页面迁移对照；命名尽量贴近 Material 语义）
FT = {
    "ADD_OUTLINED": "plus",
    "ARROW_DOWNWARD_OUTLINED": "arrow-down",
    "ARROW_LEFT_OUTLINED": "arrow-left",
    "ARROW_RIGHT_OUTLINED": "arrow-right",
    "ARROW_UPWARD_OUTLINED": "arrow-up",
    "ASSESSMENT_OUTLINED": "chart-box-outline",
    "AUTO_AWESOME_OUTLINED": "creation",
    "BUILD_OUTLINED": "hammer-wrench",
    "CHECK_CIRCLE_OUTLINED": "check-circle-outline",
    "CHECK_OUTLINED": "check",
    "CHEVRON_RIGHT_OUTLINED": "chevron-right",
    "CODE_OUTLINED": "code-tags",
    "CONSTRUCTION_OUTLINED": "tools",
    "CONTENT_COPY_OUTLINED": "content-copy",
    "DELETE_OUTLINED": "delete-outline",
    "DOWNLOAD_OUTLINED": "download-outline",
    "DRIVE_FILE_RENAME_OUTLINE_OUTLINED": "file-edit-outline",
    "EDIT_OUTLINED": "pencil-outline",
    "ENGINEERING_OUTLINED": "wrench-cog",
    "EXPAND_MORE_OUTLINED": "chevron-down",
    "FOLDER_OPEN_OUTLINED": "folder-open-outline",
    "FOLDER_OUTLINED": "folder-outline",
    "HUB_OUTLINED": "cloud-outline",
    "IMAGE_OUTLINED": "image-outline",
    "INSIGHTS_OUTLINED": "lightbulb-on-outline",
    "MODEL_TRAINING_OUTLINED": "brain",
    "NOTIFICATIONS_ACTIVE_OUTLINED": "bell-ring-outline",
    "NOTIFICATIONS_OUTLINED": "bell-outline",
    "OPEN_IN_NEW_OUTLINED": "open-in-new",
    "QUERY_STATS_OUTLINED": "chart-line",
    "REDO_OUTLINED": "redo",
    "REFRESH_OUTLINED": "refresh",
    "REPORT_PROBLEM_OUTLINED": "alert-circle-outline",
    "RESTORE_OUTLINED": "history",
    "ROCKET_LAUNCH_OUTLINED": "rocket-launch-outline",
    # 打包字体无 rule/verified/system-update/construction，映射到语义等价 glyph
    "RULE_FOLDER_OUTLINED": "folder-outline",
    "RULE_OUTLINED": "clipboard-text-outline",
    "SAVE_OUTLINED": "content-save-outline",
    "SENSORS_OUTLINED": "access-point",
    "SETTINGS_OUTLINED": "cog-outline",
    "SPACE_DASHBOARD_OUTLINED": "view-dashboard-outline",
    "SYSTEM_UPDATE_OUTLINED": "update",
    "TERMINAL_OUTLINED": "console",
    "VERIFIED_OUTLINED": "shield-check",
    "WARNING_AMBER_OUTLINED": "alert",
    "WARNING_OUTLINED": "alert-outline",
    # 导航选中态（Filled 版；MDI 无 outline/filled 之分，用同 glyph + 选中色表达）
    "SPACE_DASHBOARD": "view-dashboard",
    "INSIGHTS": "lightbulb-on",
    "QUERY_STATS": "chart-line-variant",
    "RULE": "clipboard-text-outline",
    "DOWNLOAD": "download",
    "HUB": "cloud",
    "SETTINGS": "cog",
    "NOTIFICATIONS": "bell",
}

_FONT_ID: int | None = None
_FONT_FAMILY: str | None = None


def _load_font() -> None:
    """加载 MDI 字体，缓存 font id 与 family。"""
    global _FONT_ID, _FONT_FAMILY
    if _FONT_ID is not None:
        return
    _FONT_ID = -1  # 标记已尝试，避免重复加载失败
    if not _MDI_PATH.exists():
        return
    fid = QFontDatabase.addApplicationFont(str(_MDI_PATH))
    if fid >= 0:
        families = QFontDatabase.applicationFontFamilies(fid)
        if families:
            _FONT_FAMILY = families[0]


def icon_glyph(name: str) -> str:
    """MDI 图标名 → Unicode 字符（未命中 → "●" 占位）。"""
    mdi = _mdi()
    if name in mdi:
        return chr(mdi[name])
    return "\u25CF"


def icon_font(size: int = 24) -> QFont:
    """图标字体 QFont（MDI 加载成功用它，否则回退系统字体）。

    注意：仅用作 setFont 的信息来源（供字体度量/自绘控件）；
    作为文本渲染的 QLabel 请走 icon_widget——它用内联样式表锁
    font-family/font-size，避免被全局 QWidget{} 样式覆盖（见下）。"""
    _load_font()
    if _FONT_FAMILY:
        return QFont(_FONT_FAMILY, size)
    return QFont("Segoe UI Symbol", size)


def icon_widget(name: str, size: int = 24, color: str | None = None,
                center: bool = True) -> QLabel:
    """线性图标唯一出口（对应 theme.icon）。

    name 可为 MDI 名（kebab-case）或 Flet 常量名（自动经 FT 映射）。
    size 只许 14/16/18/20/24。

    关键：字体必须走**内联样式表**（font-family + font-size），不能只 setFont——
    全局样式表 QWidget{font-family; font-size} 优先级高于 setFont，
    会把 MDI 字体压回 UI 字体栈（图标变豆腐块）或缩到 14px（与 txt() 同坑）。
    """
    from .theme import C, ICON_SIZES

    if size not in ICON_SIZES:
        size = ICON_SIZES[-1] if size > 24 else (ICON_SIZES[0] if size < 14 else size)
    glyph_name = FT.get(name, name)
    label = QLabel(icon_glyph(glyph_name))
    label.setFont(icon_font(size))
    color = color or C.ink_500
    # 内联样式：font-family 用 MDI 族名（加载失败回退系统符号字体），
    # font-size 显式锁像素，全局 QWidget{} 无法覆盖（内联优先级最高）
    family = _FONT_FAMILY or "Segoe UI Symbol"
    label.setStyleSheet(
        f"color: {color}; background: transparent; border: none;"
        f" font-family: \"{family}\"; font-size: {size}px;")
    if center:
        label.setAlignment(Qt.AlignCenter)
    return label


def restyle_icon(label: QLabel, name: str, color: str, size: int = 24) -> None:
    """原地换 MDI 图标 glyph + 颜色，不 deleteLater 重建 QLabel。

    主题切换 / 选中态切换复用同一 QLabel：setText 换 glyph、setStyleSheet 换色，
    保留字体族 / 字号 / 对齐——替代「insertWidget + removeWidget +
    deleteLater」的交换式替换，消除导航栏重刷期间 deleteLater 与 paint /
    定时器事件竞争的 -805306369 use-after-free 竞态（Qt_theme 切换路径）。
    """
    glyph_name = FT.get(name, name)
    label.setText(icon_glyph(glyph_name))
    family = _FONT_FAMILY or "Segoe UI Symbol"
    label.setStyleSheet(
        f"color: {color}; background: transparent; border: none;"
        f" font-family: \"{family}\"; font-size: {size}px;")
    label._cached_color = color
