"""本地 API 测试（Phase 3，GUI 的第一批数据面）。"""

import pytest

from app.store.store import Store
from conftest import local_api_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    keys: dict[str, str] = {}
    import keyring

    monkeypatch.setattr(keyring, "set_password", lambda svc, name, pw: keys.update({name: pw}))
    monkeypatch.setattr(keyring, "get_password", lambda svc, name: keys.get(name))
    monkeypatch.setattr(keyring, "delete_password", lambda svc, name: keys.pop(name, None))
    store = Store(tmp_path)
    store.ensure_layout()
    return local_api_client(store), store, keys


# ---------- hooks 管理路由 ----------

def test_hooks_admin_overview_not_swallowed_by_agent_param(client):
    """路由顺序回归：overview 必须先于 {agent} 匹配，否则被吞成 agent 名（GUI 总览 400）。"""
    c, store, _ = client
    r = c.get("/api/hooks/admin/overview")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), dict)


def test_hooks_explain_requires_model(client, monkeypatch):
    """未接入模型 → 409（GUI"先去接模型"兜底提示依赖此状态码）。"""
    c, _, _ = client
    from app.distill import llm

    monkeypatch.setattr(llm, "model_available", lambda s, r=None: False)
    r = c.post("/api/hooks/admin/explain",
               json={"agent": "cursor", "entry_id": "x"})
    assert r.status_code == 409


def test_hooks_explain_returns_model_text(client, monkeypatch):
    """接入模型 → 返回模型大白话；条目不存在 → 404。"""
    c, _, _ = client
    from app.capture import hook_admin as ha
    from app.distill import llm

    monkeypatch.setattr(llm, "model_available", lambda s, r=None: True)
    monkeypatch.setattr(llm, "call_model",
                        lambda s, msgs, **kw: "开新对话时自动跑指定脚本")
    monkeypatch.setattr(
        ha, "list_agent", lambda agent, store=None: {
            "entries": [{"id": "e1", "event": "SessionStart",
                         "command": "curl -X POST "
                                    "http://127.0.0.1:8101/api/hooks/session-start"}]})
    r = c.post("/api/hooks/admin/explain",
               json={"agent": "cursor", "entry_id": "e1"})
    assert r.status_code == 200, r.text
    assert r.json()["text"].startswith("开新对话时")
    r2 = c.post("/api/hooks/admin/explain",
                json={"agent": "cursor", "entry_id": "missing"})
    assert r2.status_code == 404


# ---------- 偏好列表（含内容溯源总纲） ----------

def test_preferences_list_carries_provenance(client, monkeypatch):
    """/api/preferences 必须透出 content_source / generated_at。

    这是偏好页顶部溯源条的唯一数据源（闭合的四条链路里独漏这条）：不透出
    时 content_source 为空 = 来源未知，provenance_bar 恒返回 None → 死码。
    """
    c, store, _ = client
    from datetime import datetime

    from app.distill import llm

    monkeypatch.setattr(llm, "model_available", lambda s, r=None: False)
    store.write_preferences("营销", "- 少用感叹号\n")
    r = c.get("/api/preferences")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["bullets"] == ["- 少用感叹号"]
    assert items[0]["content_source"] == "none"
    # 时间是偏好文件的落地时刻、不是本次请求时刻：读条的人要知道内容有多旧
    path = store.preferences_path("营销")
    assert items[0]["generated_at"] == datetime.fromtimestamp(
        path.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def test_preferences_provenance_model_when_model_available(client, monkeypatch):
    """接了模型 → 标 model（内容可随模型更新，展示层不挂降级条）。"""
    c, store, _ = client
    from app.distill import llm

    monkeypatch.setattr(llm, "model_available", lambda s, r=None: True)
    store.write_preferences("文案", "- 长句拆短句\n")
    it = c.get("/api/preferences").json()["items"][0]
    assert it["content_source"] == "model"
    assert it["generated_at"]


# ---------- 偏好重归纳 ----------

def test_reinduct_requires_model(client, monkeypatch):
    """未接入模型 → 409（GUI"先去接模型"兜底；不再裸调 call_model 抛 500）。"""
    c, store, _ = client
    from app.distill import llm

    store.append_experience({"task": "t", "state": "s", "action": "a",
                             "G": 0.2, "corrected": True, "agent": "x",
                             "trunk": "营销", "category": "文案写作"})
    monkeypatch.setattr(llm, "model_available", lambda s, r=None: False)
    r = c.post("/api/preferences/营销/reinduct")
    assert r.status_code == 409


# ---------- status / config ----------

def test_status_shape(client):
    c, store, _ = client
    r = c.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] and body["data_dir"]
    assert body["proxy_port"] == 8100
    assert "agents" in body and "stats" in body and "yellow_flags" in body


