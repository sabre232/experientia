"""：会话索引的读侧必须持写锁。

旧实现两处漏锁：
1. `list_sessions()` 快路径（已有索引 → `list(dict.values())`）：与
   `record_session` 的锁内插入并发会抛
   `RuntimeError: dictionary changed size during iteration` → API 偶发 500；
2. `stats()` 的懒建（锁外判空→构建→整体赋值）：锁外旧快照会覆盖掉刚写入的
   新 session → 新会话从内存索引静默消失，直到进程重启。

证明方式（确定性，不靠概率）：另一线程持写锁期间调用读方法必须**阻塞**——
不阻塞即说明没加锁。
"""

from __future__ import annotations

import threading

from app.store.store import Store


def _rec(sid: str, agent: str = "codex") -> dict:
    return {"agent": agent, "session_id": sid, "project": "F:/demo",
            "user_messages": ["帮我修 pytest 收集不到测试的问题"],
            "assistant_messages": ["conftest 路径配错了"], "req_count": 1,
            "correction_hits": 0, "trunk": "编程", "category": "调试",
            "started_at": "2026-10-14T00:00:00Z"}


def _store(tmp_path) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    s.record_session(_rec("s-1"))  # 建好索引 → 旧实现的"快路径"会被走到
    assert s._session_index is not None
    return s


def _hold_lock(store: Store):
    """起一个持写锁的线程，返回 (held_event, release_fn, thread)。"""
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with store._write_lock:
            held.set()
            release.wait(5)

    th = threading.Thread(target=hold, daemon=True)
    th.start()
    assert held.wait(5), "测试线程未能拿到写锁"
    return release


def test_list_sessions_takes_write_lock(tmp_path):
    """list_sessions 必须在写锁下取快照（持锁期间读者被挡住）。"""
    store = _store(tmp_path)
    release = _hold_lock(store)
    done = threading.Event()

    def reader() -> None:
        try:
            store.list_sessions()
        finally:
            done.set()

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()
    try:
        assert not done.wait(0.3), \
            "list_sessions 未取写锁：快路径无锁迭代与并发插入会抛 RuntimeError"
    finally:
        release.set()
    assert done.wait(5), "释放锁后 list_sessions 应能完成"


def test_stats_takes_write_lock(tmp_path):
    """stats 的会话索引懒建同样必须在写锁下（防旧快照覆盖新 session）。"""
    store = _store(tmp_path)
    store._session_index = None  # 制造"需懒建"状态
    release = _hold_lock(store)
    done = threading.Event()

    def reader() -> None:
        try:
            store.stats()
        finally:
            done.set()

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()
    try:
        assert not done.wait(0.3), "stats 的懒建未取写锁（锁外旧快照会覆盖新 session）"
    finally:
        release.set()
    assert done.wait(5), "释放锁后 stats 应能完成"
