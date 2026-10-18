"""应用图标/splash/吉祥物表情资产冒烟（scripts/make_icons.py 的产物，随仓库提交）。

mascot 唯一存放处 = assets/mascot_<name>.png（应用运行时只读这里，删就是删、新增就
新增，不再维护第二份母版目录）；应用图标 icon/ico/splash 由 mascot_smile.png 派生。
v1 手绘蜡笔版保留在 assets_src/icon_src.svg 作回滚源。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
MASCOT_KEYS = ("smile", "peace", "think", "fail", "sleep")


def _check_1024_transparent_centered(img: "object") -> None:
    from PIL import Image

    img = Image.open(img).convert("RGBA")
    assert img.size == (1024, 1024), img.size
    px = list(img.get_flattened_data())
    cov = sum(1 for p in px if p[3] > 200) / len(px)
    assert 0.40 < cov < 0.70, cov
    for corner in ((2, 2), (1021, 2), (2, 1021), (1021, 1021)):
        assert img.getpixel(corner)[3] < 40, corner
    bbox = img.getbbox()
    assert bbox is not None
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    assert abs(cx - 512) < 60 and abs(cy - 512) < 60, (cx, cy)


def _check_1024_refit_icon(img: "object") -> None:
    """refit 应用图标（mascot 裁边放大）的构图约束。

    与吉祥物源图的 0.70 覆盖率上限不同：refit 把主体放大到 ~90% 画布
    （托盘/任务栏更醒目），覆盖率会到 0.7x，故这里只卡「足够实 + 四角透明 +
    居中」，不设 0.70 上限（见 make_icons.py 的 _refit 注释）。
    """
    from PIL import Image

    img = Image.open(img).convert("RGBA")
    assert img.size == (1024, 1024), img.size
    px = list(img.get_flattened_data())
    cov = sum(1 for p in px if p[3] > 200) / len(px)
    assert cov > 0.40, cov
    for corner in ((2, 2), (1021, 2), (2, 1021), (1021, 1021)):
        assert img.getpixel(corner)[3] < 40, corner
    bbox = img.getbbox()
    assert bbox is not None
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    assert abs(cx - 512) < 60 and abs(cy - 512) < 60, (cx, cy)


def _refit_icon_bytes() -> bytes:
    """按 make_icons.py 的单一来源逻辑，重新生成 refit 应用图标字节。"""
    import importlib.util
    from PIL import Image

    spec = importlib.util.spec_from_file_location(
        "make_icons", str(ROOT / "scripts" / "make_icons.py"))
    mi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mi)
    smile = Image.open(ASSETS / "mascot_smile.png").convert("RGBA")
    import io

    buf = io.BytesIO()
    mi._refit(smile, mi.ICON_FILL).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def test_app_icon_is_smile_master() -> None:
    _check_1024_refit_icon(ASSETS / "icon.png")
    # 应用图标 = 中性微笑 mascot 裁边放大（用户拍板：比耶让位给开心/庆祝场景）。
    # 单一来源：icon.png 必须 == make_icons._refit(mascot_smile, ICON_FILL)。
    # 比对**解码后像素**（哈希）而非 PNG 原始字节：压缩字节随平台 zlib/PIL 版本变化，
    # 不代表图标内容不同（旧写法在 CI 上字节不等时触发对两张 1024² 图的 difflib 对比，假死 180s+）。
    import hashlib
    import io

    from PIL import Image

    committed = Image.open(ASSETS / "icon.png").convert("RGBA").tobytes()
    refit = Image.open(io.BytesIO(_refit_icon_bytes())).convert("RGBA").tobytes()
    assert hashlib.sha256(committed).hexdigest() == hashlib.sha256(refit).hexdigest()


def test_mascot_family_generated() -> None:
    for key in MASCOT_KEYS:
        gui = ASSETS / f"mascot_{key}.png"
        assert gui.exists(), gui
        _check_1024_transparent_centered(gui)


def test_icon_windows_ico_multisize() -> None:
    from PIL import Image

    ico = Image.open(ASSETS / "icon_windows.ico")
    sizes = getattr(ico, "info", {}).get("sizes", set())
    assert (256, 256) in sizes or ico.size[0] >= 256


def test_splash_transparent_same_master() -> None:
    from PIL import Image

    master = Image.open(ASSETS / "icon.png").convert("RGBA")
    for name in ("splash.png", "splash_dark.png"):
        img = Image.open(ASSETS / name).convert("RGBA")
        assert img.size == (1024, 1024)
        px = list(img.get_flattened_data())
        cov = sum(1 for p in px if p[3] > 200) / len(px)
        assert cov > 0.40, (name, cov)  # refit 图标，无 0.70 上限（见 _check_1024_refit_icon）
        # 与母版同一主体（透明底图标，明暗版仅背景色填充不同）
        assert img.tobytes() == master.tobytes()


def test_design_sources_present() -> None:
    svg = ROOT / "assets_src" / "icon_src.svg"
    assert svg.exists()
    src = svg.read_text(encoding="utf-8")
    assert "__OUTLINE__" in src and "__BG__" in src
    # mascot 已在 assets/ 唯一化（见本文件头注释），这里不再要求第二份源目录
