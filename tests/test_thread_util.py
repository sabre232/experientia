"""app/thread_util.py：后台线程兜底契约（打包事故的防线）。

事故回放：uvicorn 的动态后端 import 失败死在 `experientia-local-api` 线程里，
windowed 打包态 stderr 不存在 → 异常被吞 → 引擎进程活着、端口没起、日志零报错，
"冒烟通过"是假象。本文件钉住的承诺：**线程再死，也必须留日志**。
"""

import logging
import sys
import threading

from app.thread_util import install_thread_excepthook, run_logged, spawn


def test_spawn_runs_target_and_returns_joinable_thread():
    done = threading.Event()
    t = spawn(lambda: done.set(), name="t-runs")
    assert done.wait(5)
    t.join(5)
    assert not t.is_alive()


def test_spawn_logs_error_with_traceback_when_target_raises(caplog):
    def _boom():
        raise RuntimeError("boom-标记串")

    with caplog.at_level(logging.ERROR, logger="experientia.thread"):
        t = spawn(_boom, name="t-boom")
        t.join(5)
    assert not t.is_alive()  # 线程自己收尾，不把异常漏给默认 excepthook
    errs = [r for r in caplog.records
            if r.name == "experientia.thread" and r.levelno >= logging.ERROR]
    assert errs, "target 抛异常必须落 ERROR 日志（不能静默死亡）"
    err = errs[0]
    assert "t-boom" in err.getMessage()  # 带线程名
    assert err.exc_info is not None      # 带栈
    assert "boom-标记串" in str(err.exc_info[1])  # 异常本体在 exc_info 里


def test_spawn_logs_info_on_normal_exit(caplog):
    with caplog.at_level(logging.INFO, logger="experientia.thread"):
        t = spawn(lambda: None, name="t-ok")
        t.join(5)
    assert any("正常退出" in r.getMessage() and "t-ok" in r.getMessage()
               for r in caplog.records if r.name == "experientia.thread")


def test_spawn_catches_system_exit(caplog):
    """SystemExit 也必须留日志。

    uvicorn 启动失败走 sys.exit(STARTUP_FAILURE)——SystemExit 是
    BaseException，`except Exception` 接不住（实测从这缝漏出去过）。
    """
    def _exit_boom():
        sys.exit(3)

    with caplog.at_level(logging.ERROR, logger="experientia.thread"):
        t = spawn(_exit_boom, name="t-exit")
        t.join(5)
    assert not t.is_alive()
    errs = [r for r in caplog.records
            if r.name == "experientia.thread" and r.levelno >= logging.ERROR]
    assert errs, "SystemExit 也不能静默"
    assert "t-exit" in errs[0].getMessage()


def test_run_logged_takes_thread_name_from_current_thread(caplog):
    """直接当 target 用时，线程名从 current_thread 取，不依赖调用方传名。"""
    def _boom():
        raise ValueError("x")

    with caplog.at_level(logging.ERROR, logger="experientia.thread"):
        t = threading.Thread(target=run_logged, args=(_boom,), name="t-direct")
        t.start()
        t.join(5)
    assert any("t-direct" in r.getMessage()
               for r in caplog.records if r.levelno >= logging.ERROR)


def test_excepthook_logs_uncaught_thread_exception(caplog):
    """全局兜底：没走 spawn 的线程抛异常也落 ERROR（幂等，重复装安全）。"""
    prev = threading.excepthook  # 测完还原，不污染同进程后续测试
    try:
        install_thread_excepthook()
        install_thread_excepthook()  # 第二次不得叠加/报错

        def _boom():
            raise RuntimeError("hook-标记串")

        with caplog.at_level(logging.ERROR, logger="experientia.thread"):
            t = threading.Thread(target=_boom, name="t-hook")
            t.start()
            t.join(5)
        hits = [r for r in caplog.records
                if r.name == "experientia.thread" and r.levelno >= logging.ERROR
                and "t-hook" in r.getMessage()
                and r.exc_info and "hook-标记串" in str(r.exc_info[1])]
        assert hits, "未包装线程的未捕获异常也必须落日志（否则同类问题再次全隐）"
    finally:
        threading.excepthook = prev
