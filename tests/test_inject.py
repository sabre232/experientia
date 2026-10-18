"""注入组装测试。"""

import json

from app.proxy import inject
from app.store.store import Store, normalize_rule

PLAYBOOK = """# 营销 / 文案写作 · playbook

> version: 1
> updated: 2026-08-28T00:00:00Z

## 标准流程
1. 确认投放目标与人群
2. 产出 ≥2 版标题（{利益点}前置）
3. A/B 投放，48h 后看点击率

## 成功要点
- 标题用利益点前置句式
- 每次至少 A/B 测试两版

## 失败模式
- [Solidified] 纯情绪文案不做利益承诺，点击率低（出现 3 次）
- [Watching] 标题超过 20 字会被平台截断（出现 2 次）
"""


def _store(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作", PLAYBOOK)
    store.write_preferences("营销", "- 结论先行，先给数字再给推理\n- 文案偏克制")
    return store


def test_block_order_and_solidified_only(tmp_path):
    store = _store(tmp_path)
    block = inject.assemble_experience_block(store, "营销", "文案写作")
    assert block.startswith(inject.INJECTION_MARKER)
    assert block.index("[你的偏好]") < block.index("[失败模式]") < block.index("[标准流程：文案写作]")
    assert "纯情绪文案不做利益承诺" in block  # 已固化 → 注入
    assert "标题超过 20 字" not in block      # 观察中 → 不注入


def test_budget_truncation(tmp_path):
    store = _store(tmp_path)
    # 极小预算：偏好能进，SOP 被截，成功要点（兜底层）直接不注入
    block = inject.assemble_experience_block(store, "营销", "文案写作", budget=25)
    assert "[你的偏好]" in block
    assert "经验要点" not in block


def test_legacy_chinese_marks_normalized(tmp_path):
    """R6 存量兼容：旧中文判定键（已固化/观察中/用户确认）读取时归一化为 ASCII 键。"""
    assert inject.normalize_marks("- [已固化] 坑（出现 3 次）") == \
        "- [Solidified] 坑（出现 3 次）"
    assert inject.normalize_marks("- [观察中] 坑（出现 1 次）") == \
        "- [Watching] 坑（出现 1 次）"
    assert inject.normalize_marks("- 结论先行（用户确认）") == \
        "- 结论先行[UserConfirmed]"
    # 已归一化文本不受影响
    assert inject.normalize_marks("- [Solidified] x") == "- [Solidified] x"
    # 旧格式 playbook 的失败模式仍能解析出三态（legacy 中文标记映射）
    legacy = {"失败模式": "- [已固化] 旧坑（出现 3 次）\n"
                          "- （待验证） 老坑（出现 3 次）\n"
                          "- [观察中] 新坑（出现 1 次）"}
    solid, pending, watching = inject.failure_mode_entries(legacy)
    assert solid == ["旧坑（出现 3 次）"]
    assert pending == ["老坑（出现 3 次）"]
    assert watching == ["新坑（出现 1 次）"]


def test_empty_assets_no_block(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    assert inject.assemble_experience_block(store, "x", "y") == ""


def test_apply_openai_prepend(tmp_path):
    body = {"messages": [{"role": "user", "content": "hi"}]}
    out = inject.apply_injection_openai(body, "BLOCK")
    assert out["messages"][0]["role"] == "system"
    assert out["messages"][0]["content"] == "BLOCK"


def test_apply_openai_merge_existing_system():
    body = {"messages": [{"role": "system", "content": "OLD"}, {"role": "user", "content": "hi"}]}
    out = inject.apply_injection_openai(body, "BLOCK")
    assert out["messages"][0]["role"] == "system"
    assert out["messages"][0]["content"].startswith("OLD")
    assert "BLOCK" in out["messages"][0]["content"]


def test_apply_anthropic_string_system():
    body = {"system": "OLD", "messages": [{"role": "user", "content": "hi"}]}
    out = inject.apply_injection_anthropic(body, "BLOCK")
    assert out["system"].startswith("OLD") and "BLOCK" in out["system"]


def test_apply_anthropic_no_system():
    out = inject.apply_injection_anthropic({"messages": []}, "BLOCK")
    assert out["system"] == "BLOCK"


def test_rules_hard_hook_always(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    rules = {"rules": [
        {"name": "投标红线", "text": "NEVER 报价超最高限价", "trigger": "hard-hook", "enabled": True},
        {"name": "投标触发", "text": "废标条款核对清单", "trigger": "keyword", "keyword": "投标", "enabled": True},
    ]}
    (store.data_dir / "rules.json").write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
    # 无关键词命中：只有硬钩子
    block = inject.assemble_rules_block(store, "帮我写周报")
    assert "NEVER 报价超最高限价" in block
    assert "废标条款核对清单" not in block
    # 关键词命中：两条都在
    block2 = inject.assemble_rules_block(store, "帮我写投标文件")
    assert "废标条款核对清单" in block2


def test_rules_disabled_excluded(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    rules = {"rules": [{"name": "x", "text": "T", "trigger": "always", "enabled": False}]}
    (store.data_dir / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    assert inject.assemble_rules_block(store, "任何内容") == ""


# ---------- H-A0 多 agent 配装 / H-O1 文件范围（治理方案 //） ----------

def _rules_store(tmp_path, rules: list[dict]) -> Store:
    store = Store(tmp_path)
    store.ensure_layout()
    (store.data_dir / "rules.json").write_text(
        json.dumps({"rules": rules}, ensure_ascii=False), encoding="utf-8")
    return store


def test_agents_global_and_specified(tmp_path):
    store = _rules_store(tmp_path, [
        {"name": "g", "text": "全局规则", "trigger": "always", "enabled": True, "agents": ["*"]},
        {"name": "cc", "text": "claude专属", "trigger": "always", "enabled": True,
         "agents": ["claude-code"]},
        {"name": "none", "text": "未配装规则", "trigger": "always", "enabled": True, "agents": []},
    ])
    block = inject.assemble_rules_block(store, "hi", agent="claude-code")
    assert "全局规则" in block
    assert "claude专属" in block
    assert "未配装规则" not in block  # [] = 不注入任何工具（≠ 全局）
    block2 = inject.assemble_rules_block(store, "hi", agent="cursor")
    assert "全局规则" in block2
    assert "claude专属" not in block2
    assert "未配装规则" not in block2


def test_agents_unknown_only_global(tmp_path):
    """unknown 兜底（写死）：只注入 ["*"] 全局规则，指定规则一律跳过（宁缺毋滥）。"""
    store = _rules_store(tmp_path, [
        {"name": "g", "text": "全局规则", "trigger": "always", "enabled": True, "agents": ["*"]},
        {"name": "cc", "text": "claude专属", "trigger": "always", "enabled": True,
         "agents": ["claude-code"]},
    ])
    block = inject.assemble_rules_block(store, "hi", agent="unknown")
    assert "全局规则" in block
    assert "claude专属" not in block


def test_agents_missing_defaults_global(tmp_path):
    """存量规则无 agents 字段 = 全局（向后兼容，不改变现有行为）。"""
    store = _rules_store(tmp_path, [
        {"name": "legacy", "text": "老规则", "trigger": "always", "enabled": True},
    ])
    assert "老规则" in inject.assemble_rules_block(store, "hi", agent="任意工具")


def test_normalize_rule_semantics():
    assert normalize_rule({"name": "x"})["agents"] == ["*"]
    assert normalize_rule({"agents": []})["agents"] == []  # 显式未配装不回填
    r = normalize_rule({"agents": [1], "scope": "glob", "globs": ["a/**", "", "b"]})
    assert r["agents"] == ["1"]
    assert r["globs"] == ["a/**", "b"]
    assert normalize_rule("不是dict") == "不是dict"


def test_store_load_rules_normalizes(tmp_path):
    store = _rules_store(tmp_path, [{"name": "old", "text": "t", "trigger": "always"}])
    assert store.load_rules()[0]["agents"] == ["*"]
    # upsert 补 agents 缺省（GUI 开关 enabled 的局部更新不丢配装）
    out = store.upsert_rule({"id": "new", "name": "n", "text": "t"})
    assert out["agents"] == ["*"]


def test_glob_scope_filter(tmp_path):
    store = _rules_store(tmp_path, [
        {"name": "g", "text": "全局规则", "trigger": "always", "enabled": True, "agents": ["*"]},
        {"name": "tests", "text": "测试规范", "trigger": "always", "enabled": True,
         "agents": ["*"], "scope": "glob", "globs": ["**/test_*.py"]},
    ])
    hit = inject.assemble_rules_block(
        store, "改一下测试", agent="claude-code", files=["tests/test_inject.py"])
    assert "测试规范" in hit
    miss = inject.assemble_rules_block(
        store, "改一下主程序", agent="claude-code", files=["app/main.py"])
    assert "测试规范" not in miss
    assert "全局规则" in miss
    # 无文件上下文时 glob 规则不注入（宁缺毋滥），全局规则不受影响
    nofiles = inject.assemble_rules_block(store, "hi", agent="claude-code")
    assert "测试规范" not in nofiles
    assert "全局规则" in nofiles


def test_extract_file_context():
    text = "帮我修 tests/test_inject.py 和 F:\\proj\\app\\main.py 里的问题"
    files = inject.extract_file_context(text)
    assert "tests/test_inject.py" in files
    assert any(f.endswith("app/main.py") for f in files)
    assert inject.extract_file_context("没有路径的普通话") == []
    # 上限 50 条
    assert len(inject.extract_file_context(" ".join(f"a/b/c{i}.py" for i in range(80)))) <= 50


# ---------- H-O2：规则注入命中追踪 ----------

def test_rules_block_records_hits(tmp_path):
    """进入注入块的规则记命中（always + hard-hook）；停用/agent 不匹配不记。"""
    store = _store(tmp_path)
    store.upsert_rule({"id": "r-always", "name": "a", "text": "甲", "trigger": "always"})
    store.upsert_rule({"id": "r-hard", "name": "b", "text": "乙", "trigger": "hard-hook",
                       "template_priority": "p0"})
    store.upsert_rule({"id": "r-off", "name": "c", "text": "丙", "trigger": "always",
                       "enabled": False})
    store.upsert_rule({"id": "r-agent", "name": "d", "text": "丁", "trigger": "always",
                       "agents": ["codex"]})
    block = inject.assemble_rules_block(store, agent="claude-code")
    assert "甲" in block and "乙" in block
    hits = store.load_rule_hits()
    assert hits["r-always"]["count"] == 1 and hits["r-hard"]["count"] == 1
    assert hits["r-always"]["last"] and hits["r-hard"]["last"]
    assert "r-off" not in hits and "r-agent" not in hits
    # 再注入一次 → 累计 +1
    inject.assemble_rules_block(store, agent="claude-code")
    assert store.load_rule_hits()["r-always"]["count"] == 2


def test_rules_block_keyword_hit_only_when_matched(tmp_path):
    """keyword 规则：关键词未命中不注入也不记命中；命中才记。"""
    store = _store(tmp_path)
    store.upsert_rule({"id": "r-kw", "name": "k", "text": "开票",
                       "trigger": "keyword", "keyword": "发票"})
    inject.assemble_rules_block(store, user_content="随便聊聊", agent="claude-code")
    assert "r-kw" not in store.load_rule_hits()
    block = inject.assemble_rules_block(store, user_content="开一张发票",
                                        agent="claude-code")
    assert "开票" in block
    assert store.load_rule_hits()["r-kw"]["count"] == 1


def test_rules_block_manual_only_when_mentioned(tmp_path):
    """M1：手动（我提及时才用）= 当前消息命中 keyword/规则名才注入，
    不再无条件注入。"""
    store = _store(tmp_path)
    store.upsert_rule({"id": "r-m1", "name": "公文格式", "text": "发文字号用六角括号",
                       "trigger": "manual"})
    store.upsert_rule({"id": "r-m2", "name": "n2", "text": "开票流程",
                       "trigger": "manual", "keyword": "发票"})
    block = inject.assemble_rules_block(store, user_content="随便聊聊",
                                        agent="claude-code")
    assert "发文字号用六角括号" not in block and "开票流程" not in block
    assert store.load_rule_hits() == {}
    block = inject.assemble_rules_block(store, user_content="按公文格式来",
                                        agent="claude-code")
    assert "发文字号用六角括号" in block  # 命中规则名
    assert "开票流程" not in block
    block = inject.assemble_rules_block(store, user_content="开一张发票",
                                        agent="claude-code")
    assert "开票流程" in block  # keyword 优先命中
    hits = store.load_rule_hits()
    assert hits["r-m1"]["count"] == 1 and hits["r-m2"]["count"] == 1


def test_rules_block_smart_injects_brief_only(tmp_path):
    """M1：智能应用（默认档）= 只给描述（名字+首行截断），agent 判断相关才用。"""
    store = _store(tmp_path)
    store.upsert_rule({"id": "r-s1", "name": "品牌语气",
                       "text": "第一行要点\n第二行不该出现", "trigger": "smart"})
    block = inject.assemble_rules_block(store, user_content="随便聊聊",
                                        agent="claude-code")
    assert "品牌语气：第一行要点" in block
    assert "第二行不该出现" not in block


def test_rules_block_smart_not_counted_as_hit(tmp_path):
    """低7：smart 是默认档（启用即每次注入 brief），若计命中则「过时」判定
    （长期无命中 → 提示淘汰）对默认档永不触发——smart 不记账；
    同请求里的 always 规则仍记。"""
    store = _store(tmp_path)
    store.upsert_rule({"id": "r-s1", "name": "品牌语气",
                       "text": "第一行要点", "trigger": "smart"})
    store.upsert_rule({"id": "r-a1", "name": "格式", "text": "代码块", "trigger": "always"})
    block = inject.assemble_rules_block(store, user_content="随便聊聊",
                                        agent="claude-code")
    assert "品牌语气" in block and "代码块" in block
    hits = store.load_rule_hits()
    assert "r-s1" not in hits
    assert hits["r-a1"]["count"] == 1


def test_rules_block_budget_truncation_excludes_hit(tmp_path):
    """预算截短掉的规则不算命中（没真正注入给模型）。"""
    store = _store(tmp_path)
    store.upsert_rule({"id": "r1", "name": "1", "text": "一" * 30, "trigger": "always"})
    store.upsert_rule({"id": "r2", "name": "2", "text": "二" * 30, "trigger": "always"})
    block = inject.assemble_rules_block(store, budget=40, agent="claude-code")
    hits = store.load_rule_hits()
    assert hits.get("r1", {}).get("count") == 1
    assert "r2" not in hits
    assert "一" * 30 in block and "二" * 30 not in block


def test_record_rule_hits_dedup_and_empty(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_rule_hits(["a", "a", "b"])  # 单次请求同规则去重
    h = store.load_rule_hits()
    assert h["a"]["count"] == 1 and h["b"]["count"] == 1
    store.record_rule_hits([])  # 空 ids no-op
    assert store.load_rule_hits() == h


# ---------- H-O3：反例引导（应当 + 绝不） ----------

def test_rule_injection_text_with_donts(tmp_path):
    """注入文本 = 应当正文 + 绝不列表；无 donts 的规则注入文本不变（向后兼容）。"""
    store = _store(tmp_path)
    store.upsert_rule({"id": "r1", "name": "a", "text": "发文字号用六角括号",
                       "trigger": "always",
                       "donts": ["别用圆括号", "别漏年份"]})
    store.upsert_rule({"id": "r2", "name": "b", "text": "旧规则", "trigger": "always"})
    block = inject.assemble_rules_block(store, agent="claude-code")
    assert "绝不：\n- 别用圆括号\n- 别漏年份" in block
    assert "旧规则" in block
    # 单元口径：无 donts 原样；空 text 只出绝不
    assert inject._rule_injection_text({"text": "x"}) == "x"
    assert inject._rule_injection_text({"text": "", "donts": ["d1"]}) == "绝不：\n- d1"
    assert inject._rule_injection_text({"text": "  "}) == ""


def test_donts_rule_counts_one_hit(tmp_path):
    """带 donts 的规则仍是整条规则：命中记一次（不拆行计数）。"""
    store = _store(tmp_path)
    store.upsert_rule({"id": "r1", "name": "a", "text": "t", "trigger": "always",
                       "donts": ["d1", "d2"]})
    inject.assemble_rules_block(store, agent="claude-code")
    h = store.load_rule_hits()
    assert h["r1"]["count"] == 1 and len(h) == 1
