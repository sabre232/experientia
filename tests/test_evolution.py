"""演化链 / 遗忘 / 回滚测试（P0-3，纪律 D4 合并、D5 冲突、D6 遗忘）。

核心断言只有一句：**换代一定留痕，历史一定只增不改，遗忘一定可逆**。
"""

import json

import pytest

from app.mcp_server import _tool_search
from app.store import experience_db as edb
from app.store.store import Store

EXP_A = {
    "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
    "task": "首屏加载很慢", "action": "压缩图片", "outcome": "LCP 降到 2s",
    "G": 0.9,
}


def _store(tmp_path):
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


def _add(store, **over):
    rec = dict(EXP_A)
    rec.update(over)
    return store.append_experience(rec)


# ---------- 换代 ----------

def test_supersede_creates_a_chain(tmp_path):
    store = _store(tmp_path)
    a = _add(store)
    b = store.supersede_experience(a["id"], {"action": "图片转 AVIF 并加懒加载"},
                                   reason="发现更好的做法")

    assert b["id"] != a["id"]
    assert b["revision"] == 2
    assert b["root_id"] == a["root_id"] == a["id"]
    assert b["supersedes"] == [a["id"]]
    assert b["superseded_by"] == ""
    # 身份字段继承旧头（换代不该把归属改丢）
    assert (b["agent"], b["trunk"], b["category"]) == \
        (a["agent"], a["trunk"], a["category"])

    old = store.find_experience(a["id"])
    assert old["superseded_by"] == b["id"]

    # 默认读只剩链头——旧版不该再被检索/注入
    ids = [e["id"] for e in store.iter_experiences(include_distilled=True)]
    assert ids == [b["id"]]


def test_supersede_twice_keeps_single_root(tmp_path):
    store = _store(tmp_path)
    a = _add(store)
    b = store.supersede_experience(a["id"], {"action": "做法二"})
    c = store.supersede_experience(b["id"], {"action": "做法三"})
    assert [x["revision"] for x in (a, b, c)] == [1, 2, 3]
    assert {x["root_id"] for x in (a, b, c)} == {a["id"]}
    chain = store.experience_chain(c["id"])
    assert chain["depth"] == 3
    assert [r["revision"] for r in chain["revisions"]] == [1, 2]
    assert chain["current"]["id"] == c["id"]


def test_update_experience_does_not_create_revision(tmp_path):
    """原地补字段（改 G / 标记）不算换代——否则每次 G 反馈都生成一版历史。"""
    store = _store(tmp_path)
    a = _add(store)
    store.update_experience(a["id"], {"G": 0.3})
    cur = store.find_experience(a["id"])
    assert cur["revision"] == 1
    assert store.experience_chain(a["id"])["depth"] == 1


def test_supersede_through_mid_chain_id(tmp_path):
    """传中间版本的 id 也应作用于链头，不会造出分叉。"""
    store = _store(tmp_path)
    a = _add(store)
    b = store.supersede_experience(a["id"], {"action": "做法二"})
    c = store.supersede_experience(a["id"], {"action": "从老 id 换代"})
    assert c["supersedes"] == [b["id"]]
    assert c["root_id"] == a["id"]
    assert store.experience_chain(c["id"])["depth"] == 3


# ---------- 遗忘 ----------

def test_forget_hides_then_restore(tmp_path):
    store = _store(tmp_path)
    a = _add(store)
    assert store.forget_experience(a["id"]) is True
    assert store.find_experience(a["id"]) is None or \
        store.find_experience(a["id"]).get("tombstone")
    # 默认读路径一律不返回（含 show_dismissed 也不返回遗忘项）
    assert [e["id"] for e in store.iter_experiences(include_distilled=True)] == []
    assert [e["id"] for e in store.iter_experiences(
        show_dismissed=True, include_distilled=True)] == []
    # 显式要才看得见
    assert [e["id"] for e in store.iter_experiences(
        show_tombstoned=True, include_distilled=True)] == [a["id"]]
    # 幂等
    assert store.forget_experience(a["id"]) is False
    # 可逆
    assert store.restore_experience(a["id"]) is True
    assert [e["id"] for e in store.iter_experiences(include_distilled=True)] == [a["id"]]


