"""模型调用（蒸馏/复盘/AI 优化统一走这里，"用当前接入模型跑"）。

直接调上游 endpoint，不经 8100 代理（自引用防护的等价实现，：
内部调用只转发不记录不注入——这里干脆不进代理）。

路由：
- 代理主路由 = `default_model`（models 表里的路由名）
- 蒸馏路由 = `distill_model`（可选，同样是 models 表里的路由名）——
  允许"agent 干活走本地模型、蒸馏/复盘走云端 API"（或反过来）。
  未配置时回退 default_model，行为与旧版一致。
- 每次调用还可显式传 route_name 覆盖（GUI 逐次选择用，预留）。

协议：type=local/cloud 走 OpenAI 兼容 /chat/completions；
type=anthropic 走 /v1/messages（x-api-key + anthropic-version 头）。
API Key 走 keyring（服务名 "experientia"，条目名 = key_ref），不落 config。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

from ..net_util import DIRECT_LOOPBACK
from ..store.store import Store

logger = logging.getLogger(__name__)

# 后台事件循环复用（B-09：避免每次 call_model 创建/销毁新循环）
_background_loop: asyncio.AbstractEventLoop | None = None

# 本地模型生成慢（27B 级单次蒸馏可达 10 分钟+），放宽到 30 分钟；云端保持 10 分钟
_LOCAL_TIMEOUT = httpx.Timeout(1800.0, connect=10.0)
_CLOUD_TIMEOUT = httpx.Timeout(600.0, connect=10.0)

# REL-1：LLM 调用重试预算——瞬时错误/429/5xx 最多 3 次尝试，指数退避 2/4s（封顶 8s）。
# 蒸馏/复盘是后台任务，可接受有界延迟；宁可降级也不无限阻塞（报告权衡 3）。
_LLM_MAX_ATTEMPTS = 3
_LLM_RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}

# ---------- 轻量熔断器（M3 内存/可用性预算：三态，Martin Fowler 范式） ----------
# closed（正常）→ 连续 N 次失败/超时 → open（冷却期内跳过模型、直接走无模型
# fallback 或跳过本轮蒸馏，不空等）→ 冷却到期 half-open（放一次试探调用，
# 成功回 closed、失败重开并延长冷却）。
# 调用级超时解决"单次挂死"，熔断解决"反复失败别空耗"：单 worker 下一次挂死
# 即全停（daemon 注释"最长 30 分钟"）；熔断把"对一个不会应答的依赖反复锤击、
# 浪费 30 分钟×N"变成"快速降级 + 定时试探"。
# 状态存 config（notify_state 同处），跨重启保留。
CB_FAILURE_THRESHOLD = 3        # 连续失败 N 次 → open
CB_COOLDOWN_SECONDS = 300       # 初始冷却（秒）
CB_COOLDOWN_MAX_SECONDS = 1800  # 重开延长上限


class EmptyResponseError(RuntimeError):
    """上游 200 但 assistant 内容为空——**这算失败**，不算成功。

    真机踩坑：本地小模型对 1 万字蒸馏提示词回了空字符串，
    旧代码原样返回 ""，distill 把 parse_playbook("") 得到的三节"（无）"
    当成功写盘、还升 version 标 confidence: high → playbook 被清空、
    注入块永远为空、飞轮第④格恒 0，而所有日志都说"蒸馏成功"。"""


class CircuitOpenError(RuntimeError):
    """模型熔断 open：跳过本次调用（调用方降级无模型 fallback / 跳过本轮）。"""


def _breaker_state(config: dict) -> dict:
    st = config.get("model_breaker") or {}
    if not isinstance(st, dict):
        st = {}
    return {
        "state": st.get("state") or "closed",
        "fail_count": int(st.get("fail_count") or 0),
        "cooldown": float(st.get("cooldown") or CB_COOLDOWN_SECONDS),
        "opened_at": float(st.get("opened_at") or 0),
    }


def _breaker_read(store: Store) -> dict:
    return _breaker_state(store.load_config())


def circuit_open(store: Store) -> bool:
    """纯检查（调用方据此直接走无模型 fallback，不空等）：open 且冷却期未过。"""
    st = _breaker_read(store)
    return st["state"] == "open" and (time.time() - st["opened_at"]) < st["cooldown"]


def _breaker_allow(store: Store) -> None:
    """调用入口：open 且冷却期未过 → CircuitOpenError；冷却到期 → half-open 放试探。

    判定与写回同在 store.mutate_config 写锁内完成——
    此前无锁「读-改-写」与设置页保存 config.json 并发时互相覆盖。"""

    def _transact(config: dict) -> dict | None:
        st = _breaker_state(config)
        if st["state"] != "open":
            return None  # closed/half_open：放行且不动状态
        if (time.time() - st["opened_at"]) < st["cooldown"]:
            raise CircuitOpenError(
                f"模型熔断 open，冷却 {st['cooldown']:.0f}s 未过（{st['fail_count']} 次连续失败）")
        config["model_breaker"] = {**st, "state": "half_open"}
        return config

    store.mutate_config(_transact)


def _breaker_record(store: Store, ok: bool) -> None:
    """调用结果记账：成功 → closed 清零；失败 → 累计，达阈/试探失败 → open。

    首开用初始冷却；重开（half-open 试探失败）冷却翻倍（封顶）。
    读-改-写同在 mutate_config 写锁内，并发调用不再互相踩状态。
    每次失败都落盘：计数跨进程（daemon 重启不清零），不持久化则
    每次重读都归零，阈值永远到不了。"""

    def _transact(config: dict) -> dict | None:
        st = _breaker_state(config)
        if ok:
            if st["state"] != "closed" or st["fail_count"]:
                config["model_breaker"] = {"state": "closed", "fail_count": 0,
                                           "cooldown": CB_COOLDOWN_SECONDS,
                                           "opened_at": 0}
                return config
            return None  # 已 closed 且零计数：成功热路径不写盘
        was_half_open = st["state"] == "half_open"
        st["fail_count"] += 1
        if st["fail_count"] >= CB_FAILURE_THRESHOLD or was_half_open:
            st["state"] = "open"
            st["opened_at"] = time.time()
            if was_half_open:
                st["cooldown"] = min(st["cooldown"] * 2, CB_COOLDOWN_MAX_SECONDS)
        config["model_breaker"] = st
        return config

    store.mutate_config(_transact)

ANTHROPIC_VERSION = "2023-06-01"
# keyring service 与本地 API token 共用同一 "experientia" 域（唯一来源在 token_util）
from ..token_util import TOKEN_KEYRING_SERVICE as KEYRING_SERVICE  # noqa: E402
from .. import token_util  # noqa: E402


# 遗留：明文 api_key 兜底的弃用告警（每路由每进程只告一次，防刷屏）
_PLAINTEXT_KEY_WARNED: set[str] = set()


def _resolve_key(route: dict) -> str | None:
    """keyring（key_ref）优先，config 兜底次之（DPAPI 加密 api_key_enc，
    或旧明文 api_key）。见 token_util.resolve_fallback_secret。"""
    key_ref = route.get("key_ref")
    if key_ref:
        try:
            import keyring

            key = keyring.get_password(KEYRING_SERVICE, key_ref)
            if key:
                return key
        except Exception:
            import logging as _log
            _log.getLogger("experientia.distill.llm").warning(
                "keyring 不可用，退回 config 兜底密钥")
    key = token_util.resolve_fallback_secret(route)
    if route.get("api_key"):  # 仅旧明文（非 DPAPI 加密）才提示弃用
        name = str(route.get("route_name") or route.get("model") or "?")
        if name not in _PLAINTEXT_KEY_WARNED:
            _PLAINTEXT_KEY_WARNED.add(name)
            logger.warning("路由 %s 使用 config.json 明文 api_key（已弃用），"
                           "建议改用 key_ref + keyring", name)
    return key


def default_route(store: Store) -> dict | None:
    config = store.load_config()
    routes = config.get("models", {}) or {}
    name = config.get("default_model")
    if name in routes:
        return {"route_name": name, **routes[name]}
    if routes:
        first = next(iter(routes))
        # 回退必留痕（default_model 未配置/拼写漂移 → 静默回退
        # 会让蒸馏流量打到非预期路由）
        logger.warning("default_model=%r 未命中路由表，回退到首个路由 %r", name, first)
        return {"route_name": first, **routes[first]}
    return None


def distill_route(store: Store, route_name: str | None = None) -> dict | None:
    """蒸馏/复盘路由：显式 route_name > distill_model 配置 > default_model 回退链。"""
    config = store.load_config()
    routes = config.get("models", {}) or {}
    for name in (route_name, config.get("distill_model"), config.get("default_model")):
        if name and name in routes:
            return {"route_name": name, **routes[name]}
    if routes:
        first = next(iter(routes))
        # 整条回退链（route_name/distill_model/default_model）
        # 都未命中才落到首个路由——必留痕，含请求的 route_name 与回退目标
        logger.warning("蒸馏路由回退：route_name=%r / distill_model=%r / default_model=%r "
                       "均未命中路由表，回退到首个路由 %r",
                       route_name, config.get("distill_model"),
                       config.get("default_model"), first)
        return {"route_name": first, **routes[first]}
    return None


def model_available(store: Store, route_name: str | None = None) -> bool:
    """模型是否可用：有路由 + endpoint 非空（蒸馏兜底方案统一 switcher）。

    不试连——试连了也是同一条命；只挡"压根没配"的最快路径，
    "配了但调不通"由调用方的 try/except 回落兜住（两条都要接）。

    这是**配置维度**的判定（有没有端点），给"要调模型、自己有 try/except 兜底"
    的调用方用；展示层要区分"没配"与"配了连不上"请用 ``model_state``。
    """
    route = distill_route(store, route_name)
    return bool(route and route.get("endpoint"))


# 模型接入三态（展示层降级用，结算卡）
MODEL_STATE_AVAILABLE = "available"        # 已配置、最近可用
MODEL_STATE_UNCONFIGURED = "unconfigured"  # 压根没配 → 引导去接入
MODEL_STATE_UNREACHABLE = "unreachable"    # 配了但最近连不上 → 引导去检查


def model_endpoint(store: Store, route_name: str | None = None) -> str:
    """当前蒸馏路由的端点串（无路由 → 空串）。

    "连不上"的文案要点名是哪个端点（"检查 127.0.0.1:8080 是不是没开"——写死
    本机地址对云端 API 用户是句假话），所以端点单独取，不塞进状态值里。"""
    route = distill_route(store, route_name)
    return str((route or {}).get("endpoint") or "").strip()


def model_state(store: Store, route_name: str | None = None) -> str:
    """模型接入三态：未配置 / 配了连不上 / 可用。

    为什么布尔不够：`model_available=False` 把"压根没配"和"配了但连不上"压成
    同一个值，用户拿到同一句空话，既不知道自己属于哪一种，也不知道下一步该干
    什么。Apple 对 AI 不可用给了四个独立状态，官方口径是"没开启"引导去开、
    "模型未就绪"等待重试，不一律降级。

    "连不上"**不试连**：试连要真发一次补全（``models_service.check_route`` 那样，
    30s 超时），而周日结算在 daemon 里跑、结算卡每次打开都跑一遍，太重。改用
    **熔断 open** 当证据——连续 ``CB_FAILURE_THRESHOLD`` 次真实调用失败才开，
    零网络、有据可查、跨重启保留；没跑过调用就没证据，按"已配置可用"处理
    （宁可少提示，不误报故障）。
    """
    if not model_endpoint(store, route_name):
        return MODEL_STATE_UNCONFIGURED
    if circuit_open(store):
        return MODEL_STATE_UNREACHABLE
    return MODEL_STATE_AVAILABLE


def _is_anthropic(route: dict) -> bool:
    return (route.get("type") or "").lower() == "anthropic"


def _headers(route: dict) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if _is_anthropic(route):
        key = _resolve_key(route)
        if key:
            headers["x-api-key"] = key
        headers["anthropic-version"] = ANTHROPIC_VERSION
        return headers
    key = _resolve_key(route)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _chat_url(route: dict) -> str:
    """OpenAI 兼容 /chat/completions 端点。"""
    base = (route.get("endpoint") or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1") or "/v1" in base:
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _anthropic_url(route: dict) -> str:
    base = (route.get("endpoint") or "").rstrip("/")
    if base.endswith("/messages"):
        return base
    if base.endswith("/v1"):
        return base + "/messages"
    return base + "/v1/messages"


def _to_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Anthropic 不接受 messages 里的 system 角色，抽出来放 body.system。"""
    system_parts: list[str] = []
    msgs: list[dict] = []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(m.get("content") or "")
        else:
            msgs.append(m)
    return "\n\n".join(system_parts), msgs


