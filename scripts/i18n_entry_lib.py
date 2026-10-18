# -*- coding: utf-8 -*-
"""i18n 词条脚本的公共库：语体自检 + 落 .po。

`scripts/i18n_*_entries.py` 一族曾各自复制同一份 `_check()` / `main()`
（19 个脚本、三个漂移变体：占位符正则宽严不一、省略号检查有无不一）。
改自检规则要改 20+ 处、漏改无测试能发现—— L3 抽成此处，
各脚本只留 `E` 表与两行调用。

用法（词条脚本内）：

    from i18n_entry_lib import check_entries, apply_entries

    E: dict[str, dict[str, str]] = {...}

    def main() -> int:
        check_entries(E)
        apply_entries(E)
        return 0

补完词条必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=tú+«»、fr=撇号 ’+«»、ko=합니다체+''、
非 CJK 语言禁全角括号与残留汉字（check_entries 执法）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "app" / "gui" / "locales"
LANGS = ["de", "en", "es", "fr", "ja", "ko", "zh"]
LATIN = ("de", "en", "es", "fr")


def check_entries(E: dict[str, dict[str, str]]) -> None:
    """语体自检：占位符一致 / 无空译文 / 无省略号残句 / 拉丁语零 CJK。"""
    for mid, table in E.items():
        ph = set(re.findall(r"\{(\w+)(?::\w+)?\}", mid))
        for lang, text in table.items():
            assert text.strip(), f"{lang} 空译文: {mid[:20]}"
            assert "…" not in text, f"{lang} 疑似半截句: {mid[:20]}"
            got = set(re.findall(r"\{(\w+)(?::\w+)?\}", text))
            assert got == ph, \
                f"{lang} 占位符不符 {mid[:24]}: {sorted(ph)} vs {sorted(got)}"
            if lang in LATIN:
                bad = [c for c in text if "一" <= c <= "鿿"]
                assert not bad, f"{lang} 残留汉字 {mid[:24]}: {bad[:6]}"
                assert "（" not in text and "）" not in text, \
                    f"{lang} 出现全角括号: {mid[:24]}"


def apply_entries(E: dict[str, dict[str, str]]) -> None:
    """把 E 表里缺失的 msgid 补进 7 语 .po（已存在则跳过；字节写保 LF）。"""
    for lang in LANGS:
        po = LOCALES / lang / "LC_MESSAGES" / "messages.po"
        if not po.exists():
            print(f"缺少 {po}")
            continue
        with po.open("rb") as fh:
            catalog = read_po(fh, locale=lang)
        added = 0
        for msgid, table in E.items():
            msgid = str(msgid)
            if msgid in catalog:
                continue
            text = msgid if lang == "zh" else table.get(lang)
            if not text:
                print(f"[{lang}] 缺译文: {msgid[:24]}")
                continue
            catalog.add(msgid, text,
                        flags=["python-format"] if "{" in msgid else [])
            added += 1
        if added:
            with po.open("wb") as fh:  # 字节写：防 Windows 换行二次转换（.po LF 铁律）
                write_po(fh, catalog, width=0)
        print(f"[{lang}] 新增 {added} 条")
    print("完成——请跑 scripts/compile_locales.py 重编译 .mo")


if __name__ == "__main__":  # 直接跑 = 无 E 表可补，提示用法
    print("本文件是库；词条在 scripts/i18n_*_entries.py 各脚本里。")
    sys.exit(0)
