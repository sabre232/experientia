"""Zed 会话解析器（T2 SQLite，官方源码口径）。

平台数据目录下的 `threads/threads.db`：
  - macOS: ~/Library/Application Support/zed
  - Win:   %APPDATA%\\Zed
  - Linux: ~/.config/zed（XDG_CONFIG_HOME 可覆盖）
threads 表：id + data 列（整 thread 序列化 JSON，内含消息与工具调用）。
表名/列名按 PRAGMA 探测（格式漂移容错 → 空 → 黄标）。
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from ..models import AdapterBase, Session, SessionRef
from .base_sqlite import build_session, connect_ro, json_cell, parse_db_ref, table_columns, table_exists


def _data_dir() -> Path | None:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "zed"
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return appdata / "Zed"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) / "zed" if xdg else Path.home() / ".config" / "zed"


class ZedAdapter(AdapterBase):
    name = "zed"
    search_names = ["zed", "Zed"]

    def discover(self) -> list[SessionRef]:
        base = _data_dir()
        if base is None:
            return []
        db = base / "threads" / "threads.db"
        if not db.is_file():
            return []
        try:
            st = db.stat()
        except OSError:
            return []
        return [SessionRef(agent=self.name, session_id="threads.db", path=db,
                           size=st.st_size, mtime=st.st_mtime)]

    def parse(self, ref) -> Session | None:
        return parse_db_ref(self, ref)

    def parse_sessions(self, ref) -> list:
        try:
            conn = connect_ro(ref.path)
        except sqlite3.Error:
            return []
        try:
            table = next((t for t in ("threads", "Threads", "thread") if table_exists(conn, t)), None)
            if not table:
                return []
            cols = table_columns(conn, table) or []
            id_col = "id" if "id" in cols else (cols[0] if cols else None)
            blob_col = next((c for c in cols if c.lower() in ("data", "thread", "json")), None)
            if not id_col or not blob_col:
                return []
            sessions = []
            for row in conn.execute(f"SELECT {id_col}, {blob_col} FROM {table}"):
                s = build_session(self.name, row[0], json_cell(row[1]))
                if s:
                    sessions.append(s)
            return sessions
        except sqlite3.Error:
            return []
        finally:
            conn.close()
