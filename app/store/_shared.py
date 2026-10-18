"""store 层各 mixin 共用的小工具（L4 拆分的**前置改动**）。

背景：`app/store/store.py` 原本是 3538 行单文件（`class Store` 占 2796 行、148 个
方法）。按域拆成 mixin 时，各 mixin 需要用到其中的模块级小工具——但 mixin 模块
不能反向 import `store.py`（会与 `class Store` 的组装形成循环导入），故这些共用件
先落到这里，由 `store.py` 与各 mixin 共同 import。

只放"确属跨域共用"的东西；单个域私有的助手仍随各自 mixin 走。
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# 数据目录名与资产子目录清单——`Store` 主体、`resolve_data_dir`
# / `cleanup_pending_data_dir`、以及「数据目录」域 mixin 都要用，故下沉到这里。
DATA_DIR_NAME = ".experientia"

ASSET_DIRS = ("skills", "preferences", "deprecated", "sessions",
              "incoming", "keys", "models", "generated_skills")


def _safe(name: str) -> str:
    """trunk/category 变路径段：去掉非法字符，防路径穿越。

     M16（修）：纯点段（"." / ".." / "..."）不含任何被
    过滤的字符，此前能原样通过——`trunk=".."` 会把 skill 写到数据目录根乃至
    越出一级。这里显式拒绝"仅由点构成"的段；"v1.2" 这类含点的正常名字不受影响。
    """
    cleaned = "".join(c for c in name if c not in '<>:"/\\|?*\x00').strip()
    if not cleaned or set(cleaned) <= {"."}:
        return "未分类"
    return cleaned


def _safe_int(v, default: int = 0) -> int:
    """外部数据（JSONL 手工编辑/旧版本残留）的整数读取容错：坏值按 default。
    一行坏数据不得抛 ValueError 击穿整个读取视图。"""
    try:
        return int(float(v or default))
    except (TypeError, ValueError):
        return default


def _safe_float(v, default: float = 0.0) -> float:
    """同 _safe_int，浮点口径（G 值求和/比较）。"""
    try:
        return float(v or default)
    except (TypeError, ValueError):
        return default


def _sess_stamp(s: dict) -> str:
    """会话行的时间戳（started_at 优先，回落 ended_at；缺失 → 空串）。

    真机坑：sessions.jsonl 追加式落库，同一会话的**部分行**
    started_at 是 JSON null（1645 行里 159 行）。此前各处写
    `str(s.get("started_at", ""))`——键存在值为 None 时 get 的默认值不生效，
    得到字符串 "None"，字典序大于任何日期 → 去重时"丢时间戳的那一行"反而胜出、
    排序时被排到最后，257 个会话被压成 98 个（磨合度窗口同时错位）。
    统一走本函数：None 与缺失同形（空串），比较时永远让有时间的行赢。"""
    return str(s.get("started_at") or s.get("ended_at") or "")


def _session_ident(s: dict):
    """会话去重身份：即 (agent, session_id) 去重键里的 session_id 分量。

    有 session_id 用之；缺失/为空时不能沿用 None——同一 agent 下所有无 id 会话
    会在 (agent, None) 键上坍缩成一条，而账本/成长/复盘队列都以去重结果为准，
    直接少算会话数。退到内容指纹元组：同一条重复上报仍命中同键去重，不同会话
    各留一条。与 _sess_stamp 同型（都防 None 直接参与键/比较）。"""
    sid = s.get("session_id")
    if sid:
        return sid
    return ("#noid#",
            _sess_stamp(s), s.get("req_count"), s.get("correction_hits"),
            s.get("tokens_in"), s.get("tokens_out"), s.get("tokens"),
            len(s.get("user_messages") or ()),
            len(s.get("assistant_messages") or ()),
            len(s.get("events") or ()),
            s.get("trunk"), s.get("category"))
