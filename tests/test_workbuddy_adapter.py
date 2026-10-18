"""WorkBuddy 适配器文本通道修复测试（断链修复方案 P0）。

背景：workbuddy 原始 JSONL 的 content 是块数组，块类型 input_text / output_text
与 Claude 系 text 块不同，旧解析器 `_text_of` 全判空 → user/assistant 文本在解析
层丢失，落库 session 是空壳（req_count=0），一个月零经验的根因。

fixture 按实测样本的形态内联（覆盖 user / assistant / 工具输出 / 旧格式各形态）；
真实文件冒烟用 skipif（仓库约定）。
"""

import json
import re
from pathlib import Path

import pytest

from app.capture.adapters.workbuddy import (
    WorkBuddyAdapter,
    _ts_to_iso,
    _user_text,
)
from app.capture.models import Session, SessionRef
from app.store.store import Store


# 首个事件 timestamp（epoch 毫秒）= T09:00:00Z
TS0 = 1768467600331
TS0_ISO = "2026-01-15T09:00:00Z"

# 真实形态：user 块 = input_text 数组，块内混宿主注入 + <user_query> 标签
MIXED_USER_BLOCK = (
    '<system-reminder data-role="user-context">\n'
    "<user_info>\nOS Version: win32\nWorkspace Folder: C:\\proj\n</user_info>\n"
    "<identity_context>\nSOUL.md 内容若干……\n</identity_context>\n"
    "<user_query>\n调研示例课题，输出可行性报告，引用权威来源，禁止编造</user_query>"
)

# 多段 user_query（实测样本含多个标签：宿主切段，拼接还原）
MULTI_USER_BLOCKS = [
    '<system-reminder data-role="user-context">\n'
    "<user_query>第一部分：整理本项目的历史决策记录</user_query>",
    "<user_query>第二部分：补充风险清单，面向评审方</user_query>",
]

# 纯注入块（无 user_query）→ 整块丢弃
NOISE_BLOCKS = [
    '<system-reminder data-role="user-context">\n<user_info>OS: win32</user_info>',
    '<cb_summary>上一段对话的压缩摘要……</cb_summary>',
    "<task-notification>\n<task-id>UZBlEF</task-id>\n<status>completed</status>\n"
    "<summary>Background command ok</summary>\n</task-notification>",
    "<conversation_history_summary>\n# Summary\n## 1. 核心请求\n……\n"
    "</conversation_history_summary>",
    '<image_local_path>C:\\Users\\x\\img.png</image_local_path>',
    "Please continue with the conversation based on the summarized context above. "
    "Maintain the same level of detail and helpfulness as before the summarization.",
    "Please continue based on the summarized context above.",
    '<system-reminder data-role="error-recovery">重试提示</system-reminder>',
]

# 无标签真实用户文本（子代理任务提示等）→ 保留原文
PLAIN_USER_TEXT = (
    "你是代码考古员。背景：我们是一套分模块协作的桌面应用，"
    "请把这条链路的调用关系梳理清楚，只做只读调研。"
)

