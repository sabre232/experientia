"""我的经验聚合页（P2 IA 收敛）——Qt 版（原 Flet 源文件 my_experience.py）。

5 tab = 同一堆数据的五个切面。自绘 tab 行（选中 brand_50 底 + brand_700 字，
未选 surface_2 + ink_500）+ QStackedWidget。
5 个子页 = ExperiencesPage / MethodsPage / FailureModesPage /
PreferencesPage / RefutationPage，tab 切换时调用对应子页 refresh()。
"""

from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QStackedWidget, QVBoxLayout, QWidget)

from .api_client import LocalApi
from .i18n import t
from .page_base import PageBase
from .qt_theme import seg_button, seg_style, txt
from .qt_widgets import page_header
from .theme import C, D, F, S


class MyExperiencePage(PageBase):
    """我的经验 4 tab 容器页。

    **UI 统一化第 1 波 S6**（原口径问题见方案文档 ）：
    - 补齐顶层页头（与其它 6 个顶层页同一个 `page_header` 组件）——此前本页
      **没有** h1 标题，是唯一一例；
    - tab 行**吸顶**（`QSizePolicy.Fixed` + 底部分隔线）：切 tab 不必滚回顶部，
      同时用分隔线交代"这是壳"；
    - **去掉叠加留白**：容器头部给 32px 顶边，5 个子页改用 `embedded=True`
      （顶部留白归 0）——此前容器头 `S.s8` 与本页子页 `S.s8` 叠成 64px。
    """

    def __init__(self, api: LocalApi, parent=None):
        super().__init__(api, parent)
        self._build()

    # ---------- UI 构建 ----------

    def _build(self) -> None:
        # 每次构建现取 t()（原 _tabs 注释：模块导入早于 i18n.load_catalog，
        # 切语言走 rebuild 不重导模块——模块级常量会冻结中文源串）。
        self._tabs = (
            ("experiences", t("经验"), t("原始对话轨迹")),
            ("methods", t("方法"), t("提炼出的可复用做法（可导出 SKILL.md）")),
            ("failures", t("踩过的坑"), t("失败模式（自动记录，留意中不自动带上）")),
            ("prefs", t("偏好"), t("模型行为偏好（自动带上）")),
            ("refutation", t("回炉"), t("被系统反复判定用错而降权/停用的经验，可查看并恢复")),
        )

        cl = QVBoxLayout()
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # ① 顶层页头（与其它顶层页同一组件；顶边 32px 由它提供，左右与滚动列对齐）
        head = page_header(t("我的经验"), side=S.s8, top=S.s8)
        self._title_label = head.findChild(QLabel, "pageTitle")
        cl.addWidget(head)

        # ② tab 行：统一分段开关（seg_button/seg_style，对齐 Hooks 页"按规则/按工具"）
        tab_row = QHBoxLayout()
        tab_row.setSpacing(S.s2)
        self._tab_buttons: list[QPushButton] = []
        for key, label, _d in self._tabs:
            btn = seg_button(label, on_click=lambda _=False, k=key: self._switch(k))
            self._tab_buttons.append(btn)
            tab_row.addWidget(btn)
        tab_row.addStretch(1)

        self._desc_label: QLabel = txt(self._tabs[0][2], F.caption, color=C.ink_500)

        # 4 个子页（methods 由另一 agent 迁移，类名 MethodsPage）
        from .experiences import ExperiencesPage
        from .methods import MethodsPage
        from .failure_modes import FailureModesPage
        from .preferences_page import PreferencesPage
        from .refutation import RefutationPage

        # embedded=True：子页顶部留白归 0（顶边 32px 已由上面的页头给），
        # 否则容器头 + 子页头叠成 64px。
        self._subpages = [
            ExperiencesPage(self.api, self, embedded=True),
            MethodsPage(self.api, self, embedded=True),
            FailureModesPage(self.api, self, embedded=True),
            PreferencesPage(self.api, self, embedded=True),
            RefutationPage(self.api, self, embedded=True),
        ]
        self._stack = QStackedWidget()
        for p in self._subpages:
            self._stack.addWidget(p)

        # tab 壳（吸顶）：固定竖向尺寸 → QVBoxLayout 把富余高度全给下面的 stack，
        # 于是本壳不参与拉伸、稳稳停在顶部；底部分隔线交代"这是壳"。
        self._tabs_bar = QWidget()
        self._tabs_bar.setObjectName("myExpTabsBar")
        self._tabs_bar.setSizePolicy(QSizePolicy.Policy.Preferred,
                                     QSizePolicy.Policy.Fixed)
        tb = QVBoxLayout(self._tabs_bar)
        tb.setContentsMargins(S.s8, S.s4, S.s8, S.s2)
        tb.setSpacing(S.s1)
        tb.addLayout(tab_row)
        tb.addWidget(self._desc_label)
        self._tabs_bar.setStyleSheet(
            f"QWidget#myExpTabsBar {{ background: {C.surface};"
            f" border-bottom: {D.BORDER_W}px solid {C.line}; }}")

        cl.addWidget(self._tabs_bar)
        cl.addWidget(self._stack, 1)

        # P1-2：不再包外层滚动区——5 个子页各自 page_scaffold，
        # 消除"滚动区套滚动区"（页头/tab 固定，内容在子页内滚动）
        self._layout.addLayout(cl)

        # 初始 tab 只切显示不刷数据：懒加载下构建阶段零 API，
        # 首屏数据由主窗口的延迟 refresh（refresh()）触发
        self._switch("experiences", refresh=False)

    # ---------- tab 切换 ----------

    def _switch(self, key: str, refresh: bool = True) -> None:
        idx = next(i for i, (k, _l, _d) in enumerate(self._tabs) if k == key)
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tab_buttons):
            self._style_tab(btn, i == idx)
        self._desc_label.setText(self._tabs[idx][2])
        if refresh:
            self._subpages[idx].refresh()

    @staticmethod
    def _style_tab(btn: QPushButton, selected: bool) -> None:
        # 统一分段开关样式（seg_style：下划线式，选中品牌橙加粗）
        seg_style(btn, selected)

    # ---------- 状态行注入 / 刷新 ----------

    def set_status_bar(self, label: QLabel) -> None:
        """把状态行同时注入给全部子页（子页 set_status 写同一个 label）。"""
        super().set_status_bar(label)
        for p in self._subpages:
            p.set_status_bar(label)

    def refresh(self) -> None:
        """导航到本页时刷新当前 tab 子页。"""
        cur = self._stack.currentWidget()
        if cur is not None and hasattr(cur, "refresh"):
            cur.refresh()

    # ---------- 重新翻译 ----------

    def retranslateUi(self) -> None:
        """语言切换时原地更新 tab 文字和子页文字。"""
        self._tabs = (
            ("experiences", t("经验"), t("原始对话轨迹")),
            ("methods", t("方法"), t("提炼出的可复用做法（可导出 SKILL.md）")),
            ("failures", t("踩过的坑"), t("失败模式（自动记录，留意中不自动带上）")),
            ("prefs", t("偏好"), t("模型行为偏好（自动带上）")),
            ("refutation", t("回炉"), t("被系统反复判定用错而降权/停用的经验，可查看并恢复")),
        )
        # 更新页头标题
        if self._title_label is not None:
            self._title_label.setText(t("我的经验"))
        # 更新 tab 按钮文字
        for i, (_, label, _) in enumerate(self._tabs):
            self._tab_buttons[i].setText(label)
        # 更新描述文字
        idx = self._stack.currentIndex()
        self._desc_label.setText(self._tabs[idx][2])
        # 更新子页文字
        for p in self._subpages:
            if hasattr(p, "retranslateUi"):
                p.retranslateUi()
