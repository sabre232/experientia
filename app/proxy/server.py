"""统一代理层 localhost:8100（产品文档）。

- 协议：OpenAI 兼容 /v1/chat/completions + Anthropic 原生 /v1/messages
- 注入：session 首条（或任务归类变化）注入经验块；硬钩子规则每次请求重注入
- 记录：请求级记录进 session 追踪（sessions.jsonl 由 session 结束时统一落库）
- fail-open：上游错误原样透传，代理只加功能不添故障；注入组装异常时跳过注入直接转发
- 自引用防护：x-experientia-internal: 1 的请求只转发、不记录、不注入
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..net_util import DIRECT_LOOPBACK
from ..store.store import SESSION_MSG_KEEP, Store
from ..time_util import utc_str
from ..token_util import ensure_api_token, resolve_fallback_secret
from . import detect, inject

logger = logging.getLogger("experientia.proxy")

# proxy_span 是每被代理请求一行的热路径——默认降到 DEBUG（异常路径仍
# WARNING/ERROR）。排查代理问题时设 EXPERIENTIA_PROXY_TRACE=1 可恢复 INFO 全量。
_PROXY_TRACE = os.environ.get("EXPERIENTIA_PROXY_TRACE") == "1"


def _proxy_span(msg: str, *args) -> None:
    if _PROXY_TRACE:
        logger.info(msg, *args)
    else:
        logger.debug(msg, *args)


INTERNAL_HEADER = "x-experientia-internal"
DEFAULT_TIMEOUT = httpx.Timeout(600.0, connect=10.0)

# REL-2：非流式上游转发对瞬时网络错 / 429 / 5xx 重试 1 次（chat 幂等、成本有界；
# 流式已在响应中途产生，重试语义不成立，只记录不重试）
_PROXY_RETRYABLE_CODES = {429, 500, 502, 503, 504}



def _proxy_retryable(status: int) -> bool:
    """TEST-3 纯函数：该 HTTP 状态码是否值得对幂等 chat 请求重试。"""
    return status in _PROXY_RETRYABLE_CODES


def _sse_delta_text(data: dict) -> str:
    """TEST-3 纯函数：OpenAI SSE data 块 → 本次增量文本（缺失/非 dict → ""）。"""
    delta = ((data.get("choices") or [{}])[0].get("delta") or {})
    return delta.get("content") or ""


async def _relay_post_nonstream(client: httpx.AsyncClient, url: str, json_body: dict,
                                headers: dict, what: str) -> httpx.Response:
    """带 1 次重试的非流式 POST；最终仍失败时向上抛（fail-open 语义不变）。"""
    for attempt in (1, 2):
        try:
            resp = await client.post(url, json=json_body, headers=headers)
        except httpx.HTTPError as exc:
            if attempt == 2:
                raise
            logger.warning("%s 上游瞬时错误，重试 1 次: %s", what, exc)
            await asyncio.sleep(1.0)
            continue
        if _proxy_retryable(resp.status_code) and attempt == 1:
            logger.warning("%s 上游 %s，重试 1 次", what, resp.status_code)
            await asyncio.sleep(1.0)
            continue
        return resp
    raise RuntimeError("unreachable")


@dataclass
class TrackedSession:
    session_id: str
    agent: str
    model: str
    trunk: str = "其他"
    category: str = "未分类"
    project: str | None = None
    started_at: float = field(default_factory=time.time)
    last_ts: float = field(default_factory=time.time)
    user_messages: list[str] = field(default_factory=list)
    assistant_messages: list[str] = field(default_factory=list)
    injected_task: tuple[str, str] | None = None
    req_count: int = 0
    correction_hits: int = 0
    # chat 协议每请求重发全量历史，记录已见 user 消息数，
    # 只对本次新增的消息做入列与否定词计数（否则修正轮数随轮数平方膨胀）
    last_user_count: int = 0
    tokens_in: int = 0   # 上游 usage 累进（W1-01；取不到记 0，fail-open）
    tokens_out: int = 0
    inject_hits: int = 0      # 注入实际发生次数（OBS-2）
    latency_sum_ms: float = 0.0  # 请求耗时累进（OBS-2，供平均/分位）
    latency_max_ms: float = 0.0


class SessionTracker:
    """内存 session 状态 + 空闲 30 分钟结束。"""

    def __init__(self, store: Store, on_session_end=None) -> None:
        self.store = store
        self._sessions: dict[str, TrackedSession] = {}
        self.on_session_end = on_session_end  # distill.review 的钩子

    def get(self, session_id: str, agent: str, model: str) -> TrackedSession:
        s = self._sessions.get(session_id)
        if s is None:
            s = TrackedSession(session_id=session_id, agent=agent, model=model)
            self._sessions[session_id] = s
        s.last_ts = time.time()
        s.req_count += 1
        return s

    def record_exchange(self, s: TrackedSession, user_text: str, assistant_text: str, negation_words: list[str]) -> None:
        # 内存封顶：列表只留最近 SESSION_MSG_KEEP 条（与落库契约同参）——
        # 数小时、数百轮、每轮重发全量历史的 agent 会话此前可驻留数百 MB。
        # 计数器（req_count/correction_hits）独立累进，不受截断影响；
        # 复盘 digest 只吃 [-15:]×800 字，fallback 否定词命中取第一条——
        # 最近 20 条覆盖全部消费口径，更早正文在 sessions.jsonl 与归档。
        if user_text:
            s.user_messages.append(user_text)
            if len(s.user_messages) > SESSION_MSG_KEEP:
                s.user_messages = s.user_messages[-SESSION_MSG_KEEP:]
        if assistant_text:
            s.assistant_messages.append(assistant_text)
            if len(s.assistant_messages) > SESSION_MSG_KEEP:
                s.assistant_messages = s.assistant_messages[-SESSION_MSG_KEEP:]
        # 否定词信号：后续用户消息命中否定词 → 计数
        if user_text and any(w in user_text for w in negation_words if w):
            s.correction_hits += 1

    def record_exchange_delta(self, s: TrackedSession, new_user_texts: list[str],
                              assistant_text: str, negation_words: list[str]) -> None:
        """：增量记录——chat 协议每请求重发全量历史，代理端只对
        本次新增的 user 消息入列与计否定词（与文件通道 scan.py 逐条口径一致）。

        new_user_texts 由 _new_user_texts() 产出（已按 last_user_count 截差并推进）。
        user_messages[-1] 因此是真实的「最后一条 user 消息」，收尾判定
        （gsignal._is_confirmatory_closing）得以成立。
        """
        for text in new_user_texts:
            if not text:
                continue
            s.user_messages.append(text)
            if any(w in text for w in negation_words if w):
                s.correction_hits += 1
        if len(s.user_messages) > SESSION_MSG_KEEP:
            s.user_messages = s.user_messages[-SESSION_MSG_KEEP:]
        if assistant_text:
            s.assistant_messages.append(assistant_text)
            if len(s.assistant_messages) > SESSION_MSG_KEEP:
                s.assistant_messages = s.assistant_messages[-SESSION_MSG_KEEP:]

    def record_usage(self, s: TrackedSession, tokens_in: int, tokens_out: int) -> None:
        s.tokens_in += max(int(tokens_in or 0), 0)
        s.tokens_out += max(int(tokens_out or 0), 0)

    def record_latency(self, s: TrackedSession, ms: float) -> None:
        """OBS-2：请求耗时累进（平均可由 latency_sum_ms / req_count 得出）。"""
        ms = max(float(ms or 0), 0)
        s.latency_sum_ms += ms
        s.latency_max_ms = max(s.latency_max_ms, ms)

    def sweep(self) -> list[TrackedSession]:
        """结束空闲 session（>30 分钟无请求），交给蒸馏复盘。"""
        now = time.time()
        ended = [
            s for s in self._sessions.values()
            if now - s.last_ts > detect.SESSION_IDLE_TIMEOUT_SECONDS
        ]
        for s in ended:
            self._sessions.pop(s.session_id, None)
            self._finalize(s)
        return ended

    def to_dict(self, s: TrackedSession) -> dict:
        """TrackedSession → 落库/复盘共用的 session dict（统一格式）。"""
        return {
            "agent": s.agent,
            "session_id": s.session_id,
            "model": s.model,
            "trunk": s.trunk,
            "category": s.category,
            "project": s.project,
            # 去重 R1：epoch → ISO 统一走 time_util（原先是本地 strftime+gmtime 组合）
            "started_at": utc_str(s.started_at),
            "ended_at": utc_str(s.last_ts),
            "req_count": s.req_count,
            "correction_hits": s.correction_hits,
            "tokens_in": s.tokens_in,
            "tokens_out": s.tokens_out,
            "inject_hits": s.inject_hits,
            "latency_sum_ms": round(s.latency_sum_ms, 1),
            "latency_max_ms": round(s.latency_max_ms, 1),
            # 入点已封顶（record_exchange），这里不再截断
            "user_messages": s.user_messages,
            "assistant_messages": s.assistant_messages,
        }

    def _finalize(self, s: TrackedSession) -> None:
        if s.req_count == 0:
            return
        self.store.record_session(self.to_dict(s))

    @property
    def active_count(self) -> int:
        return len(self._sessions)


def _model_routes(store: Store) -> dict[str, dict]:
    config = store.load_config()
    return config.get("models", {}) or {}


def _resolve_route(store: Store, model: str) -> dict | None:
    """body.model → 上游路由。精确匹配 name/model 字段；否则默认模型路由。"""
    routes = _model_routes(store)
    if not routes:
        return None
    for name, route in routes.items():
        if model in (name, route.get("model")):
            return {"route_name": name, **route}
    config = store.load_config()
    default_name = config.get("default_model")
    if default_name in routes:
        return {"route_name": default_name, **routes[default_name]}
    # 没有任何配置 → 原样直连（fail-open：代理不该变成单点）
    # 回退必留痕——静默回退会让"请求的 model"与"实际走的
    # 路由"悄悄脱节，排查路由漂移无从下手
    first_name = next(iter(routes))
    logger.warning("路由回退：请求 model=%r 未命中任何路由且 default_model=%r 未配置，"
                   "回退到首个路由 %r", model, default_name, first_name)
    return {"route_name": first_name, **routes[first_name]}


def _endpoint_url(route: dict) -> str:
    base = (route.get("endpoint") or "").rstrip("/")
    return base


# 遗留：明文 api_key 兜底的弃用告警（每路由每进程只告一次，防刷屏）
_PLAINTEXT_KEY_WARNED: set[str] = set()


def _upstream_headers(route: dict, store: Store) -> dict[str, str]:
    headers = {}
    key_ref = route.get("key_ref")
    if key_ref:
        try:
            import keyring

            key = keyring.get_password("experientia", key_ref)
            if key:
                headers["Authorization"] = f"Bearer {key}"
        except Exception as exc:
            # 必留痕：keyring 读失败 = 上游请求静默丢 Authorization，属难排查静默点
            logger.warning("keyring 读取路由密钥失败（key_ref=%s），上游请求将不带 Authorization: %s",
                           key_ref, exc)
    elif (key := resolve_fallback_secret(route)):
        if route.get("api_key"):  # 仅旧明文（非 DPAPI 加密）才提示弃用
            name = str(route.get("route_name") or route.get("model") or "?")
            if name not in _PLAINTEXT_KEY_WARNED:
                _PLAINTEXT_KEY_WARNED.add(name)
                logger.warning("路由 %s 使用 config.json 明文 api_key（已弃用），"
                               "建议改用 key_ref + keyring", name)
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _user_text_from_openai(body: dict) -> str:
    parts = []
    for m in body.get("messages") or []:
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, list):
                parts.append("".join(p.get("text", "") for p in c if isinstance(p, dict)))
    return "\n".join(parts)


def _assistant_text_from_openai(data: Any) -> str:
    try:
        choices = data.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            return msg.get("content") or ""
    except AttributeError:
        pass
    return ""


def _usage_from_openai(data: Any) -> tuple[int, int]:
    """OpenAI 协议 usage → (in, out)。缺字段/非 dict 一律 (0, 0)（fail-open）。"""
    try:
        u = data.get("usage") or {}
        return int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0, 0


def _usage_from_anthropic(data: Any) -> tuple[int, int]:
    """Anthropic 协议 usage → (in, out)。缺字段一律 (0, 0)（fail-open）。"""
    try:
        u = data.get("usage") or {}
        return int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0, 0


def _user_texts_from_openai(body: dict) -> list[str]:
    """OpenAI body.messages → 按序 user 消息文本列表（全量历史）。"""
    parts: list[str] = []
    for m in body.get("messages") or []:
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, list):
                parts.append("".join(p.get("text", "") for p in c if isinstance(p, dict)))
    return parts


def _user_texts_from_anthropic(body: dict) -> list[str]:
    """Anthropic body.messages → 按序 user 消息文本列表（全量历史）。"""
    parts: list[str] = []
    for m in body.get("messages") or []:
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            parts.append("".join(
                p.get("text", "") for p in c if isinstance(p, dict)))
    return parts


def _peek_user_texts(texts: list[str], s: TrackedSession) -> list[str]:
    """：只截差**不推进**计数。

    转发路径原来在请求前就调 `_new_user_texts` 推进了计数，而上游失败
    （不可达 → 502 / 非 JSON / 非 200）时并不记账：客户端重试同一全量历史
    会被判"无新增"，该轮 user 消息与否定词**永久不计**（修正轮数系统性偏弱）。
    现在先 peek，确认上游成功再 `_commit_user_count`。
    客户端压缩历史（总条数变少）时保守视为无新增，不回退计数。"""
    if len(texts) <= s.last_user_count:
        return []
    return texts[s.last_user_count:]


def _commit_user_count(texts: list[str], s: TrackedSession | None) -> None:
    """M5：成功记账点调用——推进计数（单调取大，防并发请求互相盖回旧值）。"""
    if s is None:
        return
    s.last_user_count = max(s.last_user_count, len(texts))


def _new_user_texts(texts: list[str], s: TrackedSession) -> list[str]:
    """：全量历史 → 本次新增段（按 last_user_count 截差并推进）。

    客户端压缩历史（总条数变少）时按保守处理：视为无新增，不回退计数，
    避免压缩后整段重发导致修正轮数虚高（宁少计不多计）。

    ⚠️ 会**立即推进**计数，只适合"确定要记账"的场合；上游可能失败的转发
    路径请用 `_peek_user_texts` + `_commit_user_count`。"""
    new = _peek_user_texts(texts, s)
    if new:
        # 仅在真有新增时推进：历史被压缩（total <= last）时保持不回退计数，
        # 避免压缩后整段重发把计数顶掉、后续真实新增被误判为"无新增"。
        s.last_user_count = len(texts)
    return new


def _anthropic_sse_delta_text(data: dict) -> str:
    """TEST-3 纯函数：Anthropic SSE data 块 → 本次增量文本（content_block_delta）。"""
    if data.get("type") != "content_block_delta":
        return ""
    delta = data.get("delta") or {}
    return delta.get("text") or ""


def _anthropic_sse_usage(data: dict, usage: list[int]) -> None:
    """Anthropic SSE data 块 → 就地更新 [in, out]（message_start 给 in、
    message_delta 给 out；只取事件携带的字段，缺省保持原值）。"""
    u = (data.get("message") or {}).get("usage") or data.get("usage") or {}
    if not isinstance(u, dict):
        return
    if "input_tokens" in u:
        usage[0] = int(u.get("input_tokens") or 0)
    if "output_tokens" in u:
        usage[1] = int(u.get("output_tokens") or 0)


def _proxy_token_matches(header_value: str, expected: str | None) -> bool:
    """M-N1: 代理 Bearer token 校验（空 expected 视为不启用）。
    header_value 支持 "Bearer x" / 裸值 / Anthropic 客户端的 x-api-key 原值。"""
    if not expected:
        return True
    import hmac
    got = header_value.strip()
    if got.lower().startswith("bearer "):
        got = got[7:].strip()
    # 与 local_api._token_matches 同款）：compare_digest 对含
    # 非 ASCII 的 str 抛 TypeError；编码为 bytes 后比较，语义不变。
    return bool(got) and hmac.compare_digest(got.encode(), expected.encode())


def _resolve_upstream(store: Store, model: str, body: dict, path: str,
                      base_headers: dict | None = None) -> tuple[str, dict, dict] | None:
    """路由解析 + 上游 URL / 请求头 / 真实模型名替换。

    OpenAI（v1/chat/completions）与 Anthropic（v1/messages）两个转发管道的
    这段此前逐字重复，只有 path 与基础请求头不同。抽出来后两处共用同一份
    "路由不存在 / 模型名替换"逻辑，不会再各自漂移。

    顺带统一 URL 拼接：`_endpoint_url(route)` 带尾斜杠时，OpenAI 侧原本会拼出
    `//chat/completions`（Anthropic 侧已有 rstrip，两边不一致）。

    返回 None = 未配置上游模型——由调用方按各自协议回 502（错误体格式不同，故
    不在这里统一）。
    """
    route = _resolve_route(store, model)
    if route is None or not route.get("endpoint"):
        return None
    # endpoint 已含完整路径（.../chat/completions）时避免拼出
    # 双路径 → 上游 404（与 llm._chat_url 的 endswith 分支同口径）。
    base = _endpoint_url(route).rstrip("/")
    url = base if base.endswith(path) else base + path
    forward_headers = {"Content-Type": "application/json"}
    if base_headers:
        forward_headers.update(base_headers)
    forward_headers.update(_upstream_headers(route, store))
    # 上游模型名：agent 用路由名（代理侧名称）调用时，替换为路由配置的真实上游 model ID
    if route.get("model") and model == route.get("route_name"):
        body = {**body, "model": route["model"]}
    return url, forward_headers, body


def create_app(store: Store) -> FastAPI:
    tracker = SessionTracker(store, on_session_end=_make_session_end_hook(store))
    state: dict[str, Any] = {"client": None, "sweeper_task": None}
    # 8100 鉴权默认开启——config.proxy_token 未显式配置时
    # 复用 8101 同源 token（env → keyring → 数据目录文件，见 token_util）。
    # 「token 为空 = 放行全部请求」的旧默认让本机任意进程可白嫖上游模型路由；
    # config.proxy_token 保留为显式覆盖（老部署自配过 token 的不受影响）。
    # 外部 agent 侧的 apiKey/ANTHROPIC_API_KEY 需填 Experientia 令牌（接入页可复制）。
    _proxy_cfg_token = str(store.load_config().get("proxy_token") or "").strip()
    _proxy_token = _proxy_cfg_token or ensure_api_token(store.data_dir)
    logger.info("代理 8100 Bearer 鉴权已启用%s",
                "（config.proxy_token 显式配置）" if _proxy_cfg_token
                else "（复用 8101 同源 token）")

    def negation_words() -> list[str]:
        return store.load_config().get("negation_words", []) or [
            "不对", "错了", "重来", "不是这个意思", "不要这样", "wrong", "redo",
        ]

    async def get_client() -> httpx.AsyncClient:
        if state["client"] is None or state["client"].is_closed:
            # 显式连接池上限（默认池在并发转发下可能排队）——上游并发
            # 能力有限，保持 20 上限、10 keep-alive。mounts=DIRECT_LOOPBACK 必须保留。
            state["client"] = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT, follow_redirects=True,
                mounts=DIRECT_LOOPBACK,
                limits=httpx.Limits(max_keepalive_connections=10,
                                    max_connections=20))
        return state["client"]

    async def sweeper() -> None:
        while True:
            await asyncio.sleep(60)
            try:
                ended = tracker.sweep()
                for s in ended:
                    if tracker.on_session_end is not None:
                        try:
                            await tracker.on_session_end(tracker.to_dict(s))
                        except Exception as exc:
                            logger.warning("session 结束处理失败: %s", exc)
            except Exception as exc:
                logger.warning("sweeper 异常: %s", exc)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await get_client()
        state["sweeper_task"] = asyncio.create_task(sweeper())
        try:
            yield
        finally:
            if state["sweeper_task"]:
                state["sweeper_task"].cancel()
            if state["client"] and not state["client"].is_closed:
                await state["client"].aclose()

    app = FastAPI(title="experientia-proxy", lifespan=lifespan)

    @app.middleware("http")
    async def _proxy_auth(request: Request, call_next):
        """H4：8100 默认强制 Bearer 鉴权（health 豁免）。
        Anthropic 系客户端（Claude Code 的 ANTHROPIC_API_KEY）走 x-api-key 头，
        一并接受；两者都不匹配 → 401。"""
        if request.url.path != "/health":
            auth = (request.headers.get("authorization", "")
                    or request.headers.get("x-api-key", ""))
            if not _proxy_token_matches(auth, _proxy_token):
                return JSONResponse(
                    status_code=401,
                    content={"error": {"message": "unauthorized"}})
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "active_sessions": tracker.active_count}

    @app.get("/v1/models")
    async def openai_models() -> dict:
        """OpenAI 兼容模型列表（B-2）。

        OpenCode / LM Studio 等 OpenAI 兼容客户端用 /v1/models 探测模型 id；
        未配路由也返回空 list（对象存在即可，兼容客户端握手）而非 404。
        """
        routes = _model_routes(store)
        return {
            "object": "list",
            "data": [
                {"id": (r.get("model") or name), "object": "model",
                 "owned_by": name, "created": 0}
                for name, r in routes.items()
            ],
        }

    def _assemble_injection_block(store, s, user_text, agent):
        """注入组装（fail-open：任何异常都跳过注入）。OpenAI/Anthropic 端点共用。

        提取为独立函数，消除两处 100% 相同的 try/except 注入代码。"""
        block = ""
        if s is not None:
            try:
                need_experience = s.injected_task != (s.trunk, s.category)
                experience = ""
                if need_experience:
                    experience = inject.assemble_experience_block(
                        store, s.trunk, s.category, task_text=user_text)
                # H-A0 工具范围：传已识别的 agent；H-O1 文件范围：当前消息里的文件上下文
                rules = inject.assemble_rules_block(
                    store, user_text, agent=agent,
                    files=inject.extract_file_context(user_text))
                parts = [p for p in (rules, experience) if p]
                block = "\n\n".join(parts)
                if need_experience and experience:
                    # 仅当真正注入了经验才钉 injected_task——
                    # 空结果也置位会把"会话首条注入"钉死，会话中途蒸馏出经验也不再注入。
                    s.injected_task = (s.trunk, s.category)
                    # 真实注入落盘：injection.log + (trunk/category)
                    # 条目级命中累计——第⑤环反馈与档 C 条目老化的数据锚点，
                    # 必须把"真正进入注入块的条目"items 一并落盘，否则反馈/老化空转。
                    try:
                        store.record_injection(
                            s.trunk, s.category, s.session_id,
                            inject.estimate_tokens(experience),
                            items=inject.selected_experience_items(
                                store, s.trunk, s.category,
                                task_text=user_text))
                    except Exception as exc:
                        logger.warning("注入命中落盘失败（不影响注入）: %s", exc)
                if block:
                    s.inject_hits += 1
            except Exception as exc:
                logger.warning("注入组装失败，跳过注入: %s", exc)
        return block


# ---------- OpenAI 兼容 ----------

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Any:
        body = await request.json()
        headers = {k.lower(): v for k, v in request.headers.items()}
        internal = headers.get(INTERNAL_HEADER) == "1"

        agent = detect.detect_agent(headers)
        model = body.get("model", "")
        session_id = detect.get_session_id(headers, body)
        s = tracker.get(session_id, agent, model) if not internal else None

        if s is not None:
            user_text = _user_text_from_openai(body)
            task = detect.detect_task_context(
                body.get("messages") or [],
                store.load_config().get("seed_keywords", detect.DEFAULT_SEED_KEYWORDS),
                detect.known_categories_from_store(store),
            store=store,
            )
            s.trunk, s.category = task["trunk"], task["category"]
            s.project = body.get("project")
        else:
            user_text = ""

        block = _assemble_injection_block(store, s, user_text, agent)
        body = inject.apply_injection_openai(body, block)

        # 路由与转发
        resolved = _resolve_upstream(store, model, body, "/chat/completions")
        if resolved is None:
            return JSONResponse({"error": {"message": "experientia: 未配置上游模型（config.json models）"}}, status_code=502)
        url, forward_headers, body = resolved

        client = await get_client()
        t0 = time.monotonic()
        # 先只截差**不推进**计数——上游失败（502 / 非 JSON /
        # 非 200）时不记账，客户端重试同一全量历史仍算新增；确认成功才推进。
        # （旧实现在此处调 _new_user_texts 立即推进，重试被判"无新增"永久漏计。）
        user_texts_all = _user_texts_from_openai(body) if s is not None else []
        new_user_texts = _peek_user_texts(user_texts_all, s) if s is not None else []
        try:
            if body.get("stream"):
                # OpenAI 协议流式默认不带 usage；请求 include_usage 让上游在
                # 末块回传（W1-01）。客户端已自带 stream_options 时不覆盖。
                if not body.get("stream_options"):
                    body = {**body, "stream_options": {"include_usage": True}}
                req = client.build_request("POST", url, json=body, headers=forward_headers)
                upstream = await client.send(req, stream=True)

                async def stream_back():
                    collected: list[str] = []
                    usage_in = usage_out = 0
                    usage_seen = False  # 只取最后一次 usage 事件，避免重复累加
                    t_start = time.monotonic()
                    try:
                        async for line in upstream.aiter_lines():
                            if line.startswith("data: "):
                                payload = line[6:].strip()
                                if payload == "[DONE]":
                                    break
                                try:
                                    data = json.loads(payload)
                                    piece = _sse_delta_text(data)
                                    if piece:
                                        collected.append(piece)
                                    u = data.get("usage")
                                    if isinstance(u, dict):
                                        usage_in = int(u.get("prompt_tokens") or 0)
                                        usage_out = int(u.get("completion_tokens") or 0)
                                        usage_seen = True
                                except json.JSONDecodeError as exc:
                                    # 必留痕：SSE data 行非 JSON = 协议漂移信号，丢弃但不可静默
                                    logger.warning("SSE data 行 JSON 解析失败（已丢弃该行）: %s", exc)
                            yield line + "\n"
                    finally:
                        ms = int((time.monotonic() - t_start) * 1000)
                        await upstream.aclose()
                        if s is not None and not internal:
                            _commit_user_count(user_texts_all, s)  # 成功记账点推进
                            tracker.record_exchange_delta(s, new_user_texts, "".join(collected), negation_words())
                            if usage_seen:
                                tracker.record_usage(s, usage_in, usage_out)
                            tracker.record_latency(s, ms)
                        _proxy_span("proxy_span protocol=openai stream=1 agent=%s model=%s status=%s ms=%d",
                                    agent, model, upstream.status_code, ms)
                return StreamingResponse(stream_back(), status_code=upstream.status_code,
                                         media_type=upstream.headers.get("content-type", "text/event-stream"))
            resp = await _relay_post_nonstream(client, url, body, forward_headers, "openai-chat")
        except httpx.HTTPError as exc:
            # fail-open：上游不可达 → 透传错误语义
            return JSONResponse({"error": {"message": f"upstream unavailable: {exc}"}}, status_code=502)

        try:
            data = resp.json()
        except ValueError:
            # 上游可能回网关 HTML 错误页等非 JSON 体，裸解析
            # 会 500 暴栈——透传状态码 + 结构化错误（fail-open 语义不变）
            logger.warning("openai-chat 上游返回非 JSON（status=%s），已转为 502", resp.status_code)
            return JSONResponse({"error": {"message": "upstream returned non-JSON response", "upstream_status": resp.status_code}}, status_code=502)
        if s is not None and not internal and resp.status_code == 200:
            try:
                _commit_user_count(user_texts_all, s)  # 成功记账点推进
                tracker.record_exchange_delta(s, new_user_texts, _assistant_text_from_openai(data), negation_words())
                tracker.record_usage(s, *_usage_from_openai(data))
            except Exception as exc:
                logger.warning("非流式响应 session 记录失败: %s", exc)
        t_ms = int((time.monotonic() - t0) * 1000)
        if s is not None and not internal:
            tracker.record_latency(s, t_ms)
        _proxy_span("proxy_span protocol=openai stream=0 agent=%s model=%s status=%s ms=%d",
                    agent, model, resp.status_code, t_ms)
        return JSONResponse(data, status_code=resp.status_code)

    # ---------- Anthropic 原生 ----------

    @app.post("/v1/messages")
    async def anthropic_messages(request: Request) -> Any:
        body = await request.json()
        headers = {k.lower(): v for k, v in request.headers.items()}
        internal = headers.get(INTERNAL_HEADER) == "1"

        agent = detect.detect_agent(headers)
        model = body.get("model", "")
        session_id = detect.get_session_id(headers, body)
        s = tracker.get(session_id, agent, model) if not internal else None

        user_text = "\n".join(_user_texts_from_anthropic(body))

        if s is not None:
            task = detect.detect_task_context(
                [{"content": user_text}],
                store.load_config().get("seed_keywords", detect.DEFAULT_SEED_KEYWORDS),
                detect.known_categories_from_store(store),
            store=store,
            )
            s.trunk, s.category = task["trunk"], task["category"]

        block = _assemble_injection_block(store, s, user_text, agent)
        body = inject.apply_injection_anthropic(body, block)

        resolved = _resolve_upstream(store, model, body, "/messages",
                                     {"anthropic-version": "2023-06-01"})
        if resolved is None:
            return JSONResponse({"type": "error", "error": {"type": "invalid_request_error", "message": "experientia: 未配置上游模型"}}, status_code=502)
        url, forward_headers, body = resolved

        client = await get_client()
        t0 = time.monotonic()
        # 同 OpenAI 路径——先只截差不推进，成功记账点再推进
        user_texts_all = _user_texts_from_anthropic(body) if s is not None else []
        new_user_texts = _peek_user_texts(user_texts_all, s) if s is not None else []
        try:
            if body.get("stream"):
                # Anthropic 原生端点此前不支持流式，Claude Code
                # 等默认 stream:true 的客户端必 500——补 SSE 透传与增量采集
                #（对齐 OpenAI 流式路径：文本增量 + usage + 延迟落账）。
                req = client.build_request("POST", url, json=body, headers=forward_headers)
                upstream = await client.send(req, stream=True)

                async def stream_back_anthropic():
                    collected: list[str] = []
                    usage = [0, 0]  # [in, out]
                    t_start = time.monotonic()
                    try:
                        async for line in upstream.aiter_lines():
                            if line.startswith("data: "):
                                payload = line[6:].strip()
                                try:
                                    data = json.loads(payload)
                                    piece = _anthropic_sse_delta_text(data)
                                    if piece:
                                        collected.append(piece)
                                    _anthropic_sse_usage(data, usage)
                                except json.JSONDecodeError as exc:
                                    # 必留痕：SSE data 行非 JSON = 协议漂移信号，丢弃但不可静默
                                    logger.warning("Anthropic SSE data 行 JSON 解析失败（已丢弃该行）: %s", exc)
                            yield line + "\n"
                    finally:
                        ms = int((time.monotonic() - t_start) * 1000)
                        await upstream.aclose()
                        if s is not None and not internal:
                            _commit_user_count(user_texts_all, s)  # 成功记账点推进
                            tracker.record_exchange_delta(s, new_user_texts, "".join(collected), negation_words())
                            tracker.record_usage(s, usage[0], usage[1])
                            tracker.record_latency(s, ms)
                        _proxy_span("proxy_span protocol=anthropic stream=1 agent=%s model=%s status=%s ms=%d",
                                    agent, model, upstream.status_code, ms)
                return StreamingResponse(stream_back_anthropic(), status_code=upstream.status_code,
                                         media_type=upstream.headers.get("content-type", "text/event-stream"))
            resp = await _relay_post_nonstream(client, url, body, forward_headers,
                                               "anthropic-chat")
        except httpx.HTTPError as exc:
            return JSONResponse({"type": "error", "error": {"type": "api_error", "message": f"upstream unavailable: {exc}"}}, status_code=502)

        try:
            data = resp.json()
        except ValueError:
            # 非 JSON 体（网关错误页等）裸解析会 500 暴栈
            logger.warning("anthropic-chat 上游返回非 JSON（status=%s），已转为 502", resp.status_code)
            return JSONResponse({"type": "error", "error": {"type": "api_error", "message": "upstream returned non-JSON response"}}, status_code=502)
        if s is not None and not internal and resp.status_code == 200:
            try:
                _commit_user_count(user_texts_all, s)  # 成功记账点推进
                assistant = "".join(
                    p.get("text", "") for p in data.get("content", []) if isinstance(p, dict) and p.get("type") == "text"
                )
                tracker.record_exchange_delta(s, new_user_texts, assistant, negation_words())
                tracker.record_usage(s, *_usage_from_anthropic(data))
            except Exception as exc:
                logger.warning("Anthropic 非流式响应 session 记录失败: %s", exc)
        t_ms = int((time.monotonic() - t0) * 1000)
        if s is not None and not internal:
            tracker.record_latency(s, t_ms)
        _proxy_span("proxy_span protocol=anthropic agent=%s model=%s status=%s ms=%d",
                    agent, model, resp.status_code, t_ms)
        return JSONResponse(data, status_code=resp.status_code)

    app.state.tracker = tracker
    app.state.proxy_token = _proxy_token  # 生效 token（状态展示/测试取证用）
    return app


def _make_session_end_hook(store: Store):
    """延迟导入 distill，避免循环依赖（proxy → distill → proxy 不存在，但保持单向）。

    async：maybe_review_session 是 async（内部有 LLM 调用），sweeper 直接 await；
    参数 = session dict（TrackedSession.to_dict），不是 dataclass。
    """

    async def on_session_end(session_dict: dict) -> None:
        # 档 A「触发一次」：台账门控（与文件通道 run_scan 同口径）——
        # 已复盘的 session 直接跳过，防跨通道重复提炼落重复经验行
        # （LLM 措辞漂移会击穿 (agent,task,action) 精确去重）。
        agent = session_dict.get("agent")
        sid = session_dict.get("session_id")
        try:
            # 入队不再等于已复盘——只记「在飞」，由下方复盘成功后才真正标记。
            if not store.should_enqueue_review(agent, sid):
                return
            store.mark_review_queued(agent, sid)
        except Exception as exc:
            logger.warning("复盘台账门控失败（不阻断复盘）: %s", exc)
        try:
            from ..distill import review

            await review.maybe_review_session(store, session_dict)
            # 复盘跑完且没抛异常才标记——失败留着在飞标记，下轮重试
            from ..capture.scan import settle_reviewed

            settle_reviewed(store, [session_dict])
        except Exception as exc:
            logger.warning("会话复盘失败: %s", exc)

    return on_session_end

