"""模型路由管理（CLI / 本地 API / GUI 共用）。

API Key 存系统钥匙串（service "experientia"），config 只存 key_ref。
所有写操作返回 (ok, message)；读操作返回结构化 dict。
"""

from __future__ import annotations

import logging

from . import token_util
from .distill import llm
from .store.store import Store

logger = logging.getLogger("experientia.models")


def _routes(config: dict) -> dict:
    return config.get("models", {}) or {}


def list_routes(store: Store) -> dict:
    config = store.load_config()
    routes = _routes(config)
    out = []
    for name, r in routes.items():
        out.append({
            "name": name,
            "type": r.get("type", "cloud"),
            "endpoint": r.get("endpoint"),
            "model": r.get("model"),
            "key_source": ("keyring" if r.get("key_ref")
                           else "encrypted" if r.get("api_key_enc")
                           else "plaintext" if r.get("api_key")
                           else "none"),
            "is_default": name == config.get("default_model"),
            "is_distill": name == config.get("distill_model"),
        })
    return {
        "routes": out,
        "default_model": config.get("default_model"),
        "distill_model": config.get("distill_model"),
    }


def add_route(store: Store, name: str, endpoint: str, model: str,
              rtype: str = "cloud", key: str | None = None) -> tuple[bool, str]:
    if rtype not in ("local", "cloud", "anthropic"):
        return False, "type 必须是 local / cloud / anthropic"
    if not name or not endpoint or not model:
        return False, "name / endpoint / model 均必填"
    config = store.load_config()
    routes = _routes(config)
    if name in routes:
        return False, f"模型 '{name}' 已存在，先删除再重新添加"
    route: dict = {"type": rtype, "endpoint": endpoint, "model": model}
    keyring_error = None
    fallback_encrypted = False
    if key:
        try:
            import keyring

            keyring.set_password(llm.KEYRING_SERVICE, name, key)
        except Exception as exc:
            # 低6/SEC-1/M12：keyring 失败（未安装 / headless 无凭据管理器）→ 兜底存 config
            # 以保功能可用，但必留痕 + 返回信息明示（绝不静默）。Windows 上 0600 无效，
            # 兜底值经 DPAPI（当前用户域）加密后存 api_key_enc；POSIX 才落明文 api_key
            # （0600 有效）。该兜底被 test_cli_model_add_keyring_failure_falls_back 钉死。
            fields = token_util.protect_fallback_secret(key)
            route.update(fields)
            fallback_encrypted = token_util.FALLBACK_ENC_FIELD in fields
            keyring_error = str(exc)
            if fallback_encrypted:
                logger.warning("keyring 写入失败，API Key 已 DPAPI 加密后兜底存 config.json: %s", exc)
            else:
                logger.warning("keyring 写入失败，API Key 明文兜底 config.json（已 0600）: %s", exc)
        else:
            route["key_ref"] = name
    # 只有 config 的读-改-写进写锁；keyring/DPAPI 的 I/O
    # 留在锁外（锁内做系统调用会拖长持锁时间，阻塞扫描/代理线程的记账）。
    def _apply(config: dict) -> dict:
        now = _routes(config)
        now[name] = route
        config["models"] = now
        return config

    store.mutate_config(_apply)
    base = f"已添加模型: {name} (type={rtype}, endpoint={endpoint}, model={model})"
    if keyring_error is not None:
        where = ("已 DPAPI 加密后存入 config.json（仅本机当前用户可读回）"
                 if fallback_encrypted else "已明文存入 config.json")
        base += f"；注意：系统钥匙串不可用（{keyring_error}），API Key {where}"
    return True, base


def set_route(store: Store, name: str, which: str) -> tuple[bool, str]:
    """which: "default"（代理主路由）| "distill"（蒸馏/复盘专用）。"""
    if which not in ("default", "distill"):
        return False, "which 必须是 default / distill"
    config = store.load_config()
    if name not in _routes(config):
        return False, f"模型 '{name}' 不存在"

    # 写走 mutate_config；锁内再查一次，防并发删路由后
    # 写入悬空 default_model/distill_model。
    field = "default_model" if which == "default" else "distill_model"

    def _apply(cfg: dict) -> dict | None:
        if name not in _routes(cfg):
            return None
        cfg[field] = name
        return cfg

    store.mutate_config(_apply)
    label = "默认模型" if which == "default" else "蒸馏模型"
    return True, f"已设置{label}: {name}"


def check_route(store: Store) -> tuple[bool, str]:
    """接入自检（W1-08）：对默认路由发一次 1-token 最小补全。

    用真实补全而非 GET /models——很多上游的 /models 不需要鉴权，
    空 key 也能过，自检会失真。失败信息给可操作的下一步。
    """
    config = store.load_config()
    routes = _routes(config)
    if not routes:
        return False, "还没有配置模型"
    name = config.get("default_model")
    if name not in routes:
        name = next(iter(routes))
    route = routes[name]
    if not (route.get("endpoint") or "").rstrip("/"):
        return False, f"模型「{name}」没有端点"
    # URL 归一化与鉴权头复用 llm 单一实现——此前 check_route 自己拼
    # endpoint + "/chat/completions"，endpoint 已带 /v1 或 /chat/completions 时
    # 与真实调用路径不一致，自检报"端点路径不存在"但代理实际能通（误导改配置）
    is_anthropic = llm._is_anthropic(route)
    url = llm._anthropic_url(route) if is_anthropic else llm._chat_url(route)
    headers = llm._headers(route)
    payload = {"model": route.get("model"), "max_tokens": 1,
               "messages": [{"role": "user", "content": "hi"}]}
    try:
        import httpx

        from app.net_util import DIRECT_LOOPBACK

        # 端点可能是本机的 llama-server / LM Studio（127.0.0.1），这类必须绕过
        # 系统代理；云端端点不在 DIRECT_LOOPBACK 里，仍然尊重用户配的代理。
        # （mounts 只有 Client 构造函数认，顶层 httpx.post() 传它会 TypeError）
        with httpx.Client(mounts=DIRECT_LOOPBACK, timeout=30.0) as cli:
            resp = cli.post(url, json=payload, headers=headers)
    except Exception as exc:
        return False, f"连不上这个端点（{type(exc).__name__}）"
    if resp.status_code == 200:
        return True, "接入正常"
    if resp.status_code in (401, 403):
        return False, "密钥被拒绝——检查密钥是否有效"
    if resp.status_code == 404:
        return False, "端点路径不存在——检查端点地址"
    return False, f"上游返回 {resp.status_code}"


def remove_route(store: Store, name: str) -> tuple[bool, str]:
    config = store.load_config()
    if name not in _routes(config):
        return False, f"模型 '{name}' 不存在"

    # 配置读-改-写进写锁；keyring 清理留在锁外
    def _apply(cfg: dict) -> dict | None:
        routes = _routes(cfg)
        if name not in routes:
            return None
        del routes[name]
        cfg["models"] = routes
        if cfg.get("default_model") == name:
            cfg.pop("default_model", None)
        if cfg.get("distill_model") == name:
            cfg.pop("distill_model", None)
        return cfg

    store.mutate_config(_apply)
    try:
        import keyring

        keyring.delete_password(llm.KEYRING_SERVICE, name)
    except Exception:
        pass
    return True, f"已删除模型: {name}"
