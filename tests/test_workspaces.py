"""E-1：workspace↔session 索引（数据层聚合 + 本地 API）。

session 记录的 project（cwd）字段是事实源；list_workspaces 只读聚合，
不新增写路径。缓存失效 = 源文件签名变化（与 growth_summary 同口径）。
"""

from app.store.store import Store
from conftest import local_api_client


def _store(tmp_path) -> Store:
    s = Store(data_dir=tmp_path / "data")
    s.ensure_layout()
    return s


def _rec(session_id: str, project: str, trunk: str = "其他",
         category: str = "未分类", ts: str = "2026-09-01T00:00:00Z") -> dict:
    return {"agent": "claude-code", "session_id": session_id, "project": project,
            "trunk": trunk, "category": category, "started_at": ts}


def test_list_workspaces_aggregates_and_sorts(tmp_path):
    s = _store(tmp_path)
    s.record_session(_rec("a", "/work/x", trunk="公文", category="起草",
                          ts="2026-09-01T01:00:00Z"))
    s.record_session(_rec("b", "/work/x", trunk="公文", category="起草",
                          ts="2026-09-02T01:00:00Z"))
    s.record_session(_rec("c", "/work/y", trunk="工程", category="后端"))
    ws = s.list_workspaces()
    assert [w["project"] for w in ws] == ["/work/x", "/work/y"]  # 最近活跃在前
    by = {w["project"]: w for w in ws}
    assert by["/work/x"]["count"] == 2
    assert by["/work/x"]["agents"] == ["claude-code"]
    assert by["/work/x"]["trunks"] == ["公文"]
    assert by["/work/y"]["count"] == 1


def test_workspace_cache_invalidates_on_new_session(tmp_path):
    s = _store(tmp_path)
    assert s.list_workspaces() == []
    s.record_session(_rec("a", "/work/z"))
    assert len(s.list_workspaces()) == 1  # 源文件变化 → 重算
    s.record_session(_rec("b", "/work/z2"))
    assert len(s.list_workspaces()) == 2


def test_api_workspaces_returns_items(tmp_path):
    s = _store(tmp_path)
    s.record_session(_rec("a", "/work/x", trunk="工程", category="前端"))
    client = local_api_client(s)
    r = client.get("/api/workspaces")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["project"] == "/work/x"
