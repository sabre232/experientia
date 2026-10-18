"""经验证据锚点（P0-2，纪律 D3：没有原话就不入库）。

一条经验要能"看原话"，就必须带一个**能在会话里定位到的原文片段**。本模块只做
这一件事：把散在各处的原文收敛成一个结构，并给出"它到底在不在原会话里"的判定。

为什么值得单独一层：G≥0.5 的经验会进入注入块，成为 agent 下次做同类任务的依据。
没有可溯源原话的经验，等于让人凭一句结论下判断——这正是防错误传播
要挡的东西，也正是混元专用模型那套"写入协议"里最该抄的一条。

证据三档（`source`）：

- `session`    从本次会话消息定位到的原话（含模型引用、验收收尾锚点）
- `capture`    兜底：原文本身就是被蒸馏的材料（自报场景）
- `user`       用户显式确认（g_source=user）——最高信任，**不要求带 quote**

向后兼容：早期数据的 `evidence` 是纯字符串，`normalize()` 负责包成结构，
不迁移、不改存量；定位不到或没定过位的，`locatable` 给 False/None，
**绝不假装定位过**。
"""

from __future__ import annotations

import re

from .gsignal import G_MIN_INJECT, _is_confirmatory_closing

EVIDENCE_SOURCES = ("session", "capture", "user")
QUOTE_MAX = 600          # 单条证据引文上限（与 review._process_candidate 旧口径一致）
# 会话内定位的判定：短引用必须被消息包含；长引用允许消息被压缩到只剩引用的一部分。
# 同一个下限还用在 from_candidate 的编造防御上（见那里）—— M3 之前
# 只保护反方向，模型编个 2 字引用（"好的"）即可被任意消息包含 → 过证据闸。
_MIN_LOCATE_LEN = 8


