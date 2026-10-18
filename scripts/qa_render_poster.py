# -*- coding: utf-8 -*-
"""成长海报 / 本周结算卡真机数据离屏目检（交付自证）。

三条链路一次渲完：海报 PNG（PIL）、App 内海报弹层（Qt）、本周结算卡（Qt）。
全程只读：Store._init_expdb 打桩（引擎在跑时不碰 experience.db，避免与写者抢锁），
不调 check_achievements / maybe_run（它们会写 achievements.json 与通知）。

用法：QT_QPA_PLATFORM=offscreen uv run python -X utf8 scripts/_qa_render_poster.py [输出目录]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.store.store as _ss  # noqa: E402

_ss.Store._init_expdb = lambda self: None  # 只读：不重建 SQLite 索引

from PySide6.QtWidgets import QApplication, QLabel, QScrollArea  # noqa: E402

from app.distill import weekly_report  # noqa: E402
from app.gui import growth as growth_mod  # noqa: E402
from app.gui import i18n, poster, report_model  # noqa: E402
from app.gui.i18n import t  # noqa: E402
from app.store.store import Store  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else ROOT / "build" / "qa_poster"
OUT.mkdir(parents=True, exist_ok=True)
DATA = Path.home() / ".experientia"


def main() -> int:
    i18n.load_catalog("zh")
    app = QApplication.instance() or QApplication([])
    store = Store(DATA)
    g = store.growth_summary(days=30)

    # ① 海报 PNG（PIL，无 Qt 依赖）
    spec = poster.growth_poster(report_model.growth_report_model(g), t)
    png = OUT / "poster_real.png"
    poster.render_png(spec, png, scale=2)
    kinds = [b["type"] for b in spec["blocks"]]

    # ② App 内海报弹层
    from app.gui.report_view import _three_layer_body

    dlg = _three_layer_body(spec)
    dlg.resize(760, 1500)
    dlg.show()
    for _ in range(4):
        app.processEvents()
    dlg.grab().save(str(OUT / "poster_dialog.png"))

    # ③ 本周结算卡（服务端 peek → GUI 本地化）
    from app.gui.weekly_card import WeeklyCard

    data = weekly_report.peek(store)
    from app.distill import growth_story
    data["story"] = growth_story.localize(data["story"], t)
    card = WeeklyCard(data)
    card.show()
    for _ in range(4):
        app.processEvents()
    card.grab().save(str(OUT / "weekly_card.png"))

    # 结构断言：不塌、不横滚、不漏内部串
    problems = []
    collapsed = [l.text()[:20] for l in card.findChildren(QLabel)
                 if l.text().strip() and l.height() < 8]
    if collapsed:
        problems.append(f"结算卡标签塌陷: {collapsed}")
    for sc in card.findChildren(QScrollArea):
        bar = sc.horizontalScrollBar()
        if bar.isVisible() and bar.maximum() > 0:
            problems.append("结算卡出现横向滚动条")
    blob = str(kinds) + "".join(l.text() for l in card.findChildren(QLabel))
    for bad in ("未分类", "sig:", "pit_avoider", "{'tpl'"):
        if bad in blob:
            problems.append(f"内部串泄漏: {bad}")

    h = spec["blocks"][0]
    print("海报区块:", kinds)
    print("主句:", h.get("big"), h.get("unit"), "|", h.get("from"), "→", h.get("to"))
    print("庆祝标志:", spec["has_significant_improvement"], "(本机无新解锁应为 False)")
    print("产物:", png.name, "poster_dialog.png", "weekly_card.png")
    print("问题:", problems or "无")
    print("RESULT:", "PASS" if not problems else "FAIL")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
