# -*- coding: utf-8 -*-
"""补齐「L6 前瞻意图 + 六层存量 UI（P1-1）」新增词条到 7 语 .po。

`app/gui/experiences.py` 的 t("字面量") 由 AST 护栏卡；带占位符的
（`出现过 {n} 次`、`约 {n} 天后过期`）须保证各语占位符一致。
 M10 补意图 14 天过期提示两条。
用法：uv run python scripts/i18n_intentions_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=tú+«»、fr=撇号 ’+«»、ko=합니다체+''、
非 CJK 语言禁全角括号与残留汉字（脚本末尾自检）。
"""

from __future__ import annotations

import sys

from i18n_entry_lib import apply_entries, check_entries

E: dict[str, dict[str, str]] = {
    "接下来可能要处理": {
        "en": "Coming up next", "de": "Als Nächstes dran",
        "es": "Lo que viene ahora", "fr": "À traiter ensuite",
        "ja": "次にやること", "ko": "다음에 할 일"},
    "从你反复做的事里看出来的苗头——只是提醒，不是要求；每条都可以「不再提醒」": {
        "en": "Patterns spotted in what you keep doing — a nudge, not an "
              "instruction; every item can be dismissed",
        "de": "Muster aus dem, was Sie wiederholt tun – ein Hinweis, keine "
              "Vorgabe; jeder Eintrag lässt sich abwählen",
        "es": "Patrones vistos en lo que repites: solo un aviso, no una orden; "
              "cada elemento se puede descartar",
        "fr": "Des tendances vues dans ce que vous faites souvent — un rappel, "
              "pas une consigne ; chaque élément peut être écarté",
        "ja": "繰り返している作業から見えた傾向——ただのリマインダーで、指示ではありません。"
              "項目ごとに通知をオフにできます",
        "ko": "반복하는 작업에서 발견된 흐름——안내일 뿐 지시가 아닙니다. "
              "항목마다 알림을 끌 수 있습니다"},
    "出现过 {n} 次": {
        "en": "Seen {n} times", "de": "{n} Mal aufgetreten",
        "es": "Apareció {n} veces", "fr": "Vu {n} fois",
        "ja": "{n} 回出现", "ko": "{n}회出现"},
    "不再提醒": {
        "en": "Stop reminding", "de": "Nicht mehr erinnern",
        "es": "Dejar de avisar", "fr": "Ne plus rappeler",
        "ja": "もう通知しない", "ko": "다시 알리지 않음"},
    "今天过期": {
        "en": "Expires today", "de": "Läuft heute ab",
        "es": "Caduca hoy", "fr": "Expire aujourd’hui",
        "ja": "今日が期限", "ko": "오늘 만료"},
    "约 {n} 天后过期": {
        "en": "Expires in about {n} days", "de": "Läuft in etwa {n} Tagen ab",
        "es": "Caduca en unos {n} días", "fr": "Expire dans environ {n} jours",
        "ja": "約{n}日後に期限切れ", "ko": "약 {n}일 후 만료"},
    "忽略失败：{err}": {
        "en": "Dismiss failed: {err}", "de": "Ausblenden fehlgeschlagen: {err}",
        "es": "No se pudo descartar: {err}", "fr": "Impossible d’écarter : {err}",
        "ja": "通知オフに失敗しました：{err}", "ko": "알림 해제 실패: {err}"},
    "……还有 {n} 条": {
        "en": "{n} more", "de": "{n} weitere", "es": "{n} más",
        "fr": "{n} de plus", "ja": "さらに {n} 件", "ko": "{n}개 더"},
}


def main() -> int:
    check_entries(E)
    apply_entries(E)
    return 0


if __name__ == "__main__":
    sys.exit(main())
