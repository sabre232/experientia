"""Phase 5 + W4 模板库：注册表（6 类目 × 5 优先级矩阵）/ 导入流程 / 模板文件改完即生效 /
恢复默认 / API 端点。W4 专项验收（P0 锁定、file 废弃、用户规则迁移）见
test_w4_template_matrix.py。"""

from pathlib import Path

import pytest

from app.proxy import inject
from app.rules import registry
from app.store.store import Store

P0_IDS = {
    "c5-p0-accounting", "c5-p0-bidding", "c5-p0-insurance",
    "c5-p0-legal", "c5-p0-medical", "c5-p0-official-doc",
    "c5-p0-edu-pii", "c5-p0-eng-safety",
}


def _store(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    return store


# ---------- 注册表（W4 矩阵） ----------

def test_zh_and_en_have_full_library():
    for lang in ("zh", "en"):
        cats = registry.list_templates(lang)
        by_cat = {c["id"]: c for c in cats}
        # 6 类目齐全（c5 = 6 强约束 + edu-pii + eng 安全边界）
        assert list(by_cat) == ["c1", "c2", "c3", "c4", "c5", "c6"], lang
        assert len(by_cat["c5"]["templates"]) == 8, lang
        assert len(by_cat["c4"]["templates"]) == 5, lang
        total = sum(len(c["templates"]) for c in cats)
        assert total == 50, (lang, total)


def test_missing_lang_falls_back_to_en_with_flag():
    """语言目录不存在 → 全量 en 回退 + native=False。"""
    cats = registry.list_templates("xx")  # 不存在的语言
    all_t = [t for c in cats for t in c["templates"]]
    assert len(all_t) == 50  # 回退后仍全量
    assert all(not t["native"] and t["served_by"] == "en" for t in all_t)


def test_all_five_locale_langs_have_full_native_library():
    """Batch B+C：ja/ko/fr/de/es 结构层全补齐，7 语全量原生（各 50/50，native 全 True）。"""
    for lang in ("ja", "ko", "fr", "de", "es"):
        cats = registry.list_templates(lang)
        all_t = [t for c in cats for t in c["templates"]]
        assert len(all_t) == 50, lang
        assert all(t["native"] and t["served_by"] == lang for t in all_t), lang


def test_frontmatter_new_fields_parsed():
    t = registry.get_template("zh", "c5-p0-bidding")
    assert t["layer"] == "hard"
    assert t["priority"] == "p0"
    assert t["trigger_default"] == "hard-hook"
    assert "投标" in t["keywords"]
    assert "bidding" in t["tags"]
    assert t["source"] == "research"
    assert t["from"] == "hard-bidding"  # 旧 ID 别名（W4-07 迁移用）
    assert len(t["donts"]) == 5  # P0 必填 donts
    assert "NEVER" in t["body"]
    # 正文不应带 frontmatter 残留
    assert not t["body"].startswith("---")


def test_donts_block_with_semicolons_roundtrips():
    """de 的 donts 条目自身含分号 → 块标量按行解析，不能按分号切。"""
    t = registry.get_template("de", "c5-p0-insurance")
    assert t["donts"], "de P0 应有 donts"
    assert any(";" in d for d in t["donts"]), "应保留含分号的完整条目"


def test_priority_sort_within_category():
    cats = {c["id"]: c for c in registry.list_templates("zh")}
    pris = [t["priority"] for t in cats["c6"]["templates"]]
    rank = {"p0": 0, "p1": 1, "p2": 2, "p3": 3, "p4": 4}
    assert pris == sorted(pris, key=lambda p: rank[p]), "类目内 P0 应在前"
    assert pris[0] == "p1"  # c6 无 P0，最前是 P1（sale-followup/mtg/prd）


def test_unknown_template_is_none():
    assert registry.get_template("zh", "no-such-tpl") is None


# ---------- 导入流程 ----------

def test_import_copies_file_and_upserts_rule(tmp_path):
    store = _store(tmp_path)
    rule = registry.import_template(store, "zh", "c5-p0-bidding")
    assert rule["id"] == "tpl-c5-p0-bidding"
    assert rule["trigger"] == "hard-hook"  # P0 锁定硬钩子
    assert rule["template_priority"] == "p0"
    f = Path(store.data_dir) / "rules" / "c5-p0-bidding.md"
    assert f.exists()
    rules = store.load_rules()
    assert any(r["id"] == "tpl-c5-p0-bidding" for r in rules)


def test_import_structure_defaults_to_smart(tmp_path):
    store = _store(tmp_path)
    rule = registry.import_template(store, "en", "c6-p2-mkt-brand")
    assert rule["trigger"] == "smart"


def test_import_p1_defaults_to_always(tmp_path):
    store = _store(tmp_path)
    rule = registry.import_template(store, "zh", "c4-p1-commit")
    assert rule["trigger"] == "always"


def test_import_unknown_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(KeyError):
        registry.import_template(store, "zh", "nope")


def test_import_bad_trigger_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        registry.import_template(store, "zh", "c6-p2-mkt-brand", trigger="bogus")


def test_reimport_is_idempotent(tmp_path):
    store = _store(tmp_path)
    registry.import_template(store, "zh", "c6-p2-mkt-seo")
    registry.import_template(store, "zh", "c6-p2-mkt-seo")
    assert sum(1 for r in store.load_rules() if r["id"] == "tpl-c6-p2-mkt-seo") == 1


# ---------- 改完即生效 + 恢复默认 ----------

def test_user_edit_of_file_is_injected(tmp_path):
    store = _store(tmp_path)
    registry.import_template(store, "zh", "c5-p0-legal")
    f = Path(store.data_dir) / "rules" / "c5-p0-legal.md"
    # 用户改文件 → 注入用新内容
    f.write_text("USER-CUSTOM-RULE\n", encoding="utf-8")
    block = inject.assemble_rules_block(store, "任何消息")
    assert "USER-CUSTOM-RULE" in block
    assert "IRAC" not in block  # 原文已被用户版本取代


def test_restore_default_overwrites_user_edit(tmp_path):
    store = _store(tmp_path)
    registry.import_template(store, "zh", "c5-p0-legal")
    f = Path(store.data_dir) / "rules" / "c5-p0-legal.md"
    f.write_text("USER-CUSTOM-RULE\n", encoding="utf-8")
    t = registry.get_template("zh", "c5-p0-legal")
    f.write_text(t["body"] + "\n", encoding="utf-8")
    block = inject.assemble_rules_block(store, "任何消息")
    assert "USER-CUSTOM-RULE" not in block
    assert "IRAC" in block


def test_rule_without_file_falls_back_to_text(tmp_path):
    store = _store(tmp_path)
    store.upsert_rule({"id": "r1", "name": "n", "text": "PLAIN-TEXT-RULE",
                       "trigger": "always", "enabled": True})
    block = inject.assemble_rules_block(store, "x")
    assert "PLAIN-TEXT-RULE" in block


def test_hard_hook_ignores_budget(tmp_path):
    store = _store(tmp_path)
    registry.import_template(store, "zh", "c5-p0-bidding")
    block = inject.assemble_rules_block(store, "投标", budget=10)
    assert "投标" in block or "NEVER" in block  # 硬钩子不受预算截断


# ---------- API 端点 ----------

def test_api_templates_list_and_import(tmp_path):
    from conftest import local_api_client
    store = _store(tmp_path)
    client = local_api_client(store)

    r = client.get("/api/rules/templates", params={"lang": "en"})
    assert r.status_code == 200
    data = r.json()
    assert data["lang"] == "en"
    cats = {c["id"] for c in data["categories"]}
    assert cats == {"c1", "c2", "c3", "c4", "c5", "c6"}

    r = client.post("/api/rules/templates/import",
                    json={"template_id": "c5-p0-legal", "lang": "en"})
    assert r.status_code == 200
    rule = r.json()["rule"]
    assert rule["id"] == "tpl-c5-p0-legal"
    assert rule["trigger"] == "hard-hook"

    # 未知模板 404
    r = client.post("/api/rules/templates/import",
                    json={"template_id": "nope", "lang": "en"})
    assert r.status_code == 404

    # 恢复默认
    r = client.post("/api/rules/templates/c5-p0-legal/restore-default",
                    params={"lang": "en"})
    assert r.status_code == 200
    r = client.post("/api/rules/templates/nope/restore-default")
    assert r.status_code == 404


# ---------- H-O3：导入校验（P0 必带 donts） ----------

def test_import_p0_stores_donts(tmp_path):
    """P0 红线导入时 donts 随规则落库（编辑器「绝不」栏预填 + 注入拼接）。"""
    store = _store(tmp_path)
    rule = registry.import_template(store, "zh", "c5-p0-bidding")
    assert rule["donts"], "P0 必须带 donts 反例"
    assert all(isinstance(d, str) and d for d in rule["donts"])


def test_import_p0_without_donts_raises(tmp_path, monkeypatch):
    """P0 模板缺 donts → 拒导入（兜底防坏模板；规范本就要求 P0 必带反例）。"""
    store = _store(tmp_path)
    real = registry.get_template

    def _fake(lang, tid):
        t = dict(real(lang, tid))
        t["donts"] = []
        return t

    monkeypatch.setattr(registry, "get_template", _fake)
    with pytest.raises(ValueError):
        registry.import_template(store, "zh", "c5-p0-bidding")
