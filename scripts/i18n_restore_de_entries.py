# -*- coding: utf-8 -*-
"""一次性补齐脚本：把 de.po 被写空后从 HEAD 恢复所丢失的 15 个在飞
词条回补进德语 .po（已存在则跳过）。德文用语规范：Sie 式、„" 引号、非 CJK 禁全角括号。

用法：.venv/Scripts/python.exe scripts/i18n_restore_de_entries.py
补完后跑 scripts/compile_locales.py 重编译 .mo。
"""
from __future__ import annotations

import sys
from pathlib import Path

from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parent.parent
PO = ROOT / "app" / "gui" / "locales" / "de" / "LC_MESSAGES" / "messages.po"

# msgid: msgstr（de）
E: dict[str, str] = {
    "Experientia 添加的": "Von Experientia hinzugefügt",
    "不再自动使用，经验仍保留":
        "Wird nicht mehr automatisch verwendet; die Erfahrung bleibt erhalten",
    "使用权重降半，预算紧张时先被截掉":
        "Wird mit halber Gewichtung verwendet; bei knappem Budget zuerst gekürzt",
    "全部移除 Experientia 添加的": "Alle von Experientia hinzugefügten entfernen",
    "工具触发事件时跑的命令，含它们原本就有的和 Experientia 添加的；可逐条开关、编辑、删除、AI 解释，也能新增一条。":
        "Befehle, die beim Auslösen von Ereignissen laufen – einschließlich derer, "
        "die das Werkzeug schon hatte, und derer, die Experientia hinzugefügt hat. "
        "Jede kann einzeln geschaltet, bearbeitet, gelöscht oder von der KI erklärt "
        "werden, und Sie können eine neue hinzufügen.",
    "已恢复到正常使用": "Zurück zur normalen Verwendung",
    "当某条经验被反复用错，会自动出现在这里，供你查看或恢复":
        "Wenn eine Erfahrung wiederholt falsch verwendet wird, erscheint sie hier "
        "zur Einsicht oder Wiederherstellung",
    "恢复使用": "Verwendung wiederherstellen",
    "未连接": "Nicht verbunden",
    "经验已用上 {n} 次；样本攒够后第 ⑤ 格会给出同类任务的返工对比。":
        "Erfahrung {n} Mal verwendet; bei genug Beispielen zeigt Feld ⑤ den "
        "Nacharbeitsvergleich für ähnliche Aufgaben.",
    "经验自动送达还没装上——装上 Claude Code 连接，或把助手的接口地址指向 {url}":
        "Automatische Zustellung ist noch nicht eingerichtet – installieren Sie "
        "den Claude-Code-Hook oder richten Sie die Schnittstelle Ihres Assistenten "
        "auf {url}",
    "被系统判断反复用错的经验，已降权或停用；证真后自动回归，也可在这里手动恢复":
        "Als wiederholt falsch verwendete eingestufte Erfahrungen werden abgestuft "
        "oder pausiert; sie kehren automatisch zurück, wenn sie sich bewähren, und "
        "können hier manuell wiederhergestellt werden",
    "被系统反复判定用错而降权/停用的经验，可查看并恢复":
        "Wiederholt als falsch verwendet eingestufte, abgestufte oder pausierte "
        "Erfahrungen; hier einsehen und wiederherstellen",
    "连接脚本已装上，但助手一次都没用过——从那类工具发起一次会话就会开始记":
        "Der Hook ist installiert, wurde aber von Ihrem Assistenten noch nie "
        "verwendet – starten Sie dort eine Sitzung, dann beginnt die Aufzeichnung",
    "送达通道已通，但还没有经验真正用上（可能还没有可归类的经验）":
        "Der Zustellkanal steht, aber noch keine Erfahrung wurde wirklich verwendet "
        "(vielleicht gibt es noch nichts Kategorisierbares)",
}


def main() -> int:
    with PO.open(encoding="utf-8") as fh:
        catalog = read_po(fh, locale="de")
    added = skipped = 0
    for msgid, msgstr in E.items():
        existing = catalog.get(msgid)
        if existing is not None and existing.string:
            skipped += 1
            continue
        catalog.add(id=msgid, string=msgstr)
        added += 1
    # write_po 写 bytes——必须二进制句柄（踩过文本句柄写空 po 的坑）
    with PO.open("wb") as fh:
        write_po(fh, catalog, width=0)
    print(f"de: added {added}, skipped {skipped} -> {PO.relative_to(ROOT)}")
    print("next: .venv/Scripts/python.exe scripts/compile_locales.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
