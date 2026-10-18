"""归一化 schema——G 信号蒸馏只认这个 schema，不认原始格式。

    {agent, session_id, project, started_at,
     messages: [{role, content, tool_use?, tool_result?, ts?}],
     model?, tokens?}
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Message:
    role: str  # user / assistant / tool
    content: str = ""
    tool_use: dict | None = None        # {name, arguments, call_id}
    tool_result: dict | None = None     # {call_id, output}
    ts: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Session:
    agent: str
    session_id: str
    project: str | None = None
    started_at: str | None = None
    messages: list[Message] = field(default_factory=list)
    model: str | None = None
    tokens: int | None = None

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "session_id": self.session_id,
            "project": self.project,
            "started_at": self.started_at,
            "messages": [m.to_dict() for m in self.messages],
            "model": self.model,
            "tokens": self.tokens,
        }


@dataclass
class SessionRef:
    """一个待解析的原始会话文件。"""

    agent: str
    session_id: str
    path: Path
    size: int = 0
    mtime: float = 0.0
    encrypted: bool = False
    parse_error: str | None = None  # 解析失败原因，如 "encrypted"


class AdapterBase:
    """per-agent 解析器统一接口。"""

    name: str = ""

    def discover(self) -> list[SessionRef]:
        raise NotImplementedError

    def parse(self, ref: SessionRef) -> Session | None:
        raise NotImplementedError

    def parse_sessions(self, ref: SessionRef) -> list[Session]:
        """一个 ref 可能含多个会话（SQLite 类单库多会话）——默认 = 单会话解析。"""
        session = self.parse(ref)
        return [session] if session is not None else []
