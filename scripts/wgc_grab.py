"""经 Windows.Graphics.Capture（WGC）抓窗口合成帧，存 PNG。

适用场景：桌面锁屏 / 无活动控制台时 GDI 截屏（GetDC(NULL)+BitBlt）不可用，
但 DWM 仍在合成窗口——WGC 直接取 DWM 的帧。纯 ctypes COM，无第三方依赖。

用法：uv run python scripts/wgc_grab.py out.png [--title Experientia] [--wait 30]
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes as wt
from ctypes.wintypes import RECT, HWND

kernel32 = ctypes.windll.kernel32  # noqa: F841
user32 = ctypes.windll.user32
ole32 = ctypes.windll.ole32
dxgi = ctypes.windll.dxgi
d3d11 = ctypes.windll.d3d11
storage = ctypes.WinDLL(r"C:\Windows\System32\windows.storage.dll")
rtstr = ctypes.WinDLL(r"C:\Windows\System32\combase.dll")  # 导出 WindowsCreateString

GUID = ctypes.c_ubyte * 16
GUIDREF = ctypes.POINTER(GUID)
PVOID = ctypes.c_void_p
HRESULT = ctypes.c_long  # HRESULT 是 32 位，wintypes 没提供

storage.DllGetActivationFactory.argtypes = [ctypes.c_void_p, GUIDREF,
                                            ctypes.POINTER(PVOID)]
storage.DllGetActivationFactory.restype = HRESULT
rtstr.WindowsCreateString.argtypes = [ctypes.c_wchar_p, wt.UINT,
                                      ctypes.POINTER(ctypes.c_void_p)]
rtstr.WindowsCreateString.restype = HRESULT

user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
user32.FindWindowW.restype = HWND


def _guid(s: str) -> GUID:
    # GUID 内存布局：Data1/2/3 小端，Data4/5 原序
    a, b, c, r, e = s.split("-")
    raw = (bytes.fromhex(a)[::-1] + bytes.fromhex(b)[::-1]
           + bytes.fromhex(c)[::-1] + bytes.fromhex(r) + bytes.fromhex(e))
    buf = GUID()
    ctypes.memmove(buf, raw, 16)
    return buf


# ---------- GUID ----------
IID_IDXGI_FACTORY1 = _guid("77da53e0-9698-458d-80c0-3070d26f3b87")
IID_IDXGI_ADAPTER1 = _guid("291e9c95-356a-405b-808d-3fa5d5a4503f")
IID_IDXGI_OUTPUT1 = _guid("0700bc70-e618-4c92-84f2-bc04d2d75c99")
IID_IDXGI_SURFACE = _guid("0c74bd13-15c6-43c8-90e3-f5a9b8320c82")
IID_IDXGI_SWAP_CHAIN1 = _guid("93d525a1-b765-46b4-b05b-5135cf310f84")
IID_IDXGI_SWAP_CHAIN3 = _guid("47ecd17a-077b-4d4b-8917-fa95abf798c0")
IID_ID3D11_DEVICE = _guid("63c0db00-bad9-428e-894b-14a63b4c4278")
IID_ID3D11_DEVICE_CONTEXT = _guid("54ec79a5-0395-443b-8d54-5b3a8ca5601a")
IID_ID3D11_TEXTURE2D = _guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")
IID_GRAPHICS_CAPTURE_ITEM = _guid("22668b6d-4e7a-4a6c-83cb-53319f726338")
IID_GRAPHICS_CAPTURE_SESSION = _guid("37e8fc7b-1c4b-4c1e-8dc6-ea03c15b02d1")
IID_GRAPHICS_CAPTURE_FRAME_POOL = _guid("f7f2126f-4f6e-4a59-b8e6-61c58e782e92")
IID_GRAPHICS_CAPTURE_SURFACE = _guid("e17575a6-9287-4a5e-a5b3-8b57485a2085")

CLS_CAPTURE_ITEM = "Windows.Graphics.Capture.GraphicsCaptureItem"
CLS_FRAME_POOL = "Windows.Graphics.Capture.GraphicsCaptureFramePool"

DXGI_FORMAT_B8G8R8A8_UNORM = 27
DXGI_SWAP_EFFECT_FLIP_DISCARD = 3
DXGI_USAGE_RENDER_TARGET_OUTPUT = 2
D3D11_USAGE_STAGING = 2
D3D11_BIND_SHADER_RESOURCE = 8
D3D11_MAP_READ = 1
D3D11_CPU_ACCESS_READ = 4


def _vt(ptr: int):
    return (ctypes.POINTER(ctypes.c_void_p) * 100).from_address(
        ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p)).contents)


def _call(ptr: int, off: int, restype, argtypes, *args):
    """经对象虚表调第 off 个方法（COM 调用约定；首参恒为 this）。"""
    fn = ctypes.cast(_vt(ptr)[off],
                     ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)).contents
    return fn(ptr, *args)


def _qif(obj: int, iid: GUID, out: PVOID) -> int:
    return _call(obj, 0, HRESULT, [GUIDREF, ctypes.POINTER(PVOID)],
                 ctypes.byref(iid), ctypes.byref(out))


def _static(cls: str, iid: GUID) -> int:
    hstr = ctypes.c_void_p()
    hr = rtstr.WindowsCreateString(cls, len(cls), ctypes.byref(hstr))
    if hr != 0:
        raise SystemExit(f"WindowsCreateString 失败: {hex(hr)}")
    out = PVOID()
    hr = storage.DllGetActivationFactory(hstr, ctypes.byref(iid),
                                         ctypes.byref(out))
    if hr != 0 or not out:
        raise SystemExit(f"DllGetActivationFactory({cls}) 失败: {hex(hr)}")
    return out.value


class DXGI_SAMPLE_DESC(ctypes.Structure):
    _fields_ = [("Count", wt.ULONG), ("Quality", wt.ULONG)]


class DXGI_SWAP_CHAIN_DESC1(ctypes.Structure):
    _fields_ = [("Width", wt.ULONG), ("Height", wt.ULONG), ("Format", wt.ULONG),
                ("SampleDesc", DXGI_SAMPLE_DESC), ("BufferUsage", wt.ULONG),
                ("BufferCount", wt.UINT), ("OutputWindow", HWND),
                ("Windowed", wt.UINT), ("SwapEffect", wt.ULONG)]


class D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [("Width", wt.ULONG), ("Height", wt.ULONG),
                ("MipLevels", wt.ULONG), ("ArraySize", wt.ULONG),
                ("Format", wt.ULONG), ("SampleDesc", DXGI_SAMPLE_DESC),
                ("Usage", wt.ULONG), ("BindFlags", wt.ULONG),
                ("CPUAccessFlags", wt.ULONG), ("MiscFlags", wt.ULONG)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--title", default="Experientia")
    ap.add_argument("--wait", type=int, default=30)
    a = ap.parse_args()

    deadline = time.time() + a.wait
    hwnd = 0
    while time.time() < deadline:
        hwnd = user32.FindWindowW(None, a.title)
        if hwnd:
            break
        time.sleep(1)
    if not hwnd:
        print("找不到窗口:", a.title)
        sys.exit(1)

    if ole32.CoInitializeEx(None, 0) < 0:
        print("CoInitializeEx 失败")
        sys.exit(1)

    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = max(1, r.right - r.left), max(1, r.bottom - r.top)
    print(f"窗口 {w}x{h}")

    # ---------- 1) capture item（静态 CreateForWindow 在虚表槽 6） ----------
    item_f = _static(CLS_CAPTURE_ITEM, IID_GRAPHICS_CAPTURE_ITEM)
    item = PVOID()
    hr = _call(item_f, 6, HRESULT, [HWND, ctypes.POINTER(PVOID)],
               hwnd, ctypes.byref(item))
    print("CreateForWindow:", hex(hr))
    if hr != 0 or not item:
        sys.exit(1)

    # RequestAccessAsync（程序化捕获；异步结果不阻塞，稍等即可）
    op = PVOID()
    _call(item, 12, HRESULT, [ctypes.POINTER(PVOID)], ctypes.byref(op))
    if op:
        rel = ctypes.cast(_vt(op)[2],
                          ctypes.WINFUNCTYPE(wt.UINT, ctypes.c_void_p)).contents
        rel(op)  # Release 异步句柄
    time.sleep(0.5)  # 给异步授权一点时间（无交互场景通常自动放行）

    # item.GetGraphicsCaptureSession()（槽 6）
    session = PVOID()
    _call(item, 6, HRESULT, [ctypes.POINTER(PVOID)], ctypes.byref(session))
    print("session:", hex(session.value or 0))
    if not session:
        sys.exit(1)

    # ---------- 2) D3D11 设备（EnumAdapters1=14 / GetOutput1=10 / GetDevice=18） ----------
    factory = PVOID()
    dxgi.CreateDXGIFactory1.argtypes = [GUIDREF, ctypes.POINTER(PVOID)]
    dxgi.CreateDXGIFactory1(ctypes.byref(IID_IDXGI_FACTORY1), ctypes.byref(factory))
    adapter = PVOID()
    _call(factory, 14, HRESULT, [wt.ULONG, GUIDREF, ctypes.POINTER(PVOID)],
          0, ctypes.byref(IID_IDXGI_ADAPTER1), ctypes.byref(adapter))
    output1 = PVOID()
    _call(adapter, 10, HRESULT, [wt.ULONG, GUIDREF, ctypes.POINTER(PVOID)],
          0, ctypes.byref(IID_IDXGI_OUTPUT1), ctypes.byref(output1))
    device = PVOID()
    hr = _call(output1, 18, HRESULT, [GUIDREF, ctypes.POINTER(PVOID)],
               ctypes.byref(IID_ID3D11_DEVICE), ctypes.byref(device))
    print("device:", hex(hr), hex(device.value or 0))
    if hr != 0:
        sys.exit(1)
    ctx = PVOID()
    _qif(device, IID_ID3D11_DEVICE_CONTEXT, ctx)

    # ---------- 3) 交换链（flip model，挂目标窗口） ----------
    desc = DXGI_SWAP_CHAIN_DESC1(
        Width=w, Height=h, Format=DXGI_FORMAT_B8G8R8A8_UNORM,
        SampleDesc=DXGI_SAMPLE_DESC(1, 0),
        BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT, BufferCount=2,
        OutputWindow=HWND(hwnd), Windowed=1, SwapEffect=DXGI_SWAP_EFFECT_FLIP_DISCARD)
    sc1 = PVOID()
    hr = _call(device, 15, HRESULT,
               [ctypes.POINTER(DXGI_SWAP_CHAIN_DESC1), PVOID, PVOID,
                ctypes.POINTER(PVOID)],
               ctypes.byref(desc), None, None, ctypes.byref(sc1))
    print("CreateSwapChainForHwnd:", hex(hr))
    if hr != 0:
        sys.exit(1)
    sc3 = PVOID()
    _qif(sc1, IID_IDXGI_SWAP_CHAIN3, sc3)  # noqa: F841  保持引用
    back = PVOID()
    hr = _call(sc1, 11, HRESULT, [wt.ULONG, GUIDREF, ctypes.POINTER(PVOID)],
               0, ctypes.byref(IID_IDXGI_SURFACE), ctypes.byref(back))
    print("backbuffer:", hex(hr))
    if hr != 0:
        sys.exit(1)

    # ---------- 4) 帧池（静态 Create 在虚表槽 6） ----------
    pool_f = _static(CLS_FRAME_POOL, IID_GRAPHICS_CAPTURE_FRAME_POOL)
    pool = PVOID()
    hr = _call(pool_f, 6, HRESULT,
               [wt.ULONG, wt.ULONG, PVOID, ctypes.POINTER(PVOID)],
               DXGI_FORMAT_B8G8R8A8_UNORM, 2, back, ctypes.byref(pool))
    print("CreateFramePool:", hex(hr))
    if hr != 0 or not pool:
        sys.exit(1)

    # ---------- 5) 配置会话 + 开始捕获（Configure=6 / StartCapture=7） ----------
    hr = _call(session, 6, HRESULT, [PVOID, wt.ULONG, ctypes.POINTER(wt.DOUBLE)],
               back, DXGI_FORMAT_B8G8R8A8_UNORM, None)
    print("Configure:", hex(hr))
    if hr != 0:
        sys.exit(1)
    hr = _call(session, 7, HRESULT, [])
    print("StartCapture:", hex(hr))
    if hr != 0:
        sys.exit(1)

    # ---------- 6) 等一帧（WaitOneFrame=11） ----------
    frame = None
    deadline = time.time() + 20
    while time.time() < deadline:
        f = PVOID()
        hr = _call(pool, 11, HRESULT, [wt.ULONG, ctypes.POINTER(PVOID)],
                   2000, ctypes.byref(f))
        if hr == 0 and f:
            frame = f
            break
        print("WaitOneFrame:", hex(hr))
    if not frame:
        sys.exit(1)

    # 帧尺寸（GetWidth=9 / GetHeight=11）
    fw, fh = wt.UINT(), wt.UINT()
    _call(frame, 9, HRESULT, [ctypes.POINTER(wt.UINT)], ctypes.byref(fw))
    _call(frame, 11, HRESULT, [ctypes.POINTER(wt.UINT)], ctypes.byref(fh))
    fw, fh = fw.value, fh.value
    print(f"frame: {fw}x{fh}")

    # ---------- 7) 帧表面 → DXGI 表面 → 拷进 staging 纹理 ----------
    surf_rt = PVOID()
    hr = _call(frame, 7, HRESULT, [ctypes.POINTER(PVOID)],
               ctypes.byref(surf_rt))
    print("CreateSurface:", hex(hr))
    if hr != 0:
        sys.exit(1)
    gc_surf = PVOID()
    _qif(surf_rt, IID_GRAPHICS_CAPTURE_SURFACE, gc_surf)
    dxgi_surf = PVOID()
    hr = _call(gc_surf, 9, HRESULT, [GUIDREF, ctypes.POINTER(PVOID)],
               ctypes.byref(IID_IDXGI_SURFACE), ctypes.byref(dxgi_surf))
    print("GetDxgiSurface:", hex(hr))
    if hr != 0:
        sys.exit(1)
    frame_tex = PVOID()
    _qif(dxgi_surf, IID_ID3D11_TEXTURE2D, frame_tex)

    sdesc = D3D11_TEXTURE2D_DESC(
        Width=fw, Height=fh, MipLevels=1, ArraySize=1,
        Format=DXGI_FORMAT_B8G8R8A8_UNORM, SampleDesc=DXGI_SAMPLE_DESC(1, 0),
        Usage=D3D11_USAGE_STAGING, BindFlags=D3D11_BIND_SHADER_RESOURCE,
        CPUAccessFlags=D3D11_CPU_ACCESS_READ, MiscFlags=0)
    staging = PVOID()
    hr = _call(device, 5, HRESULT,
               [ctypes.POINTER(D3D11_TEXTURE2D_DESC), PVOID,
                ctypes.POINTER(PVOID)],
               ctypes.byref(sdesc), None, ctypes.byref(staging))
    print("CreateTexture2D(staging):", hex(hr))
    if hr != 0:
        sys.exit(1)

    _call(ctx, 32, None, [PVOID, wt.ULONG, PVOID, wt.ULONG],
          staging, 0, frame_tex, 0)  # CopyResource

    mapped = ctypes.create_string_buffer(fw * fh * 4)
    hr = d3d11.ID3D11DeviceContext_Map(
        ctx, 0, staging, D3D11_MAP_READ, 0, ctypes.byref(ctypes.c_void_p(mapped)))
    print("Map:", hex(hr))
    if hr != 0:
        sys.exit(1)
    d3d11.ID3D11DeviceContext_Unmap(ctx, 0, staging)

    from PIL import Image
    img = Image.frombuffer("RGBA", (fw, fh), mapped, "raw", "BGRA", 0, 1) \
        .convert("RGB")
    img.save(a.out)
    print(f"已存 {a.out}: {img.size[0]}x{img.size[1]}")


if __name__ == "__main__":
    main()
