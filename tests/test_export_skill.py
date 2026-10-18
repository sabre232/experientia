"""Phase 6 测试：五粒度导出+ 全量打包 + Skill 版本化/diff+ 本地 API 端点。"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.distill import export as exporter, llm, skill as skillgen
from app.store.store import Store
from conftest import local_api_client

TODAY = date.today()
# store 的时间口径是 UTC（ts 存 "…Z"，growth_summary 按 UTC 开窗）：
# UTC+8 机器本地 0:00–8:00 间本地日期领先 UTC 一天，growth 测试必须按 UTC 播种
UTC_TODAY = datetime.now(timezone.utc).date()


def _store(tmp_path) -> Store:
    store = Store(tmp_path)
    store.ensure_layout()
    return store


def _exp(store, task="写投放标题", trunk="营销", category="文案写作",
         ts=None, G=0.9, **kw) -> dict:
    rec = {"task": task, "trunk": trunk, "category": category,
           "agent": "Codex", "model": "local",
           "ts": (ts or TODAY).isoformat() + "T10:00:00+00:00",
           "G": G, "action": "利益点前置", "outcome": "点击率 +30%", **kw}
    return store.append_experience(rec)


# ---------- 粒度 1：经验 ----------

def test_export_experiences_success_and_failure(tmp_path):
    store = _store(tmp_path)
    _exp(store, task="双十一主标题", G=0.9)
    _exp(store, task="社媒短文案", G=0.3, state="纯情绪文案转化低")
    r = exporter.export_experiences(store, trunk="营销", category="文案写作")
    md = r["md"]
    assert "经验导出：营销 / 文案写作" in md
    assert "经验条数：2 条（成功 1 / 避坑 1）" in md
    assert "## 成功经验" in md and "## 失败模式" in md
    assert "### 文案写作 - 双十一主标题" in md
    assert "- 来源：Codex · local" in md
    assert "- 做法：利益点前置" in md          # 成功 → 做法
    assert "- 踩坑：纯情绪文案转化低" in md
    assert "- 教训：利益点前置" in md           # 失败 → 教训
    assert r["filename"].endswith(".md")


def test_export_experiences_corrected_counts_as_failure(tmp_path):
    store = _store(tmp_path)
    _exp(store, G=0.9, corrected=True)
    r = exporter.export_experiences(store)
    assert "成功 0 / 避坑 1" in r["md"]


def test_export_experiences_empty_no_crash(tmp_path):
    store = _store(tmp_path)
    r = exporter.export_experiences(store, trunk="不存在", category="不存在")
    assert "经验条数：0 条" in r["md"]


def test_export_experiences_settled_section(tmp_path):
    """模板：蒸馏过的类别 → 经验条之后附「已沉淀的方法」要点。"""
    store = _store(tmp_path)
    _exp(store, task="双十一主标题", G=0.9)
    store.write_skill("营销", "文案写作",
                      "# 营销 / 文案写作 · playbook\n\n"
                      "> name: 投放标题方法\n"
                      "## 成功要点\n- 标题用利益点前置句式\n- 每次至少 A/B 测试两版\n\n"
                      "## 失败模式\n- [Solidified] 纯情绪文案点击率低（出现 3 次）\n")
    md = exporter.export_experiences(store, trunk="营销", category="文案写作")["md"]
    assert "## 已沉淀的方法（如有）" in md
    assert "**成功策略**" in md and "- 标题用利益点前置句式" in md
    assert "**失败模式**" in md and "[Solidified] 纯情绪文案点击率低（出现 3 次）" in md
    # 顺序：经验条 → 沉淀方法（结论垫底，先轨迹后结论）
    assert md.index("## 成功经验") < md.index("## 已沉淀的方法（如有）")


def test_export_experiences_no_settled_without_playbook(tmp_path):
    """没有蒸馏过 → 不附「已沉淀的方法」节（不为空壳撑场面）。"""
    store = _store(tmp_path)
    _exp(store, task="双十一主标题", G=0.9)
    md = exporter.export_experiences(store, trunk="营销", category="文案写作")["md"]
    assert "已沉淀的方法" not in md


def test_export_experiences_settled_trunk_scope(tmp_path):
    """单项目导出（无类别）→ 逐类别小节（### 类别 + 两组要点）。"""
    store = _store(tmp_path)
    _exp(store, trunk="营销", category="文案写作")
    _exp(store, trunk="营销", category="投放", task="渠道选择")
    store.write_skill("营销", "文案写作",
                      "## 成功要点\n- 利益点前置\n## 失败模式\n- 纯情绪转化低")
    # 投放 playbook 没有「成功要点」→ 成功策略回退「标准流程」
    store.write_skill("营销", "投放", "## 标准流程\n- 先定人群包再选渠道")
    md = exporter.export_experiences(store, trunk="营销")["md"]
    assert "### 文案写作" in md and "### 投放" in md
    assert "- 利益点前置" in md and "- 纯情绪转化低" in md
    # 成功要点缺失时回退标准流程
    assert "- 先定人群包再选渠道" in md


