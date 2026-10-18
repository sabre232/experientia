# -*- coding: utf-8 -*-
"""补齐「避坑卡同类归堆（方案 B）」新增词条到 7 语 .po。

9 个桶短标题经 group_friction 变量传入 t()，AST 护栏抓不到，必须手工登记；
4 条框架文案是 t("字面量")，护栏会卡，一并补齐。
用法：uv run python scripts/i18n_friction_bucket_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=tú+«»、fr=撇号 ’+«»、ko=합니다체+''、
非 CJK 语言禁全角括号与残留汉字（脚本末尾自检）。
"""

from __future__ import annotations

import sys

from i18n_entry_lib import apply_entries, check_entries

E: dict[str, dict[str, str]] = {
    # ---------- 桶短标题（变量传 t()，护栏抓不到，手工登记） ----------
    "编辑前没先读文件": {
        "en": "Edited before reading the file",
        "de": "Vor dem Editieren nicht gelesen",
        "es": "Editaste sin leer el archivo",
        "fr": "Fichier modifié sans lecture préalable",
        "ja": "ファイルを読まずに編集",
        "ko": "파일 먼저 읽지 않고 편집"},
    "操作顺序或参数不对": {
        "en": "Wrong order or parameters",
        "de": "Reihenfolge oder Parameter falsch",
        "es": "Orden o parámetros incorrectos",
        "fr": "Ordre ou paramètres incorrects",
        "ja": "手順かパラメータが誤り",
        "ko": "순서나 매개변수가 잘못됨"},
    "替换没匹配上": {
        "en": "Replacement didn’t match",
        "de": "Ersetzung traf nicht",
        "es": "El reemplazo no coincidió",
        "fr": "Texte à remplacer introuvable",
        "ja": "置換が一致しない",
        "ko": "치환이 일치하지 않음"},
    "命令被安全策略拦下": {
        "en": "Command blocked by security policy",
        "de": "Befehl durch Sicherheitsregel blockiert",
        "es": "Orden bloqueada por seguridad",
        "fr": "Commande bloquée par la sécurité",
        "ja": "コマンドがセキュリティ規則で停止",
        "ko": "명령이 보안 정책에 막힘"},
    "拿着旧内容改文件": {
        "en": "Edited from stale content",
        "de": "Mit veraltetem Inhalt geändert",
        "es": "Editaste con contenido anticuado",
        "fr": "Modification sur du contenu périmé",
        "ja": "古い内容のまま編集",
        "ko": "지난 내용으로 편집"},
    "传的参数类型不对": {
        "en": "Wrong parameter type",
        "de": "Falscher Parametertyp",
        "es": "Tipo de parámetro incorrecto",
        "fr": "Type de paramètre incorrect",
        "ja": "渡したパラメータの型が誤り",
        "ko": "매개변수 형식이 다름"},
    "要用的技能没装": {
        "en": "Required skill not installed",
        "de": "Benötigter Skill fehlt",
        "es": "Falta la habilidad necesaria",
        "fr": "Compétence requise manquante",
        "ja": "使うスキルが未導入",
        "ko": "필요한 스킬이 없음"},
    "一处改还是全改没说清": {
        "en": "One or all replacements unclear",
        "de": "Unklar: eine oder alle Ersetzungen",
        "es": "No aclaraste uno o todos",
        "fr": "Un ou tous : pas précisé",
        "ja": "1 か所か全体か不明",
        "ko": "한 곳인지 전체인지 불명확"},
    "其实没改动却提交": {
        "en": "Submitted without changes",
        "de": "Commit ohne Änderung",
        "es": "Commit sin cambios",
        "fr": "Commit sans changement",
        "ja": "変更なしで提出",
        "ko": "변경 없이 제출"},
    # ---------- 框架文案（t("字面量")，AST 护栏会卡） ----------
    "{c} 次小毛病归成 {k} 类，都在自动改进 · 不用你操心": {
        "en": "{c} little slips grouped into {k} kinds — all improving on "
             "their own · nothing to worry about",
        "de": "{c} kleine Patzer, in {k} Gruppen einsortiert – das wird "
             "automatisch besser, Sie müssen sich nicht darum kümmern",
        "es": "{c} despistes agrupados en {k} tipos; todo mejora solo, no "
             "te preocupes",
        "fr": "{c} petites bourdes regroupées en {k} sortes — tout se "
             "corrige automatiquement, ne vous en faites pas",
        "ja": "小さなミス {c} 回を {k} 種に整理、すべて自動で改善中 · "
             "おまかせください",
        "ko": "잔실수 {c}회를 {k}종으로 묶었습니다 — 자동으로 개선 중, "
             "걱정하지 마세요"},
    "还有 {n} 类 · 合计 {c} 次": {
        "en": "{n} more kinds · {c} times total",
        "de": "Noch {n} Arten · insgesamt {c} Mal",
        "es": "Quedan {n} tipos · {c} veces en total",
        "fr": "{n} autres sortes · {c} fois au total",
        "ja": "他に {n} 種 · 計 {c} 回",
        "ko": "다른 {n}종 · 합계 {c}회"},
    "展开": {"en": "Expand", "de": "Ausklappen", "es": "Desplegar",
           "fr": "Déplier", "ja": "展開", "ko": "펼치기"},
    "查看相关会话记录": {
        "en": "View related sessions", "de": "Zugehörige Sitzungen ansehen",
        "es": "Ver sesiones relacionadas", "fr": "Voir les sessions liées",
        "ja": "関連セッションを見る", "ko": "관련 세션 보기"},
}


def main() -> int:
    check_entries(E)
    apply_entries(E)
    return 0


if __name__ == "__main__":
    sys.exit(main())
