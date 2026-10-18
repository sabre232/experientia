"""首次引导（F0-04，安装方案）——Qt 版（迁移自 Flet onboarding.py）。

4 屏故事线，1 分钟内走完。
屏 1 这是什么：目标语主标 + 场景句 + 自启状态。
屏 2 它接管了什么：自动记录 / 总结成方法 / 下次自动带上三状态灯。
屏 3 你现在要做的三件事。
屏 4 完成：→ 进入主界面（写 onboarded）。
每屏只有一个主操作；措辞全用户话术；软脸区：宇航员 + 暖色 + 口语化。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .api_client import LocalApi
from .i18n import t
from .page_base import PageBase
from .qt_theme import (_apply_btn_icon, btn_flat, btn_primary, icon_widget,
                       mascot_image, txt)
from .theme import C, D, F, S

_N_SCREENS = 4


def _lamp(ok: bool, title: str, state_text: str) -> QWidget:
    """状态灯一行：已就位 = 绿勾；未就位 = 灰点（给预期，不给假数字）。"""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(S.s2)
    if ok:
        lay.addWidget(icon_widget("CHECK_CIRCLE_OUTLINED", 20, C.ok_fg))
    else:
        dot = QLabel()
        dot.setFixedSize(S.s2, S.s2)
        dot.setStyleSheet(f"background: {C.ink_300}; border-radius: {S.s1}px;")
        lay.addWidget(dot)
    lay.addWidget(txt(title, F.body, 600, C.ink_900))
    lay.addStretch(1)
    lay.addWidget(txt(state_text, F.caption, color=C.ok_fg if ok else C.ink_500))
    return row


class OnboardingPage(PageBase):
    """首次引导：4 屏 + 进度点 + 下一步/上一步/进入主界面。"""

    def __init__(self, api: LocalApi, parent: QWidget | None = None):
        super().__init__(api, parent)
        self._idx = 0
        self._build()

    # ---------- 构建 ----------

    def _build(self) -> None:
        self.content = QWidget()
        self._cl = QVBoxLayout(self.content)
        self._cl.setContentsMargins(S.s8, S.s8, S.s8, S.s8)
        self._cl.setSpacing(S.s6)
        self._cl.setAlignment(Qt.AlignCenter)

        # 进度点
        self._dots: list[QLabel] = []
        dots_row = QHBoxLayout()
        dots_row.setSpacing(S.s1)
        dots_row.setAlignment(Qt.AlignCenter)
        for _i in range(_N_SCREENS):
            d = QLabel()
            d.setFixedSize(S.s2, S.s2)
            d.setStyleSheet(
                f"background: {C.brand_700}; border-radius: {S.s1}px;")
            dots_row.addWidget(d)
            self._dots.append(d)
        dots_box = QWidget()
        dots_box.setLayout(dots_row)
        self._cl.addWidget(dots_box, 0, Qt.AlignHCenter)

        # 四屏（仅一屏可见）
        self._screens = [self._build_screen1(), self._build_screen2(),
                         self._build_screen3(), self._build_screen4()]
        stack = QWidget()
        stack_lay = QVBoxLayout(stack)
        stack_lay.setContentsMargins(0, 0, 0, 0)
        stack_lay.setSpacing(S.s4)
        for s in self._screens:
            stack_lay.addWidget(s)
        self._cl.addWidget(stack, 0, Qt.AlignHCenter)

        # 底部操作行（向导惯例：上一步在左、下一步/进入主界面在右，同一水平轴）：
        # 上一步 = 文字式次操作（中性灰 + 左箭头）；下一步 = 主按钮（品牌底 + 右箭头）。
        # 主次同高，视觉有层不打架。
        nav_row = QHBoxLayout()
        nav_row.setSpacing(S.s2)
        self._btn_back = QPushButton(t("上一步"))
        self._btn_back.setProperty("class", "flat")
        self._btn_back.setStyleSheet(
            f"color: {C.ink_500}; font-weight: 500;")
        self._btn_back.setFixedHeight(D.BTN_H)
        _apply_btn_icon(self._btn_back, "arrow-left", C.ink_500)
        self._btn_back.clicked.connect(self._back)
        self._btn_back.hide()
        nav_row.addWidget(self._btn_back)
        nav_row.addStretch(1)
        self._btn_next = btn_primary(t("下一步"), "arrow-right",
                                     on_click=self._next)
        self._btn_go = btn_primary(t("进入主界面"), "ROCKET_LAUNCH_OUTLINED",
                                   on_click=lambda: self._finish())
        self._btn_go.hide()
        nav_row.addWidget(self._btn_next, 0, Qt.AlignRight)
        nav_row.addWidget(self._btn_go, 0, Qt.AlignRight)
        nav_box = QWidget()
        nav_box.setLayout(nav_row)
        self._cl.addWidget(nav_box)

        # 正文包进滚动区
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(self.content)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(wrap)
        self._layout.addWidget(scroll)

        self._sync(0)
        self.refresh()

    # ---------- 四屏 ----------

    def _build_screen1(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S.s4)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(mascot_image("smile", D.MASCOT_LG), 0, Qt.AlignHCenter)
        self._s1_title = txt(t("越用越懂你的 AI 搭档"), F.h1, 800)
        lay.addWidget(self._s1_title, 0, Qt.AlignHCenter)
        self._s1_body = txt(t("它记得你踩过的坑，也记得那些好用的妙招"),
                            F.body, color=C.ink_500)
        lay.addWidget(self._s1_body, 0, Qt.AlignHCenter)
        self._s1_caption1 = txt(t("每次协作都在成长，下次开口，经验早已备好"),
                                F.caption, color=C.ink_500)
        lay.addWidget(self._s1_caption1, 0, Qt.AlignHCenter)
        self._s1_caption2 = txt(t("数据不出这台机器"), F.caption, color=C.ink_500)
        lay.addWidget(self._s1_caption2, 0, Qt.AlignHCenter)
        self._autostart_txt = txt("", F.caption, color=C.ink_500)
        lay.addWidget(self._autostart_txt, 0, Qt.AlignHCenter)
        return w

    def _build_screen2(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S.s4)
        lay.setAlignment(Qt.AlignCenter)
        self._s2_title = txt(t("它在后台帮你做三件事"), F.h1, 800)
        lay.addWidget(self._s2_title, 0, Qt.AlignHCenter)
        self._lamp_box = QWidget()
        self._lamp_lay = QVBoxLayout(self._lamp_box)
        self._lamp_lay.setContentsMargins(0, 0, 0, 0)
        self._lamp_lay.setSpacing(S.s4)
        lay.addWidget(self._lamp_box, 0, Qt.AlignHCenter)
        # 三档口径一句说清：哪些不接模型也能用、哪些需要模型；
        # 接模型是增强而非前提（总纲）。
        self._s2_caption = txt("", F.caption, color=C.ink_500)
        self._s2_caption.setWordWrap(True)
        self._s2_caption.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._s2_caption, 0, Qt.AlignHCenter)
        return w

    def _build_screen3(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S.s4)
        lay.setAlignment(Qt.AlignCenter)
        self._s3_title = txt(t("你现在要做的三件事"), F.h1, 800)
        lay.addWidget(self._s3_title, 0, Qt.AlignHCenter)
        self._step_box = QWidget()
        self._step_lay = QVBoxLayout(self._step_box)
        self._step_lay.setContentsMargins(0, 0, 0, 0)
        self._step_lay.setSpacing(S.s4)
        lay.addWidget(self._step_box, 0, Qt.AlignHCenter)
        return w

    def _build_screen4(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S.s4)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(mascot_image("wave", D.MASCOT_LG), 0, Qt.AlignHCenter)
        self._s4_title = txt(t("越用越熟，它已经就位"), F.h1, 800)
        lay.addWidget(self._s4_title, 0, Qt.AlignHCenter)
        self._s4_body = txt(t("它会在后台默默积累，你只管用 agent 干活"),
                            F.body, color=C.ink_500)
        lay.addWidget(self._s4_body, 0, Qt.AlignHCenter)
        return w

    # ---------- 数据 ----------

    def refresh(self) -> None:
        # 首刷 5 连同步 HTTP 原全在主线程串行——引擎刚起、
        # 8101 未 bind 时每次连接约 2s，窗口 show() 前冻结最长 ~10s（用户看到
        # "程序点了没反应"），且每处 except 静默兜底、失败不留痕。改走
        # page_base.fetch_and_render：取数进工作线程，渲染回主线程；
        # 整体失败给默认态 + 状态行留痕（SYS-5）。
        self.fetch_and_render(self._load_data, self._render, "onboarding")

    def _render(self, data: dict | None) -> None:
        if data is None:
            # fetch 整体失败（status 都取不到）→ 默认态 + 明确留痕，
            # 不假装"还没发现 agent"。
            data = {"n_agents": 0, "n_cap": 0, "skills_n": 0, "rules_n": 0,
                    "has_model": False, "autostart_on": False}
            self.report_error(t("引导页数据读取失败，显示默认状态"))
        # 屏 1：自启状态
        self._autostart_txt.setText(
            t("开机自启：已开") if data["autostart_on"]
            else t("开机自启：已关（设置里可打开）"))
        # 屏 2：三状态灯
        self._clear(self._lamp_lay)
        self._lamp_lay.addWidget(_lamp(
            data["n_cap"] > 0, t("自动记录"),
            t("已在记录 {n} 个 agent", n=data["n_cap"]) if data["n_cap"] > 0
            else t("还没发现 agent，会持续探测")))
        self._lamp_lay.addWidget(_lamp(
            data["skills_n"] > 0, t("总结成方法"),
            t("已沉淀 {n} 套方法", n=data["skills_n"]) if data["skills_n"] > 0
            else t("完成几个任务后开始沉淀")))
        carry_ok = data["rules_n"] > 0 and data["has_model"]
        if carry_ok:
            carry_state = t("经验和 Hook 会自动带上")
        elif not data["has_model"]:
            carry_state = t("配好模型后开始带上")
        else:
            carry_state = t("导入或总结出 Hook 后开始带上")
        self._lamp_lay.addWidget(_lamp(carry_ok, t("下次自动带上"), carry_state))
        # 三档口径一句说清：事实类（自动记录/搜索/坑卡）不接模型
        # 也能用；归纳类（总结成方法/自动带上）需要模型——接模型是**增强**而非
        # 前提（总纲）。未接模型时把这点讲明，避免"整页都要接模型"的错觉。
        self._s2_caption.setText(
            t("自动记录、搜索、坑卡不接模型也能用；总结成方法与自动带上需要"
              "模型——接入是增强，不是前提")
            if not data["has_model"]
            else t("自动记录一直在跑；总结成方法、自动带上已在工作"))
        # 屏 3：三件事
        self._clear(self._step_lay)
        if data["n_agents"] > 0:
            go_btn = None
            state1 = t("已发现 {n} 个", n=data["n_agents"])
        else:
            go_btn = btn_flat(t("去接入"), on_click=lambda: self._finish("connect"))
            state1 = t("还没发现")
        self._step_lay.addWidget(
            self._step_line("①", t("接入一个 agent"), state1, go_btn))
        self._step_lay.addWidget(
            self._step_line("②", t("让它在后台记录"),
                            t("默认允许，设置里可随时关")))
        self._step_lay.addWidget(
            self._step_line(
                "③", t("完成一次真实的 coding 任务"),
                t("已总结 {n} 套方法", n=data["skills_n"]) if data["skills_n"] > 0
                else t("用你的 agent 干一单，回来看看它总结了什么")))

    def _load_data(self) -> dict:
        # status 是页面主判据，取不到必须让上层知道
        # （fetch_and_render 会转 None → _render 留痕 + 默认态）；其余次要
        # 请求保留逐项降级（缺一项好过整页空）。
        status = self.api.status()
        agents = status.get("agents", {}) or {}
        has_model = bool(status.get("default_model"))
        try:
            cap_agents = self.api.capture_status().get("agents") or {}
        except Exception:
            cap_agents = {}
        try:
            skills_n = len(self.api.skills().get("items", []))
        except Exception:
            skills_n = 0
        try:
            rules_n = sum(1 for r in (self.api.rules().get("items") or [])
                          if r.get("enabled", True))
        except Exception:
            rules_n = 0
        try:
            autostart_on = bool((self.api.config() or {}).get("autostart"))
        except Exception:
            autostart_on = False
        # status 的 agents 是 name→条数（可 sum）；capture_status 的 agents 是
        # name→状态 dict（数个数用 len，见 local_api.capture_status）
        n_agents = sum(agents.values()) if isinstance(agents, dict) else len(agents)
        n_cap = len(cap_agents)
        return {"n_agents": n_agents, "n_cap": n_cap, "skills_n": skills_n,
                "rules_n": rules_n, "has_model": has_model,
                "autostart_on": autostart_on}

    @staticmethod
    def _step_line(no: str, title: str, state: str,
                   btn: QWidget | None = None) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S.s2)
        lay.addWidget(txt(no, F.body, 600, C.ink_700))
        lay.addWidget(txt(title, F.body, 600, C.ink_900))
        lay.addStretch(1)
        lay.addWidget(txt(state, F.caption, color=C.ink_500))
        if btn:
            lay.addWidget(btn)
        else:
            spacer = QWidget()
            spacer.setFixedWidth(S.s1)
            lay.addWidget(spacer)
        return row

    # ---------- 导航 ----------

    def retranslateUi(self) -> None:
        """重新应用翻译：更新所有静态文本后刷新数据。"""
        self._s1_title.setText(t("越用越懂你的 AI 搭档"))
        self._s1_body.setText(t("它记得你踩过的坑，也记得那些好用的妙招"))
        self._s1_caption1.setText(t("每次协作都在成长，下次开口，经验早已备好"))
        self._s1_caption2.setText(t("数据不出这台机器"))
        self._s2_title.setText(t("它在后台帮你做三件事"))
        self._s3_title.setText(t("你现在要做的三件事"))
        self._s4_title.setText(t("越用越熟，它已经就位"))
        self._s4_body.setText(t("它会在后台默默积累，你只管用 agent 干活"))
        # _btn_back/_btn_next/_btn_go have icons, so find child QLabel
        back_label = self._btn_back.layout().itemAt(1).widget()
        back_label.setText(t("上一步"))
        next_label = self._btn_next.layout().itemAt(1).widget()
        next_label.setText(t("下一步"))
        go_label = self._btn_go.layout().itemAt(1).widget()
        go_label.setText(t("进入主界面"))
        self.refresh()

    def _sync(self, idx: int) -> None:
        self._idx = idx
        for i, s in enumerate(self._screens):
            s.setVisible(i == idx)
        for i, d in enumerate(self._dots):
            side = S.s2 if i == idx else S.s1
            d.setFixedSize(side, side)
            d.setStyleSheet(
                f"background: {C.brand_700 if i == idx else C.line}; "
                f"border-radius: {S.s1}px;")
        # 屏 1–3 统一「下一步」；屏 4 换「进入主界面」主按钮
        self._btn_next.setVisible(idx < _N_SCREENS - 1)
        self._btn_go.setVisible(idx == _N_SCREENS - 1)
        self._btn_back.setVisible(idx > 0)

    def _next(self) -> None:
        self._sync(min(self._idx + 1, _N_SCREENS - 1))

    def _back(self) -> None:
        self._sync(max(self._idx - 1, 0))

    def _finish(self, key: str = "home") -> None:
        try:
            self.api.update_config({"onboarded": True})
        except Exception:
            pass
        self.go(key)

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                OnboardingPage._clear(item.layout())