def test_export_experiences_ids_selection_no_settled(tmp_path):
    """精选（ids）跨类别 → 不附沉淀节（范围与 playbook 不对应）。"""
    store = _store(tmp_path)
    e1 = _exp(store, task="双十一主标题", G=0.9)
    _exp(store, trunk="营销", category="投放", task="渠道选择")
    store.write_skill("营销", "文案写作",
                      "## 成功要点\n- 利益点前置\n## 失败模式\n- 纯情绪转化低")
    md = exporter.export_experiences(store, ids=[e1["id"]])["md"]
    assert "精选" in md
    assert "已沉淀的方法" not in md


# ---------- 粒度 2/3：playbook / 偏好 ----------

def test_export_playbook_wraps_md(tmp_path):
    store = _store(tmp_path)
    store.write_skill("营销", "文案写作", "# playbook\n\n## 成功要点\n- x")
    r = exporter.export_playbook(store, "营销", "文案写作")
    assert "方法导出：营销 / 文案写作" in r["md"]
    assert "## 成功要点" in r["md"]


def test_export_playbook_missing_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(LookupError):
        exporter.export_playbook(store, "营销", "没有")


def test_export_playbook_provenance(tmp_path):
    """方案 A：md 导出带溯源节（首次沉淀/最近更新/沉淀依据/置信度）。"""
    store = _store(tmp_path)
    _exp(store, task="双十一主标题", G=0.9)
    _exp(store, task="社媒短文案", G=0.3, state="纯情绪文案转化低")
    store.write_skill("营销", "文案写作",
                      "# 营销 / 文案写作 · playbook\n\n"
                      "> name: 投放标题方法\n"
                      "> created: 2026-06-11\n"
                      "> version: 3\n"
                      "> updated: 2026-08-21T09:00:00Z\n"
                      "> source_exps: e1, e2\n"
                      "> confidence: high\n\n"
                      "## 成功要点\n- 利益点前置\n")
    md = exporter.export_playbook(store, "营销", "文案写作")["md"]
    assert "## 溯源" in md
    assert "- 首次沉淀：2026-06-11" in md
    assert "- 最近更新：2026-08-21（v3）" in md
    assert "- 沉淀依据 2 条经验（成功 1 / 踩坑 1），可在经验库按类别回看" in md
    assert "- 置信度：已验证" in md
    # 溯源垫底（方法正文之后）
    assert md.index("## 成功要点") < md.index("## 溯源")


def test_export_playbook_provenance_empty_when_no_data(tmp_path):
    """老 playbook（无 created/confidence 头）+ 无经验 → 不附溯源节（不为空壳撑场面）。"""
    store = _store(tmp_path)
    store.write_skill("营销", "文案写作", "# playbook\n\n## 成功要点\n- x")
    md = exporter.export_playbook(store, "营销", "文案写作")["md"]
    assert "## 溯源" not in md
    assert "## 成功要点" in md


def test_export_preferences(tmp_path):
    store = _store(tmp_path)
    store.write_preferences("营销", "# 营销 · 偏好画像\n\n- 结论先行")
    r = exporter.export_preferences(store, "营销")
    assert "偏好画像导出：营销" in r["md"] and "结论先行" in r["md"]
    with pytest.raises(LookupError):
        exporter.export_preferences(store, "没有")


# ---------- 粒度 4：阶段任务经验 ----------

