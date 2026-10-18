"""Cline 会话解析器（T1，JSON，官方源码口径）。

格式：编辑器 globalStorage/<扩展id>/tasks/<taskId>/api_conversation_history.json
（Anthropic MessageParam[]：role/content，content 为字符串或块数组）
  - 新扩展 id：cline.cline
  - 旧扩展 id：saoudrizwan.claude-dev
  - 新版跨平台 home：~/.cline/（同布局）
VS Code 系编辑器（Code/Cursor/Trae/Windsurf 等）globalStorage 路径同构，
多编辑器探测。Roo Code（Cline fork）复用本基类，见 roo_code.py。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ..models import AdapterBase, Message, Session, SessionRef
from .base_jsonl import _text_of, tool_result_message, tool_use_message

# VS Code 系 AI 编码主力编辑器的 User/globalStorage 探测清单
_VS_EDITORS = ("Code", "Code - Insiders", "Cursor", "Trae", "Trae CN", "Windsurf", "Qoder")


def _vscode_global_storage_roots() -> list[Path]:
    """各编辑器的 User/globalStorage 目录（三平台）。"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return [base / editor / "User" / "globalStorage" for editor in _VS_EDITORS]


class VSClineBase(AdapterBase):
    """Cline 系（Cline/Roo Code）VS Code globalStorage 任务目录解析器基类。"""

    name: str = ""
    search_names: list[str] = ["cline", "Cline", ".cline"]
    extension_dirs: tuple[str, ...] = ("cline.cline", "saoudrizwan.claude-dev")
    file_name: str = "api_conversation_history.json"

    def extra_roots(self) -> list[Path]:
        """扩展根目录（如新版 ~/.cline）；默认无。"""
        return []

    def _roots(self) -> list[Path]:
        roots = [
            root / ed
            for root in _vscode_global_storage_roots()
            for ed in self.extension_dirs
        ]
        roots.extend(self.extra_roots())
        return roots

    def discover(self) -> list[SessionRef]:
        refs: list[SessionRef] = []
        seen: set[str] = set()
        for root in self._roots():
            if not root.is_dir():
                continue
            for path in sorted(root.rglob(f"tasks/*/{self.file_name}")):
                key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    st = path.stat()
                except OSError:
                    continue
                refs.append(
                    SessionRef(
                        agent=self.name,
                        session_id=path.parent.name,
                        path=path,
                        size=st.st_size,
                        mtime=st.st_mtime,
                    )
                )
        return refs

    def parse(self, ref: SessionRef) -> Session | None:
        try:
            data = json.loads(ref.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(data, dict):
            data = data.get("messages") or []
        if not isinstance(data, list):
            return None
        session = Session(agent=self.name, session_id=ref.session_id)
        for item in data:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if role not in ("user", "assistant"):
                continue
            content = item.get("content")
            ts = item.get("ts")
            if isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        session.messages.append(tool_use_message(b, ts))
                    elif b.get("type") == "tool_result":
                        session.messages.append(tool_result_message(b, ts))
                text = _text_of(content)
                if text:
                    session.messages.append(Message(role=role, content=text, ts=ts))
            else:
                text = _text_of(content)
                if text:
                    session.messages.append(Message(role=role, content=text, ts=ts))
        return session if session.messages else None


class ClineAdapter(VSClineBase):
    name = "cline"

    def extra_roots(self) -> list[Path]:
        return [Path.home() / ".cline"]
