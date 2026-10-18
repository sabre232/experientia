"""本地 API 各资源域共用的小工具（M5 拆分的**前置改动**）。

背景：`create_local_app()` 原本是个 1652 行的大闭包，里面有几个被**多个资源域**
共用的私有助手。按拆分范式，域模块不能反向 import `app.local_api`（会与挂载处
形成循环导入），所以这些共用件必须先落到这里，再由 `local_api` 与各域模块共同
import——否则后面每搬一个域就得各抄一份。

只放"确属跨域共用"的东西；单个域私有的助手仍随各自域模块走。
"""

from __future__ import annotations

from fastapi import HTTPException

# 引擎 result.status → (HTTP 码, 用户可见文案)：跨端点逐字一致的部分收口成表，
# 避免同一句提示散抄多处（改文案要挨个找）。各端点特有文案（no_pending/empty_result/
# not_found 因场景语义不同）仍就地显式，不并入本表，防止把刻意差异误抹平。
_ENGINE_STATUS_ERRORS = {
    "no_model": (409, "尚未接入模型，请先在模型页配置"),
    "model_failed": (502, "模型调用失败，请检查模型连接后重试"),
}


def _raise_engine_status(status: str) -> None:
    """命中收口表里的引擎状态即抛对应 HTTPException；未命中静默放行给调用方续处理。"""
    err = _ENGINE_STATUS_ERRORS.get(status)
    if err:
        raise HTTPException(status_code=err[0], detail=err[1])


# 归纳层动作无模型的用户可见文案（总纲的 model_required 结构用；
# 与 _ENGINE_STATUS_ERRORS 同处集中管理，改文案只动这里）。
# 首句与 GUI 目录里的既有 key「未接入模型，无法完成这一步」同口径，
# 后接一步引导；不新造近似句，避免 7 语言翻译漂移。
MODEL_REQUIRED_REWRITE = ("未接入模型，无法完成这一步。"
                          "去「接入」页接一个本地模型或 API 后再试。")


def _mask_config(config: dict) -> dict:
    """配置出网前把 api_key / api_key_enc 打码（跨域共用：settings 与 status 都用）。"""
    masked = dict(config)
    routes = masked.get("models")
    if isinstance(routes, dict):
        masked["models"] = {
            name: {**r,
                   "api_key": "***" if r.get("api_key") else None,
                   "api_key_enc": "***" if r.get("api_key_enc") else None}
            for name, r in routes.items()
        }
    return masked


def _is_model_required(result) -> bool:
    """引擎回了"没接模型"的结构化拒绝（总纲）。

    这类拒绝**不是错误**：原样 200 返回给调用方，由页面提示"去接模型"并说明
    已保留上次内容（抛 4xx 会让调用方走错误分支，反而丢掉 message/kept_previous）。
    """
    return isinstance(result, dict) and result.get("status") == "model_required"