def _norm(text) -> str:
    """折叠空白（显示/存储用）：保留单空格，人在 UI 上读着不糊成一团。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _key(text) -> str:
    """匹配键：**去掉所有空白**。

    引用常被换行/缩进改过样式，消息也可能被压缩——只要字序一样就算定位成功。
    中文里多余空格尤其常见（"图片转成" vs "图片转成"）。只用于比对，不用于展示。
    """
    return re.sub(r"\s+", "", str(text or ""))


def _session_messages(session_dict) -> list[tuple[str, str]]:
    """[(role, text)]，role ∈ user / assistant。坏输入一律跳过。"""
    if not isinstance(session_dict, dict):
        return []
    out: list[tuple[str, str]] = []
    for key, role in (("user_messages", "user"),
                      ("assistant_messages", "assistant")):
        msgs = session_dict.get(key)
        if not isinstance(msgs, list):
            continue
        for m in msgs:
            body = _norm(m)
            if body:
                out.append((role, body))
    return out


def _session_text(session_dict) -> str:
    return "\n".join(text for _role, text in _session_messages(session_dict))


def locate(session_dict, quote) -> dict | None:
    """在会话消息里定位 quote。命中返回 {"role", "index", "matched"}，否则 None。

    `index` 是该角色消息列表内的下标（与 store 中 user_messages /
    assistant_messages 的落地口径一致，供"看原话"下钻用）。
    双向包含判定：引用可能被压缩，消息也可能被截断，单向子串会漏。
    """
    q = _norm(quote)
    q_key = _key(quote)
    if not q_key:
        return None
    if not isinstance(session_dict, dict):
        return None
    for key, role in (("user_messages", "user"),
                      ("assistant_messages", "assistant")):
        msgs = session_dict.get(key)
        if not isinstance(msgs, list):
            continue
        for i, m in enumerate(msgs):
            body = _norm(m)
            body_key = _key(m)
            if not body_key:
                continue
            if q_key in body_key or (len(q_key) >= _MIN_LOCATE_LEN
                                     and body_key in q_key):
                return {"role": role, "index": i, "matched": body[:QUOTE_MAX]}
    return None


def build(quote, session_dict=None, source: str = "session") -> dict | None:
    """构造一条结构化证据。quote 空 → None（无证据就是无证据，不造空壳）。"""
    text = _norm(quote)[:QUOTE_MAX]
    if not text:
        return None
    hit = locate(session_dict, quote) if session_dict else None
    return {"quote": text, "source": source, "locatable": hit is not None, "at": hit}


def from_confirm_close(session_dict) -> dict | None:
    """确定性锚点：会话以明确验收收尾时，最后一条用户消息就是最硬的原话证据。

    零模型成本——`_is_confirmatory_closing` 已经判定过这条消息存在。
    """
    if not isinstance(session_dict, dict):
        return None
    msgs = session_dict.get("user_messages")
    if not isinstance(msgs, list) or not msgs:
        return None
    return build(msgs[-1], session_dict, source="session")


def from_candidate(cand, session_dict) -> dict | None:
    """模型自报的 evidence：必须在会话里定位得到，否则整段丢弃。

    这是防幻觉的关键一道——模型编一句"用户当时说…"很容易，定位不了就是编的。
    长度下限：短引用（"好的"）会被任意消息包含，2 字就能造出
    一条"定位成功"的证据。只拦这条候选路径——`from_confirm_close` 的原话是
    消息本身，短确认句（"可以"）是合法验收证据，不走这道闸。
    """
    raw = _norm((cand or {}).get("evidence"))
    if not raw:
        return None
    if len(_key(raw)) < _MIN_LOCATE_LEN:
        return None
    built = build(raw, session_dict, source="session")
    if built is None or not built["locatable"]:
        return None
    return built


def from_capture(session_dict) -> dict | None:
    """兜底锚点（source=capture）：原文本身就是被蒸馏的材料。

    只给自报这类"没有明确验收收尾、但原文即证据"的场景用。它保证**可溯源**
    （看原话时回得到这段），但不代表模型判断可信——G 值照算，一码归一码。
    """
    blob = _session_text(session_dict)
    if not blob:
        return None
    return {"quote": blob[:QUOTE_MAX], "source": "capture",
            "locatable": True, "at": None}


def resolve(cand, session_dict) -> tuple[dict | None, str]:
    """按优先级给一条候选找证据。返回 (evidence|None, kind)。

    kind ∈ "candidate"（模型引用且定位成功）/ "confirm"（验收锚点）
            / "capture"（原文兜底，需 session 显式开启）/ "none"

    优先级理由：模型明确引用的原话 > 会话自身的确定性锚点 > 原文兜底。
    兜底只在调用方声明"原文即证据"时启用（`session_dict.evidence_fallback`），
    否则任何会话都能靠兜底过关，D3 就白设了。
    """
    hit = from_candidate(cand, session_dict)
    if hit is not None:
        return hit, "candidate"
    if _is_confirmatory_closing(session_dict):
        hit = from_confirm_close(session_dict)
        if hit is not None:
            return hit, "confirm"
    if isinstance(session_dict, dict) \
            and session_dict.get("evidence_fallback") == "capture":
        hit = from_capture(session_dict)
        if hit is not None:
            return hit, "capture"
    return None, "none"


def normalize(value, session_dict=None) -> dict | None:
    """存量兼容：老字符串 → 结构体。

    没给 session_dict = **没验过**，`locatable` 置 None（不是 False）——
    False 表示"验了，不在"，None 表示"没验"，两者含义不同，别混。
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    text = _norm(value)[:QUOTE_MAX]
    if not text:
        return None
    if session_dict is None:
        return {"quote": text, "source": "session",
                "locatable": None, "at": None}
    hit = locate(session_dict, value)
    return {"quote": text, "source": "session",
            "locatable": hit is not None, "at": hit}


def quote_of(rec) -> str:
    """读侧统一取证据引文（结构体 / 老字符串都能读）。"""
    ev = (rec or {}).get("evidence")
    if not ev:
        return ""
    if isinstance(ev, dict):
        return _norm(ev.get("quote"))
    return _norm(ev)


def gate(rec, session_dict=None) -> tuple[bool, str]:
    """D3 写入闸：想进经验库，就得有证据。

    返回 (是否放行, 理由)。不放行 ≠ 丢弃——调用方应转草稿 pending，让用户
    看过原话再决定，这比"悄悄不记"更诚实。

    只拦"本来能进注入块"的记录（G ≥ 门槛）。低 G 记录本就不注入（失败候选池），
    再拦一道只是重复设卡。
    """
    if str((rec or {}).get("g_source") or "") == "user":
        return True, "user"            # 用户确认 = 最高信任，不要求带 quote
    if quote_of(rec):
        return True, "quoted"
    try:
        g = float((rec or {}).get("G") or 0)
    except (TypeError, ValueError):
        g = 0.0
    if g < G_MIN_INJECT:
        return True, "below-threshold"  # 本就不注入，不额外拦
    return False, "no-evidence"
