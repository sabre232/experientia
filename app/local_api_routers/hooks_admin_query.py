"""本地 API 的「hooks 管理·查询」域：总览 / 单 agent 说明 / 单 agent 详情。

 L4 续：原 build_hooks_admin_router 169 行塞了 15 个端点，按职责
切成三组，本模块是只读查询的三个。

⚠️ 保序：`/api/hooks/admin/{agent}` 是通配路径，必须排在 overview 与 explain
之后，否则会把它们吃掉（不报错，只表现为一直 404）。故这三个刻意留在同一
模块内，顺序与拆分前一致。"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException

from ..capture import hook as hook_channel
from ..distill import llm
from ..store.store import Store

logger = logging.getLogger("experientia.local_api.hooks")


def build_hooks_admin_query_router(store: Store) -> APIRouter:
    """hooks 管理查询，3 个端点（overview / explain / {agent}）。"""
    router = APIRouter()

    # 注意：overview 必须先于 {agent} 定义——FastAPI 按定义顺序匹配，
    # 否则 "overview" 会被 {agent} 吞掉当 agent 名（GUI 总览会一直 400）。

    @router.get("/api/hooks/admin/overview")
    def hooks_admin_overview():
        """全部 agent 的 hook 管理态（一次返回，支撑 GUI 自动接入提议）。

        agent 集合 = 内置表 ∪ 自报 hook 面 ∪ 本机检测到在跑的 agent（本地启发式）。"""
        from ..capture import hook_admin as ha
        return ha.overview(store=store)

    @router.post("/api/hooks/admin/explain")
    def hooks_admin_explain(payload: dict = None):
        """LLM 辅助解释：让模型把某条 hook 条目翻译成更详细的大白话（可选项，用户主动触发）。

        静态人话字典（GUI 层兜底）不受本端点影响，未接模型也照常工作。
        未接入模型 → 409（GUI 回落"先去接模型"提示）；条目不存在 → 404；
        模型调用失败 → 502（GUI 显示重试提示，不吞原始错误）。"""
        from ..capture import hook_admin as ha

        if not llm.model_available(store):
            raise HTTPException(status_code=409, detail="未接入模型")
        agent = str((payload or {}).get("agent") or "")
        entry_id = str((payload or {}).get("entry_id") or "")
        try:
            info = ha.list_agent(agent, store=store)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        e = next((x for x in (info.get("entries") or [])
                  if str(x.get("id")) == entry_id), None)
        if e is None:
            raise HTTPException(status_code=404, detail="条目不存在")
        prompt = (
            "你是 AI 编码工具的配置助手，负责把 hook（提醒规则）配置解释给非技术用户。"
            "请用人话说明：1) 它什么时候触发 2) 它替用户做什么 3) 用户是否需要留意。"
            "要求：120 字以内、不堆术语、不向用户抛英文事件名或原始命令；"
            "对命令行为拿不准时只解释文本能确认的部分，不要猜测。"
        )
        # hook 命令里可能带上报 URL 的 ?key= 防伪令牌，
        # 外发 LLM 前先抹掉（与 log_conf 脱敏同口径，防令牌进第三方）。
        cmd = re.sub(r"(\?key=)[^\s&\"']+", r"\1***",
                     str(e.get("command") or ""))
        user = (f"工具：{agent}\n触发事件：{e.get('event') or ''}\n"
                f"命令：{cmd}")
        try:
            text = llm.call_model(store, [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user},
            ], temperature=0.2, max_tokens=300)
        except Exception as exc:  # noqa: BLE001 模型调用失败统一 502，GUI 显示重试提示
            logger.warning("hook explain LLM 调用失败: %s", exc)
            raise HTTPException(status_code=502, detail="模型调用失败，请稍后再试")
        return {"agent": agent, "entry_id": entry_id, "text": (text or "").strip()}

    @router.get("/api/hooks/admin/{agent}")
    def hooks_admin_list(agent: str):
        """某 agent 的 hook 全量条目 + 来源/启用态（管理页读）。

        store → 自报 hook 面发现 + 本地启发式发现（表外 agent 如 workbuddy/codex 可列出）。"""
        from ..capture import hook_admin as ha
        try:
            return ha.list_agent(agent, store=store)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return router
