"""M8 / L6 / 守卫。

- M8：`wipe_all` 必须关掉会话搜索索引连接（否则 Windows 上 search.db 删不掉，
  假告警）并清空全部进程内派生缓存（否则 `_dup_index` 会把新经验合并进已删记录）；
- L6：hook 复盘 worker 抛异常要回滚"已复盘中水位"，否则该 sid 本进程内永不重试；
- L9s：`reinduct_preferences` 熔断 open 时与"无模型"同形降级（409），不裸抛 500。
"""

from __future__ import annotations

import pytest

from app.store.store import Store


def _rec(sid: str) -> dict:
    return {"agent": "codex", "session_id": sid, "project": "F:/demo",
            "user_messages": ["帮我修 pytest 收集不到测试的问题"],
            "assistant_messages": ["conftest 路径配错了"], "req_count": 1,
            "correction_hits": 0, "trunk": "编程", "category": "调试",
            "started_at": "2026-10-14T00:00:00Z"}


# ---------- M8 ----------

def test_wipe_all_closes_search_index_and_clears_caches(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.record_session(_rec("s1"))
    store.search_sessions("pytest")  # 建 search.db 连接
    assert getattr(store, "_searchidx", None) is not None
    # 放哨兵：wipe 后必须全部清空（不清则幽灵合并/顶着旧库）
    store._dup_index = {"x": {"id": "ghost"}}
    store._reviewed = {("a", "s1")}
    store._queued_reviews = {("a", "s1"): "t"}
    store._growth_cache = (("k",), {"assets": {}})
    store._workspace_cache = (("k",), {})

    leftovers = store.wipe_all()

    assert not any("search.db" in p for p in leftovers), \
        f"search.db 泄漏为残留（连接没关）：{leftovers}"
    assert store._dup_index is None
    assert store._reviewed is None
    assert store._queued_reviews is None
    assert store._growth_cache is None
    assert store._workspace_cache is None


# ---------- L6 ----------

def test_hook_review_worker_rolls_back_on_failure(monkeypatch):
    from app.capture import hook

    class _StopLoop(Exception):
        pass

    calls = {"n": 0}

    class _Q:
        def get(self):
            calls["n"] += 1
            if calls["n"] > 1:
                raise _StopLoop  # 第一轮跑完就跳出无限循环
            return (object(), type("S", (), {"session_id": "s1"})())

    def _boom(store, session):
        raise RuntimeError("boom")

    monkeypatch.setattr(hook, "_review_queue", _Q())
    monkeypatch.setattr(hook, "_run_stop_review", _boom)
    monkeypatch.setitem(hook._reviewed_upto, "s1", 5)

    with pytest.raises(_StopLoop):
        hook._stop_review_worker_loop()

    assert hook._reviewed_upto["s1"] == 0, \
        "复盘失败必须回滚中水位，否则该 sid 本进程内永不重试"


# ---------- L9s ----------

def test_reinduct_preferences_respects_circuit_open(tmp_path, monkeypatch):
    from app.distill import engine_curation, llm

    store = Store(tmp_path)
    store.ensure_layout()
    monkeypatch.setattr(llm, "model_available", lambda s: True)
    monkeypatch.setattr(llm, "circuit_open", lambda s: True)
    assert engine_curation.reinduct_preferences(store, "编程") == {"status": "no_model"}
