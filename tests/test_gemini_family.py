"""Wave 2 测试：Gemini 系三家（gemini-cli / qwen-code / iflow，单 Chat JSON）。"""

import json

from app.capture.adapters.gemini_family import (
    GeminiCliAdapter,
    IflowAdapter,
    QwenCodeAdapter,
)
from app.capture.models import SessionRef

CHAT = {
    "version": "1",
    "projectHash": "abc123",
    "startTime": "2026-08-28T09:00:00Z",
    "messages": [
        {"role": "user", "parts": [{"text": "帮我写个快排"}],
         "timestamp": "2026-08-28T09:00:01Z"},
        {"role": "model", "parts": [
            {"text": "先看下代码结构"},
            {"functionCall": {"id": "fc1", "name": "read_file", "args": {"path": "a.py"}}},
        ], "timestamp": "2026-08-28T09:00:05Z",
         "usageMetadata": {"promptTokenCount": 100, "totalTokenCount": 150}},
        {"role": "user", "parts": [
            {"functionResponse": {"name": "read_file", "response": {"content": "def f(): pass"}}}
        ], "timestamp": "2026-08-28T09:00:06Z"},
        {"role": "model", "parts": [{"text": "已实现：\ndef qs(a): ..."}],
         "timestamp": "2026-08-28T09:00:10Z",
         "usageMetadata": {"totalTokenCount": 300}},
    ],
}


def _write_chat(tmp_path, chat, name="session-1.json"):
    p = tmp_path / "chats" / name
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(chat, ensure_ascii=False), encoding="utf-8")
    st = p.stat()
    return SessionRef(agent="gemini-cli", session_id=name[:-5], path=p,
                      size=st.st_size, mtime=st.st_mtime)


def test_gemini_parse(tmp_path):
    ref = _write_chat(tmp_path, CHAT)
    s = GeminiCliAdapter().parse(ref)
    assert s is not None
    assert [m.role for m in s.messages] == ["user", "assistant", "assistant", "tool", "assistant"]
    assert s.messages[0].content == "帮我写个快排"
    assert s.messages[1].content == "先看下代码结构"
    assert s.messages[2].tool_use == {"name": "read_file", "arguments": {"path": "a.py"},
                                      "call_id": "fc1"}
    assert "def f(): pass" in (s.messages[3].tool_result["output"] or "")
    assert "qs" in s.messages[4].content
    assert s.project == "abc123"
    assert s.started_at == "2026-08-28T09:00:00Z"
    assert s.tokens == 450


def test_gemini_parse_empty_none(tmp_path):
    ref = _write_chat(tmp_path, {"messages": []}, name="empty.json")
    assert GeminiCliAdapter().parse(ref) is None


def test_gemini_parse_bad_file_none(tmp_path):
    p = tmp_path / "chats" / "bad.json"
    p.parent.mkdir(parents=True)
    p.write_text("{broken", encoding="utf-8")
    st = p.stat()
    ref = SessionRef(agent="gemini-cli", session_id="bad", path=p,
                     size=st.st_size, mtime=st.st_mtime)
    assert GeminiCliAdapter().parse(ref) is None


def test_qwen_and_iflow_home(tmp_path, monkeypatch):
    import pathlib

    home = tmp_path / "home"
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    chat = {"messages": [{"role": "user", "parts": [{"text": "hi"}]}]}

    for cls, home_dir in ((QwenCodeAdapter, ".qwen"), (IflowAdapter, ".iflow")):
        d = home / home_dir / "tmp" / "proj1" / "chats"
        d.mkdir(parents=True)
        p = d / "session-x.json"
        p.write_text(json.dumps(chat), encoding="utf-8")
        refs = cls().discover()
        assert any(r.path == p for r in refs), f"{cls.__name__} 未发现"
        s = cls().parse(next(r for r in refs if r.path == p))
        assert s is not None and s.messages[0].content == "hi"
        assert s.agent == cls().name


def test_gemini_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "ghome"))
    d = tmp_path / "ghome" / "tmp" / "h1" / "chats"
    d.mkdir(parents=True)
    p = d / "session-y.json"
    p.write_text(json.dumps({"messages": [{"role": "user", "parts": [{"text": "yo"}]}]}),
                 encoding="utf-8")
    refs = GeminiCliAdapter().discover()
    assert any(r.path == p for r in refs)