def test_status_lite_skips_detect(client, monkeypatch):
    """M-4：探活口径 lite=1 不跑 registry.detect()（冷缓存全盘探测 2.4s+），
    但仍回探活需要的 data_dir。"""
    c, store, _ = client
    from app.capture import registry

    monkeypatch.setattr(registry, "detect",
                        lambda **kw: pytest.fail("lite 不该触发 detect"))
    r = c.get("/api/status?lite=1")
    assert r.status_code == 200
    body = r.json()
    assert body["data_dir"] and body["agents"] == {}


def test_config_mask_and_merge(client):
    c, store, _ = client
    store.save_config({"models": {"m": {"endpoint": "http://e", "model": "x",
                                        "api_key": "sk-secret"}}})
    body = c.get("/api/config").json()
    assert body["models"]["m"]["api_key"] == "***"

    r = c.put("/api/config", json={"locale": "en", "onboarded": True})
    assert r.status_code == 200
    cfg = store.load_config()
    assert cfg["locale"] == "en" and cfg["onboarded"] is True
    assert cfg["models"]["m"]["endpoint"] == "http://e"  # 合并不覆盖


def test_config_update_allows_ui_theme_not_theme(client):
    """外观切换回归：GUI/启动全链读写 ui_theme，白名单必须放行它、
    且旧名 theme 不得再混入（曾导致设置页"外观切换失败"——PUT 400）。"""
    c, store, _ = client
    r = c.put("/api/config", json={"ui_theme": "dark"})
    assert r.status_code == 200
    assert store.load_config()["ui_theme"] == "dark"
    assert c.put("/api/config", json={"theme": "dark"}).status_code == 400


def test_config_plain_keys_write_and_unknown_rejected(client):
    """普通偏好键直写放行；未知键（含 confirm 与已移除的更新相关键）一律拒绝。"""
    c, store, _ = client
    assert c.put("/api/config", json={"locale": "ja"}).status_code == 200
    assert store.load_config()["locale"] == "ja"
    assert c.put("/api/config", json={"confirm": "anything"}).status_code == 400
    for gone in ("repo_url", "auto_update", "update_signature_public_key"):
        assert c.put("/api/config", json={gone: "x"}).status_code == 400, gone


# ---------- 数据主权：一键彻底删除 ----------

def test_wipe_requires_confirm_token(client):
    c, store, _ = client
    store.append_experience({"agent": "a", "task": "t", "action": "x", "G": 0.3})
    r = c.post("/api/wipe", json={"confirm": "wrong"})
    assert r.status_code == 400
    assert len(list(store.iter_experiences(include_distilled=True))) == 1  # 未删


def test_wipe_erases_and_rebuilds_layout(client):
    c, store, _ = client
    store.append_experience({"agent": "a", "task": "t", "action": "x", "G": 0.3})
    store.save_config({"locale": "en", "onboarded": True})
    r = c.post("/api/wipe", json={"confirm": "WIPE"})
    assert r.status_code == 200
    assert list(store.iter_experiences(include_distilled=True)) == []
    assert store.load_config() == {}  # 配置一并清除
    # 初始布局重建（ensure_layout 幂等）
    assert (store.data_dir / "experience.jsonl").exists()
    assert (store.data_dir / "sessions").is_dir()


# ---------- models CRUD ----------

def test_models_crud(client):
    c, store, keys = client
    assert c.get("/api/models").json()["routes"] == []

    r = c.post("/api/models", json={
        "name": "local-8b", "endpoint": "http://127.0.0.1:8080/v1",
        "model": "Qwen3-8B", "type": "local"})
    assert r.status_code == 200
    assert keys == {}  # 本地模型无 key

    r = c.post("/api/models", json={
        "name": "gpt", "endpoint": "https://api.openai.com/v1",
        "model": "gpt-4o", "key": "sk-api-test"})
    assert r.status_code == 200
    assert keys.get("gpt") == "sk-api-test"
    info = c.get("/api/models").json()
    gpt = next(x for x in info["routes"] if x["name"] == "gpt")
    assert gpt["key_source"] == "keyring"

    # 重名拒绝
    assert c.post("/api/models", json={"name": "gpt", "endpoint": "http://e",
                                       "model": "m"}).status_code == 400

    # set-default / set-distill / clear-distill
    assert c.post("/api/models/local-8b/set-default").status_code == 200
    assert c.post("/api/models/gpt/set-distill").status_code == 200
    info = c.get("/api/models").json()
    assert info["default_model"] == "local-8b" and info["distill_model"] == "gpt"
    assert c.post("/api/models/clear-distill").status_code == 200
    assert c.get("/api/models").json()["distill_model"] is None

    # 不存在的名字 → 404
    assert c.post("/api/models/ghost/set-default").status_code == 404

    # 删除（连带 keyring）
    assert c.delete("/api/models/gpt").status_code == 200
    assert "gpt" not in keys
    cfg = store.load_config()
    assert "gpt" not in cfg["models"] and cfg.get("distill_model") is None
    assert c.delete("/api/models/ghost").status_code == 404


