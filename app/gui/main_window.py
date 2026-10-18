"""主窗口（Qt 版，迁移清单 ，替代 shell.py）。

布局：左侧导航栏（品牌区 + 三组导航） + 右侧 AnimatedStack（QStackedWidget 子类）。
- 页面切换：AnimatedStack（过渡动画；motion 关/异常时 fail-open 瞬时切换）
- 关闭藏到托盘，托盘右键菜单
- 通知轮询（60s）→ 新未读达批量阈值时发系统原生通知弹窗
- 活数据页轮询（30s，home/growth）→ 自动刷新
- 语言切换：重写配置 → 重建整个窗口
"""

from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QMainWindow, QStatusBar,
                               QVBoxLayout, QWidget)

from . import i18n
from .api_client import CachedApi, local_api_listening
from .i18n import t
from .page_base import ApiWorker
from .qt_dialogs import confirm_dialog
from .qt_icons import icon_widget
from .qt_theme import (APP_STYLESHEET, DIVIDER_STYLE, NAV_BUTTON_STYLE,
                       apply_text_palette, btn_flat, btn_primary, txt)
from .theme import C, D, F, S, SIZES, resolve_theme_mode
from .qt_widgets import AnimatedStack, NavButton

logger = logging.getLogger("experientia.gui.main_window")


def _phase_page(tag: str, ms: float) -> None:
    """页面级耗时打点：只写日志，沿用 main._phase 的 [tag] 风格。

    独立成模块级函数（不依赖 MainWindow 实例），便于测试直接调用验证不抛异常。
    默认 DEBUG（切页是热路径，不再逐页刷 INFO）；仅超阈值（>50ms）时记
    INFO 点名——保留 `[page]` 前缀，便于 grep 超阈值页。
    """
    if ms > 50.0:
        logger.info("[page] %s 耗时 %.1f ms", tag, ms)
    else:
        logger.debug("[page] %s 耗时 %.1f ms", tag, ms)


# 页面键顺序 = _NAV 项顺序（与 shell.PAGES 同口径）
PAGES = ("home", "mine", "growth", "hooks", "export", "connect", "settings")

_LEGACY = {
    "experiences": "mine", "methods": "mine", "failures": "mine", "prefs": "mine",
    "preferences": "mine",
    "models": "connect", "preview": "connect", "skill": "export",
    "rules": "hooks", "share": "export",
}

# 有「一键接入实时捕获」配方的 agent（= hook_admin.install_all 覆盖集）。
# 表外 agent（workbuddy/codex 等）只能逐条手动新增（codex 是 toml v1 只读、
# workbuddy 无注入配方）——不能进这个提议横幅，否则"全部接入"点了也不生效。
# claude-code 走接入页既有通道，也不在此列。与 Hooks 页 offerable 同口径。
_HOOK_OFFERABLE = ("hermes", "cursor", "windsurf")

# 导航三组：MDI 图标名 + 标签 i18n key（与 shell._NAV_GROUPS 同口径）
NAV_GROUPS = (
    ("使用", (
        ("view-dashboard-outline", "view-dashboard", "首页"),
        ("lightbulb-on-outline", "lightbulb-on", "我的经验"),
        ("chart-line", "chart-line-variant", "成长"),
    )),
    ("管理", (
        ("clipboard-text-outline", "clipboard-text", "Hooks"),
        ("download-outline", "download", "导出"),
    )),
    ("系统", (
        ("cloud-outline", "cloud", "接入"),
        ("cog-outline", "cog", "设置"),
    )),
)
NAV_ITEMS = tuple(item for _g, items in NAV_GROUPS for item in items)

NOTIFY_POLL_MS = 60_000  # 通知轮询：30s→60s 降频（通知弹窗不刷屏）
NOTIFY_TOAST_MS = 3000   # 托盘不可用时的降级形态（状态栏消息条）显示时长
PAGE_POLL_MS = 30_000    # 活数据页轮询：10s→30s 降频（减少 API 请求，改善卡顿）
LIVE_PAGES = frozenset({"home", "growth"})
REFRESH_MIN_INTERVAL = 30.0  # 同一页面最短刷新间隔（秒），防止频繁切页多次触发 API
API_TIMEOUT = 15.0            # API 请求超时（全局 30s→15s，避免单个请求卡死 UI）
_BOOT_CONFIG_UNREAD = object()  # 启动期配置哨兵：None = 已尝试过但读不到


