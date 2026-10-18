"""整理 Skill 区（Qt 版，对应 Flet 源文件 app/gui/skill_organize.py；+ M1）：
路径 A（每类一键转）+ 路径 B（勾选精选，可跨类）。嵌在导出页「导出 Skill」卡内
（页级标题与 do/dont 提示由卡提供，本区不带头）。

两条路径产出同一标准 SKILL.md（agentskills.io 开放标准）。
默认快路径是 A；想"自己组"时才进 B 的勾选模式。

⚠️ 本区**没有 retranslateUi**：语言切换走
`MainWindow._rebuild_visited_pages` 整页重建（生产路径），区块随页面一起
重建，故不实现原地翻译。若将来改回"原地翻译"，必须给本区补 retranslateUi，
否则切语言后这里会滞留中文。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLineEdit,
                               QVBoxLayout, QWidget)

from .api_client import LocalApi, LocalApiError
from . import _name_map as name_map
from ._name_map import invalidate as invalidate_name_map
from .i18n import t
from .page_base import PageBase, clear_layout, parallel_fetch
from .qt_dialogs import confirm_skill_export, skill_preview_dialog
from .qt_theme import (btn_flat, btn_primary, btn_secondary, chip, divider,
                       empty_state, txt, txt_clamped)
from .qt_widgets import RotatingIcon, SelectButton
from .theme import C, D, F, R, S

# _clear_layout → page_base.clear_layout（统一入口）


class SkillOrganizePage(PageBase):
    """Skill 整理区：按类一键生成 / 勾选精选（可跨类）+ SKILL.md 预览 / 版本历史。

    内嵌于导出页（ExportPage）。数据在 refresh() 加载（失败兜底空数据）。
    """

    def __init__(self, api: LocalApi, parent: QWidget | None = None):
        super().__init__(api, parent)
        self.selected: set[str] = set()
        self._name_map: dict[tuple, str] = {}
        self._exps: list[dict] = []  # 内存经验列表（refresh 后台取一次，搜索零 HTTP）
        self._page_size = 100  # 列表渲染上限；「加载更多」步进扩充
        # 折叠分组：技能（类别）增长后页面不肿——默认只展开条数前 3 组，
        # 其余折叠为一行组头（折叠组不创建条目控件）。用户手动展开/收起的
        # 组记住状态（_touched），未碰过的组每次重建时按条数重新取前 3。
        self._collapsed: set[tuple] = set()
        self._touched: set[tuple] = set()
        self._default_expand_n = 3
        self._default_expanded_keys: set[tuple] = set()
        self._build()

    # ---------- UI ----------

    def _build(self) -> None:
        lay = self._layout
        lay.setSpacing(S.s3)

        # 筛选工具行：分类 + 搜索（浏览层）
        self.search_tf = QLineEdit()
        self.search_tf.setPlaceholderText(t("搜索经验（task/state/action）"))
        self.search_tf.setFixedWidth(D.DD_W_LG)
        # 分类筛选下拉（与数据导出口径一致）：全部 / 各 (trunk, category)
        self.cat_sel = SelectButton()
        self.cat_sel.setFixedWidth(D.DD_W_LG)
        self.cat_sel.currentIndexChanged.connect(lambda _: self._rebuild_list())
        sr = QHBoxLayout()
        sr.addWidget(self.cat_sel)
        sr.addWidget(self.search_tf)
        sr.addStretch(1)
        lay.addLayout(sr)

        # 经验列表（勾选层）
        self._list_box = QWidget()
        self._list_lay = QVBoxLayout(self._list_box)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(S.s1)
        lay.addWidget(self._list_box, 1)

        # 生成设置：名字 / 描述（配置层，贴近导出动作，不占浏览位）
        self.name_tf = QLineEdit()
        self.name_tf.setPlaceholderText(t("Skill 名（留空 = AI 起说人话的短名）"))
        self.desc_tf = QLineEdit()
        self.desc_tf.setPlaceholderText(t("一句话描述（进 frontmatter）"))
        fr = QHBoxLayout()
        fr.setSpacing(S.s3)
        fr.addWidget(self.name_tf, 1)
        fr.addWidget(self.desc_tf, 1)
        lay.addLayout(fr)

        # 动作行：计数 + 清空 + 导出（动作层，分隔线把配置和动作从列表里隔出来）
        lay.addWidget(divider())
        self._count_line = txt("", F.caption, color=C.ink_500)
        self._clear_btn = btn_flat(t("清空"))
        self._clear_btn.clicked.connect(self._clear_selected)
        self._clear_btn.hide()
        self._gen_btn = btn_primary(t("导出 Skill"), "BUILD_OUTLINED")
        self._gen_btn.clicked.connect(lambda: self._generate(None, None, True))
        bottom = QHBoxLayout()
        bottom.addWidget(self._count_line)
        bottom.addWidget(self._clear_btn)
        bottom.addStretch(1)
        bottom.addWidget(self._gen_btn)
        lay.addLayout(bottom)

        self.search_tf.textChanged.connect(lambda _: self._rebuild_list())

    # ---------- 数据 ----------

    def refresh(self) -> None:
        """切页刷新：取数整体在后台线程（主线程零 HTTP），渲染回主线程。"""
        # S5：补首屏骨架（此前本页取数期间无占位）
        self.fetch_and_render(
            lambda: parallel_fetch({
                "skills": self.api.skills,
                "exps": lambda: self.api.experiences(limit=500),
            }),
            self._render, "skill_org", skeleton=[24, 64, 64, 64])

    def _render(self, data: dict | None) -> None:
        """渲染回调（主线程）：**不得再发 HTTP**，只按取数结果更新内存数据与 UI。"""
        data = data or {}
        self._apply_name_map(data.get("skills"))
        self._exps = (data.get("exps") or {}).get("items") or []
        self._fill_cat_sel()
        self._rebuild_list()

    def _fill_cat_sel(self) -> None:
        """填充分类筛选下拉：全部 / 各 (trunk, category)，沿用现有方法显示名/
        trunk/category 展示逻辑；builtin 归并后首个为当前项（不触发信号）。"""
        self.cat_sel.clear()
        self.cat_sel.addItem(t("全部"), None)
        cats = sorted({self._cat_key(e) for e in self._exps_filtered()})
        for trunk, category in cats:
            nm = self._name_map.get((trunk, category))
            label = nm or self._disp_cat(trunk, category)
            self.cat_sel.addItem(label, (trunk, category))
        self.cat_sel.setCurrentIndex(0)

    def _apply_name_map(self, skills: dict | None) -> None:
        """消费取数结果里的 skills（主线程、零 HTTP）填 (trunk, category)→显示名。

        去重 R2：本页与 inject_preview 原先各存一份 name_map 缓存，现在共用
        app/gui/_name_map.py 这一份（失效一处、两边同时生效）。
        取数失败（skills 为 None）时不动缓存，仅复用既有条目，不崩。
        """
        if skills is not None:
            name_map.replace(skills)
        self._name_map = name_map.get()

    def _exps_filtered(self, q: str = "") -> list[dict]:
        """纯内存过滤 self._exps（主线程零 HTTP，打字不再发请求）。"""
        items = self._exps
        if q:
            items = [e for e in items
                     if q in " ".join(str(e.get(k, "")) for k in
                                      ("task", "action", "state", "outcome")).lower()]
        return items

    def _scoped_items(self) -> list[dict]:
        """当前搜索 + 分类筛选范围内的经验（计数、导出、确认弹窗共用同一口径）。"""
        q = (self.search_tf.text() or "").strip().lower()
        items = self._exps_filtered(q)
        picked = self.cat_sel.currentData()  # None=全部；否则 (trunk, category)
        if picked is not None:
            items = [e for e in items if self._cat_key(e) == picked]
        return items

    @staticmethod
    def _cat_key(e: dict) -> tuple:
        return (e.get("trunk") or "其他", e.get("category") or "未分类")

    @staticmethod
    def _disp_cat(trunk: str, category: str) -> str:
        # 「其他/未分类」是系统默认桶名（数据值），展示时翻译；用户填的值原样透传
        return (f"{t('其他') if trunk == '其他' else trunk} / "
                f"{t('未分类') if category == '未分类' else category}")

    @staticmethod
    def _g_chip(g) -> QWidget:
        """G 是内部置信度（数值不暴露给用户）——只给三档标签。"""
        g = float(g or 0)
        if g >= 0.7:
            return chip(t("已验证"), "ok")
        if g >= 0.5:
            return chip(t("部分验证"), "warn")
        return chip(t("待验证"), "brand")

    # ---------- 列表重建 ----------

    def _rebuild_list(self) -> None:
        clear_layout(self._list_lay)
        exps = self._scoped_items()
        total = len(exps)
        visible = exps[: self._page_size]
        groups: dict[tuple, list[dict]] = {}
        for e in visible:
            groups.setdefault(self._cat_key(e), []).append(e)

        if not groups:
            self._list_lay.addWidget(empty_state(
                t("经验库还是空的"), t("先用 agent 干点活"), mascot="think"))
        # 默认展开条数前 3 组；用户手动碰过的组保持其折叠状态
        default_expanded = {k for k, _ in sorted(
            groups.items(), key=lambda kv: -len(kv[1]))[:self._default_expand_n]}
        self._default_expanded_keys = default_expanded
        for i, ((trunk, category), items) in enumerate(sorted(groups.items())):
            key = (trunk, category)
            collapsed = (key in self._collapsed if key in self._touched
                         else key not in default_expanded)
            ids = [e.get("id") for e in items if e.get("id")]
            checked = bool(ids) and all(i in self.selected for i in ids)
            nm = self._name_map.get(key)
            hbox = self._group_header(key, items, checked, collapsed, nm)
            if i:
                gap = QWidget()
                gap.setFixedHeight(S.s2)
                self._list_lay.addWidget(gap)
            self._list_lay.addWidget(hbox)
            if collapsed:
                continue  # 折叠组不创建条目控件，页面高度与 widget 数随类别数受控
            if nm:
                self._list_lay.addWidget(
                    txt(self._disp_cat(trunk, category), F.caption, color=C.ink_500))
            for e in items:
                self._list_lay.addWidget(self._exp_row(e))
        if total > self._page_size:
            self._list_lay.addWidget(self._load_more_row(total - self._page_size))
        self._update_count()

    def _group_header(self, key: tuple, items: list[dict], checked: bool,
                      collapsed: bool, nm: str | None) -> QWidget:
        """可折叠组头：chevron + 全选 + 名称 + 条数 + 「导出 Skill」一键。

        整行可点（chevron 朝上=展开可收起，朝下=折叠可展开）；折叠组也保留
        导出入口（A 路径是默认快路径，不因折叠丢失）。"""
        trunk, category = key
        all_cb = QCheckBox()
        all_cb.setChecked(checked)
        all_cb.toggled.connect(lambda on, its=items: self._select_all(its, on))

        header = QWidget()
        header.setObjectName("skillGroupHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header.setAttribute(Qt.WA_Hover, True)
        header.setCursor(Qt.PointingHandCursor)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(0, 0, 0, 0)
        h_lay.setSpacing(S.s1)
        icon = RotatingIcon("EXPAND_MORE_OUTLINED", 18, C.ink_500)
        if not collapsed:
            icon.setRotation(180)
        h_lay.addWidget(icon)
        h_lay.addWidget(all_cb)
        h_lay.addWidget(txt(nm or self._disp_cat(trunk, category), F.body, 600))
        h_lay.addWidget(txt(t("（{n} 条）", n=len(items)), F.caption, color=C.ink_500))
        h_lay.addStretch(1)
        h_lay.addWidget(self._gen_btn_for(trunk, category, False))
        # #id 限定防级联：hover 暖底只落在组头本身
        header.setStyleSheet(
            f"QWidget#skillGroupHeader {{ border-radius: {R.sm}px;"
            f" background: transparent; }}"
            f"QWidget#skillGroupHeader:hover {{ background: {C.surface_2}; }}")
        header.mousePressEvent = lambda e, k=key: self._toggle_group(k)
        return header

    def _toggle_group(self, key: tuple) -> None:
        """展开/收起一组：记入用户状态并整表重建（重建后 chevron 直落目标角）。

        首次点击翻转该组的默认态（默认折叠→展开、默认展开→折叠），
        之后按用户上次选择翻转。"""
        if key in self._touched:
            if key in self._collapsed:
                self._collapsed.discard(key)
            else:
                self._collapsed.add(key)
        else:
            self._touched.add(key)
            if key in self._default_expanded_keys:
                self._collapsed.add(key)
            else:
                self._collapsed.discard(key)
        self._rebuild_list()

    def _load_more_row(self, remain: int) -> QWidget:
        """分页尾行：还剩 N 条 → 加载更多（步进扩充渲染上限）。"""
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(S.s4, S.s2, 0, S.s1)
        lay.setSpacing(S.s1)
        btn = btn_flat(t("加载更多（还有 {n} 条）", n=remain))
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self._load_more())
        lay.addWidget(btn)
        lay.addStretch(1)
        return row

    def _load_more(self) -> None:
        self._page_size += 100
        self._rebuild_list()

    def _exp_row(self, e: dict) -> QWidget:
        row = QWidget()
        row.setObjectName("skillExpRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        # #id 限定防级联：悬停底只落在条目行，不污染内部 chip/文本
        row.setStyleSheet(
            f"QWidget#skillExpRow {{ border-radius: {R.md}px; }}"
            f"QWidget#skillExpRow:hover {{ background: {C.surface_2}; }}")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(S.s4, S.s1, S.s2, S.s1)
        lay.setSpacing(S.s2)
        eid = e.get("id")
        cb = QCheckBox()
        cb.setChecked(bool(eid) and eid in self.selected)
        cb.toggled.connect(lambda on: self._check(e, on))
        lay.addWidget(cb, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(S.s1)
        line1 = QHBoxLayout()
        line1.setSpacing(S.s1)
        line1.addWidget(txt_clamped(e.get("task", ""), size=F.body, weight=500,
                                    color=C.ink_900, max_lines=1), 1)
        line1.addWidget(self._g_chip(e.get("G")))
        line1.addWidget(txt(f"{e.get('agent', '')} · {str(e.get('ts', ''))[:10]}",
                            F.caption, color=C.ink_500))
        col.addLayout(line1)
        line2 = " · ".join(x for x in (
            f"{t('踩坑：')}{e.get('state', '')}" if e.get("state") else "",
            f"{t('做法：')}{e.get('action', '')}" if e.get("action") else "",
        ) if x)
        if line2:
            col.addWidget(txt_clamped(line2, size=F.caption, weight=400,
                                      color=C.ink_500, max_lines=1))
        lay.addLayout(col, 1)
        return row

    def _check(self, exp: dict, on: bool) -> None:
        eid = exp.get("id", "")
        if on and eid:
            self.selected.add(eid)
        elif eid:
            self.selected.discard(eid)
        self._update_count()

    def _select_all(self, exps: list[dict], on: bool) -> None:
        for e in exps:
            eid = e.get("id", "")
            if not eid:
                continue
            if on:
                self.selected.add(eid)
            else:
                self.selected.discard(eid)
        self._rebuild_list()

    def _scope_active(self) -> bool:
        """是否处于筛选态（搜索词或分类筛选任一生效）——决定计数口径与范围外提示。"""
        return bool((self.search_tf.text() or "").strip()) or \
            self.cat_sel.currentData() is not None

    def _update_count(self) -> None:
        scoped = self._scoped_items()
        n_scoped = sum(1 for e in scoped if e.get("id") in self.selected)
        n_total = len(self.selected)
        cats = len({self._cat_key(e) for e in scoped if e.get("id") in self.selected})
        if self._scope_active() and n_scoped != n_total:
            self._count_line.setText(
                t("已选 {n} 条，范围内 {m} 条（跨 {c} 个类别）",
                  n=n_total, m=n_scoped, c=cats))
        else:
            self._count_line.setText(
                t("已选 {n} 条（跨 {c} 个类别）", n=n_total, c=cats))
        self._clear_btn.setVisible(n_total > 0)

    def _clear_selected(self) -> None:
        self.selected.clear()
        self._rebuild_list()

    # ---------- 生成 ----------

    def _gen_btn_for(self, trunk: str | None, category: str | None,
                     use_selected: bool) -> QWidget:
        # 每类一键（路径 A）：行内小号次按钮，视觉让位给底部唯一主 CTA
        btn = btn_secondary(t("导出 Skill"))
        btn.setFixedHeight(D.BTN_H_XS)
        # 空类别不给入口：按钮置灰 + tooltip 说明（不误导"点了就有产出"）
        items = self._scoped_items()
        if trunk and category:
            has = any(self._cat_key(e) == (trunk, category) for e in items)
            if not has:
                btn.setEnabled(False)
                btn.setToolTip(t("这个类别还没有可自动带上的内容"))
        btn.clicked.connect(lambda: self._generate(trunk, category, use_selected))
        return btn

    def _generate(self, trunk: str | None, category: str | None,
                  use_selected: bool) -> None:
        # 生成类动作统一走模型门禁（起旧门禁方法已删除，只走 require_model）
        if not self.require_model(t("导出 Skill")):
            return
        name_val = (self.name_tf.text() or "").strip() or None
        desc_val = (self.desc_tf.text() or "").strip() or None
        # R1 命名：留空时优先预填方法显示名（用户可见可改）
        if not name_val and trunk and category:
            preset = self._name_map.get((trunk, category))
            if preset:
                self.name_tf.setText(preset)
                name_val = preset
        scoped = self._scoped_items()
        if use_selected:
            sel = [e for e in scoped if e.get("id") in self.selected] or None
            if not sel:
                self.set_status(t("还没选经验——先在列表里勾几条，或切到「全部」"), "err")
                return
            items = sel
            out_of_scope = len(self.selected) - len(sel)
        else:
            sel = None
            # A 路径：弹窗展示该类别实际将打包的条目——后端按类别打包，
            # 不受当前搜索/筛选影响；否则数字与产物脱钩（误导）
            items = ([e for e in self._exps_filtered()
                      if self._cat_key(e) == (trunk, category)]
                     if trunk and category else scoped)
            out_of_scope = 0
        if not confirm_skill_export(
                self,
                scope=(self._disp_cat(trunk, category) if trunk and category else None),
                items=items,
                name=name_val, description=desc_val,
                out_of_scope=out_of_scope):
            return
        self._set_working(True)

        def work():
            try:
                return self.api.skill_generate(trunk=trunk, category=category,
                                               selected=sel, name=name_val,
                                               description=desc_val)
            except LocalApiError as exc:
                raise RuntimeError(exc.localized()) from None
            except Exception as exc:  # 超时/连接中断等 httpx 异常也要给用户看
                raise RuntimeError(
                    f"{t('导出失败：{err}', err=type(exc).__name__)}") from None

        def on_done(r: dict) -> None:
            self._set_working(False)
            self._preview_md(r["md"], r["name"], r["source_count"],
                             r.get("description", ""))

        def on_error(msg: str) -> None:
            self._set_working(False)
            self.set_status(msg, "err")

        self.run_async(work, on_done, on_error)

    def _set_working(self, working: bool) -> None:
        self._gen_btn.setEnabled(not working)
        text = t("正在导出 Skill…") if working else t("导出 Skill")
        # _gen_btn has icon：可见文字由子 QLabel 渲染（按钮自身 text 已被
        # _apply_btn_icon 清空），直接对按钮 setText 不生效；且更长的
        # 「正在导出…」需同步加宽最小宽，否则子标签被裁
        lay = self._gen_btn.layout()
        if lay is not None:
            lab = lay.itemAt(1).widget()
            lab.setText(text)
            fm = lab.fontMetrics()
            self._gen_btn.setMinimumWidth(
                S.s2 + 18 + S.s1 + fm.horizontalAdvance(text) + S.s3)
        else:
            self._gen_btn.setText(text)

    def _preview_md(self, md: str, name: str = "", source_count: int = 0,
                    description: str = "") -> None:
        dlg = skill_preview_dialog(self.api, md, name, source_count, description,
                                   parent=self)
        dlg.exec()
