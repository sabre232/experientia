"""经验与成长模块优化方案·第一步验收（docs/Experientia_经验与成长模块优化方案.md）。

覆盖：失败模式三态双门/ 成功要点复现门/ 注入命中落盘/
档 C1 空闲后台整理/ 周日结算四段式 + 成就/ 磨合度 v2 差值口径。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app import notify
from app.distill import gate, maintenance, weekly_report
from app.store.store import Store
from conftest import freeze_utcnow

TRUNK, CAT = "营销", "文案写作"
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)  # 周四

# 成长叙事属归纳类内容：起 weekly_report 传 model_available 给
# growth_story，无模型时四段皆空（与「未接入模型：归纳类内容不可用」同口径）。
# 本文件这些用例测的是周报的分组/推送逻辑，不是门禁本身，故配一个模型让叙事
# 正常产出；要测门禁请看 test_ws6_content_policy::test_weekly_report_story_is_stamped。
MODEL_CFG = {"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                  "type": "local", "model": "qwen"}},
             "default_model": "local"}


def _store(tmp_path) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    return s


def _store_with_model(tmp_path) -> Store:
    """带模型配置的 store（周报四段用例需要叙事正常产出）。"""
    s = _store(tmp_path)
    s.save_config(dict(MODEL_CFG))
    return s


def _exp(store, i, ts, G=0.3, corrected=False, count=1, action=None,
         g_source="auto"):
    store.append_experience({
        "id": f"g{i}", "ts": ts, "task": f"任务{i}",
        "action": action or f"坑{i}", "G": G, "g_source": g_source,
        "corrected": corrected, "trunk": TRUNK, "category": CAT,
        "count": count,
    })
    return store.find_experience(f"g{i}")


def _session(store, sid, started, req=5, corr=1, ended=None):
    store.record_session({
        "agent": "codex", "session_id": sid, "trunk": TRUNK, "category": CAT,
        "req_count": req, "correction_hits": corr,
        "started_at": started, "ended_at": ended or started,
    })


def _recent_ts(days: int = 1) -> str:
    """相对**真实当前时间**的时间戳（不写死日期）。

    本文件大量硬编码 2026-09-xx，而 gate 的老化判据是"距今
    ≥30 天"——日历走满 30 天后这类断言会自动变红（本轮首次触发：
    `test_gate_watch_below_count` 的刚好满 30 天 → expired 翻 True）。
    凡断言与老化/过期相关的，一律用本函数取相对时间。
    其余只与冻结的 NOW 相互比较的硬编码日期不受日历影响，暂未改动。
    """
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _playbook_with_failures(md_fail_lines: list[str]) -> str:
    return ("# 营销 / 文案写作 · playbook\n\n> version: 1\n\n"
            "## 标准流程\n- 先列卖点\n\n## 成功要点\n- 利益点前置\n\n"
            "## 失败模式\n" + "\n".join(md_fail_lines) + "\n")


# ---------- 失败模式三态 ----------

def test_gate_watch_below_count(tmp_path):
    store = _store(tmp_path)
    e = _exp(store, 1, _recent_ts(), count=1)
    st = gate._state_for("坑1", [e], [])
    assert st["state"] == "watch" and st["count"] == 1
    assert st["expired"] is False


def test_gate_pending_count_without_repro(tmp_path):
    """计数 ≥3 但复现双门未过 → 待验证（不注入）。"""
    store = _store(tmp_path)
    e = _exp(store, 1, "2026-09-09T10:00:00Z", count=4)
    st = gate._state_for("坑1", [e], [])
    assert st["state"] == "pending" and st["repro_clear"] is False


def test_gate_solid_via_reproduction(tmp_path):
    """双门①：坑之后有同类成功任务（G≥0.5 未纠正）→ 固化。"""
    store = _store(tmp_path)
    low = _exp(store, 1, "2026-09-01T10:00:00Z", count=3)
    _exp(store, 2, "2026-09-05T10:00:00Z", G=0.8, action="先列卖点再润色")
    ok_ts = [e["ts"] for e in gate._ok_experiences(store, TRUNK, CAT)]
    st = gate._state_for("坑1", [low], ok_ts)
    assert st["state"] == "solid" and st["repro_clear"] is True


def test_gate_solid_via_user_l1(tmp_path):
    """双门②：支撑经验被用户标 L1"有效"（g_source=user 且 G≥1.0）→ 固化。"""
    store = _store(tmp_path)
    e = _exp(store, 1, "2026-09-01T10:00:00Z", count=3,
             G=1.0, g_source="user")
    st = gate._state_for("坑1", [e], [])
    assert st["state"] == "solid" and st["user_valid"] is True


def test_gate_deadlock_gate_removed(tmp_path):
    """修复方案：旧「≥6 次自动固化」直通门已废除——无复现证据永远停在待验证
    （次数多不等于可信；护栏防回潮）。"""
    store = _store(tmp_path)
    e = _exp(store, 1, "2026-09-01T10:00:00Z", count=6)
    st = gate._state_for("坑1", [e], [])
    assert st["state"] == "pending"


def test_gate_count_sums_backing_experiences(tmp_path):
    """计数 = 同类失败经验的 count 之和（近重复经验不重复立项）。"""
    store = _store(tmp_path)
    e1 = _exp(store, 1, "2026-09-01T10:00:00Z", count=2,
              action="纯情绪文案点击率低")
    e2 = _exp(store, 2, "2026-09-02T10:00:00Z", count=1,
              action="纯情绪文案点击率偏低")
    st = gate._state_for("纯情绪文案点击率低", [e1, e2], [])
    assert st["count"] == 3 and st["state"] == "pending"


def test_gate_observation_expiry(tmp_path):
    """观察中 + 30 天无新出现 → 观察过期（不再累计）。"""
    store = _store(tmp_path)
    e = _exp(store, 1, "2026-07-20T10:00:00Z", count=1)  # 距 NOW 52 天
    st = gate._state_for("坑1", [e], [])
    assert st["state"] == "watch" and st["expired"] is True


def test_gate_remark_line_formats():
    st_pending = {"state": "pending", "count": 4, "expired": False}
    assert gate.remark_line("标题超长被截断", st_pending) == \
        "- [Pending] 标题超长被截断（出现 4 次）"
    st_expired = {"state": "watch", "count": 2, "expired": True}
    assert gate.remark_line("旧坑", st_expired) == \
        "- [Watching] 旧坑（观察过期）"


def test_gate_playbook_states_live_recompute(tmp_path):
    """读路径权威：playbook 标记是快照，三态由经验数据实时复算。"""
    store = _store(tmp_path)
    _exp(store, 1, "2026-09-01T10:00:00Z", count=4,
         action="纯情绪文案点击率低")
    # playbook 里还是旧快照 [Watching]，但经验已 4 次 → 实时判定 pending
    store.write_skill(TRUNK, CAT, _playbook_with_failures(
        ["- [Watching] 纯情绪文案点击率低（出现 1 次）"]))
    states = gate.failure_mode_states(store, TRUNK, CAT)
    body = "纯情绪文案点击率低（出现 1 次）"
    assert body in states and states[body]["state"] == "pending"
    # 重打标记 = 实时三态（其余节原样）
    md2 = gate.remark_failure_section(
        store.read_skill(TRUNK, CAT), states)
    # 计数 = 实时复算（经验 4 次），不是 playbook 快照里的 1 次
    assert "- [Pending] 纯情绪文案点击率低（出现 4 次）" in md2
    assert "## 成功要点" in md2 and "- 利益点前置" in md2


# ---------- 成功要点复现门 ----------

def test_success_point_new_single_source(tmp_path):
    """仅 1 条来源轨迹 → [NewPoint] 新要点·待复现（注入权重降半）。"""
    store = _store(tmp_path)
    _exp(store, 1, "2026-09-01T10:00:00Z", G=0.9, action="利益点前置")
    md = _playbook_with_failures([])
    md2 = gate.remark_success_points(md, store, TRUNK, CAT)
    assert "- [NewPoint] 利益点前置" in md2


def test_success_point_promoted_two_sources(tmp_path):
    """≥2 条近重复来源 → 转正（去掉新要点标记）。"""
    store = _store(tmp_path)
    _exp(store, 1, "2026-09-01T10:00:00Z", G=0.9, action="利益点前置")
    _exp(store, 2, "2026-09-03T10:00:00Z", G=0.8,
         action="利益点前置 + A/B 两版")  # 近重复 → 第 2 条来源
    md = _playbook_with_failures([])
    md2 = gate.remark_success_points(md, store, TRUNK, CAT)
    assert "- 利益点前置" in md2
    assert "[NewPoint]" not in md2


def test_new_point_injection_weight_halved(tmp_path):
    """注入块：新要点单独成块、成本按 2 倍计（权重降半）。"""
    from app.proxy import inject

    store = _store(tmp_path)
    _exp(store, 1, "2026-09-01T10:00:00Z", G=0.9, action="利益点前置")
    _exp(store, 2, "2026-09-03T10:00:00Z", G=0.9, action="利益点要前置")
    store.write_skill(TRUNK, CAT,
                      "# pb\n\n## 成功要点\n- [NewPoint] 利益点前置\n"
                      "- 利益点要前置\n\n## 失败模式\n")
    items = inject.iter_injection_items(store, TRUNK, CAT)
    marks = {it["text"]: it.get("new_point") for it in items
             if it["kind"] == "insight"}
    assert marks.get("利益点前置") is True
    assert marks.get("利益点要前置") in (False, None)


# ---------- 注入命中落盘 ----------

def test_record_injection_log_and_hits(tmp_path, monkeypatch):
    # record_injection 用 utcnow()（真实当前时间）落 ts；窗口断言基于固定 NOW，
    # 须把时钟钉到 NOW，否则记录落在真实时间、窗口（固定日期）读不到 → 恒空。
    # record_injection 已搬到 app/store/injection.py，而 utcnow
    # 是各模块早绑定的模块级名字——只 patch app.store.store 覆盖不到它，必须
    # 用 conftest.freeze_utcnow 把所有绑了 utcnow 的子模块一起钉住。
    freeze_utcnow(monkeypatch, NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
    store = _store(tmp_path)
    store.record_injection(TRUNK, CAT, "s1", 120, files=["a.md"])
    store.record_injection(TRUNK, CAT, "s2", 80)
    hits = store.load_injection_hits()
    assert hits[f"{TRUNK}/{CAT}"]["count"] == 2
    assert store.last_injection_ts() == hits[f"{TRUNK}/{CAT}"]["last"]
    # 窗口读：全部在窗口内
    out = store.read_injection(NOW - timedelta(days=1), NOW + timedelta(days=1))
    assert [r["session"] for r in out] == ["s1", "s2"]
    # 窗口外：空
    assert store.read_injection(NOW + timedelta(days=1),
                                NOW + timedelta(days=2)) == []


def test_injection_log_capped(tmp_path):
    store = _store(tmp_path)
    for i in range(Store.INJECTION_LOG_MAX_LINES + 3):
        store.record_injection(TRUNK, CAT, f"s{i}", 1)
    ts = store.last_injection_ts()
    assert ts is not None
    assert store.load_injection_hits()[f"{TRUNK}/{CAT}"]["count"] == \
        Store.INJECTION_LOG_MAX_LINES + 3


# ---------- 档 C1 空闲后台整理 ----------

def test_should_run_gates(tmp_path, monkeypatch):
    """触发条件：空闲 ≥2h + 1h 无真实注入 + 当日已有会话。

    假时钟 REF=当日 UTC 12:00：真实时钟在 UTC 凌晨 <5h 窗口构造不出
    "当日且已空闲 2h"的样本（3/4 小时前落到昨天），测试必挂——
     真机 01:44 实际踩到，改为确定性时钟。"""
    REF = datetime.now(timezone.utc).replace(
        hour=12, minute=0, second=0, microsecond=0)

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return REF if tz else REF.replace(tzinfo=None)

    monkeypatch.setattr(maintenance, "datetime", _DT)
    store = _store(tmp_path)
    assert maintenance.should_run(store) is False  # 无会话

    def ts(seconds_ago: int) -> str:
        return (REF - timedelta(seconds=seconds_ago)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")

    # 当日有会话，但 10 分钟前还有活动 → 不跑（2h 空闲未满足）
    _session(store, "s1", ts(1800), ended=ts(600))
    assert maintenance.should_run(store) is False

    # 会话 3h 前结束，但 30 分钟前还有真实注入 → 不跑（1h 注入口径）
    store_b = _store(tmp_path / "b")
    _session(store_b, "s1", ts(4 * 3600), ended=ts(3 * 3600))
    store_b.data_dir.joinpath("injection.log").write_text(
        json.dumps({"ts": ts(1800), "session": "s1", "trunk": TRUNK,
                    "category": CAT, "tokens": 50, "files": []},
                   ensure_ascii=False) + "\n",
        encoding="utf-8")
    assert maintenance.should_run(store_b) is False

    # 会话 3h 前结束、注入也 2h 前 → 该跑
    store_c = _store(tmp_path / "c")
    _session(store_c, "s1", ts(4 * 3600), ended=ts(3 * 3600))
    store_c.data_dir.joinpath("injection.log").write_text(
        json.dumps({"ts": ts(2 * 3600), "session": "s1", "trunk": TRUNK,
                    "category": CAT, "tokens": 50, "files": []},
                   ensure_ascii=False) + "\n",
        encoding="utf-8")
    store_c.data_dir.joinpath("injection_hits.json").write_text(
        json.dumps({f"{TRUNK}/{CAT}": {"count": 1, "last": ts(2 * 3600)}},
                   ensure_ascii=False), encoding="utf-8")
    assert maintenance.should_run(store_c) is True

    # 只有往日的会话（当日无活动）→ 不跑
    store_d = _store(tmp_path / "d")
    _session(store_d, "s9", ts(3 * 86400), ended=ts(3 * 86400 - 2400))
    assert maintenance.should_run(store_d) is False


def test_should_run_overdue_ignores_no_session_today(tmp_path):
    """逾期补跑：整理日志隔 ≥2 天 → 不再要求"当日有会话结束"。

    为什么要这条：daemon 的日期门只管日期、不管是否真跑过——跨天后的第一次
    检查若不满足条件，当天就被废掉；长期不开应用时欠的账一直还不上。
    边界：**无日志不算逾期**（全新安装不该因此绕开"当日有会话"），
    日志在但只隔 1 小时也不算。"""
    ref = datetime.now(timezone.utc)

    def ago(days: float) -> str:
        return (ref - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def log_at(store, ts: str) -> None:
        (store.data_dir / "maintenance.log").write_text(
            json.dumps({"ts": ts}, ensure_ascii=False) + "\n", encoding="utf-8")

    # 只有往日会话 + 日志停在 3 天前 → 该跑
    overdue = _store(tmp_path / "overdue")
    _session(overdue, "s9", ago(3), ended=ago(3))
    log_at(overdue, ago(3))
    assert maintenance.should_run(overdue) is True

    # 刚整理过（1h 前）→ 仍要"当日有会话"
    fresh = _store(tmp_path / "fresh")
    _session(fresh, "s9", ago(3), ended=ago(3))
    log_at(fresh, ago(1 / 24))
    assert maintenance.should_run(fresh) is False

    # 从未整理过 → 不算逾期（首启当天不跑无意义的全量整理）
    virgin = _store(tmp_path / "virgin")
    _session(virgin, "s9", ago(3), ended=ago(3))
    assert maintenance.should_run(virgin) is False


def test_c1_aging_demote_and_retire(tmp_path):
    """条目级老化：≥30 天无注命中 → 降权；≥90 天 → 归档；
    失败池只降权不淘汰。锚点 = 与经验近重复的注入条目 last，非类别整体 last。"""
    store = _store(tmp_path)
    store.write_skill(TRUNK, CAT, "# pb\n")
    _exp(store, 1, "2026-08-01T10:00:00Z", G=0.9, count=1)   # 高 G → 可归档
    _exp(store, 2, "2026-08-01T10:00:00Z", G=0.3, count=1)   # 失败池 → 只降权
    # 注入条目命中：it1 停 100 天前（高G→归档）、it2 停 34 天前（失败池→降权）
    store.data_dir.joinpath("injection_hits.json").write_text(
        json.dumps({f"{TRUNK}/{CAT}": {"count": 2,
                                       "last": "2026-05-01T00:00:00Z",
                                       "items": {
                                           "it1": {"text": "坑1",
                                                   "last": "2026-05-01T00:00:00Z",
                                                   "corroborated": 0},
                                           "it2": {"text": "坑2",
                                                   "last": "2026-08-15T00:00:00Z",
                                                   "corroborated": 0},
                                       }}},
                   ensure_ascii=False), encoding="utf-8")
    actions = maintenance.run(store)
    assert actions["aged_retired"] == 1
    assert actions["aged_demoted"] == 1
    assert store.find_experience("g1") is None  # 已移入 deprecated/
    e2 = store.find_experience("g2")
    assert e2 is not None and e2.get("aged") is True
    # 审计件：maintenance.log + trigger_log 各一行
    assert store.read_maintenance()[-1]["aged_retired"] == 1
    assert store.read_trigger_log()[-1]["trigger"] == "C_maintenance"


def test_c1_aging_skips_without_hits(tmp_path):
    """第一钟无命中不动；第二钟窗口内（ts<180 天）同样不动。"""
    store = _store(tmp_path)
    store.write_skill(TRUNK, CAT, "# pb\n")
    recent = (datetime.now(timezone.utc) - timedelta(days=40)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    _exp(store, 1, recent, G=0.9, count=1)
    actions = maintenance.run(store)
    assert actions["aged_demoted"] == 0 and actions["aged_retired"] == 0
    assert store.find_experience("g1") is not None


def test_c1_observation_expiry_remark(tmp_path):
    """观察中 + 30 天无新出现 → 标记落进 playbook（最小落盘）。"""
    store = _store(tmp_path)
    _exp(store, 1, "2026-07-20T10:00:00Z", count=1,
         action="纯情绪文案点击率低")
    store.write_skill(TRUNK, CAT, _playbook_with_failures(
        ["- [Watching] 纯情绪文案点击率低（出现 1 次）"]))
    actions = maintenance.run(store)
    assert actions["obs_expired"] == 1
    md = store.read_skill(TRUNK, CAT)
    assert "- [Watching] 纯情绪文案点击率低（观察过期）" in md
    # 成功要点节不被误动
    assert "- 利益点前置" in md


# ---------- 周日结算四段式 + 成就 ----------

# 固定"现在"：周四（本周 = 09-08 周一起）；09-06 周日；09-07 周一
NOW_THU = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
SUN = datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc)


def _report_store(tmp_path) -> Store:
    """上周 4 次 + 本周 2 次会话（M1 不重叠窗口：基线中位 5 − 近期中位 4 = 差值 1），
    本周有注入命中。"""
    store = _store_with_model(tmp_path)
    store.write_skill(TRUNK, CAT, "# pb\n")
    for sid, day, corr in (("s3", "02", 6), ("s4", "03", 5),
                           ("s5", "04", 4), ("s6", "05", 4)):
        _session(store, sid, f"2026-09-{day}T08:00:00Z", req=10, corr=corr)
    for sid, day, corr in (("s1", "08", 4), ("s2", "09", 4)):
        _session(store, sid, f"2026-09-{day}T08:00:00Z", req=10, corr=corr)
    # 本周注入命中（"哪条经验在变强"数据源；ts 直接落窗内，不依赖真实时钟）
    store.data_dir.joinpath("injection.log").write_text(
        json.dumps({"ts": "2026-09-09T09:00:00Z", "session": "s2",
                    "trunk": TRUNK, "category": CAT, "tokens": 100,
                    "files": []}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return store


def test_weekly_report_four_sections(tmp_path, monkeypatch):
    store = _report_store(tmp_path)
    monkeypatch.setattr(weekly_report, "_now", lambda: NOW_THU)
    report = weekly_report.build_report(store)
    sec = report["sections"]
    assert report["week"] == "2026-09-07"  # 本周一（09-10 周四）
    # 主句 = 时间口径（样本不足时诚实降级）+  类别判据加项
    assert any("还在攒样本" in ln for ln in sec["main"])
    assert any("少 1 轮修正" in ln for ln in sec["main"])
    assert any("更快了吗" in ln for ln in sec["questions"])
    assert any("哪条经验在变强" in ln for ln in sec["questions"])
    assert sec["rest"] == []  # 本周有会话 → 无休整段
    assert weekly_report.has_content(report) is True


def test_weekly_report_rest_only_not_pushed(tmp_path):
    """无变化无里程碑 → has_content 假（纯休整周不打扰）。"""
    store = _store_with_model(tmp_path)
    _session(store, "s1", "2026-08-03T08:00:00Z", req=10, corr=1)
    _session(store, "s2", "2026-08-04T08:00:00Z", req=10, corr=1)
    _session(store, "s3", "2026-08-05T08:00:00Z", req=10, corr=1)
    report = weekly_report.build_report(store)
    # 新口径：主句不再留空（诚实说"样本还在攒"）；该不该推由 active 决定
    assert any("还在攒样本" in ln for ln in report["sections"]["main"])
    assert report["active"] is False
    assert weekly_report.has_content(report) is False


def test_achievement_veteran_and_idempotent(tmp_path, monkeypatch):
    """老练：磨合差值 ≥1 且本周上周都有实例 → 解锁一次，幂等。"""
    store = _report_store(tmp_path)
    monkeypatch.setattr(weekly_report, "_now", lambda: NOW_THU)
    fresh = weekly_report.check_achievements(store)
    # veteran 按 agent·category，id 含 agent（_session 用 agent=codex）
    assert f"veteran/codex/{TRUNK}/{CAT}" in {a["id"] for a in fresh}
    # 幂等：再跑一次没有新解锁
    assert weekly_report.check_achievements(store) == []
    assert weekly_report.load_achievements(store)  # 落盘可读


def test_achievement_pit_avoider(tmp_path, monkeypatch):
    """已固化失败模式 + 4 周窗口内未再踩 → 避坑达人。"""
    store = _store(tmp_path)
    _exp(store, 1, "2026-07-01T10:00:00Z", count=4,
         action="纯情绪文案点击率低")
    # playbook：坑已过复现门 → [Solidified]
    store.write_skill(TRUNK, CAT, _playbook_with_failures(
        ["- [Solidified] 纯情绪文案点击率低（出现 4 次）"]))
    monkeypatch.setattr(weekly_report, "_now", lambda: NOW_THU)
    fresh = weekly_report.check_achievements(store)
    assert any(a["type"] == "pit_avoider" for a in fresh)


def test_achievement_pit_avoider_blocked_by_recurrence(tmp_path, monkeypatch):
    """4 周窗口内又踩了同一个坑 → 不解锁。"""
    store = _store(tmp_path)
    _exp(store, 1, "2026-07-01T10:00:00Z", count=4,
         action="纯情绪文案点击率低")
    _exp(store, 3, "2026-09-09T10:00:00Z", count=1,
         action="纯情绪文案点击率偏低")  # 本周又踩
    store.write_skill(TRUNK, CAT, _playbook_with_failures(
        ["- [Solidified] 纯情绪文案点击率低（出现 4 次）"]))
    monkeypatch.setattr(weekly_report, "_now", lambda: NOW_THU)
    fresh = weekly_report.check_achievements(store)
    assert not any(a["type"] == "pit_avoider" for a in fresh)


def test_achievement_legacy_from_changelog(tmp_path):
    store = _store(tmp_path)
    store.append_changelog("导出 skill：营销/文案写作 → skills/文案写作.md")
    fresh = weekly_report.check_achievements(store)
    assert any(a["type"] == "legacy" for a in fresh)


def test_maybe_run_sunday_push_and_defer(tmp_path, monkeypatch):
    """周日有内容 → 推送；周日无内容但有成就 → 顺延下个工作日 10:00。"""
    # —— 分支 1：周日有内容，直接推 ——
    store = _report_store(tmp_path)
    monkeypatch.setattr(weekly_report, "_now", lambda: SUN)
    report = weekly_report.maybe_run(store)
    assert report is not None and weekly_report.has_content(report)
    items = notify.list_notifications(store)
    assert items and items[0]["type"] == "growth_report"
    assert items[0]["title"].startswith("本周结算：")
    # 同周重复调用 → 幂等返回 None
    assert weekly_report.maybe_run(store) is None

    # —— 分支 2：周日无内容 + 新成就 → 顺延，工作日 10 点后补发 ——
    store2 = _store(tmp_path / "b")
    _exp(store2, 1, "2026-07-01T10:00:00Z", count=4,
         action="纯情绪文案点击率低")
    store2.write_skill(TRUNK, CAT, _playbook_with_failures(
        ["- [Solidified] 纯情绪文案点击率低（出现 4 次）"]))
    monkeypatch.setattr(weekly_report, "_now", lambda: SUN)
    report2 = weekly_report.maybe_run(store2)
    assert report2 is not None and not weekly_report.has_content(report2)
    assert report2["achievements"]  # 成就解锁了
    assert notify.list_notifications(store2) == []  # 周日不发
    # 周一 09:00（未到 10 点）→ 仍不发
    monkeypatch.setattr(weekly_report, "_now",
                        lambda: datetime(2026, 9, 7, 9, 0,
                                         tzinfo=timezone.utc))
    assert weekly_report.maybe_run(store2) is None
    assert notify.list_notifications(store2) == []
    # 周一 10:30 → 补发
    monkeypatch.setattr(weekly_report, "_now",
                        lambda: datetime(2026, 9, 7, 10, 30,
                                         tzinfo=timezone.utc))
    assert weekly_report.maybe_run(store2) is None  # 补发不返回 report
    items2 = notify.list_notifications(store2)
    assert items2 and items2[0]["title"] == "上周解锁的成就"
    assert "避坑达人" in items2[0]["body"]  # 成就机器键不再裸奔给用户
    # 再跑 → pending 已清，不重发
    assert weekly_report.maybe_run(store2) is None
    assert notify.list_notifications(store2) == items2


def test_maybe_run_weekday_noop(tmp_path, monkeypatch):
    """非周日且无顺延成就 → 不动。"""
    store = _report_store(tmp_path)
    monkeypatch.setattr(weekly_report, "_now", lambda: NOW_THU)
    assert weekly_report.maybe_run(store) is None
    assert notify.list_notifications(store) == []


# ---------- 磨合度 v2补充 ----------

def test_affinity_pending_below_three(tmp_path):
    store = _store(tmp_path)
    _session(store, "s1", "2026-09-08T08:00:00Z")
    _session(store, "s2", "2026-09-09T08:00:00Z")
    aff = store.growth_summary(days=30)["affinity"]
    # 键含 agent（_session 用 agent=codex）
    assert aff[f"codex/{TRUNK}/{CAT}"] == {"n": 2, "level": "待积累"}


def test_affinity_dedup_same_session(tmp_path):
    """独立实例 = 一个 session：同 session 重记录不重复计数。"""
    store = _store(tmp_path)
    for i in range(3):
        _session(store, "same", "2026-09-08T08:00:00Z", req=10, corr=i)
    _session(store, "s2", "2026-09-09T08:00:00Z", req=9, corr=1)
    _session(store, "s3", "2026-09-10T08:00:00Z", req=8, corr=0)
    # 键含 agent（_session 用 agent=codex）
    aff = store.growth_summary(days=30)["affinity"][f"codex/{TRUNK}/{CAT}"]
    assert aff["n"] == 3  # 3 个独立实例，不是 5 条记录
