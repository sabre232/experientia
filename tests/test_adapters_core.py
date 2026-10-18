"""Wave 1 解析器测试（T1 文本系 9 家 + codex .zst）。

fixture 全部内联，不依赖磁盘真实数据（真实文件冒烟用 skipif）。
"""

import json
from pathlib import Path

import pytest

from app.capture.adapters.aider import AiderAdapter
from app.capture.adapters.claude_code import ClaudeCodeAdapter
from app.capture.adapters.cline import ClineAdapter
from app.capture.adapters.codex import CodexAdapter
from app.capture.adapters.codebuddy import CodeBuddyAdapter
from app.capture.adapters.openclaw import OpenClawAdapter
from app.capture.adapters.qclaw import QClawAdapter
from app.capture.adapters.qoder import QoderAdapter
from app.capture.adapters.roo_code import RooCodeAdapter
from app.capture.adapters.workbuddy import WorkBuddyAdapter
from app.capture.models import SessionRef


# ---------- Claude 系 ----------

CLAUDE_LINES = [
    {"type": "summary", "summary": "写投放标题"},
    {"type": "user", "timestamp": "2026-08-28T10:00:00Z", "sessionId": "abc",
     "cwd": "/proj/demo", "message": {"role": "user", "content": "写投放标题"}},
    {"type": "assistant", "timestamp": "2026-08-28T10:00:05Z", "sessionId": "abc",
     "cwd": "/proj/demo", "message": {"role": "assistant", "model": "claude-sonnet-4",
                                      "content": [
                                          {"type": "text", "text": "标题A"},
                                          {"type": "tool_use", "id": "tu_1",
                                           "name": "web_search", "input": {"q": "双十一"}},
                                      ]}},
    {"type": "user", "timestamp": "2026-08-28T10:00:08Z", "sessionId": "abc",
     "message": {"role": "user", "content": [
         {"type": "tool_result", "tool_use_id": "tu_1",
          "content": [{"type": "text", "text": "搜索结果"}]}]}},
    {"type": "assistant", "timestamp": "2026-08-28T10:00:12Z", "sessionId": "abc",
     "message": {"role": "assistant", "content": "标题B（利益点前置）"}},
]

# WorkBuddy 独立格式（type=message + role 字段，与 Claude 系不同）
WORKBUDDY_LINES = [
    {"type": "message", "role": "user", "content": "hello", "sessionId": "s1", "cwd": "C:\\proj", "id": "1"},
    {"type": "message", "role": "assistant", "content": "hi there", "id": "2"},
    {"type": "function_call", "callId": "t1", "name": "read_file", "arguments": "{\"path\":\"x.py\"}", "id": "3"},
    {"type": "function_call_result", "callId": "t1", "content": "def f(): pass", "id": "4"},
    {"type": "message", "role": "assistant", "content": "done", "id": "5"},
    {"type": "reasoning", "content": "thinking...", "id": "6"},
    {"type": "file-history-snapshot", "snapshot": {}, "cwd": "C:\\proj", "id": "7"},
]


def _write_jsonl(tmp_path, lines, name="s-uuid.jsonl") -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines),
                 encoding="utf-8")
    return p


def _ref(path) -> SessionRef:
    st = path.stat()
    return SessionRef(agent="claude-code", session_id=path.stem, path=path,
                      size=st.st_size, mtime=st.st_mtime)


def test_claude_code_parse(tmp_path):
    path = _write_jsonl(tmp_path, CLAUDE_LINES)
    s = ClaudeCodeAdapter().parse(_ref(path))
    assert s is not None
    assert [m.role for m in s.messages] == ["user", "assistant", "assistant", "tool", "assistant"]
    assert s.messages[0].content == "写投放标题"
    assert s.messages[1].content == "标题A"
    assert s.messages[2].tool_use == {"name": "web_search", "arguments": {"q": "双十一"},
                                      "call_id": "tu_1"}
    assert s.messages[3].tool_result["call_id"] == "tu_1"
    assert "搜索结果" in (s.messages[3].tool_result["output"] or "")
    assert s.model == "claude-sonnet-4"
    assert s.project == "/proj/demo"


def test_claude_code_empty_returns_none(tmp_path):
    path = _write_jsonl(tmp_path, [{"type": "summary", "summary": "空会话"}])
    assert ClaudeCodeAdapter().parse(_ref(path)) is None


def test_claude_family_bad_line_skipped(tmp_path):
    lines = list(CLAUDE_LINES)
    lines.insert(2, "这不是JSON{{")
    path = _write_jsonl(tmp_path, lines)
    s = ClaudeCodeAdapter().parse(_ref(path))
    assert s is not None and len(s.messages) == 5


