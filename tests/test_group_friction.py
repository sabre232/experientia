"""避坑卡同类归堆（方案 B）护栏。

三层：
1. group_friction 纯函数——真机 30 条样本进 → 9 桶出、次数严格守恒（172）、
   降序、未命中落通用桶、空输入不炸；
2. 首页 GUI——卡可见、默认只露前 5 桶 + 折叠行、点展开/收起行数往返、
   「查看会话」收成底部一个、悬停保留报错原文；
3. 成长页——同一份数据两页口径一致（桶标题同源、长模板句不再出现）。

既有教训：带模态门禁的按钮不直调（本测试链路本就不碰 AI 门禁按钮）。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from app.gui import i18n, rule_render  # noqa: E402

# ---------- 真机 30 条样本（桌面方案 /：9 桶、合计 172 次） ----------

REAL_30: list[tuple[str, int]] = [
    # 桶 1 编辑前没先读文件 —— 46
    ("Error: File has not been read yet: F:/p/app.py Read it first before writing.", 15),
    ("File has not been read yet: F:/p/cfg.yaml", 15),
    ("Edit blocked: file has not been read yet (db.py)", 8),
    ("has not been read yet: utils.ts", 8),
    # 桶 2 通用桶（操作顺序或参数不对）—— 46
    ("FileNotFoundError: [Errno 2] No such file or directory: 'data.csv'", 10),
    ("SyntaxError: invalid syntax in line 42", 10),
    ("AttributeError: 'NoneType' object has no attribute 'strip'", 8),
    ("IndexError: list index out of range", 8),
    ("TypeError: can only concatenate str (not int)", 5),
    ("KeyError: 'portfolio'", 5),
    # 桶 3 替换没匹配上 —— 29
    ("String to replace not found in file.", 7),
    ("Error: Edit error on app.py old_string mismatch", 6),
    ("String to replace not found in file: port=8080", 6),
    ("edit error on F:/p/x.py", 5),
    ("String to replace not found (config.json)", 5),
    # 桶 4 命令被安全策略拦下 —— 18
    ("command blocked for security: rm -rf build", 5),
    ("Command blocked for security policy: del /q", 5),
    ("blocked command: command blocked for security (powershell)", 4),
    ("command blocked for security: reg delete", 4),
    # 桶 5 拿着旧内容改文件 —— 13
    ("File has been modified since read, either by the user or a linter.", 5),
    ("Please read it again before editing", 4),
    ("modified since read: app.py", 4),
    # 桶 6 传的参数类型不对 —— 8
    ("expected string, but received int for parameter url", 5),
    ("invalid parameters provided: query must be non-empty", 3),
    # 桶 7 要用的技能没装 —— 5
    ("Error: cannot find skill 'docker-compose'", 3),
    ("can not find skill pdf-tools", 2),
    # 桶 8 一处改还是全改没说清 —— 4
    ("replace_all is false but multiple matches found", 2),
    ("Found # matches in file, use replace_all", 2),
    # 桶 9 其实没改动却提交 —— 3
    ("No changes to make: old_string and new_string are exactly the same", 2),
    ("no changes to make", 1),
]

EXPECT_TITLES = {
    "编辑前没先读文件": 46, "操作顺序或参数不对": 46, "替换没匹配上": 29,
    "命令被安全策略拦下": 18, "拿着旧内容改文件": 13, "传的参数类型不对": 8,
    "要用的技能没装": 5, "一处改还是全改没说清": 4, "其实没改动却提交": 3,
}


def _home_item(state: str, count: int, idx: int) -> dict:
    """首页 /api/rule-cards 形态（真 payload 带 surface 字段）。"""
    from app.distill import value_gate
    return {"id": f"r{idx}", "rule_kind": "error_sig", "g_source": "rule",
            "surface": value_gate.SURFACE_ADVICE, "task": f"sig:{state[:40]}",
            "state": state, "action": "recurring-error-signature",
            "count": count, "sessions": 1, "G": 0.6, "injectable": True,
            "agent": "codex", "session_id": f"s{idx}"}


def _growth_item(state: str, count: int, idx: int) -> dict:
    """成长页 advice_items 形态（store.growth_summary 派生字段）。"""
    return {"id": f"e{idx}", "task": f"sig:{state[:40]}", "state": state,
            "count": count, "seen": 1}


# ---------- 1. 纯函数 ----------

def test_group_friction_real30_nine_buckets():
    items = [_home_item(s, c, i) for i, (s, c) in enumerate(REAL_30)]
    buckets = rule_render.group_friction(items)
    assert len(buckets) == 9
    # 次数严格守恒：sum(桶) == sum(明细) == 172
    assert sum(b["count"] for b in buckets) == sum(c for _, c in REAL_30) == 172
    for b in buckets:
        assert b["count"] == EXPECT_TITLES[b["title"]]
    counts = [b["count"] for b in buckets]
    assert counts == sorted(counts, reverse=True)
    assert all(b["advice"] and b["samples"] for b in buckets)


def test_group_friction_sessions_and_samples():
    items = [_home_item(s, c, i) for i, (s, c) in enumerate(REAL_30)]
    buckets = {b["title"]: b for b in rule_render.group_friction(items)}
    # 桶 3 五种报错写法去重后全保留（悬停兜原文）
    assert len(buckets["替换没匹配上"]["samples"]) == 5
    # 来源会话逐条收集
    assert len(buckets["编辑前没先读文件"]["sessions"]) == 4


def test_group_friction_unknown_falls_to_generic():
    g = rule_render.group_friction(
        [{"state": "ZeroDivisionError: division by zero", "count": 2,
          "session_id": "sx"}])
    assert len(g) == 1
    assert g[0]["title"] == "操作顺序或参数不对"
    assert g[0]["advice"] == "遇到这类工具报错前先自查操作顺序与参数"


def test_group_friction_empty_and_missing_fields():
    assert rule_render.group_friction([]) == []
    # count 缺失/非数按 1，空 state 不炸、落通用桶
    assert rule_render.group_friction([{}])[0]["count"] == 1


# ---------- 2. 首页 GUI ----------

BUCKETS_7 = [("File has not been read yet: a.py", 44),
             ("String to replace not found in file.", 29),
             ("command blocked for security: rm build", 18),
             ("File has been modified since read", 13),
             ("expected string, but received int", 8),
             ("cannot find skill pdf", 5),
             ("no changes to make", 3)]


class _HomeApi:
    """home._fetch 九个只读端点的最小桩（duck-type，不发网络）。"""

    def __init__(self, rule_items):
        self._items = rule_items

    def status(self):
        return {"agents": {}}

    def experiences(self, limit=300):
        return {"items": [], "total": 0}

    def capture_status(self):
        return {"agents": {}}

    def growth(self, days=30):
        return {"affinity": {}}

    def insights(self):
        return {"items": [], "total": 0}

    def experience_drafts(self):
        return {"count": 0, "items": []}

    def ledger(self):
        return {"sessions": 9, "rounds": 20, "rule_cards": len(self._items),
                "pending_fragments": 0}

    def rule_cards(self, limit=40):
        return {"items": list(self._items), "total": len(self._items)}

    def models(self):
        return {"routes": [{"endpoint": ""}]}

    def search(self, q, limit=12):
        return {"items": []}

    def session_view(self, agent, sid):
        return {}


def _spin(app, n=12):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.02)


def _mk_home(qapp, items):
    from app.gui.home import HomePage
    from tests.conftest import pump_until
    h = HomePage(_HomeApi(items))
    h.resize(1000, 900)
    h.show()  # 离屏也必须 show：未经历布局的 grab/findChildren 不可信
    h.refresh()
    assert pump_until(lambda: not h._fetches, qapp), "后台取数未在超时内完成"
    _spin(qapp)
    return h


def test_home_friction_grouped_and_folded(qapp):
    items = [_home_item(s, c, i) for i, (s, c) in enumerate(BUCKETS_7)]
    h = _mk_home(qapp, items)
    assert h._friction_card.isVisible()
    # 7 桶 + 折叠行 + 底部入口 = 9 个行控件
    assert h._friction_layout.count() == 9
    rows = [h._friction_layout.itemAt(i).widget() for i in range(7)]
    assert all(r.isVisible() for r in rows[:5])
    assert all(not r.isVisible() for r in rows[5:])
    # 卡副标题写明"归成 N 类"（口径透明可解释）
    assert "归成 7 类" in h._friction_caption.text()
    # 悬停保留原始报错（数据不丢）
    assert rows[0].toolTip()
    # 折叠行文案：还有 2 类 · 合计 8 次
    fold = h._friction_layout.itemAt(7).widget()
    fold_btn = fold.findChildren(QPushButton)[0]
    assert fold_btn.text() == "展开"
    btns = h._friction_card.findChildren(QPushButton)
    labels = sorted(b.text() for b in btns)
    assert labels == sorted(["展开", "查看相关会话记录"])
    # 点展开 → 7 桶全露、按钮变收起；再点 → 还原
    btns[[b.text() for b in btns].index("展开")].click()
    _spin(qapp, 3)
    assert all(r.isVisible() for r in rows)
    btns = h._friction_card.findChildren(QPushButton)
    collapse = btns[[b.text() for b in btns].index("收起")]
    collapse.click()
    _spin(qapp, 3)
    assert all(not r.isVisible() for r in rows[5:])


def test_home_friction_no_per_row_session_button(qapp):
    """按钮雨收口：归堆区不再有每条一个「查看会话」，只留底部一个入口。"""
    items = [_home_item(s, c, i) for i, (s, c) in enumerate(BUCKETS_7)]
    h = _mk_home(qapp, items)
    assert not any(b.text() == "查看会话"
                   for b in h._friction_card.findChildren(QPushButton))


def test_home_friction_below_five_buckets_no_fold(qapp):
    items = [_home_item(s, c, i) for i, (s, c) in enumerate(BUCKETS_7[:3])]
    h = _mk_home(qapp, items)
    # 3 桶 + 底部入口，无折叠行
    assert h._friction_layout.count() == 4
    labels = [b.text() for b in h._friction_card.findChildren(QPushButton)]
    assert labels == ["查看相关会话记录"]


# ---------- 3. 成长页同口径 + 两页守恒对照 ----------

def _growth_payload(items):
    return {
        "days": 30, "cumulative": {}, "heatmap": {"trunks": [], "grid": {}},
        "affinity": {}, "changelog": [], "maintenance": [],
        "stage": {"start": "2026-09-01", "end": "2026-09-26", "weeks": 4,
                  "active_days": 20, "sessions": 50, "agents": 2, "projects": 3},
        "assets": {"experience": 10, "advice": len(items), "corrected": 0,
                   "judged": 0, "top": 0, "high": 0, "feedback": 0,
                   "total": 10 + len(items),
                   "advice_hits": sum(int(i.get("count") or 1) for i in items)},
        "flywheel": {"collected": 50, "distilled": 10, "judged": 0,
                     "injected": 0, "improved": None},
        "rework": {"early": None, "recent": None, "drop_pct": None,
                   "comparable": False},
        "weekly": [], "phases": [], "agents": [], "ledger": [],
        "advice_items": items,
    }


class _GrowthApi:
    def __init__(self, payload):
        self._p = payload

    def growth(self, days=30):
        return self._p

    def skills(self):
        return {"items": []}

    def models(self):
        return {"routes": [{"endpoint": ""}]}

    def hooks_config(self):
        return {}


def test_growth_advice_card_same_bucket_caliber(qapp):
    from PySide6.QtWidgets import QLabel

    from app.gui import growth as growth_mod
    growth_items = [_growth_item(s, c, i) for i, (s, c) in enumerate(REAL_30)]
    page = growth_mod.GrowthPage(_GrowthApi(_growth_payload(growth_items)))
    page.refresh()
    from tests.conftest import pump_until
    assert pump_until(lambda: not page._fetches, qapp), "后台取数未在超时内完成"
    body = "\n".join(l.text() for l in page.findChildren(QLabel))
    # 桶标题口径（与首页同源 group_friction），长模板句不再出现
    assert "编辑前没先读文件" in body
    assert "共 9 类、累计撞见 172 次" in body
    assert "我发现自己常在" not in body


def test_two_pages_group_identically():
    """同一份数据两种 payload 形态 → 桶聚合结果逐字段一致（两页口径一致）。"""
    home = rule_render.group_friction(
        [_home_item(s, c, i) for i, (s, c) in enumerate(REAL_30)])
    growth = rule_render.group_friction(
        [_growth_item(s, c, i) for i, (s, c) in enumerate(REAL_30)])
    slim = lambda bs: [(b["title"], b["count"]) for b in bs]  # noqa: E731
    assert slim(home) == slim(growth)
