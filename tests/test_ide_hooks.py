"""Cursor / Windsurf hooks.json 注入测试（总方案 S3b）。"""

import json

import pytest

from app.capture import ide_hooks as ih
from app.store.store import Store


@pytest.fixture
def store(tmp_path):
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


def test_cursor_apply_idempotent_and_preserves_others(tmp_path):
    path = tmp_path / "hooks.json"
    # 用户已有自己的 hook（须保留）
    path.write_text(json.dumps({
        "version": 1,
        "hooks": {"stop": [{"command": "echo user-hook", "type": "command"}]},
    }), encoding="utf-8")
    r = ih.apply_config("cursor", path)
    assert r["ok"] is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert set(data["hooks"]) >= {"sessionStart", "afterAgentResponse", "stop"}
    # 用户已有条目保留
    assert any("echo user-hook" in str(x.get("command"))
               for x in data["hooks"]["stop"])
    # 我们条目含 8101 marker
    ours = [x for x in data["hooks"]["afterAgentResponse"]]
    assert any(ih._ours_in(x, "cursor-event") for x in ours)
    # 幂等：重跑不重复
    ih.apply_config("cursor", path)
    data2 = json.loads(path.read_text(encoding="utf-8"))
    n_after = len(data2["hooks"]["afterAgentResponse"])
    assert n_after == len([x for x in data["hooks"]["afterAgentResponse"]])
    assert ih.config_status("cursor", path)["installed"] is True


def test_cursor_remove_only_ours(tmp_path):
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps({
        "version": 1,
        "hooks": {
            "stop": [{"command": "echo user", "type": "command"},
                     {"command": "curl 127.0.0.1:8101/api/hooks/cursor-event", "type": "command"}],
            "afterAgentResponse": [{"command": "curl 127.0.0.1:8101/api/hooks/cursor-event",
                                    "type": "command"}],
        },
    }), encoding="utf-8")
    r = ih.remove_config("cursor", path)
    assert r["removed"] is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hooks"] == {"stop": [{"command": "echo user", "type": "command"}]}
    assert ih.config_status("cursor", path)["installed"] is False


def test_windsurf_apply_remove(tmp_path):
    path = tmp_path / "windsurf" / "hooks.json"
    ih.apply_config("windsurf", path)
    data = json.loads(path.read_text(encoding="utf-8"))
    # Windsurf 独立 hooks.json：无顶层 version
    assert "version" not in data
    ev = data["hooks"]["post_cascade_response_with_transcript"]
    assert len(ev) == 1 and ih._ours_in(ev[0], "windsurf-event")
    assert ev[0]["show_output"] is False
    assert ih.config_status("windsurf", path)["installed"] is True
    ih.remove_config("windsurf", path)
    data2 = json.loads(path.read_text(encoding="utf-8"))
    assert data2 == {} or "hooks" not in data2


def test_handle_ide_event_observed(store):
    assert ih.handle_ide_event(store, "cursor",
                               {"hook_event_name": "afterAgentResponse",
                                "conversation_id": "c1"}) == {}
    assert "cursor:afterAgentResponse" in store.load_hook_observed()
    assert ih.handle_ide_event(store, "windsurf",
                               {"agent_action_name":
                                "post_cascade_response_with_transcript"}) == {}
    assert "windsurf:post_cascade_response_with_transcript" in store.load_hook_observed()


def test_local_api_ide_endpoints(store):
    from fastapi.testclient import TestClient

    from app.local_api import create_local_app

    client = TestClient(create_local_app(store))
    assert client.post("/api/hooks/cursor-event",
                       json={"hook_event_name": "stop"}).status_code == 200
    assert client.post("/api/hooks/windsurf-event",
                       json={"agent_action_name": "post_cascade_response_with_transcript"}
                       ).status_code == 200
    obs = store.load_hook_observed()
    assert "cursor:stop" in obs
    assert "windsurf:post_cascade_response_with_transcript" in obs
