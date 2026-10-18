"""B/C 类尺寸派生。

A 类（"长什么样"）在 theme.py 的 token；本模块只回答两个问题：
- B 类：内容要多宽（text_width——全 app 唯一的文本测量函数）
- C 类：窗口还剩多少（clamp——比例 + 夹取，P3 起对话框/代码框走这里）

**测量是单一事实来源**：运行时 B 类容器用它算宽，测试护栏也用它校验，
两套不可能各说各话。跨机器稳定性依据（章程 /）：
- 拉丁/数字：内嵌 Manrope（assets/fonts，OFL）→ 任何机器同一份字体，测量恒定；
- CJK：走系统回退字体，全角字宽 ≈ 1em 是雅黑/苹方/思源的稳定上界 →
  按 1em 计宽，实际渲染只会"略窄于上界"，容器按上界留宽则永不溢出。
DPI 缩放不进入本模块：Qt 布局单位是逻辑像素（device-independent），缩放由框架在渲染层处理。
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

from .theme import F

_FONT_PATH = (Path(__file__).resolve().parents[2] / "assets" / "fonts"
              / "Manrope-Medium.ttf")

# 内嵌文件是 Medium(500)。Regular 略窄、W_600/Bold 略宽——非 Regular 一律
# ×1.05 上界（容器按上界留宽，偏差方向只会是"略窄"，不会溢出）。
_BOLD_FACTOR = 1.05


@lru_cache(maxsize=None)
def _pil_font(size: int):
    """PIL 惰性导入：本模块在 main_window 依赖链上，顶层拉 PIL 实测
    ~42ms 却只有此函数用；`from __future__ import annotations` 使返回注解不求值。"""
    from PIL import ImageFont

    return ImageFont.truetype(str(_FONT_PATH), size)


def text_width(s: str, size: int = F.body,
               weight=None) -> float:
    """逻辑像素宽：拉丁/数字内嵌 Manrope 实测；CJK 按 1em（= size）上界。

    weight：None = 常规；非 None（加粗）一律 ×_BOLD_FACTOR 上界。
    """
    f = _pil_font(size)
    factor = _BOLD_FACTOR if weight is not None else 1.0
    return sum(size if unicodedata.east_asian_width(ch) in ("W", "F")
               else f.getlength(ch) * factor for ch in s)


def clamp(v: float, lo: float, hi: float) -> float:
    """C 类夹取：任意窗口尺寸下输出恒在 [lo, hi]（护栏会校验）。"""
    return max(lo, min(hi, v))


# 窗口默认/最小尺寸（A 类：设计骨架，deck 口径"1200×800 对内容够用"）
WINDOW_DEFAULT = (1200, 800)
WINDOW_MIN = (1000, 640)


def initial_window_size(
        screen: tuple[int, int] | None) -> tuple[int, int, int, int]:
    """C 类（章程）：启动窗口尺寸 = 默认值 clamp 到屏工作区。

    返回 (width, height, min_width, min_height)，全部逻辑像素。
    screen=None（取不到屏尺寸）→ 原样返回默认/最小值（与现状一致，不猜不崩）。
    """
    dw, dh = WINDOW_DEFAULT
    mw, mh = WINDOW_MIN
    if not screen:
        return dw, dh, mw, mh
    sw, sh = screen
    return (min(dw, sw), min(dh, sh), min(mw, sw), min(mh, sh))


def dialog_width(window: tuple[int, int]) -> int:
    """C 类（章程）：对话框宽 = 窗口宽 85%，夹在 [420, 720]。

    as-built 偏差：原计划公式减去导航宽——但对话框是 Material overlay
    居中于**整个窗口**（ui.open_dialog → page.overlay），不占导航区，
    减导航宽反而偏小。
    """
    return int(clamp(window[0] * 0.85, 420, 720))


def code_box_size(window: tuple[int, int]) -> tuple[int, int]:
    """C 类（章程）：对话框内代码框 = (窗口宽 60%, 窗口高 55%)，
    夹在 [480, 680] × [240, 460]。窗口缩小时框跟着缩，内容靠 scroll 兜底。"""
    w = int(clamp(window[0] * 0.6, 480, 680))
    h = int(clamp(window[1] * 0.55, 240, 460))
    return w, h


def screen_work_area() -> tuple[int, int] | None:
    """C 类底料：屏**工作区**（排除任务栏）逻辑尺寸，供启动时 clamp 窗口。

    走 OS 标准接口（不引 Qt 屏幕 API 进这个纯函数，保持无 GUI 依赖）：
    - Windows：Win32 SPI_GETWORKAREA（ctypes，标准库，无第三方依赖）；
      返回物理像素，按系统 DPI 缩放（GetDeviceCaps LOGPIXELSX / 96）换算
      逻辑像素——Qt 布局单位同样是逻辑像素（device-independent），DPI 不进布局（见头注）。
    - macOS/Linux：返回 None → 调用方保持默认窗口尺寸（与现状一致；
      不为这一件事引入平台依赖，章程  N6）。
    取不到（API 失败/异常）一律 None，绝不抛。
    """
    import sys

    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(48, 0,  # SPI_GETWORKAREA
                                                        ctypes.byref(rect), 0)
        if not ok:
            return None
        w_phys = rect.right - rect.left
        h_phys = rect.bottom - rect.top
        if w_phys <= 0 or h_phys <= 0:
            return None
        hdc = ctypes.windll.user32.GetDC(None)
        try:
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        finally:
            ctypes.windll.user32.ReleaseDC(None, hdc)
        scale = dpi / 96.0 if dpi else 1.0
        return int(round(w_phys / scale)), int(round(h_phys / scale))
    except Exception:
        return None