def test_export_phase_date_window(tmp_path):
    store = _store(tmp_path)
    _exp(store, ts=TODAY, task="本月内")
    _exp(store, ts=TODAY - timedelta(days=45), task="上月")
    r = exporter.export_phase(store)  # 默认本月
    assert "本月内" in r["md"]
    assert "上月" not in r["md"]
    r2 = exporter.export_phase(store, since=(TODAY - timedelta(days=60)).isoformat())
    assert "上月" in r2["md"]


def test_export_phase_overview(tmp_path):
    """阶段报告模板：概览（总量/时间范围/类别分布）垫在经验条前面。"""
    store = _store(tmp_path)
    _exp(store, ts=TODAY, task="标题 A", G=0.9)
    _exp(store, ts=TODAY - timedelta(days=2), task="标题 B", G=0.4, state="点击率低")
    _exp(store, ts=TODAY - timedelta(days=3), trunk="营销", category="投放",
         task="渠道 C")
    # 显式窗口（默认"本月"在月初会吞掉几天前的种子数据）
    md = exporter.export_phase(store, since=(TODAY - timedelta(days=10)).isoformat(),
                               until=TODAY.isoformat())["md"]
    assert "## 阶段概览" in md
    assert "- 经验总量：3 条（成功 2 / 避坑 1）" in md
    assert "- 类别分布：" in md
    assert "营销 / 文案写作：2 条（成功 1 / 避坑 1）" in md
    assert "营销 / 投放：1 条（成功 1 / 避坑 0）" in md
    # 概览在前，明细在后
    assert md.index("## 阶段概览") < md.index("## 成功经验")


# ---------- 粒度 5：成长报告 ----------

def _session(store, trunk, category, req, corr, started):
    store.record_session({"trunk": trunk, "category": category,
                          "req_count": req, "correction_hits": corr,
                          "started_at": started, "agent": "Codex",
                          "model": "local", "session_id": f"s-{started}"})


def test_export_growth_with_affinity(tmp_path):
    store = _store(tmp_path)
    _exp(store, G=0.9, ts=UTC_TODAY)
    d = (UTC_TODAY - timedelta(days=1)).isoformat()
    # 5 个独立实例（M1 不重叠窗口）：基线=前 3 次中位 5，近期（第 4~5 个）中位 4 → 差值 +1（中）
    _session(store, "营销", "文案写作", 10, 6, d + "T08:00:00Z")
    _session(store, "营销", "文案写作", 9, 5, d + "T08:30:00Z")
    _session(store, "营销", "文案写作", 8, 4, d + "T09:00:00Z")
    _session(store, "营销", "文案写作", 8, 4, d + "T09:30:00Z")
    _session(store, "营销", "文案写作", 9, 4, d + "T10:00:00Z")
    r = exporter.export_growth(store, days=30)
    md = r["md"]
    # 主体换成 growth_story 口径（结论/飞轮/资产/助手/每周…），旧判据降为附录
    assert "成长报告（" in md
    assert "## 结论" in md and "## 经验飞轮" in md and "## 攒下的东西" in md
    assert "## 附：磨合度（基线前 3 次中位数 − 基线后 5 次中位数）" in md
    # 类别判据仍是加项：有改善就出现在结论里，没改善也不空掉整份报告
    assert "少 1 轮修正" in md.split("## 附：")[0]
    assert "变好的类别平均比最初几次少走 1 轮修正（仅统计变好的类别）" in md
    # 主角：基线 vs 近期窗口中位数（v2 口径）
    # 导出标题含 agent（_session 用 agent=Codex）
    assert "### Codex / 营销 / 文案写作 · 磨合差值 +1" in md
    assert "- 修正轮数：基线中位 5 → 近期中位 4（差值 +1）" in md
    assert "- 协作轮数：9 → 8（差值 +1）" in md
    assert "- 磨合度：中（样本 5 次）" in md
    assert "- 样本 5 次，结论仅供参考" in md  # 3 ≤ n < 8 置信度标注
    # 无 token 数据（老记录）→ token 行省略
    assert "token：" not in md
    # 佐证：经验累积（数值行，无字符画——人读不懂终端块）+ 近 14 天（数值表）
    assert "## 经验累积" in md
    assert not any(ch in md for ch in "▁▂▃▄▅▆▇█"), "md 不应再含 ASCII 块状图"
    assert "- 营销/文案写作：1 条 / 30 天" in md
    # 时间佐证换成"每周"表（吃会话口径；旧的"近 14 天 G 加权和"回灌后全是同一天）
    assert "## 每周" in md
    assert "| 周 | 任务 | 返工回/次 |" in md
    # 结论在前、旧判据退居附录（顺序即口径优先级）
    assert md.index("## 结论") < md.index("## 附：磨合度") < md.index("## 经验累积")


