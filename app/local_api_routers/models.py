"""本地 API 的「模型管理」资源域：`/api/models/*`。

`create_local_app()` 曾是一个 1652 行、约 115 个端点的大闭包，
定位、review、并行修改都容易踩到无关分支。本模块是拆分出的**第一个资源域**，
用来确立后续各域的搬移范式：

1. 域模块只依赖 `store` 与产品层（这里只用到 `models_service`），
   **绝不 import `app.local_api`**——否则与 create_local_app 的挂载形成循环导入；
2. 对外只暴露一个工厂 `build_xxx_router(store)`，由 `create_local_app` 用
   `app.include_router(...)` 挂载；端点通过闭包拿到 store，语义与原先完全一致；
3. 请求体 schema 随域走。`RouteIn` 全库仅本域使用，故一并搬来；`local_api`
   侧保留同名再导出以兼容既有 `from app.local_api import RouteIn`。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import models_service as models
from ..store.store import Store


class RouteIn(BaseModel):
    name: str
    endpoint: str
    model: str
    type: str = "cloud"  # local / cloud / anthropic
    key: str | None = None


def build_models_router(store: Store) -> APIRouter:
    """挂载 /api/models/* 七个端点（增删、设默认、设蒸馏、自检、清蒸馏）。"""
    router = APIRouter()

    @router.get("/api/models")
    def models_list():
        return models.list_routes(store)

    @router.post("/api/models")
    def models_add(body: RouteIn):
        ok, msg = models.add_route(store, body.name, body.endpoint, body.model,
                                   body.type, body.key)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"message": msg, **models.list_routes(store)}

    @router.post("/api/models/{name}/set-default")
    def models_set_default(name: str):
        ok, msg = models.set_route(store, name, "default")
        if not ok:
            raise HTTPException(status_code=404, detail=msg)
        return {"message": msg, **models.list_routes(store)}

    @router.post("/api/models/{name}/set-distill")
    def models_set_distill(name: str):
        ok, msg = models.set_route(store, name, "distill")
        if not ok:
            raise HTTPException(status_code=404, detail=msg)
        return {"message": msg, **models.list_routes(store)}

    @router.post("/api/models/check")
    def models_check():
        """接入自检（W1-08）：默认路由 1-token 最小补全，结果带可操作指引。"""
        ok, msg = models.check_route(store)
        return {"ok": ok, "message": msg}

    @router.post("/api/models/clear-distill")
    def models_clear_distill():
        """蒸馏模型回到「跟随默认模型」。"""
        # 读-改-写走 mutate_config（持写锁，防并发丢字段）
        def _apply(config: dict) -> dict | None:
            if config.pop("distill_model", None) is None:
                return None  # 无变化不落盘
            return config

        store.mutate_config(_apply)
        return {"message": "ok", **models.list_routes(store)}

    @router.delete("/api/models/{name}")
    def models_remove(name: str):
        ok, msg = models.remove_route(store, name)
        if not ok:
            raise HTTPException(status_code=404, detail=msg)
        return {"message": msg, **models.list_routes(store)}

    return router
