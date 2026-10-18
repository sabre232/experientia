"""CodeBuddy CLI（腾讯）会话解析器（T1，JSONL，官方目录文档口径）。

格式：~/.codebuddy/projects/**/*.jsonl（项目会话记录）；
~/.codebuddy/history.jsonl 为全局历史（resume 用），非会话文件，不作解析对象。
CODEBUDDY_HOME 可覆盖。字段未公开，按 Claude 系容错解析。
"""

from __future__ import annotations

from pathlib import Path

from .base_jsonl import ClaudeFamilyAdapter, _resolve_home


class CodeBuddyAdapter(ClaudeFamilyAdapter):
    name = "codebuddy"
    search_names = ["codebuddy", "CodeBuddy", "codebuddy-cli"]

    def session_roots(self) -> list[Path]:
        return [_resolve_home("CODEBUDDY_HOME", ".codebuddy") / "projects"]
