"""SQLite 经验读索引层（产品文档：SQLite WAL + 单写队列 + busy_timeout 30s +
thread-local 连接）。

分层口径（方案 B）：
- **experience.db（本模块，SQLite WAL）是唯一持久事实源**：读路径全走它；写路径
  由 Store 在 _write_lock 内只落它（新增记录同时 append 一行 JSONL 作低成本备份）；
- **experience.jsonl 降级为导出/备份格式**：运行期不再被读路径消费，由
  Store.export_experience_snapshot 定期/显式原子导出对齐；
- meta 表记录轻量指纹 (size, mtime_ns) 与事实源标志 `experience_source`：标志为
  `"sqlite"` 时 `rebuild_if_stale` **绝不按 JSONL 重建**（防陈旧快照覆盖库丢数据）；
  缺标志（迁移前）才按指纹判定是否从 JSONL 重建，否则跳过（**O(1)，不读 JSONL**）；
- 索引必须 fail-open：索引不可用时调用方（Store）回退 JSONL 读路径，
  绝不能让应用因索引故障不可用（防错误传播）。

连接约定：WAL + busy_timeout 30s + synchronous=NORMAL + foreign_keys=ON；
thread-local 连接（check_same_thread=False 由 thread-local 规避）；连接级异常
重置当前线程连接后安全重试一次（除 sqlite3.IntegrityError 外不向调用方泄漏
其他裸异常场景由 Store 的 fail-open 兜底）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Iterator

from ..distill import value_gate

logger = logging.getLogger("experientia.store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiences (
    id TEXT PRIMARY KEY,
    agent TEXT,
    trunk TEXT,
    category TEXT,
    task TEXT,
    action TEXT,
    outcome TEXT,
    g REAL,
    count INTEGER,
    ts TEXT,
    distilled INTEGER DEFAULT 0,
    retired INTEGER DEFAULT 0,
    surface TEXT,
    dismissed INTEGER DEFAULT 0,
    data TEXT
);
CREATE INDEX IF NOT EXISTS idx_experiences_dup ON experiences(agent, task, action);
CREATE INDEX IF NOT EXISTS idx_experiences_cat ON experiences(trunk, category);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

# P0-3 演化链 / 版本快照 / 遗忘标记。**追加列必须放在 `data` 之后**——
# `_COLS` 与 `_row()` 的元组顺序一一对应，插在中间会让 UPSERT 串列。
_CHAIN_COLS = ("revision", "root_id", "supersedes", "superseded_by", "tombstone")
_CHAIN_DEFAULTS = {"revision": "INTEGER DEFAULT 1", "root_id": "TEXT",
                   "supersedes": "TEXT", "superseded_by": "TEXT",
                   "tombstone": "INTEGER DEFAULT 0"}

# 版本快照：append-only，只存被换代/回滚掉的旧版。当前头版本在 experiences 主行，
# 不重复存这里——链视图 = revisions(旧版) + 主行(当前)。
_REVISIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS experience_revisions (
    id TEXT NOT NULL,
    root_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    data TEXT NOT NULL,
    reason TEXT,
    ts TEXT,
    PRIMARY KEY (id, revision)
);
CREATE INDEX IF NOT EXISTS idx_revisions_root ON experience_revisions(root_id, revision);
"""
_REVISIONS_COLS = ("id", "root_id", "revision", "data", "reason", "ts")
_REVISIONS_SQL = (
    f"INSERT OR IGNORE INTO experience_revisions ({', '.join(_REVISIONS_COLS)}) "
    f"VALUES ({', '.join('?' * len(_REVISIONS_COLS))})"
)

# surface / dismissed 是纯读路径派生列（surface = value_gate.surface_of；
# dismissed = data JSON 的软删除标记）——落库后 WHERE + LIMIT 可整体下推到 SQL，
# 不再"查全表 → Python 逐条 surface_of 直到凑够 limit"。写口（_row）与 data JSON
# 同源派生，口径一致；判定逻辑若变需迁移重算（connection() 补列迁移 + 清指纹重建）。
_COLS = ("id", "agent", "trunk", "category", "task", "action", "outcome",
         "g", "count", "ts", "distilled", "retired", "surface", "dismissed",
         "data", *_CHAIN_COLS)

