"""按系统进程探测"当前正在运行的 coding agent"（首页状态行用）。

思路（用户拍板：简单粗暴）：直接看进程表里有没有已知 agent 的主程序名，
有就是"正在运行"。规则：
- 只认**主进程名**（进程名包含产品关键词，如 "CodeBuddy CN.exe"→codebuddy、
  "TRAE SOLO CN.exe"→trae）；忽略 pythonw/node/agent-tool-host 等运行时子进程
  （CodeBuddy 的后台跑在 ~/.workbuddy/…，那不算 WorkBuddy 在跑）；
- CodeBuddy 与 WorkBuddy 存在历史改名关系：CodeBuddy 命中时不再叠加 WorkBuddy，
  避免同一套运行时被双算。

Windows 用 tasklist、其他平台用 ps；纯标准库；结果 8s 模块级缓存；
任何异常静默返回空（探测失败不打扰 UI）。
"""

from __future__ import annotations

import os
import subprocess
import time

# agent key -> 主进程名关键词（小写，命中即算该 agent 在跑）
_MAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "codebuddy": ("codebuddy",),
    "trae": ("trae",),
    "cursor": ("cursor",),
    "qclaw": ("qclaw",),
    "windsurf": ("windsurf",),
    "workbuddy": ("workbuddy",),  # 仅当没有 codebuddy 命中时才可能保留（改名关系）
}

_cache: dict = {"ts": 0.0, "running": []}
_TTL = 8.0


def running_agents() -> list[str]:
    """返回当前正在运行的已知 agent 的内部 key（按 _MAIN_KEYWORDS 序）。"""
    now = time.monotonic()
    if now - _cache["ts"] < _TTL:
        return list(_cache["running"])
    try:
        names = _process_names()
    except Exception:
        names = set()
    found: list[str] = []
    for key, keywords in _MAIN_KEYWORDS.items():
        if any(k in name for name in names for k in keywords):
            if key not in found:
                found.append(key)
    # CodeBuddy 存在时 WorkBuddy 大概率是同套改名，不再叠加
    if "codebuddy" in found and "workbuddy" in found:
        found = [k for k in found if k != "workbuddy"]
    _cache.update(ts=now, running=found)
    return list(found)


def _process_names() -> set[str]:
    """进程名集合（小写，不含自己）。"""
    try:
        if os.name == "nt":
            flags = 0x08000000  # CREATE_NO_WINDOW：探测时不闪黑框
            out = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
                creationflags=flags, check=False).stdout or ""
            names = set()
            for line in out.splitlines():
                if '"' not in line:
                    continue
                name = line.split('"', 2)[1].strip().lower()
                if name:
                    names.add(name)
            return names
        out = subprocess.run(
            ["ps", "-eo", "comm="],
            capture_output=True, text=True, timeout=5, check=False).stdout or ""
        return {os.path.basename(p.strip()).lower()
                for p in out.splitlines() if p.strip()}
    except Exception:
        return set()
