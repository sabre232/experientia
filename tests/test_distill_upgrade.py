"""W3 蒸馏升级：纠正补丁（双层提炼）+ 注入成对 + 分层下钻 + 质量评分（LLM mock）。"""

from app.distill import engine_curation
from app.proxy import inject
from app.store.store import Store
from conftest import local_api_client


EXP_HIGH = {"agent": "codex", "task": "写投放标题", "action": "利益点前置 + A/B 两版",
            "G": 0.8, "g_source": "judge", "trunk": "营销", "category": "文案写作",
            "outcome": "点击率 +30%", "session_id": "sess-1"}
EXP_CORRECTED = {"agent": "codex", "task": "写投放标题", "action": "纯情绪文案",
                 "G": 0.2, "g_source": "user", "corrected": True,
                 "trunk": "营销", "category": "文案写作", "state": "点击率低",
                 "session_id": "sess-1"}

PLAYBOOK_CANON = """## 标准流程
1. 确认投放目标与人群

## 成功要点
- 利益点前置句式有效

## 失败模式
- [Solidified] 纯情绪文案点击率低（出现 3 次）

## 过时项标记
（无）

## 偏好增量
（无）
"""

FIXES_CANON = """## 纠正补丁
- 遇到首版标题点击率低，不要继续打磨原文案，改为利益点前置句式
"""


def _mock_llm(monkeypatch):
    def fake(store, messages, **kw):
        prompt = messages[0]["content"]
        if "失败分析师" in prompt:
            return FIXES_CANON
        return PLAYBOOK_CANON

    monkeypatch.setattr("app.distill.llm.call_model", fake)


MODEL_CFG = {"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                    "type": "local", "model": "qwen"}},
             "default_model": "local"}


