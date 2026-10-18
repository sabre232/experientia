"""失败模式双门 / 成功要点复现门（产品文档  /）。

确定性规则，零 LLM 成本。门在调用方（审计口径）：playbook 里的
ASCII 标记只是上一次蒸馏的快照，权威三态由本模块从经验数据实时复算——
写路径（distill 重打标记）与读路径（失败模式页 /api/failure-modes）
共用同一组函数，防口径漂移。

失败模式三态（修复方案修订）：
- 观察中 watch：计数 <3，只记录不注入；30 天无新出现 → 观察过期（不再累计）
- 待验证 pending：计数 ≥3 但复现未过（不注入；旧「≥6 自动固化」直通门已废除）
- 已固化 solid：计数门 + 复现门（其后有同类成功任务或用户 L1"有效"）
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from ..time_util import parse_ts

from ..proxy.inject import (FAILURE_PENDING_MARK, FAILURE_SOLID_MARK,
                            FAILURE_WATCH_MARK, NEW_POINT_MARK,
                            normalize_marks, parse_playbook)
from . import dedupe, gsignal

_COUNT_RE = re.compile(r"（出现\s*(\d+)\s*次）")


def _strip_count(text: str) -> str:
    return _COUNT_RE.sub("", text).strip()


def _line_body(line: str) -> str:
    """失败模式行 → 正文（去 bullet、去三态标记，保留"（出现 N 次）"）。"""
    line = normalize_marks(line.strip())
    for mark in (FAILURE_SOLID_MARK, FAILURE_PENDING_MARK, FAILURE_WATCH_MARK):
        line = line.replace(mark, "")
    return line.lstrip("- ").strip()


def _marked_count(line: str) -> int:
    m = _COUNT_RE.search(_line_body(line))
    return int(m.group(1)) if m else 0


def _ts_key(e: dict) -> str:
    return str(e.get("ts", ""))


def _days_since(ts: str, now: datetime | None = None) -> int | None:
    t = parse_ts(ts)
    if t is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, (now - t).days)


def _low_experiences(store, trunk: str, category: str) -> list[dict]:
    """失败候选池：低 G 或被用户纠正的经验 + rule 源坑卡（恒属失败域，
    复现升档后也不外出——它是"坑被再次踩到"的铁证，不是成功经验）。"""
    out = []
    for e in store.iter_experiences(trunk=trunk, category=category,
                                    include_distilled=True):
        if gsignal.is_rule(e) or float(e.get("G") or 0) < gsignal.G_MIN_INJECT \
                or e.get("corrected"):
            out.append(e)
    return out


def _ok_experiences(store, trunk: str, category: str) -> list[dict]:
    """同类成功任务：G ≥0.5、未被纠正且非 rule 源的经验（复现门①的证据）。"""
    out = []
    for e in store.iter_experiences(trunk=trunk, category=category,
                                    include_distilled=True):
        if gsignal.high_value_eligible(e) and not e.get("corrected"):
            out.append(e)
    return out


def _state_for(desc: str, backing: list[dict], ok_ts: list[str],
               count_fallback: int = 0) -> dict | None:
    """单条失败模式的三态判定（双门核心，供 playbook 行与新生成行共用）。"""
    if not desc or desc in ("（无）", "(无)"):
        return None
    if backing:
        count = sum(int(e.get("count") or 1) for e in backing)
        last_seen = max(_ts_key(e) for e in backing)
    else:
        count = count_fallback  # 无支撑经验（模型抽象行）→ 行内标注次数
        last_seen = ""
    repro_clear = bool(last_seen) and any(t > last_seen for t in ok_ts)
    user_valid = any(e.get("g_source") == "user"
                     and float(e.get("G") or 0) >= gsignal.L1_VALID
                     for e in backing)
    # rule 复现即铁证：同坑跨 ≥3 会话被再踩（读取侧 effective_g 升档）——
    # 结构事实的"复现门"内置在计数里，不依赖同类成功轨迹佐证
    rule_repro = any(gsignal.is_rule(e)
                     and gsignal.effective_g(e) >= gsignal.G_MIN_INJECT
                     for e in backing)
    if count < gsignal.FAILURE_SOLIDIFY_COUNT:
        state = "watch"
    elif repro_clear or user_valid or rule_repro:
        # 死锁直通门已废除（修复方案）：光"出现次数多"永不等于可信——
        # 曾把"引号笔误（出现 14 次）"这类噪音推成唯一固化注入项。
        # 固化必须过复现门（同类成功/用户 L1/rule 跨会话复现）。
        state = "solid"
    else:
        state = "pending"
    days = _days_since(last_seen)
    return {
        "count": count,
        "last_seen": last_seen or None,
        "state": state,
        "expired": state == "watch" and days is not None
                   and days >= gsignal.FAILURE_OBSERVE_EXPIRE_DAYS,
        "user_valid": user_valid,
        "repro_clear": repro_clear,
    }


def _match_text(e: dict) -> str:
    """三态回撑匹配文本：rule 卡的 playbook 行正文是模板句
    （mining.rule_line_text），普通经验是 action/state 原文——两侧口径
    必须一致，否则支撑丢失、三态永远算不到 solid。"""
    if gsignal.is_rule(e):
        from . import mining

        return mining.rule_line_text(e)
    return str(e.get("action") or e.get("state") or "")


def failure_mode_states(store, trunk: str, category: str) -> dict[str, dict]:
    """playbook 每条失败模式行 → 实时三态（键 = 行正文，含"（出现 N 次）"）。

    找不到支撑经验的行（模型抽象后与原文不再近重复）回落行内标注次数、
    last_seen 取该类别最近一次低 G 经验（保守：不算复现通过）。
    """
    md = store.read_skill(trunk, category) or ""
    sections = parse_playbook(md)
    lines = [raw for raw in sections.get("失败模式", "").splitlines()
             if raw.strip().startswith("-")]
    if not lines:
        return {}
    low = _low_experiences(store, trunk, category)
    ok_ts = [_ts_key(e) for e in _ok_experiences(store, trunk, category) if _ts_key(e)]
    fallback_seen = max((_ts_key(e) for e in low), default="")
    out: dict[str, dict] = {}
    for raw in lines:
        body = _line_body(raw)
        desc = _strip_count(body)
        backing = [e for e in low if dedupe.near_dup(desc, _match_text(e))]
        if not backing:
            backing = []
            last = _state_for(desc, [], ok_ts, _marked_count(raw))
            if last:
                last["last_seen"] = fallback_seen or None
                days = _days_since(fallback_seen)
                last["expired"] = last["state"] == "watch" and days is not None \
                    and days >= gsignal.FAILURE_OBSERVE_EXPIRE_DAYS
                out[body] = last
            continue
        st = _state_for(desc, backing, ok_ts)
        if st:
            out[body] = st
    return out


_STATE_MARK = {
    "watch": FAILURE_WATCH_MARK,
    "pending": FAILURE_PENDING_MARK,
    "solid": FAILURE_SOLID_MARK,
}


def remark_line(desc: str, st: dict) -> str:
    """按三态生成失败模式行：标记 + 实时计数（机器判定，模型只写正文）。"""
    if st["expired"]:
        return f"- {FAILURE_WATCH_MARK} {desc}（观察过期）"
    return f"- {_STATE_MARK[st['state']]} {desc}（出现 {st['count']} 次）"


def remark_failure_section(md: str, states: dict[str, dict]) -> str:
    """把 playbook 失败模式节的所有行重打为实时三态标记（其余节原样）。"""
    out, in_sec = [], False
    for line in (md or "").splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_sec = s[3:].strip() == "失败模式"
            out.append(line)
            continue
        if in_sec and s.startswith("-"):
            body = _line_body(line)
            st = states.get(body)
            if st is not None:
                out.append(remark_line(_strip_count(body), st))
                continue
        out.append(line)
    return "\n".join(out) + ("\n" if (md or "").endswith("\n") else "")


# ---------- 成功要点复现门（与失败模式双门同源） ----------

def remark_success_points(md: str, store, trunk: str, category: str) -> str:
    """成功要点行按来源轨迹数打标：≥2 条来源 = 已复现（去标记转正），
    仅 1 条来源 = 新要点·待复现（注入权重降半）。

    匹配口径与失败模式一致（要点行 vs 高 G 经验 action/state 近重复）；
    找不到任何来源的要点行保持原样（可能是用户手改的资产，不越权动）。
    """
    md = normalize_marks(md or "")
    sections = parse_playbook(md)
    points = [raw for raw in sections.get("成功要点", "").splitlines()
              if raw.strip().startswith("-")]
    if not points:
        return md
    high = _ok_experiences(store, trunk, category)
    mark_map: dict[str, bool] = {}  # 行正文（去标记）→ 是否新要点
    for raw in points:
        body = normalize_marks(raw.strip()).replace(NEW_POINT_MARK, "")
        body = body.lstrip("- ").strip()
        desc = _strip_count(body)
        n_src = sum(1 for e in high
                    if dedupe.near_dup(desc, e.get("action") or e.get("state") or ""))
        if n_src:
            mark_map[body] = n_src < gsignal.SUCCESS_POINT_PROMOTE_COUNT
    if not mark_map:
        return md
    out, in_sec = [], False
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_sec = s[3:].strip() == "成功要点"
            out.append(line)
            continue
        if in_sec and s.startswith("-"):
            body = normalize_marks(s).replace(NEW_POINT_MARK, "")
            body = body.lstrip("- ").strip()
            fresh = mark_map.get(body)
            if fresh is True:
                out.append(f"- {NEW_POINT_MARK} {body}")
            elif fresh is False:
                out.append(f"- {body}")
            else:
                out.append(line)  # 无来源可核（含用户手改行）→ 原样
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if md.endswith("\n") else "")


def remark_playbook(md: str, store, trunk: str, category: str) -> str:
    """蒸馏写盘前的机器复标（失败模式三态 + 成功要点复现门，一次调用）。"""
    md = remark_failure_section(md, failure_mode_states(store, trunk, category))
    md = remark_success_points(md, store, trunk, category)
    return md


def solid_backed_session_ids(store, trunk: str, category: str,
                             batch: list[dict]) -> set[tuple[str, str]]:
    """：固化回填的严格双门口径。

    返回本蒸馏批次中实际支撑「已固化」失败模式的经验来源 (agent, session_id)
    集合——该行已过计数门 + 复现门。无固化产出 → 空集，
    源复盘节点不标 solidified（蒸馏仅有 [Watching]/[Pending] 产出时，
    学习历程不再提前显示「已固化」）。
    """
    try:
        states = failure_mode_states(store, trunk, category)
    except Exception:
        return set()
    solid_descs = [_strip_count(body) for body, st in states.items()
                   if st.get("state") == "solid"]
    if not solid_descs:
        return set()
    out: set[tuple[str, str]] = set()
    for e in batch:
        if not (e.get("agent") and e.get("session_id")):
            continue
        act = _match_text(e)
        if any(dedupe.near_dup(d, act) for d in solid_descs):
            out.add((str(e["agent"]), str(e["session_id"])))
    return out
