"""Hermes gateway 事件铃响（总方案 S3：B 档"代码型 hook"注入，Hermes 首发）。

Hermes（gateway 架构）的 hook 与 Claude/Cursor 的"shell 命令 + JSON"不同，是
**代码型目录**（实测口径，gateway/hooks.py）：
  <home>/hooks/<name>/
    ├── HOOK.yaml     # name + events（gateway 启动 discover_and_load 扫描加载）
    └── handler.py    # handle(event_type, context)（同步/异步均可，错误被捕获不阻塞）

本模块职责：
1. write_hook / remove_hook：生成"铃响" hook 到 Hermes hooks 目录（幂等 / 可卸载）；
2. 铃响语义：只在 agent:end / session:end 时向 Experientia 8101 报一声
   （携带 session_id），Experientia 侧只记 observed；**全文仍由文件通道
   scan_loop 读 state.db**——hook 上下文 message/response 被 Hermes 截断 500 字，
   传正文不如不传（总方案  Hermes 行"B hook 铃响"）。
3. handle_hermes_event：8101 端点收到铃响后的处理（fail-open）。

生效方式：gateway 启动时一次性加载 → 写入后需重启 Hermes gateway
（`hermes gateway restart`）才生效；我们提示用户，不静默重启。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .adapters.hermes import _home as hermes_home

logger = logging.getLogger("experientia.capture.hermes_hook")

HOOK_NAME = "experientia-event"
EVENTS = ("agent:end", "session:end")
HOOK_URL = "http://127.0.0.1:8101/api/hooks/hermes-event"


def hermes_event_url(key: str | None = None, base: str = HOOK_URL) -> str:
    """铃响上报 URL；key（事件通道防伪令牌，M10）以 ?key= 查询参数附加。"""
    if not key:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}key={key}"


HOOK_YAML = """\
name: {name}
description: 通知 Experientia 本轮/会话已结束（铃响）；Experientia 自行读取本地会话复盘
events:
  - agent:end
  - session:end
"""

# 注意：此 handler 跑在 Hermes gateway 进程内——必须零阻塞、失败无感：
# 后台线程 POST（daemon），绝不影响 agent 主流程；任何异常吞掉。
# 吞异常改为 logger.debug 留痕（落 Hermes 自己的日志；
# 本进程没有 experientia logger，用独立命名，fail-open 语义不变）。
# URL 占位符从 %s 改为 __EXPERIENTIA_URL__ 字面量、
# 生成时用 str.replace 填入——% 格式化遇到 URL 里的 % 会 ValueError 中断写 hook；
# handler 内 logger 的 %s 不再需要 %% 转义（不走 % 格式化了）。
_HANDLER_TEMPLATE = '''\
# -*- coding: utf-8 -*-
# 由 Experientia 生成：Hermes gateway 事件铃响（agent:end / session:end → 8101）。
# 只读只报，不传正文；失败记 debug 日志后吞掉。卸载：删除本目录后重启 gateway。
import json
import logging
import os
import threading
import urllib.request

_log = logging.getLogger("experientia.hermes_hook.handler")


def handle(event_type, context):
    if event_type not in ("agent:end", "session:end"):
        return None
    ctx = context or {}
    payload = {"event": event_type, "session_id": ctx.get("session_id") or "",
               "platform": ctx.get("platform") or "", "at": ctx.get("timestamp") or ""}
    url = os.environ.get("EXPERIENTIA_HERMES_URL", "__EXPERIENTIA_URL__")
    threading.Thread(target=_post, args=(url, payload), daemon=True).start()
    return None


def _post(url, payload):
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception as exc:
        _log.debug("experientia 铃响上报失败（忽略，不影响 gateway）: %s", exc)
'''


def _handler_py(url: str) -> str:
    """按上报 URL（可含 ?key=）生成 handler.py 正文。"""
    # replace 填入而非 % 格式化——URL 含 % 时后者抛 ValueError。
    return _HANDLER_TEMPLATE.replace("__EXPERIENTIA_URL__", url)


def hooks_root(home: Path | None = None) -> Path:
    """Hermes hooks 根目录（默认探测本机 home）。"""
    h = Path(home) if home else hermes_home()
    return h / "hooks"


def write_hook(home: Path | None = None,
               key: str | None = None) -> Path:
    """把铃响 hook 写入 Hermes hooks/<HOOK_NAME>/（幂等覆盖），返回 hook 目录。

    key：事件通道防伪令牌，嵌入 handler 默认上报 URL 的 ?key= 参数。"""
    root = hooks_root(home)
    d = root / HOOK_NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "HOOK.yaml").write_text(HOOK_YAML.format(name=HOOK_NAME), encoding="utf-8")
    (d / "handler.py").write_text(_handler_py(hermes_event_url(key)), encoding="utf-8")
    return d


def remove_hook(home: Path | None = None) -> bool:
    """卸载：删除 hooks/<HOOK_NAME>/。返回是否删除了东西。"""
    d = hooks_root(home) / HOOK_NAME
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False


def hook_status(home: Path | None = None) -> dict:
    """当前铃响 hook 是否已写入（写入 ≠ 生效，生效需重启 gateway）。"""
    d = hooks_root(home) / HOOK_NAME
    ok = (d / "HOOK.yaml").is_file() and (d / "handler.py").is_file()
    return {"installed": ok, "note": "写入后需重启 Hermes gateway 生效" if ok
            else "未安装：写入后重启 gateway（hermes gateway restart）生效"}


def handle_hermes_event(store, payload: dict | None) -> dict:
    """8101 收到铃响：只记 observed（install→observed 验证，memorax 口径），
    不落库不复盘——全文由文件通道 scan_loop 兜底（60s），避免双写。fail-open。"""
    payload = payload or {}
    event = str(payload.get("event") or "agent:end")
    session_id = str(payload.get("session_id") or "")
    try:
        store.record_hook_observed("hermes", event)
        logger.info("Hermes 铃响 %s session=%s（已记 observed，复盘走文件通道）",
                    event, session_id[:12])
    except Exception as exc:
        logger.warning("Hermes 铃响处理失败（fail-open）: %s", exc)
    return {}
