# -*- coding: utf-8 -*-
"""一次性补齐脚本：把新增的界面词条补进 7 语 .po（已存在则跳过）。

用法：.venv/Scripts/python.exe scripts/i18n_review_1014_entries.py
补完后照旧跑 scripts/compile_locales.py 重编译 .mo。
语体规范：de=Sie+"、es=tú、fr=撇号 '、ko=합니다체+''、非 CJK 禁全角括号（ja 除外）。
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
    "展开状态保存失败：{err}": {
        "en": "Failed to save expanded state: {err}",
        "de": "Speichern des Aufklapp-Zustands fehlgeschlagen: {err}",
        "es": "No se pudo guardar el estado desplegado: {err}",
        "fr": "Échec de l'enregistrement de l'état déployé : {err}",
        "ja": "展開状態の保存に失敗しました：{err}",
        "ko": "펼침 상태 저장 실패: {err}",
    },
    "引导页数据读取失败，显示默认状态": {
        "en": "Failed to load onboarding data — showing defaults",
        "de": "Onboarding-Daten konnten nicht geladen werden – Standardwerte "
              "werden angezeigt",
        "es": "No se pudieron cargar los datos de bienvenida: se muestran los "
              "valores por defecto",
        "fr": "Échec du chargement des données d'accueil – affichage des valeurs "
              "par défaut",
        "ja": "ガイドデータの読み込みに失敗しました——既定値を表示しています",
        "ko": "시작 안내 데이터 로드 실패——기본 상태를 표시합니다",
    },
    "采集开关设置失败：{err}": {
        "en": "Failed to change capture switch: {err}",
        "de": "Ändern des Aufzeichnung-Schalters fehlgeschlagen: {err}",
        "es": "No se pudo cambiar el interruptor de captura: {err}",
        "fr": "Échec du changement de l'interrupteur de capture : {err}",
        "ja": "記録スイッチの設定に失敗しました：{err}",
        "ko": "기록 스위치 설정 실패: {err}",
    },
    # 尾部（失败模式轨迹展开占位）
    "正在读取轨迹…": {
        "en": "Reading trajectory…",
        "de": "Verlauf wird gelesen…",
        "es": "Leyendo la trayectoria…",
        "fr": "Lecture de la trajectoire…",
        "ja": "軌跡を読み込み中…",
        "ko": "궤적 읽는 중…",
    },
    # 更换数据目录：主目录外目标的风险提示）
    "注意：这个位置在用户主目录之外（可能是移动盘或网络盘）——"
    "盘不在线时软件会读不到经验库。": {
        "en": "Note: this location is outside your home directory (possibly a "
              "removable or network drive) — the app can't reach your "
              "experience library while the drive is offline.",
        "de": "Hinweis: Dieser Ort liegt außerhalb Ihres Benutzerordners "
              "(möglicherweise ein Wechsel- oder Netzlaufwerk) — solange das "
              "Laufwerk nicht verbunden ist, kann die App Ihre "
              "Erfahrungsbibliothek nicht lesen.",
        "es": "Nota: esta ubicación está fuera de tu directorio personal "
              "(puede ser un disco extraíble o de red): con el disco "
              "desconectado la app no puede leer tu biblioteca de experiencias.",
        "fr": "Attention : cet emplacement est en dehors de votre dossier "
              "personnel (peut-être un disque amovible ou réseau) — quand le "
              "disque n'est pas connecté, l'app ne peut pas lire votre "
              "bibliothèque d'expériences.",
        "ja": "注意：この場所はユーザーホームの外です（リムーバブルドライブや"
              "ネットワークドライブの可能性があります）——ドライブが接続されて"
              "いないと、経験ライブラリを読めません。",
        "ko": "주의: 이 위치는 사용자 홈 디렉터리 밖입니다(이동식·네트워크 "
              "드라이브일 수 있음)——드라이브가 연결되어 있지 않으면 경험 "
              "라이브러리를 읽을 수 없습니다.",
    },
}


def main() -> int:
    added = skipped = 0
    for lang in LANGS:
        po_path = LOCALES / lang / "LC_MESSAGES" / "messages.po"
        with po_path.open(encoding="utf-8") as fh:
            catalog = read_po(fh, locale=lang)
        for msgid, table in E.items():
            existing = catalog.get(msgid)
            if existing is not None and existing.string:
                skipped += 1
                continue
            msgstr = msgid if lang == "zh" else table[lang]
            catalog.add(id=msgid, string=msgstr)
            added += 1
        # write_po 写的是 bytes——必须二进制句柄（文本句柄会 TypeError 且把
        # po 写空，踩过：de.po 被截断成 0 行）
        with po_path.open("wb") as fh:
            write_po(fh, catalog, width=0)
        print(f"{lang}: written {po_path.relative_to(ROOT)}")
    print(f"done: added {added}, skipped {skipped}")
    print("next: .venv/Scripts/python.exe scripts/compile_locales.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
