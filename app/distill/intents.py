"""L6 前瞻意图的沉淀（P1-1，System2 慢路径）。

输入 = `app/insight/patterns.py` 已经检测出来的确定性模式（频率 / 路径 / 纠正），
输出 = 一句"下一步可能想干什么"。

为什么不另起炉灶：模式检测器已经在跑（建议卡的原料），意图只是同一批发现的
**另一种表述**——建议卡问"要不要沉淀成规则"，意图说"接下来大概要处理这个"。
同一个证据、两种面向，污染面就小。

三条约束：

1. **零模型**。全部确定性拼句；模型不可用不影响意图生成。
2. **不注入**。意图只写 intentions.jsonl，`app/proxy/inject.py` 不读它；
   只在 MCP 的 context_capsule 里以 L6 最低权重出现。
3. **单轮有上限**。一次最多沉淀 `MAX_PER_RUN` 条，防把 L6 刷成噪音源。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("experientia.distill.intents")

MAX_PER_RUN = 3           # 单次沉淀条数上限
_MIN_OCCURRENCES = 2      # 至少出现 2 次才算"反复"（与 patterns 口径一致）

# 模式类型 → 意图句式。占位符 {example} / {n} 由模式数据填。
_TEMPLATES = {
    "frequency": "下次做「{example}」这类任务时，先看有没有现成流程可复用",
    "path": "把这条反复出现的操作路径整理成标准流程：{example}",
    "correction": "动手前先确认边界，避免再在「{example}」上被纠正",
}


def _intent_for(pattern: dict) -> str | None:
    """一个模式 → 一句意图。模板缺失或样本为空 → None（不硬凑）。"""
    ptype = str(pattern.get("type") or "")
    tpl = _TEMPLATES.get(ptype)
    if not tpl:
        return None
    example = str(pattern.get("example") or "").strip()
    if not example:
        return None
    occurrences = int(pattern.get("occurrences") or 0)
    if occurrences and occurrences < _MIN_OCCURRENCES:
        return None
    return tpl.format(example=example[:60], n=occurrences)


def derive_intentions(store, patterns: list[dict] | None = None,
                      exps: list[dict] | None = None) -> int:
    """从模式沉淀前瞻意图，返回新增条数。

    `patterns` / `exps` 都给就用；只给 store 时自己跑检测器（调用方已有时传进来，
    避免重复计算）。任一环节异常只记日志、返回 0——L6 是附加层，绝不能拖垮主路径。
    """
    try:
        if patterns is None:
            from ..insight import patterns as _patterns

            if exps is None:
                exps = list(store.iter_experiences(include_distilled=True))
            patterns = _patterns.detect_all(exps)
        added = 0
        for pattern in list(patterns or [])[: MAX_PER_RUN * 3]:
            if added >= MAX_PER_RUN:
                break
            intent = _intent_for(pattern)
            if not intent:
                continue
            rec = store.add_intention(
                intent,
                trunk=str(pattern.get("trunk") or "其他"),
                category=str(pattern.get("category") or "未分类"),
                evidence_ids=list(pattern.get("evidence") or []),
                kind=str(pattern.get("type") or "pattern"),
            )
            if rec is not None and int(rec.get("count") or 1) == 1:
                added += 1
        return added
    except Exception as exc:  # noqa: BLE001 附加层失败不得影响主路径
        logger.warning("前瞻意图沉淀失败（忽略）: %s", exc)
        return 0