def test_export_growth_empty(tmp_path):
    store = _store(tmp_path)
    r = exporter.export_growth(store)
    md = r["md"]
    # 空库也要说人话：主句给"样本还在攒"，附录仍标磨合度待积累
    assert "还在攒样本" in md
    assert "待积累" in md
    assert "'tpl'" not in md  # 模板不得泄漏成字典字面量


# ---------- 落盘与全量打包 ----------

def test_save_export_dedup_names(tmp_path):
    store = _store(tmp_path)
    p1 = exporter.save_export(store, "a.md", "1")
    p2 = exporter.save_export(store, "a.md", "2")
    assert p1.name == "a.md" and p2.name == "a-1.md"
    assert p2.parent == store.data_dir / exporter.EXPORTS_DIRNAME


def test_export_all_copies_md_assets_readonly(tmp_path):
    store = _store(tmp_path)
    store.write_skill("营销", "文案写作", "# pb")
    store.write_preferences("营销", "# prefs")
    (store.data_dir / "rules" / "x.md").parent.mkdir(parents=True, exist_ok=True)
    (store.data_dir / "rules" / "x.md").write_text("rule", encoding="utf-8")
    store.append_changelog("节点 1")
    r = exporter.export_all(store)
    dest = Path(r["dest"])
    assert dest.is_dir()
    assert (dest / "skills" / "营销" / "文案写作.md").read_text(encoding="utf-8") == "# pb"
    assert (dest / "preferences" / "营销.md").exists()
    assert (dest / "rules" / "x.md").exists()
    assert (dest / "changelog.md").exists()
    manifest = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
    assert any("skills" in f for f in manifest["files"])
    # 源目录只读：原资产还在
    assert (store.data_dir / "skills" / "营销" / "文案写作.md").exists()


# ---------- Skill 版本化 ----------

def test_skill_versions_save_list_read_diff(tmp_path):
    store = _store(tmp_path)
    v1 = skillgen.save_skill_version(store, "copywriting",
                                     "# s\n\n## Procedure\n- a\n- b\n",
                                     "第一版", 5, created_at="2026-08-20T00:00:00Z")
    v2 = skillgen.save_skill_version(store, "copywriting",
                                     "# s\n\n## Procedure\n- a\n- c\n",
                                     "第二版", 9, created_at="2026-08-25T00:00:00Z")
    assert v1["version"] == 1 and v2["version"] == 2
    vers = skillgen.list_skill_versions(store, "copywriting")
    assert [v["n"] for v in vers] == [2, 1]  # 新在前
    assert skillgen.read_skill_version(store, "copywriting", 1).endswith("- b\n")
    diff = skillgen.diff_versions(store, "copywriting", 1, 2)
    assert "- b" in diff and "+ - c" in diff or "- c" in diff
    assert skillgen.read_skill_version(store, "copywriting", 99) is None


