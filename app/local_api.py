"""本地 API（GUI 外壳用，引擎/外壳分层）。

GUI（PySide6）不直接 import 引擎，只调这组 /api/* 端点（独立端口 8101，
与 8100 模型转发代理分离，避免路径混淆）。端点：

  GET    /api/status                     运行状态 / 已探测 agent / 统计 / 黄标
  GET    /api/models                     模型路由 + 默认/蒸馏标记
  POST   /api/models                     添加路由（key → 系统钥匙串）
  POST   /api/models/{name}/set-default  设默认模型（代理主路由）
  POST   /api/models/{name}/set-distill  设蒸馏/复盘专用模型（下拉）
  DELETE /api/models/{name}              删除路由（连带钥匙串 key）
  GET    /api/experiences                经验列表（trunk/category/q 过滤）
  POST   /api/experiences/{id}/feedback  L1 反馈 valid|corrected（用户唯一手动反馈）
  POST   /api/experiences/{id}/edit      纠正 = 直接改内容（；旧值存 previous 快照）
  GET    /api/skills                     playbook 清单
  GET    /api/skills/versions/{name}     生成的 Skill 版本清单（新在前）
  GET    /api/skills/versions/{name}/{n} 某版 SKILL.md 正文
  GET    /api/skills/versions/{name}/diff/{old}/{new}  两版 unified diff
  POST   /api/skills/save                保存一份 SKILL.md 为新版本（活资产）
  GET    /api/skills/{trunk}/{category}  playbook 正文
  POST   /api/skills/distill             触发蒸馏 {trunk, category}
  POST   /api/export                     五粒度导出→ 落 exports/ 返回路径
  POST   /api/export/all                 全量打包（skills/preferences/rules/exports/… + MANIFEST）
  POST   /api/exports/open               打开导出目录（白名单校验）
  GET    /api/config                     配置（明文 api_key 掩码）
  PUT    /api/config                     局部合并更新（GUI 设置页）
  POST   /api/hooks/session-start        Claude Code hook：SessionStart（实时 session + 即时归档）
  POST   /api/hooks/user-prompt-submit   Claude Code hook：UserPromptSubmit（additionalContext 注入）
  POST   /api/hooks/post-tool-use        Claude Code hook：PostToolUse（工具完成，生效验证）
  POST   /api/hooks/stop                 Claude Code hook：Stop（轮毕后台复盘写经验，fail-open）
  GET    /api/hooks/config               当前 settings.json hook 配置状态
  POST   /api/hooks/plugin/generate      生成 Claude 官方插件包（.claude-plugin + hooks/http，阶段 C）
  POST   /api/hooks/apply                一键写入 ~/.claude/settings.json（幂等 + 备份）
  POST   /api/hooks/remove               移除 hook 配置条目
"""

from __future__ import annotations

import datetime as _dt
import hmac
import logging
import os
import re as _re
import subprocess
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .store.store import Store

logger = logging.getLogger("experientia.local_api")

# 版本号唯一来源（见 app/version.py）；这里保持 VERSION 名导出以兼容旧 import
from .version import VERSION  # noqa: E402

# ---------- 8101 鉴权（本机任意进程可访问 → 全端点 Bearer token） ----------
# 实现拆到轻量 app/token_util.py（仅标准库 + 惰性 keyring）——main 冷启动
# 主线程取 token 不再连带 import 本模块的整棵 FastAPI 服务树（实测省 ~2s）。

from .token_util import ensure_api_token

# 豁免：status（GUI 首连/健康探测）+ hooks 数据通道（外部 agent 的 curl，
# fail-open 语义，无法携带 token——见 hook_channel 设计）
# status：GUI 首连/健康探测；精确 /api/probe：skill 的 curl 无法携带 token（只提交报告）。
# /api/probe/apply 与 /api/probe/{ide,hermes}/* 等写操作保持 token 保护（由 GUI 按钮触发）。
# hooks 只豁免只读状态 + 事件上报端点；admin/*、apply、remove、plugin/generate
# 等写操作一律恢复 token 保护（安全：/api/hooks/ 前缀豁免曾把
# 整个 hook 管理面暴露为无鉴权）。
_AUTH_EXEMPT_PATHS = {
    "/api/status",
    "/api/probe",
    # hooks 只读状态（GUI 区分「已写入配置 / 已生效」）
    "/api/hooks/config",
    # hooks 数据通道：外部 agent curl 事件上报（fail-open）
    "/api/hooks/session-start",
    "/api/hooks/user-prompt-submit",
    "/api/hooks/post-tool-use",
    "/api/hooks/stop",
    "/api/hooks/hermes-event",
    "/api/hooks/cursor-event",
    "/api/hooks/windsurf-event",
}


