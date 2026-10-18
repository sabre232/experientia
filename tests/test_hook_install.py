"""Phase 8a：Hook 通道（通道 3，Claude Code 首发）。

覆盖：settings.json 一键配置（合并/幂等/备份/移除）+ 事件处理
（SessionStart 即时归档、UserPromptSubmit additionalContext 注入、
PostToolUse 生效验证、Stop 轮毕复盘写经验、代理通道富记录不降级）
+ 本地 API 端点（fail-open）。
"""

import json
from pathlib import Path

import pytest

from app.capture import hook
from app.store.store import Store
from conftest import local_api_client

ALL_EVENTS = ["SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"]

TRANSCRIPT = [
    {"type": "user", "timestamp": "2026-08-28T10:00:00Z", "cwd": "/work/proj",
     "sessionId": "abc123", "message": {"role": "user", "content": "写一份公文"}},
    {"type": "assistant", "timestamp": "2026-08-28T10:00:05Z",
     "message": {"role": "assistant", "model": "claude-sonnet-4-5",
                 "content": [{"type": "text", "text": "好的，开始起草"}]}},
]

# Stop 轮毕复盘用例：2 轮用户消息 + 中间一次纠正（命中默认否定词 "不对"）
CORRECTION_TRANSCRIPT = [
    {"type": "user", "timestamp": "2026-08-28T11:00:00Z", "cwd": "/work/proj",
     "sessionId": "corr1", "message": {"role": "user", "content": "写一份通知"}},
    {"type": "assistant", "timestamp": "2026-08-28T11:00:05Z",
     "message": {"role": "assistant", "model": "claude-sonnet-4-5",
                 "content": [{"type": "text", "text": "好的，我起草一份通知"}]}},
    {"type": "user", "timestamp": "2026-08-28T11:00:10Z",
     "message": {"role": "user", "content": "不对，通知正文要用公文格式"}},
    {"type": "assistant", "timestamp": "2026-08-28T11:00:15Z",
     "message": {"role": "assistant",
                 "content": [{"type": "text", "text": "好，已改为公文格式"}]}},
]


@pytest.fixture
def store(tmp_path):
    s = Store(data_dir=tmp_path / "data")
    s.ensure_layout()
    return s


def _write_transcript(tmp_path: Path) -> Path:
    p = tmp_path / "abc123.jsonl"
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in TRANSCRIPT),
                 encoding="utf-8")
    return p


# ---------- settings.json 一键配置 ----------

def test_hook_command_posix(monkeypatch):
    monkeypatch.setattr(hook.os, "name", "posix")
    cmd = hook.hook_command("user-prompt-submit")
    assert cmd.startswith("curl -s --max-time 15 -X POST "
                          "http://127.0.0.1:8101/api/hooks/user-prompt-submit")
    assert "--data-binary @-" in cmd
    assert "Content-Type: application/json" in cmd


def test_hook_command_windows(monkeypatch):
    monkeypatch.setattr(hook.os, "name", "nt")
    cmd = hook.hook_command("session-start")
    assert cmd.startswith('curl.exe -s --max-time 15 -X POST ')
    assert 'http://127.0.0.1:8101/api/hooks/session-start' in cmd
    assert '--data-binary @-' in cmd


def test_hook_config_shape():
    cfg = hook.hook_config()
    assert list(cfg["hooks"]) == ALL_EVENTS  # 阶段 B：扩到 4 事件，顺序稳定
    for event, matchers in cfg["hooks"].items():
        assert len(matchers) == 1
        assert matchers[0]["hooks"][0]["type"] == "command"
        assert "/api/hooks/" in matchers[0]["hooks"][0]["command"]


def _count_ours(path: Path, event: str) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for m in data.get("hooks", {}).get(event, []):
        if isinstance(m, dict) and hook._matcher_is_ours(m, 8101):
            n += 1
    return n


def test_apply_creates_and_is_idempotent(tmp_path):
    p = tmp_path / ".claude" / "settings.json"
    r1 = hook.apply_hook_config(p)
    assert r1["events"] == ALL_EVENTS
    assert p.exists()
    assert _count_ours(p, "SessionStart") == 1
    # 幂等：再跑一次不重复
    hook.apply_hook_config(p)
    for event in ALL_EVENTS:
        assert _count_ours(p, event) == 1
    st = hook.hook_status(p)
    assert st["configured"] is True
    assert st["events"] == ALL_EVENTS


