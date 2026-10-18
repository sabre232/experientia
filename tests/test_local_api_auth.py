"""8101 本地 API 鉴权（H-5）：全端点 Bearer token + 豁免项 + token 生命周期。

本机任意进程可访问 127.0.0.1:8101——wipe/config/autostart 等写端点无鉴权
即任何本地进程可清空数据。token 走 keyring（生产随机值），测试用固定值。
"""

import pytest
from fastapi.testclient import TestClient

from app import token_util
from app.local_api import create_local_app, ensure_api_token
from app.store.store import Store
from conftest import TEST_API_TOKEN


@pytest.fixture(autouse=True)
def _no_token_env(monkeypatch):
    """conftest 全局钉死 EXPERIENTIA_API_TOKEN（H4：代理默认复用同源），
    本模块的 ensure_api_token 生成链路（keyring/文件）测试必须先摘掉它。"""
    monkeypatch.delenv(token_util.TOKEN_ENV, raising=False)


def _store(tmp_path) -> Store:
    store = Store(tmp_path)
    store.ensure_layout()
    return store


def test_protected_endpoint_requires_token(tmp_path):
    client = TestClient(create_local_app(_store(tmp_path), api_token=TEST_API_TOKEN))
    assert client.get("/api/models").status_code == 401  # 无 token
    assert client.get("/api/models",
                      headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/models",
                      headers={"Authorization": f"Bearer {TEST_API_TOKEN}"}).status_code == 200


def test_exempt_endpoints_open(tmp_path):
    """status（GUI 首连/健康探测）+ hooks 通道（外部 agent curl，fail-open 语义）豁免。"""
    client = TestClient(create_local_app(_store(tmp_path), api_token=TEST_API_TOKEN))
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/hooks/config").status_code == 200
    assert client.post("/api/hooks/session-start", json={}).status_code == 200


def test_hooks_data_channel_endpoints_exempt(tmp_path):
    """hooks 数据通道（agent curl 事件上报）逐端点豁免（H3 白名单口径）。"""
    client = TestClient(create_local_app(_store(tmp_path), api_token=TEST_API_TOKEN))
    for path in ("/api/hooks/user-prompt-submit", "/api/hooks/post-tool-use",
                 "/api/hooks/stop", "/api/hooks/hermes-event",
                 "/api/hooks/cursor-event", "/api/hooks/windsurf-event"):
        # 事件端点无 token 时不得 401（fail-open；400/200 取决于载荷校验）
        assert client.post(path, json={}).status_code != 401, path


def test_hooks_admin_write_requires_token(tmp_path):
    """admin/apply/remove/plugin-generate 等写端点必须 token 保护。

    /api/hooks/ 前缀整体豁免曾把 hook 管理面暴露为无鉴权——本机任意进程可
    向第三方工具 hook 配置写入任意命令。
    """
    client = TestClient(create_local_app(_store(tmp_path), api_token=TEST_API_TOKEN))
    protected = [
        ("get", "/api/hooks/admin/overview"),
        ("post", "/api/hooks/admin/install"),
        ("post", "/api/hooks/admin/install-all"),
        ("post", "/api/hooks/admin/remove-all"),
        ("post", "/api/hooks/admin/delete"),
        ("post", "/api/hooks/admin/toggle"),
        ("post", "/api/hooks/admin/edit"),
        ("post", "/api/hooks/admin/add"),
        ("post", "/api/hooks/apply"),
        ("post", "/api/hooks/remove"),
        ("post", "/api/hooks/plugin/generate"),
    ]
    for method, path in protected:
        resp = client.request(method.upper(), path, json={})
        assert resp.status_code == 401, f"{method.upper()} {path} 未受 token 保护"


def test_ensure_api_token_idempotent_keyring(tmp_path, monkeypatch):
    """keyring 优先 + 幂等——引擎与 GUI 两次 ensure 取到同一值。"""
    import keyring

    saved: dict = {}
    monkeypatch.setattr(keyring, "set_password",
                        lambda s, n, pw: saved.setdefault((s, n), pw))
    monkeypatch.setattr(keyring, "get_password", lambda s, n: saved.get((s, n)))
    t1 = ensure_api_token(tmp_path)
    t2 = ensure_api_token(tmp_path)
    assert t1 == t2
    assert len(t1) >= 32  # 随机 token，不是固定口令