WORKBUDDY_LINES = [
    # 首个事件：混合注入块 + user_query（started_at 来源）
    {"type": "message", "role": "user", "sessionId": "s-wb", "cwd": "C:\\proj",
     "timestamp": TS0,
     "content": [{"type": "input_text", "text": MIXED_USER_BLOCK}]},
    {"type": "reasoning", "timestamp": TS0 + 1000,
     "providerData": {"model": "hy3"}, "content": "thinking"},
    {"type": "message", "role": "assistant", "timestamp": TS0 + 2000,
     "providerData": {"model": "hy3"},
     "content": [{"type": "output_text",
                  "text": "我先确认分析思路，并同时把已附上的 6 个文件快速归类。"}]},
    {"type": "function_call", "callId": "chatcmpl-tool-1", "name": "Read",
     "arguments": "{\"path\": \"a.pdf\"}", "timestamp": TS0 + 3000},
    # 工具输出在 output 字段（实测样本均为 output，dict {type,text}）
    {"type": "function_call_result", "callId": "chatcmpl-tool-1", "name": "Read",
     "status": "completed", "timestamp": TS0 + 4000,
     "output": {"type": "text", "text": "PDF 第一页内容……"}},
    {"type": "file-history-snapshot", "timestamp": TS0 + 5000, "snapshot": {}},
    {"type": "resend-fork-notice", "timestamp": TS0 + 6000,
     "editedUserItemId": "x"},
    # 多段 user_query（拼接）
    {"type": "message", "role": "user", "timestamp": TS0 + 7000,
     "content": [{"type": "input_text", "text": t} for t in MULTI_USER_BLOCKS]},
    # 纯注入块（8 种形态）→ 全部丢弃，不产生 user 消息
    *[{"type": "message", "role": "user", "timestamp": TS0 + 8000 + i,
       "content": [{"type": "input_text", "text": t}]}
      for i, t in enumerate(NOISE_BLOCKS)],
    # 无标签真实用户文本
    {"type": "message", "role": "user", "timestamp": TS0 + 9000,
     "content": [{"type": "input_text", "text": PLAIN_USER_TEXT}]},
    # 否定词用户消息（供 correction_hits 断言）
    {"type": "message", "role": "user", "timestamp": TS0 + 10000,
     "content": [{"type": "input_text", "text": "不对，方向反了，重来"}]},
    {"type": "message", "role": "assistant", "timestamp": TS0 + 11000,
     "content": [{"type": "output_text", "text": "收到，已调整。"}]},
    # 旧格式兼容：content 纯字符串
    {"type": "message", "role": "user", "timestamp": TS0 + 12000,
     "content": "旧格式纯字符串 user"},
    {"type": "message", "role": "assistant", "timestamp": TS0 + 13000,
     "content": "旧格式纯字符串 assistant"},
    # 旧格式兼容：function_call_result 走 content 字段
    {"type": "function_call", "callId": "t-old", "name": "read_file",
     "arguments": "{}", "timestamp": TS0 + 14000},
    {"type": "function_call_result", "callId": "t-old",
     "content": "def f(): pass", "timestamp": TS0 + 15000},
]


def _write(dirpath: Path, lines, name="00000000-0000-0000-0000-000000000000.jsonl") -> Path:
    p = dirpath / name
    p.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines),
                 encoding="utf-8")
    return p


def _parse(tmp_path: Path, lines) -> "Session | None":
    (tmp_path / "projects" / "proj").mkdir(parents=True)
    path = _write(tmp_path / "projects" / "proj", lines)
    st = path.stat()
    ref = SessionRef(agent="workbuddy", session_id=path.stem, path=path,
                     size=st.st_size, mtime=st.st_mtime)
    return WorkBuddyAdapter().parse(ref)


# ---------- 块文本提取与剥噪（单函数口径） ----------

def test_user_text_extracts_query_from_mixed_block():
    out = _user_text([{"type": "input_text", "text": MIXED_USER_BLOCK}])
    assert out == "调研示例课题，输出可行性报告，引用权威来源，禁止编造"
    assert "system-reminder" not in out
    assert "user_info" not in out


def test_user_text_joins_multi_query_tags():
    out = _user_text([{"type": "input_text", "text": t} for t in MULTI_USER_BLOCKS])
    assert out == "第一部分：整理本项目的历史决策记录\n第二部分：补充风险清单，面向评审方"


def test_user_text_drops_pure_injection_blocks():
    for t in NOISE_BLOCKS:
        assert _user_text([{"type": "input_text", "text": t}]) == "", t[:40]


def test_user_text_keeps_plain_and_legacy_string():
    assert _user_text([{"type": "input_text", "text": PLAIN_USER_TEXT}]) == PLAIN_USER_TEXT
    assert _user_text("旧格式纯字符串 user") == "旧格式纯字符串 user"
    assert _user_text(None) == ""
    assert _user_text([{"type": "other", "text": "x"}]) == ""


def test_ts_to_iso_epoch_ms():
    assert _ts_to_iso(TS0) == TS0_ISO
    assert _ts_to_iso(str(TS0)) == TS0_ISO
    assert _ts_to_iso(TS0 / 1000) == TS0_ISO  # 秒级兜底
    assert _ts_to_iso("2026-01-15T09:00:00Z") == "2026-01-15T09:00:00Z"
    assert _ts_to_iso(None) is None


# ---------- 整文件解析 ----------

