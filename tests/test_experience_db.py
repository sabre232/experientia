"""SQLite 经验读索引测试：WAL、双写一致性、sha256 重建、并发、降级回退。"""

import json
import threading

from app.store.experience_db import ExperienceDB
from app.store.store import Store


def _rec(i=0, **kw):
    base = {"id": f"e{i}", "agent": "codex", "task": f"写标题{i}",
            "action": "利益点前置", "outcome": "ok", "G": 0.7,
            "trunk": "营销", "category": "文案写作", "count": 1,
            "ts": "2026-01-01T00:00:00Z"}
    base.update(kw)
    return base


def _make_db(tmp_path):
    return ExperienceDB(tmp_path / "experience.db", tmp_path)


# ---------- WAL 模式与连接约定 ----------

def test_wal_mode_and_pragmas(tmp_path):
    db = _make_db(tmp_path)
    conn = db.connection()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    # thread-local：同线程同连接
    assert db.connection() is conn


# ---------- 双写后读一致 ----------

def test_upsert_and_read_consistency(tmp_path):
    db = _make_db(tmp_path)
    db.rebuild([_rec(1), _rec(2, distilled=True)])
    # 写入序 = JSONL 行序
    assert [r["id"] for r in db.iter_experiences()] == ["e1", "e2"]
    assert [r["id"] for r in db.iter_experiences(include_distilled=False)] == ["e1"]
    # upsert 新增 + update_many 更新，读回一致（data JSON 为准，字段不丢）
    new = _rec(3, G=0.9, count=2)
    db.upsert(new)
    db.update_many({"e1": {**_rec(1), "G": 0.95, "count": 5}})
    rows = {r["id"]: r for r in db.iter_experiences()}
    assert rows["e3"]["G"] == 0.9 and rows["e3"]["count"] == 2
    assert rows["e1"]["G"] == 0.95 and rows["e1"]["count"] == 5
    assert rows["e1"]["outcome"] == "ok"  # data JSON 完整
    assert db.count() == 3
    # update_many 值 None = 删除（retire 语义）
    db.update_many({"e2": None})
    assert db.count() == 2
    assert db.find_duplicate("codex", "写标题3", "利益点前置")["id"] == "e3"
    assert db.find_duplicate("codex", "不存在", "x") is None
    assert db.find_by_session("s9") is None


def test_find_by_session_fallback(tmp_path):
    db = _make_db(tmp_path)
    db.rebuild([{"id": "a", "task": "t", "action": "a", "session_id": "s1"},
                {"id": "b", "task": "t", "action": "a", "session": "s2"}])
    assert db.find_by_session("s1")["id"] == "a"
    assert db.find_by_session("s2")["id"] == "b"


def test_all_for_category_index_source(tmp_path):
    db = _make_db(tmp_path)
    db.rebuild([_rec(1, trunk="营销", category="文案", task="写标题"),
                _rec(2, trunk="营销", category="文案", task="写文案", distilled=True),
                _rec(3, trunk="工程", category="发布", task="部署", dismissed=True)])
    got = list(db.all_for_category_index())
    assert [r["id"] for r in got] == ["e1", "e2", "e3"]  # 含已蒸馏/不采纳，与 JSONL 全扫口径一致


def test_rewrite_category(tmp_path):
    db = _make_db(tmp_path)
    db.rebuild([_rec(1, trunk="营销", category="旧类"),
                _rec(2, trunk="营销", category="旧类"),
                _rec(3, trunk="营销", category="别类")])
    n = db.rewrite_category("营销", "旧类", "新类")
    assert n == 2
    rows = {r["id"]: r for r in db.iter_experiences()}
    assert rows["e1"]["category"] == "新类" and rows["e3"]["category"] == "别类"


# ---------- sha256 失配自动重建 ----------

