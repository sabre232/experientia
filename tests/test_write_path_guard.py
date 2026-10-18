"""数据写路径加固护栏（第一批：H1/H2/H6/H7/M8）。

锁五件事：
1. H2 原子写：写成功不留 .tmp 残骸；rename 失败时清走自己的临时文件；
2. M8 整文件重写：坏行先归档进 deprecated/<日期>/salvage-*.jsonl 再丢，
   绝不物理删除（坏行可能是半写的好数据）；
3. H6 写口契约：importance 非数值在 append 时归一/剔除，不入库埋雷；
4. H6 读侧容错：外部编辑的坏 importance / 坏 G 不击穿 growth_summary 与
   iter_experiences 回退读路径（坏 G 在读视图被净化为 0.0）；
5. H7 熔断器：config.json 的读-改-写走 mutate_config 写锁事务，
   与设置页保存并发互不覆盖；热路径（已 closed 且零计数）不写盘。
"""

from __future__ import annotations

import json
import os

import pytest

from app.distill import llm
from app.store.store import REPLACE_RETRIES, Store


def _store(tmp_path) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    s.save_config({})
    return s


def _exp(i: int, **patch) -> dict:
    rec = {"task": f"任务{i}", "action": f"动作{i}", "G": 0.7,
           "g_source": "auto", "agent": "codex", "trunk": "营销",
           "category": "文案写作", "session_id": f"s{i}", "count": 1}
    rec.update(patch)
    return rec


# ---------- 1. H2 原子写 ----------

def test_atomic_write_leaves_no_tmp(tmp_path):
    store = _store(tmp_path)
    p = store.data_dir / "experience.jsonl"
    store._write_tmp_rename(p, '{"a": 1}\n')
    assert json.loads(p.read_text(encoding="utf-8").strip()) == {"a": 1}
    leftovers = [f for f in store.data_dir.iterdir()
                 if f.name.endswith(".tmp")]
    assert not leftovers, f"原子写后残留 .tmp: {leftovers}"


def test_atomic_write_retries_transient_winerror5(tmp_path, monkeypatch):
    """AV/索引服务短暂持锁 → PermissionError，重试后成功（WinError 5 实锤路径）。"""
    store = _store(tmp_path)
    p = store.data_dir / "experience.jsonl"
    p.write_text("old", encoding="utf-8")
    calls = []
    real_replace = os.replace

    def _flaky(src, dst):
        calls.append(dst)
        if len(calls) <= 2:  # 前两次撞瞬时锁
            raise PermissionError(5, "拒绝访问", str(dst), None)
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _flaky)
    store._write_tmp_rename(p, "new content")
    monkeypatch.undo()
    assert len(calls) == 3
    assert p.read_text(encoding="utf-8") == "new content"


def test_replace_gives_up_and_cleans_tmp(tmp_path, monkeypatch):
    """持锁不释放（非瞬时）→ 重试耗尽后抛原异常，且 tmp 不残留、正式文件不动。"""
    store = _store(tmp_path)
    p = store.data_dir / "experience.jsonl"
    p.write_text("keep", encoding="utf-8")
    attempts = []

    def _locked(src, dst):
        attempts.append(1)
        raise PermissionError(5, "拒绝访问", str(dst), None)

    monkeypatch.setattr(os, "replace", _locked)
    with pytest.raises(PermissionError):
        store._write_tmp_rename(p, "new content")
    monkeypatch.undo()
    assert len(attempts) == REPLACE_RETRIES
    assert p.read_text(encoding="utf-8") == "keep", "写失败不得动正式文件"
    assert not [f for f in store.data_dir.iterdir() if f.name.endswith(".tmp")]


def test_replace_does_not_retry_non_permission_errors(tmp_path, monkeypatch):
    """非 PermissionError（目录不可写等）不重试——重试没有意义，白等 ~0.1s。"""
    store = _store(tmp_path)
    p = store.data_dir / "experience.jsonl"
    attempts = []

    def _boom(src, dst):
        attempts.append(1)
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        store._write_tmp_rename(p, "new content")
    monkeypatch.undo()
    assert len(attempts) == 1


