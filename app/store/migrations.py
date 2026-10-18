"""数据目录启动迁移（版本门控，方案 -P1-8）。

背景：P0 修复靠手动运维脚本救开发机——真实老用户升级后库里的逐字兜底
垃圾不会自愈，一切修复对现役版本等于零。本模块把迁移做成产品能力：
引擎（daemon run_forever / GUI 内嵌 scan_loop，两条路都汇于此）启动时
按 meta.json 的 data_version 跑一次。

两阶段（轻重分离）：
- 轻相（同步，秒级）：清库快照 / 派生资产重置 / 历史证据入队 / 盖版本戳。
  全新安装（无经验库无会话）只盖章，不产生任何快照。
- 重相（异步）：归档回采（解析 sessions/ 原件重派生事件行 + mine_all）
  可能分钟级（workbuddy 归档实测数百 MB），只置 backfill_pending 旗标，
  由 scan_loop 起后台线程消化，跑完清旗标——绝不冻结捕获循环。

幂等：每步先探测再动；快照 append-only、清库以"文件已空"为跳过条件；
中途崩溃后重启重跑安全（版本戳最后盖）。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..time_util import parse_ts
from .store import Store

logger = logging.getLogger("experientia.store.migrations")

DATA_VERSION = 4          # 迁移注册表最高版本（新增迁移 = +1 并注册一行）
EVIDENCE_WINDOW_DAYS = 90  # 历史证据入队窗口（拍板 -2）

# ②：归档回采分片 + 断点续跑。回采可能分钟级（workbuddy 归档实测数百 MB），
# 旧口径"一次跑完"期间无法让位、崩溃后要整段重来。改为**按字节预算分批**，
# 每批结束把"已完成档清单"原子写进 meta['backfill_done']（checkpoint 先于输出），
# 崩了下次从断点续跑；全部档处理完才跑一次 mine_all（全局签名聚类不可分片）。
BACKFILL_BATCH_BYTES = 64 * 1024 * 1024   # 每批最多解析这么多字节（防单批过长）
BACKFILL_BATCH_PAUSE_S = 1.0              # 批间主动让位（与扫描循环/界面错峰）
_BACKFILL_DONE_KEY = "backfill_done"

_backfill_lock = threading.Lock()
_backfill_thread: threading.Thread | None = None


def _iso_older(ts: str, cutoff: datetime) -> bool:
    """ISO 时间戳是否早于 cutoff；空/解析失败 → False。

    去重 R1：原实现写了一版 `[:19]` 截断 + 替换尾 Z + 手动补时区，与 store.py
    的 `_ts_older_than` 语义重复。统一走 time_util 解析，失败语义不变。
    """
    t = parse_ts(ts)
    if t is None:
        return False
    return t < cutoff


# ---------- v1：经验链路双端修复（清库重采 + 证据入队 + 回采旗标） ----------

def _append_snapshot(path: Path, lines: list[str]) -> None:
    """快照 append + fsync：归档必须先于清空真正落盘，
    否则崩溃窗口 = 快照没写完、原文件已被清 → 数据两头空。"""
    with path.open("a", encoding="utf-8") as fh:  # append：重跑不覆盖已有快照
        for line in lines:
            fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _v1_clear_experience(store: Store) -> int:
    """experience.jsonl 快照进 deprecated/<日期>/ 后清空。返回快照条数。

    读-快照-清空收口进 Store 写锁 + 原子写——
    与并发 record_session/append_experience 争抢同一文件时不再产生
    半写/丢行（此前裸 write_text 且全程不持锁）。

    索引对账**对"无事可做"路径也要跑**——上次若崩在
    "已清空"与"索引重建"之间，重跑时文件已是空的，早退会让索引永远留着
    已清掉的行（读路径全走索引 → 用户看到"清库了却还在"）。"""
    p = store.data_dir / "experience.jsonl"
    db = getattr(store, "_expdb", None)

    def _reindex() -> None:
        """索引与（可能已清空的）JSONL 对账；必须在写锁外调用。

        用 `rebuild_if_stale` 而非强制重建是刻意的：v1 按版本顺序跑在 v4 之前，
        此时 `experience_source` 还是空的（"sqlite" 标志由 v4 才盖上），指纹
        失配即重建；若标志已是 sqlite，说明 v4 已成功、本迁移不会重跑。"""
        if db is None:
            return
        try:
            db.rebuild_if_stale(p)
        except Exception:
            # 索引重建失败此前无痕吞掉——补留痕（不改控制流）
            logger.warning("v1 清库后 SQLite 索引重建失败（下次启动 sha 失配自愈重建）",
                           exc_info=True)

    if not p.exists():
        _reindex()  # 文件不在 = 空库，索引也必须对齐到空
        return 0
    records: list[str] = []
    with store._write_lock:
        records = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        if records:
            day_dir = store.deprecated_day_dir()
            _append_snapshot(day_dir / "experience_reset.jsonl", records)
            store._write_tmp_rename(p, "")
    if not records:
        _reindex()  # 上次可能崩在"已清空"之后 → 这次补上对账
        return 0
    store._dup_index = None  # 去重内存索引必须作废，否则幽灵合并
    _reindex()
    return len(records)


def _v1_reset_derived_assets(store: Store) -> int:
    """skills/ playbook+_fixes、preferences/ 快照进 deprecated 后清空。

    注入读路径吃 playbook 标记不吃经验库——不重置则"清库了还在注旧垃圾"。
    30 天可恢复由既有 clean_deprecated 治理。"""
    reset_dir = store.deprecated_day_dir("assets_reset")
    moved = 0
    for sub in ("skills", "preferences"):
        base = store.data_dir / sub
        if not base.exists():
            continue
        for f in sorted(base.rglob("*.md")):
            target = reset_dir / sub / f.relative_to(base)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            if target.exists() and target.stat().st_size == f.stat().st_size:
                f.unlink()
                moved += 1
    return moved


def _v1_enqueue_evidence(store: Store) -> int:
    """近 90 天有纠正命中的会话挂进证据队列（片段=命中否定词的用户消息）。"""
    from ..distill.review import _FALLBACK_NEGATION_DEFAULTS

    cutoff = datetime.now(timezone.utc) - timedelta(days=EVIDENCE_WINDOW_DAYS)
    negation = [w for w in (store.load_config().get("negation_words")
                            or _FALLBACK_NEGATION_DEFAULTS) if w]
    n = 0
    for s in store.list_sessions():
        if int(s.get("correction_hits") or 0) <= 0:
            continue
        if _iso_older(str(s.get("started_at") or ""), cutoff):
            continue
        snippets = [str(m).strip()[:160] for m in (s.get("user_messages") or [])
                    if any(w in str(m) for w in negation)][:4]
        if not snippets:
            continue
        n += store.append_pending_review(
            str(s.get("agent") or "unknown"), str(s.get("session_id") or ""),
            snippets=snippets, trunk=s.get("trunk"), category=s.get("category"))
    return n


def _v1_needs_backfill(store: Store) -> bool:
    """有归档原件且存在无事件行的会话 → 需要重相回采。"""
    archives = store.data_dir / "sessions"
    if not archives.exists() or not any(archives.rglob("*")):
        return False
    return any(not s.get("events") for s in store.list_sessions())


def _v2_reclassify_experience(store: Store) -> dict:
    """存量 rule 经验打 value_class 标；env 噪音 / 源码回声下架（快照进
    deprecated，不物理删）。价值闸门方案 。幂等：已打标的不重算。

    整文件重写收口进 Store 写锁 + 原子写（fsync→rename），
    下架快照同样先 fsync 落盘再动主文件。

    索引/类别索引对账对"无事可做"路径也要跑——上次若崩在
    "已重写主文件"与"重建索引"之间，重跑时 dropped/tagged 都是 0，早退会让索引
    继续保留已下架的 env 噪音行（且仍会被注入）。"""
    from ..distill import value_gate

    p = store.data_dir / "experience.jsonl"

    def _reindex() -> None:
        """索引与类别索引对账；必须在写锁外调用。"""
        db = getattr(store, "_expdb", None)
        if db is not None:
            try:
                db.rebuild_if_stale(p)
            except Exception:
                # 索引重建失败补留痕（不改控制流）
                logger.warning("v2 value_gate 后 SQLite 索引重建失败"
                               "（读取侧 sha 失配自愈重建）", exc_info=True)
        try:
            store.rebuild_category_index()
        except Exception:
            logger.warning("v2 迁移后类别索引重建失败（读取侧自愈重建）",
                           exc_info=True)

    if not p.exists():
        _reindex()  # 无文件 = 空库，索引也必须对齐
        return {"tagged": 0, "dropped": 0}
    with store._write_lock:
        kept: list[dict] = []
        dropped: list[dict] = []
        tagged = 0
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                kept.append({"_raw": line})  # 坏行原样保留，绝不吞
                continue
            if (rec.get("g_source") == "rule" and "value_class" not in rec):
                kind = str(rec.get("rule_kind") or "")
                if kind == "error_sig":
                    rec["value_class"] = value_gate.classify(
                        str(rec.get("state") or rec.get("task") or ""))
                else:
                    rec["value_class"] = value_gate.LESSON
                tagged += 1
            if value_gate.is_suppressed(str(rec.get("value_class") or "")):
                dropped.append(rec)
            else:
                kept.append(rec)
        # 无变更时不重写主文件（白抖 mtime/缓存），
        # 但对账照跑——上次可能崩在"重写后、重建前"。
        touched = bool(dropped or tagged)
        if touched:
            if dropped:
                day_dir = store.deprecated_day_dir()
                _append_snapshot(
                    day_dir / "experience_value_gate.jsonl",
                    [json.dumps(rec, ensure_ascii=False) for rec in dropped])
            content = "".join(
                (json.dumps(r, ensure_ascii=False) if "_raw" not in r else r["_raw"])
                + "\n" for r in kept)
            store._write_tmp_rename(p, content)
    if touched:
        store._dup_index = None  # 作废去重内存索引，防幽灵合并
    _reindex()
    return {"tagged": tagged, "dropped": len(dropped)}


def _v3_content_source(store: Store) -> dict:
    """v3：历史"废话"标记（总纲  /）——旧确定性兜底产物标
    ``content_source="none"``，**只标记不删除**（删除必须用户显式操作）。

    幂等：已带 content_source 的卡一律不动（模型产物不会被误标），重复跑
    结果一致；写盘全走 Store（数据层铁律）。
    """
    from ..distill import maintenance

    try:
        rc = maintenance.run_content_governance(store)
    except Exception as exc:
        logger.warning("v3 内容溯源治理失败（下次启动重试）: %s", exc)
        return {"scanned": 0, "marked": 0}
    return {"scanned": int(rc.get("scanned") or 0),
            "marked": int(rc.get("marked") or 0)}


def _v4_experience_sqlite_source(store: Store) -> dict:
    """v4（方案 B）：experience.db 升为经验**唯一事实源**，
    experience.jsonl 降级为导出/备份格式。

    幂等步骤：
    1. 已盖 ``experience_source="sqlite"`` → 跳过；
    2. 索引不可用（fail-open 降级中）→ 不迁移，保持 JSONL 事实源（下次再试）；
    3. 原 ``experience.jsonl`` 复制留档为 ``experience.jsonl.pre-sqlite.bak``
       （**只复制不删除/不改名原文件**——防用户回退旧版本程序后读不到数据；
       随后由导出原子重写 experience.jsonl 为规范快照）；
    4. 盖 meta 标记；
    5. 导出一次当前快照。
    """
    db = getattr(store, "_expdb", None)
    if db is None:
        return {"skipped": True, "reason": "no_index"}
    if db.is_sqlite_source:
        return {"skipped": True}
    p = store.data_dir / "experience.jsonl"
    bak = store.data_dir / "experience.jsonl.pre-sqlite.bak"
    if p.exists() and not bak.exists():
        try:
            if p.stat().st_size > 0:
                shutil.copy2(p, bak)
        except OSError as exc:
            logger.warning("v4 原 JSONL 留档失败（继续，不阻塞）: %s", exc)
    db.set_experience_source("sqlite")
    exported = store.export_experience_snapshot()
    logger.info("v4：experience.db 升为唯一事实源；快照导出 %d 条", exported)
    return {"exported": exported}


def run_startup_migrations(store: Store) -> dict:
    """引擎启动时调用（scan_loop 顶部，两条引擎入口共用 choke point）。

    返回本次执行的摘要（供日志/测试断言）；已最新 → {"skipped": True}。
    任何一步失败只记日志不抛出——迁移绝不能拦死引擎启动。"""
    out: dict = {"skipped": False}
    try:
        meta = store.load_meta()
    except Exception as exc:
        logger.warning("meta.json 读取异常（按 v0 处理）: %s", exc)
        meta = {}
    ver = int(meta.get("data_version") or 0)
    if ver >= DATA_VERSION:
        return {"skipped": True}
    try:
        if ver < 1:
            cleared = _v1_clear_experience(store)
            reset = _v1_reset_derived_assets(store)
            enq = _v1_enqueue_evidence(store)
            try:
                store.rebuild_category_index()
            except Exception:
                # 补留痕（此前 pass 无痕），控制流不变
                logger.warning("v1 迁移后类别索引重建失败（读取侧自愈重建）",
                               exc_info=True)
            if cleared or reset or enq:
                store.append_changelog(
                    f"自动迁移 v1（经验链路修复）：清库 {cleared} 条（快照进 deprecated）· "
                    f"派生资产重置 {reset} 个 · 证据入队 {enq} 条")
            out.update(cleared=cleared, assets_reset=reset, enqueued=enq)
            if _v1_needs_backfill(store):
                store.save_meta({"backfill_pending": True})
                out["backfill_pending"] = True
        if ver < 2:
            rc = _v2_reclassify_experience(store)
            if rc["tagged"] or rc["dropped"]:
                store.append_changelog(
                    f"自动迁移 v2（经验价值闸门）：打标 {rc['tagged']} 条 · "
                    f"下架环境噪音/源码回声 {rc['dropped']} 条（快照进 deprecated）")
            out.update(value_tagged=rc["tagged"], value_dropped=rc["dropped"])
        if ver < 3:
            rc = _v3_content_source(store)
            if rc["marked"]:
                store.append_changelog(
                    f"自动迁移 v3（内容溯源）：扫描 {rc['scanned']} 张方法卡，"
                    f"标记 {rc['marked']} 张旧整理产物（content_source=none，未删除）")
            out.update(content_scanned=rc["scanned"], content_marked=rc["marked"])
        if ver < 4:
            rc = _v4_experience_sqlite_source(store)
            if not rc.get("skipped"):
                store.append_changelog(
                    f"自动迁移 v4（经验事实源切换）：experience.db 升为唯一事实源，"
                    f"原 experience.jsonl 留档为 .pre-sqlite.bak，快照导出 "
                    f"{rc.get('exported')} 条")
            out.update(sqlite_source=rc)
        store.save_meta({"data_version": DATA_VERSION})
    except Exception as exc:
        logger.warning("启动迁移异常（引擎继续，下次启动重试）: %s", exc)
        out["error"] = str(exc)
    return out


# ---------- 重相：归档回采（后台线程，scan_loop 按旗标拉起一次） ----------

def backfill_from_archive(store: Store, limit: int = 0) -> tuple[int, int]:
    """解析 sessions/<agent>/ 归档原件 → 重落 sessions.jsonl（派生事件行）
    → mine_all（含全局签名聚类）。返回 (回采会话数, 坑卡落/合并数)。

    单文件失败跳过不中断。"""
    from ..capture.models import SessionRef
    from ..capture.registry import REGISTRY
    from ..capture.scan import session_to_review_dict
    from ..distill import mining

    sessions_dir = store.data_dir / "sessions"
    seen_keys: set[tuple[str, str]] = set()
    if sessions_dir.exists():
        for agent_dir in sorted(sessions_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            agent = agent_dir.name
            adapter_cls = REGISTRY.get(agent)
            if adapter_cls is None:
                logger.info("回采跳过无适配器的归档目录: %s", agent)
                continue
            adapter = adapter_cls()
            for f in sorted(agent_dir.iterdir()):
                if f.name.endswith((".tmp", ".bak")):
                    continue
                stem = f.name[:-len(".zst")] if f.name.endswith(".zst") else f.name
                sid = stem[:-len(".jsonl")] if stem.endswith(".jsonl") else stem
                try:
                    ref = SessionRef(agent=agent, session_id=sid, path=f,
                                     size=f.stat().st_size, mtime=f.stat().st_mtime)
                    parsed = adapter.parse_sessions(ref)
                except Exception as exc:
                    logger.info("回采解析失败跳过 %s/%s: %s", agent, f.name, exc)
                    continue
                for session in parsed:
                    if not session or not session.session_id:
                        continue
                    key = (agent, session.session_id)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    try:
                        store.record_session(session_to_review_dict(session, store))
                    except Exception as exc:
                        logger.info("回采落库失败跳过 %s/%s: %s", *key[:2], exc)
                    if limit and len(seen_keys) >= limit:
                        break
                if limit and len(seen_keys) >= limit:
                    break
            if limit and len(seen_keys) >= limit:
                break
    cards = mining.mine_all(store)
    return len(seen_keys), cards


def _archive_units(store: Store) -> list[tuple[str, str, Path]]:
    """列全部可回采的归档单元 [(agent, sid, path)]。

    - 只收有适配器的 agent 目录；跳过 `.tmp` / `.bak`（含压缩的中间态 `.zst.tmp`）。
    - **identity = (agent, sid)，sid 剥掉 `.jsonl` / `.jsonl.zst` 后缀**：归档压缩
      （`x.jsonl` → `x.jsonl.zst`）不改变 identity，否则压缩后的档会被误判为"新档"
      而重复回采（重复本身幂等，只是白跑）。
    """
    from ..capture.registry import REGISTRY

    out: list[tuple[str, str, Path]] = []
    base = store.data_dir / "sessions"
    if not base.exists():
        return out
    for agent_dir in sorted(base.iterdir()):
        if not agent_dir.is_dir():
            continue
        agent = agent_dir.name
        if REGISTRY.get(agent) is None:
            logger.info("回采跳过无适配器的归档目录: %s", agent)
            continue
        for f in sorted(agent_dir.iterdir()):
            if not f.is_file() or f.name.endswith((".tmp", ".bak")):
                continue
            stem = f.name[:-len(".zst")] if f.name.endswith(".zst") else f.name
            sid = stem[:-len(".jsonl")] if stem.endswith(".jsonl") else stem
            out.append((agent, sid, f))
    return out


def _load_backfill_done(store: Store) -> dict[str, set[str]]:
    try:
        raw = store.load_meta().get(_BACKFILL_DONE_KEY) or {}
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(a): {str(s) for s in (v or []) if s} for a, v in raw.items()}


def backfill_batch(store: Store, *,
                   byte_budget: int = BACKFILL_BATCH_BYTES) -> dict:
    """回采**一批**尚未完成的归档单元，返回进度报告（**不跑 `mine_all`**）。

    已完成清单持久化在 `meta['backfill_done']`，每批结束后原子写盘——对应可恢复
    批处理的通行约束「checkpoint 需与输出原子或先于输出」：崩在"已落库未记录"时
    只会重跑该批一次（`record_session` 按 (agent, sid) 幂等，不产生重复行）。

    解析失败的档也计入已完成（与旧口径"单文件失败跳过不中断"一致），否则剩余数
    永不归零、批次无限循环；失败档记 warning。
    """
    from ..capture.models import SessionRef
    from ..capture.registry import REGISTRY
    from ..capture.scan import session_to_review_dict

    adapter_cache: dict[str, object] = {}
    done = _load_backfill_done(store)
    units = _archive_units(store)
    pending = [u for u in units if u[1] not in done.get(u[0], set())]

    batch: list[tuple[str, str, Path]] = []
    used = 0
    for agent, sid, path in pending:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        # 至少收 1 档（单档超预算也必须推进，否则永远卡在同一档）
        if batch and used + size > byte_budget:
            break
        batch.append((agent, sid, path))
        used += size

    processed = passed = 0
    for agent, sid, path in batch:
        adapter = adapter_cache.get(agent)
        if adapter is None:
            adapter = adapter_cache[agent] = REGISTRY[agent]()
        try:
            ref = SessionRef(agent=agent, session_id=sid, path=path,
                             size=path.stat().st_size, mtime=path.stat().st_mtime)
            parsed = adapter.parse_sessions(ref)
        except Exception as exc:
            logger.info("回采解析失败跳过 %s/%s: %s", agent, path.name, exc)
            parsed, passed = [], passed + 1
        for session in parsed:
            if not session or not session.session_id:
                continue
            try:
                store.record_session(session_to_review_dict(session, store))
                processed += 1
            except Exception as exc:
                logger.info("回采落库失败跳过 %s/%s: %s",
                            agent, session.session_id, exc)
        done.setdefault(agent, set()).add(sid)

    if batch:
        _save_backfill_done(store, done)
    units_done = sum(1 for a, s, _p in units if s in done.get(a, set()))
    return {"processed": processed, "passed": passed,
            "units_total": len(units), "units_done": units_done,
            "remaining": max(0, len(units) - units_done)}


def _save_backfill_done(store: Store, done: dict[str, set[str]]) -> None:
    """原子写回已完成档清单（经 Store，meta.json 的 tmp+rename）。"""
    store.save_meta({_BACKFILL_DONE_KEY: {a: sorted(v) for a, v in done.items() if v}})


def _run_backfill_task(store: Store) -> None:
    """分片回采执行体（②）：逐批推进 + 断点续跑，全部完成后收尾一次。

    收尾 = 跑一次 `mine_all`（全局签名聚类，不可分片）→ 清 `backfill_pending`
    与进度清单。任何异常都保留旗标（下次启动从断点继续），不丢已完成进度。
    """
    try:
        total_sess = 0
        rep = {"units_total": 0, "units_done": 0, "remaining": 0,
               "processed": 0, "passed": 0}
        while True:
            rep = backfill_batch(store)
            total_sess += rep["processed"]
            if rep["remaining"] <= 0:
                break
            if rep["processed"] == 0 and rep["passed"] == 0:
                logger.warning("回采批次无进展（%d/%d），本轮中止待下轮",
                               rep["units_done"], rep["units_total"])
                return
            time.sleep(BACKFILL_BATCH_PAUSE_S)
        from ..distill import mining

        cards_n = mining.mine_all(store)
        store.append_changelog(
            f"自动迁移 v1 回采：会话 {total_sess} 个 · 坑卡 {cards_n} 条"
            f"（分 {rep['units_total']} 档，断点续跑）")
        logger.info("回采完成：会话 %d 个 · 坑卡 %d 条", total_sess, cards_n)
    except Exception as exc:
        logger.warning("回采失败（旗标保留，下次启动从断点续跑）: %s", exc)
        return
    store.save_meta({"backfill_pending": False, _BACKFILL_DONE_KEY: {}})


def spawn_backfill_if_pending(store: Store) -> bool:
    """scan_loop 每轮调用：旗标在且无在跑线程 → 起后台回采（宁慢勿堵）。"""
    global _backfill_thread
    try:
        pending = bool(store.load_meta().get("backfill_pending"))
    except Exception:
        return False
    if not pending:
        return False
    with _backfill_lock:
        if _backfill_thread is not None and _backfill_thread.is_alive():
            return False
        _backfill_thread = threading.Thread(
            target=_run_backfill_task, args=(store,),
            name="experientia-backfill", daemon=True)
        _backfill_thread.start()
    return True
