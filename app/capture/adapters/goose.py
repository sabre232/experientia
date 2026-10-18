"""Goose（AAIF）会话解析器（T2 SQLite，官方文档口径）。

格式：~/.local/share/goose/sessions/sessions.db（v1.10+；
Win %APPDATA%\\Block\\goose\\data\\sessions\\sessions.db）
sessions 表：id/description/working_dir/created_at + transcript（JSON 列，
含 thinking、工具调用/结果、token 用量）。
旧版 per-session *.jsonl 格式未公开，不解析（黄标覆盖）。
官方兜底：`goose session export`（JSON/Markdown）。
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from ..models import AdapterBase, Session, SessionRef
from .base_sqlite import (
    build_session,
    connect_ro,
    json_cell,
    parse_db_ref,
    table_columns,
    table_exists,
)


def _db_path() -> Path:
    env = os.environ.get("GOOSE_HOME")
    if env:
        return Path(env) / "sessions" / "sessions.db"
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return appdata / "Block" / "goose" / "data" / "sessions" / "sessions.db"
    return Path.home() / ".local" / "share" / "goose" / "sessions" / "sessions.db"


class GooseAdapter(AdapterBase):
    name = "goose"
    search_names = ["goose", "Block\\goose"]

    def discover(self) -> list[SessionRef]:
        db = _db_path()
        if not db.is_file():
            return []
        try:
            st = db.stat()
        except OSError:
            return []
        return [SessionRef(agent=self.name, session_id=db.stem, path=db,
                           size=st.st_size, mtime=st.st_mtime)]

    def parse(self, ref) -> Session | None:
        return parse_db_ref(self, ref)

    def parse_sessions(self, ref) -> list:
        try:
            conn = connect_ro(ref.path)
        except sqlite3.Error:
            return []
        try:
            if not table_exists(conn, "sessions"):
                return []
            cols = table_columns(conn, "sessions") or []
            id_col = "id" if "id" in cols else (cols[0] if cols else None)
            blob_col = next(
                (c for c in cols
                 if any(k in c.lower() for k in ("transcript", "messages", "content", "data"))),
                None,
            )
            ts_col = next((c for c in cols if any(k in c.lower()
                                                  for k in ("created", "timestamp", "time"))), None)
            wd_col = next((c for c in cols if any(k in c.lower()
                                                  for k in ("dir", "path", "workspace"))), None)
            if not id_col or not blob_col:
                return []
            query_cols = [id_col, blob_col] + ([ts_col] if ts_col else []) + ([wd_col] if wd_col else [])
            sessions = []
            for row in conn.execute(f"SELECT {', '.join(query_cols)} FROM sessions"):
                sid, blob = row[0], row[1]
                ts = row[2] if ts_col else None
                wd = row[3] if wd_col else None
                s = build_session(self.name, sid, json_cell(blob), project=wd,
                                  started_at=ts if isinstance(ts, str) else None)
                if s:
                    sessions.append(s)
            return sessions
        except sqlite3.Error:
            return []
        finally:
            conn.close()
