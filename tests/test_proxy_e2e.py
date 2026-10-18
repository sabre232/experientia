"""代理端到端测试：真实端口上的 mock 上游 + ASGI 代理。

验证：首条注入 / 同 session 不重复注入 / 硬钩子每次在场 /
内部头不注入不记录 / fail-open / 任务自动归类。
"""

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, Request

from app.proxy.server import create_app
from app.store.store import Store
from tests.conftest import PROXY_AUTH_HEADERS, start_upstream

CAPTURED: list[dict] = []


def _make_upstream() -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def cc(request: Request):
        body = await request.json()
        CAPTURED.append(body)
        return {
            "choices": [
                {"message": {"role": "assistant", "content": "上游回复：利益点前置标题两版"}}
            ]
        }

    return app


@pytest.fixture(scope="module")
def upstream():
    port, stop = start_upstream(_make_upstream())
    try:
        yield port
    finally:
        stop()


def _make_store(tmp_path, port):
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_config({
        "default_model": "local",
        "models": {"local": {"type": "local", "endpoint": f"http://127.0.0.1:{port}/v1",
                             "model": "test-model"}},
        "seed_keywords": {"营销": ["文案", "投放", "标题"]},
    })
    store.write_skill("营销", "营销",
                      "## 标准流程\n1. 确认投放目标与人群\n2. 产出 ≥2 版标题（利益点前置）\n\n"
                      "## 成功要点\n- 标题用利益点前置句式\n\n"
                      "## 失败模式\n- [Solidified] 纯情绪文案点击率低（出现 3 次）\n"
                      "- [Watching] 标题超长会被截断（出现 1 次）\n")
    store.write_preferences("营销", "- 结论先行")
    rules = {"rules": [{"name": "硬钩子测试", "text": "NEVER 跳过 A/B 测试",
                        "trigger": "hard-hook", "enabled": True}]}
    (store.data_dir / "rules.json").write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
    return store


def test_first_request_injects_subsequent_does_not(tmp_path, upstream):
    store = _make_store(tmp_path, upstream)
    app = create_app(store)
    CAPTURED.clear()

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     headers=PROXY_AUTH_HEADERS) as client:
            headers = {"x-session-id": "e2e-s1"}
            r1 = await client.post("/v1/chat/completions", headers=headers,
                                   json={"model": "local", "messages": [{"role": "user", "content": "帮我写个投放标题"}]})
            r2 = await client.post("/v1/chat/completions", headers=headers,
                                   json={"model": "local", "messages": [{"role": "user", "content": "第二轮：再改一下"}]})
            return r1, r2

    r1, r2 = asyncio.run(run())
    assert r1.status_code == 200 and r2.status_code == 200

    body1, body2 = CAPTURED[0], CAPTURED[1]
    # 首条：system 注入块在场
    sys1 = body1["messages"][0]
    assert sys1["role"] == "system"
    assert "injected by experientia" in sys1["content"]
    assert "纯情绪文案点击率低" in sys1["content"]      # 已固化失败模式
    assert "标题超长会被截断" not in sys1["content"]     # 观察中不注入
    assert "结论先行" in sys1["content"]                  # 偏好
    assert "确认投放目标与人群" in sys1["content"]          # SOP
    assert "NEVER 跳过 A/B 测试" in sys1["content"]        # 硬钩子
    # 同 session 第二条：经验块不再注入，硬钩子每次在场
    sys2 = next((m for m in body2["messages"] if m.get("role") == "system"), None)
    if sys2 is not None:
        assert "标准流程" not in sys2["content"]
        assert "NEVER 跳过 A/B 测试" in sys2["content"]
    else:
        pytest.fail("第二条请求丢失了硬钩子规则注入")
    # 上游模型名被替换为路由配置的真实 model
    assert body1["model"] == "test-model"


def test_task_trunk_category_recorded(tmp_path, upstream):
    store = _make_store(tmp_path, upstream)
    app = create_app(store)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     headers=PROXY_AUTH_HEADERS) as client:
            return await client.post("/v1/chat/completions",
                                     headers={"x-session-id": "e2e-s2"},
                                     json={"model": "local", "messages": [{"role": "user", "content": "写投放文案"}]})

    r = asyncio.run(run())
    assert r.status_code == 200
    tracker = app.state.tracker
    s = tracker._sessions.get("e2e-s2")
    assert s is not None
    assert s.trunk == "营销"  # 种子关键词命中
    assert s.category


def test_internal_header_bypasses_injection(tmp_path, upstream):
    store = _make_store(tmp_path, upstream)
    app = create_app(store)
    CAPTURED.clear()

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     headers=PROXY_AUTH_HEADERS) as client:
            return await client.post("/v1/chat/completions",
                                     headers={"x-experientia-internal": "1"},
                                     json={"model": "local", "messages": [{"role": "user", "content": "内部调用"}]})

    r = asyncio.run(run())
    assert r.status_code == 200
    body = CAPTURED[0]
    assert not any(m.get("role") == "system" for m in body["messages"])
    # 不记录：session 追踪为空
    assert app.state.tracker.active_count == 0


def test_health(tmp_path, upstream):
    store = _make_store(tmp_path, upstream)
    app = create_app(store)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     headers=PROXY_AUTH_HEADERS) as client:
            return await client.get("/health")

    r = asyncio.run(run())
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