def test_rebuild_if_stale_sha_mismatch(tmp_path):
    jsonl = tmp_path / "experience.jsonl"
    jsonl.write_text(json.dumps(_rec(1), ensure_ascii=False) + "\n", encoding="utf-8")
    db = _make_db(tmp_path)
    assert db.rebuild_if_stale(jsonl) is True   # 首次：db 不存在 → 重建
    assert db.rebuild_if_stale(jsonl) is False  # 一致 → 跳过（不重刷）
    assert db.count() == 1
    # mark_synced 刷新指纹后仍跳过
    jsonl.write_text(json.dumps(_rec(1), ensure_ascii=False) + "\n"
                     + json.dumps(_rec(2), ensure_ascii=False) + "\n", encoding="utf-8")
    assert db.rebuild_if_stale(jsonl) is True   # 外部编辑（追加）→ sha 失配 → 重建
    assert db.count() == 2
    assert db.rebuild_if_stale(jsonl) is False


def test_rebuild_if_stale_missing_meta(tmp_path):
    jsonl = tmp_path / "experience.jsonl"
    jsonl.write_text(json.dumps(_rec(1), ensure_ascii=False) + "\n", encoding="utf-8")
    db = _make_db(tmp_path)
    db.rebuild_if_stale(jsonl)
    with db.connection() as conn:
        conn.execute("DELETE FROM meta")  # 模拟 meta 缺失
    assert db.rebuild_if_stale(jsonl) is True
    assert db.count() == 1


def test_corrupt_db_self_heals(tmp_path):
    jsonl = tmp_path / "experience.jsonl"
    jsonl.write_text(json.dumps(_rec(1), ensure_ascii=False) + "\n", encoding="utf-8")
    db_path = tmp_path / "experience.db"
    db_path.write_bytes(b"not a sqlite file at all")
    db = _make_db(tmp_path)
    assert db.rebuild_if_stale(jsonl) is True
    assert db.count() == 1


# ---------- 线程局部连接并发 upsert ----------

def test_threaded_concurrent_upserts_no_loss(tmp_path):
    db = _make_db(tmp_path)
    n_threads, per_thread = 10, 10

    def worker(t):
        for i in range(per_thread):
            db.upsert(_rec(t * per_thread + i, task=f"任务{t}-{i}"))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert db.count() == n_threads * per_thread  # 100 条不丢
    rows = {r["id"] for r in db.iter_experiences()}
    assert len(rows) == n_threads * per_thread


# ---------- Store 接入：双写一致 + 降级回退 ----------

