"""Roo Code 会话解析器（T1，JSON，社区口径——实验性）。

Roo Code = Cline fork，VS Code globalStorage 扩展目录
rooveterinaryinc.roo-cline/，tasks/<id>/api_conversation_history.json 布局同构，
复用 VSClineBase。
"""

from __future__ import annotations

from .cline import VSClineBase


class RooCodeAdapter(VSClineBase):
    name = "roo-code"
    search_names = ["roo", "roo-cline", "rooveterinaryinc.roo-cline"]
    extension_dirs = ("rooveterinaryinc.roo-cline",)
