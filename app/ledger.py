"""AI 员工账本（修复方案首屏大数字行）：纯本地统计，零 LLM、零网络。

无模型时产品的第一身份 = 账本：agent 们干了多少活、烧了多少钱（估算）、
留下多少坑卡。钱用静态价格表（assets/models_pricing.json，随包分发、
季度人工更新），表里没有的模型计入"未计价"，UI 一律标"估算"。
本地模型（gguf/ollama/localhost 端点口粮）成本记 0。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# USD / 百万 token，(输入, 输出)。近似值——展示必须带"估算"字样。
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet": (3.0, 15.0),
    "claude-opus": (15.0, 75.0),
    "claude-haiku": (0.8, 4.0),
    "gpt-5": (1.25, 10.0),
    "gpt-4.1": (2.0, 8.0),
    "o3": (10.0, 40.0),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.50),
    "deepseek": (0.27, 1.10),
}
_LOCAL_HINT_RE = re.compile(r"(\.gguf|ollama|localhost|127\.0\.0\.1|lm\.?studio|qwen3|glm-)", re.I)
_PRICING_FILE = Path(__file__).resolve().parents[1] / "assets" / "models_pricing.json"


def load_pricing() -> dict[str, tuple[float, float]]:
    """内置表打底 + 资产文件逐键覆盖（可配性走文件，不新增 config 孤儿键）。"""
    table = dict(DEFAULT_PRICING)
    try:
        raw = json.loads(_PRICING_FILE.read_text(encoding="utf-8"))
        for k, v in (raw.get("usd_per_mtok") or {}).items():
            if isinstance(v, list) and len(v) == 2:
                table[str(k).lower()] = (float(v[0]), float(v[1]))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass  # 文件缺失/损坏 → 内置表兜底，账本不炸
    return table


def price_for(model: str, table: dict[str, tuple[float, float]] | None = None) -> tuple[float, float] | None:
    """模型名 → (输入价, 输出价)；本地模型 (0,0)；识别不了 None（计入未计价）。"""
    name = str(model or "").lower()
    if not name:
        return None
    if _LOCAL_HINT_RE.search(name):
        return (0.0, 0.0)
    table = table or load_pricing()
    for key, price in table.items():
        if key and key in name:
            return price
    return None


def compute(store) -> dict:
    """账本计数 + 口径元数据（首屏只展示其中三个数字，花费估算仍由
    `experientia stats` 使用）。纯读 sessions/experiences，异常由调用方兜。"""
    sessions = store.list_sessions()
    table = load_pricing()
    total_in = total_out = 0
    unsplit_tokens = 0
    cost = 0.0
    priced_sessions = 0
    for s in sessions:
        ti = int(s.get("tokens_in") or 0)
        to = int(s.get("tokens_out") or 0)
        legacy = int(s.get("tokens") or 0)
        total_in += ti
        total_out += to
        if not ti and not to and legacy:
            unsplit_tokens += legacy
        p = price_for(str(s.get("model") or ""), table)
        if p is not None:
            pin, pout = p
            si = ti + (int(legacy * 0.8) if not ti and not to else 0)
            so = to + (legacy - int(legacy * 0.8) if not ti and not to else 0)
            cost += (si * pin + so * pout) / 1_000_000
            if si or so:
                priced_sessions += 1
    rounds = sum(int(s.get("req_count") or 0) for s in sessions)
    rule_cards = 0
    injectable = 0
    for e in store.iter_experiences(include_distilled=True):
        if e.get("g_source") == "rule":
            rule_cards += 1
            if float(e.get("G") or 0) >= 0.5:  # iter 读取视图已含复现升档
                injectable += 1
    total_tokens = total_in + total_out + unsplit_tokens
    return {
        "sessions": len(sessions),
        "rounds": rounds,
        "tokens": total_tokens,
        "cost_usd_est": round(cost, 4),
        "cost_priced_share": (priced_sessions / len(sessions)) if sessions else 0.0,
        "rule_cards": rule_cards,
        "rule_injectable": injectable,
        "pending_fragments": len(store.load_pending_reviews()),
    }
