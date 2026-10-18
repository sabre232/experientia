# -*- coding: utf-8 -*-
"""补齐「成长页重构思」新增界面词条到 7 语 .po。

用法：uv run python scripts/i18n_growth_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=tú+«»、fr=撇号 ’+«»、ko=합니다체+''、
非 CJK 语言禁全角括号与残留汉字（脚本末尾自检）。
"""

from __future__ import annotations

import sys

from i18n_entry_lib import apply_entries, check_entries

E: dict[str, dict[str, str]] = {
    "AI 判定 {n} 分": {
        "en": "AI rated {n}", "de": "KI-Bewertung {n}",
        "es": "La IA lo puntuó {n}", "fr": "Noté {n} par l’IA",
        "ja": "AI 判定 {n} 点", "ko": "AI 평가 {n}점"},
    "AI 判过轻重 + 反复撞见的做法": {
        "en": "AI-rated + fixes you kept hitting",
        "de": "KI-gewichtet + wiederkehrende Lösungen",
        "es": "Puntuado por la IA + soluciones que repetías",
        "fr": "Notés par l’IA + réflexes revenus souvent",
        "ja": "AI が重要度を判定＋何度も出会った対処",
        "ko": "AI 우선순위 판정 + 반복된 대응"},
    "AI 打了重要性分": {
        "en": "AI scored its importance", "de": "KI bewertete die Wichtigkeit",
        "es": "La IA puntuó su importancia", "fr": "L’IA a noté son importance",
        "ja": "AI が重要度をつけました", "ko": "AI 가 중요도를 매겼습니다"},
    "{a}；{b} 次任务还都在“未分类”一个桶里，没法按同类任务做严格对比 —— "
    "这条线现在只能当参考，不能当证据。": {
        "en": "{a}; and all {b} tasks still sit in one “Uncategorized” bucket, "
             "so like-for-like comparison isn’t possible — read this line as a "
             "reference, not as proof.",
        "de": "{a}; außerdem liegen alle {b} Aufgaben noch in der einen Gruppe "
             "„Nicht kategorisiert“, ein strikter Vergleich gleicher Aufgaben "
             "ist so nicht möglich. Diese Linie ist ein Hinweis, kein Beweis.",
        "es": "{a}; y las {b} tareas siguen todas en «Sin categorizar», así que "
             "no se puede comparar tarea por tarea. Toma esta línea como "
             "referencia, no como prueba.",
        "fr": "{a} ; et les {b} tâches sont encore toutes dans « Non classées », "
             "impossible de comparer des tâches semblables — lisez cette courbe "
             "comme une référence, pas comme une preuve.",
        "ja": "{a}。{b} 件のタスクがまだ「未分類」1 区分にまとまっているため、"
             "同種タスクとの厳密な比較はできません。この線は参考値で、証拠では "
             "ありません。",
        "ko": "{a}; {b}개 작업이 아직 '미분류' 한 칸에 묶여 있어 같은 종류끼리 "
             "엄밀히 비교할 수 없습니다 — 이 선은 참고용이지 증거가 아닙니다."},
    "{n} 个助手 · {p} 个项目": {
        "en": "{n} assistants · {p} projects", "de": "{n} Assistenten · {p} Projekte",
        "es": "{n} asistentes · {p} proyectos", "fr": "{n} assistants · {p} projets",
        "ja": "{n} エージェント · {p} プロジェクト", "ko": "어시스턴트 {n}개 · 프로젝트 {p}개"},
    "{n} 次任务 · 纠正 {c} 回 · 最近 {d}": {
        "en": "{n} tasks · {c} corrections · last {d}",
        "de": "{n} Aufgaben · {c} Korrekturen · zuletzt {d}",
        "es": "{n} tareas · {c} correcciones · último {d}",
        "fr": "{n} tâches · {c} corrections · dernier {d}",
        "ja": "{n} タスク · 修正 {c} 回 · 最終 {d}",
        "ko": "작업 {n}회 · 교정 {c}회 · 최근 {d}"},
    "{n} 次任务现在全挤在“未分类”一个桶里，所以“某类任务越做越顺”给不了分项对比": {
        "en": "All {n} tasks are still lumped into “Uncategorized”, so “smoother "
             "with practice” can’t be broken down by task type yet",
        "de": "Alle {n} Aufgaben stecken noch in „Nicht kategorisiert“, daher kann "
             "„mit Routine wird es glatter“ noch nicht nach Aufgabentyp aufgeschlüsselt werden",
        "es": "Las {n} tareas siguen metidas en «Sin categorizar», así que «cada vez "
             "más fluido» todavía no se puede desglosar por tipo",
        "fr": "Les {n} tâches sont encore regroupées dans « Non classées », "
             "impossible donc de détailler « ça roule mieux » par type de tâche",
        "ja": "{n} 件のタスクがまだ「未分類」一か所なので、「だんだんスムーズ」を "
             "タスク種別ごとには示せません",
        "ko": "{n}개 작업이 아직 '미분류' 하나에 몰려 있어 '점점顺滑' 항목별 비교는 "
             "아직 못 만듭니다"},
    "{s} 次任务 · 活跃 {d} 天 · 纠正 {c} 回": {
        "en": "{s} tasks · {d} active days · {c} corrections",
        "de": "{s} Aufgaben · {d} aktive Tage · {c} Korrekturen",
        "es": "{s} tareas · {d} días activos · {c} correcciones",
        "fr": "{s} tâches · {d} jours actifs · {c} corrections",
        "ja": "{s} タスク · 稼働 {d} 日 · 修正 {c} 回",
        "ko": "작업 {s}회 · 활동 {d}일 · 교정 {c}회"},
    "{w} 周里活跃 {d} 天": {
        "en": "{d} active days across {w} weeks", "de": "{d} aktive Tage in {w} Wochen",
        "es": "{d} días activos en {w} semanas", "fr": "{d} jours actifs sur {w} semaines",
        "ja": "{w} 週のうち稼働 {d} 日", "ko": "{w}주 중 활동 {d}일"},
    "{y} 年 {m} 月": {
        "en": "{y}-{m}", "de": "{m}/{y}", "es": "{m}/{y}", "fr": "{m}/{y}",
        "ja": "{y} 年 {m} 月", "ko": "{y}년 {m}월"},
    "① 收进来": {"en": "① Collected", "de": "① Erfasst", "es": "① Recogido",
              "fr": "① Collecté", "ja": "① 収集", "ko": "① 수집"},
    "② 提炼出": {"en": "② Distilled", "de": "② Verdichtet", "es": "② Destilado",
             "fr": "② Distillé", "ja": "② 抽出", "ko": "② 추려냄"},
    "③ 判轻重": {"en": "③ Ranked", "de": "③ Bewertet", "es": "③ Priorizado",
             "fr": "③ Priorisé", "ja": "③ 重要度判定", "ko": "③ 우선순위"},
    "④ 带回给 AI": {"en": "④ Fed back to AI", "de": "④ Zurück an die KI",
                "es": "④ Devuelto a la IA", "fr": "④ Rendu à l’IA",
                "ja": "④ AI に返す", "ko": "④ AI 에게 되돌림"},
    "⑤ 少返工": {"en": "⑤ Less rework", "de": "⑤ Weniger Nacharbeit",
             "es": "⑤ Menos rehacer", "fr": "⑤ Moins de retouches",
             "ja": "⑤ 手戻り減", "ko": "⑤ 재작업 감소"},
    "不过严格讲，这功劳还不能记在经验头上——它们一次都没被带回给你的助手，"
    "见下面第 ④ 格。": {
        "en": "Strictly speaking, that credit can’t go to the experiences yet — "
             "none of them has ever been handed back to your assistant "
             "(see step ④ below).",
        "de": "Streng genommen kann das nicht den Erfahrungen zugerechnet werden – "
             "keine davon wurde bisher an Ihren Assistenten zurückgegeben "
             "(siehe Feld ④ unten).",
        "es": "En rigor, eso aún no puede atribuirse a las experiencias: ninguna se "
             "ha devuelto a tu asistente (mira el paso ④ abajo).",
        "fr": "À strictement parler, ce mérite ne revient pas encore aux "
              "expériences : aucune n’a été rendue à votre assistant "
              "(voir la case ④ plus bas).",
        "ja": "厳密には、この改善を経験の成果とはまだ言えません——一度も AI に "
             "返っていないので（下の ④ 番目参照）。",
        "ko": "엄밀히 말해 이 개선은 경험 덕분에 됐다고 못 합니다 — 한 번도 "
             "어시스턴트에게 되돌려지지 않았습니다 (아래 ④ 칸)."},
    "为什么平了，以及还不能算证据": {
        "en": "Why it flattened, and why it isn’t proof yet",
        "de": "Warum es sich glättet – und warum es noch kein Beleg ist",
        "es": "Por qué se aplana, y por qué aún no es prueba",
        "fr": "Pourquoi ça s’aplatit, et pourquoi ce n’est pas encore une preuve",
        "ja": "横ばいな理由、そしてまだ証拠ではない理由",
        "ko": "횡보하는 이유, 그리고 아직 증거가 아닌 이유"},
    "从这些活里总结出可复用的做法": {
        "en": "Reusable practices distilled from this work",
        "de": "Wiederverwendbare Vorgehensweisen aus dieser Arbeit",
        "es": "Prácticas reutilizables sacadas de este trabajo",
        "fr": "Bonnes pratiques réutilisables tirées de ce travail",
        "ja": "この作業から再利用できるやり方を抽出",
        "ko": "이 작업에서 재사용 가능한 방법을 추렸습니다"},
    "你带着 {n} 个 AI 助手跑了 {s} 次活，攒下 {e} 条真算你的经验": {
        "en": "You ran {s} jobs with {n} AI assistants and banked {e} experiences "
             "that are genuinely yours",
        "de": "Sie haben {s} Aufgaben mit {n} KI-Assistenten erledigt und {e} "
             "Erfahrungen gesammelt, die wirklich Ihre sind",
        "es": "Has hecho {s} tareas con {n} asistentes de IA y guardado {e} "
             "experiencias que son de verdad tuyas",
        "fr": "Vous avez mené {s} tâches avec {n} assistants IA et accumulé {e} "
             "expériences qui sont vraiment les vôtres",
        "ja": "{n} 体の AI エージェントと {s} 件の作業をし、自分の経験 {e} 件をためました",
        "ko": "AI 어시스턴트 {n}개로 작업 {s}회를 하고, 진짜 내 경험 {e}건을 모았습니다"},
    "你干活的量 vs 要你返工的次数": {
        "en": "How much you got done vs how often you sent it back",
        "de": "Erledigtes Volumen vs. Anzahl Ihrer Nacharbeiten",
        "es": "Cuánto hiciste vs. cuántas veces lo tuviste que corregir",
        "fr": "Ce que vous avez produit vs les fois où vous avez dû reprendre",
        "ja": "作業量 vs 手戻りを頼んだ回数",
        "ko": "처리량 vs 다시 시킨 횟수"},
    "你干的活都被看见，不用手动记": {
        "en": "Your work is captured automatically — nothing to log by hand",
        "de": "Ihre Arbeit wird erfasst – nichts von Hand notieren",
        "es": "Vemos tu trabajo solo: no tienes que anotar nada",
        "fr": "Votre travail est saisi automatiquement, rien à noter à la main",
        "ja": "作業は自動で記録されます。手入力は不要です",
        "ko": "작업은 자동으로 기록됩니다. 직접 적지 않아도 돼요"},
    "你的经验": {"en": "Your experience", "de": "Ihre Erfahrungen",
             "es": "Tus experiencias", "fr": "Vos expériences",
             "ja": "あなたの経験", "ko": "내 경험"},
    "你的经验账本": {"en": "Your experience ledger", "de": "Ihr Erfahrungskonto",
               "es": "Tu libro de experiencias", "fr": "Votre registre d’expériences",
               "ja": "あなたの経験台帳", "ko": "내 경험 장부"},
    "你的经验（{n} 条 ≥8 分）": {
        "en": "Your experiences ({n} rated ≥8)", "de": "Ihre Erfahrungen ({n} mit ≥8)",
        "es": "Tus experiencias ({n} con ≥8)", "fr": "Vos expériences ({n} notées ≥8)",
        "ja": "あなたの経験（{n} 件が 8 点以上）", "ko": "내 경험 ({n}건이 8점 이상)"},
    "你纠正后定下": {"en": "Settled after you corrected it",
                "de": "Nach Ihrer Korrektur festgelegt",
                "es": "Fijado tras corregirlo tú", "fr": "Établi après votre correction",
                "ja": "あなたの修正で確定", "ko": "당신 교정 후 확정"},
    "你表过态的": {"en": "You’ve rated", "de": "Von Ihnen bewertet",
              "es": "Las que has valorado", "fr": "Celles que vous avez notées",
              "ja": "あなたが評価したもの", "ko": "당신이 평가한 것"},
    "你说过“不对，应该这样”": {
        "en": "You said “no, it should be like this”",
        "de": "Sie sagten „Nein, so muss es“",
        "es": "Dijiste «no, así no, así»",
        "fr": "Vous avez dit « non, il faut faire ainsi »",
        "ja": "あなたが「違う、こうする」と言ったもの",
        "ko": "당신이 '아니, 이렇게 해'라고 한 것"},
    "你还没点过“有用 / 没用”，AI 只能自己猜": {
        "en": "You haven’t marked anything useful/useless yet, so the AI can only guess",
        "de": "Sie haben noch nichts als nützlich/unbrauchbar markiert – die KI rät nur",
        "es": "Todavía no has marcado útil/inútil, así que la IA solo lo supone",
        "fr": "Vous n’avez rien marqué utile/inutile, l’IA ne peut que deviner",
        "ja": "まだ「有用／不要」を押していないので、AI は推測するのみです",
        "ko": "아직 '도움됨/안 됨'을 누르지 않아 AI 는 추측만 합니다"},
    "共 {n} 条属于你的经验": {
        "en": "{n} experiences are yours", "de": "{n} Erfahrungen gehören Ihnen",
        "es": "{n} experiencias son tuyas", "fr": "{n} expériences sont les vôtres",
        "ja": "あなた向けの経験は計 {n} 件", "ko": "내 경험은 총 {n}건"},
    "共 {n} 类、累计撞见 {c} 次，已自动生效": {
        "en": "{n} kinds, {c} hits in total — already applied automatically",
        "de": "{n} Arten, insgesamt {c} Mal aufgetreten – wirkt bereits automatisch",
        "es": "{n} tipos, {c} veces encontradas en total; ya actúa solo",
        "fr": "{n} sortes, {c} rencontres au total — déjà appliqué automatiquement",
        "ja": "計 {n} 種・延べ {c} 回、自動で反映済み",
        "ko": "총 {n}종 · 누적 {c}회, 자동으로 적용 중"},
    "几个助手各自的磨合": {
        "en": "How you’re syncing with each assistant",
        "de": "Einspielen mit jedem Assistenten",
        "es": "Cómo encajas con cada asistente",
        "fr": "L’accordage avec chaque assistant",
        "ja": "エージェントごとの手応え",
        "ko": "어시스턴트별 손발"},
    "分出任务类型": {"en": "Sort tasks by type", "de": "Aufgaben typisieren",
               "es": "Clasificar los tipos de tarea", "fr": "Classer les types de tâche",
               "ja": "タスクの種類分け", "ko": "작업 유형 분류"},
    "助手替你挡的坑": {"en": "Pitfalls your assistant takes for you",
                "de": "Fallstricke, die der Assistent für Sie auffängt",
                "es": "Tropiezos que el asistente asume por ti",
                "fr": "Les écueils que l’assistant encaisse pour vous",
                "ja": "エージェントが代わりに踏む落とし穴",
                "ko": "어시스턴트가 대신 막는 함정"},
    "去经验库看全部": {"en": "See all in the experience library",
                 "de": "Alle in der Erfahrungsbibliothek ansehen",
                 "es": "Ver todo en la biblioteca", "fr": "Tout voir dans la bibliothèque",
                 "ja": "経験ライブラリで全部見る", "ko": "경험 라이브러리에서 전체 보기"},
    "变顺只发生了一次": {"en": "The smoothness came once",
                  "de": "Der Routinegewinn kam nur einmal",
                  "es": "La mejora llegó una sola vez",
                  "fr": "Le progrès s’est produit une fois",
                  "ja": "スムーズになったのは一度だけ",
                  "ko": "손발이 맞은 건 한 번"},
    "同类任务返工降幅": {"en": "Rework drop for like tasks",
                  "de": "Nacharbeits-Rückgang bei gleichen Aufgaben",
                  "es": "Caída de rehacer en tareas iguales",
                  "fr": "Baisse des retouches sur tâches semblables",
                  "ja": "同種タスクの手戻り減少率",
                  "ko": "동일 작업 재작업 감소율"},
    "同类情况遇到 {n} 次": {"en": "Seen {n} times in similar cases",
                     "de": "{n} Mal in ähnlichen Fällen",
                     "es": "{n} veces en casos parecidos",
                     "fr": "{n} fois dans des cas semblables",
                     "ja": "同種ケース {n} 回", "ko": "유사 상황 {n}회"},
    "听你说哪条真有用": {"en": "Tell us which ones actually help",
                   "de": "Sagen Sie, was wirklich hilft",
                   "es": "Dinos cuáles sirven de verdad",
                   "fr": "Dites-nous ce qui sert vraiment",
                   "ja": "どれが本当に役立ったか教えてください",
                   "ko": "뭐가 진짜 도움됐는지 알려주세요"},
    "回/次": {"en": "per task", "de": "pro Aufgabe", "es": "por tarea",
           "fr": "par tâche", "ja": "回/件", "ko": "회/건"},
    "头 {e} 次任务你纠正了 {er} 回（平均 {early} 回/次），最近 {r} 次任务只纠正 "
    "{rr} 回（{recent} 回/次）。": {
        "en": "In the first {e} tasks you corrected {er} times ({early} per task); "
             "in the last {r}, only {rr} ({recent} per task).",
        "de": "In den ersten {e} Aufgaben korrigierten Sie {er} Mal ({early} pro "
             "Aufgabe), in den letzten {r} nur {rr} Mal ({recent}).",
        "es": "En las primeras {e} tareas corregiste {er} veces ({early} por tarea); "
             "en las últimas {r}, solo {rr} ({recent}).",
        "fr": "Sur les {e} premières tâches, vous avez repris {er} fois ({early} par "
             "tâche) ; sur les {r} dernières, seulement {rr} ({recent}).",
        "ja": "最初の {e} 件では {er} 回（{early} 回/件）修正、直近 {r} 件では "
             "{rr} 回（{recent} 回/件）だけ。",
        "ko": "처음 {e}회 때 {er}번 교정({early}회/건), 최근 {r}회 때는 {rr}번"
             "({recent}회/건)에 그쳤습니다."},
    "学习历程 / 方法沉淀 / 后台整理": {
        "en": "Learning history / methods / background tidy-up",
        "de": "Lernverlauf / Methoden / Hintergrundaufräumen",
        "es": "Historial de aprendizaje / métodos / orden en segundo plano",
        "fr": "Historique d’apprentissage / méthodes / ménage en arrière-plan",
        "ja": "学習の歩み / 方法の蓄積 / 裏方の整理",
        "ko": "학습 기록 / 방법 축적 / 백그라운드 정리"},
    "它自己手滑，不算你的": {"en": "Its own slip, not your lesson",
                      "de": "Eigener Fehler, nicht Ihrer",
                      "es": "Se resbaló solo, no es tu lección",
                      "fr": "Sa propre bourde, pas votre leçon",
                      "ja": "エージェントのミスで、あなたの教訓ではありません",
                      "ko": "그게 실수한 거라 당신의 교훈이 아니에요"},
    "平均每个任务纠正 {n} 回": {"en": "{n} corrections per task on average",
                        "de": "Ø {n} Korrekturen pro Aufgabe",
                        "es": "{n} correcciones por tarea de media",
                        "fr": "{n} corrections par tâche en moyenne",
                        "ja": "1 タスク平均 {n} 回修正",
                        "ko": "작업당 평균 {n}회 교정"},
    "平均每个任务被你纠正几回": {
        "en": "How often per task you had to step in",
        "de": "Wie oft Sie je Aufgabe eingreifen mussten",
        "es": "Cuántas veces por tarea tuviste que intervenir",
        "fr": "Combien de fois par tâche vous êtes intervenu",
        "ja": "タスクあたり何回修正を入れたか",
        "ko": "작업당 몇 번 고쳐 달라고 했는지"},
    "当前模型端点连不上 · 已熔断": {
        "en": "Model endpoint unreachable · circuit breaker open",
        "de": "Modell-Endpunkt nicht erreichbar · Sicherung ausgelöst",
        "es": "No se llega al endpoint del modelo · protección activada",
        "fr": "Point de terminaison du modèle injoignable · disjoncteur ouvert",
        "ja": "モデルエンドポイントに接続できず · 遮断中",
        "ko": "모델 엔드포인트에 연결 안 됨 · 차단됨"},
    "无月份": {"en": "No month", "de": "Kein Monat", "es": "Sin mes",
           "fr": "Sans mois", "ja": "月情報なし", "ko": "월 정보 없음"},
    "最近平均返工": {"en": "Recent rework average", "de": "Aktueller Nacharbeits-Schnitt",
               "es": "Media reciente de rehacer", "fr": "Moyenne récente de retouches",
               "ja": "直近の平均手戻り", "ko": "최근 평균 재작업"},
    "有记录的周还不够多（需要至少 {n} 个），先继续用助手干活。": {
        "en": "Not enough recorded weeks yet (need at least {n}) — keep working "
             "with your assistants.",
        "de": "Es fehlen noch aufgezeichnete Wochen (mindestens {n}) – arbeiten Sie "
             "einfach weiter mit dem Assistenten.",
        "es": "Aún no hay suficientes semanas registradas (hacen falta {n}); sigue "
             "trabajando con el asistente.",
        "fr": "Pas encore assez de semaines relevées (il en faut {n}) — continuez à "
             "travailler avec l’assistant.",
        "ja": "記録のある週がまだ足りません（最低 {n} 週）。まずは作業を続けてください。",
        "ko": "기록된 주가 아직 부족합니다 (최소 {n}주). 계속 작업해 주세요."},
    "未知时间": {"en": "Unknown time", "de": "Unbekannter Zeitpunkt",
             "es": "Hora desconocida", "fr": "Date inconnue",
             "ja": "時刻不明", "ko": "시간 알 수 없음"},
    "本阶段 {a} – {b} · {w} 周": {
        "en": "This stage {a} – {b} · {w} weeks", "de": "Diese Phase {a} – {b} · {w} Wochen",
        "es": "Esta etapa {a} – {b} · {w} semanas", "fr": "Étape actuelle {a} – {b} · "
        "{w} semaines", "ja": "この段階 {a} – {b} · {w} 週", "ko": "이번 단계 {a} – {b} · {w}주"},
    "样本不够的直接说不够，不拿进度条装样子": {
        "en": "Where there aren’t enough samples we say so — no decorative progress bars",
        "de": "Wo Proben fehlen, sagen wir das – keine dekorativen Fortschrittsbalken",
        "es": "Si faltan muestras lo decimos, sin barras de progreso de adorno",
        "fr": "Quand les exemples manquent, on le dit — pas de barre de remplissage "
        "pour faire joli",
        "ja": "サンプルが足りなければそう書きます。見せかけの進捗バーは使いません",
        "ko": "표본이 부족하면 그렇게 씁니다. 모양새용 진행률은 안 씁니다"},
    "次": {"en": "runs", "de": "Mal", "es": "veces", "fr": "fois", "ja": "回", "ko": "회"},
    "次任务": {"en": "tasks", "de": "Aufgaben", "es": "tareas", "fr": "tâches",
           "ja": "タスク", "ko": "회 작업"},
    "每周任务数": {"en": "Tasks per week", "de": "Aufgaben pro Woche",
              "es": "Tareas por semana", "fr": "Tâches par semaine",
              "ja": "週次タスク数", "ko": "주별 작업 수"},
    "满分 {n} 的 {c} 条，先看前 {m} 条": {
        "en": "{c} entries with a perfect {n}; showing the first {m}",
        "de": "{c} Einträge mit Bestnote {n} – erste {m} davon",
        "es": "{c} con nota máxima {n}; mostramos las primeras {m}",
        "fr": "{c} entrées notées {n} sur {n} — voici les {m} premières",
        "ja": "満点 {n} の {c} 件、まず {m} 件を表示",
        "ko": "만점 {n}인 {c}건, 먼저 {m}건 표시"},
    "点一次“有用”，排序听你的": {
        "en": "Mark one useful and the ranking follows you",
        "de": "Einmal „nützlich“ – die Reihenfolge folgt Ihnen",
        "es": "Marca una como útil y el orden te obedece",
        "fr": "Marquez-en une utile et le tri vous suit",
        "ja": "1 件「有用」を押せば並びがあなたの優先に",
        "ko": "하나만 '도움됨' 눌러도 순서가 당신 기준이 됩니다"},
    "点开展开：学习历程 / 方法沉淀 / 后台整理": {
        "en": "Expand: learning history / methods / background tidy-up",
        "de": "Aufklappen: Lernverlauf / Methoden / Aufräumen",
        "es": "Despliega: historial / métodos / orden en segundo plano",
        "fr": "Déplier : historique / méthodes / ménage en arrière-plan",
        "ja": "展開：学習の歩み / 方法 / 裏方の整理",
        "ko": "펼치기: 학습 기록 / 방법 / 백그라운드 정리"},
    "看怎么接上": {"en": "See how to connect", "de": "So verbinden",
              "es": "Ver cómo conectarlo", "fr": "Voir comment brancher",
              "ja": "接続方法を見る", "ko": "연결 방법 보기"},
    "看现场": {"en": "See the session", "de": "Sitzung ansehen",
           "es": "Ver la sesión", "fr": "Voir la session",
           "ja": "現場を見る", "ko": "현장 보기"},
    "第 ④ 格为什么是 0：你的助手还没从这里取过经验。接上之后每次开工它先带着"
    "这些教训，你不用重复交代。": {
        "en": "Why step ④ is 0: your assistant hasn’t pulled anything from here yet. "
             "Once connected, it starts each job with these lessons so you stop "
             "repeating yourself.",
        "de": "Warum Feld ④ 0 ist: Ihr Assistent hat hier noch nichts abgeholt. Ist "
             "er verbunden, startet er jede Aufgabe mit diesen Lehren – Sie müssen "
             "sich nicht wiederholen.",
        "es": "Por qué el paso ④ es 0: tu asistente aún no ha tomado nada de aquí. "
             "Cuando lo conectes, empezará cada tarea con estas lecciones y dejarás "
             "de repetirlo.",
        "fr": "Pourquoi la case ④ vaut 0 : votre assistant n’a encore rien puisé ici. "
             "Une fois branché, il démarrera chaque tâche avec ces leçons — vous "
             "n’aurez plus à vous répéter",
        "ja": "④ が 0 な理由：エージェントはまだここから経験を取っていません。接続すれ"
             "ば作業開始時にこれらを持って臨むので、言い直しは要りません。",
        "ko": "④ 가 0 인 이유: 어시스턴트가 여기서 경험을 가져간 적이 없습니다. 연결하면 "
             "작업 시작 때 이 교훈을 들고 가서 다시 말하지 않아도 됩니다."},
    "第一件连上 AI 就自动补，后两件各点几下就行。已经自动做好的：把干过的活收"
    "进来（{n} 次）。": {
        "en": "The first fixes itself once an AI is connected; the other two are a "
             "few clicks. Already handled automatically: collecting your work ({n} runs).",
        "de": "Das Erste erledigt sich nach dem Verbinden automatisch; die anderen "
             "beiden sind ein paar Klicks. Läuft bereits: Ihre Aufgaben erfassen ({n} Mal).",
        "es": "Lo primero se solo al conectar la IA; los otros dos son unos clics. "
             "Ya automático: recoger tu trabajo ({n} veces).",
        "fr": "Le premier se règle dès qu’une IA est branchée ; les deux autres "
             "demandent quelques clics. Déjà automatique : la collecte de votre "
             "travail ({n} passages).",
        "ja": "1 つ目は AI をつなげば自動で埋まり、残り 2 つは数クリックです。すでに"
             "自動でできていること：作業の取り込み（{n} 回）。",
        "ko": "첫 번째는 AI 를 연결하면 자동으로 채워지고, 나머지 둘은 몇 번만 누르면 "
             "됩니다. 이미 자동인 것: 작업 수집 ({n}회)."},
    "等第 ④ 格跑起来，这里给同类任务的对比": {
        "en": "Once step ④ runs, this shows a like-for-like comparison",
        "de": "Sobald Feld ④ läuft, erscheint hier der Vergleich gleicher Aufgaben",
        "es": "Cuando el paso ④ arranque, aquí verás la comparación entre tareas iguales",
        "fr": "Quand la case ④ tournera, la comparaison s’affichera ici",
        "ja": "④ が回り始めると、ここに同種タスクの比較が出ます",
        "ko": "④ 가 돌기 시작하면 여기에 동일 작업 비교가 뜹니다"},
    "经验一次都没被带回给助手，降下来靠的是你自己反复交代": {
        "en": "No experience has been handed back yet — the drop came from you "
             "re-explaining things",
        "de": "Keine Erfahrung wurde zurückgegeben – der Rückgang kam daher, dass Sie "
             "es immer wieder erklärt haben",
        "es": "Ninguna experiencia se ha devuelto: bajó porque tú lo repetías",
        "fr": "Aucune expérience n’a été renvoyée — si ça baisse, c’est que vous "
             "répétez les consignes",
        "ja": "経験は一度も AI に返っていないので、下がったのはあなたが繰り返し伝えた "
             "おかげです",
        "ko": "경험이 한 번도 되돌려지지 않았으니, 떨어진 건 당신이 계속 설명한 덕입니다"},
    "经验已被助手取用 {n} 次，效果还要再攒样本": {
        "en": "Experiences were used {n} times; still need more samples to judge effect",
        "de": "Erfahrungen {n} Mal abgerufen; für die Wirkung fehlen noch Stichproben",
        "es": "Las experiencias se usaron {n} veces; faltan muestras para ver el efecto",
        "fr": "Les expériences ont servi {n} fois ; il faut plus d’exemples pour "
             "juger l’effet",
        "ja": "経験は {n} 回利用されました。効果判定にはもう少しサンプルが要ります",
        "ko": "경험이 {n}회 쓰였습니다. 효과를 보려면 표본이 더 필요합니다"},
    "经验飞轮转到哪一格了": {"en": "Where the experience flywheel stands",
                     "de": "Wo das Erfahrungsrad gerade steht",
                     "es": "En qué punto está el volante de experiencias",
                     "fr": "Où en est la roue des expériences",
                     "ja": "経験フライホイールはどこまで回ったか",
                     "ko": "경험 플라이휠이 어디까지 돌았나"},
    "覆盖 {a} – {b}": {"en": "Covers {a} – {b}", "de": "Zeitraum {a} – {b}",
                   "es": "Cubre {a} – {b}", "fr": "Période {a} – {b}",
                   "ja": "対象 {a} – {b}", "ko": "범위 {a} – {b}"},
    "让经验回到会话里": {"en": "Get experiences back into sessions",
                   "de": "Erfahrungen zurück in die Sitzungen",
                   "es": "Que las experiencias vuelvan a las sesiones",
                   "fr": "Ramener les expériences dans les sessions",
                   "ja": "経験をセッションに返す", "ko": "경험을 세션으로 되돌리기"},
    "讲人话": {"en": "Plain words", "de": "Klartext", "es": "En cristiano",
           "fr": "En clair", "ja": "かみくだく", "ko": "쉽게 설명"},
    "过程记录": {"en": "Process log", "de": "Verlaufsprotokoll",
            "es": "Registro del proceso", "fr": "Journal du déroulé",
            "ja": "経過記録", "ko": "경과 기록"},
    "返工 {e} 回/次 → {r} 回/次": {
        "en": "Rework {e} per task → {r} per task",
        "de": "Nacharbeit {e} → {r} pro Aufgabe",
        "es": "Rehacer {e} → {r} por tarea",
        "fr": "Retouches {e} → {r} par tâche",
        "ja": "手戻り {e} 回/件 → {r} 回/件",
        "ko": "재작업 {e}회/건 → {r}회/건"},
    "返工确实少了：最早每次任务平均纠正 {e} 回，最近 {r} 回。": {
        "en": "Rework really dropped: from {e} corrections per task at first to {r} recently.",
        "de": "Nacharbeit sinkt tatsächlich: von zuerst {e} Korrekturen pro Aufgabe "
             "auf zuletzt {r}.",
        "es": "El rehacer baja de verdad: de {e} correcciones por tarea al principio "
             "a {r} ahora.",
        "fr": "Les retouches baissent vraiment : de {e} corrections par tâche au "
             "début à {r} récemment.",
        "ja": "手戻りは確かに減りました：当初は 1 件 {e} 回、直近は {r} 回。",
        "ko": "재작업이 실제로 줄었습니다: 처음엔 건당 {e}회, 최근엔 {r}회."},
    "还在攒样本": {"en": "Still collecting samples", "de": "Proben sammeln sich noch",
              "es": "Aún juntando muestras", "fr": "Échantillons en cours",
              "ja": "サンプル集め中", "ko": "표본 모으는 중"},
    "还在攒样本：同类任务多做几次，这里就能告诉你返工有没有变少。": {
        "en": "Still collecting samples: do a few more like tasks and this will tell "
             "you whether rework is dropping.",
        "de": "Proben sammeln sich noch: Erledigen Sie einige ähnliche Aufgaben, dann "
             "zeigt sich hier, ob die Nacharbeit sinkt.",
        "es": "Aún juntando muestras: haz unas cuantas tareas iguales y aquí verás si "
             "el rehacer baja.",
        "fr": "Échantillons en cours : faites quelques tâches semblables et vous "
             "saurez ici si les retouches baissent.",
        "ja": "サンプルをためています。同種の作業をもう少しすれば、手戻りが減ったか "
             "わかります。",
        "ko": "표본을 모으는 중입니다. 같은 작업을 몇 번 더 하면 재작업이 줄었는지 "
             "알 수 있습니다."},
    "还差这三件，才能给你看证据": {
        "en": "Three things still missing before we can show proof",
        "de": "Drei Punkte fehlen noch, bis wir Belege zeigen können",
        "es": "Faltan tres cosas para poder enseñar pruebas",
        "fr": "Il manque trois choses avant de pouvoir montrer des preuves",
        "ja": "証拠をお見せするにはあと 3 つ必要です",
        "ko": "증거를 보이려면 세 가지가 더 필요합니다"},
    "还没接到你的助手会话里 —— 当前最该修的一环": {
        "en": "Not wired into your assistant sessions yet — the link to fix first",
        "de": "Noch nicht mit Ihren Assistentensitzungen verbunden – das zuerst zu "
             "behebende Glied",
        "es": "Aún no conectado a tus sesiones; es el eslabón a arreglar primero",
        "fr": "Pas encore branché sur vos sessions — le maillon à réparer d’abord",
        "ja": "まだエージェントのセッションに接続されていません——今一番直す場所です",
        "ko": "아직 어시스턴트 세션에 연결 안 됨 — 지금 고칠 우선순위입니다"},
    "这 {n} 条不是你的教训，是它自己手滑，你不用管": {
        "en": "These {n} aren’t your lessons — the assistant slipped; leave them to it",
        "de": "Diese {n} sind nicht Ihre Lehren – der Assistent rutschte ab, darum "
             "müssen Sie sich nicht kümmern",
        "es": "Estas {n} no son tus lecciones: el asistente resbaló, no te ocupes",
        "fr": "Ces {n} ne sont pas vos leçons — l’assistant a glissé, laissez-le faire",
        "ja": "この {n} 件はあなたの教訓ではなく、エージェントのミスです。お任せください",
        "ko": "이 {n}건은 당신의 교훈이 아니라 어시스턴트의 실수입니다. 신경 쓰지 마세요"},
    "这一周没有记录": {"en": "No records this week", "de": "Keine Daten in dieser Woche",
                 "es": "Sin registros esta semana", "fr": "Aucun relevé cette semaine",
                 "ja": "この週は記録なし", "ko": "이번 주 기록 없음"},
    "这些经验已被助手取用": {"en": "The assistant has used these",
                     "de": "Diese wurden bereits abgerufen",
                     "es": "El asistente ya las usó", "fr": "L’assistant les a utilisées",
                     "ja": "この経験はすでに利用済み", "ko": "이 경험은 이미 쓰였습니다"},
    "这条经验没记下来源会话": {
        "en": "This experience has no source session recorded",
        "de": "Für diese Erfahrung ist keine Quellensitzung gespeichert",
        "es": "Esta experiencia no tiene sesión de origen",
        "fr": "Aucune session source n’est enregistrée pour cette expérience",
        "ja": "この経験には元になったセッションが記録されていません",
        "ko": "이 경험에는 출처 세션이 남아 있지 않습니다"},
    "这段时间经验被带回给助手 {n} 次。": {
        "en": "Experiences were handed back {n} times in this period.",
        "de": "In diesem Zeitraum wurden Erfahrungen {n} Mal zurückgegeben.",
        "es": "En este periodo se devolvieron experiencias {n} veces.",
        "fr": "Sur cette période, les expériences ont été renvoyées {n} fois.",
        "ja": "この期間、経験は {n} 回 AI に返されました。",
        "ko": "이 기간 동안 경험이 {n}회 되돌려졌습니다."},
    "阶段结论 · 自动生成": {"en": "Stage summary · auto-generated",
                    "de": "Phasenbilanz · automatisch erstellt",
                    "es": "Resumen de etapa · automático",
                    "fr": "Bilan d’étape · généré automatiquement",
                    "ja": "段階まとめ · 自動生成", "ko": "단계 요약 · 자동 생성"},
    # ---------- 以下四串经 _AGENT_STATE 变量传入 t()，AST 护栏抓不到，手工登记 ----------
    "明显变顺": {"en": "Clearly smoother", "de": "Deutlich glatter",
             "es": "Claramente más fluido", "fr": "Nettement plus fluide",
             "ja": "明らかにスムーズに", "ko": "확실히 부드러워짐"},
    "暂无明显变化": {"en": "No clear change yet", "de": "Noch keine klare Änderung",
                "es": "Sin cambio claro todavía", "fr": "Pas encore de changement net",
                "ja": "目立った変化なし", "ko": "뚜렷한 변화 없음"},
}


def main() -> int:
    check_entries(E)
    apply_entries(E)
    return 0


if __name__ == "__main__":
    sys.exit(main())
