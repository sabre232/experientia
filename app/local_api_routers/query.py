"""本地 API 的「成长与查询」资源域：成长/周报/治理/工作区/账本/坑卡/片段/会话/搜索。

覆盖 `/api/growth`、`/api/weekly-report`、`/api/content/governance`、
`/api/workspaces`、`/api/ledger`、`/api/rule-cards`、`/api/pending-fragments`、
`/api/session-view`、`/api/search` 共 9 个端点。

从 `create_local_app()` 拆出的第九个资源域，范式同 models.py
（只依赖 store 与产品层、暴露 `build_xxx_router(store)` 工厂、不反向 import
`app.local_api`）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..distill import llm
from ..distill import skill as skillgen
from ..store.store import Store


def build_query_router(store: Store) -> APIRouter:
    """挂载成长/周报/治理/工作区/账本/坑卡/待提炼片段/会话下钻/搜索，共 9 个端点。"""
    router = APIRouter()

    @router.get("/api/growth")
    def growth(days: int = 30):
        days = max(7, min(int(days), 365))
        summary = store.growth_summary(days=days)
        summary["changelog"] = store.list_changelog()[-50:][::-1]  # 新在前
        # 档 C 整理时间线+ 成就记录
        summary["maintenance"] = store.read_maintenance(limit=20)
        try:
            from ..distill import weekly_report
            summary["achievements"] = weekly_report.load_achievements(store)
        except Exception:
            summary["achievements"] = []
        # 内容溯源（总纲）：成长叙事属归纳层——没接模型时内容不会更新，
        # 显式标 "none" 让展示层挂溯源条（有模型标 "model"，时间 = 本次计算时间）
        summary["content_source"] = (
            skillgen.CONTENT_SOURCE_MODEL if llm.model_available(store)
            else skillgen.CONTENT_SOURCE_NONE)
        summary["generated_at"] = skillgen.now_iso()
        return summary

    @router.get("/api/weekly-report")
    def weekly_report():
        """本周结算叙事（App 内结算卡）：只读，不跑成就判定、不推通知。"""
        from ..distill import weekly_report as _wr
        out = _wr.peek(store)
        story = out.get("story")
        if isinstance(story, dict) and not story.get("content_source"):
            # 叙事由引擎侧数据算出，但"能不能随模型更新"必须如实标注（总纲）：
            # 有模型 → model + 本次生成时间；无模型 → none（展示层挂溯源条，
            # 见  provenance_bar：有内容但未接入模型才亮条）。
            story["content_source"] = (
                skillgen.CONTENT_SOURCE_MODEL if llm.model_available(store)
                else skillgen.CONTENT_SOURCE_NONE)
            story["generated_at"] = (skillgen.now_iso()
                                     if story["content_source"] == skillgen.CONTENT_SOURCE_MODEL
                                     else "")
        return out

    @router.post("/api/content/governance")
    def content_governance():
        """历史"废话"治理：旧的本机整理产物标 content_source="none"。

        **只标记不删除**——用户可在方法页看到"这是旧整理产物"并自行决定重建。
        返回 {"scanned": n, "marked": m}。"""
        from ..distill import maintenance

        return maintenance.run_content_governance(store)

    @router.get("/api/workspaces")
    def workspaces():
        """E-1：按工作区（session.project=cwd）聚合的会话索引（Repo Memory 前置）。"""
        return {"items": store.list_workspaces()}

    # ---------- 账本与坑卡（经验链路修复方案：无模型首屏素材） ----------

    @router.get("/api/ledger")
    def ledger_api():
        """AI 员工账本四数字：会话/轮数/token/花费估算 + 坑卡与片段计数。"""
        from .. import ledger
        try:
            return ledger.compute(store)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"账本计算失败: {exc}")

    @router.get("/api/rule-cards")
    def rule_cards(limit: int = 8):
        """T1 结构事实坑卡（rule 源），按可注入→复现→时间排序（洞察卡数据源）。"""
        cards = [e for e in store.iter_experiences(include_distilled=True)
                 if e.get("g_source") == "rule"]
        from ..distill import value_gate as _vg
        cards.sort(key=lambda e: (
            -float(e.get("G") or 0), -int(e.get("count") or 1),
            str(e.get("ts") or "")), reverse=False)
        out = []
        for e in cards[:max(1, min(limit, 50))]:
            seen = e.get("seen_in") or []
            out.append({
                "id": e.get("id"), "rule_kind": e.get("rule_kind"),
                "value_class": e.get("value_class"), "surface": _vg.surface_of(e),
                "task": e.get("task"), "state": e.get("state"),
                "action": e.get("action"), "count": int(e.get("count") or 1),
                "sessions": len({str(s) for s in seen if s}),
                "G": float(e.get("G") or 0), "injectable": float(e.get("G") or 0) >= 0.5,
                "ts": e.get("ts"), "agent": e.get("agent"),
                "session_id": e.get("session_id"), "project": e.get("project"),
            })
        return {"items": out, "total": len(cards)}

    @router.get("/api/pending-fragments")
    def pending_fragments():
        """未提炼片段（证据队列）：原文现场片段，不是经验、永不注入。"""
        return {"items": store.load_pending_review_records()[::-1]}

    @router.get("/api/session-view")
    def session_view(agent: str, sid: str):
        """会话下钻抽屉数据：落库截断转录 + 事件行 + 归档原件可用性。"""
        rec = next((s for s in store.list_sessions()
                    if s.get("agent") == agent and s.get("session_id") == sid), None)
        if rec is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        archive = store.data_dir / "sessions" / str(agent) / f"{sid}.jsonl"
        # ②：旧归档可能已被压缩为 <name>.jsonl.zst（原件已删）——仍算"有原件"
        has_archive = (archive.exists()
                       or archive.with_name(archive.name + ".zst").exists())
        return {
            "agent": agent, "session_id": sid,
            "project": rec.get("project"), "started_at": rec.get("started_at"),
            "model": rec.get("model"), "req_count": rec.get("req_count"),
            "correction_hits": rec.get("correction_hits"),
            "trunk": rec.get("trunk"), "category": rec.get("category"),
            "user_messages": rec.get("user_messages") or [],
            "assistant_messages": rec.get("assistant_messages") or [],
            "events": (rec.get("events") or [])[-80:],
            "has_archive": has_archive,
        }

    @router.get("/api/search")
    def search_sessions_api(q: str = "", limit: int = 20):
        """会话全文搜索：FTS5 BM25 + trigram（CJK 直检），
        embedding 就位时叠加向量重排；<3 字查询 LIKE 兜底。"""
        q = (q or "").strip()
        if not q:
            return {"items": []}
        limit = max(1, min(int(limit), 50))
        embedder = None
        try:
            from ..semantic.embedder import get_embedder
            embedder = get_embedder(store)
        except Exception:
            embedder = None
        return {"items": store.search_sessions(q, limit=limit,
                                               embedder=embedder)}

    return router
