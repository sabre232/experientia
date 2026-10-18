"""本地 API 的「规则与模板」资源域：`/api/rules/*`。

从 `create_local_app()`（原 1652 行大闭包）拆出的第二个资源域，
范式同 `models.py`：

1. 只依赖 `store` 与产品层（detect / inject / rules registry），
   **绝不 import `app.local_api`**，避免与挂载处循环导入；
2. 只暴露 `build_xxx_router(store)` 工厂，端点靠闭包拿 store；
3. 本域专属的 schema（RuleIn / TemplateImportIn）与私有助手全部随域搬走
   （已核对：全库仅本域使用）；`local_api` 侧保留同名再导出以兼容旧 import。
"""

from __future__ import annotations

import datetime as _dt

from ..time_util import parse_ts
import re as _re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..proxy import detect, inject
from ..rules import registry as templates
from ..store.store import Store


class RuleIn(BaseModel):
    id: str | None = None
    name: str
    text: str
    trigger: str = "smart"  # always / file / smart / manual / hard-hook
    keyword: str | None = None
    file_match: str | None = None
    enabled: bool = True
    # H-A0 工具范围：["*"]=全部工具（缺省）/ 指定列表 / []=未配装（软停用）
    agents: list[str] | None = None
    # H-O1 文件范围："glob" + globs（缺省 = 全局生效）
    scope: str | None = None
    globs: list[str] | None = None
    # H-O3 反例引导：绝不（donts 列表，与 text=应当分列）
    donts: list[str] | None = None


class TemplateImportIn(BaseModel):
    template_id: str
    trigger: str | None = None  # 缺省 = 模板建议档位（强约束=硬钩子）
    keyword: str | None = None
    lang: str | None = None  # 缺省 = GUI 当前界面语言


def _stale_days(store: Store) -> int:
    """H-O2 过时阈值（天，可配）：config.hook_stale_days，缺省 30，限 [1,365]。"""
    try:
        v = int(store.load_config().get("hook_stale_days", 30))
    except (TypeError, ValueError):
        v = 30
    return max(1, min(v, 365))


def _sum_rule_days(days: dict, window: int = 7) -> int:
    """近 N 天命中聚合：{iso_date: n} 中取最近 window 天求和（含今天）。"""
    today = _dt.datetime.now(_dt.timezone.utc).date()
    cutoff = (today - _dt.timedelta(days=window - 1)).isoformat()
    return sum(int(v) for k, v in days.items() if str(k) >= cutoff)


def _rule_hit_view(rule: dict, hits: dict, stale_days: int) -> dict:
    """H-O2 单条 hook 命中视图：累计次数 / 最近命中 / 是否过时。

    过时 = 最近命中距今 > N 天；或从未命中且规则已存在 > N 天（新规则宽限）。"""
    e = hits.get(str(rule.get("id"))) or {}
    count = int(e.get("count", 0) or 0)
    last = parse_ts(e.get("last"))
    stale = False
    if last is not None:
        stale = (_dt.datetime.now(_dt.timezone.utc) - last).days >= stale_days
    elif count == 0:
        created = parse_ts(rule.get("created_at"))
        if created is not None:
            stale = (_dt.datetime.now(_dt.timezone.utc) - created).days >= stale_days
    near7 = count  # 旧数据无 days → 累计垫底（迁移期近似）
    days = e.get("days")
    if isinstance(days, dict):
        near7 = _sum_rule_days(days)
    return {"hit_count": count, "hit_7d": near7,
            "last_hit": e.get("last"), "stale": stale}


def _rule_priority(rule: dict) -> str:
    """H-O3 规则优先级档：template_priority；自定义规则按 trigger 降级推断（与导出口径一致）。"""
    return rule.get("template_priority") or {
        "hard-hook": "p0", "always": "p1", "smart": "p2",
        "manual": "p4"}.get(rule.get("trigger", "smart"), "p2")


def _contradicts(a: dict, b: dict) -> bool:
    """H-O3：a 的「绝不」与 b 的「应当」正文互相排斥（简单子串口径）。

    只报确定矛盾（某条 dont 原句出现在对方应当正文里），宁可漏报不误报；
    语义级矛盾交给用户看红点后自己拍板（不引入裁决引擎）。"""
    for d in a.get("donts") or []:
        d = str(d).strip()
        if len(d) >= 4 and d in str(b.get("text") or ""):
            return True
    return False


