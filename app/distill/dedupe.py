"""近重复去重（蒸馏兜底方案）：去重不需要语义相似度，只需要近重复检测。

外部实践：trigram 相似度在 0.85 阈值一次抓到 115 条重复
（scien.cx 《I gave my AI agent memory across sessions》）。
用 difflib 标准库实现，零新依赖。
"""

from __future__ import annotations

import difflib
import logging

logger = logging.getLogger("experientia.distill.dedupe")

NEAR_DUP_THRESHOLD = 0.85


MIN_RATIO_LEN = 6  # 短文本（<6 字）ratio 虚高（"ab"/"a" = 0.67），只信包含关系


def near_dup(a: str, b: str, threshold: float = NEAR_DUP_THRESHOLD) -> bool:
    """两段文本是否近重复。

    判定：完全相等；或短文本互为子串（"a"/"ab"）；或长文本
    （≥MIN_RATIO_LEN 字）字符级相似度 ≥ 阈值。空串不算重复。
    """
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) < MIN_RATIO_LEN or len(b) < MIN_RATIO_LEN:
        return a in b or b in a
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def dedupe_lines(lines: list[str],
                 threshold: float = NEAR_DUP_THRESHOLD) -> list[str]:
    """按顺序保留首见，丢掉与前面任一条近重复的行。"""
    out: list[str] = []
    for ln in lines:
        if any(near_dup(ln, kept, threshold) for kept in out):
            continue
        out.append(ln)
    return out


def upsert_experience(store, rec: dict) -> tuple[dict, str]:
    """语义去重四操作。

    - 同 (agent, task, action) 精确重复 → append_experience 内建合并（count/seen_in）；
    - 同 agent 下 task 与 action 都近重复（≥0.85）→ MERGE/NOOP：count+1、
      G 取大、seen_in 并集；**文本不覆盖**——LLM 措辞每次漂移，让漂移改写
      已沉淀资产是污染（用户手动编辑走 edit 端点，那是明确意图）；
    - 都不像 → ADD。
    返回 (记录, 操作名 ∈ add/merge/exact)。
    """
    agent = str(rec.get("agent") or "")
    task = str(rec.get("task") or "")
    action = str(rec.get("action") or "")
    if agent and task:
        for e in store.iter_experiences(agent=agent, include_distilled=True):
            if str(e.get("id") or "") == str(rec.get("id") or ""):
                continue
            if not near_dup(task, str(e.get("task") or "")):
                continue
            if not near_dup(action, str(e.get("action") or "")):
                continue
            new_ids = set()
            if rec.get("session_id"):
                new_ids.add(str(rec["session_id"]))
            if isinstance(rec.get("seen_in"), list):
                new_ids |= {str(x) for x in rec["seen_in"] if x}
            new_ids.discard("")
            # count+1 / G 取大 / seen_in 并集交给 store 在写锁内
            # 用**当前行**派生——此前用锁外快照 e 算 count+1 再整行写回，与并发
            # append_experience 的合并交叠会丢更新。
            updated = store.bump_experience_merge(
                str(e["id"]), g_value=rec.get("G"), seen_ids=new_ids) or e
            try:  # 佐证/反驳回灌与 append 路径同口径（第⑤环）
                store.apply_injection_feedback(updated)
            except Exception as exc:
                # 反馈回灌失败静默吞掉无痕迹——与 append_experience
                # 路径同口径补留痕（反馈只增强不拖垮主合并，故仍不抛出）。
                logger.warning("经验反馈回填异常(忽略): %s", exc)
            return updated, "merge"
    return store.append_experience(rec), "add"