async def call_model_async(
    store: Store,
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 4096,
    route_name: str | None = None,
) -> str:
    """单次 chat completion，返回 assistant 文本。失败抛异常（调用方决定降级）。

    REL-1：瞬时网络错 / 429 / 5xx 指数退避重试（上限 _LLM_MAX_ATTEMPTS 次）；
    OBS-1：成功与最终失败都留 `llm_span` 结构化日志（route/attempts/ms/status）；
    M3：外层套轻量熔断器——open 冷却期内抛 CircuitOpenError（调用方降级，
    不空等挂死的端点），成功/最终失败记账。
    """
    route = distill_route(store, route_name)
    if route is None or not route.get("endpoint"):
        raise RuntimeError(
            "experientia: 未配置模型（config.json models + default_model / distill_model）"
        )
    _breaker_allow(store)
    try:
        text = await _call_model_async_impl(
            store, messages, temperature, max_tokens, route_name)
        if not (text or "").strip():
            raise EmptyResponseError(
                f"experientia: 模型返回空内容（route={route_name or '默认'}）")
    except Exception:
        _breaker_record(store, False)
        raise
    _breaker_record(store, True)
    return text


async def _call_model_async_impl(
    store: Store,
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 4096,
    route_name: str | None = None,
) -> str:
    """call_model_async 的实际 HTTP 调用体（熔断记账在外层包装）。"""
    route = distill_route(store, route_name)
    timeout = _LOCAL_TIMEOUT if (route.get("type") or "").lower() == "local" else _CLOUD_TIMEOUT
    t0 = time.monotonic()
    # 仅本地（local）路由跟随重定向。httpx 的
    # follow_redirects 会用**原样 headers** 重放 POST——云端端点被攻破/CDN
    # 返回 3xx 到外部域时，Authorization / x-api-key 会随之外泄。
    follow = (route.get("type") or "").lower() == "local"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=follow,
                                 mounts=DIRECT_LOOPBACK) as client:
        attempts = 0

        async def _post(url: str, body: dict, headers: dict) -> httpx.Response:
            """带重试的 POST：瞬时错 / 429 / 5xx 退避后重试。"""
            nonlocal attempts
            for attempt in range(1, _LLM_MAX_ATTEMPTS + 1):
                attempts = attempt
                try:
                    resp = await client.post(url, json=body, headers=headers)
                except httpx.HTTPError as exc:
                    if attempt == _LLM_MAX_ATTEMPTS:
                        raise
                    logger.warning("llm 调用瞬时错误（attempt %d/%d）: %s",
                                   attempt, _LLM_MAX_ATTEMPTS, exc)
                    await asyncio.sleep(min(2 ** attempt, 8))
                    continue
                if resp.status_code in _LLM_RETRYABLE_CODES and attempt < _LLM_MAX_ATTEMPTS:
                    logger.warning("llm 上游 %s（attempt %d/%d，退避重试）",
                                   resp.status_code, attempt, _LLM_MAX_ATTEMPTS)
                    await asyncio.sleep(min(2 ** attempt, 8))
                    continue
                return resp
            raise RuntimeError("unreachable")

        if _is_anthropic(route):
            system, msgs = _to_anthropic_messages(messages)
            body: dict = {
                "model": route.get("model") or route["route_name"],
                "max_tokens": max_tokens or 4096,
                "temperature": temperature,
                "messages": msgs,
            }
            if system:
                body["system"] = system
            resp = await _post(_anthropic_url(route), body, _headers(route))
            if resp.status_code != 200:
                # M-N4: 错误响应脱敏——不暴露上游响应正文；但写日志方便调试
                logger.warning("Anthropic call failed (%s): %.200s",
                               resp.status_code, resp.text)
                raise RuntimeError(f"model call failed ({resp.status_code})")
            data = resp.json()
            text = "".join(
                block.get("text", "") for block in data.get("content") or []
                if isinstance(block, dict) and block.get("type") == "text"
            )
            logger.info(
                "llm_span protocol=anthropic route=%s attempts=%d ms=%d status=200 chars=%d",
                route.get("route_name"), attempts, int((time.monotonic() - t0) * 1000),
                len(text))
            return text
        body = {
            "model": route.get("model") or route["route_name"],
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        resp = await _post(_chat_url(route), body, _headers(route))
    if resp.status_code != 200:
        # M-N4: 错误响应脱敏
        logger.warning("OpenAI-compatible call failed (%s): %.200s",
                       resp.status_code, resp.text)
        raise RuntimeError(f"model call failed ({resp.status_code})")
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"model call returned no choices: {str(data)[:300]}")
    text = (choices[0].get("message") or {}).get("content") or ""
    logger.info(
        "llm_span protocol=openai route=%s attempts=%d ms=%d status=200 chars=%d",
        route.get("route_name"), attempts, int((time.monotonic() - t0) * 1000),
        len(text))
    return text