def _store(tmp_path, exps, with_session=True):
    """蒸馏要走模型路径（后无模型一律不产出），故默认带上模型配置。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_config(dict(MODEL_CFG))
    for e in exps:
        store.append_experience(dict(e))
    if with_session:
        store.record_session({"agent": "codex", "session_id": "sess-1",
                              "trunk": "营销", "category": "文案写作",
                              "req_count": 5, "started_at": "2026-08-28T08:00:00Z",
                              "user_messages": ["帮我写个投放标题", "再改一版"]})
    return store


# ---------- W3-01：纠正补丁新资产 ----------

def test_distill_with_corrected_writes_fixes(tmp_path, monkeypatch):
    store = _store(tmp_path, [EXP_HIGH, EXP_CORRECTED])
    # 模型路径需要配置（switcher：没配走确定性降级，不会用 canned 补丁）
    store.save_config({"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                            "type": "local", "model": "qwen"}},
                       "default_model": "local"})
    _mock_llm(monkeypatch)
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["status"] == "success"
    assert r["fixes"] is not None
    fixes = store.read_fixes("营销", "文案写作")
    assert "纠正补丁" in fixes
    assert "不要继续打磨原文案" in fixes
    # _fixes.md 与 playbook 同目录，但不是方法清单的一部分
    assert [s["category"] for s in store.list_skills()] == ["文案写作"]
    assert store.fixes_path("营销", "文案写作").exists()


def test_distill_without_corrected_no_fixes(tmp_path, monkeypatch):
    """验收：无 corrected 经验时不产出空补丁文件。"""
    store = _store(tmp_path, [EXP_HIGH])
    _mock_llm(monkeypatch)
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["status"] == "success"
    assert r["fixes"] is None
    assert not store.fixes_path("营销", "文案写作").exists()


def test_fixes_version_increments(tmp_path, monkeypatch):
    store = _store(tmp_path, [EXP_HIGH, EXP_CORRECTED])
    _mock_llm(monkeypatch)
    engine_curation.distill(store, "营销", "文案写作")
    assert "version: 1" in store.read_fixes("营销", "文案写作")
    store.append_experience(dict(EXP_CORRECTED, task="写社媒短文案", id="x2"))
    engine_curation.distill(store, "营销", "文案写作")
    assert "version: 2" in store.read_fixes("营销", "文案写作")


def test_fixes_failure_does_not_break_playbook(tmp_path, monkeypatch):
    """失败分析师抛错 → playbook 照常落盘（双层互不拖累）；
    补丁侧落入原样罗列兜底（蒸馏兜底方案：配了但调不通也要回落）。"""
    store = _store(tmp_path, [EXP_HIGH, EXP_CORRECTED])
    store.save_config({"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                            "type": "local", "model": "qwen"}},
                       "default_model": "local"})

    def fake(store_, messages, **kw):
        if "失败分析师" in messages[0]["content"]:
            raise RuntimeError("模型不可用")
        return PLAYBOOK_CANON

    monkeypatch.setattr("app.distill.llm.call_model", fake)
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["status"] == "success"
    assert store.read_skill("营销", "文案写作")
    # 补丁回落：被纠正经验原样罗列（state/action 原文，不归纳）
    assert r["fixes"] is not None
    fixes = store.read_fixes("营销", "文案写作")
    assert "遇到 点击率低，不要 纯情绪文案" in fixes


# ---------- W3-02：注入成对 + 预算优先级 ----------

def _store_with_assets(tmp_path):
    store = _store(tmp_path, [EXP_HIGH, EXP_CORRECTED])
    store.write_skill("营销", "文案写作", PLAYBOOK_CANON)
    store.write_fixes("营销", "文案写作",
                      "# 营销 / 文案写作 · 纠正补丁\n\n## 纠正补丁\n"
                      "- 遇到首版标题点击率低，不要继续打磨原文案，改为利益点前置句式\n")
    return store


def test_fix_items_injected_after_failure(tmp_path):
    store = _store_with_assets(tmp_path)
    items = inject.iter_injection_items(store, "营销", "文案写作")
    kinds = [it["kind"] for it in items]
    assert "failure" in kinds and "fix" in kinds
    # 补丁紧跟坑之后（成对注入）
    assert kinds.index("fix") == kinds.index("failure") + 1
    fix = next(it for it in items if it["kind"] == "fix")
    assert fix["section"] == "纠正补丁：文案写作"
    assert "改为利益点前置句式" in fix["text"]


def test_fix_priority_in_budget_ladder(tmp_path):
    """预算分层截断：坑 > 补丁 > 流程。预算恰好容纳"坑+补丁"时流程被截。"""
    store = _store_with_assets(tmp_path)
    items = inject.iter_injection_items(store, "营销", "文案写作")
    failure_part = "[失败模式]\n" + "\n".join(
        f"- {it['text']}" for it in items if it["kind"] == "failure")
    fix_part = "[纠正补丁：文案写作]\n" + "\n".join(
        f"- {it['text']}" for it in items if it["kind"] == "fix")
    budget = inject.estimate_tokens(failure_part) + inject.estimate_tokens(fix_part)
    block = inject.assemble_experience_block(store, "营销", "文案写作", budget=budget)
    assert "失败模式" in block          # 第 2 层：坑最先保
    assert "纠正补丁：文案写作" in block  # 第 3 层：补丁优先于流程
    assert "标准流程" not in block       # 第 4 层：流程被截


def test_no_fixes_file_no_fix_items(tmp_path):
    store = _store(tmp_path, [EXP_HIGH])
    store.write_skill("营销", "文案写作", PLAYBOOK_CANON)
    items = inject.iter_injection_items(store, "营销", "文案写作")
    assert all(it["kind"] != "fix" for it in items)


# ---------- W3-03/05：frontmatter 来源链 + 质量评分 ----------

def test_frontmatter_has_source_exps_and_confidence(tmp_path, monkeypatch):
    store = _store(tmp_path, [EXP_HIGH, EXP_CORRECTED])
    _mock_llm(monkeypatch)
    engine_curation.distill(store, "营销", "文案写作")
    md = store.read_skill("营销", "文案写作")
    assert "> source_exps:" in md
    # 2 条来源（<3）→ low
    assert "> confidence: low" in md
    # 来源 id 必须指向真实存在的经验
    line = [ln for ln in md.splitlines() if ln.startswith("> source_exps:")][0]
    ids = [x.strip() for x in line.split(":", 1)[1].split(",") if x.strip()]
    all_ids = {str(e.get("id")) for e in store.iter_experiences(include_distilled=True)}
    assert set(ids) <= all_ids


def test_confidence_high_when_user_feedback(tmp_path, monkeypatch):
    exps = [dict(EXP_HIGH), dict(EXP_CORRECTED),
            dict(EXP_HIGH, task="写双十一主标题", id="e3",
                 g_source="user", outcome="点击率 +50%")]
    store = _store(tmp_path, exps)
    _mock_llm(monkeypatch)
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["confidence"] == "high"
    assert "> confidence: high" in store.read_skill("营销", "文案写作")


def test_confidence_medium_without_user_feedback(tmp_path, monkeypatch):
    """3 条来源但无用户确认（corrected/用户反馈）→ medium。"""
    exps = [dict(EXP_HIGH),
            dict(EXP_HIGH, task="写双十一主标题", id="e2"),
            dict(EXP_HIGH, task="写社媒短文案", id="e3")]
    store = _store(tmp_path, exps)
    _mock_llm(monkeypatch)
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["confidence"] == "medium"


def test_confidence_counts_corrected_as_user_confirmed(tmp_path, monkeypatch):
    """被纠正 = 用户确认（review 通道 corrected 的 g_source 是 auto，不能只看 g_source）。"""
    exps = [dict(EXP_HIGH),
            dict(EXP_CORRECTED, g_source="auto"),
            dict(EXP_HIGH, task="写双十一主标题", id="e3")]
    store = _store(tmp_path, exps)
    _mock_llm(monkeypatch)
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["confidence"] == "high"


# ---------- W3-03/04：下钻端点（方法 → 经验 → session 摘要） ----------

def test_sources_endpoint_drilldown(tmp_path, monkeypatch):
    store = _store(tmp_path, [EXP_HIGH, EXP_CORRECTED])
    _mock_llm(monkeypatch)
    engine_curation.distill(store, "营销", "文案写作")
    client = local_api_client(store)
    r = client.get("/api/skills/营销/文案写作/sources")
    assert r.status_code == 200
    body = r.json()
    assert body["missing"] == 0
    assert len(body["exps"]) == 2
    e1 = next(e for e in body["exps"] if e["task"] == "写投放标题")
    # 只给摘要：首条 user 消息截断 + 轮数，不给全文
    assert e1["session"]["first_msg"] == "帮我写个投放标题"
    assert e1["session"]["req_count"] == 5
    assert e1["session"]["agent"] == "codex"
    assert e1["corrected"] is False


def test_sources_endpoint_missing_skill_404(tmp_path):
    store = _store(tmp_path, [EXP_HIGH], with_session=False)
    client = local_api_client(store)
    r = client.get("/api/skills/不存在的/类目/sources")
    assert r.status_code == 404


# ---------- R1：蒸馏时智能命名（说人话短名，非术语） ----------

def test_distill_adopts_model_name(tmp_path, monkeypatch):
    def fake(store, messages, **kw):
        prompt = messages[0]["content"]
        if "失败分析师" in prompt:
            return FIXES_CANON
        return "## 方法名\n- 投标报价核算\n\n" + PLAYBOOK_CANON

    monkeypatch.setattr("app.distill.llm.call_model", fake)
    store = _store(tmp_path, [EXP_HIGH, EXP_CORRECTED])
    # 模型命名需要配置（switcher：没配走确定性降级，不产方法名）
    store.save_config({"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                            "type": "local", "model": "qwen"}},
                       "default_model": "local"})
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["name"] == "投标报价核算"
    md = store.read_skill("营销", "文案写作")
    assert "> name: 投标报价核算" in md
    assert "> name_source: auto" in md
    assert store.list_skills()[0]["name"] == "投标报价核算"


def test_distill_keeps_manual_name(tmp_path, monkeypatch):
    """用户手改的名（name_source=manual）蒸馏不得覆盖——代码侧硬保证。"""
    def fake(store, messages, **kw):
        return "## 方法名\n- 模型新名\n\n" + PLAYBOOK_CANON

    monkeypatch.setattr("app.distill.llm.call_model", fake)
    store = _store(tmp_path, [EXP_HIGH, EXP_CORRECTED])
    store.write_skill("营销", "文案写作",
                      "# 营销 / 文案写作 · playbook\n\n"
                      "> name: 周报数据核对\n> name_source: manual\n"
                      "> version: 1\n> updated: 2026-01-01T00:00:00Z\n"
                      "> source_exps: （无）\n> confidence: low\n\n"
                      "## 标准流程\n- 步骤一\n")
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["name"] == "周报数据核对"
    md = store.read_skill("营销", "文案写作")
    assert "> name: 周报数据核对" in md
    assert "> name_source: manual" in md
    assert "模型新名" not in md


def test_distill_no_name_line_when_model_none(tmp_path, monkeypatch):
    """模型没给方法名 → 不写 name 行（展示层回退项目/类别两级路径），不留术语。"""
    store = _store(tmp_path, [EXP_HIGH])
    _mock_llm(monkeypatch)
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["name"] is None
    md = store.read_skill("营销", "文案写作")
    assert "> name:" not in md
    assert store.list_skills()[0]["name"] is None
