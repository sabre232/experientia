"""六层记忆模型（P1-1，纪律 D2 归位的唯一权威）。

借鉴混元 Hy Memory 的 L1–L6 分层：**不把记忆揉成一锅**——原话、事实、画像、
摘要、方法、下一步意图的信息形态完全不同，检索时一锅捞等于每次都把 100 轮
对话原文塞给模型。

本模块只做"分层与归位"，不搬运数据：

- `LAYERS`     每层叫什么、存在哪、谁写、留多久；
- `KIND_LAYER` 注入/召回条目（inject 的 kind）→ 层；
- `LAYER_WEIGHT` 召回时的层权重（越大越优先保留）；
- `inventory()`  各层现有多少料（确定性、零模型，给 GUI / 洞察用）。

**不改任何现有行为**：这是给已经存在的产物贴层标，不是重写它们。
介入点只有两处——capsule 取用层权重，intentions 落 L6。
"""

from __future__ import annotations

LAYER_ORDER = ("L1", "L2", "L3", "L4", "L5", "L6")

# 每层的职责与物理落点。clock = 谁负责写（system1 快 / system2 慢）。
LAYERS: dict[str, dict] = {
    "L1": {"name": "原始痕迹", "clock": "system1",
           "home": "sessions.jsonl / capture/archive",
           "weight": 0.0, "retention": "90 天"},
    "L2": {"name": "原子事实", "clock": "system1",
           "home": "experience 条目（task/action/outcome）",
           "weight": 0.4, "retention": "永久（可退休）"},
    "L3": {"name": "身份画像", "clock": "system1",
           "home": "preferences/<trunk>.md",
           "weight": 1.0, "retention": "永久"},
    "L4": {"name": "会话摘要", "clock": "system1",
           "home": "sessions 有界转录 + extract 把手",
           "weight": 0.2, "retention": "90 天"},
    "L5": {"name": "心智模型", "clock": "system2",
           "home": "skills/<trunk>/<category>.md（playbook）",
           "weight": 0.9, "retention": "永久"},
    "L6": {"name": "前瞻意图", "clock": "system2",
           "home": "intentions.jsonl",
           "weight": 0.3, "retention": "14 天"},
}

# 注入/召回条目的 kind（见 app/proxy/inject.py）→ 层。
# 加新 kind 必须同时在此登记，否则 D2 归位会漏。
KIND_LAYER: dict[str, str] = {
    "pref": "L3",          # 偏好画像
    "failure": "L5",       # playbook 失败模式
    "fix": "L5",           # playbook 纠正补丁
    "flow": "L5",          # playbook 标准流程
    "insight": "L5",       # playbook 成功要点
    "intention": "L6",     # 前瞻意图
    "experience": "L2",    # 经验条目（胶囊补捞时入，见 capsule.REFILL_*
}

# 经验库条目不在注入链路里（它由 search 召回），单独一个映射供清单统计用。
EXPERIENCE_LAYER = "L2"

_FALLBACK_LAYER = "L2"   # 未知 kind → 最低可信档，不升到 L5 去冒充方法


def layer_of_kind(kind: str) -> str:
    """条目的 kind → 层。未知类型回落 L2（不谎报成方法卡）。"""
    return KIND_LAYER.get(str(kind or ""), _FALLBACK_LAYER)


def weight_of_layer(layer: str) -> float:
    """层的召回权重。未知层给 0（宁可丢掉，不该掺进来）。"""
    try:
        return float(LAYERS[str(layer)]["weight"])
    except (KeyError, TypeError, ValueError):
        return 0.0


def weight_of_kind(kind: str) -> float:
    return weight_of_layer(layer_of_kind(kind))


def inventory(store) -> dict:
    """各层现有多少料。确定性、零模型、零异常（任何一层读失败记 0）。

    用途：GUI"你的记忆构成"、以及判断 L2→L5 蒸馏是否值得跑
    （L2 攒够而 L5 空 → 该蒸馏了）。失败一律不抛：这是展示面，不能带崩调用方。
    """
    out: dict[str, dict] = {}

    def _count(key: str, fn) -> None:
        layer = LAYERS[key]
        try:
            n = int(fn())
        except Exception:  # noqa: BLE001 展示面：单层读失败只记 0
            n = 0
        out[key] = {"name": layer["name"], "count": n, "home": layer["home"]}

    _count("L2", lambda: len(list(store.iter_experiences(
        include_distilled=True, show_superseded=True))))
    _count("L3", lambda: len(store.list_preference_trunks()))
    _count("L5", lambda: len(store.list_skills()))
    _count("L6", lambda: len(store.list_intentions()))
    # L1/L4 同源（会话记录）：L1 是原件、L4 是派生转录，条数同口径
    try:
        sessions = len(store.list_sessions())
    except Exception:  # noqa: BLE001
        sessions = 0
    for key in ("L1", "L4"):
        out[key] = {"name": LAYERS[key]["name"], "count": sessions,
                    "home": LAYERS[key]["home"]}
    return out
