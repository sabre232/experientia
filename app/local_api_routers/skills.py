"""本地 API 的「方法与 Skill」资源域：`/api/skills/*`。

从 `create_local_app()` 拆出的第五个资源域，范式同 models.py
（只依赖 store 与产品层、暴露 `build_xxx_router(store)` 工厂、不反向 import
`app.local_api`）。`_raise_engine_status` / `_is_model_required` 是跨域共用件，
从 `._shared` 引入。

⚠️ 路由声明顺序敏感：`versions/*` 必须**先于** `/api/skills/{trunk}/{category}`
声明（FastAPI 按序匹配），搬迁时保持原有顺序不变。
"""

from __future__ import annotations

import re as _re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import notify
from ..distill import engine_curation
from ..distill import skill as skillgen
from ..store.store import Store
from ._shared import _is_model_required, _raise_engine_status


class DistillIn(BaseModel):
    trunk: str
    category: str
    # force = 用该类目**全部**经验重蒸馏（不只待总结的）：修被写坏的空卡要用它
    force: bool = False


class RenameSkillIn(BaseModel):
    name: str | None = None      # 显示名（说人话短名）；None = 不改
    category: str | None = None  # 新分类（迁移）；None = 不改


class SkillRewriteApplyIn(BaseModel):
    trunk: str
    category: str
    md: str                 # 预览返回的整份新 playbook（逐字落盘）


class SkillSaveIn(BaseModel):
    name: str
    md: str
    description: str | None = None
    source_count: int | None = None


def _skills_with_provenance(store: Store, items: list[dict]) -> list[dict]:
    """方法卡清单逐项补 content_source / generated_at（总纲）。

    旧卡没有这两个字段 → 空串 = **来源未知**（不是"none"），展示层据此不挂降级条。
    """
    for it in items or []:
        trunk, category = it.get("trunk"), it.get("category")
        src, at = ("", "")
        if trunk and category:
            src, at = skillgen.provenance_of(store.read_skill(trunk, category) or "")
        it["content_source"] = src
        it["generated_at"] = at
    return items


