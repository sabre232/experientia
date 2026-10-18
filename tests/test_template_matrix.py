"""W4 验收（模板矩阵重设计）：

- P0 导入后 trigger 锁定 hard-hook（不可改）
- 非 P0 模板不可选 hard-hook（代码层拦截）
- file trigger 废弃（导入报错；已有用户规则自动迁 manual）
- 用户 rules 一次性迁移：旧 ID → 新 ID、数据文件改名、eng-general 拆分降级、幂等
- 旧模板 ID 通过 frontmatter `from` 字段保留别名
"""

from pathlib import Path

import pytest

from app.rules import migrate, registry
from app.store.store import Store


def _store(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    return store


# ---------- P0 锁定 + trigger 校验 ----------

def test_import_p0_forces_hard_hook(tmp_path):
    """P0 红线：传任何 trigger 都锁定 hard-hook。"""
    for i, trig in enumerate(("always", "smart", "manual", "hard-hook", None)):
        store = _store(tmp_path / f"s{i}")
        rule = registry.import_template(store, "zh", "c5-p0-medical", trigger=trig)
        assert rule["trigger"] == "hard-hook"


def test_import_non_p0_rejects_hard_hook(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="仅 P0"):
        registry.import_template(store, "zh", "c6-p2-mkt-brand", trigger="hard-hook")


def test_import_file_trigger_deprecated(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="废弃"):
        registry.import_template(store, "zh", "c6-p2-mkt-brand", trigger="file")


def test_api_import_file_trigger_400(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    client = local_api_client(store)
    r = client.post("/api/rules/templates/import",
                    json={"template_id": "c6-p2-mkt-brand", "lang": "zh",
                          "trigger": "file"})
    assert r.status_code == 400
    r = client.post("/api/rules/templates/import",
                    json={"template_id": "c5-p0-bidding", "lang": "zh",
                          "trigger": "smart"})
    assert r.status_code == 200
    assert r.json()["rule"]["trigger"] == "hard-hook"  # P0 锁定


# ---------- 用户规则迁移（W4-07，幂等） ----------

def _seed_old_rules(store: Store):
    """模拟旧世界用户数据：模板规则（旧 ID）+ file 触发 + 用户自写规则 + eng-general。"""
    rules_dir = Path(store.data_dir) / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "hard-bidding.md").write_text("OLD-TPL-BODY-已改\n", encoding="utf-8")
    (rules_dir / "eng-general.md").write_text("OLD-ENG-GENERAL-BODY\n", encoding="utf-8")
    store.upsert_rule({"id": "tpl-hard-bidding", "name": "投标废标红线",
                       "text": "OLD-TPL-BODY-已改", "trigger": "hard-hook",
                       "template_id": "hard-bidding", "file": "rules/hard-bidding.md",
                       "enabled": True})
    store.upsert_rule({"id": "tpl-eng-general", "name": "工程通用",
                       "text": "OLD-ENG-GENERAL-BODY", "trigger": "smart",
                       "template_id": "eng-general", "file": "rules/eng-general.md",
                       "enabled": True})
    store.upsert_rule({"id": "r-user", "name": "我的规则", "text": "USER-RULE",
                       "trigger": "file", "keyword": "投标", "enabled": True})


def test_migrate_remaps_template_rules(tmp_path):
    store = _store(tmp_path)
    _seed_old_rules(store)
    result = migrate.migrate_user_rules(store)
    assert result["remapped"] == 1
    assert result["unsplittable"] == 1
    assert result["file_to_manual"] == 1

    rules = {r["id"]: r for r in store.load_rules()}
    # 1:1 映射：id 改名 + template_id 换新 + 数据文件改名（用户改动随文件保留）
    assert "tpl-c5-p0-bidding" in rules
    r = rules["tpl-c5-p0-bidding"]
    assert r["template_id"] == "c5-p0-bidding"
    assert r["file"] == "rules/c5-p0-bidding.md"
    assert (Path(store.data_dir) / "rules" / "c5-p0-bidding.md").exists()
    assert not (Path(store.data_dir) / "rules" / "hard-bidding.md").exists()
    assert "OLD-TPL-BODY-已改" in r["text"]
    # eng-general 1→3 拆分：内容保留，降级为普通用户规则
    r = rules["tpl-eng-general"]
    assert r["template_id"] == ""
    assert "OLD-ENG-GENERAL-BODY" in r["text"]
    assert r["trigger"] == "smart"
    # file 触发 → manual（keyword 保留）
    r = rules["r-user"]
    assert r["trigger"] == "manual"
    assert r["keyword"] == "投标"


def test_migrate_is_idempotent(tmp_path):
    store = _store(tmp_path)
    _seed_old_rules(store)
    migrate.migrate_user_rules(store)
    again = migrate.migrate_user_rules(store)
    assert again == {"remapped": 0, "unsplittable": 0, "file_to_manual": 0}
    assert len(store.load_rules()) == 3  # 不增不删


def test_migrate_noop_on_clean_data(tmp_path):
    store = _store(tmp_path)
    store.upsert_rule({"id": "r1", "name": "新规则", "text": "x",
                       "trigger": "always", "enabled": True})
    assert migrate.migrate_user_rules(store) == \
        {"remapped": 0, "unsplittable": 0, "file_to_manual": 0}


def test_migrate_all_old_ids_have_mapping():
    """映射表必须覆盖全部旧模板 ID（防漏迁）。"""
    from app.rules.migrate import OLD_TO_NEW, SPLIT_OLD_IDS

    old_ids = {"eng-backend", "eng-frontend", "eng-general", "eng-data", "eng-deploy",
               "hard-accounting", "hard-bidding", "hard-insurance", "hard-legal",
               "hard-medical", "hard-official-doc",
               "edu-pii", "edu-facts", "edu-rubric", "edu-smart",
               "mkt-ads", "mkt-brand", "mkt-reuse", "mkt-seo", "mkt-titles",
               "mtg-agenda", "mtg-weekly", "mtg-onboarding",
               "prd-structure", "prd-decision", "prd-competitor", "prd-stories",
               "data-framework", "data-report", "data-viz",
               "biz-gtm", "biz-okr", "biz-pricing", "biz-swot",
               "re-housing", "re-listing", "re-plain",
               "sale-followup", "sale-call", "sale-objection",
               "wri-edit", "wri-structure", "wri-style"}
    assert set(OLD_TO_NEW) | SPLIT_OLD_IDS == old_ids
    # 新 ID 必须都存在于模板库（zh）
    by_id = registry._load_dir("zh")
    for new in OLD_TO_NEW.values():
        assert new in by_id, f"映射目标不存在: {new}"


def test_from_alias_covers_all_migrated_templates():
    """W4-05：迁移过的模板 frontmatter 保留 from: 旧 ID 别名。"""
    by_id = registry._load_dir("zh")
    for old, new in migrate.OLD_TO_NEW.items():
        assert by_id[new]["from"] == old, new
    for tid in ("c2-p2-eng-style", "c3-p2-eng-baseline", "c5-p0-eng-safety"):
        assert by_id[tid]["from"] == "eng-general", tid


def test_no_old_ids_remain_in_template_dirs():
    """模板目录里不应再有旧 ID 文件（迁移彻底）。"""
    import re

    old_prefix = re.compile(r"^(biz|data|edu|eng|hard|mkt|mtg|prd|re|sale|wri)-")
    from app.rules.registry import TEMPLATES_DIR

    for f in TEMPLATES_DIR.glob("*/*.md"):
        assert not old_prefix.match(f.stem), f
