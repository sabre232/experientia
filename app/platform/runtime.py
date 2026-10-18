"""打包运行时判定唯一出口（重构报告 CLN-2 收敛）。

原 install.is_frozen / autostart._is_packaged / main.is_packaged 三处各自判定，
语义与注释漂移。收敛点 = 本模块。

打包 = PyInstaller onedir（见 experientia.spec），运行时由 PyInstaller 注入
`sys.frozen`。flet build 嵌入运行时（FLET_PLATFORM 环境变量）已随 PySide6 迁移
彻底废弃——flet 不在依赖里、spec excludes flet，故本判定只看 sys.frozen。
"""

from __future__ import annotations

import sys


def is_packaged() -> bool:
    """PyInstaller 打包运行时：sys.frozen 由 PyInstaller 设置。"""
    return bool(getattr(sys, "frozen", False))
