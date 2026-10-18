# -*- coding: utf-8 -*-
"""首页删掉「花费估算」格：7 语删两条死词条 + 加一条新空态串。

用法：uv run python scripts/i18n_home_no_cost_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。

本批与既有 i18n_*_entries.py 的差别：**既加也删**。
- 删 `花费估算·美元`：首页那一格已下线（只接本地模型时恒为 0.00），界面不再引用；
- 删旧空态整串：空态文案改成不提钱的说法，旧串随之变成死词条；
- 加新空态整串：zh 恒等，另 6 语见下表。

i18n 护栏只校验「源码用到的 key 在 7 语里都有」（test_i18n.py:95/:109），
**不查孤儿词条**——所以死词条必须在这里主动删干净，别指望测试报错。
语体规范同 i18n_poster_entries.py：de=Sie+„“、es=tú+«»、fr=’+«»、
ko=합니다체+''、非 CJK 禁全角括号与残留汉字（脚本自检）。
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

# 死词条（按 msgid 删，不按行号——各语行号不同）
DROP = [
    "花费估算·美元",
    "去让任意 AI 工具干个活，它的操作会自动出现在这里——花多少钱、踩了什么坑，一目了然",
]

# 新词条（app/gui/home.py 空态文案，构造处与 retranslateUi 各一份，折叠后是同一串）
E: dict[str, dict[str, str]] = {
    "去让任意 AI 工具干个活，它的操作会自动出现在这里——踩了什么坑、怎么改好的，一目了然": {
        "en": "Send any AI tool off to do some work — its actions show up here by "
              "themselves, so the pitfalls it hit and how they were fixed are "
              "plain to see",
        "de": "Lassen Sie irgendein KI-Tool eine Aufgabe erledigen – seine Aktionen "
              "erscheinen hier von selbst, sodass Fallstricke und ihre Lösungen "
              "klar zu sehen sind",
        "es": "Pon a trabajar cualquier herramienta de IA: sus acciones aparecerán "
              "aquí solas y verás de un vistazo los tropiezos y cómo se resolvieron",
        "fr": "Faites travailler n’importe quel outil d’IA : ses actions "
              "apparaîtront ici d’elles-mêmes, avec les écueils rencontrés et la "
              "façon dont ils ont été résolus",
        "ja": "任意の AI ツールに仕事を任せると、その操作がここに自動で並びます"
              "——つまずいた点と直し方が一目で分かります",
        "ko": "어떤 AI 도구에든 일을 맡기면 그 작업이 여기에 자동으로 쌓여, 걸린 "
              "함정과 해결 방법을 한눈에 볼 수 있습니다"},
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


def _drop(catalog, msgid: str) -> bool:
    """删一条词条（含 `#~` 废弃区），返回是否真删到。"""
    hit = False
    try:
        del catalog[msgid]
        hit = True
    except KeyError:
        pass
    obsolete = getattr(catalog, "obsolete", None)
    if isinstance(obsolete, dict) and msgid in obsolete:
        del obsolete[msgid]
        hit = True
    return hit


def main() -> int:
    _check()
    for lang in LANGS:
        po = LOCALES / lang / "LC_MESSAGES" / "messages.po"
        with po.open("rb") as fh:
            catalog = read_po(fh, locale=lang)
        dropped = sum(1 for mid in DROP if _drop(catalog, str(mid)))
        added = 0
        for msgid, table in E.items():
            msgid = str(msgid)
            if msgid in catalog:
                continue
            text = msgid if lang == "zh" else table.get(lang)
            if not text:
                print(f"[{lang}] 缺译文: {msgid[:24]}")
                continue
            catalog.add(msgid, text)
            added += 1
        if dropped or added:
            with po.open("wb") as fh:  # 字节写：防 Windows 换行二次转换（.po LF 铁律）
                write_po(fh, catalog, width=0)
        print(f"[{lang}] 删 {dropped}/{len(DROP)} 条 · 新增 {added} 条")
    print("完成——请跑 scripts/compile_locales.py 重编译 .mo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
