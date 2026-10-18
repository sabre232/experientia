"""Hermes 铃响 hook（总方案 S3）测试：写入/卸载/事件处理。"""

import importlib.util
import sys

import pytest

from app.capture import hermes_hook as hh
from app.store.store import Store


@pytest.fixture
def home(tmp_path):
    return tmp_path / "hermes"


def test_write_status_remove_idempotent(home):
    assert hh.hook_status(home)["installed"] is False
    d = hh.write_hook(home)
    assert d.name == hh.HOOK_NAME
    assert (d / "HOOK.yaml").is_file() and (d / "handler.py").is_file()
    # 幂等重写
    hh.write_hook(home)
    yaml_text = (d / "HOOK.yaml").read_text(encoding="utf-8")
    for ev in hh.EVENTS:
        assert ev in yaml_text
    assert hh.hook_status(home)["installed"] is True
    # 卸载
    assert hh.remove_hook(home) is True
    assert not d.exists()
    assert hh.hook_status(home)["installed"] is False


def _load_handler(d):
    """从生成目录加载 handler.py 模块。"""
    path = d / "handler.py"
    spec = importlib.util.spec_from_file_location("_exp_hook_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_handler_syntax_and_events_only(home):
    d = hh.write_hook(home)
    mod = _load_handler(d)
    try:
        fired = []
        mod._post = lambda url, payload: fired.append((url, payload))
        # agent:end → 触发；未在 EVENTS 的事件 → 不触发
        mod.handle("agent:end", {"session_id": "s1", "platform": "telegram"})
        mod.handle("agent:start", {"session_id": "s2"})
        assert len(fired) == 1
        url, payload = fired[0]
        assert url == hh.HOOK_URL
        assert payload["event"] == "agent:end" and payload["session_id"] == "s1"
    finally:
        sys.modules.pop("_exp_hook_test", None)


def test_handler_py_url_with_percent():
    """URL 含 % 时生成不炸、URL 原样落进 handler（
    原 % 格式化遇 URL 里的 % 抛 ValueError，写 hook 整个失败）。"""
    url = "http://127.0.0.1:8101/api/hooks/hermes-event?key=a%20b"
    text = hh._handler_py(url)
    compile(text, "<handler>", "exec")  # 生成的 handler 仍是合法 Python
    assert url in text
    assert "%%s" not in text  # 不走 % 格式化了，不再需要 %% 转义


def test_handle_hermes_event_records_observed_and_fail_open(tmp_path):
    store = Store(tmp_path / "data")
    store.ensure_layout()
    assert hh.handle_hermes_event(store, {"event": "agent:end", "session_id": "s9"}) == {}
    observed = store.load_hook_observed()
    assert "hermes:agent:end" in observed
    # 异常也不抛（fail-open）
    assert hh.handle_hermes_event(store, None) == {}


def test_local_api_hermes_hook_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from app.local_api import create_local_app

    store = Store(tmp_path / "data")
    store.ensure_layout()
    client = TestClient(create_local_app(store))
    r = client.post("/api/hooks/hermes-event",
                    json={"event": "agent:end", "session_id": "abc123"})
    assert r.status_code == 200
    assert "hermes:agent:end" in store.load_hook_observed()
