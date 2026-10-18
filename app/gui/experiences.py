"""经验库页——Qt 版（原 Flet 源文件 experiences.py）。

列表 + 搜索/筛选 + 「有效/纠正」反馈（G 信号 L1）：有效 = 标记（G=1.0），
纠正 = 打开编辑框直接改内容（改对了才叫纠正），保存后旧值留快照、回炉重蒸馏。
不暴露 G 值与 schema 字段——卡片只展示上下文与结论。
空状态 = think 宇航员（deck  表情家族：空状态默认脸）。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QVBoxLayout, QWidget)

from .api_client import LocalApi, LocalApiError
from .ai_rewrite import ExperienceRewriteDialog
from .experience_edit import ExperienceEditDialog
from .qt_dialogs import input_dialog, rich_info_dialog
from .i18n import current_language, t
from .page_base import (PageBase, build_centered_scroll, clear_layout,
                        content_sig, parallel_fetch, page_scaffold,
                        PAGE_SIDE_PAD, sync_tracked)
from .qt_theme import (btn_flat, btn_ghost, btn_pill, btn_primary, card, chip,
                       divider, ellipsis_button, empty_state,
                       expandable_clamped, field_row, txt)
from .qt_widgets import (DetailDrawer, SelectButton, ShadowCard, hover_lift,
                         page_header)
from .theme import C, D, F, R, S


def _group_by_task(items: list[dict]) -> list[list[dict]]:
    """按 (类别, task) 聚合经验记录：同一 task 的多条经验（不同做法）收成一组，
    组内保持原顺序；返回的组顺序 = 各 task 首次出现的顺序（dict 保序）。

    经验库页一卡一 task：同 task 的多条记录若各出一卡，会渲染出
    重复标题、且第二做法被埋在第一张卡后面——聚合后同 task 只出一张卡，
    卡内逐行列出各做法。"""
    groups: dict[tuple[str, str], list[dict]] = {}
    for e in items:
        key = (str(e.get("category", "") or ""), str(e.get("task", "") or ""))
        groups.setdefault(key, []).append(e)
    return list(groups.values())


class ExperiencesPage(PageBase):
    """经验库子页。"""

    def __init__(self, api: LocalApi, parent=None, embedded: bool = False):
        super().__init__(api, parent)
        self._embedded = embedded
        self._build()

    # ---------- UI 构建 ----------

    def _build(self) -> None:
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(S.s6)

        # 标题行：经验库 + 任务类型下拉 + 搜索 + 导出
        # 整页滚动区内的选择器用 SelectButton（QMenu 顶层弹层，-fix-2）
        self._trunk_combo = SelectButton(width=D.DD_W_SM)
        self._trunk_combo.activated.connect(lambda _i: self.refresh())
        # agent 筛选（经验列表可按来源 agent 过滤，数据层 iter_experiences
        # 已支持 agent 参数；raw agent 名与卡片 meta 口径一致）
        self._agent_combo = SelectButton(width=D.DD_W_SM)
        self._agent_combo.activated.connect(lambda _i: self.refresh())
        self._search_tf = QLineEdit()
        self._search_tf.setPlaceholderText(t("搜索"))
        self._search_tf.setFixedWidth(D.FIELD_W)
        self._search_tf.returnPressed.connect(self.refresh)

        # P2：导出不在此弹窗——统一收进「导出」页的内嵌区
        self._export_btn = btn_primary(t("导出"), "DOWNLOAD_OUTLINED",
                                       on_click=lambda: self.go("share"))
        # 统一页头（S1）：嵌入「我的经验」容器时走 dense 档（h2）
        head = page_header(
            t("经验库"), dense=self._embedded,
            actions=[self._trunk_combo, self._agent_combo,
                     self._search_tf, self._export_btn])
        self._title_label = head.findChild(QLabel, "pageTitle")
        lay.addWidget(head)

        # 模型提示条：有待总结卡片且未接模型时出现——引导接本地模型/API，
        # 原始记录会被总结成一句结论、卡片更清爽（无模型时确定性压缩兜底，
        # 接模型后总结更精炼；经验库体验）。默认隐藏，refresh() 按状态显隐。
        self._llm_hint = card(secondary=True, visible=False)
        _hint_hbox = QHBoxLayout()
        _hint_hbox.setSpacing(S.s3)
        self._llm_hint_text = txt(
            t("接入模型（本地模型或 API）后，原始记录会自动总结成一句结论，"
              "卡片更清爽"), F.body, color=C.ink_700)
        self._llm_hint_text.setWordWrap(True)
        _hint_hbox.addWidget(self._llm_hint_text, 1)
        self._llm_hint_btn = btn_pill(t("去接入"), "HUB_OUTLINED",
                                      on_click=lambda: self.go("connect"))
        _hint_hbox.addWidget(self._llm_hint_btn, 0, Qt.AlignCenter)
        self._llm_hint.layout().addLayout(_hint_hbox)
        lay.addWidget(self._llm_hint)

        # S5 待放行草稿（三入口之二：经验页 = 主处理处）
        self._draft_section = card(title=t("待放行的经验上报"), secondary=True,
                                   visible=False)
        self._draft_title = self._draft_section.layout().itemAt(0).widget()
        _dcl = self._draft_section.layout()
        self._draft_hint = txt(t("工具收尾自动上报的经验：确认后入库，忽略即放弃"),
                               F.caption, color=C.ink_500)
        self._draft_hint.setWordWrap(True)
        _dcl.addWidget(self._draft_hint)
        self._draft_rows = QVBoxLayout()
        self._draft_rows.setSpacing(S.s2)
        _dcl.addLayout(self._draft_rows)
        lay.addWidget(self._draft_section)

        # 未提炼片段（修复方案灰标区）：否定词命中的原文现场片段。
        # 定位讲清楚：它是证据不是经验、永不注入，接模型后自动整理。
        self._frag_section = card(title=t("未提炼片段"), secondary=True,
                                  visible=False)
        self._frag_title = self._frag_section.layout().itemAt(0).widget()
        self._frag_hint = txt(
            t("这些是 AI 被你说「不对」时的原文片段——只是现场证据，不是经验，"
              "永远不会被带进 AI 的工作里；接上模型后会自动整理成经验"),
            F.caption, color=C.ink_500)
        self._frag_hint.setWordWrap(True)
        self._frag_section.layout().addWidget(self._frag_hint)
        self._frag_rows = QVBoxLayout()
        self._frag_rows.setSpacing(S.s2)
        self._frag_section.layout().addLayout(self._frag_rows)
        lay.addWidget(self._frag_section)

        # 列表容器
        self._list_box = QWidget()
        self._list_layout = QVBoxLayout(self._list_box)
        self._list_layout.setSpacing(S.s3)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._list_box, 1)

        # 待撤销的不采纳（3 秒窗口）：token → {strip, card, ids, idx}
        self._pending_undo: dict[int, dict] = {}
        self._undo_token = 0
        self._exp_cards: dict[str, dict] = {}  # 增量 diff：组键 → {w, sig}
        self._drawer: DetailDrawer | None = None
        self._pending_scroll: int | None = None  # 归类重建后待回填的滚动位置

        # P1-2 + S2：子页滚动区走统一骨架；嵌入容器时顶部留白归 0
        # （顶边 32px 由容器页头提供，两处各加会叠成 64px）
        self._scroll = page_scaffold(
            lay, top=0 if self._embedded else PAGE_SIDE_PAD)
        self._layout.addWidget(self._scroll)

        # 懒加载下构建阶段零 API：trunk 下拉选项与列表都在 refresh() 里补齐
        # （数据由主窗口的延迟 refresh 触发）

    # ---------- 数据刷新 ----------

    def refresh(self) -> None:
        """切页/轮询刷新：取数整体在工作线程（主线程零 HTTP），渲染回主线程。

        下拉补齐（trunk/agent）与列表取数合并进**同一次**
        ``parallel_fetch``，不再主线程串行两次。"""
        # 任何重建先作废未到期的撤销条（其隐藏卡已脱离布局，重建会孤儿化）
        self._invalidate_undos()
        need_meta = self._trunk_combo.count() == 0
        trunk = self._trunk_combo.currentData()
        agent = self._agent_combo.currentData()
        q = self._search_tf.text().strip() or None
        self.fetch_and_render(
            lambda: self._fetch_all(need_meta, trunk, agent, q),
            self._render_all, "experiences", skeleton=[72, 72, 72])

    def _fetch_all(self, need_meta: bool, trunk, agent, q) -> dict:
        """工作线程：一次并行取列表/草稿/片段/模型状态（+ 首次下拉元数据）。

        不碰任何控件——筛选条件由调用方在主线程快照后传入。"""
        calls = {
            "list": lambda: self.api.experiences(trunk=trunk, agent=agent, q=q,
                                                 limit=300),
            "drafts": lambda: self.api.experience_drafts("pending"),
            "frags": self.api.pending_fragments,
            "models": self.api.models,
        }
        if need_meta:
            calls["meta"] = lambda: self.api.experiences(limit=300)
        return parallel_fetch(calls)

    def _render_all(self, data: dict | None) -> None:
        """渲染回调（主线程）：**不得再发 HTTP**，只按取数结果增量更新列表。"""
        data = data or {}
        items_res = data.get("list")
        if items_res is None:
            # 取数失败：如实报错，不清空现有卡片（下次轮询自愈）
            self.report_error(t("（读取失败）"))
            return
        meta = data.get("meta")
        if meta is not None and self._trunk_combo.count() == 0:
            all_items = meta.get("items", [])
            self._trunk_combo.addItem(t("全部"), None)
            for x in sorted({e.get("trunk") for e in all_items
                             if e.get("trunk")}):
                self._trunk_combo.addItem(x, x)
            # agent 筛选项（数据去重，raw agent 名）
            self._agent_combo.addItem(t("全部 agent"), None)
            for x in sorted({e.get("agent") for e in all_items
                             if e.get("agent")}):
                self._agent_combo.addItem(x, x)

        items = items_res.get("items", [])
        # 模型提示条：有待总结卡片且未接模型 → 显示（可用性随取数带下，零额外 HTTP）
        routes = (data.get("models") or {}).get("routes") or []
        model_available = any(str((r or {}).get("endpoint") or "").strip()
                              for r in routes)
        self._update_llm_hint(items, model_available)
        self._render_drafts((data.get("drafts") or {}).get("items") or [])
        self._render_fragments((data.get("frags") or {}).get("items") or [])

        trunk = self._trunk_combo.currentData()
        agent = self._agent_combo.currentData()
        q = self._search_tf.text().strip() or None
        want: list[tuple[str, str, object]] = []
        if not items:
            # P4-08：空库与「筛选无结果」分开——空库给下一步动作，无匹配提示换词
            filtered = bool(trunk or agent or q)
            if filtered:
                factory = lambda: empty_state(  # noqa: E731
                    t("没有匹配的经验"), t("换个关键词，或等 agent 多干几活"),
                    mascot="think")
            else:
                factory = lambda: empty_state(  # noqa: E731
                    t("还没有经验"),
                    t("去让任意 agent 干个活——反复失败又修好、报错再三出现，"
                      "都会自动变成坑卡落在这里"),
                    mascot="think")
            want.append(("__empty__", "empty:filtered" if filtered
                         else "empty:blank", factory))
        else:
            # 同一 task 的多个做法（不同解法）聚合成一张卡：逐条渲染会同 task 撞出
            # 重复标题、第二做法被埋——按 (类别, task) 分组后一卡一 task。
            for recs in _group_by_task(items):
                key = (f"{recs[0].get('category') or ''}\x00"
                       f"{recs[0].get('task') or ''}")
                want.append((key, content_sig(recs),
                             lambda r_=recs: self._exp_card(r_)))
        sync_tracked(self._list_layout, self._exp_cards, want)
        # 首屏错峰入场（"只首屏"的判断在基类 stagger_cards 里，一处实现）
        self.stagger_cards(self._list_layout)

        # 归类重建后回填滚动位置（重建是异步的，等本次渲染落地再设值）
        pos = self._pending_scroll
        if pos is not None:
            self._pending_scroll = None
            sb = self._scroll.verticalScrollBar()
            QTimer.singleShot(0, lambda p=pos: sb.setValue(min(p, sb.maximum())))

    def _forget_card(self, card) -> None:
        """把已释放的卡从增量 store 摘除（防下次 sync_tracked 触达已删控件）。"""
        for key, entry in list(self._exp_cards.items()):
            if entry["w"] is card:
                self._exp_cards.pop(key, None)

    # ---------- 重新翻译 ----------

    def retranslateUi(self) -> None:
        self._title_label.setText(t("经验库"))
        self._search_tf.setPlaceholderText(t("搜索"))
        # _export_btn has icon, so find child QLabel
        export_label = self._export_btn.layout().itemAt(1).widget()
        export_label.setText(t("导出"))
        if self._trunk_combo.count() > 0:
            self._trunk_combo.setItemText(0, t("全部"))
        if self._agent_combo.count() > 0:
            self._agent_combo.setItemText(0, t("全部 agent"))
        if hasattr(self, "_draft_title"):
            self._draft_title.setText(t("待放行的经验上报"))
            self._draft_hint.setText(t("工具收尾自动上报的经验：确认后入库，忽略即放弃"))
        if hasattr(self, "_frag_title"):
            self._frag_title.setText(t("未提炼片段"))
            self._frag_hint.setText(
                t("这些是 AI 被你说「不对」时的原文片段——只是现场证据，不是经验，"
                  "永远不会被带进 AI 的工作里；接上模型后会自动整理成经验"))
        if hasattr(self, "_llm_hint_text"):
            self._llm_hint_text.setText(
                t("接入模型（本地模型或 API）后，原始记录会自动总结成一句结论，"
                  "卡片更清爽"))
            _hint_lbl = self._llm_hint_btn.layout().itemAt(1).widget()
            if _hint_lbl is not None:
                _hint_lbl.setText(t("去接入"))
        self.refresh()

    # ---------- 模型提示条 ----------

    def _update_llm_hint(self, items: list[dict], model_available: bool) -> None:
        """有待总结（未蒸馏）卡片且未接模型 → 显示接入提示；否则隐藏。

        模型可用性由取数段（工作线程）随 ``api.models`` 带下，渲染回调不再发
        HTTP（门禁口径与 ``PageBase.model_state`` 一致：routes[].endpoint 非空）。"""
        has_undistilled = any(not e.get("distilled") for e in items)
        self._llm_hint.setVisible(bool(has_undistilled) and not model_available)

    def _render_fragments(self, items: list[dict]) -> None:
        """未提炼片段（证据队列）渲染：最多 6 条 + 总数提示（灰标区）。"""
        self._frag_section.setVisible(bool(items))
        clear_layout(self._frag_rows)
        for it in items[:6]:
            snippets = [str(s) for s in (it.get("snippets") or []) if str(s).strip()]
            if not snippets:
                continue
            meta_bits = [str(it.get("agent") or "")]
            if it.get("trunk"):
                meta_bits.append(f"{it['trunk']}/{it.get('category') or '未分类'}")
            meta_bits.append(str(it.get("ts") or "")[:16].replace("T", " "))
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(txt("  ·  ".join(b for b in meta_bits if b),
                              F.caption, color=C.ink_500))
            body = txt("｜".join(snippets[:2])[:200], F.body, 620)
            body.setWordWrap(True)
            col.addWidget(body)
            box = QWidget()
            box.setLayout(col)
            self._frag_rows.addWidget(box)
        if len(items) > 6:
            self._frag_rows.addWidget(txt(
                t("……还有 {n} 条，接上模型后会自动整理", n=len(items) - 6),
                F.caption, color=C.ink_500))

    # ---------- S5 待放行草稿 ----------

    def _render_drafts(self, items: list[dict]) -> None:
        """待放行草稿（无 LLM 时收尾经验只到这一步，靠用户一键放行）。"""
        items = items[:50]
        self._draft_section.setVisible(bool(items))
        clear_layout(self._draft_rows)
        for it in items:
            row = QHBoxLayout()
            row.setSpacing(S.s2)
            text = str(it.get("text") or "").replace("\n", " ")[:180]
            meta = f"{str(it.get('agent') or '')} · " \
                   f"{str(it.get('ts') or '')[:16].replace('T', ' ')}"
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(txt(meta, F.caption, color=C.ink_500))
            body = txt(text, F.body, 620)
            body.setWordWrap(True)
            col.addWidget(body)
            box = QWidget()
            box.setLayout(col)
            row.addWidget(box, 1)
            ad = btn_flat(t("放行"))
            ad.setFixedHeight(D.BTN_H_SM)
            ad.clicked.connect(lambda _=False, i=it["id"]: self._draft_adopt(i))
            row.addWidget(ad)
            ig = btn_flat(t("忽略"))
            ig.setFixedHeight(D.BTN_H_SM)
            ig.clicked.connect(lambda _=False, i=it["id"]: self._draft_ignore(i))
            row.addWidget(ig)
            w = QWidget()
            w.setLayout(row)
            self._draft_rows.addWidget(w)

    def _draft_adopt(self, draft_id: str) -> None:
        self._draft_act(draft_id, True)

    def _draft_ignore(self, draft_id: str) -> None:
        self._draft_act(draft_id, False)

    def _draft_act(self, draft_id: str, adopt: bool) -> None:
        """adopt/ignore 客户端超时 60s，原主线程同步
        请求会冻结整窗——改走 run_async 后台线程（同文件其余写操作模式），
        忙态防重复提交，完成/失败都给状态行反馈。"""
        if getattr(self, "_draft_busy", False):
            return
        self._draft_busy = True
        self.set_status(t("正在处理…"), "info")

        def work():
            if adopt:
                return self.api.experience_draft_adopt(draft_id)
            return self.api.experience_draft_ignore(draft_id)

        def on_done(r) -> None:
            self._draft_busy = False
            if adopt and not (r or {}).get("ok"):
                self.set_status(str((r or {}).get("error") or t("处理失败")))
                return
            self.refresh()

        def on_error(err: str) -> None:
            self._draft_busy = False
            self.set_status(err)

        self.run_async(work, on_done, on_error)

    def _exp_card(self, recs: list[dict]) -> QFrame:
        """经验卡：同一 task 的多个做法收成一张卡。

        顶行 = category 小标签（未分类弱化）+ 日期；标题 = task（蒸馏压出的一句
        结论，两行省略，原文更长时可点展开看全）；副行 = agent · model；内容区 =
        踩坑/做法/结果走 field_row（值 = 一句结论，原文可点展开）；底行 = 状态 chip
        + 有效/纠正 ghost 按钮。同一 task 的多条记录（不同做法）聚合后一卡一 task，
        反馈按钮指向组内首条。"""
        rep = recs[0]  # 组内首条：标题 / 元信息 / 反馈 id 的取值基准

        def _first_nonempty(key: str) -> tuple[str, str]:
            # 取组内首个非空值，连同原文（key_raw）供卡片点击展开下钻
            for r in recs:
                v = str(r.get(key) or "").strip()
                if v:
                    return v, str(r.get(key + "_raw") or v)
            return "", ""

        # 全部不同做法（保序去重）——多做法任务的每种解法都可见，保留原文供展开
        action_pairs: list[tuple[str, str]] = []
        for r in recs:
            a = str(r.get("action") or "").strip()
            if a and not any(x[0] == a for x in action_pairs):
                action_pairs.append((a, str(r.get("action_raw") or a)))
        # 踩坑 / 结果：取组内首个非空值（+ 原文）
        state, state_raw = _first_nonempty("state")
        outcome, outcome_raw = _first_nonempty("outcome")

        # 档 2：自绘投影卡片（省逐控件 QGraphicsDropShadowEffect 的 CPU 合成）
        c = ShadowCard()
        hover_lift(c)
        cl = c.layout()

        # 整卡操作作用于组内全部 id（一卡一任务），摘要取首条 task 短显
        group_ids = [r["id"] for r in recs]
        summary = str(rep.get("task") or "") or str(rep.get("task_raw") or "")
        summary_short = summary if len(summary) <= 20 else summary[:20] + "…"

        # 顶行：category 小标签（未分类弱化）+ 日期（右）+ ⋯ 卡片操作（最右角）
        top = QHBoxLayout()
        top.setSpacing(S.s2)
        category = str(rep.get("category") or "").strip()
        if category:
            top.addWidget(chip(category, "ink"))
        top.addStretch(1)
        top.addWidget(txt(str(rep.get("ts") or "")[:10], F.caption,
                          color=C.ink_500))
        mbtn = ellipsis_button(tooltip=t("更多操作"))
        mbtn.clicked.connect(
            lambda _=False: self._open_card_menu(mbtn, c, group_ids,
                                                 summary_short, recs))
        top.addWidget(mbtn)
        cl.addLayout(top)

        # 标题：task（蒸馏压出的一句结论）两行省略；原文更长时可点展开看全——
        # 解决"两行显示不全"：默认紧凑不撑卡，用户点一下看全，全文不再被截断。
        task = str(rep.get("task") or "")
        task_raw = str(rep.get("task_raw") or task)
        cl.addWidget(expandable_clamped(task, task_raw, F.h2, 600,
                                        C.ink_900, max_lines=3))

        # 副行：agent · model
        cl.addWidget(txt(
            f"{rep.get('agent', '')} · {rep.get('model', '') or '—'}",
            F.caption, color=C.ink_500))

        # 内容区：踩坑/做法/结果逐条走 field_row（值 = 一句结论，原文可点展开）
        if state:
            cl.addWidget(field_row(t("踩坑："), "err", state, state_raw))
        for a, a_raw in action_pairs:
            cl.addWidget(field_row(t("做法："), "brand", a, a_raw))
        if outcome:
            cl.addWidget(field_row(t("结果："), "ok", outcome, outcome_raw))

        # 底行：状态 chip + 详情（左）+ 有效/纠正 ghost（右）
        cl.addWidget(divider())
        foot = QHBoxLayout()
        foot.setSpacing(S.s2)
        foot.addWidget(chip(t("已总结") if rep.get("distilled") else t("待总结"),
                            "info" if rep.get("distilled") else "warn"))
        detail_btn = btn_flat(t("详情"))
        detail_btn.setToolTip(t("查看这条经验的完整详情"))
        detail_btn.clicked.connect(
            lambda _=False, r_=recs: self._open_detail(r_))
        foot.addWidget(detail_btn)
        foot.addStretch(1)
        valid_btn = btn_ghost(t("有效"), "CHECK_OUTLINED", C.ok_fg,
                              on_click=lambda _=False,
                              eid=rep["id"]: self._feedback(eid, "valid"))
        valid_btn.setToolTip(t("有效"))
        foot.addWidget(valid_btn)
        correct_btn = btn_ghost(t("纠正"), "EDIT_OUTLINED", C.err_fg,
                                on_click=lambda _=False,
                                grp=recs: self._correct_group(grp))
        correct_btn.setToolTip(t("纠正"))
        foot.addWidget(correct_btn)
        cl.addLayout(foot)

        return c

    def _open_detail(self, recs: list[dict]) -> None:
        """点「详情」→ 统一下钻抽屉。底部操作槽 = 纠正 / 讲人话。"""
        if self._drawer is None:
            self._drawer = DetailDrawer(self)
        rep = recs[0]
        task = str(rep.get("task") or rep.get("task_raw") or "")
        agents: dict[str, int] = {}
        for r in recs:
            a = str(r.get("agent") or "").strip()
            if a:
                agents[a] = agents.get(a, 0) + 1
        path = " / ".join(x for x in (str(rep.get("trunk") or ""),
                                      str(rep.get("category") or "")) if x)
        payload = {
            "title": task or t("经验"),
            "body": self._exp_detail_body(recs),
            "status": t("已总结") if rep.get("distilled") else t("待总结"),
            "status_tone": "info" if rep.get("distilled") else "warn",
            "experience_ids": [str(r.get("id")) for r in recs if r.get("id")],
            "timeline": " · ".join(x for x in (path, str(rep.get("ts") or ""))
                                   if x),
        }
        if agents:
            payload["agents"] = agents
        drawer = self._drawer

        def _correct_from_drawer() -> None:
            drawer.close_drawer()
            self._correct_group(recs)

        def _explain_from_drawer() -> None:
            drawer.close_drawer()
            self._ai_explain(recs)

        drawer.set_actions([
            btn_flat(t("纠正"), on_click=lambda _=False: _correct_from_drawer()),
            btn_flat(t("讲人话（AI 解释 + 建议）"),
                     on_click=lambda _=False: _explain_from_drawer()),
        ])
        drawer.open_detail("experience", payload)

    @staticmethod
    def _exp_detail_body(recs: list[dict]) -> str:
        """抽屉正文：逐条做法的 Markdown（阅读态富文本由的 md_view 渲染）。"""
        blocks: list[str] = []
        multi = len(recs) > 1
        for i, r in enumerate(recs):
            lines: list[str] = []
            if multi:
                lines.append(f"### {t('第 {n} 个做法', n=i + 1)}")
            meta = " · ".join(x for x in (str(r.get("agent") or ""),
                                          str(r.get("ts") or "")[:19]) if x)
            if meta:
                lines.append(f"*{meta}*")
            for label, key in ((t("踩坑："), "state"), (t("做法："), "action"),
                               (t("结果："), "outcome")):
                v = str(r.get(key + "_raw") or r.get(key) or "").strip()
                if v:
                    lines.append(f"**{label}** {v}")
            if lines:
                blocks.append("\n\n".join(lines))
        return "\n\n".join(blocks)

    def _feedback(self, eid: str, kind: str) -> None:
        try:
            self.api.feedback(eid, kind)
            self.set_status(t("反馈已记录"), "ok")
            self.refresh()
        except LocalApiError as exc:
            self.set_status(str(exc.detail))

    def _correct_group(self, recs: list[dict]) -> None:
        """纠正 = 直接改内容：打开编辑框，逐条改这张卡里的全部记录。
        保存后按纠正口径落库（G=0.2、corrected=true、回炉重蒸馏），故整表重建
        ——分组可能因此变化，保留滚动位置。"""
        dlg = ExperienceEditDialog(self.api, recs, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self.set_status(t("已纠正，内容已更新"), "ok")
        self._rebuild_preserve_scroll()

    # ---------- 卡片操作：归类 / 不采纳 ----------

    def _open_card_menu(self, anchor, card, ids, summary,
                        recs: list[dict] | None = None) -> None:
        """卡片右上 ⋯ 菜单：让 AI 重写 + 归类为…（子菜单）+ 不采纳。
        弹层锚定在按钮右下、且 clamp 到屏幕内（治"弹到屏幕右边缘"）。"""
        menu = QMenu(anchor)
        explain_act = menu.addAction(t("讲人话（AI 解释 + 建议）"))
        ai_act = menu.addAction(t("让 AI 重写"))
        sub = menu.addMenu(t("归类为…"))
        try:
            cats = sorted({str(c) for c in
                           (self.api.experience_categories().get("categories")
                            or [])})
        except LocalApiError:
            cats = []
        cat_acts = [sub.addAction(c) for c in cats]
        sub.addSeparator()
        new_act = sub.addAction(t("新建分类…"))
        dismiss_act = menu.addAction(t("不采纳"))
        chosen = self._exec_menu_anchored(anchor, menu)
        if chosen is explain_act:
            self._ai_explain(recs or [])
        elif chosen is ai_act:
            self._ai_rewrite_group(recs or [])
        elif chosen is new_act:
            self._new_category(anchor, card, ids, summary)
        elif chosen in cat_acts:
            self._categorize_group(card, ids, chosen.text(), summary)
        elif chosen is dismiss_act:
            self._dismiss_group(card, ids, summary)

    # ---------- 让 AI 重写（第二项蒸馏：提案 → 预览对比 → 采纳才落库） ----------

    def _ai_rewrite_group(self, recs: list[dict]) -> None:
        """整卡记录送模型重写；「重写一遍」= 再调一次模型。
        采纳口径 = rewrite.apply_polish：只动总结层、不标纠正、回炉重总结。"""
        if not self.require_model(t("让 AI 重写")):
            return
        ids = [str(r.get("id")) for r in recs if r.get("id")]
        if not ids:
            return
        self.set_status(t("正在让 AI 重写…"), "info")

        def work():
            return self.api.ai_polish_experiences(ids)

        def on_done(r):
            if self._reject_model_required(r):
                return
            proposals = [p for p in ((r or {}).get("proposals") or [])
                         if p.get("id")]
            if not proposals:
                self.set_status(t("AI 没有给出可用的重写"))
                return
            dlg = ExperienceRewriteDialog(recs, proposals, self)
            ret = dlg.exec()
            if ret == 2:  # REDO
                self._ai_rewrite_group(recs)
                return
            if ret != QDialog.Accepted:
                self.set_status(t("已保留当前内容"), "info")
                return
            try:
                for p in proposals:
                    self.api.ai_apply_experience(
                        str(p["id"]),
                        {k: str(p.get(k) or "") for k in
                         ("task", "state", "action", "outcome")})
            except LocalApiError as exc:
                self.set_status(str(exc.detail))
                return
            self.set_status(t("已采纳，内容已更新"), "ok")
            self._rebuild_preserve_scroll()

        def on_error(err):
            self.set_status(t("AI 重写失败：{err}", err=err))

        self.run_async(work, on_done, on_error)

    # ---------- 讲人话 ----------

    def _ai_explain(self, recs: list[dict]) -> None:
        """单条经验送模型讲人话；结果缓存在记录上，再点零成本。"""
        if not self.require_model(t("讲人话（AI 解释 + 建议）")):
            return
        r = recs[0] if recs else None
        eid = str(r.get("id") or "") if r else ""
        if not eid:
            return
        self.set_status(t("正在让 AI 讲人话…"), "info")

        def work():
            return self.api.experience_explain(eid, current_language())

        def on_done(res):
            res = res or {}
            if self._reject_model_required(res):
                return
            explain = str(res.get("explain") or "").strip()
            advice = str(res.get("advice") or "").strip()
            if not explain and not advice:
                self.set_status(t("AI 没有给出可用的解释"))
                return
            rich_info_dialog(
                t("这条经验在说什么"),
                f"<b>{t('这是什么')}</b><br>{explain}"
                f"<br><br><b>{t('给你的建议')}</b><br>{advice}",
                self)
            self.set_status(t("已用大白话讲完"), "ok")

        def on_error(err):
            self.set_status(t("AI 讲人话失败：{err}", err=err))

        self.run_async(work, on_done, on_error)

    def _reject_model_required(self, r) -> bool:
        """引擎返回 ``status == "model_required"`` → 如实告知，不假装已生成。

        返回 True 表示已按拒绝路径处理（调用方不得再显示"已生成/已更新"）。"""
        if not isinstance(r, dict) or r.get("status") != "model_required":
            return False
        msg = str(r.get("message") or t("未接入模型，无法完成这一步"))
        if r.get("kept_previous"):
            msg = f"{msg} {t('已保留上次内容')}"
        self.set_status(msg, "warn")
        self.toast(msg)
        return True

    @staticmethod
    def _exec_menu_anchored(anchor, menu):
        """在按钮右下方 exec QMenu，并 clamp 到屏幕可用区（避免跑出屏幕边缘）。"""
        menu.ensurePolished()
        gp = anchor.mapToGlobal(anchor.rect().bottomRight())
        sz = menu.sizeHint()
        x, y = gp.x(), gp.y() + 4
        scr = QGuiApplication.screenAt(gp) or QGuiApplication.primaryScreen()
        if scr is not None:
            av = scr.availableGeometry()
            x = max(av.left(), min(x, av.right() - sz.width() - 8))
            y = max(av.top(), min(y, av.bottom() - sz.height() - 8))
        return menu.exec(QPoint(x, y))

    def _new_category(self, anchor, card, ids, summary) -> None:
        # 原生 QInputDialog 在中文界面显示英文按钮、
        # 风格与品牌冲突，且不释放——改主题化 input_dialog。
        name = input_dialog(t("新建分类"), t("输入分类名"), self)
        if not name or not name.strip():
            return
        self._categorize_group(card, ids, name.strip(), summary)

    def _categorize_group(self, card, ids, category, summary) -> None:
        """组内全部记录一起归类（连带 trunk 推断在服务端）。归类会改变分组
        → 整表重建，但保留滚动位置（不让页面跳到顶部/中间）。"""
        try:
            for eid in ids:
                self.api.categorize_experience(eid, category)
        except LocalApiError as exc:
            self.set_status(str(exc.detail))
            return
        self._rebuild_preserve_scroll()

    def _dismiss_group(self, card, ids, summary) -> None:
        """不采纳：对组内各 id 打 dismissed 标记后，手术式移除这一张卡
        （不整屏重建），并在原位插一条 3 秒可撤销条。"""
        try:
            for eid in ids:
                self.api.dismiss_experience(eid)
        except LocalApiError as exc:
            self.set_status(str(exc.detail))
            return
        idx = self._list_layout.indexOf(card)
        if idx < 0:  # 卡已不在列表（理论上不会），放弃手术
            return
        self._list_layout.takeAt(idx)   # 解除归属，卡保留 alive 供撤销复用
        card.hide()
        token = self._undo_token
        self._undo_token += 1
        strip = self._make_undo_strip(token, summary)
        self._list_layout.insertWidget(idx, strip)
        pend = {"strip": strip, "card": card, "ids": ids, "idx": idx}
        self._pending_undo[token] = pend
        QTimer.singleShot(3000, lambda: self._expire_undo(token))

    def _make_undo_strip(self, token, summary):
        w = QWidget()
        # #id 限定作用域：裸 QWidget{} 会级联到内部文本/按钮，顶掉它们的样式
        w.setObjectName("undoStrip")
        w.setStyleSheet(
            f"QWidget#undoStrip {{ background: {C.surface_2};"
            f" border: 1px solid {C.line}; border-radius: {R.md}px; }}")
        h = QHBoxLayout(w)
        h.setContentsMargins(S.s3, S.s2, S.s3, S.s2)
        h.setSpacing(S.s3)
        lbl = txt(f"{t('已移出')}「{summary}」", F.body, color=C.ink_700)
        lbl.setWordWrap(True)
        h.addWidget(lbl, 1)
        undo = btn_flat(t("撤销"),
                        on_click=lambda _=False: self._undo_dismiss(token))
        h.addWidget(undo, 0, Qt.AlignVCenter)
        return w

    def _undo_dismiss(self, token) -> None:
        """撤销条点「撤销」：恢复组内各 id，把原卡插回原位，撤掉撤销条。"""
        pend = self._pending_undo.pop(token, None)
        if pend is None:
            return
        try:
            for eid in pend["ids"]:
                self.api.restore_experience(eid)
        except LocalApiError as exc:
            self.set_status(str(exc.detail))
            self._finish_remove(pend)
            return
        strip = pend["strip"]
        si = self._list_layout.indexOf(strip)
        if si >= 0:
            self._list_layout.takeAt(si)
        strip.deleteLater()
        card = pend["card"]
        card.show()
        self._list_layout.insertWidget(pend["idx"], card)

    def _expire_undo(self, token) -> None:
        """3 秒窗口结束未撤销：清掉撤销条并释放这张被移出的卡。"""
        pend = self._pending_undo.pop(token, None)
        if pend is not None:
            self._finish_remove(pend)

    def _finish_remove(self, pend) -> None:
        strip = pend["strip"]
        si = self._list_layout.indexOf(strip)
        if si >= 0:
            self._list_layout.takeAt(si)
        strip.deleteLater()
        card = pend["card"]
        self._forget_card(card)
        card.deleteLater()

    def _invalidate_undos(self) -> None:
        """列表重建前作废所有待撤销条目：撤掉撤销条并释放被移出的卡，
        防重建把布局里的隐藏控件 deleteLater 后定时器再触达已删对象。"""
        for token in list(self._pending_undo):
            pend = self._pending_undo.pop(token)
            si = self._list_layout.indexOf(pend["strip"])
            if si >= 0:
                self._list_layout.takeAt(si)
            pend["strip"].deleteLater()
            card = pend["card"]
            self._forget_card(card)  # store 同步摘除，防 sync_tracked 触达已删控件
            card.deleteLater()

    def _rebuild_preserve_scroll(self) -> None:
        """归类后的整表重建并保持滚动位置（不让页面跳到顶部/中间）。

        重建走异步取数，故把位置交给 ``_render_all`` 在渲染落地后回填。"""
        self._pending_scroll = self._scroll.verticalScrollBar().value()
        self.refresh()

    # ---------- 工具 ----------

    @staticmethod
    def _clear_layout(lay: QVBoxLayout) -> None:
        clear_layout(lay)
