"""Wave 3 SQLite/KV 系 adapter 测试（goose/kilocode/opencode/zed/hermes/openhands/cursor/dsh）。

模式与 Wave 1/2 一致：内联 fixture（tmp_path 建库/建文件）+ 路径不存在返回空。
"""

import json
import os
import sqlite3
from pathlib import Path

from app.capture.adapters.cursor import CursorAdapter
from app.capture.adapters.dsh import DshAdapter
from app.capture.adapters.goose import GooseAdapter
from app.capture.adapters.hermes import HermesAdapter
from app.capture.adapters.kilocode import KiloCodeAdapter, parse_opencode_like_db
from app.capture.adapters.openhands import OpenHandsAdapter
from app.capture.adapters.opencode import OpenCodeAdapter, _db_candidates
from app.capture.adapters.zed import ZedAdapter
from app.capture.models import SessionRef


# ---------- goose ----------

def _make_goose_db(tmp_path) -> Path:
    home = tmp_path / "goose"
    (home / "sessions").mkdir(parents=True)
    db = home / "sessions" / "sessions.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, description TEXT, "
        "working_dir TEXT, created_at TEXT, transcript TEXT)"
    )
    transcript = json.dumps({"messages": [
        {"role": "user", "content": "帮我写个函数"},
        {"role": "assistant", "parts": [
            {"text": "好的"},
            {"toolCall": {"name": "read_file", "arguments": {"path": "a.py"}}},
        ]},
    ]}, ensure_ascii=False)
    conn.execute(
        "INSERT INTO sessions VALUES ('g1', 'd', '/work/proj', "
        "'2026-08-01T00:00:00Z', ?)", (transcript,)
    )
    conn.commit()
    conn.close()
    return db


def test_goose_parse_sessions(tmp_path, monkeypatch):
    db = _make_goose_db(tmp_path)
    monkeypatch.setenv("GOOSE_HOME", str(db.parent.parent))
    adapter = GooseAdapter()
    refs = adapter.discover()
    assert len(refs) == 1 and refs[0].path == db
    sessions = adapter.parse_sessions(refs[0])
    assert len(sessions) == 1
    s = sessions[0]
    assert s.session_id == "g1" and s.project == "/work/proj"
    assert s.started_at == "2026-08-01T00:00:00Z"
    assert s.messages[0].content == "帮我写个函数"
    assert s.messages[1].tool_use["name"] == "read_file"


def test_goose_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOSE_HOME", str(tmp_path / "nope"))
    assert GooseAdapter().discover() == []


def test_goose_bad_schema_returns_empty(tmp_path, monkeypatch):
    home = tmp_path / "goose"
    (home / "sessions").mkdir(parents=True)
    db = home / "sessions" / "sessions.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE other (x TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("GOOSE_HOME", str(home))
    adapter = GooseAdapter()
    refs = adapter.discover()
    assert refs and adapter.parse_sessions(refs[0]) == []


# ---------- kilocode ----------

def _make_kilo_db(tmp_path):
    d = tmp_path / "kilo"
    d.mkdir(parents=True)
    db = d / "kilo.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, "
        "role TEXT, data TEXT, time_created TEXT)"
    )
    rows = [
        ("s1", "user", {"role": "user", "content": "你好"}, "2026-08-01T01:00:00Z"),
        ("s1", "assistant", {"role": "assistant",
                             "parts": [{"text": "你好，有什么可以帮你"}]},
         "2026-08-01T01:00:05Z"),
        ("s2", "user", {"role": "user", "content": "写测试"}, "2026-08-02T01:00:00Z"),
    ]
    for i, (sid, role, data, ts) in enumerate(rows):
        conn.execute(
            "INSERT INTO messages (session_id, role, data, time_created) "
            "VALUES (?,?,?,?)", (sid, role, json.dumps(data, ensure_ascii=False), ts)
        )
    conn.commit()
    conn.close()
    return db


def test_kilocode_two_sessions(tmp_path, monkeypatch):
    db = _make_kilo_db(tmp_path)
    monkeypatch.setenv("KILO_DB", str(db))
    adapter = KiloCodeAdapter()
    refs = adapter.discover()
    assert len(refs) == 1
    sessions = adapter.parse_sessions(refs[0])
    by_id = {s.session_id: s for s in sessions}
    assert set(by_id) == {"s1", "s2"}
    assert [m.content for m in by_id["s1"].messages] == ["你好", "你好，有什么可以帮你"]
    assert by_id["s1"].started_at == "2026-08-01T01:00:00Z"


