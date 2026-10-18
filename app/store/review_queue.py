"""`Store` 的「复盘队列与台账」域 mixin（M3 背压 +  台账 + H7 在飞窗口）。

从 `store.py` 的 `class Store` 拆出的第十一个域。承载三块：

- **复盘队列背压**：队列满时挂起的 (agent, session_id) 清单，下轮扫描从
  落库记录重建 review dict 再入队；溢出降级冷存（DLX 口径）防 FIFO 静默挤丢。
- **复盘台账**（档 A「触发一次」）：(agent, session_id) 复盘去重，防活会话
  文件每轮重解析导致同一会话被反复复盘、经验库落重复行。
- **在飞窗口**：入队只记「在飞」，复盘成功后摘掉；窗口内不重复入队，
  超窗才允许重试——兼顾「别空转」与「失败要能重来」。

约定与其余 mixin 一致：方法体**逐字搬移**、签名与返回值一律不变；共享状态
（`data_dir` / `_write_lock` / `_iter_jsonl` / `_write_tmp_rename` /
`_cap_jsonl_lines` / `_reviewed` / `_queued_reviews`）留在 `Store` 主体、靠
`self` 访问；**不 import `store.py`**（避免与 `class Store` 的组装形成循环导入）。

常量随本域搬移（原先定义在 store.py 模块级），`store.py` 侧保留同名再导出——
外部从 app.store.store import 它们，`tests/test_h7_*` 还 monkeypatch 打桩
`store_mod.REVIEW_RETRY_AFTER_S`。**注意**：常量搬家后，打桩目标要跟着改成
本模块（见 test_h7_review_retry / test_h7_cross_channel），否则改的是 store.py
那个再导出的副本、`should_enqueue_review` 读的仍是本模块的，打桩静默失效。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..time_util import parse_ts
from ._shared import utcnow

# 复盘队列背压：队列满时挂起的 (agent, session_id) 清单（下轮扫描从落库
# 记录重建 review dict 再入队），封顶防自身膨胀。
# 溢出降级冷存（质量挂账，RabbitMQ DLX 口径）：目标用户可能数月不接
# 模型，FIFO 静默挤丢 = 证据永久丢；超容量的旧条目搬入冷存文件仍可查。
PENDING_REVIEWS_FILE = "pending_reviews.jsonl"
PENDING_REVIEWS_MAX_LINES = 200
PENDING_ARCHIVE_FILE = "pending_archive.jsonl"
PENDING_ARCHIVE_MAX_LINES = 500

# 档 A「触发一次」：(agent, session_id) 复盘台账。活会话文件持续增长时
# 每轮扫描都会重解析（size/mtime 变化），若无台账，同一会话会被反复入队复盘
# ——LLM 对同一段会话多次提炼，措辞漂移会击穿 (agent,task,action) 精确去重，
# 经验库落下同一经验的重复行（用户可见 = 经验 tab 重复卡片）。台账封顶防自身
# 膨胀；最旧条目被挤出后，对应会话若文件再变至多被重新复盘一次（无害）。
REVIEWED_FILE = "reviewed_sessions.jsonl"
REVIEWED_MAX_LINES = 5000

# ，用户拍板）：复盘**成功后**才进 reviewed_sessions；入队只记
# 「在飞」，成功后摘掉。独立文件，不复用 pending_reviews.jsonl——后者是带
# snippets 证据片段的「未提炼队列」，UI 在消费它（复用会污染语义）。
REVIEW_QUEUED_FILE = "queued_reviews.jsonl"
REVIEW_QUEUED_MAX_LINES = 5000
# 在飞多久后允许重新入队（= 失败重试的等待窗口）。设窗口而不是"每次扫描都重入"
# 是为了防活会话文件每轮都在长时被反复复盘——措辞漂移会击穿经验侧精确去重。
REVIEW_RETRY_AFTER_S = 2 * 3600


class ReviewQueueMixin:
    """复盘队列背压、复盘台账与在飞窗口的读写。"""

    # ---------- 复盘队列背压（M3：队列满挂起项，下轮扫描从落库记录恢复） ----------

    def append_pending_review(self, agent: str, session_id: str,
                              snippets: list[str] | None = None,
                              trunk: str | None = None,
                              category: str | None = None) -> int:
        """挂起一条 (agent, session_id) 进证据队列（同键去重，封顶 200 行）。

        两个来源共用此队列（修复方案）：
        - M3 队列背压：复盘队列满时纯键挂起（无片段），下轮从落库记录重建；
        - 无模型降级：`review.enqueue_for_replay` 一并带上否定词命中片段，
          供「未提炼片段」视图展示——片段只是现场证据，永远不是经验、永不注入。
           M5 起片段是可选的：`req_count≥6` 的干净长会话同样挂起，
          只是没有片段可展示。
        复盘只消费落库记录里已有的字段，故可从 list_sessions() 重建 review dict
        再入队——这是唯一的无损恢复路径（ref 签名首轮解析后已更新，关闭的文件
        下轮扫描会被跳过，不能靠重新解析兜底）。返回 1=新挂起，0=已在队。"""
        if not agent or not session_id:
            return 0
        key = (str(agent), str(session_id))
        rec: dict = {"agent": key[0], "session_id": key[1], "ts": utcnow()}
        if snippets:
            rec["snippets"] = [str(s)[:200] for s in snippets[:4]]
        if trunk:
            rec["trunk"] = str(trunk)[:40]
        if category:
            rec["category"] = str(category)[:40]
        # 归档引用（-P1-4，Zep episode 范式）：重放前回读原件全文，
        # 不吃落库截断转录（20×200 是展示口径，不是复盘素材口径）
        arc = self.data_dir / "sessions" / key[0] / f"{key[1]}.jsonl"
        if arc.exists():
            rec["ref"] = f"sessions/{key[0]}/{key[1]}.jsonl"
        with self._write_lock:
            pathf = self.data_dir / PENDING_REVIEWS_FILE
            lines: list[str] = []
            if pathf.exists():
                lines = [l for l in pathf.read_text(encoding="utf-8").splitlines()
                         if l.strip()]
            for l in lines:
                try:
                    existing = json.loads(l)
                except json.JSONDecodeError:
                    continue
                if (existing.get("agent"), str(existing.get("session_id", ""))) == key:
                    return 0  # 已挂起，不重复（先来片段保真，不被覆盖）
            lines.append(json.dumps(rec, ensure_ascii=False))
            if len(lines) > PENDING_REVIEWS_MAX_LINES:
                # 溢出降级冷存（DLX 口径）：被挤出的旧条目进 pending_archive，
                # 永不静默丢（冷存自身封顶 500，最老再溢才弃）
                spilled = lines[:-PENDING_REVIEWS_MAX_LINES]
                lines = lines[-PENDING_REVIEWS_MAX_LINES:]
                apf = self.data_dir / PENDING_ARCHIVE_FILE
                old: list[str] = []
                if apf.exists():
                    old = [l for l in apf.read_text(encoding="utf-8").splitlines()
                           if l.strip()]
                merged = (old + spilled)[-PENDING_ARCHIVE_MAX_LINES:]
                self._write_tmp_rename(apf, "\n".join(merged) + "\n")
            self._write_tmp_rename(pathf, "\n".join(lines) + "\n")
            return 1

    def load_pending_archive_records(self) -> list[dict]:
        """冷存证据（被主队列溢出降级的旧片段，可查不注入）。"""
        out: list[dict] = []
        for rec in self._iter_jsonl(PENDING_ARCHIVE_FILE):
            if isinstance(rec, dict):
                out.append(rec)
        return out

    def load_pending_reviews(self) -> list[tuple[str, str]]:
        """挂起清单 [(agent, session_id), ...]（文件序 = 挂起序）。"""
        return [(str(rec["agent"]), str(rec["session_id"]))
                for rec in self.load_pending_review_records()]

    def load_pending_review_records(self) -> list[dict]:
        """挂起记录全量（含可选 snippets/trunk/category，「未提炼片段」视图用）。"""
        out: list[dict] = []
        for rec in self._iter_jsonl(PENDING_REVIEWS_FILE):
            if isinstance(rec, dict) and rec.get("agent") and rec.get("session_id"):
                out.append(rec)
        return out

    def drop_pending_review(self, agent: str, session_id: str) -> None:
        """恢复成功（或落库记录已不存在）后移除挂起项。"""
        key = (str(agent), str(session_id))
        with self._write_lock:
            pathf = self.data_dir / PENDING_REVIEWS_FILE
            if not pathf.exists():
                return
            lines = [l for l in pathf.read_text(encoding="utf-8").splitlines()
                     if l.strip()]
            kept: list[str] = []
            for l in lines:
                try:
                    rec = json.loads(l)
                except json.JSONDecodeError:
                    continue
                if (rec.get("agent"), str(rec.get("session_id", ""))) == key:
                    continue
                kept.append(l)
            if len(kept) != len(lines):
                self._write_tmp_rename(
                    pathf, "\n".join(kept) + ("\n" if kept else ""))

    # ---------- 复盘台账（档 A「触发一次」） ----------

    def _build_reviewed_set(self) -> set[tuple[str, str]]:
        s: set[tuple[str, str]] = set()
        for rec in self._iter_jsonl(REVIEWED_FILE):
            if isinstance(rec, dict) and rec.get("agent") and rec.get("session_id"):
                s.add((str(rec["agent"]), str(rec["session_id"])))
        return s

    def _reviewed_snapshot(self) -> set[tuple[str, str]]:
        """惰性构建"已复盘"集合（**调用方须持写锁**）。

        锁外"判空→构建→整体赋值"会让锁外构建的旧快照覆盖掉并发
        mark_reviewed 刚 add 的键——该会话回退成"未复盘"被反复复盘。"""
        if self._reviewed is None:
            self._reviewed = self._build_reviewed_set()
        return self._reviewed

    def _queued_snapshot(self) -> dict[tuple[str, str], str]:
        """惰性构建"在飞"映射（**调用方须持写锁**，同上）。"""
        if self._queued_reviews is None:
            self._queued_reviews = self._build_queued_map()
        return self._queued_reviews

    def is_reviewed(self, agent: str | None,
                    session_id: str | None) -> bool:
        """该 (agent, session_id) 是否已入过复盘队列（两通道共用口径）。

        无 agent/session_id 的异常记录返回 False（保持旧行为：照常入队，
        靠经验侧 (agent,task,action) 去重兜底，不因台账缺键而丢复盘）。"""
        if not agent or not session_id:
            return False
        key = (str(agent), str(session_id))
        with self._write_lock:  # 读侧也持锁（快照与并发写序一致）
            return key in self._reviewed_snapshot()

    def mark_reviewed(self, agent: str | None, session_id: str | None) -> None:
        """标记 (agent, session_id) 已复盘（幂等；台账封顶防自身膨胀）。

        在**入队点**调用（文件通道 run_scan / 代理通道 on_session_end）——
        入队即视为「已安排一次复盘」，与复盘是否产出一条经验无关。"""
        if not agent or not session_id:
            return
        key = (str(agent), str(session_id))
        # 内存改与文件写必须在**同一临界区**。原来
        # `_reviewed.add(key)` 在锁外，与并发写交错时内存会落后于文件 →
        # should_enqueue_review 提前放行重复入队（重复 LLM 成本 + 重复复盘）。
        with self._write_lock:
            reviewed = self._reviewed_snapshot()
            if key in reviewed:
                return
            reviewed.add(key)
            with (self.data_dir / REVIEWED_FILE).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(
                    {"agent": key[0], "session_id": key[1], "ts": utcnow()},
                    ensure_ascii=False) + "\n")
            self._cap_jsonl_lines(self.data_dir / REVIEWED_FILE,
                                  REVIEWED_MAX_LINES)
            # 任何通道标记「已复盘」都要顺手摘掉在飞标记。否则会出现环：
            # 文件通道入队记了在飞 → 代理通道（仍为入队即标记）把它标成已复盘
            # → 文件通道的在飞条目没人摘 → 2 小时后被判"失败待重试"重新入队，
            # 于是每 2 小时重复复盘一次。摘掉即断环。
            queued = self._queued_snapshot()
            if key in queued:
                kept = [r for r in self._iter_jsonl(REVIEW_QUEUED_FILE)
                        if isinstance(r, dict)
                        and (str(r.get("agent") or ""),
                             str(r.get("session_id") or "")) != key]
                self._write_tmp_rename(
                    self.data_dir / REVIEW_QUEUED_FILE,
                    "\n".join(json.dumps(r, ensure_ascii=False) for r in kept)
                    + ("\n" if kept else ""))
                queued.pop(key, None)

    def _build_queued_map(self) -> dict[tuple[str, str], str]:
        """{(agent, session_id): 入队时间 ts}（在飞台账）。"""
        out: dict[tuple[str, str], str] = {}
        for rec in self._iter_jsonl(REVIEW_QUEUED_FILE):
            if not isinstance(rec, dict):
                continue
            a, s = rec.get("agent"), rec.get("session_id")
            if a and s:
                out[(str(a), str(s))] = str(rec.get("ts") or "")
        return out

    def should_enqueue_review(self, agent: str | None,
                              session_id: str | None) -> bool:
        """H7：该会话现在该不该入队复盘。

        判据 = 「没复盘过」且（没在飞，或在飞已超过 REVIEW_RETRY_AFTER_S）。
        在飞窗口的存在是为了兼顾两端：不给窗口 → 活会话文件每轮都在长，会被
        反复入队复盘（措辞漂移击穿经验侧精确去重）；窗口太长 → 真失败要等很久
        才重试。2 小时是"一次复盘正常应在分钟级完成"与"别空转"之间的折中。
        """
        if not agent or not session_id:
            return False
        key = (str(agent), str(session_id))
        # 整体在写锁内判（不再调 is_reviewed——那会重入），
        # 保证"是否已复盘 + 在飞窗口"读的是同一时刻的一致快照。
        with self._write_lock:
            if key in self._reviewed_snapshot():
                return False
            ts = self._queued_snapshot().get(key)
            if not ts:
                return True
            queued_at = parse_ts(ts)
            if queued_at is None:
                return True
            return (datetime.now(timezone.utc) - queued_at).total_seconds() \
                >= REVIEW_RETRY_AFTER_S

    def mark_review_queued(self, agent: str | None,
                           session_id: str | None) -> None:
        """H7：入队只记「在飞」（幂等；已在飞则刷新 ts，重置重试窗口）。"""
        if not agent or not session_id:
            return
        key = (str(agent), str(session_id))
        now = utcnow()
        with self._write_lock:
            pathf = self.data_dir / REVIEW_QUEUED_FILE
            recs: list[dict] = []
            for rec in self._iter_jsonl(REVIEW_QUEUED_FILE):
                if isinstance(rec, dict):
                    recs.append(rec)
            hit = False
            for rec in recs:
                if (str(rec.get("agent") or ""),
                        str(rec.get("session_id") or "")) == key:
                    rec["ts"] = now
                    hit = True
            if not hit:
                recs.append({"agent": key[0], "session_id": key[1], "ts": now})
            self._write_tmp_rename(pathf, "\n".join(
                json.dumps(r, ensure_ascii=False) for r in recs
            ) + "\n")
            self._cap_jsonl_lines(pathf, REVIEW_QUEUED_MAX_LINES)
            # 内存时间戳与文件写同临界区——原来在锁外赋值，
            # 并发下内存会落后文件，should_enqueue_review 提前放行重复入队。
            self._queued_snapshot()[key] = now

    def clear_review_queued(self, agent: str | None,
                            session_id: str | None) -> None:
        """H7：复盘成功后摘掉在飞标记（此后永不再入队）。"""
        if not agent or not session_id:
            return
        key = (str(agent), str(session_id))
        with self._write_lock:
            pathf = self.data_dir / REVIEW_QUEUED_FILE
            kept = [r for r in self._iter_jsonl(REVIEW_QUEUED_FILE)
                    if isinstance(r, dict)
                    and (str(r.get("agent") or ""),
                         str(r.get("session_id") or "")) != key]
            self._write_tmp_rename(pathf, "\n".join(
                json.dumps(r, ensure_ascii=False) for r in kept
            ) + ("\n" if kept else ""))
            # 内存摘除与文件写同临界区
            if self._queued_reviews is not None:
                self._queued_reviews.pop(key, None)
