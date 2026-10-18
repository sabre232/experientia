# -*- coding: utf-8 -*-
"""一次性目检（交付自证）：无模型状态下首页/经验库/踩坑 tab 的真实渲染。

stub API 的返回全部来自临时 Store 的真实计算（事件行→T1 挖掘→坑卡），
不是假数据；offscreen grab 存 PNG 供人眼过一遍「首三分钟」门面。
用法：QT_QPA_PLATFORM=offscreen uv run python -X utf8 scripts/_qa_render_p0.py outdir
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tempfile  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.distill import mining  # noqa: E402
from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApi  # noqa: E402
from app.store.store import Store  # noqa: E402

i18n.load_catalog("zh")

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "qa_p0"
OUT.mkdir(parents=True, exist_ok=True)


def build_store() -> Store:
    d = tempfile.mkdtemp()
    store = Store(d)
    store.ensure_layout()

    def bash(cid, cmd, out, ts):
        return [{"role": "assistant", "tool_use": {"name": "Bash",
                "arguments": json.dumps({"cmd": cmd}), "call_id": cid}, "ts": ts},
                {"role": "tool", "tool_result": {"call_id": cid, "output": out}, "ts": ts}]

    for sid in ("s1", "s2", "s3"):
        msgs = (bash("c1", "npm run build", "ERR! Module not found\nProcess exited with code 1", "2026-09-19T01:00:01Z")
                + bash("c2", "npm run build", "ERR! Module not found\nProcess exited with code 1", "2026-09-19T01:00:02Z")
                + bash("c3", "npm install", "installed\nProcess exited with code 0", "2026-09-19T01:00:03Z")
                + bash("c4", "npm run build", "done\nProcess exited with code 0", "2026-09-19T01:00:04Z"))
        store.record_session({"agent": "codex", "session_id": sid,
                              "project": "F:/demo-app", "model": "claude-sonnet-4-5",
                              "tokens_in": 120000, "tokens_out": 15000,
                              "messages": msgs, "user_messages": ["构建一下", f"再来{sid}"],
                              "assistant_messages": ["好了"], "req_count": 2,
                              "correction_hits": 0, "trunk": "编程", "category": "构建"})
        store.record_session({"agent": "workbuddy", "session_id": "w" + sid,
                              "project": "F:/demo-app",
                              "messages": [
                                  {"role": "user", "content": "帮我改配置", "ts": "2026-09-19T02:00:00Z"},
                                  {"role": "assistant", "tool_use": {"name": "Edit", "call_id": "e1",
                                   "arguments": json.dumps({"file_path": "F:/demo/app.py",
                                                            "old_string": "port=8080", "new_string": "port=9000"})}, "ts": "2026-09-19T02:00:01Z"},
                                  {"role": "tool", "tool_result": {"call_id": "e1", "output": "ok"}, "ts": "2026-09-19T02:00:02Z"},
                                  {"role": "assistant", "tool_use": {"name": "Edit", "call_id": "e2",
                                   "arguments": json.dumps({"file_path": "F:/demo/app.py",
                                                            "old_string": "port=9000", "new_string": "port=8080"})}, "ts": "2026-09-19T02:00:03Z"},
                                  {"role": "tool", "tool_result": {"call_id": "e2", "output": "ok"}, "ts": "2026-09-19T02:00:04Z"},
                                  {"role": "user", "content": "不对，端口回滚吧", "ts": "2026-09-19T02:00:05Z"}],
                              "user_messages": ["帮我改配置", "不对，端口回滚吧"],
                              "assistant_messages": ["已回滚"], "req_count": 2,
                              "correction_hits": 1, "trunk": "编程", "category": "构建"})
    mining.mine_all(store)
    # 目检价值闸门分区：注入一张 agent_friction（应进"助手避坑"）+ 一张 env（应消失）
    from app.distill import value_gate
    store.append_experience({
        "task": "sig:Error: File has not been read yet: <p> Read it first", "action": "recurring-error-signature",
        "state": "Error: File has not been read yet: F:/demo/app.py Read it first before writing to it.",
        "outcome": "", "G": 0.55, "g_source": "rule", "rule_kind": "error_sig",
        "value_class": value_gate.FRICTION, "corrected": False, "agent": "workbuddy",
        "session_id": "s1", "count": 44, "seen_in": ["s1", "s2", "s3"],
        "trunk": "编程", "category": "构建"})
    store.append_experience({
        "task": "sig:fetch failed", "action": "recurring-error-signature",
        "state": "Error during web fetch for https://x fetch failed",
        "outcome": "", "G": 0.55, "g_source": "rule", "rule_kind": "error_sig",
        "value_class": value_gate.ENV, "corrected": False, "agent": "codex",
        "session_id": "s1", "count": 24, "seen_in": ["s1", "s2", "s3"],
        "trunk": "编程", "category": "构建"})
    # 同类归堆目检（方案 B）：再塞几张不同桶的 friction 卡，
    # 单张看不出归堆效果
    for _sig, _n, _ag, _sid in (
        ("Error: Edit error on F:/demo/app.py: string to replace not found in file", 12, "workbuddy", "s2"),
        ("command blocked for security: rm -rf build", 8, "codex", "s1"),
        ('invalid parameters provided: parameter "url" expected string, but received int', 6, "workbuddy", "s3"),
        ("Error: can not find skill docker-compose", 5, "codex", "s2"),
        ("Edit: no changes to make, old_string and new_string are identical", 4, "workbuddy", "s1"),
    ):
        store.append_experience({
            "task": "sig:" + _sig[:40], "action": "recurring-error-signature",
            "state": _sig, "outcome": "", "G": 0.55, "g_source": "rule",
            "rule_kind": "error_sig", "value_class": value_gate.FRICTION,
            "corrected": False, "agent": _ag, "session_id": _sid,
            "count": _n, "seen_in": [_sid], "trunk": "编程", "category": "构建"})
    from app.distill.review import enqueue_for_replay
    for s in store.list_sessions():
        if int(s.get("correction_hits") or 0) > 0:
            enqueue_for_replay(store, dict(s))
    return store


class StubApi(LocalApi):
    def __init__(self, store: Store):
        super().__init__(base_url="http://stub")
        self._store = store

    def _request(self, method, path, json=None, params=None, timeout=None):
        st = self._store
        p = path.split("?")[0]
        if p == "/api/status":
            return {"agents": {"codex": {"running": True}, "workbuddy": {"running": True}}}
        if p == "/api/models":
            return {"routes": [], "default": None}
        if p == "/api/capture/status":
            return {"agents": {"codex": {"hits_24h": 34}, "workbuddy": {"hits_24h": 12}}}
        if p == "/api/growth":
            return st.growth_summary()
        if p == "/api/insights":
            return {"items": [], "total": 0}
        if p == "/api/experience_drafts":
            return {"count": 0, "items": []}
        if p == "/api/ledger":
            from app import ledger
            return ledger.compute(st)
        if p == "/api/rule-cards":
            from app.distill import value_gate as _vg
            cards = [e for e in st.iter_experiences(include_distilled=True)
                     if e.get("g_source") == "rule"]
            return {"items": [{
                "id": c.get("id"), "rule_kind": c.get("rule_kind"), "task": c.get("task"),
                "value_class": c.get("value_class"), "g_source": "rule",
                "surface": _vg.surface_of(c),
                "state": c.get("state"), "action": c.get("action"),
                "count": int(c.get("count") or 1),
                "sessions": len(set((c.get("seen_in") or []) + [c.get("session_id", "")])),
                "G": float(c.get("G") or 0), "injectable": float(c.get("G") or 0) >= 0.5,
                "ts": c.get("ts"), "agent": c.get("agent"),
                "session_id": c.get("session_id"), "project": c.get("project"),
            } for c in cards[:40]], "total": len(cards)}
        if p == "/api/pending-fragments":
            return {"items": st.load_pending_review_records()[::-1]}
        if p == "/api/search":
            q = str((params or {}).get("q") or "")
            return {"items": st.search_sessions(q, limit=12)}
        if p == "/api/session-view":
            rec = st.list_sessions()[0]
            return {"agent": rec.get("agent"), "session_id": rec.get("session_id"),
                    "project": rec.get("project"), "started_at": rec.get("started_at"),
                    "model": rec.get("model"), "req_count": rec.get("req_count"),
                    "correction_hits": rec.get("correction_hits"),
                    "user_messages": rec.get("user_messages") or [],
                    "assistant_messages": rec.get("assistant_messages") or [],
                    "events": (rec.get("events") or [])[-80:], "has_archive": False}
        if p == "/api/experiences":
            from app.distill import mining as _mining
            from app.distill import value_gate as _vg
            items = []
            for e in st.iter_experiences(include_distilled=True):
                # 与产品同口径（价值闸门 A 收口）：只留"你的经验"去向
                if _vg.surface_of(e) != _vg.SURFACE_EXPERIENCE:
                    continue
                if e.get("g_source") == "rule":
                    e = dict(e)
                    e["task"] = str(e.get("task") or "").split(":", 1)[-1]
                    e["action"] = _mining.rule_line_text(e)
                items.append(e)
            return {"items": items, "total": len(items)}
        if p == "/api/skills":
            return {"items": []}
        if p == "/api/failure-modes":
            return {"items": []}
        if p == "/api/rules":
            return {"items": []}
        return {}


def shoot(page, name: str, app) -> None:
    page.resize(1000, 760)
    page.show()  # 离屏也必须 show：未经历布局的 grab 不渲染动态新增的行
    page.refresh()
    for _ in range(6):
        app.processEvents()
        time.sleep(0.08)
    page.grab().save(str(OUT / f"{name}.png"))
    print("saved", name)


def main() -> int:
    store = build_store()
    cards = list(store.iter_experiences(include_distilled=True))
    print("rule 卡:", [(c.get("rule_kind"), c.get("G")) for c in cards])
    app = QApplication.instance() or QApplication([])
    api = StubApi(store)
    from app.gui.experiences import ExperiencesPage
    from app.gui.failure_modes import FailureModesPage
    from app.gui.home import HomePage
    home = HomePage(api)
    shoot(home, "home", app)
    # 归堆目检（方案 B）：收起态见 home.png；点「展开」再出一张
    from PySide6.QtWidgets import QPushButton
    for b in home._friction_card.findChildren(QPushButton):
        if b.text() == i18n.t("展开"):
            b.click()
            break
    for _ in range(4):
        app.processEvents()
        time.sleep(0.05)
    home.grab().save(str(OUT / "home_friction_expanded.png"))
    print("saved home_friction_expanded")
    # 搜索目检：模拟用户搜 npm（结果卡渲染 + 点击链路验证）
    home._search_tf.setText("npm")
    home._do_search()
    for _ in range(15):
        app.processEvents()
        time.sleep(0.08)
    home.grab().save(str(OUT / "home_search.png"))
    print("saved home_search")
    shoot(ExperiencesPage(api), "mine_experiences", app)
    shoot(FailureModesPage(api), "failure_modes", app)
    return 0


if __name__ == "__main__":
    sys.exit(main())
