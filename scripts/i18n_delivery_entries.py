# -*- coding: utf-8 -*-
"""补齐「送达通道记账 + 第④格诊断」新增词条到 7 语 .po。

用法：uv run python scripts/i18n_delivery_entries.py
补完必须跑 scripts/compile_locales.py 重编译 .mo。
语体规范同 i18n_poster_entries.py：de=Sie+„“、es=tú+«»、fr=’+«»、
ko=합니다체+''、非 CJK 禁全角括号与残留汉字（脚本自检）。
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
    # ---------- 里程碑（growth_story ACH_HIT*） ----------
    "{name}解锁了": {"en": "{name} unlocked", "de": "{name} freigeschaltet",
                "es": "{name} desbloqueado", "fr": "{name} débloqué",
                "ja": "{name} を解除", "ko": "{name} 해제됨"},
    "{name}解锁了：{agent}": {"en": "{name} unlocked: {agent}",
                         "de": "{name} freigeschaltet: {agent}",
                         "es": "{name} desbloqueado: {agent}",
                         "fr": "{name} débloqué : {agent}",
                         "ja": "{name} を解除：{agent}",
                         "ko": "{name} 해제: {agent}"},
    "{name}解锁了：{agent} 的「{who}」": {
        "en": "{name} unlocked: {agent} · {who}",
        "de": "{name} freigeschaltet: {agent} · {who}",
        "es": "{name} desbloqueado: {agent} · {who}",
        "fr": "{name} débloqué : {agent} · {who}",
        "ja": "{name} を解除：{agent}「{who}」",
        "ko": "{name} 해제: {agent} · {who}"},
    # ---------- 类别判据加项 ----------
    "『{who}』平均比最初几次少 {n} 轮修正": {
        "en": "“{who}” takes {n} fewer rounds on average than at first",
        "de": "„{who}“: {n} Runden weniger als anfangs",
        "es": "«{who}» necesita {n} rondas menos que al principio",
        "fr": "« {who} » demande {n} allers-retours de moins qu’au début",
        "ja": "『{who}』は最初より平均 {n} ラウンド少ない",
        "ko": "『{who}』는 처음보다 평균 {n}라운드 줄었습니다"},
    # ---------- 四问（growth_story Q_*） ----------
    "这周新固化 {n} 条坑：{who}": {
        "en": "{n} pitfalls locked in this week: {who}",
        "de": "{n} Fallstricke diese Woche verankert: {who}",
        "es": "{n} tropiezos fijados esta semana: {who}",
        "fr": "{n} écueils ancrés cette semaine : {who}",
        "ja": "今週 {n} 件の落とし穴を固定：{who}",
        "ko": "이번 주 함정 {n}개 고정: {who}"},
    "『{who}』这周被自动带上 {n} 次": {
        "en": "“{who}” was auto-attached {n} times this week",
        "de": "„{who}“ wurde diese Woche {n} Mal automatisch beigefügt",
        "es": "«{who}» se adjuntó solo {n} veces esta semana",
        "fr": "« {who} » a été joint automatiquement {n} fois cette semaine",
        "ja": "『{who}』は今週 {n} 回自動で添付されました",
        "ko": "『{who}』가 이번 주 {n}회 자동으로 첨부됐습니다"},
    "从每次任务 {e} 回降到 {r} 回": {
        "en": "from {e} fixes per task down to {r}",
        "de": "von {e} auf {r} Korrekturen pro Aufgabe",
        "es": "de {e} correcciones por tarea a {r}",
        "fr": "de {e} à {r} corrections par tâche",
        "ja": "1 件 {e} 回 → {r} 回に減少",
        "ko": "작업당 {e}회에서 {r}회로 감소"},
    "有记录的周还不够多，先继续用助手干活": {
        "en": "Not enough recorded weeks yet — keep working with your assistants",
        "de": "Noch zu wenige aufgezeichnete Wochen – arbeiten Sie weiter damit",
        "es": "Aún faltan semanas registradas; sigue trabajando con el asistente",
        "fr": "Pas encore assez de semaines relevées — continuez à travailler ainsi",
        "ja": "記録のある週がまだ少ないので、まずは作業を続けてください",
        "ko": "기록된 주가 아직 부족해요, 계속 작업해 보세요"},
    "没有发现用错地方的情况": {
        "en": "Nothing was applied in the wrong place",
        "de": "Keine Fehlplatzierung festgestellt",
        "es": "No se usó nada donde no tocaba",
        "fr": "Rien n’a été appliqué au mauvais endroit",
        "ja": "場違いな使い方はありませんでした",
        "ko": "잘못 쓰인 곳은 없었습니다"},
    # ---------- 送达通道（growth_story DELIV_*） ----------
    "经验已送达助手 {n} 次（代理 {proxy} · hook {hook}）": {
        "en": "Experience reached your assistants {n} times "
             "(proxy {proxy} · hook {hook})",
        "de": "Erfahrungen {n} Mal an Assistenten übergeben "
             "(Proxy {proxy} · Hook {hook})",
        "es": "Las experiencias llegaron {n} veces a los asistentes "
             "(proxy {proxy} · hook {hook})",
        "fr": "Les expériences sont parvenues {n} fois aux assistants "
             "(proxy {proxy} · hook {hook})",
        "ja": "経験を {n} 回エージェントへ届けました（プロキシ {proxy} · hook {hook}）",
        "ko": "경험을 {n}회 어시스턴트에게 전달했습니다 (프록시 {proxy} · hook {hook})"},
    "自动回灌还没装上——装 Claude Code 回灌，或把助手的接口地址指到 {url}": {
        "en": "Auto-injection isn’t installed — install the Claude Code hook, "
             "or point your assistant’s endpoint at {url}",
        "de": "Automatische Rückgabe ist nicht installiert – installieren Sie den "
             "Claude-Code-Hook oder zeigen Sie mit der KI auf {url}",
        "es": "La inyección automática no está instalada: instala el hook de "
             "Claude Code o apunta el endpoint de tu asistente a {url}",
        "fr": "La réinjection automatique n’est pas installée — installez le hook "
             "Claude Code ou pointez l’endpoint de votre assistant vers {url}",
        "ja": "自動還元はまだ導入されていません。Claude Code の hook を入れるか、"
             "エージェントのエンドポイントを {url} に向けてください",
        "ko": "자동 주입이 아직 설치되지 않았어요 — Claude Code hook 을 설치하거나 "
              "어시스턴트 주소를 {url} 로 지정하세요"},
    "回灌脚本已装上，但助手一次都没回调过——从那类工具发起一次会话就会开始记": {
        "en": "The hook is installed but your assistant never called back — start "
             "one session from it and counting begins",
        "de": "Hook ist installiert, aber der Assistent meldete sich noch nie – "
             "starten Sie dort eine Sitzung, dann läuft die Zählung",
        "es": "El hook está instalado pero el asistente nunca llamó: abre una "
             "sesión desde él y empezará a contar",
        "fr": "Le hook est installé mais l’assistant n’a jamais rappelé — lancez-y "
             "une session et le comptage démarrera",
        "ja": "フックは導入済みですがエージェントから一度も回调がありません。"
             "そこから会話を一度始めると記録されます",
        "ko": "훅은 설치됐지만 어시스턴트 호출이 한 번도 없었어요 — 그 도구로 "
              "세션을 시작하면 기록됩니다"},
    "回灌通道已通，但还没有经验真正进入上下文（可能还没有可注入的归类）": {
        "en": "The channel is live, but no experience has entered a context yet "
             "(there may be nothing categorised to inject)",
        "de": "Kanal ist aktiv, aber noch ist keine Erfahrung in einen Kontext "
             "gelangt (möglicherweise gibt es noch keine Kategorisierung)",
        "es": "El canal funciona pero ninguna experiencia ha entrado en un "
             "contexto todavía (quizá no hay categorías que inyectar)",
        "fr": "Le canal est actif, mais aucune expérience n’est encore entrée dans "
             "un contexte (peut-être rien de classé à injecter)",
        "ja": "通道は通っていますが、まだ経験はコンテキストに入っていません"
             "（注入できる分類が無い可能性）",
        "ko": "통로는 열렸지만 아직 경험이 컨텍스트에 들어가지 않았어요 "
              "(주입할 분류가 없을 수 있습니다)"},
    # ---------- 欠账卡 / 主句 ----------
    "{n} 次已送达（代理 {p} · hook {h}）/ 需要 {need} 次，第 ⑤ 格才会有数字": {
        "en": "{n} delivered (proxy {p} · hook {h}) / {need} needed before "
             "step ⑤ shows a number",
        "de": "{n} übergeben (Proxy {p} · Hook {h}) / {need} nötig, damit Feld ⑤ "
             "eine Zahl zeigt",
        "es": "{n} entregadas (proxy {p} · hook {h}) / hacen falta {need} para "
             "que el paso ⑤ muestre un número",
        "fr": "{n} remises (proxy {p} · hook {h}) / il en faut {need} pour que la "
             "case ⑤ affiche un chiffre",
        "ja": "{n} 回届けました（プロキシ {p} · hook {h}）／{need} 回必要で "
             "⑤ に数が出ます",
        "ko": "{n}회 전달됨 (프록시 {p} · hook {h}) / {need}회는 되어야 ⑤ 에 "
              "숫자가 뜹니다"},
    "要你返工的次数，从每次 {e} 回降到 {r} 回": {
        "en": "You sent work back less often: {e} → {r} fixes per task",
        "de": "Nacharbeit seltener: {e} → {r} Korrekturen pro Aufgabe",
        "es": "Menos rehacer: de {e} a {r} correcciones por tarea",
        "fr": "Moins de retouches : de {e} à {r} corrections par tâche",
        "ja": "手戻りが 1 件 {e} 回 → {r} 回に減少",
        "ko": "재작업이 작업당 {e}회 → {r}회로 줄었습니다"},
    "还在攒样本：多做几次同类任务就能看出返工有没有变少": {
        "en": "Still collecting samples — a few more like tasks will show whether "
             "rework is dropping",
        "de": "Proben sammeln noch – einige ähnliche Aufgaben zeigen, ob die "
             "Nacharbeit sinkt",
        "es": "Siguiendo con muestras: unas cuantas tareas iguales dirán si el "
             "rehacer baja",
        "fr": "Échantillons en cours — quelques tâches semblables diront si les "
             "retouches baissent",
        "ja": "サンプルをためています。同種の作業をもう少しすれば手戻りの減少が "
             "分かります",
        "ko": "표본을 모으는 중입니다. 같은 작업을 몇 번 더 하면 재작업 감소가 "
              "보여요"},
    "去接上": {"en": "Connect it", "de": "Jetzt verbinden", "es": "Conectarlo",
            "fr": "Le brancher", "ja": "接続する", "ko": "연결하기"},
}


def _check() -> None:
    for mid, table in E.items():
        ph = set(re.findall(r"\{(\w+)\}", mid))
        for lang, text in table.items():
            assert text.strip(), f"{lang} 空译文: {mid[:20]}"
            got = set(re.findall(r"\{(\w+)\}", text))
            assert got == ph, f"{lang} 占位符不符 {mid[:24]}: {sorted(ph)} vs {sorted(got)}"
            if lang in LATIN:
                bad = [c for c in text if "一" <= c <= "鿿"]
                assert not bad, f"{lang} 残留汉字 {mid[:24]}: {bad[:6]}"
                assert "（" not in text and "）" not in text, f"{lang} 全角括号: {mid[:24]}"


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