_PLACEHOLDERS = ", ".join("?" * len(_COLS))

# 写路径 upsert：ON CONFLICT 就地更新（保留 rowid = 写入序，iter 顺序与 JSONL 一致）
_UPSERT_SQL = (
    f"INSERT INTO experiences ({', '.join(_COLS)}) VALUES ({_PLACEHOLDERS}) "
    "ON CONFLICT(id) DO UPDATE SET "
    + ", ".join(f"{c}=excluded.{c}" for c in _COLS[1:])
)
# 全量重建用 OR REPLACE：外部编辑过的 JSONL 可能出现重复 id，后行覆盖前行
_REPLACE_SQL = (
    f"INSERT OR REPLACE INTO experiences ({', '.join(_COLS)}) VALUES ({_PLACEHOLDERS})"
)

_META_SET_SQL = "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)"


def _file_signature(path: Path) -> tuple[int, int] | None:
    """JSONL 文件的轻量指纹 (size, mtime_ns)；文件缺失/不可读 → None。

    取舍（如实说明）：不再整文件算 sha256。**代价**：极端情况下"内容变了但
    size 与 mtime_ns 都没变"（如同字节数原地覆盖）会漏检——故保留手动
    「重建索引」入口兜底。收益：启动校验耗时与文件大小**无关**（O(1) stat）。"""
    try:
        st = Path(path).stat()
        return int(st.st_size), int(st.st_mtime_ns)
    except OSError:
        return None


def _sig_meta(sig: tuple[int, int] | None) -> tuple[str, str]:
    """指纹 → meta 存储对（缺失 → 两个空串，与旧实现 meta 缺省口径一致）。"""
    if sig is None:
        return "", ""
    return str(sig[0]), str(sig[1])


def _iter_jsonl_records(path: Path) -> Iterator[dict]:
    """逐行解析 JSONL：单条坏行跳过不中断（容错约定，与 store._iter_jsonl 一致）。"""
    p = Path(path)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                yield item


def _g_of(rec: dict) -> float:
    try:
        return float(rec.get("G") or 0)
    except (TypeError, ValueError):
        return 0.0


def _count_of(rec: dict) -> int:
    try:
        return int(rec.get("count") or 1)
    except (TypeError, ValueError):
        return 1


def _row(rec_id: str, rec: dict) -> tuple:
    """经验记录 → 行元组。data 列存完整 JSON（其余列只是索引列，读路径以 data 为准）。

    P0-3：演化链列缺省自愈——老记录（外部编辑的 JSONL / 迁移前的行）没有这些字段时
    revision=1、root_id=自身 id，绝不因为缺字段就让行写不进去。
    """
    supersedes = rec.get("supersedes")
    if isinstance(supersedes, list):
        sup_json = json.dumps([str(x) for x in supersedes if x], ensure_ascii=False)
    elif supersedes:
        sup_json = json.dumps([str(supersedes)])
    else:
        sup_json = "[]"
    try:
        revision = max(1, int(rec.get("revision") or 1))
    except (TypeError, ValueError):
        revision = 1
    return (
        rec_id, rec.get("agent"), rec.get("trunk"), rec.get("category"),
        rec.get("task"), rec.get("action"), rec.get("outcome"),
        _g_of(rec), _count_of(rec), rec.get("ts"),
        1 if rec.get("distilled") else 0,
        1 if rec.get("retired") else 0,
        value_gate.surface_of(rec),
        1 if rec.get("dismissed") else 0,
        json.dumps(rec, ensure_ascii=False),
        revision,
        str(rec.get("root_id") or rec_id),
        sup_json,
        str(rec.get("superseded_by") or ""),
        1 if rec.get("tombstone") else 0,
    )


