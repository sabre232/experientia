"""导出页（Qt 版，对应 Flet 源文件 app/gui/export_page.py；M1 信息架构重构）：
三件套三卡。

1. 导出 Skill（内嵌 SkillOrganizePage：按类一键 / 勾选精选 + SKILL.md 预览/版本；
   产物 frontmatter 自动补 dos/donts，E-05）
2. 导出 md（5 粒度：经验记录 / 方法和坑 / 成长报告 / 偏好画像 / 阶段经验
   + 全量打包；经验、方法支持勾选精选，纯数据导出）
3. 导出 Hooks（「我的 Hooks」逐条勾选 → 单个 md，每 hook 带 frontmatter 一节）

术语：Skill / md / Hooks 均为用户话术或生态词，直接用；
机制词（蒸馏/注入/路由…）不入文案。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
                               QWidget)

from . import i18n
from .api_client import LocalApi, LocalApiError
from .i18n import t
from .page_base import (PageBase, clear_layout, page_scaffold,
                        parallel_fetch)
from .qt_theme import (btn_flat, btn_primary, btn_secondary, card, icon_widget,
                       status_text, status_tone, switch, txt)
from .qt_widgets import page_header
from .skill_organize import SkillOrganizePage
from .theme import C, D, F, R, S, SIZES, TONE_BG, TONE_FG


# _clear_layout → page_base.clear_layout（统一入口）


def _phase_since(key: str) -> str:
    """阶段经验时间窗：client 算 since，后端 until 缺省今天。"""
    from datetime import date, timedelta

    today = date.today()
    if key == "month":
        return today.replace(day=1).isoformat()
    return (today - timedelta(days=int(key))).isoformat()


def _tone_chip(label: str, tone: str) -> QFrame:
    """语义色小标签（与 Hooks 页优先级视觉一致）。"""
    fg = TONE_FG.get(tone, C.ink_500)
    bg = TONE_BG.get(tone, C.surface_2)
    frame = QFrame()
    frame.setStyleSheet(
        f"QFrame {{ background: {bg}; border: none; border-radius: {R.xl}px; }}")
    lay = QHBoxLayout(frame)
    lay.setContentsMargins(D.CHIP_PAD_X, D.CHIP_PAD_Y, D.CHIP_PAD_X, D.CHIP_PAD_Y)
    lay.setSpacing(S.s1)
    lay.addWidget(txt(label, F.caption, 600, fg))
    return frame


def _export_center_item(icon_name: str, title: str, desc: str, on_click,
                        accent_color: str) -> QFrame:
    """导出中心列表项：左侧 3px 色条 + 图标 + 标题 + 描述 + 右箭头。"""
    box = QFrame()
    box.setCursor(Qt.PointingHandCursor)
    box.setFixedHeight(SIZES.EXPORT_ITEM_HEIGHT)
    box.setStyleSheet(f"""
        QFrame {{ background: {C.surface}; border: 1px solid {C.line};
                  border-radius: {R.md}px; }}
        QFrame:hover {{ background: {C.surface_2}; }}
    """)
    box.mousePressEvent = lambda e: on_click()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, S.s2, S.s3, S.s2)
    lay.setSpacing(S.s3)
    accent = QFrame()
    accent.setFixedWidth(SIZES.EXPORT_ACCENT_WIDTH)
    accent.setStyleSheet(
        f"background: {accent_color}; border: none; border-radius: 8px;")
    lay.addWidget(accent)
    lay.addWidget(icon_widget(icon_name, SIZES.ICON_NAV, C.ink_700))
    text_col = QVBoxLayout()
    text_col.setSpacing(S.s2)
    text_col.addWidget(txt(title, F.h2))
    text_col.addWidget(txt(desc, F.caption, color=C.ink_500))
    lay.addLayout(text_col, 1)
    lay.addWidget(icon_widget("CHEVRON_RIGHT_OUTLINED", 18, C.ink_500))
    return box


class ExportPage(PageBase):
    """导出页：数据导出 / 规则导出弹层 + 内嵌 Skill 导出子区。"""

    def __init__(self, api: LocalApi, parent: QWidget | None = None):
        super().__init__(api, parent)
        self._build()

    def _build(self) -> None:
        cl = QVBoxLayout()
        cl.setSpacing(S.s6)

        # 统一页头（S1）
        head = page_header(
            t("导出"),
            t("导出会按主题分类打包：经验按领域打包，规则按模板类目打包"))
        self._export_heading = head.findChild(QLabel, "pageTitle")
        self._export_subtitle = head.findChild(QLabel, "pageSubtitle")
        cl.addWidget(head)

        self._data_export_item = _export_center_item(
            "FOLDER_OUTLINED", t("数据导出"),
            t("经验记录 · 方法和坑 · 成长报告 · 偏好画像 · 阶段经验"),
            self._show_data_export, C.ok_fg)
        cl.addWidget(self._data_export_item)
        self._hooks_export_item = _export_center_item(
            "RULE_FOLDER_OUTLINED", t("规则导出"),
            t("导出我的 Hooks（带 frontmatter）"),
            self._show_hooks_export, C.info_fg)
        cl.addWidget(self._hooks_export_item)

        # Skill 导出子区（内嵌 SkillOrganizePage，直接上页）
        skill_card = card(title=t("技能导出"))
        _card_lay = skill_card.layout()
        self._skill_card_title = _card_lay.itemAt(0).widget()
        self._skill_subtitle = txt(
            t("生成技能文件，可被 Claude Code / Codex 直接加载"),
            F.caption, color=C.ink_500)
        _card_lay.insertWidget(1, self._skill_subtitle)
        self._skill_page = SkillOrganizePage(self.api, self)
        _card_lay.addWidget(self._skill_page)
        cl.addWidget(skill_card)

        # 尾部 stretch：内容不足时靠顶排布，避免卡片被视口拉高（同 home 收尾）
        cl.addStretch(1)

        # S2：统一骨架（顶边 32px 由页头给）
        scroll = page_scaffold(cl, top=0)
        self._layout.addWidget(scroll, 1)

    def refresh(self) -> None:
        if hasattr(self, "_skill_page"):
            self._skill_page.refresh()

    def retranslateUi(self) -> None:
        """重新调用 t() 更新所有静态 widget 文本。"""
        self._export_heading.setText(t("导出"))
        self._export_subtitle.setText(
            t("导出会按主题分类打包：经验按领域打包，规则按模板类目打包"))
        # 数据导出 item
        text_col = self._data_export_item.layout().itemAt(2)
        text_col.layout().itemAt(0).widget().setText(t("数据导出"))
        text_col.layout().itemAt(1).widget().setText(
            t("经验记录 · 方法和坑 · 成长报告 · 偏好画像 · 阶段经验"))
        # 规则导出 item
        text_col2 = self._hooks_export_item.layout().itemAt(2)
        text_col2.layout().itemAt(0).widget().setText(t("规则导出"))
        text_col2.layout().itemAt(1).widget().setText(
            t("导出我的 Hooks（带 frontmatter）"))
        self._skill_card_title.setText(t("技能导出"))
        self._skill_subtitle.setText(
            t("生成技能文件，可被 Claude Code / Codex 直接加载"))

    # ---------- 导出中心弹层 ----------

    def _export_meta(self) -> tuple:
        """trunks / cats / name_map（R4 显示名）——**工作线程**执行，不碰控件。

        两次取数并行（``parallel_fetch``），失败兜底空数据。"""
        res = parallel_fetch({
            "exps": lambda: self.api.experiences(limit=300),
            "skills": self.api.skills,
        })
        items = (res.get("exps") or {}).get("items", [])
        trunks = sorted({e.get("trunk") for e in items if e.get("trunk")})
        cats = sorted({e.get("category") for e in items if e.get("category")})
        name_map: dict[tuple, str] = {}
        for s in (res.get("skills") or {}).get("items", []):
            if s.get("name"):
                name_map[(s["trunk"], s["category"])] = s["name"]
        return trunks, cats, name_map

    def _show_data_export(self) -> None:
        """数据导出弹窗：5 粒度 + 时间范围 + 生成按钮。

        取数（trunks/cats/name_map）走后台线程——打开弹层不再冻主线程；
        取数期间弹层先显示占位，落地后替换为真实表单。"""
        dlg = QDialog(self)
        dlg.setWindowTitle(t("数据导出"))
        dlg.setMinimumWidth(SIZES.CONTENT_FORM)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(S.s3)
        holder = QWidget()
        holder_lay = QVBoxLayout(holder)
        holder_lay.setContentsMargins(0, 0, 0, 0)
        holder_lay.addWidget(txt(t("正在读取…"), F.caption, color=C.ink_500))
        lay.addWidget(holder)
        close = btn_secondary(t("关闭"))
        close.clicked.connect(dlg.reject)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(close)
        lay.addLayout(btn_row)

        def on_done(meta) -> None:
            trunks, cats, name_map = meta
            clear_layout(holder_lay)
            holder_lay.addWidget(
                self._build_export_section(trunks, cats, name_map))

        def on_error(err: str) -> None:
            clear_layout(holder_lay)
            holder_lay.addWidget(
                txt(t("（读取失败）"), F.caption, color=C.err_fg))

        self.run_async(self._export_meta, on_done, on_error)
        dlg.exec()
        dlg.deleteLater()

    def _show_hooks_export(self) -> None:
        """Hooks 导出弹窗。"""
        dlg = QDialog(self)
        dlg.setWindowTitle(t("规则导出"))
        dlg.setMinimumWidth(SIZES.CONTENT_FORM)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(S.s3)
        lay.addWidget(self._build_hooks_export_section())
        close = btn_secondary(t("关闭"))
        close.clicked.connect(dlg.reject)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(close)
        lay.addLayout(btn_row)
        dlg.exec()
        dlg.deleteLater()

    # ---------- 数据导出区（原 _export_section） ----------

    def _export_task(self, gran, trunk, cat, days, phase_key,
                     exp_checked: bool, exp_snap: set, pb_snap: set):
        """导出任务本体（**工作线程**执行，绝不碰 Qt 控件）。

        从 `_build_export_section` 里嵌套的 `work()` 抽出。
        这一段的性质是**纯取数**——把"用户在界面上选了什么"翻译成一次 API 调用，
        全程不读写任何控件，因此可以脱离 UI 单独测试；抽出来后 `_do_export`
        只剩快照与 UI 接线，读起来也清楚哪部分是"可能失败的业务"。

        返回 `(错误文案 | None, 结果 dict | None)`——两者互斥，与原先 `work()`
        的返回契约完全一致。
        """
        err: str | None = None
        r: dict | None = None
        try:
            if gran == "playbook" and not pb_snap:
                err = t("请至少勾选一个方法")
            elif gran == "experiences" and exp_checked and not exp_snap:
                err = t("请至少勾选一条经验")
            elif gran == "experiences":
                r = self.api.export(gran, trunk=trunk, category=cat,
                                    ids=sorted(exp_snap)
                                    if (exp_checked and exp_snap) else None)
            elif gran == "playbook":
                r = self.api.export(
                    gran, playbooks=[{"trunk": tk, "category": c}
                                     for tk, c in sorted(pb_snap)])
            elif gran == "growth":
                r = self.api.export(gran, days=days)
            elif gran == "preferences":
                r = self.api.export(gran, trunk=trunk)
            elif gran == "phase":
                r = self.api.export(gran, trunk=trunk, category=cat,
                                    since=_phase_since(phase_key))
            else:
                r = self.api.export(gran)
        except LocalApiError as exc:
            err = t("导出失败：{err}", err=exc.localized())
        return err, r

    def _build_export_section(self, trunks: list[str], cats: list[str],
                              name_map: dict[tuple, str] | None = None) -> QWidget:
        name_map = name_map or {}
        open_path: list[str] = [""]
        sel_exp: set[str] = set()
        sel_pb: set[tuple] = set()
        pb_filled: list[bool] = [False]

        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setSpacing(S.s3)
        lay.setContentsMargins(0, 0, 0, 0)

        gran_dd = QComboBox()
        gran_dd.addItem(t("经验记录"), "experiences")
        gran_dd.addItem(t("方法和坑"), "playbook")
        gran_dd.addItem(t("成长报告"), "growth")
        gran_dd.addItem(t("我的偏好"), "preferences")
        gran_dd.addItem(t("阶段经验"), "phase")
        gran_dd.setFixedWidth(D.DD_W_MD)
        r0 = QHBoxLayout()
        r0.addWidget(txt(t("粒度"), F.body, color=C.ink_700))
        r0.addWidget(gran_dd)
        r0.addStretch(1)
        lay.addLayout(r0)

        # R4：类别下拉优先显示名（说人话），key 仍是原始类别（API 不变）
        _cat_name: dict[str, str] = {}
        for c in cats:
            _cat_name[c] = next((name_map[(t_, c)] for t_ in trunks
                                 if (t_, c) in name_map), c)

        trunk_dd = QComboBox()
        trunk_dd.addItem(t("全部"), None)
        for x in trunks:
            trunk_dd.addItem(x, x)
        cat_dd = QComboBox()
        cat_dd.addItem(t("全部"), None)
        for c in cats:
            cat_dd.addItem(_cat_name.get(c, c), c)
        trunk_cat_row = QWidget()
        tcr = QHBoxLayout(trunk_cat_row)
        tcr.setContentsMargins(0, 0, 0, 0)
        tcr.addWidget(trunk_dd)
        tcr.addWidget(cat_dd)
        tcr.addStretch(1)
        lay.addWidget(trunk_cat_row)

        # 阶段经验时间窗（B4 恢复该粒度）
        phase_dd = QComboBox()
        phase_dd.addItem(t("本月"), "month")
        phase_dd.addItem(t("最近 30 天"), "30")
        phase_dd.addItem(t("最近 90 天"), "90")
        phase_row = QWidget()
        pr = QHBoxLayout(phase_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.addWidget(txt(t("时间范围（仅阶段经验）"), F.body, color=C.ink_700))
        pr.addWidget(phase_dd)
        pr.addStretch(1)
        phase_row.setVisible(False)
        lay.addWidget(phase_row)

        # 时间窗只对成长报告有意义
        days_dd = QComboBox()
        # 默认"本阶段"= 与成长页同一跨度（旧版只有 30/90，两处"本阶段"不是一回事）
        days_dd.addItem(t("本阶段（全部记录）"), 365)
        days_dd.addItem(t("最近 30 天"), 30)
        days_dd.addItem(t("最近 90 天"), 90)
        days_dd.setCurrentIndex(0)
        days_row = QWidget()
        dr = QHBoxLayout(days_row)
        dr.setContentsMargins(0, 0, 0, 0)
        dr.addWidget(txt(t("时间范围（仅成长报告）"), F.body, color=C.ink_700))
        dr.addWidget(days_dd)
        dr.addStretch(1)
        days_row.setVisible(False)
        lay.addWidget(days_row)

        # R5 经验精选（勾选模式）：单点启停走 switch()（方框留给下方逐条勾选）
        exp_sw_row = QHBoxLayout()
        exp_sw_row.setSpacing(S.s2)
        exp_sw = switch()
        exp_sw_row.addWidget(exp_sw)
        exp_sw_row.addWidget(txt(
            t("只导出勾选的经验（不勾 = 范围内全部）"), F.body, color=C.ink_700))
        exp_sw_row.addStretch(1)
        lay.addLayout(exp_sw_row)
        exp_search = QLineEdit()
        exp_search.setPlaceholderText(t("搜索经验（task/做法/踩坑）"))
        exp_search.setFixedWidth(D.DD_W_SM)
        exp_search.setVisible(False)
        lay.addWidget(exp_search)
        exp_list_box = QWidget()
        exp_list_lay = QVBoxLayout(exp_list_box)
        exp_list_lay.setContentsMargins(0, 0, 0, 0)
        exp_list_lay.setSpacing(S.s1)
        exp_list_box.setVisible(False)
        lay.addWidget(exp_list_box)
        # R5 方法精选（多选）
        pb_list_box = QWidget()
        pb_list_lay = QVBoxLayout(pb_list_box)
        pb_list_lay.setContentsMargins(0, 0, 0, 0)
        pb_list_lay.setSpacing(S.s1)
        pb_list_box.setVisible(False)
        lay.addWidget(pb_list_box)

        msg = status_text(tone="ok")
        lay.addWidget(msg)
        gen_btn = btn_primary(t("生成"))
        all_btn = btn_secondary(t("全量打包"))
        open_btn = btn_secondary(t("打开文件夹"))
        open_btn.setVisible(False)
        op_row = QHBoxLayout()
        op_row.setSpacing(S.s2)
        op_row.addWidget(gen_btn)
        op_row.addWidget(all_btn)
        op_row.addWidget(open_btn)
        op_row.addStretch(1)
        lay.addLayout(op_row)

        def _sync_rows() -> None:
            gran = gran_dd.currentData()
            trunk_cat_row.setVisible(gran in ("experiences", "phase"))
            days_row.setVisible(gran == "growth")
            phase_row.setVisible(gran == "phase")
            exp_sw.setVisible(gran == "experiences")
            show_exp = gran == "experiences" and exp_sw.isChecked()
            exp_search.setVisible(show_exp)
            exp_list_box.setVisible(show_exp)
            pb_list_box.setVisible(gran == "playbook")
            if show_exp:
                _fill_exp_list()
            elif gran == "playbook":
                _fill_pb_list()

        # 经验选择列表原每次按键/切筛选都同步拉 500 条
        # （打字即冻结 ~2s）。改为按 (trunk, category) 缓存一次全量，之后纯
        # 内存过滤；缓存未命中时才走后端取数（不碰 UI 线程）。
        _exp_cache: dict[tuple, list] = {}

        def _fill_exp_list() -> None:
            key = (trunk_dd.currentData() or "", cat_dd.currentData() or "")
            q = (exp_search.text() or "").strip().lower()

            def render(items: list) -> None:
                if q:
                    items = [e for e in items
                             if q in " ".join(str(e.get(k, "")) for k in
                                              ("task", "action", "state",
                                               "outcome")).lower()]
                clear_layout(exp_list_lay)
                rows = [e for e in items[:200] if e.get("id")]
                if not rows:
                    exp_list_lay.addWidget(txt(t("没有符合条件的经验"), F.caption,
                                               color=C.ink_500))
                    return
                for e in rows:
                    eid = e["id"]
                    row = QWidget()
                    rl = QHBoxLayout(row)
                    rl.setContentsMargins(0, 0, 0, 0)
                    rl.setSpacing(S.s1)
                    cb = QCheckBox()
                    cb.setChecked(eid in sel_exp)
                    cb.toggled.connect(lambda on, i=eid: _toggle_exp(i, on))
                    rl.addWidget(cb)
                    rl.addWidget(txt(e.get("task", ""), F.body), 1)
                    rl.addWidget(txt(
                        f"{e.get('category', '')} · {e.get('agent', '')}"
                        f" · {str(e.get('ts', ''))[:10]}",
                        F.caption, color=C.ink_500))
                    exp_list_lay.addWidget(row)

            if key in _exp_cache:
                render(_exp_cache[key])
                return

            def work():
                return self.api.experiences(
                    trunk=trunk_dd.currentData() or None,
                    category=cat_dd.currentData() or None,
                    limit=500).get("items", [])

            def done(items):
                _exp_cache[key] = items or []
                render(_exp_cache[key])

            def err(_e):
                _exp_cache[key] = []
                render([])

            self.run_async(work, done, err)

        def _toggle_exp(eid: str, on: bool) -> None:
            if on:
                sel_exp.add(eid)
            else:
                sel_exp.discard(eid)

        def _fill_pb_list() -> None:
            try:
                skills = self.api.skills().get("items", [])
            except LocalApiError:
                skills = []
            clear_layout(pb_list_lay)
            if not skills:
                pb_list_lay.addWidget(txt(t("还没有方法（先在方法页总结）"),
                                          F.caption, color=C.ink_500))
                return
            if not pb_filled[0]:
                sel_pb.update((s["trunk"], s["category"]) for s in skills)
                pb_filled[0] = True
            for s in skills:
                key = (s["trunk"], s["category"])
                nm = s.get("name")
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(S.s1)
                cb = QCheckBox()
                cb.setChecked(key in sel_pb)
                cb.toggled.connect(lambda on, k=key: _toggle_pb(k, on))
                rl.addWidget(cb)
                col = QVBoxLayout()
                col.setSpacing(S.s1)
                col.addWidget(txt(nm or f"{s['trunk']} / {s['category']}",
                                  F.body, 600))
                if nm:
                    col.addWidget(txt(f"{s['trunk']} / {s['category']}",
                                      F.caption, color=C.ink_500))
                rl.addLayout(col, 1)
                pb_list_lay.addWidget(row)

        def _toggle_pb(key: tuple, on: bool) -> None:
            if on:
                sel_pb.add(key)
            else:
                sel_pb.discard(key)

        def _open_path() -> None:
            try:
                self.api.open_export(open_path[0])
            except LocalApiError as exc:
                msg.setText(exc.localized())
                msg.setStyleSheet(f"color: {C.err_fg};")

        open_btn.clicked.connect(_open_path)

        def _do_export() -> None:
            # 快照（工作线程不碰 Qt 控件）
            gran = gran_dd.currentData()
            trunk = trunk_dd.currentData()
            cat = cat_dd.currentData()
            days = days_dd.currentData()
            phase_key = phase_dd.currentData()
            exp_checked = exp_sw.isChecked()
            exp_snap = set(sel_exp)
            pb_snap = set(sel_pb)
            gen_btn.setEnabled(False)
            gen_btn.setText(t("生成中…"))

            def work():
                return self._export_task(gran, trunk, cat, days, phase_key,
                                         exp_checked, exp_snap, pb_snap)

            def on_done(res) -> None:
                err, r = res
                if err:
                    msg.setText(err)
                    msg.setStyleSheet(f"color: {C.err_fg};")
                elif r:
                    open_path[0] = r["path"]
                    msg.setText(t("已保存到 {path}", path=r["path"]))
                    status_tone(msg, C.ok_fg)
                    open_btn.setVisible(True)
                gen_btn.setText(t("生成"))
                gen_btn.setEnabled(True)

            def on_error(exc: str) -> None:
                msg.setText(t("导出失败：{err}", err=exc))
                msg.setStyleSheet(f"color: {C.err_fg};")
                gen_btn.setText(t("生成"))
                gen_btn.setEnabled(True)

            self.run_async(work, on_done, on_error)

        def _do_all() -> None:
            all_btn.setEnabled(False)
            all_btn.setText(t("打包中…"))

            def work():
                return self.api.export_all()

            def on_done(r: dict) -> None:
                open_path[0] = r["dest"]
                msg.setText(t("全量包已导出到 {dest}（{n} 个文件）",
                              dest=r["dest"], n=len(r["files"])))
                status_tone(msg, C.ok_fg)
                open_btn.setVisible(True)
                all_btn.setText(t("全量打包"))
                all_btn.setEnabled(True)

            def on_error(exc: str) -> None:
                msg.setText(t("导出失败：{err}", err=exc))
                msg.setStyleSheet(f"color: {C.err_fg};")
                all_btn.setText(t("全量打包"))
                all_btn.setEnabled(True)

            self.run_async(work, on_done, on_error)

        gen_btn.clicked.connect(_do_export)
        all_btn.clicked.connect(_do_all)
        gran_dd.currentIndexChanged.connect(lambda _: _sync_rows())
        exp_sw.toggled.connect(lambda _: _sync_rows())
        exp_search.textChanged.connect(lambda _: _fill_exp_list())

        _sync_rows()
        return box

    # ---------- Hooks 导出区（原 _hooks_export_section） ----------

    def _export_hooks_task(self, sel_snap: list[str]):
        """Hooks 导出任务本体（**工作线程**执行，绝不碰 Qt 控件）。

        从 `_build_hooks_export_section` 里嵌套的 `work()` 抽出。
        性质与 `_export_task` 相同——纯取数，可脱离 UI 单独测试，也是这段里唯一
        可能失败的业务逻辑。返回 `(错误文案 | None, 结果 | None)`，契约不变。
        """
        err: str | None = None
        r: dict | None = None
        try:
            if not sel_snap:
                err = t("请至少勾选一个 Hook")
            else:
                r = self.api.export("hooks", ids=sel_snap)
        except LocalApiError as exc:
            err = t("导出失败：{err}", err=exc.localized())
        return err, r

    def _fetch_hook_catalog(self):
        """取 Hooks 清单 + 类目映射（**工作线程**执行，不碰 Qt 控件）。

        从 `_fill()` 抽出两段取数。类目映射走本地 API（GUI 不
        import 引擎）；**失败降级就在这里就地完成**——取不到就把全部条目归到
        "自定义"组，调用方拿到的永远是可直接用的一组数据，不用再判空。

        返回 `(规则清单, 类目顺序, 类目显示名, 模板 id → 类目)`。
        """
        try:
            rules = [r for r in self.api.rules().get("items", []) if r.get("id")]
        except LocalApiError:
            rules = []
        cat_order: list[str] = []
        cat_label: dict[str, str] = {}
        tid_cat: dict[str, str] = {}
        try:
            for c in self.api.templates(i18n.current_language()).get("categories", []):
                cid = c.get("id")
                if not cid:
                    continue
                cat_order.append(cid)
                cat_label[cid] = t(c.get("label_key", cid))
                for tpl in c.get("templates", []):
                    tid_cat[tpl.get("id", "")] = cid
        except LocalApiError:
            pass
        cat_order.append("custom")
        cat_label["custom"] = t("自定义")
        return rules, cat_order, cat_label, tid_cat

    def _build_hooks_export_section(self) -> QWidget:
        from .hooks_page import _PRI_STYLE  # 优先级视觉与 Hooks 页一致（P0 红…P4 灰）

        open_path: list[str] = [""]
        sel: set[str] = set()
        all_rules: list[dict] = []
        cat_order: list[str] = []
        cat_label: dict[str, str] = {}
        tid_cat: dict[str, str] = {}

        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setSpacing(S.s3)
        lay.setContentsMargins(0, 0, 0, 0)

        sel_all_cb = QCheckBox(t("全选"))
        sel_all_cb.setChecked(True)
        clear_btn = btn_flat(t("清空"))
        top = QHBoxLayout()
        top.setSpacing(S.s2)
        top.addWidget(sel_all_cb)
        top.addWidget(clear_btn)
        top.addStretch(1)
        lay.addLayout(top)

        list_box = QWidget()
        list_lay = QVBoxLayout(list_box)
        list_lay.setContentsMargins(0, 0, 0, 0)
        list_lay.setSpacing(S.s1)
        lay.addWidget(list_box)

        msg = status_text(tone="ok")
        lay.addWidget(msg)
        gen_btn = btn_primary(t("导出 Hooks"))
        open_btn = btn_secondary(t("打开文件夹"))
        open_btn.setVisible(False)
        op_row = QHBoxLayout()
        op_row.setSpacing(S.s2)
        op_row.addWidget(gen_btn)
        op_row.addWidget(open_btn)
        op_row.addStretch(1)
        lay.addLayout(op_row)

        def _cat_of(r: dict) -> str:
            return tid_cat.get(r.get("template_id") or "", "custom")

        def _groups() -> list[tuple[str, list[dict]]]:
            out: list[tuple[str, list[dict]]] = []
            for cid in cat_order:
                items = [r for r in all_rules if _cat_of(r) == cid]
                if items:
                    out.append((cid, items))
            return out

        def _rebuild() -> None:
            clear_layout(list_lay)
            groups = _groups()
            if not groups:
                list_lay.addWidget(txt(t("还没有 Hook（先到 Hooks 页添加）"),
                                       F.caption, color=C.ink_500))
            for cid, items in groups:
                ids = {r["id"] for r in items}
                gh = QHBoxLayout()
                gh.setSpacing(S.s1)
                gh.addWidget(txt(cat_label.get(cid, t("自定义")),
                                 F.caption, 600, C.ink_700))
                gh.addStretch(1)
                cb = QCheckBox()
                cb.setChecked(bool(ids) and sel >= ids)
                cb.toggled.connect(lambda on, gids=ids: _toggle_group(gids, on))
                gh.addWidget(cb)
                hbox = QWidget()
                hbox.setLayout(gh)
                list_lay.addWidget(hbox)
                for r in items:
                    list_lay.addWidget(_rule_row(r))
            all_ids = {r["id"] for r in all_rules if r.get("id")}
            sel_all_cb.blockSignals(True)
            sel_all_cb.setChecked(bool(all_ids) and sel >= all_ids)
            sel_all_cb.blockSignals(False)

        def _rule_row(r: dict) -> QWidget:
            rid = r["id"]
            enabled = bool(r.get("enabled", True))
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(S.s4, 0, 0, 0)
            rl.setSpacing(S.s1)
            cb = QCheckBox()
            cb.setChecked(rid in sel)
            cb.toggled.connect(lambda on, i=rid: _toggle(i, on))
            rl.addWidget(cb)
            rl.addWidget(txt(r.get("name", ""), F.body, 600,
                             C.ink_500 if not enabled else C.ink_900), 1)
            pri = r.get("template_priority")
            pri_label, pri_tone = _PRI_STYLE.get(pri, ("", "ink")) if pri else ("", "ink")
            if pri_label:
                rl.addWidget(_tone_chip(t(pri_label), pri_tone))
            if not enabled:
                rl.addWidget(txt(t("未启用"), F.caption, color=C.ink_500))
            return row

        def _toggle(rid: str, on: bool) -> None:
            if on:
                sel.add(rid)
            else:
                sel.discard(rid)
            _rebuild()

        def _toggle_group(gids: set, on: bool) -> None:
            if on:
                sel.update(gids)
            else:
                sel.difference_update(gids)
            _rebuild()

        def _set_all(flag: bool) -> None:
            sel.clear()
            if flag:
                sel.update(r["id"] for r in all_rules if r.get("id"))
            _rebuild()

        sel_all_cb.toggled.connect(lambda on: _set_all(on))
        clear_btn.clicked.connect(lambda: _set_all(False))

        def _fill() -> None:
            rules, order, label, tid = self._fetch_hook_catalog()
            all_rules[:] = rules
            cat_order[:] = order
            cat_label.clear()
            cat_label.update(label)
            tid_cat.clear()
            tid_cat.update(tid)
            _set_all(True)

        _fill()

        def _do_export() -> None:
            sel_snap = sorted(sel)
            gen_btn.setEnabled(False)
            gen_btn.setText(t("生成中…"))

            def work():
                return self._export_hooks_task(sel_snap)

            def on_done(res) -> None:
                err, r = res
                if err:
                    msg.setText(err)
                    msg.setStyleSheet(f"color: {C.err_fg};")
                elif r:
                    open_path[0] = r["path"]
                    msg.setText(t("已保存到 {path}", path=r["path"]))
                    status_tone(msg, C.ok_fg)
                    open_btn.setVisible(True)
                gen_btn.setText(t("导出 Hooks"))
                gen_btn.setEnabled(True)

            def on_error(exc: str) -> None:
                msg.setText(t("导出失败：{err}", err=exc))
                msg.setStyleSheet(f"color: {C.err_fg};")
                gen_btn.setText(t("导出 Hooks"))
                gen_btn.setEnabled(True)

            self.run_async(work, on_done, on_error)

        gen_btn.clicked.connect(_do_export)

        def _open_path() -> None:
            try:
                self.api.open_export(open_path[0])
            except LocalApiError as exc:
                msg.setText(exc.localized())
                msg.setStyleSheet(f"color: {C.err_fg};")

        open_btn.clicked.connect(_open_path)
        return box
