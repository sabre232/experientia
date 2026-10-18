"""集中 Feature Flag / 开关清单（重构报告  SYS-4 + FLAG-1）。

产品每项常驻能力必须有可关面，且开关集中在 config 的 `features` 段维护，
不散落在各处 `config.get(...)`。缺省全部 True（不改现有体验），提供关闭面。

当前清单（新增能力先在此登记再接入）：
- auto_distill  档 B 阈值自动蒸馏（daemon 每轮 spawn auto_check）
- daily_summary 每日总结 21:00 通知任务
- growth_report 磨合度升档成长通知任务
- background_maintenance  档 C1 空闲后台整理
- background_maintenance_llm 档 C2 LLM 深度整理
- weekly_report 周日结算四段式报告

读取顺序：config.features.<name> → default。
开关值经 config.json 可配（`{"features": {...}}`），UI 后续接入设置页。
"""

from __future__ import annotations

# 常驻任务开关默认值（缺省全开 = 不改变现有体验，只提供关闭面）
FEATURE_DEFAULTS: dict[str, bool] = {
    "auto_distill": True,
    "daily_summary": True,
    "growth_report": True,
    # E-2：会话结束"写仓库记忆"提醒——默认关（防噪音），开启后按通知开关走
    "memory_reminder": False,
    # 档 C：C1 纯规则整理默认开；C2 费 token 且合并可能丢信息 → 默认关
    "background_maintenance": True,
    "background_maintenance_llm": False,
    # 周日结算：每周一次的成长叙事，默认开
    "weekly_report": True,
    # 语义归类 embedding 后端：默认关——需模型文件就位
    # （data_dir/models/*.onnx）+ onnxruntime 可导入；关/缺料自动走 BM25
    "semantic_embedding": False,
}


def feature_enabled(config: dict, name: str, default: bool = True) -> bool:
    """读取某个常驻能力开关。优先 features 段；缺失 → FEATURE_DEFAULTS → default。

    新增能力 = FEATURE_DEFAULTS 加一行 + 使用处调本函数（禁止新写裸 config.get）。
    """
    features = config.get("features")
    if isinstance(features, dict) and name in features:
        return bool(features[name])
    if name in FEATURE_DEFAULTS:
        return FEATURE_DEFAULTS[name]
    return default


# ---------- 数值配置 ----------
# 每个键必须有代码消费方（与 feature 同纪律）；config.json 同形嵌套覆盖默认。
NUMERIC_DEFAULTS: dict[str, int | float] = {
    "inject.top_k": 5,                  # 每节注入条目上限（三因子排序后截断，防 context rot）
    "solidify.probation_sessions": 3,   # 新固化条目试用注入次数（期内被反驳 → 直接移出）
    "events.max_bytes": 8192,           # 单会话事件行字节预算（431MB 教训的容量闸）
    "adopt.min_injections": 5,          # 采纳率评估门槛：注入满 N 次零佐证 → 受限
}


def numeric(config: dict, key: str):
    """读数值配置："段.叶子" 寻址，config 覆盖默认；坏值回落默认不抛。"""
    default = NUMERIC_DEFAULTS.get(key, 0)
    section, _, leaf = key.partition(".")
    v = default
    try:
        sec = config.get(section) if section else config
        if isinstance(sec, dict):
            raw = sec.get(leaf)
            if raw is not None:
                v = raw
    except Exception:
        return default
    if not isinstance(default, (int, float)) or isinstance(default, bool):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return int(f) if isinstance(default, int) else f
