"""OpenHands 会话解析器（T2 事件流，SDK 官方 + 社区口径）。

布局：~/.openhands/conversations/<conversation_id>/
  - base_state.json   会话元信息（conversation_id / directory / ...）
  - events/*.json     事件流，每事件一 JSON：
      MessageEvent  {event_type:"message", role, message}
      ActionEvent   {event_type:"action", action:{name, args}}
      ObservationEvent {event_type:"observation", observation:{...}}
  文件名含序号前缀（如 0001_message.json）保证顺序；无前缀按文件名字典序。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import AdapterBase, Message, Session, SessionRef
from .base_sqlite import json_cell

_SEQ_RE = re.compile(r"^(\d+)")


def _conv_root() -> Path:
    return Path.home() / ".openhands" / "conversations"


def _dir_signature(d: Path) -> tuple[int, float] | None:
    """目录签名 = 会话文件（base_state.json + events/*.json）总大小 + 最大 mtime。

    不能用父目录 stat：事件追加在 events/ 子目录内，不改变 conversations/<id>/ 的
    目录 mtime，进行中的会话首次扫描后签名永不变化 → 后续轮询全部跳过。
    """
    size, mtime = 0, 0.0
    event_files = sorted((d / "events").glob("*.json")) if (d / "events").is_dir() else []
    for f in [d / "base_state.json", *event_files]:
        try:
            st = f.stat()
        except OSError:
            continue
        size += st.st_size
        mtime = max(mtime, st.st_mtime)
    return (size, mtime) if size else None


class OpenHandsAdapter(AdapterBase):
    name = "openhands"
    search_names = ["openhands", ".openhands"]

    def discover(self) -> list[SessionRef]:
        root = _conv_root()
        if not root.is_dir():
            return []
        refs = []
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            if not (d / "base_state.json").is_file() and not (d / "events").is_dir():
                continue
            sig = _dir_signature(d)
            if sig is None:
                continue
            refs.append(SessionRef(agent=self.name, session_id=d.name, path=d,
                                   size=sig[0], mtime=sig[1]))
        return refs

    def parse_sessions(self, ref) -> list:
        session = self._parse_dir(ref.path)
        return [session] if session is not None else []

    def parse(self, ref) -> Session | None:
        return self._parse_dir(ref.path)

    def _parse_dir(self, d: Path) -> Session | None:
        base = json_cell((d / "base_state.json").read_bytes()) if (d / "base_state.json").is_file() else None
        sid = d.name
        project = None
        started_at = None
        if isinstance(base, dict):
            sid = str(base.get("conversation_id") or d.name)
            project = base.get("directory") or base.get("workspace")
            started_at = base.get("created_at") or base.get("time")

        def _seq(path: Path) -> int:
            m = _SEQ_RE.match(path.name)
            return int(m.group(1)) if m else 1 << 30

        messages: list[Message] = []
        events_dir = d / "events"
        if events_dir.is_dir():
            for f in sorted(events_dir.glob("*.json"), key=_seq):
                ev = json_cell(f.read_bytes())
                if not isinstance(ev, dict):
                    continue
                et = ev.get("event_type") or ev.get("type")
                if et == "message":
                    role = ev.get("role")
                    text = ev.get("message") or ev.get("content")
                    if role in ("user", "assistant") and isinstance(text, str) and text:
                        messages.append(Message(role=role, content=text))
                elif et == "action":
                    a = ev.get("action")
                    if isinstance(a, dict):
                        messages.append(Message(
                            role="assistant",
                            tool_use={"name": a.get("name") or a.get("action"),
                                      "arguments": a.get("args") or a.get("input"),
                                      "call_id": a.get("action_id")},
                        ))
                elif et == "observation":
                    o = ev.get("observation")
                    if isinstance(o, dict):
                        out = o.get("content") or o.get("observation") or o.get("exit_code")
                        if isinstance(out, (list, dict)):
                            import json as _json

                            out = _json.dumps(out, ensure_ascii=False)
                        messages.append(Message(role="tool",
                                                tool_result={"call_id": o.get("action_id"),
                                                             "output": str(out) if out is not None else ""}))
        if not messages:
            return None
        return Session(agent=self.name, session_id=sid, project=project,
                       started_at=started_at, messages=messages)
