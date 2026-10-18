"""QClaw 会话解析器（T1，JSONL，OpenClaw v3 会话格式）。

QClaw = OpenClaw 桌面 GUI 封装。实测：会话目录
~/.qclaw/agents/<agentId>/sessions/ 下成对文件：

- ``<uuid>.jsonl``          v3 主文件，解析主对象。行类型
  session / model_change / thinking_level_change / custom / message；
  消息行 ``type="message"``，正文在 ``message.role`` + ``message.content``
  （字符串或块数组，块类型 text / toolCall——与 Claude 系顶层
  type=user/assistant 行不同，旧 ClaudeFamilyAdapter 分派零命中）。
- ``<uuid>.trajectory.jsonl``  openclaw-trajectory schema 的派生轨迹
  （同一会话的另一份视图）：解析它会以不同 session_id（stem 带
  .trajectory 后缀）重复落同一会话 → discover 层显式跳过。

双格式兼容：v3 消息行是主格式；非 message 行回退 Claude 系顶层
type=user/assistant 分派（旧版 QClaw 写 Claude 格式，存量文件仍可解析）。
此前只走 Claude 分派、对 v3 消息行零命中 → parse 恒返回 None →
连续失败循环（capture_failures 计数无限增长，实测 7668 轮）。
"""

from __future__ import annotations

from pathlib import Path

from ..models import Message
from .base_jsonl import ClaudeFamilyAdapter, _append_blocks, _text_of, claude_handle_event


class QClawAdapter(ClaudeFamilyAdapter):
    name = "qclaw"
    glob_pattern = "*/sessions/*.jsonl"
    search_names = ["qclaw", "QClaw", ".qclaw"]

    def session_roots(self) -> list[Path]:
        return [Path.home() / ".qclaw" / "agents"]

    def discover(self) -> list:
        # 显式跳过派生轨迹文件（主文件是解析对象；轨迹是同一会话的另一视图）
        return [r for r in super().discover()
                if not r.path.name.endswith(".trajectory.jsonl")]

    def _handle_event(self, session, event: dict) -> None:
        cwd = event.get("cwd")
        if isinstance(cwd, str) and cwd and not session.project:
            session.project = cwd
        if event.get("type") != "message":
            # 旧版 QClaw 写 Claude 系行（type=user/assistant）→ 回退公共分派
            claude_handle_event(session, event)
            return
        msg = event.get("message") or {}
        role = msg.get("role")
        if role not in ("user", "assistant"):
            return
        ts = event.get("timestamp")
        ts_s = str(ts) if ts is not None else None
        if ts is not None and not session.started_at:
            session.started_at = ts_s
        model = msg.get("model")
        if isinstance(model, str) and model and not session.model:
            session.model = model
        content = msg.get("content")
        if isinstance(content, list):
            # 块数组：text 块合并落一条；toolCall 块不进转录
            #（与 Claude 系 tool_use 不进 user/assistant 文本同口径）
            _append_blocks(session, role, content, ts_s)
        else:
            text = _text_of(content)
            if text:
                session.messages.append(Message(role=role, content=text, ts=ts_s))
