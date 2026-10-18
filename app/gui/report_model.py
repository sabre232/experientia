"""报告数据模型：成长 / 方法论两份结构化模型。

应用内弹层（report_view）与导出 md（distill/export.py）共用同一套"从原始
数据抽结构"的口径：这里只做确定性抽取与排序，不花模型调用、不做文案
（文案在视图层按当前语言拼）。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..time_util import parse_ts

from .i18n import t

# 里程碑庆祝窗口：最近 7 天内解锁才算"新高"（——旧成就常驻不重复庆祝）
_MILESTONE_WINDOW_DAYS = 7


def _unlocked_recently(rec: dict) -> bool:
    when = parse_ts(rec.get("unlocked_at"))
    if when is None:
        return False
    return when >= datetime.now(timezone.utc) - timedelta(
        days=_MILESTONE_WINDOW_DAYS)

# ---------- 方法论（playbook md → 结构） ----------

_HEAD_KEYS = ("name", "version", "updated", "created", "source_exps", "confidence",
              "content_source", "generated_at")

# 报告展示顺序：流程/要点/坑在前，治理性两节（过时/偏好）垫底
_SECTION_ORDER = ("标准流程", "成功要点", "失败模式", "过时项标记", "偏好增量")


def _head_value(md: str, key: str) -> str | None:
    m = re.search(rf"^>\s*{key}:\s*(.+?)\s*$", md, re.M)
    if not m:
        return None
    v = m.group(1).strip()
    return v or None


def parse_playbook(md: str) -> dict:
    """playbook md → 方法论报告模型。

    sections：展示节名 → 条目行列表（去掉 "- " 前缀，空/（无）→ 空列表）。
    """
    head = {k: _head_value(md, k) for k in _HEAD_KEYS}
    src = head.get("source_exps") or ""
    src_ids = [x for x in src.split(",") if x.strip() and x.strip() != "（无）"]
    sections: dict[str, list[str]] = {}
    for m in re.finditer(r"^##\s+(.+?)\s*\n(.*?)(?=^##\s|\Z)", md, re.M | re.S):
        name = m.group(1).strip()
        lines = []
        for ln in m.group(2).splitlines():
            s = ln.strip()
            if not s or s in ("（无）", "(无)"):
                continue
            s = re.sub(r"^([-*]|\d+\.)\s+", "", s).strip()
            if s:
                lines.append(s)
        sections[name] = lines
    return {
        "head": head,
        "source_n": len(src_ids),
        "sections": sections,
        "md": md,
    }


def method_sections(model: dict) -> list[tuple[str, list[str]]]:
    """按 _SECTION_ORDER 输出非空节（治理性两节为空时不展示）。"""
    out = []
    for name in _SECTION_ORDER:
        lines = model["sections"].get(name) or []
        if lines:
            out.append((name, lines))
    return out


# ---------- 成长（growth_summary 响应 → 结构） ----------

def growth_report_model(g: dict) -> dict:
    """growth API 响应 → 成长报告模型（只抽数据，文案在视图层拼）。

    affinity 排序：有对比数据的在前（磨合度高→中→低），待积累垫底；
    heat_vals = 最近 14 天全部主干 G 加权和逐日合计（报告里的 14 格条）。
    """
    days = int(g.get("days") or 30)
    cum = g.get("cumulative") or {}
    curves = [{"key": k, "total": int(s[-1][1]) if s else 0, "series": s}
              for k, s in sorted(cum.items(), key=lambda kv: -kv[1][-1][1])]
    total = sum(c["total"] for c in curves)
    trunk_split: dict[str, int] = {}
    for c in curves:
        trunk = c["key"].split("/")[0]
        trunk_split[trunk] = trunk_split.get(trunk, 0) + c["total"]

    aff = g.get("affinity") or {}
    level_rank = {"高": 0, "中": 1, "低": 2}
    with_data = {k: a for k, a in aff.items() if a.get("level") != "待积累"}
    pending = {k: a for k, a in aff.items() if a.get("level") == "待积累"}
    affinity = (
        [{"key": k, **a} for k, a in sorted(
            with_data.items(),
            key=lambda kv: (level_rank.get(kv[1].get("level"), 9), kv[0]))]
        + [{"key": k, **a} for k, a in sorted(pending.items(), key=lambda kv: kv[0])]
    )
    # 平均改善（v2）：只取 diff≥1（变好）且非负例的类别；没有 → None
    improved = [int(a.get("diff") or 0) for a in with_data.values()
                if not a.get("excluded") and int(a.get("diff") or 0) >= 1]
    avg_diff = round(sum(improved) / len(improved)) if improved else None
    # 旧口径保留（百分比辅助，防调用方断裂）
    neg = [a["rounds_pct"] for a in with_data.values()
           if a.get("rounds_pct") is not None and a["rounds_pct"] < 0]
    avg_rounds_pct = round(sum(neg) / len(neg)) if neg else None

    hm = g.get("heatmap") or {}
    dates = hm.get("dates") or []
    grid = hm.get("grid") or {}
    n_days = len(dates)
    heat_vals = [sum((grid.get(t) or [0.0] * n_days)[i]
                     for t in grid) for i in range(n_days)] if grid else []

    # 结算叙事（单一口径）：海报/周报/App 内结算卡共用 growth_story。
    # 旧字段（affinity/curves/heat_vals）原样保留——notify 与既有测试仍依赖。
    from ..distill import growth_story

    # 叙事在展示侧本地化：海报 / 结算卡拿到的就是成品字符串
    story = growth_story.localize(
        growth_story.build(g, unlocked=[{**a, "fresh": _unlocked_recently(a)}
                                        for a in (g.get("achievements") or [])]),
        t)

    return {
        "days": days,
        "total": total,
        "trunk_split": sorted(trunk_split.items(), key=lambda kv: -kv[1]),
        "affinity": affinity,
        "curves": curves,
        "heat_dates": dates,
        "heat_vals": heat_vals,
        "avg_diff": avg_diff,
        "avg_rounds_pct": avg_rounds_pct,
        "story": story,
        # 内容溯源（总纲 /）：原样透传，不做字段过滤—— 落库后
        # /api/growth 会带 content_source/generated_at，海报/周卡据此挂降级条。
        # 旧响应没有这两个字段 → 空串（来源未知，provenance_bar 返回 None，不打扰）。
        "content_source": str(g.get("content_source")
                              or (story.get("content_source") or "")),
        "generated_at": str(g.get("generated_at")
                            or (story.get("generated_at") or "")),
    }
