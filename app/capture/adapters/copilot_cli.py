"""GitHub Copilot CLI 会话解析器（T2 JSON，社区口径，**实验性**）。

路径：~/.copilot/session-state（文件：JSON；目录：内含 *.json / *.jsonl）。
结构未公开 → 容错解析：
  - dict：按 messages/conversation/history 键抽消息
  - list：逐项当消息
  - .jsonl：逐行（裸消息或 {message:{...}} 包装）
抽不出消息即返回 None → 黄标机制兜底。
"""

from __future__ import annotations

from pathlib import Path

from ..models import AdapterBase, Session, SessionRef
from .base_sqlite import extract_messages, json_cell


def _root() -> Path:
    return Path.home() / ".copilot" / "session-state"


class CopilotCliAdapter(AdapterBase):
    name = "copilot-cli"
    search_names = ["copilot", ".copilot"]

    def discover(self) -> list[SessionRef]:
        r = _root()
        refs: list[SessionRef] = []
        if r.is_file():
            try:
                st = r.stat()
            except OSError:
                return []
            refs.append(SessionRef(agent=self.name, session_id="session-state",
                                   path=r, size=st.st_size, mtime=st.st_mtime))
        elif r.is_dir():
            for f in sorted(r.iterdir()):
                if not f.is_file() or f.suffix not in (".json", ".jsonl"):
                    continue
                try:
                    st = f.stat()
                except OSError:
                    continue
                refs.append(SessionRef(agent=self.name, session_id=f.stem, path=f,
                                       size=st.st_size, mtime=st.st_mtime))
        return refs

    def parse(self, ref) -> Session | None:
        try:
            raw = ref.path.read_bytes()
        except OSError:
            return None
        if ref.path.suffix == ".jsonl":
            messages = []
            for line in raw.decode("utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                blob = json_cell(line)
                if not isinstance(blob, dict):
                    continue
                inner = blob.get("message") if isinstance(blob.get("message"), dict) else blob
                messages.extend(extract_messages({"messages": [inner]}))
        else:
            blob = json_cell(raw)
            messages = extract_messages(blob)
        if not messages:
            return None
        return Session(agent=self.name, session_id=ref.session_id, messages=messages)

    def parse_sessions(self, ref) -> list:
        s = self.parse(ref)
        return [s] if s is not None else []
