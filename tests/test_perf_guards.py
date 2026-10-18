"""性能守卫测试（回归红线）——波 1 的四条不可回退行为。

覆盖：
  1. `/api/status` 绝不调用 registry.detect()（摘掉 13.6s 冷探测）。
  2. AiderAdapter 在无 aider_scan_roots 时 discover() 返回 [] 且不遍历家目录。
  3. `start_deep_scan` 默认不启动全盘扫描线程。
  4. `app.gui.layout` 导入不拉入 PIL。

口径：只断言**行为**（是否调用 / 是否返回空 / 是否起线程），不断言私有变量名
以外的实现细节，降低脆性。测试不得依赖宿主机真实状态（AGENTS 铁律 5）。
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_status_endpoint_never_triggers_detect(tmp_path, monkeypatch):
    """/api/status（非 lite）只读快照，绝不触发全量探测。"""
    from app.capture import registry
    from app.local_api_routers.status import build_status_router
    from app.store.store import Store

    def _boom(*a, **k):  # detect 一旦被调用即失败——快照缺失也必须走空态
        raise AssertionError("T1.2 回退：/api/status 触发了 registry.detect()")

    monkeypatch.setattr(registry, "detect", _boom)
    store = Store(tmp_path)
    store.ensure_layout()
    router = build_status_router(store, "tok", lambda h, t: False)
    ep = next(r.endpoint for r in router.routes
              if getattr(r, "path", "") == "/api/status")
    out = ep(lite=0, request=None)
    assert out["agents"] == {}  # 无快照 → 空 dict（UI 走空态），绝不假数字
    assert "agents_at" in out


def test_agents_endpoint_reads_snapshot_only(tmp_path, monkeypatch):
    """GET /api/agents 同样只读快照，不触发探测。"""
    from app.capture import registry
    from app.local_api_routers.status import build_status_router
    from app.store.store import Store

    monkeypatch.setattr(registry, "detect",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("T1.2 回退：/api/agents 触发了 detect()")))
    store = Store(tmp_path)
    store.ensure_layout()
    store.save_agents_snapshot({"codex": 3})
    router = build_status_router(store, "tok", lambda h, t: False)
    ep = next(r.endpoint for r in router.routes
              if getattr(r, "path", "") == "/api/agents")
    out = ep()
    assert out["agents"] == {"codex": 3}
    assert out["at"]  # 采集时间必须落盘


def test_aider_without_scan_roots_does_not_walk_home(monkeypatch):
    """无 aider_scan_roots → discover() 返回 [] 且不 os.walk。"""
    from app.capture.adapters import aider

    monkeypatch.setattr(aider, "_load_config", lambda: {})  # 不构造 Store、不读宿主机
    walked = {"n": 0}

    def _fake_walk(*a, **k):
        walked["n"] += 1
        return iter(())

    monkeypatch.setattr(aider.os, "walk", _fake_walk)
    refs = aider.AiderAdapter().discover()
    assert refs == []
    assert walked["n"] == 0, "T1.1 回退：无配置仍在遍历家目录"


def test_aider_with_scan_roots_still_scans(monkeypatch, tmp_path):
    """配了 aider_scan_roots 时仍会遍历该目录（功能未被误删）。"""
    from app.capture.adapters import aider

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / aider._HIST_NAME).write_text(
        "## [2026-08-28 10:00:00] gpt-4o\n**User:** hi\n**Assistant:** yo\n",
        encoding="utf-8")
    monkeypatch.setattr(aider, "_load_config",
                        lambda: {"aider_scan_roots": [str(repo)]})
    refs = aider.AiderAdapter().discover()
    assert len(refs) == 1 and refs[0].path.name == aider._HIST_NAME


def test_deep_scan_not_started_by_default():
    """start_deep_scan 默认被总闸拦住，不起线程。"""
    from app.capture import registry

    registry.start_deep_scan()
    assert registry._deep_scan_started is False
    assert not any(t.name == "deep-scan" for t in threading.enumerate())


def test_gui_layout_import_does_not_pull_pil():
    """app.gui.layout 导入期不得拉入 PIL——用净解释器验证。"""
    code = (
        "import sys;"
        f"sys.path.insert(0, r'{_REPO_ROOT}');"
        "import app.gui.layout;"
        "print('PIL_LOADED=' + str(any(m == 'PIL' or m.startswith('PIL.')"
        " for m in sys.modules)))"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(_REPO_ROOT),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "PIL_LOADED=False" in r.stdout, r.stdout


# ---------- ：引擎拆进程（GUI 不持锁、子进程唯一写者）----------

class _FakeProc:
    """假子进程：只实现 _terminate/_alive/_spawn 用到的接口。"""

    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.returncode = None
        self.terminated = False
        self.waited = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        self.waited = True
        return self.returncode or 0


def test_engine_command_source_and_packaged(monkeypatch):
    """拉起命令：源码 = <python> <main.py> --headless；打包 = 同一产物 + --headless。"""
    import main

    monkeypatch.setattr(main, "is_packaged", lambda: False)
    cmd = main._engine_command()
    assert cmd == [sys.executable, str(_REPO_ROOT / "main.py"), "--headless"]

    monkeypatch.setattr(main, "is_packaged", lambda: True)
    assert main._engine_command() == [sys.executable, "--headless"]


def test_spawn_engine_env_contract(monkeypatch):
    """子进程 env 契约：带父 pid、禁托盘、剥掉 SHELL_MODE。"""
    import os

    import main

    captured: dict = {}

    def _fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        captured["cwd"] = kwargs.get("cwd")
        return _FakeProc()

    monkeypatch.setattr(main, "is_packaged", lambda: False)
    monkeypatch.setattr(main.subprocess, "Popen", _fake_popen)
    proc = main._spawn_engine()

    assert isinstance(proc, _FakeProc)
    env = captured["env"]
    assert env["EXPERIENTIA_PARENT_PID"] == str(os.getpid())
    assert env["EXPERIENTIA_NO_TRAY"] == "1"
    assert "EXPERIENTIA_SHELL_MODE" not in env
    assert captured["cwd"] == str(_REPO_ROOT)


def test_terminate_engine_child_is_safe_and_idempotent(monkeypatch):
    """关窗/退出回收子进程：terminate 一次、清句柄、重复调用不抛。"""
    import main

    proc = _FakeProc()
    main._set_engine_child(proc)
    try:
        main._terminate_engine_child()
        assert proc.terminated is True
        assert main._engine_child is None
        main._terminate_engine_child()  # 幂等：句柄已清，无副作用
    finally:
        main._set_engine_child(None)


def _prep_main_spawn_test(monkeypatch, tmp_path):
    """共用桩：GUI 常规启动路径（不 headless、不 INPROC）。返回调用记录。"""
    import daemon as engine
    import main
    from app.platform.engine_lock import EngineLock

    monkeypatch.setenv("EXPERIENTIA_HOME", str(tmp_path))
    for k in ("EXPERIENTIA_SHELL_MODE", "EXPERIENTIA_INPROC_ENGINE",
              "EXPERIENTIA_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)

    calls = {"acquire": 0, "release": 0, "start_servers": 0, "spawn": 0,
             "run_gui": 0, "watchdog": 0}
    monkeypatch.setattr(EngineLock, "acquire",
                        lambda self: (calls.__setitem__("acquire", calls["acquire"] + 1) or True))
    monkeypatch.setattr(EngineLock, "release",
                        lambda self: calls.__setitem__("release", calls["release"] + 1))
    monkeypatch.setattr(engine, "probe_local_api", lambda **kw: None)
    monkeypatch.setattr(engine, "scan_loop", lambda *a, **k: None)

    def _start(store):
        calls["start_servers"] += 1
        return 8100

    monkeypatch.setattr(engine, "start_servers", _start)
    monkeypatch.setattr(main, "is_packaged", lambda: False)
    monkeypatch.setattr(main, "_engine_child_alive", lambda p, **kw: True)
    monkeypatch.setattr(main, "_run_gui", lambda *a, **k: calls.__setitem__("run_gui", calls["run_gui"] + 1))
    # 看护线程不真起（避免测试进程留下长驻线程）；只记录是否被调
    monkeypatch.setattr(main, "_start_engine_watchdog",
                        lambda tok: calls.__setitem__("watchdog", calls["watchdog"] + 1))

    def _spawn():
        calls["spawn"] += 1
        return _FakeProc()

    monkeypatch.setattr(main, "_spawn_engine", _spawn)
    return main, calls


def test_gui_launch_spawns_engine_and_never_holds_lock(tmp_path, monkeypatch):
    """GUI 常规启动：释放数据目录锁 → 拉子进程 → 走纯壳；本进程不起引擎。"""
    import os

    main, calls = _prep_main_spawn_test(monkeypatch, tmp_path)
    try:
        main.main([])
        assert calls["spawn"] == 1
        assert calls["start_servers"] == 0  # 引擎不在 GUI 进程里
        assert calls["release"] == 1        # 先交还锁，子进程才是唯一写者
        assert isinstance(main._engine_child, _FakeProc)
        assert os.environ.get("EXPERIENTIA_SHELL_MODE") == "1"
        assert calls["watchdog"] == 1  # 阶段 2：只在 GUI 自己拉起子进程时起看护
    finally:
        main._set_engine_child(None)
        os.environ.pop("EXPERIENTIA_SHELL_MODE", None)
        os.environ.pop("EXPERIENTIA_API_TOKEN", None)


def test_inproc_flag_keeps_old_in_process_engine(tmp_path, monkeypatch):
    """回退开关 EXPERIENTIA_INPROC_ENGINE=1：不拉子进程，本进程起引擎。"""
    import os

    main, calls = _prep_main_spawn_test(monkeypatch, tmp_path)
    monkeypatch.setenv("EXPERIENTIA_INPROC_ENGINE", "1")
    try:
        main.main([])
        assert calls["spawn"] == 0
        assert calls["start_servers"] == 1
        assert calls["release"] == 0
        assert main._engine_child is None
        assert "EXPERIENTIA_SHELL_MODE" not in os.environ
        assert calls["watchdog"] == 0  # 同进程引擎无子进程可看护
    finally:
        main._set_engine_child(None)
        os.environ.pop("EXPERIENTIA_SHELL_MODE", None)
        os.environ.pop("EXPERIENTIA_API_TOKEN", None)


# ----------  阶段 2：引擎看护（掉线自愈 + 僵死判死重拉）----------

def _run_watchdog(monkeypatch, *, interval: float = 0.01):
    """起看护循环（把巡检周期压到毫秒级便于测试），返回 (stop, thread, calls)。"""
    import main

    monkeypatch.setattr(main, "ENGINE_WATCH_INTERVAL", interval)
    stop = threading.Event()
    calls: list = []
    t = threading.Thread(target=main._engine_watchdog_loop,
                         args=("tok", stop), daemon=True)
    return stop, t, calls


def test_watchdog_restarts_when_child_died(monkeypatch):
    """阶段 2：子进程已退出（Popen.poll() 非空）→ 直接重拉一次。"""
    import main

    dead = _FakeProc()
    dead.returncode = 1  # poll() 非 None = 已退出
    main._set_engine_child(dead)
    stop, t, calls = _run_watchdog(monkeypatch)
    monkeypatch.setattr(main, "ENGINE_WATCH_MAX_RESTARTS", 1)
    monkeypatch.setattr(main, "_restart_engine",
                        lambda: (calls.append(1), stop.set()))
    try:
        t.start()
        t.join(timeout=5)
        assert calls, "子进程已退出却未触发重拉"
        assert not t.is_alive()
    finally:
        stop.set()
        main._set_engine_child(None)


def test_watchdog_hang_needs_consecutive_strikes(monkeypatch):
    """阶段 2：进程活着但 8101 无响应 → 连续 STRIKES 次才判僵死（防误杀重活中的引擎）。"""
    import main

    live = _FakeProc()  # poll() 返回 None = 进程活着
    main._set_engine_child(live)
    stop, t, calls = _run_watchdog(monkeypatch)
    monkeypatch.setattr(main, "ENGINE_WATCH_STRIKES", 3)
    monkeypatch.setattr(main, "ENGINE_WATCH_MAX_RESTARTS", 1)
    probes: list = []
    monkeypatch.setattr(main, "_engine_responding",
                        lambda tok, timeout: (probes.append(1) or False))
    monkeypatch.setattr(main, "_restart_engine",
                        lambda: (calls.append(1), stop.set()))
    try:
        t.start()
        t.join(timeout=5)
        assert len(probes) == 3, f"应在第 3 次探活失败才判死，实际 {len(probes)}"
        assert len(calls) == 1
    finally:
        stop.set()
        main._set_engine_child(None)


def test_watchdog_gives_up_after_max_restarts(monkeypatch):
    """阶段 2：连续重拉达上限即放弃（端口被占时不做无限重拉）。"""
    import main

    dead = _FakeProc()
    dead.returncode = 1
    main._set_engine_child(dead)
    stop, t, calls = _run_watchdog(monkeypatch)
    monkeypatch.setattr(main, "ENGINE_WATCH_MAX_RESTARTS", 3)
    monkeypatch.setattr(main, "_restart_engine", lambda: calls.append(1))
    try:
        t.start()
        t.join(timeout=5)
        assert len(calls) == 3
        assert not t.is_alive(), "达上限后应退出，不无限重拉"
    finally:
        stop.set()
        main._set_engine_child(None)
        main._engine_watch_stop.clear()  # 别把停表漏给后续用例（L9u 起句会看它）


def test_watchdog_stops_when_not_owning_child(monkeypatch):
    """阶段 2：归属已变（无子进程）→ 看护循环立即退，不碰别人的引擎。"""
    import main

    main._set_engine_child(None)
    stop, t, _calls = _run_watchdog(monkeypatch)
    try:
        t.start()
        t.join(timeout=5)
        assert not t.is_alive()
    finally:
        stop.set()
        main._engine_watch_stop.clear()  # 别把停表漏给后续用例（L9u 起句会看它）


def test_restart_engine_is_fail_open(monkeypatch):
    """阶段 2：重拉失败（拉起抛异常 / 新进程立即暴毙）→ 只清句柄，绝不抛。"""
    import main

    # _restart_engine 起句会看停表（退出路径不重拉）。
    # 前面的看护测试把停表留在置位态，这里必须先清掉，否则测的是"退出路径"。
    main._engine_watch_stop.clear()
    main._set_engine_child(_FakeProc())

    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "_spawn_engine", _boom)
    main._restart_engine()  # 不抛
    assert main._engine_child is None

    monkeypatch.setattr(main, "_spawn_engine", _FakeProc)
    monkeypatch.setattr(main, "_engine_child_alive", lambda p, **kw: False)
    main._restart_engine()  # 新进程立即暴毙：不登记句柄
    assert main._engine_child is None


def test_restart_engine_skips_when_watch_stopped(monkeypatch):
    """：停表置位（退出路径）→ 不重拉子进程。

    旧实现在退出瞬间仍可能被看护线程拉出新引擎并重新登记句柄，而
    `_terminate_engine_child` 已经跑完 → 退出时漏杀一个孤儿引擎进程。
    """
    import main

    main._engine_watch_stop.set()
    calls = []
    monkeypatch.setattr(main, "_spawn_engine",
                        lambda: calls.append(1) or _FakeProc())
    try:
        main._set_engine_child(_FakeProc())
        before = main._engine_child
        main._restart_engine()
        assert calls == [], "退出路径不得重拉引擎子进程"
        # 早退路径不动既有句柄——收尸由 _terminate_engine_child 负责（它先置停表
        # 再杀进程），这里再动一次反而可能和退出流程抢同一个句柄。
        assert main._engine_child is before
    finally:
        main._engine_watch_stop.clear()
        main._set_engine_child(None)


def test_terminate_engine_child_stops_watchdog(monkeypatch):
    """阶段 2：退出时置停看护表——退出过程中绝不再重拉子进程。"""
    import main

    main._engine_watch_stop.clear()
    main._set_engine_child(_FakeProc())
    try:
        main._terminate_engine_child()
        assert main._engine_watch_stop.is_set()
    finally:
        main._set_engine_child(None)