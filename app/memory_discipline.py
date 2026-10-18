"""记忆纪律总收口（方案：七条纪律的唯一入口）。

七条纪律分散在各自模块里（价值闸门 / 分层 / 证据 / 去重 / 演化链 / 遗忘 / 取用），
本模块不做第二套实现，只做三件事：

1. **一张政策表**：`POLICY` 把每条纪律、它的实现模块、收口函数列清楚——想改纪律
   先看这张表，不会七处各改一套；
2. **唯一入口**：`admit()` 是写入注意力闸，**所有写入通道**（复盘 / 文件扫描 /
   自报）都必须过它，不许旁路；
3. **可解释**：`explain()` 给一条记录回答"它凭什么进来、摆在哪儿、能放多久"。

设计取舍：本模块**只 import 不搬运**。纪律的判定逻辑已在 `distill/value_gate.py`、
`distill/layers.py`、`distill/evidence.py`、`distill/dedupe.py`、`store/experience.py`
里跑了很多轮；在这里重写一遍只会制造第二个真相来源。
"""

from __future__ import annotations

from .distill import evidence as _evidence
from .distill import gsignal as _gsignal
from .distill import layers as _layers
from .distill import value_gate as _value_gate
from .time_util import parse_ts  # noqa: F401（should_decay 用，顶层包内相对导入）

# ---------- 政策表：纪律 → 实现 → 收口函数 ----------

POLICY: dict[str, dict] = {
    "D1": {"name": "准入纪律", "impl": "distill.value_gate",
           "entry": "memory_discipline.admit"},
    "D2": {"name": "归位纪律", "impl": "distill.layers",
           "entry": "memory_discipline.assign_layer"},
    "D3": {"name": "证据纪律", "impl": "distill.evidence",
           "entry": "distill.evidence.gate"},
    "D4": {"name": "合并纪律", "impl": "distill.dedupe",
           "entry": "distill.dedupe.upsert_experience"},
    "D5": {"name": "冲突纪律", "impl": "distill.gsignal",
           "entry": "store.experience.supersede_experience"},
    "D6": {"name": "遗忘纪律", "impl": "store.experience",
           "entry": "store.experience.forget_experience"},
    "D7": {"name": "取用纪律", "impl": "distill.layers + distill.capsule",
           "entry": "distill.capsule.build_capsule"},
}

# 准入结论（D1）。
ADMIT_REJECT = "reject"      # 不入库：环境抖动 / 源码回声
ADMIT_ADVICE = "advice"      # 不进用户经验墙：助手自己手笨，转"避坑建议"口吻
ADMIT_EXPERIENCE = "experience"  # 入库：可复用的真教训

# 入库衰减三态（D6）：由 should_decay 给结论，动作在 store 层执行。
DECAY_NONE = "none"
DECAY_RETIRE = "retire"      # 90 天未被注入命中 → 自动老化
DECAY_FORGET = "forget"      # 用户显式遗忘


def admit(cand: dict | str, session_dict: dict | None = None) -> dict:
    """写入注意力闸（D1）。进库之前先问：这东西值不值得占地方？

    返回 `{route, value_class, reason}`：
    - `reject`      环境抖动 / 源码回声——不是经验，是噪音；
    - `advice`      助手自己手笨（编辑前没读、替换没匹配、命令被拦…）——
                     照样可注入（提醒 agent 别犯），但不占用户经验墙；
    - `experience`  真·教训，入库。

    失败安全：分类器自身异常 → 放行（宁漏勿拦）。这个闸是降噪用的，
    不该有能力把主流程打死。
    """
    if isinstance(cand, dict):
        blob = " ".join(str(cand.get(k) or "") for k in
                        ("state", "task", "action", "outcome"))
    else:
        blob = str(cand or "")
    try:
        vclass = _value_gate.classify(blob)
    except Exception:  # noqa: BLE001 分类器异常不拦路
        return {"route": ADMIT_EXPERIENCE, "value_class": "",
                "reason": "classify-failed (fail-open)"}
    if _value_gate.is_suppressed(vclass):
        return {"route": ADMIT_REJECT, "value_class": vclass,
                "reason": "环境抖动/源码回声不是经验"}
    if vclass == _value_gate.FRICTION:
        return {"route": ADMIT_ADVICE, "value_class": vclass,
                "reason": "助手自身操作摩擦，转避坑建议通道"}
    return {"route": ADMIT_EXPERIENCE, "value_class": vclass, "reason": "真教训"}


