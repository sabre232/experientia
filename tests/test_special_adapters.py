"""Wave 4 特殊格式 adapter（trae/windsurf/copilot-cli，均实验性）+ 格式漂移黄标机制测试。"""

import json
import logging
import sqlite3

from app.capture.adapters.copilot_cli import CopilotCliAdapter
from app.capture.adapters.trae import TraeAdapter
from app.capture.adapters.windsurf import WindsurfAdapter
from app.capture.models import Message, Session, SessionRef
from app.store.store import Store


# ---------- trae ----------

def _make_trae_legacy_db(tmp_path):
    base = tmp_path / "Trae CN"
    ws = base / "User" / "workspaceStorage" / "abc123"
    ws.mkdir(parents=True)
    db = ws / "state.vscdb"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO ItemTable VALUES (?,?)", (
        "memento/icube-ai-agent-storage",
        json.dumps({"session_id": "trae-1", "messages": [
            {"role": "user", "content": "trae 提问"},
            {"role": "assistant", "content": "trae 回答"},
        ]}, ensure_ascii=False),
    ))
    conn.commit()
    conn.close()
    return base


def test_trae_legacy_memento(tmp_path, monkeypatch):
    base = _make_trae_legacy_db(tmp_path)
    monkeypatch.setattr("app.capture.adapters.trae._trae_dirs", lambda: [base])
    adapter = TraeAdapter()
    refs = adapter.discover()
    assert len(refs) == 1
    sessions = adapter.parse_sessions(refs[0])
    assert len(sessions) == 1
    assert sessions[0].session_id == "trae-1"
    assert [m.content for m in sessions[0].messages] == ["trae 提问", "trae 回答"]


def test_trae_skips_encrypted_db(tmp_path, monkeypatch):
    """新版 ModularData/ai-agent/database.db 加密 → 发现但标记为 encrypted。"""
    base = tmp_path / "Trae CN"
    mod = base / "ModularData" / "ai-agent"
    mod.mkdir(parents=True)
    # 真实 SQLCipher 文件 ≥ 4096 字节，且头部不是 "SQLite format 3\0"
    (mod / "database.db").write_bytes(b"\x00" * 4096)
    ws = base / "User" / "workspaceStorage" / "ws1"
    ws.mkdir(parents=True)
    (ws / "state.vscdb").write_bytes(b"not-a-sqlite-file")
    monkeypatch.setattr("app.capture.adapters.trae._trae_dirs", lambda: [base])
    refs = TraeAdapter().discover()
    # 新版：加密库被发现，标记 encrypted=True
    assert len(refs) == 1
    assert refs[0].session_id == "database"
    assert refs[0].encrypted is True
    assert refs[0].parse_error == "encrypted"


def test_trae_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.capture.adapters.trae._trae_dirs", lambda: [])
    assert TraeAdapter().discover() == []


# ---------- windsurf ----------

def test_windsurf_itemtable_heuristic(tmp_path, monkeypatch):
    db = tmp_path / "state.vscdb"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    conn.executemany("INSERT INTO ItemTable VALUES (?,?)", [
        ("aicoding.aichat.sess-w1", json.dumps({
            "messages": [{"role": "user", "content": "windsurf 问题"},
                         {"role": "assistant", "content": "windsurf 回答"}]})),
        ("workbench.composer.cmp-2", json.dumps({
            "conversation": [{"role": "user", "content": "composer 任务"}]})),
        ("workbench.some.ui-state", json.dumps({"messages": [{"role": "user", "content": "x"}]})),
        ("no.hint.key", json.dumps({"messages": [{"role": "user", "content": "y"}]})),
    ])
    conn.commit()
    conn.close()
    monkeypatch.setattr("app.capture.adapters.windsurf._db_path", lambda: db)
    adapter = WindsurfAdapter()
    refs = adapter.discover()
    assert len(refs) == 1
    sessions = {s.session_id: s for s in adapter.parse_sessions(refs[0])}
    # "chat"/"composer" 命中；"some.ui-state" 无 hint 不收
    assert set(sessions) == {"sess-w1", "cmp-2"}
    assert sessions["sess-w1"].messages[0].content == "windsurf 问题"


def test_windsurf_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.capture.adapters.windsurf._db_path", lambda: None)
    assert WindsurfAdapter().discover() == []


# ---------- copilot-cli ----------

def test_copilot_cli_json_file(tmp_path, monkeypatch):
    f = tmp_path / "session-state"
    f.write_text(json.dumps({"messages": [
        {"role": "user", "content": "copilot 问题"},
        {"role": "assistant", "content": "copilot 回答"},
    ]}), encoding="utf-8")
    monkeypatch.setattr("app.capture.adapters.copilot_cli._root", lambda: f)
    adapter = CopilotCliAdapter()
    refs = adapter.discover()
    assert len(refs) == 1
    s = adapter.parse(refs[0])
    assert s is not None
    assert len(s.messages) == 2


