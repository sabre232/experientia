"""代理 OpenAI 兼容 /v1/models（B-2：OpenCode/LM Studio 探测模型用）。

不真连模型；只验证列表形状与「配置路由 → 模型 id」映射。
"""

from fastapi.testclient import TestClient

from app.proxy import server
from app.store.store import Store
from tests.conftest import PROXY_AUTH_HEADERS


def _store(tmp_path):
    s = Store(data_dir=tmp_path / "data")
    s.ensure_layout()
    return s


def _client(store):
    c = TestClient(server.create_app(store))
    # 代理默认鉴权——同源 token（测试会话由 conftest 钉死）
    c.headers.update(PROXY_AUTH_HEADERS)
    return c


def test_v1_models_empty_when_no_routes(tmp_path):
    with _client(_store(tmp_path)) as c:
        r = c.get("/v1/models")
    assert r.status_code == 200
    assert r.json() == {"object": "list", "data": []}


def test_v1_models_lists_configured_routes(tmp_path):
    s = _store(tmp_path)
    s.save_config({
        "models": {
            "gpt": {"type": "cloud", "endpoint": "http://up/v1",
                    "model": "gpt-4o"},
            "local-8b": {"type": "local", "endpoint": "http://l",
                          "model": "qwen3-coder:27b"},
        },
        "default_model": "gpt",
    })
    with _client(s) as c:
        payload = c.get("/v1/models").json()
    ids = [m["id"] for m in payload["data"]]
    owners = [m["owned_by"] for m in payload["data"]]
    assert ids == ["gpt-4o", "qwen3-coder:27b"]
    assert owners == ["gpt", "local-8b"]


def test_v1_models_route_name_as_id_when_no_model(tmp_path):
    s = _store(tmp_path)
    s.save_config({"models": {"gpt": {"type": "cloud",
                                      "endpoint": "http://up/v1"}}})
    with _client(s) as c:
        payload = c.get("/v1/models").json()
    assert payload["data"][0]["id"] == "gpt"


# ---------- ：8100 默认鉴权护栏 ----------

def test_default_auth_enforced_same_origin_token(tmp_path):
    """未配 proxy_token → 复用 8101 同源 token；无头/坏头 401，/health 豁免。"""
    app = server.create_app(_store(tmp_path))
    with TestClient(app) as c:
        assert c.get("/v1/models").status_code == 401          # 裸请求拒
        assert c.get("/v1/models", headers={"Authorization": "Bearer wrong"}
                     ).status_code == 401
        assert c.get("/health").status_code == 200             # 健康豁免
    assert app.state.proxy_token  # env 钉死后 = 测试 token
    with TestClient(app) as c:
        c.headers.update(PROXY_AUTH_HEADERS)
        assert c.get("/v1/models").status_code == 200


def test_x_api_key_header_accepted(tmp_path):
    """Anthropic 系客户端（Claude Code）走 x-api-key 原值，同样放行。"""
    from tests.conftest import TEST_API_TOKEN
    with _client(_store(tmp_path)) as c:
        c.headers.pop("Authorization", None)
        assert c.get("/v1/models",
                     headers={"x-api-key": TEST_API_TOKEN}
                     ).status_code == 200
        assert c.get("/v1/models", headers={"x-api-key": "nope"}
                     ).status_code == 401


def test_explicit_proxy_token_overrides_default(tmp_path):
    """config.proxy_token 显式配置 = 唯一覆盖通道（老部署兼容），同源 token 失效。"""
    s = _store(tmp_path)
    s.save_config({"proxy_token": "custom-pt"})
    with TestClient(server.create_app(s)) as c:
        assert c.get("/v1/models",
                     headers=PROXY_AUTH_HEADERS).status_code == 401  # 同源被覆盖
        assert c.get("/v1/models",
                     headers={"Authorization": "Bearer custom-pt"}
                     ).status_code == 200
