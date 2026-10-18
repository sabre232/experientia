"""本地 API 的「状态」资源域：`/api/status`（唯一一个免鉴权端点）。

从 `create_local_app()` 拆出的第十六个资源域，也是最后一个。
范式同 models.py，但**本域有一个额外依赖**：`data_dir` 只回给带有效 Bearer token
的调用方，需要拿到本 app 实例的 `token`，故工厂多一个参数（与 `ingest.py` /
`hooks_admin.py` 收 `hook_event_token` 同款做法），而不是反向 import `local_api`。

安全约束（搬迁时原样保留）：`/api/status` 整体免鉴权，但 **`data_dir` 绝对路径
只回给带有效 token 的调用方**——未鉴权的本机进程不再白拿数据目录路径
（M-N3 +）。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..capture.scan import YELLOW_FLAG_THRESHOLD
from ..store.store import Store
from ..version import VERSION


def build_status_router(store: Store, token: str,
                        token_matches) -> APIRouter:
    """挂载 /api/status 与 /api/agents。

    token_matches：校验 Bearer 头的函数（由 create_local_app 传入，与鉴权中间件同源）。
    """
    router = APIRouter()

    @router.get("/api/status")
    def status(lite: int = 0, request: Request = None):
        """lite=1：探活口径（daemon.probe_local_api）——只回探活需要的字段。

        **任何情况下都不触发 registry.detect()**。agent 列表改读落盘快照
        （agents_snapshot.json，由扫描循环/预热线程覆盖写入）——旧实现每次
        刷新都同步全量探测（冷 13.6s），被首页/设置/接入/模型/引导页每页都打，
        与 GUI 同抢 GIL → "每一页都慢"。快照缺失 → 空 dict（UI 走空态）。"""
        config = store.load_config()
        if lite:
            agents = {}
            agents_at = ""
        else:
            snap = store.load_agents_snapshot()
            agents = snap.get("agents") or {}
            agents_at = snap.get("at") or ""
        out = {
            "version": VERSION,
            "proxy_port": int(config.get("port", 8100)),
            "proxy_base_url": f"http://127.0.0.1:{int(config.get('port', 8100))}",
            "agents": agents,
            "agents_at": agents_at,
            "stats": store.stats(),
            "yellow_flags": store.load_capture_failures(),
            "yellow_flag_threshold": YELLOW_FLAG_THRESHOLD,
            "default_model": config.get("default_model"),
            "distill_model": config.get("distill_model"),
        }
        # M-N3 + ：data_dir 绝对路径只回给带有效 Bearer token 的
        # 调用方（GUI 与本地 daemon 探活都带 token）；/api/status 整体仍免鉴权，
        # 但未鉴权的本机进程不再白拿数据目录路径。
        if (request is not None and token_matches(
                request.headers.get("authorization", ""), token)):
            out["data_dir"] = str(store.data_dir)
            # 数据目录指针失效回退默认位置（GUI 提示用）
            out["data_dir_fallback"] = bool(getattr(store, "data_dir_fallback", False))
        return out

    @router.get("/api/agents")
    def agents():
        """探测结果快照（agent → 会话引用数）+ 采集时间。

        与 /api/status 同源：接口层**不触发** detect()，只读落盘快照；真正的
        探测由扫描循环 / 启动预热线程在后台做。需要 token（不在免鉴权清单）。"""
        snap = store.load_agents_snapshot()
        return {"agents": snap.get("agents") or {}, "at": snap.get("at") or ""}

    return router
