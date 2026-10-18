# -*- coding: utf-8 -*-
"""一次性补齐脚本：8100 默认鉴权改动涉及的接入页词条。

- 7 条分工具说明改串（"填任意非空值" → "填本页的接入令牌"）；
- 3 条新串（令牌行标签 / 提示 / 复制按钮）。
旧 msgid 留在 .po 里无害（下轮 pybabel extract/update 自然清理）。

用法：uv run python scripts/i18n_h4_proxy_token_entries.py
补完后跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=tú、fr=撇号 ’、ko=합니다체+''、非 CJK 禁全角括号（ja 除外）。
"""

from __future__ import annotations

import sys

from i18n_entry_lib import apply_entries, check_entries

E: dict[str, dict[str, str]] = {
    # ---------- 分工具说明（改串） ----------
    ("把环境变量 ANTHROPIC_BASE_URL 指到上面的地址（ANTHROPIC_API_KEY 填本页的"
     "接入令牌；真正生效的 Key 是你在 Experientia 里配的模型）。"): {
        "en": ("Point the ANTHROPIC_BASE_URL environment variable at the address "
               "above (set ANTHROPIC_API_KEY to this page's access token; the key "
               "that actually talks upstream is the model you configured in "
               "Experientia)."),
        "de": ("Zeigen Sie mit der Umgebungsvariable ANTHROPIC_BASE_URL auf die "
               "Adresse oben (als ANTHROPIC_API_KEY tragen Sie das Zugangstoken "
               "dieser Seite ein; der wirklich wirksame Schlüssel ist das Modell, "
               "das Sie in Experientia konfiguriert haben)."),
        "es": ("Apunte la variable ANTHROPIC_BASE_URL a la dirección de arriba "
               "(en ANTHROPIC_API_KEY ponga el token de acceso de esta página; la "
               "clave que de verdad actúa es el modelo que configure en Experientia)."),
        "fr": ("Pointez la variable d'environnement ANTHROPIC_BASE_URL vers "
               "l'adresse ci-dessus (mettez le jeton d'accès de cette page dans "
               "ANTHROPIC_API_KEY ; la clé réellement effective est le modèle "
               "configuré dans Experientia)."),
        "ja": ("環境変数 ANTHROPIC_BASE_URL を上のアドレスへ向けてください"
               "（ANTHROPIC_API_KEY には本ページの接続トークンを設定；実際に効く "
               "Key は Experientia で設定したモデルです）。"),
        "ko": ("환경 변수 ANTHROPIC_BASE_URL을 위 주소로 지정하세요"
               "(ANTHROPIC_API_KEY에는 이 페이지의 연결 토큰을 입력; 실제로 "
               "동작하는 Key는 Experientia에 설정한 모델입니다)."),
    },
    ("在 ~/.codebuddy/models.json 的 models 里加一条模型，url 填 "
     "http://127.0.0.1:8100/v1/chat/completions（必须是完整接口路径），"
     "apiKey 填本页的接入令牌。"): {
        "en": ("In ~/.codebuddy/models.json, add a model under models with url "
               "http://127.0.0.1:8100/v1/chat/completions (the full endpoint path "
               "is required) and apiKey set to this page's access token."),
        "de": ("Fügen Sie in ~/.codebuddy/models.json unter models ein Modell "
               "hinzu: url = http://127.0.0.1:8100/v1/chat/completions "
               "(vollständiger Pfad nötig), apiKey = das Zugangstoken dieser Seite."),
        "es": ("En ~/.codebuddy/models.json, añada un modelo en «models» con url "
               "http://127.0.0.1:8100/v1/chat/completions (ruta completa "
               "obligatoria) y apiKey con el token de acceso de esta página."),
        "fr": ("Dans ~/.codebuddy/models.json, ajoutez un modèle dans « models » "
               "avec url http://127.0.0.1:8100/v1/chat/completions (chemin complet "
               "obligatoire) et apiKey égal au jeton d'accès de cette page."),
        "ja": ("~/.codebuddy/models.json の models にモデルを 1 つ追加：url は "
               "http://127.0.0.1:8100/v1/chat/completions（完全なインターフェース"
               "パス必須）、apiKey には本ページの接続トークンを設定。"),
        "ko": ("~/.codebuddy/models.json의 models에 모델을 하나 추가하세요. url은 "
               "http://127.0.0.1:8100/v1/chat/completions(전체 엔드포인트 경로 "
               "필수), apiKey에는 이 페이지의 연결 토큰을 입력합니다."),
    },
    ("在项目 opencode.json 加自定义 provider：npm 用 "
     "@ai-sdk/openai-compatible，options.baseURL 填上面的地址再加 /v1，"
     "apiKey 填本页的接入令牌，模型 ID 填你配的模型名；它的会话可自动记录，"
     "见下方「采集」。（模型列表见 /v1/models）"): {
        "en": ("In the project's opencode.json add a custom provider: npm "
               "@ai-sdk/openai-compatible, options.baseURL = the address above "
               "plus /v1, apiKey = this page's access token, model ID = the model "
               "name you configured; its sessions are recorded automatically (see "
               "Capture below). (Model list: /v1/models)"),
        "de": ("Ergänzen Sie im Projekt in opencode.json einen eigenen Provider: "
               "npm @ai-sdk/openai-compatible, options.baseURL = Adresse oben plus "
               "/v1, apiKey = Zugangstoken dieser Seite, Modell-ID = Ihr "
               "konfigurierter Modellname; Sitzungen werden automatisch erfasst "
               "(siehe „Erfassung“ unten). (Modellliste: /v1/models)"),
        "es": ("Añada en el opencode.json del proyecto un proveedor "
               "personalizado: npm @ai-sdk/openai-compatible, options.baseURL = la "
               "dirección de arriba + /v1, apiKey = el token de acceso de esta "
               "página, ID de modelo = el nombre que configuró; sus sesiones se "
               "registran solas (vea «Captura» más abajo). (Lista de modelos: "
               "/v1/models)"),
        "fr": ("Dans le opencode.json du projet, ajoutez un fournisseur "
               "personnalisé : npm @ai-sdk/openai-compatible, options.baseURL = "
               "l'adresse ci-dessus + /v1, apiKey = le jeton d'accès de cette "
               "page, ID de modèle = le nom configuré ; ses sessions sont "
               "enregistrées automatiquement (voir « Collecte »). (Liste des "
               "modèles : /v1/models)"),
        "ja": ("プロジェクトの opencode.json にカスタム provider を追加：npm は "
               "@ai-sdk/openai-compatible、options.baseURL は上のアドレスに /v1 を"
               "足したもの、apiKey は本ページの接続トークン、モデル ID は設定した"
               "モデル名；セッションは自動で記録されます（下の「収集」を参照）。"
               "（モデル一覧は /v1/models）"),
        "ko": ("프로젝트의 opencode.json에 자체 provider를 추가하세요: npm은 "
               "@ai-sdk/openai-compatible, options.baseURL은 위 주소에 /v1을 붙인 "
               "것, apiKey는 이 페이지의 연결 토큰, 모델 ID는 설정한 모델명; "
               "세션은 자동으로 기록됩니다(아래 '수집' 참조). (모델 목록은 "
               "/v1/models)"),
    },
    ("把环境变量 DEEPSEEK_BASE_URL 指到上面的地址（或在配置里设 baseURL），"
     "Key 填本页的接入令牌。"): {
        "en": ("Point the DEEPSEEK_BASE_URL environment variable at the address "
               "above (or set baseURL in the config), with the key set to this "
               "page's access token."),
        "de": ("Zeigen Sie mit DEEPSEEK_BASE_URL auf die Adresse oben (oder "
               "setzen Sie baseURL in der Konfiguration); als Schlüssel das "
               "Zugangstoken dieser Seite."),
        "es": ("Apunte DEEPSEEK_BASE_URL a la dirección de arriba (o defina "
               "baseURL en la configuración), con la clave puesta en el token de "
               "acceso de esta página."),
        "fr": ("Pointez DEEPSEEK_BASE_URL vers l'adresse ci-dessus (ou définissez "
               "baseURL dans la config), avec comme clé le jeton d'accès de cette "
               "page."),
        "ja": ("環境変数 DEEPSEEK_BASE_URL を上のアドレスへ（または設定で "
               "baseURL を指定）、Key には本ページの接続トークンを設定。"),
        "ko": ("환경 변수 DEEPSEEK_BASE_URL을 위 주소로 지정하세요(설정에서 "
               "baseURL도 가능), Key에는 이 페이지의 연결 토큰을 입력합니다."),
    },
    ("在配置里加一个自定义 provider（models.providers 下）：baseUrl 填上面的地址、"
     "api 选 openai-completions、Key 填本页的接入令牌，再选它作为模型。"): {
        "en": ("Add a custom provider under models.providers in the config: "
               "baseUrl = the address above, api = openai-completions, key = this "
               "page's access token, then select it as the model."),
        "de": ("Fügen Sie in der Konfiguration unter models.providers einen "
               "eigenen Provider hinzu: baseUrl = Adresse oben, api = "
               "openai-completions, Schlüssel = Zugangstoken dieser Seite, dann "
               "als Modell auswählen."),
        "es": ("Añada un proveedor personalizado en models.providers de la "
               "configuración: baseUrl = la dirección de arriba, api = "
               "openai-completions, clave = el token de acceso de esta página; "
               "luego selecciónelo como modelo."),
        "fr": ("Ajoutez un fournisseur personnalisé sous models.providers dans la "
               "config : baseUrl = l'adresse ci-dessus, api = openai-completions, "
               "clé = le jeton d'accès de cette page, puis choisissez-le comme "
               "modèle."),
        "ja": ("設定の models.providers にカスタム provider を追加：baseUrl は上の"
               "アドレス、api は openai-completions、Key は本ページの接続トークン、"
               "その後それでモデルを選択。"),
        "ko": ("설정의 models.providers 아래 자체 provider를 추가하세요: baseUrl은 "
               "위 주소, api는 openai-completions, Key는 이 페이지의 연결 토큰, "
               "그 다음 이를 모델로 선택합니다."),
    },
    ("在 ~/.hermes/.env 里设 OPENAI_BASE_URL 为上面的地址，OPENAI_API_KEY "
     "填本页的接入令牌（或在 hermes model 里选 Custom endpoint）。"): {
        "en": ("In ~/.hermes/.env set OPENAI_BASE_URL to the address above and "
               "OPENAI_API_KEY to this page's access token (or pick a custom "
               "endpoint in hermes model)."),
        "de": ("Setzen Sie in ~/.hermes/.env OPENAI_BASE_URL auf die Adresse oben "
               "und OPENAI_API_KEY auf das Zugangstoken dieser Seite (oder wählen "
               "Sie in hermes model einen eigenen Endpoint)."),
        "es": ("En ~/.hermes/.env, ponga OPENAI_BASE_URL en la dirección de arriba "
               "y OPENAI_API_KEY en el token de acceso de esta página (o elija un "
               "endpoint personalizado con hermes model)."),
        "fr": ("Dans ~/.hermes/.env, mettez OPENAI_BASE_URL sur l'adresse "
               "ci-dessus et OPENAI_API_KEY sur le jeton d'accès de cette page (ou "
               "choisissez un endpoint personnalisé dans hermes model)."),
        "ja": ("~/.hermes/.env で OPENAI_BASE_URL を上のアドレスに、"
               "OPENAI_API_KEY に本ページの接続トークンを設定（または hermes "
               "model で Custom endpoint を選択）。"),
        "ko": ("~/.hermes/.env에서 OPENAI_BASE_URL을 위 주소로, OPENAI_API_KEY에 "
               "이 페이지의 연결 토큰을 입력하세요(또는 hermes model에서 Custom "
               "endpoint 선택)."),
    },
    ("设置 → 模型 → 添加自定义模型：URL 填上面的地址、Key 填本页的接入令牌、"
     "模型名任选。"): {
        "en": ("Settings → Models → Add custom model: URL = the address above, "
               "Key = this page's access token, model name up to you."),
        "de": ("Einstellungen → Modelle → Eigenes Modell hinzufügen: URL = "
               "Adresse oben, Schlüssel = Zugangstoken dieser Seite, Modellname "
               "frei wählbar."),
        "es": ("Ajustes → Modelos → Añadir modelo personalizado: URL = la "
               "dirección de arriba, clave = el token de acceso de esta página, "
               "nombre de modelo al gusto."),
        "fr": ("Paramètres → Modèles → Ajouter un modèle personnalisé : URL = "
               "l'adresse ci-dessus, clé = le jeton d'accès de cette page, nom du "
               "modèle au choix."),
        "ja": ("設定 → モデル → カスタムモデル追加：URL は上のアドレス、Key は"
               "本ページの接続トークン、モデル名は自由に。"),
        "ko": ("설정 → 모델 → 사용자 지정 모델 추가: URL은 위 주소, Key는 이 "
               "페이지의 연결 토큰, 모델명은 자유롭게."),
    },
    # ---------- 令牌行（新串） ----------
    "接入令牌：{tok}": {
        "en": "Access token: {tok}",
        "de": "Zugangstoken: {tok}",
        "es": "Token de acceso: {tok}",
        "fr": "Jeton d'accès : {tok}",
        "ja": "接続トークン：{tok}",
        "ko": "연결 토큰: {tok}",
    },
    ("外部 agent 接 8100 时，apiKey / API_KEY / x-api-key 填这个令牌；"
     "填错会被拒绝"): {
        "en": ("When an external agent connects to 8100, set its apiKey / "
               "API_KEY / x-api-key to this token — a wrong one is rejected."),
        "de": ("Wenn ein externer Agent 8100 verbindet, tragen Sie dieses Token "
               "als apiKey / API_KEY / x-api-key ein – ein falsches wird "
               "abgelehnt."),
        "es": ("Cuando un agente externo se conecte a 8100, use este token como "
               "apiKey / API_KEY / x-api-key; si es incorrecto, se rechazará."),
        "fr": ("Quand un agent externe se connecte au 8100, utilisez ce jeton "
               "comme apiKey / API_KEY / x-api-key ; un jeton erroné sera refusé."),
        "ja": ("外部 agent が 8100 に接続する際は apiKey / API_KEY / x-api-key に"
               "このトークンを設定；間違えると拒否されます"),
        "ko": ("외부 agent가 8100에 연결할 때는 apiKey / API_KEY / x-api-key에 이 "
               "토큰을 입력하세요; 틀리면 거부됩니다"),
    },
    "复制令牌": {
        "en": "Copy token", "de": "Token kopieren", "es": "Copiar token",
        "fr": "Copier le jeton", "ja": "トークンをコピー", "ko": "토큰 복사",
    },
}


def main() -> int:
    check_entries(E)
    apply_entries(E)
    return 0


if __name__ == "__main__":
    sys.exit(main())
