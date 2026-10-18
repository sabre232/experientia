"""M1–：config / rules / 复盘台账 / 快照导出的写锁口径。

这一族问题的共同点：**文件写进了锁、内存状态或读-改-写在锁外**，并发下
表现为"丢字段 / 丢更新 / 内存落后于文件"。测试用两种手段锁死：

1. 行为断言：写路径必须走 `mutate_config`（持锁），不走 = 老实现；
2. 阻塞断言：持写锁期间调用读/写方法必须**阻塞**——不阻塞即说明没加锁。
"""

from __future__ import annotations

import threading

from app.store.store import Store
from conftest import local_api_client


def _store(tmp_path) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    return s


def _hold_lock(store: Store):
    """另一线程持写锁；返回 release 事件。"""
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with store._write_lock:
            held.set()
            release.wait(5)

    th = threading.Thread(target=hold, daemon=True)
    th.start()
    assert held.wait(5), "测试线程未拿到写锁"
    return release


def _assert_blocks(fn, release, msg: str) -> None:
    """持锁期间 fn() 必须挡住；释放后必须完成。"""
    done = threading.Event()

    def run() -> None:
        try:
            fn()
        finally:
            done.set()

    th = threading.Thread(target=run, daemon=True)
    th.start()
    try:
        assert not done.wait(0.3), msg
    finally:
        release.set()
    assert done.wait(5), "释放锁后应当完成"


# ---------- M1：写 config 的入口必须走 mutate_config ----------

def test_config_update_goes_through_mutate_config(tmp_path, monkeypatch):
    """PUT /api/config 必须走 store.mutate_config（锁内读-改-写）。

    老实现是 load_config → update → save_config（全程无锁），会与 llm 熔断
    记账 / notify 状态写互相覆盖（整文件原子替换 → 后写者抹掉先写者字段）。
    """
    store = _store(tmp_path)
    calls = []
    real = store.mutate_config

    def spy(mutate):
        calls.append(1)
        return real(mutate)

    monkeypatch.setattr(store, "mutate_config", spy)
    r = local_api_client(store).put("/api/config", json={"locale": "en"})
    assert r.status_code == 200
    assert calls, "配置写入没有走 mutate_config（无锁读-改-写）"
    assert store.load_config()["locale"] == "en"


def test_capture_switch_goes_through_mutate_config(tmp_path, monkeypatch):
    """采集开关同理（M1 六处之一）。"""
    store = _store(tmp_path)
    calls = []
    real = store.mutate_config

    def spy(mutate):
        calls.append(1)
        return real(mutate)

    monkeypatch.setattr(store, "mutate_config", spy)
    r = local_api_client(store).post("/api/capture",
                                     json={"name": "codex", "enabled": False})
    assert r.status_code == 200
    assert calls, "采集开关没有走 mutate_config"


# ---------- M2：rules 读路径的迁移写盘 / save_rules 都在锁内 ----------

def test_save_rules_takes_write_lock(tmp_path):
    store = _store(tmp_path)
    release = _hold_lock(store)
    _assert_blocks(lambda: store.save_rules([{"id": "r1", "text": "x"}]),
                   release, "save_rules 未取写锁")


def test_load_rules_migration_takes_write_lock(tmp_path):
    """版本落后的 rules.json → load_rules 的迁移写盘必须持锁。"""
    store = _store(tmp_path)
    # 造一个 v0 容器（schema_version 缺省 = 0 < 当前版本）
    (tmp_path / "rules.json").write_text(
        '{"rules": [{"id": "r1", "text": "x"}]}', encoding="utf-8")
    store.invalidate_cache(tmp_path / "rules.json")
    release = _hold_lock(store)
    _assert_blocks(lambda: store.load_rules(), release,
                   "load_rules 的迁移写盘未取写锁（读路径内无锁写）")


def test_upsert_rule_does_not_deadlock_with_locked_writers(tmp_path):
    """upsert_rule 自身持锁 + 内部走无锁读/写口——不得自锁死。"""
    store = _store(tmp_path)
    r = store.upsert_rule({"id": "r1", "name": "红线", "text": "NEVER x"})
    assert r["id"] == "r1"
    assert [x["id"] for x in store.load_rules()] == ["r1"]
    assert store.remove_rule("r1") is True
    assert store.load_rules() == []


# ---------- M3：复盘台账的内存状态改与文件写同临界区 ----------

