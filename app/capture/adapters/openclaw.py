"""OpenClaw（Clawdbot/Moltbot）会话解析器（T1，JSONL，官方文档口径）。

格式：~/.openclaw/agents/<agentId>/sessions/<sessionId>.jsonl（归档转录，
与 Claude Code 系同构）；同目录 agent/openclaw-agent.sqlite 为运行时行，
JSONL 归档是解析主对象。
注意：自带 30 天维护清理（session.maintenance.pruneAfter 默认 30d）→ 捕获即归档。
OPENCLAW_STATE_DIR 可覆盖 home。
"""

from __future__ import annotations

from pathlib import Path

from .base_jsonl import ClaudeFamilyAdapter, _resolve_home


class OpenClawAdapter(ClaudeFamilyAdapter):
    name = "openclaw"
    glob_pattern = "*/sessions/*.jsonl"
    search_names = ["openclaw", "OpenClaw", ".openclaw"]

    def session_roots(self) -> list[Path]:
        return [_resolve_home("OPENCLAW_STATE_DIR", ".openclaw") / "agents"]
