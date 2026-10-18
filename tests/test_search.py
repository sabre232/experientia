"""会话全文搜索护栏。

④：索引改**增量维护**——增/改/删三类正确性 + "不整表重建"（rowid 稳定）
+ 老库（无 sess_rows 映射）自动迁移，均在此守护。
"""

import json
import sqlite3
from pathlib import Path

from app.store.store import Store
from app.store.search_index import SearchIndex
from conftest import local_api_client


def _rec(agent, sid, umsgs, amsgs=(), events=()):
    return {"agent": agent, "session_id": sid, "project": "F:/demo",
            "user_messages": list(umsgs), "assistant_messages": list(amsgs),
            "events": list(events), "req_count": len(umsgs),
            "correction_hits": 0, "trunk": "编程", "category": "调试",
            "started_at": "2026-09-15T00:00:00Z"}


def _store(tmp_path):
    s = Store(tmp_path)
    s.ensure_layout()
    s.record_session(_rec("codex", "s-a",
                          ["帮我修 pytest 收集不到测试的问题"],
                          ["conftest 路径配错了"],
                          [{"tool": "Bash", "cmd": "pytest -q", "ex": 1, "e": 1,
                            "sig": "ImportError: conftest not found"}]))
    s.record_session(_rec("workbuddy", "s-b",
                          ["推导一下薛定谔方程的数值解"],
                          ["用差分法"]))
    return s


def test_search_cjk_trigram_and_latin(tmp_path):
    store = _store(tmp_path)
    hits = store.search_sessions("薛定谔")
    assert [h["session_id"] for h in hits] == ["s-b"]
    hits = store.search_sessions("pytest")
    assert hits and hits[0]["session_id"] == "s-a"
    # 事件行里的报错也入索引（"上次那个报错怎么修的"主场景）
    hits = store.search_sessions("conftest")
    assert hits and hits[0]["session_id"] == "s-a"
    assert "conftest" in hits[0]["snippet"]


def test_search_short_query_like_fallback(tmp_path):
    store = _store(tmp_path)
    hits = store.search_sessions("差分")   # 2 字符 < trigram 窗 → LIKE 兜底
    assert [h["session_id"] for h in hits] == ["s-b"]
    assert store.search_sessions("") == []
    assert store.search_sessions("   ") == []


def test_search_rebuilds_on_sessions_change(tmp_path):
    store = _store(tmp_path)
    assert store.search_sessions("webpack") == []
    store.record_session(_rec("codex", "s-c", ["webpack 打包内存溢出"]))
    hits = store.search_sessions("webpack")
    assert [h["session_id"] for h in hits] == ["s-c"]


def test_search_index_survives_orphan_rowid(tmp_path):
    """FTS 里遗留映射表没有的孤儿 rowid → 新会话入库不得撞主键、搜索不得
    静默失效（原 next_rid 只看映射表，撞车后
    IntegrityError 被吞、连接被关、索引永久不可用）。"""
    store = _store(tmp_path)
    assert store.search_sessions("pytest")  # 先建索引
    conn = sqlite3.connect(store.data_dir / "search.db")
    orphan_rid = conn.execute("SELECT MAX(rid) FROM sess_rows").fetchone()[0] + 1
    conn.execute("INSERT INTO sess_fts(rowid, agent, sid, body) "
                 "VALUES (?, 'x', 'orphan', 'ghost row')", (orphan_rid,))
    conn.commit()
    conn.close()
    # 新会话入库：原实现 next_rid 恰好 = orphan_rid → 撞主键 → 索引被关、搜索空
    store.record_session(_rec("codex", "s-c", ["孤儿 rowid 之后的新会话"]))
    hits = store.search_sessions("孤儿 rowid 之后")
    assert hits and hits[0]["session_id"] == "s-c"


def test_search_fail_open_on_corrupt_index(tmp_path):
    store = _store(tmp_path)
    assert store.search_sessions("pytest")  # 先建索引
    idx = store._searchidx
    idx.close()  # 关连接，让 WAL/SHM 归位（起 search.db 走 WAL）
    store._searchidx = None  # 模拟新进程读到坏侧车
    # 真损坏：主库 + 侧车（-wal/-shm）**全部**写坏。只坏主文件会被 WAL 恢复，
    # 不构成"坏索引"——这是启用 WAL 后必须的测试口径修正。
    for suf in ("", "-wal", "-shm"):
        (store.data_dir / f"search.db{suf}").write_bytes(b"not a sqlite file at all")
    assert store.search_sessions("pytest") == []  # fail-open：空结果不抛


# ---------- ④ 增量维护（直接驱动 SearchIndex，精确控制 sessions 列表） ----------

def _sess(agent, sid, *umsgs):
    return {"agent": agent, "session_id": sid, "user_messages": list(umsgs),
            "assistant_messages": [], "events": []}


def _touch(tmp_path, n: int) -> None:
    """写 sessions.jsonl 让 (size, mtime_ns) 指纹变化（驱动一次增量对齐）。"""
    (Path(tmp_path) / "sessions.jsonl").write_bytes(b"x" * n)


