"""git / 文件系统交叉验证（蒸馏兜底方案）：给经验 bump 置信度。

外部实践把"验证"列为 non-negotiable——一条未验证的记忆比没有记忆更糟。
第一批只做两个低风险核对（纯确定性，无模型兜底里最值钱的质量底线）：
1. 经验 handles 里的文件路径是否存在；
2. 项目带 git 时，git log -S 关键词是否有提交佐证。

失败语义（防歪 #6）：无 git 目录 / 子进程失败 → 返回 0，不 raise、不杀流程。
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger("experientia.distill.verify")

# 文件路径（含相对路径 app/x.py；后缀白名单防把版本号/普通词当路径）
_PATH_HINT_RE = re.compile(
    r"(?:[A-Za-z]:[/\\])?[\w.-]+(?:[/\\][\w.-]+)*\."
    r"(?:py|ts|tsx|js|jsx|md|json|ya?ml|sql|sh|go|rs|java|toml)\b")
_WORD_RE = re.compile(r"[\w.-]{3,}")

BUMP_FILE_EXISTS = 0.1   # 文件路径存在
BUMP_GIT_EVIDENCE = 0.1  # git 提交佐证
MAX_BUMP = 0.2           # 单条经验置信度增量上限
_GIT_TIMEOUT = 10        # 秒


_GIT_ROOT_CACHE: dict[str, Path | None] = {}
_GIT_ROOT_CACHE_MAX = 64


def _git_root(project) -> Path | None:
    """M-N12: 带进程内缓存的 git 根目录查找——同一项目连续验证时避免重复查找。"""
    if not project:
        return None
    key = str(project)
    cached = _GIT_ROOT_CACHE.get(key)
    if cached is not None:
        return cached if cached.exists() else None
    p = Path(key).expanduser()
    if not p.exists():
        _GIT_ROOT_CACHE[key] = None
        if len(_GIT_ROOT_CACHE) > _GIT_ROOT_CACHE_MAX:
            _GIT_ROOT_CACHE.clear()
        return None
    cur = p
    for _ in range(8):  # 有限向上找 .git，防异常深路径
        if (cur / ".git").exists():
            _GIT_ROOT_CACHE[key] = cur
            if len(_GIT_ROOT_CACHE) > _GIT_ROOT_CACHE_MAX:
                _GIT_ROOT_CACHE.clear()
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    _GIT_ROOT_CACHE[key] = None
    if len(_GIT_ROOT_CACHE) > _GIT_ROOT_CACHE_MAX:
        _GIT_ROOT_CACHE.clear()
    return None


def _file_exists(exp: dict, project) -> bool:
    """经验正文/handles 里提到的文件路径，在项目下是否真实存在。"""
    if not project:
        return False
    base = Path(str(project)).expanduser()
    if not base.exists():
        return False
    blob = " ".join([
        *(exp.get("handles") or []),
        str(exp.get("action") or ""), str(exp.get("state") or ""),
    ])
    for m in _PATH_HINT_RE.finditer(blob):
        rel = m.group(0).replace("\\", "/").lstrip("/")
        if not rel or rel.startswith(("http", "/dev")):
            continue
        # 全路径直接查；相对路径在项目根下查
        cand = Path(m.group(0).replace("\\", "/"))
        if cand.is_absolute() and cand.exists():
            return True
        if (base / rel).exists():
            return True
    return False


def _git_evidence(exp: dict, git_root: Path) -> bool:
    """git 提交佐证：标识词命中的文件被提交过（路径核对），
    或 diff 内容里该词出现次数变化过（-S 内容核对）。

    -S 只搜 diff 内容不搜文件名，两层都要做；每词先路径后内容，命中即返回。
    """
    blob = " ".join([
        *(exp.get("handles") or []),
        str(exp.get("action") or ""), str(exp.get("state") or ""),
    ])
    # 优先把手里的路径末段/版本号，其次正文里的长词（防空命中）
    words = [Path(h).name for h in (exp.get("handles") or [])
             if Path(h).name and not Path(h).name.startswith(".")]
    words += [w for w in _WORD_RE.findall(blob) if len(w) >= 5][:3]
    for w in dict.fromkeys(words):  # 去重保序
        if not w or len(w) > 60:
            continue
        for args in (["git", "log", "--oneline", "--", f"*{w}*"],
                     ["git", "log", "--oneline", f"-S{w}", "--", "."]):
            try:
                r = subprocess.run(args, cwd=git_root, capture_output=True,
                                   timeout=_GIT_TIMEOUT)
            except (OSError, subprocess.SubprocessError, subprocess.CalledProcessError):
                return False
            if r.returncode == 0 and r.stdout.strip():
                return True
    return False


def verify_experience(store, exp: dict) -> float:
    """交叉验证置信度增量（0 ~ MAX_BUMP）。任何异常 → 0，不 raise。"""
    try:
        bump = 0.0
        project = exp.get("project")
        if _file_exists(exp, project):
            bump += BUMP_FILE_EXISTS
        root = _git_root(project)
        if root is not None and _git_evidence(exp, root):
            bump += BUMP_GIT_EVIDENCE
        return min(bump, MAX_BUMP)
    except Exception as exc:
        logger.warning("经验交叉验证失败（按 0 增量处理）: %s", exc)
        return 0.0