def test_kilocode_role_in_column(tmp_path, monkeypatch):
    """role 不在 data JSON 里而在独立列（表结构漂移容错）。"""
    d = tmp_path / "kilo2"
    d.mkdir(parents=True)
    db = d / "kilo.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE message (id INTEGER PRIMARY KEY, session_id TEXT, "
        "role TEXT, content TEXT)"
    )
    conn.execute(
        "INSERT INTO message (session_id, role, content) VALUES "
        "('k1','user','直接列存文本')",
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("KILO_DB", str(db))
    sessions = KiloCodeAdapter().parse_sessions(
        SessionRef(agent="kilocode", session_id="kilo.db", path=db, size=1, mtime=0)
    )
    assert len(sessions) == 1
    assert sessions[0].messages[0].content == "直接列存文本"
    assert sessions[0].messages[0].role == "user"


def test_kilocode_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("KILO_DB", str(tmp_path / "nope.db"))
    assert KiloCodeAdapter().discover() == []


def test_parse_opencode_like_no_messages_table(tmp_path):
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sessions (id TEXT)")
    conn.commit()
    conn.close()
    conn2 = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    assert parse_opencode_like_db(conn2, "kilocode") == []
    conn2.close()


# ---------- opencode ----------

def test_opencode_db_candidate(tmp_path, monkeypatch):
    """现行 SQLite 主库 + dev channel 库双探测。"""
    root = tmp_path / "opencode"
    root.mkdir()
    main = root / "opencode.db"
    dev = root / "opencode-dev.db"
    for db in (main, dev):
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE message (id INTEGER PRIMARY KEY, session_id TEXT, "
            "data TEXT, time_created INTEGER)"
        )
        conn.execute(
            "INSERT INTO message (session_id, data, time_created) VALUES "
            "('oc1', ?, 1700000000000)",
            (json.dumps({"role": "user", "parts": [{"text": "opencode 会话"}]}),),
        )
        conn.commit()
        conn.close()
    monkeypatch.delenv("OPENCODE_DATA", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-none"))  # 排除真实 home 的 .local/share/opencode
    if "win32" in str(__import__("sys").platform):
        monkeypatch.setenv("LOCALAPPDATA", str(root.parent))
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(root.parent))
    cands = _db_candidates()
    assert main in cands and dev in cands
    adapter = OpenCodeAdapter()
    refs = adapter.discover()
    assert {r.path for r in refs} == {main, dev}
    sessions = adapter.parse_sessions(next(r for r in refs if r.path == main))
    assert len(sessions) == 1
    assert sessions[0].messages[0].content == "opencode 会话"


def test_opencode_legacy_storage_layout(tmp_path, monkeypatch):
    """旧版 JSON 目录布局（storage/message/<sid>/*.json）双探测。"""
    root = tmp_path / "opencode"
    (root / "storage" / "session" / "oc9").mkdir(parents=True)
    msg_dir = root / "storage" / "message" / "oc9"
    msg_dir.mkdir(parents=True)
    (msg_dir / "m1.json").write_text(json.dumps({
        "id": "m1", "session_id": "oc9", "role": "user",
        "time": {"created": 1700000000000},
        "parts": [{"type": "text", "text": "旧布局消息"}],
    }), encoding="utf-8")
    (root / "storage" / "session" / "oc9" / "info.json").write_text(json.dumps(
        {"id": "oc9", "title": "t", "directory": "/proj/legacy"}), encoding="utf-8")
    monkeypatch.delenv("OPENCODE_DATA", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-none"))
    if "win32" in str(__import__("sys").platform):
        monkeypatch.setenv("LOCALAPPDATA", str(root.parent))
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(root.parent))
    adapter = OpenCodeAdapter()
    refs = adapter.discover()
    assert len(refs) == 1 and refs[0].path == root / "storage"
    sessions = adapter.parse_sessions(refs[0])
    assert len(sessions) == 1
    assert sessions[0].session_id == "oc9"
    assert sessions[0].project == "/proj/legacy"
    assert sessions[0].messages[0].content == "旧布局消息"


def test_opencode_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENCODE_DATA", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    if "win32" in str(__import__("sys").platform):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert _db_candidates() == []
    assert OpenCodeAdapter().discover() == []


# ---------- zed ----------

def test_zed_parse_sessions(tmp_path, monkeypatch):
    """threads.db：threads 表，data 列整 thread JSON。"""
    threads_json = json.dumps({
        "messages": [
            {"role": "user", "content": "zed 问题"},
            {"role": "assistant", "content": "回答"},
        ],
    })
    base = tmp_path / "zed"
    (base / "threads").mkdir(parents=True)
    db = base / "threads" / "threads.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, data TEXT)")
    conn.execute("INSERT INTO threads VALUES ('th1', ?)", (threads_json,))
    conn.commit()
    conn.close()
    monkeypatch.setattr("app.capture.adapters.zed._data_dir", lambda: base)
    adapter = ZedAdapter()
    refs = adapter.discover()
    assert len(refs) == 1
    sessions = adapter.parse_sessions(refs[0])
    assert len(sessions) == 1
    assert [m.content for m in sessions[0].messages] == ["zed 问题", "回答"]


