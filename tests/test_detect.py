"""上下文自动感知测试。"""

from app.proxy import detect


def test_detect_agent_user_agent():
    assert detect.detect_agent({"user-agent": "workbuddy/1.0"}) == "workbuddy"
    assert detect.detect_agent({"user-agent": "Mozilla/5.0 Cursor/1.2"}) == "cursor"
    assert detect.detect_agent({"user-agent": "claude-code/2.0"}) == "claude-code"


def test_detect_agent_custom_header():
    assert detect.detect_agent({"user-agent": "x", "x-agent-name": "my-agent"}) == "my-agent"


def test_detect_agent_unknown():
    assert detect.detect_agent({}) == "unknown"


def test_detect_api_and_model():
    assert detect.detect_api_and_model("gpt-4o")["provider"] == "openai"
    assert detect.detect_api_and_model("claude-sonnet-4")["provider"] == "anthropic"
    assert detect.detect_api_and_model("gemini-2.5-pro")["provider"] == "google"
    assert detect.detect_api_and_model("deepseek-chat")["provider"] == "deepseek"
    assert detect.detect_api_and_model("Qwen3-8B")["provider"] == "local"


def test_detect_task_seed_keywords():
    seeds = {"营销": ["文案", "投放", "标题"]}
    r = detect.detect_task_context(
        [{"role": "user", "content": "帮我写个投放标题"}], seeds, {}
    )
    assert r["trunk"] == "营销"


def test_detect_task_history_match_wins():
    known = {("营销", "文案写作"): ["写个投放标题", "改文案"]}
    r = detect.detect_task_context(
        [{"role": "user", "content": "再帮我写个投放标题吧"}], {"其他": []}, known
    )
    assert r == {"trunk": "营销", "category": "文案写作"}


def test_detect_task_default():
    r = detect.detect_task_context([{"role": "user", "content": "你好"}], {"其他": []}, {})
    assert r == {"trunk": "其他", "category": "未分类"}


def test_get_session_id_priority():
    assert detect.get_session_id({"x-session-id": "abc"}, {}) == "abc"
    assert detect.get_session_id({}, {"metadata": {"thread_id": "t9"}}) == "thread-t9"
    auto = detect.get_session_id({}, {})
    assert auto.startswith("auto-unknown-default-")


def test_get_session_id_metadata_non_dict():
    """metadata 非 dict → 按无 thread_id 处理，不得 500（
    原写法 (body.get("metadata") or {}).get(...) 遇 "metadata": "x" 抛
    AttributeError → FastAPI 裸 500）。"""
    for bad in ("x", None, [1], 42):
        sid = detect.get_session_id({}, {"metadata": bad})
        assert sid.startswith("auto-")


def test_get_session_id_auto_window_stable():
    """H4：无会话头时连续请求聚合成同一 session（不再每请求一个新 id）。"""
    h = {"user-agent": "workbuddy/1.0"}
    a = detect.get_session_id(h, {"project": "p1"})
    b = detect.get_session_id(h, {"project": "p1"})
    assert a == b, "同 agent/user/project 的连续请求必须同一 session"
    assert a.startswith("auto-workbuddy-default-p1-")
    # 不同 agent / project → 不同 session
    assert detect.get_session_id({"user-agent": "cursor/1.0"}, {"project": "p1"}) != a
    assert detect.get_session_id(h, {"project": "p2"}) != a


def test_auto_session_gap_based(monkeypatch):
    """M-6：session 边界 = 间隔 >30 分钟（与 tracker 空闲超时同判据），
    不是固定时间窗——9:59:59 与 10:00:01 的连续对话不得被切成两段。"""
    clock = {"t": 1_800_000_000.0}
    monkeypatch.setattr(detect.time, "time", lambda: clock["t"])
    h = {"user-agent": "workbuddy/1.0"}
    detect._auto_segments.clear()
    try:
        a = detect.get_session_id(h, {"project": "pg"})
        # 间隔 29 分钟 → 同一 session
        clock["t"] += 29 * 60
        b = detect.get_session_id(h, {"project": "pg"})
        assert a == b
        # 距上次请求（b）再隔 31 分钟 → 新段，段号（epoch 秒）单调递增
        clock["t"] += 31 * 60
        c = detect.get_session_id(h, {"project": "pg"})
        assert c != a
        assert int(c.rsplit("-", 1)[1]) > int(a.rsplit("-", 1)[1])
        # 进程重启（状态清空）→ 段号继续递增，不撞历史 id
        detect._auto_segments.clear()
        clock["t"] += 60
        d = detect.get_session_id(h, {"project": "pg"})
        assert int(d.rsplit("-", 1)[1]) > int(c.rsplit("-", 1)[1])
    finally:
        detect._auto_segments.clear()


def test_agent_names_public():
    """低11：可识别 agent 名走公开 getter（治理视图不再私有引用 _UA_AGENT_PATTERNS）。"""
    names = detect.agent_names()
    assert {"workbuddy", "codebuddy", "cursor", "trae", "claude-code",
            "cline", "codex", "gemini-cli"} <= names
