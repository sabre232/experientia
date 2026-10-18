"""W1 价值可见：token 链路 + 采集命中流水 + 接入自检。

验收（路线图  W1-01..09）：
- 上游回 usage → 累进 session tokens_in/out；不回 → 记 0 不报错（fail-open）
- growth affinity 加 tokens_pct（与 rounds_pct 同口径：首次 vs 最近）
- capture_hits.jsonl 流水（每轮每 agent ≤1 行）+ 1000 行滚动截断
- GET /api/capture/status：agents 24h 计数 / last_hit / 黄标 + recent_hits
- check_route 接入自检：200/401/404/不可达/未配模型五种出口
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI, Request

from app.models_service import check_route
from conftest import local_api_client
from app.proxy.server import SessionTracker, TrackedSession, create_app
from tests.conftest import PROXY_AUTH_HEADERS, start_upstream
from app.store.store import Store


def _make_upstream(with_usage: bool = True) -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def cc(request: Request):
        body = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        if with_usage:
            body["usage"] = {"prompt_tokens": 100, "completion_tokens": 50}
        return body

    @app.post("/v1/messages")
    async def messages(request: Request):
        body = {"content": [{"type": "text", "text": "ok"}]}
        if with_usage:
            body["usage"] = {"input_tokens": 80, "output_tokens": 20}
        return body

    return app


@pytest.fixture(scope="module")
def upstream():
    port, stop = start_upstream(_make_upstream(with_usage=True))
    try:
        yield port
    finally:
        stop()


def _make_store(tmp_path, port, mtype="local") -> Store:
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_config({
        "default_model": "m",
        "models": {"m": {"type": mtype, "endpoint": f"http://127.0.0.1:{port}/v1",
                         "model": "test-model"}},
    })
    return store


def _post_once(client, path, headers, body):
    return client.post(path, headers=headers, json=body)


# ---------- W1-01/02：proxy usage → session tokens ----------

def test_proxy_openai_usage_accumulates(tmp_path, upstream):
    store = _make_store(tmp_path, upstream)
    app = create_app(store)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     headers=PROXY_AUTH_HEADERS) as client:
            h = {"x-session-id": "w1-s1"}
            b = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
            r1 = await _post_once(client, "/v1/chat/completions", h, b)
            r2 = await _post_once(client, "/v1/chat/completions", h, b)
            return r1, r2

    r1, r2 = asyncio.run(run())
    assert r1.status_code == 200 and r2.status_code == 200
    s = app.state.tracker._sessions["w1-s1"]
    assert (s.tokens_in, s.tokens_out) == (200, 100)  # 两次请求累进


def test_proxy_openai_no_usage_fail_open(tmp_path):
    """上游不回 usage → 记 0、不报错（W1-01 验收：token 缺失场景不报错）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    # 上游直接挂：用不存在的路由端口，验证代理不抛错
    store.save_config({
        "default_model": "m",
        "models": {"m": {"type": "local", "endpoint": "http://127.0.0.1:1/v1",
                         "model": "x"}},
    })
    app = create_app(store)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     headers=PROXY_AUTH_HEADERS) as client:
            return await _post_once(
                client, "/v1/chat/completions", {"x-session-id": "w1-s2"},
                {"model": "m", "messages": [{"role": "user", "content": "hi"}]})

    r = asyncio.run(run())
    # fail-open：上游不可达 → 502 透传（不是 500 崩溃）
    assert r.status_code == 502
    s = app.state.tracker._sessions.get("w1-s2")
    assert s is not None and (s.tokens_in, s.tokens_out) == (0, 0)


def test_proxy_anthropic_usage(tmp_path, upstream):
    store = _make_store(tmp_path, upstream, mtype="anthropic")
    app = create_app(store)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     headers=PROXY_AUTH_HEADERS) as client:
            return await _post_once(
                client, "/v1/messages", {"x-session-id": "w1-s3"},
                {"model": "m", "messages": [{"role": "user", "content": "hi"}]})

    r = asyncio.run(run())
    assert r.status_code == 200
    s = app.state.tracker._sessions["w1-s3"]
    assert (s.tokens_in, s.tokens_out) == (80, 20)


