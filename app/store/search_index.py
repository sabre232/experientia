"""会话全文搜索索引（修复方案 -P1-2：FTS5 BM25，embedding 就位后叠加向量）。

模式与 experience.db 一致：sessions.jsonl 是事实源，search.db 是可丢弃的
读侧派生索引——(size, mtime_ns) 指纹失配即整表重建；任何异常 fail-open
（搜索降级为空结果，绝不带崩调用方）。

① 指纹改 (size, mtime_ns)（不再每次搜索整读文件算 sha256）；② 连接补
experience.db 同口径 PRAGMA（WAL + synchronous=NORMAL + busy_timeout 30s）；
③ 建连后一次性 `integrity-check` 自检，损坏即清映射强制重建；④ **逐行增量维护**——
不再"指纹一变就 `DELETE FROM sess_fts` + 全量重插"，改按 `sess_rows(key, rid, h)`
映射做增/改/删 diff：key = `agent\0sid`，h = 正文 CRC32，只有正文真变的行才动，
trigram 索引不再每次变更全量重建。

为什么用「映射表 + 普通 FTS5 表（存正文）」而不是 contentless/external-content：
搜索要读回 `body` 出片段（`_make_snippet`）且 <3 字查询走 `LIKE body` 兜底，
contentless 表取不到列值；external-content 需要一张镜像正文表、把 6KB×N 的正文
再存一份。普通 FTS5 表本身支持 `DELETE/UPDATE`（存了正文即可自算 delete），
故用一张轻量映射表做主键⇄rowid 的稳定对应即可，零额外正文副本。

分词：trigram（SQLite ≥3.41，随包 sqlite 3.53 ✓）对 CJK 直接可用；
<3 字符的查询走 LIKE 兜底（数据量千级，全扫无压力）。
向量路：embedding 可用时对 FTS 候选做余弦重排（缺料自动跳过，零回归）。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import zlib
from pathlib import Path

logger = logging.getLogger("experientia.store.search")

_BODY_MAX = 6000          # 每会话入索引正文上限（转录+事件命令/签名，截尾）
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
-- T2.6④ 增量维护的映射表：key(agent\\0sid) ⇄ FTS rowid，h = 正文 CRC32 变更判据
CREATE TABLE IF NOT EXISTS sess_rows(
    key TEXT PRIMARY KEY, rid INTEGER NOT NULL, h INTEGER NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS sess_fts USING fts5(
    agent UNINDEXED, sid UNINDEXED, body, tokenize='trigram');
"""


def _session_body(rec: dict) -> str:
    parts = [str(m) for m in (rec.get("user_messages") or [])]
    parts += [str(m) for m in (rec.get("assistant_messages") or [])]
    for ev in (rec.get("events") or []):
        if ev.get("cmd"):
            parts.append(str(ev["cmd"]))
        if ev.get("sig"):
            parts.append(str(ev["sig"]))
    return "\n".join(p for p in parts if p)[:_BODY_MAX]


def _make_snippet(body: str, query: str, width: int = 96) -> str:
    """自构造命中片段（弃 FTS5 snippet()：其高亮标记会把 ASCII 词切断）。

    大小写不敏感定位首个命中，前后各留窗，命中段用【】包裹，换行压平。"""
    if not body:
        return ""
    i = body.lower().find(query.lower())
    if i < 0:
        return body[:width].replace("\n", " ")
    pre = max(0, i - 24)
    end = min(len(body), i + len(query) + 64)
    return ("…" if pre > 0 else "") + body[pre:i] + "【" \
        + body[i:i + len(query)] + "】" + body[i + len(query):end] \
        + ("…" if end < len(body) else "")


