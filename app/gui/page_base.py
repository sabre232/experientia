"""页面基类（所有页面继承）——Qt 版（迁移清单）。

- 构造函数签名：__init__(self, api, parent)
- 子类在 __init__ 中调用 self._build() 构建 UI，覆盖 refresh() 刷新数据
- set_status(msg, tone) 写状态行（语义色）
- go(name) 页面跳转 / toast(msg) 底部消息（经主窗口）
- run_async(fn, on_done, on_error) 后台线程执行（Flet page.run_thread 的 Qt 版）
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QEvent, QThread, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea,
                                QSizePolicy, QVBoxLayout, QWidget)

from .api_client import LocalApi, LocalApiError
from .i18n import t
from .theme import C, F, S, SIZES, THRESHOLDS

_logger = logging.getLogger("experientia.gui.page_base")


def _has_horizontal_stretch(layout, _depth: int = 0) -> bool:
    """布局（含嵌套子布局）里是否有**水平 Expanding** 的 spacer。

    ``addStretch(1)`` 会往 ``QBoxLayout`` 里放一个水平 Expanding 的 spacer——
    页头 / 状态行 / 筛选行都是这个形状，故它是"这一行是静态外壳、不是数据区"
    的可核实信号（用于 ``_skeleton_insert_index`` 决定骨架插在哪）。
    递归下探子布局与子控件布局；深度上限防环。
    """
    if layout is None or _depth > 4:
        return False
    for i in range(layout.count()):
        item = layout.itemAt(i)
        sp = item.spacerItem()
        if sp is not None:
            try:
                pol = sp.sizePolicy().horizontalPolicy()
                if pol in (QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.MinimumExpanding):
                    return True
            except Exception:  # noqa: BLE001
                pass
            continue
        sub = item.layout()
        if sub is not None and _has_horizontal_stretch(sub, _depth + 1):
            return True
        w = item.widget()
        if (w is not None and w.layout() is not None
                and _has_horizontal_stretch(w.layout(), _depth + 1)):
            return True
    return False


def parallel_fetch(calls: dict[str, callable],
                   timeout: float = 20.0,
                   max_workers: int | None = None) -> dict:
    """并发执行若干命名只读请求（工作线程内完成网络 IO）。

    - 返回 {name: result}；单项失败返回 None（不中断其余项）并记 warning。
    - 只做取数，绝不在此触碰任何 widget——UI 更新由调用方在主线程完成。
    - 依赖 shared httpx.Client（LocalApi）的线程安全性；结果收集完即退出线程池。
    """
    if not calls:
        return {}
    out: dict = {}
    n = min(len(calls), max_workers or 5)
    with ThreadPoolExecutor(max_workers=max(1, n),
                            thread_name_prefix="exp-page") as pool:
        fut = {pool.submit(fn): name for name, fn in calls.items()}
        for f in as_completed(fut):
            name = fut[f]
            try:
                out[name] = f.result(timeout=timeout)
            except Exception as exc:  # noqa: BLE001 并行取数单项失败不拖垮整页
                _logger.warning("并行取数 %s 失败: %s", name, exc)
                out[name] = None
    return out


def content_sig(payload) -> str:
    """结构签名：判断"这一条到底变没变"（列表增量 diff 的判据）。

    放在基类而不是某个列表页里：经验/方法/坑三页（以及成长页）共用同一口径，
    一处改口径就会漂移。
    """
    try:
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return repr(payload)


def sync_tracked(lay, store: dict, want: list) -> None:
    """按 key 增量同步一个布局里的卡片（替代「清空 + 全建」）。

    ``want = [(key, sig, factory)]``：

    - key 命中且 sig 未变 → 控件**原地不动**（不丢 hover / 动画 / 焦点）；
    - sig 变 → 原位替换；
    - 新 key → 插入；消失的 key → 删除；
    - 布局里未被 ``store`` 追踪的遗留控件（空态/提示）先清掉。

    口径与 ``content_sig`` 配套，三页共用同一实现。
    """
    tracked = {e["w"] for e in store.values()}
    for i in reversed(range(lay.count())):
        w = lay.itemAt(i).widget()
        if w is not None and w not in tracked:
            lay.takeAt(i)
            w.deleteLater()
    want_set = {k for k, _s, _f in want}
    for key in list(store):
        if key in want_set:
            continue
        entry = store.pop(key)
        i = lay.indexOf(entry["w"])
        if i >= 0:
            lay.takeAt(i)
        entry["w"].deleteLater()
    for idx, (key, sig, factory) in enumerate(want):
        entry = store.get(key)
        if entry is None:
            w = factory()
            lay.insertWidget(idx, w)
            store[key] = {"w": w, "sig": sig}
            continue
        if entry["sig"] != sig:
            new_w = factory()
            i = lay.indexOf(entry["w"])
            if i < 0:
                i = idx
            else:
                lay.takeAt(i)
            entry["w"].deleteLater()
            lay.insertWidget(i, new_w)
            entry["w"] = new_w
            entry["sig"] = sig
        cur = lay.indexOf(entry["w"])
        if cur != idx:
            lay.takeAt(cur)
            lay.insertWidget(idx, entry["w"])


_STATUS_QSS: dict[str, str] = {}


def _status_qss(color: str, size: int) -> str:
    """状态行样式串缓存（同色同字号复用，避免每次调用重拼）。"""
    key = f"{color}|{size}"
    qss = _STATUS_QSS.get(key)
    if qss is None:
        qss = (f"color: {color}; background: transparent; border: none;"
               f" font-size: {size}px;")
        _STATUS_QSS[key] = qss
    return qss


def clear_layout(layout) -> None:
    """移除布局内所有子项（含嵌套布局），7 处重复实现统一入口。"""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


class ApiWorker(QThread):
    """后台 API 调用线程（迁移清单：distill/check 等长超时不阻塞 UI）。"""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.finished.emit(self._fn())
        except Exception as exc:  # noqa: BLE001  后台线程错误统一收口
            self.error.emit(str(exc))


class _FetchWorker(QThread):
    """页面取数专用后台线程：整段 fetch 在工作线程完成，主线程零 HTTP。

    单项异常按 parallel_fetch 同口径收敛为 None（单项失败不拖垮整页渲染），
    worker 内部绝不触碰任何 widget。"""

    done = Signal(object)

    def __init__(self, fetch, parent=None):
        super().__init__(parent)
        self._fetch = fetch

    def run(self) -> None:
        try:
            self.done.emit(self._fetch())
        except Exception as exc:  # noqa: BLE001  取数整体失败也要留痕
            _logger.warning("页面后台取数失败: %s", exc)
            self.done.emit(None)


class PageBase(QWidget):
    """所有页面继承此类。

    子类必须：
    - 在 __init__ 中调用 self._build() 构建 UI
    - 覆盖 refresh() 在导航切换时刷新数据
    """

    def __init__(self, api: LocalApi, parent: QWidget | None = None):
        super().__init__(parent)
        self.api = api
        self._status_bar: QLabel | None = None  # 由父窗口注入
        self._last_error: str = ""  # SYS-5：最近一次页面错误（测试/调试可读）
        self._fetches: dict[str, _FetchWorker] = {}  # fetch_and_render 在飞任务（按名去重）
        self._threads: set[QThread] = set()  # run_async 在飞线程（销毁前统一收尾）
        self._content_ready = False  # 页面内容是否已落地（决定骨架是否再插，见 fetch_and_render）
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    # ---------- 生命周期：销毁前收尾在飞线程 ----------

    def _skeleton_host_layout(self):
        """本页「内容列」布局（骨架该插入的位置）——**永不返回 None**。

        口径：骨架是"占位未到位的真实内容"，就该落在**内容列**里——而**不是**当页面
        布局的兄弟控件。骨架块是 Fixed 高度（合计常 400~550px），塞进页面布局会跟
        唯一的滚动区争高：实测页面 678px 时滚动区被挤到 122px（82% 版面被几道灰条
        占满）→ 任何页面每次加载都长得像"整页空白"。放进内容列后滚动区保持满高，
        骨架只是内容顶部的一段占位，页头与页壳照常可见。

        解析顺序（每一步都"可核实"，不猜）：

        1. **统一滚动骨架**：``_layout`` 里的 ``QScrollArea`` → 其内容列。
           结构由 ``build_centered_scroll`` 唯一决定：
           ``根 _layout → QScrollArea → inner(outer) → content(内容列)``。
        2. **内嵌页约定**：可见内容包在 ``self.content`` 里（此时根 ``_layout`` 为空，
           如 ModelsPage / InjectPreviewPage 内嵌于接入页/导出页）→ ``content`` 的布局。
           此前没有这一条，内嵌页的骨架被插进**看不见**的根 ``_layout``（占位等于没挂）。
        3. **页面根本身就是内容列**（无滚动、无 ``content`` 包装）→ ``_layout``。
        """
        try:
            # 1) 统一滚动骨架 → 内容列
            lay = self._layout
            for i in range(lay.count()):
                w = lay.itemAt(i).widget()
                if not isinstance(w, QScrollArea):
                    continue
                inner = w.widget()
                outer = inner.layout() if inner is not None else None
                if outer is None:
                    continue
                for j in range(outer.count()):
                    col = outer.itemAt(j).widget()
                    if col is not None and col.layout() is not None:
                        return col.layout()
            # 2) 内嵌页约定 → self.content 的布局
            content = getattr(self, "content", None)
            if (content is not None and content is not self
                    and content.layout() is not None):
                return content.layout()
        except Exception as exc:  # noqa: BLE001 结构探测失败不阻断取数
            _logger.warning("内容列定位失败，骨架退回页面布局: %s", exc)
        # 3) 页面根本身就是内容列
        return self._layout

    @staticmethod
    def _skeleton_insert_index(host) -> int:
        """骨架在内容列里的插入下标：首项是**静态外壳行**时插到它之后（=1），
        否则插到最前（=0）。任何异常都退回 0（fail-open）。

        "静态外壳行"= 页头 / 状态行 / 筛选行——骨架要占的是它**下面**的数据区：
        - 首项内含 ``QLabel#pageTitle``（统一页头 ``page_header()`` 的约定）；
        - 首项是横向行：其布局含水平 Expanding 的 spacer（``addStretch(1)`` 的
          产物）——页头、状态行、筛选/工具行都是这个形状。
        插到 0 会把外壳整个下推，取数结束再弹回（多余的布局跳动）。
        """
        try:
            if host is None or host.count() == 0:
                return 0
            first = host.itemAt(0)
            w = first.widget()
            if w is not None:
                if w.findChild(QLabel, "pageTitle"):
                    return 1
                lay = w.layout()
            else:
                lay = first.layout()  # 首项本身就是布局（未包 QWidget 的行）
            if lay is not None and _has_horizontal_stretch(lay):
                return 1
        except Exception:  # noqa: BLE001
            pass
        return 0

    def _wait_inflight(self, timeout_ms: int = 5000) -> None:
        """等本页所有在飞后台线程收尾（销毁页面前的安全闸）。

        Qt 销毁一个仍在运行的 ``QThread`` 子对象会直接 abort（Windows
        ``0xC0000409``，无 Python 栈）——父窗口重建 / 语言·主题切换删页时，
        若取数或 run_async 线程还在跑就会硬崩。故删页前先 ``wait()``。
        """
        workers = list(self._fetches.values()) + list(self._threads)
        # 总预算替代每项预算。逐个 wait(5000) 在最坏
        # 情况（N 页 × M 个在飞任务且都卡住）会把主线程堵 5s×N×M——切语言/
        # 主题重建页面时表现为界面假死数十秒。改为整体 timeout_ms 封顶，
        # 超时即不再等（DeferredDelete 路径上 Qt 自身还有兜底，不会 abort）。
        deadline = time.monotonic() + timeout_ms / 1000.0
        for w in workers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                if w.isRunning():
                    w.wait(int(remaining * 1000))
            except RuntimeError:
                pass  # 底层 C++ 对象已销毁（Python 包装失效），无需再等

    def event(self, e) -> bool:
        # DeferredDelete 是 deleteLater / 三步删除法的必经事件：在真正析构
        # 之前先把在飞线程收尾，避免 QThread 随父对象析构时 abort。
        if e.type() == QEvent.Type.DeferredDelete:
            self._wait_inflight()
        return super().event(e)

    # ---------- 父窗口服务 ----------

    @property
    def _mw(self):
        """主窗口（用于 go / toast）。"""
        w = self.window()
        return w if w is not self else None

    def go(self, name: str) -> None:
        """页面跳转（对应 Flet shell.go）。"""
        mw = self._mw
        if mw is not None and hasattr(mw, "go"):
            mw.go(name)

    def toast(self, msg: str, duration: int = 5000) -> None:
        """底部消息条（对应 ui.toast / SnackBar）。"""
        mw = self._mw
        if mw is not None and hasattr(mw, "toast"):
            mw.toast(msg, duration)

    def set_status_bar(self, label: QLabel) -> None:
        """由 MainWindow 注入状态行引用。"""
        self._status_bar = label

    def set_status(self, msg: str, tone: str = "err") -> None:
        """写状态行（语义色）。tone ∈ ok/err/warn/info。"""
        if not self._status_bar:
            return
        colors = {"ok": C.ok_fg, "err": C.err_fg,
                  "warn": C.warn_fg, "info": C.info_fg}
        self._status_bar.setText(msg)
        # 保留 txt() 内联字号：setStyleSheet 整表覆写，不带 font-size 会塌回 14px
        qss = _status_qss(colors.get(tone, C.err_fg), F.caption)
        # 同一视觉状态下不重复 setStyleSheet——状态行刷新频繁，重复设置每
        # 次都触发 style re-polish。色板切换会改变 color 值 → 串不同 → 照常重设。
        if getattr(self, "_status_qss_applied", "") != qss:
            self._status_bar.setStyleSheet(qss)
            self._status_qss_applied = qss

    def report_error(self, msg: str) -> None:
        """SYS-5 统一错误呈现：记录最近错误 + 写状态行。

        页面数据/操作失败不得静默——能写状态行的写状态行，至少留 `_last_error`
        供调试与回归断言。msg 建议先用 t() 本地化再传入。
        """
        self._last_error = msg
        try:
            self.set_status(msg, "err")
        except Exception:
            pass

    def run_async(self, fn, on_done=None, on_error=None) -> None:
        """后台线程执行 fn；完成后回调（主线程）。对应 Flet page.run_thread。

        回调签名：on_done(result) / on_error(str)。
        """
        worker = ApiWorker(fn, self)
        self._threads.add(worker)
        if on_done:
            worker.finished.connect(on_done)
        if on_error:
            worker.error.connect(on_error)

        def _release(*_a):
            self._threads.discard(worker)

        # 先摘登记再 deleteLater：删页时 _wait_inflight 才能安全遍历
        worker.finished.connect(_release)
        worker.error.connect(_release)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        worker.start()

    def fetch_and_render(self, fetch, render, name: str = "refresh", *,
                         skeleton: list[int] | None = None) -> None:
        """：页面刷新的取数段整体挪后台线程，仅渲染回调
        留主线程——主线程零 HTTP。冷缓存窗口单请求 1.7-2.4s，旧式主线程
        parallel_fetch 让 30s 轮询周期各冻结一轮。

        - fetch() 在工作线程执行：只做网络取数，绝不触碰 widget；
        - render(result) 在主线程执行；fetch 抛异常 → result 为 None，
          页面按"数据不可用"自行降级渲染；
        - **render 自身抛异常也不外泄**：记 WARNING（落 gui.log）后收尾，页面展示
          已渲染的部分；且无论成败都置 ``_content_ready``——否则一次渲染缺陷会让
          页面被当成"永远没加载过"，每次刷新重放骨架屏（看着一直空白），且异常
          逃出 Qt 槽函数在打包态（无控制台）不可见；
        - 同名在飞去重：轮询撞上一个未跑完的周期直接跳过，不排队堆叠；
        - 页面销毁前由 ``event()`` 拦 ``DeferredDelete`` → ``_wait_inflight()`` 收尾
          在飞线程（QThread 仍在跑时随父对象析构会让 Qt abort）；
        - ``skeleton=list[int]`` 时挂一列骨架块占位：骨架先以隐藏态
          入本页**内容列**（``_skeleton_host_layout``：统一滚动区的内容列 / 内嵌页的
          ``content`` 容器 / 页面根本身；**绝不**当页面布局的兄弟控件——否则会跟唯一
          的滚动区争高，把整页挤成"只剩几道灰条"），且插在首行静态外壳（页头/状态/
          筛选行）**之后**（``_skeleton_insert_index``），取数达
          ``THRESHOLDS.SKELETON_MIN_MS`` 才显示——**取数快于此阈值就根本不显示**
          （避免"闪一下更差"）；render 前移除，异常也由 finally 兜底。
          **仅首屏挂**：``_content_ready`` 为真（已渲染过一轮）后不再插入——已有正文
          时插入骨架会把内容整体顶下去、取数结束再弹回，轮询页每 30s 跳一次。
        测试侧用 tests/conftest.py 的 pump_until(page) 等渲染完成。
        """
        inflight = self._fetches.get(name)
        if inflight is not None and inflight.isRunning():
            return
        # 不挂页面为父对象：QThread 作为子对象会一直挂在页面上（即使已结束），
        # 页面每刷新一次累积一个。改由 ``_fetches`` 持有引用，线程结束后摘除
        # 即可自然回收。页面销毁时的安全由 ``_wait_inflight`` 保证（登记在,
        # 就一定会被 wait）。
        worker = _FetchWorker(fetch)
        skel: QWidget | None = None
        skel_timer: QTimer | None = None
        skel_host = None  # 骨架所在布局（用于精确移除；见 _skeleton_host_layout）
        # 只在页面内容还没落地过（首屏）才插骨架。已有内容时插入会把正文
        # 顶下去、取数结束再弹回——轮询页（home 每 30s 一次）会看到整页下跳。
        if skeleton and not self._content_ready:
            try:
                from .qt_widgets import skeleton_column  # 懒导入防循环依赖
                skel = skeleton_column(list(skeleton))
                skel.hide()
                # **必须塞进本页「内容列」，不能当页面布局的兄弟控件**：
                # 骨架块是 Fixed 高度、合计可达 500+px，插到页面布局里会跟滚动区
                # 争高——实测滚动区被挤到 122/678px（页面 82% 被骨架盖住），看起来
                # 就是"整页空白，只剩几道灰条"。放进内容列则滚动区保持满高、骨架只
                # 作为内容顶部的占位，页头/页壳照常可见（含内嵌页的 content 容器）。
                skel_host = self._skeleton_host_layout()
                # 页头在内容列首项时，骨架插到页头**之后**——先看到标题再看到
                # 占位块，读起来是"这页在加载"，而不是"一堵灰墙"。
                skel_host.insertWidget(self._skeleton_insert_index(skel_host), skel)
                skel_timer = QTimer(self)
                skel_timer.setSingleShot(True)
                skel_timer.timeout.connect(skel.show)
                skel_timer.start(int(THRESHOLDS.SKELETON_MIN_MS))
            except Exception as exc:  # noqa: BLE001 骨架失败不影响正常取数
                _logger.warning("骨架屏挂载失败，跳过: %s", exc)
                skel, skel_timer, skel_host = None, None, None

        skel_fading = {"v": False}

        def _drop_skeleton() -> None:
            """移除骨架（M3：以**浮层淡出**过渡，替硬切）。

            M3 口径：骨架先从布局里摘掉（内容立刻占位、不被顶着），但**控件本体留在
            页面上原位**、作为浮层 120ms 淡出——这才是真正的"交叉"，而不是"先没后
            有"的硬切。要点：

            - 淡出**只给骨架这一个控件**挂 `QGraphicsOpacityEffect`（就是几个色块，
              开销有界）；**绝不**挂到整页/滚动区（项目明令禁止的用法）。
            - **幂等**：`_done` 与 `finally` 会各调一次；`skel_fading` 保证只淡一次。
            - **fail-open**：reduced-motion / 低特效 / 骨架不可见 / 任何异常 →
              走原来的**瞬时移除**路径，绝不因过渡失败留下残留浮层。
            """
            nonlocal skel, skel_timer, skel_host
            if skel_fading["v"]:
                return  # 已在淡出中：后一次调用直接让位
            if skel_timer is not None:
                try:
                    skel_timer.stop()
                    skel_timer.deleteLater()
                except Exception:
                    pass
                skel_timer = None
            if skel is None:
                return
            widget = skel
            skel = None  # 先摘引用：后续调用不再处理它

            try:
                geo = widget.geometry()  # 相对其所在内容列（淡出时原位保留）
                (skel_host or self._layout).removeWidget(widget)  # 内容立刻占位
            except Exception as exc:  # noqa: BLE001
                _logger.warning("骨架屏移除失败: %s", exc)
                return

            can_fade = False
            try:
                from .theme import ANIMATION, low_fx, motion_ok
                can_fade = (widget.isVisible() and motion_ok() and not low_fx())
            except Exception:  # noqa: BLE001
                can_fade = False

            if not can_fade:
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except Exception:  # noqa: BLE001
                    pass
                return

            try:
                from PySide6.QtCore import QPropertyAnimation
                from PySide6.QtWidgets import QGraphicsOpacityEffect

                from .qt_widgets import _ease
                widget.setGeometry(geo)  # 留在原位
                widget.raise_()
                eff = QGraphicsOpacityEffect(widget)
                eff.setOpacity(1.0)
                widget.setGraphicsEffect(eff)
                anim = QPropertyAnimation(eff, b"opacity", widget)
                anim.setDuration(int(ANIMATION.DURATION_STATE * 1000))
                anim.setStartValue(1.0)
                anim.setEndValue(0.0)
                anim.setEasingCurve(_ease(ANIMATION.EASE_OUT_CUBIC))

                def _bye(w=widget) -> None:
                    try:
                        w.setParent(None)
                        w.deleteLater()
                    except Exception:  # noqa: BLE001
                        pass

                anim.finished.connect(_bye)
                skel_fading["v"] = True
                anim.start()
            except Exception as exc:  # noqa: BLE001 fail-open：过渡失败即瞬时移除
                _logger.warning("骨架屏淡出失败，瞬时移除: %s", exc)
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except Exception:  # noqa: BLE001
                    pass
                skel_fading["v"] = False

        def _done(result):
            _drop_skeleton()  # render 前移除骨架
            try:
                render(result)
            except Exception as exc:  # noqa: BLE001 单个渲染缺陷不得毁掉整页
                # 渲染异常绝不能让页面停在"没加载过"的状态：否则每次刷新都会
                # 重放骨架屏（_content_ready 恒假）→ 页面看着一直空白/加载中；
                # 且在打包态（无控制台）异常逃出 Qt 槽函数是**不可见**的。
                # 此处记 WARNING（落 gui.log）后仍然收尾，页面展示已渲染的部分。
                _logger.warning("页面渲染失败（展示已渲染部分）: %s", exc)
            finally:
                # 无论渲染成败都算"内容已落地"：骨架只给真正的首屏一次，
                # 不因一次渲染缺陷而永久重放。
                self._content_ready = True
                _drop_skeleton()  # 兜底：render 抛异常也必须移除

        def _finish(w=worker):
            """线程**真正结束后**才摘登记并释放。

            两处都不能提前：① ``_fetches`` 也是 Python 侧的唯一强引用，摘早了
            包装会被 GC，Qt 随后删除 C++ 对象时仍在分发信号 → 访问失效包装直接
            abort；② 在 ``_done`` 里就释放，线程可能还在收尾 → 销毁运行中的
            ``QThread`` 同样 abort。故用默认参数抓住 worker，保证这两个动作之间
            包装一直活着。
            """
            self._fetches.pop(name, None)
            try:
                w.deleteLater()
            except RuntimeError:
                pass  # 底层 C++ 对象已销毁，无需再释放

        worker.finished.connect(_finish)
        worker.done.connect(_done)
        worker.start()
        self._fetches[name] = worker

    def refresh(self) -> None:
        """导航到此页时调用，子类覆盖。"""
        pass

    # ---------- 首屏错峰入场 ----------

    def stagger_cards(self, layout) -> None:
        """给列表/网格容器里的卡片一个**首屏**错峰入场。

        **"只首屏"这条规则只在这里实现一次**（页面不必各自判断）：``_content_ready``
        由 ``fetch_and_render`` 在首个渲染周期**返回之后**才置真，故本方法在首屏首次
        渲染时为假 → 触发；之后的轮询刷新（``sync_tracked`` 原地复用同一批控件）
        为真 → 直接返回，**绝不重放入场**（否则每 30s 整列表重放一次就成了骚扰）。

        降级（reduced-motion / 低特效）与"绝不挂 graphicsEffect"的硬要求由
        ``qt_widgets.stagger_in`` 内部 fail-open 兜住。本方法**绝不抛**。
        """
        if self._content_ready or layout is None:
            return
        try:
            from .qt_widgets import stagger_in  # 懒导入防循环依赖
            items = [layout.itemAt(i).widget() for i in range(layout.count())]
            stagger_in([w for w in items if w is not None])
        except Exception as exc:  # noqa: BLE001 入场动画绝不阻断列表渲染
            _logger.warning("首屏错峰入场跳过: %s", exc)

    def set_count(self, label, value: int, *, size: int | None = None) -> None:
        """把大数字写进 ``label``（M2 数字滚动）——**首屏滚动、之后直写**。

        与 ``stagger_cards`` 同一套"只首屏"口径：首屏首次渲染从 0 滚到 ``value``，
        之后（轮询/重渲染）直接写终值，不重放滚动。``size`` 传该 label 的字号
        （用于预置最小宽，防数字变长导致整行重排）。降级与零-effect 由
        ``qt_widgets.count_up`` 内部 fail-open 兜住。**绝不抛**。
        """
        if label is None:
            return
        try:
            if self._content_ready:
                label.setText(str(int(value)))
                return
            from .qt_widgets import count_up  # 懒导入防循环依赖
            count_up(label, int(value), size=size)
        except Exception as exc:  # noqa: BLE001 数字滚动绝不阻断渲染
            _logger.warning("数字滚动跳过: %s", exc)
            try:
                label.setText(str(value))
            except Exception:  # noqa: BLE001
                pass

    # ---------- 模型接入门禁（生成类动作共用） ----------

    def model_state(self) -> dict:
        """当前模型接入状态：``{"available": bool, "endpoint": str}``。

        口径：``self.api.models()`` 的 ``routes[].endpoint`` 任一非空即已接入
        （与经验库页「去接入」提示条一致）；引擎不可达 → 视为未接入。
        本方法是门禁口径的**唯一来源**，``_model_available()`` 直接复用。
        """
        try:
            routes = self.api.models().get("routes") or []
        except LocalApiError:
            return {"available": False, "endpoint": ""}
        for r in routes:
            endpoint = str((r or {}).get("endpoint") or "").strip()
            if endpoint:
                return {"available": True, "endpoint": endpoint}
        return {"available": False, "endpoint": ""}

    def _model_available(self) -> bool:
        """是否接入了可用模型（口径见 ``model_state``）。保留供既有页面复用。"""
        return self.model_state()["available"]

    def require_model(self, action: str) -> bool:
        """生成类动作的模型门禁（**取代** confirm_builtin_summary / guide_connect_ai）。

        有模型 → ``True``（放行）；无模型 → 弹窗明确"该动作需要模型"并引导去
        「接入」页 → 返回 ``False``（本次不执行）。文案不暗示可以本机凑出来
        （总纲：无模型不产出归纳类内容，拒绝而非给半成品）。
        """
        if self.model_state()["available"]:
            return True
        from .qt_dialogs import confirm_dialog  # 懒导入防循环依赖
        if confirm_dialog(
                t("需要接入模型"),
                t("{action}需要先接一个模型（本地模型或 API 都行）。"
                  "现在去「接入」页配置吗？").format(action=action),
                self):
            self.go("connect")
        return False

    def retranslateUi(self) -> None:
        """语言切换时原地更新所有 t() 文字。子类覆盖。"""
        pass

    def _build(self) -> None:
        """构建 UI。子类覆盖。"""
        raise NotImplementedError


def build_centered_scroll(
    content_lay: QVBoxLayout,
    max_width: int | None = None,
) -> QScrollArea:
    """把内容布局包装为居中 QScrollArea（最大宽度限制，左右自适应留白）。

    设计方案 V-B1 沿用：内容列 ≤880px 居中，全页左对齐。
    所有页面统一走此函数，消除各自内联 QScrollArea 的重复代码。

    滚动规范：页面整滚只保留这一层；整滚区内的下拉选择
    一律用 qt_widgets.SelectButton（QMenu 顶层弹层，不随滚动条移动），
    QComboBox 只允许出现在 QDialog（独立窗口）内部。

    **留白**请用 ``page_scaffold``（它在调用本函数前先设好内容列边距）——
    直接调本函数不会替你设边距，页面就得各记一遍「32 还是 0」。
    """
    content = QWidget()
    content.setLayout(content_lay)
    content.setMaximumWidth(max_width or SIZES.CONTENT_HOME)
    outer = QHBoxLayout()
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    outer.addStretch(1)
    outer.addWidget(content)
    outer.addStretch(1)
    inner = QWidget()
    inner.setLayout(outer)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(inner)
    return scroll


# 页面内容列的标准留白（UI 统一化第 1 波 S2）：左右/底部 32px（= S.s8）。
# 顶边缺省 0 —— 由 page_header(top=S.s8) 提供，两处各加会叠成 64px。
PAGE_SIDE_PAD = S.s8


def page_scaffold(content_lay: QVBoxLayout, *,
                  max_width: int | None = None,
                  top: int = 0,
                  side: int = PAGE_SIDE_PAD,
                  bottom: int = PAGE_SIDE_PAD) -> QScrollArea:
    """统一页面滚动骨架（S2）：一次性设好内容列留白 + 居中 + 单一外层滚动。

    **统一口径**（第 1 波定的四条）：
    - 左右 / 底部留白 = 32px（`S.s8`）——与全部顶层页现状一致；
    - 顶部留白 = 0，**由 `page_header()` 提供**（缺省 S.s8）；
    - 内容列最大宽 = `SIZES.CONTENT_HOME`（880px），全站唯一一个值；
    - 整页只有一个滚动区（本函数返回的那个）。

    无页头的页面显式传 ``top=PAGE_SIDE_PAD``。**页头在滚动区之外**的页面
    （如「我的经验」容器：固定头 + 子页各滚）不要用本函数，见该页注释。
    """
    content_lay.setContentsMargins(side, top, side, bottom)
    return build_centered_scroll(content_lay, max_width)
