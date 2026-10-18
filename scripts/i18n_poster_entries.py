# -*- coding: utf-8 -*-
"""补齐「成长海报 × 周报重构思」新增界面词条到 7 语 .po。

用法：uv run python scripts/i18n_poster_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=tú+«»、fr=撇号 ’+«»、ko=합니다체+''、
非 CJK 禁全角括号与残留汉字（脚本自检）。

注意：growth_story 只存模板 + 参数，所以这里每条 msgid 都带 {占位符}，
译文必须用同名占位符（test_i18n 有"占位符 ⊆ zh 源串"护栏）。
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
    # ---------- 叙事模板（growth_story） ----------
    "{agents} 个助手 · {proj} 个项目 · {days} 个活跃日": {
        "en": "{agents} assistants · {proj} projects · {days} active days",
        "de": "{agents} Assistenten · {proj} Projekte · {days} aktive Tage",
        "es": "{agents} asistentes · {proj} proyectos · {days} días activos",
        "fr": "{agents} assistants · {proj} projets · {days} jours actifs",
        "ja": "{agents} エージェント · {proj} プロジェクト · {days} 日稼働",
        "ko": "어시스턴트 {agents}개 · 프로젝트 {proj}개 · 활동 {days}일"},
    "{a} – {b} · {w} 周": {
        "en": "{a} – {b} · {w} weeks", "de": "{a} – {b} · {w} Wochen",
        "es": "{a} – {b} · {w} semanas", "fr": "{a} – {b} · {w} semaines",
        "ja": "{a} – {b} · {w} 週", "ko": "{a} – {b} · {w}주"},
    "{cnt} 类 · 最多一类撞了 {top} 次": {
        "en": "{cnt} kinds · worst hit {top} times",
        "de": "{cnt} Arten · häufigste {top} Mal",
        "es": "{cnt} tipos · el peor, {top} veces",
        "fr": "{cnt} sortes · le pire, {top} fois",
        "ja": "{cnt} 種 · 最多で {top} 回", "ko": "{cnt}종 · 최다는 {top}회"},
    "{q}？{a}": {
        "en": "{q}? {a}", "de": "{q}? {a}", "es": "¿{q}? {a}",
        "fr": "{q} ? {a}", "ja": "{q}？{a}", "ko": "{q}? {a}"},
    "{who} 从 {e} 回/次 降到 {r} 回/次": {
        "en": "{who} dropped from {e} to {r} corrections per task",
        "de": "{who}: von {e} auf {r} Korrekturen pro Aufgabe",
        "es": "{who} bajó de {e} a {r} correcciones por tarea",
        "fr": "{who} : de {e} à {r} corrections par tâche",
        "ja": "{who}は 1 件 {e} 回 → {r} 回に減少",
        "ko": "{who}는 작업당 {e}회 → {r}회로 줄었습니다"},
    "{who} 你一次都没纠正过，本来就顺": {
        "en": "You never corrected {who} — it was already smooth",
        "de": "{who} korrigierten Sie nie – es lief schon glatt",
        "es": "{who} nunca lo corregiste; ya iba fluido",
        "fr": "Vous n’avez jamais repris {who} — ça roulait déjà",
        "ja": "{who} は一度も修正なし、もともとスムーズ",
        "ko": "{who}는 한 번도 고쳐 달라고 하지 않았어요, 원래 부드러움"},
    "{who} 这周没来干活": {
        "en": "{who} didn’t work this week", "de": "{who} war diese Woche nicht aktiv",
        "es": "{who} no trabajó esta semana", "fr": "{who} n’a rien fait cette semaine",
        "ja": "{who} は今週動きませんでした", "ko": "{who}는 이번 주에 없었어요"},
    "从这些活里总结出做法": {
        "en": "Practices distilled from this work",
        "de": "Aus dieser Arbeit gewonnene Vorgehensweisen",
        "es": "Prácticas sacadas de este trabajo",
        "fr": "Bonnes pratiques tirées de ce travail",
        "ja": "この作業から対処を抽出", "ko": "이 작업에서 방법을 추렸습니다"},
    "任务": {"en": "Tasks", "de": "Aufgaben", "es": "Tareas", "fr": "Tâches",
           "ja": "タスク", "ko": "작업"},
    "传承 把一份方法导出成可复用的 Skill 就解锁": {
        "en": "Legacy — unlock by exporting a method as a reusable Skill",
        "de": "Vermächtnis – freischalten, indem Sie eine Methode als "
             "wiederverwendbares Skill exportieren",
        "es": "Legado: se desbloquea exportando un método como Skill reutilizable",
        "fr": "Transmission — débloqué en exportant une méthode en Skill réutilisable",
        "ja": "伝承 方法を再利用可能な Skill に書き出すと解除",
        "ko": "전승 방법을 재사용 가능한 Skill로 내보내면 해제됩니다"},
    "你干的活都被看见": {
        "en": "Your work is captured automatically",
        "de": "Ihre Arbeit wird automatisch erfasst",
        "es": "Tu trabajo se registra solo",
        "fr": "Votre travail est saisi automatiquement",
        "ja": "作業は自動で記録", "ko": "작업이 자동으로 기록됩니다"},
    "做对了吗": {"en": "Did it get it right", "de": "Richtig gemacht?",
             "es": "¿Lo hizo bien", "fr": "Bien fait ?", "ja": "正しくできたか",
             "ko": "잘했나요"},
    "判轻重": {"en": "Ranked", "de": "Bewertet", "es": "Priorizado",
            "fr": "Priorisé", "ja": "重要度判定", "ko": "우선순위"},
    "助手": {"en": "Assistant", "de": "Assistent", "es": "Asistente",
           "fr": "Assistant", "ja": "エージェント", "ko": "어시스턴트"},
    "哪条经验在变强": {"en": "Which experience is getting stronger",
                  "de": "Welche Erfahrung wird stärker",
                  "es": "Qué experiencia está mejorando",
                  "fr": "Quelle expérience progresse",
                  "ja": "どの経験が強くなっているか", "ko": "어떤 경험이 강해지나"},
    "四个问题": {"en": "Four questions", "de": "Vier Fragen",
             "es": "Cuatro preguntas", "fr": "Quatre questions",
             "ja": "四つの問い", "ko": "네 가지 질문"},
    "头两周 {en} 次任务改 {ec} 回 · 最近 {rn} 次任务改 {rc} 回": {
        "en": "First two weeks: {ec} fixes over {en} tasks · "
             "last {rn} tasks: {rc} fixes",
        "de": "Erste zwei Wochen: {ec} Korrekturen in {en} Aufgaben · "
             "letzte {rn} Aufgaben: {rc} Korrekturen",
        "es": "Primeras dos semanas: {ec} correcciones en {en} tareas · "
             "últimas {rn} tareas: {rc} correcciones",
        "fr": "Deux premières semaines : {ec} reprises en {en} tâches · "
             "{rn} dernières tâches : {rc} reprises",
        "ja": "最初の 2 週 {en} 件で {ec} 回 · 最近 {rn} 件で {rc} 回",
        "ko": "처음 2주 {en}회 작업에 {ec}회 · 최근 {rn}회 작업에 {rc}회"},
    "头两周 → 最近": {"en": "First weeks → recent", "de": "Anfang → zuletzt",
                  "es": "Principio → ahora", "fr": "Début → récent",
                  "ja": "初期 → 直近", "ko": "초기 → 최근"},
    "带回给 AI": {"en": "Fed back to AI", "de": "Zurück zur KI",
              "es": "Devuelto a la IA", "fr": "Rendu à l’IA",
              "ja": "AI に返す", "ko": "AI 에게 되돌림"},
    "平均每个任务：{e} 回/次 → {r} 回/次": {
        "en": "Average per task: {e} → {r} corrections",
        "de": "Ø pro Aufgabe: {e} → {r} Korrekturen",
        "es": "Media por tarea: {e} → {r} correcciones",
        "fr": "Moyenne par tâche : {e} → {r} corrections",
        "ja": "1 タスク平均：{e} 回 → {r} 回",
        "ko": "작업당 평균: {e}회 → {r}회"},
    "恭喜！解锁新里程碑": {"en": "A new milestone unlocked",
                     "de": "Neuen Meilenstein freigeschaltet",
                     "es": "¡Nuevo hito desbloqueado!",
                     "fr": "Nouveau palier débloqué",
                     "ja": "新しい到達点！", "ko": "새 기록을 달성했어요!"},
    "拼成一张海报": {"en": "Turn this into a poster",
                "de": "Als Poster erstellen", "es": "Convertir en póster",
                "fr": "En faire une affiche", "ja": "ポスターにする",
                "ko": "포스터로 만들기"},
    "提炼出": {"en": "Distilled", "de": "Verdichtet", "es": "Destilado",
            "fr": "Distillé", "ja": "抽出", "ko": "추려냄"},
    "收进来": {"en": "Collected", "de": "Erfasst", "es": "Recogido",
            "fr": "Collecté", "ja": "収集", "ko": "수집"},
    "更快了吗": {"en": "Did it get faster", "de": "Schneller geworden?",
             "es": "¿Más rápido", "fr": "Plus rapide ?", "ja": "速くなったか",
             "ko": "빨라졌나요"},
    "最值钱的三条经验": {"en": "Three most valuable lessons",
                   "de": "Die drei wertvollsten Erfahrungen",
                   "es": "Las tres experiencias más valiosas",
                   "fr": "Les trois expériences les plus utiles",
                   "ja": "一番価値ある 3 件", "ko": "가장 값진 세 가지"},
    "有没有用错地方": {"en": "Was it used in the wrong place",
                  "de": "Falsch eingesetzt?", "es": "¿Se usó donde no tocaba",
                  "fr": "Mal appliqué ?", "ja": "場違いな使い方はなかったか",
                  "ko": "잘못 쓰인 곳은 없나요"},
    "本周结算": {"en": "Weekly wrap-up", "de": "Wochenabschluss",
             "es": "Cierre semanal", "fr": "Bilan hebdomadaire",
             "ja": "今週の締め", "ko": "이번 주 마감"},
    "本阶段（全部记录）": {"en": "This stage (all records)",
                     "de": "Diese Phase (alle Daten)",
                     "es": "Esta etapa (todo)", "fr": "Étape actuelle (tout)",
                     "ja": "この段階（全記録）", "ko": "이번 단계 (전체)"},
    "柱 = 每周任务数 · 线 = 返工回/次": {
        "en": "Bars = tasks per week · line = fixes per task",
        "de": "Balken = Aufgaben pro Woche · Linie = Korrekturen pro Aufgabe",
        "es": "Barras = tareas/semana · línea = correcciones/tarea",
        "fr": "Barres = tâches par semaine · courbe = reprises par tâche",
        "ja": "棒 = 週次タスク数 · 線 = 1 件あたり手戻り",
        "ko": "막대 = 주별 작업 · 선 = 작업당 재작업"},
    "没有新固化的坑——不是坏事，说明没踩到新的": {
        "en": "No new pitfall locked in — nothing new tripped it up",
        "de": "Kein neuer Fallstricke verankert – nichts Neues ist aufgetreten",
        "es": "Ningún tropiezo nuevo fijado, no hubo recaídas",
        "fr": "Aucun nouvel écueil ancré — rien de nouveau n’est apparu",
        "ja": "新たに固定した落とし穴はなし——新しい失敗もなし",
        "ko": "새로 굳어진 함정은 없어요, 새 실수도 없었습니다"},
    "没有新的就不庆祝——数字变大不算里程碑，具象变身才算。": {
        "en": "Nothing to celebrate this week — a bigger number isn’t a "
             "milestone, a real change is.",
        "de": "Nichts zu feiern – eine größere Zahl ist kein Meilenstein, "
             "eine echte Veränderung schon",
        "es": "Nada que celebrar: un número más grande no es un hito, "
             "un cambio real sí",
        "fr": "Rien à fêter : un chiffre plus grand n’est pas un palier, "
             "un vrai changement oui",
        "ja": "新しい達成がなければ祝いません。数字の増加は到達点ではありません。",
        "ko": "새로 이룬 게 없으면 축하하지 않아요. 숫자 늘어난 건 기록이 아닙니다."},
    "满分 {top} · 你纠正后定下 {corr}": {
        "en": "{top} perfect scores · {corr} settled after you corrected",
        "de": "{top} Bestnoten · {corr} nach Ihrer Korrektur",
        "es": "{top} con nota máxima · {corr} tras tus correcciones",
        "fr": "{top} notes parfaites · {corr} après vos corrections",
        "ja": "満点 {top} · 修正で確定 {corr}",
        "ko": "만점 {top} · 교정 후 확정 {corr}"},
    "点开看本周结算": {"en": "Open the weekly wrap-up",
                  "de": "Wochenabschluss ansehen", "es": "Ver el cierre semanal",
                  "fr": "Voir le bilan hebdomadaire", "ja": "今週の締めを見る",
                  "ko": "이번 주 마감 보기"},
    "经验飞轮转到哪了": {"en": "Where the experience flywheel stands",
                   "de": "Wo das Erfahrungsrad steht",
                   "es": "En qué punto está el volante",
                   "fr": "Où en est la roue des expériences",
                   "ja": "フライホイールの現在地", "ko": "플라이휠 진행 상황"},
    "老练 还差 1 个任务类别出现真实改善（现在 {n} 次任务都还没分类）": {
        "en": "Veteran — needs one task type to show real gains "
             "(all {n} tasks are still uncategorized)",
        "de": "Routine – nötig ist eine Aufgabenart mit echtem Zugewinn "
             "(alle {n} Aufgaben sind noch unkategorisiert)",
        "es": "Experto — falta un tipo de tarea con mejora real "
             "(las {n} tareas siguen sin categorizar)",
        "fr": "Expertise — il faut un type de tâche avec un vrai gain "
             "({n} tâches sont encore non classées)",
        "ja": "老練 真の改善が出るタスク種があと 1 つ必要（現在 {n} 件は未分類）",
        "ko": "원숙 실제 개선이 있는 작업 유형이 하나 더 필요해요 "
              "(현재 {n}회 모두 미분류)"},
    "要你返工的次数，{w} 周里少了 {p}%": {
        "en": "You sent work back {p}% less often over {w} weeks",
        "de": "Nacharbeit in {w} Wochen um {p}% weniger",
        "es": "Hiciste rehacer un {p}% menos en {w} semanas",
        "fr": "{p}% de retouches en moins sur {w} semaines",
        "ja": "{w} 週で手戻りが {p}% 減少",
        "ko": "{w}주 동안 재작업이 {p}% 줄었습니다"},
    "读取本周结算失败：{err}": {
        "en": "Couldn’t load the weekly wrap-up: {err}",
        "de": "Wochenabschluss konnte nicht geladen werden: {err}",
        "es": "No se pudo leer el cierre semanal: {err}",
        "fr": "Lecture du bilan hebdomadaire impossible : {err}",
        "ja": "今週の締めを読み込めません：{err}",
        "ko": "이번 주 마감을 불러오지 못했습니다: {err}"},
    "还没开始——经验一次都没被带回给助手": {
        "en": "Not started — no experience has been handed back yet",
        "de": "Noch nicht begonnen – keine Erfahrung wurde zurückgegeben",
        "es": "Aún no empieza: ninguna experiencia se ha devuelto",
        "fr": "Pas encore commencé — aucune expérience n’a été renvoyée",
        "ja": "まだ始まっていません——経験は一度も AI に返っていません",
        "ko": "아직 시작 전이에요 — 경험이 되돌려진 적이 없습니다"},
    "还没接到你的助手会话里": {"en": "Not wired into your sessions yet",
                        "de": "Noch nicht mit Ihren Sitzungen verbunden",
                        "es": "Aún no conectado a tus sesiones",
                        "fr": "Pas encore branché sur vos sessions",
                        "ja": "まだセッションに接続されていません",
                        "ko": "아직 세션에 연결 안 됨"},
    "这段时间": {"en": "This period", "de": "Dieser Zeitraum",
             "es": "Este periodo", "fr": "Cette période", "ja": "この期間",
             "ko": "이 기간"},
    "这段时间攒下的东西": {"en": "What you built up",
                     "de": "Was sich angesammelt hat",
                     "es": "Lo que has acumulado",
                     "fr": "Ce que vous avez accumulé",
                     "ja": "この期間の積み上げ", "ko": "这段时间 쌓인 것"},
    "避坑达人 {cnt} 类坑还在反复出现，最频繁的一类撞了 {top} 次": {
        "en": "Pitfall pro — {cnt} pitfalls still recur; the worst hit {top} times",
        "de": "Fallstrick-Profi – {cnt} Fallstricke treten weiter auf, "
             "der häufigste {top} Mal",
        "es": "Antitropiezos — {cnt} tropiezos siguen repitiéndose; "
             "el peor, {top} veces",
        "fr": "Chasse-écueils — {cnt} écueils reviennent encore, "
             "le pire {top} fois",
        "ja": "落とし穴マスター {cnt} 種がまだ再発、最多は {top} 回",
        "ko": "함정 퇴치 {cnt}종이 계속 나와요, 최다는 {top}회"},
    "这阵子攒下的东西": {"en": "What you built up", "de": "Was sich angesammelt hat",
                "es": "Lo que has acumulado", "fr": "Ce que vous avez accumulé",
                "ja": "この間の積み上げ", "ko": "요즘 쌓아둔 것"},
    "这轮结算里有成就达成——点开报告看是哪一项": {
        "en": "This wrap-up unlocked an achievement — open the report to see which",
        "de": "Dieser Abschluss hat eine Auszeichnung freigeschaltet – "
             "öffnen Sie den Bericht, um zu sehen welche",
        "es": "Este cierre desbloqueó un logro; abre el informe para ver cuál",
        "fr": "Ce bilan a débloqué une réussite — ouvrez le rapport pour la voir",
        "ja": "今回の締めで達成点が解禁されました。報告書でどの項目か確認できます",
        "ko": "이번 마감에서 기록을 하나 열었어요 — 보고서에서 확인하세요"},
    "按任务的磨合": {"en": "How each task type is going",
                "de": "Einspielen je Aufgabe", "es": "Cómo va cada tipo de tarea",
                "fr": "L'accordage par type de tâche",
                "ja": "タスク種ごとの手応え", "ko": "작업 종류별 손발"},
    "里程碑": {"en": "Milestones", "de": "Meilensteine", "es": "Hitos",
           "fr": "Paliers", "ja": "到達点", "ko": "기록"},
    "里程碑 · 已解锁": {"en": "Milestones · unlocked", "de": "Meilensteine · frei",
                   "es": "Hitos · desbloqueados", "fr": "Paliers · débloqués",
                   "ja": "到達点 · 解除済み", "ko": "기록 · 해제됨"},
    "里程碑 · 还没解锁": {"en": "Milestones · not yet unlocked",
                     "de": "Meilensteine · noch nicht freigeschaltet",
                     "es": "Hitos · aún no desbloqueados",
                     "fr": "Paliers · pas encore débloqués",
                     "ja": "到達点 · まだ未解除", "ko": "기록 · 아직 해제 안 됨"},
    "（还没有成长记录——用 agent 干几个活，这张图就有内容了）": {
        "en": "(No growth records yet — let an agent do a few tasks and "
             "this fills in)",
        "de": "(Noch keine Wachstumsdaten – lassen Sie ein Agent einige "
             "Aufgaben erledigen, dann füllt sich das)",
        "es": "(Aún no hay registro de crecimiento: deja que un agente haga "
             "varias tareas y esto se llenará)",
        "fr": "Pas encore de suivi de progression — faites faire quelques "
             "tâches à un agent et cela se remplira",
        "ja": "成長記録はまだありません——エージェントにいくつか作業させると埋まります",
        "ko": "성장 기록이 아직 없어요 — 에이전트에게 몇 번 시키면 채워집니다"},
}


def _check() -> None:
    for mid, table in E.items():
        ph = set(re.findall(r"\{(\w+)\}", mid))
        for lang, text in table.items():
            assert text.strip(), f"{lang} 空译文: {mid[:20]}"
            assert "…" not in text, f"{lang} 半截句: {mid[:20]}"
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
