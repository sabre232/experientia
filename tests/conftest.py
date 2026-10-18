"""pytest 引导：把仓库根加入 sys.path。

不依赖 editable 安装的 .pth（中文路径下 site.py 的编码解码可能不一致），
保证任何环境下 pytest 都能 import app。
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 离线 API 桩基类（不牵入 Qt，已验证：import 后 PySide6 不在 sys.modules）
from app.gui.api_client import LocalApi, LocalApiError  # noqa: E402


def pytest_report_header(config):
    """提醒：本机 Python 装了 safe-delete 闸门，跑全量前需先关掉它。

    闸门接管了 shutil.rmtree 与 Path.unlink，同一回合内累计删除超过 50 个
    文件就 SystemExit(1)。pytest 靠删除来回收临时目录（单次全量约 1.5 万个
    文件），必然撞闸门：进程在写汇总前被打断，表现为 exit 1、汇总行丢失，
    看着像测试大面积失败，实际是收尾被打断；回收失败又让历史临时目录只增
    不减（系统临时目录下已堆到 6.5 万文件 / 300 MB）。

    闸门自带开关（进程启动时读取，conftest 里再改已太晚），跑全量时前置：
        CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -m pytest tests/ -q
    """
    import sys

    shim = sys.modules.get("sitecustomize")
    armed = getattr(shim, "_SAFE_DELETE_ENABLED", False)
    if armed and os.environ.get("CODEBUDDY_SAFE_DELETE_ENABLED") != "0":
        return ("safe-delete 闸门生效中：pytest 回收临时目录会触发 SystemExit(1)，"
                "跑全量请前置 CODEBUDDY_SAFE_DELETE_ENABLED=0")
    return None

# 8101 本地 API 鉴权：测试统一用固定 token（生产走 keyring 随机值）
TEST_API_TOKEN = "test-local-api-token"

# ensure_api_token env 优先——测试会话统一钉死该值，引擎/代理/GUI 解析
# 结果确定（生产由 main.py 启动时注入同名变量，链路一致）
os.environ.setdefault("EXPERIENTIA_API_TOKEN", TEST_API_TOKEN)

# 代理 8100 默认鉴权后的统一请求头：ASGITransport 测试传给
# httpx.AsyncClient(headers=...)，TestClient 用 c.headers.update(...)
PROXY_AUTH_HEADERS = {"Authorization": f"Bearer {TEST_API_TOKEN}"}


def rmtree_readonly(path) -> None:
    """递归删除含只读文件的目录（Windows 专用兜底）。

    `git init` 生成的 object 文件权限是 444，Windows 上删只读文件直接抛
    PermissionError——**连 pytest 自己的临时目录回收也救不回来**（它的 rm_rf
    只 chmod 报错的那一个路径，git object 是"只读文件 + 只读父目录"，向上递归
    不覆盖父目录时就失败）。实测：跑一次 `test_verify_git_evidence`，系统临时
    目录里就永久留一个含 `.git` 的目录，pytest 只保留最近 3 个 numbered dir
    的机制因此失效、只增不减。

    用法：测试里凡是用 subprocess 建 git 仓库 / 造只读产物的，收尾用它删，
    别指望 pytest 回收。
    """
    import stat

    def _chmod_and_retry(func, target, exc):
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
        func(target)

    import shutil
    shutil.rmtree(path, onerror=_chmod_and_retry)


class OfflineApi(LocalApi):
    """一切请求立即失败（模拟引擎未运行），**不碰网络**。

    页面测试里的 API 桩必须继承它。踩过的坑：直挂 `LocalApi` 而没覆写
    `_request` 的桩，未桩的方法会真的打到 8101——代价是每条用例 ~2s 的死端口
    等待（本机安全软件审计），且宿主机跑着真守护进程时会喂进真实数据。
    """

    def _request(self, method, path, json=None, params=None, timeout=None):
        raise LocalApiError(0, "本地 API 未连接")


@pytest.fixture(scope="session", autouse=True)
def _no_env_proxy():
    """整个测试会话摘掉系统代理（最高性价比的一道闸）。

    httpx 默认 `trust_env=True`、urllib 的 ProxyHandler 也会读 `HTTP_PROXY`，
    于是**回环请求被送到代理**：请求行被改写成绝对 URI，代理返回 404/502 →
    表现为"本机绿、别人机器红"，换台有代理的机器就复现。产品侧的修法是
    `mounts=DIRECT_LOOPBACK`（见 `app/net_util.py`），测试侧再加这道闸兜住
    所有没走产品代码路径的裸调用（子进程继承的 env 也一并干净）。
    """
    for v in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
              "ALL_PROXY", "all_proxy"):
        os.environ.pop(v, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


@pytest.fixture(autouse=True)
def _pin_local_api_listening():
    """钉死"8101 上有没有人在听"这个真实端口探测。

    `MainWindow._boot_api_config()` 启动时会真 socket 探测 8101，没在听就直接
    走兜底分支、压根不调用测试注入的假接口——**守护进程开没开决定用例红绿**。
    默认钉 False（引擎未运行，与 OfflineApi 语义一致）；要测"引擎在跑"的用例
    自己 `monkeypatch.setattr(mw, "local_api_listening", lambda base: True)` 覆盖。
    """
    try:
        from app.gui import main_window as mw
    except Exception:
        yield
        return
    real = mw.local_api_listening
    mw.local_api_listening = lambda base: False
    try:
        yield
    finally:
        mw.local_api_listening = real


@pytest.fixture(autouse=True)
def _clear_detect_cache():
    """M10：detect() 的 TTL 缓存是模块级全局，跨测试会串味（前一个测试指向的
    临时目录结果被后一个测试吃到）。每个测试前清空。"""
    from app.capture import registry
    registry._detect_cache = None
    registry._last_force = None
    # aider 的配置缓存是模块级全局（避免每轮探测重建 Store），跨测试会
    # 串味（前一个测试的 config 被后一个吃到）——一并清空 + 复位首告警标志。
    try:
        from app.capture.adapters import aider as _aider
        _aider._config_cache = None
        _aider._no_roots_logged = False
    except Exception:
        pass
    # b：auto_search 负结果缓存也是模块级全局，跨测试串味——清空
    try:
        from app.capture.adapters import base_jsonl as _bj
        _bj._autosearch_neg.clear()
    except Exception:
        pass
    yield
    registry._detect_cache = None
    registry._last_force = None


@pytest.fixture(autouse=True)
def _reap_gui_workers():
    """Qt 退出段错误收口·闸一：每个测试收尾时等在飞的 GUI 取数
    线程落地。本机对死端口 HTTP 连接一挂 ~2s，_FetchWorker/ApiWorker 常在
    测试结束后仍 running（faulthandler 崩溃栈抓到 httpcore connect_tcp），
    与后续 teardown/解释器 finalize 赛跑——崩点随线程完成时机漂移。等干净
    再走；无在飞线程时零开销。

    Qt 不提供"枚举全部 QThread"的 API（PySide6 连 QThread.threads() 都没有），
    故在 conftest 里包一层 QThread.start 记录启动过的 GUI worker 实例
    （WeakSet 不延命、不影响产品代码）。"""
    yield
    import time
    try:
        from app.gui.page_base import _FetchWorker, ApiWorker
    except Exception:
        return
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        alive = []
        for t in list(_STARTED_QTHREADS):  # list 快照：防并发 add 迭代中变形
            try:
                if isinstance(t, (ApiWorker, _FetchWorker)) and t.isRunning():
                    alive.append(t)
            except RuntimeError:
                pass  # C++ 侧已析构的包装器：视为已落地
        if not alive:
            return
        time.sleep(0.02)


# conftest 装载时包一层 QThread.start 记录实例（见 _reap_gui_workers docstring）
import weakref  # noqa: E402

_STARTED_QTHREADS: "weakref.WeakSet" = weakref.WeakSet()
try:
    from PySide6.QtCore import QThread as _QT

    _orig_qthread_start = _QT.start

    def _tracking_qthread_start(self, *args, **kwargs):
        _STARTED_QTHREADS.add(self)
        return _orig_qthread_start(self, *args, **kwargs)

    _QT.start = _tracking_qthread_start
except ImportError:  # 无 PySide6 环境：闸一自动失效
    pass


@pytest.fixture(scope="session", autouse=True)
def _qt_session_teardown():
    """Qt 退出段错误收口·闸二：会话结束主动收尸顶层控件。

    背景：测试全绿后解释器关闭阶段 access violation（exit 139，faulthandler
    栈 "<no Python frame>"）——session 级 QApplication 与测试攒下的顶层控件
    （MainWindow/QMenu 弹层等，全量能到 90+ 个）在 Python finalization 与
    Qt 静态析构之间互相踩。worktree 基线确认此崩早于本改动存在。os._exit
    硬退方案试过：崩在 DLL detach 本身，且吞掉 capture 缓冲里的汇总行，作废。

    做法：逐控件 isValid 守卫 → close → 摘父 → deleteLater → 只泵
    DeferredDelete（不 processEvents——main_window 有 2500ms 的
    QTimer.singleShot，全泵会让它在对象半毁时开火）。闸一（_reap_gui_workers）
    先等取数线程落地，本闸收尸才稳；qt_pages 单文件实测 exit 0。"""
    yield
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    import shiboken6
    from PySide6.QtCore import QEvent, QCoreApplication
    for w in list(app.topLevelWidgets()):
        try:
            if not shiboken6.isValid(w):
                continue  # C++ 侧已死、只剩 Python 壳：碰即抛，跳过
            w.close()
            w.setParent(None)
            w.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        except Exception:
            pass


def start_upstream(app, timeout: float = 10.0):
    """后台线程起 uvicorn，端口由内核分配；返回 (port, stop)。

    端口硬编码（18123/18124 被多个测试文件各自声明）在串行全量里会串台：
    上一个 module 的 server 线程没退干净时，新 server 仍能 bind（Windows
    SO_REUSEADDR），请求被旧 app 接走 —— 表现为第二轮请求莫名其妙的 404。
    改由内核分配端口，每个 module 各用各的，互不影响。

    就绪判定用 server.started 而非 socket connect_ex：后者只证明端口在
    listen，不证明 ASGI app 已就绪。stop() 必须在 teardown 里调用。
    """
    import threading
    import time

    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0,
                                           log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not server.started:
        time.sleep(0.02)
    if not server.started:
        server.should_exit = True
        t.join(timeout=5)
        raise RuntimeError(f"mock upstream 在 {timeout}s 内未启动")

    def stop():
        server.should_exit = True
        t.join(timeout=5)

    return server.servers[0].sockets[0].getsockname()[1], stop


# ---------- 起回环 HTTP 服务的共享助手 ----------
#
# 此前 tests/test_daemon.py 与 tests/test_engine_lock.py 各自定义了逐字相同的
# `_free_port()`：bind 到 0 → 取到端口号 → **立刻关闭 socket** → 再拿这个号去
# bind。中间存在 TOCTOU 窗口：全量跑时别的测试可能抢走同一个端口，表现为
# "时灵时不灵"。这里统一改成让服务器自己 bind 到端口 0（构造时即完成 bind +
# listen 且不放开 socket），再取 server_address[1]——与 tests/test_distill_route.py
# 和 tests/test_net_util.py 既有写法一致。


def start_loopback_server(handler_cls):
    """起一个回环 HTTP 服务，端口由内核分配。返回 (server, port)。

    构造返回时 socket 已处于 listen 状态：客户端连接会进 backlog，等
    serve_forever 起来就被接受，**不会** connection refused——因此调用方
    不需要做就绪轮询（此前 test_daemon 的 health_server 靠 5s 轮询探活，
    全量负载下可能耗尽预算）。

    调用方必须在收尾调 stop_loopback_server(server)。
    """
    import http.server
    import threading

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def stop_loopback_server(srv) -> None:
    """停掉 start_loopback_server 起的服务（停止 serve_forever + 关监听）。"""
    srv.shutdown()
    srv.server_close()


def hold_unlistened_port():
    """占住一个回环随机端口但**不监听**，返回已 bind 的 socket（调用方负责 close）。

    给"这个端口上没人在听"的断言用：端口由本 socket 持有，别人抢不走（无
    TOCTOU）；连接它会被拒（与端口完全空闲同表现）。
    """
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    return s


def freeze_utcnow(monkeypatch, iso: str) -> None:
    """把 store 层的时钟钉死到 `iso`（L4 的附带改动）。

    `utcnow` 是 `from ._shared import utcnow` 的**早绑定**：每个 import 它的模块
    各自持有一份模块级名字。只 patch `app.store.store.utcnow` 覆盖不到已经搬到
    mixin 里的写口（`injection.py` / `changelog.py` / `rules.py` 都直接绑了一份），
    表现为"落库时间戳是真实当前时间、窗口断言读到空"。
    这里遍历 `app.store` 下所有子模块，凡是绑了 `utcnow` 的一律钉住。
    """
    import importlib
    import pkgutil

    import app.store as pkg

    def _frozen() -> str:
        return iso

    for mi in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"{pkg.__name__}.{mi.name}")
        if hasattr(mod, "utcnow"):
            monkeypatch.setattr(mod, "utcnow", _frozen)


def local_api_client(store):
    """带 Bearer 头的 TestClient（create_local_app 默认鉴权，裸 client 必 401）。"""
    from fastapi.testclient import TestClient

    from app.local_api import create_local_app

    client = TestClient(create_local_app(store, api_token=TEST_API_TOKEN))
    client.headers["Authorization"] = f"Bearer {TEST_API_TOKEN}"
    return client


def pump_until(cond, qapp, timeout: float = 5.0) -> bool:
    """泵事件循环直到 cond() 为真（H3 异步刷新配套：等后台取数渲染完成）。

    超时返回 False——由调用方断言或继续，不直接抛，方便写"应当很快完成"的
    弱等待。qapp 由调用方传入（各测试文件的 session 级 fixture）。"""
    import time

    from PySide6.QtCore import QCoreApplication

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def pump_page():
    """页面异步刷新泵：page.refresh() 后调用，等 fetch_and_render 落地渲染。

    用法：pump_page(page, qapp)。仅对 PageBase 系页面有效（_fetches 清单）。"""
    def _pump(page, qapp, timeout: float = 5.0) -> bool:
        return pump_until(lambda: not getattr(page, "_fetches", None),
                          qapp, timeout)
    return _pump
