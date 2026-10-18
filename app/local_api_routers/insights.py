"""本地 API 的「工作流洞察 + 学习历程」资源域：`/api/insights/*`、`/api/changelog/*`，
外加「整理 Skill」的 `/api/skills/generate`。

从 `create_local_app()` 拆出的第十一个资源域，范式同 models.py
（只依赖 store 与产品层、暴露 `build_xxx_router(store)` 工厂、不反向 import
`app.local_api`）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..distill import export as exporter
from ..distill import skill as skillgen
from ..insight import suggest
from ..store.store import Store

logger = logging.getLogger("experientia.local_api.insights")


class SkillGenIn(BaseModel):
    trunk: str | None = None
    category: str | None = None
    selected: list[dict] | None = None
    name: str | None = None
    description: str | None = None
    version: str | None = None


def build_insights_router(store: Store) -> APIRouter:
    """挂载洞察 2 + changelog 2 + 整理 Skill 1，共 5 个端点。"""
    router = APIRouter()

    # ---------- 工作流洞察（W4-04：建议卡 + 三选一） ----------

    @router.get("/api/insights")
    def insights_list():
        return {"items": suggest.unhandled_cards(store, limit=2),
                "total": len([c for c in store.load_insights()
                              if c.get("action") is None])}

    @router.post("/api/insights/{insight_id}/{action}")
    def insight_act(insight_id: str, action: str):
        if action not in ("apply", "dismiss", "defer"):
            raise HTTPException(status_code=400, detail="action 必须是 apply/dismiss/defer")
        card = next((c for c in store.load_insights()
                     if c.get("id") == insight_id), None)
        if card is None:
            raise HTTPException(status_code=404, detail="建议卡不存在")
        if card.get("action") is not None:
            raise HTTPException(status_code=404, detail="建议卡已处理")
        if action == "apply":
            rule = suggest.apply_card(store, card)
            return {"message": "已写入规则", "rule": rule}
        if action == "dismiss":
            suggest.dismiss_card(store, insight_id)
            return {"message": "已忽略（同类建议不再提示）"}
        suggest.defer_card(store, insight_id, card)
        return {"message": "稍后再说（已进通知提醒）"}

    # ---------- 学习历程（changelog 节点编辑/删除） ----------

    @router.post("/api/changelog/{idx}")
    def changelog_edit(idx: int, body: dict):
        text = str(body.get("text", "")).strip()
        if not text:
            raise HTTPException(status_code=400, detail="text 不能为空")
        if not store.edit_changelog(idx, text):
            raise HTTPException(status_code=404, detail="节点不存在")
        return {"message": "已编辑", "idx": idx}

    @router.delete("/api/changelog/{idx}")
    def changelog_delete(idx: int):
        if not store.delete_changelog(idx):
            raise HTTPException(status_code=404, detail="节点不存在")
        return {"message": "已删除（归档 30 天可恢复）", "idx": idx}

    # ---------- 整理 Skill ----------

    @router.post("/api/skills/generate")
    def skill_generate(body: SkillGenIn):
        try:
            result = skillgen.generate_skill(
                store, trunk=body.trunk, category=body.category,
                selected=body.selected, name=body.name,
                description=body.description,
                version=body.version or "1.0.0")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except Exception as exc:
            logger.exception("skill 生成失败")
            raise HTTPException(status_code=502, detail=f"模型调用失败：{exc}")
        # E-05（M1 信息架构重构）：SKILL.md frontmatter 补 dos/donts
        # （从方法正文 Procedure/Pitfalls 归纳，幂等）
        result["md"] = exporter.with_skill_dodonts(result["md"])
        return result

    return router
