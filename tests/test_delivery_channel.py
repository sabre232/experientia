"""送达通道记账与诊断护栏。

补的是一个**指标性缺陷**：经验有两条路真的能进助手上下文——代理改写请求（proxy）、
Claude Code UserPromptSubmit 回灌（hook）。此前只有代理通道调 record_injection，
hook 通道注入成功也什么都不留 → 飞轮第④格、周报"哪条经验在变强"、档 C 条目老化
全部少算一条路：送达了却没留痕，等于没送达。

同时锁住第④格的诊断文案：没送达时必须说清卡在哪一步（没装 / 装了没回调 /
通了没内容），而不是甩给用户一个 0。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.capture import hook as hook_channel  # noqa: E402
from app.distill import growth_story as gs  # noqa: E402
from app.gui import growth as growth_mod, i18n  # noqa: E402
from app.store.store import Store  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    i18n.load_catalog("zh")
    return QApplication.instance() or QApplication([])


def _store(tmp_path) -> Store:
    store = Store(Path(tmp_path))
    store.ensure_layout()
    store.save_config({"seed_keywords": {"营销": ["文案", "投放", "标题"]}})
    store.write_skill("营销", "营销",
                      "## 成功要点\n- 标题用利益点前置句式\n\n"
                      "## 失败模式\n- [Solidified] 纯情绪文案点击率低（出现 3 次）\n")
    return store


def _injections(store: Store) -> list[dict]:
    p = store.data_dir / "injection.log"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x]


# ---------- 1. hook 通道注入必须记账 ----------

def test_hook_injection_records_one_line_per_session(tmp_path, monkeypatch):
    """同 session 同归类只记一次，且标 channel=hook。"""
    store = _store(tmp_path)
    monkeypatch.setattr(hook_channel, "_injected_memo", type(hook_channel._injected_memo)())
    prompt = "帮我把这条投放文案的标题写得利益点前置"

    first = hook_channel.build_hook_context(store, prompt, session_id="s1")
    second = hook_channel.build_hook_context(store, prompt, session_id="s1")
    third = hook_channel.build_hook_context(store, prompt, session_id="s2")

    assert first and second, "经验块应仍能注入（记账不能改变注入本身）"
    recs = _injections(store)
    assert len(recs) == 2, f"两个 session 各记一次，实得 {recs}"
    assert {r["session"] for r in recs} == {"s1", "s2"}
    assert all(r["channel"] == "hook" for r in recs)
    assert all(x["items"] for x in recs), "条目级命中必须落盘，否则第⑤环反馈与条目老化空转"
    assert third


def test_hook_context_without_session_still_injects(tmp_path):
    """没带 session_id 也要正常注入（记账只是副作用，不能挡注入）。"""
    store = _store(tmp_path)
    ctx = hook_channel.build_hook_context(
        store, "帮我把投放标题写得利益点前置")
    assert ctx and "Experientia" in ctx
    assert _injections(store) == []


def test_proxy_channel_still_defaults_to_proxy(tmp_path):
    """代理通道不传 channel 时仍是 proxy（旧行为不变）。"""
    store = _store(tmp_path)
    store.record_injection("营销", "营销", "p1", 120, items=[{"id": "x", "text": "t"}])
    assert _injections(store)[0]["channel"] == "proxy"


# ---------- 2. 第④格覆盖两条通道 ----------

def test_injected_by_splits_channels(tmp_path):
    store = _store(tmp_path)
    store.record_injection("营销", "营销", "p1", 100, channel="proxy")
    store.record_injection("营销", "营销", "h1", 100, channel="hook")
    store.record_injection("营销", "营销", "h2", 100, channel="hook")
    fw = store.growth_summary(days=30)["flywheel"]
    assert fw["injected"] == 3
    assert fw["injected_by"] == {"proxy": 1, "hook": 2}


def test_missing_injection_log_counts_zero(tmp_path):
    store = _store(tmp_path)
    fw = store.growth_summary(days=30)["flywheel"]
    assert fw["injected"] == 0 and fw["injected_by"] == {"proxy": 0, "hook": 0}


# ---------- 3. 卡在哪一步要说清 ----------

def test_delivery_states_are_distinguished():
    g0 = {"flywheel": {"injected": 0, "injected_by": {"proxy": 0, "hook": 0}}}
    assert gs.delivery(g0, {})["state"] == "no_hook"
    assert gs.delivery(g0, {"configured": True, "observed": {}})["state"] == "not_observed"
    assert gs.delivery(g0, {"configured": True,
                            "observed": {"UserPromptSubmit": "2026-09-20T10:00:00Z"}}
                       )["state"] == "idle"
    live = gs.delivery({"flywheel": {"injected": 4,
                                     "injected_by": {"proxy": 1, "hook": 3}}}, {})
    assert live["state"] == "live" and not live["action"]
    # 没装才有行动入口（装了没回调时催也没用，只说事实）
    assert gs.delivery(g0, {})["action"] == "去接上"
    assert gs.delivery(g0, {"configured": True})["action"] == ""


def test_delivery_text_names_both_channels():
    d = gs.delivery({"flywheel": {"injected": 4,
                                  "injected_by": {"proxy": 1, "hook": 3}}}, {})
    text = d["tpl"].format(**d["params"])
    assert "代理 1" in text and "hook 3" in text


# ---------- 4. 欠账卡真的用上了诊断 ----------

class _Api:
    def __init__(self, hook):
        self._hook = hook

    def growth(self, days=30):
        return {"days": 30, "cumulative": {},
                "heatmap": {"trunks": [], "grid": {}}, "affinity": {},
                "changelog": [], "maintenance": [],
                "stage": {"start": "2026-07-04", "end": "2026-09-20", "weeks": 12,
                          "active_days": 39, "sessions": 257, "agents": 4,
                          "projects": 59},
                "assets": {"experience": 52, "advice": 30, "corrected": 14,
                           "judged": 51, "top": 10, "high": 31, "feedback": 0,
                           "total": 82, "advice_hits": 172},
                "flywheel": {"collected": 257, "distilled": 82, "judged": 51,
                             "injected": 0, "injected_by": {"proxy": 0, "hook": 0},
                             "improved": None},
                "rework": {"early": 2.14, "recent": 0.35, "drop_pct": 84,
                           "early_n": 14, "recent_n": 199, "early_corr": 30,
                           "recent_corr": 69, "comparable": True},
                "weekly": [{"week": "2026-09-14", "sessions": 27,
                            "corrections": 10, "rate": 0.37}],
                "agents": [], "phases": [], "ledger": [], "advice_items": []}

    def skills(self):
        return {"items": []}

    def models(self):
        return {"routes": [{"endpoint": ""}]}

    def hooks_config(self):
        return self._hook


def _pump(page) -> None:
    """H3 后 refresh() 取数在后台线程：泵到渲染落地再断言。"""
    from PySide6.QtWidgets import QApplication

    from tests.conftest import pump_until

    assert pump_until(lambda: not page._fetches, QApplication.instance()), \
        "后台取数未在超时内完成"


def _page(hook: dict) -> growth_mod.GrowthPage:
    page = growth_mod.GrowthPage(_Api(hook))
    page.refresh()
    _pump(page)
    return page


def _text(page) -> str:
    return "\n".join(l.text() for l in page.findChildren(QLabel))


def test_gaps_card_says_hook_not_installed(qapp):
    body = _text(_page({}))
    assert "经验自动送达还没装上" in body
    assert "127.0.0.1:8100" in body, "要给出可直接照做的地址，不能只说 0"


def test_gaps_card_says_hook_installed_but_silent(qapp):
    body = _text(_page({"configured": True, "observed": {},
                        "last_observed_ago_s": None}))
    assert "一次都没用过" in body
    assert "经验自动送达还没装上" not in body, "已装却催用户去装 = 诊断说谎"


def test_gaps_card_reports_delivery_mix(qapp):
    api = _Api({"configured": True})
    orig = api.growth

    def growth(days=30):
        g = orig(days)
        g["flywheel"] = {**g["flywheel"], "injected": 4,
                         "injected_by": {"proxy": 1, "hook": 3}}
        return g
    api.growth = growth
    page = growth_mod.GrowthPage(api)
    page.refresh()
    _pump(page)
    body = _text(page)
    assert "4 次已送达" in body and "代理 1" in body and "hook 3" in body