@pytest.mark.parametrize("adapter_cls,home_env,rel", [
    (OpenClawAdapter, "OPENCLAW_STATE_DIR", "agents/main/sessions/uuid-1.jsonl"),
    (QClawAdapter, None, ".qclaw/agents/main/sessions/uuid-1.jsonl"),
    (CodeBuddyAdapter, "CODEBUDDY_HOME", "projects/proj/uuid-1.jsonl"),
    (QoderAdapter, "QODER_CONFIG_DIR", "projects/proj/uuid-1.jsonl"),
])
def test_claude_family_variants_parse(tmp_path, monkeypatch, adapter_cls, home_env, rel):
    """同族 adapter 共用 Claude 行分派：发现 + 解析行为一致。"""
    import pathlib

    root = tmp_path / "home"
    (root / rel).parent.mkdir(parents=True)
    path = root / rel
    path.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in CLAUDE_LINES),
                    encoding="utf-8")
    # home 与 env 双保险指向同一目录（env 可覆盖的走 env，qclaw 走 Path.home）
    if home_env:
        monkeypatch.setenv(home_env, str(root))
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: root))
    adapter = adapter_cls()
    refs = adapter.discover()
    assert any(r.path == path for r in refs), f"{adapter_cls.__name__} 未发现会话"
    target = next(r for r in refs if r.path == path)
    s = adapter.parse(target)
    assert s is not None and len(s.messages) == 5
    assert s.agent == adapter_cls().name


def test_workbuddy_parse(tmp_path, monkeypatch):
    """WorkBuddy 独立格式测试（type=message + role 字段，非 Claude 系）。"""
    import pathlib

    root = tmp_path / "home"
    (root / "projects" / "proj" / "uuid-1.jsonl").parent.mkdir(parents=True)
    path = root / "projects" / "proj" / "uuid-1.jsonl"
    path.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in WORKBUDDY_LINES),
                    encoding="utf-8")
    monkeypatch.setenv("WORKBUDDY_HOME", str(root))
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: root))
    adapter = WorkBuddyAdapter()
    refs = adapter.discover()
    assert any(r.path == path for r in refs), "WorkBuddy 未发现会话"
    target = next(r for r in refs if r.path == path)
    s = adapter.parse(target)
    assert s is not None and len(s.messages) == 5
    assert s.agent == "workbuddy"
    assert s.project == "C:\\proj"
    # 检查消息类型：user → assistant → tool_use → tool_result → assistant
    assert s.messages[0].role == "user"
    assert s.messages[0].content == "hello"
    assert s.messages[1].role == "assistant"
    assert s.messages[1].content == "hi there"
    assert s.messages[2].role == "assistant"
    assert s.messages[2].tool_use is not None
    assert s.messages[2].tool_use["name"] == "read_file"
    assert s.messages[3].role == "tool"
    assert s.messages[3].tool_result is not None
    assert s.messages[3].tool_result["output"] == "def f(): pass"
    assert s.messages[4].role == "assistant"
    assert s.messages[4].content == "done"


# ---------- Cline 系 ----------

