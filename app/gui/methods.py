"""我的方法页（Qt 版，对应 Flet 源 methods.py）：playbook 展示
+ [蒸馏] + 每类 [转 Skill]（版本化/diff）+ [整理 Skill]。

取数整体挪工作线程（切页不冻）、列表按 id 增量复用、无模型溯源条、
点标题下钻统一抽屉。：列表卡正文改纯文本摘录（富文本仅在详情抽屉渲染）。
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from . import report_view
from .ai_rewrite import md_rewrite_dialog
from .api_client import LocalApi, LocalApiError
from .i18n import t
from .page_base import (PAGE_SIDE_PAD, PageBase, content_sig, page_scaffold,
                        parallel_fetch, sync_tracked)
from .qt_dialogs import skill_preview_dialog, sources_dialog
from .qt_theme import (btn_flat, btn_primary, btn_secondary, card, chip,
                       empty_state, icon_button, list_row,
                       provenance_bar, status_text, status_tone, txt)
from .qt_widgets import DetailDrawer, ShadowCard, hover_lift, page_header
from .theme import C, D, F, S

# 方法正文取数的批量上限：每批至多这么多个请求，批内并发数见 _BODY_WORKERS。
# 卡很多时不一次性把上百个请求全塞进线程池；取数范围不变（正文照样全取）。
_BODY_BATCH = 12
_BODY_WORKERS = 5

# 方法页列表卡不再逐张富文本渲染——setMarkdown 的富文本解析是入页构建的
# 主要成本（实测 300 张卡：md_view 约 150ms、纯文本摘录约 14ms，差约 10 倍）。
# 列表只显示正文的纯文本摘录，完整排版正文仍在详情抽屉里看（_open_detail）。
_EXCERPT_LINES = 4
_EXCERPT_CHARS = 200
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")   # 链接 → 文字
_MD_INLINE_RE = re.compile(r"[*_`~]+")              # 强调 / 行内代码标记
_MD_TABLE_RULE_RE = re.compile(r"^\|?[\s\-:|]+\|?$")  # 表格分隔 / 纯装饰行


def _md_excerpt(md: str, max_lines: int = _EXCERPT_LINES,
                max_chars: int = _EXCERPT_CHARS) -> str:
    """Markdown 正文 → 列表卡纯文本摘录。

    只取前若干**非空正文行**，去掉 Markdown 标记（标题/列表/引用/链接/强调/
    代码围栏），使列表读起来是自然文本而不是源码语法。不改变正文语义；完整
    排版正文由详情抽屉呈现，故此处不追求富文本观感。
    """
    lines: list[str] = []
    in_fence = False
    for raw in (md or "").splitlines():
        s = raw.strip()
        if s.startswith("```") or s.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence or not s:
            continue
        s = re.sub(r"^(?:#{1,6}|>|[-*+]|\d+[.)])\s+", "", s)  # 标题/引用/列表标号
        s = _MD_LINK_RE.sub(r"\1", s)                          # 链接 → 文字
        s = _MD_INLINE_RE.sub("", s).strip()                   # 强调/行内代码标记
        if not s or _MD_TABLE_RULE_RE.match(s):                # 表格分隔/装饰行
            continue
        lines.append(s)
        if len(lines) >= max_lines:
            break
    text = " ".join(lines).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text


def _conf_chip(conf: str):
    """W3-05：蒸馏产物质量评分 → 与经验库 G chip 同一套标签（数值不暴露）。"""
    return {"high": chip(t("已验证"), "ok"),
            "medium": chip(t("部分验证"), "warn"),
            "low": chip(t("待验证"), "brand")}.get(conf)


def _display_name(s: dict) -> tuple[str, str]:
    """R1/R4：卡片标题 = 显示名（说人话），副标签 = 项目/类别两级路径（恒显）。"""
    name = s.get("name")
    return (name or f"{s['trunk']} / {s['category']}"), f"{s['trunk']} / {s['category']}"


class MethodsPage(PageBase):
    """我的方法页：方法卡列表（报告/改名/导出 Skill/来源）+ 待总结蒸馏区。"""

    def __init__(self, api: LocalApi, parent: QWidget | None = None,
                 embedded: bool = False):
        super().__init__(api, parent)
        self._embedded = embedded
        self._cards: dict[str, dict] = {}    # 增量 diff：key → {w, sig}
        self._pending: dict[str, dict] = {}  # 待总结区（单卡，按 sig 复用）
        self._drawer: DetailDrawer | None = None
        self._build()

    # ---------- UI ----------

    def _build(self) -> None:
        """构建静态 UI（数据在 refresh 中加载，不在构造函数发请求）。"""
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setSpacing(S.s6)

        # 统一页头（S1）：嵌入「我的经验」容器时走 dense 档（h2）
        self._main_btn = btn_primary(t("导出 Skill"))
        self._main_btn.clicked.connect(lambda: self.go("export"))
        head = page_header(t("我的方法"), dense=self._embedded,
                           actions=[self._main_btn])
        self._title_label = head.findChild(QLabel, "pageTitle")
        cl.addWidget(head)

        self._subtitle_label = txt(
            t("提炼成每次任务自动带上的方法（SKILL.md 格式，可供 Claude Code 等直接使用）"),
            F.caption, color=C.ink_500)
        cl.addWidget(self._subtitle_label)

        # 行内状态行（与主窗口状态行同步显示）
        self._status_local = status_text("", tone="ok")
        cl.addWidget(self._status_local)

        # 方法卡列表（_render_all 增量同步）
        self._cards_lay = QVBoxLayout()
        self._cards_lay.setSpacing(S.s6)
        cl.addLayout(self._cards_lay)

        # 待总结的经验
        self._pending_lay = QVBoxLayout()
        self._pending_lay.setSpacing(S.s2)
        cl.addLayout(self._pending_lay)

        cl.addStretch(1)
        # P1-2 + S2：子页滚动区走统一骨架；嵌入容器时顶部留白归 0
        self._layout.addWidget(page_scaffold(
            cl, top=0 if self._embedded else PAGE_SIDE_PAD))

    def _set_status(self, msg: str, tone: str = "err") -> None:
        """写主窗口状态行 + 本页行内状态行。"""
        self.set_status(msg, tone)
        self._status_local.setText(msg)
        color = {"ok": C.ok_fg, "err": C.err_fg,
                 "warn": C.warn_fg, "info": C.info_fg}[tone]
        status_tone(self._status_local, color)

    # ---------- 数据 ----------

    def refresh(self) -> None:
        """导航到本页时重新加载数据。"""
        self.refresh_all()

    # ---------- 重新翻译 ----------

    def retranslateUi(self) -> None:
        self._title_label.setText(t("我的方法"))
        self._main_btn.setText(t("导出 Skill"))
        self._subtitle_label.setText(t(
            "提炼成每次任务自动带上的方法（SKILL.md 格式，可供 Claude Code 等直接使用）"))

    def refresh_all(self) -> None:
        """切页/轮询刷新：取数整体在工作线程（主线程零 HTTP），渲染回主线程。"""
        self.fetch_and_render(self._fetch_all, self._render_all, "methods",
                              skeleton=[24, 72, 72, 72])

    def _fetch_all(self) -> dict:
        """工作线程：并行取经验 + 方法列表，再并行取各方法正文（不碰任何控件）。"""
        data = parallel_fetch({
            "exp": lambda: self.api.experiences(limit=300),
            "skills": self.api.skills,
        })
        skills = (data.get("skills") or {}).get("items") or []
        bodies: dict[str, str] = {}
        if skills:
            # 正文请求数等于方法卡数量，故按批推进：每批至多 _BODY_BATCH 个，
            # 批内并发 _BODY_WORKERS。这样卡很多时（几十上百张）单批规模可控，
            # 不会一次性把上百个请求全塞进线程池；取数范围不变，正文照样全取。
            for start in range(0, len(skills), _BODY_BATCH):
                batch = skills[start:start + _BODY_BATCH]
                calls = {}
                for i, s in enumerate(batch):
                    tk, cat = s.get("trunk"), s.get("category")
                    calls[f"b{i}"] = (lambda tk=tk, cat=cat:
                                      self.api.read_skill(tk, cat).get("md", ""))
                res = parallel_fetch(calls, max_workers=_BODY_WORKERS)
                for i, s in enumerate(batch):
                    key = f"{s.get('trunk')}\x00{s.get('category')}"
                    v = res.get(f"b{i}")
                    bodies[key] = v if isinstance(v, str) else ""
        data["bodies"] = bodies
        return data

    def _render_all(self, data: dict | None) -> None:
        """渲染回调（主线程）：**不得再发 HTTP**，只按取数结果增量更新两区。"""
        data = data or {}
        exp, skills_res = data.get("exp"), data.get("skills")
        if exp is None and skills_res is None:
            # 取数失败：如实报错，不清空现有卡片（下次轮询自愈）
            self.report_error(t("（读取失败）"))
            return
        pending: dict[tuple[str, str], int] = {}
        for e in (exp or {}).get("items", []):
            if e.get("distilled"):
                continue
            key = (e.get("trunk") or "?", e.get("category") or "?")
            pending[key] = pending.get(key, 0) + 1

        skills = (skills_res or {}).get("items", [])
        bodies = data.get("bodies") or {}
        want: list[tuple[str, str, object]] = []
        for s in skills:
            key = f"{s.get('trunk')}\x00{s.get('category')}"
            md = bodies.get(key, "")
            want.append((key, content_sig([s, md]),
                         lambda s_=s, md_=md: self._skill_card(s_, md_)))
        if not skills:
            # P0-4 每屏主操作唯一：页头已有「导出 Skill」主按钮，空态这里降为次级
            b = btn_secondary(t("导出 Skill"))
            b.clicked.connect(lambda: self.go("export"))
            want.append(("__empty__", "empty", lambda b_=b: empty_state(
                t("暂无方法"),
                t("经验攒够后这里会出现方法，点「总结成方法」即可"),
                button=b_, mascot="think")))
        sync_tracked(self._cards_lay, self._cards, want)
        pend_want: list[tuple[str, str, object]] = []
        if skills:
            pend_want.append(("pending", content_sig(sorted(pending.items())),
                              lambda: self._pending_card(pending)))
        sync_tracked(self._pending_lay, self._pending, pend_want)
        # 首屏错峰入场（"只首屏"在基类 stagger_cards 里一处实现）
        self.stagger_cards(self._cards_lay)

    def _pending_card(self, pending: dict) -> QWidget:
        """待总结区单卡（全部行在卡内；sig 未变时整卡复用不重建）。"""
        if not pending:
            return card(content=txt(t("全部总结完毕"), F.body, color=C.ink_500),
                        title=t("待总结的经验"))
        c = card(title=t("待总结的经验"))
        for (trunk, category), n in sorted(pending.items()):
            c.layout().addWidget(list_row(
                "AUTO_AWESOME_OUTLINED",
                t("{trunk} / {category}：{n} 条", trunk=trunk,
                  category=category, n=n),
                trailing=self._distill_button(trunk, category)))
        return c

    # ---------- 蒸馏 ----------

    def _distill_button(self, trunk: str, category: str) -> QPushButton:
        """待总结行蒸馏按钮（行内轻量操作 → btn_flat）。"""
        btn = btn_flat(t("总结成方法"))
        btn.setFixedHeight(D.BTN_H_XS)
        btn.clicked.connect(lambda _=False, t_=trunk, c_=category:
                            self._distill(btn, t_, c_))
        return btn

    def _distill(self, btn: QPushButton, trunk: str, category: str) -> None:
        """后台调用 api.distill（长超时），成功重建列表。

        无模型 → 门禁拦截（require_model）或引擎回 model_required 结构化拒绝；
        两者都**不产出任何正文**（不做本机兜底）。"""
        if not self.require_model(t("总结成方法")):
            return
        btn.setEnabled(False)
        btn.setText(t("正在总结…"))
        self._set_status(t("正在总结…"), "info")

        def work():
            self.api.distill(trunk, category)

        def on_done(r):
            btn.setText(t("总结成方法"))
            btn.setEnabled(True)
            if self._reject_model_required(r):
                return
            self._set_status(t("总结完成"), "ok")
            self.refresh_all()

        def on_error(err):
            btn.setText(t("总结成方法"))
            btn.setEnabled(True)
            self._set_status(t("总结失败：{err}", err=err))

        self.run_async(work, on_done, on_error)

    def _reject_model_required(self, r) -> bool:
        """引擎返回 ``status == "model_required"`` → 如实告知，不假装已生成。

        返回 True 表示已按拒绝路径处理（调用方不得再显示"已生成/已更新"）。"""
        if not isinstance(r, dict) or r.get("status") != "model_required":
            return False
        msg = str(r.get("message") or t("未接入模型，无法归纳成方法"))
        if r.get("kept_previous"):
            msg = f"{msg} {t('已保留上次内容')}"
        self._set_status(msg, "warn")
        self.toast(msg)
        return True

    def _rebuild(self, btn: QPushButton, trunk: str, category: str) -> None:
        """重建这份方法卡：用该类目**全部**经验重蒸馏（force）。

        为什么单独一个动作：「总结成方法」只处理待总结经验，而一张被写坏的
        空卡其经验早已标为已总结（pending=0）——按原按钮永远修不回来。
        真机就是这么卡住的。"""
        if not self.require_model(t("重建")):
            return
        btn.setEnabled(False)
        btn.setText(t("正在重建…"))
        self._set_status(t("正在用全部经验重建这份方法卡…"), "info")

        def work():
            self.api.distill(trunk, category, force=True)

        def on_done(r):
            btn.setText(t("重建"))
            btn.setEnabled(True)
            if self._reject_model_required(r):
                return
            self._set_status(t("重建完成"), "ok")
            self.refresh_all()

        def on_error(err):
            btn.setText(t("重建"))
            btn.setEnabled(True)
            self._set_status(t("重建失败：{err}", err=err))

        self.run_async(work, on_done, on_error)

    # ---------- 转 Skill（一键类目 → 生成 → 预览 → 保存版本） ----------

    def _to_skill_button(self, trunk: str, category: str) -> QPushButton:
        """「导出 Skill」按钮（行内轻量操作 → btn_flat）。"""
        btn = btn_flat(t("导出 Skill"))
        btn.setFixedHeight(D.BTN_H_XS)
        btn.clicked.connect(lambda _=False, t_=trunk, c_=category:
                            self._to_skill(btn, t_, c_))
        return btn

    def _to_skill(self, btn: QPushButton | None, trunk: str,
                  category: str) -> None:
        """后台生成 SKILL.md → 预览弹层（版本历史/保存都在弹层内）。

        ``btn`` 可为 None（从详情抽屉触发时没有行内按钮）。"""
        def _busy(text: str, enabled: bool) -> None:
            if btn is not None:
                btn.setText(text)
                btn.setEnabled(enabled)

        _busy(t("正在导出 Skill…"), False)

        def work():
            return self.api.skill_generate(trunk=trunk, category=category)

        def on_done(r):
            _busy(t("导出 Skill"), True)
            dlg = skill_preview_dialog(
                self.api, r["md"], r["name"], r["source_count"],
                r.get("description", ""), self)
            dlg.exec()
            dlg.deleteLater()

        def on_error(err):
            _busy(t("导出 Skill"), True)
            self._set_status(t("导出 Skill 失败：{err}", err=err))

        self.run_async(work, on_done, on_error)

    # ---------- 让 AI 重写（整方法重总结：预览 → 采纳才落盘） ----------

    def _ai_rewrite_skill(self, trunk: str, category: str) -> None:
        """该类别全部经验（含已总结）交模型重新总结一份 playbook，
        预览对比后采纳才写盘（rewrite-preview/apply 两段式，旧版留快照可回退）。"""
        if not self.require_model(t("AI 重写")):
            return
        self._set_status(t("正在让 AI 重写…"), "info")

        def work():
            return self.api.skill_rewrite_preview(trunk, category)

        def on_done(r):
            r = r or {}
            if self._reject_model_required(r):
                return
            new_md = str(r.get("md") or "")
            if not new_md:
                self._set_status(t("AI 没有给出可用的重写"))
                return
            ret = md_rewrite_dialog(self, new_md, str(r.get("old_md") or ""))
            if ret == 2:  # REDO
                self._ai_rewrite_skill(trunk, category)
                return
            if ret != QDialog.Accepted:
                self._set_status(t("已保留当前内容"), "info")
                return
            # apply 原同步（15s 超时）跑在 UI 线程——
            # 采纳重写结果时引擎卡住就冻结界面。改后台执行。
            def _apply():
                return self.api.skill_rewrite_apply(trunk, category, new_md)

            def _applied(_r) -> None:
                self._set_status(t("已采纳，内容已更新"), "ok")
                self.refresh_all()

            def _apply_err(e) -> None:
                self._set_status(str(e), "err")

            self.run_async(_apply, _applied, _apply_err)

        def on_error(err):
            self._set_status(t("AI 重写失败：{err}", err=err))

        self.run_async(work, on_done, on_error)

    # ---------- 方法卡 ----------

    def _skill_card(self, s: dict, md: str | None = None) -> QWidget:
        """单张方法卡：显示名 + 置信度 chip + 报告/改名/导出 + 来源 agent + md。

        ``md`` 由取数段（工作线程）带下来；缺省时按旧口径自取一次（仅测试/兼容
        路径用，生产 refresh_all 恒传）。正文在列表只显示纯文本摘录，
        完整富文本正文点标题进详情抽屉看。"""
        from ..distill.engine_curation import playbook_has_body

        trunk, category = s["trunk"], s["category"]
        if md is None:
            try:
                md = self.api.read_skill(trunk, category).get("md", "")
            except LocalApiError:
                md = t("（读取失败）")
        title, sub = _display_name(s)
        conf_chip = self._conf_chip(md)
        src_n = self._src_count(md)

        # 档 2：自绘投影卡片（省逐控件 QGraphicsDropShadowEffect 的 CPU 合成）
        c = ShadowCard()
        hover_lift(c)
        cl = c.layout()

        # 行 1：标题（点标题下钻详情）+ chip + 操作（报告 / 改名 / 导出 Skill）
        r1 = QHBoxLayout()
        r1.setSpacing(S.s2)
        title_lbl = txt(title, F.h2, 600)
        title_lbl.setCursor(Qt.PointingHandCursor)
        title_lbl.setToolTip(t("查看详情"))
        title_lbl.mousePressEvent = (
            lambda _e, s_=s, md_=md: self._open_detail(s_, md_))
        r1.addWidget(title_lbl)
        if conf_chip:
            r1.addWidget(conf_chip)
        r1.addStretch(1)
        report_btn = btn_flat(t("报告"))
        report_btn.setFixedHeight(D.BTN_H_XS)
        report_btn.clicked.connect(
            lambda _=False, t_=trunk, c_=category:
            report_view.open_methodology_report(self.api, t_, c_, self))
        r1.addWidget(report_btn)
        rename_btn = icon_button("DRIVE_FILE_RENAME_OUTLINE_OUTLINED",
                                 t("改名"), color=C.brand_700)
        rename_btn.clicked.connect(
            lambda _=False, t_=trunk, c_=category, nm=s.get("name"):
            self._rename_dialog(t_, c_, nm))
        r1.addWidget(rename_btn)
        rewrite_btn = btn_flat(t("让 AI 重写"))
        rewrite_btn.setFixedHeight(D.BTN_H_XS)
        rewrite_btn.setToolTip(t("用 AI 把这份方法重新总结一遍"))
        rewrite_btn.clicked.connect(
            lambda _=False, t_=trunk, c_=category:
            self._ai_rewrite_skill(t_, c_))
        r1.addWidget(rewrite_btn)
        # 空卡才出现「重建」：健康的方法卡不添按钮，空卡却必须给一条自救路
        # （真机：模型返回空 → 卡被写成三节"（无）"，而「总结成方法」
        # 只处理待总结经验，pending=0 时永远修不回来）
        if not playbook_has_body(md):
            rebuild_btn = btn_flat(t("重建"))
            rebuild_btn.setFixedHeight(D.BTN_H_XS)
            rebuild_btn.setToolTip(
                t("这份方法卡是空的（多半是上次总结没拿到内容）"
                  "——用全部经验重蒸馏一次"))
            rebuild_btn.clicked.connect(
                lambda _=False, b=rebuild_btn, t_=trunk, c_=category:
                self._rebuild(b, t_, c_))
            r1.addWidget(rebuild_btn)
        r1.addWidget(self._to_skill_button(trunk, category))
        r1w = QWidget()
        r1w.setLayout(r1)
        cl.addWidget(r1w)

        # 行 2：副标签 + 来源 agent（后台填充）
        r2 = QHBoxLayout()
        r2.setSpacing(S.s2)
        r2.addWidget(txt(sub, F.caption, color=C.ink_500))
        r2.addStretch(1)
        r2.addWidget(self._agents_line(trunk, category))
        r2w = QWidget()
        r2w.setLayout(r2)
        cl.addWidget(r2w)

        # 溯源条：无模型产出/来源未知的旧内容如实披露，接入后可更新
        pbar = provenance_bar({
            "content_source": s.get("content_source"),
            "generated_at": s.get("generated_at"),
            "has_content": playbook_has_body(md),
        })
        if pbar is not None:
            cl.addWidget(pbar)

        excerpt = _md_excerpt(md)
        if excerpt:
            cl.addWidget(txt(excerpt, F.caption, color=C.ink_700, wrap=True))
        if src_n:
            src_btn = btn_flat(t("来自 {n} 条记录", n=src_n))
            src_btn.clicked.connect(
                lambda _=False, t_=trunk, c_=category, n=src_n:
                self._sources_dialog(t_, c_, n))
            cl.addWidget(src_btn)
        return c

    def _open_detail(self, s: dict, md: str) -> None:
        """点方法卡标题 → 统一下钻抽屉。底部操作槽 = AI 重写 / 导出 Skill。"""
        if self._drawer is None:
            self._drawer = DetailDrawer(self)
        trunk, category = s["trunk"], s["category"]
        title, _sub = _display_name(s)
        payload = {
            "title": title,
            "body": md,
            "timeline": f"{trunk} / {category}",
            "experience_ids": self._src_ids(md),
            "content_source": s.get("content_source"),
            "generated_at": s.get("generated_at"),
        }
        if s.get("content_source") == "none" and self._conf_chip(md) is not None:
            payload["status"] = t("未接入模型")
            payload["status_tone"] = "warn"
        drawer = self._drawer

        def _rewrite_from_drawer() -> None:
            drawer.close_drawer()
            self._ai_rewrite_skill(trunk, category)

        def _export_from_drawer() -> None:
            drawer.close_drawer()
            self._to_skill(None, trunk, category)

        drawer.set_actions([
            btn_flat(t("让 AI 重写"),
                     on_click=lambda _=False: _rewrite_from_drawer()),
            btn_flat(t("导出 Skill"),
                     on_click=lambda _=False: _export_from_drawer()),
        ])
        drawer.open_detail("method", payload)

    @staticmethod
    def _src_ids(md: str) -> list[str]:
        """frontmatter source_exps → 来源经验 id 列表（抽屉来源区用）。"""
        m = re.search(r"^>\s*source_exps:\s*(.+)$", md, re.M)
        if not m:
            return []
        return [x.strip() for x in m.group(1).split(",")
                if x.strip() and x.strip() != "（无）"]

    def _conf_chip(self, md: str):
        """从 frontmatter 读 confidence → 语义 chip（W3-03/05）。"""
        m = re.search(r"^>\s*confidence:\s*(\S+)", md, re.M)
        return _conf_chip(m.group(1) if m else "")

    @staticmethod
    def _src_count(md: str) -> int:
        """从 frontmatter 读来源经验数（下钻入口）。"""
        m = re.search(r"^>\s*source_exps:\s*(.+)$", md, re.M)
        if not m:
            return 0
        ids = [x for x in m.group(1).split(",")
               if x.strip() and x.strip() != "（无）"]
        return len(ids)

    def _agents_line(self, trunk: str, category: str) -> QWidget:
        """R3 来源 agent 行（后台线程填充，失败静默不挡渲染）。"""
        holder = txt("", F.caption, color=C.ink_500)
        holder.hide()

        def work():
            r = self.api.skill_agents(trunk, category)
            parts = [f"{a['agent']} · {t('{n} 次', n=a['count'])}"
                     for a in r.get("agents", [])[:4]]
            if not parts:
                return None
            return t("来源：{agents}", agents=" ｜ ".join(parts))

        def on_done(text):
            if text:
                holder.setText(text)
                holder.show()

        def on_error(err: str) -> None:
            # 失败不再静默——留 _last_error 供诊断 +
            # 状态栏弱提示（不弹窗，保持「失败不挡渲染」：行本身保持隐藏）。
            self.report_error(t("来源 agent 加载失败：{err}", err=err))

        self.run_async(work, on_done, on_error)
        return holder

    # ---------- 改名 / 来源下钻 ----------

    def _rename_dialog(self, trunk: str, category: str,
                       current_name: str | None) -> None:
        """R2 改名：显示名（说人话）+ 可选分类迁移（两个输入框）。"""
        dlg = QDialog(self)
        dlg.setWindowTitle(t("改名这个方法"))
        lay = QVBoxLayout(dlg)
        lay.setSpacing(S.s2)
        lay.addWidget(txt(t("显示名（说人话，如「投标报价核算」）"), F.caption,
                          color=C.ink_500))
        name_edit = QLineEdit(current_name or "")
        name_edit.setPlaceholderText(t("留空 = 保持当前名字"))
        lay.addWidget(name_edit)
        lay.addWidget(txt(t("分类（留空 = 不变）"), F.caption, color=C.ink_500))
        cat_edit = QLineEdit(category)
        lay.addWidget(cat_edit)
        lay.addWidget(txt(
            t("改分类会把方法和它名下的经验一起挪过去；经验库、成长曲线自动跟随"),
            F.caption, color=C.ink_500, wrap=True))
        btn_row = QHBoxLayout()
        btn_row.setSpacing(S.s2)
        btn_row.addWidget(btn_secondary(t("取消"), on_click=dlg.reject))
        btn_row.addStretch(1)
        btn_row.addWidget(btn_primary(t("保存"), on_click=dlg.accept))
        lay.addLayout(btn_row)

        try:
            if dlg.exec() != QDialog.Accepted:
                return
            # 读完输入框再释放：deleteLater 不能早于这里，否则读到的是已删控件
            name = name_edit.text().strip() or None
            new_cat = cat_edit.text().strip() or None
            if name in (None, current_name) and new_cat in (None, category):
                return
            # rename 原同步（15s 超时）跑在 UI 线程——
            # 改名时引擎卡住就冻结界面（且还开着模态框）。改后台执行；
            # name_map 作废放进工作线程收尾（纯内存字典清理，线程安全）。
            def _rename():
                r = self.api.skill_rename(trunk, category, name, new_cat)
                # 改名后作废 name_map（否则整理页/注入预览的
                # 组头仍显旧名，进程内永不过期）。去重 R2：两份缓存已合并为一份。
                from ._name_map import invalidate
                invalidate()
                return r

            def _renamed(r) -> None:
                msg = t("已改名")
                if r.get("stale_overrides"):
                    msg += t("（{n} 条你改过的内容已失效，可到「模型会看到什么」页清理）",
                             n=r["stale_overrides"])
                self._set_status(msg, "ok")
                self.refresh_all()

            def _rename_err(e) -> None:
                self._set_status(str(e), "err")

            self.run_async(_rename, _renamed, _rename_err)
        finally:
            # 模态对话框是局部变量 + exec()，不设 WA_DeleteOnClose（栈对象
            # delete-this 会崩）；读完字段后显式释放，避免每开一次泄漏一棵子树。
            dlg.deleteLater()

    def _sources_dialog(self, trunk: str, category: str, n: int) -> None:
        """W3-04 下钻：方法 → 来源经验(L1) → session 摘要(L0)。"""
        dlg = sources_dialog(self.api, trunk, category, n, self)
        dlg.exec()
        dlg.deleteLater()
