"""OpenCode 会话解析器（T2 SQLite，官方源码口径）。

现行：SQLite `opencode.db`
  - Win: %LOCALAPPDATA%\\opencode\\opencode.db
  - mac/linux: ~/.local/share/opencode/opencode.db（XDG_DATA_HOME 可覆盖）
  - dev channel: 同目录 `opencode-<channel>.db`（双探测）
表结构与 Kilo 同族（session/message/part，message.data JSON 含 role + parts）。
旧版（SQLite 引入前）为 `storage/` 下 JSON 目录布局：
  storage/session/<session_id>/...  + storage/message/<session_id>/*.json
  （每消息一 JSON：{id, session_id, role, parts:[...]}）——双探测，实验性。
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from ..models import AdapterBase, Session, SessionRef
from .base_sqlite import connect_ro, json_cell, parse_db_ref
from .kilocode import parse_opencode_like_db


def _data_roots() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        roots.append(local / "opencode")
    xdg = os.environ.get("XDG_DATA_HOME")
    roots.append(Path(xdg) / "opencode" if xdg else Path.home() / ".local" / "share" / "opencode")
    env = os.environ.get("OPENCODE_DATA")
    if env:
        roots.insert(0, Path(env))
    return roots


def _db_candidates() -> list[Path]:
    out: list[Path] = []
    for root in _data_roots():
        if not root.is_dir():
            continue
        main = root / "opencode.db"
        if main.is_file():
            out.append(main)
        out.extend(sorted(root.glob("opencode-*.db")))
    return out


class OpenCodeAdapter(AdapterBase):
    name = "opencode"
    search_names = ["opencode", "OpenCode", ".local/share/opencode"]

    def discover(self) -> list[SessionRef]:
        refs: list[SessionRef] = []
        seen: set[Path] = set()
        for db in _db_candidates():
            if db in seen:
                continue
            seen.add(db)
            try:
                st = db.stat()
            except OSError:
                continue
            refs.append(SessionRef(agent=self.name, session_id=db.stem, path=db,
                                   size=st.st_size, mtime=st.st_mtime))
        if refs:
            return refs
        # 旧版 JSON 布局双探测
        for root in _data_roots():
            storage = root / "storage"
            if (storage / "session").is_dir():
                try:
                    st = storage.stat()
                except OSError:
                    continue
                refs.append(SessionRef(agent=self.name, session_id="storage",
                                       path=storage, size=st.st_size, mtime=st.st_mtime))
        return refs

    def parse(self, ref) -> Session | None:
        return parse_db_ref(self, ref)

    def parse_sessions(self, ref) -> list:
        if ref.path.suffix == ".db":
            try:
                conn = connect_ro(ref.path)
                return parse_opencode_like_db(conn, self.name)
            except sqlite3.Error:
                return []
            finally:
                conn.close()
        return self._parse_legacy_storage(ref.path)

    def _parse_legacy_storage(self, storage: Path) -> list:
        """旧版 JSON 布局（实验性）：message/<session_id>/*.json 每消息一文件。"""
        by_session: dict[str, list] = {}
        msg_root = storage / "message"
        if msg_root.is_dir():
            for f in sorted(msg_root.glob("*/*.json")):
                blob = json_cell(f.read_bytes())
                if not isinstance(blob, dict):
                    continue
                sid = blob.get("session_id") or f.parent.name
                by_session.setdefault(str(sid), []).append(blob)
        # 会话元信息（标题/目录/时间），有则补
        meta_root = storage / "session"
        metas: dict[str, dict] = {}
        if meta_root.is_dir():
            for f in meta_root.glob("*/*.json"):
                blob = json_cell(f.read_bytes())
                if isinstance(blob, dict) and blob.get("id"):
                    metas[str(blob["id"])] = blob
        out = []
        for sid, blobs in by_session.items():
            blobs.sort(key=lambda b: (b.get("time") or {}).get("created", 0) if isinstance(b.get("time"), dict)
                       else (b.get("created_at") or ""))
            messages = []
            for b in blobs:
                messages.append({
                    "role": b.get("role"),
                    "parts": b.get("parts"),
                    "time_created": (b.get("time") or {}).get("created") if isinstance(b.get("time"), dict)
                    else b.get("created_at"),
                })
            from .base_sqlite import build_session

            meta = metas.get(sid, {})
            directory = meta.get("directory") or meta.get("path")
            s = build_session(self.name, sid, {"messages": messages}, project=directory)
            if s:
                out.append(s)
        return out