def test_apply_preserves_user_config_and_backs_up(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "theme": "dark",
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "notify-send done"}]}],
        },
    }, ensure_ascii=False), encoding="utf-8")
    hook.apply_hook_config(p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"  # 用户配置保留
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "notify-send done"
    assert _count_ours(p, "SessionStart") == 1
    assert _count_ours(p, "Stop") == 1  # 用户 Stop 条目之外，我们的 Stop 追加
    assert (tmp_path / "settings.json.experientia.bak").exists()  # 写前备份


def test_apply_malformed_existing_treated_as_empty(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{not json", encoding="utf-8")
    hook.apply_hook_config(p)
    json.loads(p.read_text(encoding="utf-8"))  # 结果必须是合法 JSON
    assert _count_ours(p, "SessionStart") == 1


def test_remove_only_ours(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "user-cmd"}]}],
    }}), encoding="utf-8")
    hook.apply_hook_config(p)
    r = hook.remove_hook_config(p)
    assert r["removed"] is True
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "user-cmd"  # 用户条目不动
    for event in ALL_EVENTS:
        assert _count_ours(p, event) == 0
    # 再移除 = 无操作
    assert hook.remove_hook_config(p)["removed"] is False


# ---------- 事件处理 ----------

def test_session_start_without_sid_noop(store):
    assert hook.handle_session_start(store, {}) == {}
    assert hook.handle_session_start(store, {"prompt": "x"}) == {}


def test_session_start_minimal_record(store):
    hook.handle_session_start(store, {"session_id": "s1", "cwd": "/w"})
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["channel"] == "hook"
    assert sessions[0]["project"] == "/w"


def test_session_start_archives_transcript(store, tmp_path):
    tp = _write_transcript(tmp_path)
    hook.handle_session_start(store, {
        "session_id": "abc123", "transcript_path": str(tp), "cwd": "/work/proj",
    })
    sessions = [s for s in store.list_sessions() if s["session_id"] == "abc123"]
    assert len(sessions) == 1
    s = sessions[0]
    assert s["model"] == "claude-sonnet-4-5"
    # P1a-1：原始 messages 恒不落盘，落库为派生的截断转录
    assert "messages" not in s
    assert s["user_messages"] == ["写一份公文"]
    assert s["assistant_messages"] == ["好的，开始起草"]
    assert s["project"] == "/work/proj"
    # 捕获即归档（抢在 30 天清理前）
    archived = store.data_dir / "sessions" / "claude-code" / "abc123.jsonl"
    assert archived.exists()


def test_session_start_empty_transcript_falls_back_to_minimal(store, tmp_path):
    tp = tmp_path / "empty.jsonl"
    tp.write_text('{"type": "summary", "summary": "no messages"}\n', encoding="utf-8")
    hook.handle_session_start(store, {"session_id": "s2", "transcript_path": str(tp)})
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].get("channel") == "hook"


def test_prompt_submit_empty_store_noop(store):
    assert hook.handle_user_prompt_submit(store, {"session_id": "s3"}) == {}


def test_prompt_submit_injects_rules_and_records_session(store):
    store.save_rules([{"id": "r1", "name": "红线", "text": "NEVER 使用纯情绪文案",
                       "trigger": "hard-hook", "enabled": True}])
    r = hook.handle_user_prompt_submit(store, {"session_id": "s4", "prompt": "写文案"})
    out = r.get("hookSpecificOutput")
    assert out is not None
    assert out["hookEventName"] == "UserPromptSubmit"
    assert "NEVER 使用纯情绪文案" in out["additionalContext"]
    assert "硬钩子" in out["additionalContext"]
    assert any(s["session_id"] == "s4" for s in store.list_sessions())


def test_prompt_submit_injects_preferences(store):
    # 先有一条已归类经验 → detect_task_context 能把 prompt 路由到公文/起草
    store.append_experience({"agent": "claude-code", "task": "公文起草", "trunk": "公文",
                             "category": "起草", "action": "起草通知", "G": 0.7})
    store.write_preferences("公文", "- 落款日期用汉字\n")
    store.write_skill("公文", "起草", "## 标准流程\n1. 拟提纲\n")
    r = hook.handle_user_prompt_submit(store, {"session_id": "s5", "prompt": "公文起草一份通知"})
    ctx = r["hookSpecificOutput"]["additionalContext"]
    assert "落款日期用汉字" in ctx
    assert "拟提纲" in ctx


