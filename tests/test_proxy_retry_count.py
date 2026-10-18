"""守卫：上游失败后客户端重试，该轮消息必须仍计入。

旧实现在请求前就推进 `last_user_count`，而上游失败（不可达/非 JSON/非 200）
不记账——客户端重试同一全量历史被判"无新增"，该轮 user 消息与否定词**永久
不计**（correction_hits 系统性偏弱、复盘 digest 变弱）。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.proxy.server import create_app
from app.store.store import Store
from tests.conftest import PROXY_AUTH_HEADERS, start_upstream


@pytest.fixture(scope="module")
def flaky_upstream():
    """首个请求回 400（不重试的失败），之后正常 200。"""
    app = FastAPI()
    state = {"calls": 0}

    @app.post("/v1/chat/completions")
    async def cc(request: Request):
        state["calls"] += 1
        if state["calls"] == 1:
            return JSONResponse(status_code=400,
                                content={"error": "bad request"})
        await request.json()
        return {"choices": [{"message": {"role": "assistant",
                                         "content": "好的，已调整"}}]}

    port, stop = start_upstream(app)
    try:
        yield port
    finally:
        stop()


def _store(tmp_path, port) -> Store:
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_config({
        "default_model": "local",
        "models": {"local": {"type": "local",
                             "endpoint": f"http://127.0.0.1:{port}/v1",
                             "model": "test-model"}},
    })
    return store


def test_failed_upstream_then_retry_still_counts(tmp_path, flaky_upstream):
    store = _store(tmp_path, flaky_upstream)
    app = create_app(store)
    payload = {"model": "local",
               "messages": [{"role": "user", "content": "不对，利益点没有前置"}]}

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     headers=PROXY_AUTH_HEADERS) as client:
            h = {"x-session-id": "m5-s1"}
            r1 = await client.post("/v1/chat/completions", headers=h, json=payload)
            # 客户端重试：同一全量历史（真实客户端的重试行为）
            r2 = await client.post("/v1/chat/completions", headers=h, json=payload)
            return r1, r2

    r1, r2 = asyncio.run(run())
    assert r1.status_code == 400, "首次应透传上游拒绝"
    assert r2.status_code == 200, "重试应成功"

    s = app.state.tracker._sessions.get("m5-s1")
    assert s is not None
    assert s.last_user_count == 1, "上游失败不得推进计数（否则重试被判无新增）"
    assert s.correction_hits == 1, \
        "重试后该轮 user 消息与否定词必须计入（旧实现永久漏计）"


def test_success_path_counts_normally(tmp_path, flaky_upstream):
    """回归：成功路径计数与旧行为一致（不因 M5 少计）。"""
    store = _store(tmp_path, flaky_upstream)
    app = create_app(store)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     headers=PROXY_AUTH_HEADERS) as client:
            h = {"x-session-id": "m5-s2"}
            b1 = {"model": "local", "messages": [
                {"role": "user", "content": "第一轮：写个标题"}]}
            b2 = {"model": "local", "messages": [
                {"role": "user", "content": "第一轮：写个标题"},
                {"role": "assistant", "content": "标题 A"},
                {"role": "user", "content": "不对，重写"}]}
            r1 = await client.post("/v1/chat/completions", headers=h, json=b1)
            r2 = await client.post("/v1/chat/completions", headers=h, json=b2)
            return r1, r2

    r1, r2 = asyncio.run(run())
    assert r1.status_code == 200 and r2.status_code == 200
    s = app.state.tracker._sessions.get("m5-s2")
    assert s.last_user_count == 2
    assert s.correction_hits == 1  # 只有第二轮含否定词
    assert json.dumps({"ok": True})  # 占位：保持 json 导入有实际用途