def test_ensure_api_token_file_fallback(tmp_path, monkeypatch):
    """keyring 不可用（headless 无桌面会话）→ 数据目录文件兜底，二次读取同值。

    Windows 走 DPAPI 加密 local_api_token.bin（明文 0600
    在 Windows 无效）；POSIX 维持明文 local_api_token + chmod 0600。"""
    import sys

    import keyring

    def boom(*a, **k):
        raise RuntimeError("no keyring backend")

    monkeypatch.setattr(keyring, "set_password", boom)
    monkeypatch.setattr(keyring, "get_password", boom)
    t1 = ensure_api_token(tmp_path)
    t2 = ensure_api_token(tmp_path)
    assert t1 == t2
    if sys.platform == "win32":
        f = tmp_path / "local_api_token.bin"
        assert f.exists()
        assert f.read_bytes().startswith(b"EXPTOKEN1")  # DPAPI 新格式 + magic 头
        assert not (tmp_path / "local_api_token").exists()
    else:
        f = tmp_path / "local_api_token"
        assert f.exists()
        assert f.read_text(encoding="utf-8").strip() == t1


# ---------- ：速率限制按通道隔离 ----------
# 假时钟：限流数的是时间窗，真表在连发期间会走——机器一忙
# 121 次请求跨过窗口边界，"第 121 次必 429"偶发假红。clock 注入后整段
# 测试钉在同一秒内，跨窗行为改为显式拨表验证（顺带补上"窗口滚动清零"断言）。

class _FrozenClock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_hook_channel_rate_limit_isolated_with_retry_after(tmp_path):
    """hook 数据通道独立配额 120 req/s（不与 GUI 共享 30），429 带 Retry-After
    ——此前 hook 与 GUI 共享配额，GUI 密集轮询会把 hook 事件挤到 429，
    fail-open 语义失效。"""
    clock = _FrozenClock()
    client = TestClient(create_local_app(_store(tmp_path),
                                         api_token=TEST_API_TOKEN, clock=clock))
    path = "/api/hooks/post-tool-use"
    statuses = [client.post(path, json={}).status_code for _ in range(121)]
    # 前 120 次全部放行（fail-open 通道不被限流掐断）
    assert all(s == 200 for s in statuses[:120])
    assert statuses[120] == 429
    resp = client.post(path, json={})
    assert resp.status_code == 429
    assert resp.headers.get("retry-after") == "1"
    # Retry-After=1 的语义兑现：拨表过 1s，配额清零重新放行
    clock.advance(1.1)
    assert client.post(path, json={}).status_code == 200


def test_other_paths_keep_30_per_second_no_retry_after(tmp_path):
    """其余路径（GUI 用）维持 30 req/s；429 不带 Retry-After（原语义）。"""
    clock = _FrozenClock()
    client = TestClient(create_local_app(_store(tmp_path),
                                         api_token=TEST_API_TOKEN, clock=clock))
    statuses = [client.get("/api/status", params={"lite": 1}).status_code
                for _ in range(31)]
    assert all(s == 200 for s in statuses[:30])
    resp = client.get("/api/status", params={"lite": 1})
    assert resp.status_code == 429
    assert "retry-after" not in {k.lower() for k in resp.headers}


def test_hook_quota_does_not_consume_gui_quota(tmp_path):
    """通道隔离：hook 通道打满不影响 GUI 路径自己的配额（反之亦然）。"""
    clock = _FrozenClock()
    client = TestClient(create_local_app(_store(tmp_path),
                                         api_token=TEST_API_TOKEN, clock=clock))
    for _ in range(121):
        client.post("/api/hooks/post-tool-use", json={})
    # hook 通道已 429，GUI 路径仍可正常放行（各自独立计数）
    assert client.get("/api/status", params={"lite": 1}).status_code == 200
