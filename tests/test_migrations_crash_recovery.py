"""：迁移半途失败后重跑必须能收敛。

崩在"已清空/已重写主文件"与"重建索引"之间时，重跑会走早退分支——
旧实现在早退前 `return`，跳过了索引对账，于是：
- v1：被"清库"的经验仍留在 experience.db，而读路径全走索引 →
  用户看到迁移报告说清了 N 条，实际一条没清；
- v2：下架的 env 噪音仍在索引里被注入。
"""

from __future__ import annotations

from app.store import migrations
from app.store.store import Store


def _store(tmp_path) -> Store:
    """**不要**在这里设 experience_source=sqlite：v1/v2 按版本顺序跑在 v4 之前，
    真实崩溃恢复时该标志尚未置位（若已置位说明 v4 已成功过，迁移不会重跑）。
    置位后 `rebuild_if_stale` 会按设计短路"不按 JSONL 重建"，那是另一条语义。"""
    s = Store(tmp_path)
    s.ensure_layout()
    return s


def test_v1_rerun_with_empty_file_still_reconciles_index(tmp_path):
    """文件已清空（上次崩在清空后）→ 重跑必须把索引也对账清空。"""
    store = _store(tmp_path)
    db = store._expdb
    db.update_many({"e1": {"id": "e1", "trunk": "编程", "category": "调试"}})
    assert "e1" in db.existing_ids()
    # 模拟上次：主文件已清空，索引还没重建
    (tmp_path / "experience.jsonl").write_text("", encoding="utf-8")
    n = migrations._v1_clear_experience(store)
    assert n == 0
    assert "e1" not in db.existing_ids(), \
        "早退跳过了索引对账 → 被清掉的经验还在索引里（读路径全走索引）"


def test_v1_rerun_without_file_still_reconciles_index(tmp_path):
    """文件被删（清空后再被删；索引还留着行）→ 重跑同样要对齐到空。

    走真实写路径落一条（会经 mark_synced 给索引盖文件指纹章），再删文件——
    这样指纹由"有条目"变成 None，重建条件成立。"""
    store = _store(tmp_path)
    db = store._expdb
    store.append_experience({"id": "e1", "ts": "2026-10-14T00:00:00Z",
                             "trunk": "编程", "category": "调试",
                             "task": "t", "action": "a", "G": 0.5})
    assert "e1" in db.existing_ids()
    p = tmp_path / "experience.jsonl"
    p.unlink()
    migrations._v1_clear_experience(store)
    assert "e1" not in db.existing_ids()


def test_v2_rerun_with_empty_file_still_reconciles_index(tmp_path):
    """v2 崩在"已重写主文件"与"重建索引"之间 → 重跑仍要重建索引。"""
    store = _store(tmp_path)
    db = store._expdb
    db.update_many({"ghost": {"id": "ghost", "trunk": "编程",
                              "category": "调试"}})
    assert "ghost" in db.existing_ids()
    (tmp_path / "experience.jsonl").write_text("", encoding="utf-8")
    rc = migrations._v2_reclassify_experience(store)
    assert rc == {"tagged": 0, "dropped": 0}
    assert "ghost" not in db.existing_ids(), \
        "早退跳过了索引对账 → 已下架的行仍在索引里被注入"