def test_store_double_write_reads_via_index(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    assert store._expdb is not None
    r1 = store.append_experience(_rec(1))
    r2 = store.append_experience(_rec(1, G=0.9))  # 合并 dup → update_many
    assert r2["count"] == 2 and r2["G"] == 0.9
    assert store._expdb.count() == 1  # 索引去重后一条
    rows = list(store.iter_experiences())
    assert len(rows) == 1 and rows[0]["count"] == 2 and rows[0]["G"] == 0.9
    # JSONL 降级为追加式备份——合并/更新只落 SQLite、不再重写 JSONL，故备份
    # 仍只有首条追加的 1 行；合并后的 count 以 SQLite 读视图为准（上面已断言）。
    lines = [l for l in (tmp_path / "experience.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    # 蒸馏打标双写
    store.mark_experiences_distilled([r1["id"]])
    assert list(store.iter_experiences(trunk="营销")) == []
    assert len(list(store.iter_experiences(include_distilled=True))) == 1
    assert store._expdb.count() == 1
    # retire 删除双写
    store.retire_experience(r1["id"])
    assert list(store.iter_experiences(include_distilled=True)) == []
    assert store._expdb.count() == 0
    # 更新路径双写
    r3 = store.append_experience(_rec(2))
    store.update_experience(r3["id"], {"G": 0.1})
    rows = list(store.iter_experiences())
    assert len(rows) == 1 and rows[0]["G"] == 0.1


def test_store_index_rebuild_on_restart_after_external_edit(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.append_experience(_rec(1))
    # 外部编辑 JSONL（模拟用户手改）：新 Store 初始化应 sha256 失配自动重建
    with (tmp_path / "experience.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_rec(2), ensure_ascii=False) + "\n")
    store2 = Store(tmp_path)
    assert store2._expdb.count() == 2
    assert [r["id"] for r in store2.iter_experiences(include_distilled=True)] == ["e1", "e2"]
    # 正常重启（无外部编辑）→ 跳过重建，读路径仍一致
    store2.append_experience(_rec(3))
    store3 = Store(tmp_path)
    assert store3._expdb.count() == 3


def test_store_fallback_when_rebuild_fails(tmp_path, monkeypatch):
    """初始化失败 → _expdb=None，读/写路径仍走 JSONL 正确返回（fail-open）。"""
    monkeypatch.setattr(ExperienceDB, "rebuild",
                        lambda self, exps, **kw: (_ for _ in ()).throw(
                            RuntimeError("磁盘只读")))
    store = Store(tmp_path)
    store.ensure_layout()
    assert store._expdb is None
    r = store.append_experience(_rec(1))
    assert r["id"] == "e1"
    rows = list(store.iter_experiences())
    assert len(rows) == 1 and rows[0]["task"] == "写标题1"
    store.mark_experiences_distilled([r["id"]])
    assert list(store.iter_experiences()) == []
    assert len(list(store.iter_experiences(include_distilled=True))) == 1
    store.retire_experience(r["id"])
    assert list(store.iter_experiences(include_distilled=True)) == []
    lines = [l for l in (tmp_path / "experience.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines == []  # JSONL 事实源行为不变


def test_store_double_write_failure_self_heals_via_rebuild(tmp_path, monkeypatch):
    """运行中双写失败 → 自动从 JSONL 全量重建索引（自愈），读路径保持正确。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.append_experience(_rec(1))

    def broken_update_many(self, id_to_rec):
        raise RuntimeError("索引写失败")

    monkeypatch.setattr(ExperienceDB, "update_many", broken_update_many)
    store.append_experience(_rec(2))
    assert store._expdb is not None            # 重建成功 → 索引自愈，不停用
    assert store._expdb.count() == 2           # 重建读 JSONL（事实源），两条都在
    rows = list(store.iter_experiences(include_distilled=True))
    assert [r["id"] for r in rows] == ["e1", "e2"]


def test_store_double_write_failure_falls_back_to_jsonl(tmp_path, monkeypatch):
    """重建也失败 → 停用索引，读路径回退 JSONL（fail-open）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    store.append_experience(_rec(1))
    db = store._expdb

    def broken(self, *a, **kw):
        raise RuntimeError("索引不可用")

    monkeypatch.setattr(ExperienceDB, "update_many", broken)
    monkeypatch.setattr(ExperienceDB, "rebuild", broken)
    store.append_experience(_rec(2))
    assert store._expdb is None                # 停用索引
    assert db.count() == 1                     # 旧索引内容停留在失败前，不再被读路径使用
    rows = list(store.iter_experiences(include_distilled=True))
    assert [r["id"] for r in rows] == ["e1", "e2"]  # 读路径走 JSONL，结果正确
    monkeypatch.undo()
    # 重启后 sha 失配 → 自动重建修复索引
    store2 = Store(tmp_path)
    assert store2._expdb is not None and store2._expdb.count() == 2


def test_store_wipe_recreates_empty_index(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.append_experience(_rec(1))
    assert store.wipe_all() == []
    assert store._expdb is not None
    assert store._expdb.count() == 0
    assert list(store.iter_experiences(include_distilled=True)) == []
    # wipe 后可继续正常写入
    store.append_experience(_rec(2))
    assert [r["id"] for r in store.iter_experiences(include_distilled=True)] == ["e2"]


def test_store_rename_category_syncs_index(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("营销", "文案写作", "# 营销 / 文案写作 · playbook\n\n> version: 1\n\n## 标准流程\n- 步骤一\n")
    store.append_experience(_rec(1))
    store.rename_skill("营销", "文案写作", None, "报价文案")
    rows = list(store.iter_experiences(include_distilled=True))
    assert [r["category"] for r in rows] == ["报价文案"]
    assert store._expdb.count() == 1
