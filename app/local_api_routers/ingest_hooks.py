"""本地 API 的「hook 事件通道」域（通道 3，Claude Code 首发）。

 L4 续：原 `build_ingest_router` 265 行塞了 19 个端点，按职责
切成三组，本模块是 hook 事件通道——Claude Code 的 SessionStart /
UserPromptSubmit / PostToolUse / Stop 四个 hook，加 hermes / cursor /
windsurf 三个事件端点。

fail-open 语义：任何异常都返回空 dict（curl 退出码 0），绝不阻塞用户的
agent；但**必须留痕**（logger.exception），否则真出问题无从追查。

范式同 models.py：只依赖 store 与产品层、暴露工厂、不反向 import
`app.local_api`。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ..capture import hook as hook_channel
from ..store.store import Store

logger = logging.getLogger("experientia.local_api.ingest")


def build_hooks_router(store: Store) -> APIRouter:
    """hook 事件通道，7 个端点。"""
    router = APIRouter()
    # ---------- Hook 通道（通道 3，Claude Code 首发） ----------
    # 供 Claude Code 的 SessionStart / UserPromptSubmit / PostToolUse / Stop
    # hook（curl 管道）调用。fail-open：任何异常都返回空 dict（curl 退出码 0），
    # 绝不阻塞用户的 agent；Stop 的复盘写经验在独立 worker 里跑，不等 LLM。

    @router.post("/api/hooks/session-start")
    def hooks_session_start(payload: dict = None):
        try:
            return hook_channel.handle_session_start(store, payload or {})
        except Exception:
            logger.exception("hook session-start 处理失败（fail-open）")
            return {}

    @router.post("/api/hooks/user-prompt-submit")
    def hooks_user_prompt_submit(payload: dict = None):
        try:
            return hook_channel.handle_user_prompt_submit(store, payload or {})
        except Exception:
            logger.exception("hook user-prompt-submit 处理失败（fail-open）")
            return {}

    @router.post("/api/hooks/post-tool-use")
    def hooks_post_tool_use(payload: dict = None):
        try:
            return hook_channel.handle_post_tool_use(store, payload or {})
        except Exception:
            logger.exception("hook post-tool-use 处理失败（fail-open）")
            return {}

    @router.post("/api/hooks/stop")
    def hooks_stop(payload: dict = None):
        try:
            return hook_channel.handle_stop(store, payload or {})
        except Exception:
            logger.exception("hook stop 处理失败（fail-open）")
            return {}

    @router.post("/api/hooks/hermes-event")
    def hermes_hook_event(payload: dict = None):
        from ..capture import hermes_hook as hermes_ch
        try:
            return hermes_ch.handle_hermes_event(store, payload or {})
        except Exception:
            logger.exception("hermes hook 事件处理失败（fail-open）")
            return {}

    @router.post("/api/hooks/cursor-event")
    def cursor_hook_event(payload: dict = None):
        from ..capture import ide_hooks as ide_ch
        try:
            return ide_ch.handle_ide_event(store, "cursor", payload or {})
        except Exception:
            logger.exception("cursor hook 事件处理失败（fail-open）")
            return {}

    @router.post("/api/hooks/windsurf-event")
    def windsurf_hook_event(payload: dict = None):
        from ..capture import ide_hooks as ide_ch
        try:
            return ide_ch.handle_ide_event(store, "windsurf", payload or {})
        except Exception:
            logger.exception("windsurf hook 事件处理失败（fail-open）")
            return {}

    return router
