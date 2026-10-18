"""回环请求绕过系统代理的收口契约（`app/net_util.py`）。

背景：本机设了系统代理（`HTTP_PROXY`），httpx 默认 `trust_env=True` 会把回环请求
也送进代理——请求行被改写成绝对 URI，代理回 404。产品侧表现是"第一次正常、第二次
404"，测试侧表现是"本机绿、别人机器红"。

统一做法是 `httpx.Client(mounts=DIRECT_LOOPBACK)`；云端端点不在 pattern 里，仍然
尊重用户配的代理。
"""

from pathlib import Path

import httpx
import pytest

from app.net_util import DIRECT_LOOPBACK

ROOT = Path(__file__).resolve().parent.parent


def test_top_level_api_rejects_mounts():
    """`httpx.get/post()` 顶层 API 不接受 mounts（传了直接 TypeError）。

    踩过：给 `daemon._proxy_alive` 加 `httpx.get(url, mounts=DIRECT_LOOPBACK)`，
    探活直接抛 TypeError、被 except 吞掉 → 探活恒假。只有 Client/AsyncClient
    的构造函数认 mounts。
    """
    with pytest.raises(TypeError):
        httpx.get("http://127.0.0.1:1/", mounts=DIRECT_LOOPBACK)
    with pytest.raises(TypeError):
        httpx.post("http://127.0.0.1:1/", mounts=DIRECT_LOOPBACK)


def test_loopback_bypasses_env_proxy(monkeypatch):
    """行为验证：开着系统代理时，加了 mounts 的回环请求仍能成功；不带的被劫持。

    这是 `daemon._proxy_alive` 的真实故障形态——开着代理的机器上探活恒假，
    代理挂了也拉不起来（崩溃自恢复永不触发）。
    """
    import http.server
    import threading
    import time

    class _Ok(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *a):
            pass

    class _Proxy(http.server.BaseHTTPRequestHandler):
        def do_GET(self):          # 模拟代理对回环请求的应答
            self.send_response(404)
            self.end_headers()

        def do_CONNECT(self):
            self.send_response(502)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Ok)
    proxy = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Proxy)
    port, pport = srv.server_address[1], proxy.server_address[1]
    for s in (srv, proxy):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    time.sleep(0.3)
    url = f"http://127.0.0.1:{port}/health"
    for var in ("HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(var, f"http://127.0.0.1:{pport}")
    # conftest 的 _no_env_proxy 设了 NO_PROXY=*（整会话免代理），对照组要摘掉它
    # 才能还原"没加 mounts"的真实处境。
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    try:
        with httpx.Client(mounts=DIRECT_LOOPBACK, timeout=2) as cli:
            assert cli.get(url).status_code == 200
        # 对照：裸 Client 吃代理 → 拿不到 200
        with httpx.Client(timeout=2) as cli:
            assert cli.get(url).status_code != 200
    finally:
        srv.shutdown()
        proxy.shutdown()


def test_loopback_clients_used_in_write_paths():
    """收口守卫：业务层的裸 httpx 顶层调用不得带 mounts（那是无效写法）。

    允许 `httpx.Client(mounts=...)` / `httpx.AsyncClient(mounts=...)`；
    禁止 `httpx.get(..., mounts=...)` 这类。
    """
    offenders: list[str] = []
    for base in (ROOT / "app", ROOT / "daemon.py"):
        paths = base.rglob("*.py") if base.is_dir() else [base]
        for py in paths:
            for i, line in enumerate(
                    py.read_text(encoding="utf-8").splitlines(), 1):
                s = line.strip()
                if s.startswith("#"):
                    continue
                if s.startswith(("httpx.get(", "httpx.post(", "httpx.put(")) \
                        and "mounts" in s:
                    offenders.append(f"{py.relative_to(ROOT)}:{i}: {s[:70]}")
    assert not offenders, "顶层 httpx 调用不接受 mounts，请改 httpx.Client：" + \
        "\n".join(offenders)
