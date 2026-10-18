# -*- coding: utf-8 -*-
"""补齐「记忆构成（六层存量）」首页卡词条到 7 语 .po。

六层的层名（原始痕迹 / 原子事实 / 身份画像 / 会话摘要 / 心智模型 / 前瞻意图）
是引擎内部术语，UI 按改名成平实名：会话原话 / 经验 / 偏好 / 会话摘要 /
方法卡 / 意图。其中「会话原话」「经验」「偏好」词典已有，这里只补缺的三条 +
卡片标题 + 提示句。

用法：uv run python scripts/i18n_memory_mix_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=tú+«»、fr=撇号 ’+«»、ko=합니다체+''、
非 CJK 语言禁全角括号与残留汉字（脚本末尾自检）。
"""

from __future__ import annotations

import sys

from i18n_entry_lib import apply_entries, check_entries

E: dict[str, dict[str, str]] = {
    "记忆构成": {
        "en": "What your memory holds",
        "de": "Woraus dein Gedächtnis besteht",
        "es": "De qué está hecha tu memoria",
        "fr": "De quoi est faite votre mémoire",
        "ja": "記憶の中身", "ko": "기억 구성"},
    "会话摘要": {
        "en": "Session digests", "de": "Sitzungszusammenfassungen",
        "es": "Resúmenes de sesión", "fr": "Résumés de session",
        "ja": "セッション要約", "ko": "세션 요약"},
    "方法卡": {
        "en": "Methods", "de": "Methodenkarten",
        "es": "Fichas de método", "fr": "Fiches méthode",
        "ja": "メソッドカード", "ko": "메서드 카드"},
    "意图": {
        "en": "Intents", "de": "Absichten",
        "es": "Intenciones", "fr": "Intentions",
        "ja": "意図", "ko": "의도"},
    "经验攒够了，可以总结成方法": {
        "en": "You have enough experiences — time to distill them "
              "into a method",
        "de": "Genug Erfahrungen gesammelt – Zeit, daraus eine Methode "
              "zu machen",
        "es": "Ya tienes suficientes experiencias: es momento de "
              "resumirlas en un método",
        "fr": "Assez d’expériences — il est temps d’en tirer une méthode",
        "ja": "経験がたまりました。メソッドにまとめましょう",
        "ko": "경험이 충분히 쌓였습니다. 메서드로 정리해 보세요"},
}


def main() -> int:
    check_entries(E)
    apply_entries(E)
    return 0


if __name__ == "__main__":
    sys.exit(main())