def test_forgotten_not_searchable_via_mcp(tmp_path):
    """D6：遗忘项从召回面也消失——不只在 GUI 藏。"""
    store = _store(tmp_path)
    a = _add(store)
    out = _tool_search(store, {"query": "图片 压缩"})
    assert [r["id"] for r in out["results"]] == [a["id"]]
    store.forget_experience(a["id"])
    out2 = _tool_search(store, {"query": "图片 压缩"})
    assert out2["results"] == []


def test_forgotten_or_dismissed_not_gettable_via_mcp(tmp_path):
    """D6 的 get 侧：按 id 直取同样不返回已遗忘/已忽略/已换代——与 search 同口径。

     H4 之前 `_tool_get` 直落 `find_experience`，三种状态按 id 可取全文。
    """
    from app.mcp_server import _tool_get

    store = _store(tmp_path)
    a = _add(store)
    assert _tool_get(store, {"id": a["id"]})["found"] is True

    store.forget_experience(a["id"])
    assert _tool_get(store, {"id": a["id"]})["found"] is False
    store.restore_experience(a["id"])

    store.update_experience(a["id"], {"dismissed": True})
    assert _tool_get(store, {"id": a["id"]})["found"] is False
    store.update_experience(a["id"], {"dismissed": False})

    b = store.supersede_experience(a["id"], {"action": "图片转 AVIF"},
                                   reason="更好的做法")
    assert _tool_get(store, {"id": a["id"]})["found"] is False
    assert _tool_get(store, {"id": b["id"]})["found"] is True


