"""本地 API 的「接入与上报」资源域（**组合层**）。

 L4 续：原 `build_ingest_router` 是 265 行的单函数、塞了 19 个
端点。按职责切成三个子域，本模块只做组合：

| 模块 | 职责 | 端点 |
|---|---|---|
| `ingest_hooks.py` | hook 事件通道（Claude Code + hermes/cursor/windsurf） | 7 |
| `ingest_probe.py` | probe 自报与上报码管理 | 9 |
| `ingest_drafts.py` | 经验草稿 | 3 |

对外仍是 `build_ingest_router(store, hook_event_token)`，`create_local_app`
的调用方式不变（仍是一条 `include_router`）。

⚠️ `hook_event_token`（hook 事件通道防伪令牌，每个 app 实例一份）由
`create_local_app` 注入后透传给 `ingest_probe`，子域一律不去 `local_api` 里取
（会循环导入）。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..store.store import Store
from .ingest_drafts import build_drafts_router
from .ingest_hooks import build_hooks_router
from .ingest_probe import build_probe_router


def build_ingest_router(store: Store, hook_event_token: str) -> APIRouter:
    """挂载 hook 事件通道 + probe + 草稿，共 19 个端点。"""
    router = APIRouter()
    router.include_router(build_hooks_router(store))
    router.include_router(build_probe_router(store, hook_event_token))
    router.include_router(build_drafts_router(store))
    return router