def test_generate_skill_version_param(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _exp(store)
    monkeypatch.setattr(llm, "call_model", lambda s, m: "## When to Use（何时使用）\n- x")
    r = skillgen.generate_skill(store, trunk="营销", category="文案写作",
                                version="2.0.0")
    # R1 后 version 进 metadata（agentskills.io 规范无顶层 version 字段）
    assert 'version: "2.0.0"' in r["md"]


def test_generate_skill_model_name_and_ascii_alias(tmp_path, monkeypatch):
    """R1：模型起说人话短名进标题/metadata，frontmatter name 保持 ASCII 合规。"""
    store = _store(tmp_path)
    # 模型命名需要配置（switcher：没配走确定性降级，不产模型名/alias）
    store.save_config({"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                            "type": "local", "model": "qwen"}},
                       "default_model": "local"})
    _exp(store)
    monkeypatch.setattr(llm, "call_model", lambda s, m:
                        "name: 投标报价核算\nalias: bid-quote-check\n\n"
                        "## When to Use（何时使用）\n- 投标时")
    r = skillgen.generate_skill(store, trunk="营销", category="文案写作")
    assert r["name"] == "投标报价核算" and r["alias"] == "bid-quote-check"
    assert "name: bid-quote-check" in r["md"]          # frontmatter = ASCII
    assert "display_name: 投标报价核算" in r["md"]      # 展示名进 metadata
    assert "# 投标报价核算" in r["md"]
    assert "alias: bid-quote-check" not in r["md"].split("---", 2)[2]  # 正文剥净


def test_generate_skill_name_fallback_when_model_noncompliant(tmp_path, monkeypatch):
    """模型没按格式输出 name/alias 时：回退项目-类别名 + ASCII 兜底，不崩。"""
    store = _store(tmp_path)
    _exp(store)
    monkeypatch.setattr(llm, "call_model", lambda s, m: "## Procedure（成功做法）\n1. x")
    r = skillgen.generate_skill(store, trunk="营销", category="文案写作")
    assert r["name"] == "营销-文案写作"
    import re as _re
    m = _re.search(r"^name: (\S+)$", r["md"], _re.M)
    assert _re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", m.group(1))


# ---------- 本地 API 端点 ----------

def _client(tmp_path) -> TestClient:
    store = _store(tmp_path)
    return local_api_client(store), store


def test_api_export_experiences_writes_file(tmp_path):
    client, store = _client(tmp_path)
    _exp(store)
    r = client.post("/api/export", json={"granularity": "experiences",
                                         "trunk": "营销", "category": "文案写作"})
    assert r.status_code == 200
    body = r.json()
    assert (store.data_dir / "exports" / body["filename"]).exists()
    assert "经验导出：营销 / 文案写作" in body["md"]


def test_api_export_playbook_missing_404(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/api/export", json={"granularity": "playbook",
                                         "trunk": "营销", "category": "没有"})
    assert r.status_code == 404


