"""本地 API 的「经验草稿」域（自报经验待用户裁决）。

 L4 续：从 ingest.py 拆出的第三组——草稿清单与采纳/忽略。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ..store.store import Store

logger = logging.getLogger("experientia.local_api.ingest")


def build_drafts_router(store: Store) -> APIRouter:
    """经验草稿，3 个端点。"""
    router = APIRouter()
    @router.get("/api/experience-drafts")
    def experience_drafts(status: str = "pending"):
        try:
            rows = store.list_drafts(status or None)
            return {"items": rows, "count": len(rows)}
        except Exception as exc:
            logger.exception("experience-drafts 读取失败")
            return {"items": [], "count": 0, "error": str(exc)}

    @router.post("/api/experience-drafts/{draft_id}/adopt")
    def experience_draft_adopt(draft_id: str):
        from ..capture import self_experience as se_ch
        try:
            return se_ch.adopt(store, draft_id)
        except Exception as exc:
            logger.exception("experience-drafts adopt 失败")
            return {"ok": False, "error": str(exc)}

    @router.post("/api/experience-drafts/{draft_id}/ignore")
    def experience_draft_ignore(draft_id: str):
        from ..capture import self_experience as se_ch
        try:
            return se_ch.ignore(store, draft_id)
        except Exception as exc:
            logger.exception("experience-drafts ignore 失败")
            return {"ok": False, "error": str(exc)}

    # ---------- IDE / Hermes 事件通道 ----------

    return router