def test_prompt_submit_keeps_proxy_rich_record(store):
    """冲突合并：代理通道记录（带 req_count）不被 hook 的瘦记录降级。"""
    store.record_session({"agent": "claude-code", "session_id": "s6",
                          "req_count": 12, "correction_hits": 2})
    hook.handle_user_prompt_submit(store, {"session_id": "s6", "prompt": "继续"})
    sessions = [s for s in store.list_sessions() if s["session_id"] == "s6"]
    assert len(sessions) == 1
    assert sessions[0].get("req_count") == 12


def test_build_hook_context_empty(store):
    assert hook.build_hook_context(store, "任意 prompt") == ""


# ---------- 本地 API 端点 ----------

@pytest.fixture
def client(store, tmp_path, monkeypatch):
    # apply/remove 端点默认写 ~/.claude/settings.json——测试改写到 tmp，避免动真实配置
    fake = tmp_path / "claude-settings" / "settings.json"
    monkeypatch.setattr(hook, "default_settings_path", lambda: fake)
    return local_api_client(store)


def test_api_session_start(client):
    r = client.post("/api/hooks/session-start", json={})
    assert r.status_code == 200
    assert r.json() == {}
    r = client.post("/api/hooks/session-start",
                    json={"session_id": "api-s1", "cwd": "/x"})
    assert r.status_code == 200