CLINE_JSON = [
    {"role": "user", "content": "修这个 bug", "ts": "2026-08-28T09:00:00Z"},
    {"role": "assistant", "content": [
        {"type": "text", "text": "看了下代码"},
        {"type": "tool_use", "id": "x1", "name": "read_file", "input": {"path": "a.py"}},
    ]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x1", "content": "def f(): pass"}]},
    {"role": "assistant", "content": "已修复"},
]


def test_cline_parse(tmp_path, monkeypatch):
    import pathlib

    home = tmp_path / "home"
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    # globalStorage 根也指向 tmp（三平台 base 都重定向）
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    (home / ".cline" / "tasks" / "t1").mkdir(parents=True)
    path = home / ".cline" / "tasks" / "t1" / "api_conversation_history.json"
    path.write_text(json.dumps(CLINE_JSON, ensure_ascii=False), encoding="utf-8")

    adapter = ClineAdapter()
    refs = adapter.discover()
    assert any(r.path == path for r in refs)
    s = adapter.parse(next(r for r in refs if r.path == path))
    assert s is not None
    assert [m.role for m in s.messages] == ["user", "assistant", "assistant", "tool", "assistant"]
    assert s.messages[1].tool_use["name"] == "read_file"
    assert s.messages[3].tool_result["call_id"] == "x1"


def test_cline_parse_bad_file(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    st = p.stat()
    assert ClineAdapter().parse(SessionRef(agent="cline", session_id="x",
                                           path=p, size=st.st_size, mtime=st.st_mtime)) is None


def test_roo_code_extension_dir(tmp_path, monkeypatch):
    import pathlib

    home = tmp_path / "home"
    appdata = tmp_path / "appdata"
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("APPDATA", str(appdata))
    # VS Code globalStorage 根目录按平台取：win=APPDATA，linux=XDG_CONFIG_HOME。
    # 两个都指到同一目录，测试在 Windows 与 Linux CI 上等价。
    monkeypatch.setenv("XDG_CONFIG_HOME", str(appdata))

    ext = appdata / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline"
    tasks = ext / "tasks" / "t9"
    tasks.mkdir(parents=True)
    path = tasks / "api_conversation_history.json"
    path.write_text(json.dumps(CLINE_JSON, ensure_ascii=False), encoding="utf-8")

    adapter = RooCodeAdapter()
    refs = adapter.discover()
    assert any(r.path == path for r in refs)
    assert adapter.name == "roo-code"


# ---------- Aider ----------

AIDER_MD = """# Chat history for /proj/demo

## [2026-08-28 10:00:00] gpt-4o

**User:** 帮我写个快排

**Assistant:** 好的，实现如下：
```python
def qs(a): ...
```

**User:** 再加个测试

**Assistant:** 已加。
"""


def test_aider_parse(tmp_path):
    repo = tmp_path / "repo" / "demo"
    repo.mkdir(parents=True)
    path = repo / ".aider.chat.history.md"
    path.write_text(AIDER_MD, encoding="utf-8")
    st = path.stat()
    ref = SessionRef(agent="aider", session_id="demo", path=path,
                     size=st.st_size, mtime=st.st_mtime)
    s = AiderAdapter().parse(ref)
    assert s is not None
    assert [m.role for m in s.messages] == ["user", "assistant", "user", "assistant"]
    assert s.messages[0].content == "帮我写个快排"
    assert "def qs(a): ..." in s.messages[1].content
    assert s.model == "gpt-4o"
    assert s.started_at == "2026-08-28 10:00:00"


def test_aider_discover_requires_config(tmp_path, monkeypatch):
    """：无 aider_scan_roots → 不探测（不再回落 home）；配了才扫。"""
    import pathlib

    from app.capture.adapters import aider

    home = tmp_path / "home"
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    repo = home / "work" / "repo1"
    repo.mkdir(parents=True)
    (repo / ".aider.chat.history.md").write_text(AIDER_MD, encoding="utf-8")
    # 未配置扫描根 → 返回空（不再 os.walk 整棵家目录）
    monkeypatch.setattr(aider, "_load_config", lambda: {})
    assert AiderAdapter().discover() == []
    # 显式配置 home 为扫描根 → 正常发现
    monkeypatch.setattr(aider, "_load_config",
                        lambda: {"aider_scan_roots": [str(home)]})
    refs = AiderAdapter().discover()
    assert any(r.path == repo / ".aider.chat.history.md" for r in refs)


def test_aider_empty_md_none(tmp_path):
    p = tmp_path / ".aider.chat.history.md"
    p.write_text("# 空", encoding="utf-8")
    st = p.stat()
    assert AiderAdapter().parse(SessionRef(agent="aider", session_id="x",
                                           path=p, size=st.st_size, mtime=st.st_mtime)) is None


# ---------- Codex .zst ----------

CODEX_EVENTS = [
    {"type": "session_meta", "payload": {"session_id": "u1", "cwd": "/p",
                                         "timestamp": "2026-08-28T10:00:00Z",
                                         "provenance": {"model": "o4"}},
     "timestamp": "2026-08-28T10:00:00Z"},
    {"type": "response_item",
     "payload": {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "修 bug"}]},
     "timestamp": "2026-08-28T10:00:01Z"},
    {"type": "response_item",
     "payload": {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "已修复"}]},
     "timestamp": "2026-08-28T10:00:02Z"},
]


def _codex_ref(path, name) -> SessionRef:
    st = path.stat()
    return SessionRef(agent="codex", session_id=name, path=path,
                      size=st.st_size, mtime=st.st_mtime)


def test_codex_plain_jsonl(tmp_path):
    p = tmp_path / "rollout-2026-08-28T10-00-00-u1.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in CODEX_EVENTS), encoding="utf-8")
    s = CodexAdapter().parse(_codex_ref(p, "u1"))
    assert s is not None and [m.role for m in s.messages] == ["user", "assistant"]
    assert s.model == "o4"


def test_codex_zst(tmp_path):
    import zstandard

    raw = "\n".join(json.dumps(e) for e in CODEX_EVENTS).encode("utf-8")
    p = tmp_path / "rollout-2026-08-28T10-00-00-u1.jsonl.zst"
    p.write_bytes(zstandard.ZstdCompressor().compress(raw))
    s = CodexAdapter().parse(_codex_ref(p, "u1"))
    assert s is not None and [m.role for m in s.messages] == ["user", "assistant"]
    assert s.messages[1].content == "已修复"