class SearchIndex:
    """sessions.jsonl → search.db（FTS5）。线程安全（读多写少，锁重建）。"""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._sig = ""

    @property
    def path(self) -> Path:
        return self.data_dir / "search.db"

    def _sessions_sig(self) -> str:
        """sessions.jsonl 的轻量指纹 (size, mtime_ns)（不再整读文件算 sha256）。"""
        p = self.data_dir / "sessions.jsonl"
        try:
            st = p.stat()
            return f"{int(st.st_size)}:{int(st.st_mtime_ns)}"
        except OSError:
            return "empty"

    def _connect(self) -> None:
        """建连（幂等）：PRAGMA 同 experience.db 口径 + schema + 一次性完整性自检。"""
        if self._conn is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, timeout=30.0)
        # ②：连接 PRAGMA 与 experience.db 完全同口径
        try:
            self._conn.execute("PRAGMA busy_timeout=30000")
            try:
                self._conn.execute("PRAGMA journal_mode=WAL").fetchone()
            except sqlite3.OperationalError:
                pass  # WAL 被并发占用等不致命，后续事务仍可用
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error:
            pass
        self._conn.executescript(_SCHEMA)
        # ③：建连后一次性完整性自检：索引损坏 → 清映射 + 指纹，强制本轮全建
        try:
            self._conn.execute(
                "INSERT INTO sess_fts(sess_fts) VALUES('integrity-check')")
        except sqlite3.Error as exc:
            logger.info("搜索索引自检未通过，强制重建: %s", exc)
            try:
                self._conn.execute("DELETE FROM sess_rows")
                self._conn.execute("DELETE FROM sess_fts")
                self._conn.execute("DELETE FROM meta WHERE key='sig'")
                self._conn.commit()
            except sqlite3.Error:
                pass

    def _apply(self, sessions: list[dict], sig: str) -> None:
        """**增量**对齐：只增/改/删正文真变的会话（④）。

        sessions.jsonl 每次追加/重写都会让指纹失配，但绝大多数会话正文未变；
        逐行比对 `h`（正文 CRC32）后只动变化的那几行——trigram 索引不再每次
        变更全量重建（旧行为 = DELETE 全表 + 重插 N×6KB）。
        """
        assert self._conn is not None
        conn = self._conn
        mapped = {k: (rid, h) for k, rid, h in
                  conn.execute("SELECT key, rid, h FROM sess_rows")}
        fts_n = conn.execute("SELECT COUNT(*) FROM sess_fts").fetchone()[0]
        if not mapped and fts_n:
            # 老库（前的 search.db 只有 sess_fts、无映射表）→ 一次性全建
            conn.execute("DELETE FROM sess_fts")
            mapped = {}

        wanted: dict[str, tuple[str, str, str, int]] = {}
        for s in sessions:
            sid = str(s.get("session_id") or "")
            if not sid:
                continue
            agent = str(s.get("agent") or "")
            body = _session_body(s)
            wanted[f"{agent}\x00{sid}"] = (agent, sid, body,
                                           zlib.crc32(body.encode("utf-8")))

        # FTS 里可能存在映射表没有的孤儿 rowid（历史失同步），
        # 只按映射表取 max 会让新 INSERT 撞孤儿 rowid 的主键 → IntegrityError 被
        # _ensure_fresh 吞掉、索引永久不可用（搜索静默返回空且不自愈）。
        # 取映射表与 FTS 两者的最大值，Insert 永不撞车。
        fts_max = conn.execute(
            "SELECT MAX(rowid) FROM sess_fts").fetchone()[0] or 0
        next_rid = max([rid for rid, _h in mapped.values()] + [fts_max],
                       default=0) + 1
        inserts: list[tuple] = []
        updates: list[tuple] = []
        for key, (agent, sid, body, h) in wanted.items():
            cur = mapped.get(key)
            if cur is None:
                inserts.append((next_rid, agent, sid, body, key, h))
                next_rid += 1
            elif cur[1] != h:
                updates.append((body, cur[0], h, key))
        deletes = [(rid, key) for key, (rid, _h) in mapped.items()
                   if key not in wanted]

        for rid, agent, sid, body, key, h in inserts:
            conn.execute(
                "INSERT INTO sess_fts(rowid, agent, sid, body) VALUES (?,?,?,?)",
                (rid, agent, sid, body))
            conn.execute("INSERT INTO sess_rows(key, rid, h) VALUES (?,?,?)",
                         (key, rid, h))
        for body, rid, h, key in updates:
            conn.execute("UPDATE sess_fts SET body=? WHERE rowid=?", (body, rid))
            conn.execute("UPDATE sess_rows SET h=? WHERE key=?", (h, key))
        for rid, key in deletes:
            conn.execute("DELETE FROM sess_fts WHERE rowid=?", (rid,))
            conn.execute("DELETE FROM sess_rows WHERE key=?", (key,))
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('sig', ?)", (sig,))
        conn.commit()
        logger.debug("搜索索引增量维护: +%d ~%d -%d",
                     len(inserts), len(updates), len(deletes))

    def _ensure_fresh(self, sessions: list[dict]) -> bool:
        """指纹失配则**增量**对齐；返回索引是否可用。"""
        sig = self._sessions_sig()
        with self._lock:
            if self._conn is not None and sig == self._sig:
                return True
            try:
                self._connect()
                assert self._conn is not None
                row = self._conn.execute(
                    "SELECT value FROM meta WHERE key='sig'").fetchone()
                if row and row[0] == sig:
                    self._sig = sig
                    return True
                self._apply(sessions, sig)
                self._sig = sig
                return True
            except sqlite3.Error as exc:
                logger.warning("搜索索引维护失败（搜索暂不可用）: %s", exc)
                try:
                    if self._conn is not None:
                        self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None
                return False

    def search(self, sessions: list[dict], query: str, limit: int = 20,
               embedder=None) -> list[dict]:
        """返回 [{agent, session_id, score, snippet}]，按 BM25（越小越优）排序。

        <3 字符查询 LIKE 兜底；embedder 由调用方注入（None = 纯 FTS）。"""
        query = (query or "").strip()
        if not query or not self._ensure_fresh(sessions):
            return []
        by_key = {(str(s.get("agent")), str(s.get("session_id"))): s
                  for s in sessions}
        hits: list[dict] = []
        try:
            with self._lock:
                assert self._conn is not None
                if len(query) >= 3:
                    rows = self._conn.execute(
                        "SELECT agent, sid, bm25(sess_fts) AS score, body "
                        "FROM sess_fts WHERE sess_fts MATCH ? "
                        "ORDER BY score LIMIT ?",
                        (f'"{query}"', max(limit * 3, 30))).fetchall()
                    for agent, sid, score, body in rows:
                        hits.append({"agent": agent, "session_id": sid,
                                     "score": -float(score),
                                     "snippet": _make_snippet(body, query)})
                else:
                    like = f"%{query}%"
                    rows = self._conn.execute(
                        "SELECT agent, sid, body FROM sess_fts "
                        "WHERE body LIKE ? LIMIT ?", (like, limit * 3)).fetchall()
                    for agent, sid, body in rows:
                        i = body.find(query)
                        snip = body[max(0, i - 20):i + 40] if i >= 0 else body[:60]
                        hits.append({"agent": agent, "session_id": sid,
                                     "score": 1.0, "snippet": snip})
        except sqlite3.Error as exc:
            logger.info("搜索查询失败（返回空）: %s", exc)
            return []
        hits = self._rerank(query, hits, by_key, embedder)[:limit]
        for h in hits:
            rec = by_key.get((h["agent"], h["session_id"])) or {}
            h["project"] = rec.get("project")
            h["started_at"] = rec.get("started_at")
            h["trunk"] = rec.get("trunk")
            h["category"] = rec.get("category")
        return hits

    def _rerank(self, query: str, hits: list[dict], by_key: dict,
                embedder) -> list[dict]:
        """向量重排（可选）：embedder 注入时 score = 0.7*bm25 归一 + 0.3*cos。"""
        if not hits or embedder is None:
            return hits
        try:
            qv = embedder.embed([query])[0]
            texts = [_session_body(by_key.get((h["agent"], h["session_id"]), {}))
                     for h in hits]
            vecs = embedder.embed(texts)

            def cos(a, b):
                return sum(x * y for x, y in zip(a, b))
            top = max((h["score"] for h in hits), default=1.0) or 1.0
            for h, v in zip(hits, vecs):
                h["score"] = 0.7 * (h["score"] / top) + 0.3 * max(0.0, cos(qv, v))
            hits.sort(key=lambda h: -h["score"])
        except Exception as exc:
            logger.debug("向量重排跳过: %s", exc)
        return hits

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None
                self._sig = ""
