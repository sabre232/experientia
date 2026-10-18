"""M2 agent 维度（方案  / 产品文档  v3）：磨合度按 agent 拆分 + 经验列表 agent 筛选。

- affinity 键 = agent/trunk/category，同 trunk/category 不同 agent 分桶（不混合）
- agent 缺失 → unknown 桶
- affinity_display 展示口径（agent·category / unknown 只显示类别 / 2 段兜底）
- iter_experiences(agent=) 过滤
- growth_edges 键格式迁移不首轮误报新高（迁移轮只落基线）
- 全新安装不误触迁移
"""

from __future__ import annotations

from app import notify
from app.store.store import Store, affinity_display


TRUNK, CAT = "营销", "文案写作"


def _store(tmp_path) -> Store:
    store = Store(tmp_path)
    store.ensure_layout()
    return store


def _session(store, agent, sid, started, req=5, corr=1):
    store.record_session({
        "agent": agent, "session_id": sid, "trunk": TRUNK, "category": CAT,
        "req_count": req, "correction_hits": corr,
        "started_at": started, "ended_at": started,
    })


# ---------- affinity 按 agent 拆分 ----------

def test_affinity_split_by_agent(tmp_path):
    """同 trunk/category，两个 agent → 两个独立 affinity 桶（不混合）。"""
    store = _store(tmp_path)
    for i in range(3):
        _session(store, "workbuddy", f"wb{i}", f"2026-08-{20 + i}T08:00:00Z",
                 req=10 - i, corr=3 - i)
        _session(store, "codex", f"cx{i}", f"2026-08-{20 + i}T09:00:00Z",
                 req=10 - i, corr=3 - i)
    aff = store.growth_summary(days=60)["affinity"]
    # 两个 agent 各一桶，键含 agent
    assert "workbuddy/营销/文案写作" in aff
    assert "codex/营销/文案写作" in aff
    # 没有全局混合桶（拆分而非合并）
    assert "营销/文案写作" not in aff
    # 每桶各自 3 个独立实例
    assert aff["workbuddy/营销/文案写作"]["n"] == 3
    assert aff["codex/营销/文案写作"]["n"] == 3


def test_affinity_missing_agent_unknown_bucket(tmp_path):
    """agent 缺失 → unknown 桶（不崩、不并入别的 agent）。"""
    store = _store(tmp_path)
    store.record_session({
        "session_id": "s1", "trunk": TRUNK, "category": CAT,
        "req_count": 5, "correction_hits": 1,
        "started_at": "2026-08-20T08:00:00Z",
    })
    aff = store.growth_summary(days=60)["affinity"]
    assert "unknown/营销/文案写作" in aff
    assert aff["unknown/营销/文案写作"]["n"] == 1


# ---------- affinity_display 展示口径 ----------

def test_affinity_display():
    assert affinity_display("workbuddy/营销/文案写作") == "workbuddy · 文案写作"
    assert affinity_display("unknown/营销/文案写作") == "文案写作"
    assert affinity_display("营销/文案写作") == "文案写作"  # 2 段兜底
    assert affinity_display("claude-code/工程/修服务") == "claude-code · 修服务"


# ---------- iter_experiences(agent=) 过滤 ----------

def test_iter_experiences_agent_filter(tmp_path):
    """iter_experiences(agent=) 按来源 agent 过滤（经验列表筛选的数据层支撑）。"""
    store = _store(tmp_path)
    store.append_experience({"task": "t1", "action": "a", "G": 0.8,
                             "agent": "workbuddy", "trunk": TRUNK,
                             "category": CAT, "ts": "2026-09-01T08:00:00Z"})
    store.append_experience({"task": "t2", "action": "a", "G": 0.8,
                             "agent": "codex", "trunk": TRUNK,
                             "category": CAT, "ts": "2026-09-01T09:00:00Z"})
    assert len(list(store.iter_experiences(include_distilled=True))) == 2
    wb = list(store.iter_experiences(agent="workbuddy", include_distilled=True))
    assert len(wb) == 1 and wb[0]["task"] == "t1"
    cx = list(store.iter_experiences(agent="codex", include_distilled=True))
    assert len(cx) == 1 and cx[0]["task"] == "t2"
    # 不存在的 agent → 空
    assert list(store.iter_experiences(agent="cursor", include_distilled=True)) == []


# ---------- growth_edges 键格式迁移 ----------

def test_growth_edges_migration_no_false_edges(tmp_path):
    """键格式迁移（2 段→3 段）：旧基线存在时首轮只落新基线、不推沿（防误报新高）。"""
    store = _store(tmp_path)
    # 模拟迁移前的旧基线（2 段键，含中档）
    cfg = store.load_config()
    cfg["notify_state"] = {"growth_levels": {"营销/文案写作": "中"}}
    store.save_config(cfg)
    aff = {"workbuddy/营销/文案写作": {"level": "中"}}
    # 迁移轮：不推沿
    assert notify.growth_edges(store, aff) == []
    # 新基线已落 + 迁移哨兵
    st = store.load_config()["notify_state"]["growth_levels"]
    assert "workbuddy/营销/文案写作" in st
    assert notify._GROWTH_MIGRATED in st
    # 次轮（档没变）：不推沿
    assert notify.growth_edges(store, aff) == []
    # 升到高档：正常推沿
    assert notify.growth_edges(store, {"workbuddy/营销/文案写作": {"level": "高"}}) \
        == [("workbuddy/营销/文案写作", "中", "高")]


def test_growth_edges_fresh_no_migration(tmp_path):
    """全新安装（无旧基线）：不误触迁移，首轮中/高正常推沿。"""
    store = _store(tmp_path)
    aff = {"workbuddy/营销/文案写作": {"level": "中"}}
    assert notify.growth_edges(store, aff) \
        == [("workbuddy/营销/文案写作", "待积累", "中")]
