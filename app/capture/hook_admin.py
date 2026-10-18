"""Agent 官方 hook 统一管理（总方案 ，入口放 hooks 栏）。

把"各家 agent 的 hook 配置"管起来，不只管我们注入的：
- 读：某 agent 当前 hook 配置**全部条目** + 来源分类（experientia / user）+ 是否启用；
- 写：接入我们的（复用 ide_hooks/hermes_hook）→ 单条目修改 / 删除 / 禁用 / 启用 → 移除我们的。

配置定位发现（两级）：
  ① 内置表（hermes/cursor/windsurf/claude-code，已核实）——内置路径存在时优先；
  ② skill 自报 hook_surface（最新钥匙明细）——覆盖表外新 agent（workbuddy/codex 等），
     内置文件缺失时也用它兜底（自定义配置目录场景）。

schema 配方门控（写权限分级，总方案）：
  json_hooks（顶层 hooks 结构的 JSON）  → 全量管理（删除/禁用/修改）
  hook_dir（hooks/<名>/HOOK.yaml 目录型）→ 目录配方（禁用 = handler 改名保留，删除 = 删目录）
  toml_hooks（TOML 含 [hooks] 段，如 codex config.toml）→ v1 只读列出（写配方待实测定稿）
  认不出                                     → v1 只读列出
自报误报的最坏后果 = 列表多一条，不会写坏文件。

安全口径（沿用护栏）：写前备份 + 原子替换；origin 判定 = 命令 URL 含 "/api/hooks/"
（JSON 系）或目录名 = experientia-event（目录型）；**原有条目也允许删除/禁用，但必须由 UI
二次确认**；禁用对 JSON 系 = 移入文件内保留段（不破坏配置、可逆），对目录型 = 改名保留。
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import tomllib
from pathlib import Path

from ..fs_util import replace_atomic

logger = logging.getLogger("experientia.capture.hook_admin")

OUR_URL_MARK = "api/hooks/"
HERMES_HOOK_NAME = "experientia-event"

# 内置表（已核实）agent；其余走 skill 自报
KNOWN_AGENTS = ("hermes", "cursor", "windsurf", "claude-code")
# 允许写操作的 schema（配方门控）；toml_hooks v1 只读（写配方待实测定稿）。
# json_hooks 支持增/改/删/开关；hook_dir 支持增（新建目录）/删/开关（改 handler 名）。
WRITABLE_SCHEMAS = ("json_hooks", "hook_dir")

# JSON 系 agent：配置文件定位函数 + 是否 claude 嵌套结构 + 允许编辑的字段（按官方 schema）
from .ide_hooks import IDES  # cursor/windsurf user_path（同一常量，避免两处维护）

_LABELS = {"hermes": "Hermes", "cursor": "Cursor", "windsurf": "Windsurf",
           "claude-code": "Claude Code", "workbuddy": "WorkBuddy",
           "codex": "Codex", "codebuddy": "CodeBuddy"}


def _claude_settings() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _config_file(agent: str) -> Path | None:
    if agent in ("cursor", "windsurf"):
        return IDES[agent]["user_path"]
    if agent == "claude-code":
        return _claude_settings()
    return None


def _slug(agent: str) -> str:
    return {"cursor": "cursor-event", "windsurf": "windsurf-event",
            "claude-code": ""}.get(agent, agent)


def _is_ours_command(command: str) -> bool:
    return OUR_URL_MARK in (command or "")


# ---------- 配置定位：内置表 ∪ skill 自报（两级发现） ----------

def self_reported_sources(store) -> dict[str, dict]:
    """agent → 最新自报 hook 面（钥匙明细 keys/ 新码在前，首次命中即最新）。

    返回 {agent: {config_paths, formats: {path: schema}, writable_paths, at}}；
    只收 supported 且有路径的 hook 面；无钥匙 → 空 dict（不拦内置表）。
    """
    out: dict[str, dict] = {}
    if store is None:
        return out
    try:
        codes = store.list_key_codes()
    except Exception:  # noqa: BLE001 读失败降级为仅内置表
        return out
    for code in codes:
        m = store.load_key_manifest(code)
        if not isinstance(m, dict):
            continue
        agent = str(m.get("agent") or "")
        if not agent or agent in out:
            continue
        rep = m.get("report")
        hs = rep.get("hook_surface") if isinstance(rep, dict) else None
        if not isinstance(hs, dict) or not hs.get("supported"):
            continue
        cfg = [str(p) for p in (hs.get("config_paths") or []) if p]
        if not cfg:
            continue
        fmts: dict[str, str] = {}
        for f in (hs.get("formats") or []):
            if isinstance(f, dict) and str(f.get("path") or "") in cfg:
                sch = str(f.get("schema") or "")
                if sch in ("json_hooks", "toml_hooks", "hook_dir", "unknown"):
                    fmts[str(f["path"])] = sch
        out[agent] = {"config_paths": cfg, "formats": fmts,
                      "writable_paths": [str(p) for p in (hs.get("writable_paths") or [])
                                         if str(p) in cfg],
                      "at": str(m.get("at") or "")}
    return out


def _guess_schema(path: str) -> str:
    """自报缺 schema 标注时按扩展名/名保守推断（不猜内容）。

    误判 json_hooks 也无害：无 hooks 结构的文件读不出条目，写操作定位不到
    列表即安全 no-op（_locate → lst None）。
    """
    low = str(path or "").lower()
    if low.endswith(".toml"):
        return "toml_hooks"
    if low.endswith(".json"):
        return "json_hooks"
    if low.rsplit(os.sep, 1)[-1] == "hooks":
        return "hook_dir"
    return "unknown"


def _is_writable_file(p: Path) -> bool:
    """配置不存在也能写（首次创建看父目录）；存在则看文件/目录本身可写。"""
    if p.is_dir() or p.is_file():
        return os.access(str(p), os.W_OK)
    return bool(p.parent) and os.access(str(p.parent), os.W_OK)


def _builtin_info(agent: str, home: Path | None = None) -> dict:
    """内置表四家（已核实路径）。"""
    if agent == "hermes":
        root = hooks_root(home)
        return {"agent": agent, "kind": "code",
                "paths": [{"path": str(root), "schema": "hook_dir",
                           "writable": root.is_dir()
                                       and os.access(str(root), os.W_OK)}],
                "source": "builtin"}
    path = _config_file(agent)
    if path is None:
        raise ValueError(f"暂不支持管理该 agent 的 hook: {agent}")
    return {"agent": agent, "kind": "json",
            "paths": [{"path": str(path), "schema": "json_hooks",
                       "writable": _is_writable_file(path)}],
            "source": "builtin"}


def _kind_from_schemas(schemas: list[str]) -> str:
    """schema 列表 → 管理形态（code/toml/json/unknown）。"""
    if "hook_dir" in schemas:
        return "code"
    if schemas and all(s == "toml_hooks" for s in schemas):
        return "toml"
    if "json_hooks" in schemas:
        return "json"
    return "unknown"


def resolve_agent(agent: str, store=None, home: Path | None = None) -> dict:
    """agent → hook 配置定位 {agent, kind, paths:[{path,schema,writable}], source, reported_at}。

    优先级：① 内置表（四家已核实；内置路径存在时用内置）② skill 自报
    （远程/表外 agent 的现场情报）③ 本机启发式（agent 装在本机、app 看得见
    它的配置根——无需 skill 自报往返）。都无 → ValueError（含自报建议）。
    """
    if agent in KNOWN_AGENTS:
        info = _builtin_info(agent, home)
        p = Path(info["paths"][0]["path"])
        if p.is_file() or p.is_dir():
            return info
    sr = self_reported_sources(store).get(agent)
    if sr and sr.get("config_paths"):
        paths = [{"path": p,
                  "schema": sr["formats"].get(p) or _guess_schema(p),
                  "writable": p in sr["writable_paths"]}
                 for p in sr["config_paths"]]
        return {"agent": agent, "kind": _kind_from_schemas(
                    [x["schema"] for x in paths]), "paths": paths,
                "source": "self_report", "reported_at": sr.get("at") or ""}
    from . import hook_discovery
    found = hook_discovery.discover_hooks(agent, home)
    if found:
        paths = [{"path": p, "schema": sch,
                  "writable": os.access(p, os.W_OK)} for p, sch in found]
        return {"agent": agent, "kind": _kind_from_schemas(
                    [x["schema"] for x in paths]), "paths": paths,
                "source": "local_scan", "reported_at": ""}
    if agent in KNOWN_AGENTS:
        return _builtin_info(agent, home)  # 内置但文件不存在 → 列空态
    raise ValueError(f"暂不支持管理该 agent 的 hook: {agent}（可装 experientia-report skill 自报覆盖）")


# ---------- 读取：全部条目 + 来源 + 启用态 ----------

def _json_entries(path: Path, agent: str, pi: int = 0) -> list[dict]:
    """JSON 系读条目：{id, event, command, origin, enabled}。

    cursor/windsurf：hooks[event] = [命令对象]；
    claude-code/workbuddy 同族：hooks[event] = [条目对象（可含 hooks 嵌套）]，
    命令取嵌套首个（结构自动识别）。
    pi = 文件序号（同一 agent 多配置时，条目 ID 带序号以路由回正确文件）。
    """
    out: list[dict] = []
    if not path.is_file():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return out
    hooks = data.get("hooks") if isinstance(data, dict) else None
    disabled = data.get("_experientia_disabled") or {}
    if not isinstance(hooks, dict):
        return out

    def _item_command(item: dict) -> str:
        """条目命令：扁平（cursor/windsurf）取顶层 command；
        嵌套（claude-code / workbuddy 等同族，command 在 hooks[0].command）自动识别。"""
        cmd = item.get("command") or ""
        if not cmd:
            inner = item.get("hooks")
            if isinstance(inner, list) and inner and isinstance(inner[0], dict):
                cmd = inner[0].get("command") or ""
        return cmd

    for event, lst in hooks.items():
        if not isinstance(lst, list):
            continue
        for i, item in enumerate(lst):
            if not isinstance(item, dict):
                continue
            cmd = _item_command(item)
            if not cmd:
                continue
            out.append(_entry(agent, event, i, cmd, enabled=True, pi=pi))
    for event, lst in disabled.items():
        if not isinstance(lst, list):
            continue
        for i, item in enumerate(lst):
            if not isinstance(item, dict):
                continue
            cmd = _item_command(item)
            if not cmd:
                continue
            out.append(_entry(agent, event, f"d{i}", cmd, enabled=False, pi=pi))
    return out


def _entry(agent: str, event: str, idx, command: str, enabled: bool,
           pi: int = 0) -> dict:
    origin = "experientia" if _is_ours_command(command) else "user"
    id_ = (f"{agent}:{pi}:{event}:{idx}" if pi
           else f"{agent}:{event}:{idx}")
    return {"id": id_, "agent": agent, "event": event,
            "idx": str(idx), "command": command, "origin": origin,
            "enabled": enabled}


def _dir_entries(root: Path, agent: str) -> list[dict]:
    """目录型（hook_dir）：hooks 根下每个目录 = 一条（HOOK.yaml 声明事件，
    handler.py 存在即启用）。hermes 与自报同构 agent 共用。"""
    out: list[dict] = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        yaml_f = d / "HOOK.yaml"
        handler = d / "handler.py"
        if not yaml_f.is_file():
            continue
        events = "?, ?"
        try:
            txt = yaml_f.read_text(encoding="utf-8")
            ev = [ln.strip().lstrip("- ").strip()
                  for ln in txt.splitlines()
                  if ln.strip().startswith("- ")]
            events = ", ".join(ev) if ev else "?"
        except OSError:
            pass
        origin = "experientia" if d.name == HERMES_HOOK_NAME else "user"
        out.append({"id": f"{agent}:{d.name}", "agent": agent, "event": events,
                    "idx": d.name, "command": d.name, "origin": origin,
                    "enabled": handler.is_file()})
    return out


def _toml_entries(path: Path, agent: str) -> list[dict]:
    """TOML 型（codex config.toml 的 hooks.*）：只读列出，宽容解析。

    条目 schema 待实测定稿——dict 取 command/handler/script 字段，字符串直接用；
    解析不出命令的条目以占位符列出（不丢条目）。"""
    out: list[dict] = []
    if not path.is_file():
        return out
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError):
        return out
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return out
    for event, val in hooks.items():
        items = val if isinstance(val, list) else [val]
        for i, it in enumerate(items):
            cmd = ""
            if isinstance(it, dict):
                cmd = str(it.get("command") or it.get("handler")
                          or it.get("script") or "")
            elif isinstance(it, str):
                cmd = it
            out.append(_entry(agent, str(event), i, cmd or "（TOML 条目）", enabled=True))
    return out


def list_agent(agent: str, home: Path | None = None, store=None) -> dict:
    """{agent, label, kind, path, exists, entries, source, reported_at}；不支持 → raise ValueError。"""
    res = resolve_agent(agent, store, home)
    p0 = res["paths"][0]
    path = Path(p0["path"])
    if res["kind"] == "code":
        entries = _dir_entries(path, agent)
    elif res["kind"] == "toml":
        entries = _toml_entries(path, agent)
    elif res["kind"] == "json":
        # 多配置 agent（如 codex 各插件 hooks.json）：逐文件列条目，
        # pi = 在 res["paths"] 中的序号（写操作凭它路由回正确文件）
        entries = []
        for pi, pth in enumerate(res["paths"]):
            if pth["schema"] == "json_hooks":
                entries.extend(_json_entries(Path(pth["path"]), agent, pi))
    else:
        entries = []
    return {"agent": agent, "label": _LABELS.get(agent, agent),
            "kind": res["kind"], "path": p0["path"],
            "exists": path.is_file() or path.is_dir(),
            "entries": entries, "source": res["source"],
            "reported_at": res.get("reported_at") or ""}


# ---------- 总览（一次返回全部 agent 的接入态，支撑 GUI 自动接入提议） ----------

def overview(home: Path | None = None, store=None) -> dict:
    """一次返回全部 agent 的 hook 管理态：

    {agent: {agent,label,kind,path,exists,installed,writable,entries,source,reported_at}}。
    agent 集合 = 内置表 ∪ 自报 hook 面 ∪ 本机检测到在跑的 agent（走本地启发式发现）。
    installed = 配置里含 Experientia 注入条目；writable = 可写入（用于自动接入提议）。
    """
    out: dict = {}
    agents = list(KNOWN_AGENTS)
    for a in self_reported_sources(store):
        if a not in agents:
            agents.append(a)
    detected: set = set()
    if store is not None:
        try:
            detected = store.load_detected_agents()
        except Exception as exc:  # noqa: BLE001 detected 读取失败不拦总览
            # 不拦总览的语义不变，补一条 debug 便于追查
            # "为什么总览里少了某几个 agent"。
            logger.debug("已检测 agent 读取失败（不拦总览）: %s", exc)
        for a in detected:
            if a not in agents:
                agents.append(a)
    for agent in agents:
        try:
            info = list_agent(agent, home, store)
        except ValueError:
            # 检测到在跑但找不到 hook 配置 → 显式空态（不再静默消失，
            # 免得用户"明明搜到了"却不见卡片）
            if agent in detected:
                out[agent] = {"agent": agent, "label": _LABELS.get(agent, agent),
                              "kind": "none", "path": "", "exists": False,
                              "entries": [], "installed": False,
                              "writable": False, "source": "none",
                              "reported_at": ""}
            continue
        entries = info.get("entries") or []
        info["installed"] = any(e.get("origin") == "experientia" for e in entries)
        p = Path(str(info.get("path") or ""))
        info["writable"] = bool(p) and p.exists() and os.access(str(p), os.W_OK)
        out[agent] = info
    return out


# ---------- 写操作（JSON/目录型全量；TOML 型 v1 只读；claude-code 含原有条目） ----------

_EDITABLE_FIELDS = ("command", "working_directory", "show_output", "timeout", "type")
# 这些字段落在"命令对象"上：扁平结构=条目本身；嵌套结构（claude/workbuddy 同族，
# command 在 hooks[0].command）=内层 hooks[0]。写错层 = 改了不生效（读通写断）。
_COMMAND_LEVEL_FIELDS = ("command", "type", "timeout")


def _command_target(item: dict) -> dict:
    """返回承载 command/type/timeout 的 dict。

    嵌套（无顶层 command、command 在 hooks[0].command）→ 内层 hooks[0]；
    扁平（cursor/windsurf，command 在条目顶层）→ 条目本身。
    与读路径 _item_command 的取值层级严格对齐。
    """
    if not item.get("command"):
        inner = item.get("hooks")
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            return inner[0]
    return item


def _readonly_error(schema: str) -> ValueError:
    """写门控拒绝：按 schema 给具体原因（TOML 型 vs 形态未识别）。"""
    if schema == "toml_hooks":
        return ValueError("TOML 型配置 v1 只读列出（写配方待实测定稿）")
    return ValueError("配置形态未识别，v1 只读列出")


def _load(path: Path) -> dict:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"hooks": {}}


def _backup_and_write(path: Path, data: dict) -> None:
    try:
        if path.is_file():
            shutil.copy2(path, path.with_name(path.name + ".experientia.bak"))
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    replace_atomic(tmp, path)  # Windows 瞬时锁（AV 扫描）重试，见 app/fs_util.py


def _split_entry(entry_id: str) -> tuple[int, str, bool, int] | None:
    """entry_id → (文件序号, event, 是否在保留段, 列表内序号)。

    4 段（agent:pi:event:idx，多配置）/ 3 段（agent:event:idx，单配置）。
    """
    parts = (entry_id or "").split(":", 3)
    if len(parts) == 4:
        pi_tok, event, idx_tok = parts[1], parts[2], parts[3]
        if not pi_tok.isdigit():
            return None
        pi = int(pi_tok)
    elif len(parts) == 3:
        pi, event, idx_tok = 0, parts[1], parts[2]
    else:
        return None
    disabled = idx_tok.startswith("d")
    idx_tok = idx_tok[1:] if disabled else idx_tok
    if not idx_tok.isdigit():
        return None
    return pi, event, disabled, int(idx_tok)


def _prune_empty_event(data: dict, event: str, disabled: bool) -> None:
    """事件列表清空后删掉空键（避免配置里残留 "Stop": [] 噪音）。"""
    section = data.get("_experientia_disabled") if disabled else data.get("hooks")
    if isinstance(section, dict) and not section.get(event):
        section.pop(event, None)


def _locate(paths: list[dict], entry_id: str):
    """返回 (path, data, event, lst, idx)；找不到 → lst None。

    paths = resolve 出的全部配置；pi 越界/文件缺失安全降级（lst None）。
    """
    parsed = _split_entry(entry_id)
    if parsed is None:
        return None, None, None, None, None
    pi, event, disabled, idx = parsed
    if not (0 <= pi < len(paths)):
        return None, None, None, None, None
    path = Path(paths[pi]["path"])
    data = _load(path)
    if disabled:
        lst = (data.get("_experientia_disabled") or {}).get(event, [])
    else:
        lst = (data.get("hooks") or {}).get(event, [])
    if not (0 <= idx < len(lst)):
        return path, data, event, None, idx
    return path, data, event, lst, idx


# 目录型条目名门禁（安全）：entry_id 来自 API payload，
# 目录分支直接 `Path(root) / name` 做 rmtree/改名，必须拒绝 `..` 与路径
# 分隔符等穿越段，防止越出 hooks 根目录操作任意目录。
_SAFE_DIR_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _code_dir_name(entry_id: str) -> str | None:
    """目录型 entry_id（`<name>:<dir>`）→ 校验后的目录名；非法返回 None。"""
    if ":" not in entry_id:
        return None
    name = entry_id.split(":", 1)[1]
    if not name or ".." in name or not _SAFE_DIR_NAME_RE.match(name):
        return None
    return name


def delete_entry(agent: str, entry_id: str, home: Path | None = None,
                 store=None) -> dict:
    """删除任意条目（origin 为 user 也允许——UI 必须二次确认后调此）。"""
    res = resolve_agent(agent, store, home)
    p0 = res["paths"][0]
    if res["kind"] == "code":
        name = _code_dir_name(entry_id)
        if name is None:
            return {"ok": False, "error": "非法条目名"}
        d = Path(p0["path"]) / name
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            return {"ok": True, "removed": True}
        return {"ok": True, "removed": False}
    if p0["schema"] != "json_hooks":
        raise _readonly_error(p0["schema"])
    path, data, event, lst, idx = _locate(res["paths"], entry_id)
    if lst is None:
        return {"ok": True, "removed": False}
    was_disabled = entry_id.rsplit(":", 1)[-1].startswith("d")
    lst.pop(idx)
    _prune_empty_event(data, event, was_disabled)
    if not data.get("_experientia_disabled"):
        data.pop("_experientia_disabled", None)  # 保留段空了不残留空键
    _backup_and_write(path, data)
    return {"ok": True, "removed": True}


def toggle_entry(agent: str, entry_id: str, enabled: bool,
                 home: Path | None = None, store=None) -> dict:
    """启用/禁用。JSON 系：条目在 hooks 与保留段 _experientia_disabled 间移动；
    目录型：handler.py 改名保留（.disabled）。"""
    res = resolve_agent(agent, store, home)
    p0 = res["paths"][0]
    if res["kind"] == "code":
        name = _code_dir_name(entry_id)
        if name is None:
            return {"ok": False, "error": "非法条目名"}
        d = Path(p0["path"]) / name
        handler = d / "handler.py"
        off = d / "handler.py.disabled"
        if enabled and off.is_file() and not handler.exists():
            off.rename(handler)
            return {"ok": True}
        if not enabled and handler.is_file():
            handler.rename(off)
            return {"ok": True}
        return {"ok": True, "unchanged": True}
    if p0["schema"] != "json_hooks":
        raise _readonly_error(p0["schema"])
    path, data, event, lst, idx = _locate(res["paths"], entry_id)
    if lst is None:
        return {"ok": False, "error": "条目不存在"}
    item = lst.pop(idx)
    _prune_empty_event(data, event, enabled)  # 源段（禁用操作源=hooks）空了则清键
    data.setdefault("hooks", {})
    data.setdefault("_experientia_disabled", {})
    target = data["hooks"] if enabled else data["_experientia_disabled"]
    target.setdefault(event, []).append(item)
    if not data.get("_experientia_disabled"):
        data.pop("_experientia_disabled", None)  # 保留段空了不残留空键
    _backup_and_write(path, data)
    return {"ok": True}


def edit_entry(agent: str, entry_id: str, updates: dict,
               home: Path | None = None, store=None) -> dict:
    """修改条目字段（允许字段见 _EDITABLE_FIELDS，命令类安全字段白名单）。仅 JSON 系。"""
    res = resolve_agent(agent, store, home)
    if res["paths"][0]["schema"] != "json_hooks":
        raise _readonly_error(res["paths"][0]["schema"])
    path, data, event, lst, idx = _locate(res["paths"], entry_id)
    if lst is None:
        return {"ok": False, "error": "条目不存在"}
    item = lst[idx]
    cmd_target = _command_target(item)
    for k, v in updates.items():
        if k not in _EDITABLE_FIELDS or v is None:
            continue
        if k in _COMMAND_LEVEL_FIELDS:
            cmd_target[k] = v  # 嵌套→hooks[0]，扁平→item（对齐读路径层级）
        else:
            item[k] = v
    _backup_and_write(path, data)
    return {"ok": True}


def _new_item(agent: str, command: str, hooks: dict) -> dict:
    """构造新条目：扁平/嵌套形状自动探测，与读路径 _item_command 严格对齐。

    嵌套（claude/workbuddy 同族，命令在 hooks[0].command）→ {"hooks":[{type,command}]}；
    扁平（cursor/windsurf，命令在顶层）→ {"command": cmd}。
    探测：统计现有条目，多数派胜出；无现有 → 按 agent 默认（claude-code 嵌套、其余扁平）。
    保证 add 写出的层与 edit_entry/_command_target 改的层一致——读通写不断。"""
    flat_n = nested_n = 0
    for lst in (hooks or {}).values():
        if not isinstance(lst, list):
            continue
        for it in lst:
            if not isinstance(it, dict):
                continue
            if it.get("command"):
                flat_n += 1
            else:
                inner = it.get("hooks")
                if (isinstance(inner, list) and inner
                        and isinstance(inner[0], dict)
                        and inner[0].get("command")):
                    nested_n += 1
    if nested_n > flat_n:
        nested = True
    elif flat_n > nested_n:
        nested = False
    else:
        nested = agent == "claude-code"
    if nested:
        return {"hooks": [{"type": "command", "command": command}]}
    return {"command": command}


# 目录型（hook_dir）新增的 HOOK.yaml / handler.py 模板。handler 是薄壳：命中事件时
# 后台 daemon 线程 subprocess 跑命令、异常吞掉（零阻塞、失败无感，对齐 hermes_hook
# .HANDLER_PY 纪律——它跑在 Hermes gateway 进程内，绝不能阻塞 agent 主流程）。
_DIR_HOOK_YAML = """\
name: {name}
description: 用户自定义 hook（Experientia 新增）；命中事件时执行命令
events:
{events}
"""

_DIR_HANDLER_PY = '''\
# -*- coding: utf-8 -*-
# 由 Experientia 生成：事件 {events} 命中时执行命令（薄壳；后台线程、失败无感）。
# 卸载：删除本目录后重启 Hermes gateway 生效。
import subprocess
import threading

_EVENTS = {events}
_CMD = {cmd}


def handle(event_type, context):
    if event_type not in _EVENTS:
        return None
    threading.Thread(target=_run, daemon=True).start()
    return None


def _run():
    try:
        # 安全边界（保持 shell 语义）：
        # 用户 hook 命令需支持 && / 管道等 shell 组合语法，改列表执行
        # （shell=False）会破坏既有命令的兼容性；单机自用、命令仅来自本机
        # 可改的配置文件，攻击面不在进程边界上，风险可接受。
        subprocess.run(_CMD, shell=True, timeout=30)
    except Exception:
        pass
'''


def _add_dir_hook(root: Path, event: str, command: str) -> Path:
    """目录型（hook_dir）新增一条：root/user-hook-<hex>/{HOOK.yaml, handler.py}。

    目录名唯一（secrets 6 位 hex，碰撞重试）；命令用 json.dumps 安全嵌入 handler
    防注入。事件按逗号分隔（hermes gateway 事件，如 agent:end / session:end）。
    返回新 hook 目录。写的是**新建目录**，不覆盖任何既有文件。"""
    d: Path | None = None
    for _ in range(8):
        cand = root / f"user-hook-{secrets.token_hex(3)}"
        if not cand.exists():
            d = cand
            break
    if d is None:
        raise ValueError("无法生成唯一 hook 目录名")
    d.mkdir(parents=True, exist_ok=True)
    events = [e.strip() for e in event.split(",") if e.strip()]
    # event 原样拼进 HOOK.yaml——含换行 / # 的片段可向用户
    # Hermes 配置注入任意 YAML 键。限定单行安全字符集（覆盖 PreToolUse /
    # agent:end 等既有形态），非法即拒绝。
    for _e in events:
        if not re.fullmatch(r"[\w:.@/()-]{1,64}", _e):
            raise ValueError(f"非法事件名：{_e!r}")
    yaml_events = "\n".join(f"  - {e}" for e in events)
    (d / "HOOK.yaml").write_text(
        _DIR_HOOK_YAML.format(name=d.name, events=yaml_events), encoding="utf-8")
    (d / "handler.py").write_text(
        _DIR_HANDLER_PY.format(events=repr(events), cmd=json.dumps(command)),
        encoding="utf-8")
    return d


def add_entry(agent: str, event: str, command: str, home: Path | None = None,
              store=None) -> dict:
    """手动往 agent 配置新增一条 hook 条目。

    JSON 系（cursor/windsurf/claude-code/codex/workbuddy）：追加到 hooks[event]，
    形状由 _new_item 自动探测（扁平/嵌套）。目录型（hook_dir，如 hermes）：新建
    user-hook-<hex> 目录（HOOK.yaml + handler.py 薄壳包命令）。TOML/unknown 只读门控。

    event = 事件名（工具特定：claude 的 PreToolUse、hermes 的 agent:end 等）；
    command = 要执行的命令。写前备份 + 原子替换（与 edit/delete 同口径）。
    空事件/空命令 → ValueError。
    """
    event = (event or "").strip()
    command = (command or "").strip()
    if not event:
        raise ValueError("事件名不能为空")
    if not command:
        raise ValueError("命令不能为空")
    res = resolve_agent(agent, store, home)
    # 目录型（hook_dir，如 hermes）：新建 user-hook-<hex> 目录（HOOK.yaml + handler.py）
    if res["kind"] == "code":
        _add_dir_hook(Path(res["paths"][0]["path"]), event, command)
        return {"ok": True, "added": True, "event": event}
    if res["paths"][0]["schema"] != "json_hooks":
        raise _readonly_error(res["paths"][0]["schema"])
    pi = next((i for i, p in enumerate(res["paths"])
               if p["schema"] == "json_hooks"), 0)
    path = Path(res["paths"][pi]["path"])
    data = _load(path)
    hooks = data.setdefault("hooks", {})
    lst = hooks.get(event)
    if not isinstance(lst, list):
        lst = []
        hooks[event] = lst
    lst.append(_new_item(agent, command, hooks))
    _backup_and_write(path, data)
    return {"ok": True, "added": True, "event": event}


def install_ours(agent: str, home: Path | None = None,
                 key: str | None = None) -> dict:
    """接入我们的 hook（Hermes/Cursor/Windsurf；claude 用既有 hook 通道）。

    key：事件通道防伪令牌，透传给各家注入器写进上报命令的 ?key= 参数。"""
    if agent == "hermes":
        from .hermes_hook import write_hook
        write_hook(home, key=key)
        return {"ok": True}
    if agent in ("cursor", "windsurf"):
        from .ide_hooks import apply_config
        return apply_config(agent, key=key)
    raise ValueError(f"该 agent 接入走既有通道: {agent}")


def remove_ours(agent: str, home: Path | None = None) -> dict:
    """移除我们注入的全部条目。"""
    if agent == "hermes":
        from .hermes_hook import remove_hook
        return {"ok": True, "removed": remove_hook(home)}
    if agent in ("cursor", "windsurf"):
        from .ide_hooks import remove_config
        return remove_config(agent)
    raise ValueError(f"该 agent 移除走既有通道: {agent}")


def install_all(home: Path | None = None,
                key: str | None = None) -> dict:
    out = {}
    for a in ("hermes", "cursor", "windsurf"):
        try:
            out[a] = install_ours(a, home, key=key)
        except Exception as exc:
            out[a] = {"ok": False, "error": str(exc)}
    return out


def remove_all(home: Path | None = None) -> dict:
    out = {}
    for a in ("hermes", "cursor", "windsurf"):
        try:
            out[a] = remove_ours(a, home)
        except Exception as exc:
            out[a] = {"ok": False, "error": str(exc)}
    return out


def hooks_root(home: Path | None = None) -> Path:
    from .hermes_hook import hooks_root as _r
    return _r(home)
