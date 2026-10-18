# -*- coding: utf-8 -*-
"""补齐「经验详情 / 演化链（P0-3）」新增词条到 7 语 .po。

两部分：
- 框架文案：`app/gui/experience_detail.py` 与 `experiences.py` 里的
  t("字面量")，AST 护栏会卡，必须登记；
- `_SOURCE_LABEL` 的三个证据来源标签：以"字典存 msgid + 运行时直接引用"出现，
  AST 抓不到，漏补只会在非中文界面静默回落中文——同 friction bucket 一并要求手工登记。

错误文案一律占位符形式（`…：{err}`）不拼接：翻译时才能调整语序。
 L10/L11/L13 补：读取中 / 会话打开中 / 恢复 / 已恢复。

用法：uv run python scripts/i18n_evolution_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=tú+«»、fr=撇号 ’+«»、ko=합니다체+''、
非 CJK 语言禁全角括号与残留汉字（脚本末尾自检）。
"""

from __future__ import annotations

import sys

from i18n_entry_lib import apply_entries, check_entries

E: dict[str, dict[str, str]] = {
    # ---------- 详情 / 演化链对话框 ----------
    "经验详情": {
        "en": "Experience details", "de": "Erfahrungsdetails",
        "es": "Detalles de la experiencia",
        "fr": "Détails de l’expérience", "ja": "経験の詳細",
        "ko": "경험 상세"},
    "凭什么这么说": {
        "en": "What backs this up",
        "de": "Womit begründet sich das",
        "es": "En qué se basa", "fr": "Sur quoi repose ce choix",
        "ja": "その根拠", "ko": "근거"},
    "这条经验没有带原话证据（可能是早期数据或用户直接确认的）": {
        "en": "This experience has no quoted evidence "
              "(early data, or confirmed directly by you)",
        "de": "Für diese Erfahrung liegt kein Zitat vor "
              "(alte Daten oder von Ihnen direkt bestätigt)",
        "es": "Esta experiencia no tiene cita que la respalde "
              "(datos antiguos o confirmada directamente por ti)",
        "fr": "Aucune citation pour cette expérience "
              "(donnée ancienne ou confirmée par vous)",
        "ja": "この経験には原話の証拠がありません"
              "（初期データ、またはあなたが直接確認したもの）",
        "ko": "이 경험에는 원문 증거가 없습니다"
             "（초기 데이터이거나 직접 확인한 항목）"},
    "看原话": {
        "en": "See the original", "de": "Original ansehen",
        "es": "Ver el original", "fr": "Voir l’original",
        "ja": "原話を見る", "ko": "원문 보기"},
    "它被改过吗": {
        "en": "Has it changed", "de": "Wurde es geändert",
        "es": "¿Ha cambiado?", "fr": "A-t-il été modifié",
        "ja": "変更されたか", "ko": "변경된 적 있나요"},
    "读不到演化链：{err}": {
        "en": "Can’t read the revision chain: {err}",
        "de": "Versionskette nicht lesbar: {err}",
        "es": "No se puede leer el historial: {err}",
        "fr": "Historique illisible : {err}",
        "ja": "変更履歴を読めません: {err}", "ko": "변경 이력을 읽을 수 없음: {err}"},
    "还没被改过，这是第 1 版": {
        "en": "Never revised — this is version 1",
        "de": "Noch nie geändert – das ist Version 1",
        "es": "Todavía sin cambios: es la versión 1",
        "fr": "Jamais modifié — voici la version 1",
        "ja": "まだ変更されていません（1 版目）",
        "ko": "아직 변경되지 않았습니다(1번째 판)"},
    "共 {n} 版，下面是历史改动": {
        "en": "{n} versions in total — past revisions below",
        "de": "Insgesamt {n} Versionen – frühere Änderungen unten",
        "es": "{n} versiones en total: los cambios anteriores abajo",
        "fr": "{n} versions au total — les versions passées ci-dessous",
        "ja": "全 {n} 版、以下が過去の変更",
        "ko": "총 {n}판, 아래는 과거 변경"},
    "当前": {"en": "Current", "de": "Aktuell", "es": "Actual",
             "fr": "Actuelle", "ja": "現在", "ko": "현재"},
    "回到这版": {
        "en": "Restore this version", "de": "Diese Version wiederherstellen",
        "es": "Volver a esta versión", "fr": "Revenir à cette version",
        "ja": "この版に戻す", "ko": "이 판으로 되돌리기"},
    "忘了这条": {
        "en": "Forget this", "de": "Das vergessen",
        "es": "Olvidar esto", "fr": "Oublier",
        "ja": "これを忘れる", "ko": "이 항목 잊기"},
    "彻底删除": {
        "en": "Delete permanently", "de": "Endgültig löschen",
        "es": "Eliminar definitivamente", "fr": "Supprimer définitivement",
        "ja": "完全に削除", "ko": "완전 삭제"},
    "打不开当时的会话：{err}": {
        "en": "Can’t open that session: {err}",
        "de": "Sitzung lässt sich nicht öffnen: {err}",
        "es": "No se puede abrir esa sesión: {err}",
        "fr": "Impossible d’ouvrir cette session : {err}",
        "ja": "その時のセッションを開けません: {err}",
        "ko": "당시 세션을 열 수 없음: {err}"},
    # ---------- L10/L11/L13：后台取数态 + 恢复入口 ----------
    "读取中…": {
        "en": "Reading", "de": "Wird gelesen", "es": "Leyendo",
        "fr": "Lecture", "ja": "読み込み中", "ko": "읽는 중"},
    "正在打开当时的会话…": {
        "en": "Opening that session", "de": "Sitzung wird geöffnet",
        "es": "Abriendo esa sesión", "fr": "Ouverture de cette session",
        "ja": "その時のセッションを開いています", "ko": "당시 세션을 여는 중"},
    "恢复": {
        "en": "Restore", "de": "Wiederherstellen", "es": "Restaurar",
        "fr": "Restaurer", "ja": "復元", "ko": "복원"},
    "已恢复": {
        "en": "Restored", "de": "Wiederhergestellt", "es": "Restaurado",
        "fr": "Restauré", "ja": "復元しました", "ko": "복원했습니다"},
    "回到第 {n} 版": {
        "en": "Restore version {n}", "de": "Version {n} wiederherstellen",
        "es": "Volver a la versión {n}",
        "fr": "Revenir à la version {n}",
        "ja": "{n} 版に戻す", "ko": "{n}판으로 되돌리기"},
    "会以新的一版写入（历史保留、不被覆盖），确定回滚吗？": {
        "en": "This writes a new version (the history is kept and never "
              "overwritten). Roll back?",
        "de": "Es wird eine neue Version geschrieben; der Verlauf bleibt "
              "erhalten und wird nicht überschrieben. Zurückrollen?",
        "es": "Se escribirá una versión nueva: el historial se conserva y no "
              "se sobrescribe. ¿Volver?",
        "fr": "Une nouvelle version sera écrite (l’historique est conservé, "
              "jamais écrasé). Revenir ?",
        "ja": "新しい版として書き込みます（履歴は残り、上書きされません）。"
              "戻しますか？",
        "ko": "새 판으로 기록합니다(이력은 보존되며 덮어쓰지 않습니다). "
              "되돌릴까요?"},
    "彻底删除不可撤销（只留 30 天归档副本），确定吗？": {
        "en": "Permanent deletion cannot be undone (only a 30-day archive "
              "copy remains). Are you sure?",
        "de": "Das endgültige Löschen kann nicht rückgängig gemacht werden "
              "(nur eine 30-tägige Archivkopie bleibt). Sind Sie sicher?",
        "es": "La eliminación definitiva no se puede deshacer (solo queda una "
              "copia de archivo de 30 días). ¿Seguro?",
        "fr": "La suppression définitive est irréversible (seule une copie "
              "d’archive de 30 jours reste). Confirmer ?",
        "ja": "完全削除は元に戻せません（30 日間のアーカイブのみ残ります）。"
              "よろしいですか？",
        "ko": "완전 삭제는 되돌릴 수 없습니다(30일 보관본만 남음). "
              "확실합니까?"},
    "已回到第 {n} 版": {
        "en": "Restored to version {n}", "de": "Version {n} wiederhergestellt",
        "es": "Vuelto a la versión {n}",
        "fr": "Revenu à la version {n}",
        "ja": "{n} 版に戻しました", "ko": "{n}판으로 되돌렸습니다"},
    "已彻底删除": {
        "en": "Deleted permanently", "de": "Endgültig gelöscht",
        "es": "Eliminado definitivamente", "fr": "Supprimé définitivement",
        "ja": "完全に削除しました", "ko": "완전 삭제했습니다"},
    "已遗忘，可从回收恢复": {
        "en": "Forgotten — can be restored from the recycle bin",
        "de": "Vergessen – über den Papierkorb wiederherstellbar",
        "es": "Olvidado: se puede restaurar desde la papelera",
        "fr": "Oublié — restaurable depuis la corbeille",
        "ja": "忘れました。ごみ箱から復元できます",
        "ko": "잊었습니다. 휴지통에서 복원할 수 있습니다"},
    # ---------- 经验页抽屉入口 ----------
    "详情 / 演化": {
        "en": "Details / history", "de": "Details / Verlauf",
        "es": "Detalles / historial", "fr": "Détails / historique",
        "ja": "詳細 / 履歴", "ko": "상세 / 이력"},
    # ---------- _SOURCE_LABEL（字典值，AST 抓不到，手工登记） ----------
    "会话原话": {
        "en": "Session quote", "de": "Zitat aus der Sitzung",
        "es": "Cita de la sesión", "fr": "Citation de la session",
        "ja": "セッションの原話", "ko": "세션 원문"},
    "上报原文": {
        "en": "Reported as-is", "de": "Wie gemeldet",
        "es": "Tal como se informó", "fr": "Tel que rapporté",
        "ja": "報告された原文", "ko": "보고된 원문"},
    "用户确认": {
        "en": "Confirmed by you", "de": "Von Ihnen bestätigt",
        "es": "Confirmado por ti", "fr": "Confirmé par vous",
        "ja": "あなたが確認", "ko": "직접 확인함"},
}


def main() -> int:
    check_entries(E)
    apply_entries(E)
    return 0


if __name__ == "__main__":
    sys.exit(main())