def test_cap_jsonl_lines_survives_transient_lock(tmp_path, monkeypatch):
    """封顶写路径（changelog 1001 次的真实场景）在瞬时锁下照样收敛到上限。"""
    from app.store.store import CHANGELOG_MAX_LINES

    store = _store(tmp_path)
    hits = []
    real_replace = os.replace

    def _flaky(src, dst):
        hits.append(1)
        # 每个 replace 的第一次尝试都撞瞬时锁：模拟 AV 扫描恰好在整个写路径上
        if len(hits) % 2 == 1:
            raise PermissionError(5, "拒绝访问", str(dst), None)
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _flaky)
    for i in range(CHANGELOG_MAX_LINES + 3):
        store.append_changelog(f"entry {i}")
    monkeypatch.undo()
    lines = [l for l in (store.data_dir / "changelog.md").read_text(
        encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == CHANGELOG_MAX_LINES
    assert lines[-1].endswith(f"entry {CHANGELOG_MAX_LINES + 2}")


def test_atomic_write_cleans_tmp_on_replace_failure(tmp_path, monkeypatch):
    store = _store(tmp_path)
    p = store.data_dir / "experience.jsonl"
    p.write_text("keep", encoding="utf-8")

    def _boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        store._write_tmp_rename(p, "new content")
    monkeypatch.undo()
    leftovers = [f for f in store.data_dir.iterdir()
                 if f.name.endswith(".tmp")]
    assert not leftovers, "rename 失败必须清走自己的临时文件"
    assert p.read_text(encoding="utf-8") == "keep", "写失败不得动正式文件"


# ---------- 2. M8 坏行先归档再丢 ----------

def test_rewrite_salvages_bad_lines(tmp_path):
    store = _store(tmp_path)
    p = store.data_dir / "experience.jsonl"
    good = json.dumps({**_exp(1), "id": "e1"}, ensure_ascii=False)
    # 半写的坏行：截断的 JSON——物理删除 = 无声丢数据
    bad = '{"task": "投放标题第9版", "acti'
    p.write_text(good + "\n" + bad + "\n", encoding="utf-8")

    store._read_write_jsonl(p, lambda item: item)  # 直接触发整文件重写（后经验更新不再走它）

    assert bad not in p.read_text(encoding="utf-8"), "坏行应已移出主文件"
    salvage_dirs = list((store.data_dir / "deprecated").rglob(
        "salvage-experience.jsonl"))
    assert salvage_dirs, "坏行必须先归档进 deprecated/ 再丢"
    assert bad in salvage_dirs[0].read_text(encoding="utf-8")


# ---------- 3. H6 写口契约：importance 归一 ----------

def test_append_experience_normalizes_importance(tmp_path):
    store = _store(tmp_path)
    r1 = store.append_experience(_exp(1, importance="8"))
    assert r1["importance"] == 8
    r2 = store.append_experience(_exp(2, importance="很高"))
    assert "importance" not in r2, "非数值 importance 应被剔除而非入库埋雷"
    r3 = store.append_experience(_exp(3, importance=7.9))
    assert r3["importance"] == 7


# ---------- 4. H6 读侧容错：外部编辑的脏行 ----------

def test_growth_summary_survives_dirty_rows(tmp_path):
    store = _store(tmp_path)
    store.append_experience(_exp(1, importance=9))
    # 模拟外部编辑/旧数据：非数值 importance + 坏 G 直接进文件
    p = store.data_dir / "experience.jsonl"
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({**_exp(2, id="e2"), "importance": "x"}) + "\n")
        fh.write(json.dumps({**_exp(3, id="e3", g_source="rule"),
                             "G": "bad"}) + "\n")
    # growth_summary 改走经验索引（SQLite 事实源，与
    # 其余页面同口径），带外手改的文件要"下次启动按 sha 自愈重建"才可见——
    # 正是下面注释说的契约内路径，故这里用全新 Store 实例读。
    fresh = Store(tmp_path)
    summary = fresh.growth_summary(days=30)  # 旧代码在此 int("x") 抛异常
    assert summary["assets"]["judged"] == 2
    exps = list(fresh.iter_experiences(include_distilled=True))
    dirty = next(e for e in exps if e.get("id") == "e3")
    assert dirty["G"] == 0.0, "读视图的坏 G 必须被净化为 0.0"
    # iter_experiences 契约：G/count/importance 对下游永远是干净数值
    for e in exps:
        assert isinstance(e["G"], float)
        assert isinstance(e["count"], int)
        if e.get("importance") is not None:
            assert isinstance(e["importance"], int)
    assert next(e for e in exps if e.get("id") == "e2")["importance"] == 0


# ---------- 5. H7 熔断器走写锁事务 ----------

def test_breaker_record_keeps_concurrent_config_edits(tmp_path):
    store = _store(tmp_path)
    store.save_config({"models": {"m": {"endpoint": "http://x"}}})
    llm._breaker_record(store, False)
    cfg = store.load_config()
    assert cfg["model_breaker"]["state"] == "closed"
    assert cfg["model_breaker"]["fail_count"] == 1
    assert "models" in cfg, "熔断写回不得覆盖用户配置"


def test_breaker_success_on_closed_zero_does_not_rewrite(tmp_path, monkeypatch):
    store = _store(tmp_path)
    llm._breaker_record(store, True)  # 初始即 closed 零计数 → 无变化
    calls = []
    monkeypatch.setattr(store, "save_config",
                        lambda cfg: calls.append(cfg))
    llm._breaker_record(store, True)
    assert not calls, "热路径无状态变化时不应重写 config.json"


def test_breaker_allow_transitions_atomically(tmp_path):
    store = _store(tmp_path)
    import time as _t
    store.save_config({"model_breaker": {"state": "open", "fail_count": 3,
                                         "cooldown": 0.0, "opened_at": 0}})
    llm._breaker_allow(store)  # 冷却已过 → half_open 落盘
    st = store.load_config()["model_breaker"]
    assert st["state"] == "half_open"

    store.save_config({"model_breaker": {"state": "open", "fail_count": 3,
                                         "cooldown": 600, "opened_at": _t.time()}})
    with pytest.raises(llm.CircuitOpenError):
        llm._breaker_allow(store)
    st = store.load_config()["model_breaker"]
    assert st["state"] == "open", "拒绝放行时不得改状态"


# ---------- 6. M7 经验合并丢失更新窗口 + retire 重跑不叠副本 ----------

def test_bump_experience_merge_semantics(tmp_path):
    """M7：bump_experience_merge 用当前行派生 count+1 / G 取大 / seen_in 并集。"""
    store = _store(tmp_path)
    base = store.append_experience(_exp(2, G=0.4, seen_in=["a"], count=3))
    merged = store.bump_experience_merge(base["id"], g_value=0.9,
                                         seen_ids=["b", "c"])
    assert merged["count"] == 4
    assert merged["G"] == 0.9
    assert {"a", "b", "c", "s2"} <= set(merged["seen_in"]), "含自身 session_id"


def test_bump_experience_merge_concurrent_no_lost_update(tmp_path):
    """M7：读-改-写全程持写锁、用当前行派生 → 多线程并发合并同一经验，
    count 精确等于 1 + 总合并次数（任何交叠丢更新都会让它偏小）。"""
    import threading
    store = _store(tmp_path)
    base = store.append_experience(_exp(1, task="共享任务", action="共享动作",
                                        count=1))
    eid = base["id"]
    N, M = 8, 25  # 8 线程 × 25 次 = 200 次合并

    def worker():
        for _ in range(M):
            store.bump_experience_merge(eid, g_value=0.7, seen_ids=["sX"])

    threads = [threading.Thread(target=worker) for _ in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.find_experience(eid)["count"] == 1 + N * M


def test_retire_experience_rerun_no_double_archive(tmp_path):
    """M7：retire 先归档后删主行（不丢数据安全序）。模拟崩在两步之间——
    把条目塞回主行而 deprecated 副本仍在——重跑不得叠加第二份副本。"""
    store = _store(tmp_path)
    base = store.append_experience(_exp(3))
    eid = base["id"]
    assert store.retire_experience(eid) is True
    main = store.data_dir / "experience.jsonl"
    dep = store.deprecated_day_dir() / "experiences.jsonl"

    def dep_lines():
        return [l for l in dep.read_text(encoding="utf-8").splitlines() if l.strip()]

    assert len(dep_lines()) == 1
    assert store.find_experience(eid) is None
    # 主行仍在（重放）：后事实源是 SQLite → 塞回索引模拟"崩在两步之间"
    #（deprecated 副本已在 → 重跑只补删主行，不再归档）
    store._write_experiences_sqlite({eid: base})
    assert store.retire_experience(eid) is True
    assert len(dep_lines()) == 1, "重跑不得叠加第二份 deprecated 副本"
    assert store.find_experience(eid) is None

