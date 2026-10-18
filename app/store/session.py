"""`Store` 的「会话」域 mixin（sessions.jsonl 的读侧：搜索与工作区聚合）。

从 `store.py` 的 `class Store` 拆出的第七个域。只做不动语义的搬家，约定：

1. 方法体逐字搬移，签名与返回值一律不变；
2. 共享状态（`data_dir`、`_write_lock`、`_session_index`、`_iter_jsonl`、
   `_jsonl_signature`、`_workspace_cache`）留在 `Store` 主体，mixin 通过 `self`
   访问，**不复制状态**；
3. 需要模块级小工具时从 `._shared` 取，不 import `store.py`（避免循环导入）。

写侧（`record_session` / 索引构建 / 裁剪）本轮仍留在主体：它们围绕
`_session_index` 与写锁紧密协作，拆开容易让索引与文件内容的更新顺序出错——
这正是「强耦合就跳过」条款所指的情形。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("experientia.store.session")


class SessionMixin:
    """会话的检索视图：全文搜索 + 工作区聚合。"""

    def search_sessions(self, query: str, limit: int = 20,
                        embedder=None) -> list[dict]:
        """会话全文搜索（修复方案 -P1-2）：sessions.jsonl 事实源 +
        search.db FTS5 派生索引（sha 失配重建，异常 fail-open 返回空）。"""
        from .search_index import SearchIndex

        idx = getattr(self, "_searchidx", None)
        if idx is None:
            idx = SearchIndex(self.data_dir)
            self._searchidx = idx
        try:
            return idx.search(self.list_sessions(), query,
                              limit=limit, embedder=embedder)
        except Exception:
            logger.warning("会话搜索异常（返回空）", exc_info=True)
            return []

    def list_workspaces(self) -> list[dict]:
        """E-1 workspace↔session 索引：聚合 sessions.jsonl 的 project（cwd）字段。

        返回按最近活跃倒序的列表，每项含 project / count / first / last /
        agents / trunks / categories——供 Repo Memory（E-2）与按仓库维度检索/注入。
        结果带源文件签名缓存（与 growth_summary 同口径；写路径 mtime/size 变化即失效）。
        """
        sig = self._jsonl_signature(("sessions.jsonl",))
        key = ("workspaces", sig)
        cached = getattr(self, "_workspace_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]

        agg: dict[str, dict] = {}
        for s in self._iter_jsonl("sessions.jsonl"):
            proj = str(s.get("project") or "").strip()
            if not proj:
                continue
            a = agg.setdefault(proj, {
                "count": 0, "agents": set(), "trunks": set(),
                "categories": set(), "first": None, "last": None})
            a["count"] += 1
            a["agents"].add(str(s.get("agent") or "?"))
            trunk = str(s.get("trunk") or "其他")
            cat = str(s.get("category") or "未分类")
            if trunk:
                a["trunks"].add(trunk)
            if cat:
                a["categories"].add(cat)
            ts = str(s.get("started_at") or "")
            if ts:
                if a["first"] is None or ts < a["first"]:
                    a["first"] = ts
                if a["last"] is None or ts > a["last"]:
                    a["last"] = ts

        items = [{
            "project": p,
            "count": a["count"],
            "first": a["first"],
            "last": a["last"],
            "agents": sorted(a["agents"]),
            "trunks": sorted(a["trunks"]),
            "categories": sorted(a["categories"]),
        } for p, a in sorted(agg.items(),
                              key=lambda kv: (kv[1]["last"] or ""), reverse=True)]
        self._workspace_cache = (key, items)
        return items
