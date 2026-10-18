"""started_at 的提取必须在 Claude Code 家族基类里，不能由各 adapter 各抄一遍。

根因（实测）：这一步原本只写在 workbuddy 适配器里，后加的 qoder 直接漏抄 →
已有会话的 started_at 恒为 null，而它是 90 天保留期的唯一依据，prune_sessions
按它删，于是这些会话**永久滞留、永远清不掉**。

修法：提到家族共用的 claude_handle_event，新增 Claude Code 系 agent（只给 name
与路径）就自动带上；workbuddy 里那份重复实现删掉，改调同一个函数。
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.capture.adapters.base_jsonl import _ts_to_iso
from app.capture.adapters.qoder import QoderAdapter
from app.capture.adapters.workbuddy import WorkBuddyAdapter
from app.capture.models import SessionRef


def _ref(tmp_path, name="s.jsonl") -> SessionRef:
    p = tmp_path / name
    p.touch()
    return SessionRef(agent="x", session_id="s1", path=p, size=0,
                      mtime=p.stat().st_mtime)


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# ---------- 家族基类：started_at 统一提取 ----------

QODER_LINES = [
    {"type": "user", "timestamp": "2026-09-21T10:00:00Z",
     "cwd": "C:\\proj", "message": {"role": "user", "content": "写个脚本"}},
    {"type": "assistant", "timestamp": "2026-09-21T10:00:07Z",
     "message": {"role": "assistant", "model": "qfmodel", "content": "好的"}},
]


def _write_events(tmp_path, lines) -> SessionRef:
    import json
    p = tmp_path / "s1.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")
    return SessionRef(agent="qoder", session_id="s1", path=p,
                      size=p.stat().st_size, mtime=p.stat().st_mtime)


def test_qoder_now_produces_started_at(tmp_path):
    """修之前这条为 null → 会话永久滞留；现在是真实的 ISO 时间。"""
    ref = _write_events(tmp_path, QODER_LINES)
    s = QoderAdapter().parse(ref)
    assert s.started_at == "2026-09-21T10:00:00Z"


def test_started_at_is_first_timestamped_event(tmp_path):
    """取首个带时间戳的事件，不是最后一个（会话开始时间语义）。"""
    lines = [dict(l) for l in QODER_LINES]
    lines.insert(0, {"type": "summary", "summary": "摘要行没有时间戳"})
    ref = _write_events(tmp_path, lines)
    s = QoderAdapter().parse(ref)
    assert s.started_at == "2026-09-21T10:00:00Z"


def test_workbuddy_epoch_millis_still_works(tmp_path):
    """workbuddy 走 epoch 毫秒，合并实现后口径不能变。"""
    import json
    ref = _ref(tmp_path, "wb.jsonl")
    ts_ms = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp() * 1000)
    rows = [
        {"type": "session_meta", "session_id": "real-sid"},
        {"type": "message", "role": "user", "timestamp": ts_ms,
         "content": [{"type": "input_text", "text": "hi"}]},
        {"type": "message", "role": "assistant", "timestamp": ts_ms + 1000,
         "content": [{"type": "output_text", "text": "hello"}]},
    ]
    ref.path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                        encoding="utf-8")
    ref.size = ref.path.stat().st_size
    s = WorkBuddyAdapter().parse(ref)
    assert s.started_at
    assert s.started_at.endswith("Z")


# ---------- _ts_to_iso：两种口径 + 垃圾输入 ----------

@pytest.mark.parametrize("raw,expected", [
    (1_750_000_000_000, "2025-06-15T15:06:40Z"),   # epoch 毫秒
    (1_750_000_000, "2025-06-15T15:06:40Z"),       # epoch 秒
    ("1750000000000", "2025-06-15T15:06:40Z"),     # 数字字符串
    ("2026-09-21T12:34:56.789Z", "2026-09-21T12:34:56Z"),  # ISO 带毫秒
    ("2026-09-21T12:34:56Z", "2026-09-21T12:34:56Z"),
    ("2026-09-21 12:34:56", "2026-09-21T12:34:56Z"),       # 无时区 → 视为 UTC
])
def test_ts_to_iso_shapes(raw, expected):
    assert _ts_to_iso(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "garbage", [], {}])
def test_ts_to_iso_rejects_unusable(raw):
    """识别不了就返回 None——**绝不原样透传**。

    写进去一个非 ISO 的字符串会让 prune_sessions 的时间比较静默失效：字符串比较
    不报错、也不删，等于保留期悄悄关掉。
    """
    assert _ts_to_iso(raw) is None
