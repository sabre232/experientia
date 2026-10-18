"""飞轮核心闭环集成测试（H1-H4）：真实接线，从 session 到经验。

- 代理通道：ASGI 代理跑请求 → 会话结束 → 复盘接线（sweeper 同款调用）产经验
  （此前接线三处错误：await 同步函数 / async 未 await / dataclass 当 dict 传参）
- 文件通道：run_scan（假 adapter）→ session 落库带 trunk/req_count（磨合度可算）
  + 档 A 复盘产经验（"文件捕获零配置即自动出经验"，验收）
- 无模型降级：无纠正信号 → 0 条（空转会话零成本）
"""

import asyncio
import json
import time

import httpx
import pytest
from fastapi import FastAPI, Request

from app.capture.models import Message, Session, SessionRef
from app.distill import gsignal
from app.proxy.server import create_app
from tests.conftest import PROXY_AUTH_HEADERS, start_upstream
from app.store.store import Store

# 复盘模型输出（固定候选；corrected=True → G=L2_CORRECTED）
CANDIDATES = json.dumps([{
    "task": "写投放标题", "state": "首版标题被否",
    "action": "利益点前置出两版标题", "outcome": "点击率提升",
    "corrected": True, "causal": False,
}], ensure_ascii=False)


def _make_upstream() -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def cc(request: Request):
        return {"choices": [{"message": {"role": "assistant", "content": CANDIDATES}}]}

    return app


@pytest.fixture(scope="module")
def upstream():
    port, stop = start_upstream(_make_upstream())
    try:
        yield port
    finally:
        stop()


def _make_store(tmp_path, port) -> Store:
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_config({
        "default_model": "local",
        "models": {"local": {"type": "local",
                             "endpoint": f"http://127.0.0.1:{port}/v1",
                             "model": "test-model"}},
    })
    return store


def _run_session_end(app, session_id: str) -> None:
    """模拟 sweeper 的结束处理：sweep（落库）+ on_session_end(to_dict)（复盘）。

    钩子内部捕获异常并返回 None（fire-and-forget 口径），断言走 store 状态。"""
    tracker = app.state.tracker
    s = tracker._sessions.get(session_id)
    assert s is not None, "session 未进入追踪"
    s.last_ts = time.time() - 3700  # 越过 30 分钟空闲超时
    ended = tracker.sweep()
    assert [x.session_id for x in ended] == [session_id]
    asyncio.run(tracker.on_session_end(tracker.to_dict(
        next(x for x in ended if x.session_id == session_id))))


def test_proxy_session_end_review_produces_experience(tmp_path, upstream):
    """H1：代理通道会话结束 → 复盘接线 → 经验落库（生产路径同款调用）。"""
    store = _make_store(tmp_path, upstream)
    app = create_app(store)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     headers=PROXY_AUTH_HEADERS) as client:
            headers = {"x-session-id": "fw-p1"}
            msgs = ["帮我写投放标题 第1轮", "不对，利益点要前置，重写"]
            for i in range(2):
                # 口径：第 2 轮含否定词 → correction_hits>0 才复盘；
                # 真实 chat 客户端每请求重发全量历史（H6 增量口径依赖此约定）
                history = [{"role": "user", "content": m} for m in msgs[:i + 1]]
                r = await client.post("/v1/chat/completions", headers=headers,
                                      json={"model": "local", "messages": history})
                assert r.status_code == 200

    asyncio.run(run())
    _run_session_end(app, "fw-p1")

    exps = list(store.iter_experiences(include_distilled=True))
    assert len(exps) == 1, "会话结束复盘应产出 1 条候选经验"
    assert exps[0]["G"] == gsignal.L2_CORRECTED
    assert exps[0]["g_source"] == "auto"
    assert exps[0]["session_id"] == "fw-p1"
    # session 落库（sweep 内 _finalize）
    sessions = {s["session_id"]: s for s in store.list_sessions()}
    assert "fw-p1" in sessions
    assert sessions["fw-p1"]["req_count"] >= 2


def test_proxy_idle_short_session_no_review(tmp_path, upstream):
    """单请求会话（req_count=1）：落库但不复盘（空转零成本）。"""
    store = _make_store(tmp_path, upstream)
    app = create_app(store)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     headers=PROXY_AUTH_HEADERS) as client:
            r = await client.post("/v1/chat/completions",
                                  headers={"x-session-id": "fw-p2"},
                                  json={"model": "local",
                                        "messages": [{"role": "user", "content": "你好"}]})
            assert r.status_code == 200

    asyncio.run(run())
    _run_session_end(app, "fw-p2")
    assert list(store.iter_experiences(include_distilled=True)) == []


