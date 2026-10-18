"""Hooks 页（Qt 版，2026-09 整页重做；方案见《Hooks页重做方案》）。

三段式单轴（用户做事的先后次序 = 页面自上而下）：
- 区一实时捕获：一次性的接入工作——提议横幅 + 工具行（条目行可展开）；
  无提议时安静收起
- 区二我的规则：页面主角——预算条 + 信号行 + 按规则/按工具双视图 + CRUD + 批量
- 区三模板库：进货通道——类目 chip + 四维筛选 + 模板行导入（默认展开）

全页唯一实心橙 = 页头「+ 新增规则」（设计家族每屏一个主操作）。
"Hook"只出现在页头，正文全说人话（规则 / 实时捕获 / 模板）。

模块级公开契约（其他模块 import，勿删）：
- _event_plain：connect_page 复用（事件名→人话映射）
- _PRI_STYLE：export_page 复用（优先级视觉常量）
- _i18n_extract_anchor：pybabel extract 扫描锚点（模板类目/优先级文案键）
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPointF, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor, QIntValidator, QPaintEvent, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from ..proxy.detect import agent_display_name
from . import i18n
from .api_client import LocalApi, LocalApiError
from .i18n import t
from .template_library import _PRI_STYLE, TRIGGER_KEYS, TemplateLibraryMixin  # noqa: F401
from .page_base import (PageBase, clear_layout, content_sig, page_scaffold,
                        parallel_fetch, sync_tracked)
from .qt_dialogs import confirm_dialog
from .qt_theme import (btn_flat, btn_primary, btn_secondary, card, chip,
                       empty_state, icon_widget, mascot_image, seg_button,
                       seg_style, status_text, status_tone, switch, txt)
from .qt_widgets import (DetailDrawer, FlowLayout, RotatingIcon, SelectButton,
                         ShadowCard, hover_lift, page_header)
from .theme import ANIMATION, C, D, F, R, S, SIZES, TONE_BG, TONE_FG, motion_ok

logger = logging.getLogger("experientia.gui.hooks")


def _agent_display(name: str) -> str:
    """内部 agent 名 → 用户友好显示名。未知名称原样返回。

    定义统一在 app.proxy.detect，避免双份定义漂移。"""
    return agent_display_name(name)


def _event_plain(name: str) -> str:
    """Hook 事件名 → 人话说明（用户反馈：PreToolUse 这类太技术、看不懂）。

    逗号分隔的多事件字段逐段映射（如 Hermes 的 "agent:end, session:end"）；
    未知事件名原样返回（保留可溯源性，不藏原始值）。"""
    raw = (name or "").strip()
    if "," in raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return "、".join(_event_plain(p) for p in parts)
    m = {
        "SessionStart": t("开新对话时"),
        "UserPromptSubmit": t("你发消息时"),
        "PostToolUse": t("跑完一条命令后"),
        "Stop": t("AI 答完话时"),
        "PreToolUse": t("要跑一条命令前"),
        "sessionStart": t("开新对话时"),
        "afterAgentResponse": t("AI 回复后"),
        "stop": t("AI 停下的时候"),
        "post_cascade_response_with_transcript": t("AI 回复后"),
        "agent:end": t("AI 回复后"),
        "session:end": t("一轮结束时"),
    }
    return m.get(raw, raw)


def _elide(text: str, limit: int = 72) -> str:
    """长命令/路径 → 压成一行截断显示（全文在 tooltip 与"查看命令"里，不甩字墙）。"""
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _our_purpose(event: str) -> str:
    """Experientia 自注入条目按事件写各自的分工（差异化；条条一个样 = 白解释）。

    未知事件回退空串（调用方落到通用句）。"""
    m = {
        "SessionStart": t("开始记录这次任务"),
        "UserPromptSubmit": t("把用得上的经验自动提给 AI 参考"),
        "PostToolUse": t("AI 每做完一步，记下这步的效果"),
        "Stop": t("一轮做完，自动复盘、写成经验"),
        "sessionStart": t("开始记录这次任务"),
        "afterAgentResponse": t("记下这轮对话"),
        "stop": t("一轮做完，自动复盘、写成经验"),
        "post_cascade_response_with_transcript": t("记下这轮对话"),
    }
    return m.get(event, "")


def _i18n_extract_anchor() -> None:  # pragma: no cover — 仅供 pybabel extract 扫描
    """pybabel extract 锚点：模板类目/优先级文案键以 t() 字面量出现一次。

    这些 key 在注册表/上方常量里是数据，extract 扫不到变量引用——曾导致
    6 个类目名在全部语言包缺失（切语言后仍显示中文）。勿删。"""
    for key in ("架构与设计", "代码风格与格式", "测试与验证", "文档与沟通",
                "安全与合规", "工作流与流程", "P0 红线", "P1 必须",
                "P2 应该", "P3 建议", "P4 优化"):
        t(key)


TRIGGER_KEYS = ("smart", "always", "manual", "hard-hook")  # file 已废弃（W4：manual + 关键词）

# 工具名（生态词，如 claude-code）不进 i18n（口径，与接入页一致）


def _trigger_labels() -> dict:
    return {
        "always": t("一直生效"),
        "smart": t("AI 判断相关时"),
        "manual": t("我提及时才用"),
        "hard-hook": t("每次必须发生，绕不过去"),
    }


class _DotsButton(QWidget):
    """⋯ 溢出按钮：三点用矢量自绘，不依赖任何字体回退。

    用户反馈"⋯ 看不见"——Unicode "⋯"（U+22EF）与 MDI dots 字形在全局字体栈
    首选 Manrope（拉丁）下回退不可靠：离屏/部分系统不落到 YaHei/符号字体，
    点会整个消失（按钮只剩空框）。直接画三个实心圆，任何平台都稳定可见。
    surface 底 + 描边 + 圆角 = "可见但安静"，不抢橙色主角；点击开菜单。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hooksDotsButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(D.ICON_BOX, D.ICON_BOX)

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(C.line), 1))
        p.setBrush(QColor(C.surface_2))
        p.drawRoundedRect(r, R.sm, R.sm)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C.ink_700))
        cy = self.height() / 2
        rad, gap = 2.3, 6.5
        for dx in (-gap, 0.0, gap):
            p.drawEllipse(QPointF(self.width() / 2 + dx, cy), rad, rad)
        p.end()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class HooksPage(TemplateLibraryMixin, PageBase):
    """Hooks 页：三段式（实时捕获 / 我的规则 / 模板库）+ 按规则/按工具双视图。

    数据在 refresh() 加载（失败兜底空数据）；_build() 只搭静态骨架。
    """

    def __init__(self, api: LocalApi, parent: QWidget | None = None):
        super().__init__(api, parent)
        self._trigger_labels = _trigger_labels()
        self._selected: set[str] = set()
        self._rules_cache: list[dict] = []
        self._agents_cache: list[str] = []
        self._tpl_holder: list[dict] = []
        self._cat_state: list[int] = [0]
        self._f_state: dict = {"pri": "all", "tag": "all", "q": ""}
        self._view_state = "rules"
        self._tool_state: dict = {"agent": ""}
        self._stale_loaded = False
        self._templates_loaded = False
        self._stale_days_val = 30
        self._hooks_warn = False
        self._hooks_offer = False
        self._model_ok = False
        # 区一：工具行展开态（agent → 是否展开条目行）。默认全收起（可扩展），
        # 用户展开选择持久化到 config（hooks_agents_expanded），跨重启记住。
        self._agent_expanded: set[str] = set()
        self._expanded_loaded = False
        self._agent_row_bodies: dict[str, QWidget] = {}
        self._agent_row_icons: dict[str, RotatingIcon] = {}
        self._agent_animations: dict = {}
        # 区一增量 diff：agent → {w, sig, kind} 行引用 / 不变即不重建
        self._live_rows: dict[str, dict] = {}
        self._chip_sig: str = ""
        self._banner_sig: str | None = None
        self._entry_ai_blocks: dict[str, list[QLabel]] = {}
        self._agents_ov_cache: dict = {}
        self._live_open = True
        self._tpl_open = True  # 模板库默认展开（空态主出口，重做方案 D8）
        self._stale_open = False
        self._build()

    # ---------- 页面骨架 ----------

    def _build(self) -> None:
        # 规则列表增量渲染账本：按规则 id 原地复用，数据不变不重建
        self._rule_tracked: dict = {}
        cl = QVBoxLayout()
        cl.setSpacing(S.s6)
        cl.addWidget(self._build_header())
        cl.addWidget(self._build_live_section())
        cl.addWidget(self._build_rules_section())
        self._tpl_card_ref = self._build_tpl_section()
        cl.addWidget(self._tpl_card_ref)
        cl.addStretch(1)
        # S2：统一骨架（顶边 32px 由页头给）
        scroll = page_scaffold(cl, top=0)
        self._page_scroll = scroll
        self._layout.addWidget(scroll)

    def _build_header(self) -> QWidget:
        """统一页头（S1）：吉祥物 + 标题 + 副题 + 唯一主按钮。

        副题沿用**原有那一个** t() 键（隐式拼接成的单串），不新增文案键
        ——locales 目录冻结，每个 t() 键必须在全部 catalog 存在。
        副作用（有意统一）：副题字号由 `F.body`(14) 归到全站页头副标题口径
        `F.caption`(12)。
        """
        self._add_btn = btn_primary(t("+ 新增规则（Hook）"))
        self._add_btn.clicked.connect(lambda: self._rule_dialog(None))
        box = page_header(
            t("我的 Hooks"),
            t("工具触发这些事件时，会自动捕获进你的经验库。规则是你额外加上的："
              "告诉 AI 该怎么做、绝不能怎么做。"),
            actions=[self._add_btn], mascot="smile")
        self._heading_txt = box.findChild(QLabel, "pageTitle")
        self._what_is_hook = box.findChild(QLabel, "pageSubtitle")
        # 页头吉祥物（page_header 给了 objectName="pageMascot"）：_update_mascot
        # 按警示/空态换表情。此前漏取引用 → _update_mascot 抛 AttributeError，
        # 令 _render_all 每次都在最后一步中断、_content_ready 永不置真（页面被当成
        # "永远没加载过"，每次打开都重放骨架屏=看着像空白）。
        self._hooks_mascot = box.findChild(QLabel, "pageMascot")
        return box

    # ---------- 区一 · 实时捕获 ----------

    def _build_live_section(self) -> QFrame:
        c = card()
        lay = c.layout()
        # 卡头：图标 + 标题 + 副题 + 状态 chip + 展开箭头
        hdr = QHBoxLayout()
        hdr.setSpacing(S.s2)
        hdr.addWidget(icon_widget("NOTIFICATIONS_ACTIVE_OUTLINED", 20, C.brand_700))
        self._live_title = txt(t("工具的 Hook"), F.h2, 600)
        hdr.addWidget(self._live_title)
        self._live_sub = txt(
            t("工具触发事件时跑的命令，含它们原本就有的和 Experientia 添加的；"
              "可逐条开关、编辑、删除、AI 解释，也能新增一条。"),
            F.caption, color=C.ink_500, wrap=True)
        hdr.addWidget(self._live_sub, 1)
        self._live_chip_host = QWidget()
        self._live_chip_lay = QHBoxLayout(self._live_chip_host)
        self._live_chip_lay.setContentsMargins(0, 0, 0, 0)
        self._live_chip_lay.setSpacing(S.s1)
        hdr.addWidget(self._live_chip_host)
        self._live_caret = QPushButton("▾")
        self._live_caret.setCursor(Qt.PointingHandCursor)
        self._live_caret.setFixedSize(D.ICON_BOX, D.ICON_BOX)
        self._live_caret.setStyleSheet(
            f"QPushButton {{ color: {C.ink_500}; border: none; "
            f"background: transparent; font-size: {F.body}px; }}"
            f" QPushButton:hover {{ color: {C.ink_700}; }}")
        self._live_caret.clicked.connect(self._toggle_live)
        hdr.addWidget(self._live_caret, 0, Qt.AlignVCenter)
        hdr_w = QWidget()
        hdr_w.setLayout(hdr)
        lay.addWidget(hdr_w)
        # 提议横幅（有可写且未接入的工具才出现）
        self._banner_box = QWidget()
        self._banner_box.setObjectName("hooksBannerBox")
        self._banner_lay = QHBoxLayout(self._banner_box)
        self._banner_lay.setContentsMargins(S.s3, S.s2, S.s3, S.s2)
        self._banner_lay.setSpacing(S.s2)
        # #id 限定：裸 QWidget{} 会级联到子按钮（护栏第 3 条）
        self._banner_box.setStyleSheet(
            f"QWidget#hooksBannerBox {{ background: {C.brand_50}; border: none; "
            f"border-radius: {R.md}px; }}")
        lay.addWidget(self._banner_box)
        # 工具行列表（refresh 重建）
        self._live_list_box = QWidget()
        self._live_list_lay = QVBoxLayout(self._live_list_box)
        self._live_list_lay.setContentsMargins(0, 0, 0, 0)
        self._live_list_lay.setSpacing(S.s2)
        lay.addWidget(self._live_list_box)
        # 卡尾弱链（有已接入工具才出现）
        self._all_remove_btn = btn_flat(t("全部移除 Experientia 添加的"))
        self._all_remove_btn.clicked.connect(self._agents_all_remove)
        self._all_remove_btn.setVisible(False)
        lay.addWidget(self._all_remove_btn, 0, Qt.AlignLeft)
        return c

    def _toggle_live(self) -> None:
        self._live_open = not self._live_open
        self._live_caret.setText("▾" if self._live_open else "▸")
        self._banner_box.setVisible(self._live_open and self._hooks_offer)
        self._live_list_box.setVisible(self._live_open)
        self._all_remove_btn.setVisible(self._live_open
                                        and any(
                                            isinstance(v, dict)
                                            and v.get("installed")
                                            for v in self._agents_overview().values()))

    def _agents_overview(self) -> dict:
        return getattr(self, "_agents_ov_cache", {}) or {}

    def refresh_live(self) -> None:
        """区一刷新：overview 一次全量（内置表 ∪ skill 自报 ∪ 本机检测在跑）。

        动作收尾后的就地重刷仍走同步单请求（用户等待反馈，且写后缓存已失效）；
        页面导航整刷由 _fetch/_render_all 在后台线程完成。"""
        try:
            overview = self.api.hooks_admin_overview()
        except LocalApiError:
            overview = None
        try:
            models = self.api.models()
        except LocalApiError:
            models = None
        self._render_live(overview, models)

    def _render_live(self, overview, models) -> None:
        self._agents_ov_cache = overview if isinstance(overview, dict) else {}
        # LLM 辅助解释口子：备注是否已接模型（接了"可用"，没接"接了就有"）
        self._model_ok = bool(models.get("routes")) if isinstance(models, dict) else False
        installed_n = sum(1 for v in self._agents_ov_cache.values()
                          if isinstance(v, dict) and v.get("installed"))
        known = ("hermes", "cursor", "windsurf", "claude-code")
        # 内置表在前，自报发现的表外新 agent（如 workbuddy/codex）按名排序在后
        order = [a for a in known if a in self._agents_ov_cache] + sorted(
            a for a in self._agents_ov_cache if a not in known)
        wanted, offerable = [], []
        for agent in order:
            info = self._agents_ov_cache.get(agent)
            if not isinstance(info, dict):
                continue
            if not info.get("exists"):
                wanted.append((agent, "plain", self._plain_msg(agent, info)))
                continue
            wanted.append((agent, "row", info))
            if (agent in known and agent != "claude-code"
                    and not info.get("installed") and info.get("writable")):
                offerable.append(agent)
        self._sync_live_rows(wanted)
        self._hooks_offer = bool(offerable)
        self._sync_banner(offerable)
        self._sync_chips(installed_n)
        self._banner_box.setVisible(self._live_open and self._hooks_offer)
        self._live_list_box.setVisible(self._live_open)
        self._all_remove_btn.setVisible(self._live_open and installed_n > 0)

    # ---------- 区一增量 diff ----------
    # 30s 轮询整删整建全部工具行：用户的展开态/箭头动画被无谓打断，
    # widget 树全量重建。样板 = 经验库「不采纳」的手术式移除——
    # 按 agent 持行引用，数据没变的行原地不动，只删/只建/只移变化项。

    @staticmethod
    def _row_sig(kind: str, payload) -> str:
        import json as _json
        try:
            return _json.dumps(payload, sort_keys=True, ensure_ascii=False,
                               default=str)
        except (TypeError, ValueError):
            return repr(payload)

    def _plain_msg(self, agent: str, info: dict) -> str:
        return (f"{_agent_display(agent)}：" +
                (t("检测到在跑，未发现 Hook 配置") if info.get("kind") == "none"
                 else t("未检测到该工具的 Hook 配置")))

    def _drop_row_refs(self, agent: str) -> None:
        self._agent_row_bodies.pop(agent, None)
        self._agent_row_icons.pop(agent, None)
        old = self._agent_animations.pop(agent, None)
        if old is not None:
            old.stop()
        self._live_rows.pop(agent, None)

    def _set_row_body(self, container: QWidget, agent: str, info: dict) -> None:
        """复用行容器，原地重建内部条目/箭头/开关（保留容器与列表槽位）。"""
        v = container.layout()
        while v.count():
            it = v.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        self._agent_row_icons.pop(agent, None)
        old = self._agent_animations.pop(agent, None)
        if old is not None:
            old.stop()
        self._agent_row(agent, info, v)

    def _sync_live_rows(self, wanted: list[tuple[str, str, object]]) -> None:
        lay = self._live_list_lay
        want_map = {a: (k, p) for a, k, p in wanted}

        for agent in list(self._live_rows):
            if agent in want_map:
                continue
            entry = self._live_rows.pop(agent)
            for i in range(lay.count()):
                if lay.itemAt(i).widget() is entry["w"]:
                    lay.takeAt(i)
                    break
            entry["w"].deleteLater()
            self._drop_row_refs(agent)

        for agent, kind, payload in wanted:
            sig = self._row_sig(kind, payload)
            entry = self._live_rows.get(agent)
            if entry is not None and entry["sig"] == sig:
                continue
            if entry is None:
                if kind == "plain":
                    w = self._live_plain_line(str(payload))
                else:
                    w = QWidget()
                    vl = QVBoxLayout(w)
                    vl.setContentsMargins(0, 0, 0, 0)
                    vl.setSpacing(0)
                    self._agent_row(agent, payload, vl)
                lay.addWidget(w)
                self._live_rows[agent] = {"w": w, "sig": sig, "kind": kind}
            else:
                if kind != entry["kind"]:
                    # plain ↔ 完整行互换 = 结构变了，整行重建（罕见分支）
                    for i in range(lay.count()):
                        if lay.itemAt(i).widget() is entry["w"]:
                            lay.takeAt(i)
                            break
                    entry["w"].deleteLater()
                    self._drop_row_refs(agent)
                    if kind == "plain":
                        w = self._live_plain_line(str(payload))
                    else:
                        w = QWidget()
                        vl = QVBoxLayout(w)
                        vl.setContentsMargins(0, 0, 0, 0)
                        vl.setSpacing(0)
                        self._agent_row(agent, payload, vl)
                    lay.addWidget(w)
                    self._live_rows[agent] = {"w": w, "sig": sig,
                                              "kind": kind}
                else:
                    if kind == "plain":
                        entry["w"].layout().itemAt(0).widget().setText(
                            str(payload))
                    else:
                        self._set_row_body(entry["w"], agent, payload)
                    entry["sig"] = sig
                    entry["kind"] = kind

        # 按目标顺序归位：takeAt 摘出再 insertWidget（re-parent，不销毁）
        for i, (agent, _kind, _p) in enumerate(wanted):
            entry = self._live_rows.get(agent)
            if entry is None:
                continue
            cur = lay.indexOf(entry["w"])
            if cur != i:
                if cur >= 0:
                    lay.takeAt(cur)
                lay.insertWidget(i, entry["w"])

    def _sync_chips(self, installed_n: int) -> None:
        label = t("已接入 {n} 个", n=installed_n) if installed_n else ""
        if label == self._chip_sig:
            return
        self._chip_sig = label
        clear_layout(self._live_chip_lay)
        if label:
            self._live_chip_lay.addWidget(chip(label, "ok"))

    def _sync_banner(self, offerable: list[str]) -> None:
        sig = ",".join(offerable)
        if sig == self._banner_sig:
            return
        self._banner_sig = sig
        clear_layout(self._banner_lay)
        if offerable:
            self._render_banner(offerable)

    def _live_plain_line(self, text: str) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(S.s3, S.s1, S.s3, S.s1)
        lay.addWidget(txt(text, F.caption, color=C.ink_500))
        return w

    def _render_banner(self, agents: list[str]) -> None:
        """检测到可写且未接入的 agent → 一条横幅，一键全部接入（不弹一堆确认框）。

        重做方案 D4：横幅按钮降为次按钮——全页唯一实心橙留在页头。"""
        lay = self._banner_lay
        names = ", ".join(_agent_display(a) or a for a in agents)
        lay.addWidget(icon_widget("NOTIFICATIONS_ACTIVE_OUTLINED", 18, C.brand_700))
        lay.addWidget(txt(t("发现 {n} 个工具可以接入：{names}",
                            n=len(agents), names=names),
                          F.body, 600, C.ink_900))
        lay.addStretch(1)
        b = btn_secondary(t("全部接入"))
        b.setFixedHeight(D.BTN_H_SM)
        b.clicked.connect(self._agents_all_install)
        lay.addWidget(b)

    def _agent_row(self, agent: str, info: dict,
                   v: QVBoxLayout | None = None) -> QWidget | None:
        """工具行 = 可折叠分区头（整行可点，默认收起，展开态持久化到 config）。

        结构（重做方案 v2）：
        [名字 600] [状态注记 caption] [条目数 caption] ……stretch [接入/switch] [+新增] [chevron]
        点击整行展开/收起：该工具配置文件里的全部 hook 条目行（含用户自己的）。
        按钮/开关各自消费点击，不会误触折叠。
        v 传入既有布局 = 原地重建行内容（M15 增量刷新复用行容器），返回 None。"""
        entries = info.get("entries") or []
        installed = bool(info.get("installed"))
        readonly = info.get("kind") in ("toml", "unknown")
        box = None
        if v is None:
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(S.s2)
        name_t = txt(_agent_display(agent) or agent, F.body, 600, C.ink_900)
        if info.get("path"):
            name_t.setToolTip(str(info.get("path")))
        head.addWidget(name_t)
        # 状态注记（caption，替代现状"按钮+灰字"混杂）
        if agent == "claude-code":
            note, note_color = t("接入开关在「接入」页"), C.ink_500
        elif installed:
            note, note_color = t("已接入"), C.ok_fg
        elif readonly:
            note, note_color = t("只可查看"), C.ink_500
        else:
            note, note_color = t("未接入"), C.ink_500
        head.addWidget(txt(note, F.caption, color=note_color))
        if entries:
            head.addWidget(txt(t("{n} 条提醒规则", n=len(entries)),
                               F.caption, color=C.ink_500))
        head.addStretch(1)
        # 行尾控件
        if agent in ("hermes", "cursor", "windsurf") and not readonly:
            if installed:
                sw = switch(checked=True)
                sw.toggled.connect(
                    lambda on, a=agent: self._agents_toggle_ours(a, on))
                head.addWidget(sw, 0, Qt.AlignVCenter)
            else:
                b = btn_secondary(t("接入"))
                b.setFixedHeight(D.BTN_H_XS)
                b.clicked.connect(
                    lambda _=False, a=agent: self._agents_toggle_ours(a, True))
                head.addWidget(b, 0, Qt.AlignVCenter)
        # + 新增：可写工具（JSON 系 + 目录型 hook_dir，如 hermes）；只读（toml/unknown）不显示
        if info.get("kind") in ("json", "code"):
            add_b = btn_flat(t("+ 新增"))
            add_b.setToolTip(t("给这个工具加一条自定义提醒规则"))
            add_b.clicked.connect(lambda _=False, a=agent: self._entry_add(a))
            head.addWidget(add_b, 0, Qt.AlignVCenter)
        # 折叠箭头（RotatingIcon chevron；整行可点，箭头随展开态旋转 180°）
        icon = RotatingIcon("EXPAND_MORE_OUTLINED", 18, C.ink_500)
        if agent in self._agent_expanded:
            icon.setRotation(180)
        head.addWidget(icon, 0, Qt.AlignVCenter)
        self._agent_row_icons[agent] = icon
        # 整行作折叠头：hover 暖底 + 手型光标 + 点击切换展开（按钮/开关各自消费点击）
        head_w = QWidget()
        head_w.setObjectName("hooksAgentHead")
        head_w.setAttribute(Qt.WA_Hover, True)
        head_w.setCursor(Qt.PointingHandCursor)
        head_w.setStyleSheet(
            f"QWidget#hooksAgentHead {{ border-radius: {R.sm}px; }}"
            f"QWidget#hooksAgentHead:hover {{ background: {C.surface_2}; }}")
        head_w.mousePressEvent = lambda e, a=agent: self._toggle_agent(a)
        head_w.setLayout(head)
        v.addWidget(head_w)
        # 条目组容器（展开时可见）：左缩进 + 左缘 2px 浅竖线表达分组归属（V4：
        # 不用嵌套 card，避免"盒中盒"；工具=分组头、条目=缩进组）。
        body = QWidget()
        body.setObjectName("hooksEntryGroup")
        body.setStyleSheet(
            f"QWidget#hooksEntryGroup {{ border-left: 2px solid {C.line}; }}")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(S.s4, S.s1, S.s2, S.s1)
        bl.setSpacing(S.s2)
        self._render_agent_entries(agent, info, bl)
        body.setVisible(agent in self._agent_expanded)
        v.addWidget(body)
        self._agent_row_bodies[agent] = body
        return box

    def _toggle_agent(self, agent: str) -> None:
        if agent in self._agent_expanded:
            self._agent_expanded.discard(agent)
        else:
            self._agent_expanded.add(agent)
        body = self._agent_row_bodies.get(agent)
        if body is not None:
            body.setVisible(agent in self._agent_expanded)
        self._animate_agent_icon(agent)
        self._save_expanded()

    def _animate_agent_icon(self, agent: str) -> None:
        """折叠箭头旋转（chevron-down 转 180° 即展开态）；reduced-motion 直落目标角。"""
        icon = self._agent_row_icons.get(agent)
        if icon is None:
            return
        target = 180 if agent in self._agent_expanded else 0
        if not motion_ok():
            icon.setRotation(target)
            return
        old = self._agent_animations.get(agent)
        if old is not None:
            old.stop()
        anim = QPropertyAnimation(icon, b"rotation", icon)  # 随 icon 删除自动回收
        anim.setDuration(int(ANIMATION.DURATION_NORMAL * 1000))
        anim.setStartValue(icon.rotation)
        anim.setEndValue(target)
        anim.start()
        self._agent_animations[agent] = anim

    def _save_expanded(self) -> None:
        """展开态持久化到 config（跨重启记住哪些工具展开着）。"""
        try:
            self.api.update_config(
                {"hooks_agents_expanded": sorted(self._agent_expanded)})
        except LocalApiError as exc:
            # 持久化失败留痕——静默时用户以为展开态
            # 已记住，重启后"丢了"且无从排查（SYS-5）。
            logger.warning("展开态持久化失败: %s", exc.detail)
            self.set_status(t("展开状态保存失败：{err}", err=exc.localized()), "warn")

    def _render_expanded(self, cfg) -> None:
        """首刷时应用一次持久化的展开态（默认全收起，只有用户展开过的才展开）。
        cfg 来自后台取数；None（引擎未连）本轮跳过，下次整刷重试。"""
        if self._expanded_loaded:
            return
        raw = (cfg or {}).get("hooks_agents_expanded") or []
        self._expanded_loaded = True
        if isinstance(raw, list):
            self._agent_expanded = {str(a) for a in raw}

    def _render_agent_entries(self, agent: str, info: dict,
                              lay: QVBoxLayout) -> None:
        """条目行：来源点 + 人话一句 + 开关（可写）+ 醒目 ⋯（按 kind 分级动作）。"""
        kind = str(info.get("kind") or "")
        clear_layout(lay)
        for e in (info.get("entries") or []):
            lay.addWidget(self._entry_row(agent, e, kind))

    @staticmethod
    def _source_dot(origin: str, enabled: bool) -> QLabel:
        """来源点（V3：替代橙色 chip）：8px 圆点，Experientia 注入=品牌橙、原本就有=中性灰。

        停用降透明；tooltip 说明来源（不加字，克制）。"""
        is_ours = origin == "experientia"
        color = C.brand_500 if is_ours else C.ink_300
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            f"QLabel {{ background: {color}; border: none; border-radius: 4px; "
            f"opacity: {'1' if enabled else '0.4'}; }}")
        dot.setToolTip(t("Experientia 添加的") if is_ours else t("原本就有"))
        return dot

    def _entry_row(self, agent: str, e: dict, kind: str) -> QWidget:
        """条目行：[来源点] "什么时候 · 做什么"（人话一句）…stretch… [开关] [⋯]。

        - 命令退出行内（V1）：全文在 tooltip 与「编辑」弹窗里，想看才看。
        - 来源点替代橙 chip（V3）：一个 8px 点，不是一块橙底。
        - 操作分级（V2）：开关（状态）留行内；动作收 ⋯，且 ⋯ 按 kind 给能力——
          json=编辑+删除+AI 解释；目录型(code，如 hermes)=删除+AI 解释（handler 是
          Python，命令改不了，不给编辑）；只读(toml/unknown)=查看命令+AI 解释。"""
        enabled = bool(e.get("enabled"))
        raw_ev = str(e.get("event") or "")
        raw_cmd = str(e.get("command") or "")
        readonly = kind in ("toml", "unknown")
        can_edit = (kind == "json")           # 目录型 handler 是 Python，命令不可改
        can_write = kind in ("json", "code")  # 开关 + 删除（目录型也支持）
        row = QHBoxLayout()
        row.setSpacing(S.s2)
        row.addWidget(self._source_dot(e.get("origin"), enabled), 0, Qt.AlignVCenter)
        # 人话一句：什么时候（事件白话）· 做什么（分工说明，仅 Experientia 条目有）
        when = _event_plain(raw_ev) or raw_ev
        purpose = (_our_purpose(raw_ev) if e.get("origin") == "experientia" else "")
        human = f"{when} · {purpose}" if purpose else when
        human_txt = txt(human, F.body, 400,
                        C.ink_500 if not enabled else C.ink_700)
        human_txt.setToolTip(f"{raw_ev}\n{raw_cmd}" if raw_cmd else raw_ev)
        row.addWidget(human_txt, 1)
        if can_write:
            sw = switch(checked=enabled)
            sw.toggled.connect(
                lambda on, a=agent, i=e["id"]: self._entry_toggle(a, i, on))
            row.addWidget(sw, 0, Qt.AlignVCenter)
        # 动作收 ⋯：按 kind 给能力（见 docstring；目录型不给编辑）
        menu_items: list[tuple[str, object]] = []
        if readonly:
            menu_items.append((t("查看命令"),
                               lambda a=agent, i=e["id"]:
                               self._entry_edit(a, i, readonly=True)))
        if can_edit:
            menu_items.append((t("编辑"),
                               lambda a=agent, i=e["id"]: self._entry_edit(a, i)))
        if can_write:
            menu_items.append((t("删除这条 Hook"),
                               lambda a=agent, i=e["id"]: self._entry_delete(a, i)))
        menu_items.append((t("AI 解释"),
                           lambda a=agent, i=e["id"]:
                           self._entry_explain(a, i, None, None)))
        row.addWidget(self._more_button(menu_items), 0, Qt.AlignVCenter)
        # AI 解释结果块：条目行下方的全宽块（换行高度安全）
        ai = txt("", F.body, color=C.ink_700)
        ai.setWordWrap(True)
        ai.setVisible(False)
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(1)
        row_w = QWidget()
        row_w.setLayout(row)
        outer.addWidget(row_w)
        outer.addWidget(ai)
        self._entry_ai_blocks.setdefault(e["id"], []).append(ai)
        return w

    # ---------- 区一操作 ----------

    def _agents_toggle_ours(self, agent: str, on: bool) -> None:
        try:
            if on:
                self.api.hooks_admin_install(agent)
            else:
                self.api.hooks_admin_remove(agent)
        except LocalApiError as exc:
            self._set_status(str(exc))
            return
        self._set_status(t("已更新"), tone="ok")
        self.refresh_live()

    def _agents_all_install(self) -> None:
        self._agents_all(True)

    def _agents_all_remove(self) -> None:
        self._agents_all(False)

    def _hooks_write(self, work, on_ok, buttons=()) -> None:
        """Hooks 写操作统一入口：HTTP 挪后台线程。

        旧实现全部同步跑在 UI 线程（api_client 侧 timeout=60s）——引擎无响应时
        点一次"全部接入"冻结整窗 60s，Windows 直接弹"无响应"。同类操作在主窗
        已改 ApiWorker，Hooks 页这份漏改。现在统一：写请求进后台线程、
        触发按钮置灰 + 忙态闸（防重复提交），完成回主线程落 on_ok。

        词条全部复用既有键（"正在处理…"等），不新增 i18n 键——test_i18n 的
        "每个 t() 键必须全语种收录"守卫会让新键直接 CI 红。
        """
        if getattr(self, "_hooks_busy", False):
            return
        self._hooks_busy = True
        btns = [b for b in buttons if b is not None]
        for b in btns:
            try:
                b.setEnabled(False)
            except RuntimeError:
                pass  # 控件已销毁（页面刚被重建），无需置灰
        self._set_status(t("正在处理…"), "info")

        def _restore() -> None:
            self._hooks_busy = False
            for b in btns:
                try:
                    b.setEnabled(True)
                except RuntimeError:
                    pass

        def done(r) -> None:
            _restore()
            on_ok(r)

        def err(e) -> None:
            _restore()
            # 错误文本沿用旧口径（str(exc)），不造新词条
            self._set_status(str(e), "err")

        self.run_async(work, done, err)

    def _agents_all(self, on: bool) -> None:
        # confirm_dialog（主题化中文按钮）；不再用裸 QMessageBox
        if not confirm_dialog(
                t("全部接入 Experientia") if on else t("全部移除 Experientia"),
                t("对已检测到的工具全部接入 Experientia Hook？") if on
                else t("移除已接入的全部 Experientia Hook？（原有 Hook 不动）"),
                self):
            return

        def work():
            return (self.api.hooks_admin_install_all if on
                    else self.api.hooks_admin_remove_all)()

        def on_ok(r) -> None:
            fail = [k for k, v in (r or {}).items() if not v.get("ok")]
            self._set_status(t("已更新") if not fail else t("部分失败"),
                             tone="ok" if not fail else "warn")
            self.refresh_live()

        self._hooks_write(work, on_ok, [self._all_remove_btn])

    def _entry_toggle(self, agent: str, entry_id: str, enabled: bool) -> None:
        def work():
            self.api.hooks_admin_toggle(agent, entry_id, enabled)

        def on_ok(_r) -> None:
            self.refresh_live()

        self._hooks_write(work, on_ok)

    def _entry_explain(self, agent: str, entry_id: str, ai_label: QLabel,
                       btn: QPushButton | None) -> None:
        """LLM 辅助解释（可选项，用户主动触发）：后台线程调模型，不冻结 UI。

        静态人话字典是兜底（没接模型也照常显示）；「AI 解释」本身依赖模型，
        前端统一走 require_model 门禁（生成类入口同口径）。"""
        if not self.require_model(t("AI 解释")):
            return
        if btn is not None:
            btn.setEnabled(False)
            btn.setText(t("正在分析…"))
        self._set_status(t("AI 正在分析这条规则…（本地模型可能要 1–2 分钟）"), "info")

        def on_done(r):
            if btn is not None:
                btn.setEnabled(True)
                btn.setText(t("AI 解释"))
            text = str((r or {}).get("text") or "").strip()
            if text:
                for lbl in self._entry_ai_blocks.get(entry_id, []):
                    lbl.setText(t("AI 解释：{text}", text=text))
                    lbl.setVisible(True)
                self._set_status(t("AI 解释完成"), "ok")
            else:
                self._set_status(t("AI 没返回内容，再试一次"), "warn")

        def on_error(err):
            if btn is not None:
                btn.setEnabled(True)
                btn.setText(t("AI 解释"))
            msg = str(err)
            if "未接入模型" in msg:
                self._set_status(
                    t("还没接入模型：去「接入」页接一个，AI 就能帮你把规则"
                      "翻译成大白话"), "info")
            else:
                self._set_status(t("AI 解释失败：{msg}", msg=msg), "warn")

        self.run_async(lambda: self.api.hooks_admin_explain(agent, entry_id),
                       on_done, on_error)

    def _entry_edit(self, agent: str, entry_id: str, readonly: bool = False) -> None:
        """查看/编辑某条 Hook 的命令（后端字段白名单，仅 JSON 系可写）。"""
        cur = ""
        try:
            for e in (self.api.hooks_admin(agent).get("entries") or []):
                if e.get("id") == entry_id:
                    cur = e.get("command") or ""
        except LocalApiError:
            pass
        dlg = QDialog(self)
        dlg.setWindowTitle(t("Hook 命令") if readonly else t("编辑 Hook 命令"))
        dlg.setMinimumWidth(SIZES.CONTENT_FORM)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(S.s2)
        hint = txt(
            t("此工具的命令只能看，改不了") if readonly else
            t("只改它执行什么；什么时候触发由「事件」决定，这里改不了"),
            F.caption, color=C.ink_500)
        hint.setWordWrap(True)
        lay.addWidget(hint)
        ta = QPlainTextEdit(cur)
        ta.setReadOnly(readonly)
        ta.setMinimumHeight(D.TEXTAREA_H_SM)
        lay.addWidget(ta)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_b = btn_secondary(t("关闭") if readonly else t("取消"))
        close_b.clicked.connect(dlg.reject)
        btn_row.addWidget(close_b)
        if not readonly:
            def _save() -> None:
                new_cmd = ta.toPlainText().strip()
                if not new_cmd:
                    self._set_status(t("命令不能为空"), "warn")
                    return

                def work():
                    self.api.hooks_admin_edit(agent, entry_id,
                                              {"command": new_cmd})

                def on_ok(_r) -> None:
                    dlg.accept()
                    self._set_status(t("已保存"), tone="ok")
                    self.refresh_live()

                # 编辑保存原是 60s 同步调用跑在 UI 线程
                self._hooks_write(work, on_ok, [save_b])
            save_b = btn_primary(t("保存"))
            save_b.clicked.connect(_save)
            btn_row.addWidget(save_b)
        lay.addLayout(btn_row)
        dlg.exec()
        dlg.deleteLater()

    def _entry_delete(self, agent: str, entry_id: str) -> None:
        # confirm_dialog（主题化中文按钮），不再用裸 QMessageBox（英文 Yes/No）
        if not confirm_dialog(
                t("删除这条 Hook"),
                t("删除后不可恢复。若它是该工具原本就有的 Hook，请确认你真的要删？"),
                self):
            return

        def work():
            self.api.hooks_admin_delete(agent, entry_id)

        def on_ok(_r) -> None:
            self._set_status(t("已删除"), tone="ok")
            self.refresh_live()

        self._hooks_write(work, on_ok)

    def _entry_add(self, agent: str) -> None:
        """手动给可写工具新增一条 hook 条目（事件 + 命令）。

        JSON 系：形状后端自动探测（扁平/嵌套）。目录型（hook_dir，如 hermes）：后端
        把命令包成 gateway handler.py（HOOK.yaml + handler.py 目录）。模态对话框是独立
        窗口（不在页面滚动区内）→ 可用可编辑下拉预填该工具的已知事件；事件名工具特定，
        允许用户输入任意值（不强枚举）。"""
        kind = str(self._agents_ov_cache.get(agent, {}).get("kind") or "")
        from ..capture.ide_hooks import IDES
        if kind == "code":
            # 目录型（hermes）：gateway 事件名；命令会被包成 handler.py
            known = ["agent:end", "session:end"]
            is_dir_hook = True
        else:
            known = list(IDES.get(agent, {}).get("events") or ())
            if agent == "claude-code":
                known = ["PreToolUse", "PostToolUse", "SessionStart",
                         "UserPromptSubmit", "Stop", "Notification", "SessionEnd"]
            is_dir_hook = False
        dlg = QDialog(self)
        dlg.setWindowTitle(t("新增 Hook 条目"))
        dlg.setMinimumWidth(SIZES.CONTENT_FORM)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(S.s2)
        lay.addWidget(self._field_label(t("事件（工具触发时机）")))
        ev_dd = QComboBox()
        ev_dd.setEditable(True)
        ev_dd.addItems(known)
        ev_dd.setFixedWidth(D.FIELD_W)
        lay.addWidget(ev_dd)
        if is_dir_hook:
            cmd_label = t("命令（触发时执行；Hermes 目录型会包成 gateway handler）")
            cmd_ph = t("例如 echo done，或任意 shell 命令；写入后需重启 Hermes gateway 生效")
        else:
            cmd_label = t("命令（触发时执行的 shell 命令）")
            cmd_ph = t("例如 curl -s --max-time 15 -X POST "
                       "http://127.0.0.1:8101/api/hooks/... --data-binary @-")
        lay.addWidget(self._field_label(cmd_label))
        cmd_ta = QPlainTextEdit()
        cmd_ta.setPlaceholderText(cmd_ph)
        cmd_ta.setFixedHeight(D.TEXTAREA_H_SM)
        lay.addWidget(cmd_ta)

        def _save() -> None:
            event = (ev_dd.currentText() or "").strip()
            command = cmd_ta.toPlainText().strip()
            if not event:
                self._set_status(t("事件名不能为空"), "warn")
                return
            if not command:
                self._set_status(t("命令不能为空"), "warn")
                return

            def work():
                self.api.hooks_admin_add(agent, event, command)

            def on_ok(_r) -> None:
                dlg.accept()
                msg = t("已新增")
                if is_dir_hook:
                    msg = t("已新增，需重启 Hermes gateway 生效")
                self._set_status(msg, tone="ok")
                self._agent_expanded.add(agent)  # 展开该工具，新条目立即可见
                self._save_expanded()
                self.refresh_live()

            # 新增保存原是 60s 同步调用跑在 UI 线程
            self._hooks_write(work, on_ok, [save])

        btn_row = QHBoxLayout()
        btn_row.setSpacing(S.s2)
        cancel = btn_secondary(t("取消"))
        cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel)
        btn_row.addStretch(1)
        save = btn_primary(t("保存"))
        save.clicked.connect(_save)
        btn_row.addWidget(save)
        lay.addLayout(btn_row)
        dlg.exec()
        dlg.deleteLater()

    # ---------- 区二 · 我的规则 ----------

    def _build_rules_section(self) -> QFrame:
        c = card()
        lay = c.layout()
        # 卡头：标题 + 预算条 + 数值 + 提醒设置弱链
        hdr = QHBoxLayout()
        hdr.setSpacing(S.s2)
        self._rules_title = txt(t("我的规则"), F.h2, 600)
        hdr.addWidget(self._rules_title)
        hdr.addStretch(1)
        self._budget_bar = self._budget_widget()
        hdr.addWidget(self._budget_bar)
        self._budget_val = txt("0 / 400", F.caption, 600, C.ink_500)
        hdr.addWidget(self._budget_val)
        self._stale_cfg_lbl = txt(t("提醒设置"), F.caption, color=C.ink_500)
        self._stale_cfg_lbl.setCursor(Qt.PointingHandCursor)
        self._stale_cfg_lbl.mousePressEvent = lambda _e: self._toggle_stale_cfg()
        hdr.addWidget(self._stale_cfg_lbl, 0, Qt.AlignVCenter)
        hdr_w = QWidget()
        hdr_w.setLayout(hdr)
        lay.addWidget(hdr_w)
        # 未命中提醒设置行（默认折叠，收在卡头下）
        self._stale_tf = QLineEdit("30")
        self._stale_tf.setFixedWidth(D.DD_W_XS)
        self._stale_tf.setFixedHeight(D.BTN_H_SM)
        self._stale_tf.setValidator(QIntValidator(1, 365))
        self._stale_tf.returnPressed.connect(self._save_stale_days)
        self._stale_cfg_txt = txt("", F.caption, color=C.ink_500)
        stale_box = QWidget()
        stale_lay = QVBoxLayout(stale_box)
        stale_lay.setContentsMargins(S.s3, S.s2, S.s3, S.s2)
        stale_lay.setSpacing(S.s1)
        sr = QHBoxLayout()
        sr.setSpacing(S.s2)
        self._stale_label = txt(t("多少天没用上就提醒（默认 30）"),
                                F.body, color=C.ink_700)
        self._stale_label.setToolTip(t(
            "同一条规则连续这么多天一次都没用上，就提醒你考虑关掉或改触发方式。\n"
            "为什么建议关掉：规则要精简——每开一个新对话，AI 都要先把这些规则读一遍，"
            "条数越多，启动越慢、注意力被分走越多"))
        sr.addWidget(self._stale_label)
        sr.addWidget(self._stale_tf)
        self._save_stale_btn = btn_flat(t("保存"))
        self._save_stale_btn.clicked.connect(self._save_stale_days)
        sr.addWidget(self._save_stale_btn)
        sr.addStretch(1)
        stale_lay.addLayout(sr)
        stale_lay.addWidget(self._stale_cfg_txt)
        stale_box.setVisible(False)
        self._stale_cfg_box = stale_box
        lay.addWidget(stale_box)
        # 信号行（有信号才出现：预算/过时/冲突药丸）
        self._signal_row = QHBoxLayout()
        self._signal_row.setSpacing(S.s2)
        signal_box = QWidget()
        signal_box.setLayout(self._signal_row)
        signal_box.setVisible(False)
        self._signal_box = signal_box
        lay.addWidget(signal_box)
        # 分段开关（按规则 / 按工具）
        self._seg_btns: dict[str, QPushButton] = {}
        seg_box = QWidget()
        seg_lay = QHBoxLayout(seg_box)
        seg_lay.setContentsMargins(0, 0, 0, 0)
        seg_lay.setSpacing(S.s2)
        for key, label in (("rules", t("按规则")), ("tools", t("按工具"))):
            btn = seg_button(label, on_click=lambda _=False, k=key: self._switch_view(k))
            self._seg_btns[key] = btn
            seg_lay.addWidget(btn)
        seg_lay.addStretch(1)
        lay.addWidget(seg_box)
        self._update_seg()
        # 批量管理条（有勾选才浮现）
        batch_box = QWidget()
        batch_lay = QHBoxLayout(batch_box)
        batch_lay.setContentsMargins(0, 0, 0, 0)
        batch_lay.setSpacing(S.s1)
        self._select_all_cb = QCheckBox()
        self._select_all_cb.toggled.connect(self._toggle_select_all)
        batch_lay.addWidget(self._select_all_cb)
        self._sel_all_btn = btn_flat(t("全选"))
        self._sel_all_btn.clicked.connect(lambda: self._toggle_select_all(True))
        batch_lay.addWidget(self._sel_all_btn)
        self._sel_count = txt("", F.caption, color=C.ink_500)
        batch_lay.addWidget(self._sel_count)
        self._batch_en_btn = btn_flat(t("批量启用"))
        self._batch_en_btn.clicked.connect(self._batch_enable)
        batch_lay.addWidget(self._batch_en_btn)
        self._batch_del_btn = btn_flat(t("批量删除"))
        self._batch_del_btn.clicked.connect(self._batch_delete)
        batch_lay.addWidget(self._batch_del_btn)
        batch_lay.addStretch(1)
        batch_box.setVisible(False)
        self._batch_box = batch_box
        lay.addWidget(batch_box)
        # 行内状态行（与主窗口状态行同步显示；空消息时隐藏）
        self._status_local = status_text("", tone="ok")
        self._status_local.setVisible(False)
        lay.addWidget(self._status_local)
        # 规则列表（按规则视图，refresh 重建）
        self._list_box = QWidget()
        self._list_lay = QVBoxLayout(self._list_box)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(S.s3)
        lay.addWidget(self._list_box)
        # 按工具视图
        self._tools_view = QWidget()
        tl = QVBoxLayout(self._tools_view)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(S.s3)
        tool_hdr = QHBoxLayout()
        tool_hdr.setSpacing(S.s2)
        self._tool_dd = SelectButton(width=D.DD_W_LG)
        self._tool_dd.currentIndexChanged.connect(self._on_tool_select)
        tool_hdr.addWidget(self._tool_dd)
        tool_hdr.addStretch(1)
        self._tool_new_btn = btn_secondary(t("为此工具新建规则"))
        self._tool_new_btn.clicked.connect(lambda: self._rule_dialog(
            None, preset_agent=self._tool_state["agent"] or None))
        tool_hdr.addWidget(self._tool_new_btn)
        tool_hdr_w = QWidget()
        tool_hdr_w.setLayout(tool_hdr)
        tl.addWidget(tool_hdr_w)
        self._tool_list_box = QWidget()
        self._tool_list_lay = QVBoxLayout(self._tool_list_box)
        self._tool_list_lay.setContentsMargins(0, 0, 0, 0)
        self._tool_list_lay.setSpacing(S.s3)
        tl.addWidget(self._tool_list_box)
        lay.addWidget(self._tools_view)
        self._tools_view.setVisible(False)
        return c

    # ---------- 预算条 + 信号行 ----------

    def _budget_widget(self) -> QWidget:
        """预算条：宽 96 高 6（设计文档新 token 的兜底实现：96=3×SIZES.LIST_ICON_BOX，
        条高 6 用 S.s1+2 兜底不引入表外值；若 deck 修订采纳新 token 则替换）。"""
        outer = QWidget()
        outer.setObjectName("hooksBudgetBar")
        outer.setFixedWidth(SIZES.LIST_ICON_BOX * 3)
        outer.setFixedHeight(6)
        outer.setStyleSheet(
            f"QWidget#hooksBudgetBar {{ background: {C.surface_3}; "
            f"border-radius: 3px; }}")
        self._budget_fill = QLabel()
        self._budget_fill.setFixedHeight(6)
        self._budget_fill.setStyleSheet(
            f"background: {C.brand_500}; border: none; border-radius: 3px;")
        self._budget_fill.hide()
        lay = QHBoxLayout(outer)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._budget_fill, 0, Qt.AlignLeft)
        lay.addStretch(1)
        return outer

    def _set_budget(self, used: int, budget: int) -> None:
        if budget <= 0:
            self._budget_fill.hide()
            self._budget_val.setText(f"{used} / {budget}")
            return
        pct = min(100, round(used / budget * 100))
        self._budget_val.setText(f"{used} / {budget}")
        if used == 0:
            self._budget_fill.hide()
            return
        self._budget_fill.show()
        w = max(6, int(self._budget_fill.parentWidget().width() * pct / 100))
        self._budget_fill.setFixedWidth(w)
        color = C.warn_fg if used > budget * 0.8 else C.brand_500
        self._budget_fill.setStyleSheet(
            f"background: {color}; border: none; border-radius: 3px;")

    def _toggle_stale_cfg(self) -> None:
        self._stale_open = not self._stale_open
        self._stale_cfg_box.setVisible(self._stale_open)

    def _render_signals(self, rules: list[dict], used: int, budget: int) -> None:
        """信号行：预算/过时/冲突药丸，有信号才出现（平时整行不占位）。"""
        clear_layout(self._signal_row)
        self._hooks_warn = False
        hint = (t("规则太多会互相稀释，建议把不常用的改成按需触发")
                if budget and used > budget * 0.8 else "")
        pct = min(100, round(used / budget * 100)) if budget else 0
        if budget and used > budget * 0.8:
            p = self._pill(f"{t('占用')} {pct}%", "warn")
            p.setToolTip(hint)
            self._signal_row.addWidget(p)
            self._hooks_warn = True
        stale_n = sum(1 for r in rules if r.get("stale"))
        if stale_n:
            self._signal_row.addWidget(self._pill(
                t("{n} 条规则已经 {d} 天没用上了", n=stale_n, d=self._stale_days_val),
                "warn"))
            self._hooks_warn = True
        conflict_n = sum(1 for r in rules if r.get("conflict"))
        if conflict_n:
            self._signal_row.addWidget(self._pill(
                t("{n} 个规则同优先级冲突，点开对照后自己拍板", n=conflict_n), "err"))
            self._hooks_warn = True
        self._signal_box.setVisible(self._hooks_warn)

    def _pill(self, text: str, tone: str) -> QLabel:
        """语义胶囊：红/橙/黄状态色只收敛到信号行这一处用。"""
        lbl = QLabel(text)
        bg = TONE_BG.get(tone, C.surface_2)
        fg = TONE_FG.get(tone, C.ink_500)
        lbl.setStyleSheet(
            f"QLabel {{ background: {bg}; color: {fg}; border-radius: {R.xl}px; "
            f"padding: 3px 10px; font-size: {F.caption}px; font-weight: 600; }}")
        return lbl

    # ---------- 规则数据与卡片 ----------

    def refresh_rules(self) -> None:
        try:
            data = self.api.rules()
        except LocalApiError as exc:
            self._set_status(exc.localized())
            return
        self._render_rules(data)

    def _render_rules(self, data) -> None:
        if not isinstance(data, dict):
            self._set_status(t("本地 API 未连接"))
            return
        rules = data.get("items", [])
        self._rules_cache[:] = rules
        used, budget = data.get("budget_used", 0), data.get("budget", 400)
        self._stale_days_val = int(data.get("stale_days", 30) or 30)
        self._set_budget(used, budget)
        self._render_signals(rules, used, budget)
        self._render_rule_list()
        if self._view_state == "tools":
            self._refresh_tools()
        self._sync_select_all()

    def _render_rule_list(self) -> None:
        rules = self._rules_cache
        # 增量渲染：按规则 id 原地复用；sig 除规则内容外还含命中行依赖的
        # stale_days 与勾选态——卡内容不变即不重建，这两者变化时按需重建。
        want: list[tuple[str, str, object]] = [
            (f"r:{r.get('id')}",
             content_sig([r, self._stale_days_val, r.get("id") in self._selected]),
             lambda r_=r: self._rule_card(r_))
            for r in rules
        ]
        sync_tracked(self._list_lay, self._rule_tracked, want)
        if not rules:
            # 空态控件不被追踪：want 为空时先由 sync_tracked 清空，再补空态
            b = btn_secondary(t("去模板库"))
            b.clicked.connect(self._goto_templates)
            self._list_lay.addWidget(empty_state(
                t("还没有规则"),
                t("规则从第一天就能用（不用等经验积累）——从下面的模板库挑一套，"
                  "或点上方「+ 新增规则」自己写一条。"),
                button=b, mascot="think"))
        # 首屏错峰入场（"只首屏"在基类 stagger_cards 里一处实现）
        self.stagger_cards(self._list_lay)

    def _rule_card(self, r: dict) -> QFrame:
        enabled = bool(r.get("enabled", True))
        trig = r.get("trigger", "smart")
        label = self._trigger_labels.get(trig, trig)
        if trig == "keyword" and r.get("keyword"):
            label = t("含「{kw}」时", kw=r["keyword"])
        # 档 2：自绘投影卡片（省逐控件 QGraphicsDropShadowEffect 的 CPU 合成）
        c = ShadowCard()
        main_row = QHBoxLayout()
        main_row.setSpacing(S.s2)
        col = QVBoxLayout()
        col.setSpacing(S.s1)
        h1 = QHBoxLayout()
        h1.setSpacing(S.s1)
        cb = QCheckBox()
        cb.setChecked(r.get("id") in self._selected)
        cb.toggled.connect(lambda on, rid=r["id"]: self._toggle_select(rid, on))
        h1.addWidget(cb)
        h1.addWidget(txt(r.get("name", ""), F.h2, 600,
                         C.ink_500 if not enabled else C.ink_900))
        h1.addWidget(self._agents_chip(r.get("agents")))
        # 冲突标记（中性 ink——红/黄警示收敛到信号行）
        if r.get("conflict"):
            dot = icon_widget("REPORT_PROBLEM_OUTLINED", 18, C.ink_500)
            dot.setToolTip(t("与另一条同优先级规则可能冲突，点开对照后自己拍板"))
            h1.addWidget(dot)
        h1.addStretch(1)
        h1_w = QWidget()
        h1_w.setLayout(h1)
        col.addWidget(h1_w)
        col.addWidget(txt(f"{label} · {r.get('text', '')[:60]}",
                          F.caption, color=C.ink_500, wrap=True))
        agents = r.get("agents")
        if agents and "*" not in agents:
            col.addWidget(txt(" · ".join(agents), F.caption, color=C.ink_700,
                              wrap=True))
        if r.get("scope") == "glob":
            col.addWidget(txt(t("仅 {globs}", globs=", ".join(r.get("globs") or [])),
                              F.caption, color=C.ink_500, wrap=True))
        col.addWidget(self._hit_line(r, self._stale_days_val))
        col_w = QWidget()
        col_w.setLayout(col)
        col_w.setMaximumWidth(SIZES.CONTENT_FORM)
        main_row.addWidget(col_w, 1)
        # 编辑升为可见按钮（高频操作直达）；⋯ 只留低频项
        edit_b = btn_flat(t("编辑"))
        edit_b.clicked.connect(lambda _=False, rr=r: self._rule_dialog(rr))
        main_row.addWidget(edit_b, 0, Qt.AlignVCenter)
        sw = switch(checked=enabled)
        sw.toggled.connect(lambda on, rr=r: self._toggle_rule(rr, on))
        main_row.addWidget(sw, 0, Qt.AlignVCenter)
        menu_items: list[tuple[str, object]] = []
        if r.get("template_id"):
            menu_items.append((t("恢复默认"), lambda rr=r: self._restore_default(rr)))
        menu_items.append((t("删除"), lambda rr=r: self._remove_rule(rr)))
        main_row.addWidget(self._more_button(menu_items), 0, Qt.AlignVCenter)
        row_w = QWidget()
        row_w.setLayout(main_row)
        c.layout().addWidget(row_w)
        # 卡片 hover 抬升 + 层次；点空白处下钻看完整规则（复选框/
        # 编辑/开关/⋯ 各自消费点击，不受影响）。
        self._attach_rule_card_click(c, r)
        return c

    def _attach_rule_card_click(self, c: QWidget, r: dict) -> None:
        """规则卡交互四件套（hover 抬升 / 手型 / 提示 / 点空白处下钻）。

        「按规则」「按工具」两个视图共用，改一处即两处生效。
        """
        hover_lift(c)
        c.setCursor(Qt.PointingHandCursor)
        c.setToolTip(t("点开看完整规则"))
        # 卡上的复选框/开关/⋯ 菜单各自消费点击，空白处才落到这里
        c.mousePressEvent = lambda _e, rr=r: self._open_rule_detail(rr)

    def _open_rule_detail(self, r: dict) -> None:
        """规则卡下钻：整条正文 + 触发/范围/命中轨迹，收进统一
        ``DetailDrawer``（kind="preference"——规则就是你对 AI 的偏好指令）。

        职责边界：本抽屉只读**规则本体**（按规则/按工具两视图共用）；会话现场
        由 ``session_drawer.py`` 负责，两者不重叠。首次点击懒建一个实例
        复用，随页面一起回收。
        """
        drawer = getattr(self, "_rule_drawer", None)
        if drawer is None:
            drawer = DetailDrawer(self)
            self._rule_drawer = drawer
        enabled = bool(r.get("enabled", True))
        trig = r.get("trigger", "smart")
        label = self._trigger_labels.get(trig, trig)
        if trig == "keyword" and r.get("keyword"):
            label = t("含「{kw}」时", kw=r["keyword"])
        agents = r.get("agents")
        if agents is None or "*" in agents:
            scope = t("全部工具")
        elif agents:
            scope = "、".join(_agent_display(a) for a in agents)
        else:
            scope = t("未配装")
        meta = [f"{t('触发时机')}：{label}", f"{t('生效范围')}：{scope}"]
        if r.get("scope") == "glob" and r.get("globs"):
            meta.append(t("仅 {globs}", globs=", ".join(r.get("globs") or [])))
        near7 = int(r.get("hit_7d", 0) or 0)
        count = int(r.get("hit_count", 0) or 0)
        if near7:
            meta.append(t("近 7 天命中 {n} 次", n=near7))
        elif count:
            meta.append(t("用过 {n} 次", n=count))
        else:
            meta.append(t("还没用过"))
        text = str(r.get("text") or "").strip() or t("（这条规则没有正文）")
        body = text + "\n\n" + "\n".join(f"- {m}" for m in meta)
        drawer.open_detail("preference", {
            "title": str(r.get("name") or t("规则")),
            "status": t("已启用") if enabled else t("已停用"),
            "status_tone": "ok" if enabled else "ink",
            "body": body,
        })

    def _tool_rule_card(self, r: dict, agent: str) -> QFrame:
        """按工具视图的规则卡：带全局/指定来源标记 + 三档操作。"""
        enabled = bool(r.get("enabled", True))
        trig = r.get("trigger", "smart")
        label = self._trigger_labels.get(trig, trig)
        if trig == "keyword" and r.get("keyword"):
            label = t("含「{kw}」时", kw=r["keyword"])
        source = chip(t("全局"), "brand") if (
            r.get("agents") is None or "*" in r.get("agents")) else None
        scope_note = None
        if r.get("scope") == "glob":
            scope_note = txt(t("仅 {globs}", globs=", ".join(r.get("globs") or [])),
                             F.caption, color=C.ink_500, wrap=True)
        # 档 2：自绘投影卡片（省逐控件 QGraphicsDropShadowEffect 的 CPU 合成）
        c = ShadowCard()
        main_row = QHBoxLayout()
        main_row.setSpacing(S.s2)
        col = QVBoxLayout()
        col.setSpacing(S.s1)
        h1 = QHBoxLayout()
        h1.setSpacing(S.s1)
        h1.addWidget(txt(r.get("name", ""), F.h2, 600))
        if source:
            h1.addWidget(source)
        h1.addStretch(1)
        h1_w = QWidget()
        h1_w.setLayout(h1)
        col.addWidget(h1_w)
        col.addWidget(txt(f"{label} · {r.get('text', '')[:60]}",
                          F.caption, color=C.ink_500, wrap=True))
        if scope_note is not None:
            col.addWidget(scope_note)
        col_w = QWidget()
        col_w.setLayout(col)
        col_w.setMaximumWidth(SIZES.CONTENT_FORM)
        main_row.addWidget(col_w, 1)
        edit_b = btn_flat(t("编辑"))
        edit_b.clicked.connect(lambda _=False, rr=r: self._rule_dialog(rr))
        main_row.addWidget(edit_b, 0, Qt.AlignVCenter)
        sw = switch(checked=enabled)
        sw.toggled.connect(lambda on, rr=r: self._toggle_rule(rr, on))
        main_row.addWidget(sw, 0, Qt.AlignVCenter)
        menu_items: list[tuple[str, object]] = []
        if source is None:
            # A 档：从此工具移除（全局规则不给 A 档，防歪 #5）
            menu_items.append((t("从此工具移除"),
                               lambda rr=r, ag=agent: self._remove_from_tool(rr, ag)))
        else:
            # B 档：改为指定工具
            menu_items.append((t("改为指定工具"),
                               lambda rr=r, ag=agent: self._to_specified_tools(rr, ag)))
        # C 档：删除规则
        menu_items.append((t("删除规则"), lambda rr=r: self._remove_rule(rr)))
        main_row.addWidget(self._more_button(menu_items), 0, Qt.AlignVCenter)
        row_w = QWidget()
        row_w.setLayout(main_row)
        c.layout().addWidget(row_w)
        self._attach_rule_card_click(c, r)
        return c

    # ---------- 通用小组件 ----------

    @staticmethod
    def _agents_chip(agents: list | None) -> QFrame:
        """「生效工具」徽标：["*"]（或缺省）= 全部工具；N 个指定 = N 个工具；
        [] = 未配装（muted）。"""
        if agents is None:
            agents = ["*"]
        if "*" in agents:
            return chip(t("全部工具"), "brand")
        if not agents:
            return HooksPage._muted_chip(t("未配装"))
        return chip(t("{n} 个工具", n=len(agents)), "brand")

    @staticmethod
    def _muted_chip(label: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {C.surface_2}; border: none; border-radius: {R.sm}px; }}")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(D.CHIP_PAD_X, D.CHIP_PAD_Y, D.CHIP_PAD_X, D.CHIP_PAD_Y)
        lay.addWidget(txt(label, F.caption, 600, C.ink_500))
        return frame

    @staticmethod
    def _pri_chip(pri: str) -> QFrame:
        """优先级小标签（模板行 + 筛选行共用）。"""
        label_key, tone = _PRI_STYLE.get(pri, (pri.upper(), "ink"))
        fg = TONE_FG.get(tone, C.ink_500)
        bg = TONE_BG.get(tone, C.surface_2)
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {bg}; border: none; border-radius: {R.xl}px; }}")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(D.CHIP_PAD_X, D.CHIP_PAD_Y, D.CHIP_PAD_X, D.CHIP_PAD_Y)
        lay.addWidget(txt(t(label_key), F.caption, 600, fg))
        return frame

    @staticmethod
    def _hit_line(r: dict, stale_days: int) -> QWidget:
        """命中行：近7天命中用品牌橙（高频=活着），过时提示中性 ink（警示收敛信号行）。"""
        count = int(r.get("hit_count", 0) or 0)
        near7 = int(r.get("hit_7d", 0) or 0)
        if r.get("stale"):
            w = txt(t("已经 {d} 天没用上，可以关掉或删掉", d=stale_days),
                    F.caption, color=C.ink_500)
            if near7:
                w.setToolTip(t("近 7 天命中 {n} 次", n=near7))
            return w
        if near7:
            w = txt(t("近 7 天命中 {n} 次", n=near7), F.caption, color=C.brand_700)
            if count:
                last = str(r.get("last_hit") or "")[:10]
                w.setToolTip(t("累计 {c} 次 · 最近 {at}", c=count, at=last))
            return w
        if count:
            last = str(r.get("last_hit") or "")[:10]
            return txt(t("用过 {n} 次 · 最近 {at}", n=count, at=last),
                       F.caption, color=C.ink_500)
        return txt(t("还没用过"), F.caption, color=C.ink_500, italic=True)

    @staticmethod
    def _locked_trig(label: str) -> QFrame:
        """P0 红线：trigger 锁定 hard-hook（红标 + 不可选，W4-06）。"""
        frame = QFrame()
        frame.setFixedWidth(D.DD_W_MD)
        frame.setStyleSheet(
            f"QFrame {{ background: {C.err_bg}; border: none; border-radius: {R.xl}px; }}")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(D.CHIP_PAD_X, D.CHIP_PAD_Y, D.CHIP_PAD_X, D.CHIP_PAD_Y)
        lay.addWidget(txt(label, F.caption, 600, C.err_fg))
        return frame

    @staticmethod
    def _field_label(text: str):
        return txt(text, F.caption, color=C.ink_500)

    @staticmethod
    def _form_row(label: str, widget: QWidget) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S.s2)
        lay.addWidget(txt(label, F.body, color=C.ink_700))
        lay.addWidget(widget)
        lay.addStretch(1)
        return row

    def _more_button(self, items: list[tuple[str, QMenu | None]]) -> QWidget:
        """⋯ 溢出按钮：低频操作收进菜单。三点矢量自绘（_DotsButton），任何平台
        都稳定可见；surface 底 + 描边 + 圆角，"可见但安静"，不抢橙色主角。"""
        b = _DotsButton(self)
        b.setToolTip(t("更多操作"))

        def open_menu() -> None:
            m = QMenu(self)
            for label, fn in items:
                act = m.addAction(label)
                act.triggered.connect(lambda _=False, f=fn: f())
            m.exec(b.mapToGlobal(b.rect().bottomLeft()))
        b.clicked.connect(lambda: open_menu())
        return b

    # ---------- 规则 CRUD ----------

    def _rule_dialog(self, rule: dict | None, preset_agent: str | None = None) -> None:
        """新建/编辑规则。preset_agent：按工具视图"为此工具新增"时预填 agents=[该工具]。"""
        is_new = rule is None
        rule = rule or {}
        dlg = QDialog(self)
        dlg.setWindowTitle(t("新增规则") if is_new else t("编辑规则"))
        dlg.setMinimumWidth(SIZES.CONTENT_FORM)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(S.s2)
        name_tf = QLineEdit(rule.get("name", ""))
        name_tf.setPlaceholderText(t("规则名（如 公文格式）"))
        lay.addWidget(self._field_label(t("规则名（如 公文格式）")))
        lay.addWidget(name_tf)
        # 应当/绝不两栏分列（反例单独成栏更醒目可维护）
        lay.addWidget(self._field_label(t("应当（每次自动带上的正文，可多行）")))
        text_tf = QPlainTextEdit(rule.get("text", ""))
        text_tf.setFixedHeight(D.TEXTAREA_H_LG)
        lay.addWidget(text_tf)
        lay.addWidget(self._field_label(t("绝不（反例，每行一条；留空 = 无反例）")))
        donts_tf = QPlainTextEdit("\n".join(rule.get("donts") or []))
        donts_tf.setFixedHeight(D.TEXTAREA_H_SM)
        lay.addWidget(donts_tf)
        trigger_dd = QComboBox()
        for k in TRIGGER_KEYS:
            if k in self._trigger_labels:
                trigger_dd.addItem(self._trigger_labels[k], k)
        idx = trigger_dd.findData(rule.get("trigger", "smart"))
        trigger_dd.setCurrentIndex(max(0, idx))
        trigger_dd.setFixedWidth(D.FIELD_W)
        lay.addWidget(self._form_row(t("生效方式"), trigger_dd))
        kw_tf = QLineEdit(rule.get("keyword", ""))
        kw_tf.setPlaceholderText(t("关键词（如：投标）"))
        lay.addWidget(self._field_label(t("关键词（如：投标）")))
        lay.addWidget(kw_tf)
        # 生效工具（治理方案：全部工具 ↔ 指定工具勾选）
        cur_agents = rule.get("agents")
        if cur_agents is None:
            cur_agents = ["*"] if preset_agent is None else [preset_agent]
        agents_dd = QComboBox()
        agents_dd.addItem(t("全部工具"), "all")
        agents_dd.addItem(t("指定工具"), "specified")
        agents_dd.setCurrentIndex(0 if "*" in cur_agents else 1)
        agents_dd.setFixedWidth(D.DD_W_MD)
        lay.addWidget(self._form_row(t("生效工具"), agents_dd))
        if not self._agents_cache:
            self._load_agents()
        agent_checks: list[QCheckBox] = []
        agent_box = QWidget()
        agent_lay = QVBoxLayout(agent_box)
        agent_lay.setContentsMargins(0, 0, 0, 0)
        agent_lay.setSpacing(S.s1)
        for a in self._agents_cache:
            cb = QCheckBox(_agent_display(a))
            cb.setChecked(a in cur_agents)
            cb.setProperty("agent", a)
            agent_checks.append(cb)
            agent_lay.addWidget(cb)
        agent_box.setVisible(agents_dd.currentData() == "specified")
        lay.addWidget(agent_box)
        agents_dd.currentIndexChanged.connect(
            lambda _: agent_box.setVisible(agents_dd.currentData() == "specified"))
        # 生效范围（治理方案：所有任务 / 针对特定文件 globs）
        cur_scope = rule.get("scope") or "all"
        scope_dd = QComboBox()
        scope_dd.addItem(t("所有任务"), "all")
        scope_dd.addItem(t("针对特定文件"), "glob")
        scope_dd.setCurrentIndex(1 if cur_scope == "glob" else 0)
        scope_dd.setFixedWidth(D.DD_W_MD)
        lay.addWidget(self._form_row(t("生效范围"), scope_dd))
        globs_tf = QLineEdit(", ".join(rule.get("globs") or []))
        globs_tf.setPlaceholderText(
            t("文件范围（如 *.test.* / src/api/**，多个用逗号分隔）"))
        globs_tf.setVisible(cur_scope == "glob")
        lay.addWidget(globs_tf)
        scope_dd.currentIndexChanged.connect(
            lambda _: globs_tf.setVisible(scope_dd.currentData() == "glob"))

        def save() -> None:
            if agents_dd.currentData() == "specified":
                agents_out = [cb.property("agent") for cb in agent_checks
                              if cb.isChecked()]
                if not agents_out:
                    self._set_status(t("指定工具至少要勾选一个（一个都不勾 = 哪个工具都不带上）"))
                    return
            else:
                agents_out = ["*"]
            globs_out = ([g.strip() for g in (globs_tf.text() or "").split(",")
                          if g.strip()] if scope_dd.currentData() == "glob" else [])
            # 绝不栏按行拆成列表（注入时拼在应当正文后）
            donts_out = [d.strip() for d in (donts_tf.toPlainText() or "").splitlines()
                         if d.strip()]
            payload = {
                "id": rule.get("id"), "name": name_tf.text(),
                "text": text_tf.toPlainText(),
                "donts": donts_out,
                "trigger": trigger_dd.currentData() or "smart",
                "keyword": kw_tf.text() or None,
                "enabled": rule.get("enabled", True),
                "agents": agents_out,
                "scope": "glob" if scope_dd.currentData() == "glob" else "all",
                "globs": globs_out,
            }
            try:
                if is_new:
                    self.api.add_rule(payload)
                else:
                    self.api.update_rule(rule["id"], payload)
                dlg.accept()
                self.refresh()
            except LocalApiError as exc:
                self._set_status(exc.localized())

        btn_row = QHBoxLayout()
        btn_row.setSpacing(S.s2)
        cancel = btn_secondary(t("取消"))
        cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel)
        btn_row.addStretch(1)
        save_btn = btn_primary(t("保存"))
        save_btn.clicked.connect(save)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)
        dlg.exec()
        dlg.deleteLater()

    def _toggle_rule(self, r: dict, enabled: bool) -> None:
        try:
            self.api.update_rule(r["id"], {**r, "enabled": enabled,
                                           "id": r["id"], "name": r.get("name", "")})
            self.refresh()
        except LocalApiError as exc:
            self._set_status(exc.localized())

    def _remove_rule(self, r: dict) -> None:
        if not confirm_dialog(t("删除这条规则？"),
                              t("删掉后不再自动带上；想找回可以从模板库重新导入"),
                              self):
            return
        try:
            self.api.remove_rule(r["id"])
            self._set_status(t("已删除"), "ok")
            self.refresh()
        except LocalApiError as exc:
            self._set_status(exc.localized())

    def _restore_default(self, r: dict) -> None:
        try:
            self.api.restore_template(r["template_id"], i18n.current_language())
            self._set_status(t("已恢复默认"), "ok")
            self.refresh()
        except LocalApiError as exc:
            self._set_status(exc.localized())

    # ---------- 三档删除语义（治理方案 ，防歧义写死） ----------

    def _remove_from_tool(self, r: dict, agent: str) -> None:
        """A 档：从 agents 移除该工具（规则保留；删空 → 未配装 []，可重配）。"""
        agents = [a for a in (r.get("agents") or []) if a != agent]
        try:
            self.api.update_rule(r["id"], {**r, "agents": agents})
            self._set_status(t("已不再带给该工具，规则保留"), "ok")
            self.refresh()
        except LocalApiError as exc:
            self._set_status(exc.localized())

    def _to_specified_tools(self, r: dict, agent: str) -> None:
        """B 档：全局规则转指定列表（默认勾上除本工具外的全部已知工具）。"""
        known = [a for a in self._agents_cache if a != agent]
        dlg = QDialog(self)
        dlg.setWindowTitle(t("改为指定工具"))
        lay = QVBoxLayout(dlg)
        lay.setSpacing(S.s2)
        lay.addWidget(txt(t("当前是全部工具通用，要单独调整需先转成指定"),
                          F.caption, color=C.ink_500))
        checks: list[QCheckBox] = []
        for a in known:
            cb = QCheckBox(_agent_display(a))
            cb.setChecked(True)
            cb.setProperty("agent", a)
            checks.append(cb)
            lay.addWidget(cb)
        if not known:
            lay.addWidget(txt(t("还没有其他已知工具"), F.caption, color=C.ink_500))

        def do() -> None:
  
            out = [cb.property("agent") for cb in checks if cb.isChecked()]
            try:
                self.api.update_rule(r["id"], {**r, "agents": out})
                self._set_status(t("已改为只带给所选工具"), "ok")
                self.refresh()
            except LocalApiError as exc:
                self._set_status(exc.localized())
            dlg.accept()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(S.s2)
        cancel = btn_secondary(t("取消"))
        cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel)
        btn_row.addStretch(1)
        save = btn_primary(t("保存"))
        save.clicked.connect(do)
        btn_row.addWidget(save)
        lay.addLayout(btn_row)
        dlg.exec()
        dlg.deleteLater()

    # ---------- 批量管理 ----------

    def _toggle_select(self, rid: str, on: bool) -> None:
        if on:
            self._selected.add(rid)
        else:
            self._selected.discard(rid)
        self._sync_select_all()

    def _toggle_select_all(self, on: bool) -> None:
        if on:
            self._selected.update(r["id"] for r in self._rules_cache if r.get("id"))
        else:
            self._selected.clear()
        self.refresh_rules()

    def _sync_select_all(self) -> None:
        ids = {r["id"] for r in self._rules_cache if r.get("id")}
        self._select_all_cb.blockSignals(True)
        self._select_all_cb.setChecked(bool(ids) and self._selected >= ids)
        self._select_all_cb.blockSignals(False)
        # 批量工具栏有选中才浮现：无选中时零占位
        self._batch_box.setVisible(bool(self._selected))
        self._sel_count.setText(
            t("已选 {n} 条", n=len(self._selected)) if self._selected else "")

    def _batch_enable(self) -> None:
        for r in [x for x in self._rules_cache if x.get("id") in self._selected]:
            try:
                self.api.update_rule(r["id"], {**r, "enabled": True})
            except LocalApiError as exc:
                self._set_status(exc.localized())
                return
        self._selected.clear()
        self.refresh_rules()

    def _batch_delete(self) -> None:
        n = len([x for x in self._rules_cache if x.get("id") in self._selected])
        if n == 0:
            self._set_status(t("请先勾选要删除的规则"))
            return
        if not confirm_dialog(t("删除 {n} 条规则？", n=n),
                              t("删掉后不再自动带上；想找回可以从模板库重新导入"),
                              self):
            return
        for r in [x for x in self._rules_cache if x.get("id") in self._selected]:
            try:
                self.api.remove_rule(r["id"])
            except LocalApiError as exc:
                self._set_status(exc.localized())
                return
        self._selected.clear()
        self._set_status(t("已删除"), "ok")
        self.refresh_rules()

    # ---------- 未命中提醒 ----------

    def _save_stale_days(self) -> None:
        raw = (self._stale_tf.text() or "").strip()
        try:
            v = max(1, min(int(raw) if raw else 30, 365))
        except ValueError:
            v = 30
        self._stale_tf.setText(str(v))
        try:
            self.api.update_config({"hook_stale_days": v})
            self._stale_cfg_txt.setText(
                t("已保存：超过 {n} 天没用上的规则会提醒你", n=v))
            self._stale_cfg_txt.setStyleSheet(
                f"color: {C.ok_fg}; background: transparent; border: none;")
        except LocalApiError as exc:
            self._stale_cfg_txt.setText(exc.localized())
            self._stale_cfg_txt.setStyleSheet(
                f"color: {C.err_fg}; background: transparent; border: none;")

    def _render_stale_cfg(self, cfg) -> None:
        self._stale_loaded = True
        try:
            v = int((cfg or {}).get("hook_stale_days") or 30)
            self._stale_tf.setText(str(v))
        except (TypeError, ValueError):
            pass

    # ---------- 视图切换 + 按工具视图 ----------

    def _update_seg(self) -> None:
        for key, btn in self._seg_btns.items():
            seg_style(btn, self._view_state == key)

    def _switch_view(self, key: str) -> None:
        self._view_state = key
        self._list_box.setVisible(key == "rules")
        self._batch_box.setVisible(key == "rules" and bool(self._selected))
        self._tools_view.setVisible(key == "tools")
        self._update_seg()
        if key == "tools":
            self._refresh_tools()

    def _load_agents(self) -> None:
        try:
            self._agents_cache[:] = self.api.rule_agents().get("agents", [])
        except LocalApiError:
            self._agents_cache[:] = []
        self._tool_dd.blockSignals(True)
        self._tool_dd.clear()
        for a in self._agents_cache:
            self._tool_dd.addItem(_agent_display(a), a)
        if self._tool_state["agent"] not in self._agents_cache:
            self._tool_state["agent"] = self._agents_cache[0] if self._agents_cache else ""
        if self._tool_state["agent"]:
            idx = self._tool_dd.findData(self._tool_state["agent"])
            self._tool_dd.setCurrentIndex(max(0, idx))
        self._tool_dd.blockSignals(False)

    def _on_tool_select(self, _index: int) -> None:
        self._tool_state["agent"] = self._tool_dd.currentData() or ""
        self._refresh_tools()

    def _refresh_tools(self) -> None:
        self._load_agents()
        agent = self._tool_state["agent"]
        clear_layout(self._tool_list_lay)
        if not agent:
            self._tool_list_lay.addWidget(empty_state(
                t("还没有识别到工具"),
                t("接上任意一个工具（见「接入」页）后，这里就能按工具配装规则"),
                mascot="think"))
            return
        try:
            data = self.api.rules()
        except LocalApiError as exc:
            self._set_status(exc.localized())
            return
        # 该工具当前生效的规则：全局（["*"]）+ 指定包含该工具的
        eff = [r for r in data.get("items", [])
               if r.get("enabled", True)
               and (r.get("agents") is None or "*" in r.get("agents")
                    or agent in r.get("agents"))]
        if not eff:
            b = btn_secondary(t("为此工具新建规则"))
            b.clicked.connect(lambda: self._rule_dialog(None, preset_agent=agent))
            self._tool_list_lay.addWidget(empty_state(
                t("这个工具还没有专属规则"),
                t("全局规则仍会生效；想只给它加一条，点下面的按钮。"),
                button=b, mascot="think"))
        for r in eff:
            self._tool_list_lay.addWidget(self._tool_rule_card(r, agent))

    # ---------- 状态 / 数据入口 ----------

    def _set_status(self, msg: str, tone: str = "err") -> None:
        """写主窗口状态行 + 本页行内状态行（空消息时收起，不占版面）。"""
        self.set_status(msg, tone)
        self._status_local.setText(msg)
        color = {"ok": C.ok_fg, "err": C.err_fg,
                 "warn": C.warn_fg, "info": C.info_fg}[tone]
        status_tone(self._status_local, color)
        self._status_local.setVisible(bool(msg))

    def refresh(self) -> None:
        """：整页 5 段只读取数并一次后台并行，主线程分段渲染。

        首屏骨架：按三段式真实形状给高度（页头 / 实时捕获 / 我的
        规则 / 模板库）；取数快于 SKELETON_MIN_MS 时骨架根本不显示，由
        fetch_and_render 自动挂/撤。取数方式不变。
        """
        self.fetch_and_render(self._fetch, self._render_all,
                              skeleton=[44, 132, 188, 156])

    def _fetch(self) -> dict:
        need_cfg = not self._stale_loaded or not self._expanded_loaded
        calls = {
            "overview": self.api.hooks_admin_overview,
            "models": self.api.models,
            "rules": self.api.rules,
        }
        if need_cfg:
            calls["config"] = self.api.config
        if not self._templates_loaded:
            calls["templates"] = lambda: self.api.templates(
                i18n.current_language())
        return parallel_fetch(calls)

    def _render_all(self, res: dict | None) -> None:
        res = res or {}
        cfg = res.get("config")
        if not self._stale_loaded:
            self._render_stale_cfg(cfg)
        self._render_expanded(cfg)
        self._render_live(res.get("overview"), res.get("models"))
        self._render_rules(res.get("rules"))
        if not self._templates_loaded and "templates" in res:
            self._templates_loaded = self._render_templates(res.get("templates"))
        self._update_mascot()

    def _update_mascot(self) -> None:
        """标题吉祥物随页面状态切换。

        sweat=有警示（预算超限/过时/冲突）；wave=有可一键接入的工具；
        think=一条规则都还没有；smile=正常。"""
        if self._hooks_warn:
            new = "sweat"
        elif self._hooks_offer:
            new = "wave"
        elif not self._rules_cache:
            new = "think"
        else:
            new = "smile"
        pm = mascot_image(new, SIZES.MASCOT_DIALOG_TITLE).pixmap()
        if pm is not None and self._hooks_mascot is not None:
            self._hooks_mascot.setPixmap(pm)

    def retranslateUi(self) -> None:
        """重新调用 t() 更新所有静态 widget 文本。"""
        self._trigger_labels = _trigger_labels()
        self._heading_txt.setText(t("我的 Hooks"))
        self._add_btn.setText(t("+ 新增规则（Hook）"))
        self._what_is_hook.setText(
            t("工具触发这些事件时，会自动捕获进你的经验库。规则是你额外加上的："
              "告诉 AI 该怎么做、绝不能怎么做。"))
        # 区一
        self._live_title.setText(t("工具的 Hook"))
        self._live_sub.setText(
            t("工具触发事件时跑的命令，含它们原本就有的和 Experientia 添加的；"
              "可逐条开关、编辑、删除、AI 解释，也能新增一条。"))
        self._all_remove_btn.setText(t("全部移除 Experientia 添加的"))
        # 区二
        self._rules_title.setText(t("我的规则"))
        self._stale_cfg_lbl.setText(t("提醒设置"))
        self._stale_label.setText(t("多少天没用上就提醒（默认 30）"))
        self._save_stale_btn.setText(t("保存"))
        self._sel_all_btn.setText(t("全选"))
        self._batch_en_btn.setText(t("批量启用"))
        self._batch_del_btn.setText(t("批量删除"))
        self._seg_btns["rules"].setText(t("按规则"))
        self._seg_btns["tools"].setText(t("按工具"))
        self._tool_new_btn.setText(t("为此工具新建规则"))
        # 区三
        self._tpl_title.setText(t("模板库"))
        self._tpl_sub.setText(t("挑一套精选模板，按你的偏好导入成规则"))
        if self._tpl_note is not None:
            self._tpl_note.setText(
                t("模板正文由中文原版经 AI 翻译，个别措辞可能不准"
                  "——导入后建议过一遍再启用"))
        # R6：模板库按界面语言加载——切语言后若已加载过，按新语言重载并保留选中类目
        if self._templates_loaded:
            cat = self._cat_state[0] if self._cat_state else 0
            self._load_templates()
            self._cat_state[0] = min(cat, max(0, len(self._tpl_holder) - 1))
            self._render_category_chips()
            self._render_tpl_list()
        # 动态区重建同步语言（工具行/规则卡含 LLM 备注与条目按钮）
        # 原来这里同步 refresh_live + refresh_rules 两个
        # HTTP——retranslateUi 只在测试/兼容路径可达（生产走 _rebuild_visited_pages
        # 整页重建，取数在后台），一旦有人改回"原地翻译"就会冻结 UI。刷新交给
        # 页面重建/导航时的后台取数，这里只做静态文本翻译。