class ExperienceDB:
    """experience.db 的唯一读写入口。

    连接是 thread-local 的：每线程首次使用时建立并注册到共享清单
    （close_all 可从其他线程统一关闭，关闭后各线程下次使用自动重连）。
    所有公开方法经 _run 执行：sqlite3.Error 时重置当前线程连接并安全重试一次。
    """

    def __init__(self, db_path: str | Path, data_dir: str | Path) -> None:
        self._db_path = Path(db_path)
        self._data_dir = Path(data_dir)
        self._local = threading.local()
        self._conns: list[sqlite3.Connection] = []
        self._conns_lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # 事实源标记缓存（meta.experience_source）；"sqlite" = 本库为唯一事实源
        self._source: str | None = None

    # ---------- 事实源标记 ----------

    @property
    def is_sqlite_source(self) -> bool:
        """本库是否为唯一事实源（meta.experience_source == 'sqlite'）。"""
        if self._source is None:
            try:
                row = self._run(lambda conn: conn.execute(
                    "SELECT value FROM meta WHERE key='experience_source'"
                ).fetchone())
                self._source = str(row[0]) if row else ""
            except sqlite3.Error:
                self._source = ""
        return self._source == "sqlite"

    def set_experience_source(self, value: str) -> None:
        """写事实源标记（迁移调用）；同时刷新实例缓存。"""
        def op(conn: sqlite3.Connection) -> None:
            with conn:
                conn.execute(_META_SET_SQL, ("experience_source", str(value)))
        self._run(op)
        self._source = str(value)

    # ---------- 连接管理 ----------

    def connection(self) -> sqlite3.Connection:
        """当前线程的 sqlite3 连接（惰性建立；PRAGMA 见模块 docstring）。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        conn = sqlite3.connect(str(self._db_path), timeout=30.0,
                               check_same_thread=False)
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            try:
                conn.execute("PRAGMA journal_mode=WAL").fetchone()
            except sqlite3.OperationalError:
                pass  # WAL 设置被并发占用等场景不致命，后续事务仍可用
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(_SCHEMA)
            # 迁移（幂等）：老库缺 surface / dismissed 列 → 补列 + 清指纹（强制
            # 下次 rebuild_if_stale 全量重建回填）。**必须先于下面的 surface 索引**：
            # 老库 experiences 表已存在（CREATE TABLE IF NOT EXISTS 不会补列），若先
            # 建 `ON experiences(surface)` 索引会 "no such column: surface" 直接失败。
            try:
                cols = {r[1] for r in conn.execute(
                    "PRAGMA table_info(experiences)").fetchall()}
                missing = {"surface", "dismissed"} - cols
                if missing:
                    for col in sorted(missing):
                        conn.execute(
                            f"ALTER TABLE experiences ADD COLUMN {col} TEXT")
                    conn.execute("DELETE FROM meta WHERE key IN "
                                 "('jsonl_size','jsonl_mtime_ns')")
                    conn.commit()
                conn.execute("CREATE INDEX IF NOT EXISTS idx_experiences_surface "
                             "ON experiences(surface)")
            except sqlite3.Error:
                pass
            # P0-3 迁移（幂等）：演化链 / 版本 / 遗忘列 + revisions 表。
            # 与块分开写：那一块注释明确要求"补列必须先于 surface 索引"，
            # 这里只追加不冲突的列，互不影响。
            try:
                cols = {r[1] for r in conn.execute(
                    "PRAGMA table_info(experiences)").fetchall()}
                missing = [c for c in _CHAIN_COLS if c not in cols]
                for col in missing:
                    conn.execute(
                        f"ALTER TABLE experiences ADD COLUMN {col} "
                        f"{_CHAIN_DEFAULTS[col]}")
                if missing:
                    # ALTER 带 DEFAULT 会给存量行填默认值，但 root_id/revision 的
                    # **正确**值是"自身 id / 1"——这里 heal 一次，之后靠 _row() 自愈。
                    conn.execute("UPDATE experiences SET revision=1 "
                                 "WHERE revision IS NULL OR revision<1")
                    conn.execute("UPDATE experiences SET root_id=id "
                                 "WHERE root_id IS NULL OR root_id=''")
                    conn.execute("UPDATE experiences SET tombstone=0 "
                                 "WHERE tombstone IS NULL")
                    # 清 JSONL 指纹：下次 rebuild_if_stale 全量回填链列。
                    # sqlite-source 模式下 rebuild_if_stale 会短路（不重建），
                    # 那时的口径以库为准、链列已由上面 heal 补好，不会丢数据。
                    conn.execute("DELETE FROM meta WHERE key IN "
                                 "('jsonl_size','jsonl_mtime_ns')")
                    conn.commit()
                conn.execute("CREATE INDEX IF NOT EXISTS idx_experiences_root "
                             "ON experiences(root_id)")
                conn.executescript(_REVISIONS_SCHEMA)
            except sqlite3.Error:
                pass
        except sqlite3.Error:
            # 初始化失败（如库文件损坏）：关闭句柄再抛，防泄漏句柄卡住后续删库重建
            try:
                conn.close()
            except sqlite3.Error:
                pass
            raise
        with self._conns_lock:
            self._conns.append(conn)
        self._local.conn = conn
        return conn

    def _reset_connection(self) -> None:
        """关闭并丢弃当前线程连接（下次使用自动重建）。"""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return
        self._local.conn = None
        try:
            conn.close()
        except sqlite3.Error:
            pass
        with self._conns_lock:
            if conn in self._conns:
                self._conns.remove(conn)

    def close_all(self) -> None:
        """关闭所有线程的连接（wipe/迁移等目录级操作前调用，释放文件句柄）。"""
        with self._conns_lock:
            conns = list(self._conns)
            self._conns.clear()
        self._local.conn = None
        for conn in conns:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def _run(self, op):
        """执行一次数据库操作；sqlite3.Error 时重置连接重试一次。"""
        try:
            return op(self.connection())
        except sqlite3.Error:
            self._reset_connection()
            return op(self.connection())

    # ---------- JSONL 待对账标记 ----------

    _JSONL_AHEAD_KEY = "jsonl_ahead"

    def mark_jsonl_ahead(self) -> None:
        """记下"SQLite 写失败、JSONL 里可能有库中没有的行"。

        sqlite-source 模式下写库失败时调用；下次启动 / 下次快照导出前按 id 做
        一次"只插不删"的对账。不这么做的后果：那些行既不被任何读路径消费
        （读者只看库），又会被下一次快照导出（整文件从库重写）静默抹掉——
        两头都不见了。"""
        def op(conn) -> None:
            with conn:
                conn.execute(_META_SET_SQL, (self._JSONL_AHEAD_KEY, "1"))
        self._run(op)

    def jsonl_ahead(self) -> bool:
        """是否处于"JSONL 领先于库、待对账"状态（读失败按 False 保守处理）。"""
        try:
            row = self._run(lambda conn: conn.execute(
                "SELECT value FROM meta WHERE key=?",
                (self._JSONL_AHEAD_KEY,)).fetchone())
        except sqlite3.Error:
            return False
        return bool(row and str(row[0]) == "1")

    def clear_jsonl_ahead(self) -> None:
        """对账完成后撤标记（只在对账完整跑通时调用）。"""
        def op(conn) -> None:
            with conn:
                conn.execute(_META_SET_SQL, (self._JSONL_AHEAD_KEY, ""))
        self._run(op)

    def existing_ids(self) -> set[str]:
        """库中全部经验 id（对账用；仅在待对账状态下调用，O(N) 可接受）。"""
        try:
            rows = self._run(lambda conn: conn.execute(
                "SELECT id FROM experiences").fetchall())
        except sqlite3.Error:
            return set()
        return {str(r[0]) for r in rows}

    # ---------- 全量重建 ----------

    def rebuild(self, experiences: Iterable[dict], *,
                file_sig: tuple[int, int] | None = None) -> int:
        """清表全量重建（单事务 DELETE + executemany），meta 记录 JSONL 轻量指纹。

        返回写入行数。file_sig 由 rebuild_if_stale 传入以免重复 stat；缺省时
        现场取 experience.jsonl 的 (size, mtime_ns)。"""
        rows: list[tuple] = []
        anon = 0
        for rec in experiences:
            if not isinstance(rec, dict):
                continue
            rid = rec.get("id")
            if not rid:
                # 无 id 行无法做主键（find_experience 对其也永不命中），合成键保序保留
                anon += 1
                rid = f"__no_id__:{anon}"
            rows.append(_row(str(rid), rec))
        if file_sig is None:
            file_sig = _file_signature(self._data_dir / "experience.jsonl")
        size_s, mtime_s = _sig_meta(file_sig)

        def op(conn: sqlite3.Connection) -> None:
            with conn:  # 单事务：失败整体回滚，旧索引内容保留
                conn.execute("DELETE FROM experiences")
                conn.executemany(_REPLACE_SQL, rows)
                conn.executemany(_META_SET_SQL, [
                    ("jsonl_size", size_s),
                    ("jsonl_mtime_ns", mtime_s),
                ])

        self._run(op)
        return len(rows)

    def rebuild_if_stale(self, jsonl_path: str | Path) -> bool:
        """按 (size, mtime_ns) 指纹判定是否需要重建；需要则读 JSONL 全量 rebuild。

        返回是否执行了重建。db 不存在 / meta 缺失 / 指纹失配 / 库损坏（meta 读
        失败）→ 重建；否则跳过（**O(1) stat，不读 JSONL 内容**）。"""
        jsonl_path = Path(jsonl_path)
        db_existed = self._db_path.exists()
        sig = _file_signature(jsonl_path)
        size_s, mtime_s = _sig_meta(sig)
        if db_existed:
            try:
                meta = dict(self.connection()
                            .execute("SELECT key, value FROM meta").fetchall())
            except sqlite3.Error:
                meta = None
            if meta is not None:
                # 本库为唯一事实源 → **绝不按 JSONL 重建**。否则启动时会用
                # 陈旧快照（导出是低频的）覆盖库，丢掉尚未导出的新记录（数据丢失！）。
                if str(meta.get("experience_source") or "") == "sqlite":
                    return False
                if (meta.get("jsonl_size") == size_s
                        and meta.get("jsonl_mtime_ns") == mtime_s):
                    return False  # 索引与 JSONL 一致，跳过
                self.rebuild(_iter_jsonl_records(jsonl_path), file_sig=sig)
                return True
            # meta 读失败 → 库可能损坏：删库文件重建（JSONL 是事实源，索引可再生）
            self._destroy_files()
        self.rebuild(_iter_jsonl_records(jsonl_path), file_sig=sig)
        return True

    def _destroy_files(self) -> None:
        """删除 db/-wal/-shm 文件（库损坏时的 fail-safe 重建前置）。"""
        self.close_all()
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(self._db_path) + suffix).unlink(missing_ok=True)
            except OSError as exc:
                raise sqlite3.OperationalError(
                    f"损坏索引文件无法删除: {exc}") from exc

    def mark_synced(self, jsonl_path: str | Path, *, line_delta: int = 0) -> None:
        """写完成后用 O(1) stat 刷新 JSONL 指纹 (size, mtime_ns)。

        由此：正常写路径之后，下次启动 rebuild_if_stale 直接命中**跳过**——不再
        "每进程启动必然全量重建一次"（旧实现 mark_synced 不重算 sha256，导致任一
        写之后启动必重建）。指纹在外部编辑 / 库损坏时仍会失配 → 自动重建，索引
        内容正确性不变（JSONL 仍是事实源）。

        line_delta 保留以兼容既有调用签名，**不再参与指纹**——size/mtime_ns 天然
        反映增删（旧实现按行数增量记账的必要性随 sha 一起消失）。
        """
        sig = _file_signature(jsonl_path)
        size_s, mtime_s = _sig_meta(sig)

        def op(conn: sqlite3.Connection) -> None:
            with conn:
                conn.executemany(_META_SET_SQL, [
                    ("jsonl_size", size_s),
                    ("jsonl_mtime_ns", mtime_s),
                ])

        self._run(op)

    # ---------- 写路径（Store 在 _write_lock 内调用） ----------

    def upsert(self, rec: dict) -> None:
        """单条 upsert（新增经验双写）。无 id 的记录忽略（调用方 append 口保证有 id）。"""
        rid = rec.get("id") if isinstance(rec, dict) else None
        if not rid:
            return
        self.update_many({str(rid): rec})

    def update_many(self, id_to_rec: dict) -> None:
        """同事务批量 upsert；值为 None 表示删除（与 store._update_jsonl 的
        updates 值 None = 移除该行语义一致，retire 路径走这里）。"""
        if not id_to_rec:
            return

        def op(conn: sqlite3.Connection) -> None:
            with conn:
                for rid, rec in id_to_rec.items():
                    if rec is None:
                        conn.execute("DELETE FROM experiences WHERE id=?", (str(rid),))
                    else:
                        conn.execute(_UPSERT_SQL, _row(str(rid), rec))

        self._run(op)

    # ---------- 版本快照（P0-3 演化链） ----------

    def save_revision(self, rec: dict, reason: str = "") -> None:
        """把一条经验的当前内容写进版本快照表。**只增不改**：

        用 `INSERT OR IGNORE`——同 (id, revision) 已在表里就跳过。重复提交同一
        换代会再次触发这里，历史快照绝不能被后一次写入改写掉。
        """
        rid = str(rec.get("id") or "")
        if not rid:
            return
        try:
            revision = max(1, int(rec.get("revision") or 1))
        except (TypeError, ValueError):
            revision = 1
        root = str(rec.get("root_id") or rid)
        payload = json.dumps(rec, ensure_ascii=False)
        ts = str(rec.get("ts") or "")

        def op(conn: sqlite3.Connection) -> None:
            with conn:
                conn.execute(_REVISIONS_SQL,
                             (rid, root, revision, payload, str(reason or ""), ts))

        self._run(op)

    def iter_revisions(self, root_id: str) -> list[dict]:
        """某条经验的全部历史版本（按 revision 升序）。坏行跳过，不中断。"""
        def op(conn: sqlite3.Connection) -> list[dict]:
            rows = conn.execute(
                "SELECT data FROM experience_revisions WHERE root_id IS ? "
                "ORDER BY revision ASC", (str(root_id),)).fetchall()
            return [r[0] for r in rows]

        out: list[dict] = []
        try:
            payloads = self._run(op)
        except sqlite3.Error:
            return out
        for text in payloads:
            try:
                item = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def get_revision(self, root_id: str, revision: int) -> dict | None:
        """取指定历史版本（回滚的数据源）。"""
        def op(conn: sqlite3.Connection) -> str | None:
            row = conn.execute(
                "SELECT data FROM experience_revisions WHERE root_id IS ? "
                "AND revision IS ?", (str(root_id), int(revision))).fetchone()
            return row[0] if row else None

        try:
            text = self._run(op)
        except sqlite3.Error:
            return None
        if not text:
            return None
        try:
            item = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        return item if isinstance(item, dict) else None

    def revision_count(self, root_id: str) -> int:
        """历史版本条数（链深度 = 本数 + 当前头）。"""
        row = self._run(lambda conn: conn.execute(
            "SELECT COUNT(*) FROM experience_revisions WHERE root_id IS ?",
            (str(root_id),)).fetchone())
        return int(row[0] or 0)

    def rewrite_category(self, trunk: str, old_category: str,
                         new_category: str) -> int:
        """分类迁移（rename_skill）同步：把 (trunk, old_category) 记录的
        category 索引列与 data JSON 一并改写。返回改写行数。"""
        def op(conn: sqlite3.Connection) -> int:
            rows = conn.execute(
                "SELECT id, data FROM experiences WHERE trunk IS ? AND category IS ?",
                (trunk, old_category)).fetchall()
            updates = []
            for rid, data in rows:
                try:
                    item = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(item, dict):
                    continue
                item["category"] = new_category
                updates.append((new_category,
                                json.dumps(item, ensure_ascii=False), rid))
            with conn:
                conn.executemany(
                    "UPDATE experiences SET category=?, data=? WHERE id=?", updates)
            return len(updates)

        return self._run(op)

    # ---------- 读路径（与 store.py 原 JSONL 读语义逐字段一致） ----------

    def iter_experiences(
        self,
        include_distilled: bool = True,
        trunk: str | None = None,
        category: str | None = None,
        agent: str | None = None,
        show_dismissed: bool = False,
        show_tombstoned: bool = False,
        show_superseded: bool = False,
        surface: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict]:
        """按写入序（= JSONL 行序）产出经验记录。

        trunk/category/agent/distilled/surface/dismissed/tombstone/superseded 走 SQL
        索引列过滤（列值在写口从同一 JSON 派生，口径一致）；起 surface + dismissed
        可整体下推，配合 limit → SQL `WHERE … ORDER BY rowid LIMIT ?`（耗时与总条数无关）。
        P0-3 两个新默认：`tombstone`（用户遗忘）与**已被换代的旧头**默认都不返回——
        它们只属于 `experience_chain` 的历史视图，不该再进检索/注入/列表。
        """
        conds: list[str] = []
        params: list = []
        if trunk is not None:
            conds.append("trunk IS ?")
            params.append(trunk)
        if category is not None:
            conds.append("category IS ?")
            params.append(category)
        if agent is not None:
            conds.append("agent IS ?")
            params.append(agent)
        if not include_distilled:
            conds.append("distilled = 0")
        if surface is not None:
            conds.append("surface IS ?")
            params.append(surface)
        if not show_dismissed:
            conds.append("dismissed = 0")
        if not show_tombstoned:
            conds.append("tombstone = 0")
        if not show_superseded:
            # 已被换代的旧头：只有历史视图要看。空串/NULL 都算"未被换代"。
            conds.append("(superseded_by IS NULL OR superseded_by = '')")
        sql = "SELECT data FROM experiences"
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY rowid"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        cur = self._run(lambda conn: conn.execute(sql, params))
        for (data,) in cur:
            try:
                item = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                continue
            yield item

    def get(self, rec_id: str) -> dict | None:
        """按 id 取单条（find_experience 的 O(1) 读路径，不再全表/全文件扫）。

        无此 id / data JSON 损坏 → None。"""
        row = self._run(lambda conn: conn.execute(
            "SELECT data FROM experiences WHERE id=?", (str(rec_id),)).fetchone())
        if row is None:
            return None
        try:
            item = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None
        return item if isinstance(item, dict) else None

    def find_duplicate(self, agent, task, action) -> dict | None:
        """(agent, task, action) 精确查重：取写入序最后一条
        （与原内存去重索引 dict 覆盖语义一致）。键不全 → None。"""
        if not (agent and task and action):
            return None
        row = self._run(lambda conn: conn.execute(
            "SELECT data FROM experiences "
            "WHERE agent IS ? AND task IS ? AND action IS ? "
            "ORDER BY rowid DESC LIMIT 1",
            (agent, task, action)).fetchone())
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None

    def find_by_session(self, session_key: str) -> dict | None:
        """缺 (agent, task, action) 键时的 fallback 查重：全表扫（写入序），
        返回第一条 session_id/session 匹配的记录（与原 JSONL 全扫语义一致）。"""
        cur = self._run(lambda conn: conn.execute(
            "SELECT data FROM experiences ORDER BY rowid"))
        for (data,) in cur:
            try:
                item = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                continue
            if (item.get("session_id") or item.get("session")) == session_key:
                return item
        return None

    def all_for_category_index(self) -> Iterator[dict]:
        """类别派生索引的数据源：全表按写入序（含已蒸馏/不采纳，
        与原 _build_category_index 全量扫 experience.jsonl 口径一致）。"""
        cur = self._run(lambda conn: conn.execute(
            "SELECT data FROM experiences ORDER BY rowid"))
        for (data,) in cur:
            try:
                item = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                continue
            yield item

    def count(self) -> int:
        """索引内经验条数。"""
        return int(self._run(
            lambda conn: conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]))

    def counts(self) -> tuple[int, int]:
        """(总条数, 未蒸馏条数) —— 单次查询（stats() 的 O(1) 取数）。"""
        row = self._run(lambda conn: conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN distilled=0 THEN 1 ELSE 0 END),0)"
            " FROM experiences").fetchone())
        return int(row[0] or 0), int(row[1] or 0)

    def distinct_categories(self) -> list[str]:
        """出现过的分类名（去重、排序）——：不再在 Python 里遍历全部经验。

        缺列（NULL）归入「未分类」（与读路径 `category` 兜底口径一致）。"""
        rows = self._run(lambda conn: conn.execute(
            "SELECT DISTINCT category FROM experiences").fetchall())
        return sorted({(str(c) if c is not None else "未分类") for (c,) in rows})
