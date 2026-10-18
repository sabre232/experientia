"""`Store` 的「成长页」域 mixin（growth_summary / growth_panorama）。

从 `store.py` 拆出的第八个域。`growth_summary()`（231 行）与
`growth_panorama()`（173 行）是原 `class Store` 里最大的两个方法，成长页 / 周报 /
海报 / notify 都吃这一份口径。只做不动语义的搬家，约定与其余 mixin 一致：

1. 方法体逐字搬移，签名与返回值一律不变；
2. 共享状态（`data_dir`、`_iter_jsonl`、`_jsonl_signature`、`read_skill`、
   `_growth_cache`）留在 `Store` 主体，mixin 通过 `self` 访问，**不复制状态**；
3. 跨域小工具从 `._shared` 取；playbook 创建日期从 `.skill`
   取；绝不 import `store.py`（避免与 `class Store` 的组装形成循环导入）。

`growth_panorama()` 是模块级纯函数（不吃 `self`），成长页/周报都直接用它，故不
收进 mixin；`store.py` 侧保留同名再导出以兼容既有 import。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..time_util import day_of, parse_ts, week_start
from ._shared import _safe_float, _safe_int, _sess_stamp, _session_ident
from .skill import _skill_created_date

_REWORK_EARLY_WEEKS = 2    # 返工对比：最早有记录的 2 个自然周
_REWORK_RECENT_WEEKS = 3   # vs 最近 3 个自然周
_REWORK_MIN_SESSIONS = 5   # 单侧会话下限（不足不给数字，防小分母假结论）
_WEEKLY_MAX = 26           # 折柱图最多 26 周（再久也不撑爆布局）
_LEDGER_TOP_N = 6          # 账本首屏露出的高分经验条数


def _median(values: list[int]) -> int:
    """整数中位数。"""
    if not values:
        return 0
    vs = sorted(values)
    m = len(vs) // 2
    return vs[m] if len(vs) % 2 else (vs[m - 1] + vs[m]) // 2


def _session_day(rec: dict) -> str | None:
    """会话记录的日期 YYYY-MM-DD；无/坏时间戳 → None（不进时间轴）。

    去重 R1：原写法 `_sess_stamp(rec)[:10]` 手工截日期前缀再拼一番，与
    time_util.day_of 同义。
    """
    return day_of(_sess_stamp(rec))


def _week_of(day: str) -> str:
    """该日所属自然周起点（周一）。11 周跨度上按天太碎，按周正好对上"阶段"。

    去重 R1：与 distill/weekly_report.py 的 `_week_start` 是同一算式的两份实现
    （一份返回 str、一份返回 datetime），此处改调 time_util.week_start。
    """
    ws = week_start(day)
    return ws.isoformat() if ws is not None else None


def growth_panorama(sessions: list[dict], assets: dict, ledger_pool: list[dict],
                    advice_pool: list[dict], injected: int,
                    injected_by: dict | None = None) -> dict:
    """成长页需要的全景统计（确定性、零模型调用）。

    解决的三件事（设计走查  blocker/major）：
    1. **时间轴换源**——旧口径吃 experience.jsonl 的 ts，而经验回灌后 82 条 ts
       全在同一天，页面只能显示"最近活跃 1 天"；真正跨多周的是会话记录。
    2. **不依赖"任务类别"**——按 trunk/category 聚合的图在分类还没长出来时
       （模型端点不可用）必然空壳；这里全部按时间/价值闸门两个不空口径算。
    3. **资产口径与首页同源**——surface_of 派生"你的经验 / 助手能帮你避的坑"，
       两页不再各报各的数。

    与 cumulative/heatmap/affinity 并存不替换（那些仍被周报/海报/notify 消费）。
    """
    # ---- 账本（你的经验 top N，按重要性；同分新在前） ----
    pool = sorted(ledger_pool, key=lambda e: str(e.get("ts") or ""), reverse=True)
    pool = sorted(pool, key=lambda e: -_safe_int(e.get("importance")))  # 稳定排序
    ledger = [{
        "id": e.get("id"), "task": str(e.get("task") or ""),
        "action": str(e.get("action") or ""), "importance": e.get("importance"),
        "agent": str(e.get("agent") or ""), "corrected": bool(e.get("corrected")),
        "g_source": e.get("g_source"), "seen": len(e.get("seen_in") or []),
        "count": _safe_int(e.get("count")),
        # 下钻现场用（成长页「看现场」→ session_view）：经验记录自带来源会话
        "session_id": e.get("session_id") or "",
        "explain": str(e.get("explain") or ""), "advice": str(e.get("advice") or ""),
    } for e in pool[:_LEDGER_TOP_N]]

    # ---- 助手避坑（建议口吻原料，按累计次数） ----
    # 同类归堆（方案 B）：成长页避坑区按桶聚合要与首页严格守恒，
    # 不能再截断样本（条数 = advice 类坑卡全量，每条只有 5 个小字段，负载可忽略）
    adv = sorted(advice_pool, key=lambda e: -_safe_int(e.get("count")))
    advice_items = [{
        "id": e.get("id"), "task": str(e.get("task") or ""),
        "state": str(e.get("state") or ""), "count": _safe_int(e.get("count")),
        "seen": len(e.get("seen_in") or []),
    } for e in adv]

    rows = sorted(((d, s) for d, s in (( _session_day(x), x) for x in sessions)
                   if d), key=lambda t: t[0])
    # 账本/避坑只依赖经验库，不能被"还没有会话"一起清空——新装机先看资产
    if not rows:
        return {"stage": {"start": "", "end": "", "weeks": 0, "active_days": 0,
                          "sessions": 0, "agents": 0, "projects": 0},
                "weekly": [],
                "rework": {"early": None, "recent": None, "drop_pct": None,
                           "early_n": 0, "recent_n": 0, "early_corr": 0,
                           "recent_corr": 0, "comparable": False},
                "agents": [], "phases": [],
                "flywheel": {"collected": 0, "distilled": assets.get("total", 0),
                             "judged": assets.get("judged", 0),
                             "injected": injected,
                             "injected_by": dict(injected_by or {}),
                             "improved": None},
                "ledger": ledger, "advice_items": advice_items}

    # ---- 周桶（含无记录的空周，页面据此留空、不连线） ----
    buckets: dict[str, dict] = {}
    for day, s in rows:
        wk = _week_of(day)
        b = buckets.setdefault(wk, {"week": wk, "sessions": 0, "corrections": 0,
                                    "days": set()})
        b["sessions"] += 1
        b["corrections"] += int(s.get("correction_hits") or 0)
        b["days"].add(day)
    all_weeks: list[str] = []
    # 去重 R1：bucket 键已是周起点（周一），week_start 幂等，故不受-weekday 回溯影响
    cur = week_start(min(buckets))
    last = week_start(max(buckets))
    while cur <= last:
        all_weeks.append(cur.isoformat())
        cur += timedelta(days=7)
    all_weeks = all_weeks[-_WEEKLY_MAX:]
    weekly = []
    for w in all_weeks:
        b = buckets.get(w)
        n = int(b["sessions"]) if b else 0
        c = int(b["corrections"]) if b else 0
        weekly.append({"week": w, "sessions": n, "corrections": c,
                       "rate": round(c / n, 2) if n else None})

    # ---- 返工对比（早窗口 vs 近窗口，两侧都不足样本则判"不可比"） ----
    rework = {"early": None, "recent": None, "drop_pct": None,
              "early_n": 0, "recent_n": 0, "early_corr": 0, "recent_corr": 0,
              "comparable": False}
    live = [w for w in weekly if w["sessions"] > 0]
    early_wks: set[str] = set()
    recent_wks: set[str] = set()
    if len(live) >= _REWORK_EARLY_WEEKS + _REWORK_RECENT_WEEKS:
        e = live[:_REWORK_EARLY_WEEKS]
        r = live[-_REWORK_RECENT_WEEKS:]
        en, rn = sum(w["sessions"] for w in e), sum(w["sessions"] for w in r)
        if en >= _REWORK_MIN_SESSIONS and rn >= _REWORK_MIN_SESSIONS:
            early = round(sum(w["corrections"] for w in e) / en, 2)
            recent = round(sum(w["corrections"] for w in r) / rn, 2)
            rework = {
                "early": early, "recent": recent,
                "drop_pct": round((1 - recent / early) * 100) if early > 0 else None,
                "early_n": en, "recent_n": rn, "comparable": True,
                # 纠正总数字面带上：展示层反算（rate×n）会四舍五入出 69→70 这种假数
                "early_corr": sum(w["corrections"] for w in e),
                "recent_corr": sum(w["corrections"] for w in r),
                "early_span": [e[0]["week"], e[-1]["week"]],
                "recent_span": [r[0]["week"], r[-1]["week"]],
            }
            early_wks = {w["week"] for w in e}
            recent_wks = {w["week"] for w in r}

    # ---- 按助手拆的磨合（零纠正 = "本来就顺"，不再冒充"低熟练度"） ----
    per: dict[str, list] = {}
    for day, s in rows:
        per.setdefault(str(s.get("agent") or "unknown"), []).append((day, s))

    def _rate(sub: list) -> float | None:
        if not sub:
            return None
        return round(sum(int(s.get("correction_hits") or 0) for _, s in sub) / len(sub), 2)

    agent_rows = []
    for ag, lst in sorted(per.items(), key=lambda kv: -len(kv[1])):
        corr = sum(int(s.get("correction_hits") or 0) for _, s in lst)
        n = len(lst)
        if n < _REWORK_MIN_SESSIONS:
            state = "few"            # 样本不够
        elif corr == 0:
            state = "smooth"         # 一次都没被纠正 = 本来就顺
        else:
            e_rate = _rate([x for x in lst if _week_of(x[0]) in early_wks])
            r_rate = _rate([x for x in lst if _week_of(x[0]) in recent_wks])
            state = "improved" if (e_rate and r_rate is not None and r_rate < e_rate) \
                else "flat"
        agent_rows.append({
            "agent": ag, "n": n, "corrections": corr,
            "projects": len({s.get("project") for _, s in lst if s.get("project")}),
            "last": max(d for d, _ in lst),
            "early": _rate([x for x in lst if _week_of(x[0]) in early_wks]) or None,
            "recent": _rate([x for x in lst if _week_of(x[0]) in recent_wks]) or None,
            "state": state,
        })

    # ---- 按月阶段带 ----
    months: dict[str, dict] = {}
    for day, s in rows:
        m = months.setdefault(day[:7], {"month": day[:7], "sessions": 0,
                                        "corrections": 0, "days": set()})
        m["sessions"] += 1
        m["corrections"] += int(s.get("correction_hits") or 0)
        m["days"].add(day)
    phases = [{"month": k, "sessions": v["sessions"], "corrections": v["corrections"],
               "days": len(v["days"])} for k, v in sorted(months.items())]

    return {
        "stage": {
            "start": rows[0][0], "end": rows[-1][0],
            "weeks": len(all_weeks), "active_days": len({d for d, _ in rows}),
            "sessions": len(rows), "agents": len(per),
            "projects": len({s.get("project") for _, s in rows if s.get("project")}),
        },
        "weekly": weekly,
        "rework": rework,
        "agents": agent_rows,
        "phases": phases,
        "flywheel": {
            "collected": len(rows), "distilled": assets.get("total", 0),
            "judged": assets.get("judged", 0), "injected": injected,
            "injected_by": dict(injected_by or {}),
            # 第⑤格只在"确实回灌过 + 样本可比"时才给数，否则 None（页面画"—"）
            "improved": rework["drop_pct"] if (rework["comparable"] and injected > 0)
            else None,
        },
        "ledger": ledger,
        "advice_items": advice_items,
    }


def _build_affinity(store, cat_sessions: dict) -> dict:
    """磨合度计算。

    从 `growth_summary` 抽出的独立一段——输入是会话去重后的
    分组，输出是各组的磨合指标，不依赖 `growth_summary` 的其他中间变量，
    因此可单独读、也可单独测。逻辑逐字搬移，未改语义。

    判据要点（搬移时原样保留，勿改）：
    - 基线 = 前 3 个独立实例，近期 = 第 4~8 个（两者**不重叠**，0919 M1）；
    - 主指标 = 磨合差值（基线中位数 − 近期中位数），不用比值（防小分母假数字）；
    - 基线修正中位数为 0 → excluded（负例自查，不算改善样本）；
    - 基线窗口内 playbook 已存在 → excluded（防作弊，0919 M2）。
    """
    affinity: dict[str, dict] = {}
    for key, deduped in cat_sessions.items():
        ss = sorted(deduped.values(), key=_sess_stamp)
        n = len(ss)
        # 基线与近期窗口必须不重叠——此前 recent=ss[-5:]
        # 在 n<8 时与基线（前 3）重叠 1~3 个实例，diff 被基线自身稀释，
        # 主判据（diff≥1）实际需 n≥8 才可能成立。改为基线=前 3、
        # 近期=第 4~8 个独立实例；n==3 尚无基线后实例 → 待积累。
        if n < 4:
            affinity[key] = {"n": n, "level": "待积累"}
            continue
        base, recent = ss[:3], ss[3:8]
        b_fix = _median([int(s.get("correction_hits") or 0) for s in base])
        b_req = _median([int(s.get("req_count") or 0) for s in base])
        b_tok = _median([int(s.get("tokens_in") or 0) + int(s.get("tokens_out") or 0)
                         for s in base])
        r_fix = _median([int(s.get("correction_hits") or 0) for s in recent])
        r_req = _median([int(s.get("req_count") or 0) for s in recent])
        r_tok = _median([int(s.get("tokens_in") or 0) + int(s.get("tokens_out") or 0)
                         for s in recent])
        diff = b_fix - r_fix            # 主指标：磨合差值（>0 = 变顺）
        rounds_diff = b_req - r_req     # 辅判据：协作轮数差值（同口径）
        # 百分比仅作辅助展示；基线中位数为 0 → None（防小分母假数字）
        corr_pct = round((r_fix - b_fix) / b_fix * 100) if b_fix else None
        rounds_pct = round((r_req - b_req) / b_req * 100) if b_req else None
        tokens_pct = round((r_tok - b_tok) / b_tok * 100) if b_tok else None
        # 负例自查：基线本来就很好（修正中位数 0）
        # 的类别不算改善样本——防"经验被过度套用在简单任务上"的假改善
        excluded = b_fix == 0
        # 防作弊：基线必须处于空库状态——playbook
        # 在基线窗口结束（第 3 个实例）之前已存在，则早期实例本就有资产
        # 可依赖，改善数字不能归因于新经验 → 基线不成立，标 excluded
        #（与负例自查同口径：不算改善样本）。
        _rest = key.partition("/")[2]
        _trunk, _, _cat = _rest.partition("/")
        _created = _skill_created_date(store.read_skill(_trunk, _cat))
        if _created and _created <= _sess_stamp(ss[2])[:10]:
            excluded = True
        if excluded:
            level = "低"
        elif diff >= 2:
            level = "高"
        elif diff >= 1:
            level = "中"
        else:
            level = "低"
        affinity[key] = {
            "n": n, "level": level,
            "diff": diff, "rounds_diff": rounds_diff,
            "excluded": excluded,
            # 4 ≤ n <8：差值照算（基线 3 + 近期≥1），页面标注样本量
            #（给数字也给置信度，；n==3 无基线后实例已在上方待积累）
            "sample_note": 4 <= n < 8,
            "baseline": {"fix": b_fix, "req": b_req, "tokens": b_tok,
                         "n": len(base),
                         "at": _sess_stamp(ss[0])[:10]},
            "recent": {"fix": r_fix, "req": r_req, "tokens": r_tok,
                       "n": len(recent),
                       "at": _sess_stamp(ss[-1])[:10]},
            "rounds_pct": rounds_pct, "corrections_pct": corr_pct,
            "tokens_pct": tokens_pct,
            "first": {"req_count": int(ss[0].get("req_count") or 0),
                      "correction_hits": int(ss[0].get("correction_hits") or 0),
                      "tokens": int(ss[0].get("tokens_in") or 0) + int(ss[0].get("tokens_out") or 0),
                      "at": _sess_stamp(ss[0])[:10]},
            # "last" 槽位 = 近期窗口中位代表（v2 口径），键名保留兼容下游
            "last": {"req_count": r_req, "correction_hits": r_fix, "tokens": r_tok,
                     "at": _sess_stamp(ss[-1])[:10]},
            # 时间轴：Strava segment 式"同一条路跨时间对比"（周报"更快了吗"用）
            "timeline": [
                {"at": _sess_stamp(s)[:10],
                 "req_count": int(s.get("req_count") or 0),
                 "correction_hits": int(s.get("correction_hits") or 0)}
                for s in ss[:10]
            ],
        }
    return affinity


class GrowthMixin:
    """成长页口径（确定性统计，零模型调用）。"""

    def growth_summary(self, days: int = 30) -> dict:
        """确定性统计（不花模型调用）：按 trunk/category 聚合。

        - cumulative：每类逐日累积条数
        - heatmap：最近 14 天 × 主干，格值 = 当天该主干经验 G 加权和
        - affinity（磨合度，口径，按 agent 拆分 v3）：
          键 = `agent/trunk/category`（agent 缺失 → unknown；展示走
          affinity_display）。基线 = 前 3 个独立实例修正轮数中位数；
          主指标 = 磨合差值（diff）= 基线中位数 − 近期窗口（最近 5 个
          独立实例）中位数，差值不用比值（防小分母假数字 + 回归到均值）；
          百分比仅作辅助（基线修正中位数为 0 时 None）；基线修正中位数
          为 0 的类别标 excluded（负例自查，不算改善样本）；独立实例 =
          一个 session（session_id 去重）；<3 次 → 待积累
        """

        today = datetime.now(timezone.utc).date()
        # UI-4：/api/growth 每次全量扫双 JSONL → 源文件签名级结果缓存。
        # 只缓存低频慢口径；写路径任一文件变化（mtime/size）即失效重算。
        # injection.log 必须在签名里（冒烟抓到）：第④格读它计数，
        # 不纳入签名会让"刚发生的回灌"永远看不见，直到别的文件恰好变化才刷新。
        sig = self._jsonl_signature(
            ("experience.jsonl", "sessions.jsonl", "injection.log"))
        # 还要吃"经验写世代"——SQLite 事实源模式下更新/删除
        # 只写库不写文件，纯索引写光靠文件签名刷不掉缓存（会一直吃旧结果）。
        cache_key = (days, today.isoformat(), sig,
                     getattr(self, "_exp_write_gen", 0))  # 跨日窗口不串
        cached = getattr(self, "_growth_cache", None)
        if cached is not None and cached[0] == cache_key:
            return cached[1]

        cats: dict[str, dict] = {}
        trunks: dict[str, float] = {}
        all_grid: dict[str, list[float]] = {}
        # 成长页重构思：价值闸门口径的资产计数 + 账本原料，
        # 与首页同一函数派生（surface_of），两页不再各说一套数（走查 blocker）。
        from ..distill.value_gate import SURFACE_ADVICE, SURFACE_EXPERIENCE, surface_of

        assets = {"experience": 0, "advice": 0, "corrected": 0, "judged": 0,
                  "top": 0, "high": 0, "feedback": 0, "total": 0,
                  "advice_hits": 0}
        ledger_pool: list[dict] = []
        advice_pool: list[dict] = []

        # 经验读侧统一走 iter_experiences（SQLite 事实源；
        # 索引不可用时其内部自动回退 JSONL）。原实现直读 experience.jsonl——
        # 起该文件只是"每 20 次脏写才导出"的备份快照，更新（G/count/
        # importance/反馈）与退休删除都看不到。附带口径统一：读侧净化
        # （_normalize_read_view 的 G 升档/坏值兜底）与其余页面一致。
        for e in self.iter_experiences(include_distilled=True,
                                       show_dismissed=True):
            assets["total"] += 1
            surf = surface_of(e)
            if surf == SURFACE_EXPERIENCE:
                assets["experience"] += 1
                ledger_pool.append(e)
            elif surf == SURFACE_ADVICE:
                assets["advice"] += 1
                assets["advice_hits"] += _safe_int(e.get("count"))
                advice_pool.append(e)
            if e.get("corrected"):
                assets["corrected"] += 1
            if e.get("importance") is not None:
                assets["judged"] += 1
                try:  # 存量/外部编辑的非数值 importance 不得击穿首页
                    imp = _safe_int(e.get("importance"))
                except (TypeError, ValueError):
                    imp = 0
                if imp >= 9:
                    assets["top"] += 1
                if imp >= 8:
                    assets["high"] += 1
            if e.get("user_valid") or e.get("user_rejected"):
                assets["feedback"] += 1
            trunk = str(e.get("trunk") or "其他")
            category = str(e.get("category") or "未分类")
            key = f"{trunk}/{category}"
            d = cats.setdefault(key, {"count": 0, "days": {}})
            d["count"] += 1
            # 去重 R1：原 `str(ts)[:10]` 截前缀 + 手工解析，统一走 day_of 口径
            day = parse_ts(e.get("ts"))
            if day is None:
                continue
            day = day.date()
            d["days"][day.isoformat()] = d["days"].get(day.isoformat(), 0) + 1

            # 热力图所需：最近 14 天 × 主干 G 加权（单次迭代同时构建 gird 和 trunks）
            age = (today - day).days
            if 0 <= age <= 13:
                trunks[trunk] = trunks.get(trunk, 0.0) + _safe_float(e.get("G"))
                if trunk not in all_grid:
                    all_grid[trunk] = [0.0] * 14
                all_grid[trunk][13 - age] += _safe_float(e.get("G"))

        top_trunks = [t for t, _ in sorted(trunks.items(), key=lambda kv: -kv[1])[:4]]
        grid = {t: all_grid.get(t, [0.0] * 14) for t in top_trunks}

        # 累积曲线：每类逐日累积条数
        cumulative: dict[str, list] = {}
        for key, d in cats.items():
            series = dict(d["days"])
            window_start = (today - timedelta(days=days - 1)).isoformat()
            pre_base = sum(v for day, v in series.items() if day < window_start)
            running, out = 0, []
            for i in range(days - 1, -1, -1):
                day = (today - timedelta(days=i)).isoformat()
                running += series.get(day, 0)
                out.append([day, pre_base + running])
            cumulative[key] = out

        # 磨合度 v2：基线 = 前 3 个独立实例修正轮数中位数；
        # 主指标 = 磨合差值 = 基线中位数 − 近期窗口（最近 5 个独立实例）中位数。
        # 独立实例 = 一个 session（session_id 去重——同一 session 内重跑不计，
        # 重跑污染独立性）；差值不用比值（防小分母假数字 + 回归到均值）。
        # 按 agent 拆分：键 = agent/trunk/category——
        # 语义是"和*某个 agent*协作这类任务的顺度"；不同 agent 工具调用/纠正
        # 模式不同，混合中位数不可比（假数字）。经验池（蒸馏/注入/三态）仍按
        # (trunk,category) 混合（跨 agent 交叉验证是特性），只拆成长指标。
        # 档位门槛（独立实例 ≥3）按单 agent 计，样本被 agent 稀释 → 档位来得慢，
        # 用"样本不足"（n<3 → 待积累）显式化对冲。agent 缺失 → unknown 桶。
        cat_sessions: dict[str, dict[tuple, dict]] = {}
        # 成长页时间轴原料：全量会话按 (agent, session_id) 去重留最新一行
        # （sessions.jsonl 追加式落库，首行优先会拿旧行——验收踩过的坑）。
        # 与 affinity 的差别：affinity 只收有 trunk/req_count 的样本，
        # 时间轴要全部有 started_at 的会话（否则"活跃天数"被过滤掉一截）。
        pano: dict[tuple, dict] = {}
        for s in self._iter_jsonl("sessions.jsonl"):
            _pk = (str(s.get("agent") or "unknown"), _session_ident(s))
            _cur = pano.get(_pk)
            if _cur is None or _sess_stamp(s) >= _sess_stamp(_cur):
                pano[_pk] = s
            if not s.get("trunk") or not s.get("req_count"):
                continue
            agent = str(s.get("agent") or "unknown")
            key = f"{agent}/{s.get('trunk')}/{s.get('category')}"
            dedup = (agent, _session_ident(s))
            cur = cat_sessions.setdefault(key, {}).get(dedup)
            if cur is None or _sess_stamp(s) >= _sess_stamp(cur):
                cat_sessions[key][dedup] = s  # 同 session 重记录：留时间较新的一条
        affinity = _build_affinity(self, cat_sessions)

        # 回灌计数（injection.log 行数）：飞轮第④格。文件不存在 → 0（缺文件是
        # 事实而非异常——8100 从未被真实调用过时，页面必须显示 0 而不是报错）。
        # 按通道拆开：proxy = 走 8100 改写请求；hook = Claude Code 回灌
        # additionalContext。两条都算"经验真的到了助手"，只统计一条会少算。
        injected = 0
        injected_by = {"proxy": 0, "hook": 0}
        try:
            for rec in self._iter_jsonl("injection.log"):
                injected += 1
                ch = str(rec.get("channel") or "proxy")
                injected_by[ch] = injected_by.get(ch, 0) + 1
        except OSError:
            injected, injected_by = 0, {"proxy": 0, "hook": 0}

        result = {
            "days": days,
            "cumulative": cumulative,
            "heatmap": {"trunks": top_trunks, "grid": grid,
                        "dates": [(today - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]},
            "affinity": affinity,
            "assets": assets,
        }
        result.update(growth_panorama(list(pano.values()), assets, ledger_pool,
                                      advice_pool, injected, injected_by))
        self._growth_cache = (cache_key, result)
        return result
