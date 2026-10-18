"""DSH 会话解析器（T2 JSONL，社区口径，**实验性**）。

路径：~/.dsh/sessions/（DSH_HOME 可覆盖），每文件一会话的 JSONL。
行内可能是裸消息 {role, content} 或 Claude 族包装 {type, message:{...}}；
也可能出现分片行（shard 引用）——非消息行静默跳过。
社区口径 + 格式未公开 → 实验性，黄标重点盯。
"""

from __future__ import annotations

import os
from pathlib import Path

from ..models import AdapterBase, Session, SessionRef
from .base_sqlite import extract_messages, json_cell


def _sessions_dir() -> Path:
    env = os.environ.get("DSH_HOME")
    if env:
        return Path(env) / "sessions"
    return Path.home() / ".dsh" / "sessions"


class DshAdapter(AdapterBase):
    name = "dsh"
    search_names = ["dsh", ".dsh"]

    def session_roots(self) -> list[Path]:
        d = _sessions_dir()
        return [d] if d.is_dir() else []

    def discover(self) -> list[SessionRef]:
        refs: list[SessionRef] = []
        for f in sorted(_sessions_dir().glob("*.jsonl")) if _sessions_dir().is_dir() else []:
            try:
                st = f.stat()
            except OSError:
                continue
            refs.append(SessionRef(agent=self.name, session_id=f.stem, path=f,
                                   size=st.st_size, mtime=st.st_mtime))
        return refs

    def parse(self, ref) -> Session | None:
        try:
            text = ref.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        messages = []
        project = None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            blob = json_cell(line)
            if not isinstance(blob, dict):
                continue
            inner = blob.get("message") if isinstance(blob.get("message"), dict) else blob
            if project is None:
                project = blob.get("cwd") or (inner.get("cwd") if isinstance(inner, dict) else None)
            messages.extend(extract_messages({"messages": [inner]}))
        if not messages:
            return None
        return Session(agent=self.name, session_id=ref.session_id,
                       project=project, messages=messages)

    def parse_sessions(self, ref) -> list:
        s = self.parse(ref)
        return [s] if s is not None else []
