"""G 信号三级打分（产品文档）：能用确定性规则就不用模型。

| 级别 | 触发 | G | g_source |
|------|------|---|----------|
| L1 用户显式 | 桌面端点"有效"/"纠正" | 1.0 / 0.2 + corrected=true | user |
| L2 会话内确定性 | 否定词命中 / 正常收尾 | 0.3 / 0.7 | auto |
| L3 模型自评 | L2 无信号时，二值判定 | 0.8 / 0.4 | judge |

防错误传播：G < 0.5 永不注入，只进失败模式候选池；
被纠正的经验内容改记失败模式；失败 ≥3 次才固化。
"""

from __future__ import annotations

G_MIN_INJECT = 0.5  # G < 0.5 永不注入（红线）
FAILURE_SOLIDIFY_COUNT = 3  # 失败模式计数门：出现 ≥3 次（双门之一）
# 防死锁门已废除（经验链路修复方案）：旧规则「待验证 ≥6 次自动固化」会把
# 从未被反证的噪音碎片推成唯一注入项。固化只看复现门/用户 L1（gate._state_for）。
# FAILURE_PENDING_DEADLOCK_COUNT 常量保留仅作历史数据解读，不再参与判定。
FAILURE_PENDING_DEADLOCK_COUNT = 6  # 已废除（勿在新代码引用）
# 隔离区试用（probation）的行为落在 store（record_injection/反驳出清），
# 名额读 config：solidify.probation_sessions。此处不再重复定义常量。
# 观察过期（档 C1）：观察中（<3 次）且 30 天无新出现 → 不再累计固化计数
FAILURE_OBSERVE_EXPIRE_DAYS = 30
# 成功要点复现门（与失败模式双门同源）：要点来源轨迹 ≥2 条 = 已复现转正
SUCCESS_POINT_PROMOTE_COUNT = 2

L1_VALID = 1.0
L1_CORRECTED = 0.2
L2_CORRECTED = 0.3
L2_CLEAN = 0.7
L2_NEUTRAL = 0.5   # /9.3：中性收尾档——"没被否定 ≠ 成功"，与 L2_CLEAN 分开
L3_CAUSAL = 0.8
L3_WEAK = 0.4

# rule 源（经验链路修复方案）：T1 确定性结构事实（重试成功对/回滚/错误签名）。
# 单次强证据 G=0.4 不注入（红线自动守住）；独立复现 ≥RULE_PROMOTE_SESSIONS
# 个会话升 0.5+ 才准注入——复现门替代语义自信，"数出来的可信"而非"模型说可信"。
RULE_SINGLE = 0.4
RULE_PROMOTED = 0.55
RULE_PROMOTE_SESSIONS = FAILURE_SOLIDIFY_COUNT  # 3，与失败模式双门同数不同义


def effective_g(exp: dict) -> float:
    """读取侧统一 G 口径：rule 源按用户反馈/跨会话复现动态升级，其余取存量 G。
    复现集 = seen_in ∪ {自身 session_id}（与 store._normalize_read_view 同口径）。
    用户确认（user_valid）= 最强证据直接过线；用户否定（user_rejected）= 压回。
    坏 G 值按 0 处理（与 store._normalize_read_view 同口径）——
    一行外部编辑的脏数据不得击穿注入/蒸馏读路径。"""
    try:
        g = float(exp.get("G") or 0)
    except (TypeError, ValueError):
        g = 0.0
    if exp.get("g_source") != "rule":
        return g
    # 价值闸门（方案）：环境抖动/源码回声永不升档注入——先于用户确认，
    # 与 store._normalize_read_view 同口径（护栏 test 锁定两处一致）。
    if exp.get("value_class") in ("env_transient", "signature_garbage"):
        return g
    if exp.get("user_rejected"):
        return RULE_SINGLE
    if exp.get("user_valid"):
        return RULE_PROMOTED
    seen = exp.get("seen_in") or []
    ids = {str(s) for s in seen if s}
    if exp.get("session_id"):
        ids.add(str(exp["session_id"]))
    return RULE_PROMOTED if len(ids) >= RULE_PROMOTE_SESSIONS else g


