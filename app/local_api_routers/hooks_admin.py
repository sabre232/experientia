"""本地 API 的「hooks 管理」资源域（**组合层**）。

 L4 续：原 `build_hooks_admin_router` 是 169 行的单函数、塞了 15 个
端点。按职责切成三组，本模块只做组合：

| 模块 | 职责 | 端点 |
|---|---|---|
| `hooks_admin_query.py` | 总览 / 单 agent 说明 / 单 agent 详情 | 3 |
| `hooks_admin_ops.py` | 安装 / 移除 / 启停 / 增删 | 8 |
| `hooks_apply.py` | 读配置 / 写入 / 移除 / 生成插件 | 4 |

对外仍是 `build_hooks_admin_router(store)`，`create_local_app` 的调用方式不变
（仍是一条 `include_router`）。

⚠️ **保序**：`/api/hooks/admin/{agent}` 是通配路径，必须排在 `overview` /
`explain` 之后，否则会把它们吃掉——不报错，只表现为一直 404。`include_router`
的顺序即注册顺序，故**查询组必须最先挂载**，且 `{agent}` 与 overview / explain
刻意留在同一模块内以固定相对顺序。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..store.store import Store
from .hooks_admin_ops import build_hooks_admin_ops_router
from .hooks_admin_query import build_hooks_admin_query_router
from .hooks_apply import build_hooks_apply_router


def build_hooks_admin_router(store: Store, hook_event_token: str) -> APIRouter:
    """挂载 hooks 管理，共 15 个端点（查询组最先，含通配 {agent} 的保序要求）。

    `hook_event_token` 由 `create_local_app` 注入（每 app 实例一份的防伪令牌），
    透传给 ops（install / install-all 写 hook 配置）与 apply（apply / plugin
    generate）两组；查询组不需要。
    """
    router = APIRouter()
    router.include_router(build_hooks_admin_query_router(store))
    router.include_router(build_hooks_admin_ops_router(store, hook_event_token))
    router.include_router(build_hooks_apply_router(store, hook_event_token))
    return router
