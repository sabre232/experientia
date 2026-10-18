"""H7 跨通道一致性：任一通道标记已复盘，都必须摘掉「在飞」标记。

文件通道（scan.py）改为「入队记在飞、成功才标记」后，代理通道（server.py）与
hook 通道（hook.py）仍是「入队即标记」。若不处理，会形成环：

    文件通道入队 → 记在飞
    → 代理通道把同一会话标成已复盘（它不认在飞标记）
    → 文件通道的在飞条目没人摘
    → 2 小时后 should_enqueue_review 判"失败待重试" → 重新入队
    → 每 2 小时重复复盘一次（措辞漂移 → 经验库落重复行）

断环的办法：`mark_reviewed` 内部顺手摘掉在飞条目。本文件锁死这个行为。
"""

from __future__ import annotations

from app.store import review_queue as review_queue_mod
from app.store import store as store_mod
from app.store.store import Store


def test_mark_reviewed_clears_inflight(tmp_path):
    """代理/hook 通道走 mark_reviewed 时，文件通道记的在飞也要被摘掉。"""
    store = Store(tmp_path)
    # 文件通道：入队记在飞
    store.mark_review_queued("a", "s1")
    assert store.is_reviewed("a", "s1") is False
    # 代理通道：入队即标记（旧行为）
    store.mark_reviewed("a", "s1")
    assert store.is_reviewed("a", "s1") is True
    # 关键：在飞标记必须已摘掉，否则 2 小时后会被当失败重试
    monkeypatch_ttl = 0
    old = review_queue_mod.REVIEW_RETRY_AFTER_S
    review_queue_mod.REVIEW_RETRY_AFTER_S = monkeypatch_ttl
    try:
        assert store.should_enqueue_review("a", "s1") is False
    finally:
        review_queue_mod.REVIEW_RETRY_AFTER_S = old


def test_inflight_survives_if_never_reviewed(tmp_path):
    """反例：没标已复盘时，在飞条目要留着（那是重试的凭据）。"""
    store = Store(tmp_path)
    store.mark_review_queued("a", "s1")
    old = review_queue_mod.REVIEW_RETRY_AFTER_S
    review_queue_mod.REVIEW_RETRY_AFTER_S = 0
    try:
        assert store.should_enqueue_review("a", "s1") is True
    finally:
        review_queue_mod.REVIEW_RETRY_AFTER_S = old
