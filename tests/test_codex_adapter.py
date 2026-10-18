"""Codex 解析器测试。

用内置 fixture 验证归一化；另有一个对真实 ~/.codex 会话的集成测试
（本机没有 Codex 数据时自动跳过）。
"""

import json

import pytest

from app.capture.adapters.codex import CodexAdapter, _session_id_from_path
from app.capture.models import SessionRef

SAMPLE = [
    {"timestamp": "2024-01-01T00:00:16Z", "type": "session_meta",
     "payload": {"session_id": "s1", "cwd": "C:\\proj",
                 "timestamp": "2024-01-01T00:00:16Z",
                 "provenance": {"model": "C:\\models\\Test-7B.gguf"}}},
    {"timestamp": "2024-01-01T00:00:20Z", "type": "turn_context",
     "payload": {"model": "Test-7B"}},
    {"timestamp": "2024-01-01T00:00:21Z", "type": "response_item",
     "payload": {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "写个投放标题"}]}},
    {"timestamp": "2024-01-01T00:00:25Z", "type": "response_item",
     "payload": {"type": "function_call", "name": "shell", "arguments": "{}",
                 "call_id": "c1"}},
    {"timestamp": "2024-01-01T00:00:26Z", "type": "response_item",
     "payload": {"type": "function_call_output", "call_id": "c1", "output": "ok"}},
    {"timestamp": "2024-01-01T00:00:30Z", "type": "response_item",
     "payload": {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "标题是……"}]}},
    {"timestamp": "2024-01-01T00:00:31Z", "type": "world_state",
     "payload": {"huge": "x" * 100}},
]


def _write_session(tmp_path, events, name="rollout-2024-01-01T00-00-00-00000000-0000-0000-0000-000000000000.jsonl"):
    f = tmp_path / name
    f.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    return f


def test_session_id_from_path():
    from pathlib import Path

    p = Path("rollout-2024-01-01T00-00-00-01234567-89ab-cdef-0123-456789abcdef.jsonl")
    assert _session_id_from_path(p) == "01234567-89ab-cdef-0123-456789abcdef"


def test_parse_normalizes(tmp_path):
    f = _write_session(tmp_path, SAMPLE)
    ref = SessionRef(agent="codex", session_id="s1", path=f,
                     size=f.stat().st_size, mtime=f.stat().st_mtime)
    s = CodexAdapter().parse(ref)
    assert s is not None
    assert s.session_id == "s1"
    assert s.project == "C:\\proj"
    assert s.model == "Test-7B"
    roles = [m.role for m in s.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert s.messages[0].content == "写个投放标题"
    assert s.messages[1].tool_use["name"] == "shell"
    assert s.messages[2].tool_result["output"] == "ok"
    d = s.to_dict()
    assert d["agent"] == "codex" and len(d["messages"]) == 4


def test_parse_empty_returns_none(tmp_path):
    f = _write_session(tmp_path, [{"type": "session_meta", "payload": {}}])
    ref = SessionRef(agent="codex", session_id="s2", path=f)
    assert CodexAdapter().parse(ref) is None


@pytest.mark.skipif(not __import__("pathlib").Path.home().joinpath(".codex", "sessions").is_dir(),
                    reason="本机没有 Codex 会话数据")
def test_parse_real_codex_session():
    """对本机真实 rollout 文件跑一遍（冒烟，不入库）。"""
    refs = CodexAdapter().discover()
    assert refs, "本机应有至少一个 Codex 会话"
    parsed = 0
    for ref in refs[:5]:
        s = CodexAdapter().parse(ref)
        if s is not None:
            parsed += 1
            assert s.agent == "codex"
            assert any(m.role == "user" for m in s.messages)
    assert parsed >= 1
