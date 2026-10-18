"""档 C 空闲后台整理（产品文档）："遗忘/整理"触发。

学习触发（档 A/B）决定"什么时候学"，档 C 决定"什么时候忘"——没有遗忘
触发，降权条目、过期观察、deprecated 残留都没有出路。

C1 纯规则整理（恒跑，零 LLM 成本，同步完成）：
1. 经验条目老化：距上次被注入命中 ≥30 天 → 降权（aged 标记，原文永久保留）；
   ≥90 天 → 移入 deprecated/（30 天可恢复）。失败池（低 G / 被纠正）不做
   90 天淘汰：它是失败模式/偏好画像/纠正补丁的来源，它的出路是观察过期
   与用户否决，不是老化。
   M3 第二钟："从来没用过"也要有出口——从未被注入命中且 ts 距今 >180 天
   → deprecated（30 天后随 deprecated 物理删）。失败池对两个钟都免疫。
2. 失败模式观察过期：观察中（<3 次）且 30 天无新出现 → 标"观察过期"
   （gate 实时复算，本函数负责把标记落进 playbook）。
3. deprecated/ 清理：满 30 天物理删除（既有机制，档 C 是唯一执行者）。
4. maintenance.log + trigger_log（门的审计件）。
5. M3 生命周期：sessions/ 归档 90 天 mtime 保留（与 sessions.jsonl 保留期
   对齐，冷会话的 db 行与归档副本同期消失，不留"有归档无索引"孤儿）。
6. 归档容量三闸（保留期之外的第二维）：sessions/ 总量 >2GB → 削到 1.6GB、
   归档文件数 >4000 → 削、单体 >100MB 的容器库不拷（写入侧拦）。裁剪顺序
   = 孤儿优先 → 其余最旧优先，只删副本不动源文件。
7. 归档压缩（②）：旧 .jsonl 归档转 zstd（<name>.zst）省盘——只压"近期不再改"
   的档（mtime 阈值，对齐 logrotate delaycompress）、压后回读校验、校验通过才删原件；
   读取侧透明解压（`.zst` 由适配器基类认），故复盘/回采无感。候选两条腿：满 14 天，
   **或**单体 ≥32MB 且满 1 天（大档快速通道）。排在 90 天保留清理之后、容量裁剪之前：
   压缩省下的体积直接减少容量闸要删的档。
8. M1 存储自检：三大 JSONL 体积 / 最大单行 / 超容量记录 / 无时间戳记录
   （>0 = 格式漂移黄标信号，与捕获黄标同语义）。

触发条件（daemon 扫描循环每轮判定，每天至多跑一次）：
- 空闲 ≥2 小时：最近 2h 无 session 活动且最近 1h 无真实注入请求
- 当日已有会话结束（**逾期时免**：距上次成功整理 ≥2 天即不再要求）
- ≤1 次/天：日期门由 daemon 的 notify.state 把守，且**只在真正跑过后才盖章**——
  跳过不盖章，当天后续轮次还能补跑。
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from ..time_util import parse_ts

from ..store.store import (SESSION_RECORD_MAX_BYTES, SESSION_RETENTION_DAYS,
                           SESSIONS_HIGH_WATER_BYTES, SESSIONS_MAX_DISK_BYTES,
                           SESSIONS_MAX_FILES)
from . import gate, gsignal

logger = logging.getLogger("experientia.distill.maintenance")

# 参数 = （发版行为，用户侧任何页面不可见）
IDLE_SESSION_SECONDS = 2 * 3600    # 空闲 ≥2h：无 session 活动
IDLE_INJECTION_SECONDS = 3600      # 空闲口径的注入侧：1h 内无 8100 真实注入
AGE_DEMOTE_DAYS = 30               # ≥30 天无注入命中 → 降权（aged）
AGE_RETIRE_DAYS = 90               # ≥90 天无注入命中 → 移入 deprecated/
NEVER_HIT_RETIRE_DAYS = 180        # 第二钟：从未命中 + ts 距今 >180 天 → deprecated
OBSERVE_EXPIRE_DAYS = gsignal.FAILURE_OBSERVE_EXPIRE_DAYS  # 30 天观察过期
# 第⑤环回炉阈值：入口设 refuted≥2 且 refuted>corroborated（次数+对照双门槛，
# 分得开"被证真抵消"的条目）；受限后再涨到 ≥4 → 移出。与"失败≥3 次才固化"同阶防误伤。
REF_DOWNGRADE_REF = 2
REF_EXCLUDE_REF = 4
# sessions/ 归档保留期与 sessions.jsonl 同源（90 天；恢复路径先于清理——
# 归档是 session 的唯一可重解析来源，两者同期消失不留孤儿）
ARCHIVE_RETENTION_DAYS = SESSION_RETENTION_DAYS
# 容量三闸（store 是常量单点，这里只是模块内别名）：保留期挡时间、容量闸挡速率，
# 两个维度都要设——只设保留期时，高频用户的 90 天内照样能撑满磁盘。
ARCHIVE_MAX_DISK_BYTES = SESSIONS_MAX_DISK_BYTES
ARCHIVE_HIGH_WATER_BYTES = SESSIONS_HIGH_WATER_BYTES
ARCHIVE_MAX_FILES = SESSIONS_MAX_FILES

# 逾期补跑：距上次成功整理 ≥2 天时，放宽"当日已有会话结束"这一条。
# 背景：档 C 的每日门由 daemon 的日期字段把守，而**只管日期不管是否真跑过**——
# 于是跨天后的第一次检查若恰好不满足条件（如 0 点刚过、当日还没会话结束），
# 日期就被盖章、当天再也不重试。叠加"长期不开应用"，整理会一直欠着不还。
# 这里补一道逾期判据：只要有整理日志且已隔 ≥2 天，就不再要求"当日有会话"。
# 空闲两条（2h 无 session 活动 / 1h 无真实注入）仍然保留——整理只在空闲时做，
# 不因为逾期就在用户正干活时抢 IO。
MAINTENANCE_OVERDUE_DAYS = 2

# 归档压缩（②）：把「近期不再改」的旧 .jsonl 归档转 zstd（<name>.zst）
# 省盘。语义对齐 logrotate 的 compress + delaycompress：按 mtime 阈值只压旧档，压后
# **回读校验**（zstd 帧 + 全量字节数比对），**校验通过才删原件**（宁可不压，绝不丢数据）。
# 用 zstd 而非 gzip：zstandard 已是既有依赖（codex 冷档 `.zst` 解压在用），比 gzip 更快、
# 比更高（JSONL 约 6~10×）。只针对可流式重放的 **.jsonl** 归档；容器库（.vscdb 等）不动。
# 读取侧透明：`JsonlAdapterBase._open_text` 认 `.zst`（流式解压），故复盘/回采无感。
ARCHIVE_COMPRESS_AFTER_DAYS = 14
ARCHIVE_COMPRESS_MIN_BYTES = 64 * 1024   # 太小的档压了也不省，还添 churn
# 大档快速通道：单体 ≥ 32MB 且龄 ≥ 1 天的档不必等满 14 天——
# 一个 84MB 的会话档裸着两周，是"看着像缓存失控"的主因；实测 zstd 对 JSONL
# 会话档约 7×（24MB 切片实测 6.9~7.7×），早压一周省下的就是几十 MB。
# 小档仍走 14 天：频繁改写小文件只添 churn，省不到多少体积。
ARCHIVE_COMPRESS_BIG_BYTES = 32 * 1024 * 1024
ARCHIVE_COMPRESS_BIG_AFTER_DAYS = 1
ARCHIVE_COMPRESS_SUFFIX = ".zst"


def _ts_age_seconds(ts: str | None) -> float | None:
    """ISO 时间戳距今秒数；空/解析失败 → None（调用方按"不限期"处理）。"""
    t = parse_ts(ts)
    if t is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - t).total_seconds())


def _last_session_activity(store) -> str | None:
    """sessions.jsonl 里最近的 ended_at / started_at（任一通道）。"""
    latest = ""
    for s in store.list_sessions():
        for field in ("ended_at", "started_at"):
            v = str(s.get(field) or "")
            if v > latest:
                latest = v
    return latest or None


def _maintenance_overdue(store) -> bool:
    """距上次**成功**整理是否已达 MAINTENANCE_OVERDUE_DAYS。

    数据源 = maintenance.log 最近一条（每次跑完由 C1-4 写入）。
    **无日志 = 不算逾期**：全新安装不该因为"还没整理过"就绕开"当日有会话"
    这道门，否则首启当天就会跑一次意义不大的全量整理。日志在但时间戳读不出
    同样按不逾期处理（宁可晚跑，不要在依据不可信时抢跑）。
    """
    try:
        rows = store.read_maintenance(limit=1)
    except Exception:  # noqa: BLE001 读日志失败不该挡住整理本身
        return False
    if not rows:
        return False
    age = _ts_age_seconds(str(rows[0].get("ts") or ""))
    return age is not None and age >= MAINTENANCE_OVERDUE_DAYS * 86400


def should_run(store) -> bool:
    """档 C 触发条件：空闲 ≥2h + 当日已有会话结束（逾期时免这一条）。

    每天至多一次由调用方（daemon daily_checks 的日期门）保证；本函数
    只判"现在该不该跑"。"""
    today = datetime.now(timezone.utc).date().isoformat()
    ended_today = False
    latest = ""
    for s in store.list_sessions():
        for field in ("ended_at", "started_at"):
            v = str(s.get(field) or "")
            if v[:10] == today:
                ended_today = True
            if v > latest:
                latest = v
    if not ended_today and not _maintenance_overdue(store):
        return False
    if latest and (_ts_age_seconds(latest) or 0) < IDLE_SESSION_SECONDS:
        return False  # 2h 内还有 session 活动
    inj_age = _ts_age_seconds(store.last_injection_ts())
    if inj_age is not None and inj_age < IDLE_INJECTION_SECONDS:
        return False  # 1h 内还有真实注入（8100 请求）
    return True


def _match_injected(store, inj_items: list[dict], exp: dict) -> dict | None:
    """条目级老化匹配：这条经验对应到哪个"真实注入过的条目"（按注入时间取最近）。

    经验与注入条目的对应用"近重复"（action/state vs 条目 text）——注入的是
    playbook 行，经验是与它同源的原始句，形状不完全一致但高度相近。
    """
    text = str(exp.get("action") or exp.get("state") or "").strip()
    if not text:
        return None
    best = None
    for it in inj_items:
        itext = str(it.get("text") or "").strip()
        if not itext or not store._near_dup(itext, text):
            continue
        if best is None or (str(it.get("last") or "") > str(best.get("last") or "")):
            best = it
    return best


def _age_experiences(store) -> tuple[int, int]:
    """C1-1 经验老化：两个钟，失败池双钟免疫。

    老化锚点从"类别整体命中"下放到"条目命中"：每条经验只与"真实注入过、且与
    它近重复的条目"最近一次命中比——

    第一钟：该条目 ≥30 天无注入命中 → 降权（aged）；≥90 天 → deprecated；
    若该条目被后续高 G 经验佐证（corroborated>0，/ importance 保护位）→
    视为"用对了且仍有用"，本轮不老化（防低频重要实践误杀）。
    第二钟：找不到对应注入条目（从未被注入）+ ts 距今 >180 天 → deprecated。
    返回 (降权条数, 淘汰条数)。
    """
    demoted = retired = 0
    # 先全量物化：iter_experiences 是惰性生成器（持有文件句柄），循环内
    # retire/update 会对同一文件做原子 rename——Windows 上替换打开中的
    # 文件直接 WinError 5。按 (trunk, category) 分组（覆盖所有经验，包括
    # 还没有 playbook 的类别）。
    cats: dict[tuple[str, str], list[dict]] = {}
    for e in store.iter_experiences(include_distilled=True):
        if not e.get("id"):
            continue
        key = (str(e.get("trunk") or "其他"), str(e.get("category") or "未分类"))
        cats.setdefault(key, []).append(e)
    for (trunk, category), items in cats.items():
        inj_items = store.injected_items(trunk, category)
        for e in items:
            exp_id = e["id"]
            is_failure_pool = (float(e.get("G") or 0) < gsignal.G_MIN_INJECT
                               or e.get("corrected"))
            matched = _match_injected(store, inj_items, e)
            if matched is not None:
                # 被佐证 = "用而且用对了" → 保护位，本轮不老化
                if int(matched.get("corroborated") or 0) > 0:
                    continue
                age = _ts_age_seconds(matched.get("last"))
                days = (age or 0) / 86400
                if age is not None and days >= AGE_DEMOTE_DAYS:
                    if days >= AGE_RETIRE_DAYS and not is_failure_pool:
                        if store.retire_experience(exp_id):
                            retired += 1
                    elif not e.get("aged"):
                        store.update_experience(exp_id, {"aged": True})
                        demoted += 1
            elif not is_failure_pool:
                # 第二钟：从未注入命中 + 绝对时间 >180 天
                ts_age = _ts_age_seconds(e.get("ts"))
                if ts_age is not None and ts_age / 86400 >= NEVER_HIT_RETIRE_DAYS:
                    if store.retire_experience(exp_id):
                        retired += 1
    return demoted, retired


def _expire_observations(store) -> int:
    """C1-2 失败模式三态实时校正落盘（原「观察过期」扩展）。

    把 playbook 失败模式行与 gate 权威三态逐行比对，不一致才重写该行：
    观察过期落盘、[Pending]→[Solidified] 提升（防死锁 ≥6 次 / 复现门通过）
    等都在两次蒸馏之间即时生效——否则新固化要等下次蒸馏才进注入，学习延迟。
    行数不变的最小落盘，不变即不写。返回更新的 playbook 数。"""
    updated = 0
    for s in store.list_skills():
        trunk, category = s["trunk"], s["category"]
        md = store.read_skill(trunk, category)
        if not md:
            continue
        states = gate.failure_mode_states(store, trunk, category)
        new_md, in_sec = [], False
        changed = False
        for line in md.splitlines():
            st_line = line.strip()
            if st_line.startswith("## "):
                in_sec = st_line[3:].strip() == "失败模式"
                new_md.append(line)
                continue
            if in_sec and st_line.startswith("-"):
                body = gate._line_body(line)
                st = states.get(body)
                if st:
                    remarked = gate.remark_line(gate._strip_count(body), st)
                    if remarked.strip() != st_line:
                        # 与权威三态不一致（过期/提升/计数变化）→ 校正落盘
                        new_md.append(remarked)
                        changed = True
                        continue
            new_md.append(line)
        if changed:
            store.write_skill(trunk, category, "\n".join(new_md) + "\n")
            updated += 1
    return updated


def _evaluate_refutation(store) -> tuple[int, int, int]:
    """第⑤环回炉评估：被反复反驳、且未被证真抵消的注入条目 → 受限 / 移出。

    - 受限：refuted≥2 且 refuted>corroborated → restricted=1，注入排末、权重降半
    - 移出：restricted 后仍涨到 refuted≥4 且 refuted>corroborated → excluded=1，不再注入
    - 回归：corroborated≥refuted（证真追平/反超）→ 解除受限/移出，恢复注入
    条目数据永不删（只在 injection_hits 挂状态），可回滚、可回归。
    返回 (受限数, 移出数, 恢复数)。单条失败不影响其余。
    """
    now = datetime.now(timezone.utc).isoformat()
    downgraded = excluded = restored = 0
    for key, cat in (store.load_injection_hits() or {}).items():
        if not isinstance(cat, dict):
            continue
        items = cat.get("items") or {}
        if not isinstance(items, dict):
            continue
        trunk, _, category = key.partition("/")
        for iid, entry in items.items():
            if not isinstance(entry, dict):
                continue
            ref = int(entry.get("refuted", 0))
            corr = int(entry.get("corroborated", 0))
            try:
                if ref <= corr and (entry.get("restricted") or entry.get("excluded")):
                    store.set_injection_item_state(
                        trunk, category, iid, restricted=0, excluded=0,
                        restricted_since=None, excluded_since=None)
                    restored += 1
                elif entry.get("excluded"):
                    continue
                elif entry.get("restricted"):
                    if ref > corr and ref >= REF_EXCLUDE_REF:
                        store.set_injection_item_state(
                            trunk, category, iid, restricted=0, restricted_since=None,
                            excluded=1, excluded_since=now)
                        excluded += 1
                elif ref > corr and ref >= REF_DOWNGRADE_REF:
                    store.set_injection_item_state(
                        trunk, category, iid, restricted=1, restricted_since=now)
                    downgraded += 1
            except Exception as exc:
                logger.warning("回炉评估条目失败（跳过）: %s", exc)
    return downgraded, excluded, restored


def _evaluate_adoption(store) -> tuple[int, int]:
    """采纳率降级：注入满 N 次从未被佐证 = "带着没用过"。

    与反驳回炉分账：反驳=被证明错（_evaluate_refutation），零采纳=被证明
    没用——两者都白占注入预算，但证据不同。受限后累计 2×门槛仍零佐证 →
    移出；期间任何一次佐证即豁免（refutation 环的证真回归逻辑会救回受限）。
    probation 期条目不评（试用期由反驳管）。返回 (受限数, 移出数)。
    """
    try:
        from ..config_schema import numeric
        min_inj = int(numeric(store.load_config(), "adopt.min_injections"))
    except Exception:
        min_inj = 5
    now = datetime.now(timezone.utc).isoformat()
    downgraded = removed = 0
    for key, cat in (store.load_injection_hits() or {}).items():
        items = cat.get("items") if isinstance(cat, dict) else None
        if not isinstance(items, dict):
            continue
        trunk, _, category = key.partition("/")
        for iid, entry in items.items():
            if not isinstance(entry, dict) or entry.get("excluded"):
                continue
            if entry.get("probation_left") is not None:
                continue
            try:
                cnt = int(entry.get("count") or 0)
                corr = int(entry.get("corroborated") or 0)
            except (TypeError, ValueError):
                continue
            if corr or cnt < min_inj:
                continue
            try:
                if entry.get("restricted"):
                    if cnt >= 2 * min_inj:
                        store.set_injection_item_state(
                            trunk, category, iid, restricted=0,
                            restricted_since=None,
                            excluded=1, excluded_since=now)
                        removed += 1
                else:
                    store.set_injection_item_state(
                        trunk, category, iid, restricted=1,
                        restricted_since=now)
                    downgraded += 1
            except Exception as exc:
                logger.info("采纳评估条目跳过 %s: %s", iid, exc)
    return downgraded, removed


def _item_effect(store) -> int:
    """逐条判据。

    对每条注入过的条目：被注入的会话（injection.log items 归因）的修正轮数
    均值 vs 该类别全体会话均值 → entry.effect={n,avg,base,delta}。
    n≥2 才出判据（样本不足不出数，#5 不给假数字）；值变化才回写。
    返回更新条数。
    """
    from datetime import timedelta

    window = store.read_injection(
        datetime.now(timezone.utc) - timedelta(days=90),
        datetime.now(timezone.utc) + timedelta(days=1))
    if not window:
        return 0
    sid_corr: dict[str, int] = {}
    sid_cat: dict[str, tuple[str, str]] = {}
    for s in store.list_sessions():
        sid = str(s.get("session_id") or "")
        if not sid:
            continue
        sid_corr[sid] = int(s.get("correction_hits") or 0)
        sid_cat[sid] = (str(s.get("trunk") or "其他"),
                        str(s.get("category") or "未分类"))
    item_sessions: dict[str, set] = {}
    for rec in window:
        iid_s = str(rec.get("session") or "")
        for iid in (rec.get("items") or []):
            item_sessions.setdefault(str(iid), set()).add(iid_s)
    cat_corr: dict[tuple, list[int]] = {}
    for sid, cat_key in sid_cat.items():
        cat_corr.setdefault(cat_key, []).append(sid_corr.get(sid, 0))
    updated = 0
    for key, cat in (store.load_injection_hits() or {}).items():
        items = cat.get("items") if isinstance(cat, dict) else None
        if not isinstance(items, dict):
            continue
        trunk, _, category = key.partition("/")
        base_vals = cat_corr.get((trunk, category)) or []
        base = (sum(base_vals) / len(base_vals)) if base_vals else None
        for iid, entry in items.items():
            sids = item_sessions.get(iid) or set()
            if len(sids) < 2 or base is None:
                continue
            vals = [sid_corr.get(str(s), 0) for s in sids if str(s) in sid_corr]
            if len(vals) < 2:
                continue
            avg = sum(vals) / len(vals)
            effect = {"n": len(vals), "avg": round(avg, 2),
                      "base": round(base, 2), "delta": round(base - avg, 2)}
            if entry.get("effect") != effect:
                try:
                    store.set_injection_item_state(
                        trunk, category, iid, effect=effect)
                    updated += 1
                except Exception as exc:
                    logger.info("逐条判据写入跳过 %s: %s", iid, exc)
    return updated


def _prune_session_archives(store) -> int:
    """M3：sessions/ 归档 90 天 mtime 保留（执行器单一：清理全在 C1）。

    mtime = 最后内容变化 ≈ 会话最后活跃（扫描层 size 变化才重写归档副本）。
    与 sessions.jsonl 的 90 天保留期对齐：冷会话的 db 行与归档副本同期消失，
    不留"有归档无索引"的孤儿。恢复路径：删除前该会话已冷 90 天；agent 原
    文件若还在可重解析（冷会话的恢复价值自然衰减）。
    """
    base = store.dir("sessions")
    cutoff = time.time() - ARCHIVE_RETENTION_DAYS * 86400
    removed = 0
    for agent_dir in base.iterdir():
        if not agent_dir.is_dir():
            continue
        for f in agent_dir.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                continue
    return removed


# ---------- 归档容量三闸（保留期之外的第二维限制） ----------

def _scan_archives(base: Path) -> list[tuple[float, int, Path]]:
    """[(mtime, size, path)]，枚举 sessions/<agent>/ 下的一级文件。"""
    out: list[tuple[float, int, Path]] = []
    if not base.exists():
        return out
    for agent_dir in base.iterdir():
        if not agent_dir.is_dir():
            continue
        for f in agent_dir.iterdir():
            try:
                if f.is_file():
                    st = f.stat()
                    out.append((st.st_mtime, st.st_size, f))
            except OSError:
                continue
    return out


def _orphan_archives(store, files: list[tuple[float, int, Path]]) -> set[Path]:
    """无 sessions.jsonl 索引的 .jsonl 归档（孤儿）——优先裁剪对象。

    只判 .jsonl：容器库副本（state.vscdb 等）文件名不是 session_id，按名字判
    会整片误杀。索引读不出来或为空时整段跳过（宁可不裁，也不在索引异常时批量删）。
    """
    try:
        ids = {(str(s.get("agent") or ""), str(s.get("session_id") or ""))
               for s in store.list_sessions()}
    except Exception:
        return set()
    if not ids:
        return set()
    return {f for _m, _s, f in files
            if f.suffix == ".jsonl" and (f.parent.name, f.stem) not in ids}


def _session_archive_cleanup(store, *, dry_run: bool = False,
                             max_bytes: int | None = None,
                             high_water: int | None = None,
                             max_files: int | None = None) -> dict:
    """sessions/ 归档容量裁剪（体积闸 + 条数闸），返回裁剪报告。

    三个阈值传 None = 取模块常量（**调用时**解析，默认参数在 def 时就绑死了，
    测试 monkeypatch 常量需要这个间接层）。

    触发用上限（max_bytes / max_files）、目标用 high_water，两者之间留 20% 滞回：
    削到刚好等于上限会退化成"每天削一点点"，反复触发且日志噪音大。
    裁剪顺序（对标 OpenClaw enforce）：孤儿优先 → 其余按 mtime 最旧优先；
    两个闸同时判定，任一未达标继续裁。**只删归档副本，源文件不动。**

    dry_run=True 时只算清单不落盘（供体检脚本/UI 预览"现在跑会删什么"）。
    """
    if max_bytes is None:
        max_bytes = ARCHIVE_MAX_DISK_BYTES
    if high_water is None:
        high_water = ARCHIVE_HIGH_WATER_BYTES
    if max_files is None:
        max_files = ARCHIVE_MAX_FILES
    files = _scan_archives(store.dir("sessions"))
    sizes = {f: sz for _m, sz, f in files}
    total = sum(sizes.values())
    n = len(files)
    triggers: list[str] = []
    if total > max_bytes:
        triggers.append("disk")
    if n > max_files:
        triggers.append("files")

    orphans = _orphan_archives(store, files) if triggers else set()
    # 孤儿优先；其余按 mtime 升序（最旧的先走）
    ordered = [f for _m, _s, f in files if f in orphans]
    ordered += [f for _m, _s, f in sorted(
        (x for x in files if x[2] not in orphans), key=lambda x: x[0])]

    evicted: list[Path] = []
    keep_bytes, keep_files = total, n
    if triggers:  # 未触发就一个都不裁：high_water 是"清理后的目标"，不是常态目标
        for f in ordered:
            if keep_bytes <= high_water and keep_files <= max_files:
                break
            evicted.append(f)
            keep_bytes -= sizes[f]
            keep_files -= 1

    removed = 0
    if not dry_run:
        for f in evicted:
            try:
                f.unlink()
                removed += 1
            except OSError:
                continue
    evicted_bytes = sum(sizes[f] for f in evicted)
    # 清单只留前 20 条：裁剪规模可达数千个文件，全量塞进 maintenance.log
    # 一行 JSON 会把日志撑爆（行数封顶管不住单行体积）
    return {"files": n, "bytes": total, "triggers": triggers,
            "orphans": len(orphans), "evicted": [str(f) for f in evicted[:20]],
            "evicted_bytes": evicted_bytes, "evicted_files": len(evicted),
            "removed": removed, "kept_bytes": keep_bytes, "kept_files": keep_files,
            "dry_run": dry_run}


def plan_session_archive_cleanup(store) -> dict:
    """容量裁剪 dry-run 预览：不动任何文件，只报"现在跑会删什么"。"""
    return _session_archive_cleanup(store, dry_run=True)


def enforce_session_archive_budget(store) -> dict:
    """容量裁剪执行体（档 C 每日调用，排在 90 天保留清理之后）。"""
    return _session_archive_cleanup(store, dry_run=False)


# ---------- 归档压缩（②：旧 .jsonl 归档 → zstd，省盘不丢数据） ----------

def _compress_archive(path: Path) -> tuple[int, int]:
    """把单个归档压成 <name>.zst：写临时档 → **回读校验** → 原子改名 → 删原件。

    返回 (原字节, 压缩后字节)。任一步失败抛异常，**原件一律保留**
    （宁可不压，绝不丢数据）。校验 = 流式解压把全部字节读一遍（zstd 帧损坏
    会抛 `BadFrameError`）+ 解压字节数与原文件字节数逐一比对。
    """
    import zstandard

    from ..fs_util import replace_atomic

    st = path.stat()
    raw_size = st.st_size
    final = path.with_name(path.name + ARCHIVE_COMPRESS_SUFFIX)
    tmp = final.with_name(final.name + ".tmp")
    try:
        # write_checksum=True：帧内写入内容校验，损坏在解压时报错（不静默给坏数据）
        cctx = zstandard.ZstdCompressor(level=3, write_checksum=True)
        with path.open("rb") as src, tmp.open("wb") as dst:
            cctx.copy_stream(src, dst)   # 流式，不整文件驻留内存
        dctx = zstandard.ZstdDecompressor()
        got = 0
        with tmp.open("rb") as fh, dctx.stream_reader(fh) as rd:
            while True:
                chunk = rd.read(1 << 20)
                if not chunk:
                    break
                got += len(chunk)
        if got != raw_size:
            raise OSError(
                f"压缩校验字节数不符（原 {raw_size} / 解出 {got}）: {path.name}")
        replace_atomic(tmp, final)
        # 保留原 mtime：归档 mtime = 源文件 mtime（archive 用 shutil.copy2 故保留）
        # = 会话最后活跃，是 90 天保留与"最旧优先"裁剪的唯一依据——压缩若把它刷成
        # "现在"，保留期会被无意延长、裁剪顺序会反转（旧数据反而最后才走）。
        try:
            os.utime(final, (st.st_atime, st.st_mtime))
        except OSError as exc:
            logger.warning("归档压缩后 mtime 还原失败（保留期口径可能偏新）: %s: %s",
                           final.name, exc)
        try:
            path.unlink()
        except OSError as exc:
            # 原件删不掉只剩重复副本，数据无损，不计错（下轮被容量闸按最旧清理）
            logger.warning("归档压缩后原件删除失败（保留重复副本）: %s: %s",
                           path.name, exc)
        return raw_size, final.stat().st_size
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _archive_compression(store, *, dry_run: bool = False,
                         after_days: int | None = None,
                         min_bytes: int | None = None,
                         big_bytes: int | None = None,
                         big_after_days: int | None = None,
                         now: float | None = None) -> dict:
    """旧归档压缩（②），返回报告。

    候选 = **.jsonl** 归档（已压过的 <name>.zst 后缀不是 .jsonl，自然不再入选），
    体积 ≥ min_bytes，且满足下列任一条龄条件：
    - mtime 早于 after_days（默认 ARCHIVE_COMPRESS_AFTER_DAYS）——常规腿；
    - 体积 ≥ big_bytes 且 mtime 早于 big_after_days——大档快速通道。
    阈值传 None = 取模块常量（**调用时**解析，便于测试 monkeypatch）。
    dry_run=True 只列候选与总体积，不动任何文件。
    """
    if after_days is None:
        after_days = ARCHIVE_COMPRESS_AFTER_DAYS
    if min_bytes is None:
        min_bytes = ARCHIVE_COMPRESS_MIN_BYTES
    if big_bytes is None:
        big_bytes = ARCHIVE_COMPRESS_BIG_BYTES
    if big_after_days is None:
        big_after_days = ARCHIVE_COMPRESS_BIG_AFTER_DAYS
    base = time.time() if now is None else now
    cutoff = base - after_days * 86400
    big_cutoff = base - big_after_days * 86400

    def _is_candidate(mtime: float, size: int, path: Path) -> bool:
        if path.suffix != ".jsonl" or size < min_bytes:
            return False
        return mtime < cutoff or (size >= big_bytes and mtime < big_cutoff)

    files = _scan_archives(store.dir("sessions"))
    cands = sorted((x for x in files if _is_candidate(*x)), key=lambda x: x[0])
    before = sum(sz for _m, sz, _f in cands)
    report = {"candidates": len(cands), "bytes_before": before,
              "after_days": after_days, "min_bytes": min_bytes,
              "big_bytes": big_bytes, "big_after_days": big_after_days,
              "compressed": 0, "bytes_after": 0, "saved": 0, "errors": 0,
              # 只留前 20 条：候选可达数千，全量塞日志会撑爆单行
              "sample": [str(f) for _m, _s, f in cands[:20]], "dry_run": dry_run}
    if dry_run:
        return report
    after = 0
    for _m, _sz, f in cands:
        try:
            _raw, comp = _compress_archive(f)
            report["compressed"] += 1
            after += comp
        except Exception as exc:  # noqa: BLE001 单档失败不中断整批（原件保留）
            report["errors"] += 1
            logger.warning("归档压缩失败（原件保留）: %s: %s", f.name, exc)
    report["bytes_after"] = after
    report["saved"] = before - after
    return report


def plan_archive_compression(store) -> dict:
    """压缩 dry-run 预览：不动任何文件，只报"现在跑会压哪些、共多大"。"""
    return _archive_compression(store, dry_run=True)


def compress_old_archives(store) -> dict:
    """压缩执行体（档 C 每日调用，排在 90 天保留清理之后、容量裁剪之前）。"""
    return _archive_compression(store, dry_run=False)


def _storage_health(store) -> dict:
    """M1③ 存储自检（C1 每日）：三大 JSONL 文件体积 / 最大单行字节 /
    超容量记录数（sessions 行 >32KB 契约断路器口径）。

    sessions 无时间戳记录数 >0 = 格式漂移黄标信号（与捕获黄标同语义：
    解析器又丢字段了）——膨胀从"一个月后偶然发现"变成"后台整理一屏可见"。
    """
    health: dict = {}
    for fname in ("sessions.jsonl", "experience.jsonl", "notifications.jsonl"):
        path = store.data_dir / fname
        if not path.exists():
            health[fname] = {"bytes": 0, "max_line_bytes": 0, "oversized": 0}
            continue
        max_line = 0
        oversized = 0
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                n = len(line.encode("utf-8"))
                if n > max_line:
                    max_line = n
                if fname == "sessions.jsonl" and n > SESSION_RECORD_MAX_BYTES:
                    oversized += 1
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        health[fname] = {"bytes": size, "max_line_bytes": max_line,
                         "oversized": oversized}
    health["sessions_no_ts"] = sum(
        1 for s in store.list_sessions() if not s.get("started_at"))
    return health


def _remark_playbooks(store) -> int:
    """三态标记新鲜度（注入读的是 playbook 落盘标记）：坑卡在蒸馏之后才
    升档（seen_in 复现增长 / user_valid 确认）时，[Watching]/[Pending] 不会
    自己变 [Solidified]——等下次蒸馏太慢（纯 rule 小类目可能永远等不到）。
    档 C1 零 LLM 实时复算重标，标记变化才回写（版本戳不动，无变化不写盘）。"""
    changed = 0
    for sk in store.list_skills():
        trunk, category = sk.get("trunk"), sk.get("category")
        if not trunk or not category:
            continue
        md = store.read_skill(trunk, category)
        if not md:
            continue
        try:
            new_md = gate.remark_playbook(md, store, trunk, category)
        except Exception as exc:
            logger.info("playbook 重标跳过 %s/%s: %s", trunk, category, exc)
            continue
        if new_md and new_md != md:
            store.write_skill(trunk, category, new_md)
            changed += 1
    return changed


# ---------- 内容溯源治理（历史"废话"只标记，不删除） ----------

def _looks_like_deterministic(md: str) -> bool:
    """旧确定性兜底产物指纹（蒸馏兜底方案的行为特征）。

    主判据：**标准流程节 = "（无）"**——旧的无模型路径把它写死成占位，模型
    路径不会这么写（模型写了标准流程就说明它真的归纳了）。
    辅助判据：过时项/偏好增量同为占位（≥2 节占位）**且**头部没有方法名
    （旧路径不起名）。两条同时成立才标：**宁可漏标，绝不误伤模型产物**。
    """
    from . import engine_curation
    from ..proxy.inject import parse_playbook

    sections = parse_playbook(md or "")
    if not sections:
        return False
    placeholder = ("（无）", "(无)")
    std = str(sections.get("标准流程") or "").strip()
    if std not in placeholder:
        return False
    hits = sum(1 for k in ("标准流程", "过时项标记", "偏好增量")
               if str(sections.get(k) or "").strip() in placeholder)
    name, _ = engine_curation._parse_name_head(md)  # 旧路径不起名 → 无 name 行
    return hits >= 2 and not name


def run_content_governance(store) -> dict:
    """扫描既有方法卡，命中旧确定性兜底特征的标 ``content_source="none"``。

    **只标记、不删除**（删除必须用户显式操作）——UI 据此在卡片顶部挂溯源条，
    用户知道"这份内容是旧的本机整理产物、接入模型后可更新"。
    幂等：已带 content_source 的卡（模型产物 / 已标记过）一律不动；
    只经 Store 写 ~/.experientia/（数据层铁律）。返回 {"scanned": n, "marked": m}。
    """
    from . import skill as _skill

    scanned = marked = 0
    for sk in store.list_skills():
        trunk, category = sk.get("trunk"), sk.get("category")
        if not trunk or not category:
            continue
        md = store.read_skill(trunk, category)
        if not md:
            continue
        scanned += 1
        source, _ = _skill.provenance_of(md)
        if source:
            continue  # 已判定来源 → 不动（模型卡不被误标；重复跑结果一致）
        if not _looks_like_deterministic(md):
            continue
        store.write_skill(trunk, category,
                          _skill.set_provenance(md, _skill.CONTENT_SOURCE_NONE))
        marked += 1
    if marked:
        try:
            store.append_event(
                "governance",
                f"内容溯源治理：扫 {scanned} 张方法卡，标记 {marked} 张旧整理产物"
                "（content_source=none，未删除）",
                n=marked)
        except Exception as exc:
            logger.warning("治理事件落盘失败（不影响标记）: %s", exc)
    return {"scanned": scanned, "marked": marked}


def run(store, verbose: bool = False) -> dict:
    """跑一次档 C1 整理，返回动作计数（同时落 maintenance.log + trigger_log）。

    每步独立 try/except：单步失败不中断其余步骤，也不杀常驻。
    """
    actions: dict = {}
    try:
        actions["aged_demoted"], actions["aged_retired"] = _age_experiences(store)
    except Exception as exc:
        logger.warning("档 C 经验老化失败: %s", exc)
        actions["aged_error"] = str(exc)
    try:
        (actions["ref_downgraded"], actions["ref_excluded"],
         actions["ref_restored"]) = _evaluate_refutation(store)
    except Exception as exc:
        logger.warning("档 C 回炉评估失败: %s", exc)
        actions["ref_error"] = str(exc)
    try:
        (actions["adopt_downgraded"],
         actions["adopt_removed"]) = _evaluate_adoption(store)
    except Exception as exc:
        logger.warning("档 C 采纳评估失败: %s", exc)
        actions["adopt_error"] = str(exc)
    try:
        actions["effect_updated"] = _item_effect(store)
    except Exception as exc:
        logger.warning("档 C 逐条判据失败: %s", exc)
        actions["effect_error"] = str(exc)
    try:
        actions["obs_expired"] = _expire_observations(store)
    except Exception as exc:
        logger.warning("档 C 观察过期落盘失败: %s", exc)
        actions["obs_error"] = str(exc)
    try:
        actions["playbooks_remarked"] = _remark_playbooks(store)
    except Exception as exc:
        logger.warning("档 C playbook 重标失败: %s", exc)
        actions["remark_error"] = str(exc)
    try:
        actions["deprecated_removed"] = store.clean_deprecated(30)
    except Exception as exc:
        logger.warning("档 C deprecated 清理失败: %s", exc)
        actions["dep_error"] = str(exc)
    try:
        actions["archive_removed"] = _prune_session_archives(store)
    except Exception as exc:
        logger.warning("档 C 归档保留清理失败: %s", exc)
        actions["archive_error"] = str(exc)
    try:
        # 先压缩（14 天+ 旧档）再算预算：压缩省下的体积直接减少容量闸要删的档
        actions["archive_compressed"] = compress_old_archives(store)
    except Exception as exc:
        logger.warning("档 C 归档压缩失败: %s", exc)
        actions["archive_compress_error"] = str(exc)
    try:
        actions["archive_budget"] = enforce_session_archive_budget(store)
    except Exception as exc:
        logger.warning("档 C 归档容量裁剪失败: %s", exc)
        actions["archive_budget_error"] = str(exc)
    try:
        actions["storage"] = _storage_health(store)
    except Exception as exc:
        logger.warning("档 C 存储自检失败: %s", exc)
        actions["storage_error"] = str(exc)
    try:
        store.log_maintenance(actions)
        store.log_trigger("C_maintenance",
                          {"aged": actions.get("aged_demoted", 0),
                           "retired": actions.get("aged_retired", 0),
                           "obs_expired": actions.get("obs_expired", 0),
                           "deprecated_removed": actions.get("deprecated_removed", 0),
                           "archive_removed": actions.get("archive_removed", 0),
                           "archive_evicted": (actions.get("archive_budget") or {}).get(
                               "removed", 0),
                           "archive_compressed": (actions.get("archive_compressed") or {}).get(
                               "compressed", 0),
                           "storage_no_ts": (actions.get("storage") or {}).get(
                               "sessions_no_ts", 0)})
    except Exception as exc:
        logger.warning("档 C 整理日志落盘失败: %s", exc)
    if verbose:
        logger.info("档 C 整理完成: %s", actions)
    return actions