# ---------- experiences + L1 反馈 ----------

def test_experiences_list_and_feedback(client):
    c, store, _ = client
    store.append_experience({"agent": "codex", "task": "写标题", "action": "利益点前置",
                             "trunk": "营销", "category": "文案写作", "G": 0.8,
                             "distilled": True})
    store.append_experience({"agent": "codex", "task": "修端口", "action": "改端口",
                             "trunk": "基础设施", "category": "修服务", "G": 0.3,
                             "corrected": True})

    body = c.get("/api/experiences").json()
    assert body["count"] == 2
    body = c.get("/api/experiences", params={"trunk": "营销"}).json()
    assert body["count"] == 1
    body = c.get("/api/experiences", params={"q": "标题"}).json()
    assert body["count"] == 1

    items = c.get("/api/experiences", params={"trunk": "营销"}).json()["items"]
    exp_id = items[0]["id"]

    # 有效 → G=1.0，已蒸馏经验重置回待蒸馏（重新参与下次蒸馏）
    r = c.post(f"/api/experiences/{exp_id}/feedback", json={"feedback": "valid"})
    assert r.status_code == 200
    upd = store.find_experience(exp_id)
    assert upd["G"] == 1.0 and upd["g_source"] == "user" and upd["distilled"] is False

    # 纠正 → G=0.2
    items = c.get("/api/experiences", params={"trunk": "基础设施"}).json()["items"]
    r = c.post(f"/api/experiences/{items[0]['id']}/feedback", json={"feedback": "corrected"})
    assert r.status_code == 200
    upd = store.find_experience(items[0]["id"])
    assert upd["G"] == 0.2 and upd["corrected"] is True

    # 非法反馈 / 不存在的 id
    assert c.post(f"/api/experiences/{exp_id}/feedback",
                  json={"feedback": "maybe"}).status_code == 400
    assert c.post("/api/experiences/nope/feedback",
                  json={"feedback": "valid"}).status_code == 404


# ---------- skills ----------

def test_skills_endpoints(client, monkeypatch):
    c, store, _ = client
    store.write_skill("营销", "文案写作", "## 标准流程\n1. 步骤")
    body = c.get("/api/skills").json()
    assert body["items"][0]["trunk"] == "营销"
    # 内容溯源（总纲）：旧卡无 content_source → 空串（来源未知，UI 不挂条）
    assert body["items"][0]["content_source"] == ""
    assert body["items"][0]["generated_at"] == ""
    r = c.get("/api/skills/营销/文案写作")
    assert r.status_code == 200 and "标准流程" in r.json()["md"]
    assert c.get("/api/skills/营销/不存在").status_code == 404

    # 无待蒸馏 → 409
    r = c.post("/api/skills/distill", json={"trunk": "营销", "category": "文案写作"})
    assert r.status_code == 409

    # 有待蒸馏但**未接模型** → 结构化拒绝（总纲），不是 4xx 也不是假成功
    store.append_experience({"agent": "codex", "task": "t", "action": "a",
                             "trunk": "营销", "category": "文案写作", "G": 0.8})
    r = c.post("/api/skills/distill", json={"trunk": "营销", "category": "文案写作"})
    assert r.status_code == 200
    assert r.json()["status"] == "model_required"
    assert r.json()["kept_previous"] is True and r.json()["message"]

    # 接上模型 + mock → 蒸馏成功，并落 content_source=model
    store.save_config({"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                            "type": "local", "model": "qwen"}},
                       "default_model": "local"})
    monkeypatch.setattr("app.distill.llm.call_model",
                        lambda store_, messages, **kw: "## 标准流程\n1. 步骤")
    r = c.post("/api/skills/distill", json={"trunk": "营销", "category": "文案写作"})
    assert r.status_code == 200
    assert r.json()["status"] == "success"
    md = store.read_skill("营销", "文案写作")
    assert "> content_source: model" in md and "> generated_at:" in md
    assert c.get("/api/skills").json()["items"][0]["content_source"] == "model"


# ---------- H-A0 多 agent 配装（agents 字段 + 工具清单端点） ----------

