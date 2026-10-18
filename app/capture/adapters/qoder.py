"""Qoder CLI 会话解析器（T1，JSONL，官方文档口径）。

格式：~/.qoder/projects/<编码路径>/<session-id>.jsonl + 同目录 state.json
（会话状态，不作解析对象）；QODER_CONFIG_DIR 可覆盖根。
"""

from __future__ import annotations

from pathlib import Path

from .base_jsonl import ClaudeFamilyAdapter, _resolve_home


class QoderAdapter(ClaudeFamilyAdapter):
    name = "qoder"
    search_names = ["qoder", "Qoder", ".qoder"]

    def session_roots(self) -> list[Path]:
        return [_resolve_home("QODER_CONFIG_DIR", ".qoder") / "projects"]
