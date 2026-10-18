# -*- coding: utf-8 -*-
"""补齐「报告弹层：导出后打开文件夹」新增词条到 7 语 .po。

用法：uv run python scripts/i18n_report_folder_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范同 i18n_poster_entries.py：de=Sie+„“、es=tú+«»、fr=’+«»、
ko=합니다체+''、非 CJK 禁全角括号与残留汉字（脚本自检）。

注：「打开文件夹」本身 7 语里已有（设置页在用），本批只补三条新串。
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

E: dict[str, dict[str, str]] = {
    # ---------- 报告弹层（app/gui/report_view.py do_open_folder） ----------
    "先导出一次，再打开文件夹": {
        "en": "Export first, then you can open the folder",
        "de": "Erst exportieren, dann können Sie den Ordner öffnen",
        "es": "Exporta primero y luego podrás abrir la carpeta",
        "fr": "Exportez d’abord, vous pourrez ensuite ouvrir le dossier",
        "ja": "先にエクスポートすると、フォルダーを開けます",
        "ko": "먼저 내보내면 폴더를 열 수 있어요"},
    "文件夹已不在了：{path}": {
        "en": "That folder is gone: {path}",
        "de": "Dieser Ordner ist nicht mehr da: {path}",
        "es": "Esa carpeta ya no existe: {path}",
        "fr": "Ce dossier n’existe plus : {path}",
        "ja": "フォルダーが見つかりません：{path}",
        "ko": "폴더가 더 이상 없습니다: {path}"},
    "已打开文件夹：{path}": {
        "en": "Opened folder: {path}",
        "de": "Ordner geöffnet: {path}",
        "es": "Carpeta abierta: {path}",
        "fr": "Dossier ouvert : {path}",
        "ja": "フォルダーを開きました：{path}",
        "ko": "폴더를 열었습니다: {path}"},
}


def _check() -> None:
    for mid, table in E.items():
        ph = set(re.findall(r"\{(\w+)\}", mid))
        for lang, text in table.items():
            assert text.strip(), f"{lang} 空译文: {mid[:20]}"
            got = set(re.findall(r"\{(\w+)\}", text))
            assert got == ph, f"{lang} 占位符不符 {mid[:24]}: {sorted(ph)} vs {sorted(got)}"
            if lang in LATIN:
                bad = [c for c in text if "一" <= c <= "鿿"]
                assert not bad, f"{lang} 残留汉字 {mid[:24]}: {bad[:6]}"
                assert "（" not in text and "）" not in text, f"{lang} 全角括号: {mid[:24]}"


def main() -> int:
    _check()
    for lang in LANGS:
        po = LOCALES / lang / "LC_MESSAGES" / "messages.po"
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
