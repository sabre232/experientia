"""experientia-report skill 包生成器（总方案 S2：扫不到的 agent 才装的兜底 skill）。

只产出可安装包（开放 Agent Skills 标准）：
  <target>/experientia-report/SKILL.md
  <target>/experientia-report/scripts/probe.py   （agent 现场自检执行体，自包含标准库）

定位（与 experientia-memory 的 `.repo_memory/` 仓库复盘区分）：
- 面向"Experientia 扫描覆盖不到"的 agent（Trae 加密/未知新生态等）；
- probe 只读探测数据位置/格式/注入点 → 生成 report → 8101 直传或落 incoming；
- 输出契约：只打印一行（上报码或"已上报 ✓"），探测细节除非显式 --debug 绝不出现在
  用户面前（总方案）。

数据层铁律豁免：本脚本生成的 probe.py 会被注入给第三方
agent 独立运行，彼时无法 import app.store（目标环境没有本引擎代码），因此直写
~/.experientia/incoming/ 落报告——这是「所有对 ~/.experientia/ 的读写走
app/store/store.py」铁律的已声明例外；incoming/ 是引擎侧 store.scan 消费的
单向投递目录，probe 对数据目录只写这一个文件、不读不改任何其他资产。
"""

from __future__ import annotations

from pathlib import Path

SKILL_DIRNAME = "experientia-report"

# 候选表与矩阵文档《Agent_hook面核实与接入矩阵》一致（各家真实路径；%VAR%/~/展开）。
# 每一项: (路径表达式, kind)  kind ∈ db/jsonl/plain/config
_AGENT_CANDIDATES: dict[str, tuple] = {
    "hermes": (
        (r"%LOCALAPPDATA%/hermes/state.db", "db"),
        (r"%LOCALAPPDATA%/hermes/hooks", "hook_dir"),
    ),
    "claude-code": (
        (r"~/.claude/projects/", "jsonl_dir"),
        (r"~/.claude/settings.json", "hook_config"),
    ),
    "codex": (
        (r"~/.codex/sessions/", "jsonl_dir"),
        (r"~/.codex/config.toml", "hook_toml"),
    ),
    "workbuddy": (
        (r"~/.workbuddy/projects/", "jsonl_dir"),
        (r"~/.workbuddy/settings.json", "hook_config"),
    ),
    "codebuddy": (
        (r"~/.codebuddy/projects/", "jsonl_dir"),
    ),
    "trae": (
        (r"%APPDATA%/Trae CN/ModularData/ai-agent/database.db", "db"),
        (r"%APPDATA%/Trae/ModularData/ai-agent/database.db", "db"),
    ),
    "cursor": (
        (r"%APPDATA%/Cursor/User/globalStorage/state.vscdb", "db"),
        (r"%USERPROFILE%/.cursor/hooks.json", "hook_config"),
    ),
    "windsurf": (
        (r"~/.codeium/windsurf/hooks.json", "hook_config"),
        (r"~/.windsurf/transcripts/", "jsonl_dir"),
    ),
    "openclaw": (
        (r"~/.openclaw/agents/*/agent/openclaw-agent.sqlite", "db_glob"),
        (r"~/.openclaw/openclaw.json", "config"),
    ),
    "openhands": ((r"~/.openhands/", "jsonl_dir"),),
    "gemini-cli": ((r"~/.gemini/tmp/", "jsonl_dir"),),
    "opencode": ((r"~/.config/opencode/", "jsonl_dir"),),
    "aider": (),
    "clawdbot": ((r"~/.openclaw/agents/*/agent/openclaw-agent.sqlite", "db_glob"),),
    "qclaw": ((r"~/.qclaw/", "jsonl_dir"),),
}

PROBE_TEMPLATE = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""experientia-report 现场自检（只读，输出契约：只打印一行）。

用法:
  python probe.py --agent hermes
  python probe.py --agent trae --debug          # 调试才展开细节
  python probe.py --agent unknown-agent --path C:/xxx/sessions   # 手动指定会话位置

