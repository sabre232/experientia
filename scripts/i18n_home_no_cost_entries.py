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

import sys

from i18n_entry_lib import apply_entries, check_entries

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


def main() -> int:
    check_entries(E)
    apply_entries(E)
    return 0


if __name__ == "__main__":
    sys.exit(main())
