"""hook 配置位置通用启发式发现（app 端本地使用；skill probe 有自包含内联副本）。

有界扫描 agent 配置根：同族目录映射表 + 用户目录下同名/点号目录 +
Windows %LOCALAPPDATA%/%APPDATA% 同名目录；每根只扫两层、只认白名单文件名，
读文件内容判 schema（不靠文件名，防把普通 settings 误认成 hook 配置）：
- json_hooks：顶层是 hooks 映射的 JSON
- toml_hooks：TOML 含 [hooks] 表或 hooks. 键
- hook_dir：hooks/<名>/HOOK.yaml 目录型

只读、有界（≤6 根 × 2 层 × 256KB 文件上限）。用途：resolve_agent 的 ③ 级兜底——
本机安装的 agent（app 能看见它的文件）无需 skill 自报往返即可列出管理。
与 report_skill probe 模板内联的同名启发式保持同步（模板副本须自包含，故两份）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

_FAMILY_ROOTS = {
    "claude-code": [".claude"], "claude": [".claude"],
    # codex：本体 config.toml + 已安装插件（plugins/<名>/hooks.json）+
    # 市场缓存解包区（.tmp/plugins/plugins/<名>/hooks.json，未安装即未生效，
    # 列出来供用户核对"之前留下的 hook"）
    "codex": [".codex", ".codex/plugins", ".codex/.tmp/plugins/plugins"],
    "workbuddy": [".workbuddy"],
    "codebuddy": [".codebuddy"], "cursor": [".cursor"],
    "windsurf": [".codeium", ".windsurf"], "gemini-cli": [".gemini"],
    "qoder": [".qoder"], "iflow": [".iflow"], "opencode": [".config/opencode"],
    "openclaw": [".openclaw"], "aider": [".aider"],
}
_HOOK_FILE_NAMES = ("settings.json", "hooks.json", "config.json",
                    "config.toml", "openclaw.json", "plugin.json")


def hook_schema_file(path: str) -> str | None:
    """文件内容 → hook schema（json_hooks/toml_hooks/None）；只读、有大小上限。"""
    try:
        if os.path.getsize(path) > 262144:
            return None
        low = str(path).lower()
        if low.endswith(".toml"):
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for ln in fh.read(65536).splitlines():
                    s = ln.strip()
                    if s.startswith("[hooks") or s.startswith("hooks."):
                        return "toml_hooks"
            return None
        if low.endswith(".json"):
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and isinstance(data.get("hooks"), dict):
                return "json_hooks"
    except (OSError, json.JSONDecodeError):
        pass
    return None


def discover_hooks(agent: str, home: str | Path | None = None) -> list[tuple[str, str]]:
    """有界扫描 agent 配置根找 hook 配置/目录（只读）→ [(path, schema)]。

    本机没装该 agent → 返回空（调用方据此落"未知"分支）。
    """
    home_p = Path(home) if home else Path.home()
    name = str(agent or "").lower()
    # name 直接拼进路径分量（含 URL 传入的 ../ 之类）——
    # 非法名一律按"本机没装该 agent"处理（返回空），不做任何路径拼接。
    if not re.fullmatch(r"[a-z0-9_-]+", name):
        return []
    roots = [home_p / rel for rel in _FAMILY_ROOTS.get(name, [])]
    for var in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(var) or ""
        if base and name:
            roots.append(Path(base) / name)
    if name:
        roots.append(home_p / ("." + name))
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _check_dir(d: Path) -> None:
        try:
            names = os.listdir(d)
        except OSError:
            return
        for fn in names:
            p = d / fn
            if not p.is_file() or fn not in _HOOK_FILE_NAMES:
                continue
            sch = hook_schema_file(str(p))
            if sch and str(p) not in seen:
                seen.add(str(p))
                out.append((str(p), sch))
        hd = d / "hooks"
        if hd.is_dir():
            try:
                subs = os.listdir(hd)
            except OSError:
                subs = []
            for dd in sorted(subs)[:40]:
                if (hd / dd / "HOOK.yaml").is_file():
                    if str(hd) not in seen:
                        seen.add(str(hd))
                        out.append((str(hd), "hook_dir"))
                    break

    for root in roots[:6]:
        if not root.is_dir():
            continue
        _check_dir(root)
        try:
            # 200：codex 市场缓存实测 181 个插件目录（replayio 在第 137 位），
            # 每目录仅一次 os.listdir，开销可忽略
            subs = sorted(os.listdir(root))[:200]
        except OSError:
            subs = []
        for sub in subs:
            if len(out) >= 20:
                break
            sp = root / sub
            if sp.is_dir():
                _check_dir(sp)
        if len(out) >= 20:
            break
    return out
