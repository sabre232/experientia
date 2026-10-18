# -*- coding: utf-8 -*-
"""补齐「接入页分工具向导 C 方案」新增词条到 7 语 .po。

kind 标签（环境变量/配置文件/软件内设置）经 _TOOL_GUIDE 变量传入 t()，
AST 护栏抓不到，必须手工登记；6 条步骤壳/尾标是 t("字面量")，护栏会卡。
用法：uv run python scripts/i18n_toolguide_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=tú+«»、fr=撇号 ’+«»、ko=합니다체+''、
非 CJK 语言禁全角括号与残留汉字（脚本末尾自检）。
"""

from __future__ import annotations

import sys

from i18n_entry_lib import apply_entries, check_entries

E: dict[str, dict[str, str]] = {
    # ---------- kind 标签（变量传 t()，护栏抓不到，手工登记） ----------
    "环境变量": {
        "en": "Environment variable", "de": "Umgebungsvariable",
        "es": "Variable de entorno", "fr": "Variable d'environnement",
        "ja": "環境変数", "ko": "환경 변수"},
    "配置文件": {
        "en": "Config file", "de": "Konfigurationsdatei",
        "es": "Archivo de configuración", "fr": "Fichier de configuration",
        "ja": "設定ファイル", "ko": "설정 파일"},
    "软件内设置": {
        "en": "In-app settings", "de": "In-App-Einstellungen",
        "es": "Ajustes de la aplicación", "fr": "Réglages intégrés",
        "ja": "アプリ内設定", "ko": "앱 내 설정"},
    # ---------- 清单尾标 + 步骤壳（t("字面量")，AST 护栏会卡） ----------
    "免配": {
        "en": "No setup", "de": "Keine Einrichtung",
        "es": "Sin configuración", "fr": "Aucun réglage",
        "ja": "設定不要", "ko": "설정 불필요"},
    "设以下环境变量": {
        "en": "Set these environment variables",
        "de": "Setzen Sie diese Umgebungsvariablen",
        "es": "Define estas variables de entorno",
        "fr": "Définis ces variables d'environnement",
        "ja": "次の環境変数を設定してください",
        "ko": "다음 환경 변수를 설정하세요"},
    "打开配置文件 {file}": {
        "en": "Open the config file {file}",
        "de": "Öffnen Sie die Konfigurationsdatei {file}",
        "es": "Abre el archivo de configuración {file}",
        "fr": "Ouvre le fichier de configuration {file}",
        "ja": "設定ファイル {file} を開いてください",
        "ko": "설정 파일 {file}을 열어 주세요"},
    "照下面填，Key 用本页顶部的接入令牌": {
        "en": "Fill it in as shown below; use the access token at the top "
             "of this page as the Key",
        "de": "Füllen Sie es wie unten gezeigt aus; als Key nutzen Sie das "
             "Zugangstoken oben auf dieser Seite",
        "es": "Rellénalo como se muestra; como Key usa el token de acceso "
              "de arriba de esta página",
        "fr": "Remplis comme indiqué ci-dessous ; pour la Key, utilise le "
              "jeton d'accès affiché en haut de la page",
        "ja": "下のように記入してください。Key にはこのページ上部のアクセ"
              "ストークンを使ってください",
        "ko": "아래와 같이 채우세요. Key에는 이 페이지 상단의 접근 토큰을 "
             "사용하세요"},
    "重启该工具，回本页在「已接入」里看到它，就接好了": {
        "en": "Restart the tool; once it appears under \"Connected\" on "
             "this page, you're all set",
        "de": "Starten Sie das Tool neu; sobald es auf dieser Seite unter "
             "„Verbunden“ erscheint, hat alles geklappt",
        "es": "Reinicia la herramienta; cuando la veas en «Conectadas» de "
              "esta página, ya está",
        "fr": "Redémarre l’outil ; quand il apparaît dans « Connectés » "
              "sur cette page, c’est gagné",
        "ja": "ツールを再起動し、このページの「接続済み」に表示されれば"
              "完了です",
        "ko": "도구를 재시작한 뒤 이 페이지의 '연결됨'에 보이면 "
             "완료입니다"},
    "在工具里打开「设置 → 模型」，添加自定义模型": {
        "en": "Open Settings → Models in the tool and add a custom model",
        "de": "Öffnen Sie im Tool „Einstellungen → Modelle“ und fügen Sie "
             "ein eigenes Modell hinzu",
        "es": "Abre «Ajustes → Modelos» en la herramienta y añade un "
              "modelo propio",
        "fr": "Ouvre « Réglages → Modèles » dans l’outil et ajoute un "
              "modèle personnalisé",
        "ja": "ツールで「設定 → モデル」を開き、カスタムモデルを"
              "追加してください",
        "ko": "도구에서 '설정 → 모델'을 열고 사용자 지정 모델을 "
             "추가하세요"},
    "保存后立即生效": {
        "en": "Takes effect as soon as you save",
        "de": "Nach dem Speichern sofort wirksam",
        "es": "Se aplica en cuanto guardes",
        "fr": "Effectif dès l’enregistrement",
        "ja": "保存するとすぐに有効になります",
        "ko": "저장하면 바로 적용됩니다"},
}


def main() -> int:
    check_entries(E)
    apply_entries(E)
    return 0


if __name__ == "__main__":
    sys.exit(main())
