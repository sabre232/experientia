"""IDE 系官方 hooks.json 注入（总方案 S3b：Cursor / Windsurf）。

两家自 2025 起都有官方 hooks（核实见《Agent_hook面核实与接入矩阵》），且与
Claude 的差异是：配置落**独立 hooks.json**（不进 settings.json），事件名不同、
schema 不同。但本质相同——给事件配一条命令（curl stdin 管道 POST 本地 API）。

本模块职责（薄层，复用 hook.py 的幂等口径）：
- 生成各家 hooks.json 片段（Cursor: {"version":1,"hooks":{ev:[{command,...}]}}；
  Windsurf: {"hooks":{ev:[{command,show_output}]}}）；
- apply：读已有 hooks.json → 合并保留用户其它事件/条目 → 备份 → 原子写；
- remove：只清掉命令 URL 含 /api/hooks/<agent>-event 的自己条目，不动别人的；
- status：installed（含自己条目）→ observed（收到过真实事件，store 侧）。

事件只做"铃响 + observed"：payload 各家字段不同（cursor 带 conversation_id/
transcript_path；windsurf 带 trajectory_id/transcript_path），完整全文仍由文件
通道兜底；transcript 直读列为后续增强（文件捕获扩展），不在此轮臆造解析。
写入用户级路径属于用户级配置——GUI 接入动作时按分层授权弹一次确认。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from ..fs_util import replace_atomic

logger = logging.getLogger("experientia.capture.ide_hooks")

LOCAL_API_PORT = 8101
_URL_MARK = "/api/hooks/"

# 每 agent：label / 用户级 hooks.json 路径 / 注册的事件 → (官方事件名) /
# 事件条目构造器。slug 用于本地 API 端点与幂等 URL 识别。
IDES: dict[str, dict] = {
    "cursor": {
        "label": "Cursor",
        "user_path": Path.home() / ".cursor" / "hooks.json",
        "slug": "cursor-event",
        "schema_version": 1,
        "events": ("sessionStart", "afterAgentResponse", "stop"),
        # Cursor hooks 条目
    },
    "windsurf": {
        "label": "Windsurf",
        "user_path": Path.home() / ".codeium" / "windsurf" / "hooks.json",
        "slug": "windsurf-event",
        "schema_version": None,  # Windsurf 无顶层 version 字段
        "events": ("post_cascade_response_with_transcript",),
    },
}


def _curl_command(url_path: str, port: int = LOCAL_API_PORT,
                  key: str | None = None) -> str:
    url = f"http://127.0.0.1:{port}{url_path}"
    if key:
        url = f"{url}?key={key}"
    if os.name == "nt":
        return (f'curl.exe -s --max-time 15 -X POST "{url}" '
                f'-H "Content-Type: application/json" --data-binary @-')
    return (f"curl -s --max-time 15 -X POST {url} "
            f"-H 'Content-Type: application/json' --data-binary @-")


def _item_for(agent: str, cmd: str) -> dict:
    if agent == "cursor":
        return {"command": cmd, "type": "command", "timeout": 15}
    # windsurf：post 类事件不能阻止操作；show_output 关掉避免刷屏
    return {"command": cmd, "show_output": False}


def _ours_in(item: object, slug: str) -> bool:
    return (isinstance(item, dict)
            and f"{_URL_MARK}{slug}" in str(item.get("command") or ""))


def _config_path(agent: str, path: str | Path | None = None) -> Path:
    if path:
        return Path(path)
    return IDES[agent]["user_path"]


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _backup(path: Path) -> None:
    try:
        bak = path.with_name(path.name + ".experientia.bak")
        shutil.copy2(path, bak)
    except OSError:
        pass


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    replace_atomic(tmp, path)  # Windows 瞬时锁（AV 扫描）重试，见 app/fs_util.py


def _apply_events(agent: str, data: dict, port: int,
                  key: str | None = None) -> dict:
    """把我们的命令合并进 hooks 树（保留既有事件/条目，幂等去重）。"""
    meta = IDES[agent]
    slug = meta["slug"]
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks
    for event in meta["events"]:
        lst = hooks.get(event)
        if not isinstance(lst, list):
            lst = []
            hooks[event] = lst
        cmd = _curl_command(f"{_URL_MARK}{slug}", port, key)
        # 幂等且会刷新：先清掉我们自己的旧条目（可能是未带防伪令牌的旧版），
        # 再追加最新命令——用户其它条目原样保留（M10 迁移靠这条把 key 落下去）。
        rest = [it for it in lst if not _ours_in(it, slug)]
        rest.append(_item_for(agent, cmd))
        hooks[event] = rest
    if meta["schema_version"] is not None and "version" not in data:
        data["version"] = meta["schema_version"]
    return data


def _strip_events(agent: str, data: dict) -> dict:
    """移除我们的条目；只清空我们自己加的事件键，其余保留。"""
    meta = IDES[agent]
    slug = meta["slug"]
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    changed = False
    for event in meta["events"]:
        lst = hooks.get(event)
        if not isinstance(lst, list):
            continue
        rest = [it for it in lst if not _ours_in(it, slug)]
        if len(rest) != len(lst):
            hooks[event] = rest
            changed = True
        if not rest:
            del hooks[event]
    if not hooks:
        data.pop("hooks", None)
    if changed and "version" in data and meta["schema_version"] is not None:
        # version 仅在我们写入时添加过；清理后如文件空了则整体删除
        if not data.get("hooks"):
            data.pop("version", None)
    return data


def apply_config(agent: str, path: str | Path | None = None,
                 port: int = LOCAL_API_PORT,
                 key: str | None = None) -> dict:
    """合并写入该 agent 的 hooks.json（幂等 + 备份 + 原子）。返回安装摘要。

    key：事件通道防伪令牌，注入到各条 curl 命令的 ?key= 参数。"""
    if agent not in IDES:
        raise ValueError(f"未知 IDE agent: {agent}")
    p = _config_path(agent, path)
    if p.is_file():
        _backup(p)
    data = _read(p)
    data = _apply_events(agent, data, port, key)
    _write_atomic(p, data)
    return {"ok": True, "agent": agent, "path": str(p),
            "events": list(IDES[agent]["events"])}


def remove_config(agent: str, path: str | Path | None = None) -> dict:
    """只清掉我们注入的条目；不误删用户已有 hook。"""
    if agent not in IDES:
        raise ValueError(f"未知 IDE agent: {agent}")
    p = _config_path(agent, path)
    if not p.is_file():
        return {"ok": True, "removed": False}
    data = _read(p)
    _backup(p)
    before = json.dumps(data, sort_keys=True)
    data = _strip_events(agent, data)
    if json.dumps(data, sort_keys=True) != before:
        _write_atomic(p, data)
        return {"ok": True, "removed": True}
    return {"ok": True, "removed": False}


def config_status(agent: str, path: str | Path | None = None,
                  store=None) -> dict:
    """installed（配置里含我们条目）+ observed（真实收到事件）。"""
    if agent not in IDES:
        raise ValueError(f"未知 IDE agent: {agent}")
    meta = IDES[agent]
    p = _config_path(agent, path)
    data = _read(p)
    hooks = data.get("hooks") if isinstance(data, dict) else {}
    installed = bool(
        isinstance(hooks, dict)
        and any(_ours_in(it, meta["slug"])
                for lst in hooks.values() if isinstance(lst, list)
                for it in lst))
    observed: dict[str, str] = {}
    if store is not None:
        raw = store.load_hook_observed()
        for ev in meta["events"]:
            ts = raw.get(f"{agent}:{ev}")
            if ts:
                observed[ev] = ts
    return {"agent": agent, "path": str(p), "installed": installed,
            "observed": observed}


def handle_ide_event(store, agent: str, payload: dict | None) -> dict:
    """8101 收到 Cursor/Windsurf 铃响：只记 observed（installed→observed 验证），
    不落库不复盘——全文由文件通道兜底，避免臆造解析各家 transcript。fail-open。"""
    payload = payload or {}
    if agent not in IDES:
        return {}
    # 各家事件名所在字段不同：cursor=hook_event_name，windsurf=agent_action_name
    event = (str(payload.get("hook_event_name") or payload.get("event")
                 or payload.get("agent_action_name") or "unknown"))
    try:
        store.record_hook_observed(agent, event)
    except Exception as exc:
        logger.warning("%s 铃响记录失败（fail-open）: %s", agent, exc)
    return {}
