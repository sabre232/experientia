"""本地 API 的「导出」资源域（五粒度 + 全量打包）：`/api/export*`、`/api/exports/open`。

从 `create_local_app()` 拆出的第十四个资源域，范式同 models.py
（只依赖 store 与产品层、暴露 `build_xxx_router(store)` 工厂、不反向 import
`app.local_api`）。

安全约束（搬迁时原样保留）：`/api/exports/open` 只放行数据目录下 exports/ 与
`experientia-assets-*` 产物，**防任意路径打开**。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..distill import export as exporter
from ..store.store import Store


class ExportIn(BaseModel):
    granularity: str  # experiences / playbook / preferences / phase / growth / hooks
    trunk: str | None = None
    category: str | None = None
    since: str | None = None
    until: str | None = None
    days: int | None = None
    # R5 精选：experiences/hooks 按经验/hook id 勾选；playbook 多方法勾选
    ids: list[str] | None = None
    playbooks: list[dict] | None = None  # [{"trunk": ..., "category": ...}, ...]


class OpenIn(BaseModel):
    path: str


def build_export_router(store: Store) -> APIRouter:
    """挂载导出三个端点（五粒度导出、全量打包、打开导出产物）。"""
    router = APIRouter()

    # ---------- 导出（五粒度 + 全量打包） ----------

    @router.post("/api/export")
    def do_export(body: ExportIn):
        try:
            if body.granularity == "experiences":
                r = exporter.export_experiences(store, body.trunk, body.category,
                                                ids=body.ids)
            elif body.granularity == "playbook":
                if body.playbooks:
                    # R5 精选：多方法一次导出
                    pairs = [(p.get("trunk"), p.get("category"))
                             for p in body.playbooks
                             if p.get("trunk") and p.get("category")]
                    if not pairs:
                        raise HTTPException(
                            status_code=400, detail="请至少勾选一个方法")
                    r = exporter.export_playbooks(store, pairs)
                else:
                    if not body.trunk or not body.category:
                        raise HTTPException(
                            status_code=400, detail="playbook 导出需要 trunk+category")
                    r = exporter.export_playbook(store, body.trunk, body.category)
            elif body.granularity == "preferences":
                if not body.trunk:
                    raise HTTPException(status_code=400, detail="偏好导出需要 trunk")
                r = exporter.export_preferences(store, body.trunk)
            elif body.granularity == "phase":
                r = exporter.export_phase(store, body.trunk, body.category,
                                          body.since, body.until)
            elif body.granularity == "growth":
                r = exporter.export_growth(store, days=max(7, min(int(body.days or 30), 365)))
            elif body.granularity == "hooks":
                r = exporter.export_hooks(store, ids=body.ids)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="granularity 必须是 experiences/playbook/preferences/phase/growth/hooks")
        except HTTPException:
            raise
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        path = exporter.save_export(store, r["filename"], r["md"])
        return {"message": "已导出", "filename": r["filename"],
                "path": str(path), "md": r["md"]}

    @router.post("/api/export/all")
    def do_export_all():
        return exporter.export_all(store)

    @router.post("/api/exports/open")
    def open_export(body: OpenIn):
        """打开导出文件 / 全量包目录（只放行数据目录 exports/ 与 experientia-assets-* 产物，防任意路径）。"""
        p = Path(body.path).resolve()
        exports_root = (store.data_dir / exporter.EXPORTS_DIRNAME).resolve()
        in_exports = p == exports_root or exports_root in p.parents
        is_pkg = (p.parent == store.data_dir.parent.resolve()
                  and p.name.startswith("experientia-assets-"))
        if not (in_exports or is_pkg) or not p.exists():
            raise HTTPException(status_code=400, detail="路径不在允许的导出目录内")
        try:
            if os.name == "nt":
                os.startfile(p)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"打开失败：{exc}")
        return {"message": "已打开文件夹"}

    return router
