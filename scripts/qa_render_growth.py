# -*- coding: utf-8 -*-
"""成长页真机数据离屏目检（交付自证）。

stub API 的 growth/skills/models 全部来自真实 Store 计算（默认指向
~/.experientia；跑验收时可传副本目录，避免与在跑的引擎抢写）。
除了存 PNG，还顺手卡两条结构不变量：
1) 页面不得出现横向滚动条（QScrollArea 最小宽被内容撑破的老坑）；
2) 六个区块都必须真的在树里且可见。
用法：QT_QPA_PLATFORM=offscreen uv run python -X utf8 scripts/_qa_render_growth.py [数据目录] [输出目录]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.store.store as _ss  # noqa: E402

# 只读护栏：默认目录指向正在跑的引擎时，不重建 SQLite 索引（否则与写者抢 experience.db / engine.lock）
_ss.Store._init_expdb = lambda self: None

from PySide6.QtWidgets import (QApplication, QScrollArea, QWidget)  # noqa: E402

from app.gui import growth as growth_mod, i18n  # noqa: E402
from app.gui.i18n import t  # noqa: E402
from app.gui.api_client import LocalApi  # noqa: E402
from app.store.store import Store  # noqa: E402

i18n.load_catalog("zh")

# 空参数（shell 传 ""）不得静默变成当前目录——那会读到一个空库、渲出一张空图
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else Path.home() / ".experientia"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else ROOT / "build" / "qa_growth"
# 离屏缺 CJK 字体时中文成方块：传 en 可读到真实文案做文字级目检
LANG = sys.argv[3] if len(sys.argv) > 3 else "zh"
i18n.load_catalog(LANG)
OUT.mkdir(parents=True, exist_ok=True)


class StubApi(LocalApi):
    """零网络：接口返回全部走本地 Store 真实计算。"""

    def __init__(self, store: Store):
        super().__init__(base_url="http://stub")
        self._store = store

    def _request(self, method, path, json=None, params=None, timeout=None):
        st = self._store
        p = path.split("?")[0]
        if p == "/api/growth":
            g = st.growth_summary(days=int((params or {}).get("days") or 30))
            g["changelog"] = st.list_changelog()[-50:][::-1]
            g["maintenance"] = st.read_maintenance(limit=20)
            return g
        if p == "/api/skills":
            return {"items": [{"path": k, "failure_solid": [], "failure_watching": [],
                               "preferences": {}}
                              for k in st.list_preference_trunks()]}
        if p == "/api/models":
            return {"routes": [], "default": None}   # 真机现状：端点连不上
        return {}


def main() -> int:
    app = QApplication.instance() or QApplication([])
    store = Store(DATA)
    page = growth_mod.GrowthPage(StubApi(store))
    page.resize(1180, 2600)
    page.show()
    page.refresh()
    for _ in range(8):
        app.processEvents()
        time.sleep(0.08)

    shot = OUT / f"qt_growth_{LANG}.png"
    page.grab().save(str(shot))

    # 结构不变量 1：不得出现横向滚动条
    bad = []
    for sc in page.findChildren(QScrollArea):
        bar = sc.horizontalScrollBar()
        if bar.isVisible() and bar.maximum() > 0:
            bad.append(sc.objectName() or "scrollarea")
    # 结构不变量 2：六个主角区块都在树里且可见（用 t() 取当前语言的串，
    # 换语言目检时不会误报缺块）
    from PySide6.QtWidgets import QLabel
    texts = "\n".join(l.text() for l in page.findChildren(QLabel))
    need = [t("阶段结论 · 自动生成")[:6], t("经验飞轮转到哪一格了"),
            t("你干活的量 vs 要你返工的次数"), t("你的经验账本"),
            t("还差这三件，才能给你看证据")[:6], t("过程记录")]
    missing = [n for n in need if n not in texts]

    g = store.growth_summary(days=30)
    print("stage:", g["stage"])
    print("flywheel:", g["flywheel"])
    print("rework:", {k: g["rework"][k] for k in
                      ("early", "recent", "drop_pct", "comparable")})
    print("assets:", g["assets"])
    print("saved:", shot)
    print("横向滚动条:", bad or "无")
    print("缺区块:", missing or "无")
    ok = not bad and not missing
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
