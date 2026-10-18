# -*- coding: utf-8 -*-
"""补齐「周报无模型降级」的结算卡引导段 + 成就展示名到 7 语 .po。

用法：uv run python scripts/i18n_weekly_gate_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。

为什么不重抽：冻结的是「重抽」（并行波次各自 xgettext 会互相覆盖），本项目
一贯用增量脚本只补缺失 msgid、不动既有译文——见 scripts/i18n_*_entries.py 系列。

成就展示名（`ACH_NAME` 的 3 个值）为什么也得进来：它们以 params 塞进
`"{name}解锁了：…"`，`localize` 只对这类值单独过 `tf`（见 growth_story._slot），
词典里没有就是孤零零一个中文名挂在英文句子里。

语体规范：de=Sie+„“、es=tú+«»、fr=撇号 ’+«»、ko=합니다체+''、
非 CJK 语言禁全角括号与残留汉字（_check 自检）。
展示名的目标句型是「{name} unlocked」这类前置标签，一律用名词语感，不带句尾。
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

# 对应 app/distill/growth_story.py 的 GATE_* 常量（叙事展示串的唯一生产者）。
# 「去接入」早先已补过，脚本遇到已存在的 msgid 会跳过，留在这里是为了与代码
# 常量一一对应，便于后来人对账。
E: dict[str, dict[str, str]] = {
    "统计都在，故事要等模型接上": {
        "en": "All the stats are here — the story waits for a model",
        "de": "Alle Zahlen sind da – die Geschichte wartet auf ein Modell",
        "es": "Las cifras están todas; la historia espera a que conectes un modelo",
        "fr": "Toutes les stats sont là — l’histoire attend un modèle",
        "ja": "数字はすべて揃っています——物語はモデルの接続待ちです",
        "ko": "통계는 모두 있습니다 — 이야기는 모델 연결을 기다립니다"},
    ("接上模型后，这里会多一段叙事：这周怎么变顺的、哪条经验在变强。下面这些数是"
     "实打实干出来的，不靠模型。"): {
        "en": ("Connect a model and a story shows up here: how this week got "
               "smoother, which lesson is getting stronger. The numbers below "
               "are real work — they don’t need a model."),
        "de": ("Sobald ein Modell verbunden ist, erscheint hier eine Geschichte: "
               "wie diese Woche reibungsloser wurde, welche Erfahrung an Kraft "
               "gewinnt. Die Zahlen unten sind echte Arbeit – sie brauchen kein "
               "Modell."),
        "es": ("Conecta un modelo y aquí aparecerá una historia: cómo fue más "
               "fluida esta semana, qué experiencia está ganando fuerza. Las "
               "cifras de abajo son trabajo real, no dependen del modelo."),
        "fr": ("Connectez un modèle et une histoire apparaîtra ici : comment la "
               "semaine est devenue plus fluide, quelle expérience gagne en "
               "force. Les chiffres ci-dessous sont du vrai travail — ils ne "
               "dépendent pas du modèle."),
        "ja": ("モデルを接続すると、ここに物語が加わります：今週どう滑らかになったか、"
               "どの経験が強くなっているか。下の数字は実際にやった仕事そのもので、"
               "モデルがなくても出ています。"),
        "ko": ("모델을 연결하면 이 자리에 이야기가 생깁니다: 이번 주가 어떻게 더 "
               "수월해졌는지, 어떤 경험이 힘을 얻고 있는지. 아래 숫자는 실제로 해낸 "
               "작업 그대로이며 모델 없이도 나옵니다.")},
    "去接入": {"en": "Connect now", "de": "Jetzt verbinden",
             "es": "Conectar ahora", "fr": "Connecter maintenant",
             "ja": "接続する", "ko": "지금 연결"},
    "统计照常算，故事等模型恢复": {
        "en": "Stats still count — the story waits for the model to recover",
        "de": "Zahlen laufen weiter – die Geschichte wartet auf das Modell",
        "es": "Las cifras siguen contando; la historia espera a que el modelo vuelva",
        "fr": "Les stats continuent — l’histoire attend le retour du modèle",
        "ja": "統計はそのまま算出、物語はモデルの復帰待ち",
        "ko": "통계는 그대로 계산되고, 이야기는 모델 복구를 기다립니다"},
    "{endpoint} 最近没响应。统计照常算，叙事等模型恢复再补。": {
        "en": ("{endpoint} hasn’t responded lately. Stats still count; the story "
               "is added once the model is back."),
        "de": ("{endpoint} antwortet seit Kurzem nicht. Die Zahlen laufen weiter "
               "– die Geschichte wird nachgeliefert, sobald das Modell wieder "
               "da ist."),
        "es": ("{endpoint} no responde últimamente. Las cifras siguen; la "
               "historia se añadirá cuando el modelo vuelva."),
        "fr": ("{endpoint} ne répond plus depuis peu. Les stats continuent ; "
               "l’histoire sera ajoutée dès le retour du modèle."),
        "ja": ("{endpoint} が最近応答しません。統計はそのまま算出され、物語は"
               "モデルの復帰後に追記されます。"),
        "ko": ("{endpoint} 이 최근 응답하지 않습니다. 통계는 그대로 계산되고, "
               "이야기는 모델이 돌아오면 채워집니다.")},
    "去检查": {"en": "Go check", "de": "Prüfen", "es": "Revisar",
             "fr": "Vérifier", "ja": "確認する", "ko": "확인하기"},

    # ---------- 成就展示名（ACH_NAME）：拼进「{name} unlocked」的名词语感 ----------
    "老练": {"en": "Seasoned", "de": "Routinier", "es": "Veterano",
            "fr": "Chevronné", "ja": "老練", "ko": "노련함"},
    "避坑达人": {"en": "Pitfall dodger", "de": "Fallstrick-Vermeider",
              "es": "Esquivatrampas", "fr": "Évite-pièges",
              "ja": "落とし穴回避", "ko": "함정 회피"},
    "传承": {"en": "Legacy", "de": "Weitergabe", "es": "Legado",
            "fr": "Transmission", "ja": "伝承", "ko": "전승"},
}


def _check() -> None:
    """语体自检：拉丁语零 CJK / 占位符一致 / 无空译文 / 无省略号残句。"""
    for mid, table in E.items():
        ph = set(re.findall(r"\{(\w+)(?::\w+)?\}", mid))
        for lang, text in table.items():
            assert text.strip(), f"{lang} 空译文: {mid[:20]}"
            assert "…" not in text, f"{lang} 疑似半截句: {mid[:20]}"
            got = set(re.findall(r"\{(\w+)(?::\w+)?\}", text))
            assert got == ph, \
                f"{lang} 占位符不符 {mid[:24]}: {sorted(ph)} vs {sorted(got)}"
            if lang in LATIN:
                bad = [c for c in text if "一" <= c <= "鿿"]
                assert not bad, f"{lang} 残留汉字 {mid[:24]}: {bad[:6]}"
                assert "（" not in text and "）" not in text, \
                    f"{lang} 出现全角括号: {mid[:24]}"


def main() -> int:
    _check()
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