def test_codex_discover_includes_zst(tmp_path, monkeypatch):
    import zstandard

    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    sess = tmp_path / "codex" / "sessions" / "2026-08-28"
    sess.mkdir(parents=True)
    (sess / "rollout-a-1.jsonl").write_text(json.dumps(CODEX_EVENTS[0]), encoding="utf-8")
    (sess / "rollout-b-2.jsonl.zst").write_bytes(
        zstandard.ZstdCompressor().compress(json.dumps(CODEX_EVENTS[0]).encode()))
    refs = CodexAdapter().discover()
    names = {r.path.name for r in refs}
    assert names == {"rollout-a-1.jsonl", "rollout-b-2.jsonl.zst"}


# ---------- 低1：aider 限深遍历 / session_id / model ----------

def test_aider_discover_depth_limited(tmp_path, monkeypatch):
    """低1a：超过 MAX_DEPTH 的文件不发现（后需显式配置扫描根）。"""
    import pathlib

    from app.capture.adapters import aider

    home = tmp_path / "home"
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(aider, "_load_config",
                        lambda: {"aider_scan_roots": [str(home)]})
    # 深度 3（work/a/b/repo）→ 文件 parts=4 ≤ 6，发现
    deep_ok = home / "work" / "a" / "b" / "repo"
    deep_ok.mkdir(parents=True)
    (deep_ok / ".aider.chat.history.md").write_text(AIDER_MD, encoding="utf-8")
    # 深度 7（文件 parts=8 > 6）→ 不发现
    deep_bad = home / "d1" / "d2" / "d3" / "d4" / "d5" / "d6" / "d7"
    deep_bad.mkdir(parents=True)
    (deep_bad / ".aider.chat.history.md").write_text(AIDER_MD, encoding="utf-8")
    paths = {str(r.path) for r in AiderAdapter().discover()}
    assert str(deep_ok / ".aider.chat.history.md") in paths
    assert str(deep_bad / ".aider.chat.history.md") not in paths


def test_aider_discover_same_name_repo_distinct_ids(tmp_path, monkeypatch):
    """低1b：不同位置的同名仓库 session_id 不互相覆盖（后需显式配置扫描根）。"""
    import pathlib

    from app.capture.adapters import aider

    home = tmp_path / "home"
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(aider, "_load_config",
                        lambda: {"aider_scan_roots": [str(home)]})
    for prefix in ("work", "archive"):
        repo = home / prefix / "repo"
        repo.mkdir(parents=True)
        (repo / ".aider.chat.history.md").write_text(AIDER_MD, encoding="utf-8")
    refs = AiderAdapter().discover()
    assert len(refs) == 2
    ids = {r.session_id for r in refs}
    assert len(ids) == 2
    assert all(i.startswith("repo-") and len(i) == len("repo-") + 8 for i in ids)


def test_aider_parse_model_first_header(tmp_path):
    """低1c：多 header 会话 model 取首个 header，不被最后一个覆盖。"""
    p = tmp_path / ".aider.chat.history.md"
    p.write_text(
        "## [2026-08-28 10:00:00] gpt-4o\n"
        "**User:** hi\n**Assistant:** hello\n"
        "## [2026-08-28 11:00:00] claude-sonnet\n"
        "**User:** again\n**Assistant:** ok\n",
        encoding="utf-8")
    st = p.stat()
    s = AiderAdapter().parse(SessionRef(agent="aider", session_id="x",
                                        path=p, size=st.st_size, mtime=st.st_mtime))
    assert s.model == "gpt-4o"
    assert len(s.messages) == 4


def test_aider_scan_roots_reads_config(tmp_path, monkeypatch):
    """低1d 回归：_scan_roots 的 Store 导入路径必须正确——
    此前导入错误被 except+回落 home 掩盖，aider_scan_roots 配置永远不生效。"""
    from app.store.store import Store

    monkeypatch.setenv("EXPERIENTIA_HOME", str(tmp_path))
    custom = tmp_path / "custom-roots"
    repo = custom / "repo"
    repo.mkdir(parents=True)
    (repo / ".aider.chat.history.md").write_text(AIDER_MD, encoding="utf-8")
    s = Store(str(tmp_path))
    s.ensure_layout()
    s.save_config({"aider_scan_roots": [str(custom)]})
    refs = AiderAdapter().discover()
    assert any(r.path == repo / ".aider.chat.history.md" for r in refs)