def test_workbuddy_parse_recovers_user_and_assistant(tmp_path):
    s = _parse(tmp_path, WORKBUDDY_LINES)
    assert s is not None
    user_msgs = [m for m in s.messages if m.role == "user"]
    asst_msgs = [m for m in s.messages if m.role == "assistant" and m.content]
    # 根因断言：user 消息恢复（修复前 = 0，全部被 _text_of 判空丢弃）
    assert len(user_msgs) == 5, [m.content[:30] for m in user_msgs]
    assert len(asst_msgs) >= 3
    # 噪音断言：任何 user 文本都不含宿主注入标记
    for m in user_msgs:
        assert "system-reminder" not in m.content
        assert "task-notification" not in m.content
        assert "cb_summary" not in m.content
        assert "<user_query>" not in m.content  # 标签本身要剥掉
    # 真实查询完整
    assert any("调研示例课题" in m.content for m in user_msgs)
    assert any("不对，方向反了" in m.content for m in user_msgs)
    # assistant 文本恢复（output_text 块 + 旧格式字符串）
    assert any("归类" in m.content for m in asst_msgs)
    assert any(m.content == "旧格式纯字符串 assistant" for m in asst_msgs)
    # 工具输出：output 字段（dict {type,text}）+ 旧格式 content 字段
    tools = [m for m in s.messages if m.tool_result is not None]
    assert len(tools) == 2
    assert tools[0].tool_result["output"] == "PDF 第一页内容……"
    assert tools[1].tool_result["output"] == "def f(): pass"
    # started_at：首个事件 timestamp（epoch 毫秒）→ ISO UTC
    assert s.started_at == TS0_ISO
    # project / model 既有行为不回归
    assert s.project == "C:\\proj"
    assert s.model == "hy3"
    # 跳过类事件不产生消息
    assert not any(m.content == "thinking" for m in s.messages)


# ---------- 端到端：session → 复盘 dict → 信号判定 ----------

def test_review_dict_has_distillable_signals(tmp_path):
    from app.capture.scan import session_to_review_dict
    from app.distill.review import has_distillable_signals

    s = _parse(tmp_path, WORKBUDDY_LINES)
    assert s is not None
    store = Store(tmp_path)
    store.ensure_layout()
    d = session_to_review_dict(s, store)
    # 断链修复的核心验收：req_count > 0（修复前恒 0 → 复盘门槛永不过）
    assert d["req_count"] == 5
    assert d["user_messages"], "user_messages 非空"
    assert d["assistant_messages"], "assistant_messages 非空"
    assert d["started_at"] == TS0_ISO
    # 否定词命中（"不对，方向反了，重来"）
    assert d["correction_hits"] >= 1
    # 复盘门槛通过（修复前 has_distillable_signals 恒 False → 整批零成本跳过）
    assert has_distillable_signals(d) is True
    # 原始 messages 还在 dict 里（落库时由 store 契约 pop，P1a 管）
    assert "messages" in d and len(d["messages"]) > 0


def test_empty_shell_session_returns_none(tmp_path):
    """全噪音会话（只有注入块 + reasoning）→ 解析不出消息 → None（不产生空壳行）。"""
    lines = [
        {"type": "message", "role": "user", "timestamp": TS0,
         "content": [{"type": "input_text",
                      "text": '<system-reminder data-role="user-context">ctx</system-reminder>'}]},
        {"type": "reasoning", "timestamp": TS0 + 1000, "content": "thinking"},
    ]
    assert _parse(tmp_path, lines) is None


# ---------- 真实文件冒烟（skipif：CI 无本机 workbuddy 数据） ----------

_REAL_SAMPLE = (Path.home() / ".workbuddy" / "projects"
                / "c-Users-user-Downloads-demo"
                / "00000000-0000-0000-0000-000000000000.jsonl")


@pytest.mark.skipif(not _REAL_SAMPLE.exists(),
                    reason="本机无 workbuddy 真实样本（断链修复方案 P0 fixture 来源）")
def test_real_sample_smoke(tmp_path):
    """真实 raw 样本（200 行）：user 恢复 + 无噪音 + started_at + 复盘门槛。"""
    from app.capture.scan import session_to_review_dict
    from app.distill.review import has_distillable_signals

    st = _REAL_SAMPLE.stat()
    ref = SessionRef(agent="workbuddy", session_id=_REAL_SAMPLE.stem,
                     path=_REAL_SAMPLE, size=st.st_size, mtime=st.st_mtime)
    s = WorkBuddyAdapter().parse(ref)
    assert s is not None
    user_msgs = [m for m in s.messages if m.role == "user"]
    assert len(user_msgs) > 0
    for m in user_msgs:
        assert "system-reminder" not in m.content
        assert "task-notification" not in m.content
        assert "<user_query>" not in m.content
    assert s.started_at and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                                     s.started_at)
    store = Store(tmp_path)
    store.ensure_layout()
    d = session_to_review_dict(s, store)
    assert d["req_count"] > 0
    assert has_distillable_signals(d)
