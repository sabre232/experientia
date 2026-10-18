# -*- coding: utf-8 -*-
"""补齐「送达通道记账 + 第④格诊断」新增词条到 7 语 .po。

用法：uv run python scripts/i18n_delivery_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范同 i18n_poster_entries.py：de=Sie+„“、es=tú+«»、fr=’+«»、
ko=합니다체+''、非 CJK 禁全角括号与残留汉字（脚本自检）。
"""

from __future__ import annotations

import sys

from i18n_entry_lib import apply_entries, check_entries

E: dict[str, dict[str, str]] = {
    # ---------- 里程碑（growth_story ACH_HIT*） ----------
    "{name}解锁了": {"en": "{name} unlocked", "de": "{name} freigeschaltet",
                "es": "{name} desbloqueado", "fr": "{name} débloqué",
                "ja": "{name} を解除", "ko": "{name} 해제됨"},
    "{name}解锁了：{agent}": {"en": "{name} unlocked: {agent}",
                         "de": "{name} freigeschaltet: {agent}",
                         "es": "{name} desbloqueado: {agent}",
                         "fr": "{name} débloqué : {agent}",
                         "ja": "{name} を解除：{agent}",
                         "ko": "{name} 해제: {agent}"},
    "{name}解锁了：{agent} 的「{who}」": {
        "en": "{name} unlocked: {agent} · {who}",
        "de": "{name} freigeschaltet: {agent} · {who}",
        "es": "{name} desbloqueado: {agent} · {who}",
        "fr": "{name} débloqué : {agent} · {who}",
        "ja": "{name} を解除：{agent}「{who}」",
        "ko": "{name} 해제: {agent} · {who}"},
    # ---------- 类别判据加项 ----------
    "『{who}』平均比最初几次少 {n} 轮修正": {
        "en": "“{who}” takes {n} fewer rounds on average than at first",
        "de": "„{who}“: {n} Runden weniger als anfangs",
        "es": "«{who}» necesita {n} rondas menos que al principio",
        "fr": "« {who} » demande {n} allers-retours de moins qu’au début",
        "ja": "『{who}』は最初より平均 {n} ラウンド少ない",
        "ko": "『{who}』는 처음보다 평균 {n}라운드 줄었습니다"},
    # ---------- 四问（growth_story Q_*） ----------
    "这周新固化 {n} 条坑：{who}": {
        "en": "{n} pitfalls locked in this week: {who}",
        "de": "{n} Fallstricke diese Woche verankert: {who}",
        "es": "{n} tropiezos fijados esta semana: {who}",
        "fr": "{n} écueils ancrés cette semaine : {who}",
        "ja": "今週 {n} 件の落とし穴を固定：{who}",
        "ko": "이번 주 함정 {n}개 고정: {who}"},
    "『{who}』这周被自动带上 {n} 次": {
        "en": "“{who}” was auto-attached {n} times this week",
        "de": "„{who}“ wurde diese Woche {n} Mal automatisch beigefügt",
        "es": "«{who}» se adjuntó solo {n} veces esta semana",
        "fr": "« {who} » a été joint automatiquement {n} fois cette semaine",
        "ja": "『{who}』は今週 {n} 回自動で添付されました",
        "ko": "『{who}』가 이번 주 {n}회 자동으로 첨부됐습니다"},
    "从每次任务 {e} 回降到 {r} 回": {
        "en": "from {e} fixes per task down to {r}",
        "de": "von {e} auf {r} Korrekturen pro Aufgabe",
        "es": "de {e} correcciones por tarea a {r}",
        "fr": "de {e} à {r} corrections par tâche",
        "ja": "1 件 {e} 回 → {r} 回に減少",
        "ko": "작업당 {e}회에서 {r}회로 감소"},
    "有记录的周还不够多，先继续用助手干活": {
        "en": "Not enough recorded weeks yet — keep working with your assistants",
        "de": "Noch zu wenige aufgezeichnete Wochen – arbeiten Sie weiter damit",
        "es": "Aún faltan semanas registradas; sigue trabajando con el asistente",
        "fr": "Pas encore assez de semaines relevées — continuez à travailler ainsi",
        "ja": "記録のある週がまだ少ないので、まずは作業を続けてください",
        "ko": "기록된 주가 아직 부족해요, 계속 작업해 보세요"},
    "没有发现用错地方的情况": {
        "en": "Nothing was applied in the wrong place",
        "de": "Keine Fehlplatzierung festgestellt",
        "es": "No se usó nada donde no tocaba",
        "fr": "Rien n’a été appliqué au mauvais endroit",
        "ja": "場違いな使い方はありませんでした",
        "ko": "잘못 쓰인 곳은 없었습니다"},
    # ---------- 送达通道（growth_story DELIV_*） ----------
    "经验已送达助手 {n} 次（代理 {proxy} · hook {hook}）": {
        "en": "Experience reached your assistants {n} times "
             "(proxy {proxy} · hook {hook})",
        "de": "Erfahrungen {n} Mal an Assistenten übergeben "
             "(Proxy {proxy} · Hook {hook})",
        "es": "Las experiencias llegaron {n} veces a los asistentes "
             "(proxy {proxy} · hook {hook})",
        "fr": "Les expériences sont parvenues {n} fois aux assistants "
             "(proxy {proxy} · hook {hook})",
        "ja": "経験を {n} 回エージェントへ届けました（プロキシ {proxy} · hook {hook}）",
        "ko": "경험을 {n}회 어시스턴트에게 전달했습니다 (프록시 {proxy} · hook {hook})"},
    # ---------- 欠账卡 / 主句 ----------
    "{n} 次已送达（代理 {p} · hook {h}）/ 需要 {need} 次，第 ⑤ 格才会有数字": {
        "en": "{n} delivered (proxy {p} · hook {h}) / {need} needed before "
             "step ⑤ shows a number",
        "de": "{n} übergeben (Proxy {p} · Hook {h}) / {need} nötig, damit Feld ⑤ "
             "eine Zahl zeigt",
        "es": "{n} entregadas (proxy {p} · hook {h}) / hacen falta {need} para "
             "que el paso ⑤ muestre un número",
        "fr": "{n} remises (proxy {p} · hook {h}) / il en faut {need} pour que la "
             "case ⑤ affiche un chiffre",
        "ja": "{n} 回届けました（プロキシ {p} · hook {h}）／{need} 回必要で "
             "⑤ に数が出ます",
        "ko": "{n}회 전달됨 (프록시 {p} · hook {h}) / {need}회는 되어야 ⑤ 에 "
              "숫자가 뜹니다"},
    "要你返工的次数，从每次 {e} 回降到 {r} 回": {
        "en": "You sent work back less often: {e} → {r} fixes per task",
        "de": "Nacharbeit seltener: {e} → {r} Korrekturen pro Aufgabe",
        "es": "Menos rehacer: de {e} a {r} correcciones por tarea",
        "fr": "Moins de retouches : de {e} à {r} corrections par tâche",
        "ja": "手戻りが 1 件 {e} 回 → {r} 回に減少",
        "ko": "재작업이 작업당 {e}회 → {r}회로 줄었습니다"},
    "还在攒样本：多做几次同类任务就能看出返工有没有变少": {
        "en": "Still collecting samples — a few more like tasks will show whether "
             "rework is dropping",
        "de": "Proben sammeln noch – einige ähnliche Aufgaben zeigen, ob die "
             "Nacharbeit sinkt",
        "es": "Siguiendo con muestras: unas cuantas tareas iguales dirán si el "
             "rehacer baja",
        "fr": "Échantillons en cours — quelques tâches semblables diront si les "
             "retouches baissent",
        "ja": "サンプルをためています。同種の作業をもう少しすれば手戻りの減少が "
             "分かります",
        "ko": "표본을 모으는 중입니다. 같은 작업을 몇 번 더 하면 재작업 감소가 "
              "보여요"},
    "去接上": {"en": "Connect it", "de": "Jetzt verbinden", "es": "Conectarlo",
            "fr": "Le brancher", "ja": "接続する", "ko": "연결하기"},
}


def main() -> int:
    check_entries(E)
    apply_entries(E)
    return 0


if __name__ == "__main__":
    sys.exit(main())
