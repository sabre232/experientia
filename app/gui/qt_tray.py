"""系统托盘（QSystemTrayIcon 原生实现，零额外依赖）（迁移清单）。

窗口关闭时隐藏到托盘而非退出；托盘菜单含「显示」「退出」两项。
系统级原生通知弹窗也走这里（notify_native，通知形态）。
"""

from __future__ import annotations

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon

from .i18n import t


def setup_tray(window: QMainWindow, icon_path: str = "") -> QSystemTrayIcon | None:
    """为主窗口设置系统托盘图标。无托盘能力 → 返回 None（静默降级）。

    Windows 托盘图标必须使用 .ico 格式才能正确渲染，
    其他平台（macOS/Linux）用 .png 即可。
    """
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None

    if not icon_path:
        # 图标路径唯一入口（theme.app_icon_file：Win 用 .ico，其余 .png）
        from .theme import app_icon_file

        icon_path = str(app_icon_file())

    tray = QSystemTrayIcon(QIcon(icon_path), window)
    tray.setToolTip("Experientia")

    menu = QMenu()

    show_action = QAction(t("显示"), window)
    show_action.triggered.connect(lambda: _show_window(window))
    menu.addAction(show_action)

    menu.addSeparator()

    quit_action = QAction(t("退出"), window)
    quit_action.triggered.connect(lambda: _quit_app(window))
    menu.addAction(quit_action)

    # 语言切换时由主窗口 _retranslate_chrome 按 key 原地翻译
    window._tray_actions = {"显示": show_action, "退出": quit_action}

    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: _on_activated(reason, window))
    tray.show()
    return tray


def _show_window(window: QMainWindow) -> None:
    window.showNormal()
    window.raise_()
    window.activateWindow()


def notify_native(window: QMainWindow, title: str, body: str = "") -> bool:
    """发一条系统级原生通知弹窗（通知形态，无独立开关）。

    Windows 上即系统通知（落操作中心），非应用内自绘弹层。
    托盘不可用（无托盘环境 / 未初始化）→ 返回 False，由调用方降级，
    不在这里静默吞掉（调用方决定回退形态）。
    """
    tray = getattr(window, "_tray", None)
    if tray is None or not tray.isVisible():
        return False
    try:
        tray.showMessage(title, body)
    except Exception:  # 平台后端异常不阻断通知链路（如无 GUI 会话）
        return False
    return True


def _quit_app(window: QMainWindow) -> None:
    window._allow_quit = True  # 绕过关闭拦截（见 main_window.closeEvent）
    QApplication.quit()


def _on_activated(reason, window: QMainWindow) -> None:
    if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
        _show_window(window)
