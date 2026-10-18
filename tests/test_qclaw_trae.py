"""P2a：qclaw v3 格式解析 + trae 失败循环止住（断链修复方案）。

- qclaw：v3 message 行（type="message"，正文在 message.role/content）可解析；
  派生轨迹文件（.trajectory.jsonl）在 discover 层显式跳过；
- trae：_has_ai_sessions 与 parse 同口径（extract_messages 非空才作 ref）；
  加密 ref 解析失败 = 显式跳过（更新签名、不计失败、计数冻结）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.capture.adapters.qclaw import QClawAdapter
from app.capture.models import SessionRef
from app.store.store import Store


# ---------- qclaw：v3 会话格式 ----------

QCLAW_V3_LINES = [
    {"type": "session", "version": 3, "id": "q1",
     "timestamp": "2026-08-01T10:00:00.000Z", "cwd": "C:\\proj\\x"},
    {"type": "model_change", "id": "mc1", "parentId": None,
     "timestamp": "2026-08-01T10:00:00.001Z", "provider": "qclaw",
     "modelId": "pool-m1"},
    {"type": "message", "id": "m1", "parentId": "mc1",
     "timestamp": "2026-08-01T10:00:01.000Z",
     "message": {"role": "user", "content": "帮我查一下这个报错",
                 "timestamp": 1785556801000}},
    {"type": "message", "id": "m2", "parentId": "m1",
     "timestamp": "2026-08-01T10:00:05.000Z",
     "message": {"role": "assistant",
                 "content": [
                     {"type": "toolCall", "id": "call_1", "name": "Read",
                      "arguments": {"path": "a.py"}},
                     {"type": "text", "text": "看了代码，问题在第 3 行。"},
                 ],
                 "api": "openai-completions", "provider": "qclaw",
                 "model": "pool-m1", "stopReason": "stop",
                 "timestamp": 1785556805000}},
    {"type": "message", "id": "m3", "parentId": "m2",
     "timestamp": "2026-08-01T10:00:09.000Z",
     "message": {"role": "user", "content": "不对，应该是第 5 行",
                 "timestamp": 1785556809000}},
    {"type": "message", "id": "m4", "parentId": "m3",
     "timestamp": "2026-08-01T10:00:12.000Z",
     "message": {"role": "assistant",
                 "content": [{"type": "text", "text": "确认是第 5 行。"}],
                 "model": "pool-m1", "timestamp": 1785556812000}},
    # 元事件行不进转录
    {"type": "custom", "customType": "model-snapshot", "data": {},
     "id": "c1", "parentId": "m4", "timestamp": "2026-08-01T10:00:13.000Z"},
]


def _write_qclaw_file(tmp_path: Path, name: str, lines: list) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines),
                 encoding="utf-8")
    return p


def test_qclaw_v3_parse(tmp_path):
    p = _write_qclaw_file(tmp_path, "q1.jsonl", QCLAW_V3_LINES)
    ref = SessionRef(agent="qclaw", session_id="q1", path=p,
                     size=p.stat().st_size, mtime=p.stat().st_mtime)
    s = QClawAdapter().parse(ref)
    assert s is not None
    user = [m for m in s.messages if m.role == "user"]
    asst = [m for m in s.messages if m.role == "assistant"]
    assert len(user) == 2 and len(asst) == 2
    assert user[0].content == "帮我查一下这个报错"
    # 块数组：toolCall 块不进转录，text 块落一条
    assert asst[0].content == "看了代码，问题在第 3 行。"
    assert s.started_at == "2026-08-01T10:00:01.000Z"
    assert s.model == "pool-m1"
    assert s.project == "C:\\proj\\x"


def test_qclaw_heartbeat_session_parses(tmp_path):
    """心跳会话（1 轮 user + HEARTBEAT_OK）：可解析但复盘零成本跳过（req_count=1）。"""
    lines = [
        {"type": "session", "version": 3, "id": "hb",
         "timestamp": "2026-08-01T09:00:00.000Z", "cwd": "C:\\ws"},
        {"type": "message", "id": "h1", "parentId": None,
         "timestamp": "2026-08-01T09:00:01.000Z",
         "message": {"role": "user", "content": "[OpenClaw heartbeat poll]"}},
        {"type": "message", "id": "h2", "parentId": "h1",
         "timestamp": "2026-08-01T09:00:02.000Z",
         "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "HEARTBEAT_OK"}],
                     "model": "modelroute"}},
    ]
    p = _write_qclaw_file(tmp_path, "hb.jsonl", lines)
    ref = SessionRef(agent="qclaw", session_id="hb", path=p,
                     size=p.stat().st_size, mtime=p.stat().st_mtime)
    s = QClawAdapter().parse(ref)
    assert s is not None and len(s.messages) == 2
    from app.capture.scan import session_to_review_dict

    store = Store(tmp_path)
    store.ensure_layout()
    d = session_to_review_dict(s, store)
    assert d["req_count"] == 1  # <2 → has_distillable_signals False（零成本）
    from app.distill.review import has_distillable_signals

    assert not has_distillable_signals(d)


def test_qclaw_discover_skips_trajectory(tmp_path, monkeypatch):
    root = tmp_path / "agents" / "main" / "sessions"
    root.mkdir(parents=True)
    _write_qclaw_file(root, "q1.jsonl", QCLAW_V3_LINES)
    _write_qclaw_file(root, "q1.trajectory.jsonl",
                      [{"traceSchema": "openclaw-trajectory", "type": "x"}])
    monkeypatch.setattr(QClawAdapter, "session_roots",
                        lambda self: [tmp_path / "agents"])
    refs = QClawAdapter().discover()
    assert [r.path.name for r in refs] == ["q1.jsonl"]


# ---------- trae：_has_ai_sessions 与 parse 同口径 ----------

def _vscdb_with(tmp_path: Path, name: str, rows: list) -> Path:
    db = tmp_path / name
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ItemTable (key TEXT, value BLOB)")
    conn.executemany("INSERT INTO ItemTable VALUES (?, ?)", rows)
    conn.commit()
    conn.close()
    return db


def test_trae_has_ai_sessions_empty_memento(tmp_path):
    """新版布局：memento 值是会话索引（list[].messages 全空）→ 不作 ref。"""
    from app.capture.adapters.trae import _has_ai_sessions

    blob = json.dumps({"list": [{"isCurrent": True, "sessionId": "s1",
                                 "messages": []}],
                       "currentSessionId": "s1"})
    db = _vscdb_with(tmp_path, "a.vscdb",
                     [("memento/icube-ai-agent-storage", blob.encode())])
    assert not _has_ai_sessions(db)


def test_trae_has_ai_sessions_with_messages(tmp_path):
    """旧版布局：memento 值带正文 messages → 是 ref。"""
    from app.capture.adapters.trae import _has_ai_sessions

    blob = json.dumps({"session_id": "s2", "messages": [
        {"role": "user", "content": "写个标题"},
        {"role": "assistant", "content": "标题 A"},
    ]})
    db = _vscdb_with(tmp_path, "b.vscdb",
                     [("memento/icube-ai-agent-storage", blob.encode())])
    assert _has_ai_sessions(db)


def test_trae_has_ai_sessions_no_memento(tmp_path):
    from app.capture.adapters.trae import _has_ai_sessions

    db = _vscdb_with(tmp_path, "c.vscdb",
                     [("ai-chat-v2.lastActiveSessionId", b"abc"),
                      ("chat.customModes", b"{}")])
    assert not _has_ai_sessions(db)


# ---------- 扫描层：加密 ref 显式跳过（不计失败、计数冻结） ----------

def _scan_env(tmp_path: Path, monkeypatch, encrypted: bool, raises: bool = False):
    import app.capture.scan as scan_mod

    raw = tmp_path / "database.db"
    raw.write_bytes(b"\x00" * 16)
    ref = SessionRef(agent="fake", session_id="enc1", path=raw,
                     size=16, mtime=1.0, encrypted=encrypted)

    class FakeAdapter:
        name = "fake"

        def discover(self):
            return []

        def parse(self, ref):
            return None

        def parse_sessions(self, ref):
            if raises:
                raise ValueError("解析炸了（格式漂移）")
            return []  # 解析成功但 0 会话（加密不可解 / 新建空文件）

    monkeypatch.setattr(scan_mod, "REGISTRY", {"fake": FakeAdapter})
    monkeypatch.setattr(scan_mod, "detect",
                        lambda enabled=None, force=False, min_interval=0.0: {"fake": [ref]})
    store = Store(tmp_path)
    store.ensure_layout()
    return scan_mod, store, ref


def test_scan_encrypted_ref_explicit_skip(tmp_path, monkeypatch):
    """加密 ref 解析失败 → 更新签名 + 不计失败 + 计数冻结。"""
    scan_mod, store, ref = _scan_env(tmp_path, monkeypatch, encrypted=True)
    store.save_capture_failures({"fake": 5})  # 历史计数
    result = scan_mod.run_scan(store, verbose=False, review=False)
    assert result.parse_failures == {}
    assert result.skipped >= 1
    # 签名已更新：下轮该 ref 走常规跳过，不再解析
    state = store.load_capture_state()
    assert state[str(ref.path)] == [ref.size, ref.mtime]
    # 计数冻结（不 +1）
    assert store.load_capture_failures().get("fake") == 5


def test_scan_plain_ref_failure_still_counts(tmp_path, monkeypatch):
    """非加密 ref 解析抛异常仍计失败（格式漂移信号语义不变）。"""
    scan_mod, store, ref = _scan_env(tmp_path, monkeypatch, encrypted=False,
                                     raises=True)
    store.save_capture_failures({"fake": 2})
    result = scan_mod.run_scan(store, verbose=False, review=False)
    assert result.parse_failures == {"fake": 1}
    # 真失败不更新签名（下轮重试）
    assert str(ref.path) not in store.load_capture_state()
    assert store.load_capture_failures().get("fake") == 3


def test_scan_empty_file_skipped_not_failure(tmp_path, monkeypatch):
    """M4：非加密 ref 解析成功但 0 会话（新建空文件）→ 更新签名跳过、不计失败、
    计数冻结（与加密分支对称），不再每轮重解析无限累加误触黄标。"""
    scan_mod, store, ref = _scan_env(tmp_path, monkeypatch, encrypted=False)
    store.save_capture_failures({"fake": 5})  # 历史计数
    result = scan_mod.run_scan(store, verbose=False, review=False)
    assert result.parse_failures == {}
    assert result.skipped >= 1
    # 签名已更新：文件不增长则下轮直接常规跳过，不再重解析
    assert store.load_capture_state()[str(ref.path)] == [ref.size, ref.mtime]
    # 计数冻结（不 +1）
    assert store.load_capture_failures().get("fake") == 5
