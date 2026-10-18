"""Kilo Code 会话解析器（T2 SQLite，官方文档口径——官方含 SQL 示例）。

格式：~/.local/share/kilo/kilo.db（Win %USERPROFILE%\\.local\\share\\kilo\\kilo.db；
KILO_DB / XDG_DATA_HOME 可覆盖）。
表：messages（m.data JSON，含 $.role）+ parts（p.data JSON，$.type/$.text/
$.synthetic/$.ignored）+ sessions。Kilo 为 opencode 系 fork，表结构与 OpenCode
同族（session/message/part 三表），解析按列探测容错。
旧版 VS Code globalStorage kilocode.kilo-code/ 布局未公开，不解析。
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

MESSAGE_TABLES = ("messages", "Message", "message")


def _db_path() -> Path:
    env = os.environ.get("KILO_DB")
    if env:
        return Path(env)
    if sys.platform == "win32":
        return Path.home() / ".local" / "share" / "kilo" / "kilo.db"
    xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg) / "kilo" / "kilo.db"


def _find_table(conn: sqlite3.Connection, candidates: tuple[str, ...]) -> str | None:
    for t in candidates:
        if table_exists(conn, t):
            return t
    return None


def parse_opencode_like_db(conn: sqlite3.Connection, agent_name: str,
                           message_table: str | None = None) -> list:
    """opencode 系三表结构（session/message/part）通用解析：
    message.data JSON = 消息（role + parts 数组），按 session_id 分组。
    goose/kilocode/opencode 复用。"""
    mt = message_table or _find_table(conn, MESSAGE_TABLES)
    if not mt:
        return []
    cols = table_columns(conn, mt) or []
    if not cols:
        return []
    data_col = next((c for c in cols if c.lower() in ("data", "content", "message")), None)
    sid_col = next((c for c in cols if c.lower() in ("session_id", "conversation_id",
                                                     "sessionid")), None)
    role_col = next((c for c in cols if c.lower() == "role"), None)
    time_col = next((c for c in cols if any(k in c.lower()
                                            for k in ("time_created", "created_at", "timestamp"))), None)
    if not data_col or not sid_col:
        return []
    select = [f"{data_col} AS data", f"{sid_col} AS sid"]
    if role_col:
        select.append(f"{role_col} AS role")
    if time_col:
        select.append(f"{time_col} AS ts")
    role_idx = 2 if role_col else None
    ts_idx = 3 if (role_col and time_col) else (2 if time_col else None)
    rows = conn.execute(f"SELECT {', '.join(select)} FROM {mt} ORDER BY rowid").fetchall()
    grouped: dict[str, list] = {}
    first_ts: dict[str, str | None] = {}
    for row in rows:
        data, sid = row[0], row[1]
        role_val = row[role_idx] if role_idx is not None else None
        ts = row[ts_idx] if ts_idx is not None else None
        blob = json_cell(data)
        if blob is None and isinstance(data, str) and data.strip():
            # 纯文本列（非 JSON）：有 role 列时降级为文本消息
            blob = {"role": role_val or "user", "content": data}
        if blob is None:
            continue
        if isinstance(blob, dict) and role_val and not blob.get("role"):
            blob = {**blob, "role": role_val}
        if sid not in grouped:
            grouped[sid] = []
            first_ts[sid] = ts if isinstance(ts, str) else None
        grouped[sid].append(blob)
    sessions = []
    for sid, blobs in grouped.items():
        s = build_session(agent_name, sid, {"messages": blobs},
                          started_at=first_ts.get(sid))
        if s:
            sessions.append(s)
    return sessions


class KiloCodeAdapter(AdapterBase):
    name = "kilocode"
    search_names = ["kilo", "kilocode", ".local/share/kilo"]

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
            return parse_opencode_like_db(conn, self.name)
        except sqlite3.Error:
            return []
        finally:
            conn.close()
