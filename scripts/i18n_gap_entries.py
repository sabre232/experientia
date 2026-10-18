# -*- coding: utf-8 -*-
"""补齐「波 1 跨 WS 缺口」的 45 条词条到 7 语 .po。

背景：波 1 各 WS 新增的 t("…") 调用未进 .po/.mo（locales 在波 1 冻结，
属跨波共同债），tests/test_i18n.py::test_every_t_key_translated_in_all_catalogs
因此长红。本脚本一次性补齐；跑完必须 scripts/compile_locales.py 重编译 .mo。

语体规范同 i18n_rebuild_entries.py：de=Sie+„“、es=tú+«»、fr=’+«»、
ko=합니다체+''（半角括号）、ja=「」+全角括号；非 CJK 禁全角括号与残留汉字
（脚本自检）。

用法：uv run --with babel python scripts/i18n_wave1_gap_entries.py
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
    # ---------- 模型门禁 / 接入状态（app/gui/page_base.py、models_page.py） ----------
    "AI 重写": {"en": "AI rewrite", "de": "KI-Umschreibung",
              "es": "Reescritura con IA", "fr": "Réécriture par IA",
              "ja": "AI 書き直し", "ko": "AI 다시 쓰기"},
    "{action}需要先接一个模型（本地模型或 API 都行）。现在去「接入」页配置吗？": {
        "en": "{action} needs a model first (a local model or an API both "
              "work). Go to the “Connect” page to set it up now?",
        "de": "{action} benötigt zuerst ein Modell (ein lokales Modell oder "
              "eine API ist beides möglich). Jetzt auf der Seite „Anbindung“ "
              "einrichten?",
        "es": "{action} necesita antes un modelo (sirve un modelo local o una "
              "API). ¿Ir ahora a la página «Conexión» para configurarlo?",
        "fr": "{action} nécessite d’abord un modèle (un modèle local ou une "
              "API convient). Aller maintenant sur la page « Connexion » pour "
              "le configurer ?",
        "ja": "{action}には先にモデルが必要です（ローカルモデルでも API でも"
              "構いません）。今すぐ「接続」ページで設定しますか？",
        "ko": "{action}에는 먼저 모델이 필요합니다(로컬 모델이나 API 모두 "
              "가능). 지금 '연결' 페이지에서 설정하시겠습니까?"},
    "未接入模型": {"en": "No model connected", "de": "Kein Modell verbunden",
               "es": "Sin modelo conectado", "fr": "Aucun modèle connecté",
               "ja": "モデル未接続", "ko": "모델 미연결"},
    "未接入模型，无法完成这一步": {
        "en": "No model connected — this step can’t be completed",
        "de": "Kein Modell verbunden – dieser Schritt kann nicht abgeschlossen "
              "werden",
        "es": "Sin modelo conectado: no se puede completar este paso",
        "fr": "Aucun modèle connecté — impossible de terminer cette étape",
        "ja": "モデル未接続のため、この手順を完了できません",
        "ko": "모델 미연결이라 이 단계를 완료할 수 없습니다"},
    "未接入模型，无法归纳成方法": {
        "en": "No model connected — can’t distill into a method",
        "de": "Kein Modell verbunden – kann nicht zu einer Methode verdichtet "
              "werden",
        "es": "Sin modelo conectado: no se puede destilar en un método",
        "fr": "Aucun modèle connecté — impossible de synthétiser une méthode",
        "ja": "モデル未接続のため、方法にまとめられません",
        "ko": "모델 미연결이라 방법으로 정리할 수 없습니다"},
    "已接入 · 当前生效的模型路由：{name}（{endpoint}）": {
        "en": "Connected · Active model route: {name} ({endpoint})",
        "de": "Verbunden · Aktive Modellroute: {name} ({endpoint})",
        "es": "Conectado · Ruta de modelo activa: {name} ({endpoint})",
        "fr": "Connecté · Route de modèle active : {name} ({endpoint})",
        "ja": "接続済み · 現在有効なモデルルート：{name}（{endpoint}）",
        "ko": "연결됨 · 현재 적용 중인 모델 라우트: {name} ({endpoint})"},
    "接入模型用于归纳类内容（方法正文 / 成长叙事 / AI 重写）；"
    "不接也能用：经验照常记录，账本、坑卡、原始记录、搜索都在本机可用。": {
        "en": "A model powers summarized content (method text / growth "
              "narrative / AI rewrite); without one you can still work: "
              "experiences are recorded as usual, and the ledger, pitfall "
              "cards, original records and search all work on this machine.",
        "de": "Ein Modell wird für zusammenfassende Inhalte (Methodentext / "
              "Wachstumsnarrativ / KI-Umschreibung) genutzt; ohne es geht es "
              "weiter: Erfahrungen werden wie gewohnt erfasst, und "
              "Erfahrungskonto, Fallstrick-Karten, Ursprungseinträge und Suche "
              "funktionieren auf diesem Gerät.",
        "es": "Un modelo sirve para el contenido de síntesis (cuerpo del "
              "método / narrativa de crecimiento / reescritura con IA); sin él "
              "también puedes seguir: las experiencias se registran como "
              "siempre, y el libro, las tarjetas de errores, los registros "
              "originales y la búsqueda funcionan en este equipo.",
        "fr": "Un modèle sert au contenu de synthèse (corps de la méthode / "
              "récit de progression / réécriture par IA) ; sans lui, tout "
              "reste utilisable : les expériences sont enregistrées comme "
              "d’habitude, et le registre, les fiches pièges, les "
              "enregistrements bruts et la recherche fonctionnent sur cet "
              "appareil.",
        "ja": "モデルは帰納系の内容（方法本文 / 成長ナラティブ / AI 書き直し）に"
              "使われます。接続しなくても、経験はこれまで通り記録され、台帳・"
              "落とし穴カード・元の記録・検索はこの端末内で利用できます。",
        "ko": "모델은 요약형 콘텐츠(방법 본문 / 성장 서사 / AI 다시 쓰기)에 "
              "사용됩니다. 연결하지 않아도 경험은 그대로 기록되고, 장부·함정 "
              "카드·원본 기록·검색은 이 기기에서 모두 사용할 수 있습니다."},
    "未接入模型：归纳类内容（方法正文 / 成长叙事 / AI 重写）不可用；"
    "事实类内容（账本 / 坑卡 / 原始记录 / 搜索）本机完全可用": {
        "en": "No model connected: summarized content (method text / growth "
              "narrative / AI rewrite) is unavailable; factual content "
              "(ledger / pitfall cards / original records / search) is fully "
              "available on this machine",
        "de": "Kein Modell verbunden: zusammenfassende Inhalte (Methodentext / "
              "Wachstumsnarrativ / KI-Umschreibung) sind nicht verfügbar; "
              "faktische Inhalte (Erfahrungskonto / Fallstrick-Karten / "
              "Ursprungseinträge / Suche) sind auf diesem Gerät vollständig "
              "verfügbar",
        "es": "Sin modelo conectado: el contenido de síntesis (cuerpo del "
              "método / narrativa de crecimiento / reescritura con IA) no está "
              "disponible; el contenido fáctico (libro / tarjetas de errores / "
              "registros originales / búsqueda) sí está totalmente disponible "
              "en este equipo",
        "fr": "Aucun modèle connecté : le contenu de synthèse (corps de la "
              "méthode / récit de progression / réécriture par IA) est "
              "indisponible ; le contenu factuel (registre / fiches pièges / "
              "enregistrements bruts / recherche) reste entièrement "
              "disponible sur cet appareil",
        "ja": "モデル未接続：帰納系の内容（方法本文 / 成長ナラティブ / AI "
              "書き直し）は利用できません。事実系の内容（台帳 / 落とし穴カード "
              "/ 元の記録 / 検索）はこの端末内で完全に利用できます",
        "ko": "모델 미연결: 요약형 콘텐츠(방법 본문 / 성장 서사 / AI 다시 "
              "쓰기)는 사용할 수 없습니다. 사실형 콘텐츠(장부 / 함정 카드 / "
              "원본 기록 / 검색)는 이 기기에서 완전히 사용할 수 있습니다"},
    # ---------- 内容溯源条（app/gui/qt_theme.py、poster.py） ----------
    "未接入模型 · 内容为 {t} 生成 · 接入后可更新": {
        "en": "No model connected · Content generated at {t} · Connect to "
              "update",
        "de": "Kein Modell verbunden · Inhalt erzeugt am {t} · Nach dem "
              "Verbinden aktualisierbar",
        "es": "Sin modelo conectado · Contenido generado el {t} · Conéctate "
              "para actualizar",
        "fr": "Aucun modèle connecté · Contenu généré le {t} · Connectez-vous "
              "pour mettre à jour",
        "ja": "モデル未接続 · 内容は {t} に生成 · 接続後に更新できます",
        "ko": "모델 미연결 · 내용은 {t} 생성 · 연결 후 업데이트 가능"},
    "未接入模型 · 内容为上次生成 · 接入后可更新": {
        "en": "No model connected · Content from the last generation · "
              "Connect to update",
        "de": "Kein Modell verbunden · Inhalt aus der letzten Erzeugung · Nach "
              "dem Verbinden aktualisierbar",
        "es": "Sin modelo conectado · Contenido de la última generación · "
              "Conéctate para actualizar",
        "fr": "Aucun modèle connecté · Contenu de la dernière génération · "
              "Connectez-vous pour mettre à jour",
        "ja": "モデル未接続 · 内容は前回の生成 · 接続後に更新できます",
        "ko": "모델 미연결 · 내용은 이전 생성 · 연결 후 업데이트 가능"},
    # ---------- 经验库 / 详情抽屉（app/gui/experiences.py、qt_widgets.py） ----------
    "已保留上次内容": {"en": "Kept the previous content",
                 "de": "Vorherigen Inhalt beibehalten",
                 "es": "Se mantuvo el contenido anterior",
                 "fr": "Contenu précédent conservé",
                 "ja": "前回の内容を保持しました",
                 "ko": "이전 내용을 유지했습니다"},
    "查看这条经验的完整详情": {
        "en": "View the full details of this experience",
        "de": "Alle Details dieser Erfahrung ansehen",
        "es": "Ver todos los detalles de esta experiencia",
        "fr": "Voir tous les détails de cette expérience",
        "ja": "この経験の詳細をすべて見る",
        "ko": "이 경험의 전체 세부 정보 보기"},
    "任务记录": {"en": "Task record", "de": "Aufgabenaufzeichnung",
             "es": "Registro de tarea", "fr": "Enregistrement de tâche",
             "ja": "タスク記録", "ko": "작업 기록"},
    "暂无详情": {"en": "No details yet", "de": "Noch keine Details",
             "es": "Aún no hay detalles", "fr": "Pas encore de détails",
             "ja": "詳細はまだありません", "ko": "세부 정보 없음"},
    "来源经验：": {"en": "Source experiences: ",
              "de": "Quell-Erfahrungen: ",
              "es": "Experiencias de origen: ",
              "fr": "Expériences sources : ",
              "ja": "出典の経験：", "ko": "출처 경험: "},
    "记录来源：": {"en": "Recorded from: ", "de": "Aufgezeichnet von: ",
              "es": "Registrado desde: ", "fr": "Source d’enregistrement : ",
              "ja": "記録元：", "ko": "기록 출처: "},
    "时间轨迹：": {"en": "Timeline: ", "de": "Zeitverlauf: ",
              "es": "Cronología: ", "fr": "Chronologie : ",
              "ja": "時間の軌跡：", "ko": "시간 궤적: "},
    # ---------- 会话抽屉 / 导出页（app/gui/session_drawer.py、export_page.py） ----------
    "展开全文（还有 {n} 字）": {
        "en": "Show full text ({n} more characters)",
        "de": "Vollen Text anzeigen (noch {n} Zeichen)",
        "es": "Mostrar el texto completo ({n} caracteres más)",
        "fr": "Afficher le texte complet ({n} caractères de plus)",
        "ja": "全文を展開（残り {n} 文字）",
        "ko": "전체 보기(남은 {n}자)"},
    "正在读取…": {"en": "Reading…", "de": "Wird gelesen…",
              "es": "Leyendo…", "fr": "Lecture…",
              "ja": "読み込み中…", "ko": "읽는 중…"},
    # ---------- 成长页（app/gui/growth.py） ----------
    "你的经验按任务类型长出来": {
        "en": "Your experiences grow by task type",
        "de": "Ihre Erfahrungen wachsen nach Aufgabenart",
        "es": "Tus experiencias crecen por tipo de tarea",
        "fr": "Vos expériences grandissent par type de tâche",
        "ja": "あなたの経験はタスク種別ごとに育ちます",
        "ko": "경험은 작업 유형별로 자랍니다"},
    "这些是你收进来的活本身，跟模型通不通没关系": {
        "en": "This is the work you’ve collected — it has nothing to do with "
              "whether a model is connected",
        "de": "Das ist die Arbeit, die Sie erfasst haben – sie hat nichts "
              "damit zu tun, ob ein Modell verbunden ist",
        "es": "Esto es el trabajo que has recogido; no tiene nada que ver con "
              "si hay un modelo conectado",
        "fr": "C’est le travail que vous avez collecté ; cela n’a rien à voir "
              "avec la connexion d’un modèle",
        "ja": "これはあなたが収集した作業そのもので、モデルの接続状況とは関係"
              "ありません",
        "ko": "이것은 사용자가 수집한 작업 자체이며, 모델 연결 여부와는 관계가 "
              "없습니다"},
    "近 {n} 天每天收进多少条": {
        "en": "Entries collected each day over the last {n} days",
        "de": "Täglich erfasste Einträge der letzten {n} Tage",
        "es": "Entradas recogidas cada día en los últimos {n} días",
        "fr": "Entrées collectées chaque jour sur les {n} derniers jours",
        "ja": "直近 {n} 日の 1 日あたりの収集件数",
        "ko": "최근 {n}일간 하루 수집 건수"},
    "近 {n} 天活跃度": {"en": "Activity over the last {n} days",
                   "de": "Aktivität der letzten {n} Tage",
                   "es": "Actividad de los últimos {n} días",
                   "fr": "Activité des {n} derniers jours",
                   "ja": "直近 {n} 日の稼働度", "ko": "최근 {n}일 활동도"},
    "按任务类型攒下的条数": {
        "en": "Entries accumulated by task type",
        "de": "Nach Aufgabenart gesammelte Einträge",
        "es": "Entradas acumuladas por tipo de tarea",
        "fr": "Entrées accumulées par type de tâche",
        "ja": "タスク種別ごとに貯まった件数",
        "ko": "작업 유형별로 쌓인 건수"},
    "让 AI 讲人话": {"en": "Let AI explain in plain words",
                 "de": "KI in Klartext erklären lassen",
                 "es": "Que la IA lo explique en cristiano",
                 "fr": "Laisser l’IA expliquer en clair",
                 "ja": "AI にかみくだいてもらう",
                 "ko": "AI가 쉽게 설명하게 하기"},
    # ---------- 偏好 / 设置（app/gui/preferences_page.py、settings_page.py） ----------
    "偏好会在接入模型后，从你的纠正里归纳出来": {
        "en": "Preferences are induced from your corrections once a model is "
              "connected",
        "de": "Präferenzen werden aus Ihren Korrekturen abgeleitet, sobald ein "
              "Modell verbunden ist",
        "es": "Las preferencias se inducen de tus correcciones cuando conectes "
              "un modelo",
        "fr": "Les préférences sont induites à partir de vos corrections une "
              "fois un modèle connecté",
        "ja": "モデルを接続すると、あなたの修正から好みが帰納されます",
        "ko": "모델을 연결하면 사용자의 수정에서 선호가 유도됩니다"},
    "预览": {"en": "Preview", "de": "Vorschau", "es": "Vista previa",
           "fr": "Aperçu", "ja": "プレビュー", "ko": "미리보기"},
    "设置加载失败，稍后重试": {
        "en": "Couldn’t load settings, please try again later",
        "de": "Einstellungen konnten nicht geladen werden, bitte später "
              "erneut versuchen",
        "es": "No se pudieron cargar los ajustes, inténtalo de nuevo más tarde",
        "fr": "Échec du chargement des paramètres, réessayez plus tard",
        "ja": "設定の読み込みに失敗しました。しばらくして再試行してください",
        "ko": "설정을 불러오지 못했습니다. 나중에 다시 시도해 주세요"},
    # ---------- 首页双档 / 新手引导 / 协作页下钻（home.py、onboarding.py、
    # hooks_page.py）—— 落地晚于本脚本首版，17 条为后补 ----------
    "本机已可用": {"en": "Available on this machine",
               "de": "Auf diesem Gerät verfügbar",
               "es": "Disponible en este equipo",
               "fr": "Disponible sur cet appareil",
               "ja": "この端末で利用可能", "ko": "이 기기에서 사용 가능"},
    "接入模型后更强": {"en": "Stronger with a model connected",
                 "de": "Stärker mit verbundenem Modell",
                 "es": "Más potente con un modelo conectado",
                 "fr": "Plus puissant avec un modèle connecté",
                 "ja": "モデルを接続するとさらに強くなります",
                 "ko": "모델을 연결하면 더 강해집니다"},
    "本机已整理 {p} 条坑、{s} 场记录": {
        "en": "{p} pitfalls and {s} sessions organized on this machine",
        "de": "{p} Fallstricke und {s} Sitzungen auf diesem Gerät organisiert",
        "es": "{p} errores y {s} sesiones organizados en este equipo",
        "fr": "{p} pièges et {s} sessions organisés sur cet appareil",
        "ja": "この端末で {p} 件の落とし穴と {s} 件の記録を整理しました",
        "ko": "이 기기에서 함정 {p}건과 기록 {s}건을 정리했습니다"},
    "搜索、筛选、原始记录、坑卡都是本机能力，不接模型也能用": {
        "en": "Search, filters, original records and pitfall cards all work on "
              "this machine — no model needed",
        "de": "Suche, Filter, Ursprungseinträge und Fallstrick-Karten laufen "
              "alle auf diesem Gerät – kein Modell nötig",
        "es": "La búsqueda, los filtros, los registros originales y las "
              "tarjetas de errores funcionan en este equipo: no hace falta un "
              "modelo",
        "fr": "Recherche, filtres, enregistrements bruts et fiches pièges "
              "fonctionnent sur cet appareil — aucun modèle requis",
        "ja": "検索・絞り込み・元の記録・落とし穴カードはすべてこの端末内の機能"
              "で、モデルなしでも使えます",
        "ko": "검색, 필터, 원본 기록, 함정 카드는 모두 이 기기 기능이라 모델 "
              "없이도 사용할 수 있습니다"},
    "把踩过的坑归纳成方法正文、写成长叙事、让 AI 重写总结——这些「归纳类」"
    "能力需要模型；接入后，本机攒下的记录会被整理成它们": {
        "en": "Distilling the pitfalls you’ve hit into method text, writing the "
              "growth narrative, letting AI rewrite summaries — these "
              "induction-type abilities need a model; once connected, the "
              "records saved on this machine get organized into them",
        "de": "Aus Ihren Fallstricken Methodentexte verdichten, das "
              "Wachstumsnarrativ schreiben, Zusammenfassungen von der KI "
              "umschreiben lassen – diese induktiven Fähigkeiten benötigen ein "
              "Modell; nach dem Verbinden werden die auf diesem Gerät "
              "gesammelten Aufzeichnungen dazu verarbeitet",
        "es": "Destilar los errores que has cometido en el cuerpo del método, "
              "escribir la narrativa de crecimiento, dejar que la IA reescriba "
              "los resúmenes: estas capacidades inductivas necesitan un modelo; "
              "al conectar, los registros guardados en este equipo se organizan "
              "en ellas",
        "fr": "Distiller les pièges rencontrés en corps de méthode, écrire le "
              "récit de progression, laisser l’IA réécrire les résumés — ces "
              "capacités d’induction nécessitent un modèle ; une fois connecté, "
              "les enregistrements accumulés sur cet appareil y sont organisés",
        "ja": "踏んだ落とし穴を方法本文にまとめ、成長ナラティブを書き、AI に"
              "要約を書き直させる——こうした帰納系の機能にはモデルが必要です。"
              "接続後、この端末に貯まった記録がそれらに整理されます",
        "ko": "겪은 함정을 방법 본문으로 정리하고, 성장 서사를 쓰고, AI가 요약을 "
              "다시 쓰게 하는 것 — 이런 귀납형 기능에는 모델이 필요합니다. "
              "연결하면 이 기기에 쌓인 기록이 그것들로 정리됩니다"},
    "接入后开始把本机记录归纳成方法": {
        "en": "Once connected, it starts distilling your local records into "
              "methods",
        "de": "Nach dem Verbinden werden die lokalen Aufzeichnungen zu Methoden "
              "verdichtet",
        "es": "Al conectar, empieza a destilar tus registros locales en métodos",
        "fr": "Une fois connecté, il distille vos enregistrements locaux en "
              "méthodes",
        "ja": "接続後、この端末の記録を方法にまとめ始めます",
        "ko": "연결하면 이 기기의 기록을 방법으로 정리하기 시작합니다"},
    "已攒下 {n} 条待提炼片段，接入后自动整理": {
        "en": "{n} raw fragments saved — distilled automatically once connected",
        "de": "{n} rohe Fragmente gesammelt – nach dem Verbinden automatisch "
              "verdichtet",
        "es": "{n} fragmentos sin procesar guardados: se destilan "
              "automáticamente al conectar",
        "fr": "{n} fragments bruts enregistrés — distillés automatiquement une "
              "fois connecté",
        "ja": "{n} 件の未整理の断片を保存しました。接続後に自動で整理します",
        "ko": "{n}개의 미정제 조각을 저장했습니다. 연결 후 자동으로 정리합니다"},
    "自动记录、搜索、坑卡不接模型也能用；总结成方法与自动带上需要模型——"
    "接入是增强，不是前提": {
        "en": "Auto-recording, search and pitfall cards work without a model; "
              "distilling into methods and auto-attaching need one — "
              "connecting is an enhancement, not a prerequisite",
        "de": "Automatische Aufzeichnung, Suche und Fallstrick-Karten gehen "
              "ohne Modell; Methoden-Verdichtung und automatisches Mitführen "
              "brauchen eines – Verbinden ist eine Verbesserung, keine "
              "Voraussetzung",
        "es": "El registro automático, la búsqueda y las tarjetas de errores "
              "funcionan sin modelo; destilar en métodos y adjuntar "
              "automáticamente necesitan uno: conectar es una mejora, no un "
              "requisito",
        "fr": "L’enregistrement automatique, la recherche et les fiches pièges "
              "fonctionnent sans modèle ; distiller en méthodes et joindre "
              "automatiquement en nécessitent un — se connecter est une "
              "amélioration, pas un prérequis",
        "ja": "自動記録・検索・落とし穴カードはモデルなしでも使えます。方法への"
              "まとめと自動付与にはモデルが必要です——接続は強化であり、前提"
              "ではありません",
        "ko": "자동 기록, 검색, 함정 카드는 모델 없이도 사용할 수 있습니다. "
              "방법으로 정리하기와 자동 첨부에는 모델이 필요합니다 — 연결은 "
              "강화일 뿐 전제가 아닙니다"},
    "自动记录一直在跑；总结成方法、自动带上已在工作": {
        "en": "Auto-recording keeps running; distilling into methods and "
              "auto-attaching are already at work",
        "de": "Die automatische Aufzeichnung läuft weiter; Methoden-Verdichtung "
              "und automatisches Mitführen arbeiten bereits",
        "es": "El registro automático sigue funcionando; destilar en métodos y "
              "adjuntar automáticamente ya están activos",
        "fr": "L’enregistrement automatique tourne toujours ; la distillation "
              "en méthodes et la jointure automatique sont déjà actives",
        "ja": "自動記録は動き続けています。方法へのまとめと自動付与もすでに動作"
              "しています",
        "ko": "자동 기록은 계속 작동합니다. 방법으로 정리하기와 자동 첨부도 이미 "
              "작동 중입니다"},
    "还没有待总结的经验——先让 AI 干点活": {
        "en": "No experiences to summarize yet — let the AI do some work first",
        "de": "Noch keine Erfahrungen zum Verdichten – lassen Sie die KI erst "
              "etwas arbeiten",
        "es": "Aún no hay experiencias que destilar: deja que la IA haga algo "
              "de trabajo primero",
        "fr": "Pas encore d’expériences à distiller — laissez d’abord l’IA "
              "travailler un peu",
        "ja": "まだ要約する経験がありません——まず AI に少し働いてもらいましょう",
        "ko": "아직 정리할 경험이 없습니다 — 먼저 AI가 일을 좀 하게 하세요"},
    # 协作页规则卡下钻（DetailDrawer）字段
    "点开看完整规则": {"en": "Open to see the full rule",
                 "de": "Öffnen, um die ganze Regel zu sehen",
                 "es": "Abrir para ver la regla completa",
                 "fr": "Ouvrir pour voir la règle complète",
                 "ja": "開いてルール全体を見る", "ko": "열어서 전체 규칙 보기"},
    "规则": {"en": "Rule", "de": "Regel", "es": "Regla", "fr": "Règle",
           "ja": "ルール", "ko": "규칙"},
    "触发时机": {"en": "When it triggers", "de": "Auslösezeitpunkt",
             "es": "Cuándo se activa", "fr": "Quand cela se déclenche",
             "ja": "発動タイミング", "ko": "발동 시점"},
    "已启用": {"en": "Enabled", "de": "Aktiviert", "es": "Activada",
           "fr": "Activée", "ja": "有効", "ko": "활성화됨"},
    "已停用": {"en": "Disabled", "de": "Deaktiviert", "es": "Desactivada",
           "fr": "Désactivée", "ja": "無効", "ko": "비활성화됨"},
    "用过 {n} 次": {"en": "Used {n} times", "de": "{n} Mal verwendet",
                "es": "Usada {n} veces", "fr": "Utilisée {n} fois",
                "ja": "{n} 回使用", "ko": "{n}회 사용"},
    "（这条规则没有正文）": {"en": "(This rule has no body text)",
                    "de": "(Diese Regel hat keinen Text)",
                    "es": "(Esta regla no tiene texto)",
                    "fr": "(Cette règle n’a pas de texte)",
                    "ja": "（このルールには本文がありません）",
                    "ko": "(이 규칙에는 본문이 없습니다)"},
}

# 与 tests/test_i18n.py 同口径的护栏（此处先自检，避免跑完测试才发现）
_LATIN_RUN = re.compile(
    r"[A-Za-z][A-Za-z'’]*(?:[ ,.;:—\-]+[A-Za-z][A-Za-z'’]*){5,}")


def _check() -> None:
    for mid, table in E.items():
        assert mid.strip(), "空 msgid"
        ph = set(re.findall(r"\{(\w+)\}", mid))
        for lang in ("en", "de", "es", "fr", "ja", "ko"):
            text = table.get(lang)
            assert text and text.strip(), f"{lang} 空译文: {mid[:24]}"
            got = set(re.findall(r"\{(\w+)\}", text))
            assert got == ph, \
                f"{lang} 占位符不符 {mid[:24]}: {sorted(ph)} vs {sorted(got)}"
            assert text != mid, f"{lang} 照抄中文源串: {mid[:24]}"
            if lang in LATIN:
                assert not [c for c in text if "一" <= c <= "鿿"], \
                    f"{lang} 残留汉字: {mid[:24]}"
                assert "（" not in text and "）" not in text, \
                    f"{lang} 全角括号: {mid[:24]}"
            if lang in ("ja", "ko"):
                assert not _LATIN_RUN.search(text), \
                    f"{lang} 混入英文句: {mid[:24]}"
            if lang in LATIN and len(text) > 150 and len(text) > 5 * len(mid):
                raise AssertionError(f"{lang} 超长比: {mid[:24]}")


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