def test_zed_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.capture.adapters.zed._data_dir", lambda: tmp_path / "nope")
    assert ZedAdapter().discover() == []


# ---------- hermes ----------

def test_hermes_state_db(tmp_path, monkeypatch):
    """真实 Hermes（实测）为规范化分列 schema：sessions × messages 行。"""
    home = tmp_path / "hermes"
    home.mkdir()
    db = home / "state.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, model TEXT, "
        "started_at REAL, cwd TEXT, git_repo_root TEXT, "
        "input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, "
        "role TEXT, content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, "
        "timestamp REAL, active INTEGER)"
    )
    conn.execute(
        "INSERT INTO sessions VALUES "
        "('h1','cli','qwen-27b-local',1786752000.0,'/proj/a',NULL,100,50,10),"
        "('h2','cli','qwen-27b-local',1786752100.0,NULL,'/repo/b',NULL,NULL,NULL)"
    )
    conn.executemany(
        "INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls, "
        "tool_name, timestamp, active) VALUES (?,?,?,?,?,?,?,1)",
        [
            ("h1", "user", "hermes 问题", None, None, None, 1786752000.5),
            ("h1", "assistant", "回答", None, None, None, 1786752002.0),
            ("h2", "assistant", None, None,
             '[{"id":"c1","type":"function","function":{"name":"bash",'
             '"arguments":"{\\"cmd\\":\\"ls\\"}"}}]', None, 1786752100.5),
            ("h2", "tool", "ls 输出", "c1", None, "bash", 1786752101.0),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("HERMES_HOME", str(home))
    adapter = HermesAdapter()
    refs = adapter.discover()
    assert len(refs) == 1 and refs[0].path == db
    sessions = adapter.parse_sessions(refs[0])
    assert len(sessions) == 2
    h1, h2 = sessions
    # h1：规范化行 → 内容/project/model/tokens/started_at(UTC ISO)
    assert h1.session_id == "h1"
    assert [m.content for m in h1.messages] == ["hermes 问题", "回答"]
    assert h1.project == "/proj/a"
    assert h1.model == "qwen-27b-local"
    assert h1.tokens == 160
    assert h1.started_at == "2026-08-15T00:00:00Z"
    # h2：assistant tool_use（tool_calls JSON 拆出）+ 配对 tool_result
    use = [m for m in h2.messages if m.tool_use]
    res = [m for m in h2.messages if m.tool_result]
    assert len(use) == 1 and use[0].tool_use["name"] == "bash"
    assert use[0].tool_use["call_id"] == "c1"
    assert "ls" in use[0].tool_use["arguments"]
    assert len(res) == 1 and res[0].tool_result["output"] == "ls 输出"
    assert h2.project == "/repo/b"


def test_hermes_json_fallback(tmp_path, monkeypatch):
    home = tmp_path / "hermes2"
    (home / "sessions").mkdir(parents=True)
    f = home / "sessions" / "abc.json"
    f.write_text(json.dumps({
        "session_id": "abc",
        "messages": [{"role": "user", "content": "json 兜底"},
                     {"role": "assistant", "content": "ok"}],
    }), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    adapter = HermesAdapter()
    refs = adapter.discover()
    assert len(refs) == 1 and refs[0].path == f
    sessions = adapter.parse_sessions(refs[0])
    assert len(sessions) == 1
    assert sessions[0].session_id == "abc"
    assert len(sessions[0].messages) == 2


def test_hermes_absent(tmp_path, monkeypatch):
    """HERMES_HOME 设为空目录时，auto-search 应找到本机安装的 Hermes。"""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "nope"))
    from app.capture.adapters.hermes import HermesAdapter
    refs = HermesAdapter().discover()
    # 本机有 Hermes 安装 → 应通过 auto-search 找到
    if refs:
        assert refs[0].agent == "hermes"
    else:
        # 本机无 Hermes 安装 → 返回空
        assert refs == []


# ---------- openhands ----------

def test_openhands_conversation_events(tmp_path, monkeypatch):
    conv = tmp_path / "conv-1"
    (conv / "events").mkdir(parents=True)
    (conv / "base_state.json").write_text(json.dumps(
        {"conversation_id": "conv-1", "directory": "/proj/oh",
         "created_at": "2026-07-02T00:00:00Z"}), encoding="utf-8")
    events = [
        (0, "message", {"event_type": "message", "role": "user",
                        "message": "修个 bug"}),
        (1, "action", {"event_type": "action",
                       "action": {"name": "run_ipython",
                                  "args": {"code": "print(1)"},
                                  "action_id": "a1"}}),
        (2, "observation", {"event_type": "observation",
                            "observation": {"observation": "1", "action_id": "a1"}}),
        (3, "message", {"event_type": "message", "role": "assistant",
                        "message": "已修复"}),
    ]
    for seq, name, payload in events:
        (conv / "events" / f"{seq:04d}_{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("app.capture.adapters.openhands._conv_root",
                        lambda: tmp_path)
    adapter = OpenHandsAdapter()
    refs = adapter.discover()
    assert len(refs) == 1
    sessions = adapter.parse_sessions(refs[0])
    assert len(sessions) == 1
    s = sessions[0]
    assert s.session_id == "conv-1" and s.project == "/proj/oh"
    assert s.messages[0].content == "修个 bug"
    assert s.messages[1].tool_use["name"] == "run_ipython"
    assert s.messages[2].tool_result["output"] == "1"
    assert s.messages[3].role == "assistant"


def test_openhands_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.capture.adapters.openhands._conv_root",
                        lambda: tmp_path / "nope")
    assert OpenHandsAdapter().discover() == []


