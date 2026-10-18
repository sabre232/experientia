# -*- coding: utf-8 -*-
"""一次性补齐脚本（移除自动更新）：纯导向文案词条。

用法：uv run python scripts/i18n_guide_only_entries.py
补完后跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=usted、fr=撇号 ’、ko=하세/합니다체+''、非 CJK 禁全角括号（ja 除外）。
"""

from __future__ import annotations

import sys

from i18n_entry_lib import apply_entries, check_entries

E: dict[str, dict[str, str]] = {
}


def main() -> int:
    check_entries(E)
    apply_entries(E)
    return 0


if __name__ == "__main__":
    sys.exit(main())
