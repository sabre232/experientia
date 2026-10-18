"""本地 API 的「经验库」资源域：`/api/experiences/*`、`/api/experience-categories`。

从 `create_local_app()` 拆出的第六个资源域，范式同 models.py
（只依赖 store 与产品层、暴露 `build_xxx_router(store)` 工厂、不反向 import
`app.local_api`）。`_raise_engine_status` 从 `._shared` 引入。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..distill import gsignal, rewrite
from ..store.store import Store
from ._shared import _raise_engine_status


class FeedbackIn(BaseModel):
    feedback: str  # valid / corrected


class ExperienceEditIn(BaseModel):
    """纠正 = 改内容：只传要改的字段，None = 不改。"""
    task: str | None = None
    state: str | None = None
    action: str | None = None
    outcome: str | None = None


class CategorizeIn(BaseModel):
    category: str        # 目标分类名
    trunk: str | None = None  # 目标任务大类；None = 服务端按已知归属推断


class AiPolishExpIn(BaseModel):
    ids: list[str]          # 一张经验卡里的全部记录 id


class AiApplyExpIn(BaseModel):
    task: str | None = None
    state: str | None = None
    action: str | None = None
    outcome: str | None = None


class ForgetIn(BaseModel):
    hard: bool = False


class RollbackIn(BaseModel):
    revision: int


def build_experiences_router(store: Store) -> APIRouter:
    """挂载 /api/experiences/* 十个端点（清单、反馈、纠正、AI 改写入/采纳、讲人话、分类、不采纳/恢复）。"""
    router = APIRouter()

    @router.get("/api/experiences")
    def experiences_list(trunk: str | None = None, category: str | None = None,
                         agent: str | None = None, q: str | None = None,
                         include_distilled: bool = True, limit: int = 300):
        limit = max(1, min(int(limit), 1000))
        from ..distill import mining as _mining
        from ..distill import value_gate as _vg
        # 无关键字（首页 limit=300 的主路径）时把 surface 过滤 + LIMIT 下推到
        # SQL（O(limit)，与总条数无关）；带 q 时保持原逐条过滤——q 匹配的是"rule 项
        # 归一化后的 task/action"，SQL 列是原始值，下推会改变匹配语义，故不下推。
        push = not q
        out = []
        for item in store.iter_experiences(
                trunk=trunk, category=category, agent=agent,
                include_distilled=include_distilled,
                surface=(_vg.SURFACE_EXPERIENCE if push else None),
                limit=(limit if push else None)):
            # 价值闸门（方案  + A 收口）："你的经验"只留 LLM 真教训 + 结构化改出来的
            # 模式。下推时 SQL 已按同口径过滤，此处兜底（索引降级回退 JSONL 时同口径）。
            if _vg.surface_of(item) != _vg.SURFACE_EXPERIENCE:
                continue
            if item.get("g_source") == "rule":
                # 展示层归一：task/action 是跨会话合并用的 ASCII 指纹，
                # 卡片与搜索统一用模板句（存储快照不动）
                item = dict(item)
                item["action"] = _mining.rule_line_text(item)
                item["task"] = str(item.get("task") or "").split(":", 1)[-1]
            if q:
                blob = " ".join(str(item.get(k, "")) for k in
                                ("task", "action", "state", "outcome", "agent"))
                if q.lower() not in blob.lower():
                    continue
            out.append(item)
            if len(out) >= limit:
                break
        return {"items": out, "count": len(out)}

    @router.post("/api/experiences/{exp_id}/feedback")
    def experience_feedback(exp_id: str, body: FeedbackIn):
        if body.feedback not in ("valid", "corrected"):
            raise HTTPException(status_code=400, detail="feedback 必须是 valid / corrected")
        head = store.find_experience(exp_id)
        if head is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        if gsignal.is_rule(head):
            # rule 坑卡：反馈不翻 g_source——翻了会丢 rule 身份（seen_in 复现
            # 口径失效）且被 high_value_eligible 判成"成功要点"（坑确认了也
            # 还是坑）。"有效"=user_valid 直接过固化门；"纠正"=user_rejected
            # 停止注入（-P1-6 卡片三态反馈的 L1 通道）。
            patch = ({"user_valid": True} if body.feedback == "valid"
                     else {"user_rejected": True})
            item = store.update_experience(exp_id, {**patch, "distilled": False})
            return {"message": "已记录反馈", "experience": item}
        g, corrected = gsignal.score_l1(body.feedback)
        item = store.update_experience(exp_id, {
            "G": g, "g_source": "user", "corrected": corrected,
            "distilled": False,  # 反馈后重新参与下次蒸馏
        })
        if item is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        return {"message": "已记录反馈", "experience": item}

    @router.post("/api/experiences/{exp_id}/edit")
    def experience_edit(exp_id: str, body: ExperienceEditIn):
        """纠正 = 直接改内容。用户改对的文本成为这条经验的正式内容
        （展示与检索同源，*_raw 一并跟着改，卡片展开不会再翻出旧字）。

        被覆盖的旧值进 previous 快照（每个字段只记首次被改前的值 = 最初的错内容），
        失败分析师读旧值——"什么不能做"记的是被改掉的错内容，不把改对的内容
        当教训。保存后仍算纠正：corrected=true、G 落 L1 纠正档、回炉重蒸馏。"""
        item = store.find_experience(exp_id)
        if item is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        snap = dict(item.get("previous") or {})
        patch: dict = {}
        for key, value in (("task", body.task), ("state", body.state),
                           ("action", body.action), ("outcome", body.outcome)):
            if value is None:
                continue
            new = value.strip()
            old = str(item.get(key) or "").strip()
            if new == old:
                continue
            if key not in snap:
                snap[key] = old
            patch[key] = new
            patch[key + "_raw"] = new
        if not patch:
            return {"message": "内容未变化", "experience": item}
        g, corrected = gsignal.score_l1("corrected")
        patch.update({"previous": snap, "G": g, "g_source": "user",
                      "corrected": corrected, "distilled": False})
        updated = store.update_experience(exp_id, patch)
        if updated is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        return {"message": "已更新内容", "experience": updated}

    @router.post("/api/experiences/ai-polish")
    def experiences_ai_polish(body: AiPolishExpIn):
        """经验卡 AI 重写提案（单条粒度，不落库；用户采纳走 ai-apply）。"""
        try:
            r = rewrite.polish_experiences(store, body.ids)
        except Exception as exc:  # noqa: BLE001 模型失败/输出解析失败如实报
            raise HTTPException(status_code=502,
                                detail=f"AI 重写失败：{exc}") from exc
        _raise_engine_status(r["status"])
        if r["status"] == "not_found":
            raise HTTPException(status_code=404, detail="经验不存在")
        return {"proposals": r["proposals"]}

    @router.post("/api/experiences/{exp_id}/ai-apply")
    def experience_ai_apply(exp_id: str, body: AiApplyExpIn):
        """采纳 AI 重写：只更新总结层（G/corrected/*_raw 不动），回炉重总结。"""
        updated = rewrite.apply_polish(store, exp_id, body.model_dump())
        if updated is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        return {"message": "已采纳 AI 重写", "experience": updated}

    @router.post("/api/experiences/{exp_id}/explain")
    def experience_explain(exp_id: str, lang: str = "zh"):
        """单条经验"讲人话"：AI 大白话解释 + 一条建议（结果缓存在记录上）。"""
        try:
            r = rewrite.explain_experience(store, exp_id, lang=lang)
        except Exception as exc:  # noqa: BLE001 模型失败/解析失败如实报
            raise HTTPException(status_code=502,
                                detail=f"AI 讲人话失败：{exc}") from exc
        _raise_engine_status(r["status"])
        if r["status"] == "not_found":
            raise HTTPException(status_code=404, detail="经验不存在")
        return {"explain": r["explain"], "advice": r["advice"], "cached": r["cached"]}

    @router.post("/api/experiences/{exp_id}/categorize")
    def experience_categorize(exp_id: str, body: CategorizeIn):
        """修改经验分类（用户手动指定分类）。body.trunk 缺省时按已知归属推断
        （该 category 已存在于某 task 大类下 → 连带写 trunk；用户无需知道 trunk）。"""
        patch = {"category": body.category}
        if body.trunk:
            patch["trunk"] = body.trunk
        else:
            cat_trunk = next(
                (item.get("trunk") for item in
                 store.iter_experiences(category=body.category,
                                        include_distilled=True)
                 if item.get("trunk")), None)
            if cat_trunk:
                patch["trunk"] = cat_trunk
        item = store.update_experience(exp_id, patch)
        if item is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        return {"message": f"已分类为 {body.category}", "experience": item}

    @router.post("/api/experiences/{exp_id}/dismiss")
    def experience_dismiss(exp_id: str):
        """不采纳：软删除（打 dismissed=True 标记，保留数据可恢复）。"""
        item = store.update_experience(exp_id, {"dismissed": True})
        if item is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        return {"message": "已标记不采纳", "experience": item}

    @router.post("/api/experiences/{exp_id}/restore")
    def experience_restore(exp_id: str):
        """恢复已不采纳的经验。"""
        item = store.update_experience(exp_id, {"dismissed": False})
        if item is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        return {"message": "已恢复", "experience": item}

    @router.get("/api/experience-categories")
    def experience_categories():
        """返回所有出现过的分类名（去重、排序），用于分类下拉菜单。

        走 experience.db 的 `SELECT DISTINCT category`（O(distinct)，与经验
        条数无关），不再在 Python 里遍历全部经验；索引不可用时自动回退 JSONL。"""
        return {"categories": store.experience_categories()}

    # ---------- P0-3 演化链 / 遗忘 / 回滚 ----------
    # 路径命名注意：`/restore` 已被上面"取消不采纳"（dismissed=False）占用，
    # 遗忘的恢复用 `/unforget`——两条语义完全不同，别复用同一路径。

    @router.get("/api/experiences/{exp_id}/chain")
    def experience_chain(exp_id: str):
        """一条经验的完整演化链：历史版本 + 当前头（含证据锚点）。"""
        chain = store.experience_chain(exp_id)
        if chain is None:
            raise HTTPException(status_code=404, detail="经验不存在")
        return {"chain": chain}

    @router.post("/api/experiences/{exp_id}/forget")
    def experience_forget(exp_id: str, body: ForgetIn | None = None):
        """用户显式遗忘。默认软忘（可逆）；hard=true 走"先归档后删"硬删。"""
        hard = bool(body.hard) if body is not None else False
        if not store.forget_experience(exp_id, hard=hard):
            raise HTTPException(status_code=409, detail="无法遗忘（不存在或归档失败）")
        return {"message": "已遗忘" if not hard else "已彻底删除",
                "hard": hard}

    @router.post("/api/experiences/{exp_id}/unforget")
    def experience_unforget(exp_id: str):
        """撤销软忘（tombstone → 恢复）。硬删的走 deprecated，不在此列。"""
        if not store.restore_experience(exp_id):
            raise HTTPException(status_code=409, detail="该经验不在已遗忘状态")
        return {"message": "已恢复"}

    @router.post("/api/experiences/{exp_id}/rollback")
    def experience_rollback(exp_id: str, body: RollbackIn):
        """回滚到某个历史版本（以新版本形式落库，历史不被改写）。"""
        try:
            rec = store.rollback_experience(exp_id, body.revision)
        except KeyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"message": f"已回到第 {body.revision} 版", "experience": rec}

    return router
