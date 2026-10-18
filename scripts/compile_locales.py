"""编译 .po → .mo。

用法：uv run python scripts/compile_locales.py
（babel 已在主依赖里；等价于 pybabel compile -d app/gui/locales）
"""

from __future__ import annotations

import sys
from pathlib import Path

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po

LOCALES = Path(__file__).resolve().parent.parent / "app" / "gui" / "locales"


def main() -> int:
    if not LOCALES.is_dir():
        print(f"locales 目录不存在: {LOCALES}", file=sys.stderr)
        return 1
    n = 0
    for po in sorted(LOCALES.glob("*/LC_MESSAGES/*.po")):
        with open(po, "rb") as fh:
            catalog = read_po(fh)
        mo = po.with_suffix(".mo")
        with open(mo, "wb") as fh:
            write_mo(fh, catalog)
        print(f"compiled: {mo.relative_to(LOCALES.parent.parent.parent)}")
        n += 1
    print(f"done: {n} catalog(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
