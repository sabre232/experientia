"""抓 Experientia 主窗口截图留档（真实窗口，非 mockup）。

用法：uv run python scripts/capture_screenshot.py out.png [--title Experientia]

只截主窗口区域，不含其他窗口；64 位 HWND 与 DPI 感知都已处理，
高分屏上截出来的像素与窗口实际像素一致。
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes.wintypes import RECT

_u = ctypes.windll.user32
_u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
_u.FindWindowW.restype = ctypes.c_void_p
_u.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT)]
_u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
_u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--title", default="Experientia")
    ap.add_argument("--wait", type=int, default=30, help="等窗口的最长时间（秒）")
    a = ap.parse_args()

    # 按物理像素取窗口坐标（否则高分屏下与 ImageGrab 坐标系错位）
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    deadline = time.time() + a.wait
    hwnd = 0
    while time.time() < deadline:
        hwnd = _u.FindWindowW(None, a.title)
        if hwnd:
            break
        time.sleep(1)
    if not hwnd:
        print("找不到窗口:", a.title)
        sys.exit(1)

    r = RECT()
    # 置前再截：窗口被其他窗口（如 IDE）盖住时，屏幕坐标抓到的是别人
    _u.ShowWindow(hwnd, 9)  # SW_RESTORE
    _u.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    _u.GetWindowRect(hwnd, ctypes.byref(r))
    from PIL import ImageGrab

    img = ImageGrab.grab((r.left, r.top, r.right, r.bottom))
    img.save(a.out)
    print(f"已存 {a.out}: {img.size[0]}x{img.size[1]}")


if __name__ == "__main__":
    main()
