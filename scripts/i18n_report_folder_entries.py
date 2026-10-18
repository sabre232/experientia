# -*- coding: utf-8 -*-
"""补齐「报告弹层：导出后打开文件夹」新增词条到 7 语 .po。

用法：uv run python scripts/i18n_report_folder_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范同 i18n_poster_entries.py：de=Sie+„“、es=tú+«»、fr=’+«»、
ko=합니다체+''、非 CJK 禁全角括号与残留汉字（脚本自检）。

注：「打开文件夹」本身 7 语里已有（设置页在用），本批只补三条新串。
"""

from __future__ import annotations

import sys

from i18n_entry_lib import apply_entries, check_entries

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


def main() -> int:
    check_entries(E)
    apply_entries(E)
    return 0


if __name__ == "__main__":
    sys.exit(main())