def test_api_export_bad_granularity_400(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/api/export", json={"granularity": "bogus"})
    assert r.status_code == 400


def test_api_export_phase_defaults_to_this_month(tmp_path):
    client, store = _client(tmp_path)
    _exp(store, ts=TODAY, task="本月任务")
    r = client.post("/api/export", json={"granularity": "phase"})
    assert r.status_code == 200
    assert "本月任务" in r.json()["md"]


def test_api_export_all(tmp_path):
    client, store = _client(tmp_path)
    store.write_skill("营销", "文案写作", "# pb")
    r = client.post("/api/export/all")
    assert r.status_code == 200
    body = r.json()
    assert Path(body["dest"]).is_dir()
    assert body["files"]


def test_api_exports_open_rejects_arbitrary_path(tmp_path):
    client, store = _client(tmp_path)
    r = client.post("/api/exports/open", json={"path": str(store.data_dir.parent)})
    assert r.status_code == 400


def test_api_skill_save_and_versions(tmp_path):
    client, store = _client(tmp_path)
    r1 = client.post("/api/skills/save", json={
        "name": "copywriting", "md": "# s\n- a\n", "description": "d1"})
    assert r1.status_code == 200 and r1.json()["version"] == 1
    client.post("/api/skills/save", json={
        "name": "copywriting", "md": "# s\n- b\n", "description": "d2"})
    r = client.get("/api/skills/versions/copywriting")
    assert [v["n"] for v in r.json()["versions"]] == [2, 1]
    r = client.get("/api/skills/versions/copywriting/1")
    assert "- a" in r.json()["md"]
    r = client.get("/api/skills/versions/copywriting/diff/1/2")
    assert r.json()["diff"] and "a" in r.json()["diff"] and "b" in r.json()["diff"]
    r = client.get("/api/skills/versions/copywriting/99")
    assert r.status_code == 404


def test_api_versions_route_not_swallowed_by_trunk_category(tmp_path):
    """/api/skills/versions/x 必须命中 versions 路由而不是 {trunk}/{category}。"""
    client, store = _client(tmp_path)
    r = client.get("/api/skills/versions/nonexistent-skill")
    assert r.status_code == 200
    assert r.json()["versions"] == []


# ---------- M2 空卡守卫：空 Skill 拒写、不产空版本、不覆盖已有资产 ----------

def test_save_skill_version_rejects_empty_body(tmp_path):
    store = _store(tmp_path)
    for blank in ("", "   \n\t  ", "---\nname: x\n---\n   \n"):
        with pytest.raises(ValueError):
            skillgen.save_skill_version(store, "empty-skill", blank, "d", 3)
    # 拒写后不留任何版本文件、不建索引
    assert skillgen.list_skill_versions(store, "empty-skill") == []


def test_save_skill_version_atomic_and_no_meta_desync(tmp_path):
    store = _store(tmp_path)
    v1 = skillgen.save_skill_version(store, "atomic", "# s\n- a\n", "d1", 1)
    assert v1["version"] == 1
    # 有效正文正常写入，v{n}.md 与 meta 一致
    assert skillgen.read_skill_version(store, "atomic", 1) == "# s\n- a\n"
    assert [v["n"] for v in skillgen.list_skill_versions(store, "atomic")] == [1]


def test_api_skill_save_empty_returns_400(tmp_path):
    client, store = _client(tmp_path)
    r = client.post("/api/skills/save",
                    json={"name": "copywriting", "md": "   ", "description": "d"})
    assert r.status_code == 400
    assert client.get("/api/skills/versions/copywriting").json()["versions"] == []


# ---------- 粒度 6：导出 Hooks（M1 信息架构重构） ----------

def test_export_hooks_frontmatter_and_do_dont(tmp_path):
    store = _store(tmp_path)
    # 自定义 hook：无 dos/donts，priority 按 trigger 降级推断（always→p1）
    store.upsert_rule({"id": "r1", "name": "公文格式", "text": "发文字号用六角括号",
                       "trigger": "always", "enabled": True})
    # 模板导入的 hook：从模板库补 dos/donts（c5-p0-bidding 有 donts 五条）
    from app.rules import registry as templates
    templates.import_template(store, "zh", "c5-p0-bidding")
    r = exporter.export_hooks(store)
    md = r["md"]
    assert "Hooks 导出" in md
    assert "Hook 条数：2 条" in md
    # 自定义 hook：source=user、priority 推断、dos/donts 空键
    assert "id: hook-r1" in md
    assert "name: 公文格式" in md
    assert "priority: p1" in md
    assert "trigger: always" in md
    assert "source: user" in md
    # 模板 hook：P0 的 donts 由模板保证必填
    assert "id: hook-tpl-c5-p0-bidding" in md
    assert "priority: p0" in md
    assert "trigger: hard-hook" in md
    assert "donts: |" in md
    assert "NEVER 报价超过最高限价" in md
    assert r["filename"].startswith("Hooks导出-")


def test_export_hooks_priority_inference(tmp_path):
    store = _store(tmp_path)
    for rid, trig in (("a", "hard-hook"), ("b", "smart"), ("c", "manual")):
        store.upsert_rule({"id": rid, "name": f"n{rid}", "text": "t",
                           "trigger": trig,
                           "template_priority": "p0" if trig == "hard-hook" else ""})
    md = exporter.export_hooks(store)["md"]
    # hard-hook→p0 / smart→p2 / manual→p4
    assert "id: hook-a" in md and "priority: p0" in md
    assert "priority: p2" in md and "priority: p4" in md


def test_export_hooks_empty(tmp_path):
    store = _store(tmp_path)
    r = exporter.export_hooks(store)
    assert "Hook 条数：0 条" in r["md"]
    assert "（还没有 Hook）" in r["md"]


def test_api_export_hooks_writes_file(tmp_path):
    client, store = _client(tmp_path)
    store.upsert_rule({"id": "r1", "name": "公文格式", "text": "六角括号",
                       "trigger": "always"})
    r = client.post("/api/export", json={"granularity": "hooks"})
    assert r.status_code == 200
    body = r.json()
    assert (store.data_dir / "exports" / body["filename"]).exists()
    assert "id: hook-r1" in body["md"]


# ---------- E-05：SKILL.md frontmatter 补 dos/donts ----------

def test_with_skill_dodonts_induces_from_body():
    md = ("---\nname: copywriting\ndescription: d\nversion: 1.0.0\n---\n\n"
          "# copywriting Skill\n\n"
          "## When to Use（何时使用）\n- 写标题\n\n"
          "## Procedure（成功做法，来自 2 条验证经验）\n"
          "1. 利益点前置\n2. A/B 两版\n\n"
          "## Pitfalls（失败模式，来自 1 条踩坑经验）\n"
          "- 纯情绪文案不转化\n\n"
          "## Verification（怎么确认做对了）\n- 点击率\n")
    out = exporter.with_skill_dodonts(md)
    head = out.split("---")[1]
    assert "dos: |" in head and "  - 利益点前置" in head
    assert "  - A/B 两版" in head
    assert "donts: |" in head and "  - 纯情绪文案不转化" in head
    # 正文不动
    assert "## When to Use（何时使用）" in out
    # 幂等：已有 dos/donts 不覆盖
    assert exporter.with_skill_dodonts(out) == out


def test_with_skill_dodonts_no_sections_empty_keys():
    md = "---\nname: x\n---\n\n# x\n\n正文\n"
    out = exporter.with_skill_dodonts(md)
    head = out.split("---")[1]
    assert "dos:" in head and "donts:" in head
    assert "  - " not in head


def test_api_skill_generate_adds_do_donts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        llm, "call_model",
        lambda s, m: "## Procedure（成功做法）\n1. 步骤一\n"
                     "## Pitfalls（失败模式）\n- 别这么做\n")
    client, store = _client(tmp_path)
    # 模型正文需要配置（switcher：没配走确定性降级，无 Procedure/Pitfalls 节）
    store.save_config({"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                            "type": "local", "model": "qwen"}},
                       "default_model": "local"})
    _exp(store)
    r = client.post("/api/skills/generate",
                    json={"trunk": "营销", "category": "文案写作"})
    assert r.status_code == 200
    md = r.json()["md"]
    assert "dos: |" in md and "  - 步骤一" in md
    assert "donts: |" in md and "  - 别这么做" in md


