"""Aider 会话解析器（T1，Markdown，官方口径）。

格式：仓库根 .aider.chat.history.md（非 git 目录在 cwd）——聊天 Markdown 日志：
  ## [ 10:00:00] gpt-4o
  **User:** ...
  **Assistant:** ...
发现策略：会话文件散落在各仓库根，无法自动全知——
config.json 的 `aider_scan_roots`（list[str]）配置扫描根列表，
未配置则**不探测**（不再回落用户主目录——os.walk 整棵家目录含 AppData
实测 1.7s 且结果恒为空；真正在用 Aider 的用户需显式配置扫描根）。
用户可加自定义目录。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from pathlib import Path

from ..models import AdapterBase, Message, Session, SessionRef

logger = logging.getLogger("experientia.capture.adapters.aider")

_HEADER_RE = re.compile(r"^## \[(?P<ts>[^\]]+)\] ?(?P<model>.+?)\s*$")
_ROLE_RE = re.compile(r"^\*\*(?P<role>User|Assistant):\*\* ?(?P<text>.*)$", re.DOTALL)

MAX_DEPTH = 6
_HIST_NAME = ".aider.chat.history.md"

# /：配置按进程短 TTL 缓存——原先 _scan_roots 每轮探测都 Store() 一个新
# 实例只为读 config（aider.py:35）。捕获开关/扫描根属低频变更，60s TTL 足够；
# run_scan 每轮仍会自行读 config 做 enabled 过滤（与这里的提前短路互为冗余）。
_CONFIG_TTL = 60.0
_config_cache: tuple[float, dict] | None = None
_no_roots_logged = False


def _load_config() -> dict:
    global _config_cache
    now = time.monotonic()
    hit = _config_cache
    if hit is not None and now - hit[0] <= _CONFIG_TTL:
        return hit[1]
    try:
        from ...store.store import Store  # adapters/ 下三级：app.capture.adapters → app

        cfg = Store().load_config()
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception as exc:
        # 配置读不到只影响本轮探测范围，留痕不拦死；不回落 home
        logger.warning("读取 aider 配置失败（本轮跳过探测）：%s", exc)
        cfg = {}
    _config_cache = (now, cfg)
    return cfg


def _aider_enabled(cfg: dict) -> bool:
    """capture.enabled.aider 显式禁用 → 跳过（缺省启用，与 config_schema 同口径）。"""
    return (cfg.get("capture") or {}).get("enabled", {}).get("aider", True) is not False


def _scan_roots(cfg: dict) -> list[Path]:
    """aider_scan_roots 配置的扫描根；未配置返回 []（不再回落 Path.home()）。"""
    global _no_roots_logged
    roots = cfg.get("aider_scan_roots") or []
    if isinstance(roots, str):
        roots = [roots]
    roots = [str(r) for r in roots if str(r).strip()]
    if roots:
        return [Path(r).expanduser() for r in roots]
    if not _no_roots_logged:
        _no_roots_logged = True
        logger.info("未配置 aider_scan_roots，已跳过 Aider 探测")
    return []


def _session_id_for(repo_dir: Path) -> str:
    """低1b：目录名 → 不同位置的同名仓库互相覆盖（sessions.jsonl 按
    (agent, session_id) 去重）。= 仓库目录名 + 全路径 sha1 前 8 位区分。

    **别把 resolve() 去掉**：它会把符号链接收敛到真实路径，同一仓库经不同路径
    写法访问时得到同一个 id。本函数的产出是**落库数据**（sessions.jsonl 的去重
    键），一旦口径变更，历史会话会全部算出新 id → 去重失效、会话重复计数。
    形似的另一份是 base_sqlite._decrypted_tmp_name（算临时文件名，不做 resolve），
    两者看着重复但语义不同，请勿合并。
    """
    h = hashlib.sha1(str(repo_dir.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{repo_dir.name}-{h}"


def _iter_history_files(root: Path, max_depth: int = MAX_DEPTH):
    """限深遍历（低1a：rglob 无法阻止遍历只能事后过滤——每 60s 等于把
    home 目录含 AppData 全扫一遍；os.walk 到达深度上限即停止下钻）。

    与旧 rglob 口径一致：文件相对 root 的 parts ≤ max_depth 才收。
    """
    root_s = str(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root_s)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth >= max_depth:
            dirnames[:] = []  # 本层文件的 parts = depth+1 > max_depth，下层更深
            continue
        if _HIST_NAME in filenames:
            yield Path(dirpath) / _HIST_NAME


class AiderAdapter(AdapterBase):
    name = "aider"
    search_names = ["aider", ".aider"]

    def discover(self) -> list[SessionRef]:
        cfg = _load_config()
        if not _aider_enabled(cfg):
            return []
        refs: list[SessionRef] = []
        seen: set[str] = set()
        for root in _scan_roots(cfg):
            if not root.is_dir():
                continue
            try:
                candidates = _iter_history_files(root)
            except OSError:
                continue
            for path in sorted(candidates):
                if not path.is_file():
                    continue
                key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    st = path.stat()
                except OSError:
                    continue
                refs.append(
                    SessionRef(
                        agent=self.name,
                        session_id=_session_id_for(path.parent),
                        path=path,
                        size=st.st_size,
                        mtime=st.st_mtime,
                    )
                )
        return refs

    def parse(self, ref: SessionRef) -> Session | None:
        try:
            text = ref.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        session = Session(agent=self.name, session_id=ref.session_id)
        session.project = str(ref.path.parent)
        role: str | None = None
        buf: list[str] = []

        def _flush() -> None:
            nonlocal role, buf
            if role:
                content = "\n".join(buf).strip()
                if content:
                    session.messages.append(Message(role=role, content=content))
            role, buf = None, []

        for line in text.splitlines():
            m = _HEADER_RE.match(line)
            if m:
                _flush()
                # 低1c：model 取首个 header（多模型会话不被最后一个覆盖）
                if m.group("model") and not session.model:
                    session.model = m.group("model").strip()
                if not session.started_at and m.group("ts"):
                    session.started_at = m.group("ts").strip()
                continue
            r = _ROLE_RE.match(line)
            if r:
                _flush()
                role = "user" if r.group("role") == "User" else "assistant"
                first = r.group("text").strip()
                if first:
                    buf.append(first)
                continue
            if role:
                buf.append(line)
        _flush()
        return session if session.messages else None