def test_search_index_incremental_add_update_delete(tmp_path):
    """增 / 改 / 删三类都必须正确反映到搜索结果。"""
    idx = SearchIndex(tmp_path)
    a = _sess("codex", "s-a", "帮我修 pytest 收集不到测试的问题")
    b = _sess("workbuddy", "s-b", "推导一下薛定谔方程的数值解")
    _touch(tmp_path, 1)
    assert [h["session_id"] for h in idx.search([a, b], "pytest")] == ["s-a"]
    assert [h["session_id"] for h in idx.search([a, b], "薛定谔")] == ["s-b"]

    # 增：新会话可搜到，旧会话不受影响
    _touch(tmp_path, 2)
    c = _sess("codex", "s-c", "webpack 打包内存溢出")
    assert [h["session_id"] for h in idx.search([a, b, c], "webpack")] == ["s-c"]
    assert [h["session_id"] for h in idx.search([a, b, c], "pytest")] == ["s-a"]

    # 改：b 正文换掉 → 旧词搜不到、新词能搜到
    _touch(tmp_path, 3)
    b2 = _sess("workbuddy", "s-b", "用差分法求解偏微分方程")
    assert idx.search([a, b2, c], "薛定谔") == []
    assert [h["session_id"] for h in idx.search([a, b2, c], "差分法")] == ["s-b"]

    # 删：b 从列表移除 → 彻底搜不到
    _touch(tmp_path, 4)
    assert idx.search([a, c], "差分法") == []
    assert [h["session_id"] for h in idx.search([a, c], "pytest")] == ["s-a"]
    # 不变量：索引行数 == 有效会话数
    with idx._lock:
        n = idx._conn.execute("SELECT COUNT(*) FROM sess_fts").fetchone()[0]
        m = idx._conn.execute("SELECT COUNT(*) FROM sess_rows").fetchone()[0]
    assert n == m == 2


def test_search_index_incremental_keeps_rowids(tmp_path):
    """增量维护不整表重建：插入新会话后，原有行的 rowid 必须保持不变。

    整表重建会按列表顺序重排 rowid（新会话插到最前 → 老行 rowid 全体位移）。
    """
    idx = SearchIndex(tmp_path)
    a = _sess("codex", "s-a", "帮我修 pytest 收集不到测试的问题")
    b = _sess("workbuddy", "s-b", "推导薛定谔方程")

    def rows() -> dict:
        with idx._lock:
            return dict(idx._conn.execute("SELECT sid, rowid FROM sess_fts"))

    _touch(tmp_path, 1)
    idx.search([a, b], "pytest")
    before = rows()
    c = _sess("codex", "s-c", "webpack 打包内存溢出")
    _touch(tmp_path, 2)
    idx.search([c, a, b], "webpack")   # c 在最前：整表重建会让老行位移
    after = rows()
    assert after["s-a"] == before["s-a"]
    assert after["s-b"] == before["s-b"]
    assert after["s-c"] not in before.values()


def test_search_index_unchanged_sig_does_no_work(tmp_path):
    """指纹未变 → 直接短路：不扫正文、不写库（_apply 一进即炸来证明）。"""
    idx = SearchIndex(tmp_path)
    a = _sess("codex", "s-a", "帮我修 pytest 收集不到测试的问题")
    _touch(tmp_path, 1)
    assert [h["session_id"] for h in idx.search([a], "pytest")] == ["s-a"]

    def _boom(*_a, **_k):
        raise AssertionError("指纹未变却走了 _apply（未短路）")

    idx._apply = _boom
    assert [h["session_id"] for h in idx.search([a], "pytest")] == ["s-a"]


def test_search_index_migrates_legacy_db_without_map(tmp_path):
    """老格式库（只有 sess_fts、无 sess_rows 映射）→ 自动一次性全建，结果正确。"""
    p = Path(tmp_path) / "search.db"
    con = sqlite3.connect(str(p))
    con.executescript(
        "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);"
        "CREATE VIRTUAL TABLE sess_fts USING fts5("
        "agent UNINDEXED, sid UNINDEXED, body, tokenize='trigram');")
    con.execute("INSERT INTO sess_fts(agent, sid, body)"
                " VALUES('old', 's-old', '陈年内容不该留下')")
    con.execute("INSERT INTO meta(key, value) VALUES('sig', 'stale')")
    con.commit()
    con.close()

    idx = SearchIndex(tmp_path)
    a = _sess("codex", "s-a", "帮我修 pytest 收集不到测试的问题")
    _touch(tmp_path, 3)
    assert [h["session_id"] for h in idx.search([a], "pytest")] == ["s-a"]
    assert idx.search([a], "陈年内容") == []      # 老行已被清掉
    with idx._lock:
        m = idx._conn.execute("SELECT COUNT(*) FROM sess_rows").fetchone()[0]
    assert m == 1


def test_api_search_endpoint(tmp_path, monkeypatch):
    import keyring

    keys: dict[str, str] = {}
    monkeypatch.setattr(keyring, "set_password", lambda *a: keys.update({a[1]: a[2]}))
    monkeypatch.setattr(keyring, "get_password", lambda *a: keys.get(a[1]))
    monkeypatch.setattr(keyring, "delete_password", lambda *a: None)
    store = _store(tmp_path)
    c = local_api_client(store)
    r = c.get("/api/search", params={"q": "薛定谔"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items and items[0]["session_id"] == "s-b"
    assert items[0]["project"] == "F:/demo"
    assert c.get("/api/search", params={"q": ""}).json() == {"items": []}
