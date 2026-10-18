"""失败模式页——Qt 版（原 Flet 源文件 failure_modes.py）。

三态（观察中/待验证/已固化）+ 出现次数 + 轨迹回溯 + 用户否决。
空状态 = fail 宇航员（deck  表情家族：失败/错误空状态脸）。
"""

from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)

from .ai_rewrite import line_rewrite_dialog
from .api_client import LocalApi, LocalApiError
from .i18n import t
from .page_base import (PAGE_SIDE_PAD, PageBase, clear_layout, content_sig,
                        page_scaffold, parallel_fetch, sync_tracked)
from .qt_dialogs import confirm_dialog
from .qt_theme import btn_flat, empty_state, txt
from .qt_widgets import DetailDrawer, ShadowCard, hover_lift, page_header
from .theme import C, F, S


class FailureModesPage(PageBase):
    """失败模式子页。"""

    def __init__(self, api: LocalApi, parent=None, embedded: bool = False):
        super().__init__(api, parent)
        self._embedded = embedded
        self._cards: dict[str, dict] = {}  # 增量 diff：key → {w, sig}
        self._drawer: DetailDrawer | None = None
        self._build()

    # ---------- UI 构建 ----------

    def _build(self) -> None:
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(S.s6)

        # 统一页头（S1）：嵌入「我的经验」容器时走 dense 档（h2）。
        # 注意：**文案键不得新增**（locales 目录冻结，测试要求每个 t() 键在全部
        # catalog 存在）——故沿用原有两个键：首句作页头副标题，第二句单独一行。
        head = page_header(
            t("踩过的坑"),
            t("失败模式——自动记录每次任务反复出错的模式"),
            dense=self._embedded)
        self._title_label = head.findChild(QLabel, "pageTitle")
        self._subtitle1_label = head.findChild(QLabel, "pageSubtitle")
        lay.addWidget(head)

        self._subtitle2_label = txt(
            t("记住了 = 每次自动带上；待验证 = 等下次同类任务确认；留意中 = 只记录，不自动附带"),
            F.caption, color=C.ink_500)
        self._subtitle2_label.setWordWrap(True)
        lay.addWidget(self._subtitle2_label)

        # 列表容器
        self._list_box = QWidget()
        self._list_layout = QVBoxLayout(self._list_box)
        self._list_layout.setSpacing(S.s3)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._list_box, 1)

        # P1-2 + S2：子页滚动区走统一骨架；嵌入容器时顶部留白归 0
        self._layout.addWidget(page_scaffold(
            lay, top=0 if self._embedded else PAGE_SIDE_PAD))

        # 懒加载下构建阶段零 API：数据由 MyExperiencePage 的延迟 refresh 填充

    # ---------- 数据刷新 ----------

    def refresh(self) -> None:
        """切页/轮询刷新：取数整体在工作线程（主线程零 HTTP），渲染回主线程。"""
        self.fetch_and_render(
            lambda: parallel_fetch({
                "fm": self.api.failure_modes,
                "rules": lambda: self.api.rule_cards(limit=20),
            }),
            self._render_all, "fm", skeleton=[24, 72, 72, 72])

    def _render_all(self, data: dict | None) -> None:
        """渲染回调（主线程）：**不得再发 HTTP**，只按取数结果增量更新列表。"""
        data = data or {}
        fm = data.get("fm")
        if fm is None:
            # 取数失败：如实报错，不清空现有卡片（下次轮询自愈）
            self.report_error(t("（读取失败）"))
            return
        items = fm.get("items", [])
        rules = (data.get("rules") or {}).get("items") or []
        want: list[tuple[str, str, object]] = []
        if not items:
            # 修复方案：还没总结成方法时也要有东西可看——直接吃 T1
            # 结构事实坑卡（不接模型也在记），两者都空才是真空态
            if rules:
                want.append(("__hint__", "hint", lambda: txt(
                    t("从操作记录里直接看出来的坑（自动总结成方法后会更精炼）"),
                    F.caption, color=C.ink_500, wrap=True)))
                for c in rules:
                    want.append((f"rule:{c.get('id')}", content_sig(c),
                                 lambda c_=c: self._rule_row(c_)))
            else:
                want.append(("__empty__", "empty", lambda: empty_state(
                    t("还没有踩过的坑"),
                    t("让 agent 干点活——反复失败、报错再三出现，都会自动记在这里"),
                    mascot="fail")))
        else:
            for it in items:
                trunk, category = it["trunk"], it["category"]
                # R4：标题 = 显示名（若有），副标签 = 项目/类别两级路径恒显
                name = it.get("name")
                want.append((
                    f"head:{trunk}\x00{category}", content_sig([name, trunk, category]),
                    lambda t_=trunk, c_=category, n_=name:
                    self._head_box(t_, c_, n_)))
                entries = it.get("entries")
                if entries:
                    # 三态（gate 实时计数）：已固化 → 待验证 → 观察中
                    for state in ("solid", "pending", "watch"):
                        for e in (x for x in entries if x.get("state") == state):
                            want.append((
                                f"e:{trunk}\x00{category}\x00{state}"
                                f"\x00{e.get('text', '')}", content_sig(e),
                                lambda t_=trunk, c_=category, e_=e:
                                self._entry_card(t_, c_, e_)))
                else:
                    for text in it.get("solid", []):
                        e = {"text": text, "state": "solid"}
                        want.append((
                            f"e:{trunk}\x00{category}\x00solid\x00{text}", content_sig(e),
                            lambda t_=trunk, c_=category, e_=e:
                            self._entry_card(t_, c_, e_)))
                    for text in it.get("watching", []):
                        e = {"text": text, "state": "watch"}
                        want.append((
                            f"e:{trunk}\x00{category}\x00watch\x00{text}", content_sig(e),
                            lambda t_=trunk, c_=category, e_=e:
                            self._entry_card(t_, c_, e_)))
        sync_tracked(self._list_layout, self._cards, want)
        # 首屏错峰入场（"只首屏"在基类 stagger_cards 里一处实现）
        self.stagger_cards(self._list_layout)

    @staticmethod
    def _head_box(trunk: str, category: str, name: str | None) -> QWidget:
        head_box = QWidget()
        head_lay = QVBoxLayout(head_box)
        head_lay.setSpacing(S.s1)
        head_lay.setContentsMargins(0, 0, 0, 0)
        # 标题与副行都是**数据驱动**（trunk / category 来自后端，可能很长）——
        # wrap=True 在够宽时无视觉变化，只在窄/长时才换行（否则撑爆列宽 + 截断）。
        head_lay.addWidget(txt(name or f"{trunk} / {category}", F.h2, 600,
                               wrap=True))
        if name:
            head_lay.addWidget(txt(f"{trunk} / {category}", F.caption,
                                   color=C.ink_500, wrap=True))
        return head_box

    @staticmethod
    def _rule_row(c: dict) -> QWidget:
        """T1 结构事实坑卡单行（规则卡渲染，不接模型也看得见）。"""
        from .rule_render import rule_display, state_word
        kind, line = rule_display(c)
        label = f"「{kind}」{line}"
        reps = int(c.get("count") or 1)
        row = QHBoxLayout()
        sw, _tone = state_word(bool(c.get("injectable")))
        row.addWidget(txt(sw, F.caption, 600,
                          C.err_fg if c.get("injectable") else C.warn_fg))
        row.addWidget(txt(label, F.body, wrap=True), 1)
        if reps > 1:
            row.addWidget(txt(t("（出现 {n} 次）", n=reps), F.caption,
                              color=C.ink_500))
        box = QWidget()
        box.setLayout(row)
        return box

    # ---------- 重新翻译 ----------

    def retranslateUi(self) -> None:
        if self._title_label is not None:
            self._title_label.setText(t("踩过的坑"))
        if self._subtitle1_label is not None:
            self._subtitle1_label.setText(t(
                "失败模式——自动记录每次任务反复出错的模式"))
        if self._subtitle2_label is not None:
            self._subtitle2_label.setText(t(
                "记住了 = 每次自动带上；待验证 = 等下次同类任务确认；留意中 = 只记录，不自动附带"))

    def _entry_card(self, trunk: str, category: str, e: dict) -> QFrame:
        """单条坑卡：三态字 + 文案 + 计数/白话提示 + 查看轨迹（折叠）+ 删除（用户否决）。"""
        state = e.get("state", "watch")
        text = e.get("text", "")
        count = int(e.get("count") or 0)
        if state == "solid":
            state_txt = txt(t("记住了"), F.caption, 600, C.err_fg)
        elif state == "pending":
            state_txt = txt(t("待验证"), F.caption, 600, C.warn_fg)
        else:
            state_txt = txt(t("留意中"), F.caption, 600, C.warn_fg)

        traj_box = QWidget()
        traj_lay = QVBoxLayout(traj_box)
        traj_lay.setSpacing(S.s1)
        traj_lay.setContentsMargins(0, 0, 0, 0)
        traj_box.hide()

        def toggle_traj() -> None:
            if traj_box.isVisible():
                traj_box.hide()
                return
            # 轨迹取数原同步（15s 超时）跑在 UI 线程——
            # 点开轨迹时引擎未起/卡住直接冻结界面。改后台取数；展开期间先给
            # "正在读取"占位（动作要有即时反馈）。
            clear_layout(traj_lay)
            traj_lay.addWidget(txt(t("正在读取轨迹…"), F.caption,
                                   color=C.ink_500))
            traj_box.show()

            def work():
                return self.api.failure_mode_trajectory(trunk, category).get(
                    "items", [])

            def done(items) -> None:
                clear_layout(traj_lay)
                if items[:20]:
                    for it in items[:20]:
                        traj_lay.addWidget(txt(
                            f"· {it.get('ts', '')}  {it.get('task', '')}  "
                            f"{t('（出现 {n} 次）', n=it.get('count', 1))}",
                            F.caption, color=C.ink_500, wrap=True))
                else:
                    traj_lay.addWidget(txt(t("没有可回溯的低 G 经验"), F.caption,
                                           color=C.ink_500))

            def err(e) -> None:
                clear_layout(traj_lay)
                traj_lay.addWidget(txt(str(e), F.caption, color=C.ink_500))

            self.run_async(work, done, err)

        # 档 2：自绘投影卡片（省逐控件 QGraphicsDropShadowEffect 的 CPU 合成）
        c = ShadowCard()
        hover_lift(c)
        cl = c.layout()
        head = QHBoxLayout()
        head.setSpacing(S.s1)
        head.addWidget(state_txt)
        # ★ 坑卡正文是**数据驱动**的长句（如"反复出现的报错「Error: String to
        # replace not found…」"）。不换行 → 标签最小宽 = 整句像素宽 → 撑爆内容列
        # （实测：中文也溢出 19px，德语 129px、法语 112px，页面出现横向滚动条）。
        text_lbl = txt(text, F.body, wrap=True)
        text_lbl.setCursor(Qt.PointingHandCursor)
        text_lbl.setToolTip(t("查看详情"))
        text_lbl.mousePressEvent = (
            lambda _e, t_=trunk, c_=category, e_=e: self._open_detail(t_, c_, e_))
        head.addWidget(text_lbl, 1)
        cl.addLayout(head)

        # 计数 + 三态白话（待验证给"等下次同类任务确认"，观察过期给标注）
        if state == "pending":
            meta = t("出现了 {n} 次，等下次同类任务确认它还会不会踩", n=count)
        elif e.get("expired"):
            meta = t("出现 {n} 次 · 观察过期", n=count)
        else:
            meta = t("出现 {n} 次", n=count)
        if e.get("last_seen"):
            meta += f" · {t('最近一次：{d}', d=e['last_seen'])}"
        cl.addWidget(txt(meta, F.caption, color=C.ink_500, wrap=True))

        acts = QHBoxLayout()
        acts.setSpacing(S.s2)
        acts.addWidget(btn_flat(t("查看轨迹"), on_click=lambda _=False: toggle_traj()))
        acts.addWidget(btn_flat(
            t("让 AI 重写"),
            on_click=lambda _=False, t_=text: self._ai_rewrite(trunk, category, t_)))
        acts.addStretch(1)
        acts.addWidget(btn_flat(
            t("这条不对，删掉"),
            on_click=lambda _=False, t_=text: self._reject(trunk, category, t_)))
        cl.addLayout(acts)
        cl.addWidget(traj_box)
        return c

    def _open_detail(self, trunk: str, category: str, e: dict) -> None:
        """点坑卡标题 → 统一下钻抽屉。底部操作槽 = 标记（否决）。"""
        if self._drawer is None:
            self._drawer = DetailDrawer(self)
        text = str(e.get("text") or "")
        state = str(e.get("state") or "watch")
        payload = {
            "title": text or f"{trunk} / {category}",
            "body": text,
            "status": {"solid": t("记住了"), "pending": t("待验证")}.get(
                state, t("留意中")),
            "status_tone": "err" if state == "solid" else "warn",
            "timeline": f"{trunk} / {category}",
        }
        if e.get("ts"):
            payload["timeline"] += f" · {e['ts']}"
        drawer = self._drawer

        def _reject_from_drawer() -> None:
            drawer.close_drawer()
            self._reject(trunk, category, text)

        drawer.set_actions([btn_flat(t("这条不对，删掉"),
                                     on_click=lambda _=False: _reject_from_drawer())])
        drawer.open_detail("failure", payload)

    def _ai_rewrite(self, trunk: str, category: str, text: str) -> None:
        """单条坑 AI 改写：提案→预览对比→采纳才换行（标记与次数保持）。
        素材只有这一行 + 出现轨迹（坑没有整段原文），语义保持是关键约束。"""
        if not self.require_model(t("让 AI 重写")):
            return
        self.set_status(t("正在让 AI 重写…"), "info")

        def work():
            return self.api.ai_polish_failure(trunk, category, text)

        def on_done(r):
            if self._reject_model_required(r):
                return
            new = str((r or {}).get("new_text") or "").strip()
            if not new:
                self.set_status(t("AI 没有给出可用的重写"))
                return
            ret = line_rewrite_dialog(self, text, new)
            if ret == 2:  # REDO
                self._ai_rewrite(trunk, category, text)
                return
            if ret != 1:
                self.set_status(t("已保留当前内容"), "info")
                return
            try:
                self.api.ai_apply_failure(trunk, category, text, new)
            except LocalApiError as exc:
                self.set_status(exc.localized())
                return
            self.set_status(t("已采纳，内容已更新"), "ok")
            self.refresh()

        def on_error(err):
            self.set_status(t("AI 重写失败：{err}", err=err))

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

    def _reject(self, trunk: str, category: str, text: str) -> None:
        """用户否决：确认后删除并从方法中移除（判断优先于机器归纳）。"""
        ok = confirm_dialog(
            t("否决这条坑？"),
            f"{text}\n\n{t('删掉后不再自动带上；记录留痕（你的判断优先于机器归纳）')}",
            self)
        if not ok:
            return
        try:
            self.api.reject_failure_mode(trunk, category, text)
            self.set_status(t("已否决并从方法中删除"), "ok")
            self.refresh()
        except LocalApiError as exc:
            self.set_status(exc.localized())
