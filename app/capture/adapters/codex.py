"""Codex CLI 会话解析器（T1，JSONL，实测；官方源码口径）。

格式：~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl（CODEX_HOME 可覆盖）
行类型：session_meta / turn_context / response_item / event_msg / world_state
冷文件会被后台 zstd 压缩为 rollout-*.jsonl.zst（官方源码确认），解析时解压。
"""

from __future__ import annotations

from pathlib import Path

from .base_jsonl import JsonlAdapterBase, _resolve_home
from ..models import Message, Session

_TEXT_PART_TYPES = ("input_text", "output_text", "text")


class CodexAdapter(JsonlAdapterBase):
    name = "codex"
    glob_pattern = "rollout-*.jsonl*"  # .jsonl 与 .jsonl.zst 两态
    search_names = ["codex", "Codex"]

    def session_roots(self) -> list[Path]:
        return [_resolve_home("CODEX_HOME", ".codex") / "sessions"]

    def session_id_from_path(self, path: Path) -> str:
        stem = path.name
        if stem.endswith(".zst"):
            stem = stem[: -len(".zst")]
        return _session_id_from_name(stem)

    # `.zst` 冷文件的流式解压已上移基类 JsonlAdapterBase._open_text
    # （H10；② 归档压缩共用同一条出口），此处不再重复实现。

    def _handle_event(self, session: Session, event: dict) -> None:
        etype = event.get("type")
        payload = event.get("payload") or {}
        ts = event.get("timestamp")
        if etype == "session_meta":
            session.session_id = payload.get("session_id") or session.session_id
            session.project = payload.get("cwd")
            session.started_at = payload.get("timestamp") or ts
            model = _model_from_meta(payload)
            if model:
                session.model = model
        elif etype == "turn_context":
            model = payload.get("model")
            if isinstance(model, str) and model:
                session.model = model
        elif etype == "response_item":
            msg = _to_message(payload, ts)
            if msg is not None:
                session.messages.append(msg)
        # event_msg / world_state：不进经验流


def _session_id_from_name(stem: str) -> str:
    if len(stem) >= 36:
        tail = stem[-36:]
        if sum(c == "-" for c in tail) == 4:
            return tail
    return stem


def _model_from_meta(payload: dict) -> str | None:
    prov = payload.get("provenance") or {}
    model = prov.get("model")
    if isinstance(model, str) and model:
        return Path(model).stem  # 本地 gguf 路径 → 模型名
    return None


def _to_message(payload: dict, ts: str | None) -> Message | None:
    ptype = payload.get("type")
    if ptype == "message":
        role = payload.get("role")
        if role not in ("user", "assistant"):
            return None  # system（base instructions）不进经验流
        parts = [
            p.get("text", "")
            for p in payload.get("content") or []
            if isinstance(p, dict) and p.get("type") in _TEXT_PART_TYPES
        ]
        return Message(role=role, content="\n".join(t for t in parts if t), ts=ts)
    if ptype == "function_call":
        return Message(
            role="assistant",
            tool_use={
                "name": payload.get("name"),
                "arguments": payload.get("arguments"),
                "call_id": payload.get("call_id"),
            },
            ts=ts,
        )
    if ptype == "function_call_output":
        return Message(
            role="tool",
            tool_result={
                "call_id": payload.get("call_id"),
                "output": payload.get("output"),
            },
            ts=ts,
        )
    return None  # reasoning 等类型不进经验流


# 兼容旧引用（测试/外部）
def _session_id_from_path(path: Path) -> str:
    stem = path.name
    if stem.endswith(".zst"):
        stem = stem[: -len(".zst")]
    if stem.endswith(".jsonl"):
        stem = stem[: -len(".jsonl")]
    return _session_id_from_name(stem)
