# -*- coding: utf-8 -*-
"""一次性修复：de.po 从 HEAD 恢复后带回了 14 条含内部术语的旧译文
（Injektion/Engine/Rückgabe——在飞工作已把这些中文键改名去术语并删除旧条目，
 test_ui_jargon_guard 守护）。本脚本：

1. 删除 14 个旧 msgid（产品代码与其余 6 语 .po 均已无这些键，属死条目）；
2. 修 2 个"键未变但译文含术语"的条目（与 en/fr/es 的在飞修正版对齐）。

用法：.venv/Scripts/python.exe scripts/i18n_fix_de_jargon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parent.parent
PO = ROOT / "app" / "gui" / "locales" / "de" / "LC_MESSAGES" / "messages.po"

# 在飞工作已改名/删除的旧 msgid（含术语译词）
DEAD = [
    "有 {n} 条你改过的内容，对应的方法条目已升级或淘汰，改动已失效",
    "这里看到的是每次任务自动带上的内容——开关和改写只改你改过的部分，不动方法原文",
    "全部移除 Experientia 注入",
    "工具触发事件时跑的命令，含它们原本就有的和 Experientia 注入的；可逐条开关、编辑、删除、AI 解释，也能新增一条。",
    "引擎未连接",
    "引擎运行中",
    "被系统判断反复用错的经验，注入已降权或停止；证真后自动回归，也可在这里手动恢复",
    "当某条注入经验被反复用错，会自动出现在这里，供你查看或恢复",
    "注入权重降半，预算紧张时先被截掉",
    "不再自动注入，经验仍保留",
    "恢复注入",
    "已恢复到正常注入",
    "回灌已跑通 {n} 次；样本攒够后第 ⑤ 格会给出同类任务的返工对比。",
    "自动回灌还没装上——装 Claude Code 回灌，或把助手的接口地址指到 {url}",
    # 以下 4 条德译文不含违禁词（术语守卫不报），但中文键已改名，同属死条目
    "Experientia 注入",
    "回灌脚本已装上，但助手一次都没回调过——从那类工具发起一次会话就会开始记",
    "回灌通道已通，但还没有经验真正进入上下文（可能还没有可注入的归类）",
    "被系统反复判定用错而降权/停注入的经验，可查看并恢复",
]

# 注意：前两条的 msgid 本身未改名（zh 仍在用），不能删——改为无术语译文。
# 其余 12 条：zh 键已改名，旧键是死条目，删除。
DEAD_DELETE = DEAD[2:]

FIX = {
    DEAD[0]: "{n} von Ihnen geänderte Einträge sind ungültig geworden – die "
             "zugehörigen Methodeneinträge wurden weiterentwickelt oder "
             "ausgemustert",
    DEAD[1]: "Hier sehen Sie, was bei jeder Aufgabe mitkommt – Schalter und "
             "Umschreibungen ändern nur Ihre Änderungen, nie die "
             "Methodenquelle",
}


def main() -> int:
    with PO.open(encoding="utf-8") as fh:
        catalog = read_po(fh, locale="de")
    deleted = fixed = 0
    for mid in DEAD_DELETE:
        if catalog.get(mid) is not None:
            del catalog[mid]
            deleted += 1
    for mid, msgstr in FIX.items():
        if catalog.get(mid) is None:
            print(f"WARN: 未找到待修 key: {mid[:40]}")
            continue
        catalog[mid].string = msgstr
        fixed += 1
    with PO.open("wb") as fh:  # write_po 写 bytes，必须二进制句柄
        write_po(fh, catalog, width=0)
    print(f"de: deleted {deleted} dead entries, fixed {fixed} translations")
    print("next: .venv/Scripts/python.exe scripts/compile_locales.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
