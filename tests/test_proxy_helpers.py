"""代理转发纯函数单测（重构报告 TEST-3）。

覆盖：重试判定 / SSE delta 文本抽取 / token 匹配 / _relay_post_nonstream 重试链
（httpx 层不真连网，全用可控假 client + monkeypatch sleep）。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.proxy import server
from app.store.store import Store


class _FakeResp:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeClient:
    """按预设序列回放 post 结果：异常实例 = 抛错，否则返回该响应。"""

    def __init__(self, *steps):
        self._steps = list(steps)
        self.post_calls = 0

    async def post(self, url, json=None, headers=None, **kw):
        self.post_calls += 1
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def no_sleep(monkeypatch):
    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(server.asyncio, "sleep", _noop)


# ---------- 重试判定 ----------

def test_proxy_retryable_statuses():
    for code in (429, 500, 502, 503, 504):
        assert server._proxy_retryable(code) is True
    for code in (200, 400, 401, 404, 408, 499):
        assert server._proxy_retryable(code) is False


# ---------- SSE delta 文本 ----------

def test_sse_delta_text():
    assert server._sse_delta_text({}) == ""
    assert server._sse_delta_text(
        {"choices": [{"delta": {"content": "hi"}}]}) == "hi"
    assert server._sse_delta_text(
        {"choices": [{"delta": {"content": ""}}]}) == ""
    assert server._sse_delta_text({"choices": []}) == ""
    # usage 块没有 choices → 不应误读
    assert server._sse_delta_text({"usage": {"prompt_tokens": 1}}) == ""


# ---------- token 匹配 ----------

def test_proxy_token_matches():
    assert server._proxy_token_matches("Bearer abc", "abc") is True
    assert server._proxy_token_matches("bearer abc", "abc") is True  # 大小写不敏感前缀
    assert server._proxy_token_matches("abc", "abc") is True
    assert server._proxy_token_matches("Bearer abcd", "abc") is False
    assert server._proxy_token_matches("", "abc") is False
    assert server._proxy_token_matches("anything", None) is True  # 未启用 = 全放行
    # 恒时比较防时序侧信道
    assert server._proxy_token_matches("Bearer " + "a" * 20, "a" * 20) is True
    # 非 ASCII 令牌不得抛 TypeError（会变成 500 而非 401）
    assert server._proxy_token_matches("Bearer 中文", "abc") is False


def test_resolve_upstream_url_no_double_path(tmp_path):
    """endpoint 已含完整路径（.../chat/completions）时不得拼出双路径
    （原实现 rstrip + 拼接 → //chat/completions → 上游 404）。"""
    s = Store(data_dir=tmp_path / "data")
    s.ensure_layout()
    s.save_config({"models": {"gpt": {"type": "cloud",
                                      "endpoint":
                                      "http://up/v1/chat/completions"}},
                   "default_model": "gpt"})
    url, _headers, _body = server._resolve_upstream(
        s, "gpt", {}, "/chat/completions")
    assert url == "http://up/v1/chat/completions"
    # 常规 endpoint（带尾斜杠）仍按原语义拼接
    s.save_config({"models": {"gpt": {"type": "cloud", "endpoint": "http://up/v1/"}},
                   "default_model": "gpt"})
    url2, _h, _b = server._resolve_upstream(s, "gpt", {}, "/chat/completions")
    assert url2 == "http://up/v1/chat/completions"


# ---------- _relay_post_nonstream 重试链 ----------

def test_relay_no_retry_on_200(no_sleep):
    client = _FakeClient(_FakeResp(200))
    resp = asyncio.run(server._relay_post_nonstream(client, "u", {}, {}, "t"))
    assert resp.status_code == 200
    assert client.post_calls == 1


def test_relay_retries_transport_error_then_success(no_sleep):
    client = _FakeClient(httpx.TransportError("boom"), _FakeResp(200))
    resp = asyncio.run(server._relay_post_nonstream(client, "u", {}, {}, "t"))
    assert resp.status_code == 200
    assert client.post_calls == 2


def test_relay_retries_503_then_success(no_sleep):
    client = _FakeClient(_FakeResp(503), _FakeResp(200))
    resp = asyncio.run(server._relay_post_nonstream(client, "u", {}, {}, "t"))
    assert resp.status_code == 200
    assert client.post_calls == 2