输出: 找到可上报数据 → 一行上报码（如 HER-1A2B3C4D-9F01）；8101 直传成功则
打印 "已上报 OK"。完全没找到会话数据 → 打印 --path 定位指引（重跑补报）。
本脚本只读，不写任何 agent 数据；不含密钥、不上传。
"""
import glob as _glob
import json as _json
import os as _os
import re as _re
import sqlite3 as _sqlite3  # noqa: F401  (仅借头部常量思路，实际用二进制头判定)
import sys as _sys
import urllib.request as _urllib
import zlib as _zlib

_SQLITE_HEAD = b"SQLite format 3\x00"
# 生成时把候选表 JSON 注入此处；运行期 _json.loads 还原为 dict（此前直接塞
# 字符串导致 _AGENT_CANDIDATES.get 报 'str' 无 get —— 候选探测一跑即崩）
_AGENT_CANDIDATES = _json.loads("""__AGENT_CANDIDATES__""")

def _expand(text):
    text = _os.path.expandvars(text)
    text = _os.path.expanduser(text)
    return text.replace("\\", _os.sep).replace("/", _os.sep)

def _head(path, n=16):
    try:
        with open(path, "rb") as fh:
            return fh.read(n)
    except OSError:
        return b""

def _drives():
    """可用盘符（Windows 盘级探测；非 Windows 记空，由服务端环境兜底）。"""
    out = []
    if _os.name == "nt":
        try:
            import string as _string
            for c in _string.ascii_uppercase:
                if _os.path.exists(c + ":\\"):
                    out.append(c)
        except Exception:
            pass
    return out

def _drive_of(path):
    """取路径所在盘（Windows 返回盘符，非 Windows 空串）。"""
    m = _re.match(r"^([A-Za-z]):[\\/]", str(path))
    return m.group(1).upper() if m else ""

def _env_brief():
    """现场环境底座（drives + 关键 env 实际展开值，供接收端判断还有没有别的可能位置）。"""
    out = {"os": _os.name, "drives": _drives()}
    for field, var in (("home", "HOME"), ("localappdata", "LOCALAPPDATA"),
                       ("appdata", "APPDATA"), ("userprofile", "USERPROFILE")):
        v = _os.environ.get(var) or ""
        if v:
            out[field] = v
    return out

def _has_marker(root):
    """注入点是否已含 Experientia（文件或目录都认，有界递归，只读）。"""
    stack = [root]
    checked = 0
    while stack and checked < 400:
        p = stack.pop()
        checked += 1
        try:
            if _os.path.isdir(p):
                for child in _os.listdir(p)[:60]:
                    stack.append(_os.path.join(p, child))
                continue
            with open(p, "rb") as fh:
                if b"experientia" in fh.read(262144).lower():
                    return True
        except OSError:
            pass
    return False

def _probe_one(path):
    """单个文件探测 → (path|None, fmt)；目录/glob 由 _expand_dir 先展开。"""
    p = _expand(path)
    if not _os.path.isfile(p):
        return None, "不存在"
    head = _head(p)
    if head == _SQLITE_HEAD:
        return p, "plaintext_sqlite"
    try:
        size = _os.path.getsize(p)
    except OSError:
        size = 0
    return (p, "encrypted") if size >= 4096 else (p, "plaintext")

def _expand_dir(expr, limit=10):
    """目录/glob → 命中文件列表（jsonl/json/sqlite/db，非递归，前 limit 个）。"""
    p = _expand(expr)
    hits = []
    if "*" in p:
        hits = _glob.glob(p)
    elif _os.path.isdir(p):
        for pat in ("*.jsonl", "*.json", "*.sqlite", "*.db"):
            hits += _glob.glob(_os.path.join(p, pat))
    out = []
    for f in sorted(hits)[:limit]:
        if _os.path.isfile(f) and f not in out:
            out.append(f)
    return out

# 候选表 kind → schema（表内路径已知类型；启发式命中的由 _hook_schema_file 内容判定）
_TABLE_HOOK_SCHEMA = {"hook_config": "json_hooks", "hook_dir": "hook_dir",
                      "hook_toml": "toml_hooks"}
# 同族目录映射（agent 名 → 用户目录下的配置根；表外 agent 的启发式扫描根）
_FAMILY_ROOTS = {
    "claude-code": [".claude"], "claude": [".claude"],
    "codex": [".codex"], "workbuddy": [".workbuddy"],
    "codebuddy": [".codebuddy"], "cursor": [".cursor"],
    "windsurf": [".codeium", ".windsurf"], "gemini-cli": [".gemini"],
    "qoder": [".qoder"], "iflow": [".iflow"], "opencode": [".config/opencode"],
    "openclaw": [".openclaw"], "aider": [".aider"],
}
_HOOK_FILE_NAMES = ("settings.json", "hooks.json", "config.json",
                    "config.toml", "openclaw.json", "plugin.json")


def _hook_schema_file(path):
    """文件内容 → hook schema（json_hooks/toml_hooks/None）；只读、有大小上限。

    识别不靠文件名靠结构：JSON 顶层必须是 hooks 映射；TOML 必须出现
    [hooks] 表或 hooks. 键——避免把普通 settings 文件误认成 hook 配置。
    """
    try:
        if _os.path.getsize(path) > 262144:
            return None
        low = path.lower()
        if low.endswith(".toml"):
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for ln in fh.read(65536).splitlines():
                    s = ln.strip()
                    if s.startswith("[hooks") or s.startswith("hooks."):
                        return "toml_hooks"
            return None
        if low.endswith(".json"):
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                data = _json.load(fh)
            if isinstance(data, dict) and isinstance(data.get("hooks"), dict):
                return "json_hooks"
    except Exception:
        pass
    return None


def _discover_hooks(agent):
    """通用启发式：有界扫描 agent 配置根找 hook 配置/目录（只读）。

    覆盖候选表之外的新 agent（如 workbuddy）：同族目录映射 + 用户目录同名/
    点号目录 + Windows %LOCALAPPDATA%/%APPDATA% 同名目录；每根只扫两层、
    只认白名单文件名。→ [(path, schema)]。
    """
    home = _os.path.expanduser("~")
    name = str(agent or "").lower()
    roots = [_os.path.join(home, rel) for rel in _FAMILY_ROOTS.get(name, [])]
    for var in ("LOCALAPPDATA", "APPDATA"):
        base = _os.environ.get(var) or ""
        if base and name:
            roots.append(_os.path.join(base, name))
    if name:
        roots.append(_os.path.join(home, "." + name))
    out, seen = [], set()

    def _check_dir(d):
        try:
            names = _os.listdir(d)
        except OSError:
            return
        for fn in names:
            p = _os.path.join(d, fn)
            if not _os.path.isfile(p) or fn not in _HOOK_FILE_NAMES:
                continue
            sch = _hook_schema_file(p)
            if sch and p not in seen:
                seen.add(p)
                out.append((p, sch))
        hd = _os.path.join(d, "hooks")
        if _os.path.isdir(hd):
            try:
                subs = _os.listdir(hd)
            except OSError:
                subs = []
            for dd in sorted(subs)[:40]:
                if _os.path.isfile(_os.path.join(hd, dd, "HOOK.yaml")):
                    if hd not in seen:
                        seen.add(hd)
                        out.append((hd, "hook_dir"))
                    break

    for root in roots[:6]:
        if not _os.path.isdir(root):
            continue
        _check_dir(root)
        try:
            subs = sorted(_os.listdir(root))[:30]
        except OSError:
            subs = []
        for sub in subs:
            if len(out) >= 8:
                break
            sp = _os.path.join(root, sub)
            if _os.path.isdir(sp):
                _check_dir(sp)
        if len(out) >= 8:
            break
    return out


def _probe_agent(agent):
    """按候选表 + 通用启发式探测数据源与注入点（只读）。

    注入点附加三查：schema（表内按 kind / 启发式按内容）+ 可写性（writable）
    + 是否已含 Experientia（already_injected），供接收端决定“能不能注入/
    能不能写管理/要不要重复注入”，探测本身仍只读。
    """
    data, hook_paths, writable_paths, formats = [], [], [], {}
    raw = _AGENT_CANDIDATES.get(agent, {}) or {}
    for expr, kind in raw.get("data", []) or []:
        if expr.endswith("/") or "*" in expr:
            for f in _expand_dir(expr):
                found, fmt = _probe_one(f)
                if found:
                    data.append({"kind": kind, "path": found, "format": fmt})
            continue
        found, fmt = _probe_one(expr)
        if found:
            data.append({"kind": kind, "path": found, "format": fmt})
    for expr, kind in raw.get("hooks", []) or []:
        p = _expand(expr)
        if _os.path.exists(p):
            hook_paths.append(p)
            formats[p] = _TABLE_HOOK_SCHEMA.get(kind, "unknown")
            if _os.access(p, _os.W_OK):
                writable_paths.append(p)
    for p, sch in _discover_hooks(agent):
        if p in formats:
            continue
        hook_paths.append(p)
        formats[p] = sch
        if _os.access(p, _os.W_OK):
            writable_paths.append(p)
    already_injected = False
    for p in hook_paths:
        if _has_marker(p):
            already_injected = True
            break
    return data, hook_paths, writable_paths, already_injected, formats

def _slug(agent):
    table = {"claude-code": "CLD", "codex": "CDX", "hermes": "HMS", "trae": "TRA",
             "cursor": "CRS", "windsurf": "WND", "openclaw": "OCL", "opencode": "OPC",
             "clawdbot": "OCL", "qclaw": "QCL", "gemini-cli": "GEM"}
    if agent in table:
        return table[agent]
    s = _re.sub(r"[^A-Z0-9]", "", (agent or "agent").upper())[:4] or "AGX"
    return s

_KIND = {"P": "可扫描", "E": "已加密", "H": "可接 Hook", "N": "经验上报", "U": "未知"}

def _code(agent, rid, cls="U"):
    slug = _slug(agent)
    cls = cls if cls in _KIND else "U"
    crc = _zlib.crc32((slug + rid).encode()) & 0xFFFF
    return "%s-%s-%s-%04X" % (slug, cls, rid, crc)

def _class_of(data, hook_paths):
    """形态位：H=有官方 hook 面，P=明文可扫，E=加密，U=未知。"""
    if hook_paths:
        return "H"
    for s in data:
        fmt = s.get("format", "")
        if fmt in ("plaintext_sqlite", "sqlite", "jsonl", "json", "plaintext"):
            return "P"
        if fmt == "encrypted":
            return "E"
    return "U"

def _post(agent, report):
    """8101 直传（首选）。失败返回 False，不阻塞。"""
    try:
        body = _json.dumps(report).encode("utf-8")
        req = _urllib.Request("http://127.0.0.1:8101/api/probe", data=body,
                              headers={"Content-Type": "application/json"})
        with _urllib.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                return _json.loads(resp.read().decode("utf-8")).get("ok", False)
    except Exception:
        pass
    return False

def main(argv):
    agent, custom, debug, rid = None, None, False, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--agent" and i + 1 < len(argv):
            agent, i = argv[i + 1], i + 1
        elif a == "--path" and i + 1 < len(argv):
            custom, i = argv[i + 1], i + 1
        elif a == "--debug":
            debug = True
        elif a == "--id" and i + 1 < len(argv):
            rid, i = argv[i + 1], i + 1
        i += 1
    if not agent:
        print("ERR: 需要 --agent <你的名字>（如 hermes/claude-code/trae/cursor/windsurf）")
        return 1
    import hashlib as _h
    rid = rid or _h.sha256((agent + _os.environ.get("USERNAME", "")).encode()).hexdigest()[:8].upper()

    data, hook_paths, writable_paths, already_injected, formats = _probe_agent(agent)
    if not data and not hook_paths and not custom:
        print("未探测到可上报的会话数据：可能 agent 名不对，或会话不在默认位置。")
        print("请找到它的会话文件/目录后重跑：python probe.py --agent <你的名字> --path <路径>")
        print("找不到就如实告诉用户，不要编造路径或上报码。")
        return 2
    if custom:
        p = _expand(custom)
        if _os.path.isfile(p):
            data.append({"kind": "manual", "path": p,
                         "format": "plaintext_sqlite" if _head(p) == _SQLITE_HEAD else "plaintext"})
        elif _os.path.isdir(p):
            data.append({"kind": "manual_dir", "path": p, "format": "plaintext"})
    # M2：每条来源标实际所在盘；报告带现场环境与路径集合指纹（重复上报去重用）
    for s in data:
        s["drive"] = _drive_of(s.get("path", ""))
    env = _env_brief()
    marker = "|".join(sorted({str(s.get("path", "")) for s in data}) + sorted(hook_paths))
    finder_hash = _h.sha256(marker.encode("utf-8")).hexdigest()[:16].upper()
    report = {
        "report_version": 2, "agent": agent, "at": "",
        "env": env, "finder_hash": finder_hash,
        "data_sources": data,
        "hook_surface": {"supported": bool(hook_paths), "ecosystem": agent,
                         "config_paths": hook_paths,
                         "writable_paths": writable_paths,
                         "already_injected": already_injected,
                         "formats": [{"path": p,
                                      "schema": formats.get(p, "unknown")}
                                     for p in hook_paths]},
    }
    code = _code(agent, rid, _class_of(data, hook_paths))
    if debug:
        print(_json.dumps(report, ensure_ascii=False, indent=2))
    if _post(agent, report):
        print("已上报 OK")
        return 0
    # 落盘兜底：写入默认数据目录 incoming（同机一般可写）
    home = _os.environ.get("EXPERIENTIA_HOME") or _os.path.join(
        _os.path.expanduser("~"), ".experientia")
    inc = _os.path.join(home, "incoming")
    try:
        _os.makedirs(inc, exist_ok=True)
        with open(_os.path.join(inc, code + ".json"), "w", encoding="utf-8") as fh:
            _json.dump(report, fh, ensure_ascii=False)
        print("上报码: " + code)
        print("把上面这一行码粘贴回 Experientia 连接页即可。")
    except OSError:
        print("上报码: " + code)
        print("本目录无法写入，请把码粘贴到 Experientia 连接页（码内已含定位信息）。")
    return 0

if __name__ == "__main__":
    _sys.exit(main(_sys.argv[1:]))
'''

SKILL_MD = """---
name: experientia-report
description: 向 Experientia 上报本 agent 的接入情报（数据位置/格式/官方 hook 注入点）。
  仅当 Experientia 连接页提示"此 agent 需上报接入"（即扫描覆盖不到、需兜底）时使用；
  运行后只回报一行结果码。用于接入新 agent 时让 Experientia 自动识别怎么捕获。