def _conflict_rule_ids(rules: list[dict]) -> set:
    """同优先级冲突（双向）：不自动覆盖，只标 id 供红点提示（用户拍板）。"""
    ids: set = set()
    en = [r for r in rules if r.get("enabled", True) and r.get("id")]
    for i in range(len(en)):
        for j in range(i + 1, len(en)):
            a, b = en[i], en[j]
            if _rule_priority(a) != _rule_priority(b):
                continue
            if (_contradicts(a, b) or _contradicts(b, a)
                    or str(a.get("text") or "").strip()
                    == str(b.get("text") or "").strip()):
                ids.add(a["id"])
                ids.add(b["id"])
    return ids


def build_rules_router(store: Store) -> APIRouter:
    """挂载 /api/rules/* 八个端点（规则增删改查、工具清单、模板列表/导入/恢复默认）。"""
    router = APIRouter()

    @router.get("/api/rules")
    def rules_list():
        rules = store.load_rules()
        used = sum(inject.estimate_tokens(r.get("text", ""))
                   for r in rules if r.get("enabled", True))
        # H-O2：合并注入命中（累计次数/最近命中）+ 过时判定（N 天未命中，可配）
        hits = store.load_rule_hits()
        stale_days = _stale_days(store)
        # H-O3：同优先级冲突标记（红点，不自动裁决）
        conflict_ids = _conflict_rule_ids(rules)
        for r in rules:
            r.update(_rule_hit_view(r, hits, stale_days))
            r["conflict"] = r.get("id") in conflict_ids
        return {"items": rules, "budget_used": used,
                "budget": inject.RULES_BUDGET_TOKENS, "stale_days": stale_days}

    @router.post("/api/rules")
    def rules_add(body: RuleIn):
        rule = store.upsert_rule(body.model_dump(exclude_none=True))
        return {"message": "已导入", "rule": rule}

    @router.put("/api/rules/{rule_id}")
    def rules_update(rule_id: str, body: RuleIn):
        if body.id != rule_id:
            raise HTTPException(status_code=400, detail="id 不匹配")
        rule = store.upsert_rule(body.model_dump(exclude_none=True))
        return {"message": "已更新", "rule": rule}

    @router.delete("/api/rules/{rule_id}")
    def rules_remove(rule_id: str):
        if not store.remove_rule(rule_id):
            raise HTTPException(status_code=404, detail="规则不存在")
        return {"message": "已删除"}

    @router.get("/api/rules/agents")
    def rules_agents():
        """H-A0 按工具视图的工具清单：detect 识别模式 ∪ 实际接入过的 session agent，
        去重排序（治理方案：不开放手填，防止配装到永不命中的工具名）。"""
        known = set(detect.agent_names())
        for s in store.list_sessions():
            a = s.get("agent")
            if a and a != "unknown":
                known.add(a)
        return {"agents": sorted(known)}

    # ---------- 模板库（选模板 → 选生效方式 → 一键导入） ----------

    @router.get("/api/rules/templates")
    def templates_list(lang: str = "zh"):
        """lang = GUI 当前界面语言（外壳显式传入，引擎不 import GUI）。"""
        return {"lang": lang, "categories": templates.list_templates(lang)}

    @router.post("/api/rules/templates/import")
    def templates_import(body: TemplateImportIn):
        try:
            rule = templates.import_template(
                store, body.lang or "zh", body.template_id,
                trigger=body.trigger, keyword=body.keyword)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"message": "已导入", "rule": rule}

    @router.post("/api/rules/templates/{template_id}/restore-default")
    def templates_restore(template_id: str, lang: str = "zh"):
        """恢复默认 = 用模板库原文覆盖数据目录里的 md（「可恢复默认」）。"""
        # H-N2: 严格校验 template_id——只允许字母/数字/连字符/下划线
        if not _re.fullmatch(r"[a-zA-Z0-9_-]+", template_id):
            raise HTTPException(status_code=400, detail="template_id 包含非法字符")
        t = templates.get_template(lang, template_id)
        if t is None:
            raise HTTPException(status_code=404, detail="未知模板")
        rel = f"rules/{template_id}.md"
        if not (store.data_dir / rel).exists():
            raise HTTPException(status_code=404, detail="未导入过该模板")
        store.write_rule_file(rel, t["body"] + "\n")  # 落盘走 store
        return {"message": "已恢复默认", "template_id": template_id}

    return router