def test_finalize_writes_token_fields(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    tracker = SessionTracker(store)
    s = TrackedSession(session_id="w1-s4", agent="codex", model="m")
    s.req_count = 3
    s.tokens_in, s.tokens_out = 1234, 567
    tracker._finalize(s)
    recs = [r for r in store.list_sessions() if r.get("session_id") == "w1-s4"]
    assert len(recs) == 1
    assert recs[0]["tokens_in"] == 1234 and recs[0]["tokens_out"] == 567


# ---------- W1-03：affinity tokens_pct ----------

def _session(sid, day, req, tin, tout):
    return {"agent": "codex", "session_id": sid, "trunk": "营销",
            "category": "文案写作", "req_count": req, "correction_hits": 1,
            "tokens_in": tin, "tokens_out": tout,
            "started_at": f"2026-08-{day:02d}T10:00:00Z"}


def test_affinity_tokens_pct(tmp_path):
    """v2 口径（M1 不重叠窗口）：基线 = 前 3 次中位数，近期 = 第 4~8 个实例中位数。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session(_session("a", 1, 12, 1000, 500))   # 1500
    store.record_session(_session("b", 2, 9, 800, 300))     # 1100
    store.record_session(_session("c", 3, 8, 700, 200))     # 900
    store.record_session(_session("d", 4, 7, 600, 100))     # 700
    store.record_session(_session("e", 5, 6, 500, 200))     # 700
    aff = store.growth_summary(days=30)["affinity"]["codex/营销/文案写作"]
    assert aff["n"] == 5
    # 基线中位 1100；近期（第 4~5 个实例）中位 700 → -36%
    assert aff["tokens_pct"] == round((700 - 1100) / 1100 * 100)
    assert aff["baseline"]["tokens"] == 1100 and aff["recent"]["tokens"] == 700
    assert aff["first"]["tokens"] == 1500


def test_affinity_recent_window_not_single_latest(tmp_path):
    """v2 口径（+ M1 不重叠窗口）：对比点 = 基线（前 3 次中位数）vs
    近期窗口（基线后 ≤5 个实例中位数），单次回潮不直接拉爆结论（中位数抗噪）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session(_session("a", 1, 12, 1000, 500))   # 12 轮
    store.record_session(_session("b", 2, 10, 800, 300))    # 10 轮
    store.record_session(_session("c", 3, 8, 600, 100))     # 8 轮
    store.record_session(_session("d", 4, 7, 500, 200))     # 7 轮
    store.record_session(_session("e", 5, 9, 1200, 400))    # 回潮 9 轮
    aff = store.growth_summary(days=30)["affinity"]["codex/营销/文案写作"]
    assert aff["n"] == 5
    # 基线中位 10（[12,10,8]）；近期窗口（7,9）中位 8
    # ——单次回潮只把中位拉到 8，不直接拉爆结论
    assert aff["rounds_pct"] == round((8 - 10) / 10 * 100)  # -20
    assert aff["last"]["req_count"] == 8  # "last" 槽位 = 近期窗口中位代表（v2）
    # 同一 session 重复记录只算 1 个独立实例
    store.record_session(_session("e", 5, 11, 1200, 400))
    aff = store.growth_summary(days=30)["affinity"]["codex/营销/文案写作"]
    assert aff["n"] == 5


def test_affinity_level_high_on_diff(tmp_path):
    """v2 档位：主指标 = 磨合差值，基线中位 5 − 近期中位 3 = 2 ≥2 → 高。"""
    store = Store(tmp_path)
    store.ensure_layout()
    for sid, day, fix in (("a", 1, 6), ("b", 2, 5), ("c", 3, 4),
                          ("d", 4, 3), ("e", 5, 3)):
        s = _session(sid, day, 10, 0, 0); s["correction_hits"] = fix
        store.record_session(s)
    aff = store.growth_summary(days=30)["affinity"]["codex/营销/文案写作"]
    assert aff["diff"] == 2
    assert aff["level"] == "高"


def test_affinity_level_medium_on_diff_one(tmp_path):
    """v2 档位：磨合差值 = 1（基线中位 3 − 近期中位 2）→ 中。"""
    store = Store(tmp_path)
    store.ensure_layout()
    for sid, day, fix in (("a", 1, 4), ("b", 2, 3), ("c", 3, 2),
                          ("d", 4, 2), ("e", 5, 3)):
        s = _session(sid, day, 10, 0, 0); s["correction_hits"] = fix
        store.record_session(s)
    aff = store.growth_summary(days=30)["affinity"]["codex/营销/文案写作"]
    assert aff["diff"] == 1
    assert aff["level"] == "中"


def test_affinity_level_low_and_excluded(tmp_path):
    """v2：差值 0 → 低；基线修正中位数 0 → excluded（负例自查，不算改善样本）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    for sid, day, fix in (("a", 1, 1), ("b", 2, 1), ("c", 3, 1),
                          ("d", 4, 1), ("e", 5, 1)):
        s = _session(sid, day, 10, 0, 0); s["correction_hits"] = fix
        store.record_session(s)
    aff = store.growth_summary(days=30)["affinity"]["codex/营销/文案写作"]
    assert aff["diff"] == 0 and aff["level"] == "低"

    store2 = Store(tmp_path / "zero")
    store2.ensure_layout()
    for sid, day in (("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5)):
        s = _session(sid, day, 10, 0, 0); s["correction_hits"] = 0
        store2.record_session(s)
    aff0 = store2.growth_summary(days=30)["affinity"]["codex/营销/文案写作"]
    assert aff0["excluded"] is True and aff0["level"] == "低"
    assert aff0["corrections_pct"] is None  # 基线 0 → 百分比无定义


def test_affinity_tokens_pct_none_when_missing(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    for sid, day, req in (("a", 1, 12), ("b", 2, 9), ("c", 3, 6),
                          ("d", 4, 8), ("e", 5, 6)):
        store.record_session({"agent": "x", "session_id": sid, "trunk": "t",
                              "category": "c", "req_count": req, "correction_hits": 0,
                              "started_at": f"2026-08-{day:02d}T10:00:00Z"})
    aff = store.growth_summary(days=30)["affinity"]["x/t/c"]
    assert aff["tokens_pct"] is None  # 老记录无 token → None（UI 不显示）


# ---------- W1-05/06：命中流水 + /api/capture/status ----------

def test_capture_hits_rolling_truncation(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    for i in range(store.CAPTURE_HITS_MAX_LINES + 5):
        store.record_capture_hit("codex", f"/p/{i}.jsonl", 1)
    hits = store.load_capture_hits(limit=store.CAPTURE_HITS_MAX_LINES * 2)
    assert len(hits) == store.CAPTURE_HITS_MAX_LINES  # 滚动截断
    assert hits[-1]["path"] == f"/p/{store.CAPTURE_HITS_MAX_LINES + 4}.jsonl"


def test_capture_status_endpoint(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    # 新鲜命中 ×2 + 一条 30h 前的旧命中（不算 24h）
    store.record_capture_hit("codex", "/p/a.jsonl", 10)
    store.record_capture_hit("codex", "/p/b.jsonl", 4)
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hitsf = store.data_dir / "capture_hits.jsonl"
    with hitsf.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"agent": "workbuddy", "path": "/p/old.jsonl",
                             "events": 99, "ts": old}, ensure_ascii=False) + "\n")
    store.save_capture_failures({"cursor": 3})  # 黄标（从未命中）

    c = local_api_client(store)
    r = c.get("/api/capture/status")
    assert r.status_code == 200
    body = r.json()
    assert body["agents"]["codex"]["hits_24h"] == 2
    assert body["agents"]["codex"]["yellow_flag"] is False
    assert body["agents"]["workbuddy"]["hits_24h"] == 0  # 30h 前不算
    assert body["agents"]["cursor"]["yellow_flag"] is True  # 从未命中也露出
    assert body["agents"]["cursor"]["hits_24h"] == 0
    recent = body["recent_hits"]
    assert len(recent) == 3
    assert recent[0]["agent"] == "codex"  # 新在前（按 ts，不是文件追加序）
    assert recent[-1]["agent"] == "workbuddy"


# ---------- W1-08：check_route 接入自检 ----------

class _FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code


def _store_with_route(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_config({"default_model": "m",
                       "models": {"m": {"type": "cloud", "endpoint": "http://e/v1",
                                        "model": "x"}}})
    return store


def test_check_route_no_model(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    ok, msg = check_route(store)
    assert not ok and msg == "还没有配置模型"


def _patch_httpx_client(monkeypatch, resp=None, raises=None, seen=None):
    """整体替换 `httpx.Client` 类。

    此前只打 `httpx.Client.post` 一个方法：一旦替换因任何原因未生效，
    `check_route` 就会真的去连 "http://e/v1/chat/completions"——域名不可解析 →
    ConnectError → 全量跑时表现为"时灵时不灵"的假失败（实测出现过，且失败栈
    是 `seen[-1]` 的 IndexError，说明假桩一次都没被调用）。整体替换类之后，
    测试里**根本不存在真实传输层**，这类假失败不可能再发生。
    """

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **k):
            if seen is not None:
                seen.append(url)
            if raises is not None:
                raise raises
            return resp

    monkeypatch.setattr(httpx, "Client", _FakeClient)


def test_check_route_ok(monkeypatch, tmp_path):
    store = _store_with_route(tmp_path)
    _patch_httpx_client(monkeypatch, resp=_FakeResp(200))
    ok, msg = check_route(store)
    assert ok and msg == "接入正常"


def test_check_route_auth_rejected(monkeypatch, tmp_path):
    store = _store_with_route(tmp_path)
    _patch_httpx_client(monkeypatch, resp=_FakeResp(401))
    ok, msg = check_route(store)
    assert not ok and "密钥" in msg


def test_check_route_404(monkeypatch, tmp_path):
    store = _store_with_route(tmp_path)
    _patch_httpx_client(monkeypatch, resp=_FakeResp(404))
    ok, msg = check_route(store)
    assert not ok and "端点" in msg


def test_check_route_unreachable(monkeypatch, tmp_path):
    store = _store_with_route(tmp_path)
    _patch_httpx_client(monkeypatch, raises=httpx.ConnectError("refused"))
    ok, msg = check_route(store)
    assert not ok and "连不上" in msg


def test_check_route_url_normalized_like_llm(monkeypatch, tmp_path):
    """M8：自检 URL 与 llm 真实调用同口径——endpoint 已带 /v1 或
    /chat/completions 时不重复拼接（此前报 404 误导用户改配置）。"""
    from app.distill import llm

    seen: list[str] = []
    _patch_httpx_client(monkeypatch, resp=_FakeResp(200), seen=seen)
    for ep in ("http://e/v1", "http://e/v1/chat/completions", "http://e"):
        store = Store(tmp_path)
        store.ensure_layout()
        store.save_config({"default_model": "m",
                           "models": {"m": {"type": "cloud", "endpoint": ep,
                                            "model": "x"}}})
        check_route(store)
        assert seen[-1] == llm._chat_url({"endpoint": ep}), ep
    assert seen[0] == "http://e/v1/chat/completions"
    assert seen[1] == "http://e/v1/chat/completions"
    assert seen[2] == "http://e/v1/chat/completions"
