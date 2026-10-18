"""后台线程统一兜底：线程 target 抛异常必须留日志，绝不静默死亡。

为什么需要（打包事故复盘）：PyInstaller windowed（console=False）
下 sys.stdout/stderr 为 None，线程里未捕获的异常没有 excepthook 可去、被直接
吞掉。当时 uvicorn 的动态后端 import 失败死在 `experientia-local-api` 线程里：
引擎进程活着、日志写着"引擎已启动"，但端口从未绑定——症状全隐，只能靠摸端口
复现。`main.py` 虽把 stdout/stderr 重定向到 devnull 防 uvicorn 自己崩，但兜不住
线程异常。

两件防护，配合用：

1. `spawn()`——起 daemon 线程的统一入口：target 正常返回或抛异常都至少落一条
   日志（异常带栈）。引擎/后台线程一律用它，别再裸
   `threading.Thread(target=...).start()`。（内部已有 try/except 的循环型
   worker——如 auto_check/复盘 worker——不必强制迁移，它们自己收口。）
2. `install_thread_excepthook()`——全局兜底：给 `threading.excepthook` 挂一层
   写日志的钩子，**任何**没被 spawn 包住的线程（第三方库、将来新增的）未捕获
   异常也至少落一条 ERROR。由 `app/log_conf.setup_logging` 在进程启动时安装。

只加可见性、不改行为：异常该怎么终止线程还怎么终止，只是不再"什么都没有"。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("experientia.thread")


def run_logged(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """线程 target 包装器：异常落 ERROR（含栈），正常返回落 INFO。

    线程名取 `threading.current_thread().name`（由 spawn 在 Thread 上设好），
    调用方不需要额外传名。

    接 BaseException 而不只是 Exception：uvicorn 启动失败走
    `sys.exit(STARTUP_FAILURE)`——SystemExit 是 BaseException，`except
    Exception` 接不住，实测就从这缝里漏出去过一次。
    """
    name = threading.current_thread().name
    try:
        fn(*args, **kwargs)
    except BaseException:
        logger.exception("后台线程异常终止：%s", name)
    else:
        logger.info("后台线程正常退出：%s", name)


def spawn(target: Callable[..., Any], *args: Any, name: str,
          daemon: bool = True, **kwargs: Any) -> threading.Thread:
    """起 daemon 线程：target 的任何未捕获异常都会记 ERROR 日志（含栈）。

    返回的 Thread 与普通线程无异（`is_alive()` / `join()` 照常用）。
    """
    t = threading.Thread(target=run_logged, args=(target, *args),
                         kwargs=kwargs, name=name, daemon=daemon)
    t.start()
    return t


def install_thread_excepthook() -> None:
    """给 threading.excepthook 挂一层写日志的钩子（进程级，装一次）。

    threading 默认把未捕获异常打到 stderr——windowed 打包态 stderr 不存在 →
    异常彻底消失。本钩子保证任何线程（包括没走 spawn 的）未捕获异常至少落一条
    ERROR（含栈 + 线程名）。不链原 hook：控制台模式下 logging 本身已把 ERROR
    打到 stderr，链上去只会同一份栈打印两遍。重复调用安全。
    """
    if getattr(threading.excepthook, "_experientia_installed", False):
        return

    def _hook(args: threading.ExceptHookArgs) -> None:
        tname = args.thread.name if args.thread else "?"
        logger.error("线程未捕获异常（%s）：%s", tname, args.exc_value,
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    _hook._experientia_installed = True  # type: ignore[attr-defined]
    threading.excepthook = _hook
