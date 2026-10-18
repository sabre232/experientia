"""本地 API 的「hooks 配置与落地」域：读配置 / 写入 / 移除 / 生成插件。

 L4 续：从 hooks_admin.py 拆出的第三组。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..capture import hook as hook_channel
from ..store.store import Store

logger = logging.getLogger("experientia.local_api.hooks")


def build_hooks_apply_router(store: Store, hook_event_token: str) -> APIRouter:
    """hooks 配置与落地，4 个端点。"""
    router = APIRouter()
    @router.get("/api/hooks/config")
    def hooks_config():
        # 带 store → hook_status 附带 observed（收到真实 hook 事件的时刻），GUI 据此
        # 区分「已写入配置 / 已生效」（memorax 借鉴 A2 installed→observed）
        return hook_channel.hook_status(store=store)

    @router.post("/api/hooks/apply")
    def hooks_apply():
        try:
            return hook_channel.apply_hook_config(key=hook_event_token)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"写入 settings.json 失败：{exc}")

    @router.post("/api/hooks/remove")
    def hooks_remove():
        return hook_channel.remove_hook_config()

    @router.post("/api/hooks/plugin/generate")
    def hooks_plugin_generate():
        """C-2a：生成 Claude 官方插件包（取代改全局 settings.json 的安装形态）。

        落盘到 <data_dir>/exports/claude-plugin；返回路径与官方安装命令提示
        （`claude plugin install <dir>`，scope 与确认由用户在终端完成——引擎不代跑）。
        """
        from ..capture import hook_plugin as hp

        root = hp.write_plugin_package(store.data_dir / "exports" / "claude-plugin",
                                       key=hook_event_token)
        return {"dir": str(root), "install_hint": f'claude plugin install "{root}"'}

    return router
