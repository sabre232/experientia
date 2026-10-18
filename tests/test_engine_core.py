"""Phase 4a 引擎测试：注入覆盖层/ 失败模式否决/
偏好重归纳与自整理/ 成长摘要/ 规则通道/
通知中心/ SKILL.md 生成。"""

from datetime import datetime, timedelta, timezone

import pytest

from app import notify
from app.distill import engine_curation, llm, skill as skillgen
from app.notify import DAILY_CAP, NOTIFY_TYPES, push
from app.proxy import inject
from app.store.store import Store

PLAYBOOK = """# 营销 / 文案写作 · playbook

> version: 1
> updated: 2026-08-28T00:00:00Z

## 标准流程
1. 确认投放目标与人群
2. 产出 ≥2 版标题（{利益点}前置）

## 成功要点
- 标题用利益点前置句式

## 失败模式
- [Solidified] 纯情绪文案不做利益承诺（出现 3 次）
- [Watching] 标题超过 20 字会被平台截断（出现 2 次）
"""

PREFS = """# 营销 · 偏好画像

> 自动归纳，可编辑

- 结论先行，先给数字再给推理 [UserConfirmed]
- 文案偏克制，反感感叹号
"""


def _store(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作", PLAYBOOK)
    store.write_preferences("营销", PREFS)
    return store


# ---------- 注入覆盖层 ----------

def test_items_iterate_in_order(tmp_path):
    store = _store(tmp_path)
    items = inject.iter_injection_items(store, "营销", "文案写作")
    kinds = [it["kind"] for it in items]
    assert kinds == ["pref", "pref", "failure", "flow", "flow", "insight"]
    assert all(it["id"] for it in items)
    # 观察中条目不注入（iter 只产出 Solidified failure 条目）
    assert not any("标题超过 20 字" in it["text"] for it in items)


def test_override_disable_and_text(tmp_path):
    store = _store(tmp_path)
    items = inject.iter_injection_items(store, "营销", "文案写作")
    pref_id = next(it["id"] for it in items if it["kind"] == "pref"
                   and "克制" in it["text"])
    base = inject.assemble_experience_block(store, "营销", "文案写作")
    assert "克制" in base

    # 关闭条目 → 从注入块消失
    store.upsert_override(pref_id, enabled=False)
    out = inject.assemble_experience_block(store, "营销", "文案写作")
    assert "克制" not in out

    # 改文本 → 用覆盖文本
    store.upsert_override(pref_id, enabled=True, text="文案要克制，不用感叹号（改）")
    out = inject.assemble_experience_block(store, "营销", "文案写作")
    assert "文案要克制，不用感叹号（改）" in out

    # 覆盖层与资产解耦：playbook 原文没被碰
    assert "反感感叹号" in store.read_skill("营销", "文案写作") or \
           "反感感叹号" in store.read_preferences("营销")


def test_stale_overrides_detected(tmp_path):
    store = _store(tmp_path)
    items = inject.iter_injection_items(store, "营销", "文案写作")
    fid = next(it["id"] for it in items if it["kind"] == "failure")
    store.upsert_override(fid, text="已改")
    assert inject.stale_override_ids(store) == []

    # 条目被淘汰（playbook 重写掉该条）→ 覆盖 stale
    store.write_skill("营销", "文案写作", PLAYBOOK.replace(
        "- [Solidified] 纯情绪文案不做利益承诺（出现 3 次）\n", ""))
    stale = inject.stale_override_ids(store)
    assert stale == [fid]
    for oid in stale:
        store.remove_override(oid)
    assert inject.stale_override_ids(store) == []


def test_preview_shape(tmp_path):
    store = _store(tmp_path)
    prev = inject.injection_preview(store, "营销", "文案写作")
    assert prev["budget"] == inject.EXPERIENCE_BUDGET_TOKENS
    assert prev["used"] > 0
    assert len(prev["items"]) == 6
    assert all(i["enabled"] and not i["overridden"] for i in prev["items"])
    assert prev["stale_overrides"] == []


# ---------- 失败模式否决 ----------

def test_reject_failure_mode(tmp_path):
    store = _store(tmp_path)
    assert engine_curation.remove_failure_mode(
        store, "营销", "文案写作", "纯情绪文案不做利益承诺（出现 3 次）") is True
    md = store.read_skill("营销", "文案写作")
    assert "纯情绪文案" not in md
    assert "[Watching]" in md  # 其他条目不动
    assert engine_curation.remove_failure_mode(
        store, "营销", "文案写作", "不存在的条目") is False
    log = (store.data_dir / "changelog.md").read_text(encoding="utf-8")
    assert "用户否决失败模式" in log


def test_failure_mode_trajectory(tmp_path):
    store = _store(tmp_path)
    store.append_experience({"task": "写标题", "state": "点击率低",
                             "action": "纯情绪文案", "G": 0.3, "g_source": "auto",
                             "corrected": True, "agent": "workbuddy",
                             "trunk": "营销", "category": "文案写作",
                             "ts": "2026-08-20T10:00:00Z"})
    store.append_experience({"task": "写标题2", "state": "",
                             "action": "利益点前置", "G": 0.8, "g_source": "judge",
                             "agent": "workbuddy", "trunk": "营销",
                             "category": "文案写作", "ts": "2026-08-21T10:00:00Z"})
    traj = engine_curation.failure_mode_trajectory(store, "营销", "文案写作")
    assert len(traj) == 1  # 只有低 G/被纠正的进轨迹
    assert traj[0]["task"] == "写标题"


# ---------- 偏好重归纳 / 自整理 ----------

def test_reinduct_keeps_confirmed(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.append_experience({"task": "t", "state": "s", "action": "a",
                             "G": 0.2, "corrected": True, "agent": "x",
                             "trunk": "营销", "category": "文案写作"})
    monkeypatch.setattr(llm, "model_available", lambda s, r=None: True)
    monkeypatch.setattr(llm, "call_model",
                        lambda store, msgs: "- 少用感叹号（新）\n- 段落要短（新）")
    result = engine_curation.reinduct_preferences(store, "营销")
    assert result["status"] == "ok"
    assert result["confirmed"] == 1
    md = store.read_preferences("营销")
    assert "[UserConfirmed]" in md
    assert "少用感叹号（新）" in md


def test_reinduct_no_data(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(llm, "model_available", lambda s, r=None: True)
    assert engine_curation.reinduct_preferences(store, "营销")["status"] == "no_data"


def test_reinduct_no_model_guarded(tmp_path, monkeypatch):
    """无模型时守卫在调模型前拦截 → no_model，绝不裸调 call_model 抛"未配置模型"。"""
    store = _store(tmp_path)  # 默认无模型
    store.append_experience({"task": "t", "state": "s", "action": "a",
                             "G": 0.2, "corrected": True, "agent": "x",
                             "trunk": "营销", "category": "文案写作"})
    assert llm.model_available(store) is False

    def _boom(store, msgs, **kw):
        raise AssertionError("无模型时不应调 call_model（守卫失效）")

    monkeypatch.setattr(llm, "call_model", _boom)
    result = engine_curation.reinduct_preferences(store, "营销")
    assert result["status"] == "no_model"


def test_compact_under_budget_skips(tmp_path, monkeypatch):
    store = _store(tmp_path)
    called = []
    monkeypatch.setattr(llm, "call_model", lambda s, m: called.append(1) or "- x")
    assert engine_curation.compact_preferences(store, "营销")["status"] == "skipped"
    assert not called  # 未超预算不花模型调用


def test_compact_merges_and_keeps_confirmed(tmp_path, monkeypatch):
    store = _store(tmp_path)
    # 造一个超 400 token 的偏好
    long_prefs = "# 营销 · 偏好画像\n\n" + "\n".join(
        [f"- 用户确认过的第{i}条偏好必须保留 [UserConfirmed]" if i < 2
         else f"- 第{i}条归纳偏好：结论先行、带数字、少感叹号、克制表达、参数化步骤"
         for i in range(40)]) + "\n"
    store.write_preferences("营销", long_prefs)
    assert inject.estimate_tokens(
        "\n".join(ln for ln in long_prefs.splitlines() if ln.strip().startswith("-"))
    ) > engine_curation.PREFERENCE_BUDGET_TOKENS
    monkeypatch.setattr(llm, "call_model", lambda s, m: (
        "- 第0条归纳偏好：结论先行（合并版）\n"
        "- 第1条用户确认过的第0条偏好必须保留 [UserConfirmed]\n"
        "- 用户确认过的第1条偏好必须保留 [UserConfirmed]"))
    result = engine_curation.compact_preferences(store, "营销")
    assert result["status"] == "ok"
    assert result["before"] == 40
    md = store.read_preferences("营销")
    # 两条确认行一字不改（模型漏掉的补回）
    assert "用户确认过的第0条偏好必须保留 [UserConfirmed]" in md
    assert "用户确认过的第1条偏好必须保留 [UserConfirmed]" in md


# ---------- 成长摘要 ----------

def test_growth_summary(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    today = datetime.now(timezone.utc).date()
    for i in range(4):
        store.append_experience({
            "task": f"t{i}", "action": "a", "G": 0.8 if i % 2 else 0.3,
            "agent": "x", "trunk": "营销", "category": "文案写作",
            "ts": f"{today - timedelta(days=i)}T10:00:00Z",
        })
    # 代理通道 session（磨合度数据源）：5 个独立实例，修正轮数 6→1 递减
    for i, (req, fix) in enumerate([(12, 6), (10, 4), (9, 3), (8, 1), (7, 1)]):
        store.record_session({
            "agent": "workbuddy", "session_id": f"s{i}", "trunk": "营销",
            "category": "文案写作", "req_count": req, "correction_hits": fix,
            "started_at": f"2026-08-{20 + i:02d}T10:00:00Z",
        })
    g = store.growth_summary(days=30)
    assert g["cumulative"]["营销/文案写作"][-1][1] == 4
    assert g["heatmap"]["trunks"] == ["营销"]
    # affinity 按 agent 拆分，键 = agent/trunk/category（fixture agent=workbuddy）
    aff = g["affinity"]["workbuddy/营销/文案写作"]
    # v2 口径：基线 = 前 3 次修正中位数 4；
    # 近期窗口（第 4~5 个实例 1,1）中位数 1
    assert aff["n"] == 5 and aff["level"] == "高"
    assert aff["diff"] == 3  # 主指标：磨合差值 4 − 1
    assert aff["baseline"]["fix"] == 4 and aff["recent"]["fix"] == 1
    assert aff["rounds_pct"] == round((7 - 10) / 10 * 100)  # 辅助百分比 -30
    assert aff["excluded"] is False and aff["sample_note"] is True


def test_growth_affinity_pending(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session({"agent": "x", "session_id": "s1", "trunk": "t",
                          "category": "c", "req_count": 5,
                          "correction_hits": 1, "started_at": "2026-08-25T00:00:00Z"})
    g = store.growth_summary()
    # 键含 agent（fixture agent=x）
    assert g["affinity"]["x/t/c"] == {"n": 1, "level": "待积累"}


# ---------- 规则通道 ----------

def test_rules_crud_and_budget(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    r = store.upsert_rule({"name": "公文格式", "text": "发文字号用六角括号",
                           "trigger": "always"})
    assert r["id"]
    r2 = store.upsert_rule({"id": r["id"], "name": "公文格式",
                            "text": "发文字号用六角括号〔〕", "trigger": "hard-hook"})
    assert r2["text"].endswith("〔〕")
    assert store.remove_rule("ghost") is False
    assert store.remove_rule(r["id"]) is True
    assert store.load_rules() == []


def test_rules_block_hard_hook(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.upsert_rule({"name": "红线", "text": "NEVER 报价超限价",
                       "trigger": "hard-hook", "template_priority": "p0"})
    store.upsert_rule({"name": "关掉的", "text": "这条不生效", "enabled": False})
    block = inject.assemble_rules_block(store, user_content="投标")
    assert "NEVER 报价超限价" in block
    assert "每次必须遵守" in block
    assert "这条不生效" not in block


# ---------- 通知中心 ----------

def test_notify_push_and_cap(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    for i in range(DAILY_CAP + 1):
        push(store, "method_update", f"方法 {i}")
    items = notify.list_notifications(store)
    assert len(items) == DAILY_CAP + 1  # 超限不丢：第 3 条只进列表不占额度
    counted = [it for it in items if it.get("counted")]
    assert len(counted) == DAILY_CAP
    # update_available 不受上限
    assert push(store, "system_notice", "v2 可用") is not None
    # 关闭某类型
    config = store.load_config()
    config["notify"] = {"method_update": False}
    store.save_config(config)
    assert push(store, "method_update", "应被跳过") is None
    # 一键静音
    config["notify_muted"] = True
    store.save_config(config)
    assert push(store, "system_notice", "静音后也不发") is None


def test_notify_mark_read(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    push(store, "method_update", "新坑")
    push(store, "growth_report", "磨合度新高")
    assert notify.unread_count(store) == 2
    n = notify.mark_read(store, None)
    assert n == 2
    assert notify.unread_count(store) == 0


def test_notify_types_complete():
    assert len(NOTIFY_TYPES) == 4
    assert "system_notice" in NOTIFY_TYPES  # W4-04：建议卡「稍后再说」的轻量提醒区


# ---------- SKILL.md 生成 ----------

def test_skill_generate_path_a(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.append_experience({"task": "写标题", "action": "利益点前置",
                             "G": 0.8, "agent": "x", "trunk": "营销",
                             "category": "文案写作"})
    monkeypatch.setattr(llm, "call_model", lambda s, m: (
        "## When to Use（何时使用）\n- 写营销标题\n"
        "## Procedure（成功做法，来自 1 条验证经验）\n1. 利益点前置\n"
        "## Pitfalls（失败模式，来自 0 条踩坑经验）\n- （无）\n"
        "## Verification（怎么确认做对了）\n- 点击率对比"))
    out = skillgen.generate_skill(store, trunk="营销", category="文案写作")
    # R1：frontmatter name 必须 ASCII（agentskills.io 规范），中文展示名进 metadata
    assert out["md"].startswith("---\nname: experientia-skill\n")
    assert "display_name: 营销-文案写作" in out["md"]
    assert "description:" in out["md"]
    assert "## When to Use" in out["md"]
    assert out["source_count"] == 1


def test_skill_generate_path_b_selected(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(llm, "call_model", lambda s, m: "## When to Use（何时使用）\n- x")
    out = skillgen.generate_skill(
        store, selected=[{"task": "t1", "action": "a1", "G": 0.8},
                         {"task": "t2", "action": "a2", "G": 0.3, "corrected": True}])
    assert out["source_count"] == 2
    assert "精选" in out["description"]


def test_skill_generate_no_data(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    with pytest.raises(RuntimeError, match="没有可整理"):
        skillgen.generate_skill(store, trunk="营销", category="空")
