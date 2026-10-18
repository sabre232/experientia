"""蒸馏路由测试：distill_model 选择（本地/云端/Anthropic）+ CLI model 子命令。"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.distill import llm
from app.store.store import Store


def _store(tmp_path, config) -> Store:
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_config(config)
    return store


# ---------- distill_route 选择逻辑 ----------

def test_distill_route_none_without_models(tmp_path):
    store = _store(tmp_path, {})
    assert llm.distill_route(store) is None


def test_distill_route_falls_back_to_first(tmp_path):
    store = _store(tmp_path, {"models": {"a": {"endpoint": "http://a"}}})
    assert llm.distill_route(store)["route_name"] == "a"


def test_distill_route_default_model(tmp_path):
    store = _store(tmp_path, {"models": {"a": {"endpoint": "http://a"},
                                        "b": {"endpoint": "http://b"}},
                              "default_model": "b"})
    assert llm.distill_route(store)["route_name"] == "b"


def test_distill_route_distill_model_wins(tmp_path):
    store = _store(tmp_path, {"models": {"local": {"endpoint": "http://l"},
                                        "cloud": {"endpoint": "http://c"}},
                              "default_model": "local", "distill_model": "cloud"})
    assert llm.distill_route(store)["route_name"] == "cloud"


def test_distill_route_invalid_distill_falls_back(tmp_path):
    store = _store(tmp_path, {"models": {"local": {"endpoint": "http://l"}},
                              "default_model": "local", "distill_model": "ghost"})
    assert llm.distill_route(store)["route_name"] == "local"


def test_distill_route_explicit_override(tmp_path):
    store = _store(tmp_path, {"models": {"a": {"endpoint": "http://a"},
                                        "b": {"endpoint": "http://b"},
                                        "c": {"endpoint": "http://c"}},
                              "default_model": "a", "distill_model": "b"})
    assert llm.distill_route(store, route_name="c")["route_name"] == "c"


# ---------- 协议分支（本地 mock 上游） ----------

class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.last_request = {"path": self.path,
                                    "headers": {k.lower(): v for k, v in self.headers.items()},
                                    "body": body}
        if self.path.endswith("/messages"):
            resp = {"id": "x", "type": "message", "role": "assistant",
                    "content": [{"type": "text", "text": "anthropic-ok"}],
                    "stop_reason": "end_turn"}
        else:
            resp = {"choices": [{"message": {"role": "assistant", "content": "openai-ok"}}]}
        data = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def mock_upstream():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.last_request = None
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", server
    server.shutdown()


def test_call_model_anthropic_branch(tmp_path, mock_upstream):
    base, server = mock_upstream
    store = _store(tmp_path, {
        "models": {"cloud": {"type": "cloud", "endpoint": base + "/v1", "model": "gpt"},
                   "ant": {"type": "anthropic", "endpoint": base, "model": "claude",
                           "api_key": "sk-test"}},
        "default_model": "cloud", "distill_model": "ant",
    })
    out = llm.call_model(store, [{"role": "system", "content": "sys"},
                                 {"role": "user", "content": "hi"}])
    assert out == "anthropic-ok"
    req = server.last_request
    assert req["path"].endswith("/v1/messages")
    assert req["headers"].get("anthropic-version") == llm.ANTHROPIC_VERSION
    assert req["headers"].get("x-api-key") == "sk-test"
    assert "authorization" not in req["headers"]
    assert req["body"]["system"] == "sys"
    assert req["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert req["body"]["max_tokens"]


def test_call_model_openai_branch_unchanged(tmp_path, mock_upstream):
    base, server = mock_upstream
    store = _store(tmp_path, {
        "models": {"cloud": {"type": "cloud", "endpoint": base + "/v1", "model": "gpt"}},
        "default_model": "cloud",
    })
    out = llm.call_model(store, [{"role": "user", "content": "hi"}])
    assert out == "openai-ok"
    req = server.last_request
    assert req["path"].endswith("/v1/chat/completions")
    assert req["body"]["model"] == "gpt"


def test_explicit_route_name_overrides_distill_model(tmp_path, mock_upstream):
    base, server = mock_upstream
    store = _store(tmp_path, {
        "models": {"cloud": {"type": "cloud", "endpoint": base + "/v1", "model": "gpt"},
                   "ant": {"type": "anthropic", "endpoint": base, "model": "claude"}},
        "default_model": "cloud", "distill_model": "ant",
    })
    out = llm.call_model(store, [{"role": "user", "content": "hi"}], route_name="cloud")
    assert out == "openai-ok"
    assert server.last_request["path"].endswith("/chat/completions")


def test_call_model_unconfigured_raises(tmp_path):
    store = _store(tmp_path, {})
    with pytest.raises(RuntimeError, match="未配置模型"):
        llm.call_model(store, [{"role": "user", "content": "hi"}])


# ---------- CLI model 子命令 ----------

@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPERIENTIA_HOME", str(tmp_path / "home"))
    keys: dict[str, str] = {}
    import keyring

    monkeypatch.setattr(keyring, "set_password", lambda svc, name, pw: keys.update({name: pw}))
    monkeypatch.setattr(keyring, "get_password", lambda svc, name: keys.get(name))
    def _del(svc, name):
        keys.pop(name, None)

    monkeypatch.setattr(keyring, "delete_password", _del)
    return tmp_path


def test_cli_model_add_set_list_rm(cli_env, monkeypatch):
    from app import cli

    rc = cli.main(["model", "add", "local-8b", "--endpoint", "http://127.0.0.1:8080/v1",
                   "--model", "Qwen3-8B", "--type", "local"])
    assert rc == 0
    rc = cli.main(["model", "add", "gpt", "--endpoint", "https://api.openai.com/v1",
                   "--model", "gpt-4o", "--key", "sk-cli-test"])
    assert rc == 0
    rc = cli.main(["model", "set-default", "local-8b"])
    assert rc == 0
    rc = cli.main(["model", "set-distill", "gpt"])
    assert rc == 0

    import keyring
    assert keyring.get_password("experientia", "gpt") == "sk-cli-test"
    assert keyring.get_password("experientia", "local-8b") is None

    config = Store().load_config()
    assert config["default_model"] == "local-8b"
    assert config["distill_model"] == "gpt"
    assert "key_ref" in config["models"]["gpt"] and "api_key" not in config["models"]["gpt"]

    # 蒸馏路由确实走 gpt
    assert llm.distill_route(Store())["route_name"] == "gpt"

    rc = cli.main(["model", "rm", "gpt"])
    assert rc == 0
    config = Store().load_config()
    assert "gpt" not in config["models"] and config.get("distill_model") is None
    assert keyring.get_password("experientia", "gpt") is None


def test_cli_model_error_paths(cli_env):
    from app import cli

    assert cli.main(["model", "set-distill", "ghost"]) == 1
    assert cli.main(["model", "add", "x", "--endpoint", "http://e", "--model", "m"]) == 0
    assert cli.main(["model", "add", "x", "--endpoint", "http://e", "--model", "m"]) == 1
    assert cli.main(["model", "rm", "ghost"]) == 1


def test_cli_model_add_keyring_failure_falls_back_securely(tmp_path, monkeypatch):
    """M12/低6：keyring 失败 → key 兜底落 config 且读回永远是原值；
    Windows 走 DPAPI 加密（落盘不见明文），POSIX 走明文（0600 有效）。"""
    from app import cli, token_util
    from app import models_service as models

    monkeypatch.setenv("EXPERIENTIA_HOME", str(tmp_path / "home"))
    import keyring

    def _boom(svc, name, pw):
        raise RuntimeError("credential manager unavailable")

    monkeypatch.setattr(keyring, "set_password", _boom)

    rc = cli.main(["model", "add", "gpt", "--endpoint", "https://api.openai.com/v1",
                   "--model", "gpt-4o", "--key", "sk-fallback"])
    assert rc == 0
    store = Store()
    route = store.load_config()["models"]["gpt"]
    assert "key_ref" not in route
    # 不论哪种兜底，读回永远是原始 key
    assert token_util.resolve_fallback_secret(route) == "sk-fallback"
    src = models.list_routes(store)["routes"][0]["key_source"]
    if token_util._IS_WINDOWS:
        # 兜底落盘不得是明文：DPAPI 密文、且明文串不出现在字段值里
        assert route.get("api_key") is None
        assert route.get("api_key_enc") and "sk-fallback" not in route["api_key_enc"]
        assert src == "encrypted"
    else:
        assert route.get("api_key") == "sk-fallback"
        assert src == "plaintext"