def test_rules_agents_source(client):
    """/api/rules/agents = 内置已知 agent（detect 清单）+ 会话里出现过的 agent，去重排序。"""
    c, store, _ = client
    r = c.get("/api/rules/agents")
    assert r.status_code == 200
    agents = r.json()["agents"]
    assert "claude-code" in agents and "codex" in agents  # 内置清单恒在
    assert agents == sorted(agents)
    store.record_session({"agent": "zcode", "session_id": "s1"})
    agents2 = c.get("/api/rules/agents").json()["agents"]
    assert agents2 == sorted(set(agents) | {"zcode"})


def test_rules_upsert_agents_scope_globs(client):
    """POST/PUT /api/rules：agents/scope/globs 透传；缺 agents 归一化 ["*"]；显式 [] 保留。"""
    c, store, _ = client
    r = c.post("/api/rules", json={"name": "a", "text": "t", "trigger": "always",
                                   "agents": ["cursor"], "scope": "glob",
                                   "globs": ["src/**"]})
    assert r.status_code == 200
    rule = r.json()["rule"]
    assert rule["agents"] == ["cursor"] and rule["scope"] == "glob"
    assert rule["globs"] == ["src/**"]

    r2 = c.post("/api/rules", json={"name": "b", "text": "t", "trigger": "always"})
    assert r2.json()["rule"]["agents"] == ["*"]  # 缺省 = 全局

    r3 = c.post("/api/rules", json={"name": "c", "text": "t", "trigger": "always",
                                    "agents": []})
    assert r3.json()["rule"]["agents"] == []  # 未配装 ≠ 全局
    rid = r3.json()["rule"]["id"]
    r4 = c.put(f"/api/rules/{rid}", json={"id": rid, "name": "c", "text": "t",
                                          "trigger": "always", "agents": ["*"]})
    assert r4.json()["rule"]["agents"] == ["*"]  # 重配装


# ---------- R2 改名 / R3 来源 agent ----------

def _pb_md():
    return ("# 营销 / 文案写作 · playbook\n\n"
            "> version: 1\n> updated: 2026-01-01T00:00:00Z\n"
            "> source_exps: （无）\n> confidence: low\n\n"
            "## 标准流程\n- 结论先行\n")


def test_skill_rename_endpoint(client):
    c, store, _ = client
    store.write_skill("营销", "文案写作", _pb_md())
    r = c.put("/api/skills/营销/文案写作/rename", json={"name": "周报数据核对"})
    assert r.status_code == 200
    assert "> name: 周报数据核对" in store.read_skill("营销", "文案写作")
    # 无变化 → 400
    r2 = c.put("/api/skills/营销/文案写作/rename", json={"name": "周报数据核对"})
    assert r2.status_code == 400
    # 两者都不给 → 400
    r3 = c.put("/api/skills/营销/文案写作/rename", json={})
    assert r3.status_code == 400
    # 无方法文件时改显示名 → 400
    r4 = c.put("/api/skills/营销/不存在的类别/rename", json={"name": "x"})
    assert r4.status_code == 400


def test_skill_rename_category_migration(client):
    c, store, _ = client
    store.write_skill("营销", "文案写作", _pb_md())
    store.append_experience({"agent": "codex", "task": "t", "action": "a",
                             "trunk": "营销", "category": "文案写作", "G": 0.8,
                             "ts": "2026-01-01T00:00:00Z"})
    r = c.put("/api/skills/营销/文案写作/rename", json={"category": "报价文案"})
    assert r.status_code == 200
    assert store.read_skill("营销", "文案写作") is None
    assert store.read_skill("营销", "报价文案").startswith("# 营销 / 报价文案")
    items = store.iter_experiences(include_distilled=True)
    assert [e["category"] for e in items] == ["报价文案"]
    # 冲突：目标类别已有方法 → 409
    store.write_skill("营销", "海报设计", _pb_md().replace("文案写作", "海报设计"))
    r2 = c.put("/api/skills/营销/报价文案/rename", json={"category": "海报设计"})
    assert r2.status_code == 409