def score_l1(user_action: str) -> tuple[float, bool]:
    """用户显式反馈：'valid' → 1.0；'corrected' → 0.2 且 corrected=True。"""
    if user_action == "valid":
        return L1_VALID, False
    if user_action == "corrected":
        return L1_CORRECTED, True
    raise ValueError(f"unknown L1 action: {user_action}")


# 明确的成功收尾信号（弱成功信号）：会话以用户短确认/验收结束。
# 只认"短、无否定、含接受词"的最后一条用户消息——长消息不是验收，"不行/不好"不算接受。
_CONFIRM_CLOSE_WORDS = (
    "可以了", "可以", "没问题", "搞定", "完成", "成功", "解决", "好了",
    "完美", "不错", "很好", "好的", "对", "对的", "正确", "没错", "能用",
    "ok", "okay", "done", "works", "working", "great", "nice", "perfect",
)
_NEGATION_WORDS = ("不对", "不行", "不好", "不要", "错了", "不合适", "没用", "重来", "别")


def _is_confirmatory_closing(session_dict: dict) -> bool:
    """会话是否以明确的成功验收收尾（区别于中性的"无信号"收尾）。"""
    msgs = [str(m) for m in session_dict.get("user_messages") or []]
    if not msgs:
        return False
    last = msgs[-1].strip()
    if not last or len(last) > 40:
        return False
    low = last.lower()
    if any(w in low for w in _NEGATION_WORDS):
        return False
    return any(w in low for w in _CONFIRM_CLOSE_WORDS)


def score_l2(session_dict: dict) -> float:
    """会话结束确定性打分：否定命中→纠正；明确成功收尾→成功；否则中性。

     修复：中性收尾与"明确成功"分开，不再把"没被骂"记成成功(0.7)。"""
    if int(session_dict.get("correction_hits") or 0) > 0:
        return L2_CORRECTED
    if _is_confirmatory_closing(session_dict):
        return L2_CLEAN
    return L2_NEUTRAL


def evidence_strength(exp: dict) -> str:
    """证据强度分档（证据加权门槛）：l1 / l2 / l3 / none。

    - l1 = 用户显式（g_source=user，硬证据）；rule 卡经用户确认（user_valid）同级
    - l2 = 会话内确定性成功（g_source=auto）/ rule 跨会话复现（确定性结构证据）
    - l3 = 模型自评成功（g_source=judge，软证据，权重最低）
    - none = G 未过注入门槛，或中性（neutral 标记）不计作确定性成功
    """
    g = float(exp.get("G") or 0)
    if g < G_MIN_INJECT:
        return "none"
    src = exp.get("g_source")
    if src == "user":
        return "l1"
    if src == "rule":
        return "l1" if exp.get("user_valid") else "l2"
    if src == "auto":
        return "none" if exp.get("neutral") else "l2"
    return "l3"


def score_l3(causal: bool) -> float:
    """蒸馏阶段的二值判定结果 → G（不用 1-10 分，模糊分是噪声）。"""
    return L3_CAUSAL if causal else L3_WEAK


def should_inject(g: float) -> bool:
    return g >= G_MIN_INJECT


def is_rule(exp: dict) -> bool:
    """rule 源坑卡（T1 结构事实）：属失败域，永不作成功要点/标准流程证据。"""
    return exp.get("g_source") == "rule"


def high_value_eligible(exp: dict) -> bool:
    """高价值节（成功要点/标准流程）资格：G 过线且非 rule 源。

    rule 卡的 effective_g 升档（复现门）只解锁注入门槛（坑被反复踩就该提醒），
    不能把"cmd:xxx 连败后修好"推进成功要点——那是失败域的结构事实。"""
    if is_rule(exp):
        return False
    return float(exp.get("G") or 0) >= G_MIN_INJECT
