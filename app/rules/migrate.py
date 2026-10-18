"""用户规则一次性数据迁移（W4-07）：旧模板 ID → 新 ID + file 触发 → manual。

背景（模板矩阵重设计阶段 3）：
- 已导入用户的旧模板规则（template_id = 旧 ID）映射到新 ID，数据目录正文
  文件同步改名（用户改动随文件保留）；
- eng-general 是 1→3 拆分（c2 风格 / c3 测试 / c5 安全），无单一新模板对应：
  规则内容原样保留，降级为普通用户规则（去掉 template 关联，「恢复默认」入口消失）；
- 用户已启用的 file 触发自动转 manual（保留 keyword；inject 语义不变——
  file 原本就落入 always 分支，manual 同分支）。

幂等：映射表只含旧 ID，跑第二遍全部无操作。用户自写规则（无 template_id、
非 file 触发）不动。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("experientia.rules.migrate")

# 旧模板 ID → 新模板 ID（W4-05 映射表；eng-general 不在此表，见 SPLIT_OLD_IDS）
OLD_TO_NEW: dict[str, str] = {
    "eng-backend": "c1-p1-backend",
    "eng-frontend": "c1-p1-frontend",
    "eng-data": "c6-p2-data-eng",
    "eng-deploy": "c3-p2-deploy",
    "hard-accounting": "c5-p0-accounting",
    "hard-bidding": "c5-p0-bidding",
    "hard-insurance": "c5-p0-insurance",
    "hard-legal": "c5-p0-legal",
    "hard-medical": "c5-p0-medical",
    "hard-official-doc": "c5-p0-official-doc",
    "edu-pii": "c5-p0-edu-pii",
    "edu-facts": "c6-p3-edu-facts",
    "edu-rubric": "c6-p3-edu-rubric",
    "edu-smart": "c6-p3-edu-smart",
    "mkt-ads": "c6-p2-mkt-ads",
    "mkt-brand": "c6-p2-mkt-brand",
    "mkt-reuse": "c6-p2-mkt-reuse",
    "mkt-seo": "c6-p2-mkt-seo",
    "mkt-titles": "c6-p2-mkt-titles",
    "mtg-agenda": "c6-p1-mtg-agenda",
    "mtg-weekly": "c6-p1-mtg-weekly",
    "mtg-onboarding": "c6-p2-mtg-onboarding",
    "prd-structure": "c6-p1-prd-structure",
    "prd-decision": "c6-p1-prd-decision",
    "prd-competitor": "c6-p1-prd-competitor",
    "prd-stories": "c6-p2-prd-stories",
    "data-framework": "c6-p2-data-framework",
    "data-report": "c6-p2-data-report",
    "data-viz": "c6-p2-data-viz",
    "biz-gtm": "c6-p3-biz-gtm",
    "biz-okr": "c6-p3-biz-okr",
    "biz-pricing": "c6-p3-biz-pricing",
    "biz-swot": "c6-p3-biz-swot",
    "re-housing": "c6-p3-re-housing",
    "re-listing": "c6-p3-re-listing",
    "re-plain": "c6-p3-re-plain",
    "sale-followup": "c6-p1-sale-followup",
    "sale-call": "c6-p3-sale-call",
    "sale-objection": "c6-p3-sale-objection",
    "wri-edit": "c6-p4-wri-edit",
    "wri-structure": "c6-p3-wri-structure",
    "wri-style": "c6-p3-wri-style",
}

SPLIT_OLD_IDS = {"eng-general"}  # 1→3 拆分：保留规则内容，降级为普通用户规则


def migrate_user_rules(store) -> dict:
    """跑一遍迁移。返回 {"remapped": n, "unsplittable": n, "file_to_manual": n}，
    全 0 = 无改动（幂等判据）。"""
    rules = store.load_rules()
    remapped = unsplittable = file_to_manual = 0
    existing_ids = {r.get("id") for r in rules}

    for rule in rules:
        patch: dict = {}
        old = rule.get("template_id", "")
        if old in OLD_TO_NEW:
            new = OLD_TO_NEW[old]
            patch["template_id"] = new
            # 规则 id 随模板惯例改名（tpl-<tid>）；目标 id 已被占用则保留原 id
            if rule.get("id") == f"tpl-{old}" and f"tpl-{new}" not in existing_ids:
                patch["id"] = f"tpl-{new}"
            rel = rule.get("file", "")
            new_rel = f"rules/{new}.md"
            if rel and rel != new_rel:
                store.rename_rule_file(rel, new_rel)  # 收口 store，不裸拼 data_dir
                patch["file"] = new_rel
            remapped += 1
        elif old in SPLIT_OLD_IDS:
            patch["template_id"] = ""
            unsplittable += 1
        if rule.get("trigger") == "file":
            patch["trigger"] = "manual"
            file_to_manual += 1
        if not patch:
            continue
        if "id" in patch:
            if patch["id"] == rule["id"]:
                # L-N16: 同一 ID 原地更新，避免先 upsert 后 remove 两次写
                store.upsert_rule({**rule, **patch})
            else:
                store.upsert_rule({**rule, **patch})
                store.remove_rule(rule["id"])
        else:
            store.upsert_rule({**rule, **patch})
    if remapped or unsplittable or file_to_manual:
        logger.info("规则迁移: remapped=%d unsplittable=%d file_to_manual=%d",
                    remapped, unsplittable, file_to_manual)
    return {"remapped": remapped, "unsplittable": unsplittable,
            "file_to_manual": file_to_manual}
