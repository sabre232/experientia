"""H7：复盘**成功后**才标记已复盘，失败可重试（用户拍板）。

旧行为在**入队点**就 `mark_reviewed`——复盘失败/没跑完的会话也被标记成已复盘，
从此永不再重试。现在拆成两步：入队只记「在飞」（`mark_review_queued`），
复盘成功才 `mark_reviewed` + `clear_review_queued`。

本文件锁死四条语义：
1. 入队**不等于**已复盘（H7 核心断言）；
2. 在飞窗口内不重复入队（防活会话文件每轮增长被反复复盘）；
3. 窗口过期后可重新入队（= 失败重试）；
4. 无模型/熔断是降级路径不是成功——`settle_reviewed` 此时**不标记**。
"""

from __future__ import annotations

from app.capture import scan
from app.distill import llm
from app.store import review_queue as review_queue_mod
from app.store import store as store_mod
from app.store.store import Store


def test_enqueue_does_not_mark_reviewed(tmp_path):
    """H7 核心：入队 ≠ 已复盘。旧行为在这里就 mark_reviewed 了。"""
    store = Store(tmp_path)
    assert store.should_enqueue_review("a", "s1") is True
    store.mark_review_queued("a", "s1")
    assert store.is_reviewed("a", "s1") is False
    # 在飞窗口内不再重复入队
    assert store.should_enqueue_review("a", "s1") is False


def test_settle_marks_reviewed_and_stops_enqueue(tmp_path):
    store = Store(tmp_path)
    store.mark_review_queued("a", "s1")
    store.mark_reviewed("a", "s1")
    store.clear_review_queued("a", "s1")
    assert store.is_reviewed("a", "s1") is True
    assert store.should_enqueue_review("a", "s1") is False


def test_retry_after_inflight_window_expires(tmp_path, monkeypatch):
    """窗口过期 → 重新入队（失败重试的通路）。"""
    store = Store(tmp_path)
    store.mark_review_queued("a", "s1")
    assert store.should_enqueue_review("a", "s1") is False
    # 常量已随域搬到 review_queue（store.py 只保留再导出副本），打桩目标要跟着改，
    # 否则改的是副本、should_enqueue_review 读的仍是原模块的，打桩静默失效
    monkeypatch.setattr(review_queue_mod, "REVIEW_RETRY_AFTER_S", 0)
    assert store.should_enqueue_review("a", "s1") is True


def test_settle_marks_when_model_available(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "model_available", lambda s: True)
    monkeypatch.setattr(llm, "circuit_open", lambda s: False)
    store = Store(tmp_path)
    store.mark_review_queued("a", "s1")
    scan.settle_reviewed(store, [{"agent": "a", "session_id": "s1"}])
    assert store.is_reviewed("a", "s1") is True
    assert store.should_enqueue_review("a", "s1") is False


def test_settle_skips_when_no_model(tmp_path, monkeypatch):
    """无模型是设计好的降级路径（挂证据队列待重放），不是成功——不能标记。

    标记了就等于放弃这个会话：接上模型后它也不会再被复盘。
    """
    monkeypatch.setattr(llm, "model_available", lambda s: False)
    store = Store(tmp_path)
    store.mark_review_queued("a", "s1")
    scan.settle_reviewed(store, [{"agent": "a", "session_id": "s1"}])
    assert store.is_reviewed("a", "s1") is False
    # 仍在飞，等接上模型后重试
    assert store.should_enqueue_review("a", "s1") is False


def test_settle_skips_when_circuit_open(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "model_available", lambda s: True)
    monkeypatch.setattr(llm, "circuit_open", lambda s: True)
    store = Store(tmp_path)
    store.mark_review_queued("a", "s1")
    scan.settle_reviewed(store, [{"agent": "a", "session_id": "s1"}])
    assert store.is_reviewed("a", "s1") is False


def test_review_dict_for_replay_rejects_same_prefix_escape(tmp_path):
    """ref 指向数据目录的**同前缀兄弟目录**（.experientia-evil）→ 原样回退，
    不把外部文件并进复盘素材（原 startswith 前缀校验可被穿透）。"""
    store = Store(tmp_path / "data")
    store.ensure_layout()
    evil = tmp_path / "data-evil"
    evil.mkdir()
    (evil / "x.jsonl").write_text('{"role": "user", "content": "evil"}\n',
                                  encoding="utf-8")
    rec = {"agent": "codex", "session_id": "s1", "ref": "../data-evil/x.jsonl"}
    out = scan.review_dict_for_replay(store, rec)
    assert out == rec
    assert "user_messages" not in out  # 没有解析外部文件