def build_skills_router(store: Store) -> APIRouter:
    """挂载 /api/skills/* 十三个端点（清单、版本、读卡、下钻、蒸馏、重写、改名、来源 agent）。"""
    router = APIRouter()

    @router.get("/api/skills")
    def skills_list():
        return {"items": _skills_with_provenance(store, store.list_skills())}

    # 生成的 Skill（重新生成版本化，可回看 diff）
    # 注意：versions 路由必须先于 /api/skills/{trunk}/{category} 声明（FastAPI 按序匹配）

    @router.get("/api/skills/versions/{name}")
    def skill_versions_list(name: str):
        return {"name": name, "versions": skillgen.list_skill_versions(store, name)}

    @router.get("/api/skills/versions/{name}/{n}")
    def skill_version_read(name: str, n: int):
        md = skillgen.read_skill_version(store, name, n)
        if md is None:
            raise HTTPException(status_code=404, detail="该版本不存在")
        return {"name": name, "version": n, "md": md}

    @router.get("/api/skills/versions/{name}/diff/{old}/{new}")
    def skill_version_diff(name: str, old: int, new: int):
        return {"name": name, "old": old, "new": new,
                "diff": skillgen.diff_versions(store, name, old, new)}

    @router.post("/api/skills/save")
    def skill_save(body: SkillSaveIn):
        try:
            info = skillgen.save_skill_version(
                store, body.name, body.md, body.description or "",
                body.source_count or 0)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"message": "已保存", **info}

    @router.get("/api/skills/{trunk}/{category}")
    def skill_read(trunk: str, category: str):
        md = store.read_skill(trunk, category)
        if md is None:
            raise HTTPException(status_code=404, detail="playbook 不存在")
        return {"trunk": trunk, "category": category, "md": md}

    @router.get("/api/skills/{trunk}/{category}/sources")
    def skill_sources(trunk: str, category: str):
        """W3-03/04 下钻引用链：方法(L2) → 经验(L1) → session 摘要(L0，只给摘要不给全文)。"""
        md = store.read_skill(trunk, category)
        if md is None:
            raise HTTPException(status_code=404, detail="playbook 不存在")
        m = _re.search(r"^>\s*source_exps:\s*(.+)$", md, _re.M)
        ids = [x.strip() for x in (m.group(1).split(",") if m else [])
               if x.strip() and x.strip() != "（无）"]
        exps_by_id = {str(e.get("id")): e
                      for e in store.iter_experiences(include_distilled=True)}
        sessions_by_id = {str(s.get("session_id")): s for s in store.list_sessions()
                          if s.get("session_id")}
        out = []
        for eid in ids:
            e = exps_by_id.get(eid)
            if e is None:
                continue
            s = sessions_by_id.get(str(e.get("session_id") or ""))
            summary = None
            if s:
                first = next((str(x)[:80] for x in (s.get("user_messages") or [])
                              if x), "")
                summary = {"agent": s.get("agent", ""), "first_msg": first,
                           "req_count": s.get("req_count"),
                           "started_at": str(s.get("started_at") or "")[:16]}
            out.append({
                "id": eid, "task": e.get("task", ""), "state": e.get("state", ""),
                "action": e.get("action", ""), "G": e.get("G"),
                "corrected": bool(e.get("corrected")),
                "agent": e.get("agent", ""), "ts": str(e.get("ts", ""))[:10],
                "session": summary,
            })
        return {"trunk": trunk, "category": category, "exps": out,
                "missing": len(ids) - len(out)}

    @router.post("/api/skills/distill")
    def skill_distill(body: DistillIn):
        result = engine_curation.distill(store, body.trunk, body.category,
                                         source="gui", force=body.force)
        if result.get("status") == "no_pending":
            raise HTTPException(
                status_code=409,
                detail="该类目暂无待总结的经验（要重建这份方法卡，请用「重建」）")
        # 无模型 → 结构化拒绝原样透出（总纲）：页面据此提示"去接模型"，
        # 并说明已保留上次内容；绝不产出任何方法正文。
        if _is_model_required(result):
            return result
        if result.get("status") == "empty_result":
            raise HTTPException(
                status_code=503,
                detail=str(result.get("message")
                           or "这次总结没拿到内容，已保住原方法卡不被覆盖——可以重试或换模型"))
        _raise_engine_status(result.get("status"))  # model_failed → 502
        return result

    # ---------- AI 重写（第二项蒸馏：对已总结内容不满意 → 接的模型再来一遍） ----------

    @router.post("/api/skills/rewrite-preview")
    def skill_rewrite_preview(body: DistillIn):
        """整方法 AI 重写预览：该类别全部经验（含已总结）重新总结，dry_run 不写盘。"""
        r = engine_curation.distill(store, body.trunk, body.category,
                                    source="manual", force=True, dry_run=True)
        if _is_model_required(r):
            return r
        _raise_engine_status(r["status"])
        if r["status"] == "no_pending":
            raise HTTPException(status_code=409, detail="该类别还没有经验")
        return {"md": r["md"], "old_md": r["old_md"], "count": r["count"]}

    @router.post("/api/skills/rewrite-apply")
    def skill_rewrite_apply(body: SkillRewriteApplyIn):
        """采纳整方法重写：预览 md 逐字落盘，旧版进 deprecated/ 快照可恢复。"""
        info = engine_curation.apply_rewritten_skill(
            store, body.trunk, body.category, body.md)
        if info is None:
            raise HTTPException(status_code=400, detail="重写内容为空")
        notify.push(store, "method_update",
                    f"{body.trunk}/{body.category} 方法已更新",
                    "你采纳了 AI 对这份方法的整文档重写，旧版已留快照可回退")
        return {"message": "已保存重写后的方法", **info}

    @router.put("/api/skills/{trunk}/{category}/rename")
    def skill_rename(trunk: str, category: str, body: RenameSkillIn):
        """R2 改名：显示名（说人话短名）和/或分类迁移。分类迁移移动方法文件、
        重写经验/session 的类别字段；已改写的注入条目自动失效（stale）。"""
        try:
            return store.rename_skill(trunk, category, body.name, body.category)
        except ValueError as exc:
            msg = str(exc)
            code = 409 if ("不能" in msg or "已存在" in msg) else 400
            raise HTTPException(status_code=code, detail=msg)

    @router.get("/api/skills/{trunk}/{category}/agents")
    def skill_agents(trunk: str, category: str):
        """R3：这个方法论从哪些 agent 跑出来的（该类别全部经验的 agent 分布）。"""
        agents: dict[str, dict] = {}
        n = 0
        latest = ""
        for e in store.iter_experiences(trunk=trunk, category=category,
                                        include_distilled=True):
            a = str(e.get("agent") or "未知")
            d = agents.setdefault(a, {"count": 0, "latest": ""})
            d["count"] += int(e.get("count", 1))  # 去重条目的出现次数累加
            ts = str(e.get("ts", ""))
            if ts > d["latest"]:
                d["latest"] = ts
            if ts > latest:
                latest = ts
            n += int(e.get("count", 1))
        items = [{"agent": k, **v} for k, v in agents.items()]
        items.sort(key=lambda x: -x["count"])
        return {"trunk": trunk, "category": category, "count": n,
                "latest": latest, "agents": items}

    return router
