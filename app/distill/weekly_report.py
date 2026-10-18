"""周日结算四段式叙事 + 成就体系（产品文档 ，并入成长报告通知）。

磨合度不走冷指标汇报，周日以固定四段叙事结算：
1. 主句（带方向）：只写有变化的类别
2. 人话四问（只答有信号的）：做对了吗 / 更快了吗 / 哪条经验在变强 / 有没有用错地方
3. 里程碑（仅"新高"周出现）：具象叙事 + 成就标题
4. 休整（中性）：本周无新任务的类别一句话带过，回落不推送警报

成就（最小 PBL，绑真实挑战）：
- 老练（按 category）：磨合差值 ≥1 且持续 2 周
- 避坑达人（按 category）：一个已固化失败模式连续 4 周未复现
- 传承：一次转 Skill 导出
成就只在周报内展示 + 可导出，不单独推送（周日无报告可发时顺延下个工作日
10:00，仍计入当日 2 条上限）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from ..time_util import parse_ts, week_start

from ..proxy.inject import normalize_marks, parse_playbook
from ..store.store import affinity_display, utcnow
from . import dedupe, gate, gsignal

logger = logging.getLogger("experientia.distill.weekly")

ACHIEVEMENTS_FILE = "achievements.json"

# 成就定义（键 = 机器名；展示名走 i18n）
ACHIEVEMENT_VETERAN = "veteran"          # 老练（按 category）
ACHIEVEMENT_PITAVOIDER = "pit_avoider"  # 避坑达人（按 category）
ACHIEVEMENT_LEGACY = "legacy"           # 传承

# 老练：磨合差值 ≥1 且持续 2 周
VETERAN_DIFF_THRESHOLD = 1
VETERAN_WEEKS = 2
# 避坑达人：已固化失败模式连续 4 周未复现
PITAVOIDER_WEEKS = 4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _week_start(now: datetime | None = None) -> datetime:
    """本周一 00:00（UTC）——周日结算的"本周"窗口起点。

    去重 R1：周起点计算交 time_util.week_start（与 store/growth.py 的 `_week_of`
    原先是同一算式的两份实现），此处只负责把 date 补成 aware datetime。
    """
    d = week_start(now or _now())
    if d is None:  # 理论上不会发生（入参必为 datetime），兜底避免 None 参与构造
        d = _now().date()
    return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)


def _in_week(ts: str | None, start: datetime, end: datetime) -> bool:
    t = parse_ts(ts)
    if t is None:
        return False
    return start <= t < end


def _display(key: str) -> str:
    """类别键 → 展示名。2 段 `trunk/category` → 类别名（不写项目名）；
    3 段 `agent/trunk/category`（磨合度按 agent 拆分，M2）→ `agent · category`。
    委托 store.affinity_display（单一口径，防两处解析漂移）。"""
    return affinity_display(key)


# ---------- 成就存取（achievements.json） ----------

def _load_achievements(store) -> dict:
    pathf = store.data_dir / ACHIEVEMENTS_FILE
    if not pathf.exists():
        return {}
    try:
        data = json.loads(pathf.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _save_achievements(store, data: dict) -> None:
    store._write_json_tmp_rename(store.data_dir / ACHIEVEMENTS_FILE,
                                 data, indent=2)


def load_achievements(store) -> list[dict]:
    """对外：全部成就记录（{id, type, scope, unlocked_at, detail}），新在前。"""
    return sorted(_load_achievements(store).values(),
                  key=lambda a: str(a.get("unlocked_at", "")), reverse=True)


def _sessions_in_week(store, start: datetime, end: datetime) -> list[dict]:
    return [s for s in store.list_sessions()
            if _in_week(str(s.get("started_at") or ""), start, end)]


def _check_veteran(store, aff: dict) -> list[dict]:
    """老练（按 agent·category，M2）：磨合差值 ≥1 且持续 2 周（本周与上周都有实例）。"""
    now = _now()
    start = _week_start(now)
    # 键须与 growth_summary 的 affinity 键同形（agent/trunk/category，M2）
    this_week = {f"{s.get('agent') or 'unknown'}/{s.get('trunk')}/"
                 f"{s.get('category')}"
                 for s in _sessions_in_week(store, start, now + timedelta(seconds=1))}
    prev_week = {f"{s.get('agent') or 'unknown'}/{s.get('trunk')}/"
                 f"{s.get('category')}"
                 for s in _sessions_in_week(store, start - timedelta(days=7),
                                            start)}
    out = []
    for key, a in aff.items():
        if a.get("level") == "待积累" or a.get("excluded"):
            continue
        if int(a.get("diff") or 0) < VETERAN_DIFF_THRESHOLD:
            continue
        if key in this_week and key in prev_week:
            out.append({"id": f"veteran/{key}", "type": ACHIEVEMENT_VETERAN,
                        "scope": key, "detail": {"diff": a.get("diff")}})
    return out


def _check_pit_avoider(store) -> list[dict]:
    """避坑达人（按 category）：一个已固化失败模式连续 4 周未复现。

    确定性口径：playbook 有 [Solidified] 行，且 4 周窗口内该类别没有与之
    近重复的新低 G 经验（没再踩这个坑）。"""
    now = _now()
    start = _week_start(now) - timedelta(weeks=PITAVOIDER_WEEKS - 1)
    out = []
    for s in store.list_skills():
        trunk, category = s["trunk"], s["category"]
        md = store.read_skill(trunk, category) or ""
        sections = parse_playbook(md)
        solid_lines = [ln for ln in sections.get("失败模式", "").splitlines()
                       if normalize_marks(ln).startswith(f"- {gate._STATE_MARK['solid']}")]
        if not solid_lines:
            continue
        recent_fail = [e for e in store.iter_experiences(
            trunk=trunk, category=category, include_distilled=True)
            if (gsignal.is_rule(e)
                    or float(e.get("G") or 0) < gsignal.G_MIN_INJECT
                    or e.get("corrected"))
            and _in_week(str(e.get("ts") or ""), start, now + timedelta(seconds=1))]
        for ln in solid_lines:
            desc = gate._strip_count(gate._line_body(ln))
            if not desc or desc in ("（无）", "(无)"):
                continue
            if not any(dedupe.near_dup(desc, gate._match_text(e))
                       for e in recent_fail):
                out.append({"id": f"pit_avoider/{trunk}/{category}/{desc[:20]}",
                            "type": ACHIEVEMENT_PITAVOIDER,
                            "scope": f"{trunk}/{category}",
                            "detail": {"text": desc[:60]}})
                break  # 每类别只解锁一次
    return out


def _check_legacy(store) -> list[dict]:
    """传承：一次转 Skill 导出（changelog 留痕含"导出"与"skill"）。"""
    for rec in store.list_changelog()[-200:]:
        text = str(rec.get("text", "")) if isinstance(rec, dict) else str(rec)
        if "导出" in text and "skill" in text.lower():
            return [{"id": "legacy/once", "type": ACHIEVEMENT_LEGACY,
                     "scope": "global", "detail": {}}]
    return []


def check_achievements(store) -> list[dict]:
    """全量成就判定，返回**新解锁**的成就（已解锁的跳过，幂等）。"""
    data = _load_achievements(store)
    existing = {a["id"] for a in data.values()}
    summary = store.growth_summary(days=60)
    candidates = (_check_veteran(store, summary.get("affinity") or {})
                  + _check_pit_avoider(store) + _check_legacy(store))
    fresh = []
    for c in candidates:
        if c["id"] in existing:
            continue
        rec = {**c, "unlocked_at": utcnow()}
        data[c["id"]] = rec
        fresh.append(rec)
    if fresh:
        # 收口：成就文件读-改-写整体进 store 写锁（_load/_save 自身不持锁、
        # 无重入死锁；growth_summary/append_event 留锁外）。锁内重读最新再按 id
        # 合并，避免与并发解锁互相覆盖。
        with store.write_lock():
            latest = _load_achievements(store)
            for rec in fresh:
                latest.setdefault(rec["id"], rec)
            _save_achievements(store, latest)
        store.append_event(
            "ach", f"成就解锁 {len(fresh)} 个："
                   + "、".join(c["type"] for c in fresh[:3]),
            n=len(fresh))
    return fresh


# ---------- 周日结算叙事（口径收敛到 growth_story） ----------
#
# 重做：叙事不再就地拼 affinity 字符串，而是调 growth_story——
# 海报 / 通知 / App 内结算卡三处共用同一份 sections。旧版真机后果：主句永远为空
# （按类别的磨合差值在"全未分类"的库上算不出来）、四问被吞掉三问
# （injection.log 不存在时"哪条经验在变强"直接消失，用户不知道少了什么）。

def _active_agents(store, start: datetime, end: datetime) -> list[str]:
    """本周真正来干过活的助手（休整段用它，不再按"类别没新任务"播报）。"""
    return sorted({str(s.get("agent") or "unknown")
                   for s in _sessions_in_week(store, start, end)})


def _solid_new(store, start: datetime, end: datetime) -> tuple[int, list[str]]:
    """做对了吗：本周新固化的失败模式（gate 判 solid 且 last_seen 落在本周）。"""
    found = []
    for sk in store.list_skills():
        key = f"{sk['trunk']}/{sk['category']}"
        for body, st in gate.failure_mode_states(
                store, sk["trunk"], sk["category"]).items():
            if st["state"] == "solid" and _in_week(st["last_seen"], start, end):
                found.append(f"{_display(key)} · {gate._strip_count(body)[:30]}")
    return len(found), found[:3]


def _strongest(store, start: datetime, end: datetime) -> str:
    """哪条经验在变强：本周被注入命中 Top1 的类别名（无注入日志 → 空串）。"""
    hits: dict[str, int] = {}
    for rec in store.read_injection(start, end):
        key = f"{rec.get('trunk')}/{rec.get('category')}"
        hits[key] = hits.get(key, 0) + 1
    if not hits:
        return ""
    return _display(max(hits.items(), key=lambda kv: kv[1])[0])


def _hook_state(store) -> dict:
    """回灌通道状态（读不到就当未知——它只影响一句提示，不该阻断结算）。"""
    try:
        from ..capture import hook as hook_channel
        return hook_channel.hook_status(store=store) or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("hook 状态读取失败（按未知处理）: %s", exc)
        return {}


def _story(store, *, unlocked: list[dict] | None = None) -> dict:
    """组一份本周结算叙事（只读；成就判定由调用方决定要不要跑）。

    成长叙事属**归纳类**内容，与「未接入模型：归纳类内容（方法正文 / 成长叙事 /
    AI 重写）不可用」的对外口径一致——无模型时 `growth_story.build` 返回叙事各段
    皆空的同形结构（`content_source="none"`），周日不再推送叙事。

    传的是**三态**不是布尔：`llm.model_state` 区分"压根没配"与"配了连不上"，
    结算卡据此给不同的下一步（去接入 / 去检查端点），而不是一句通用空话。
    """
    from . import growth_story, llm

    now = _now()
    start, end = _week_start(now), now
    g = store.growth_summary(days=60)
    n_solid, solid_names = _solid_new(store, start, end)
    active = _active_agents(store, start, end)
    story = growth_story.build(
        g, unlocked=unlocked or [], active_agents=active, solid_new=n_solid,
        solid_names=solid_names, strongest=_strongest(store, start, end),
        hook=_hook_state(store),
        model_state=llm.model_state(store),
        endpoint=llm.model_endpoint(store))
    return {
        "week": start.strftime("%Y-%m-%d"),
        "sections": growth_story.sections_text(story),
        "story": story,
        "active": bool(active),
    }


def peek(store) -> dict:
    """App 内结算卡用：**只读**（不判成就、不写 achievements.json、不推通知）。

    与 build_report 的区别只在副作用——GUI 每次打开结算卡都会调它。"""
    out = _story(store, unlocked=[{**a, "fresh": False}
                                  for a in load_achievements(store)])
    out["achievements"] = []
    return out


def build_report(store) -> dict:
    """组装周日结算（daemon 用；会跑成就判定并按幂等落盘）。"""
    fresh = check_achievements(store)
    fresh_ids = {a["id"] for a in fresh}
    out = _story(store, unlocked=[{**a, "fresh": a.get("id") in fresh_ids}
                                  for a in load_achievements(store)])
    out["achievements"] = fresh
    return out


def has_content(report: dict) -> bool:
    """周日是否值得推送：本周确有活动，且主句/四问任一非空（纯休整周不打扰）。

    里程碑（新解锁成就）不计入：成就只在周报内展示、不单独推送——
    只有成就没有主内容的周，报告顺延下个工作日 10:00 补发。"""
    if not report.get("active"):
        return False
    return any(report["sections"].get(k) for k in ("main", "questions"))


def _ach_names(ach: list[dict]) -> str:
    """成就机器键 → 人话名（旧版把 pit_avoider 原样推给用户）。"""
    from . import growth_story

    return "、".join(growth_story.ACH_NAME.get(str(a.get("type")),
                                             str(a.get("type") or ""))
                     for a in ach)


def maybe_run(store) -> dict | None:
    """daemon 每日调用：周日跑一次结算并推送（≤1 条/周，并入 growth_report）。

    周日无报告可发但解锁了新成就 → 顺延下个工作日 10:00（里程碑
    不占额外名额，仍计入当日 2 条上限）。"""
    from .. import notify

    st = notify.state_get(store, "weekly") or {}
    now = _now()
    week_id = _week_start(now).strftime("%Y-W%V")
    if st.get("week_id") == week_id:
        return None  # 本周已处理
    if now.weekday() == 6:  # 周日（UTC）
        report = build_report(store)
        if has_content(report):
            body = "\n".join(
                ln for k in ("main", "questions", "milestones", "rest")
                for ln in report["sections"][k])
            first = (report["sections"]["main"] or ["这周没有新变化"])[0]
            notify.push(store, "growth_report", f"本周结算：{first}",
                        body, target="growth")
            notify.state_patch(store, "weekly",
                               week_id=week_id,
                               sent=now.date().isoformat())
        elif report["achievements"]:
            notify.state_patch(store, "weekly",
                               week_id=week_id, sent=None,
                               pending=[a["id"] for a in report["achievements"]])
        else:
            notify.state_patch(store, "weekly",
                               week_id=week_id, sent=None)
        return report
    # 工作日 10:00 后：补发顺延的成就
    pending = st.get("pending")
    if pending and now.weekday() < 5 and now.hour >= 10:
        data = _load_achievements(store)
        body = _ach_names([a for a in data.values() if a["id"] in pending])
        notify.push(store, "growth_report", "上周解锁的成就", body or "成就解锁",
                    target="growth")
        notify.state_patch(store, "weekly", pending=None)
    return None
