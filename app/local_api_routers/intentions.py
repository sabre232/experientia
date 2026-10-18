"""本地 API 的「L6 前瞻意图 + 六层存量」资源域（P1-1/P1-2 的用户可见出口）。

意图是 System2 从反复出现的模式里沉淀的“接下来可能要处理什么”。在接这个域之前，
它只有引擎侧在读（MCP 胶囊）——用户既看不见也忽略不了，等于做了个没人能用的功能。

端点：
- `GET  /api/intentions`        有效意图（trunk 可选、最新在前）
- `POST /api/intentions/{id}/dismiss`  忽略一条（幂等）
- `GET  /api/layers`            六层存量快照（记忆构成）

范式同其余资源域：`build_xxx_router(store)` 工厂、不反向 import `app.local_api`。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..distill import layers as _layers
from ..store.store import Store


def build_intentions_router(store: Store) -> APIRouter:
    router = APIRouter()

    @router.get("/api/intentions")
    def intentions_list(trunk: str | None = None, limit: int = 50):
        limit = max(1, min(int(limit), 200))
        items = store.list_intentions(trunk or None)[:limit]
        # 过期时间一并给出去：GUI 要显示“这条还会提醒多久”
        return {"items": items, "count": len(items)}

    @router.post("/api/intentions/{intention_id}/dismiss")
    def intention_dismiss(intention_id: str):
        if not store.dismiss_intention(intention_id):
            raise HTTPException(status_code=409,
                                detail="意图不存在或已忽略")
        return {"message": "已忽略，不再提醒"}

    @router.get("/api/layers")
    def layers_inventory():
        """六层存量快照：材料堆在哪一层、哪层空了。

        L2 攒够而 L5 空 → 该跑蒸馏了；L6 空且 L2 也多 → 模式不够重复，别硬造意图。
        """
        try:
            inv = _layers.inventory(store)
        except Exception as exc:  # noqa: BLE001 统计失败返回空快照，不 500
            return {"layers": {}, "error": str(exc)}
        return {"layers": inv}

    return router
