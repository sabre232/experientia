# -*- coding: utf-8 -*-
"""一次性补齐脚本：把经验链路修复新增的界面词条补进 7 语 .po（已存在则跳过）。

用法：uv run python scripts/i18n_add_entries.py
补完后照旧跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=tú、fr=撇号 ’、ko=합니다체+''、非 CJK 禁全角括号（ja 除外）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "app" / "gui" / "locales"
LANGS = ["de", "en", "es", "fr", "ja", "ko", "zh"]

# msgid: {lang: msgstr}（zh = 恒等映射，脚本自动补 msgid）
E: dict[str, dict[str, str]] = {
    "花费估算·美元": {"en": "Est. spend · USD", "de": "Kosten (Schätzung) · USD",
                  "es": "Gasto estimado · USD", "fr": "Dépense est. · USD",
                  "ja": "推定費用・USD", "ko": "추정 비용·USD"},
    "AI 干过·场": {"en": "AI sessions · runs", "de": "KI-Sitzungen · Anzahl",
                "es": "Sesiones de IA · nº", "fr": "Sessions IA · nb",
                "ja": "AIセッション・回", "ko": "AI 세션·회"},
    "协作轮次·轮": {"en": "Collab rounds · turns", "de": "Runden · Anzahl",
                "es": "Rondas de trabajo · nº", "fr": "Échanges · nb",
                "ja": "協作ターン・数", "ko": "협업 순서·회"},
    "记下的坑·个": {"en": "Pitfalls logged · count", "de": "Notierte Fallstricke · Anzahl",
                "es": "Errores anotados · nº", "fr": "Pièges relevés · nb",
                "ja": "記録した落とし穴・件", "ko": "기록된 함정·개"},
    "怎么用": {"en": "How to use", "de": "So funktioniert’s", "es": "Cómo usarlo",
             "fr": "Comment utiliser", "ja": "使い方", "ko": "사용 방법"},
    ("去让任意 AI 工具干个活，它的操作会自动出现在这里——花多少钱、踩了什么坑，"
     "一目了然"): {
        "en": ("Let any AI tool do a task — its activity lands here automatically: "
               "what it cost and where it tripped, at a glance."),
        "de": ("Lassen Sie ein KI-Werkzeug eine Aufgabe erledigen – die Aktivitäten "
               "erscheinen hier automatisch: auf einen Blick, was es kostet und "
               "worüber es stolpert."),
        "es": ("Deje que cualquier herramienta de IA haga una tarea: su actividad "
               "aparecerá aquí sola; verá de un vistazo cuánto costó y en qué falló."),
        "fr": ("Faites travailler un outil IA : son activité s’affiche ici "
               "automatiquement — le coût et les obstacles, en un coup d’œil."),
        "ja": ("AI ツールに作業させれば、その動作は自動でここに集まります——いくら掛かり、"
               "どこで躓いたかが一目で分かります"),
        "ko": ("AI 도구에 작업을 시키면 동작이 자동으로 이곳에 쌓립니다—얼마가 들었고 "
               "어디서 막혔는지 한눈에 보입니다"),
    },
    "刚发现的坑": {"en": "Freshly found pitfalls", "de": "Frisch erkannte Fallstricke",
                "es": "Errores recién detectados", "fr": "Pièges tout juste repérés",
                "ja": "見つけたばかりの落とし穴", "ko": "방금 발견한 함정"},
    ("从你的 AI 工作记录里直接看出来的，不接模型也在记"): {
        "en": "Read straight from your AI work logs — recorded even without a model",
        "de": "Direkt aus Ihren KI-Arbeitsprotokollen abgelesen – auch ohne "
             "Modellverbindung erfasst",
        "es": "Detectado directamente de sus registros de IA: se anota incluso sin modelo",
        "fr": "Déduit directement de vos journaux IA — consigné même sans modèle connecté",
        "ja": "AI の作業記録からそのまま拾ったもの——モデル未接続でも記録しています",
        "ko": "AI 작업 기록에서 바로 뽑아낸 것—모델을 연결하지 않아도 기록됩니다",
    },
    "接上 AI 后解锁": {"en": "Unlocks once an AI is connected",
                   "de": "Wird freigeschaltet, wenn eine KI verbunden ist",
                   "es": "Se desbloquea al conectar una IA",
                   "fr": "Débloqué une fois une IA connectée",
                   "ja": "AI を接続すると解放", "ko": "AI를 연결하면 해제됩니다"},
    ("把踩过的坑自动整理成方法 · 让 AI 重写总结 · 深度复盘每次协作"): {
        "en": ("Auto-organize pitfalls into methods · AI rewrites summaries · "
               "deep review of every session"),
        "de": ("Fallstricke automatisch zu Methoden ordnen · die KI fasst "
               "Zusammenfassungen neu zusammen · jede Sitzung tiefgehend aufarbeiten"),
        "es": ("Organiza los errores en métodos automáticamente · la IA reescribe "
               "los resúmenes · repasa a fondo cada sesión"),
        "fr": ("Range automatiquement les pièges en méthodes · l’IA réécrit les "
               "résumés · revue approfondie de chaque session"),
        "ja": ("踏んだ落とし穴を自動で方法に整理 · AI が要約を書き直し · 毎回のコラボを深く振り返り"),
        "ko": "함정을 자동으로 방법으로 정리·AI가 요약을 다시 씀·매 협업의 심층 복기",
    },
    "去接一个": {"en": "Connect one", "de": "Jetzt verbinden", "es": "Conectar uno",
              "fr": "En connecter un", "ja": "接続する", "ko": "연결하기"},
    "已攒下 {n} 条待提炼片段，接上模型自动整理": {
        "en": "{n} raw fragments saved — they’ll be distilled automatically once a model is connected",
        "de": "{n} Roh-Schnipsel gesammelt – nach dem Verbinden eines Modells automatisch aufbereitet",
        "es": "Hay {n} fragmentos pendientes: se destilarán solos al conectar un modelo",
        "fr": "{n} fragments bruts collectés — distillés automatiquement dès qu’un modèle sera connecté",
        "ja": "未抽出の断片が {n} 件たまっています——モデルを接続すると自動で整理されます",
        "ko": "정제 전 조각 {n}개 대기—모델을 연결하면 자동으로 정리됩니다"},
    "接上后开始积累待提炼片段": {
        "en": "Raw fragments start collecting once a model is connected",
        "de": "Roh-Schnipsel sammeln sich, sobald ein Modell verbunden ist",
        "es": "Los fragmentos se acumularán en cuanto conecte un modelo",
        "fr": "Les fragments s’accumuleront dès qu’un modèle sera connecté",
        "ja": "接続後、未抽出の断片がたまり始めます",
        "ko": "연결 후 정제 전 조각이 쌓이기 시작합니다"},
    "命令连败后修好": {"en": "Command fixed after repeated failures",
                  "de": "Befehl nach Fehler-Serie korrigiert",
                  "es": "Comando corregido tras varios fallos",
                  "fr": "Commande corrigée après échecs répétés",
                  "ja": "コマンド連続失敗後に修正", "ko": "명령 반복 실패 후 해결"},
    "反复出现的报错": {"en": "Recurring error", "de": "Wiederkehrender Fehler",
                  "es": "Error recurrente", "fr": "Erreur récurrente",
                  "ja": "繰り返し出るエラー", "ko": "반복 발생하는 오류"},
    "改动被推翻": {"en": "Change reverted", "de": "Änderung rückgängig gemacht",
               "es": "Cambio revertido", "fr": "Modification annulée",
               "ja": "変更が取り消された", "ko": "변경이 되돌려짐"},
    "路径落空转好": {"en": "Path miss resolved via scan", "de": "Pfad verfehlt, per Scan gelöst",
                 "es": "Ruta no hallada; resuelta por escaneo",
                 "fr": "Chemin introuvable, retrouvé par scan",
                 "ja": "パス不一致をスキャンで回収", "ko": "경로를 놓쳤으나 스캔으로 찾음"},
    "坑": {"en": "Pitfall", "de": "Fallstrick", "es": "Trampa", "fr": "Piège",
          "ja": "落とし穴", "ko": "함정"},
    "复现 {n} 次": {"en": "reproduced {n} times", "de": "{n}-mal reproduziert",
                 "es": "reproducido {n} veces", "fr": "reproduit {n} fois",
                 "ja": "{n} 回再現", "ko": "{n}회 재현"},
    "查看会话": {"en": "View session", "de": "Sitzung ansehen", "es": "Ver sesión",
              "fr": "Voir la session", "ja": "セッションを見る", "ko": "세션 보기"},
    "读取会话失败：{err}": {"en": "Failed to read session: {err}",
                       "de": "Sitzung konnte nicht gelesen werden: {err}",
                       "es": "No se pudo leer la sesión: {err}",
                       "fr": "Échec de lecture de la session : {err}",
                       "ja": "セッションの読み込みに失敗：{err}",
                       "ko": "세션 읽기 실패: {err}"},
    "未提炼片段": {"en": "Raw fragments", "de": "Unaufbereitete Schnipsel",
               "es": "Fragmentos sin destilar", "fr": "Fragments bruts",
               "ja": "未抽出の断片", "ko": "정제 전 조각"},
    ("这些是 AI 被你说「不对」时的原文片段——只是现场证据，不是经验，"
     "永远不会被带进 AI 的工作里；接上模型后会自动整理成经验"): {
        "en": ("These are the exact words from moments when you told the AI “no” — "
               "evidence, not experience; they never enter the AI’s context. Once a "
               "model is connected, they’ll be distilled automatically."),
        "de": ("Das sind Originalstellen, an denen Sie der KI widersprochen haben – "
               "Beweismaterial, keine Erfahrung; sie werden nie in den KI-Kontext "
               "übernommen. Nach dem Verbinden eines Modells werden sie automatisch "
               "zu Erfahrungen aufbereitet."),
        "es": ("Son fragmentos literales de cuando le dijo «no» a la IA: evidencia, "
               "no experiencia; nunca entrarán en el contexto de la IA. Al conectar un "
               "modelo se destilarán solos."),
        "fr": ("Ce sont des passages littéraux où vous avez dit « non » à l’IA — une "
               "preuve, pas une expérience ; ils n’entreront jamais dans son contexte. "
               "Connectez un modèle et ils seront distillés automatiquement."),
        "ja": ("これは AI に「違う」と言った瞬間の原文片段です——証拠であって経験では"
               "なく、AI の作業に使われることは絶対にありません。モデルを接続すると"
               "自動で経験に整理されます。"),
        "ko": ("AI에게 “아니야”라고 했던 순간의 원문 조각입니다—경험이 아닌 증거이며, "
               "AI 작업에 절대 들어가지 않습니다. 모델을 연결하면 자동으로 경험으로 "
               "정리됩니다."),
    },
    ("去让任意 agent 干个活——反复失败又修好、报错再三出现，都会自动变成坑卡落在这里"): {
        "en": ("Let an agent do some work — failures that were fixed on retry and "
               "recurring errors automatically become pitfall cards here."),
        "de": ("Lassen Sie einen Agenten arbeiten – wiederholte, später behobene "
               "Fehler und Dauerfehler werden hier automatisch zu Fallstrick-Karten."),
        "es": ("Deje que un agente trabaje: fallos que acabaron resueltos y errores "
               "recurrentes se convierten aquí automáticamente en fichas."),
        "fr": ("Faites travailler un agent — échecs résolus après retries et erreurs "
               "récurrentes deviennent ici automatiquement des fiches de pièges."),
        "ja": ("agent に手を動かさせましょう——繰り返して失敗し直ったもの、再三出る"
               "エラーは自動で落とし穴カードになります。"),
        "ko": ("agent에게 일을 맡겨보세요—반복 실패 끝에 고쳐진 것, 계속 나타나는 오류가 "
               "자동으로 함정 카드가 됩니다."),
    },
    "……还有 {n} 条，接上模型后会自动整理": {
        "en": "…plus {n} more — distilled automatically once a model is connected",
        "de": "…weitere {n} – nach Modellverbindung automatisch aufbereitet",
        "es": "…y {n} más: se destilarán solos al conectar un modelo",
        "fr": "…encore {n} — distillés automatiquement après connexion d’un modèle",
        "ja": "……さらに {n} 件、モデル接続後に自動で整理",
        "ko": "…{n}건 더—모델 연결 후 자동 정리"},
    "从操作记录里直接看出来的坑（自动总结成方法后会更精炼）": {
        "en": ("Pitfalls read straight from the logs (they get sharper once auto-"
               "summarized into methods)"),
        "de": ("Direkt aus den Protokollen abgelesene Fallstricke (nach dem "
               "automatischen Zusammenfassen zu Methoden werden sie präziser)"),
        "es": ("Errores leídos directamente de los registros (se afinan al "
               "resumirse automáticamente en métodos)"),
        "fr": ("Pièges lus directement dans les journaux (ils s’affinent une fois "
               "résumés automatiquement en méthodes)"),
        "ja": ("操作記録からそのまま読み取った落とし穴（自動で方法にまとめるとさらに洗練されます）"),
        "ko": "작업 기록에서 바로 뽑은 함정(방법으로 자동 요약하면 더 정제됩니다)"},
    "让 agent 干点活——反复失败、报错再三出现，都会自动记在这里": {
        "en": "Give an agent some work — repeated failures and recurring errors get logged here automatically",
        "de": "Geben Sie einem Agenten Arbeit – wiederholte Fehler und Dauerfehler werden hier automatisch notiert",
        "es": "Encargue trabajo al agente: fallos repetidos y errores recurrentes se anotan aquí solos",
        "fr": "Donnez du travail à l’agent — échecs répétés et erreurs récurrentes s’inscrivent ici automatiquement",
        "ja": "agent に手を動かさせれば——繰り返し失敗や再三のエラーは自動でここに記録されます",
        "ko": "agent에게 일을 맡기세요—반복 실패와 지속 오류가 자동으로 이곳에 기록됩니다"},
    "总结成方法：建议先接上 AI": {
        "en": "Summarize into methods: connect an AI first (recommended)",
        "de": "Zu Methoden zusammenfassen: vorher eine KI verbinden (empfohlen)",
        "es": "Resumir en métodos: conviene conectar antes la IA",
        "fr": "Résumer en méthodes : connectez d’abord une IA",
        "ja": "方法にまとめる：先に AI の接続を推奨",
        "ko": "방법으로 요약: AI 연결을 먼저 권장"},
    ("不接模型也能用「快速整理（本机完成）」：把记录里看出来的坑（反复报错、改好才通过、"
     "改动被推翻）直接列成方法卡。\n但把经验归纳成做法、把话理顺，需要 AI——接一个本地模型或 "
     "API 都行，接好后同样的按钮就是「AI 深度整理」。\n建议先去「接入」页接模型；"
     "仍想现在就快速整理，点「确认」。"): {
        "en": ("Without a model, Quick tidy (done locally) still works: it lays out "
               "the pitfalls seen in the logs (recurring errors, passed-only-after-"
               "retries, reverted changes) as method cards.\nDistilling experience "
               "into reusable methods and polishing wording needs AI — connect a "
               "local model or an API, and this same button becomes AI deep tidy.\n"
               "Better: connect a model on the Connect page first; to run the quick "
               "tidy now anyway, press Confirm."),
        "de": ("Ohne Modell können Sie die „Schnellordnung (lokal)“ nutzen: Sie "
               "listet die in den Protokollen sichtbaren Fallstricke (Dauerfehler, "
               "nach erneutem Versuch behobene, rückgängig gemachte Änderungen) als "
               "Methodenkarten auf.\nErfahrung zu Vorgehensweisen zu verdichten und "
               "Formulierungen zu glätten braucht jedoch eine KI – verbinden Sie ein "
               "lokales Modell oder eine API, dann wird derselbe Knopf zur „KI-"
               "Tiefenordnung“.\nEmpfehlung: verbinden Sie zuerst auf der Seite "
               "„Anbindung“ ein Modell. Möchten Sie jetzt schnell ordnen, klicken "
               "Sie auf „Bestätigen“."),
        "es": ("Sin modelo puede usar «Orden rápido (en local)»: lista en fichas los "
               "errores vistos en el registro (fallos que se repiten, resueltos al "
               "reintentar, cambios revertidos).\nPero convertir la experiencia en "
               "métodos reutilizables y pulir el texto requiere IA: conecte un modelo "
               "local o una API y el mismo botón pasará a «Orden profundo con IA».\n"
               "Conviene conectar antes un modelo en la página «Conexión»; si quiere "
               "el orden rápido ya, pulse Confirmar."),
        "fr": ("Sans modèle, « Tri rapide (local) » reste disponible : il pose en "
               "fiches les pièges vus dans les journaux (erreurs récurrentes, "
               "corrections après retries, modifications annulées).\nMais transformer "
               "l’expérience en méthodes réutilisables et soigner les formulations "
               "demande une IA — connectez un modèle local ou une API, et ce même "
               "bouton devient « Tri approfondi par IA ».\nConnectez d’abord un "
               "modèle sur la page « Connexion » ; pour un tri rapide maintenant, "
               "cliquez sur Confirmer."),
        "ja": ("モデル未接続でも「クイック整理（ローカル完結）」が使えます：記録から"
               "見える落とし穴（繰り返しエラー・再試行後に通った・変更が取り消された）を"
               "方法カードに並べます。\nただし経験をやり方に汎化し言葉を整えるのは AI の"
               "領分です——ローカルモデルか API を接続すると、同じボタンが「AI 深度整理」に"
               "なります。\nまずは「接続」ページでのモデル接続を推奨；今すぐクイック整理する"
               "なら「確認」を押してください。"),
        "ko": ("모델 없이도 “빠른 정리(로컬 완료)”를 쓸 수 있습니다—기록에서 드러나는 "
               "함정(반복 오류, 재시도 후 통과, 되돌려진 변경)을 방법 카드로 늘어놓습니다.\n"
               "다만 경험을 방법으로 일반화하고 문장을 다듬는 건 AI 영역입니다—로컬 모델이나 "
               "API를 연결하면 같은 버튼이 “AI 심층 정리”가 됩니다.\n「연결」페이지에서 모델을 "
               "먼저 권장합니다; 지금 빠른 정리를 원하시면 「확인」을 누르세요."),
    },
    ("还没接入模型：去「接入」页接一个，AI 就能帮你把规则翻译成大白话"): {
        "en": ("No model yet: connect one on the Connect page, and the AI can "
               "translate rules into plain words for you"),
        "de": ("Noch kein Modell verbunden: Auf der Seite „Anbindung“ verbinden Sie "
               "eines, dann übersetzt die KI Regeln für Sie in klare Worte"),
        "es": ("Aún no hay modelo: conecte uno en la página «Conexión» y la IA "
               "traducirá las reglas a un lenguaje claro"),
        "fr": ("Pas encore de modèle : connectez-en un sur la page « Connexion » et "
               "l’IA traduira les règles en langage clair"),
        "ja": "モデル未接続です：「接続」ページで一つ繋ぐと、AI がルールをやさしい言葉に翻訳します",
        "ko": "아직 모델이 없습니다:「연결」페이지에서 연결하면 AI가 규칙을 쉬운 말로 옮겨 줍니다"},
    "会话现场 · {agent} {sid}": {
        "en": "Session scene · {agent} {sid}", "de": "Sitzungsszene · {agent} {sid}",
        "es": "Escena de sesión · {agent} {sid}", "fr": "Scène de session · {agent} {sid}",
        "ja": "セッション現場 · {agent} {sid}", "ko": "세션 현장 · {agent} {sid}"},
    "你说": {"en": "You said", "de": "Sie sagten", "es": "Usted dijo",
            "fr": "Vous avez dit", "ja": "あなたの発言", "ko": "내가 말한 것"},
    "AI 答": {"en": "AI replied", "de": "KI-Antwort", "es": "Respuesta de la IA",
             "fr": "Réponse de l’IA", "ja": "AI の回答", "ko": "AI 답"},
    "操作时间线": {"en": "Action timeline", "de": "Aktionszeitlinie",
               "es": "Cronología de acciones", "fr": "Chronologie des actions",
               "ja": "操作タイムライン", "ko": "작업 타임라인"},
    "这个会话没有留下可展示的现场记录": {
        "en": "This session left no displayable record",
        "de": "Diese Sitzung hinterließ keine anzeigbaren Protokolle",
        "es": "Esta sesión no dejó registros mostrables",
        "fr": "Cette session n’a laissé aucun enregistrement affichable",
        "ja": "このセッションには表示できる現場記録が残っていません",
        "ko": "이 세션에는 보여 줄 현장 기록이 남아 있지 않습니다"},
    "{n} 轮": {"en": "{n} rounds", "de": "{n} Runden", "es": "{n} rondas",
             "fr": "{n} échanges", "ja": "{n} ターン", "ko": "{n}회"},
    "纠正 {n} 次": {"en": "corrected {n} times", "de": "{n}-mal korrigiert",
                 "es": "corregido {n} veces", "fr": "corrigé {n} fois",
                 "ja": "修正 {n} 回", "ko": "교정 {n}회"},
    "搜历史会话：报错、命令、项目…": {
        "en": "Search past sessions: errors, commands, projects…",
        "de": "Frühere Sitzungen durchsuchen: Fehler, Befehle, Projekte…",
        "es": "Busque en sesiones anteriores: errores, comandos, proyectos…",
        "fr": "Rechercher dans les sessions passées : erreurs, commandes, projets…",
        "ja": "過去のセッションを検索：エラー・コマンド・プロジェクト…",
        "ko": "이전 세션 검색: 오류, 명령, 프로젝트…"},
    "搜索结果": {"en": "Search results", "de": "Suchergebnisse",
              "es": "Resultados de búsqueda", "fr": "Résultats de recherche",
              "ja": "検索結果", "ko": "검색 결과"},
    "正在搜索…": {"en": "Searching…", "de": "Suche läuft…",
               "es": "Buscando…", "fr": "Recherche en cours…",
               "ja": "検索中…", "ko": "검색 중…"},
    "搜索失败：{err}": {"en": "Search failed: {err}",
                  "de": "Suche fehlgeschlagen: {err}",
                  "es": "Error al buscar: {err}",
                  "fr": "Échec de la recherche : {err}",
                  "ja": "検索に失敗：{err}", "ko": "검색 실패: {err}"},
    "搜索结果：{q}": {"en": "Search results: {q}",
                 "de": "Suchergebnisse: {q}",
                 "es": "Resultados de búsqueda: {q}",
                 "fr": "Résultats de recherche : {q}",
                 "ja": "検索結果：{q}", "ko": "검색 결과: {q}"},
    "打开": {"en": "Open", "de": "Öffnen", "es": "Abrir",
             "fr": "Ouvrir", "ja": "開く", "ko": "열기"},
    "没有找到「{q}」——换个词试试，报错原文里的词最准": {
        "en": "Nothing found for “{q}” — try other words; terms from the "
             "error text work best",
        "de": "Keine Treffer für „{q}“ – andere Wörter probieren; Begriffe "
             "aus der Fehlermeldung treffen am besten",
        "es": "No se encontró «{q}»: pruebe otras palabras; las del texto "
             "del error funcionan mejor",
        "fr": "Rien pour « {q} » — essayez d’autres mots ; ceux du texte "
             "d’erreur sont les plus efficaces",
        "ja": "「{q}」は見つかりませんでした——別の語を試してください。"
             "エラー原文の語が最も当たりやすいです",
        "ko": "“{q}”에 대한 결과가 없습니다—다른 단어를 시도해 보세요. "
             "오류 원문의 단어가 가장 잘 맞습니다"},
}


def main() -> int:
    added_total = 0
    for lang in LANGS:
        po = LOCALES / lang / "LC_MESSAGES" / "messages.po"
        if not po.exists():
            print(f"缺少 {po}")
            continue
        with po.open("rb") as fh:
            catalog = read_po(fh, locale=lang)
        added = 0
        for msgid, table in E.items():
            msgid = str(msgid)
            if msgid in catalog:
                continue
            if lang == "zh":
                text = msgid
            else:
                text = table.get(lang)
                if not text:
                    print(f"[{lang}] 缺译文: {msgid[:24]}…")
                    continue
            flags = ["python-format"] if "{" in msgid else []
            catalog.add(msgid, text, flags=flags)
            added += 1
        if added:
            with po.open("wb") as fh:  # 字节写：防 Windows 换行二次转换（.po LF 铁律）
                write_po(fh, catalog, width=0)
        print(f"[{lang}] 新增 {added} 条")
        added_total += added
    print(f"合计 {added_total} 条——记得跑 scripts/compile_locales.py 重编译 .mo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
