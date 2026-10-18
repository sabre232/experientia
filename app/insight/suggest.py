"""建议卡（W4-02）：确定性模式 → 建议卡（证据 + 推荐动作三选一）。

LLM 只用于把检测出的模式改写成口语建议；不可用时直接展示规则模板句
（降级路径，保证建议永远可用）。用户三选一：
- 应用：写入 rules（硬钩子=NEVER 红线语义）或触发蒸馏
- 忽略：记录 + 同类建议降权（同 type+trunk 不再重复提示）
- 稍后再说：进通知中心轻量提醒区
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..distill import llm
from ..store.store import Store, utcnow
from . import patterns

logger = logging.getLogger("experientia.insight")

# 规则模板句（LLM 不可用时的降级文案；zh 源串走 t() 在 GUI 层翻译）
TEMPLATE_SENTENCES = {
    "frequency": "「{example}」这类做法最近出现了 {n} 次——要不要沉淀成固定方法？",
    "path": "最近的任务里反复出现同一条操作路径（{example}）——可以提炼成标准流程。",
    "correction": "你最近 {n} 次纠正了同类问题（{example}）——要不要写成红线规则？",
}

REWRITE_PROMPT = """下面是从用户 agent 使用记录里检测出的一个重复模式：
类型：{type}
类别：{trunk} / {category}
示例：{example}
出现次数：{n}

把上面的发现改写成一句给用户的口语建议（≤60 字，直接说发现 + 一个建议动作，
不要客套，不要问句套娃）。只输出这一句话："""

MAX_UNHANDLED = 5  # 未处理建议卡上限（防堆积）


def _rule_text(p: dict) -> str:
    """建议卡 → 规则文本（应用时写入 rules）。"""
    ex = p.get("example", "")
    if p["type"] == "correction":
        return f"NEVER 重复出现同类问题：{ex}"
    if p["type"] == "frequency":
        return f"优先复用已验证的做法：{ex}"
    return f"按此标准流程执行：{ex}"


def suggest(store: Store, exps: list[dict]) -> list[dict]:
    """跑检测器 → 与已有建议卡去重 → 落 insights.jsonl。返回新增建议卡。

    去重/降权语义（W4-02）：同 type+trunk 已有未处理卡 → 不重复提示；
    被用户忽略过（action=dismissed）的同 type+trunk → 永久降权不再提示。
    """
    existing = store.load_insights()
    unhandled = [c for c in existing if not c.get("action")]
    dismissed = {(c.get("type"), c.get("trunk")) for c in existing
                 if c.get("action") == "dismissed"}
    open_keys = {(c.get("type"), c.get("trunk")) for c in unhandled}

    # 蒸馏兜底方案方向二：模型可用时口语化润色，不可用/失败回落模板句。
    # 复用 llm.model_available 统一 switcher（防歪 #11：严禁各写一套可用性判定）；
    # rewrite_text 内部以模板句为锚（防歪 #12），无模型/异常时与现状逐字一致。
    polish = llm.model_available(store)
    new_cards: list[dict] = []
    for p in patterns.detect_all(exps):
        key = (p["type"], p.get("trunk", ""))
        if key in dismissed or key in open_keys:
            continue
        text = rewrite_text(store, p) if polish else _template_sentence(p)
        card = {
            "id": f"ins-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{len(new_cards)}",
            "type": p["type"], "trunk": p.get("trunk", ""), "category": p.get("category", ""),
            "example": p.get("example", ""), "occurrences": p.get("occurrences", 2),
            "evidence": p.get("evidence", []),
            "text": text, "rule_text": _rule_text(p),
            "action": None, "ts": utcnow(),
        }
        store.append_insight(card)
        new_cards.append(card)
        open_keys.add(key)
        if len(unhandled) + len(new_cards) >= MAX_UNHANDLED:
            break
    return new_cards


def _template_sentence(p: dict) -> str:
    tpl = TEMPLATE_SENTENCES.get(p["type"], "检测到一个重复模式。")
    try:
        return tpl.format(example=p.get("example", ""), n=p.get("occurrences", 2),
                          trunk=p.get("trunk", ""), category=p.get("category", ""))
    except (KeyError, IndexError, ValueError):
        return tpl


def rewrite_text(store: Store, p: dict) -> str:
    """LLM 口语化改写（可降级）：失败/未配置模型 → 规则模板句。"""
    base = _template_sentence(p)
    try:
        from ..distill import llm

        raw = llm.call_model(store, [{"role": "user", "content": REWRITE_PROMPT.format(
            type=p["type"], trunk=p.get("trunk", ""), category=p.get("category", ""),
            example=p.get("example", ""), n=p.get("occurrences", 2))}])
        line = (raw or "").strip().splitlines()
        return line[0].strip() if line and line[0].strip() else base
    except Exception:
        return base


def apply_card(store: Store, card: dict) -> dict:
    """应用：写入 rules（红线语义 → hard-hook；其余 → always）+ 打标 applied。"""
    trigger = "hard-hook" if card.get("type") == "correction" else "always"
    rule = {
        "id": f"insight-{card['id']}",
        "name": f"洞察：{card.get('example', '')[:40]}",
        "text": card.get("rule_text", ""),
        "trigger": trigger,
        "source": "insight",
        "enabled": True,
    }
    store.upsert_rule(rule)
    store.update_insight(card["id"], {"action": "applied", "acted_at": utcnow()})
    return rule


def dismiss_card(store: Store, card_id: str) -> None:
    store.update_insight(card_id, {"action": "dismissed", "acted_at": utcnow()})


def defer_card(store: Store, card_id: str, card: dict | None = None) -> None:
    """稍后再说：进通知中心轻量提醒区（insight 类型），卡保持未处理。"""
    store.update_insight(card_id, {"action": "deferred", "acted_at": utcnow()})
    card = card or {}
    try:
        from .. import notify

        notify.push(store, "system_notice",
                    title=f"洞察待处理：{card.get('example', '')[:40]}",
                    body=card.get("text", ""))
    except Exception as exc:  # 通知失败不影响主流程
        logger.warning("洞察通知推送失败: %s", exc)


def unhandled_cards(store: Store, limit: int = 2) -> list[dict]:
    """GUI 首页"洞察"行：最多 limit 条未处理（action=None）。

    deferred = 用户已选"稍后再说"（已进通知中心提醒）→ 不再占首页位。
    """
    out = []
    for c in store.load_insights():
        if c.get("action") is None:
            out.append(c)
        if len(out) >= limit:
            break
    return out
