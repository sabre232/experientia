"""Gemini CLI 系会话解析器（T1 单 JSON，官方文档口径 + fork 关系确认）。

格式：~/.gemini/tmp/<项目hash>/chats/*.json——整会话一个 Chat JSON：
  {messages: [{role, parts: [{text} | {functionCall} | {functionResponse}],
              timestamp, usageMetadata?}], startTime?, projectHash?}
（GenAI parts 格式：text / functionCall / functionResponse）

三家共用本解析器，home 参数化：
  - gemini-cli：~/.gemini（官方，默认 30 天自动清理 → 捕获即归档）
  - qwen-code：~/.qwen（官方确认 fork 自 gemini-cli v0.8.2 → 结构同构）
  - iflow：~/.iflow（README 确认 fork 关系；路径社区口径 → 实验性）
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..models import Message, Session
from .base_jsonl import JsonlAdapterBase, _text_of


class GeminiFamilyAdapter(JsonlAdapterBase):
    """Gemini CLI 系：discover 走基类 glob 骨架，parse 整体读 Chat JSON。"""

    name: str = ""
    home_dir: str = ".gemini"
    home_env: str | None = None
    glob_pattern = "*/chats/*.json"

    def _home(self) -> Path:
        if self.home_env:
            v = os.environ.get(self.home_env)
            if v:
                return Path(v)
        return Path.home() / self.home_dir

    def session_roots(self) -> list[Path]:
        return [self._home() / "tmp"]

    def parse(self, ref) -> Session | None:
        try:
            data = json.loads(ref.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(data, list):
            msgs, meta = data, {}
        elif isinstance(data, dict):
            msgs = (
                data.get("messages")
                or data.get("conversation")
                or data.get("history")
                or []
            )
            meta = data
        else:
            return None
        session = Session(agent=self.name, session_id=ref.session_id)
        session.started_at = meta.get("startTime") or meta.get("start_time")
        project = meta.get("projectHash") or meta.get("project_hash")
        if isinstance(project, str) and project:
            session.project = project
        total_tokens = 0
        for m in msgs if isinstance(msgs, list) else []:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            if role == "model":
                role = "assistant"
            if role not in ("user", "assistant"):
                continue
            ts = m.get("timestamp") or m.get("ts")
            parts = m.get("parts")
            if not isinstance(parts, list):
                text = _text_of(m.get("content"))
                if text:
                    session.messages.append(Message(role=role, content=text, ts=ts))
                continue
            for p in parts:
                if not isinstance(p, dict):
                    continue
                if p.get("text"):
                    session.messages.append(
                        Message(role=role, content=p["text"], ts=ts)
                    )
                elif fc := p.get("functionCall"):
                    session.messages.append(
                        Message(
                            role="assistant",
                            tool_use={
                                "name": fc.get("name"),
                                "arguments": fc.get("args"),
                                "call_id": fc.get("id"),
                            },
                            ts=ts,
                        )
                    )
                elif fr := p.get("functionResponse"):
                    session.messages.append(
                        Message(
                            role="tool",
                            tool_result={
                                "call_id": None,
                                "output": json.dumps(fr.get("response"), ensure_ascii=False)
                                if isinstance(fr.get("response"), (dict, list))
                                else str(fr.get("response") or ""),
                            },
                            ts=ts,
                        )
                    )
            um = m.get("usageMetadata")
            if isinstance(um, dict):
                t = um.get("totalTokenCount")
                if isinstance(t, (int, float)):
                    total_tokens += int(t)
        if total_tokens:
            session.tokens = total_tokens
        return session if session.messages else None


class GeminiCliAdapter(GeminiFamilyAdapter):
    name = "gemini-cli"
    home_dir = ".gemini"
    home_env = "GEMINI_CLI_HOME"
    search_names = ["gemini", ".gemini"]


class QwenCodeAdapter(GeminiFamilyAdapter):
    name = "qwen-code"
    home_dir = ".qwen"
    home_env = "QWEN_HOME"
    search_names = ["qwen", ".qwen"]


class IflowAdapter(GeminiFamilyAdapter):
    name = "iflow"
    home_dir = ".iflow"
    home_env = "IFLOW_HOME"
    search_names = ["iflow", ".iflow"]
