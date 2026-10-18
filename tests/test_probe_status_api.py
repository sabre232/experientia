"""probe 状态 + 注入端点 API 测试（总方案 S2/S3，隔离真实用户目录）。"""

from fastapi.testclient import TestClient

from app.capture import ide_hooks as ide_ch
from app.local_api import create_local_app
from app.store.store import Store
from conftest import TEST_API_TOKEN


def _client(tmp_path, monkeypatch):
    store = Store(tmp_path / "data")
    store.ensure_layout()
    # 隔离：注入写用户级路径一律重定向到临时目录
    tmp_ide = tmp_path / "ide"
    monkeypatch.setitem(ide_ch.IDES["cursor"], "user_path", tmp_ide / "cursor.json")
    monkeypatch.setitem(ide_ch.IDES["windsurf"], "user_path", tmp_ide / "windsurf.json")
    hermes_home = tmp_path / "hermes"
    monkeypatch.setattr("app.capture.hermes_hook.hermes_home", lambda: hermes_home)
    client = TestClient(create_local_app(store, api_token=TEST_API_TOKEN))
    return client, store, hermes_home


def test_status_shape(tmp_path, monkeypatch):
    client, store, _ = _client(tmp_path, monkeypatch)
    auth = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
    r = client.get("/api/probe/status", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"self_reported", "ide_hooks", "hermes_hook",
                         "draft_pending"}
    assert set(data["ide_hooks"]) == {"cursor", "windsurf"}
    assert data["draft_pending"] == 0


def test_apply_needs_token_and_works(tmp_path, monkeypatch):
    client, store, _ = _client(tmp_path, monkeypatch)
    # 无 token → 401（写端点保持保护）
    assert client.post("/api/probe/ide/apply",
                       json={"agent": "cursor"}).status_code == 401
    auth = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
    r = client.post("/api/probe/ide/apply", json={"agent": "cursor"}, headers=auth)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert client.get("/api/probe/status", headers=auth).json()["ide_hooks"]["cursor"]["installed"]
    # 移除
    r = client.post("/api/probe/ide/remove", json={"agent": "cursor"}, headers=auth)
    assert r.json()["removed"] is True
    assert not client.get("/api/probe/status",
                          headers=auth).json()["ide_hooks"]["cursor"]["installed"]


def test_hermes_apply_through_api(tmp_path, monkeypatch):
    client, store, hermes_home = _client(tmp_path, monkeypatch)
    auth = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
    r = client.post("/api/probe/hermes/apply", headers=auth)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert (hermes_home / "hooks" / "experientia-event" / "HOOK.yaml").is_file()
    r = client.post("/api/probe/hermes/remove", headers=auth)
    assert r.json()["ok"] is True and r.json()["removed"] is True
