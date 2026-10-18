"""单实例进程锁（M-4）+ 8101 探活：防两套引擎并存。

OS 字节锁（Windows msvcrt / POSIX flock）随进程死亡内核释放 → 无陈旧锁；
拿不到锁 = 有活进程持有同一数据目录。8101 是固定端口，补数据目录锁
盖不到的"不同数据目录双实例"。
"""

import http.server

import daemon
from app.platform.engine_lock import EngineLock
from conftest import (hold_unlistened_port, start_loopback_server,
                      stop_loopback_server)


# ---------- EngineLock ----------

def test_second_acquire_fails_same_data_dir(tmp_path):
    a, b = EngineLock(tmp_path), EngineLock(tmp_path)
    assert a.acquire()
    assert not b.acquire()
    assert a.held and not b.held
    a.release()
    assert b.acquire()
    b.release()


def test_release_allows_reacquire(tmp_path):
    a = EngineLock(tmp_path)
    assert a.acquire()
    a.release()
    assert a.acquire()  # 同一实例可重取
    a.release()


def test_independent_per_data_dir(tmp_path):
    """不同数据目录的锁互不干扰（8101 冲突由 probe_local_api 兜底）。"""
    a, b = EngineLock(tmp_path / "a"), EngineLock(tmp_path / "b")
    assert a.acquire() and b.acquire()
    a.release()
    b.release()


def test_acquire_twice_same_instance_no_error(tmp_path):
    a = EngineLock(tmp_path)
    assert a.acquire()
    assert a.acquire()  # 幂等
    a.release()


# ---------- probe_local_api ----------

class _StatusHandler(http.server.BaseHTTPRequestHandler):
    last_path: str | None = None

    def do_GET(self) -> None:
        _StatusHandler.last_path = self.path
        if self.path.split("?", 1)[0] == "/api/status":
            body = b'{"version": "1.0.0", "data_dir": "C:/other-instance"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args) -> None:
        pass


def test_probe_local_api_free_port_returns_none():
    s = hold_unlistened_port()
    try:
        assert daemon.probe_local_api(s.getsockname()[1]) is None
    finally:
        s.close()


def test_probe_local_api_returns_running_data_dir():
    # 此前起完 serve_forever 线程**没有任何就绪等待**就直接
    # 发请求（且端口来自已释放的 _free_port，存在 TOCTOU）。改用 conftest 共享
    # 助手：端口由内核分配、构造时即 listen，请求必进 backlog 不会被拒。
    _StatusHandler.last_path = None
    srv, port = start_loopback_server(_StatusHandler)
    try:
        assert daemon.probe_local_api(port) == "C:/other-instance"
        # M-4：探活走 lite（跳过全盘 detect，冷缓存 2.4s+ 会吃掉超时预算）
        assert _StatusHandler.last_path == "/api/status?lite=1"
    finally:
        stop_loopback_server(srv)


def test_probe_local_api_ignores_listener_without_status():
    """端口被占但没有 /api/status（别的程序）→ 判空闲，不误报实例。"""

    class _NoStatus(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args) -> None:
            pass

    srv, port = start_loopback_server(_NoStatus)
    try:
        assert daemon.probe_local_api(port) is None
    finally:
        stop_loopback_server(srv)
