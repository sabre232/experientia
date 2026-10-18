"""headless 引擎守护（M-1/M-2）：代理 /health 探活与崩溃重拉、auto_check 出循环。

M-1 根因：裸 TCP connect 探活会把"端口上别人的监听"误判为代理存活
（双实例/端口被占时崩溃恢复永不触发）——探活必须打到 /health。
M-2 根因：auto_check 要调模型（单次最长 30 分钟），内联在扫描循环
会冻结文件捕获——必须进工作线程，且至多 1 个在排队（不重复入队）。
"""

import http.server
import queue
import threading

import pytest

import daemon
from app.distill import engine_curation
from conftest import (hold_unlistened_port, start_loopback_server,
                      stop_loopback_server)


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            body = b'{"status": "ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args) -> None:  # 静默
        pass


@pytest.fixture
def health_server():
    # 改用 conftest 的共享助手——端口由内核分配且构造时即
    # listen，不再需要"起线程后轮询探活"的 5s 预算（全量负载下可能耗尽）。
    srv, port = start_loopback_server(_HealthHandler)
    try:
        yield port
    finally:
        stop_loopback_server(srv)


class _NoHealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args) -> None:
        pass


# ---------- _proxy_alive：探活必须打到 /health ----------

def test_proxy_alive_false_when_nothing_listening():
    s = hold_unlistened_port()
    try:
        assert daemon._proxy_alive(s.getsockname()[1]) is False
    finally:
        s.close()


def test_proxy_alive_true_against_real_health_server(health_server):
    assert daemon._proxy_alive(health_server) is True


def test_proxy_alive_false_when_listener_has_no_health():
    """M-1 核心：端口被别的进程占用（无 /health）→ 判死，触发重拉。"""
    srv, port = start_loopback_server(_NoHealthHandler)
    try:
        assert daemon._proxy_alive(port) is False
    finally:
        stop_loopback_server(srv)


# ---------- _watch_proxy：重拉 + 上限 + 健康清零 ----------

def test_watch_proxy_respawns_when_dead(monkeypatch):
    calls = []

    def fake_thread(store, port):
        calls.append((store, port))
        return threading.Thread(daemon=True)

    monkeypatch.setattr(daemon, "_proxy_alive", lambda port: False)
    monkeypatch.setattr(daemon, "_proxy_thread", fake_thread)
    state = {"thread": None, "retries": 0, "warned": False}
    sentinel = object()
    daemon._watch_proxy(sentinel, 8100, state)
    assert state["retries"] == 1
    assert calls == [(sentinel, 8100)]
    assert state["warned"] is False


def test_watch_proxy_resets_counter_when_healthy(monkeypatch):
    monkeypatch.setattr(daemon, "_proxy_alive", lambda port: True)
    monkeypatch.setattr(daemon, "_proxy_thread", lambda s, p: pytest.fail("健康时不得重拉"))
    state = {"thread": None, "retries": daemon.PROXY_MAX_RETRIES - 1, "warned": False}
    daemon._watch_proxy(object(), 8100, state)
    assert state["retries"] == 0


def test_watch_proxy_stops_after_max_retries(monkeypatch):
    calls = []
    monkeypatch.setattr(daemon, "_proxy_alive", lambda port: False)
    monkeypatch.setattr(daemon, "_proxy_thread", lambda s, p: calls.append(p) or threading.Thread(daemon=True))
    state = {"thread": None, "retries": 0, "warned": False}
    for _ in range(daemon.PROXY_MAX_RETRIES + 3):
        daemon._watch_proxy(object(), 8100, state)
    assert len(calls) == daemon.PROXY_MAX_RETRIES  # 上限后不再重拉
    assert state["warned"] is True  # 且告警只记一次


# ---------- _spawn_auto_check：至多 1 个在排队 ----------

