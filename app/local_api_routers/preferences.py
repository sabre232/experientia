"""本地 API 的「我的偏好」资源域：`/api/preferences/*`。

从 `create_local_app()` 拆出的第四个资源域，范式同 models.py
（只依赖 store 与产品层、暴露 `build_xxx_router(store)` 工厂、不反向 import
`app.local_api`）。`_raise_engine_status` 是跨域共用件，从 `._shared` 引入。
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import notify
from ..distill import engine_curation, llm
from ..distill import skill as skillgen
from ..proxy import inject
from ..store.store import Store
from ._shared import _raise_engine_status


class PreferencesIn(BaseModel):
    md: str


def _mtime_iso(path: Path) -> str:
    """文件最后修改时刻 → ISO8601（口径同 skillgen.now_iso，带时区偏移）。

    溯源条的"内容为 X 生成"要的是内容本身的落地时刻，作者可能已离线很久。
    """
    try:
        return _dt.datetime.fromtimestamp(
            path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        return ""


def build_preferences_router(store: Store) -> APIRouter:
    """挂载 /api/preferences/* 三个端点（画像清单、保存、重新归纳）。"""
    router = APIRouter()

    @router.get("/api/preferences")
    def preferences_list():
        # 内容溯源（总纲）：偏好画像由模型从纠正里归纳，没接模型时内容不再
        # 更新 → 标 "none"，展示层据此挂溯源条（口径同 /api/growth）。
        # generated_at 取偏好文件的最后写入时刻、不是本次请求时刻：读条的人要
        # 知道"手上这份内容什么时候的"，取 now 会让条恒显示今天、失去信息量。
        src = (skillgen.CONTENT_SOURCE_MODEL if llm.model_available(store)
               else skillgen.CONTENT_SOURCE_NONE)
        out = []
        for trunk in store.list_preference_trunks():
            md = store.read_preferences(trunk) or ""
            bullets = [ln.strip() for ln in md.splitlines() if ln.strip().startswith("-")]
            tokens = inject.estimate_tokens("\n".join(bullets))
            out.append({
                "trunk": trunk, "md": md,
                "bullets": bullets,
                # R6：旧中文键（用户确认）归一化后仍能识别为 [UserConfirmed]
                "confirmed": [ln for ln in bullets
                              if inject.USER_CONFIRM_MARK in inject.normalize_marks(ln)],
                "tokens": tokens,
                "over_budget": tokens > engine_curation.PREFERENCE_BUDGET_TOKENS,
                "content_source": src,
                "generated_at": _mtime_iso(store.preferences_path(trunk)),
            })
        return {"items": out}

    @router.post("/api/preferences/{trunk}")
    def preferences_save(trunk: str, body: PreferencesIn):
        store.write_preferences(trunk, body.md)
        store.append_event("pref-edit", f"用户编辑偏好画像 {trunk}", trunk=trunk)
        return {"message": "已保存", "trunk": trunk}

    @router.post("/api/preferences/{trunk}/reinduct")
    def preferences_reinduct(trunk: str):
        result = engine_curation.reinduct_preferences(store, trunk)
        _raise_engine_status(result.get("status"))
        if result.get("status") == "no_data":
            raise HTTPException(status_code=409, detail="该类别还没有可归纳的纠正/低 G 经验")
        notify.push(store, "method_update", f"「{trunk}」偏好画像已重新归纳",
                    f"保留 {result.get('confirmed', 0)} 条用户确认 / 新归纳 {result.get('inducted', 0)} 条")
        return result

    return router
