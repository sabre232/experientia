"""通知中心：推送是用户感知价值的主要渠道，但每一项独立可关、一键静音。

- 4 项类型各自可关（config["notify"]，缺省全开）
- 每日 2 条上限（system_notice 不计入）：超限时新通知仍落列表但不占额度
  （counted=False）；更高优先级到达时可把当天最低优先级的一条降级回列表
- 「全部关闭」= 一键静音（config["notify_muted"]）
- 本模块只管"推什么、推几条"；推送形态不由开关控制，固定为系统级原生通知弹窗
  （GUI 层托盘 showMessage 实现，见 app/gui/qt_tray.notify_native）
- 通知落 notifications.jsonl（可重建的展示层，丢失不伤资产）；
  target 字段记跳转页面 key，设置页列表点击跳对应页
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from .store.store import utcnow

logger = logging.getLogger("experientia.notify")

NOTIFY_TYPES = (
    "method_update",     # 方法动态（合并原 method_new/upgrade/failure_new/preference_new）
    "daily_summary",     # 今日总结（每天 21:00 积累概况）
    "growth_report",     # 成长报告（磨合度档位新高）
    "system_notice",     # 系统通知（合并原 insight）
)
DAILY_CAP = 2  # 每天 2 条（system_notice 除外）

# 旧类型 → 新类型映射（v1.0→v1.1 配置向后兼容，v2.0 可删除此映射）
_OLD_TO_NEW = {
    "method_new": "method_update",
    "method_upgrade": "method_update",
    "failure_new": "method_update",
    "preference_new": "method_update",
    "insight": "system_notice",
    # `update_available` 原也映射到这里，但 app/updater/ 已按
    # 整块移除（产品不自我更新、不联网查更新），该类型再无生产者——
    # 旧配置里残留的这个键会被 notify_config 的"只输出 4 个内容类型键"过滤掉。
}

# 每日上限的优先级裁决（数字小 = 高）
PRIORITY = {
    "method_update": 1,
    "growth_report": 2,
    "daily_summary": 3,
    "system_notice": 4,
}

_DEFAULTS = {t: True for t in NOTIFY_TYPES}

# 磨合度档位（与 store.growth_summary 同口径）；档位上升才推"新高"
_LEVEL_RANK = {"待积累": 0, "低": 1, "中": 2, "高": 3}
_GEDGE_MIN_RANK = 2  # 只有升到中/高才算"新高"（低 = 轮数降 <10%，噪声）
# 键格式迁移哨兵（M2：affinity 键 trunk/category → agent/trunk/category）
_GROWTH_MIGRATED = "_migrated_v3"


def notify_config(config: dict) -> dict:
    """归一化通知开关，只输出 4 个内容类型键（缺省全开）。

    推送形态不在配置里——它固定由 GUI 层决定；残留的形态类键
    （如 v1.x 的 desktop_popup）一律过滤掉，不进入消费方。
    """
    out = dict(_DEFAULTS)
    raw = config.get("notify") or {}
    # 向后兼容：旧类型键映射到新类型
    migrated = {}
    for old_key, new_key in _OLD_TO_NEW.items():
        if old_key in raw:
            migrated.setdefault(new_key, True)
            migrated[new_key] = migrated[new_key] and bool(raw[old_key])
    out.update(migrated)
    out.update({k: v for k, v in raw.items() if k in _DEFAULTS})  # 新键显式覆盖
    return out


def push(store, ntype: str, title: str, body: str = "", target: str = "") -> dict | None:
    """发一条通知：过开关后落盘；每日上限只做"占不占额度"裁决，不丢通知。

    被静音/类型关闭返回 None（静默）；占额度返回 counted=True 的 rec，
    只进列表返回 counted=False 的 rec。
    """
    if ntype not in NOTIFY_TYPES:
        return None
    config = store.load_config()
    cfg = notify_config(config)
    if config.get("notify_muted"):
        return None
    if not cfg.get(ntype, True):
        return None

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    rec = {
        "id": str(uuid.uuid4())[:8],
        "ts": utcnow(),
        "type": ntype, "title": title, "body": body, "target": target,
        "read": False, "counted": ntype != "system_notice",
    }

    # H-N3: 在写锁内完成读-改-写整个周期，防止并发丢失更新
    with store.write_lock():
        records = store.load_notifications()
        if ntype != "system_notice" and rec["counted"]:
            _apply_cap(records, rec, today)
        records.append(rec)
        store.save_notifications(records)
    return rec


def _apply_cap(records: list[dict], rec: dict, today: str) -> None:
    """每日上限：额度未满直接占；满了且新通知优先级更高 → 降级当天最低一条；
    否则新通知只进列表（counted=False）。"""
    counted = [r for r in records
               if str(r.get("ts", ""))[:10] == today and r.get("counted")]
    if len(counted) < DAILY_CAP:
        return
    new_prio = PRIORITY.get(rec["type"], 99)
    lower = [r for r in counted if PRIORITY.get(r.get("type"), 99) > new_prio]
    if lower:
        victim = max(lower, key=lambda r: PRIORITY.get(r.get("type"), 99))
        victim["counted"] = False
    else:
        rec["counted"] = False


# ---------- 触发状态（config["notify_state"]，展示层状态，丢失可重算） ----------

def state_get(store, key: str, default=None):
    return (store.load_config().get("notify_state") or {}).get(key, default)


def state_set(store, key: str, value) -> None:
    """整值替换某个状态键。走 Store.mutate_config：读-改-写在写锁内闭合，
    与并发的配置写入（设置页保存等）不会互相覆盖——同 notify.push 的口径。"""
    def _mut(cfg: dict):
        st = dict(cfg.get("notify_state") or {})
        st[key] = value
        cfg["notify_state"] = st
        return cfg

    store.mutate_config(_mut)


def state_patch(store, key: str, **fields) -> None:
    """只更新某状态键内的指定字段，其余字段原样保留（写锁内读-改-写）。

    state_set 是整值替换。多个调用方各持一份**过时的快照**时，后写者会把先写者
    刚盖的字段回退掉：`daily_checks` 的四个每日任务同写 "daily"，保留清理盖的
    pruned_date 被随后的成长通知覆盖回昨天，于是同一份全量清理一天白跑两遍
    （同理 summary_date）。要盖某几格就用本函数，声明式、不碰兄弟字段。
    """
    if not fields:
        return

    def _mut(cfg: dict):
        st = dict(cfg.get("notify_state") or {})
        cur = dict(st.get(key) or {})
        cur.update(fields)
        st[key] = cur
        cfg["notify_state"] = st
        return cfg

    store.mutate_config(_mut)


def growth_edges(store, affinity: dict) -> list[tuple[str, str, str]]:
    """各类别磨合度档位与上次记忆对比 → 上升沿列表 [(key, 旧档, 新档)]，并刷新记忆。

    只在档位升且新档为中/高时返回（"低"=轮数降 <10%，不推）；
    回落时静默更新记忆，之后再升可以重推。

    键格式迁移（M2：trunk/category → agent/trunk/category）：旧基线键与新键
    不匹配，若直接对比，首轮会对所有中/高类别误报"新高"（旧记忆查无新键 →
    从"无"升到中/高）。检测到旧基线含 2 段键（迁移前格式）时，本轮只落新
    基线 + 迁移哨兵、不推沿；哨兵常驻，次轮起按新键正常对比。
    """
    old = state_get(store, "growth_levels") or {}
    # 迁移检测：旧基线含 2 段键（迁移前格式）→ 本轮仅建立新基线，不推沿
    migrating = any(str(k).count("/") == 1 for k in old)
    edges: list[tuple[str, str, str]] = []
    new_state: dict[str, str] = {}
    for key, a in (affinity or {}).items():
        lvl = (a or {}).get("level") or "待积累"
        new_state[key] = lvl
        if migrating:
            continue  # 迁移轮：只落基线，不推沿（防首轮误报新高）
        if (_LEVEL_RANK.get(lvl, 0) >= _GEDGE_MIN_RANK
                and _LEVEL_RANK.get(lvl, 0) > _LEVEL_RANK.get(old.get(key), 0)):
            edges.append((key, old.get(key) or "待积累", lvl))
    new_state[_GROWTH_MIGRATED] = "1"  # 哨兵常驻，次轮起按新键正常对比
    state_set(store, "growth_levels", new_state)
    return edges


def list_notifications(store, unread_only: bool = False, limit: int = 50) -> list[dict]:
    records = store.load_notifications()
    if unread_only:
        records = [r for r in records if not r.get("read")]
    return records[-limit:][::-1]  # 新在前


def mark_read(store, ids: list[str] | None = None) -> int:
    """ids=None → 全部已读。"""
    # 走公开锁口 store.write_lock()——同文件 push() 已这么用，
    # store.py 的 docstring 也明确要求外部模块别直接摸 `_write_lock`（将来写锁换成
    # RLock 或加锁序约束时，直取私有的地方就是暗礁）。
    with store.write_lock():
        idset = set(ids) if ids else None
        records = store.load_notifications()
        changed = 0
        for rec in records:
            if (idset is None or rec.get("id") in idset) and not rec.get("read"):
                rec["read"] = True
                changed += 1
        if changed:
            store.save_notifications(records)  # 无变更不重写（避免空转写盘）
    return changed


def unread_count(store) -> int:
    return len(list_notifications(store, unread_only=True))
