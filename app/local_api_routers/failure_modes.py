"""本地 API 的「失败模式」资源域：`/api/failure-modes/*`。

从 `create_local_app()` 拆出的第三个资源域，范式同 models.py
（只依赖 store 与产品层、暴露 `build_xxx_router(store)` 工厂、不反向 import
`app.local_api`）。本域用到的 `_raise_engine_status` 是跨域共用件，从
`._shared` 引入。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import notify
from ..distill import engine_curation, gate, rewrite
from ..proxy import inject
from ..store.store import Store
from ._shared import _raise_engine_status


class RejectIn(BaseModel):
    text: str


class AiPolishFailureIn(BaseModel):
    text: str               # 行正文（去标记去次数，与 GET /api/failure-modes 一致）


class AiApplyFailureIn(BaseModel):
    old_text: str
    new_text: str


def build_failure_modes_router(store: Store) -> APIRouter:
    """挂载 /api/failure-modes/* 五个端点（三态清单、轨迹、否决、AI 改写/采纳）。"""
    router = APIRouter()

    @router.get("/api/failure-modes")
    def failure_modes_list():
        """失败模式三态：观察中/待验证/已固化 + 实时计数（gate 双门复算）。

        solid/watching 保留兼容；entries 是带三态与实时计数的权威清单
        （页面展示用它：白话提示"出现了 3 次，等下次同类任务确认"）。"""
        out = []
        for s in store.list_skills():
            md = store.read_skill(s["trunk"], s["category"]) or ""
            solid, pending, watching = inject.failure_mode_entries(
                inject.parse_playbook(md))
            states = gate.failure_mode_states(store, s["trunk"], s["category"])
            entries = []
            for body, st in states.items():  # body 已是去标记的行正文
                entries.append({
                    "text": gate._strip_count(body),
                    "state": st["state"],
                    "count": st["count"],
                    "last_seen": str(st["last_seen"] or "")[:10],
                    "expired": st["expired"],
                })
            out.append({"trunk": s["trunk"], "category": s["category"],
                        "name": s.get("name"),  # R4：显示名（可为 None）
                        "solid": solid, "pending": pending, "watching": watching,
                        "entries": entries})
        return {"items": out}

    @router.get("/api/failure-modes/{trunk}/{category}/trajectory")
    def failure_mode_trajectory(trunk: str, category: str):
        return {"items": engine_curation.failure_mode_trajectory(store, trunk, category)}

    @router.post("/api/failure-modes/{trunk}/{category}/reject")
    def failure_mode_reject(trunk: str, category: str, body: RejectIn):
        if not engine_curation.remove_failure_mode(store, trunk, category, body.text):
            raise HTTPException(status_code=404, detail="未找到该失败模式条目")
        notify.push(store, "method_update", f"{trunk}/{category} 方法已更新",
                    "你否决了一条失败模式，方法已同步修订")
        return {"message": "已否决并从方法中删除"}

    @router.post("/api/failure-modes/{trunk}/{category}/ai-polish")
    def failure_mode_ai_polish(trunk: str, category: str,
                               body: AiPolishFailureIn):
        """单条坑 AI 改写提案（不落库；带出现轨迹作上下文）。"""
        try:
            r = rewrite.polish_failure_mode(store, trunk, category, body.text)
        except Exception as exc:  # noqa: BLE001 模型失败/输出解析失败如实报
            raise HTTPException(status_code=502,
                                detail=f"AI 重写失败：{exc}") from exc
        _raise_engine_status(r["status"])
        if r["status"] == "not_found":
            raise HTTPException(status_code=404, detail="未找到该失败模式条目")
        return {"old_text": r["old_text"], "new_text": r["new_text"]}

    @router.post("/api/failure-modes/{trunk}/{category}/ai-apply")
    def failure_mode_ai_apply(trunk: str, category: str,
                              body: AiApplyFailureIn):
        """采纳坑改写：playbook 行原位替换（三态标记与次数注记保持）。"""
        if not rewrite.apply_polish_failure(store, trunk, category,
                                            body.old_text, body.new_text):
            raise HTTPException(status_code=404,
                                detail="未找到该失败模式条目（可能已被修订）")
        notify.push(store, "method_update", f"{trunk}/{category} 方法已更新",
                    "你采纳了 AI 对一条坑的改写，方法已同步修订")
        return {"message": "已采纳 AI 改写"}

    return router