def _token_matches(header_value: str, expected: str) -> bool:
    got = header_value.strip()
    if got.lower().startswith("bearer "):
        got = got[7:].strip()
    # hmac.compare_digest 对含非 ASCII 的 str 抛 TypeError
    # （本机进程发畸形 Authorization 头时中间件 500 而非 401）；编码为 bytes
    # 后比较，时序安全语义不变。
    return bool(got) and hmac.compare_digest(got.encode(), expected.encode())









# RouteIn / RuleIn / TemplateImportIn 已随各自资源域搬到
# app/local_api_routers/{models,rules}.py（M5 拆分 create_local_app）。
# 这里保留同名再导出，兼容既有 `from app.local_api import ...`。
from .local_api_routers.hooks_admin import (  # noqa: E402
    build_hooks_admin_router)
from .local_api_routers.ingest import build_ingest_router  # noqa: E402
from .local_api_routers.injection import (  # noqa: E402,F401
    OptimizeIn, OverrideIn, RefutationRestoreIn, build_injection_router)
from .local_api_routers.insights import (SkillGenIn,  # noqa: E402,F401
                                         build_insights_router)
from .local_api_routers.intentions import (  # noqa: E402,F401
    build_intentions_router)
from .local_api_routers.capture import (CaptureIn,  # noqa: E402,F401
                                        build_capture_router)
from .local_api_routers.app_ops import (  # noqa: E402,F401
    AutoStartIn, DataDirMigrateIn, ReadIn, build_app_ops_router)
from .local_api_routers.export import (ExportIn,  # noqa: E402,F401
                                       OpenIn, build_export_router)
from .local_api_routers.experiences import (  # noqa: E402,F401
    AiApplyExpIn, AiPolishExpIn, CategorizeIn, ExperienceEditIn, FeedbackIn,
    build_experiences_router)
from .local_api_routers.failure_modes import (  # noqa: E402,F401
    AiApplyFailureIn, AiPolishFailureIn, RejectIn, build_failure_modes_router)
from .local_api_routers.models import (RouteIn,  # noqa: E402,F401
                                       build_models_router)
from .local_api_routers.preferences import (  # noqa: E402,F401
    PreferencesIn, build_preferences_router)
from .local_api_routers.query import build_query_router  # noqa: E402
from .local_api_routers.rules import (RuleIn,  # noqa: E402,F401
                                      TemplateImportIn,  # noqa: E402,F401
                                      build_rules_router)
from .local_api_routers.settings import build_settings_router  # noqa: E402
from .local_api_routers.status import build_status_router  # noqa: E402
from .local_api_routers.skills import (DistillIn,  # noqa: E402,F401
                                       RenameSkillIn,  # noqa: E402,F401
                                       SkillRewriteApplyIn,  # noqa: E402,F401
                                       SkillSaveIn,  # noqa: E402,F401
                                       build_skills_router)





# _aggregate_capture_hits 已随「采集」域搬到 app/local_api_routers/capture.py
# ——全库仅该域使用，这里不留副本。

# 规则域的私有助手（_stale_days / _sum_rule_days / _rule_hit_view /
# _rule_priority / _contradicts / _conflict_rule_ids）已随「规则与模板」域搬到
# app/local_api_routers/rules.py——全库仅该域使用，这里不留副本。
# （原列表里的 _parse_iso 已由 app/time_util.parse_ts 统一取代，/15
# 全仓 19 处 fromisoformat 收口时删除，此处同步更正，免得按注释去找一个不存在的函数。）