def test_spawn_auto_check_coalesces_and_runs(monkeypatch):
    ran = threading.Event()
    q = queue.Queue()

    monkeypatch.setattr(daemon, "_auto_check_queue", q)
    monkeypatch.setattr(daemon, "_auto_check_worker", None)
    monkeypatch.setattr(engine_curation, "auto_check", lambda st, verbose=False: ran.set())

    sentinel = object()
    daemon._spawn_auto_check(sentinel)
    daemon._spawn_auto_check(sentinel)  # 上一轮还在跑 → 不重复入队
    assert q.qsize() == 1

    assert ran.wait(10)  # worker 线程真跑起来了


# ---------- M-4：main.py 纯壳模式 ----------

def _run_main_shell(monkeypatch, tmp_path, probe_result, expect_exit: bool):
    """跑 main.main(["--headless"])，锁恒失败（模拟 daemon 持锁），探活给 probe_result。

    expect_exit=True：断言 sys.exit(1)（拒绝路径）；False：断言干净返回（壳路径）。"""
    import os

    import main as gui_main
    from app.platform.engine_lock import EngineLock

    monkeypatch.setenv("EXPERIENTIA_HOME", str(tmp_path))
    monkeypatch.delenv("EXPERIENTIA_SHELL_MODE", raising=False)
    monkeypatch.delenv("EXPERIENTIA_API_TOKEN", raising=False)
    monkeypatch.setattr(EngineLock, "acquire", lambda self: False)
    monkeypatch.setattr(daemon, "probe_local_api",
                        lambda port=daemon.LOCAL_API_PORT, **kw: probe_result)
    monkeypatch.setattr(daemon, "start_servers",
                        lambda store: pytest.fail("壳模式不该启动引擎"))
    import app.local_api as local_api
    monkeypatch.setattr(local_api, "ensure_api_token", lambda data_dir: "test-token")
    if expect_exit:
        with pytest.raises(SystemExit) as e:
            gui_main.main(["--headless"])
        assert e.value.code == 1
        assert "EXPERIENTIA_SHELL_MODE" not in os.environ
    else:
        gui_main.main(["--headless"])
        assert os.environ.get("EXPERIENTIA_SHELL_MODE") == "1"
    # main() 经 os.environ 直接写的值不在 monkeypatch 记录里，断言后手动清
    monkeypatch.delenv("EXPERIENTIA_SHELL_MODE", raising=False)
    monkeypatch.delenv("EXPERIENTIA_API_TOKEN", raising=False)


def test_main_shell_mode_when_same_data_dir_running(tmp_path, monkeypatch):
    """同数据目录有活实例 → 纯壳：不启引擎，headless 直接干净退出。"""
    _run_main_shell(monkeypatch, tmp_path, str(tmp_path), expect_exit=False)


def test_main_rejects_when_different_data_dir_running(tmp_path, monkeypatch):
    """锁失败但活实例是别的数据目录 → 维持拒绝（8101 固定端口共存不了）。"""
    _run_main_shell(monkeypatch, tmp_path, str(tmp_path / "other"), expect_exit=True)


def test_main_rejects_when_lock_held_but_probe_dead(tmp_path, monkeypatch):
    """锁失败但探活无响应（持有者 8101 异常）→ 拒绝，不进壳模式。"""
    _run_main_shell(monkeypatch, tmp_path, None, expect_exit=True)


def test_maintenance_daily_gate_not_consumed_when_skipped(tmp_path, monkeypatch):
    """档 C 的日期门只在**真跑过**时盖章。

    修复前的症状：`maintenance.log` 停在几天前，config 里的 `maintenance_date`
    却已经是今天——跨天后的第一次检查若不满足触发条件（0 点刚过、当日还没会话
    结束…），日期先被盖章，这一天就再也不补跑。跳过不盖章，当天后续轮次还能补。
    """
    from datetime import datetime

    from app import notify
    from app.distill import maintenance as mt
    from app.store.store import Store

    store = Store(tmp_path)
    store.ensure_layout()
    today = datetime.now().date().isoformat()
    calls: list[int] = []
    monkeypatch.setattr(mt, "run", lambda s, **k: calls.append(1))

    monkeypatch.setattr(mt, "should_run", lambda s: False)
    daemon.daily_checks(store)
    assert (notify.state_get(store, "daily") or {}).get("maintenance_date") != today, \
        "跳过不该盖章——盖章当天就不再补跑，整理欠账还不清"
    assert calls == []

    monkeypatch.setattr(mt, "should_run", lambda s: True)
    daemon.daily_checks(store)
    assert calls == [1], "条件满足后应当补跑"
    assert notify.state_get(store, "daily")["maintenance_date"] == today


