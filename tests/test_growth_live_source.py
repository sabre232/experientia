"""：成长页必须读 SQLite 事实源，不得读陈旧 JSONL 快照。

 起 `experience_source="sqlite"`：
- **新记录**仍 append 进 experience.jsonl（备份），但
- **更新与删除只写 SQLite**——JSONL 由每 20 次脏写触发的快照导出对齐。

旧实现 `growth_summary` 直读 `experience.jsonl`：改 importance / 退休 /
反馈后，成长页最多滞后 19 次写才更新（且结果缓存签名只看 JSONL 文件，
纯索引写连缓存都不失效）。
"""

from __future__ import annotations

from app.store.store import Store


def _exp(eid: str, **kw) -> dict:
    base = {
        "id": eid, "ts": "2026-10-14T00:00:00Z", "trunk": "编程",
        "category": "调试", "task": "修 bug", "action": "看日志",
        "state": "成功", "outcome": "解决", "G": 0.8,
        "agent": "codex", "session_id": "s-1",
    }
    base.update(kw)
    return base


def _store(tmp_path) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    # 模拟 v4 迁移后的口径：SQLite 是唯一事实源
    s._expdb.set_experience_source("sqlite")
    return s


def test_growth_reflects_sqlite_update_not_stale_jsonl(tmp_path):
    """更新类写只落 SQLite → growth_summary 必须看到新值（旧实现读 JSONL → 0）。"""
    store = _store(tmp_path)
    store.append_experience(_exp("e1"))
    assert store.growth_summary()["assets"]["top"] == 0
    store.update_experience("e1", {"importance": 9})  # sqlite-source：只写库
    assert store.growth_summary()["assets"]["top"] == 1


def test_growth_reflects_sqlite_retire_not_stale_jsonl(tmp_path):
    """退休（删主行）只落 SQLite → 成长页计数必须立刻减 1。"""
    store = _store(tmp_path)
    store.append_experience(_exp("e1"))
    before = store.growth_summary()["assets"]["total"]
    assert before == 1
    assert store.retire_experience("e1") is True
    assert store.growth_summary()["assets"]["total"] == 0


def test_growth_cache_invalidated_by_index_only_write(tmp_path):
    """纯索引写（JSONL 文件不变）也必须让结果缓存失效。"""
    store = _store(tmp_path)
    store.append_experience(_exp("e1"))
    first = store.growth_summary()
    assert first["assets"]["corrected"] == 0
    # corrected 走 update 路径（SQLite-only）
    store.update_experience("e1", {"corrected": True})
    second = store.growth_summary()
    assert second["assets"]["corrected"] == 1  # 缓存未失效的话仍是 0


def test_sqlite_write_failure_is_reconciled_not_lost(tmp_path, monkeypatch):
    """：写库失败的新记录不得永久消失。

    旧行为：只记日志 return、`_write_experiences_sqlite` 仍返 True——该行只
    存在于不被读路径消费的 JSONL，且下一次快照导出（整文件从库重写）会把它
    抹掉，两头都不见。现在：置待对账标记 → 导出前"只插不删"补回库。
    """
    import sqlite3

    store = _store(tmp_path)
    db = store._expdb
    real = db.update_many
    calls = {"n": 0}

    def flaky(updates):
        calls["n"] += 1
        if calls["n"] == 1:  # 只让第一次（新增入库）失败
            raise sqlite3.OperationalError("disk I/O error")
        return real(updates)

    monkeypatch.setattr(db, "update_many", flaky)
    store.append_experience(_exp("e1"))
    assert db.jsonl_ahead() is True, "写库失败必须置待对账标记"
    # 快照导出是"整文件从库重写"——不先对账就会把这条抹掉
    n = store.export_experience_snapshot()
    assert n == 1
    assert db.jsonl_ahead() is False
    ids = [e["id"] for e in store.iter_experiences(include_distilled=True)]
    assert "e1" in ids, "JSONL 独有行必须被补进库，而不是被快照抹掉"
    # 快照文件里也在（导出从库重写，补过的行随之落盘）
    assert "e1" in (tmp_path / "experience.jsonl").read_text(encoding="utf-8")

