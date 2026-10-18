"""Windsurf 会话解析器（T2 VS Code KV，社区口径，**实验性**）。

Windsurf 为 VS Code fork：`%APPDATA%\\Windsurf\\User\\globalStorage\\state.vscdb`
（mac ~/Library/Application Support/Windsurf/...；Linux 同 Cursor 模式）。
ItemTable 中 AI 会话键未公开 → 按 key 启发式（含 aichat/composer/chat/agent/
conversation 等）+ value 可抽取出消息才收录（宁可漏收，不可错收）。

Windsurf 的 trajectory `.pb` 文件使用 AES-256-GCM 加密，但密钥为全局硬编码：
`safeCodeiumworldKeYsecretBalloon`（32 字节 ASCII），所有用户共享。
此适配器自动检测并解密 `.pb` 文件。state.vscdb 本身不加密（明文 SQLite）。
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from ..models import AdapterBase, Session, SessionRef
from .base_sqlite import build_session, connect_ro, extract_messages, json_cell, parse_db_ref, table_exists

_KEY_HINTS = ("aichat", "composer", "chat", "agent", "conversation")

# Windsurf 硬编码 AES-256-GCM 密钥事实源收敛到 universal_decrypt（F-2 版本表化）。
# 本文件不再复制密钥——_decrypt_pb 运行时从 universal_decrypt.windsurf_known_keys() 取。

# 尝试导入 AES-GCM 解密库
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_AESGCM = True
except ImportError:
    HAS_AESGCM = False
    AESGCM = None


def _db_path() -> Path | None:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Windsurf"
    elif sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        base = appdata / "Windsurf"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        base = Path(xdg) / "Windsurf"
    for cand in (base / "User" / "globalStorage" / "state.vscdb",
                 base / "User" / "state.vscdb"):
        if cand.is_file():
            return cand
    return None


def _trajectory_dir() -> Path | None:
    """Windsurf trajectory 文件目录（加密的 .pb 文件）。"""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Windsurf"
    elif sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        base = appdata / "Windsurf"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        base = Path(xdg) / "Windsurf"
    td = base / "User" / "globalStorage" / "trajectory"
    if td.is_dir():
        return td
    return None


def _decrypt_pb(pb_path: Path) -> bytes | None:
    """解密 Windsurf 的 .pb 加密 trajectory 文件。

    格式：12 字节 nonce + AES-256-GCM 密文 + 16 字节 GCM tag，无 AAD。
    """
    if not HAS_AESGCM:
        return None
    import logging

    logger = logging.getLogger("experientia.capture.windsurf")
    from .universal_decrypt import windsurf_known_keys

    try:
        data = pb_path.read_bytes()
        if len(data) < 12 + 16:
            return None
        nonce = data[:12]
        ciphertext = data[12:]
    except Exception as exc:
        logger.debug("读取 .pb 失败 %s: %s", pb_path, exc)
        return None
    for version, key in enumerate(windsurf_known_keys(), 1):
        try:
            return AESGCM(key).decrypt(nonce, ciphertext, None)
        except Exception:
            continue  # 该版本 key 不符 → 尝试下一版本（F-2 回退）
    logger.debug("解密 .pb 失败 %s：全部已知 key 未命中（可能已升级换 key）", pb_path)
    return None


class WindsurfAdapter(AdapterBase):
    name = "windsurf"
    search_names = ["windsurf", "Windsurf"]

    def discover(self) -> list[SessionRef]:
        refs: list[SessionRef] = []
        db = _db_path()
        if db is not None:
            try:
                st = db.stat()
            except OSError:
                pass
            else:
                refs.append(SessionRef(agent=self.name, session_id="state.vscdb", path=db,
                                       size=st.st_size, mtime=st.st_mtime))
        # 也检测 trajectory 目录下的加密 .pb 文件
        td = _trajectory_dir()
        if td is not None:
            for f in sorted(td.glob("*.pb")):
                try:
                    st = f.stat()
                except OSError:
                    continue
                refs.append(SessionRef(agent=self.name, session_id=f.stem, path=f,
                                       size=st.st_size, mtime=st.st_mtime,
                                       encrypted=True, parse_error="encrypted"))
        return refs

    def parse(self, ref) -> Session | None:
        if ref.path.suffix == ".pb":
            # 空 ref 误计失败）：.pb 但调用方未标记 encrypted 时
            # 绝不能落到下面的 parse_db_ref——parse_db_ref 会回调 parse_sessions
            # 再次走 .pb 分支，形成 parse ↔ parse_db_ref 无限递归（空 .pb 实测
            # RecursionError 崩溃，被 scan 误计为解析失败）。空库/空文件契约：
            # 返回 []，不抛异常。这里直接按「不可解」返回 None。
            if not ref.encrypted:
                return None
            # 尝试解密 .pb 文件
            plain = _decrypt_pb(ref.path)
            if plain is None:
                return None
            # 解密后的 protobuf 数据暂不解析（需要 protobuf 定义），
            # 但至少返回一个标记会话，让用户知道轨迹文件已解密
            return Session(agent=self.name, session_id=ref.session_id, messages=[])
        # .db 走通用 parse_db_ref 模式（加密检测 + parse_sessions 兜底）
        return parse_db_ref(self, ref)

    def parse_sessions(self, ref) -> list:
        if ref.path.suffix == ".pb":
            s = self.parse(ref)
            return [s] if s is not None else []
        # state.vscdb - 明文 SQLite，同 Cursor 解析逻辑
        try:
            conn = connect_ro(ref.path)
        except sqlite3.Error:
            return []
        try:
            if not table_exists(conn, "ItemTable"):
                return []
            sessions = []
            for key, value in conn.execute("SELECT key, value FROM ItemTable"):
                if not isinstance(key, str):
                    continue
                lk = key.lower()
                if not any(h in lk for h in _KEY_HINTS):
                    continue
                blob = json_cell(value)
                if blob is None:
                    continue
                if not extract_messages(blob):
                    continue  # 启发式误中（普通 UI 状态）→ 不收
                sid = key.split(".")[-1] if "." in key else key
                sessions.append(build_session(self.name, sid, blob))
            return sessions
        except sqlite3.Error:
            return []
        finally:
            conn.close()