def test_daily_checks_each_block_runs_once_per_day(tmp_path, monkeypatch):
    """同一天连跑多轮，各每日任务只执行一次。

    根因：各块盖章用函数开头那份快照 + state_set 整字典替换，后盖章的块会把先
    盖的字段回退掉，下一轮又判定"今天还没跑过"——实测保留清理一天白跑两遍。
    验收口径（cron 幂等惯例）：连跑两遍，第二次不该有任何副作用。
    """
    from datetime import datetime

    from app import notify
    from app.distill import maintenance as mt
    from app.distill import weekly_report
    from app.store.store import Store

    store = Store(tmp_path)
    store.ensure_layout()
    today = datetime.now().date().isoformat()

    calls = {"prune": 0, "growth": 0}
    monkeypatch.setattr(
        store, "prune_sessions",
        lambda *a, **k: (calls.__setitem__("prune", calls["prune"] + 1), 0)[1])
    monkeypatch.setattr(
        daemon, "_daily_growth_notices",
        lambda s: calls.__setitem__("growth", calls["growth"] + 1))
    # 隔离外部动作：档 C 真跑（但不做整理）、周日结算不真发
    monkeypatch.setattr(mt, "should_run", lambda s: True)
    monkeypatch.setattr(mt, "run", lambda s, **k: None)
    monkeypatch.setattr(weekly_report, "maybe_run", lambda s: None)

    daemon.daily_checks(store)
    assert calls == {"prune": 1, "growth": 1}, f"首轮各块应各执行一次: {calls}"

    daemon.daily_checks(store)
    daemon.daily_checks(store)
    assert calls == {"prune": 1, "growth": 1}, f"第二轮起不该再有副作用: {calls}"

    st = notify.state_get(store, "daily") or {}
    for field in ("pruned_date", "growth_date", "maintenance_date"):
        assert st.get(field) == today, \
            f"{field} 应为今天，实际 {st.get(field)}（盖章被别的块抹掉了？）"


# ---------- 线程异常兜底：uvicorn 起不来必须留日志（打包事故） ----------

def test_local_api_thread_failure_leaves_log(tmp_path, monkeypatch, caplog):
    """本地 API 线程死亡不再静默。

    事故回放：uvicorn 动态后端 ImportError 死在 `experientia-local-api` 线程里，
    windowed 打包态 stderr 不存在 → 异常被吞 → 引擎进程活着、端口没起、日志零报错。
    线程死可以是结果（端口起不来），但"什么都没有"不允许。
    """
    import logging

    import app.local_api as local_api
    from app.store.store import Store

    def _boom(store):
        raise ImportError("No module named 'uvicorn.protocols.http.httptools_impl'")

    monkeypatch.setattr(local_api, "create_local_app", _boom)
    store = Store(tmp_path)
    store.ensure_layout()

    with caplog.at_level(logging.ERROR, logger="experientia.thread"):
        t = daemon._local_api_thread(store)
        t.join(10)
    assert not t.is_alive()
    errs = [r for r in caplog.records
            if r.name == "experientia.thread" and r.levelno >= logging.ERROR]
    assert errs, "线程死可以，但必须落日志"
    assert "experientia-local-api" in errs[0].getMessage()
    assert errs[0].exc_info is not None  # 带栈，才看得到死在哪个 import 上


# ---------- 打包态 headless：引擎子进程不加载 GUI ----------

