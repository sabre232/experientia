# -*- coding: utf-8 -*-
"""一次性补齐脚本：海报/报告区块标题等显示串补进 7 语 .po（已存在则跳过）。

背景：poster.py 的区块标题走 `t(name)`（name 来自 playbook md 的
节名，按契约"key = 中文源串"），但 5 个节名里只有「标准流程」登记过，
其余 4 个在非中文界面静默回落中文；另有「N 分 · 标题」分隔符与 PNG 文件名
前缀是 f-string 里硬编码的中文。

语体规范：de=Sie+„"、es=tú、fr=撇号 '、ko=합니다체+''、非 CJK 禁全角括号（ja 除外）。
长度注意：i18n 守卫要求译文 ≤5×原文（防拼接损坏），节名类短键尤其要精简。

用法：.venv/Scripts/python.exe scripts/i18n_poster_sections.py
补完后跑 scripts/compile_locales.py 重编译 .mo。
"""
from __future__ import annotations

import sys
from pathlib import Path

from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "app" / "gui" / "locales"
LANGS = ["de", "en", "es", "fr", "ja", "ko", "zh"]

E: dict[str, dict[str, str]] = {
    # 报告/海报区块标题（poster.py:188 的 t(name)，name 来自 playbook md 节名）
    "成功要点": {
        "en": "What worked",
        "de": "Was funktioniert hat",
        "es": "Lo que funcionó",
        "fr": "Ce qui a marché",
        "ja": "うまくいった点",
        "ko": "잘 된 점",
    },
    "失败模式": {
        "en": "Failure modes",
        "de": "Fehlermuster",
        "es": "Modos de fallo",
        "fr": "Modes d'échec",
        "ja": "失敗パターン",
        "ko": "실패 패턴",
    },
    "过时项标记": {
        "en": "Stale items",
        "de": "Veraltete Einträge",
        "es": "Elementos obsoletos",
        "fr": "Éléments obsolètes",
        "ja": "古くなった項目",
        "ko": "오래된 항목",
    },
    "偏好增量": {
        "en": "Preference changes",
        "de": "Präferenz-Änderungen",
        "es": "Cambios de preferencias",
        "fr": "Évolutions des préférences",
        "ja": "好みの変化",
        "ko": "선호도 변화",
    },
    # 「最值钱的三条经验」里的「N 分 · 标题」分隔符（poster.py:150）
    "{badge} 分 · {text}": {
        "en": "{badge} pts · {text}",
        "de": "{badge} Pkt. · {text}",
        "es": "{badge} pts · {text}",
        "fr": "{badge} pts · {text}",
        "ja": "{badge} 点 · {text}",
        "ko": "{badge}점 · {text}",
    },
    # PNG 导出文件名前缀（poster.png_spec_data_dir，与海报标题同口径）
    "成长报告-": {
        "en": "Growth-report-",
        "de": "Wachstumsbericht-",
        "es": "Informe-de-crecimiento-",
        "fr": "Rapport-de-croissance-",
        "ja": "成長レポート-",
        "ko": "성장-보고서-",
    },
    "方法-": {
        "en": "Method-",
        "de": "Methode-",
        "es": "Método-",
        "fr": "Méthode-",
        "ja": "メソッド-",
        "ko": "메서드-",
    },
}


def main() -> int:
    added = skipped = 0
    for lang in LANGS:
        po_path = LOCALES / lang / "LC_MESSAGES" / "messages.po"
        with po_path.open("rb") as fh:
            catalog = read_po(fh, locale=lang)
        for msgid, table in E.items():
            existing = catalog.get(msgid)
            if existing is not None and existing.string:
                skipped += 1
                continue
            msgstr = msgid if lang == "zh" else table[lang]
            catalog.add(id=msgid, string=msgstr)
            added += 1
        # write_po 写 bytes——必须二进制句柄（踩过文本句柄写空 po 的坑）
        with po_path.open("wb") as fh:
            write_po(fh, catalog, width=0)
        print(f"{lang}: written {po_path.relative_to(ROOT)}")
    print(f"done: added {added}, skipped {skipped}")
    print("next: .venv/Scripts/python.exe scripts/compile_locales.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