def test_forget_hard_deletes_row_but_keeps_archive(tmp_path):
    store = _store(tmp_path)
    a = _add(store)
    assert store.forget_experience(a["id"], hard=True) is True
    assert store.find_experience(a["id"]) is None
    # deprecated 里有完整副本（30 天内可人工捞回）
    archived = []
    for path in (store.data_dir / "deprecated").rglob("experiences.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                archived.append(json.loads(line))
    assert any(x.get("id") == a["id"] for x in archived)


def test_forget_archives_before_marking(tmp_path, monkeypatch):
    """安全序：先归档落盘，再标 tombstone。归档写失败时状态不许变。"""
    store = _store(tmp_path)
    a = _add(store)
    import app.store.experience as exp_mod

    def boom(_):
        raise OSError("磁盘满")

    monkeypatch.setattr(exp_mod.os, "fsync", boom)
    assert store.forget_experience(a["id"]) is False
    # 状态没动：没标 tombstone（新记录本就没这个字段，None 就等于没忘）
    assert not store.find_experience(a["id"]).get("tombstone")


def test_forget_then_supersede_rejected(tmp_path):
    """遗忘项不许被换代——要么先恢复，要么当它不存在。"""
    store = _store(tmp_path)
    a = _add(store)
    store.forget_experience(a["id"])
    with pytest.raises(KeyError):
        store.supersede_experience(a["id"], {"action": "复活试试"})


# ---------- 回滚 ----------

def test_rollback_creates_new_head_with_old_content(tmp_path):
    store = _store(tmp_path)
    a = _add(store)
    b = store.supersede_experience(a["id"], {"action": "做法二"})
    back = store.rollback_experience(b["id"], 1)

    assert back["action"] == a["action"]        # 内容回到旧版
    assert back["revision"] == 3                # 但它是**新**版本，历史没被改写
    assert back["root_id"] == a["id"]
    assert back["supersedes"] == [b["id"]]
    assert back["rollback_of"] == f"{a['id']}#1"
    # 回滚头必须是新 id。快照带旧 id，supersede 照单全收 →
    # UPSERT 原地顶掉旧头主行，"换代绝不原地覆盖"被破；旧头内容只剩快照里一份。
    assert back["id"] != a["id"] and back["id"] != b["id"]
    a_row = store.find_experience(a["id"])
    assert a_row is not None and a_row["action"] == a["action"]
    assert a_row["superseded_by"] == b["id"]     # 旧头标记没被顶掉
    # 旧快照仍在，链完整
    chain = store.experience_chain(back["id"])
    assert chain["depth"] == 3
    assert [r["revision"] for r in chain["revisions"]] == [1, 2]


def test_degraded_mode_state_writes_fall_back_to_jsonl(tmp_path, monkeypatch):
    """：索引不可用时，软忘/恢复/换代旧头标记也要落 JSONL。

    此前这三处裸写 SQLite（`_expdb=None` 时返回 False 被无视）：软忘返回
    True 但 tombstone 没落任何库——用户以为忘了其实没忘；旧头不标
    superseded_by → JSONL 读路径双头。
    """
    from app.store import experience_db as edb

    monkeypatch.setattr(edb.ExperienceDB, "rebuild",
                        lambda self, exps, **kw: (_ for _ in ()).throw(
                            RuntimeError("磁盘只读")))
    store = _store(tmp_path)
    assert store._expdb is None
    a = _add(store)

    assert store.forget_experience(a["id"]) is True
    assert list(store.iter_experiences(include_distilled=True)) == []
    assert store.restore_experience(a["id"]) is True
    assert [e["id"] for e in store.iter_experiences(include_distilled=True)] == \
        [a["id"]]

    b = store.supersede_experience(a["id"], {"action": "做法二"})
    old = store.find_experience(a["id"])
    assert old is not None and old["superseded_by"] == b["id"]
    assert [e["id"] for e in store.iter_experiences(include_distilled=True)] == \
        [b["id"]]


def test_rollback_unknown_revision_raises(tmp_path):
    store = _store(tmp_path)
    a = _add(store)
    with pytest.raises(KeyError):
        store.rollback_experience(a["id"], 99)


def test_history_is_append_only(tmp_path):
    """同一 (id, revision) 的快照不被二次写入改写。"""
    store = _store(tmp_path)
    a = _add(store)
    b = store.supersede_experience(a["id"], {"action": "做法二"})
    db = store._expdb
    before = db.get_revision(a["root_id"], 1)
    store.supersede_experience(b["id"], {"action": "做法三"})
    # 再换代一次 → 应去快照 b（revision 2），而不是改写 a 的 revision 1
    after = db.get_revision(a["root_id"], 1)
    assert after == before
    assert db.get_revision(a["root_id"], 2) is not None


# ---------- 兼容 / 导出 ----------

def test_row_defaults_self_heal_legacy_records():
    """老记录（外部编辑/迁移前）没有链字段 → revision=1、root_id=自身。"""
    row = edb._row("abc", {"id": "abc", "task": "t"})
    cols = dict(zip(edb._COLS, row))
    assert cols["revision"] == 1
    assert cols["root_id"] == "abc"
    assert json.loads(cols["supersedes"]) == []
    assert cols["superseded_by"] == ""
    assert cols["tombstone"] == 0


def test_export_snapshot_carries_chain_fields(tmp_path):
    store = _store(tmp_path)
    a = _add(store)
    b = store.supersede_experience(a["id"], {"action": "做法二"})
    store.export_experience_snapshot()
    rows = [json.loads(x) for x in
            (store.data_dir / "experience.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip()]
    by_id = {r["id"]: r for r in rows}
    assert by_id[b["id"]]["revision"] == 2
    assert by_id[b["id"]]["root_id"] == a["root_id"]
    assert by_id[a["id"]]["superseded_by"] == b["id"]


def test_reopen_db_after_migration(tmp_path):
    """迁移幂等：关库再开一遍，链列与 revisions 表都还在、能正常读写。"""
    store = _store(tmp_path)
    a = _add(store)
    b = store.supersede_experience(a["id"], {"action": "做法二"})
    store._expdb.close_all()

    store2 = Store(tmp_path / "data")
    chain = store2.experience_chain(b["id"])
    assert chain["depth"] == 2 and chain["current"]["id"] == b["id"]
    assert [e["id"] for e in store2.iter_experiences(include_distilled=True)] == [b["id"]]