def test_api_user_prompt_submit_with_rules(client, store):
    store.save_rules([{"id": "r1", "name": "红线", "text": "NEVER 虚构数据来源",
                       "trigger": "hard-hook", "enabled": True}])
    r = client.post("/api/hooks/user-prompt-submit",
                    json={"session_id": "api-s2", "prompt": "帮我查数据"})
    assert r.status_code == 200
    out = r.json()["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    assert "NEVER 虚构数据来源" in out["additionalContext"]


def test_api_user_prompt_submit_empty_body(client):
    # curl 空 stdin 时 body 为空——不能 422（fail-open 口径）
    r = client.post("/api/hooks/user-prompt-submit", content=b"",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 200


def test_api_post_tool_use_fail_open(client):
    r = client.post("/api/hooks/post-tool-use", json={})
    assert r.status_code == 200
    assert r.json() == {}
    st = client.get("/api/hooks/config").json()
    assert "PostToolUse" in (st.get("observed") or {})


def test_api_stop_empty_fail_open(client):
    # 空 body / 无 transcript：只标记生效，不触发复盘（fail-open 口径）
    r = client.post("/api/hooks/stop", content=b"",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert r.json() == {}
    r = client.post("/api/hooks/stop", json={"session_id": "no-tp"})
    assert r.status_code == 200
    st = client.get("/api/hooks/config").json()
    assert "Stop" in (st.get("observed") or {})


def test_api_stop_with_transcript_returns_immediately(client, store, tmp_path):
    tp = tmp_path / "corr1.jsonl"
    tp.write_text("\n".join(
        json.dumps(x, ensure_ascii=False) for x in CORRECTION_TRANSCRIPT),
        encoding="utf-8")
    r = client.post("/api/hooks/stop",
                    json={"session_id": "corr1", "transcript_path": str(tp)})
    assert r.status_code == 200
    assert r.json() == {}  # 立即返回（复盘在后台 worker，不等 LLM）


def test_api_hooks_config_apply_remove_roundtrip(client, tmp_path):
    st = client.get("/api/hooks/config").json()
    assert st["configured"] is False
    fake = tmp_path / "claude-settings" / "settings.json"

    r = client.post("/api/hooks/apply").json()
    assert fake.exists()
    assert r["events"] == ALL_EVENTS
    assert client.get("/api/hooks/config").json()["configured"] is True

    # 幂等
    client.post("/api/hooks/apply")
    data = json.loads(fake.read_text(encoding="utf-8"))
    ours = sum(1 for m in data["hooks"]["SessionStart"]
               if hook._matcher_is_ours(m, 8101))
    assert ours == 1

    rm = client.post("/api/hooks/remove").json()
    assert rm["removed"] is True
    assert client.get("/api/hooks/config").json()["configured"] is False


# ---------- installed→observed 生效验证（memorax 借鉴 A2） ----------

def test_store_hook_observed_roundtrip(store):
    store.record_hook_observed("claude-code", "session-start")
    obs = store.load_hook_observed()
    assert "claude-code:session-start" in obs


def test_handlers_mark_observed(store):
    hook.handle_session_start(store, {"session_id": "s-obs"})
    hook.handle_user_prompt_submit(store, {"session_id": "s-obs2", "prompt": "hi"})
    hook.handle_post_tool_use(store, {})
    hook.handle_stop(store, {})  # 无 transcript：只标记生效，不触发复盘
    obs = store.load_hook_observed()
    assert "claude-code:session-start" in obs
    assert "claude-code:user-prompt-submit" in obs
    assert "claude-code:post-tool-use" in obs
    assert "claude-code:stop" in obs


# ---------- 阶段 B：Stop 轮毕复盘写经验 ----------

def _correction_session(tmp_path, sid: str = "corr1") -> object:
    from app.capture import registry
    from app.capture.models import SessionRef

    p = tmp_path / f"{sid}.jsonl"
    p.write_text("\n".join(
        json.dumps(x, ensure_ascii=False) for x in CORRECTION_TRANSCRIPT),
        encoding="utf-8")
    ref = SessionRef(agent="claude-code", session_id=sid, path=p,
                     size=p.stat().st_size, mtime=p.stat().st_mtime)
    return registry.REGISTRY["claude-code"]().parse_sessions(ref)[0]


def test_run_stop_review_writes_l2_correction(store, tmp_path):
    """轮毕复盘走档 A 管线：无模型→ 不写逐字经验，纠正片段挂证据队列。"""
    session = _correction_session(tmp_path, sid="run-corrid")
    assert hook._count_user_messages(session) >= 2
    added = hook._run_stop_review(store, session)
    assert added == 0
    assert list(store.iter_experiences()) == []
    pend = store.load_pending_review_records()
    assert len(pend) == 1 and pend[0]["session_id"] == "run-corrid"
    assert any("不对，通知正文要用公文格式" in s for s in pend[0]["snippets"])


def test_spawn_stop_review_dedupes_same_content(store, tmp_path):
    """同内容重复 Stop 不重复入队（防每轮刷 LLM）。"""
    session = _correction_session(tmp_path, sid="dedupe-sid")
    assert hook._spawn_stop_review(store, session) is True
    assert hook._spawn_stop_review(store, session) is False


def test_stop_review_flag_off_disables(store, tmp_path):
    """可回滚开关：capture.hook_stop_review=False → Stop 不再触发复盘。"""
    assert hook._stop_review_enabled(store) is True  # 缺省开
    store.save_config({"capture": {"hook_stop_review": False}})
    assert hook._stop_review_enabled(store) is False
    sid = "flag-sid"
    tp = tmp_path / f"{sid}.jsonl"
    tp.write_text("\n".join(
        json.dumps(x, ensure_ascii=False) for x in CORRECTION_TRANSCRIPT),
        encoding="utf-8")
    hook.handle_stop(store, {"session_id": sid, "transcript_path": str(tp)})
    assert "claude-code:stop" in store.load_hook_observed()  # 生效验证仍在
    assert sid not in hook._reviewed_upto  # 但未触发复盘


def test_handle_stop_with_transcript_triggers_review(store, tmp_path):
    sid = "stop-sid"
    tp = tmp_path / f"{sid}.jsonl"
    tp.write_text("\n".join(
        json.dumps(x, ensure_ascii=False) for x in CORRECTION_TRANSCRIPT),
        encoding="utf-8")
    hook.handle_stop(store, {"session_id": sid, "transcript_path": str(tp)})
    # handler 立即返回（后台 worker 异步）；去重表已记录 = 已入队触发
    assert "claude-code:stop" in store.load_hook_observed()
    assert hook._reviewed_upto.get(sid) == 2


def test_hook_status_reports_observed(store, tmp_path):
    p = tmp_path / "settings.json"
    hook.apply_hook_config(p)
    hook.handle_user_prompt_submit(store, {"session_id": "sx", "prompt": "hi"})
    st = hook.hook_status(p, store=store)
    assert st["configured"] is True
    assert "UserPromptSubmit" in (st.get("observed") or {})
    assert st.get("last_observed_ago_s") is not None


def test_hook_status_without_store_has_empty_observed(tmp_path):
    p = tmp_path / "settings.json"
    hook.apply_hook_config(p)
    st = hook.hook_status(p)
    assert st.get("observed") == {}
    assert st.get("last_observed_ago_s") is None


def test_api_hooks_config_returns_observed_after_event(client, store):
    st = client.get("/api/hooks/config").json()
    assert st.get("observed") == {}
    client.post("/api/hooks/user-prompt-submit", json={"session_id": "k1", "prompt": "hi"})
    st2 = client.get("/api/hooks/config").json()
    assert "UserPromptSubmit" in (st2.get("observed") or {})
    assert st2.get("last_observed_ago_s") is not None
