"""进程存活探测 + 父进程看护（引擎拆进程用）。

跨平台判定「某个 pid 是否已退出」：

- Windows：不用 ``os.kill(pid, 0)``——实测对「已退出但仍有句柄残留」的 pid 抛
  ``SystemError``（CPython 缺陷，``except OSError`` 接不住），调用方恰在要干活时
  崩溃。改用 ``WaitForSingleObject``（内核级进程退出等待，与句柄残留无关）；
  ``OpenProcess`` 打不开（pid 无效/已回收）按已退出处理。
- POSIX：``kill(pid, 0)`` 可靠（``ESRCH`` = 死 / 0 = 活）。

``start_parent_watch`` 供 GUI 拉起的引擎子进程使用：父进程（GUI）关窗/崩溃后
子进程不残留（与 GUI 侧 ``aboutToQuit`` 的主动终止形成双保险——覆盖强杀 GUI
这种来不及走退出钩子的场景）。仅当调用方显式传入 pid 时才启用；开机自启/手工
headless 无父进程概念，不受影响。
"""

from __future__ import annotations

import os
import sys
import threading
import time

PARENT_PID_ENV = "EXPERIENTIA_PARENT_PID"


def pid_exited(pid: int, *, wait_ms: int = 2000) -> bool:
    """主进程是否已退出（详见模块 docstring 的平台口径）。"""
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return False
        except OSError:
            return True
    import ctypes

    k32 = ctypes.windll.kernel32
    PROCESS_QUERY_INFORMATION, WAIT_OBJECT_0 = 0x1000, 0
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return True  # 打不开 = pid 无效或已回收
    try:
        return k32.WaitForSingleObject(h, wait_ms) == WAIT_OBJECT_0
    finally:
        k32.CloseHandle(h)


def start_parent_watch(pid: int, *, interval: float = 2.0,
                       on_exit=None) -> threading.Thread:
    """起后台守护线程：父进程 ``pid`` 消失后回调 ``on_exit``（缺省 ``os._exit(0)``）。

    - 缺省 ``os._exit(0)``：引擎进程以 uvicorn 等守护线程常驻，正常 ``sys.exit``
      从非主线程退不掉；这里用进程级硬退出（与 GUI 侧 ``Popen.terminate()``
      同为「立即终止」语义，SQLite WAL 由下次打开自恢复）。
    - fail-open：探测或回调抛异常即停表，绝不因看护失败杀掉引擎。
    """
    if on_exit is None:
        on_exit = lambda: os._exit(0)  # noqa: E731

    def _watch() -> None:
        while True:
            time.sleep(interval)
            try:
                if pid_exited(pid):
                    on_exit()
                    return
            except Exception:  # noqa: BLE001 看护失败不杀引擎
                return

    t = threading.Thread(target=_watch, name="experientia-parent-watch",
                         daemon=True)
    t.start()
    return t