# ---------- R5：导出三件套精选（ids / 多方法 / hooks 勾选） ----------

def test_export_experiences_ids_selection(tmp_path):
    """经验记录勾选：ids 非空只出勾选条目（跨类别允许），标题带精选条数。"""
    store = _store(tmp_path)
    e1 = _exp(store, task="双十一主标题", G=0.9)
    _exp(store, task="社媒短文案", G=0.3, state="纯情绪文案转化低")
    r = exporter.export_experiences(store, ids=[e1["id"]])
    md = r["md"]
    assert "经验导出：精选 1 条" in md
    assert "双十一主标题" in md
    assert "社媒短文案" not in md
    # 缺省仍走全量口径
    r_all = exporter.export_experiences(store)
    assert "双十一主标题" in r_all["md"] and "社媒短文案" in r_all["md"]


def test_export_playbooks_multi_section(tmp_path):
    """方法多选：每方法一节，标题 = 显示名 + 两级路径；不存在的跳过。"""
    store = _store(tmp_path)
    store.write_skill("营销", "文案写作",
                      "> name: 投标报价核算\n> version: 1.0.0\n\n# 营销 / 文案写作 · v1\n\n## 成功要点\n- x")
    store.write_skill("工程", "部署", "# 工程 / 部署 · v1\n\n## 成功要点\n- y")
    r = exporter.export_playbooks(store, [("营销", "文案写作"), ("工程", "部署")])
    md = r["md"]
    assert "# 方法导出" in md and "方法条数：2 个" in md
    assert "## 投标报价核算（营销 / 文案写作）" in md
    assert "## 工程 / 部署" in md
    assert r["filename"].startswith("方法-精选-")
    # 不存在的方法跳过；全不存在 → LookupError
    r2 = exporter.export_playbooks(store, [("工程", "部署"), ("没有", "项目")])
    assert "方法条数：1 个" in r2["md"]
    with pytest.raises(LookupError):
        exporter.export_playbooks(store, [("没有", "项目")])


