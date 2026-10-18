# -*- coding: utf-8 -*-
"""首页「账本行删掉花费格」真机自证。

出两张真机图（**真实平台插件**，不设 QT_QPA_PLATFORM=offscreen——离屏缺 CJK
字体，中文会变方块）：
① 正常态：账本行只有三格（AI 干过 / 协作轮次 / 记下的坑），没有「花费估算·美元」；
② 空态：新文案不再提钱（"…踩了什么坑、怎么改好的，一目了然"）。

只读：自带假 API（覆写 `_request`，不连 8101），不碰数据目录。

用法：uv run python -X utf8 scripts/_qa_render_home_stats.py [输出目录]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApi  # noqa: E402

OUT = (Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1]
       else ROOT / "build" / "qa_home")

LEDGER = {"sessions": 6, "rounds": 12, "tokens": 900, "cost_usd_est": 1.75,
          "cost_priced_share": 1.0, "rule_cards": 3, "rule_injectable": 2,
          "pending_fragments": 1}

RULE_ITEMS = [
    {"id": "r1", "rule_kind": "retry_pair", "task": "cmd:npm run build",
     "state": "ERR! Module not found", "action": "fix:retry-with-changed-args",
     "count": 3, "sessions": 3, "G": 0.55, "injectable": True,
     "ts": "2026-09-19T00:00:00Z", "agent": "codex", "session_id": "s1",
     "project": "F:/demo"},
]


class _FakeApi(LocalApi):
    """按路径回 canned 数据（形状与 tests/test_qt_p1_surfaces.FakeApi 一致）。"""

    def __init__(self, ledger_data: dict | None = None):
        super().__init__(base_url="http://fake")
        self.ledger_data = ledger_data or dict(LEDGER)

    def _request(self, method, path, json=None, params=None, timeout=None):
        p = path.split("?")[0]
        if p == "/api/status":
            return {"agents": {"codex": {"running": True}}}
        if p == "/api/models":
            return {"routes": [{"name": "m", "endpoint": ""}]}
        if p == "/api/capture/status":
            return {"agents": {"codex": {"hits_24h": 9}}}
        if p == "/api/growth":
            return {"affinity": {}, "cumulative": {}, "heatmap": {}}
        if p == "/api/insights":
            return {"items": [], "total": 0}
        if p == "/api/experience_drafts":
            return {"count": 0, "items": []}
        if p == "/api/ledger":
            return dict(self.ledger_data)
        if p == "/api/rule-cards":
            return {"items": list(RULE_ITEMS), "total": len(RULE_ITEMS)}
        if p == "/api/pending-fragments":
            return {"items": []}
        if p == "/api/search":
            return {"items": []}
        if p in ("/api/experiences", "/api/skills", "/api/failure-modes"):
            return {"items": []}
        return {}


def _spin(app, n: int = 12) -> None:
    for _ in range(n):
        app.processEvents()
        time.sleep(0.03)


def _mk(app, ledger_data: dict | None = None):
    from app.gui.home import HomePage

    page = HomePage(_FakeApi(ledger_data))
    page.resize(1040, 900)
    page.show()
    page.refresh()
    _spin(app)
    return page


def _labels(w) -> list[str]:
    return [l.text() for l in w.findChildren(QLabel)]


def main() -> int:
    i18n.load_catalog("zh")
    app = QApplication.instance() or QApplication([])
    OUT.mkdir(parents=True, exist_ok=True)

    problems: list[str] = []

    # ① 正常态
    page = _mk(app)
    cards = page._stat_cards
    captions = {k: page._stat_captions[k].text() for k in cards}
    values = {k: page._stat_values[k].text() for k in cards}
    page.grab().save(str(OUT / "home_stats_normal.png"))

    print("账本行格数:", len(cards), "| 键:", list(cards))
    print("标题:", captions)
    print("数值:", values)
    if "cost" in cards or len(cards) != 3:
        problems.append(f"格数不符：{list(cards)}")
    if captions.get("sessions") != "AI 干过·场":
        problems.append(f"第一格不是「AI 干过·场」：{captions}")
    if set(captions.values()) != {"AI 干过·场", "协作轮次·轮", "记下的坑·个"}:
        problems.append(f"标题集合不符：{captions}")
    blob = "".join(_labels(page))
    for bad in ("花费估算", "美元", "花多少钱"):
        if bad in blob:
            problems.append(f"首页仍有残留「{bad}」")
    # 三格等宽（各占 1 份拉伸）
    widths = [c.width() for c in cards.values()]
    if widths and max(widths) - min(widths) > 4:
        problems.append(f"三格宽度不均：{widths}")

    # ② 空态（零会话）
    zero = _mk(app, dict(LEDGER, sessions=0, rounds=0, rule_cards=0))
    zero.grab().save(str(OUT / "home_stats_empty.png"))
    if not zero._empty_card.isVisible():
        problems.append("零会话时空态卡未显示")
    ztexts = "".join(_labels(zero._empty_card))
    print("空态文案:", ztexts.replace("\n", " ")[:120])
    if "踩了什么坑" not in ztexts or "怎么改好的" not in ztexts:
        problems.append(f"空态新文案没生效：{ztexts[:120]}")
    if "花多少钱" in ztexts:
        problems.append("空态仍提着「花多少钱」")

    print("产物:", "home_stats_normal.png", "home_stats_empty.png")
    print("问题:", problems or "无")
    print("RESULT:", "PASS" if not problems else "FAIL")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