# 引擎 result.status → (HTTP 码, 用户可见文案)：跨端点逐字一致的部分收口成表，
# 避免同一句提示散抄多处（改文案要挨个找）。各端点特有文案（no_pending/empty_result/
# not_found 因场景语义不同）仍就地显式，不并入本表，防止把刻意差异误抹平。
# 跨域共用件（_ENGINE_STATUS_ERRORS / _raise_engine_status /
# MODEL_REQUIRED_REWRITE / _is_model_required）已抽到
# app/local_api_routers/_shared.py：多个资源域都要用，
# 而域模块按范式不能反向 import 本模块，故集中放置后各方共同 import。
from .local_api_routers._shared import (  # noqa: E402,F401
    MODEL_REQUIRED_REWRITE, _ENGINE_STATUS_ERRORS, _is_model_required,
    _mask_config, _raise_engine_status)


def create_local_app(store: Store, api_token: str | None = None,
                     clock=None) -> FastAPI:
    """clock：限流窗口时间源，缺省 time.time。测试注入假表消除
    "连发 121 次期间真实时钟走过窗口边界" 的时序抖动（偶发假红，非逻辑错）。"""
    _clock = clock or time.time
    app = FastAPI(title="Experientia Local API", version=VERSION)
    token = api_token or ensure_api_token(store.data_dir)
    # 事件通道防伪令牌：/api/hooks/*-event 无 Bearer 鉴权，
    # 以 ?key= 查询参数校验此低权限独立令牌——泄漏只影响 fail-open 的事件通道，
    # 不交出整个本地 API。缺令牌放行并限频告警（旧安装未重贴 hook 前不断捕获）。
    _hook_event_token = store.hook_ingest_token()
    _HOOK_KEY_WARN_INTERVAL = 60.0
    _hook_key_warn: dict[str, float] = {}

    # M-N5: 简单进程内速率限制——每端点每秒最多 30 次请求
    _rate_limit: dict[str, tuple[int, float]] = {}
    _RATE_LIMIT_MAX = 30
    # 限流按通道隔离。无鉴权 hook 数据通道与 GUI 共享 30/s
    # 时，GUI 密集轮询会把 hook 事件挤到 429，fail-open 语义失效（hook 收到
    # 非 2xx 不再"无感"）。hook 事件端点单独一份更宽的配额，429 附
    # Retry-After 提示客户端退避；其余路径（GUI 用）维持 30/s 不变。
    _HOOK_RATE_LIMIT_MAX = 120
    _RATE_LIMIT_WINDOW = 1.0
    # hook 数据通道 = _AUTH_EXEMPT_PATHS 里的 /api/hooks/* 事件端点
    # （api/hooks/config 是 GUI 读的只读状态端点，不属事件通道）
    _hook_data_paths = {
        p for p in _AUTH_EXEMPT_PATHS
        if p.startswith("/api/hooks/") and p != "/api/hooks/config"}

    @app.middleware("http")
    async def _auth(request, call_next):
        path = request.url.path
        if path in _hook_data_paths:
            # 事件通道防伪：带 key 且正确 → 放行；带 key 但错误 → 401
            # （挡下本机伪造/跨安装令牌）；缺 key → 放行并限频留痕（fail-open：
            # 未重贴 hook 的旧安装仍照常上报，不静默断捕获）。
            key = request.query_params.get("key")
            if key is None:
                now = time.time()
                if now - _hook_key_warn.get(path, 0.0) >= _HOOK_KEY_WARN_INTERVAL:
                    _hook_key_warn[path] = now
                    logger.warning("hook 事件 %s 未带防伪令牌：放行并记一次"
                                   "（未重贴的旧 hook 或本机伪造），GUI 重新接入后消除",
                                   path)
            elif not hmac.compare_digest(str(key), _hook_event_token):
                return JSONResponse(status_code=401,
                                    content={"detail": "invalid hook key"})
            return await call_next(request)
        if path in _AUTH_EXEMPT_PATHS:
            return await call_next(request)
        if not _token_matches(request.headers.get("authorization", ""), token):
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
        return await call_next(request)

    @app.middleware("http")
    async def _rate_limit_middleware(request, call_next):
        path = request.url.path
        now = _clock()
        limit = _HOOK_RATE_LIMIT_MAX if path in _hook_data_paths else _RATE_LIMIT_MAX
        count, window_start = _rate_limit.get(path, (0, now))
        if now - window_start > _RATE_LIMIT_WINDOW:
            _rate_limit[path] = (1, now)
        else:
            count += 1
            _rate_limit[path] = (count, window_start)
            if count > limit:
                # hook 通道 429 带 Retry-After（客户端按秒退避重试，
                # 而不是把上游错误当失败向上传播）；其余通道维持原样
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后重试"},
                    headers={"Retry-After": "1"} if path in _hook_data_paths else None)
        # 定期清理过期条目，防止字典无限增长
        if len(_rate_limit) > 100:
            stale = [k for k, (_, ws) in _rate_limit.items() if now - ws > _RATE_LIMIT_WINDOW * 2]
            for k in stale:
                del _rate_limit[k]
        return await call_next(request)

    @app.middleware("http")
    async def _timing(request, call_next):
        """：/api/* 服务端耗时打点——>200ms 记 WARNING（慢接口点名），
        其余 DEBUG。只读 method/path，不碰 body、不改响应体。"""
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        t0 = time.perf_counter()
        response = await call_next(request)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if dt_ms > 200.0:
            logger.warning("[api] %s %s %.1f ms", request.method, path, dt_ms)
        else:
            logger.debug("[api] %s %s %.1f ms", request.method, path, dt_ms)
        return response

    # ---------- 状态 ----------

    # ---------- 状态 ----------
    # `/api/status` 已搬到 app/local_api_routers/status.py，
    # 是拆分的最后一个域。它需要校验 Bearer 才能回 data_dir，故工厂额外收
    # token 与 _token_matches（与鉴权中间件同源），不反向 import 本模块。
    app.include_router(build_status_router(store, token, _token_matches))

    # ---------- 模型路由 ----------

    # ---------- 模型管理 ----------
    # 这七个端点已搬到 app/local_api_routers/models.py，
    # 是 create_local_app 拆分出的第一个资源域（范式见该模块 docstring）。
    app.include_router(build_models_router(store))

    # ---------- 采集状态（W1-06：命中流水 + 24h 计数 + 黄标） ----------

    # ---------- 采集状态与管理 ----------
    # 这三个端点连同 CaptureIn 与 _aggregate_capture_hits
    # 已搬到 app/local_api_routers/capture.py（YELLOW_FLAG_THRESHOLD 仍从
    # .capture.scan 引入，与 /api/status 同源）。
    app.include_router(build_capture_router(store))

    # ---------- 经验库 ----------

    # ---------- 经验库 ----------
    # 这十个端点连同 FeedbackIn / ExperienceEditIn /
    # CategorizeIn / AiPolishExpIn / AiApplyExpIn 已搬到
    # app/local_api_routers/experiences.py。
    app.include_router(build_experiences_router(store))

    # ---------- 我的方法 ----------

    # ---------- 方法与 Skill ----------
    # 这十三个端点连同 DistillIn / RenameSkillIn /
    # SkillRewriteApplyIn / SkillSaveIn 与 _skills_with_provenance 已搬到
    # app/local_api_routers/skills.py（注意 versions/* 必须先于
    # /api/skills/{trunk}/{category} 声明，搬迁保持原顺序）。
    app.include_router(build_skills_router(store))

    # ---------- 配置 ----------

    # ---------- 设置与数据主权 ----------
    # `/api/config`（读 + 写）与 `/api/wipe` 共三个端点已搬到
    # app/local_api_routers/settings.py；`_mask_config` 随之抽到 _shared.py
    # （status 与 config 都要用）。
    app.include_router(build_settings_router(store))

    # ---------- 失败模式 ----------

    # ---------- 失败模式（三态） ----------
    # 这五个端点连同 RejectIn / AiPolishFailureIn /
    # AiApplyFailureIn 已搬到 app/local_api_routers/failure_modes.py。
    app.include_router(build_failure_modes_router(store))

    # ---------- 我的偏好 ----------

    # ---------- 我的偏好 ----------
    # 这三个端点连同 PreferencesIn 与本域私有助手 _mtime_iso
    # 已搬到 app/local_api_routers/preferences.py。
    app.include_router(build_preferences_router(store))

    # ---------- 成长 ----------

    # ---------- 成长与查询 ----------
    # 这九个端点（growth / weekly-report / content-governance /
    # workspaces / ledger / rule-cards / pending-fragments / session-view / search）
    # 已搬到 app/local_api_routers/query.py。
    app.include_router(build_query_router(store))

    # ---------- 工作流洞察（W4-04：建议卡 + 三选一） ----------

    # ---------- 工作流洞察 + 学习历程 + 整理 Skill ----------
    # insights 2 + changelog 2 + skills/generate 1 共五个端点
    # 已搬到 app/local_api_routers/insights.py。
    app.include_router(build_insights_router(store))

    # ---------- 规则与模板 ----------

    # ---------- 规则与模板 ----------
    # 这八个端点连同其私有助手已搬到
    # app/local_api_routers/rules.py（拆分出的第二个资源域）。
    app.include_router(build_rules_router(store))

    # ---------- L6 前瞻意图 + 六层存量（P1-1/P1-2） ----------
    # 意图由 System2 沉淀、MCP 胶囊在消费，但用户此前既看不见也忽略不了——
    # 这个域补上"能看、能忽略、能看记忆构成"的出口。
    app.include_router(build_intentions_router(store))

    # ---------- 模型会看到什么（覆盖层） ----------

    # ---------- 注入预览+ 回炉治理（第⑤环） ----------
    # 这七个端点连同 OverrideIn / OptimizeIn /
    # RefutationRestoreIn 已搬到 app/local_api_routers/injection.py。
    app.include_router(build_injection_router(store))

    # ---------- 整理 Skill ----------

    # ---------- 导出（五粒度 + 全量打包） ----------

    # ---------- 导出 ----------
    # 这三个端点连同 ExportIn / OpenIn 已搬到
    # app/local_api_routers/export.py（安全约束原样保留：只放行 exports/ 与
    # experientia-assets-* 产物）。
    app.include_router(build_export_router(store))

    # ---------- 开机自启（第 3 点，三平台注册） ----------

    # ---------- Hook 通道（通道 3，Claude Code 首发） ----------
    # 供 Claude Code 的 SessionStart / UserPromptSubmit / PostToolUse / Stop
    # hook（curl 管道）调用。fail-open：任何异常都返回空 dict（curl 退出码 0），
    # 绝不阻塞用户的 agent；Stop 的复盘写经验在独立 worker 里跑，不等 LLM。

    # ---------- 接入与上报（hook 事件通道 + probe 自报 + 草稿） ----------
    # 这 20 个端点已搬到 app/local_api_routers/ingest.py。
    # 该域需要 hook 事件通道防伪令牌，故工厂多一个参数由这里传入——域模块
    # 按范式不反向 import 本模块（会循环导入）。
    app.include_router(build_ingest_router(store, _hook_event_token))

    # ---------- Skill 自报（总方案 S2：扫不到的 agent 兜底入口） ----------
    # POST /api/probe        外部 agent 的 probe.py 直推报告（首选，用户无感）
    # POST /api/probe/apply  connect 页粘贴上报码后本地吸收（人工介质兜底）

    # ---------- 经验上报草稿（S5 ：无 LLM 时的手动放行去向） ----------

    # ---------- Hook 管理 ----------
    # 这十五个端点已搬到 app/local_api_routers/hooks_admin.py。
    # 该域同样需要防伪令牌，故工厂收 hook_event_token 参数（不反向 import 本模块）。
    # 注意：overview/explain 必须先于 {agent} 定义——FastAPI 按定义顺序匹配，
    # 否则 "overview" 会被 {agent} 吞掉当 agent 名（GUI 总览会一直 400）。
    app.include_router(build_hooks_admin_router(store, _hook_event_token))

    # ---------- 通知中心 ----------

    # ---------- 应用运维 + 通知中心 ----------
    # autostart / data-dir/migrate / app/relaunch /
    # notifications 2 共五个端点连同 AutoStartIn / DataDirMigrateIn / ReadIn
    # 与 _autostart_enabled 已搬到 app/local_api_routers/app_ops.py。
    app.include_router(build_app_ops_router(store))

    return app