def call_model(store: Store, messages: list[dict], **kw) -> str:
    """同步包装（GUI 按钮线程 / 测试用）。
    
    M-N8: 兼容已有运行中事件循环——asyncio.run() 在已有事件循环中
    会抛出 RuntimeError。使用模块级 _background_loop 避免每次创建/销毁。"""
    global _background_loop
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(call_model_async(store, messages, **kw))
    # 已有运行中事件循环 → 复用模块级后台循环
    if _background_loop is None or _background_loop.is_closed():
        _background_loop = asyncio.new_event_loop()
    return _background_loop.run_until_complete(call_model_async(store, messages, **kw))


def _repair_truncated_array(s: str):
    """把被 max_tokens 截断的 JSON 数组修复为"仅含完整元素"的可解析串。

    只保留截断点之前**完整闭合**的顶层元素（半截对象直接丢弃，绝不收进
    经验库污染资产）；无完整元素时返回 None。业界 json_repair 同思路，
    此处内联实现守项目"零第三方依赖 + exe 打包脆弱"铁律（MiniBM25/
    search_index 先例）。"""
    if not s or s[0] != "[":
        return None
    stack: list[str] = []
    in_str = esc = False
    last_complete = -1  # 顶层数组里"上一个元素完整结束"的切点
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            stack.append(ch)
        elif ch in "]}":
            if not stack:
                return None
            stack.pop()
            if not stack:
                return s[:i + 1]  # 本就完整闭合
            if len(stack) == 1:  # 刚收尾一个顶层数组元素
                last_complete = i + 1
    if last_complete > 0:
        return s[:last_complete].rstrip().rstrip(",") + "]"
    return None


def extract_json(text: str) -> dict | list:
    """从模型输出里提取 JSON（容忍 ```json 围栏、前后废话、max_tokens 截断）。

    先找第一段括号平衡的完整 JSON；解析不了再对截断数组做修复（只保留
    完整元素）。仍失败抛 ValueError——调用方据此降级/重试，绝不静默产垃圾。"""
    text = text.strip()
    if not text:
        raise ValueError("empty model output")
    # 去掉 ```json / ``` 围栏
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    # 找第一个 [ 或 { 并校验括号匹配
    start = -1
    depth = 0
    for i, ch in enumerate(text):
        if ch in ("[", "{"):
            if start < 0:
                start = i
            depth += 1
        elif ch in ("]", "}"):
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = -1  # 括号匹配但解析失败，继续找下一段
    if start < 0:
        raise ValueError(f"no JSON found in model output: {text[:200]}")
    # 截断兜底：数组被 max_tokens 砍断 → 修复到最后一个完整元素再解析
    repaired = _repair_truncated_array(text[start:])
    if repaired is not None:
        try:
            obj = json.loads(repaired)
            if isinstance(obj, list) and obj:
                return obj
        except json.JSONDecodeError:
            pass
    return json.loads(text[start:])
