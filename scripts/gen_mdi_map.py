"""从打包字体 assets/fonts/materialdesignicons-webfont.ttf 生成 app/gui/_mdi_map.py。

图标名 → Unicode 码点。直接读字体 cmap（glyph name 即 kebab-case 图标名），
保证映射表与实际渲染用的字体 100% 一致——不依赖外部 CSS 版本。

用法：python scripts/gen_mdi_map.py
"""
from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "assets" / "fonts" / "materialdesignicons-webfont.ttf"
OUT = ROOT / "app" / "gui" / "_mdi_map.py"

cmap = TTFont(str(FONT)).getBestCmap()
# 只保留合法图标名（kebab-case）；过滤空名/异常名
m = {gn: cp for cp, gn in cmap.items() if gn and all(c.isalnum() or c == "-" for c in gn)}

with OUT.open("w", encoding="utf-8") as f:
    f.write('"""MDI 图标名 → Unicode 码点（由 scripts/gen_mdi_map.py 从打包字体生成，勿手改）。"""\n\n')
    f.write("MDI = {\n")
    for name in sorted(m):
        f.write(f"    {name!r}: {m[name]},\n")
    f.write("}\n")

print(f"icons: {len(m)} -> {OUT}")