def test_is_reviewed_takes_write_lock(tmp_path):
    store = _store(tmp_path)
    release = _hold_lock(store)
    _assert_blocks(lambda: store.is_reviewed("a", "s1"), release,
                   "is_reviewed 的懒加载未取写锁（锁外快照会覆盖并发 add）")


def test_should_enqueue_review_takes_write_lock(tmp_path):
    store = _store(tmp_path)
    release = _hold_lock(store)
    _assert_blocks(lambda: store.should_enqueue_review("a", "s1"), release,
                   "should_enqueue_review 未取写锁")


def test_mark_review_queued_takes_write_lock(tmp_path):
    store = _store(tmp_path)
    release = _hold_lock(store)
    _assert_blocks(lambda: store.mark_review_queued("a", "s1"), release,
                   "mark_review_queued 未取写锁（内存 ts 会落后文件）")


def test_mark_reviewed_takes_write_lock(tmp_path):
    store = _store(tmp_path)
    release = _hold_lock(store)
    _assert_blocks(lambda: store.mark_reviewed("a", "s1"), release,
                   "mark_reviewed 未取写锁（内存 add 与文件写不同临界区）")


def test_review_state_is_consistent_after_ops(tmp_path):
    """行为面：标记后立刻可见，且在飞摘除后 should_enqueue 语义不变。"""
    store = _store(tmp_path)
    assert store.is_reviewed("a", "s1") is False
    assert store.should_enqueue_review("a", "s1") is True
    store.mark_review_queued("a", "s1")
    assert store.should_enqueue_review("a", "s1") is False  # 在飞窗口内
    store.mark_reviewed("a", "s1")   # 顺手摘在飞（H7 断环）
    store.clear_review_queued("a", "s1")
    assert store.is_reviewed("a", "s1") is True
    assert store.should_enqueue_review("a", "s1") is False


# ---------- M4：快照导出（物化 + 脏计数复位）在锁内 ----------

def test_export_snapshot_takes_write_lock(tmp_path):
    store = _store(tmp_path)
    store.append_experience({"id": "e1", "trunk": "编程", "category": "调试",
                             "task": "t", "action": "a", "G": 0.5})
    release = _hold_lock(store)
    _assert_blocks(store.export_experience_snapshot, release,
                   "export_experience_snapshot 的物化未取写锁")


def test_export_snapshot_resets_dirty_and_writes_rows(tmp_path):
    store = _store(tmp_path)
    store.append_experience({"id": "e1", "trunk": "编程", "category": "调试",
                             "task": "t", "action": "a", "G": 0.5})
    assert store.export_experience_snapshot() == 1
    assert store._exp_dirty == 0
    text = (tmp_path / "experience.jsonl").read_text(encoding="utf-8")
    assert "e1" in text


# ---------- M10：类别索引重建必须在写锁外（高频新增路径） ----------

def test_append_experience_rebuilds_category_index_outside_lock(tmp_path,
                                                                monkeypatch):
    """M10：新增经验触发的类别索引重建（O(N) 全表扫 + 整文件写）不得在写锁内。

    证明方式：给 rebuild_category_index 装上探针，看被调用时能否**非阻塞**
    拿到写锁——拿到 = 已在锁外；拿不到 = 仍在锁内（会阻塞 record_session /
    record_rule_hits / record_injection 等所有写者）。
    """
    store = _store(tmp_path)
    seen: dict[str, bool] = {}

    def probe() -> dict:
        got = store._write_lock.acquire(blocking=False)
        seen["outside"] = got
        if got:
            store._write_lock.release()
        return {}

    monkeypatch.setattr(store, "rebuild_category_index", probe)
    store.append_experience({"id": "e1", "trunk": "编程", "category": "调试",
                             "task": "t", "action": "a", "G": 0.5})
    assert seen.get("outside") is True, \
        "类别索引重建仍在写锁内（经验上千条后每次新增都会阻塞所有写者）"


def test_append_experience_still_writes_category_index(tmp_path):
    """行为面：移出锁后索引照样被重建（读侧拿到的是最新分类）。"""
    store = _store(tmp_path)
    store.append_experience({"id": "e1", "trunk": "编程", "category": "调试",
                             "task": "写单测", "action": "a", "G": 0.5})
    idx = store.load_category_index()
    assert idx and "编程/调试" in idx
    assert "写单测" in idx["编程/调试"]
