"""本地 API 的「应用运维 + 通知中心」资源域。

覆盖 `/api/autostart`、`/api/data-dir/migrate`、`/api/app/relaunch`、
`/api/notifications`、`/api/notifications/read` 共 5 个端点。

从 `create_local_app()` 拆出的第十三个资源域，范式同 models.py
（只依赖 store 与产品层、暴露 `build_xxx_router(store)` 工厂、不反向 import
`app.local_api`）。本域用到 `_autostart_enabled()`，随域一同搬走。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import notify
from ..platform import autostart
from ..store.store import Store


class AutoStartIn(BaseModel):
    enabled: bool


class DataDirMigrateIn(BaseModel):
    target: str
    # 目标在用户主目录之外时必须显式确认才迁（防移动盘
    # 拔盘后"经验全没了"）。GUI 本地镜像判据拼提示文案后带 true 重试。
    confirm_outside_home: bool = False


class ReadIn(BaseModel):
    ids: list[str] | None = None


def _autostart_enabled() -> bool:
    try:
        return autostart.is_enabled()
    except Exception:
        return False


def build_app_ops_router(store: Store) -> APIRouter:
    """挂载自启/数据目录迁移/重启 + 通知中心，共 5 个端点。"""
    router = APIRouter()

    # ---------- 开机自启 ----------

    @router.post("/api/autostart")
    def autostart_set(body: AutoStartIn):
        try:
            if body.enabled:
                autostart.enable()
            else:
                autostart.disable()
        except Exception as exc:  # subprocess/平台工具缺失等一律 400 提示
            raise HTTPException(status_code=400, detail=f"自启设置失败：{exc}")
        # 读-改-写走 mutate_config（持写锁，防并发丢字段）
        def _apply(config: dict) -> dict:
            config["autostart"] = body.enabled
            return config

        store.mutate_config(_apply)
        return {"enabled": body.enabled, "registered": _autostart_enabled()}

    # ---------- 数据目录 ----------

    @router.post("/api/data-dir/migrate")
    def data_dir_migrate(body: DataDirMigrateIn):
        """整体搬迁现有数据到 target（复制→校验→留指针；旧目录冷启动清理）。

        迁移后引擎内存中的 Store 仍指旧目录——需重启生效（GUI 提示 + 重启）。
        """
        try:
            return store.migrate_data_dir(
                body.target, confirm_outside_home=body.confirm_outside_home)
        except ValueError as exc:
            # OutsideHomeConfirmRequired 继承 ValueError，走同一分支转 400 +
            # 可读文案（GUI/CLI 都能直接展示）
            raise HTTPException(status_code=400, detail=str(exc))
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=f"迁移失败：{exc}")

    @router.post("/api/app/relaunch")
    def app_relaunch():
        """重启应用：分离 helper 等本进程退出后
        拉起新实例（新实例须等旧进程释放数据目录锁与 8101，否则被单实例
        检查拒绝）。"""
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--relaunch-helper", str(os.getpid())]
        else:
            entry = Path(sys.argv[0]).resolve() if sys.argv else None
            if entry is None or entry.suffix != ".py":
                raise HTTPException(
                    status_code=400, detail="无法确定启动入口（开发模式需经 main.py 启动）")
            cmd = [sys.executable, str(entry), "--relaunch-helper", str(os.getpid())]
        try:
            if os.name == "nt":
                subprocess.Popen(
                    cmd,
                    creationflags=(subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP))
            else:
                subprocess.Popen(cmd, start_new_session=True)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"重启失败：{exc}")
        return {"ok": True}

    # ---------- 通知中心 ----------

    @router.get("/api/notifications")
    def notifications_list(unread: bool = False, limit: int = 50):
        return {"items": notify.list_notifications(store, unread_only=unread,
                                                   limit=min(int(limit), 200)),
                "unread": notify.unread_count(store)}

    @router.post("/api/notifications/read")
    def notifications_read(body: ReadIn):
        n = notify.mark_read(store, body.ids)
        return {"message": "ok", "marked": n}

    return router