def _fake_file_env(tmp_path, monkeypatch, session: Session):
    """文件通道假 adapter（照 test_w2_capture_management 模式）。"""
    import app.capture.scan as scan_mod

    class FakeAdapter:
        name = "fake"

        def discover(self):
            return []

        def parse(self, ref):
            return None

        def parse_sessions(self, ref):
            return [session]

    f = tmp_path / "raw.txt"
    f.write_text("raw", encoding="utf-8")
    ref = SessionRef(agent="fake", session_id="fw-f1", path=f, size=1, mtime=0)
    monkeypatch.setattr(scan_mod, "REGISTRY", {"fake": FakeAdapter})
    monkeypatch.setattr(scan_mod, "detect",
                        lambda enabled=None, force=False, min_interval=0.0: {"fake": [ref]})
    return scan_mod


def _file_session() -> Session:
    return Session(
        agent="fake", session_id="fw-f1", project="p1",
        started_at="2026-09-01T10:00:00Z",
        messages=[
            Message(role="user", content="帮我写个投放标题"),
            Message(role="assistant", content="两版标题：A / B"),
            Message(role="user", content="不对，利益点要前置"),
            Message(role="assistant", content="改好了"),
        ],
    )


def test_file_channel_scan_records_and_reviews(tmp_path, monkeypatch, upstream):
    """H2/H3：文件捕获零配置出经验——scan 后 session 带 trunk/req_count（磨合度可算）
    + 复盘产经验。"""
    store = _make_store(tmp_path, upstream)
    scan_mod = _fake_file_env(tmp_path, monkeypatch, _file_session())
    result = scan_mod.run_scan(store, verbose=False)  # review=True（CLI 口径）
    assert result.new_sessions == {"fake": 1}

    # session 落库：归一化 + 复盘字段（H3：affinity 要求 trunk + req_count）
    sessions = {s["session_id"]: s for s in store.list_sessions()}
    s = sessions["fw-f1"]
    assert s["req_count"] == 2, "req_count = user 轮数"
    assert s["trunk"], "trunk 必须落库（缺省至少'其他'）"
    assert s["correction_hits"] == 1, "否定词'不对'命中 1 次"

    # 复盘产经验（mock 上游返回 1 条 corrected 候选）
    exps = list(store.iter_experiences(include_distilled=True))
    assert len(exps) == 1
    assert exps[0]["G"] == gsignal.L2_CORRECTED
    assert exps[0]["session_id"] == "fw-f1"

    # 磨合度：文件通道 session 参与 affinity 聚合（不再永远"待积累"）
    # 键 = agent/trunk/category（与 growth_summary 同形）
    aff = store.growth_summary(days=30)["affinity"]
    key = f"{s.get('agent') or 'unknown'}/{s['trunk']}/{s['category']}"
    assert key in aff, f"affinity 应含 {key}"


def test_file_channel_no_model_fallback(tmp_path, monkeypatch):
    """新语义：无模型 + 有纠正信号 → 不落逐字经验，片段挂证据队列待重放。"""
    store = Store(tmp_path)
    store.ensure_layout()  # 无 models 配置
    scan_mod = _fake_file_env(tmp_path, monkeypatch, _file_session())
    result = scan_mod.run_scan(store, verbose=False)
    assert result.new_sessions == {"fake": 1}
    assert list(store.iter_experiences(include_distilled=True)) == []
    pend = store.load_pending_review_records()
    assert len(pend) == 1 and pend[0]["session_id"] == "fw-f1"
    assert pend[0]["snippets"]  # 命中否定词的原文片段已留证


def test_file_channel_idle_session_no_experience(tmp_path, monkeypatch):
    """单轮会话（req_count=1）→ 不复盘、0 经验。"""
    store = Store(tmp_path)
    store.ensure_layout()
    s = _file_session()
    s.messages = [Message(role="user", content="你好"),
                  Message(role="assistant", content="你好！")]
    scan_mod = _fake_file_env(tmp_path, monkeypatch, s)
    scan_mod.run_scan(store, verbose=False)
    assert list(store.iter_experiences(include_distilled=True)) == []
    recorded = {x["session_id"]: x for x in store.list_sessions()}
    assert recorded["fw-f1"]["req_count"] == 1
