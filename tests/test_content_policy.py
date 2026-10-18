""" · 引擎内容策略（不做假蒸馏 + 内容溯源 + 历史数据治理）。

锁四件事（总纲  /  / ，验收）：

1. **无模型不产出归纳类内容**：`distill()` 返回 `model_required`，目标方法卡
   **字节级未被修改**（mtime + 内容哈希双证），盘上不出现任何"（无）"占位；
2. **有模型产出可溯源**：frontmatter 落 `content_source="model"` + `generated_at`，
   API 逐项透出；
3. **历史"废话"只标记不删除**：`run_content_governance()` 把旧确定性兜底产物
   标 `content_source="none"`，**连跑两次结果一致（幂等）**；
4. **启动迁移重复调用无副作用**（v3 内容溯源标记）。

附：成长叙事门禁（build(model_state=未配置/连不上) 不生成叙事）与 AI 优化
无模型结构化拒绝（不把原文当 AI 结果回给用户）。
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from app.distill import engine_curation, growth_story, llm, maintenance, skill
from app.store import migrations as mig
from app.store.store import Store

MODEL_CFG = {"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                  "type": "local", "model": "qwen"}},
             "default_model": "local"}

CANON = ("## 方法名\n- 投放标题写法\n"
         "## 标准流程\n1. 确认投放目标与人群\n"
         "## 成功要点\n- 利益点前置\n"
         "## 失败模式\n- [Watching] 纯情绪文案点击率低（出现 1 次）\n"
         "## 过时项标记\n（无）\n"
         "## 偏好增量\n（无）\n")

# 旧确定性兜底产物的样子：标准流程/过时项/偏好增量写死"（无）"、不起名
JUNK_CARD = ("# 营销 / 文案写作 · playbook\n\n> version: 3\n\n"
             "## 标准流程\n（无）\n"
             "## 成功要点\n- 利益点前置\n"
             "## 失败模式\n- [Watching] 纯情绪文案点击率低（出现 2 次）\n"
             "## 过时项标记\n（无）\n")

EXPS = [
    {"id": "e1", "ts": "2026-09-01T01:00:00Z", "task": "写标题",
     "action": "利益点前置 + A/B 两版", "G": 0.8, "g_source": "judge",
     "outcome": "点击率 +30%", "trunk": "营销", "category": "文案写作",
     "count": 1},
    {"id": "e2", "ts": "2026-09-01T02:00:00Z", "task": "写标题",
     "action": "纯情绪文案点击率低", "G": 0.3, "g_source": "auto",
     "corrected": True, "trunk": "营销", "category": "文案写作", "count": 1},
]


def _store(tmp_path, config: dict | None = None) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    s.save_config(dict(config or {}))
    return s


def _with_exps(store: Store) -> Store:
    for e in EXPS:
        store.append_experience(dict(e))
    return store


def _fingerprint(path) -> tuple | None:
    """字节级指纹：mtime_ns + 内容 sha256（两者都变才算真写过）。"""
    p = Path(path)
    if not p.exists():
        return None
    return (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())


# ---------- 1. 无模型 → 不产出、不写卡、不覆盖 ----------

def test_distill_without_model_returns_model_required(tmp_path):
    store = _with_exps(_store(tmp_path))
    store.write_skill("营销", "文案写作", JUNK_CARD)
    before = _fingerprint(store.skill_path("营销", "文案写作"))

    r = engine_curation.distill(store, "营销", "文案写作")

    assert r["ok"] is False
    assert r["status"] == "model_required"
    assert r["kept_previous"] is True
    assert "未接入模型" in (r.get("message") or "")
    # 字节级未被修改：不写卡、不覆盖、不升版本
    assert _fingerprint(store.skill_path("营销", "文案写作")) == before
    # 素材不被消耗（没有产出就不该打标已蒸馏）
    assert len(store.pending_experiences("营销", "文案写作")) == len(EXPS)
    # 也不落纠正补丁（归纳层同口径）
    assert store.read_fixes("营销", "文案写作") is None


def test_distill_without_model_writes_no_card_when_absent(tmp_path):
    store = _with_exps(_store(tmp_path))
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["status"] == "model_required" and r["kept_previous"] is False
    assert not store.skill_path("营销", "文案写作").exists()


def test_distill_without_model_never_emits_placeholder(tmp_path, monkeypatch):
    """硬禁止：不得为了"卡不为空"重新引入占位正文（"（无）"、模板句、原文罗列）。"""
    store = _with_exps(_store(tmp_path))
    monkeypatch.setattr(llm, "call_model",
                        lambda *a, **kw: pytest.fail("无模型时不应调模型"))
    engine_curation.distill(store, "营销", "文案写作")
    assert store.read_skill("营销", "文案写作") is None
    assert not engine_curation.playbook_has_body("")


def test_distill_empty_model_output_writes_nothing(tmp_path, monkeypatch):
    """有模型但这次没拿到内容 → 不写空卡（旧卡原样保留），如实报 empty_result。"""
    store = _with_exps(_store(tmp_path, MODEL_CFG))
    store.write_skill("营销", "文案写作", JUNK_CARD)
    before = _fingerprint(store.skill_path("营销", "文案写作"))
    monkeypatch.setattr(llm, "call_model", lambda *a, **kw: "谢谢，我已收到。")
    r = engine_curation.distill(store, "营销", "文案写作", force=True)
    assert r["status"] == "empty_result" and r["ok"] is False
    assert r["kept_previous"] is True
    assert _fingerprint(store.skill_path("营销", "文案写作")) == before


# ---------- 2. 有模型 → 正常产出 + 溯源落库 ----------

def test_distill_with_model_stamps_provenance(tmp_path, monkeypatch):
    store = _with_exps(_store(tmp_path, MODEL_CFG))
    monkeypatch.setattr(llm, "call_model", lambda *a, **kw: CANON)
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["status"] == "success" and r["ok"] is True

    md = store.read_skill("营销", "文案写作")
    assert "> content_source: model" in md
    assert "> generated_at:" in md
    src, at = skill.provenance_of(md)
    assert src == "model" and at
    # 章节结构不变（防歪 #3），且模型真的给了正文
    assert "## 标准流程" in md and "1. 确认投放目标与人群" in md
    assert r["content_source"] == "model"


def test_provenance_read_missing_is_unknown():
    """旧卡没有这两个字段 → 空串（**来源未知**），不报错、不补默认值。"""
    assert skill.provenance_of(None) == ("", "")
    assert skill.provenance_of(JUNK_CARD) == ("", "")
    assert skill.provenance_of("## 标准流程\n- x\n") == ("", "")


def test_set_provenance_keeps_sections_and_is_idempotent():
    md = "# a / b · playbook\n\n> version: 1\n\n## 标准流程\n- 步骤\n"
    once = skill.set_provenance(md, "none")
    assert "> content_source: none" in once and "## 标准流程" in once
    twice = skill.set_provenance(once, "none")
    assert twice == once  # 重复写不产生漂移
    # 覆盖旧值（模型重蒸馏 → 来源更新）
    assert skill.set_provenance(once, "model", "2026-09-29T10:00:00+08:00").count(
        "content_source") == 1


# ---------- 3. 历史数据治理：只标记、不删除、幂等 ----------

def test_governance_marks_junk_and_is_idempotent(tmp_path):
    store = _store(tmp_path)
    store.write_skill("营销", "文案写作", JUNK_CARD)
    before = store.read_skill("营销", "文案写作")

    first = maintenance.run_content_governance(store)
    assert first["scanned"] == 1 and first["marked"] == 1
    md1 = store.read_skill("营销", "文案写作")
    assert "> content_source: none" in md1
    # 只标记：正文一字未删（删除必须由用户显式操作）
    assert "纯情绪文案点击率低" in md1 and before.replace("\n", "") != ""

    second = maintenance.run_content_governance(store)
    assert second == {"scanned": 1, "marked": 0}   # 幂等
    assert store.read_skill("营销", "文案写作") == md1


def test_governance_does_not_touch_model_cards(tmp_path, monkeypatch):
    """宁可漏标，绝不误伤模型产物。"""
    store = _with_exps(_store(tmp_path, MODEL_CFG))
    monkeypatch.setattr(llm, "call_model", lambda *a, **kw: CANON)
    engine_curation.distill(store, "营销", "文案写作")
    before = store.read_skill("营销", "文案写作")

    rc = maintenance.run_content_governance(store)
    assert rc["marked"] == 0 and rc["scanned"] == 1
    assert store.read_skill("营销", "文案写作") == before


def test_governance_endpoint_marks_via_api(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    store.write_skill("营销", "文案写作", JUNK_CARD)
    c = local_api_client(store)
    body = c.post("/api/content/governance").json()
    assert body == {"scanned": 1, "marked": 1}
    assert "> content_source: none" in store.read_skill("营销", "文案写作")
    # 清单接口透出，UI 才能挂溯源条
    item = c.get("/api/skills").json()["items"][0]
    assert item["content_source"] == "none"
    assert item["generated_at"] == ""


# ---------- 4. 启动迁移：重复调用无副作用 ----------

def test_startup_migration_marks_once_and_is_idempotent(tmp_path):
    # 已迁到 v2 的存量库（v1 会重置派生资产，这里只验 v3 内容溯源那一步）
    store = _store(tmp_path)
    store.write_skill("营销", "文案写作", JUNK_CARD)
    store.save_meta({"data_version": 2})

    first = mig.run_startup_migrations(store)
    assert first.get("skipped") is False
    assert first.get("content_marked") == 1
    md1 = store.read_skill("营销", "文案写作")
    assert "> content_source: none" in md1

    second = mig.run_startup_migrations(store)
    assert second.get("skipped") is True
    assert store.read_skill("营销", "文案写作") == md1
    assert mig.run_startup_migrations(store) == {"skipped": True}


def test_startup_migration_fresh_install_only_stamps(tmp_path):
    """全新安装：没有方法卡可标，只盖版本戳，不产生任何标记。"""
    store = _store(tmp_path)
    out = mig.run_startup_migrations(store)
    assert out.get("skipped") is False
    assert out.get("content_scanned") == 0 and out.get("content_marked") == 0
    assert store.load_meta().get("data_version") == mig.DATA_VERSION


# ---------- 5. 成长叙事门禁（归纳层） ----------

def test_growth_story_without_model_generates_no_narrative():
    g = {"stage": {"sessions": 12, "weeks": 4},
         "flywheel": {"collected": 30, "distilled": 5, "judged": 5,
                      "injected": 2}}
    story = growth_story.build(g, model_state="unconfigured")
    assert story["content_source"] == "none"
    assert story["text"] == "" and story["has_data"] is False
    # 等价结构：正常叙事用到的键这里全都有（外加一个 text 空串），
    # 调用方（localize / 海报 / 结算卡）按固定键取值不会炸
    normal = growth_story.build(g)
    assert set(normal).issubset(set(story))
    loc = growth_story.localize(story, growth_story._zh)
    assert loc["gears"] == [] and loc["questions"] == []
    assert growth_story.sections_text(story) == {
        "main": [], "questions": [], "milestones": [], "rest": []}


def test_growth_story_with_model_stamps_provenance():
    g = {"stage": {"sessions": 12}}
    story = growth_story.build(g, model_state="available")
    assert story["content_source"] == "model" and story["generated_at"]
    # 调用方未判模型（默认）→ 未知态：叙事照旧，来源留空（UI 不挂条）
    assert growth_story.build(g)["content_source"] == ""


# ---------- 6. AI 优化：无模型结构化拒绝，不拿原文冒充 ----------

def test_optimize_override_without_model_is_structured_refusal(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    c = local_api_client(store)
    r = c.post("/api/injection-preview/optimize", json={"text": "利益点前置"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["status"] == "model_required"
    assert body["message"] and "未接入模型" in body["message"]
    # 关键：绝不能把原文原样回回去当"AI 优化好了"
    assert body.get("text") != "利益点前置" and not body.get("text")


def test_optimize_override_empty_model_output_is_error(tmp_path, monkeypatch):
    from conftest import local_api_client

    store = _store(tmp_path, MODEL_CFG)
    monkeypatch.setattr(llm, "call_model", lambda *a, **kw: "   ")
    c = local_api_client(store)
    r = c.post("/api/injection-preview/optimize", json={"text": "利益点前置"})
    assert r.status_code == 502


# ---------- 7. 注入预览只披露来源，不动门槛 ----------

def test_injection_preview_exposes_content_source(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    store.write_skill("营销", "文案写作",
                      skill.set_provenance(JUNK_CARD, "none"))
    c = local_api_client(store)
    body = c.get("/api/injection-preview",
                 params={"trunk": "营销", "category": "文案写作"}).json()
    assert body["content_source"] == "none"
    assert "items" in body and "used" in body   # 门槛与预算口径不变


def test_growth_api_exposes_content_source(tmp_path):
    """总纲：GET /api/growth 叙事字段带 content_source / generated_at。"""
    from conftest import local_api_client

    store = _store(tmp_path)
    c = local_api_client(store)
    body = c.get("/api/growth").json()
    assert body["content_source"] == "none"     # 没接模型
    assert body["generated_at"]

    store.save_config(dict(MODEL_CFG))
    assert c.get("/api/growth").json()["content_source"] == "model"


def test_weekly_report_story_is_stamped(tmp_path):
    """结算叙事同样标来源，且**随模型门禁开关**：

    无模型 → `none`，四段皆空（叙事属归纳类，门禁后不再产出，UI 挂溯源条）；
    有模型 → `model` + `generated_at`，叙事照出。

    （门禁由 `weekly_report._story()` 传 `model_available` 启用，见 。）
    """
    from conftest import local_api_client

    store = _store(tmp_path)
    store.record_session({"agent": "codex", "session_id": "s1",
                          "trunk": "营销", "category": "文案写作",
                          "req_count": 3, "correction_hits": 1,
                          "started_at": "2026-09-20T08:00:00Z"})
    c = local_api_client(store)
    body = c.get("/api/weekly-report").json()
    assert body["story"]["content_source"] == "none"
    assert body["story"]["generated_at"] == ""
    assert not body["sections"]["main"], "无模型时叙事不应产出（归纳类内容）"

    store.save_config(dict(MODEL_CFG))
    body = c.get("/api/weekly-report").json()
    assert body["story"]["content_source"] == "model"
    assert body["story"]["generated_at"]


# ---------- 8. 无模型降级：三态分治 + 统计不为假 0 ----------
#
# 布尔 model_available 把"压根没配"与"配了连不上"压成同一个 False，卡片只会
# 给一句通用空话（外加一行 0 个助手 / 0 个项目——用户干了活却报 0）。这里锁
# 三件事：状态分开判、统计照给、引导段给得出下一步。

def test_model_state_tri_state(tmp_path):
    store = _store(tmp_path)
    assert llm.model_state(store) == llm.MODEL_STATE_UNCONFIGURED

    store.save_config(dict(MODEL_CFG))
    assert llm.model_state(store) == llm.MODEL_STATE_AVAILABLE
    # 端点要能被文案点名（云端用户不该看到"检查 127.0.0.1:8080"）
    assert llm.model_endpoint(store) == "http://127.0.0.1:8081/v1"

    # 熔断 open = 连续失败的真实证据 → 配了连不上（不试连，零网络）
    store.save_config({**MODEL_CFG, "model_breaker": {
        "state": "open", "fail_count": 3, "cooldown": 300,
        "opened_at": time.time()}})
    assert llm.model_state(store) == llm.MODEL_STATE_UNREACHABLE
    # 冷却过期 → 回到可用（熔断是"最近"不可用，不是永久判决）
    store.save_config({**MODEL_CFG, "model_breaker": {
        "state": "open", "fail_count": 3, "cooldown": 1,
        "opened_at": time.time() - 60}})
    assert llm.model_state(store) == llm.MODEL_STATE_AVAILABLE


def test_growth_story_unconfigured_keeps_real_counts():
    """只掐叙事，统计照给：干过活就不该报 0 个助手 / 0 个项目。"""
    g = {"stage": {"sessions": 12, "weeks": 4, "agents": 3, "projects": 7,
                   "active_days": 9, "start": "2026-09-01", "end": "2026-09-28"}}
    story = growth_story.build(g, model_state=llm.MODEL_STATE_UNCONFIGURED)
    assert story["content_source"] == "none"
    assert story["counts"]["params"] == {"agents": 3, "proj": 7, "days": 9}
    assert story["range"] == "2026-09-01 ~ 2026-09-28"
    # 引导段：正向标题 + 为什么空着 + 单一主操作
    gate = growth_story.localize(story, growth_story._zh)["model_gate"]
    assert gate["state"] == "unconfigured"
    assert gate["title"] and gate["body"] and gate["action"]
    # 叙事仍为空、仍不推送（B 口径不变）
    assert story["headline"]["label"] == "" and story["questions"] == []
    assert growth_story.sections_text(story) == {
        "main": [], "questions": [], "milestones": [], "rest": []}


def test_growth_story_unreachable_names_the_endpoint():
    """连不上要点名是哪个端点——写死 127.0.0.1:8080 对云端 API 是句假话。"""
    g = {"stage": {"sessions": 12, "agents": 1, "projects": 2,
                   "active_days": 3}}
    story = growth_story.build(g, model_state=llm.MODEL_STATE_UNREACHABLE,
                               endpoint="http://127.0.0.1:8080/v1")
    gate = growth_story.localize(story, growth_story._zh)["model_gate"]
    assert gate["state"] == "unreachable"
    assert "127.0.0.1:8080" in gate["body"]
    assert gate["action"] != growth_story.GATE_ACTION_UNCONFIGURED


def test_weekly_report_story_gate_states(tmp_path):
    """结算卡吃到的 model_gate 随模型状态走（无配置 / 可用 / 连不上）。"""
    from conftest import local_api_client

    store = _store(tmp_path)
    store.record_session({"agent": "codex", "session_id": "s1",
                          "trunk": "营销", "category": "文案写作",
                          "req_count": 3, "correction_hits": 1,
                          "started_at": "2026-09-20T08:00:00Z"})
    c = local_api_client(store)
    assert c.get("/api/weekly-report").json()["story"]["model_gate"][
        "state"] == "unconfigured"

    store.save_config(dict(MODEL_CFG))
    body = c.get("/api/weekly-report").json()
    assert body["story"]["model_gate"]["state"] == "available"
    assert body["story"]["counts"]["params"]["days"] >= 0   # 统计键始终存在

    store.save_config({**MODEL_CFG, "model_breaker": {
        "state": "open", "fail_count": 3, "cooldown": 300,
        "opened_at": time.time()}})
    body = c.get("/api/weekly-report").json()
    assert body["story"]["model_gate"]["state"] == "unreachable"
    assert body["story"]["content_source"] == "none"
