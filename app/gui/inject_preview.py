"""「模型会看到什么」页——Qt 版（迁移自 Flet inject_preview.py）。

注入预览 + 逐条开关/改写/AI 优化/恢复默认。覆盖层与资产解耦：
这里改的是 injection_overrides.json，不动 playbook/偏好文件。
此页会被 ConnectPage 内嵌（self.content 直接加入外层滚动），也独立可用。
"""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QHBoxLayout, QPushButton, QTextEdit,
                               QVBoxLayout, QWidget)

from .ai_rewrite import is_model_required
from . import _name_map as name_map
from .api_client import LocalApi, LocalApiError
from .i18n import t
from .page_base import PageBase, build_centered_scroll
from .qt_theme import (btn_flat, btn_primary, btn_secondary, chip, empty_state,
                       icon_button, provenance_bar, status_text, switch, txt)
from .qt_widgets import SelectButton
from .theme import C, D, F, R, S

def _kind_labels() -> dict:
    return {"pref": t("你的偏好"), "failure": t("踩坑"),
            "flow": t("标准流程"), "insight": t("经验要点")}


class InjectPreviewPage(PageBase):
    """注入预览：trunk/category 选择 + 查看 + 逐条开关/改写/AI 优化/恢复。"""

    def __init__(self, api: LocalApi, parent: QWidget | None = None,
                 embedded: bool = False):
        super().__init__(api, parent)
        self._embedded = embedded
        # 可预览的类别选项（trunk / 每 trunk 的 category）：后台取一次后缓存，
        # 之后换 trunk、轮询刷新都只读内存，不再发同步请求
        self._options: dict | None = None
        self._build()
        # 懒加载下构建阶段零 API：选项与预览数据都由 _ensure_options / refresh
        # 的后台取数填充（构建期同步请求曾让首开接入页冻 6s+）

    # ---------- 构建 ----------

    def _build(self) -> None:
        self.content = QWidget()
        self._cl = QVBoxLayout(self.content)
        self._cl.setContentsMargins(0, 0, 0, 0)
        self._cl.setSpacing(S.s6)

        # 标题行
        head = QHBoxLayout()
        head.setSpacing(S.s2)
        self._head_text = txt(t("每次任务自动带上什么"),
                           F.h2 if self._embedded else F.h1, 800)
        head.addWidget(self._head_text)
        head.addStretch(1)
        self._desc_text = txt(
            t("这里看到的是每次任务自动带上的内容——开关和改写只改你改过的部分，"
              "不动方法原文"), F.caption, color=C.ink_500, wrap=True)
        head.addWidget(self._desc_text)
        head_box = QWidget()
        head_box.setLayout(head)
        self._cl.addWidget(head_box)

        # 选择行：trunk / category + 查看按钮 + 预算
        sel = QHBoxLayout()
        sel.setSpacing(S.s2)
        self._sel_label = txt(t("当前任务"), F.body, color=C.ink_700)
        sel.addWidget(self._sel_label)
        # 页面滚动区内的选择器用 SelectButton（QMenu 顶层弹层）
        self._trunk_dd = SelectButton(width=D.DD_W)
        self._trunk_dd.currentIndexChanged.connect(self._on_trunk_changed)
        self._cat_dd = SelectButton(width=D.DD_W)
        sel.addWidget(self._trunk_dd)
        sel.addWidget(txt("/", F.body, color=C.ink_500))
        sel.addWidget(self._cat_dd)
        sel.addStretch(1)
        self._budget_text = txt("", F.caption, color=C.ink_500)
        sel.addWidget(self._budget_text)
        self._view_btn = btn_secondary(t("查看"), on_click=self._view)
        sel.addWidget(self._view_btn)
        sel_box = QWidget()
        sel_box.setLayout(sel)
        self._cl.addWidget(sel_box)

        # 失效修改横幅
        self._stale_banner = QWidget()
        self._stale_banner.setObjectName("staleBanner")
        self._stale_lay = QHBoxLayout(self._stale_banner)
        self._stale_lay.setContentsMargins(S.s3, S.s3, S.s3, S.s3)
        self._stale_lay.setSpacing(S.s2)
        # #id 限定：裸 QWidget 选择器会级联到 clear_btn，顶掉 flat 按钮透明底
        self._stale_banner.setStyleSheet(
            f"QWidget#staleBanner {{ background: {C.warn_bg}; border-radius: {R.md}px; }}")
        self._stale_banner.hide()
        self._cl.addWidget(self._stale_banner)

        # 状态行
        self._status = status_text()
        self._cl.addWidget(self._status)

        # 溯源条：内容是模型产物还是旧的本机整理产物，如实披露。
        # 只在 content_source == "none" 且有内容时亮条（qt_theme.provenance_bar 口径）
        self._prov_box = QWidget()
        self._prov_lay = QVBoxLayout(self._prov_box)
        self._prov_lay.setContentsMargins(0, 0, 0, 0)
        self._prov_box.hide()
        self._cl.addWidget(self._prov_box)

        # 条目列表
        self._item_box = QWidget()
        self._item_layout = QVBoxLayout(self._item_box)
        self._item_layout.setContentsMargins(0, 0, 0, 0)
        self._item_layout.setSpacing(S.s2)
        self._cl.addWidget(self._item_box)

        # 初始下拉选项留空：等 _render_options 拿到后台取回的数据再填
        # （构建期不发任何请求）

        # 尾部 stretch：内容不足时靠顶排布，避免卡片被视口拉高（同 home 收尾）
        self._cl.addStretch(1)

        # 内嵌时跳过滚动包装（同 ModelsPage 修复）：否则 _cl 被搬进挂在不可见
        # 页根上的内部滚动区，外层拿 self.content 是空壳
        if not self._embedded:
            self._wrap_scroll()

    def _wrap_scroll(self) -> None:
        """独立可用时的滚动包装（内嵌 ConnectPage 时外层统一滚动，不走这里）。"""
        self._cl.setContentsMargins(S.s8, S.s8, S.s8, S.s8)
        scroll = build_centered_scroll(self._cl)
        self._layout.addWidget(scroll)

    # ---------- 重新翻译 ----------

    def retranslateUi(self) -> None:
        """语言切换时更新静态文字并刷新内容。"""
        self._head_text.setText(t("每次任务自动带上什么"))
        self._desc_text.setText(
            t("这里看到的是每次任务自动带上的内容——开关和改写只改你改过的部分，"
              "不动方法原文"))
        self._sel_label.setText(t("当前任务"))
        self._view_btn.setText(t("查看"))
        self.refresh()

    # ---------- 下拉选项 ----------

    def _ensure_options(self) -> None:
        """类别选项后台取一次；取回后自动填下拉并出首版预览。

        与页面数据同一套 H3 口径：取数在工作线程、渲染回到主线程；同名"在飞"
        去重由基类 fetch_and_render 保证（30s 轮询撞上不会重复发）。
        """
        if self._options is not None:
            return
        self.fetch_and_render(self._fetch_options, self._render_options,
                              name="options")

    def _fetch_options(self) -> dict:
        """工作线程：取可预览的 trunk / category（只取数，不碰 widget）。

        口径与旧实现一致（skills 清单 ∪ 经验清单，各自取其 trunk/category）；
        差别只在经验清单用一次大 limit 取回本地归并，不再按 trunk 逐个再发
        一轮请求——旧实现每换一次 trunk 就在主线程同步发一次 HTTP。
        """
        skills_items: list[dict] = []
        exp_items: list[dict] = []
        try:
            skills_items = self.api.skills().get("items") or []
        except LocalApiError:
            pass
        try:
            exp_items = self.api.experiences(limit=500).get("items") or []
        except LocalApiError:
            pass
        trunks = {str(s.get("trunk")) for s in skills_items if s.get("trunk")}
        trunks |= {str(e.get("trunk")) for e in exp_items if e.get("trunk")}
        cats: dict[str, list[str]] = {}
        for tr in trunks:
            got = {str(s.get("category")) for s in skills_items
                   if s.get("trunk") == tr and s.get("category")}
            got |= {str(e.get("category")) for e in exp_items
                    if e.get("trunk") == tr and e.get("category")}
            cats[tr] = sorted(got)
        return {"trunks": sorted(trunks), "cats": cats, "skills": skills_items}

    def _render_options(self, result) -> None:
        """主线程：选项就绪 → 填下拉（保留当前选择）→ 立刻出一版预览。"""
        if not isinstance(result, dict):
            # 取不到 = 请求没回来（口径同 growth.py 的 res 为空分支）
            self._set_status(t("本地 API 未连接"))
            return
        # 去重 R2：与 skill_organize 共用一份 name_map。这里用 replace（先清后填）
        # 而非增量——否则改名后旧 (trunk, category) 键会残留在进程内存里。
        name_map.replace(result.get("skills"))
        self._options = result
        self._populate_trunk()
        self.refresh()

    def _populate_trunk(self) -> None:
        """按已取回的选项重建 trunk 下拉（纯内存，零 HTTP）；保留当前选择。"""
        opts = self._options or {}
        trunks = list(opts.get("trunks") or [])
        keep = self._trunk_dd.currentData()
        self._trunk_dd.blockSignals(True)
        self._trunk_dd.clear()
        for x in trunks:
            self._trunk_dd.addItem(x, x)
        # 轮询刷新不得把用户选好的任务类别重置回第一项
        idx = self._trunk_dd.findData(keep) if keep in trunks else -1
        if idx >= 0:
            self._trunk_dd.setCurrentIndex(idx)
        self._trunk_dd.blockSignals(False)
        self._populate_categories()

    def _populate_categories(self) -> None:
        trunk = self._trunk_dd.currentData()
        cats = ((self._options or {}).get("cats") or {}).get(trunk, [])
        keep = self._cat_dd.currentData()
        self._cat_dd.blockSignals(True)
        self._cat_dd.clear()
        # R4：类别下拉优先显示名（说人话），key 仍是原始类别（API 不变）
        for c in cats:
            self._cat_dd.addItem(name_map.get_name(trunk, c) or c, c)
        idx = self._cat_dd.findData(keep) if keep in cats else -1
        if idx >= 0:
            self._cat_dd.setCurrentIndex(idx)
        self._cat_dd.blockSignals(False)

    def _on_trunk_changed(self, _idx: int) -> None:
        self._populate_categories()

    def _view(self) -> None:
        self.refresh()

    # ---------- 数据 ----------

    def refresh(self) -> None:
        self._ensure_options()
        if self._options is None:
            # 选项还在后台取：先给个明确状态；取回后 _render_options 会再刷一次
            self._clear(self._item_layout)
            self._stale_banner.hide()
            self._prov_box.hide()
            self._set_status(t("正在处理…"), "info")
            return
        trunk = self._trunk_dd.currentData()
        category = self._cat_dd.currentData()
        if not trunk or not category:
            self._clear(self._item_layout)
            self._item_layout.addWidget(empty_state(
                t("没有可预览的任务类别"), t("先总结出一个方法"), mascot="think"))
            self._stale_banner.hide()
            self._prov_box.hide()
            self._set_status("", "info")
            return
        # 取数走后台线程（主线程零 HTTP），渲染回主线程
        # S5：补首屏骨架（此前本页取数期间无占位）
        self.fetch_and_render(
            lambda: self.api.injection_preview(trunk, category),
            self._render_preview, name="preview", skeleton=[24, 88, 64])

    def _render_preview(self, prev) -> None:
        """主线程：渲染预览内容（prev 为 None = 后台取数失败）。"""
        if not isinstance(prev, dict):
            self._set_status(t("本地 API 未连接"))
            return
        used, budget = prev.get("used", 0), prev.get("budget", 800)
        self._budget_text.setText(
            t("占用 {used} / {budget}", used=used, budget=budget))
        stale_ids = prev.get("stale_overrides", [])
        self._rebuild_stale(bool(stale_ids), len(stale_ids))
        # 内容溯源披露：只展示，不改注入门槛
        self._rebuild_provenance(prev.get("content_source") or "",
                                 prev.get("generated_at") or "",
                                 bool(prev.get("items")))
        self._clear(self._item_layout)
        kind_labels = _kind_labels()
        rows = []
        for it in prev.get("items", []):
            rows.append(self._item_row(it, kind_labels))
        if not rows:
            self._item_layout.addWidget(txt(
                t("这个类别还没有可自动带上的内容"),
                color=C.ink_500, italic=True))
        else:
            for w in rows:
                self._item_layout.addWidget(w)

    def _rebuild_provenance(self, source: str, generated_at: str,
                            has_content: bool) -> None:
        """顶部溯源条：命中"旧的本机整理产物"才亮（其余态不打扰）。"""
        self._clear(self._prov_lay)
        bar = provenance_bar({"content_source": source,
                              "generated_at": generated_at,
                              "has_content": has_content})
        if bar is None:
            self._prov_box.hide()
            return
        self._prov_lay.addWidget(bar)
        self._prov_box.show()

    def _item_row(self, it: dict, kind_labels: dict) -> QWidget:
        label = kind_labels.get(it["kind"], it["kind"])
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S.s2)
        # 单条启停：一元素一职，用 switch()（方框留给"选择"语义）
        sw = switch(it["enabled"])
        sw.toggled.connect(lambda checked, i=it: self._toggle_item(i, checked))
        lay.addWidget(sw)
        col = QVBoxLayout()
        col.setSpacing(S.s1)
        head = QHBoxLayout()
        head.addWidget(txt(label, F.caption, color=C.ink_500))
        head.addStretch(1)
        col.addLayout(head)
        text = txt(it["effective_text"], F.body, italic=it["overridden"])
        text.setWordWrap(True)
        col.addWidget(text)
        lay.addLayout(col, 1)
        if it["overridden"]:
            lay.addWidget(chip(t("已改写"), "warn"))
        lay.addWidget(icon_button("EDIT_OUTLINED", t("改写"),
                                  lambda _=False, i=it: self._edit_item(i)))
        # AI 优化：文字按钮走 btn_flat 工厂（不再裸 setProperty class）
        opt_btn = btn_flat(t("AI 优化"))
        opt_btn.setFixedHeight(D.BTN_H_XS)
        opt_btn.clicked.connect(
            lambda _=False, i=it: self._optimize_item(i, opt_btn))
        lay.addWidget(opt_btn)
        if it["overridden"] or not it["enabled"]:
            lay.addWidget(icon_button("REFRESH_OUTLINED", t("恢复默认"),
                                      lambda _=False, i=it: self._restore(i)))
        return row

    def _rebuild_stale(self, visible: bool, n: int) -> None:
        self._clear(self._stale_lay)
        if not visible:
            self._stale_banner.hide()
            return
        self._stale_lay.addWidget(txt(
            t("有 {n} 条你改过的内容，对应的方法条目已升级或淘汰，改动已失效",
              n=n), F.caption, color=C.warn_fg, wrap=True), 1)
        clear_btn = btn_flat(t("清理失效修改"), on_click=self._clear_stale)
        self._stale_lay.addWidget(clear_btn)
        self._stale_banner.show()

    def _set_status(self, msg: str, tone: str = "err") -> None:
        colors = {"ok": C.ok_fg, "err": C.err_fg, "warn": C.warn_fg,
                  "info": C.info_fg}
        self._status.setText(msg)
        self._status.setStyleSheet(
            f"color: {colors[tone]}; border: none; background: transparent;")

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                InjectPreviewPage._clear(item.layout())

    # ---------- 操作 ----------

    def _toggle_item(self, item: dict, checked: bool) -> None:
        try:
            self.api.set_override(item["id"], enabled=bool(checked))
            self.refresh()
        except LocalApiError as exc:
            self._set_status(exc.localized())

    def _edit_item(self, item: dict) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(t("改写这条"))
        lay = QVBoxLayout(dlg)
        lay.setSpacing(S.s2)
        tf = QTextEdit(item["effective_text"])
        tf.setPlaceholderText(t("改写后的内容"))
        tf.setMinimumHeight(120)
        lay.addWidget(tf)
        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_secondary(t("取消"), on_click=dlg.reject))
        btn_row.addStretch(1)

        def save() -> None:
            try:
                self.api.set_override(item["id"], text=tf.toPlainText())
                dlg.accept()
                self.refresh()
            except LocalApiError as exc:
                self._set_status(exc.localized())

        btn_row.addWidget(btn_primary(t("应用"), on_click=save))
        lay.addLayout(btn_row)
        dlg.exec()
        dlg.deleteLater()

    def _optimize_item(self, item: dict, btn: QPushButton) -> None:
        if not self.require_model(t("AI 优化")):
            return
        btn.setEnabled(False)
        btn.setText(t("AI 优化中…"))
        self.run_async(
            lambda: self.api.optimize_override(item["effective_text"]),
            lambda payload: self._on_optimized(item, payload, btn),
            lambda err: self._on_optimize_fail(err, btn))

    def _on_optimized(self, item: dict, payload, btn: QPushButton) -> None:
        """只认真的 AI 产物：结构化拒绝 / 空文本都如实提示，绝不拿原文顶替。"""
        btn.setEnabled(True)
        btn.setText(t("AI 优化"))
        if is_model_required(payload):
            # 文案优先用引擎/本地 API 回的（含"去接入页"引导），否则复用既有目录 key
            self._set_status(str(payload.get("message")
                                 or t("未接入模型，无法完成这一步")), "warn")
            return
        new_text = str((payload or {}).get("text") or "").strip()
        if not new_text:
            self._set_status(t("AI 没有给出可用的重写"), "warn")
            return
        self._confirm_optimize(item, new_text)

    def _on_optimize_fail(self, err: str, btn: QPushButton) -> None:
        btn.setEnabled(True)
        btn.setText(t("AI 优化"))
        self._set_status(str(err))

    def _confirm_optimize(self, item: dict, new_text: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(t("AI 优化结果（确认后生效）"))
        lay = QVBoxLayout(dlg)
        lay.setSpacing(S.s2)
        lay.addWidget(txt(t("原："), F.caption, color=C.ink_500))
        orig = txt(item["effective_text"], F.body)
        orig.setWordWrap(True)
        lay.addWidget(orig)
        lay.addWidget(txt(t("改："), F.caption, color=C.brand_700))
        new = txt(new_text, F.body)
        new.setWordWrap(True)
        lay.addWidget(new)
        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_secondary(t("取消"), on_click=dlg.reject))
        btn_row.addStretch(1)

        def apply() -> None:
            try:
                self.api.set_override(item["id"], text=new_text)
                dlg.accept()
                self.refresh()
            except LocalApiError as exc:
                self._set_status(exc.localized())

        btn_row.addWidget(btn_primary(t("应用"), on_click=apply))
        lay.addLayout(btn_row)
        dlg.exec()
        dlg.deleteLater()

    def _restore(self, item: dict) -> None:
        try:
            self.api.clear_override(item["id"])
            self.refresh()
        except LocalApiError as exc:
            self._set_status(exc.localized())

    def _clear_stale(self) -> None:
        try:
            r = self.api.clear_stale_overrides()
            self._set_status(t("已清理 {n} 条失效修改",
                               n=r.get("removed", 0)), "ok")
            self.refresh()
        except LocalApiError as exc:
            self._set_status(exc.localized())
