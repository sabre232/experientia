"""System1 / System2 显式化（P1-1/P1-2：快写与慢沉淀拆成两段）。

借鉴混元的双系统：**用户开口那一秒只做快写，慢沉淀绝不挡路**。以前这两段散在
捕获、复盘、蒸馏、洞察四处，"谁负责写哪一层"得靠读代码推出来；这里把顺序和边界
写死：

    System1（快，毫秒级，零模型）
      会话落 L1 → 注意力闸 → 有信号才入复盘队列 → （有模型才）跑复盘
      全程不调模型；没模型也不丢数据（证据队列兜底）。

    System2（慢，秒~分钟级，可降级）
      去重合并（D4）→ 模式检测 → 方法卡蒸馏 L5 → 洞察卡 → L6 意图沉淀 → 过期清理
      单线程跑（daemon 的 auto_check worker 已是这个形态），任一步失败只跳过该步。

**本模块是编排层，不新增加载路径**：`engine_curation.auto_check` 仍是慢路径的
唯一驱动，daemon 工作线程改调 `system2_consolidate`（内部再调 auto_check），
不会出现"同一轮跑两遍"。
"""

from __future__ import annotations

import logging

from . import intents
from . import layers as _layers

logger = logging.getLogger("experientia.distill.pipeline")


def system1_intake(store, session_dict: dict) -> dict:
    """快路径：一次会话结束时的实时处理（零模型、有界）。

    生产接线：`review.defer_to_replay` 调本函数，它是三条
    降级路径（无模型 / 模型调用异常 / 输出不可解析）与文件通道
    （`capture/scan.review_sessions`）共用的挂起入口；两条收尾链路
    （`capture/hook._run_stop_review`、`proxy/server.on_session_end`）都经
    `review.maybe_review_session` 到 `defer_to_replay`，因此本函数在生产上
    真的会被调用，不再是只被测试调用的编排壳。

    返回 `{queued, signals}`。只做"不丢"的两件事：

    1. 注意力闸预判：没有可蒸馏信号就不入队（`has_distillable_signals`）；
    2. 入复盘队列（`review.enqueue_for_replay`，超容量由队列自己的背压处理）。

    复盘本身（要调模型）不在这里做——绝不阻塞用户那一秒。
    """
    from . import review

    out = {"queued": 0, "signals": False}
    try:
        if not review.has_distillable_signals(session_dict):
            return out
        out["signals"] = True
        out["queued"] = int(review.enqueue_for_replay(store, session_dict))
    except Exception as exc:  # noqa: BLE001 快路径失败绝不抛给调用方
        logger.warning("System1 入队失败（不阻断捕获）: %s", exc)
    return out


def system2_consolidate(store, *, verbose: bool = False,
                        derive_intents: bool = True) -> dict:
    """慢路径：一次完整的沉淀轮。顺序固定，任一步失败不影响其余步骤。

    1. `engine_curation.auto_check`——阈值蒸馏 L5 + 洞察卡（既有驱动，含模型调用）；
    2. `intents.derive_intentions`——从本轮模式沉淀 L6 前瞻意图（零模型）；
    3. `prune_expired_intentions`——清掉过期 / 已忽略的 L6。

    第 1 步失败（模型不可用 / 熔断）只跳过它：**沉淀不该被模型绑票**。
    """
    from . import engine_curation

    out: dict = {"distilled": [], "intents": 0, "pruned": 0}
    try:
        out["distilled"] = engine_curation.auto_check(store, verbose=verbose)
    except Exception as exc:  # noqa: BLE001 蒸馏失败不影响后面的步骤
        logger.warning("System2 蒸馏步骤失败（跳过该步）: %s", exc)
    if derive_intents:
        try:
            out["intents"] = intents.derive_intentions(store)
        except Exception as exc:  # noqa: BLE001
            logger.warning("System2 意图沉淀失败（跳过）: %s", exc)
    try:
        out["pruned"] = int(store.prune_expired_intentions())
    except Exception as exc:  # noqa: BLE001
        logger.warning("System2 意图清理失败（跳过）: %s", exc)
    return out


def layer_summary(store) -> dict:
    """各层存量快照（给 GUI / 排障：材料现在堆在哪一层）。"""
    try:
        return _layers.inventory(store)
    except Exception as exc:  # noqa: BLE001
        logger.warning("层存量统计失败: %s", exc)
        return {}
