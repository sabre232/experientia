"""WorkBuddy 会话解析器（T1，JSONL，实测格式）。

格式：~/.workbuddy/projects/<编码路径>/<uuid>.jsonl
每行格式（与 Claude Code 不同，有独立 role 字段和类型体系）：
  {"type": "message", "role": "user", "content": [...], "sessionId": "...", "cwd": "..."}
  {"type": "message", "role": "assistant", "content": [...], ...}
  {"type": "function_call", "callId": "...", "name": "...", "arguments": "..."}
  {"type": "function_call_result", "callId": "...", "output": {...}, ...}
  {"type": "reasoning", ...}                          ← 跳过
  {"type": "file-history-snapshot", ...}              ← 跳过
  {"type": "resend-fork-notice", ...}                 ← 跳过

块类型与 Claude 系不同（`_text_of` 只认 text 块，认不全这里）：
  user:      {"type": "input_text", "text": ...}
  assistant: {"type": "output_text", "text": ...}
content 也可能是纯字符串（旧格式，兼容保留）。

用户文本噪音（实测样本）：真实查询包在 <user_query>…</user_query>
标签里，块内还混有宿主注入块（system-reminder / cb_summary / task-notification /
conversation_history_summary / image_local_path / 摘要续写样板句）。剥噪规则
集中在 _user_text() 单函数——格式再漂移只改这一处。

started_at：session 首个事件的 timestamp（epoch 毫秒）转 ISO UTC。
WORKBUDDY_HOME 可覆盖。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Message, Session
from .base_jsonl import JsonlAdapterBase, _resolve_home, _ts_to_iso


# 真实用户查询标签（多段拼接；实测样本中有多个块含多个标签，均为同一查询
# 被宿主切段，拼接即还原）
_USER_QUERY_RE = re.compile(r"<user_query>(.*?)</user_query>", re.S)

# 宿主注入块开头标记（实测样本：无 user_query 且以这些开头的块
# 全部非用户文本）。其余保留原文——兼容旧格式与未来漂移，宁多勿丢。
_INJECTED_PREFIXES = (
    "<system-reminder",
    "<cb_summary",
    "<task-notification",
    "<conversation_history_summary",
    "<image_local_path",
    "Please continue with the conversation based on the summarized context",
    "Please continue based on the summarized context",
)


def _block_text(content, block_type: str) -> str:
    """workbuddy content：字符串（旧格式原样）或块数组（只取 block_type 块）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == block_type and b.get("text")
        ]
        return "\n".join(parts)
    return ""


def _user_text(content) -> str:
    """user 消息 → 真实用户文本（剥宿主注入噪音）。

    - 块文本含 <user_query> → 只取标签内文本（多段拼接）；
    - 无 <user_query> 且以宿主注入标记开头 → 整块丢弃（返回 ""）；
    - 其余保留原文。
    """
    text = _block_text(content, "input_text")
    if not text:
        return ""
    inner = _USER_QUERY_RE.findall(text)
    if inner:
        return "\n".join(s.strip() for s in inner if s.strip())
    if text.lstrip().startswith(_INJECTED_PREFIXES):
        return ""
    return text


def _fcr_output(event: dict) -> str:
    """function_call_result 工具输出：output 字段（实测样本均为该字段；
    dict {type,text} 或字符串），content 字段为旧格式回退。"""
    out = event.get("output")
    if isinstance(out, dict):
        return str(out.get("text") or "")
    if isinstance(out, str):
        return out
    content = event.get("content")
    if isinstance(content, str):
        return content
    return ""


class WorkBuddyAdapter(JsonlAdapterBase):
    name = "workbuddy"
    search_names = ["workbuddy", ".workbuddy"]

    def session_roots(self) -> list[Path]:
        return [_resolve_home("WORKBUDDY_HOME", ".workbuddy") / "projects"]

    def _handle_event(self, session: Session, event: dict) -> None:
        etype = event.get("type")
        ts = event.get("timestamp")
        cwd = event.get("cwd")
        session_id = event.get("sessionId")

        if isinstance(cwd, str) and cwd and not session.project:
            session.project = cwd
        if isinstance(session_id, str) and session_id and not session.session_id:
            session.session_id = session_id
        # started_at = 首个带时间戳事件（epoch 毫秒 → ISO UTC）；90 天保留期与
        # 周窗口依赖它（修复前全为 null，保留期等于不生效）
        if ts is not None and not session.started_at:
            session.started_at = _ts_to_iso(ts)

        if etype == "message":
            role = event.get("role")
            if role == "user":
                content = _user_text(event.get("content"))
                if content:
                    session.messages.append(Message(role="user", content=content, ts=ts))
            elif role == "assistant":
                content = _block_text(event.get("content"), "output_text")
                if content:
                    session.messages.append(Message(role="assistant", content=content, ts=ts))
            model = event.get("providerData") or {}
            if isinstance(model, dict) and model.get("model") and not session.model:
                session.model = model["model"]

        elif etype == "function_call":
            session.messages.append(
                Message(
                    role="assistant",
                    tool_use={
                        "name": event.get("name"),
                        "arguments": event.get("arguments"),
                        "call_id": event.get("callId"),
                    },
                    ts=ts,
                )
            )

        elif etype == "function_call_result":
            session.messages.append(
                Message(
                    role="tool",
                    tool_result={
                        "call_id": event.get("callId"),
                        "output": _fcr_output(event),
                    },
                    ts=ts,
                )
            )
        # reasoning / file-history-snapshot / resend-fork-notice：跳过，不进经验流