---

## When to Use
- Experientia 提示当前 agent 需要"上报接入"（会话文件扫描不到 / 加密 / 新生态）；
- 用户说"跑一下 experientia 上报 / 连接 Experientia"。
- 能直接被 Experientia 扫描到的 agent 不需要本 skill。

## Procedure
1. 确认你的身份：你是哪个 agent？用你自己的产品名（如 `hermes` / `trae` /
   `claude-code` / `cursor` / `windsurf` / `openclaw` / `codex`）。
2. 运行本 skill 附带的脚本（只读探测，不改任何东西）：
   - Python 可用：`python "<本 skill 目录>/scripts/probe.py" --agent <你的名字>`
   - 若无 Python：请如实告诉用户"环境无 Python，无法自动上报"，不要编造码。
3. 把脚本输出的**那一行**（`上报码: XXXX-XXXXXXXX-XXXX` 或 `已上报 OK`）原样转达用户，
   不做任何解释、不展开任何路径/文件头/探测细节。

## Pitfalls
- NEVER 把探测到的路径、文件头、数据库结构、本报告正文展示给用户或写进对话——只需转达
  脚本输出的那一行。
- 若脚本提示"未探测到可上报的会话数据"：先定位会话文件/目录（常见于 ~/.<你的名字>、
  %APPDATA%/<你的名字>、%LOCALAPPDATA%/<你的名字>），再加 `--path <路径>` 重跑；
  仍找不到就如实告诉用户，绝不编造路径或上报码。