def _run_main_headless_engine(monkeypatch, tmp_path, *, no_tray: bool):
    """跑 main.main(["--headless"])：锁成功（本进程成引擎），引擎与 GUI 全桩。

    返回 _run_gui 的调用记录（空 = 没走 Qt 路径）。常驻 sleep 第一次调用即抛
    KeyboardInterrupt，让 main() 可收尾返回。token 走桩——真实的
    ensure_api_token 会碰系统钥匙串，测试不依赖宿主机状态。
    """
    import app.token_util as token_util
    import main as gui_main
    from app.platform.engine_lock import EngineLock

    monkeypatch.setenv("EXPERIENTIA_HOME", str(tmp_path))
    for k in ("EXPERIENTIA_SHELL_MODE", "EXPERIENTIA_INPROC_ENGINE",
              "EXPERIENTIA_API_TOKEN", "EXPERIENTIA_PARENT_PID"):
        monkeypatch.delenv(k, raising=False)
    if no_tray:
        monkeypatch.setenv("EXPERIENTIA_NO_TRAY", "1")
    else:
        monkeypatch.delenv("EXPERIENTIA_NO_TRAY", raising=False)

    monkeypatch.setattr(gui_main, "is_packaged", lambda: True)
    monkeypatch.setattr(EngineLock, "acquire", lambda self: True)
    monkeypatch.setattr(EngineLock, "release", lambda self: None)
    monkeypatch.setattr(daemon, "probe_local_api", lambda **kw: None)
    monkeypatch.setattr(daemon, "start_servers", lambda store: 8100)
    monkeypatch.setattr(daemon, "scan_loop", lambda *a, **k: None)
    monkeypatch.setattr(token_util, "ensure_api_token",
                        lambda data_dir: "test-token")

    run_gui_calls: list[tuple] = []
    monkeypatch.setattr(gui_main, "_run_gui",
                        lambda *a, **k: run_gui_calls.append((a, k)))

    def _interrupt_sleep(_secs):
        raise KeyboardInterrupt

    monkeypatch.setattr(gui_main.time, "sleep", _interrupt_sleep)
    gui_main.main(["--headless"])
    # main() 经 os.environ 写的值不在 monkeypatch 记录里，断言后手动清
    monkeypatch.delenv("EXPERIENTIA_API_TOKEN", raising=False)
    return run_gui_calls


def test_headless_needs_gui_only_without_no_tray(monkeypatch):
    """纯决策函数：仅开机自启（无 NO_TRAY）的打包态 headless 需要 Qt（托盘）。"""
    import main as gui_main

    monkeypatch.setenv("EXPERIENTIA_NO_TRAY", "1")
    assert gui_main._headless_needs_gui() is False
    monkeypatch.delenv("EXPERIENTIA_NO_TRAY", raising=False)
    assert gui_main._headless_needs_gui() is True


def test_packaged_headless_engine_child_never_loads_gui(tmp_path, monkeypatch):
    """GUI 拉起的引擎子进程（NO_TRAY=1）：不 import PySide6，纯 headless 常驻。

     前这里走 _run_gui(hidden=True)——整套 PySide6（~47MB）+
    MainWindow 被塞进本该无脸的引擎进程：更重，且引擎的死活被 Qt 初始化绑住。
    """
    run_gui_calls = _run_main_headless_engine(
        monkeypatch, tmp_path, no_tray=True)
    assert run_gui_calls == [], "NO_TRAY 子进程不该走 Qt 路径"


def test_packaged_headless_autostart_keeps_hidden_gui(tmp_path, monkeypatch):
    """开机自启（exe --headless，无 NO_TRAY）：托盘只挂在 QApplication 上 →
    仍跑隐藏 Qt 窗口（既有行为，不回归）。"""
    run_gui_calls = _run_main_headless_engine(
        monkeypatch, tmp_path, no_tray=False)
    assert len(run_gui_calls) == 1
    _args, kwargs = run_gui_calls[0]
    assert kwargs.get("hidden") is True
