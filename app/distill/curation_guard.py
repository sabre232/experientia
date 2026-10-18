"""策展守卫（评估 /）：堵"经验→playbook"这步唯一无守卫的环节。

问题：`source_exps` 只留"id 串"，没有"playbook 哪一句来自哪一条经验"的逐句映射，
方法内容是否鲜活全靠 LLM 一次性总结的好坏，且无人核对是否坍缩/丢长尾。

落地（纯确定性、无 LLM、防错误传播 ——失败绝不阻断主蒸馏）：
1. 逐句来源映射：资产每一行尽力找到它"取材自哪条经验"（near_dup）。
   找不到任何来源依据的行 = 潜在臆造，单独剥出供审计/告警。
2. 内容保留守卫（防坍缩/防丢长尾，评估文档"无模型版 = merge 前后一致性 diff"）：
   - 新内容有源占比：新增行里能从来源经验/旧版找到依据的比例；
   - 旧版已固化条目保留度：[Solidified] 失败模式是否在新版仍有近重复，
     若无且无"过时项标记"淘汰声明 → 疑似坍缩。
守卫只判不杀——判"可疑"落 guard 事件 + 通知，回滚走每次蒸馏前已存的
deprecated 快照（30 天可恢复，规则 4）。
"""

from __future__ import annotations

from .dedupe import near_dup

SUSPICIOUS_UNSUPPORTED_RATIO = 0.5   # 新增行超一半无来源 → 可疑（可能臆造）
HEADING_MARK = "## "


def _section_of(line: str, in_sec: str) -> str:
    s = line.strip()
    if s.startswith(HEADING_MARK):
        return s[len(HEADING_MARK):].strip()
    return in_sec


def _meaningful_line(line: str) -> str:
    """剥掉行首标记/前缀，留"正文"用于近重复匹配。"""
    s = line.strip()
    if s.startswith("- "):
        s = s[2:].strip()
    # 剥 [Solidified]/[Pending]/[Watching]/[NewPoint] 等 ASCII 标记前缀
    import re as _re
    span = _re.match(r"\[[A-Za-z]+\]\s*", s)
    if span:
        s = s[span.end():].strip()
    return s


def line_sources(asset_text: str, experiences: list[dict]) -> list[dict]:
    """逐句来源映射：对资产每个有正文的行，返回 {line, section, supported, source_ids}。

    supported = 能从任一来源经验(action/state)或"它自己就带 G/出现次数等结构"
    找到依据。source_ids = 命中的经验 id 列表（近重复匹配）。"""
    pool = [(str(e.get("id") or ""), str(e.get("action") or e.get("state") or ""))
            for e in experiences]
    out: list[dict] = []
    section = ""
    for raw in (asset_text or "").splitlines():
        s = raw.strip()
        section = _section_of(s, section)
        if not s.startswith("- "):
            continue
        body = _meaningful_line(s)
        if not body:
            continue
        sid = [i for i, text in pool if text and near_dup(body, text)]
        out.append({"line": s, "section": section,
                    "supported": bool(sid), "source_ids": sid})
    return out


def _solidified_bodies(asset_text: str) -> list[str]:
    """资产 [Solidified] 失败的正文（旧版已固化的坑）。"""
    import re as _re
    out = []
    for s in (asset_text or "").splitlines():
        m = _re.match(r"\s*- \[Solidified\]\s*(.*?)\s*$", s)
        if m and m.group(1):
            out.append(m.group(1))
    return out


def _has_deprecation_declare(asset_text: str) -> bool:
    in_dep = False
    for s in (asset_text or "").splitlines():
        st = s.strip()
        if st.startswith(HEADING_MARK):
            in_dep = st[len(HEADING_MARK):].strip() == "过时项标记"
            continue
        if in_dep and st and st not in ("（无）", "(无)"):
            return True
    return False


def check_distill(new_md: str, old_md: str | None,
                  experiences: list[dict]) -> dict:
    """一次策展的自检报告。verdict: ok / suspicious。
    suspicious = 新增行多数无来源依据，或旧版已固化失败被整批丢弃且无淘汰声明。"""
    mapped = line_sources(new_md, experiences)
    meaningful = [m for m in mapped if any(x.strip() for x in m["line"][2:].split())]
    unsupported = [m for m in meaningful if not m["supported"]]

    new_solid = _solidified_bodies(new_md)
    old_solid = _solidified_bodies(old_md or "") if old_md else []
    # 旧版已固化、新版既无近重复、又无淘汰声明 → 疑似坍缩/丢长尾
    lost_solidified = [
        o for o in old_solid
        if not any(near_dup(o, n) for n in new_solid)
        and not _has_deprecation_declare(new_md)
    ]

    unsupported_ratio = (len(unsupported) / len(meaningful)) if meaningful else 0.0
    suspicious = (len(meaningful) >= 2 and unsupported_ratio > SUSPICIOUS_UNSUPPORTED_RATIO) \
        or bool(lost_solidified)
    return {
        "verdict": "suspicious" if suspicious else "ok",
        "lines": len(meaningful),
        "unsupported": [m["line"] for m in unsupported],
        "unsupported_ratio": round(unsupported_ratio, 2),
        "lost_solidified": lost_solidified,
    }