def test_copilot_cli_dir_jsonl(tmp_path, monkeypatch):
    d = tmp_path / "session-state"
    d.mkdir()
    (d / "sess-3.jsonl").write_text("\n".join([
        json.dumps({"role": "user", "content": "行1"}),
        json.dumps({"message": {"role": "assistant", "content": "行2"}}),
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr("app.capture.adapters.copilot_cli._root", lambda: d)
    adapter = CopilotCliAdapter()
    refs = adapter.discover()
    assert len(refs) == 1 and refs[0].session_id == "sess-3"
    s = adapter.parse(refs[0])
    assert [m.content for m in s.messages] == ["行1", "行2"]


def test_copilot_cli_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.capture.adapters.copilot_cli._root",
                        lambda: tmp_path / "nope")
    assert CopilotCliAdapter().discover() == []


# ---------- 黄标机制（scan 层） ----------

def _fake_env(tmp_path, results_box):
    """造一个恒失败（results_box 空 → 解析抛异常）或成功（有 session）的假 agent。

    注：M4 后"解析成功但返回空"＝跳过（新建空文件）而非失败，故"恒失败"必须靠
    parse_sessions 抛异常表达（格式漂移/读不了）。"""
    class FakeAdapter:
        name = "fake"

        def discover(self):
            return []

        def parse(self, ref):
            return None

        def parse_sessions(self, ref):
            s = results_box.get("s")
            if s is not None:
                return [s]
            raise ValueError("恒失败源（格式漂移）")

    f = tmp_path / "data.txt"
    f.write_text("raw", encoding="utf-8")
    ref = SessionRef(agent="fake", session_id="x", path=f, size=1, mtime=0)

    def fake_detect(enabled=None, force=False, min_interval=0.0):
        return {"fake": [ref]}

    import app.capture.scan as scan_mod

    scan_mod.REGISTRY = {"fake": FakeAdapter}
    scan_mod.detect = fake_detect
    return scan_mod


def test_yellow_flag_after_three_consecutive_failures(tmp_path, monkeypatch, caplog):
    store = Store(tmp_path)
    store.ensure_layout()
    box = {}
    scan_mod = _fake_env(tmp_path, box)
    monkeypatch.setattr("app.capture.scan.REGISTRY", scan_mod.REGISTRY)
    monkeypatch.setattr("app.capture.scan.detect", scan_mod.detect)

    with caplog.at_level(logging.WARNING, logger="experientia.capture"):
        for _ in range(3):
            scan_mod.run_scan(store, verbose=False)
    assert store.load_capture_failures() == {"fake": 3}
    assert any("黄标" in r.message for r in caplog.records)


def test_yellow_flag_lifted_on_recovery(tmp_path, monkeypatch, caplog):
    store = Store(tmp_path)
    store.ensure_layout()
    box = {}
    scan_mod = _fake_env(tmp_path, box)
    monkeypatch.setattr("app.capture.scan.REGISTRY", scan_mod.REGISTRY)
    monkeypatch.setattr("app.capture.scan.detect", scan_mod.detect)

    for _ in range(3):
        scan_mod.run_scan(store, verbose=False)
    assert store.load_capture_failures() == {"fake": 3}

    box["s"] = Session(agent="fake", session_id="x",
                       messages=[Message(role="user", content="ok")])
    with caplog.at_level(logging.INFO, logger="experientia.capture"):
        scan_mod.run_scan(store, verbose=False)
    assert store.load_capture_failures() == {}
    assert any("黄标解除" in r.message for r in caplog.records)


def test_all_skipped_is_not_failure(tmp_path, monkeypatch):
    """全部 ref 命中增量跳过（无新工作）≠ 解析失败，不得累加黄标计数。"""
    store = Store(tmp_path)
    store.ensure_layout()
    box = {"s": Session(agent="fake", session_id="x",
                        messages=[Message(role="user", content="ok")])}
    scan_mod = _fake_env(tmp_path, box)
    monkeypatch.setattr("app.capture.scan.REGISTRY", scan_mod.REGISTRY)
    monkeypatch.setattr("app.capture.scan.detect", scan_mod.detect)

    scan_mod.run_scan(store, verbose=False)          # 成功，状态记录
    for _ in range(4):                                # 全跳过，计数应保持 0
        scan_mod.run_scan(store, verbose=False)
    assert store.load_capture_failures() == {}
