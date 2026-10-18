# -*- coding: utf-8 -*-
"""补齐「服务端错误原因（HTTPException detail）」词条到 7 语 .po。

为什么需要：服务端按分层只管数据，错误 detail 是中文源串；外壳侧
`LocalApiError.localized()` 会对它过一遍 `t()`，登记的串才翻得动，没登记的
原样回落中文（不会空白，但英文界面上就是一句中文报错）。

清单来源：`app/local_api.py` + `app/local_api_routers/*.py` 里 `detail="…"`
的纯字面量（f-string 的串含运行时内容，不登记——翻不动也没必要）。

用法：uv run python scripts/i18n_api_error_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=tú+«»、fr=撇号 ’+«»、ko=합니다체+''、
非 CJK 语言禁全角括号与残留汉字（脚本末尾自检）。
"""

from __future__ import annotations

import sys

from i18n_entry_lib import apply_entries, check_entries

E: dict[str, dict[str, str]] = {
    # ---------- 找不到 ----------
    "经验不存在": {
        "en": "Experience not found", "de": "Erfahrung nicht gefunden",
        "es": "La experiencia no existe", "fr": "Expérience introuvable",
        "ja": "経験が見つかりません", "ko": "경험을 찾을 수 없습니다"},
    "会话不存在": {
        "en": "Session not found", "de": "Sitzung nicht gefunden",
        "es": "La sesión no existe", "fr": "Session introuvable",
        "ja": "セッションが見つかりません", "ko": "세션을 찾을 수 없습니다"},
    "节点不存在": {
        "en": "Node not found", "de": "Knoten nicht gefunden",
        "es": "El nodo no existe", "fr": "Nœud introuvable",
        "ja": "ノードが見つかりません", "ko": "노드를 찾을 수 없습니다"},
    "条目不存在": {
        "en": "Entry not found", "de": "Eintrag nicht gefunden",
        "es": "La entrada no existe", "fr": "Entrée introuvable",
        "ja": "項目が見つかりません", "ko": "항목을 찾을 수 없습니다"},
    "规则不存在": {
        "en": "Rule not found", "de": "Regel nicht gefunden",
        "es": "La regla no existe", "fr": "Règle introuvable",
        "ja": "ルールが見つかりません", "ko": "규칙을 찾을 수 없습니다"},
    "playbook 不存在": {
        "en": "Playbook not found", "de": "Playbook nicht gefunden",
        "es": "El playbook no existe", "fr": "Playbook introuvable",
        "ja": "プレイブックが見つかりません",
        "ko": "플레이북을 찾을 수 없습니다"},
    "该版本不存在": {
        "en": "That version does not exist",
        "de": "Diese Version existiert nicht",
        "es": "Esa versión no existe", "fr": "Cette version n’existe pas",
        "ja": "その版は存在しません", "ko": "해당 판은 존재하지 않습니다"},
    "建议卡不存在": {
        "en": "Suggestion card not found",
        "de": "Vorschlagskarte nicht gefunden",
        "es": "La tarjeta de sugerencia no existe",
        "fr": "Fiche de suggestion introuvable",
        "ja": "提案カードが見つかりません",
        "ko": "제안 카드를 찾을 수 없습니다"},
    "建议卡已处理": {
        "en": "Suggestion card already handled",
        "de": "Vorschlagskarte bereits bearbeitet",
        "es": "La tarjeta de sugerencia ya está gestionada",
        "fr": "Fiche de suggestion déjà traitée",
        "ja": "提案カードは処理済みです",
        "ko": "이미 처리된 제안 카드입니다"},
    "意图不存在或已忽略": {
        "en": "Intent not found, or already dismissed",
        "de": "Absicht nicht gefunden oder bereits verworfen",
        "es": "La intención no existe o ya se descartó",
        "fr": "Intention introuvable ou déjà ignorée",
        "ja": "意図が見つからないか、既に無視されています",
        "ko": "의도를 찾을 수 없거나 이미 무시되었습니다"},
    "未找到该失败模式条目": {
        "en": "That failure-mode entry was not found",
        "de": "Der Eintrag zum Fehlermuster wurde nicht gefunden",
        "es": "No se encontró esa entrada de modo de fallo",
        "fr": "Entrée du mode d’échec introuvable",
        "ja": "その失敗パターンの項目が見つかりません",
        "ko": "해당 실패 모드 항목을 찾을 수 없습니다"},
    "未找到该失败模式条目（可能已被修订）": {
        "en": "That failure-mode entry was not found "
              "(it may have been revised)",
        "de": "Der Eintrag zum Fehlermuster wurde nicht gefunden "
              "(eventuell überarbeitet)",
        "es": "No se encontró esa entrada de modo de fallo "
              "(puede haberse revisado)",
        "fr": "Entrée du mode d’échec introuvable "
              "(elle a peut-être été révisée)",
        "ja": "その失敗パターンの項目が見つかりません"
              "（改訂された可能性があります）",
        "ko": "해당 실패 모드 항목을 찾을 수 없습니다"
             "（수정되었을 수 있음）"},
    # ---------- 遗忘 / 回滚 ----------
    "无法遗忘（不存在或归档失败）": {
        "en": "Cannot forget it (missing, or archiving failed)",
        "de": "Vergessen nicht möglich (fehlt, oder Archivierung "
              "fehlgeschlagen)",
        "es": "No se puede olvidar (no existe o falló el archivado)",
        "fr": "Impossible d’oublier (introuvable, ou échec de "
              "l’archivage)",
        "ja": "忘却できません（存在しない、またはアーカイブに失敗）",
        "ko": "잊기 실패(존재하지 않거나 보관 실패)"},
    "该经验不在已遗忘状态": {
        "en": "That experience is not marked as forgotten",
        "de": "Diese Erfahrung ist nicht als vergessen markiert",
        "es": "Esa experiencia no está en estado olvidado",
        "fr": "Cette expérience n’est pas dans l’état oublié",
        "ja": "その経験は忘却状態ではありません",
        "ko": "해당 경험은 잊힌 상태가 아닙니다"},
    # ---------- 模型 ----------
    "未接入模型": {
        "en": "No model connected", "de": "Kein Modell angebunden",
        "es": "No hay modelo conectado", "fr": "Aucun modèle connecté",
        "ja": "モデルが接続されていません",
        "ko": "연결된 모델이 없습니다"},
    "模型调用失败，请稍后再试": {
        "en": "The model call failed — please retry later",
        "de": "Der Modellaufruf ist fehlgeschlagen – bitte später "
              "erneut versuchen",
        "es": "La llamada al modelo falló; inténtalo de nuevo más tarde",
        "fr": "L’appel au modèle a échoué — réessayez plus tard",
        "ja": "モデルの呼び出しに失敗しました。"
              "しばらくしてから再試行してください",
        "ko": "모델 호출에 실패했습니다. 나중에 다시 시도해 주세요"},
    "模型没有给出改写内容": {
        "en": "The model returned no rewritten content",
        "de": "Das Modell hat keinen umgeschriebenen Inhalt geliefert",
        "es": "El modelo no devolvió contenido reescrito",
        "fr": "Le modèle n’a renvoyé aucun contenu réécrit",
        "ja": "モデルが書き換え内容を返しませんでした",
        "ko": "모델이 다시 쓴 내용을 반환하지 않았습니다"},
    "重写内容为空": {
        "en": "The rewritten content is empty",
        "de": "Der umgeschriebene Inhalt ist leer",
        "es": "El contenido reescrito está vacío",
        "fr": "Le contenu réécrit est vide",
        "ja": "書き換え内容が空です",
        "ko": "다시 쓴 내용이 비어 있습니다"},
    # ---------- 入参校验 ----------
    "text 不能为空": {
        "en": "text cannot be empty", "de": "text darf nicht leer sein",
        "es": "text no puede estar vacío", "fr": "text ne peut être vide",
        "ja": "text は空にできません", "ko": "text는 비울 수 없습니다"},
    "body 必须是 JSON 对象": {
        "en": "body must be a JSON object",
        "de": "body muss ein JSON-Objekt sein",
        "es": "body debe ser un objeto JSON",
        "fr": "body doit être un objet JSON",
        "ja": "body は JSON オブジェクトでなければなりません",
        "ko": "body는 JSON 객체여야 합니다"},
    "feedback 必须是 valid / corrected": {
        "en": "feedback must be valid or corrected",
        "de": "feedback muss valid oder corrected sein",
        "es": "feedback debe ser valid o corrected",
        "fr": "feedback doit être valid ou corrected",
        "ja": "feedback は valid または corrected でなければなりません",
        "ko": "feedback는 valid 또는 corrected여야 합니다"},
    "action 必须是 apply/dismiss/defer": {
        "en": "action must be apply, dismiss or defer",
        "de": "action muss apply, dismiss oder defer sein",
        "es": "action debe ser apply, dismiss o defer",
        "fr": "action doit être apply, dismiss ou defer",
        "ja": "action は apply / dismiss / defer のいずれかです",
        "ko": "action은 apply/dismiss/defer 중 하나여야 합니다"},
    "granularity 必须是 experiences/playbook/preferences/phase/growth/hooks": {
        "en": "granularity must be experiences, playbook, preferences, "
              "phase, growth or hooks",
        "de": "granularity muss experiences, playbook, preferences, "
              "phase, growth oder hooks sein",
        "es": "granularity debe ser experiences, playbook, preferences, "
              "phase, growth o hooks",
        "fr": "granularity doit être experiences, playbook, preferences, "
              "phase, growth ou hooks",
        "ja": "granularity は experiences / playbook / preferences / "
              "phase / growth / hooks のいずれかです",
        "ko": "granularity는 experiences/playbook/preferences/phase/"
              "growth/hooks 중 하나여야 합니다"},
    "template_id 包含非法字符": {
        "en": "template_id contains invalid characters",
        "de": "template_id enthält unzulässige Zeichen",
        "es": "template_id contiene caracteres no válidos",
        "fr": "template_id contient des caractères invalides",
        "ja": "template_id に使用できない文字が含まれています",
        "ko": "template_id에 잘못된 문자가 포함되어 있습니다"},
    "未知模板": {
        "en": "Unknown template", "de": "Unbekannte Vorlage",
        "es": "Plantilla desconocida", "fr": "Modèle inconnu",
        "ja": "不明なテンプレート", "ko": "알 수 없는 템플릿"},
    "未导入过该模板": {
        "en": "That template was never imported",
        "de": "Diese Vorlage wurde nie importiert",
        "es": "Esa plantilla nunca se importó",
        "fr": "Ce modèle n’a jamais été importé",
        "ja": "そのテンプレートは一度もインポートされていません",
        "ko": "해당 템플릿은 가져온 적이 없습니다"},
    "id 不匹配": {
        "en": "The id does not match", "de": "Die id stimmt nicht überein",
        "es": "El id no coincide", "fr": "L’id ne correspond pas",
        "ja": "id が一致しません", "ko": "id가 일치하지 않습니다"},
    "playbook 导出需要 trunk+category": {
        "en": "Exporting a playbook needs trunk and category",
        "de": "Für den Playbook-Export werden trunk und category benötigt",
        "es": "Exportar un playbook requiere trunk y category",
        "fr": "L’export d’un playbook exige trunk et category",
        "ja": "プレイブックの書き出しには trunk と category が必要です",
        "ko": "플레이북 내보내기에는 trunk+category가 필요합니다"},
    "偏好导出需要 trunk": {
        "en": "Exporting preferences needs trunk",
        "de": "Für den Export der Präferenzen wird trunk benötigt",
        "es": "Exportar las preferencias requiere trunk",
        "fr": "L’export des préférences exige trunk",
        "ja": "好みの書き出しには trunk が必要です",
        "ko": "선호 내보내기에는 trunk가 필요합니다"},
    "请至少勾选一个方法": {
        "en": "Select at least one method",
        "de": "Bitte mindestens eine Methode auswählen",
        "es": "Marca al menos un método",
        "fr": "Cochez au moins une méthode",
        "ja": "少なくとも 1 つの方法を選んでください",
        "ko": "방법을 하나 이상 선택해 주세요"},
    "路径不在允许的导出目录内": {
        "en": "That path is outside the allowed export folders",
        "de": "Der Pfad liegt außerhalb der erlaubten Exportordner",
        "es": "La ruta está fuera de las carpetas de exportación "
              "permitidas",
        "fr": "Ce chemin est hors des dossiers d’export autorisés",
        "ja": "そのパスは許可された書き出し先にありません",
        "ko": "경로가 허용된 내보내기 폴더 밖에 있습니다"},
    "需要确认口令：请在确认弹窗输入 WIPE": {
        "en": "Confirmation required: type WIPE in the confirmation dialog",
        "de": "Bestätigung nötig: geben Sie im Dialog WIPE ein",
        "es": "Se requiere confirmación: escribe WIPE en el cuadro de "
              "confirmación",
        "fr": "Confirmation requise : saisissez WIPE dans la boîte de "
              "confirmation",
        "ja": "確認が必要です：確認ダイアログに WIPE と入力してください",
        "ko": "확인이 필요합니다: 확인 창에 WIPE를 입력하세요"},
    # ---------- 蒸馏 / 归纳 ----------
    "该类目暂无待总结的经验（要重建这份方法卡，请用「重建」）": {
        "en": "No experiences to summarize under this category yet "
              "(to rebuild this method card, use “Rebuild”)",
        "de": "Für diese Kategorie gibt es noch nichts zusammenzufassen "
              "(nutzen Sie „Neu aufbauen“, um die Methodenkarte neu zu "
              "erstellen)",
        "es": "Aún no hay experiencias que resumir en esta categoría "
              "(para reconstruir esta ficha de método, usa "
              "«Reconstruir»)",
        "fr": "Aucune expérience à synthétiser dans cette catégorie "
              "(pour reconstruire cette fiche, utilisez « Reconstruire »)",
        "ja": "このカテゴリにはまだまとめる経験がありません"
              "（メソッドカードを作り直す場合は「再構築」を使ってください）",
        "ko": "이 분류에는 아직 요약할 경험이 없습니다"
             "（메서드 카드를 다시 만들려면 '재구성'을 사용하세요）"},
    "该类别还没有经验": {
        "en": "This category has no experiences yet",
        "de": "Diese Kategorie hat noch keine Erfahrungen",
        "es": "Esta categoría todavía no tiene experiencias",
        "fr": "Cette catégorie n’a pas encore d’expérience",
        "ja": "このカテゴリにはまだ経験がありません",
        "ko": "이 분류에는 아직 경험이 없습니다"},
    "该类别还没有可归纳的纠正/低 G 经验": {
        "en": "This category has no corrections or low-G experiences to "
              "distill yet",
        "de": "Diese Kategorie hat noch keine Korrekturen oder "
              "Erfahrungen mit niedrigem G-Wert zum Zusammenfassen",
        "es": "Esta categoría todavía no tiene correcciones ni "
              "experiencias de G bajo que resumir",
        "fr": "Cette catégorie n’a pas encore de corrections ni "
              "d’expériences à faible G à synthétiser",
        "ja": "このカテゴリにはまだまとめられる修正・低 G 経験がありません",
        "ko": "이 분류에는 아직 정리할 교정/저 G 경험이 없습니다"},
    # ---------- 系统 ----------
    "无法确定启动入口（开发模式需经 main.py 启动）": {
        "en": "Cannot determine the startup entry (in dev mode, start "
              "via main.py)",
        "de": "Starteintrag nicht bestimmbar (im Entwicklungsmodus über "
              "main.py starten)",
        "es": "No se puede determinar el punto de arranque (en modo "
              "desarrollo, inicia con main.py)",
        "fr": "Point d’entrée introuvable (en mode développement, "
              "lancez via main.py)",
        "ja": "起動エントリを特定できません"
              "（開発モードでは main.py から起動してください）",
        "ko": "시작 진입점을 확인할 수 없습니다"
             "（개발 모드는 main.py로 실행）"},
    "hook 状态读取失败：{err}": {
        "en": "Could not read the hook state: {err}",
        "de": "Hook-Status konnte nicht gelesen werden: {err}",
        "es": "No se pudo leer el estado de los hooks: {err}",
        "fr": "Impossible de lire l’état des hooks : {err}",
        "ja": "フック状態を読み取れません: {err}",
        "ko": "훅 상태를 읽을 수 없습니다: {err}"},
}


def main() -> int:
    check_entries(E)
    apply_entries(E)
    return 0


if __name__ == "__main__":
    sys.exit(main())