def test_skill_agents_endpoint(client):
    c, store, _ = client
    base = {"action": "a", "trunk": "营销", "category": "文案写作", "G": 0.8}
    store.append_experience({**base, "task": "t1", "agent": "Codex",
                             "ts": "2026-01-01T00:00:00Z"})
    store.append_experience({**base, "task": "t2", "agent": "Claude Code",
                             "ts": "2026-01-02T00:00:00Z"})
    store.append_experience({**base, "task": "t3", "agent": "Claude Code",
                             "ts": "2026-01-03T00:00:00Z"})
    r = c.get("/api/skills/营销/文案写作/agents")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3 and body["latest"] == "2026-01-03T00:00:00Z"
    assert body["agents"][0] == {"agent": "Claude Code", "count": 2,
                                 "latest": "2026-01-03T00:00:00Z"}
    # 缺 agent 字段 → 归入「未知」
    store.append_experience({**base, "task": "t4", "agent": "",
                             "ts": "2026-01-04T00:00:00Z"})
    body = c.get("/api/skills/营销/文案写作/agents").json()
    assert {"agent": "未知", "count": 1, "latest": "2026-01-04T00:00:00Z"} in body["agents"]


def _age_rule_created(store, rule_id, days: int):
    """把某条规则的 created_at 改写为 N 天前（H-O2 过时判定测试用）。"""
    import json
    from datetime import datetime, timedelta, timezone

    p = store.data_dir / "rules.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for r in data.get("rules", []):
        if r.get("id") == rule_id:
            r["created_at"] = (datetime.now(timezone.utc)
                               - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_rules_endpoint_hits_and_stale(client):
    """H-O2：/api/rules 合并 hit_count/last_hit/stale；stale = N 天未命中（可配）。"""
    c, store, _ = client
    store.upsert_rule({"id": "h1", "name": "fresh", "text": "t", "trigger": "always"})
    store.upsert_rule({"id": "h2", "name": "old-never", "text": "t", "trigger": "always"})
    store.upsert_rule({"id": "h3", "name": "old-hit", "text": "t", "trigger": "always"})
    cfg = store.load_config()
    cfg["hook_stale_days"] = 7
    store.save_config(cfg)
    _age_rule_created(store, "h2", 10)  # 从未命中 + 存在 10 天 > 7 → 过时
    _age_rule_created(store, "h3", 10)  # 存在 10 天但今天命中 → 不过时
    store.record_rule_hits(["h1", "h3"])

    body = c.get("/api/rules").json()
    assert body["stale_days"] == 7
    items = {i["id"]: i for i in body["items"]}
    assert items["h1"]["hit_count"] == 1 and items["h1"]["last_hit"]
    assert items["h1"]["stale"] is False
    assert items["h2"]["hit_count"] == 0 and items["h2"]["last_hit"] is None
    assert items["h2"]["stale"] is True
    assert items["h3"]["hit_count"] == 1 and items["h3"]["stale"] is False


def test_rules_endpoint_conflict_markers(client):
    """H-O3：同优先级矛盾（dont 原句出现在对方应当正文）/ 正文重复 → conflict=True；
    不同优先级不标（P0 锁定已解决最高优先级冲突，同档才提示）。"""
    c, store, _ = client
    store.upsert_rule({"id": "a1", "name": "a", "text": "优先使用内部组件库",
                       "trigger": "smart"})
    store.upsert_rule({"id": "a2", "name": "b", "text": "b", "trigger": "smart",
                       "donts": ["优先使用内部组件库"]})
    store.upsert_rule({"id": "c1", "name": "c", "text": "用六角括号",
                       "trigger": "always"})          # p1
    store.upsert_rule({"id": "c2", "name": "d", "text": "d", "trigger": "smart",
                       "donts": ["用六角括号"]})       # p2（跨档不标）
    store.upsert_rule({"id": "d1", "name": "dup1", "text": "同一正文",
                       "trigger": "smart"})
    store.upsert_rule({"id": "d2", "name": "dup2", "text": "同一正文",
                       "trigger": "smart"})
    items = {i["id"]: i for i in c.get("/api/rules").json()["items"]}
    assert items["a1"]["conflict"] is True and items["a2"]["conflict"] is True
    assert items["c1"]["conflict"] is False and items["c2"]["conflict"] is False
    assert items["d1"]["conflict"] is True and items["d2"]["conflict"] is True


def test_rules_donts_roundtrip(client):
    """RuleIn 透传 donts：保存后读回一致；清空传 [] 生效。"""
    c, store, _ = client
    r = c.post("/api/rules", json={"name": "a", "text": "t", "trigger": "smart",
                                   "donts": ["别这样", "也别那样"]})
    assert r.status_code == 200
    rid = r.json()["rule"]["id"]
    items = {i["id"]: i for i in c.get("/api/rules").json()["items"]}
    assert items[rid]["donts"] == ["别这样", "也别那样"]
    c.put(f"/api/rules/{rid}", json={"id": rid, "name": "a", "text": "t",
                                     "trigger": "smart", "donts": []})
    items = {i["id"]: i for i in c.get("/api/rules").json()["items"]}
    assert items[rid]["donts"] == []
