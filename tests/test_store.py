"""store 数据层测试。"""

import json

import pytest

from app.store.store import Store


def _rec(**kw):
    base = {"agent": "codex", "task": "写标题", "action": "利益点前置", "G": 0.7,
            "trunk": "营销", "category": "文案写作"}
    base.update(kw)
    return base


def test_append_and_dedup_count(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.append_experience(_rec())
    r2 = store.append_experience(_rec(G=0.9))
    assert r2["count"] == 2
    assert r2["G"] == 0.9
    lines = [l for l in (tmp_path / "experience.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    # JSONL 降级为**追加式备份**（合并/更新只落 SQLite，不再重写 JSONL）——
    # 合并只追加过首条，故备份仍 1 行；事实源（读视图）里才是 count=2。
    assert len(lines) == 1  # 同 task+action 合并计数，不重复追加
    view = list(store.iter_experiences())
    assert len(view) == 1 and view[0]["count"] == 2


def test_skill_and_preferences_roundtrip(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作", "# playbook\n- 步骤一")
    assert "步骤一" in store.read_skill("营销", "文案写作")
    assert store.read_skill("营销", "不存在") is None
    store.write_preferences("营销", "- 结论先行")
    assert "结论先行" in store.read_preferences("营销")


def test_distilled_mark(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    rec = store.append_experience(_rec())
    store.mark_experiences_distilled([rec["id"]])
    assert list(store.iter_experiences(trunk="营销", category="文案写作")) == []
    assert len(list(store.iter_experiences(include_distilled=True))) == 1


def test_retire_to_deprecated(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    path = store.write_skill("营销", "文案写作", "old")
    dest = store.retire_asset(path)
    assert not path.exists()
    assert dest.exists() and "deprecated" in str(dest)


# ---------- R1 智能命名 / R2 改名与分类迁移 ----------

def _pb(name=None, source=None):
    lines = ["# 营销 / 文案写作 · playbook", ""]
    if name:
        lines += [f"> name: {name}", f"> name_source: {source or 'auto'}"]
    lines += ["> version: 1", "> updated: 2026-01-01T00:00:00Z",
              "> source_exps: （无）", "> confidence: low", "",
              "## 标准流程\n- 步骤一\n"]
    return "\n".join(lines)


def test_list_skills_returns_name(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作", _pb(name="投标报价核算", source="auto"))
    store.write_skill("营销", "海报设计", _pb().replace("文案写作", "海报设计"))
    items = {i["category"]: i for i in store.list_skills()}
    assert items["文案写作"]["name"] == "投标报价核算"
    assert items["海报设计"]["name"] is None  # 未命名 → 展示层回退两级路径


def test_rename_display_name_only(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作", _pb())
    store.append_experience(_rec())
    r = store.rename_skill("营销", "文案写作", name="周报数据核对", new_category=None)
    md = store.read_skill("营销", "文案写作")
    assert "> name: 周报数据核对" in md and "> name_source: manual" in md
    assert r["category"] == "文案写作"
    # 手改名 → 蒸馏保留（engine_curation 侧行为见 test_w3 增补）
    assert store.list_skills()[0]["name"] == "周报数据核对"


def test_rename_category_migration_moves_everything(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作", _pb(name="旧名"))
    store.write_fixes("营销", "文案写作", "# 营销 / 文案写作 · 纠正补丁\n\n- 补丁")
    store.append_experience(_rec())
    store.record_session({"trunk": "营销", "category": "文案写作", "req_count": 3,
                          "agent": "Codex", "session_id": "s1",
                          "started_at": "2026-01-01T00:00:00Z"})
    r = store.rename_skill("营销", "文案写作", None, "报价文案")
    assert r["category"] == "报价文案"
    # 文件移动 + 标题行重写
    assert store.read_skill("营销", "文案写作") is None
    md = store.read_skill("营销", "报价文案")
    assert md.startswith("# 营销 / 报价文案 · playbook")
    fixes = store.read_fixes("营销", "报价文案")
    assert fixes.startswith("# 营销 / 报价文案 · 纠正补丁")
    # 经验 / session 跟随（成长等读时计算自动更新）
    assert [e["category"] for e in store.iter_experiences(include_distilled=True)] == ["报价文案"]
    assert [s["category"] for s in store.list_sessions()] == ["报价文案"]
    # 旧 sqlite 索引也更新
    assert store.find_experience(list(store.iter_experiences(include_distilled=True))[0]["id"])["category"] == "报价文案"


def test_rename_category_collision_409(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作", _pb())
    store.write_skill("营销", "报价文案", _pb())
    with pytest.raises(ValueError, match="已存在"):
        store.rename_skill("营销", "文案写作", None, "报价文案")


def test_rename_noop_rejected(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作", _pb(name="同名"))
    with pytest.raises(ValueError):
        store.rename_skill("营销", "文案写作", name="同名", new_category=None)


def test_rename_counts_stale_overrides(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作", _pb() + "## 成功要点\n- 结论先行\n")
    store.append_experience(_rec())
    from app.proxy.inject import iter_injection_items
    items = iter_injection_items(store, "营销", "文案写作")
    assert items, "playbook 应有可注入条目"
    store.upsert_override(items[0]["id"], enabled=False)
    r = store.rename_skill("营销", "文案写作", None, "报价文案")
    assert r["stale_overrides"] >= 1


# ---------- H-O2：规则命中记录生命周期 ----------

def test_rule_hits_lifecycle(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    r = store.upsert_rule({"id": "h1", "name": "n", "text": "t"})
    assert r.get("created_at"), "新规则应有 created_at（过时判定用）"
    # 更新不应丢掉 created_at
    r2 = store.upsert_rule({"id": "h1", "name": "n2", "text": "t2"})
    assert r2["created_at"] == r["created_at"]
    store.record_rule_hits(["h1"])
    store.record_rule_hits(["h1", "h1"])  # 单次调用去重
    h = store.load_rule_hits()
    assert h["h1"]["count"] == 2 and h["h1"]["last"]
    # 删除规则 → 命中记录连带清理
    assert store.remove_rule("h1")
    assert store.load_rule_hits() == {}
    # 坏文件容错
    (store.data_dir / "rule_hits.json").write_text("{坏 json", encoding="utf-8")
    assert store.load_rule_hits() == {}


# ---------- M-8：wipe 后校验 + 不可删上报 ----------

def test_wipe_all_clean_returns_empty(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作", "v1")
    assert store.wipe_all() == []
    assert (tmp_path / "experience.jsonl").exists()  # 初始布局重建


def test_wipe_all_reports_undeletable(tmp_path, monkeypatch):
    """删不掉的文件（被进程占用）必须上报，不靠"没抛异常"当成功。"""
    from pathlib import Path

    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作", "v1")
    stubborn = tmp_path / "occupied.jsonl"
    stubborn.write_text("x")
    real_unlink = Path.unlink

    def fake_unlink(self, missing_ok=False):
        if self.name == "occupied.jsonl":
            raise OSError("in use")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    leftovers = store.wipe_all()
    assert leftovers == ["occupied.jsonl"]  # 只报占用文件，初始布局不算残留
    assert not (tmp_path / "skills").exists() or not any(
        (tmp_path / "skills").rglob("*.md"))  # 资产已删
    assert (tmp_path / "experience.jsonl").exists()


# ---------- M2：load_rules 唯一实现（模板规则读 md 权威来源，不读旧快照） ----------

def test_load_rules_prefers_fresh_md_over_snapshot(tmp_path):
    """M2：模板规则的 text 以 md 文件为准（用户改完即生效），rules.json 里的
    text 只是导入时快照。此前 API/export 走 store.load_rules 拿到旧快照，
    与注入路径（inject.load_rules）口径分叉——现已统一。"""
    store = Store(tmp_path)
    store.ensure_layout()
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "tpl-x.md").write_text("# 标题\n最新 md 内容", encoding="utf-8")
    store.save_rules([
        # 模板规则：快照 text（旧）+ file（权威 md，新）→ 应取 md
        {"id": "tpl-x", "name": "模板钩子", "text": "旧快照内容",
         "file": "rules/tpl-x.md", "enabled": True},
        # 内联规则：无 file → 保留内联 text，不碰盘
        {"id": "inline-1", "name": "内联钩子", "text": "内联文本",
         "enabled": True},
    ])
    rules = {r["id"]: r for r in store.load_rules()}
    assert rules["tpl-x"]["text"] == "# 标题\n最新 md 内容"  # 取 md，非旧快照
    assert rules["inline-1"]["text"] == "内联文本"           # 内联不受影响
    # H-A0 归一化：缺 agents → ["*"]
    assert rules["tpl-x"]["agents"] == ["*"]
    assert rules["inline-1"]["agents"] == ["*"]


def test_load_rules_missing_md_falls_back_to_snapshot(tmp_path):
    """M2：md 文件被删/读不到 → 回退 rules.json 里的快照 text（不报错）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_rules([
        {"id": "tpl-y", "name": "模板钩子", "text": "快照兜底",
         "file": "rules/不存在.md", "enabled": True},
    ])
    rules = {r["id"]: r for r in store.load_rules()}
    assert rules["tpl-y"]["text"] == "快照兜底"


# ---------- 低5：保留策略（消息截断 + 90 天） ----------

def test_record_session_trims_messages(tmp_path):
    """落库保留：每角色只留最近 20 条、每条截 200 字（复盘用内存全文不受影响）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    user_msgs = [f"u{i}-" + "x" * 400 for i in range(50)]
    store.record_session({
        "agent": "claude-code", "session_id": "s1",
        "started_at": "2026-09-01T00:00:00Z",
        "user_messages": user_msgs,
        "assistant_messages": ["a" * 400],
    })
    rec = store.list_sessions()[0]
    assert len(rec["user_messages"]) == 20
    assert rec["user_messages"][0] == user_msgs[30][:200]
    assert all(len(m) <= 200 for m in rec["user_messages"])
    assert rec["assistant_messages"] == ["a" * 200]


def test_prune_sessions_keeps_recent_and_unknown_ts(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session({"agent": "a", "session_id": "old",
                          "started_at": "2026-01-01T00:00:00Z"})
    store.record_session({"agent": "a", "session_id": "new",
                          "started_at": "2026-08-25T00:00:00Z"})
    store.record_session({"agent": "a", "session_id": "nots"})  # 无时间戳保留
    dropped = store.prune_sessions()
    ids = [s["session_id"] for s in store.list_sessions()]
    assert dropped == 1
    assert "old" not in ids and "new" in ids and "nots" in ids
    assert store.prune_sessions() == 0  # 幂等


def test_save_notifications_prunes_old(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_notifications([
        {"id": "n1", "ts": "2026-01-01T00:00:00Z", "type": "daily_summary"},
        {"id": "n2", "ts": "2026-08-25T00:00:00Z", "type": "daily_summary"},
        {"id": "n3", "type": "growth_report"},  # 无 ts 保留
    ])
    assert {r["id"] for r in store.load_notifications()} == {"n2", "n3"}


# ---------- M-5：类别派生索引 + config 缓存 ----------

def test_category_index_rebuilt_on_append(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.append_experience({"agent": "codex", "task": "写标题", "action": "前置利益点",
                             "G": 0.7, "trunk": "营销", "category": "文案"})
    store.append_experience({"agent": "codex", "task": "写文案", "action": "口语化",
                             "G": 0.6, "trunk": "营销", "category": "文案"})
    store.append_experience({"agent": "codex", "task": "部署", "action": "CI",
                             "G": 0.8, "trunk": "工程", "category": "发布"})
    assert store.load_category_index() == {
        "营销/文案": ["写标题", "写文案"], "工程/发布": ["部署"]}


def test_category_index_self_heals_when_missing(tmp_path):
    """老数据目录 / wipe 后索引缺失 → 读口现场重建并落盘。"""
    from app.proxy import detect

    store = Store(tmp_path)
    store.ensure_layout()
    store.append_experience({"agent": "codex", "task": "t1", "action": "a", "G": 0.5,
                             "trunk": "其他", "category": "未分类"})
    (tmp_path / "categories_index.json").unlink()
    known = detect.known_categories_from_store(store)
    assert known == {("其他", "未分类"): ["t1"]}
    assert (tmp_path / "categories_index.json").exists()  # 自愈重建已落盘


def test_update_experience_rebuilds_index_only_for_index_fields(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    rec = store.append_experience({"agent": "codex", "task": "t1", "action": "a",
                                   "G": 0.5, "trunk": "其他", "category": "旧类"})
    store.update_experience(rec["id"], {"G": 0.9})  # 不动索引字段
    store.update_experience(rec["id"], {"category": "新类"})
    assert list(store.load_category_index()) == ["其他/新类"]


def test_load_config_not_stale_after_save(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_config({"a": 1})
    assert store.load_config() == {"a": 1}
    store.save_config({"a": 2})  # os.replace 换 inode → 缓存不陈旧
    assert store.load_config() == {"a": 2}
    assert str(tmp_path / "config.json") in store._file_cache  # 走了缓存读口


def test_injection_hits_write_then_read_consistent_with_cache(tmp_path):
    """load_injection_hits 走 mtime 缓存后，写路径必须
    invalidate——连续写读不串台（同 tick 内 mtime/size 可能未变）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_injection("营销", "文案写作", "s1", tokens=10,
                           items=[{"id": "i1", "text": "利益点前置"}])
    assert store.load_injection_hits()["营销/文案写作"]["count"] == 1
    # 缓存已预热；再写再读必须立刻看到新值（写口失效缓存）
    store.record_injection("营销", "文案写作", "s2", tokens=10,
                           items=[{"id": "i1", "text": "利益点前置"}])
    assert store.load_injection_hits()["营销/文案写作"]["count"] == 2
    # 维护层回炉写口同样一致
    assert store.set_injection_item_state("营销", "文案写作", "i1", restricted=2)
    assert store.load_injection_hits()["营销/文案写作"]["items"]["i1"]["restricted"] == 2
    # 反馈回填写口一致
    store.append_experience({"agent": "codex", "task": "t", "trunk": "营销",
                             "category": "文案写作", "action": "利益点前置",
                             "G": 0.3, "corrected": True, "session_id": "s9"})
    assert store.load_injection_hits()["营销/文案写作"]["items"]["i1"]["refuted"] == 1


# ----------  L12/L13：stats 归档会话数 + 规则路径越界防护 ----------

def test_stats_archived_sessions_reflects_real_count(tmp_path):
    """L12：archived_sessions 不再是硬编码 0，如实反映去重后的 session 数。"""
    store = Store(tmp_path)
    store.ensure_layout()
    assert store.stats()["archived_sessions"] == 0
    store.record_session({"agent": "codex", "session_id": "s1"})
    store.record_session({"agent": "codex", "session_id": "s2"})
    # 同 (agent, session_id) 去重：不新增
    store.record_session({"agent": "codex", "session_id": "s1", "req_count": 3})
    assert store.stats()["archived_sessions"] == 2


def test_record_session_no_id_distinct_sessions_not_collapsed(tmp_path):
    """M6：无 session_id 的会话不得在 (agent, None) 键上坍缩成一条。

    真实坑（照 _sess_stamp 同型）：sessions.jsonl 追加式落库，同一 agent 下多条
    无 id 会话此前共享 (agent, None) 去重键 → list_sessions/stats 少算会话数。
    改用内容指纹身份后，不同会话各留一条；同一条重复上报仍命中同键去重不新增。"""
    store = Store(tmp_path)
    store.ensure_layout()
    # 同 agent、都无 session_id、同一时间戳：仅靠内容区分（req_count/消息不同）
    store.record_session({"agent": "codex", "started_at": "2026-09-01T10:00:00",
                          "req_count": 1, "user_messages": ["甲"]})
    store.record_session({"agent": "codex", "started_at": "2026-09-01T10:00:00",
                          "req_count": 2, "user_messages": ["乙"]})
    assert len(store.list_sessions()) == 2
    assert store.stats()["archived_sessions"] == 2
    # 同一条（内容指纹相同）重复上报：命中同键去重，不新增
    store.record_session({"agent": "codex", "started_at": "2026-09-01T10:00:00",
                          "req_count": 1, "user_messages": ["甲"]})
    assert len(store.list_sessions()) == 2



def test_load_rules_skips_path_outside_data_dir(tmp_path):
    """L13：`file` 指向 data_dir 之外的规则不得被读入正文——
    专项覆盖旧 `str.startswith` 的兄弟目录名前缀骗取（data_dir='/x/.exp'，
    兄弟='/x/.exp_evil' 时 startswith 误判为在内）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    evil = tmp_path.parent / (tmp_path.name + "_evil")
    evil.mkdir(exist_ok=True)
    (evil / "leak.md").write_text("TOP-SECRET-OUTSIDE", encoding="utf-8")
    rel = f"../{tmp_path.name}_evil/leak.md"
    store.save_rules([{"id": "r1", "file": rel, "text": ""}])
    rules = store.load_rules()
    assert rules and rules[0]["id"] == "r1"
    assert "TOP-SECRET-OUTSIDE" not in (rules[0].get("text") or "")