- NEVER 修改、解密、拷贝任何 agent 数据文件（脚本本身只读）。
- NEVER 在输出中包含密钥、令牌、内部地址。
- 输出目标不一致时（用户说"记一笔经验"），当前版本不处理——如实转达用户等 Experientia
  的收尾提醒即可，不要自行发明格式。

## Verification
- 你的最终输出只有一行：脚本返回的上报码或"已上报 OK"，没有其它内容。
- 没有出现任何路径/文件头/长 JSON。
"""


def write_report_skill(target_dir: str | Path) -> Path:
    """把 experientia-report 写到 <target>/experientia-report/（幂等覆盖），返回 SKILL.md。"""
    root = Path(target_dir) / SKILL_DIRNAME
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    skill = root / "SKILL.md"
    skill.write_text(SKILL_MD, encoding="utf-8")
    (root / "scripts" / "probe.py").write_text(
        PROBE_TEMPLATE.replace("__AGENT_CANDIDATES__",
                               _json_dumps_candidates()),
        encoding="utf-8")
    return skill


_HOOK_KINDS = ("hook_config", "hook_dir", "hook_toml")


def _json_dumps_candidates() -> str:
    """把候选表序列化成 probe 模板内联的 {agent: {"data":[...], "hooks":[...]}} JSON。

    hook 类（hook_config 单文件配置 / hook_dir 代码型 hook 目录 / hook_toml
    TOML 型 hook 段）统一归 hooks 注入点（带 kind，接收端按 kind 定 schema）；
    其余（db/jsonl_dir/db_glob/config/plain…）归 data 数据源。
    """
    import json
    data = {}
    for agent, cands in _AGENT_CANDIDATES.items():
        data[agent] = {"data": [(p, k) for p, k in cands if k not in _HOOK_KINDS],
                       "hooks": [(p, k) for p, k in cands if k in _HOOK_KINDS]}
    return json.dumps(data, ensure_ascii=False)
