"""桌面端入口：GUI（Qt/PySide6）外壳 + 内嵌引擎。

引擎（代理 8100 + 本地 API 8101 + 捕获/蒸馏循环）与 headless（daemon.py）
同一套代码路径；GUI 外壳只通过本地 API（HTTP）与引擎交互，不 import 引擎。

    python main.py            # Qt 桌面外壳 + 引擎
    python main.py --headless # 仅引擎（等价 daemon.py，留作排障入口）

打包走 PyInstaller（experientia.spec）；历史 flet build 桌面产物已迁移 Qt，
旧 flet 渲染壳（app/gui/shell）与 web 启动器已随 Qt 迁移完成裁撤（2026 清理波次）。
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

# 启动打点基准：放在第三方 import 之前（含 engine/本地模块的 import 时间）
_T0 = time.perf_counter()

import daemon as engine  # 仓库根模块（headless 入口；不反向 import main，无环）
from app.platform.proc_util import PARENT_PID_ENV
from app.platform.proc_util import pid_exited as _pid_exited
from app.store.store import (Store, cleanup_pending_data_dir,
                             default_engine_log_file, default_log_file)
from app.thread_util import spawn

# PyInstaller windowed（console=False，验收 A3 无控制台）下 sys.stdout/stderr
# 为 None：uvicorn 的 DefaultFormatter 会调 sys.stdout.isatty() 直接崩溃（两个引擎
# 线程静默死亡）。重定向到 devnull，保证二者恒为真实文件对象，全应用生效。
if sys.stdout is None or sys.stderr is None:
    _devnull = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = _devnull
    if sys.stderr is None:
        sys.stderr = _devnull

log = logging.getLogger("experientia.main")


def _phase(tag: str) -> None:
    """冷启动时序打点：记「距进程 import 起点的秒数」，定位卡在 Qt/引擎/窗口哪一段。"""
    log.info("[boot] %s（距启动 %.3fs）", tag, time.perf_counter() - _T0)


def _log_capacity(store: Store) -> None:
    """容量观测：每次启动记一条数据规模，便于按时间回看增长曲线。

    轻量：os.scandir 递归累加（不 rglob 全树、不读文件内容）；条数走 store.stats()
    的 SQL 计数（O(1) 级），绝不整读 JSONL。"""
    import os

    base = Path(store.data_dir)

    def _tree(p: Path) -> tuple[int, int]:
        files = size = 0
        stack = [str(p)]
        while stack:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                stack.append(e.path)
                            elif e.is_file(follow_symlinks=False):
                                size += e.stat(follow_symlinks=False).st_size
                                files += 1
                        except OSError:
                            continue
            except OSError:
                continue
        return files, size

    def _one(name: str) -> int:
        try:
            return (base / name).stat().st_size
        except OSError:
            return 0

    try:
        total_files, total_size = _tree(base)
        sess_files, sess_size = _tree(base / "sessions")
        st = store.stats()
        exps, arch = st.get("experiences", "?"), st.get("archived_sessions", "?")
    except Exception as exc:  # noqa: BLE001 观测失败绝不影响启动
        log.info("[boot] 容量(T3.2) 统计跳过: %s", exc)
        return
    log.info(
        "[boot] 容量(T3.2)：总 %.1fMB/%d文件 · 经验 %s条/%.0fKB · "
        "会话归档 %d文件/%.1fMB · sessions.jsonl %s条/%.0fKB · "
        "experience.db %.0fKB · search.db %.0fKB",
        total_size / 1048576, total_files, exps, _one("experience.jsonl") / 1024,
        sess_files, sess_size / 1048576, arch, _one("sessions.jsonl") / 1024,
        _one("experience.db") / 1024, _one("search.db") / 1024)


def _splash_frames(caption: str) -> dict:
    """预渲染闪屏整轮帧：SPLASH_CYCLE 每个表情各出一张 QPixmap。

    现状轮播每 450ms 一帧都重走 make_splash_pixmap（键构造 + 缓存查找，首轮
    还是缓存未命中的真绘制）；改为启动时一次画好整轮，轮播只 setPixmap。
    阶段文案变更时按新文案重出整轮（同一文案的帧在 qt_theme 里另有缓存）。
    """
    from app.gui.qt_splash import SPLASH_CYCLE, make_splash_pixmap

    frames: dict = {}
    for name in SPLASH_CYCLE:
        pm = make_splash_pixmap(name, caption=caption)
        if not pm.isNull():
            frames[name] = pm
    return frames


def _splash_frame(frames: dict, caption: str, name: str):
    """取「某表情 × 当前文案」的帧；缓存未命中则即时补绘并回填。

    启动时已把首轮整轮预渲染进 frames；文案变更后旧帧作废，此处只按需补绘
    （轮播 tick 每次至多补 1 帧 ~15ms），不整轮 6 帧同步重绘。
    """
    pm = frames.get(name)
    if pm is None:
        from app.gui.qt_splash import make_splash_pixmap

        pm = make_splash_pixmap(name, caption=caption)
        if pm is not None and not pm.isNull():
            frames[name] = pm
    return pm


def _splash_tick(splash, frames: dict, cycle: tuple, state: dict) -> None:
    """启动闪屏表情轮播一帧：换一个吉祥物表情（取预渲染帧）。失败静默跳过。"""
    try:
        state["i"] = (state["i"] + 1) % len(cycle)
        state["name"] = cycle[state["i"]]
        pm = _splash_frame(frames, state["caption"], state["name"])
        if pm is not None:
            splash.setPixmap(pm)
    except Exception:
        pass


def is_packaged() -> bool:
    """PyInstaller 打包运行时：sys.frozen 由 PyInstaller 设置。"""
    return bool(getattr(sys, "frozen", False))


def _headless_needs_gui() -> bool:
    """打包态 headless 是否需要 Qt 窗口：仅开机自启需要（托盘挂在 QApplication 上）。

    - GUI 拉起的引擎子进程（`_spawn_engine` 打 `EXPERIENTIA_NO_TRAY=1`）：不要
      托盘 → 不需要 Qt → 纯 Python 常驻（引擎线程全是 daemon，主线程睡即可）；
    - 开机自启（`autostart._daemon_command` = `exe --headless`，无该 env）：托盘
      图标是常驻入口的唯一可见面 → 仍跑隐藏 Qt 窗口。
    """
    return os.environ.get("EXPERIENTIA_NO_TRAY") != "1"


def _relaunch_helper(wait_pid: int) -> int:
    """分离重启 helper：
    等主进程退出（释放数据目录锁与 8101）后拉起新实例。返回退出码。"""
    deadline = time.time() + 120
    while time.time() < deadline:
        if _pid_exited(wait_pid):
            break
        time.sleep(0.5)
    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
    else:
        cmd = [sys.executable, str(Path(__file__).resolve().parent / "main.py")]
    try:
        if os.name == "nt":
            subprocess.Popen(
                cmd,
                creationflags=(subprocess.DETACHED_PROCESS
                               | subprocess.CREATE_NEW_PROCESS_GROUP))
        else:
            subprocess.Popen(cmd, start_new_session=True)
    except Exception as exc:
        print(f"[experientia] 重启失败：{exc}", file=sys.stderr)
        return 1
    return 0


# ---------- ：GUI 拉起的引擎子进程 ----------

# 引擎子进程句柄（全局唯一；关窗/退出时终止）。None = 本进程未拉起子进程
# （纯壳接入既有引擎、同进程回退、或 headless 引擎自身）。
_engine_child: "subprocess.Popen | None" = None


def _engine_command() -> list[str]:
    """引擎子进程启动命令（与 autostart 同口径）：源码 = <python> <main.py> --headless；
    打包 = 同一产物 + --headless。

    **不使用 multiprocessing**：冻结程序用 multiprocessing 必须在 __main__ 前
    freeze_support()，且 spawn 在 POSIX 冻结产物上有兼容限制；直接复用既有
    `--headless` 入口（纯 Python 引擎，无 Qt）规避这些坑。
    """
    if is_packaged():
        return [sys.executable, "--headless"]
    return [sys.executable, str(Path(__file__).resolve().parent / "main.py"),
            "--headless"]


def _spawn_engine() -> "subprocess.Popen":
    """拉起引擎子进程（GUI 不持锁——调用方须先释放 EngineLock，子进程成唯一写者）。

    - 子进程 env 剥掉 EXPERIENTIA_SHELL_MODE（它是引擎，不是壳），带上
      EXPERIENTIA_PARENT_PID（引擎侧父进程看护 + 本进程回收）与
      EXPERIENTIA_NO_TRAY=1（打包态隐藏窗口不再挂托盘，避免与 GUI 双图标）；
    - Windows 用 CREATE_NO_WINDOW 避免源码模式弹控制台窗口（打包 windowed 无控制台）。
    """
    env = dict(os.environ)
    env.pop("EXPERIENTIA_SHELL_MODE", None)
    env[PARENT_PID_ENV] = str(os.getpid())
    env["EXPERIENTIA_NO_TRAY"] = "1"
    kwargs: dict = {"env": env, "cwd": str(Path(__file__).resolve().parent)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(_engine_command(), **kwargs)


def _set_engine_child(p: "subprocess.Popen | None") -> None:
    """登记/清除引擎子进程句柄（退出时由 _terminate_engine_child 回收）。"""
    global _engine_child
    _engine_child = p


def _engine_child_alive(p: "subprocess.Popen", grace: float = 0.25) -> bool:
    """拉起后短促确认子进程没立即暴毙（解释器/导入/锁竞态等）。

    只等 grace 秒（默认 0.25s，对启动延迟可忽略）：正常启动的引擎不会在这么短
    内退出；退出即判死并回收（POSIX 僵尸），交由调用方 fail-open 回退同进程引擎。
    """
    time.sleep(grace)
    if p.poll() is None:
        return True
    try:
        p.wait(timeout=2)
    except Exception:  # noqa: BLE001 回收失败不影响判定
        pass
    return False


def _kill_child(p: "subprocess.Popen | None") -> None:
    """终止给定子进程句柄：terminate（SIGTERM/TerminateProcess）→ 等 8s → kill。

    幂等、绝不抛（退出与重拉路径都要用，异常不能拦住调用方）。
    """
    if p is None:
        return
    try:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
    except Exception:  # noqa: BLE001
        pass


def _terminate_engine_child() -> None:
    """终止本进程拉起的引擎子进程（D1：关窗/退出连引擎一起退）。

    同时置停看护表（阶段 2）：退出过程中绝不再重拉子进程。幂等、绝不抛——
    退出路径上的异常不能拦住 GUI 关闭。父进程崩溃的兜底由引擎侧父进程看护负责。
    """
    global _engine_child
    _engine_watch_stop.set()
    p = _engine_child
    if p is None:
        return
    _engine_child = None
    _kill_child(p)


# ----------  阶段 2：引擎看护（掉线自愈 + 僵死判死重拉）----------

# 只在本进程**自己拉起了**引擎子进程时启用（_engine_child 非空）。接入既有实例
# （shell_mode，归属外部/开机自启）或同进程回退不在此列——前者不该被本进程抢管，
# 后者根本没有子进程可拉。
ENGINE_WATCH_INTERVAL = 15.0      # 巡检周期（秒）
ENGINE_WATCH_PROBE_TIMEOUT = 8.0  # HTTP 探活超时（超时 = 无响应）
ENGINE_WATCH_STRIKES = 2          # 连续几次「进程活着但 8101 不响应」才判僵死
ENGINE_WATCH_MAX_RESTARTS = 5     # 连续重拉上限（对齐 daemon.PROXY_MAX_RETRIES 口径）
_engine_watch_stop = threading.Event()


def _engine_responding(api_token: str, *, timeout: float) -> bool:
    """引擎的 8101 是否在听且能响应（HTTP 层探活）。

    只在本进程确认子进程**还活着**（Popen.poll() 为 None）时才调用——此时端口
    必在监听，探测毫秒级返回，不会触发"对未监听端口的出站审计"。
    """
    return engine.probe_local_api(api_token=api_token, timeout=timeout) is not None


def _restart_engine() -> None:
    """重拉引擎子进程：先收掉旧句柄（活得先杀、死的直接清），再拉新的。

    fail-open：旧进程收不掉、或新进程拉不起来/立即暴毙 → 只记日志并清句柄，
    由看护循环按上限继续尝试，绝不抛进循环。

    起句先看停表——退出瞬间若看护线程正好巡检到"掉线"
    并进入本函数，`_set_engine_child(None)` 之后新拉的子进程会被重新登记，
    而 `_terminate_engine_child` 已经跑完 → 退出时漏杀一个孤儿引擎进程。
    """
    if _engine_watch_stop.is_set():
        log.info("看护已停，跳过引擎重拉（退出路径）")
        return
    _kill_child(_engine_child)
    _set_engine_child(None)
    try:
        child = _spawn_engine()
    except Exception as exc:  # noqa: BLE001
        log.warning("引擎重拉失败: %s", exc)
        return
    if not _engine_child_alive(child):
        log.warning("引擎重拉后立即退出（code=%s）", child.returncode)
        return
    _set_engine_child(child)
    log.info("引擎已重拉（pid=%s）", child.pid)


def _engine_watchdog_loop(api_token: str, stop: threading.Event) -> None:
    """引擎看护循环（阶段 2，跑在后台守护线程里）。

    判死两条路：
    - **进程已退出**（Popen.poll() 非 None）→ 直接重拉（最可靠，无 HTTP 歧义）；
    - **进程活着但 8101 连续 STRIKES 次不响应** → 判僵死重拉。要求"连续"是为了
      不误杀正在干重活（解析大档）的引擎——它可能短暂把 8101 压慢，但不该被杀。
    健康一轮即清零计数（与 daemon._watch_proxy 同口径）。连续重拉达上限则放弃
    （端口被别的进程占住时重拉只会刷屏）。
    """
    strikes = 0
    restarts = 0
    while not stop.wait(ENGINE_WATCH_INTERVAL):
        child = _engine_child
        if child is None:
            return  # 归属已变（退出 / 回退同进程）：停表
        if child.poll() is not None:
            log.warning("引擎子进程已退出（code=%s），重拉", child.returncode)
        elif _engine_responding(api_token, timeout=ENGINE_WATCH_PROBE_TIMEOUT):
            strikes = 0
            restarts = 0
            continue
        else:
            strikes += 1
            if strikes < ENGINE_WATCH_STRIKES:
                log.info("引擎探活无响应（%d/%d），继续观察", strikes,
                         ENGINE_WATCH_STRIKES)
                continue
            log.warning("引擎连续 %d 次无响应，判为僵死，重拉", strikes)
        if restarts >= ENGINE_WATCH_MAX_RESTARTS:
            log.error("引擎连续重拉已达上限（%d），放弃自动恢复", restarts)
            return
        restarts += 1
        strikes = 0
        _restart_engine()


def _start_engine_watchdog(api_token: str) -> None:
    """起引擎看护线程（阶段 2）；只在 GUI 自己拉起了引擎子进程时调用。"""
    _engine_watch_stop.clear()
    threading.Thread(target=_engine_watchdog_loop,
                     args=(api_token, _engine_watch_stop),
                     name="experientia-engine-watch", daemon=True).start()


def _run_gui(store: Store, hidden: bool = False,
             warm_detect: Callable[[], None] | None = None) -> None:
    """GUI 外壳（PySide6）：MainWindow 经本地 API 与引擎通信。

    迁移清单：Flet ft.run() → QApplication.exec()；Qt 原生加载资源。
    warm_detect：agent 探测预热（自起后台线程）。起由本函数在**闪屏
    撤幕之后**调度，不再由 main() 在窗口构建前抢跑（避免与首帧争磁盘）。
    """
    _phase("GUI 入口")
    import sys

    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("GUI 外壳未安装；引擎已在后台运行。")
        print("安装 GUI 依赖: uv pip install PySide6")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    from app.gui import i18n
    from app.gui.main_window import MainWindow
    from app.gui.qt_theme import APP_STYLESHEET, apply_text_palette
    from app.gui.theme import C, resolve_theme_mode

    # locale 存 config.json，默认跟随系统
    locale = store.load_config().get("locale") or i18n.detect_system_locale()
    i18n.load_catalog(locale)

    app = QApplication(sys.argv)
    app.setApplicationName("Experientia")
    # D1：退出应用时连引擎子进程一起退（托盘「退出」→ QApplication.quit()
    # → aboutToQuit；关窗只藏托盘、应用仍在，子进程继续跑，符合退出语义）。
    app.aboutToQuit.connect(_terminate_engine_child)
    # 应用级窗口图标：让所有顶层窗口（主窗/对话框/任务栏固定预览）统一
    # 继承 assets/icon_windows.ico——不在 _MEIPASS 不在时静默回退，
    # 避免 Qt 默认图标覆盖品牌（任务栏缩略/Alt-Tab 都看这张）。
    try:
        from PySide6.QtGui import QIcon
        ico = Path(__file__).resolve().parent / "assets" / "icon_windows.ico"
        if ico.exists():
            app.setWindowIcon(QIcon(str(ico)))
    except Exception:
        pass
    # dark mode：ui_theme 存 config.json（light/dark/system，缺省 system 跟随系统）
    ui_theme = store.load_config().get("ui_theme") or "system"
    C.set_mode(resolve_theme_mode(ui_theme, app))
    app.setStyleSheet(APP_STYLESHEET())
    apply_text_palette()  # P2-1：占位符/禁用文字 → ink_500（5.33:1）
    _phase("QApplication 就绪")

    # 品牌闪屏动画：表情包轮播 + 阶段文字（启动引擎…→加载首页…→界面已就绪），
    # 覆盖「主窗口构建 + 首帧绘制」的观感空白（开机自启隐藏模式不闪屏）
    splash = None
    _splash_timer = None
    if not hidden:
        try:
            import socket
            import httpx as _httpx
            from app.gui.i18n import t as _t
            from app.gui.qt_splash import SPLASH_CYCLE
            from PySide6.QtCore import Qt as _Qt
            from PySide6.QtCore import QTimer as _QtTimer
            from PySide6.QtWidgets import QSplashScreen

            _splash_state: dict = {
                "i": 0,
                "name": SPLASH_CYCLE[0],
                "caption": _t("启动引擎…"),
            }
            # 一次预渲染整轮帧（6 张，实测 ~64ms），轮播只 setPixmap
            _splash_frames_cache: dict = _splash_frames(_splash_state["caption"])
            _pm = _splash_frames_cache.get(_splash_state["name"])
            if _pm is not None and not _pm.isNull():
                splash = QSplashScreen(_pm)
                # 关键：主窗口 show() 会盖住后建/后 show 的闪屏——白屏元凶。
                # 置顶保证闪屏始终压在主窗口（未绘制白底）之上。
                splash.setWindowFlag(_Qt.WindowType.WindowStaysOnTopHint, True)
                splash.show()
                QApplication.processEvents()

                def _set_splash_stage(text: str) -> None:
                    """主线程更新阶段文案（旧文案帧作废，当前表情即时补绘一帧）。

                    不整轮 6 帧同步重绘——文案变更恰好落在"撤幕/揭幕"
                    关键路径上（加载首页…/界面已就绪），整轮 ~91ms 会顶到首帧；
                    只补当前表情一帧（~15ms），其余表情由轮播 tick 按需补绘。
                    """
                    if splash is None:
                        return
                    try:
                        _splash_state["caption"] = text
                        _splash_frames_cache.clear()
                        pm = _splash_frame(_splash_frames_cache, text,
                                           _splash_state["name"])
                        if pm is not None:
                            splash.setPixmap(pm)
                    except Exception:
                        pass

                _splash_timer = _QtTimer()
                _splash_timer.timeout.connect(
                    lambda: _splash_tick(splash, _splash_frames_cache,
                                         SPLASH_CYCLE, _splash_state))
                _splash_timer.start(450)  # 每 450ms 换一个表情
                _phase("闪屏已显示（表情轮播+阶段文字）")
        except Exception:
            splash = None  # 闪屏任何失败都不阻塞启动

    window = MainWindow(store)
    _phase("主窗口已构建")
    if hidden:
        window.hide()  # 开机自启：只留托盘图标
        if warm_detect is not None:
            QTimer.singleShot(0, warm_detect)  # 隐藏模式无闪屏，构建完即预热
    else:
        window.show()
        # 首帧白屏防护：show 后先冲刷一次事件（样式表 polish + 首帧入队），
        # 再延迟撤闪屏——让主窗口在闪屏底下完成第一次真实绘制后才揭开，
        # 避免 Windows 上"窗口已 show 但首帧未画完"的纯白空窗暴露给用户。
        QApplication.processEvents()
        _phase("首帧绘制完成")
        if splash is not None:
            # window.show() 之后再把闪屏顶回最前（置顶 + 激活双保险）
            splash.raise_()
            splash.activateWindow()

            _reveal_done = {"v": False}

            def _drain_and_reveal() -> None:
                """主线程：引擎就绪后完成首页首刷并排空 paint，再撤闪屏。

                白屏根因链：引擎本地 API 未就绪时首页 refresh 的 6 个并发请求
                撞"端口未监听 ~2s 审计"，主线程被同步堵住、paint 事件无法执行；
                等时钟撤屏就露出未绘制的纯白。改为「就绪→首刷→排空→揭幕」。
                """
                log.info("[boot] _drain_and_reveal enter（v=%s）", _reveal_done["v"])
                if _reveal_done["v"]:  # 幂等：就绪通道与 8s 兜底只揭一次
                    return
                _reveal_done["v"] = True
                try:
                    window._refresh_page_by_name("home")  # API 已就绪，请求快速
                    for _ in range(6):
                        QApplication.sendPostedEvents()
                        QApplication.processEvents()
                        window.repaint()
                    _set_splash_stage(_t("界面已就绪"))
                    QApplication.processEvents()
                    window.repaint()
                except Exception as exc:
                    log.warning("[boot] _drain_and_reveal 前置步骤异常: %s", exc)
                # 撤屏（按"最难失败"顺序：先 cancel token，再 hide，再 close，再 finish，
                # 最后 deleteLater；任何一步都不抛整体，splash 必定收起）
                if _splash_timer is not None:
                    try:
                        _splash_timer.stop()
                    except Exception:
                        pass
                for action in (
                    lambda: splash.finish(window),
                    splash.hide,
                    splash.close,
                ):
                    try:
                        action()
                    except Exception as exc:
                        log.warning("[boot] splash 撤幕动作失败 %s: %s",
                                    getattr(action, "__name__", "?"), exc)
                try:
                    splash.deleteLater()
                except Exception:
                    pass
                log.info("[boot] _drain_and_reveal 撤幕完成")
                # 闪屏撤幕后才起探测预热线程（避免与首帧争磁盘）
                if warm_detect is not None:
                    QTimer.singleShot(0, warm_detect)

            def _on_ready() -> None:
                """引擎就绪：回主线程切到「加载首页…」并开始收尾。"""
                _set_splash_stage(_t("加载首页…"))
                QTimer.singleShot(0, _drain_and_reveal)

            def _poll_step() -> None:
                """主线程递归探测（杜绝 worker 线程 QTimer 失效）：

                - bind 快通道：bind 失败 ≈ 端口被占用（端口空闲时绝不打 httpx，
                  避免对未监听端口反复出站触发 ~2s 安全软件审计）；
                - httpx 权威通道：仅在 bind 认为可能就绪时打一次（端口在听、连接毫秒级）；
                - 任一通道报就绪立即调用 _on_ready；过期 8s 由兜底 _drain_and_reveal 收尾。
                """
                if _reveal_done["v"]:
                    return
                port = engine.LOCAL_API_PORT
                bind_failed = False
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    s.bind(("127.0.0.1", port))
                    s.close()
                    bind_failed = False  # bind OK：端口空闲，引擎未就绪
                except OSError:
                    bind_failed = True  # 端口已被占用 → 可能就绪
                except Exception:
                    bind_failed = True
                if bind_failed:
                    try:
                        uri = f"http://127.0.0.1:{port}/api/status?lite=1"
                        if _httpx.get(uri, timeout=1.5).status_code == 200:
                            _on_ready()
                            return
                    except Exception:
                        pass
                QTimer.singleShot(120, _poll_step)

            # 主线程调度（与 app.exec() 同线程，QTimer 可靠）
            QTimer.singleShot(0, _poll_step)
            # 兜底：8 秒内无论结果如何强制揭幕，绝不无限轮播
            QTimer.singleShot(8000, _drain_and_reveal)
        else:
            QApplication.processEvents()
            if warm_detect is not None:
                QTimer.singleShot(0, warm_detect)  # 闪屏不可用：构建完即预热
    _phase("窗口显示完成")
    sys.exit(app.exec())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="experientia-gui")
    parser.add_argument("--headless", action="store_true", help="仅引擎，无 GUI")
    parser.add_argument("--relaunch-helper", nargs=1, default=None,
                        metavar="PID", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.relaunch_helper:
        try:
            sys.exit(_relaunch_helper(int(args.relaunch_helper[0])))
        except ValueError:
            print("helper 参数无效", file=sys.stderr)
            sys.exit(2)

    from app.log_conf import setup_logging

    # /：GUI 的 [boot]/[page] 打点落 gui.log；--headless（引擎进程）
    # 落 engine.log——两进程分文件，避免同文件 RotatingFileHandler 轮转互踩。
    # 轮转沿用默认 5MB×5，路径经 Store 暴露的 default_*_log_file（不裸拼）。
    setup_logging(log_file=(default_engine_log_file() if args.headless
                            else default_log_file()))
    _phase("日志就绪（模块 import 完成）")
    # 清理上次更换数据目录遗留的旧目录（引擎未启动，无文件锁）
    cleanup_pending_data_dir()
    store = Store()
    store.ensure_layout()
    _phase("Store 就绪")
    _log_capacity(store)  # 每次启动记一条数据规模（轻量）

    # 单实例探活需带自己的 token（api/status 的 data_dir 现仅对鉴权调用方
    # 回显）。ensure_api_token 幂等、无网络，且与下面 GUI 外壳注入的 env token 同源。
    from app.token_util import TOKEN_ENV, ensure_api_token
    _api_token = ensure_api_token(store.data_dir)
    _phase("token 工具就绪（轻量 import）")

    # M-4 单实例：数据目录进程锁 + 8101 探活（补不同数据目录的实例）。
    # 纯壳模式：同数据目录已有活实例（daemon/开机自启）→ 外壳只连 HTTP 不启引擎，
    # 窗口关闭只退壳；不同数据目录仍拒绝（8101 固定端口，两实例共存不了）。
    from app.platform.engine_lock import EngineLock

    shell_mode = False
    lock = EngineLock(store.data_dir)
    _phase("engine_lock 已构造")
    if not lock.acquire():
        running = engine.probe_local_api(api_token=_api_token)
        if running and running == str(store.data_dir):
            shell_mode = True
            log.info("检测到同数据目录的活实例（%s）：进入纯壳模式，不启动重复引擎", running)
        else:
            print(f"experientia 已在运行（数据目录 {store.data_dir}），不启动重复引擎。")
            sys.exit(1)
    else:
        # 启动提速：先本地 bind 探测端口占用（不出站、不触发本机安全软件对新
        # TCP 连接 ~2s 的审计延迟），空闲即视为无活实例；仅当 8101 真被占才
        # 做 httpx 慢探测拿数据目录（该路径只在"确有冲突"时发生）。
        running = None
        try:
            import socket

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("127.0.0.1", engine.LOCAL_API_PORT))
                s.close()
            except OSError:
                running = engine.probe_local_api(api_token=_api_token)
            finally:
                try:
                    s.close()
                except OSError:
                    pass
        except Exception:
            running = engine.probe_local_api(api_token=_api_token)
        if running is not None:
            print(f"本地 API 8101 已有活实例（数据目录 {running}），不启动重复引擎。")
            sys.exit(1)

    # GUI 外壳经 env 取 8101 鉴权 token；token 已在探测前
    # ensure（幂等、与本地 API 线程同源），此处直接注入给外壳。
    _phase("单实例探测完成")
    os.environ[TOKEN_ENV] = _api_token
    if shell_mode:
        os.environ["EXPERIENTIA_SHELL_MODE"] = "1"  # 设置页据此显示"已连接运行中实例"
    elif "EXPERIENTIA_SHELL_MODE" in os.environ:
        del os.environ["EXPERIENTIA_SHELL_MODE"]
    _phase("单实例/API token 就绪")

    # ---------- 引擎归属决策----------
    # shell_mode        ：同数据目录已有活引擎 → 本进程纯壳接入（不启引擎、不预热）
    # headless / INPROC ：本进程就是引擎（旧同进程路径；INPROC 为回退开关）
    # 其余（GUI 常规启动）：不持锁，拉引擎子进程，本进程走纯壳——引擎重活
    # （扫描/归档解析/探测）彻底移出 GUI 进程，不再与界面抢 GIL
    warm_detect: Callable[[], None] | None = None

    def _warm_detect() -> None:
        """预热 agent 探测缓存：全盘探测 ~1.7s 放后台跑，GUI 首个 /api/status
        命中缓存，不把冷探测开销压在启动首帧/首屏（M10 TTL 已由 scan_loop
        每轮 prime_cache 回填，这里只保证"第一次"也快）。

        本函数只负责起线程（不阻塞调用方）——由 _run_gui 在撤幕之后调用。
        """
        def _probe() -> None:
            try:
                from app.capture.registry import detect as _detect
                found = _detect()
                # 预热结果落盘快照，GUI 后续 /api/status、/api/agents
                # 直读（不再触发探测）。
                try:
                    store.save_agents_snapshot(
                        {a: len(r) for a, r in found.items()})
                except Exception:
                    pass
            except Exception:
                pass  # 预热失败只影响首帧速度，不影响功能

        threading.Thread(target=_probe, name="experientia-detect-warm",
                         daemon=True).start()

    def _start_inproc_engine() -> None:
        """本进程起引擎（headless 引擎自身 / INPROC 回退）：代理 + 本地 API +
        扫描循环（后台线程），并开放探测预热（同进程才归本进程管）。"""
        nonlocal warm_detect
        _phase("引擎线程启动前")
        try:
            port = engine.start_servers(store)
            # spawn 兜底：scan_loop 主体虽自吞异常，但看护/挂起恢复等路径在线程
            # 外抛过一次就会让扫描线程静默死亡（教训，见 thread_util）。
            spawn(engine.scan_loop, store, port, name="experientia-scan")
            _phase("引擎线程已启动")
            log.info("引擎已启动：代理 127.0.0.1:%s，本地 API 127.0.0.1:%s",
                     port, engine.LOCAL_API_PORT)
        except Exception:
            log.exception("引擎启动失败")
            raise
        warm_detect = _warm_detect

    def _fallback_inproc() -> None:
        """拆进程失败的回退（fail-open）：重新拿锁起同进程引擎；拿不到锁 =
        确实已有别的实例占用，维持拒绝。"""
        if lock.acquire():
            log.info("回退同进程引擎（T2.1 fail-open）")
            _start_inproc_engine()
        else:
            print(f"experientia 已在运行（数据目录 {store.data_dir}），不启动重复引擎。")
            sys.exit(1)

    if shell_mode:
        pass  # 接入既有引擎：不启引擎、不预热（探测缓存归引擎进程管）
    elif args.headless or os.environ.get("EXPERIENTIA_INPROC_ENGINE") == "1":
        _start_inproc_engine()
    else:
        child = None
        try:
            lock.release()  # 交还数据目录锁：子进程成唯一写者（GUI 不得持锁起子进程）
        except Exception:
            pass
        try:
            child = _spawn_engine()
        except Exception as exc:
            log.warning("引擎子进程拉起失败（回退同进程引擎）: %s", exc)
        if child is not None and _engine_child_alive(child):
            _set_engine_child(child)
            os.environ["EXPERIENTIA_SHELL_MODE"] = "1"  # 引擎在子进程里 → GUI 纯壳
            log.info("引擎已拆为子进程（pid=%s），GUI 走纯壳模式", child.pid)
            _start_engine_watchdog(_api_token)  # 阶段 2：掉线自愈 + 僵死重拉
        else:
            if child is not None:
                log.warning("引擎子进程立即退出（code=%s），回退同进程引擎",
                            child.returncode)
            _fallback_inproc()

    if args.headless:
        # headless = 引擎进程。
        if shell_mode:
            print("引擎已在运行（纯壳模式不适用 headless），直接退出。")
            return
        # 父进程看护（D1）：GUI 关窗/崩溃后本进程随之退出；无父 pid
        # （开机自启/手工 headless）则常驻。
        _parent = os.environ.get(PARENT_PID_ENV, "")
        if _parent.isdigit():
            from app.platform.proc_util import start_parent_watch
            start_parent_watch(int(_parent))
            log.info("父进程看护已启用：父 pid=%s（父退出则引擎退出，T2.1）", _parent)
        if is_packaged() and _headless_needs_gui():
            # 开机自启的 headless（autostart：`exe --headless`，不带 NO_TRAY）：
            # 托盘图标只挂在 QApplication 上 → 仍跑隐藏 Qt 窗口。
            _run_gui(store, hidden=True, warm_detect=warm_detect)
            return
        # 其余 headless：源码模式 / 打包态 GUI 拉起的引擎子进程（`_spawn_engine`
        # 打 EXPERIENTIA_NO_TRAY=1，不需要托盘）→ 纯 Python 常驻：不 import
        # PySide6 的 GUI 部分（QtGui/QtWidgets）、不建 MainWindow、不起 Qt 事件
        # 循环；引擎线程全是 daemon，主线程睡即可。
        # 打包态子进程此前也走上面的隐藏 Qt 窗口——整套 PySide6
        # （~47MB）+ MainWindow 被塞进本该无脸的引擎进程：更重，且引擎的死活被
        # Qt 初始化绑住（Qt 起不来后台服务跟着死），MainWindow 的轮询/刷新还在
        # 引擎进程里空转。现在只有开机自启（要托盘）才加载 GUI。
        # 唯一残留：PySide6.QtCore（~6MB）仍会被加载——PyInstaller 的 pyside6
        # runtime hook（pyi_rth_pyside6）在每个冻结进程启动时 import 它建
        # qt.conf，同一二进制的 GUI 进程要靠它定位 Qt 插件，无法只在子进程关掉。
        log.info("headless 常驻（不加载 GUI）")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    _run_gui(store, warm_detect=warm_detect)


if __name__ == "__main__":
    main()
