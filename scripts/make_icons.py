"""宇航员表情家族资产管线。

mascot 唯一存放处 = assets/mascot_<name>.png（**单一来源，没有第二份母版目录**）：
- 应用/运行只读 assets/mascot_*.png（theme.MASCOTS 引用）；删就是删、新增就新增。
- 本脚本只做"从 mascot 派生应用图标四件套"，不覆盖 mascot 自身。
  smile（中性微笑）→ icon.png / icon_windows.ico / splash.png / splash_dark.png。

打包/运行时图标约定（PyInstaller + Qt）：
- 项目根 assets/ 放 icon.png（窗口/关于页用）+ icon_windows.ico（Windows exe
  图标，PyInstaller spec 的 EXE(icon=...) 取它）；Linux/macOS 直接引用 icon.png。
- splash.png / splash_dark.png 供 Qt 启动闪屏（gui/qt_splash.py）按明暗主题取用。

v1 手绘蜡笔版回滚源保留在 assets_src/icon_src.svg（make_from_svg）。

用法：uv run python scripts/make_icons.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

MASCOTS = ("smile", "peace", "think", "fail", "sleep")
APP_ICON = "smile"  # 应用图标 = 中性微笑
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
# 应用图标里宇航员占画布比例：吉祥物源图自带 ~15% 透明边，原样做图标主体显小；
# 裁边放大到 90% 让托盘/任务栏图标更醒目（左右各留 ~51px 安全边，四角仍透明——
# 注意 _check 的 0.70 覆盖率红线卡的是吉祥物源图而非 refit 图标，图标侧只受四角约束）。
ICON_FILL = 0.90


def _check(img: Image.Image, name: str) -> None:
    assert img.size == (1024, 1024), (name, img.size)
    px = list(img.get_flattened_data())
    cov = sum(1 for p in px if p[3] > 200) / len(px)
    assert 0.40 < cov < 0.70, f"{name} 主体覆盖率异常: {cov:.3f}"
    for corner in ((2, 2), (1021, 2), (2, 1021), (1021, 1021)):
        assert img.getpixel(corner)[3] < 40, f"{name} 角点 {corner} 不透明"
    bbox = img.getbbox()
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    assert abs(cx - 512) < 60 and abs(cy - 512) < 60, f"{name} 构图偏心: ({cx:.0f},{cy:.0f})"


def _refit(img: Image.Image, fill: float) -> Image.Image:
    """裁掉吉祥物四周透明边，把主体放大到占画布 fill 比例后重新居中。

    吉祥物源图自带一圈透明边距（~15%），原样做应用图标会让主体在托盘/任务栏
    里显小；裁边 + 放大让主体更醒目。fill 受 _check 覆盖率上限约束
    （0.85 → cov≈0.66 < 0.70，四角仍透明）。
    """
    bbox = img.getchannel("A").getbbox()
    if bbox is None:
        return img
    content = img.crop(bbox)
    cw, ch = content.size
    side = int(img.size[0] * fill)
    scale = min(side / cw, side / ch)
    new_w, new_h = max(1, int(cw * scale)), max(1, int(ch * scale))
    content = content.resize((new_w, new_h), Image.LANCZOS)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(content, ((img.size[0] - new_w) // 2, (img.size[1] - new_h) // 2), content)
    for corner in ((2, 2), (img.size[0] - 3, 2), (2, img.size[1] - 3),
                   (img.size[0] - 3, img.size[1] - 3)):
        assert out.getpixel(corner)[3] < 40, f"refit 后角点 {corner} 不透明（fill 过大）"
    return out


def make_from_mascots() -> None:
    """mascot（assets/mascot_*.png 唯一来源）→ 应用图标四件套。

    不写回 mascot 文件本身——assets 就是唯一存放处，避免"拷贝副本=多处"。
    """
    ASSETS.mkdir(exist_ok=True)

    masters: dict[str, Image.Image] = {}
    for name in MASCOTS:
        p = ASSETS / f"mascot_{name}.png"
        assert p.exists(), f"缺 mascot: {p}"
        img = Image.open(p).convert("RGBA")
        _check(img, name)
        masters[name] = img

    icon = _refit(masters[APP_ICON], ICON_FILL)
    buf = io.BytesIO()
    icon.save(buf, format="PNG", optimize=True)
    (ASSETS / "icon.png").write_bytes(buf.getvalue())
    icon.save(ASSETS / "icon_windows.ico", sizes=ICO_SIZES)
    # splash：透明底主体，明/暗两套由 Qt 启动闪屏按主题取用（qt_splash.py）
    (ASSETS / "splash.png").write_bytes(buf.getvalue())
    (ASSETS / "splash_dark.png").write_bytes(buf.getvalue())

    ico_kb = (ASSETS / "icon_windows.ico").stat().st_size / 1024
    print(f"OK  应用图标 = {APP_ICON}：icon.png / icon_windows.ico ({ico_kb:.0f} KB) / splash×2")
    print(f"OK  GUI 表情：{', '.join(f'mascot_{m}.png' for m in MASCOTS)}")


def make_from_svg() -> None:
    """v1 手绘蜡笔版（回滚路径）：SVG → resvg 光栅化。"""
    import resvg_py

    tpl = (ROOT / "assets_src" / "icon_src.svg").read_text(encoding="utf-8")

    def render(outline: str, with_bg: bool) -> bytes:
        svg = tpl.replace("__OUTLINE__", outline).replace(
            "__BG__", '<circle cx="512" cy="512" r="496" fill="#E9EEFF"/>' if with_bg else ""
        )
        return bytes(resvg_py.svg_to_bytes(svg_string=svg, width=1024, height=1024))

    ASSETS.mkdir(exist_ok=True)
    (ASSETS / "icon.png").write_bytes(render("#33415C", True))
    Image.open(io.BytesIO(render("#33415C", True))).convert("RGBA").save(
        ASSETS / "icon_windows.ico", sizes=ICO_SIZES
    )
    (ASSETS / "splash.png").write_bytes(render("#33415C", False))
    (ASSETS / "splash_dark.png").write_bytes(render("#E7ECFB", False))
    print("OK  v1 SVG 版资产已生成")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "svg":
        make_from_svg()
    else:
        make_from_mascots()
