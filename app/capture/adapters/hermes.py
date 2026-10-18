"""Hermes 会话解析器（T2，实测口径）。

home：Win %LOCALAPPDATA%\\hermes；其它平台 ~/.hermes（HERMES_HOME 可覆盖）。
真实形态（实测本机运行中的 Hermes，gateway harness）：
- state.db = **明文 SQLite**，规范化分列（不是整会话 JSON blob）：
  - sessions(id, source, model, started_at REAL epoch, cwd, git_repo_root,
             input_tokens/output_tokens/cache_*/reasoning_tokens, …)
  - messages(session_id, role, content, tool_call_id, tool_calls, tool_name,
             timestamp REAL epoch, active, compacted, …)
- messages.active=1 才是可见行（Hermes 自身迁移保证 NULL→1）；compacted 行跳过。
- 旧社区"整 JSON blob"schema（sessions.data 列）已不作主路径——探测到旧形态返回空，
  由黄标提示（格式漂移容错口径），不强解。
- 兜底保留：sessions/*.json（每文件一会话）+ 自动搜索常见路径。

注意：Hermes 跨模型 gateway（openai/ollama/codex 传输），tool_calls 列可能存
OpenAI 风格或扁平 {name, arguments} 风格，解析按容错处理；reasoning 类列不入 content
（避免污染 G 信号的口语正文），tool 结果内容截断（防 base64 大 payload）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

from ..models import AdapterBase, Message, Session, SessionRef
from ...time_util import utc_str
from .base_jsonl import search_common_locations
from .base_sqlite import (build_session, connect_ro, is_encrypted, json_cell,
                          table_columns, table_exists)

_CONTENT_LIMIT = 20000  # tool 结果截断上限（Hermes tool 行常为大段 base64）
_DB_SUFFIXES = (".db", ".sqlite", ".sqlite3")


def _home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return local / "hermes"
    return Path.home() / ".hermes"


def _iso(ts) -> str | None:
    """epoch REAL → 产品统一 UTC ISO（store 口径 %Y-%m-%dT%H:%M:%SZ）。"""
    if ts in (None, ""):
        return None
    try:
        f = float(ts)
    except (TypeError, ValueError):
        return None
    if f <= 0:  # Hermes 口径：0 表示"未设置"，不是 1970-01-01
        return None
    # 去重 R1：格式化交 time_util（而非本地 time.strftime + gmtime 组合）
    return utc_str(f)


def _text(value: object, limit: int = _CONTENT_LIMIT) -> str:
    """消息正文安全化：空 → ""，超长截断（防 base64 大 payload 拖垮复盘 digest）。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:
            return ""
    text = str(value)
    return text if len(text) <= limit else text[:limit]


def _iter_tool_calls(raw):
    """tool_calls 列容错遍历 → {name, arguments, call_id}。

    Hermes 跨传输网关：可能存 OpenAI 风格 list[{id,type,function:{name,arguments}}]、
    扁平 {name, arguments, id}、或 codex 风格单对象；也可能字符串化 JSON。
    """
    val = raw
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return
    items: list = []
    if isinstance(val, dict):
        nested = val.get("tool_calls") or val.get("calls")
        if isinstance(nested, list):
            items = nested
        else:
            items = [val]
    elif isinstance(val, list):
        items = val
    else:
        return
    for it in items:
        if not isinstance(it, dict):
            continue
        fn = it.get("function") if isinstance(it.get("function"), dict) else {}
        name = (it.get("name") or fn.get("name") or "").strip()
        args = it.get("arguments") or it.get("input") or it.get("args") or fn.get("arguments")
        if isinstance(args, (dict, list)):
            args = json.dumps(args, ensure_ascii=False)
        args = _text(args) if args not in (None, "") else ""
        cid = it.get("id") or it.get("call_id") or it.get("toolCallId") or ""
        if not name:
            continue
        yield {"name": name, "arguments": args, "call_id": str(cid)}


def _message_from_row(row) -> list[Message]:
    """Hermes messages 规范化行 → 归一化 Message 列表（一行可拆出多条，如 assistant
    带正文 + N 个工具调用）。system/developer/reasoning 类不入归一化（防污染 G 口径）。"""
    role = (row["role"] or "").lower()
    if role not in ("user", "assistant", "model", "tool", "function"):
        return []
    ts = _iso(row["timestamp"])
    if role in ("tool", "function"):
        content = _text(row["content"])
        # 空结果/空名字的工具回显行无复盘价值，跳过（不制造空 tool 噪声）
        if not content and not (row["tool_call_id"] or ""):
            return []
        return [Message(
            role="tool",
            tool_result={"call_id": _text(row["tool_call_id"], 500) or None,
                         "output": content},
            ts=ts,
        )]
    out: list[Message] = []
    content = _text(row["content"])
    if content:
        out.append(Message(role="assistant" if role == "model" else role,
                           content=content, ts=ts))
    if role in ("assistant", "model"):
        for tc in _iter_tool_calls(row["tool_calls"]):
            out.append(Message(role="assistant", tool_use=tc, ts=ts))
    return out


