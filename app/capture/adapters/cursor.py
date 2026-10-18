"""Cursor 会话解析器（T2 VS Code KV，社区口径，**实验性**）。

路径：%APPDATA%\\Cursor\\User\\globalStorage\\state.vscdb（Win；
mac ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb）
ItemTable(key, value) 中 `cursorDiskKV.` 前缀的 KV 存 AI 会话：
  - cursorDiskKV.aichat.<session-uuid>      对话历史
  - cursorDiskKV.composer.<session-uuid>    Composer/Agent 会话
value 为整会话 JSON（结构未公开，按 messages/conversation 键容错）。
社区口径 + 结构未公开 → 实验性，黄标重点盯（schema 一变即静默跳过）。
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from ..models import AdapterBase, Session, SessionRef
from .base_sqlite import build_session, connect_ro, extract_messages, json_cell, parse_db_ref, table_exists

_PREFIXES = ("cursorDiskKV.aichat.", "cursorDiskKV.composer.")


def _db_path() -> Path | None:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Cursor"
    elif sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        base = appdata / "Cursor"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        base = Path(xdg) / "Cursor"
    db = base / "User" / "globalStorage" / "state.vscdb"
    return db if db.is_file() else None


class CursorAdapter(AdapterBase):
    name = "cursor"
    search_names = ["cursor", "Cursor"]

    def discover(self) -> list[SessionRef]:
        db = _db_path()
        if db is None:
            return []
        try:
            st = db.stat()
        except OSError:
            return []
        return [SessionRef(agent=self.name, session_id="state.vscdb", path=db,
                           size=st.st_size, mtime=st.st_mtime)]

    def parse(self, ref) -> Session | None:
        return parse_db_ref(self, ref)

    def parse_sessions(self, ref) -> list:
        try:
            conn = connect_ro(ref.path)
        except sqlite3.Error:
            return []
        try:
            if not table_exists(conn, "ItemTable"):
                return []
            sessions = []
            for key, value in conn.execute("SELECT key, value FROM ItemTable"):
                if not isinstance(key, str) or not key.startswith(_PREFIXES):
                    continue
                sid = next((key[len(pfx):] for pfx in _PREFIXES if key.startswith(pfx)), key)
                blob = json_cell(value)
                if blob is None:
                    continue
                if not extract_messages(blob):
                    continue
                sessions.append(build_session(self.name, sid, blob))
            return sessions
        except sqlite3.Error:
            return []
        finally:
            conn.close()
