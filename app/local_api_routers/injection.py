"""本地 API 的「注入预览与回炉治理」资源域：`/api/injection-preview/*`、`/api/refutation/*`。

从 `create_local_app()` 拆出的第十个资源域，范式同 models.py
（只依赖 store 与产品层、暴露 `build_xxx_router(store)` 工厂、不反向 import
`app.local_api`）。`MODEL_REQUIRED_REWRITE` 是跨域共用件，从 `._shared` 引入。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..distill import llm
from ..distill import skill as skillgen
from ..proxy import inject
from ..store.store import Store
from ._shared import MODEL_REQUIRED_REWRITE

logger = logging.getLogger("experientia.local_api.injection")


class OverrideIn(BaseModel):
    id: str
    enabled: bool | None = None
    text: str | None = None


class OptimizeIn(BaseModel):
    text: str


class RefutationRestoreIn(BaseModel):
    trunk: str
    category: str
    item_id: str


def build_injection_router(store: Store) -> APIRouter:
    """挂载注入预览 5 个端点 + 回炉治理 2 个端点。"""
    router = APIRouter()

    # ---------- 模型会看到什么（覆盖层） ----------

    @router.get("/api/injection-preview")
    def injection_preview(trunk: str, category: str):
        """内容溯源披露：带上这份注入内容的来源，让用户知道它是
        模型归纳的产物还是旧的本机整理产物。**只披露，不动注入门槛**
        （G<0.5 永不注入 / 失败模式 ≥3 次才固化，防错误传播铁律）。"""
        prev = inject.injection_preview(store, trunk, category)
        src, at = skillgen.provenance_of(store.read_skill(trunk, category) or "")
        prev["content_source"] = src
        prev["generated_at"] = at
        return prev

    @router.put("/api/injection-preview/override")
    def override_upsert(body: OverrideIn):
        store.upsert_override(body.id, enabled=body.enabled, text=body.text)
        return {"message": "ok", "id": body.id}

    @router.delete("/api/injection-preview/override/{entry_id}")
    def override_remove(entry_id: str):
        store.remove_override(entry_id)
        return {"message": "已恢复默认", "id": entry_id}

    @router.post("/api/injection-preview/optimize")
    def override_optimize(body: OptimizeIn):
        """AI 优化：让模型把注入条目改得更精炼/具体。产物先回预览，
        用户确认才落覆盖层（本端点只返回文本，不写文件）。

        无模型 → 结构化拒绝（总纲同型）；模型回了空 → 502。**绝不把原文
        原样回回去冒充"AI 优化好了"**（静默降级比不做事更伤信任）。
        """
        if not llm.model_available(store):
            return {"ok": False, "status": "model_required",
                    "message": MODEL_REQUIRED_REWRITE}
        prompt = ("下面是一条要注入给 AI agent 的经验条目。把它改写得更精炼、更具体"
                  "（保留原意与关键数值，不超过原长度，输出一行，不要解释）：\n\n"
                  f"{body.text}")
        try:
            out = llm.call_model(store, [{"role": "user", "content": prompt}])
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"模型调用失败：{exc}")
        if not (out or "").strip():
            raise HTTPException(status_code=502, detail="模型没有给出改写内容")
        return {"ok": True, "status": "ok",
                "text": out.strip().splitlines()[0]}

    @router.post("/api/injection-preview/clear-stale")
    def override_clear_stale():
        stale = inject.stale_override_ids(store)
        for oid in stale:
            store.remove_override(oid)
        return {"removed": len(stale)}

    # ---------- 回炉治理（第⑤环） ----------

    @router.get("/api/refutation")
    def refutation_items():
        """跨全库聚合的受限/移出注入条目（GUI 治理面板数据源，只看不写）。"""
        return {"items": store.injection_governed_items()}

    @router.post("/api/refutation/restore")
    def refutation_restore(body: RefutationRestoreIn):
        """逐条恢复：清掉该条目的受限/移出标记，回到正常注入（经验仍留库）。"""
        ok = store.set_injection_item_state(
            body.trunk, body.category, body.item_id,
            restricted=0, excluded=0,
            restricted_since=None, excluded_since=None)
        return {"message": "已恢复", "restored": ok}

    return router
