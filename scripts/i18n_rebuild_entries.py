# -*- coding: utf-8 -*-
"""补齐「重建空方法卡」新增词条到 7 语 .po。

用法：uv run python scripts/i18n_rebuild_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范同 i18n_poster_entries.py：de=Sie+„“、es=tú+«»、fr=’+«»、
ko=합니다체+''、非 CJK 禁全角括号与残留汉字（脚本自检）。

注意（本批特有）：tooltip 那条在 app/gui/methods.py 里是**跨行拼接**的两个字面量
（`"…（多半是上次总结没拿到内容）" "——用全部经验重蒸馏一次"`），Python AST 与
pybabel 都会折叠成**一整条**——下面的 key 必须是折叠后的整串，只补前半句护栏照样红。
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
    # ---------- 空方法卡自救（app/gui/methods.py _rebuild / _skill_card） ----------
    "重建": {"en": "Rebuild", "de": "Neu aufbauen", "es": "Reconstruir",
           "fr": "Reconstruire", "ja": "再構築", "ko": "다시 만들기"},
    "正在重建…": {"en": "Rebuilding…", "de": "Wird neu aufgebaut…",
              "es": "Reconstruyendo…", "fr": "Reconstruction…",
              "ja": "再構築中…", "ko": "다시 만드는 중…"},
    "重建完成": {"en": "Rebuild done", "de": "Neuaufbau abgeschlossen",
             "es": "Reconstrucción completada",
             "fr": "Reconstruction terminée",
             "ja": "再構築が完了しました", "ko": "다시 만들기 완료"},
    "重建失败：{err}": {"en": "Rebuild failed: {err}",
                  "de": "Neuaufbau fehlgeschlagen: {err}",
                  "es": "Fallo al reconstruir: {err}",
                  "fr": "Échec de la reconstruction : {err}",
                  "ja": "再構築に失敗しました：{err}",
                  "ko": "다시 만들기 실패: {err}"},
    "正在用全部经验重建这份方法卡…": {
        "en": "Rebuilding this method card from all experiences…",
        "de": "Diese Methodenkarte wird aus allen Erfahrungen neu aufgebaut…",
        "es": "Reconstruyendo esta tarjeta de método con todas las experiencias…",
        "fr": "Reconstruction de cette fiche méthode à partir de toutes les "
              "expériences…",
        "ja": "すべての経験からこの方法カードを再構築しています…",
        "ko": "모든 경험으로 이 방법 카드를 다시 만드는 중…"},
    # tooltip：跨行拼接后的整串（见文件头注释）
    "这份方法卡是空的（多半是上次总结没拿到内容）——用全部经验重蒸馏一次": {
        "en": "This method card is empty (the last summary probably came back "
              "with nothing) — rebuild it from all experiences",
        "de": "Diese Methodenkarte ist leer (meistens, weil die letzte "
              "Zusammenfassung nichts geliefert hat) – bauen Sie sie aus allen "
              "Erfahrungen neu auf",
        "es": "Esta tarjeta de método está vacía (casi siempre porque el último "
              "resumen no trajo nada): reconstrúyela con todas las experiencias",
        "fr": "Cette fiche méthode est vide (le plus souvent parce que la "
              "dernière synthèse n’a rien renvoyé) — reconstruisez-la à partir de "
              "toutes les expériences",
        "ja": "この方法カードは空です（前回のまとめで内容を取得できなかった場合が"
              "ほとんどです）——すべての経験からもう一度作り直します",
        "ko": "이 방법 카드는 비어 있습니다(지난번 정리에서 내용을 받지 못한 경우가 "
              "대부분입니다) — 모든 경험으로 다시 만듭니다"},
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