def test_relay_raises_after_two_transport_failures(no_sleep):
    client = _FakeClient(httpx.TransportError("a"), httpx.TransportError("b"))
    with pytest.raises(httpx.HTTPError):
        asyncio.run(server._relay_post_nonstream(client, "u", {}, {}, "t"))
    assert client.post_calls == 2


def test_relay_no_retry_on_client_error(no_sleep):
    # 4xx 非 429：重试语义不适用（业务错误）
    client = _FakeClient(_FakeResp(400))
    resp = asyncio.run(server._relay_post_nonstream(client, "u", {}, {}, "t"))
    assert resp.status_code == 400
    assert client.post_calls == 1


# ----------  H5/H6：Anthropic SSE 抽取 + 增量记录 ----------

def test_anthropic_sse_delta_text_only_from_content_block_delta():
    assert server._anthropic_sse_delta_text(
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "你好"}}) == "你好"
    assert server._anthropic_sse_delta_text({"type": "message_start"}) == ""
    assert server._anthropic_sse_delta_text({"type": "content_block_delta"}) == ""
    assert server._anthropic_sse_delta_text({}) == ""


def test_anthropic_sse_usage_from_message_start_and_delta():
    usage = [0, 0]
    server._anthropic_sse_usage(
        {"type": "message_start", "message": {"usage": {"input_tokens": 12, "output_tokens": 1}}}, usage)
    assert usage == [12, 1]
    server._anthropic_sse_usage(
        {"type": "message_delta", "usage": {"output_tokens": 34}}, usage)
    assert usage == [12, 34]


def test_new_user_texts_increments_and_skips_resend():
    from app.proxy.server import TrackedSession
    s = TrackedSession(session_id="h6", agent="a", model="m")
    assert server._new_user_texts(["q1"], s) == ["q1"]
    # 客户端重发全量历史（1 旧 + 1 新）→ 只取新增
    assert server._new_user_texts(["q1", "q2"], s) == ["q2"]
    # 再重发同样历史 → 无新增
    assert server._new_user_texts(["q1", "q2"], s) == []
    # 历史压缩（条数变少）→ 保守不回退不重计；恢复到旧条数前视为无新增
    #（宁少计不多计：压缩后整段重发若重计会让修正轮数虚高）
    assert server._new_user_texts(["q2"], s) == []
    assert server._new_user_texts(["q2", "q3"], s) == []


def test_peek_and_commit_user_texts():
    """：转发路径先 peek 不推进、成功记账点才 commit。

    上游失败不记账，客户端重试同一全量历史必须仍能拿到"新增"；一旦 commit，
    重试不再重复计。commit 单调取大，历史压缩不回退计数。"""
    from app.proxy.server import TrackedSession
    s = TrackedSession(session_id="m5", agent="a", model="m")
    texts = ["q1"]
    # 第一次 peek（随后上游失败）——计数不推进
    assert server._peek_user_texts(texts, s) == ["q1"]
    assert s.last_user_count == 0
    # 重试同一全量历史——仍然拿到同样新增（旧实现在此已被提前推进 → []）
    assert server._peek_user_texts(texts, s) == ["q1"]
    assert s.last_user_count == 0
    # 成功记账点 commit
    server._commit_user_count(texts, s)
    assert s.last_user_count == 1
    assert server._peek_user_texts(texts, s) == []
    # 历史压缩不回退（commit 单调取大）
    server._commit_user_count(["q1"], s)
    assert s.last_user_count == 1
    server._commit_user_count(["q1", "q2"], s)
    assert s.last_user_count == 2


def test_record_exchange_delta_counts_negation_per_new_message():
    from app.proxy.server import SESSION_MSG_KEEP, SessionTracker, TrackedSession
    tr = SessionTracker.__new__(SessionTracker)  # 只测计数逻辑，不初始化 store
    s = TrackedSession(session_id="h6b", agent="a", model="m")
    tr.record_exchange_delta(s, ["不对，重写", "很好"], "ok", ["不对"])
    assert s.correction_hits == 1
    assert s.user_messages[-1] == "很好"  # 最后一条 = 真实最后 user 消息（收尾判定可用）
    assert len(s.assistant_messages) == 1
    # 封顶口径与 record_exchange 一致：只留最近 SESSION_MSG_KEEP 条
    tr.record_exchange_delta(s, [f"m{i}" for i in range(SESSION_MSG_KEEP + 5)],
                             "", ["不对"])
    assert len(s.user_messages) == SESSION_MSG_KEEP
