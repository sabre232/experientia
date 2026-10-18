"""经验上报分流（总方案  / S5）。

来源：Trae 类"扫不到原文"的 agent 收尾自报（skill 输出 ≤3 句 conclusion/pitfalls）。
去向（模型或用户，二者必居其一，**启发式不作放行**）：
- 纪律闸（过滤，不放行）：超长/含密钥样式/同 agent 待处理过多 → 拒收，不进任何库；
- A 自动：有可用 LLM → 让模型从自报文本提取候选，走 review._process_candidate
  （复用 G 映射/质量字段/去重），合格 append_experience；提取为空或异常 → 落 C；
- C 草稿：无可用 LLM → 一律 append 草稿（pending），由用户"一键放行/忽略"；
- adopt（用户确认 = L3 最高信任）：结构化转正式经验（G=1, g_source=user）。
"""

from __future__ import annotations

import logging
import re

from ..distill import llm
from ..distill.review import _process_candidate

logger = logging.getLogger("experientia.capture.self_experience")

_MAX_CHARS = 800          # 自报全文上限（超过即拒收）
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|-----BEGIN[ A-Z]*PRIVATE KEY|"
    r"eyJ[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{20,})")
_MAX_PENDING_PER_AGENT = 5  # 同一 agent 待处理草稿超限 → 拒收（频率护栏）


def _compose(exp: dict) -> str:
    parts = []
    for key in ("task", "conclusion", "pitfalls"):
        v = str(exp.get(key) or "").strip()
        if v:
            parts.append(v)
    return "\n".join(parts)[:_MAX_CHARS]


def _detect_task(store, text: str) -> dict:
    try:
        from ..proxy import detect as proxy_detect
        return proxy_detect.detect_task_context(
            [{"content": text}],
            store.load_config().get("seed_keywords",
                                     proxy_detect.DEFAULT_SEED_KEYWORDS),
            proxy_detect.known_categories_from_store(store),
            store=store)
    except Exception:
        return {"trunk": "其他", "category": "未分类"}


def _discipline(store, agent: str, text: str) -> str | None:
    """返回拒绝原因或 None（通过）。纪律闸只过滤，不放行任何内容。"""
    if not text.strip():
        return "空内容"
    if len(text) > _MAX_CHARS:
        return "超过长度上限"
    if _SECRET_RE.search(text):
        return "疑似包含密钥/令牌"
    pending = [d for d in store.iter_drafts("pending") if d.get("agent") == agent]
    if len(pending) >= _MAX_PENDING_PER_AGENT:
        return "待处理草稿过多，请先处理旧的"
    for d in pending:
        if str(d.get("text") or "") == text:
            return "内容重复"
    return None


def _rec_for(store, agent: str, text: str, note: dict, g: float,
             g_source: str) -> dict:
    task = _detect_task(store, text)
    sess = {"agent": agent, "model": note.get("model", ""),
            "session_id": note.get("session_id", ""),
            "project": note.get("project"),
            "trunk": task["trunk"], "category": task["category"]}
    cand = {
        "task": str(note.get("task") or text[:60])[:200],
        "state": "",
        "action": text[:500],
        "outcome": str(note.get("result") or "")[:300],
        "corrected": bool(note.get("corrected")),
    }
    rec = _process_candidate(cand, sess, store)
    if rec is None:
        return None
    rec["G"] = g
    rec["g_source"] = g_source
    rec["source"] = "self-report"
    return rec


def _auto_route(store, agent: str, text: str, note: dict):
    """A 出口：有 LLM → 提取候选（复用复盘同款 _process_candidate 与门禁）。
    返回 rec 或 None（模型提取为空/异常 → 落草稿 C）。"""
    try:
        prompt = (
            "下面是一条 AI 工具收尾时自报的经验（第一人称结论/坑，≤3 句）。"
            "请判断是否有对下次同类任务可复用的做法，输出 JSON 数组（无可复用输出 []），"
            "每项 {\"task\": 任务一句话, \"action\": 具体做法, "
            "\"outcome\": 结果, \"corrected\": 是否被用户纠正(布尔), "
            "\"causal\": 是否做法直接导致结果(布尔)}。\n\n"
            f"自报：{text}")
        raw = llm.call_model(store, [{"role": "user", "content": prompt}])
        cands = llm.extract_json(raw)
        if not isinstance(cands, list) or not cands:
            return None
        for cand in cands[:3]:
            rec = _rec_for(store, agent, text, {**note, **cand},
                           _g_from_cand(cand), "auto" if not cand.get("corrected") else "auto")
            if rec:
                return rec
        return None
    except Exception as exc:
        logger.debug("自报 LLM 提取失败，落草稿: %s", exc)
        return None


def _g_from_cand(cand: dict) -> float:
    from ..distill import gsignal
    if cand.get("corrected"):
        return gsignal.L2_CORRECTED
    if cand.get("causal"):
        return gsignal.L3_CAUSAL
    return gsignal.L3_WEAK


def process(store, agent: str, note: dict) -> dict:
    """入口：自报经验 → {status: auto|pending|rejected, draft?/rec?}。"""
    text = _compose(note)
    reason = _discipline(store, agent, text)
    if reason:
        return {"status": "rejected", "reason": reason}
    try:
        store.record_self_reported(agent, {
            "mode": "report_only", "at": note.get("at") or "",
            "note": "经验上报已接收"})
    except Exception as exc:  # 裸 except 留痕（fail-open 不变）
        logger.debug("自报 observed 记录失败（不阻断上报流程）: %s", exc)
    # A：有 LLM 才自动
    rec = None
    if llm.model_available(store):
        try:
            rec = _auto_route(store, agent, text, note)
        except Exception as exc:  # 静默吞异常留痕（落草稿兜底不变）
            logger.debug("自报 LLM 自动路由异常，落草稿: %s", exc)
            rec = None
    if rec is not None:
        try:
            from ..distill import dedupe
            stored = dedupe.upsert_experience(store, rec)[0]
            store.append_event(
                "self", f"自报经验自动入库 {agent} → "
                        f"{rec.get('trunk', '其他')}/{rec.get('category', '未分类')}",
                agent=agent,
                path=f"{rec.get('trunk', '其他')}/{rec.get('category', '未分类')}",
                n=1)
            return {"status": "auto", "exp_id": stored.get("id")}
        except Exception as exc:
            logger.warning("自报自动入库失败，落草稿: %s", exc)
    # C：无 LLM 或提取存疑 → 草稿待手动放行
    draft = store.append_experience_draft({
        "agent": agent, "text": text, "note": note, "model": note.get("model", ""),
    })
    return {"status": "pending", "draft": draft}


def adopt(store, draft_id: str) -> dict:
    """一键放行（用户确认 = L3 最高信任）：结构化转正式经验。"""
    draft = next((d for d in store.iter_drafts("pending") if d.get("id") == draft_id),
                 None)
    if draft is None:
        return {"ok": False, "error": "草稿不存在或已处理"}
    agent = str(draft.get("agent") or "unknown")
    text = str(draft.get("text") or "")
    note = draft.get("note") or {}
    rec = _rec_for(store, agent, text, note, 1.0, "user")
    if rec is None:
        return {"ok": False, "error": "无法转为经验记录"}
    stored = store.append_experience(rec)
    store.set_draft_status(draft_id, "adopted")
    return {"ok": True, "exp_id": stored.get("id")}


def ignore(store, draft_id: str) -> dict:
    if store.set_draft_status(draft_id, "ignored"):
        return {"ok": True}
    return {"ok": False, "error": "草稿不存在"}