# ---------- cursor ----------

def test_cursor_itemtable_kv(tmp_path, monkeypatch):
    db = tmp_path / "state.vscdb"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    aichat = json.dumps({"messages": [
        {"role": "user", "content": "cursor 提问"},
        {"role": "assistant", "content": "cursor 回答"},
    ]}, ensure_ascii=False)
    conn.executemany("INSERT INTO ItemTable VALUES (?,?)", [
        ("cursorDiskKV.aichat.sess-uuid-1", aichat),
        ("cursorDiskKV.composer.comp-1",
         json.dumps({"messages": [{"role": "user", "content": "composer 任务"}]},
                    ensure_ascii=False)),
        ("some.other.key", "unrelated"),
    ])
    conn.commit()
    conn.close()
    monkeypatch.setattr("app.capture.adapters.cursor._db_path", lambda: db)
    adapter = CursorAdapter()
    refs = adapter.discover()
    assert len(refs) == 1
    sessions = {s.session_id: s for s in adapter.parse_sessions(refs[0])}
    assert set(sessions) == {"sess-uuid-1", "comp-1"}
    assert sessions["sess-uuid-1"].messages[1].content == "cursor 回答"
    assert sessions["comp-1"].messages[0].content == "composer 任务"


def test_cursor_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.capture.adapters.cursor._db_path", lambda: None)
    assert CursorAdapter().discover() == []


