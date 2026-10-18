"""本地 API 的「设置与数据主权」资源域：`/api/config`、`/api/wipe`。

从 `create_local_app()` 拆出的第十二个资源域，范式同 models.py
（只依赖 store 与产品层、暴露 `build_xxx_router(store)` 工厂、不反向 import
`app.local_api`）。

本域用到的 `_mask_config`（把 api_key 打码后再出网）原先是 `local_api` 的模块级
私有助手，按"跨域共用件放 `_shared.py`"的约定一并搬来——`/api/status` 之后若也
搬出，同样从 `._shared` 取即可。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..store.store import Store
from ._shared import _mask_config


def build_settings_router(store: Store) -> APIRouter:
    """挂载设置读写 + 一键彻底删除，共 3 个端点。"""
    router = APIRouter()

    # ---------- 配置 ----------

    @router.get("/api/config")
    def config_get():
        return _mask_config(store.load_config())

    @router.put("/api/config")
    def config_update(body: dict):
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="body 必须是 JSON 对象")
        # H-N1: 字段白名单——只允许写入已知的 UI 偏好/用户配置键，
        # 拒绝 models/default_model/distill_model 等系统配置键
        _ALLOWED_CONFIG_KEYS = {
            "locale", "onboarded", "ui_theme",
            "autostart",
            "notify", "notify_muted",
            "negation_words", "seed_keywords",
            "hook_stale_days", "hooks_agents_expanded",
            "capture", "port",
        }
        denied = [k for k in body if k not in _ALLOWED_CONFIG_KEYS]
        if denied:
            raise HTTPException(
                status_code=400,
                detail=f"不允许修改的配置键：{', '.join(sorted(denied))}",
            )
        # 结构校验：为关键字段增加类型约束，防止非法配置导致隐性问题
        _config_validators = {
            "notify": (bool, None),
            "notify_muted": (bool, None),
            "autostart": (bool, None),
            "onboarded": (bool, None),
            "capture": (dict, None),
            "negation_words": (list, None),
            "seed_keywords": (dict, None),
            "hook_stale_days": ((int, float), None),
            "hooks_agents_expanded": (list, None),
            "locale": (str, None),
            "ui_theme": (str, None),
            "port": ((int, float), None),
        }
        for k, v in body.items():
            expected = _config_validators.get(k)
            if expected is None:
                continue
            if v is not None and not isinstance(v, expected):
                raise HTTPException(
                    status_code=400,
                    detail=f"配置项「{k}」类型不合法，期望 {expected}，实际 {type(v).__name__}",
                )
        # 读-改-写走 mutate_config（持写锁）——直调
        # load/save 会与 llm 熔断记账 / notify 状态写互相覆盖（整文件原子替换，
        # 后写者抹掉先写者的字段：熔断计数归零、通知状态回退）。
        def _apply(config: dict) -> dict:
            config.update(body)
            return config

        return _mask_config(store.mutate_config(_apply))

    @router.post("/api/wipe")
    def wipe_all(body: dict = None):
        """一键彻底删除：清空数据目录全部内容并重建初始布局。

        二次防护：body 必须带确认口令（GUI 确认弹窗要求用户手动输入）。"""
        token = str((body or {}).get("confirm", "")).strip()
        if token != "WIPE":
            raise HTTPException(status_code=400, detail="需要确认口令：请在确认弹窗输入 WIPE")
        leftovers = store.wipe_all()
        return {"message": "已彻底删除全部数据", "leftovers": leftovers}

    return router