class MainWindow(QMainWindow):
    """主窗口。store 用于语言切换重建。"""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self._store = store
        self._allow_quit = False
        # 只读请求进程内缓存（写失效）；页面并行刷新复用同一实例（httpx 线程安全）
        self.api = CachedApi()
        self._pages: dict[str, QWidget] = {}
        self._nav_buttons: list[NavButton] = []
        self._group_labels: list[tuple[str, QLabel]] = []  # (group_key, QLabel)
        self._rail: QWidget | None = None
        self._rail_divider: QFrame | None = None  # 分隔线永久实例，重刷样式不重建
        self._rail_suspended = False  # 重刷导航栏期间置真，定时器回调跳过
        self._tray = None
        self._tray_actions: dict = {}  # 托盘菜单项（key→QAction），语言切换原地翻译
        self._notify_last: int | None = None  # 上次轮询的未读数（基线）
        self._notify_pending = 0              # 自上次气泡以来累计的新通知数
        self._last_refresh: dict[str, float] = {}  # 页名 → 上次 refresh 时间戳
        self._first_refreshed: set[str] = set()    # 已打过「首刷」打点的页
        # 顶部「可接入实时捕获」一次性提示：本会话已关闭则不再弹
        self._hook_offer_dismissed = False
        self._hook_offer_agents: list[str] = []
        self._hook_offer_names: list[str] = []
        self._hook_installing = False  # 「全部接入」在途标志（防重复提交）
        self._offer_busy = False       # 横幅探查在途（后台轮询去重）
        self._notify_busy = False      # 通知轮询在途（后台轮询去重）
        self._shell_workers: list = []  # 外壳后台取数线程（随窗口收尾，不脱钩）
        # 启动期 API config 缓存（见 _boot_api_config）：哨兵 = 还没读过
        self._boot_config: object = _BOOT_CONFIG_UNREAD

        self.setWindowTitle("Experientia")
        self._init_window()
        self._build_layout()
        self._restore_lang()
        self._init_tray()
        self._setup_timers()
        # 首次启动流程（与 Flet shell 同口径）：未 onboarded → 欢迎页；
        # 配置读不到（引擎未起等）兜底进首页，不把新用户挡在引导外也不困在引导里
        _boot_cfg = self._boot_api_config()
        onboarded = (bool(_boot_cfg.get("onboarded"))
                     if _boot_cfg is not None else True)
        if onboarded:
            self._select_page("home", initial=True)
            # 首帧画完立即加载首页数据：窗口先出现（不阻塞启动），
            # 数据在下一轮事件循环补上——避免首页空白等 10s 轮询的"慢"感
            QTimer.singleShot(0, lambda: self._refresh_page_by_name("home"))
            # 启动稍候检测「可一键接入实时捕获」的工具，顶部弹一次性提示
            QTimer.singleShot(2500, self._check_hook_offer)
        else:
            self._show_onboarding()

    # ---------- 初始化 ----------

    def _init_window(self) -> None:
        from .layout import initial_window_size

        w, h, mw, mh = initial_window_size(None)
        self.resize(w, h)
        self.setMinimumSize(mw, mh)
        try:
            from PySide6.QtGui import QIcon

            from .theme import app_icon_file

            self.setWindowIcon(QIcon(str(app_icon_file())))
        except Exception:
            pass

    def _build_layout(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 左侧导航栏（rail 与分隔线为永久实例：主题切换只重刷样式，不 deleteLater 重建）
        self._rail = self._build_rail()
        self._rail_divider = QFrame()
        self._rail_divider.setFixedWidth(D.BORDER_W)
        self._rail_divider.setStyleSheet(f"background: {C.line}; border: none;")
        root.addWidget(self._rail)
        root.addWidget(self._rail_divider)

        # 右侧内容区（顶部可接入提示横幅 + 主内容栈）
        self._content = QWidget()
        content_col = QVBoxLayout(self._content)
        content_col.setContentsMargins(0, 0, 0, 0)
        content_col.setSpacing(0)
        self._hook_offer_banner = self._build_hook_offer_banner()
        content_col.addWidget(self._hook_offer_banner)
        # 页面容器换 AnimatedStack（提供，重写 setCurrentWidget
        # 加过渡；motion 关/异常时 fail-open 瞬时切换），调用方式不变。
        self._stack = AnimatedStack()
        content_col.addWidget(self._stack, 1)
        root.addWidget(self._content, 1)

        self.setCentralWidget(central)

        # 状态行
        bar = QStatusBar()
        self._status_label = txt(t("就绪"), F.caption, color=C.ink_500)
        bar.addWidget(self._status_label)
        self.setStatusBar(bar)

    def _build_rail(self) -> QWidget:
        rail = QWidget()
        rail.setStyleSheet(f"background: {C.surface}; border: none;")
        rail.setFixedWidth(self._rail_width())
        col = QVBoxLayout(rail)
        col.setContentsMargins(0, S.s4, 0, 0)
        col.setSpacing(S.s2)

        # 品牌区：吉祥物居中放大（去掉产品名，更可爱）。两侧 stretch 居中，
        # 不依赖栏宽——栏宽收窄后仍精确水平居中。吉祥物源图自带 ~15% 透明边距，
        # 按 72px 渲染时可见宇航员 ≈53px（放满透明边也不溢出，栏内两边各留 ~26px）。
        from .qt_theme import mascot_image

        brand = QHBoxLayout()
        brand.setContentsMargins(0, 0, 0, 0)
        brand.addStretch(1)
        brand.addWidget(mascot_image("smile", 72))
        brand.addStretch(1)
        col.addLayout(brand)
        col.addSpacing(S.s2)

        # 三组导航（设计方案 V-A1：组标题左对齐到文字轴 x=56，caption 级）
        self._nav_buttons = []
        self._group_labels = []
        i = 0
        for g_idx, (group, items) in enumerate(NAV_GROUPS):
            if g_idx > 0:
                sep = QFrame()
                sep.setStyleSheet(DIVIDER_STYLE())
                sep.setFixedHeight(1)
                col.addWidget(sep)
                col.addSpacing(S.s2)  # 分组间留白（胶囊浮起方案：拉开「组 → 项」层次）

            # 组标题（胶囊浮起方案：加粗 700 + 加大 body + 左对齐到图标轴 x=12，贴栏左缘）
            group_label = txt(t(group), F.body, 700, C.ink_500)
            gl_margin = QWidget()
            gl_lay = QHBoxLayout(gl_margin)
            gl_lay.setContentsMargins(0, 0, 0, 0)
            gl_lay.setSpacing(0)
            # 左留 S.s3(12px) 对齐到图标轴 x=12（与吉祥物/导航图标同一条左缘线）
            gl_lay.addSpacing(S.s3)
            gl_lay.addWidget(group_label)
            gl_lay.addStretch(1)
            gl_margin.setFixedHeight(D.NAV_GROUP_LABEL_H)
            col.addWidget(gl_margin)
            self._group_labels.append((group, group_label))

            for out, fill, key in items:
                # 传原始 key（不调 t()），NavButton 内部存 raw key 供 retranslateUi 重查
                btn = NavButton(key, out, fill)
                btn.setStyleSheet(NAV_BUTTON_STYLE())
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _=False, idx=i: self._pick(idx))
                col.addWidget(btn)
                self._nav_buttons.append(btn)
                i += 1

        col.addStretch(1)

        return rail

    def _rail_width(self) -> int:
        """B 类：导航栏宽由当前语言最长标签派生（对应 shell._rail_width）。

        与 NavButton 解剖一致：左缘 12 + 图标格 32 + 间距 12 + 文本宽 + 右缘 12
        （3×S.s3 + LIST_ICON_BOX）。文本取导航最长标签（品牌区已无产品名，
        品牌名不再参与算宽）。"""
        nav_w = max(
            QFontMetrics(txt("", F.body).font()).horizontalAdvance(t(key))
            for _o, _f, key in NAV_ITEMS)
        return int(max(nav_w + 3 * S.s3 + SIZES.LIST_ICON_BOX,
                       SIZES.NAV_WIDTH))

    # ---------- 页面 ----------

    def _build_pages(self) -> None:
        """实例化页面（迁移清单架构图）+ 懒加载（性能考量）。

        启动只建首页：其余页在首次导航时才构建（_lazy_page）。全量建页会把
        7 页各自的构建 + 首轮 refresh 串行 API 调用（实测合计 ~300ms+）压到
        启动主线程；懒加载把成本摊到"第一次点到那页"，启动只承担首页。
        """
        from . import (connect_page, export_page, growth, home, hooks_page,
                       my_experience, settings_page)

        self._factories = {
            "mine": my_experience.MyExperiencePage,
            "growth": growth.GrowthPage,
            "hooks": hooks_page.HooksPage,
            "export": export_page.ExportPage,
            "connect": connect_page.ConnectPage,
            "settings": settings_page.SettingsPage,
        }
        api = self.api
        page = home.HomePage(api)
        page.set_status_bar(self._status_label)
        self._stack.addWidget(page)
        self._pages = {"home": page}

    def _lazy_page(self, name: str) -> QWidget:
        """首次导航才构建的页面（懒加载）：建页 + 注入状态行 + 入栈登记。"""
        factory = self._factories[name]
        page = factory(self.api)
        page.set_status_bar(self._status_label)
        self._stack.addWidget(page)  # 先入栈，PageBase._mw 即可经 window() 回溯到本窗口
        self._pages[name] = page
        return page

    def _select_page(self, name: str, initial: bool = False) -> None:
        # 切页打点落在本方法（唯一汇点）。任务书写在 go()，但 go() 只做
        # onboarding 分流后转调本方法，导航点击（_pick）不经 go()——落此处才能把
        # 两条入口的切页耗时都量到，语义等价且更全。
        _t0 = time.perf_counter()
        name = _LEGACY.get(name, name)
        if name not in PAGES:
            name = "home"
        self._current_nav = name
        # 已在 Hooks 页时，"去 Hooks 页管理"平链自指冗余，改用"全部接入"即可，隐藏之。
        if getattr(self, "_hook_offer_go_btn", None) is not None:
            self._hook_offer_go_btn.setVisible(name != "hooks")
        page = self._pages.get(name)
        if page is None:
            page = self._lazy_page(name)
        self._stack.setCurrentWidget(page)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == PAGES.index(name))
        # 不再自动刷新：页面内容通过轮询定时器 (_page_poll) 更新，
        # 避免每次切页触发大量 API 请求导致卡顿。
        # 首次打开或距上次刷新 > REFRESH_MIN_INTERVAL 才刷新。
        if not initial:
            now = time.monotonic()
            last = self._last_refresh.get(name, 0.0)
            if now - last > REFRESH_MIN_INTERVAL:
                QTimer.singleShot(0, lambda n=name: self._refresh_page_by_name(n))
        _phase_page(f"切页 {name}", (time.perf_counter() - _t0) * 1000)

    def _refresh_page_by_name(self, name: str) -> None:
        """按页名安全刷新：页未登记则跳过。

        记录刷新时间戳，供 _page_poll 和 _select_page 节制刷新频率。
        每页首次刷新打一条 `[page] 首刷`——量的是 refresh() 的派发
        耗时（真实取数在的 fetch_and_render/后台 worker 里完成，此处包一层
        是任务书给的两个选项之一，不侵入 page_base）。
        """
        page = self._pages.get(name)
        if page is not None:
            _first = name not in self._first_refreshed
            _t0 = time.perf_counter()
            try:
                page.refresh()
                self._last_refresh[name] = time.monotonic()
            except Exception as exc:
                logger.warning("页面延迟刷新失败: %s", exc)
                if hasattr(page, "report_error"):
                    page.report_error(f"页面刷新失败：{exc}")
            if _first:
                self._first_refreshed.add(name)
                _phase_page(f"首刷 {name}", (time.perf_counter() - _t0) * 1000)

    def _pick(self, idx: int) -> None:
        self._select_page(PAGES[idx])

    def go(self, name: str) -> None:
        """页面跳转（供子页调用）。"""
        if name == "onboarding":
            self._show_onboarding()
            return
        self._select_page(name)

    def _show_onboarding(self) -> None:
        _t0 = time.perf_counter()
        from . import onboarding

        page = onboarding.OnboardingPage(self.api)
        page.set_status_bar(self._status_label)
        self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)
        _phase_page("切页 onboarding", (time.perf_counter() - _t0) * 1000)

    # ---------- 状态行 / Toast ----------

    def toast(self, msg: str, duration: int = 5000) -> None:
        """底部消息条（对应 Flet SnackBar）。"""
        self.statusBar().showMessage(msg, duration)

    # ---------- 顶部「可接入实时捕获」一次性提示横幅 ----------

    def _build_hook_offer_banner(self) -> QWidget:
        """顶部常驻、默认隐藏的提示横幅：检测到可写且未接入的 agent 时显示。"""
        w = QWidget()
        w.setObjectName("hookOfferBanner")
        w.setStyleSheet(
            f"background: {C.brand_50}; border-bottom: 1px solid {C.brand_100};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(S.s3, S.s2, S.s3, S.s2)
        lay.setSpacing(S.s2)
        lay.addWidget(icon_widget("NOTIFICATIONS_ACTIVE_OUTLINED", 18, C.brand_700))
        self._hook_offer_label = txt("", F.body, 600, C.ink_900)
        self._hook_offer_label.setWordWrap(True)
        lay.addWidget(self._hook_offer_label, 1)
        go_btn = btn_flat(t("去 Hooks 页管理"))
        go_btn.clicked.connect(lambda _=False: self.go("hooks"))
        go_btn.setObjectName("hookOfferGoBtn")
        lay.addWidget(go_btn)
        self._hook_offer_go_btn = go_btn
        self._hook_offer_btn = btn_primary(t("全部接入"))
        self._hook_offer_btn.setFixedHeight(D.BTN_H_SM)
        self._hook_offer_btn.clicked.connect(self._hook_offer_install_clicked)
        lay.addWidget(self._hook_offer_btn)
        close = QPushButton("×")
        close.setFixedSize(D.BTN_H_SM, D.BTN_H_SM)
        close.setStyleSheet(
            f"color: {C.ink_500}; border: none; background: transparent; "
            f"font-size: 16px;")
        close.clicked.connect(self._dismiss_hook_offer)
        lay.addWidget(close)
        w.hide()
        return w

    def _check_hook_offer(self) -> None:
        """探查可一键接入的工具；可写且未注入即提示（H3：取数挪后台）。

        只提「有一键接入配方」的 agent（_HOOK_OFFERABLE = install_all 覆盖集）：
        表外 agent（workbuddy/codex 等）没有注入配方，点了"全部接入"也不生效
        （codex 还是 toml v1 只读），提了反而误导。claude-code 走接入页，同样不提。
        与 Hooks 页 offerable 同口径。"""
        if self._hook_offer_dismissed or self._offer_busy:
            return
        self._offer_busy = True

        def _fetch():
            try:
                return self.api.hooks_admin_overview()
            except Exception:
                return None

        def _done(overview):
            self._offer_busy = False
            if not isinstance(overview, dict):
                return
            offers = []
            for a, info in overview.items():
                if (a in _HOOK_OFFERABLE
                        and info.get("exists") and not info.get("installed")
                        and info.get("writable")):
                    offers.append((a, info.get("label") or a))
            if not offers:
                self._hook_offer_banner.hide()
                return
            self._render_hook_offer(offers)

        self._spawn_worker(_fetch, _done, _done)

    def _render_hook_offer(self, offers: list[tuple[str, str]]) -> None:
        self._hook_offer_agents = [a for a, _ in offers]
        self._hook_offer_names = [n for _, n in offers]
        self._hook_offer_label.setText(
            t("发现 {n} 个 AI 工具可一键接入实时捕获：{names}",
              n=len(offers), names=", ".join(self._hook_offer_names)))
        # 当前若已在 Hooks 页，"去 Hooks 页管理"平链自指冗余（旁边"全部接入"即达目标）。
        if getattr(self, "_hook_offer_go_btn", None) is not None:
            self._hook_offer_go_btn.setVisible(
                getattr(self, "_current_nav", "home") != "hooks")
        self._hook_offer_banner.show()

    def _hook_offer_install_clicked(self) -> None:
        if not self._hook_offer_agents or self._hook_installing:
            return
        # 走主题化 confirm_dialog（i18n + 样式统一），不再用裸 QMessageBox
        if not confirm_dialog(
                t("接入实时捕获"),
                t("对以下工具一键接入实时捕获？\n{names}",
                  names=", ".join(self._hook_offer_names)),
                parent=self):
            return
        # install_all 客户端超时 60s，主线程同步请求
        # 会冻结整窗——挪到后台线程（ApiWorker），按钮置灰 + 状态条忙态提示。
        self._hook_installing = True
        self._hook_offer_btn.setEnabled(False)
        self.toast(t("正在接入实时捕获…"), 0)
        worker = ApiWorker(self.api.hooks_admin_install_all, self)
        worker.finished.connect(self._hook_install_done)
        worker.error.connect(self._hook_install_fail)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        worker.start()

    def _hook_install_done(self, r: object) -> None:
        self._hook_installing = False
        self._hook_offer_btn.setEnabled(True)
        fail = [k for k, v in (r or {}).items() if not v.get("ok")]
        self.toast(t("已接入实时捕获") if not fail else t("部分工具接入失败"), 4000)
        self._dismiss_hook_offer()

    def _hook_install_fail(self, err: str) -> None:
        self._hook_installing = False
        self._hook_offer_btn.setEnabled(True)
        self.toast(str(err) or t("接入失败"))

    def _dismiss_hook_offer(self) -> None:
        self._hook_offer_dismissed = True
        self._hook_offer_banner.hide()

    # ---------- 通知 ----------

    def _spawn_worker(self, fn, on_done, on_error=None) -> None:
        """外壳级后台取数：主线程零 HTTP，回调落主线程。

        worker 随回调收尾即从清单移除（定时器长期跑，清单不得只增不减）。"""
        worker = ApiWorker(fn, self)

        def _cleanup(_, w=worker):
            try:
                self._shell_workers.remove(w)
            except ValueError:
                pass

        worker.finished.connect(on_done)
        if on_error is not None:
            worker.error.connect(on_error)
        else:
            worker.error.connect(lambda e: logger.warning("后台取数失败: %s", e))
        worker.finished.connect(_cleanup)
        worker.error.connect(_cleanup)
        # finish/error 后 deleteLater——只从清单移除不删
        # C++ QThread 子对象，60s/120s 定时器长期跑会单调累积（≈90 个/小时）。
        # 与 page_base.run_async 同一范式；_cleanup 先摘登记，删页时
        # _wait_inflight 仍能安全遍历。
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        worker.start()
        self._shell_workers.append(worker)

    def _notify_poll(self) -> None:
        if self._rail_suspended:  # 导航栏样式重刷期间跳过（双保险）
            return
        if self._notify_busy:     # 上一轮还没回来：跳过，不排队堆叠
            return
        self._notify_busy = True
        self._spawn_worker(
            lambda: self.api.notifications(unread=True, limit=50),
            self._notify_got,
            lambda e: (logger.warning("通知轮询失败: %s", e),
                       setattr(self, "_notify_busy", False)))

    def _notify_got(self, payload) -> None:
        self._notify_busy = False
        items = (payload or {}).get("items", []) if isinstance(payload, dict) else []
        # 只让占每日额度的通知（+ 系统通知例外）参与弹窗判定；超额度的静静躺在列表。
        poppable = self._poppable_notices(items)
        count = len(poppable)
        if self._notify_last is None:
            # 首轮只建基线不弹
            self._notify_last = count
            self._notify_pending = 0
            return
        if count > self._notify_last:
            # 新到占额度通知：本轮累计待弹
            self._notify_pending += count - self._notify_last
        elif count < self._notify_last:
            # 用户在应用内读掉了：重置基线并清空累计，不再为旧通知补弹
            self._notify_last = count
            self._notify_pending = 0
            return
        # 不再读 config 判开关：能进 poppable 的，push() 已过「静音 / 类型开关 /
        # 每日额度」三道闸。防轰炸由每日额度（最多 2 条占额度）承担，这里不再攒批：
        # 本轮只要新到占额度通知就弹一次（一轮最多 2 条 → 一天最多 2 次弹窗）。
        if self._notify_pending and poppable:
            self._notify_batch(poppable[:self._notify_pending])
            self._notify_pending = 0
        self._notify_last = count

    @staticmethod
    def _poppable_notices(items: list[dict]) -> list[dict]:
        """筛出该弹系统级弹窗的通知。

        只有占每日额度的（counted=True）与「系统通知」（不计入上限的唯一
        例外）才弹；超出当日额度的通知（push() 标 counted=False）只进列表不弹窗。
        """
        return [n for n in items
                if n.get("counted") or n.get("type") == "system_notice"]

    def _notify_batch(self, items: list[dict]) -> None:
        """弹新积累动态（能进 poppable = 已过「静音 / 类型开关 / 每日额度」三道闸）。

        主形态 = 系统级原生通知弹窗（托盘 notify_native，Windows 上落操作中心）；
        托盘不可用（无托盘环境 / 远程会话）→ 降级为状态栏消息条，不静默丢通知。
        """
        from .qt_tray import notify_native

        msg = self._batch_summary(items)
        if not notify_native(self, "Experientia", msg):
            self.toast(msg, NOTIFY_TOAST_MS)

    @staticmethod
    def _batch_summary(items: list[dict]) -> str:
        """把新积累的 N 条汇总成一句气泡文案（按类型计数，收敛显示）。"""
        labels = {
            "method_update": t("方法动态"),
            "daily_summary": t("每日总结"),
            "growth_report": t("成长动态"),
            "system_notice": t("系统通知"),
        }
        counts: dict[str, int] = {}
        for n in items:
            typ = str(n.get("type") or "?")
            counts[typ] = counts.get(typ, 0) + 1
        detail = " · ".join(f"{labels.get(k, k)} {v}" for k, v in counts.items())
        return t("已积累 {n} 条新动态", n=len(items)) + (f"（{detail}）" if detail else "")

    def _page_poll(self) -> None:
        if self._rail_suspended:  # 导航栏样式重刷期间跳过（双保险）
            return
        cur = self._stack.currentWidget()
        if not cur:
            return
        # 懒加载后堆栈顺序 ≠ PAGES 顺序，按对象身份找页名（onboarding 等
        # 非登记页不在 _pages，name=None → 非活数据页，跳过）
        name = next((n for n, p in self._pages.items() if p is cur), None)
        if name in LIVE_PAGES:
            # 距上次刷新不足 REFRESH_MIN_INTERVAL 则跳过
            now = time.monotonic()
            last = self._last_refresh.get(name, 0.0)
            if now - last >= REFRESH_MIN_INTERVAL:
                page = cur
                if hasattr(page, "refresh"):
                    try:
                        page.refresh()
                        self._last_refresh[name] = time.monotonic()
                    except Exception as exc:
                        logger.warning("页面轮询刷新失败: %s", exc)
                        if hasattr(page, "report_error"):
                            page.report_error(f"页面刷新失败：{exc}")

    # ---------- 托盘 / 关闭 ----------

    def _init_tray(self) -> None:
        # GUI 拉起的引擎子进程（打包态跑隐藏窗口）带 EXPERIENTIA_NO_TRAY=1
        # → 不挂托盘图标，避免「GUI 托盘 + 引擎托盘」双图标。
        if os.environ.get("EXPERIENTIA_NO_TRAY") == "1":
            self._tray = None
            return
        from .qt_tray import setup_tray

        self._tray = setup_tray(self)

    def closeEvent(self, event) -> None:
        """关闭窗口时藏到托盘，不退出（迁移清单）。"""
        if self._allow_quit or not self._tray or not self._tray.isVisible():
            event.accept()
            return
        self.hide()
        event.ignore()

    # ---------- 语言切换（Qt 标准做法：retranslateUi，零重建） ----------

    def _boot_api_config(self) -> dict | None:
        """启动期取本地 API 的 config（locale/onboarded 共用）；取不到返回 None。

        语义与"直接 self.api.config() + except"完全一致，只去掉一次注定白等的
        等待：引擎线程刚起、uvicorn 还没 bind 的那个窗口里，HTTP 必定失败，且要
        本机安全软件先审计 ~2s 才返回（实测 2.03s）——主线程上一次就冻 2 秒。
        先用毫秒级 bind 探测判断 8101 有没有人在听，没在听就直接返回 None，
        让调用方走各自的兜底分支，不再付这 2 秒。
        （口径不变：正常路径仍一律走本地 API，这里不引入
        任何"直读数据目录"的新行为——只有原来那个 except 分支的落点提前到达。）
        结果缓存一次：启动期两处要用（语言 + 是否已引导），失败也只试一次。
        """
        if self._boot_config is not _BOOT_CONFIG_UNREAD:
            return self._boot_config
        cfg: dict | None = None
        if local_api_listening(self.api.base):
            try:
                got = self.api.config()
                cfg = got if isinstance(got, dict) else None
            except Exception:
                cfg = None
        self._boot_config = cfg
        return cfg

    def _restore_lang(self) -> None:
        """恢复界面语言：优先 api.config()（外壳不再
        直读数据目录 config.json，统一走本地 API 客户端）；API 不可达（引擎
        未起/首次启动竞态）时回退 store 直读保首屏语言不炸——此处破例仅限
        初始化早期的只读兜底，正常运行路径仍一律走 api。"""
        locale = (self._boot_api_config() or {}).get("locale")
        if not locale:
            try:
                locale = self._store.load_config().get("locale")
            except Exception:
                locale = None
        i18n.load_catalog(locale or i18n.detect_system_locale())
        self._build_pages()
        # 先放 "home" 到当前索引（不触发 refresh 的双重加载）
        self._stack.setCurrentIndex(PAGES.index("home"))

    def switch_language(self, locale: str) -> None:
        """切换语言：加载新语言包 → 延迟原地更新文字。

        配置写入只在调用方（设置页 _change_language，
        失败可回滚下拉并提示）做一处，本方法不再重复 update_config({"locale"})
        ——旧实现这里 except: pass 静默吞错，且与设置页同一次切换写两遍。
        """
        i18n.load_catalog(locale)
        QTimer.singleShot(0, self._apply_language)

    def _apply_language(self) -> None:
        """延迟执行语言切换。

        主窗口级文字（导航/状态行/托盘菜单）原地翻译即可；页面本体走
        _rebuild_visited_pages——页面文案与内联样式一样在构建时冻结，且接入/导出页的内嵌子页（ModelsPage /
        InjectPreviewPage / SkillOrganizePage）不在主窗 _pages 列表、原地 retranslateUi
        覆盖不全（曾致切语言后整页滞留中文）。重建路径与主题切换同一套、无 deleteLater
        竞态（先换 _pages 再延迟删旧实例）。
        """
        self._retranslate_chrome()
        self._rebuild_visited_pages()

    def _retranslate_chrome(self) -> None:
        """主窗口级文字原地翻译：导航组标题 / 导航按钮 / 状态行 / rail 宽度。"""
        for group, label in self._group_labels:
            try:
                label.setText(t(group))
            except Exception:
                pass
        for btn in self._nav_buttons:
            try:
                btn.retranslateUi()
            except Exception:
                pass
        try:
            self._status_label.setText(t("就绪"))
        except Exception:
            pass
        if self._rail is not None:
            try:
                self._rail.setFixedWidth(self._rail_width())
            except Exception:
                pass
        # 托盘菜单项（QMenu 独立顶层，原地改 action 文本）
        for key, action in self._tray_actions.items():
            try:
                action.setText(t(key))
            except Exception:
                pass
        # 顶部「可接入提示」横幅：若可见，按新语言重渲染文案
        if getattr(self, "_hook_offer_banner", None) is not None \
                and self._hook_offer_banner.isVisible():
            self._check_hook_offer()

    def retranslateUi(self) -> None:
        """语言切换时更新 chrome + 已实例化页面文字（保留给页面内/兼容调用）。

        语言切换主入口 _apply_language 只调 _retranslate_chrome + 重建页面；
        本方法仅在需要"原地更新不动结构"时使用。
        """
        self._retranslate_chrome()
        for page in self._pages.values():
            if hasattr(page, "retranslateUi"):
                try:
                    page.retranslateUi()
                except Exception as exc:
                    logger.warning("页面 retranslateUi 异常: %s", exc)

    # ---------- 界面外观（亮/暗，dark mode） ----------

    def apply_theme(self) -> None:
        """把当前 C 色板重应用到 QApplication（切色板后全局样式必须重刷）。"""
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(APP_STYLESHEET())
            apply_text_palette()  # 占位符/禁用文字色随色板重取（P2-1）

    def _suspend_timers(self) -> None:
        """暂停定时器 + 置守卫标志（重刷导航栏/结构性改动期间）。"""
        self._rail_suspended = True
        try:
            self._notify_timer.stop()
            self._page_timer.stop()
            self._offer_timer.stop()
        except RuntimeError:
            pass

    def _resume_timers(self) -> None:
        self._rail_suspended = False
        try:
            self._notify_timer.start()
            self._page_timer.start()
            self._offer_timer.start()
        except RuntimeError:
            pass

    def switch_theme(self, mode: str) -> None:
        """切换界面外观（light/dark）：设色板 → 重应用样式 → 重刷导航栏 → 重建页面。

        ui_theme 配置写入收敛到设置页 _change_theme
        （失败可回滚下拉并提示），本方法不再重复 update_config——与语言切换
        同一缺陷类（except: pass 静默吞错 + 同一次切换写两遍）。

        页面内联 QSS 的颜色 token 在构建时冻结，仅重刷全局样式表改不掉已建页面的
        旧色值——所以收尾阶段会把已实例化的页面**整体换成新色板构建的新实例**
        （_finish_theme_switch，不 deleteLater 任何常驻 rail/widget、不碰定时器），
        让深色在设置/首页等重密度页面也彻底生效。旧页面实例先移出栈再延迟删除，
        消除原 _rebuild_rail 的 deleteLater + timer 竞争（-805306369 use-after-free 根因）。
        """
        app = QApplication.instance()
        resolved = resolve_theme_mode(mode, app)
        C.set_mode(resolved)
        # 全守卫：apply_theme(全局样式表重刷) 到主题收尾完成之间，
        # 屏蔽 notify/page 定时器回调触碰 rail 相关 widget（防 paint/样式竞态）
        self._rail_suspended = True
        self.apply_theme()
        # 延迟到当前事件循环处理完再执行（避免 paint 冲突 / 当前槽函数引用旧页）；
        # _finish_theme_switch 末尾会复位守卫标志
        QTimer.singleShot(0, self._finish_theme_switch)

    def _finish_theme_switch(self) -> None:
        """主题切换收尾（与切换调用错开一个事件循环，避免当前槽函数栈帧引用旧页）。

        同步执行两件事：重刷导航栏 QSS → 已访问页面按新色板重建。全程单线程、
        无定时器可在同步段插入，_restyle_rail 的 finally 复位守卫。
        """
        self._restyle_rail()
        self._rebuild_visited_pages()

    def _rebuild_visited_pages(self) -> None:
        """已实例化页面整体重建（主题换肤 / 语言切换共用）。

        页面内联 QSS（card/txt/button 等工厂）在构建时把 C token 冻结成具体色值、
        文案也是构建时经 t() 落定——所以主题切换后旧实例需重建才能换肤，语言切换时
        内嵌子页（Models/Inject/Skill 等，不入主窗 _pages）只有整体重建才翻译干净。
        做法：
        - 先按原栈顺序插入新实例，再移出旧实例并 deleteLater（_pages 先指向新实例，
          定时器/单发刷新永远拿到新对象，杜绝 deleteLater + timer 竞态）；
        - 单页重建失败则保留旧实例（宁可不换也不崩）；
        - 重建后重置刷新节流：当前页立即补一次数据，其余页下次访问时自动刷新。
        """
        visited = list(self._pages.items())
        if not visited:
            return
        cur = self._stack.currentWidget()
        cur_name = next((n for n, p in visited if p is cur), None)
        new_pages: dict[str, QWidget] = {}
        for name, _old in visited:
            try:
                if name == "home":
                    from . import home as _home_mod

                    new_page = _home_mod.HomePage(self.api)
                else:
                    new_page = self._factories[name](self.api)
                new_page.set_status_bar(self._status_label)
            except Exception as exc:
                logger.warning("主题重建页面 %s 失败，保留旧实例: %s", name, exc)
                new_page = self._pages[name]
            new_pages[name] = new_page
        # 1) 按旧栈顺序插入新实例（插入先于移除，索引稳定、无空窗）
        for name, old in visited:
            idx = self._stack.indexOf(old)
            new_page = new_pages[name]
            if new_page is old:
                continue
            if idx >= 0:
                self._stack.insertWidget(idx, new_page)
            elif new_page.parent() is None:
                self._stack.addWidget(new_page)
        # 2) 移出旧实例并延迟删除（deleteLater 在本次事件返回后执行，_pages 已换新）
        for name, old in visited:
            new_page = new_pages[name]
            if new_page is old:
                continue
            if old.parent() is not None:
                self._stack.removeWidget(old)
            old.deleteLater()
        self._pages = new_pages
        # 3) 刷新节流整体重置：当前页立即补一次数据，其余页下次访问/轮询自动刷新
        for name in new_pages:
            self._last_refresh.pop(name, None)
        if cur_name in new_pages:
            # 主题换肤 / 语言切换的重建：整栈实例刚换过，走过渡动画只会把
            # "旧页快照"当覆盖层闪一下（内容语义已变），故显式瞬时切换。
            self._stack.setCurrentWidget(new_pages[cur_name], animate=False)
            QTimer.singleShot(
                0, lambda n=cur_name: self._refresh_page_by_name(n))

    def _restyle_rail(self) -> None:
        """只重刷导航栏 QSS（主题切换），不重建、不删 QObject、不停表。

        _nav_buttons / _group_labels 均为常驻实例，引用始终有效；定时器回调里
        的 _rail_suspended 守卫作为双保险，杜绝访问"重建中"对象的竞态。
        """
        if self._rail is None:
            return
        self._rail_suspended = True  # 刷样式期间屏蔽定时器回调（双保险，非删对象）
        try:
            # 1. rail 背景（_build_rail 时内联了旧 C.surface）
            self._rail.setStyleSheet(
                f"background: {C.surface}; border: none;")
            # 2. 分隔线颜色
            if self._rail_divider is not None:
                self._rail_divider.setStyleSheet(
                    f"background: {C.line}; border: none;")
            # 3. 每个导航按钮：QSS + 图标色（图标色在 _apply_icon 内联固化，
            # 需逐个重刷；幂等短路在色板不变时自动跳过重建图标 widget）
            for btn in self._nav_buttons:
                try:
                    btn.setStyleSheet(NAV_BUTTON_STYLE())
                    if hasattr(btn, "_apply_icon"):
                        btn._apply_icon()
                    if hasattr(btn, "_retint_label"):
                        btn._retint_label()
                except Exception:
                    pass
            # 4. 分组标题 + 状态栏文字颜色（txt() 内联了旧 C token）
            self._refresh_group_label_colors()
            self._restyle_status_label()
        finally:
            self._rail_suspended = False

    def _restyle_status_label(self) -> None:
        """状态栏文字色随色板重刷（txt() 内联冻结，需保 caption 字号重写）。"""
        try:
            self._status_label.setStyleSheet(
                f"color: {C.ink_500}; background: transparent; border: none;"
                f" font-size: {F.caption}px;")
        except Exception:
            pass

    def _refresh_group_label_colors(self) -> None:
        for _g, label in self._group_labels:
            try:
                label.setStyleSheet(
                    f"color: {C.ink_500}; background: transparent; border: none;"
                    f" font-size: {F.body}px;")
            except Exception:
                pass

    # ---------- 定时器 ----------

    def _setup_timers(self) -> None:
        self._notify_timer = QTimer(self)
        self._notify_timer.timeout.connect(self._notify_poll)
        self._notify_timer.start(NOTIFY_POLL_MS)

        self._page_timer = QTimer(self)
        self._page_timer.timeout.connect(self._page_poll)
        self._page_timer.start(PAGE_POLL_MS)

        # 顶部「可接入实时捕获」提示：启动 2.5s 后首查，之后每 2 分钟复查
        self._offer_timer = QTimer(self)
        self._offer_timer.timeout.connect(self._check_hook_offer)
        self._offer_timer.start(120_000)