def _parse_normalized(conn: sqlite3.Connection) -> list[Session]:
    """规范化 schema：sessions × messages 行 → 归一化 Session 列表。"""
    cols_s = set(table_columns(conn, "sessions") or [])
    if not {"id", "started_at", "source"} <= cols_s:
        return []  # 旧 blob schema / 未知形态：不强解（交给黄标提示）
    cols_m = table_columns(conn, "messages") or []
    if not {"session_id", "role", "content", "timestamp"} <= set(cols_m):
        return []
    active_filter = "AND active = 1" if "active" in cols_m else ""
    srows = conn.execute(
        "SELECT id, source, model, started_at, cwd, git_repo_root, "
        "input_tokens, output_tokens, reasoning_tokens "
        "FROM sessions ORDER BY COALESCE(started_at, 0), id"
    ).fetchall()
    out: list[Session] = []
    for s in srows:
        msgs: list[Message] = []
        mrows = conn.execute(
            f"SELECT role, content, tool_call_id, tool_calls, timestamp "
            f"FROM messages WHERE session_id = ? {active_filter} "
            f"ORDER BY COALESCE(timestamp, 0), id",
            (s["id"],),
        ).fetchall()
        for r in mrows:
            msgs.extend(_message_from_row(r))
        if not msgs:
            continue  # 与 build_session 同语义：无消息的会话不进飞轮
        tok = sum(x or 0 for x in (s["input_tokens"], s["output_tokens"],
                                   s["reasoning_tokens"])) or None
        out.append(Session(
            agent="hermes",
            session_id=str(s["id"]),
            project=s["cwd"] or s["git_repo_root"],
            started_at=_iso(s["started_at"]),
            model=s["model"],
            tokens=tok,
            messages=msgs,
        ))
    return out


class HermesAdapter(AdapterBase):
    name = "hermes"
    search_names = ["hermes", "Hermes", ".hermes"]

    def discover(self) -> list[SessionRef]:
        home = _home()
        db = home / "state.db"
        if db.is_file():
            try:
                st = db.stat()
            except OSError:
                return []
            return [SessionRef(agent=self.name, session_id="state.db", path=db,
                               size=st.st_size, mtime=st.st_mtime)]
        sess_dir = home / "sessions"
        if sess_dir.is_dir():
            refs = []
            for f in sorted(sess_dir.glob("*.json")):
                try:
                    st = f.stat()
                except OSError:
                    continue
                refs.append(SessionRef(agent=self.name, session_id=f.stem, path=f,
                                       size=st.st_size, mtime=st.st_mtime))
            if refs:
                return refs
        for db_path in search_common_locations(["hermes", "Hermes"], ["state.db"]):
            try:
                st = db_path.stat()
            except OSError:
                continue
            return [SessionRef(agent=self.name, session_id="state.db", path=db_path,
                               size=st.st_size, mtime=st.st_mtime)]
        return []

    def _parse_json(self, ref: SessionRef) -> Session | None:
        """sessions/*.json 兜底：每文件一会话 {session_id?, messages:[…], created_at?}。"""
        blob = json_cell(ref.path.read_bytes())
        if not isinstance(blob, dict):
            return None
        sid = (blob.get("session_id") or blob.get("id")) if blob else None
        return build_session(self.name, sid or ref.path.stem, blob,
                             started_at=blob.get("created_at") or blob.get("started_at"),
                             model=blob.get("model"))

    def parse(self, ref: SessionRef) -> Session | None:
        if ref.path.suffix == ".json":
            return self._parse_json(ref)
        sessions = self.parse_sessions(ref)
        return sessions[0] if sessions else None

    def parse_sessions(self, ref: SessionRef) -> list[Session]:
        if ref.path.suffix == ".json":
            s = self._parse_json(ref)
            return [s] if s else []
        if is_encrypted(ref.path):
            return []  # 加密数据库，由调用方给出提示
        try:
            conn = connect_ro(ref.path)
        except sqlite3.Error:
            return []
        conn.row_factory = sqlite3.Row
        try:
            if not (table_exists(conn, "sessions") and table_exists(conn, "messages")):
                return []
            return _parse_normalized(conn)
        except sqlite3.Error:
            return []
        finally:
            conn.close()
