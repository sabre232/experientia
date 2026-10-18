"""Claude Code 会话解析器（T1，JSONL，官方文档口径）。

格式：~/.claude/projects/<编码路径>/<uuid>.jsonl（CLAUDE_CONFIG_DIR 可覆盖）
行类型：type=user/assistant/summary；message.content 为字符串或块数组
（text/tool_use/tool_result）；行内带 sessionId/cwd/gitBranch。
注意：Claude Code 默认 30 天自动清理（cleanupPeriodDays）→ 捕获即归档是刚需。
"""

from __future__ import annotations

from pathlib import Path

from .base_jsonl import ClaudeFamilyAdapter, _resolve_home


class ClaudeCodeAdapter(ClaudeFamilyAdapter):
    name = "claude-code"
    search_names = ["claude", "Claude", ".claude"]

    def session_roots(self) -> list[Path]:
        return [_resolve_home("CLAUDE_CONFIG_DIR", ".claude") / "projects"]
