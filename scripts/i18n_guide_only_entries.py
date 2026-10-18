# -*- coding: utf-8 -*-
"""一次性补齐脚本（移除自动更新）：纯导向文案词条。

用法：uv run python scripts/i18n_guide_only_entries.py
补完后跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+„“、es=usted、fr=撇号 ’、ko=하세/합니다체+''、非 CJK 禁全角括号（ja 除外）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "app" / "gui" / "locales"
LANGS = ["de", "en", "es", "fr", "ja", "ko", "zh"]

E: dict[str, dict[str, str]] = {
    "有新版本时提示我，去仓库下载": {
        "en": ("Notify me when a new version is available and point me to the "
               "repository to download it"),
        "de": ("Mich benachrichtigen, wenn eine neue Version verfügbar ist, "
               "und zum Download ins Repository führen"),
        "es": ("Avisarme cuando haya una nueva versión y dirigirme al "
               "repositorio para descargarla"),
        "fr": ("Me prévenir lorsqu’une nouvelle version est disponible et "
               "m’orienter vers le dépôt pour la télécharger"),
        "ja": ("新しいバージョンがある場合に通知し、ダウンロードはリポジトリへ案内します"),
        "ko": ("새 버전이 있으면 알려주고 다운로드를 위해 저장소로 안내합니다"),
    },
    "本应用不会自动更新，请到项目仓库下载并安装。": {
        "en": ("This app never updates automatically — please download and "
               "install it from the project repository."),
        "de": ("Diese App aktualisiert sich nie automatisch – bitte laden Sie "
               "sie aus dem Projekt-Repository herunter und installieren Sie sie."),
        "es": ("Esta aplicación nunca se actualiza automáticamente: "
               "descárguela e instálela desde el repositorio del proyecto."),
        "fr": ("Cette application ne se met jamais à jour automatiquement — "
               "veuillez la télécharger et l’installer depuis le dépôt du projet."),
        "ja": ("このアプリは自動更新しません。プロジェクトのリポジトリから"
               "ダウンロードしてインストールしてください。"),
        "ko": ("이 앱은 자동으로 업데이트되지 않습니다. 프로젝트 저장소에서 "
               "다운로드하여 설치하세요."),
    },
    "打开仓库下载更新": {
        "en": "Open repository to download update",
        "de": "Repository zum Download öffnen",
        "es": "Abrir repositorio para descargar",
        "fr": "Ouvrir le dépôt pour télécharger",
        "ja": "リポジトリを開いて更新をダウンロード",
        "ko": "저장소를 열어 업데이트 다운로드",
    },
    "仓库尚未发布安装包，请到仓库查看更新方式。": {
        "en": "No installer has been published yet — check the repository for how to update.",
        "de": ("Noch kein Installationspaket veröffentlicht – bitte entnehmen "
               "Sie dem Repository, wie Sie aktualisieren."),
        "es": ("Aún no se ha publicado ningún instalador: consulte en el "
               "repositorio cómo actualizar."),
        "fr": ("Aucun installeur n’a encore été publié — consultez le dépôt "
               "pour savoir comment mettre à jour."),
        "ja": ("インストーラーはまだ公開されていません。更新方法はリポジトリで"
               "ご確認ください。"),
        "ko": ("설치 패키지가 아직 공개되지 않았습니다. 업데이트 방법은 "
               "저장소에서 확인하세요."),
    },
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
            with po.open("wb") as fh:  # 字节写：保留 LF，防 Windows 换行二次转换
                write_po(fh, catalog, width=0)
        print(f"[{lang}] 新增 {added} 条")
        added_total += added
    print(f"合计 {added_total} 条——记得跑 scripts/compile_locales.py 重编译 .mo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