def test_export_hooks_ids_agents_frontmatter(tmp_path):
    """Hooks 勾选：ids 过滤；frontmatter 带 agents（["*"] = all / 列表 / 空 = none）。"""
    store = _store(tmp_path)
    r1 = store.upsert_rule({"id": "h1", "name": "发文字号规范",
                            "text": "六角括号", "trigger": "always",
                            "agents": ["claude-code"]})
    r2 = store.upsert_rule({"id": "h2", "name": "投标红线", "text": "五条NEVER",
                            "trigger": "hard-hook", "template_priority": "p0"})  # agents 缺省 → ["*"]
    store.upsert_rule({"id": "h3", "name": "停用规则", "text": "旧规则",
                       "trigger": "manual", "agents": []})  # 停用规则，不应进导出
    r = exporter.export_hooks(store, ids=[r1["id"], r2["id"]])
    md = r["md"]
    assert "Hook 条数：2 条（精选 2 条）" in md
    # 第 6 轮：hook 降为 ### 节（类目 = ## 节）；两条均自定义 → 同组
    assert "## 自定义" in md
    assert "### 发文字号规范" in md and "### 投标红线" in md
    assert "### 停用规则" not in md
    assert "agents: claude-code" in md      # 指定工具
    assert "agents: all" in md              # 缺省 = 全部工具
    assert "priority: p0" in md             # hard-hook 推断 P0
    # 缺省全量：3 条，停用规则 agents = none
    r_all = exporter.export_hooks(store)
    assert "Hook 条数：3 条" in r_all["md"] and "agents: none" in r_all["md"]


def test_export_hooks_category_grouping(tmp_path):
    """第 6 轮：导出 md 按模板类目分组（CATEGORIES 顺序），自定义组垫底。"""
    store = _store(tmp_path)
    from app.rules import registry as templates
    templates.import_template(store, "zh", "c5-p0-bidding")   # c5 安全与合规
    templates.import_template(store, "zh", "c1-p1-backend")   # c1 架构与设计
    store.upsert_rule({"id": "r1", "name": "自定义规则", "text": "t",
                       "trigger": "always"})
    md = exporter.export_hooks(store)["md"]
    assert "## 架构与设计" in md and "## 安全与合规" in md and "## 自定义" in md
    # 类目顺序 = CATEGORIES：c1 在 c5 前，c5 在自定义前
    assert md.index("## 架构与设计") < md.index("## 安全与合规") < md.index("## 自定义")
    # hook 在类目节内（### 级），frontmatter 跟随 hook
    assert md.index("## 安全与合规") < md.index("id: hook-tpl-c5-p0-bidding")
    assert md.index("## 自定义") < md.index("id: hook-r1")
    # 精选只留 c5 类目 → 只剩该组
    r = exporter.export_hooks(store, ids=["tpl-c5-p0-bidding"])
    assert "## 安全与合规" in r["md"]
    assert "## 架构与设计" not in r["md"] and "## 自定义" not in r["md"]


def test_api_export_selection_payloads(tmp_path):
    """API 层：experiences 带 ids / playbook 带 playbooks / hooks 带 ids 都走精选。"""
    client, store = _client(tmp_path)
    e = _exp(store, task="双十一主标题")
    store.write_skill("营销", "文案写作",
                      "> name: 投标报价核算\n\n# 营销 / 文案写作 · v1\n\n## 成功要点\n- x")
    store.upsert_rule({"id": "h1", "name": "发文字号规范", "text": "t",
                       "trigger": "always"})

    r = client.post("/api/export", json={"granularity": "experiences",
                                         "ids": [e["id"]]})
    assert r.status_code == 200 and "精选 1 条" in r.json()["md"]

    r = client.post("/api/export", json={"granularity": "playbook",
                                         "playbooks": [{"trunk": "营销",
                                                        "category": "文案写作"}]})
    assert r.status_code == 200 and "## 投标报价核算（营销 / 文案写作）" in r.json()["md"]
    r = client.post("/api/export", json={"granularity": "playbook",
                                         "playbooks": []})
    assert r.status_code == 400

    r = client.post("/api/export", json={"granularity": "hooks", "ids": ["h1"]})
    assert r.status_code == 200 and "精选 1 条" in r.json()["md"]