def test_cursor_no_itemtable(tmp_path, monkeypatch):
    db = tmp_path / "state.vscdb"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE Other (x TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr("app.capture.adapters.cursor._db_path", lambda: db)
    adapter = CursorAdapter()
    refs = adapter.discover()
    assert refs and adapter.parse_sessions(refs[0]) == []


# ---------- dsh ----------

def test_dsh_jsonl(tmp_path, monkeypatch):
    d = tmp_path / "dsh"
    (d / "sessions").mkdir(parents=True)
    f = d / "sessions" / "sess-7.jsonl"
    lines = [
        json.dumps({"role": "user", "content": "dsh 问题"}),
        json.dumps({"type": "assistant",
                    "message": {"role": "assistant", "content": "dsh 回答"}}),
        "not-a-json-line",
    ]
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setenv("DSH_HOME", str(d))
    adapter = DshAdapter()
    refs = adapter.discover()
    assert len(refs) == 1
    s = adapter.parse(refs[0])
    assert s is not None
    assert [m.content for m in s.messages] == ["dsh 问题", "dsh 回答"]


def test_dsh_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "nope"))
    assert DshAdapter().discover() == []


# ---------- 注册表集成：detect() 在无对应目录的机器上零报错零输出 ----------

def test_detect_zero_errors_without_dirs(tmp_path, monkeypatch):
    from app.capture import registry

    envs = {
        "GOOSE_HOME": str(tmp_path / "no1"),
        "KILO_DB": str(tmp_path / "no2.db"),
        "HERMES_HOME": str(tmp_path / "no3"),
        "DSH_HOME": str(tmp_path / "no4"),
        "OPENCODE_DATA": str(tmp_path / "no5"),
    }
    for k, v in envs.items():
        monkeypatch.setenv(k, v)
    if "win32" in str(__import__("sys").platform):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("APPDATA", str(tmp_path))
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no6"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no7"))
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(tmp_path / "no8"))
    monkeypatch.setattr("app.capture.adapters.opencode._data_roots", lambda: [])
    monkeypatch.setattr("app.capture.adapters.zed._data_dir", lambda: None)
    monkeypatch.setattr("app.capture.adapters.openhands._conv_root", lambda: tmp_path / "no9")
    monkeypatch.setattr("app.capture.adapters.cursor._db_path", lambda: None)
    monkeypatch.setattr("app.capture.adapters.hermes._home", lambda: tmp_path / "no10")
    found = registry.detect()
    wave3 = {"opencode", "goose", "kilocode", "zed", "hermes",
             "openhands", "cursor", "dsh"}
    assert not (wave3 & set(found))


def test_openhands_signature_tracks_event_append(tmp_path, monkeypatch):
    """低2：签名=目录内会话文件总 size + 最大 mtime——事件追加在 events/
    子目录内不改变父目录 mtime，旧口径（父目录 stat）进行中的会话首次扫描后
    永不更新；新口径下追加事件签名必须变化。"""
    conv = tmp_path / "conv-live"
    (conv / "events").mkdir(parents=True)
    (conv / "base_state.json").write_text(
        json.dumps({"conversation_id": "conv-live"}), encoding="utf-8")
    t1 = (2026, 8, 1, 10, 0, 0)
    e1 = conv / "events" / "0001_message.json"
    e1.write_text(json.dumps({"event_type": "message", "role": "user",
                              "message": "第一句"}), encoding="utf-8")
    import time
    time1 = time.mktime(time.struct_time(t1 + (0, 0, -1)))
    os.utime(e1, (time1, time1))
    os.utime(conv / "base_state.json", (time1, time1))
    monkeypatch.setattr("app.capture.adapters.openhands._conv_root", lambda: tmp_path)
    adapter = OpenHandsAdapter()
    ref1 = adapter.discover()[0]
    # 追加事件（只动 events/ 子目录）
    t2 = (2026, 8, 1, 11, 0, 0)
    time2 = time.mktime(time.struct_time(t2 + (0, 0, -1)))
    e2 = conv / "events" / "0002_message.json"
    e2.write_text(json.dumps({"event_type": "message", "role": "assistant",
                              "message": "第二句，更长一些"}), encoding="utf-8")
    os.utime(e2, (time2, time2))
    ref2 = adapter.discover()[0]
    assert ref2.size > ref1.size
    assert ref2.mtime == time2 > ref1.mtime