def assign_layer(rec_or_kind) -> str:
    """归位（D2）：一条经验属于六层里的哪一层。"""
    if isinstance(rec_or_kind, dict):
        kind = str(rec_or_kind.get("kind") or "")
        if not kind:
            return _layers.EXPERIENCE_LAYER
        return _layers.layer_of_kind(kind)
    return _layers.layer_of_kind(str(rec_or_kind or ""))


def evidence_of(rec: dict) -> dict | None:
    """取结构化证据（D3）；老字符串证据惰性包装。"""
    return _evidence.normalize((rec or {}).get("evidence"))


def conflict_winner(old: dict, new: dict) -> str:
    """同一条经验两版内容冲突时谁说话算（D5）。

    优先级：用户确认 > 会话确定性信号 > 模型自评。返回 "old" / "new"。
    两边一样强时保留旧版（已沉淀资产不被同强度的后来者轻意改写）。
    """
    rank = {"user": 3, "rule": 2, "auto": 1, "judge": 1}
    try:
        g_old = float((old or {}).get("G") or 0)
        g_new = float((new or {}).get("G") or 0)
    except (TypeError, ValueError):
        g_old, g_new = 0.0, 0.0
    score_old = (rank.get(str((old or {}).get("g_source") or ""), 0), g_old)
    score_new = (rank.get(str((new or {}).get("g_source") or ""), 0), g_new)
    return "new" if score_new > score_old else "old"


def should_decay(rec: dict, now: str | None = None) -> str:
    """该不该老化 / 遗忘（D6）。只给结论，动作由 store 层执行。

    规则：距上次被注入命中 ≥90 天 → retire；已被用户遗忘 → 维持 tombstone；
    否则不动。天数判定复用 store 的老化口径（不可注入的失败候选池不在此列）。
    """
    rec = rec or {}
    if int(rec.get("tombstone") or 0):
        return DECAY_FORGET
    from datetime import datetime, timedelta, timezone

    stamp = str(rec.get("last_injected") or rec.get("ts") or "")
    t = parse_ts(stamp)
    if t is None:
        return DECAY_NONE
    now_dt = now or datetime.now(timezone.utc)
    return DECAY_RETIRE if now_dt - t >= timedelta(days=90) else DECAY_NONE


def retrieve_weight(layer_or_kind) -> float:
    """取用层权重（D7）：越大越优先保留在胶囊里。

    与 `assign_layer` 的兜底**故意不同**：D2 问"这东西该算哪层"，未知归 L2；
    这里问"这层/这类该占多少额度"，未知一律 0——谁也不该因为没登记就白拿 L2 的权重。
    """
    if isinstance(layer_or_kind, dict):
        return _layers.weight_of_kind(str(layer_or_kind.get("kind") or ""))
    text = str(layer_or_kind or "")
    if text in _layers.LAYERS:
        return _layers.weight_of_layer(text)
    return _layers.weight_of_layer(_layers.KIND_LAYER.get(text, ""))


def explain(rec: dict) -> dict:
    """一条记录的"身份证"：凭什么进来、属于哪层、证据在哪、能活多久。"""
    rec = rec or {}
    ev = evidence_of(rec)
    g = rec.get("G")
    try:
        g_val = float(g or 0)
    except (TypeError, ValueError):
        g_val = 0.0
    return {
        "layer": assign_layer(rec),
        "value_class": str(rec.get("value_class") or ""),
        "g_source": str(rec.get("g_source") or ""),
        "injectable": g_val >= _gsignal.G_MIN_INJECT and not int(rec.get("tombstone") or 0),
        "evidence": (ev or {}).get("quote", ""),
        "evidence_locatable": (ev or {}).get("locatable"),
        "decay": should_decay(rec),
        "revision": rec.get("revision", 1),
    }
