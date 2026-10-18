"""Hooks 页的「区三 · 规则模板库」mixin（Qt 版）。

 拆分：从 `app/gui/hooks_page.py` 的 `class HooksPage` 搬出的区块
（原 L1875-2146，约 270 行 / 15 个方法）。这是四刀里**最后一个**动的区块——
动它之前先补了 `tests/test_hooks_template_library.py`（22 个用例），因为原先是
零覆盖：只有 `test_hooks_page_data_rich_render` 一条冒烟断言。

承载：
- 模板库卡（折叠/展开、副题、空态）；
- 类目 chips + 四维筛选（类目 / 优先级 / 领域标签 / 关键词）；
- 模板行（优先级徽标、触发档位下拉）与「导入」动作。

约定与其余 mixin 一致：方法体**逐字搬移**、签名与返回值不变；共享状态
（`api` / 各 `_tpl_*` `_cat_*` `_f_state` 实例属性、`_trigger_labels`、
`_set_status` / `refresh`）留在 `HooksPage` 主体、靠 `self` 访问；
**不 import hooks_page**（避免循环）。

注意 `_trigger_labels`：区块内只用实例属性 `self._trigger_labels`（由 HooksPage
的 `__init__` 与 `retranslateUi` 赋值），模块级那个函数**留在 hooks_page**——
它还被规则卡、工具视图等处用，搬过来会让主模块反向 import。

⚠️ 本 mixin **没有自己的 retranslateUi**（L9b）：语言切换走
`MainWindow._rebuild_visited_pages` 整页重建，区块随 HooksPage 一起重建
（`_load_templates` 按新语言重载）。若将来改回"原地翻译"，必须给本区块补
retranslateUi，否则切语言后模板库会滞留中文。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from . import i18n
from .api_client import LocalApiError
from .i18n import t
from .page_base import clear_layout
from .qt_theme import btn_secondary, card, txt
from .qt_widgets import FlowLayout, SelectButton
from .theme import C, D, F, R, S, SIZES

# 优先级视觉（W4 矩阵重设计）：P0 红 / P1 橙 / P2 黄 / P3 绿 / P4 灰
# 原在 hooks_page 模块级；export_page.py 依赖它（`from .hooks_page import
# _PRI_STYLE`），故搬到本模块后由 hooks_page 再导出，外部 import 不断。
_PRI_STYLE = {
    "p0": ("P0 红线", "err"),
    "p1": ("P1 必须", "brand"),
    "p2": ("P2 应该", "warn"),
    "p3": ("P3 建议", "ok"),
    "p4": ("P4 优化", "ink"),
}
_PRI_ORDER = ("p0", "p1", "p2", "p3", "p4")

# 触发档位键（W4：file 已废弃，manual + 关键词）。原在 hooks_page 模块级，
# 规则卡（hooks_page:1532）与模板行共用，故搬来后由 hooks_page 再导出。
TRIGGER_KEYS = ("smart", "always", "manual", "hard-hook")


class TemplateLibraryMixin:
    """规则模板库：类目 + 四维筛选 + 模板行 + 导入（Hooks 页区三）。"""

    # ---------- 区三 · 模板库 ----------

    def _build_tpl_section(self) -> QFrame:
        c = card()
        lay = c.layout()
        # 卡头：标题 + 副题 + 展开箭头
        hdr = QHBoxLayout()
        hdr.setSpacing(S.s2)
        self._tpl_title = txt(t("模板库"), F.h2, 600)
        hdr.addWidget(self._tpl_title)
        self._tpl_sub = txt(t("挑一套精选模板，按你的偏好导入成规则"),
                            F.caption, color=C.ink_500)
        hdr.addWidget(self._tpl_sub, 1)
        self._tpl_caret = QPushButton("▾")
        self._tpl_caret.setCursor(Qt.PointingHandCursor)
        self._tpl_caret.setFixedSize(D.ICON_BOX, D.ICON_BOX)
        self._tpl_caret.setStyleSheet(
            f"QPushButton {{ color: {C.ink_500}; border: none; "
            f"background: transparent; font-size: {F.body}px; }}"
            f" QPushButton:hover {{ color: {C.ink_700}; }}")
        self._tpl_caret.clicked.connect(self._toggle_tpl)
        hdr.addWidget(self._tpl_caret, 0, Qt.AlignVCenter)
        hdr_w = QWidget()
        hdr_w.setLayout(hdr)
        lay.addWidget(hdr_w)
        # 翻译备注（非 zh 才显示）
        self._tpl_note = None
        if i18n.current_language() != "zh":
            self._tpl_note = txt(t("模板正文由中文原版经 AI 翻译，个别措辞可能不准"
                                   "——导入后建议过一遍再启用"),
                                 F.caption, color=C.ink_500, wrap=True)
            lay.addWidget(self._tpl_note)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(S.s2)
        cat_w = QWidget()
        self._cat_chips_row = FlowLayout(cat_w, spacing=S.s1)
        self._cat_chips_row.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(cat_w)
        filter_w = QWidget()
        # 筛选行用 FlowLayout：优先级 chip 组 + 领域下拉 + 搜索框三者的**固定最小宽**
        # 合计 ≈714px（按钮不可压缩、下拉/搜索框是 setFixedWidth）。中文下内容区宽
        # (~849) 容得下，但德语等导航栏更宽（实测 234px）→ 内容区只剩 ~765，该行
        # 撑爆列宽 → 横向滚动条。FlowLayout 最小宽 = 最宽子项，放不下自动换行。
        self._filter_row = FlowLayout(filter_w, spacing=S.s2)
        self._filter_row.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(filter_w)
        self._tpl_list_box = QWidget()
        self._tpl_list_lay = QVBoxLayout(self._tpl_list_box)
        self._tpl_list_lay.setContentsMargins(0, 0, 0, 0)
        self._tpl_list_lay.setSpacing(S.s3)
        bl.addWidget(self._tpl_list_box)
        # body 此刻尚无父控件，setVisible(True) 会开出一个真顶层窗口；只在收起时隐藏
        if not self._tpl_open:
            body.hide()
        self._tpl_body = body
        lay.addWidget(body)
        return c

    def _toggle_tpl(self) -> None:
        self._tpl_open = not self._tpl_open
        self._tpl_caret.setText("▾" if self._tpl_open else "▸")
        self._tpl_body.setVisible(self._tpl_open)

    def _goto_templates(self) -> None:
        """空状态引导：展开模板库并滚到可见（空状态 = 行动入口）。"""
        if not self._tpl_open:
            self._toggle_tpl()
        scroll = getattr(self, "_page_scroll", None)
        if scroll is not None:
            scroll.ensureWidgetVisible(self._tpl_card_ref)

    def _load_templates(self) -> bool:
        """按当前界面语言加载模板库（语言切换等就地重刷用）。"""
        try:
            data = self.api.templates(i18n.current_language())
        except LocalApiError:
            data = None
        return self._render_templates(data)

    def _render_templates(self, data) -> bool:
        """渲染模板库；失败不崩（模板缺失只影响本区）。"""
        if not isinstance(data, dict):
            clear_layout(self._tpl_list_lay)
            self._tpl_list_lay.addWidget(txt(t("模板库加载失败"), F.caption, color=C.err_fg))
            return False
        self._tpl_holder[:] = data.get("categories", [])
        self._cat_state[0] = 0
        self._render_category_chips()
        self._build_filter_row()
        self._render_tpl_list()
        return True

    def _render_category_chips(self) -> None:
        clear_layout(self._cat_chips_row)
        cats = self._tpl_holder or []
        for i, c in enumerate(cats):
            active = i == self._cat_state[0]
            btn = QPushButton(t(c["label_key"]))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(D.BTN_H_SM)
            btn.setStyleSheet(
                f"QPushButton {{ background: {C.primary_fill if active else C.surface}; "
                f"color: {C.on_brand if active else C.ink_700}; "
                f"border: {D.BORDER_W}px solid {C.primary_fill if active else C.line}; "
                f"border-radius: {R.xl}px; padding: 2px 12px; "
                f"font-weight: {'600' if active else '400'}; }}"
                + ("" if active else
                   f" QPushButton:hover {{ background: {C.brand_100};"
                   f" color: {C.brand_700}; border-color: {C.brand_400}; }}"))
            btn.clicked.connect(lambda _=False, i_=i: self._pick_category(i_))
            self._cat_chips_row.addWidget(btn)

    def _pick_category(self, i: int) -> None:
        self._cat_state[0] = i
        self._render_category_chips()
        self._render_tpl_list()

    def _build_filter_row(self) -> None:
        """优先级 chip + 领域标签 + 关键词搜索（W4 四维筛选的另三维）。"""
        clear_layout(self._filter_row)
        cats = self._tpl_holder or []
        all_tags: list[str] = []
        for c in cats:
            for tpl in c.get("templates", []):
                for tag in tpl.get("tags", []):
                    if tag not in all_tags:
                        all_tags.append(tag)
        all_tags.sort()
        pri_box = QWidget()
        pri_lay = QHBoxLayout(pri_box)
        pri_lay.setContentsMargins(0, 0, 0, 0)
        pri_lay.setSpacing(S.s1)
        for key, label in [("all", t("全部"))] + [
                (p, t(_PRI_STYLE[p][0])) for p in _PRI_ORDER]:
            active = self._f_state["pri"] == key
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(D.BTN_H_SM)
            btn.setStyleSheet(
                f"QPushButton {{ background: {C.primary_fill if active else C.surface}; "
                f"color: {C.on_brand if active else C.ink_700}; "
                f"border: {D.BORDER_W}px solid {C.primary_fill if active else C.line}; "
                f"border-radius: {R.xl}px; "
                f"padding: {D.CHIP_PAD_Y}px {D.CHIP_PAD_X}px; "
                f"font-weight: {'600' if active else '400'}; }}"
                + ("" if active else
                   f" QPushButton:hover {{ background: {C.brand_100};"
                   f" color: {C.brand_700}; border-color: {C.brand_400}; }}"))
            btn.clicked.connect(lambda _=False, k=key: self._set_pri_filter(k))
            pri_lay.addWidget(btn)
        pri_lay.addStretch(1)
        self._filter_row.addWidget(pri_box)
        tag_btn = SelectButton(width=D.DD_W_XS)
        tag_btn.addItem(t("全部领域"), "all")
        for tag in all_tags:
            tag_btn.addItem(t(tag), tag)
        idx = tag_btn.findData(self._f_state.get("tag", "all"))
        tag_btn.setCurrentIndex(idx if idx >= 0 else 0)
        tag_btn.currentIndexChanged.connect(self._on_tag_menu)
        self._filter_row.addWidget(tag_btn)
        q_tf = QLineEdit(self._f_state["q"])
        q_tf.setPlaceholderText(t("搜索模板名 / 描述 / 关键词"))
        q_tf.setFixedWidth(D.FIELD_W)
        q_tf.setFixedHeight(D.BTN_H_SM)
        q_tf.returnPressed.connect(lambda: self._on_search(q_tf.text()))
        self._filter_row.addWidget(q_tf)

    def _set_pri_filter(self, key: str) -> None:
        self._f_state["pri"] = key
        self._build_filter_row()
        self._render_tpl_list()

    def _on_tag_menu(self, _idx: int) -> None:
        btn = self.sender()
        tag = btn.currentData() or "all" if isinstance(btn, SelectButton) else "all"
        if tag == self._f_state["tag"]:
            return
        self._f_state["tag"] = tag
        self._render_tpl_list()

    def _on_search(self, q: str) -> None:
        self._f_state["q"] = q or ""
        self._render_tpl_list()

    def _tpl_matches(self, tpl: dict) -> bool:
        """四维筛选（W4：类目 + 优先级 + 领域标签 + 关键词）。类目由 chip 选定。"""
        if self._f_state["pri"] != "all" and tpl.get("priority") != self._f_state["pri"]:
            return False
        if self._f_state["tag"] != "all" and self._f_state["tag"] not in tpl.get("tags", []):
            return False
        q = self._f_state["q"].strip().lower()
        if q:
            hay = " ".join([tpl.get("name", ""), tpl.get("description", ""),
                            " ".join(tpl.get("keywords", [])),
                            " ".join(tpl.get("tags", []))]).lower()
            if q not in hay:
                return False
        return True

    def _render_tpl_list(self) -> None:
        clear_layout(self._tpl_list_lay)
        cats = self._tpl_holder or []
        cat = (cats[self._cat_state[0]]
               if self._cat_state[0] < len(cats) else {})
        shown = [x for x in cat.get("templates", []) if self._tpl_matches(x)]
        if not shown:
            self._tpl_list_lay.addWidget(
                txt(t("没有匹配的模板"), F.body, color=C.ink_500))
            return
        for tpl in shown:
            self._tpl_list_lay.addWidget(self._template_row(tpl))

    def _template_row(self, tpl: dict) -> QFrame:
        pri = tpl.get("priority", "p3")
        is_p0 = pri == "p0"
        default_trig = tpl.get("trigger_default", "smart")
        if is_p0:
            trig_ctrl: QWidget = self._locked_trig(t("每次必须发生（锁定）"))
        else:
            trig_ctrl = SelectButton(width=D.DD_W_MD)
            for k in TRIGGER_KEYS:
                if k in self._trigger_labels:
                    trig_ctrl.addItem(self._trigger_labels[k], k)
            idx = trig_ctrl.findData(default_trig)
            trig_ctrl.setCurrentIndex(max(0, idx))
        native_note = "" if tpl.get("native", True) else t("无原生范本（用英文版）")
        # 反例用 P0 红标同款视觉前置（最多 2 条）
        donts_lines = [
            txt(t("红线：{d}", d=d) if is_p0 else t("绝不：{d}", d=d),
                F.caption, color=C.err_fg)
            for d in (tpl.get("donts") or [])[:2]
        ]
        c = card()
        main_row = QHBoxLayout()
        main_row.setSpacing(S.s2)
        col = QVBoxLayout()
        col.setSpacing(S.s2)
        h1 = QHBoxLayout()
        h1.setSpacing(S.s1)
        h1.addWidget(self._pri_chip(pri))
        h1.addWidget(txt(tpl["name"], F.body, 600))
        if native_note:
            h1.addWidget(txt(native_note, F.caption, color=C.ink_500))
        h1.addStretch(1)
        h1_w = QWidget()
        h1_w.setLayout(h1)
        col.addWidget(h1_w)
        col.addWidget(txt(tpl.get("description", ""), F.caption, color=C.ink_500))
        for d in donts_lines:
            col.addWidget(d)
        col_w = QWidget()
        col_w.setLayout(col)
        col_w.setMaximumWidth(SIZES.CONTENT_FORM)
        main_row.addWidget(col_w, 1)
        main_row.addWidget(trig_ctrl, 0, Qt.AlignVCenter)
        imp = btn_secondary(t("导入"))
        imp.setFixedHeight(D.BTN_H_SM)
        imp.clicked.connect(
            lambda _=False, t_=tpl, sel=trig_ctrl, hard=is_p0:
            self._do_import(t_, "hard-hook" if hard
                            else (sel.currentData() or default_trig)))
        main_row.addWidget(imp, 0, Qt.AlignVCenter)
        row_w = QWidget()
        row_w.setLayout(main_row)
        c.layout().addWidget(row_w)
        return c

    def _do_import(self, tpl: dict, trig_value: str) -> None:
        """导入模板。

        import_template 原同步跑在 UI 线程（api_client 侧
        15s 超时）——引擎未起/卡住时点「导入」冻结界面最长 15 秒。改后台执行：
        忙态闸防重复提交，完成回主线程落状态并刷新。"""
        if getattr(self, "_tpl_busy", False):
            return
        self._tpl_busy = True
        self._set_status(t("正在处理…"), "info")

        def work():
            return self.api.import_template(
                tpl["id"], trig_value, i18n.current_language())

        def done(_r) -> None:
            self._tpl_busy = False
            self._set_status(t("已导入模板「{name}」", name=tpl["name"]), "ok")
            self.refresh()

        def err(e) -> None:
            self._tpl_busy = False
            self._set_status(str(e), "err")

        self.run_async(work, done, err)

