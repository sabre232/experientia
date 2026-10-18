"""首页——Qt 版（原 Flet 源文件 home.py）。

三数字卡 + 本周发现 + 洞察卡（最多 2 条建议，应用/忽略/稍后）+ 待总结
经验列表（distill 后台跑，成功显示 ✓ 总结完成）+ 最近记录行。
视觉走 qt_theme（deck  组件长相）：硬身区，简洁清晰，无 emoji 装饰。
遵循设计方案 V-B1：内容列 ≤880px 居中；V-B2：全页左对齐。
"""

from __future__ import annotations

import logging as _log
import re

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from .api_client import LocalApi
from .agent_proc import running_agents
from .i18n import t
from .page_base import (PageBase, build_centered_scroll, clear_layout,
                        content_sig, parallel_fetch, sync_tracked)
from .qt_theme import (btn_flat, btn_primary, card, chip, empty_state,
                       icon_widget, list_row, mascot_image, status_dot, txt)
from .theme import C, D, F, R, S, SIZES
from ..proxy.detect import agent_display_name
from ..store.store import affinity_display

_logger = _log.getLogger("experientia.gui.home")

# 避坑卡同类归堆（方案 B）：首屏按次数降序露出的桶数，其余折叠
_FRICTION_SHOWN = 5

# 记忆构成：六层存量（六层的层名是引擎内部术语，UI 显示用平实名）。
# 顺序 = 取用优先级从原始到抽象（L1→L6）。
_MIX_CELLS = (("L1", "会话原话"), ("L2", "经验"), ("L3", "偏好"),
              ("L4", "会话摘要"), ("L5", "方法卡"), ("L6", "意图"))
# 提示"该总结成方法"的经验门槛：同 engine_curation 的整理口径（3 条起）
_MIX_DISTILL_MIN = 3


class _RatioBar(QWidget):
    """归堆行底部占比细条（高 3px，颜色全走主题 token，不硬编码）。"""

    H = 3

    def __init__(self, frac: float, parent=None):
        super().__init__(parent)
        self._frac = max(0.0, min(1.0, frac))
        self.setFixedHeight(self.H)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        w = self.width()
        p.setBrush(QColor(C.line))
        p.drawRoundedRect(0, 0, w, self.H, 1.5, 1.5)
        fill = max(self.H, int(w * self._frac))
        p.setBrush(QColor(C.brand_500))
        p.drawRoundedRect(0, 0, fill, self.H, 1.5, 1.5)
        p.end()


class HomePage(PageBase):
    """首页。"""

    def __init__(self, api: LocalApi, parent=None):
        super().__init__(api, parent)
        self._pending_count = 0
        self._pending_groups: list[tuple[str, str]] = []
        self._build()

    # ---------- UI 构建 ----------

    def _build(self) -> None:
        # 增量渲染账本：坑卡按稳定 key 原地复用；一级账本值供二级复用
        self._pit_tracked: dict = {}
        self._led: dict = {}
        content_lay = QVBoxLayout()
        content_lay.setSpacing(S.s6)
        content_lay.setContentsMargins(S.s8, S.s8, S.s8, S.s8)

        # ① 头部：宇航员表情 + 状态点 + 运行中 + agent chip + 最近记录行
        header = QHBoxLayout()
        header.setSpacing(S.s2)
        self._mascot_main = mascot_image("sleep", SIZES.MASCOT_STATUS)
        header.addWidget(self._mascot_main)
        dot = QFrame()
        dot.setFixedSize(D.DOT, D.DOT)
        dot.setStyleSheet(
            f"background: {C.ok_fg}; border-radius: {D.DOT // 2}px; border: none;")
        header.addWidget(dot)
        self._running_label = txt(t("运行中"), F.body, 600, C.ink_700)
        header.addWidget(self._running_label)
        header.addSpacing(S.s2)
        # agent chip 每次 refresh 重建（数量变化）
        self._chip_holder = QWidget()
        self._chip_lay = QVBoxLayout(self._chip_holder)
        self._chip_lay.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._chip_holder)
        # 最近记录行（无命中隐藏）
        self._recent_line = txt("", F.caption, color=C.ink_500)
        self._recent_line.hide()
        header.addSpacing(S.s3)
        header.addWidget(self._recent_line)
        # 尾部 stretch 吸收多余空间
        header.addStretch(1)
        content_lay.addLayout(header)

        self._build_stat_row(content_lay)
        self._build_memory_mix(content_lay)

        self._build_search_row(content_lay)

        # ③ 零状态卡（修复方案口径改：只有"机器上没有任何会话"才空态；
        # 空态是行动邀请不是接模型广告——文件捕获是默认主路）
        self._empty_btn = btn_primary(
            t("怎么用"),
            on_click=lambda: self.go("connect"),
        )
        self._empty_card = empty_state(
            title=t("还没有记录"),
            body=t("去让任意 AI 工具干个活，它的操作会自动出现在这里——"
                   "踩了什么坑、怎么改好的，一目了然"),
            button=self._empty_btn,
            mascot="think",
        )
        self._empty_card.setVisible(False)
        self._empty_title = self._empty_card.layout().itemAt(1).widget()
        self._empty_body = self._empty_card.layout().itemAt(2).widget()
        content_lay.addWidget(self._empty_card)

        # ④ 当前 agent 行（诚实语义：只表示"最近活跃的 coding agent"，
        # 不再冒充"当前模型"——具体模型/API 只有走 8100 代理才可见）
        model_row = QHBoxLayout()
        model_row.setSpacing(S.s1)
        model_ic = icon_widget("BOT_OUTLINED", 18, C.ink_500)
        model_ic.setFixedWidth(18)
        model_row.addWidget(model_ic)
        self._model_label = txt("", F.caption, color=C.ink_500)
        self._model_label.setToolTip(
            t("当前 agent 来自会话采集（24h 内最近写入会话的工具）；"
              "想看到它具体用的模型/API，需要把 base URL 接到 8100 代理"))
        model_row.addWidget(self._model_label)
        model_row.addStretch(1)
        self._agent_row = QWidget()
        self._agent_row.setLayout(model_row)
        content_lay.addWidget(self._agent_row)

        # ⑤ 本周发现
        self._findings_card = card(title=t("本周发现"))
        self._findings_title = self._findings_card.layout().itemAt(0).widget()
        self._findings_label = txt("", F.body, wrap=True)
        self._findings_card.layout().addWidget(self._findings_label)
        content_lay.addWidget(self._findings_card)

        # ⑤b 刚发现的坑（T1 洞察卡：可操作的统计，点开进会话现场——修复方案）
        self._pitfalls_card = card(title=t("刚发现的坑"), visible=False)
        self._pitfalls_title = self._pitfalls_card.layout().itemAt(0).widget()
        self._pitfalls_caption = txt(
            t("从你的 AI 工作记录里直接看出来的，不接模型也在记"),
            F.caption, color=C.ink_500)
        self._pitfalls_card.layout().addWidget(self._pitfalls_caption)
        self._pitfalls_layout = QVBoxLayout()
        self._pitfalls_layout.setSpacing(S.s2)
        self._pitfalls_card.layout().addLayout(self._pitfalls_layout)
        content_lay.addWidget(self._pitfalls_card)

        # ⑤b2 助手能自动帮你避的坑（agent_friction：不占你的经验墙，
        # 用建议口吻说"它自己会改"——价值闸门方案 /D1）
        self._friction_card = card(title=t("助手能自动帮你避的坑"), visible=False)
        self._friction_caption = txt(
            t("这些是工具自己操作不顺导致的，交给我改进，不用你操心"),
            F.caption, color=C.ink_500)
        self._friction_card.layout().addWidget(self._friction_caption)
        self._friction_layout = QVBoxLayout()
        self._friction_layout.setSpacing(S.s2)
        self._friction_card.layout().addLayout(self._friction_layout)
        content_lay.addWidget(self._friction_card)

        self._build_model_tiers(content_lay)

        # ⑥ 洞察卡（最多 2 条未处理建议；无建议不显示）
        self._insights_card = card(title=t("洞察"), visible=False)
        self._insights_title = self._insights_card.layout().itemAt(0).widget()
        self._insights_layout = QVBoxLayout()
        self._insights_layout.setSpacing(S.s2)
        self._insights_card.layout().addLayout(self._insights_layout)
        content_lay.addWidget(self._insights_card)

        # ⑦ 待总结的经验
        self._pending_card = card(title=t("待总结的经验"))
        self._pending_title = self._pending_card.layout().itemAt(0).widget()
        pl = self._pending_card.layout()
        self._pending_caption = txt(t("按任务类型分组，点右侧「总结成方法」"),
                                    F.caption, color=C.ink_500)
        pl.addWidget(self._pending_caption)
        self._pending_layout = QVBoxLayout()
        self._pending_layout.setSpacing(S.s2)
        pl.addLayout(self._pending_layout)
        content_lay.addWidget(self._pending_card)

        self._build_draft_alert(content_lay)

        # 尾部 stretch
        content_lay.addStretch(1)

        scroll = build_centered_scroll(content_lay)
        self._layout.addWidget(scroll)

    # ---------- 数据刷新 ----------

    def _build_stat_row(self, lay) -> None:
        # ② 账本三数字（修复方案 ；数据全本地零 LLM）
        # 删掉「花费估算·美元」格——只接本地模型时它结构性恒为 0.00
        # （本地/gguf 会话记 0 元但算"已计价"），占着格子却没信息量；底层花费
        # 估算与命令行 `experientia stats` 的展示都保留，删的只是首页这一格。
        self._stat_row = QHBoxLayout()
        self._stat_row.setSpacing(S.s6)
        self._stat_values: dict[str, QLabel] = {}
        self._stat_captions: dict[str, QLabel] = {}
        self._stat_cards: dict[str, QFrame] = {}
        for key, caption_text in (
            ("sessions", t("AI 干过·场")),
            ("rounds", t("协作轮次·轮")),
            ("pitfalls", t("记下的坑·个")),
        ):
            c = card()
            cl = c.layout()
            val = txt("0", F.display, 800, C.ink_900)
            self._stat_values[key] = val
            cl.addWidget(val)
            cap = txt(caption_text, F.caption, color=C.ink_500)
            self._stat_captions[key] = cap
            cl.addWidget(cap)
            self._stat_row.addWidget(c, 1)
            self._stat_cards[key] = c
        # 整行包在 widget 里以便整体显隐
        self._stat_row_widget = QWidget()
        self._stat_row_widget.setLayout(self._stat_row)
        lay.addWidget(self._stat_row_widget)

    def _build_memory_mix(self, lay) -> None:
        """记忆构成（六层存量 P1-1 的用户可见出口）。

        六层是"取用时按层捞、不全量塞给模型"的口径，但此前只有 `/api/layers`
        没有出口——用户在首页完全看不见材料堆在哪一层。形态与账本三数字同形
        （上数字、下名字），六格等宽、字号降一档（账本是主数字，这里是构成）。
        提示句只在真该动手时出现（经验攒够而方法卡为空 = 该总结成方法），
        其余情况留白，不拿解释性文案占位。
        """
        self._mix_card = card(title=t("记忆构成"), visible=False)
        self._mix_title = self._mix_card.layout().itemAt(0).widget()
        row = QHBoxLayout()
        row.setSpacing(S.s2)
        self._mix_values: dict[str, QLabel] = {}
        for code, name in _MIX_CELLS:
            c = card()
            cl = c.layout()
            val = txt("0", F.body, 700, C.ink_900)
            self._mix_values[code] = val
            cl.addWidget(val)
            cl.addWidget(txt(t(name), F.caption, color=C.ink_500))
            row.addWidget(c, 1)
        self._mix_card.layout().addLayout(row)
        self._mix_hint = txt("", F.caption, color=C.ink_500)
        self._mix_hint.setWordWrap(True)
        self._mix_hint.hide()
        self._mix_card.layout().addWidget(self._mix_hint)
        lay.addWidget(self._mix_card)

    def _build_search_row(self, lay) -> None:
        # ②b 搜索先行（修复方案 /-P1-2）：大搜索框 + 高频报错 chips，
        # "上次那个报错怎么修的"十秒可达，结果点击进会话现场抽屉
        search_row = QHBoxLayout()
        search_row.setSpacing(S.s2)
        self._search_tf = QLineEdit()
        self._search_tf.setPlaceholderText(t("搜历史会话：报错、命令、项目…"))
        self._search_tf.returnPressed.connect(self._do_search)
        search_row.addWidget(self._search_tf, 1)
        search_row.addWidget(btn_flat(t("搜索"), on_click=self._do_search))
        self._search_row_widget = QWidget()
        self._search_row_widget.setLayout(search_row)
        lay.addWidget(self._search_row_widget)
        # 示例查询 chips（取真实高频报错签名，refresh 时重建）
        self._chip_q_holder = QWidget()
        self._chip_q_lay = QHBoxLayout(self._chip_q_holder)
        self._chip_q_lay.setContentsMargins(0, 0, 0, 0)
        self._chip_q_lay.setSpacing(S.s2)
        self._chip_q_lay.addStretch(1)
        lay.addWidget(self._chip_q_holder)
        # 搜索结果卡（未搜索时隐藏）
        self._search_card = card(title=t("搜索结果"), visible=False)
        self._search_title = self._search_card.layout().itemAt(0).widget()
        self._search_layout = QVBoxLayout()
        self._search_layout.setSpacing(S.s2)
        self._search_card.layout().addLayout(self._search_layout)
        lay.addWidget(self._search_card)

    def _build_model_tiers(self, lay) -> None:
        # ⑤c 双档：先报本机已产出的量，再说接模型能更好。
        # 旧版是「接上 AI 后才有」式的锁定卡——暗示现在什么都没有，给用户
        # 整页空的观感；改为：上半「本机已可用」= 事实层（账本/坑卡/原始
        # 记录/搜索筛选）本来就不依赖模型；下半「接入模型后更强」= 归纳层
        # （方法正文/成长叙事/AI 重写）需要模型，接入是**增强**而非前提
        # （总纲）。
        self._local_card = card(title=t("本机已可用"), visible=False)
        self._local_title = self._local_card.layout().itemAt(0).widget()
        self._local_body = txt("", F.body, color=C.ink_700, wrap=True)
        self._local_card.layout().addWidget(self._local_body)
        self._local_caption = txt(
            t("搜索、筛选、原始记录、坑卡都是本机能力，不接模型也能用"),
            F.caption, color=C.ink_500, wrap=True)
        self._local_card.layout().addWidget(self._local_caption)
        lay.addWidget(self._local_card)

        self._enhance_card = card(title=t("接入模型后更强"), secondary=True,
                                  visible=False)
        self._enhance_title = self._enhance_card.layout().itemAt(0).widget()
        self._enhance_body = txt(
            t("把踩过的坑归纳成方法正文、写成长叙事、让 AI 重写总结——这些"
              "「归纳类」能力需要模型；接入后，本机攒下的记录会被整理成它们"),
            F.body, color=C.ink_700, wrap=True)
        self._enhance_card.layout().addWidget(self._enhance_body)
        _erow = QHBoxLayout()
        _erow.setSpacing(S.s2)
        self._enhance_pending_line = txt("", F.caption, color=C.ink_500)
        _erow.addWidget(self._enhance_pending_line, 1)
        self._enhance_btn = btn_flat(t("总结成方法"),
                                     on_click=self._enhance_summarize)
        _erow.addWidget(self._enhance_btn)
        _ew = QWidget()
        _ew.setLayout(_erow)
        self._enhance_card.layout().addWidget(_ew)
        lay.addWidget(self._enhance_card)

    def _build_draft_alert(self, lay) -> None:
        # ⑧ S5 经验上报待放行提示（三入口之三：首页）
        self._draft_alert = card(title=t("待放行的经验上报"), secondary=True,
                                 visible=False)
        self._draft_alert_title = self._draft_alert.layout().itemAt(0).widget()
        _dal = self._draft_alert.layout()
        _row = QHBoxLayout()
        _row.setSpacing(S.s2)
        self._draft_alert_txt = txt("", F.body, color=C.warn_fg, wrap=True)
        _row.addWidget(self._draft_alert_txt, 1)
        self._draft_alert_btn = QPushButton(t("去处理（经验库）"))
        self._draft_alert_btn.setFixedHeight(D.BTN_H_SM)
        self._draft_alert_btn.setStyleSheet(
            f"color: {C.brand_700}; font-weight: 600; border: none; "
            f"background: transparent;")
        self._draft_alert_btn.clicked.connect(lambda: self.go("mine"))
        _row.addWidget(self._draft_alert_btn)
        _w = QWidget()
        _w.setLayout(_row)
        _dal.addWidget(_w)
        lay.addWidget(self._draft_alert)

    def refresh(self) -> None:
        """首页数据刷新（分级）：9 个只读
        请求拆两级，主线程只跑渲染——30s 轮询不再每个周期冻结一个往返。

        - 一级（快）：账本 / 坑卡(rules) / 待放行草稿 / 洞察，先落首屏；
        - 二级（慢）：status（常被拖慢）/ exps / capture / growth / model_ok，
          一级渲染后延后一次取，数据到了原地补上，不闪不重排。

        并行后总耗时 ≈ max(各请求) 而非 sum；同轮导航+轮询的重复请求由
        CachedApi 合并（TTL 20s < 轮询 30s，不会变陈旧）。

        首屏骨架：4–5 个高度值按页面真实形状给（头部/三数字行/
        搜索行/坑卡/双档卡）；取数快于 SKELETON_MIN_MS 时骨架根本不显示，
        由 fetch_and_render 自动挂/撤。
        """
        self.fetch_and_render(self._fetch_fast, self._render_fast, "home",
                              skeleton=[28, 96, 44, 76, 76])

    def _fetch_fast(self) -> dict:
        """一级取数（快）：首屏先要的账本/坑卡/草稿/洞察，不等慢端点。"""
        return parallel_fetch({
            "drafts": self.api.experience_drafts,
            "ledger": self.api.ledger,
            "insights": self.api.insights,
            "rules": lambda: self.api.rule_cards(limit=40),
        })

    def _fetch_slow(self) -> dict:
        """二级取数（慢）：status 常被拖慢，连同 exps/capture/growth/model_ok
        延后一轮；双档卡的模型口径也后台探（api/models 缓存 60s，命中即零 IO）。

        六层存量（layers）放二级：它是本地统计不慢，但登上首屏只会让一级
        多一个往返，而它本就是"看一眼构成"的补充信息。
        """
        return parallel_fetch({
            "status": self.api.status,
            "exps": lambda: self.api.experiences(limit=300),
            "capture": self.api.capture_status,
            "growth": self.api.growth,
            "model_ok": lambda: self._model_available(),
            "layers": self.api.layer_inventory,
        })

    def _render_fast(self, res: dict | None) -> None:
        """一级渲染（主线程）：账本三数字 / 坑卡 / 待放行草稿 / 洞察 + 空态。

        一级不依赖 status，故不再做「本地 API 未连接」兜底（挪到二级）。渲染
        完把二级（慢）取数延后一次——首屏可见更早，慢数据随后原地补上。
        """
        res = res or {}
        led = res.get("ledger") or {}
        self._led = led if isinstance(led, dict) else {}

        # 账本三数字（数据缺 → 0，绝不给假数字）
        # 首屏从 0 滚到终值（"只首屏"在基类 set_count 里一处实现）
        self.set_count(self._stat_values["sessions"],
                       int(self._led.get("sessions") or 0))
        self.set_count(self._stat_values["rounds"],
                       int(self._led.get("rounds") or 0))
        self.set_count(self._stat_values["pitfalls"],
                       int(self._led.get("rule_cards") or 0))

        self._refresh_pitfalls(res.get("rules"))
        self._refresh_insights(insights=res.get("insights"))
        self._render_draft_alert(int((res.get("drafts") or {}).get("count", 0)))

        # 空态口径（修复方案）：只依赖账本场次（一级即有），首屏就给正确
        # 空/满态——"有会话但零经验"是正常状态（无模型时代的账本形态），
        # 绝不演成产品不能用
        show_empty = int(self._led.get("sessions") or 0) == 0
        self._stat_row_widget.setVisible(not show_empty)
        self._empty_card.setVisible(show_empty)

        # 二级（慢）紧接着另起一轮取数（工作线程，主线程仍零 HTTP）；数据到达
        # 后原地补上，不重排页头、不闪。取数工作线程不阻塞首屏绘制，故此处直接
        # 发起（不用 QTimer 延后——延后会出现 `_fetches` 瞬时为空的窗口，破坏
        # 「等取数收尾」的语义）。
        self.fetch_and_render(self._fetch_slow, self._render_slow, "home_slow")

    def _render_slow(self, res: dict | None) -> None:
        """二级渲染（主线程）：status（chip / agent 行 / recent line）、exps
        （findings / pending）、capture、growth、model_ok、layers 到的部分
        原地补上。

        status 缺失（本地 API 未连接）只跳过 status 相关行——layers 等同批
        `parallel_fetch` 取到的独立键照常渲染。 M7 之前一个早退把
        整页二级渲染连带跳过：status 单点失败时构成卡数据已拿到却被丢弃，
        且一次早退后永远不显示（卡片初建 visible=False）。
        """
        res = res or {}
        status = res.get("status")
        exps = (res.get("exps") or {}).get("items", [])
        led = self._led

        # 当前 agent = 24h 内采集到的最活跃会话工具（无则不刷存在感，
        # 语义与数据源一致：agent 名来自采集，模型/API 不在采集可见范围）
        self._refresh_agent_row(cap=res.get("capture"))
        if status is None:
            self.set_status(t("本地 API 未连接"))
        else:
            self._set_chip(len(status.get("agents", {}) or {}))
        self._refresh_recent_line(cap=res.get("capture"))
        self._refresh_findings(len(exps), growth=res.get("growth"))
        self._refresh_tiers(led, model_connected=bool(res.get("model_ok")))
        self._refresh_pending(exps)
        self._render_memory_mix(res.get("layers"))

        # 更新吉祥物表情：有发现/待总结 → surprise，全空 → sleep
        has_pending = self._pending_count > 0
        new_mascot = "surprise" if (exps or has_pending or led.get("sessions")) else "sleep"
        pm = mascot_image(new_mascot, SIZES.MASCOT_STATUS).pixmap()
        if pm is not None:
            self._mascot_main.setPixmap(pm)

    # ---------- 坑卡与双档卡（修复方案 ；渲染统一 rule_render，质量挂账） ----------

    def _refresh_pitfalls(self, rules: dict | None) -> None:
        from .rule_render import rule_display
        from ..distill import value_gate
        items = (rules or {}).get("items") or []
        # 坑卡增量渲染：按稳定 key 原地复用/增删，数据不变不重建
        want: list[tuple[str, str, object]] = []
        friction_items: list[dict] = []
        for c in items:
            # 价值闸门 A 收口：纯错误复现计数（error_sig）→"助手避坑"建议栏；
            # 结构化改出来的模式（retry_pair/pivot/revert）→"刚发现的坑"；env/garbage 不展示
            surface = str(c.get("surface") or "") or value_gate.surface_of(c)
            if surface == value_gate.SURFACE_NONE:
                continue
            if surface == value_gate.SURFACE_ADVICE:
                friction_items.append(c)
                continue
            kind, line = rule_display(c)
            rid = c.get("id")
            key = f"r:{rid}" if rid else (
                f"{c.get('agent')}\x00{c.get('session_id')}\x00{kind}")
            want.append((key, content_sig(c or {}),
                         lambda c_=c, k_=kind, l_=line:
                         self._pitfall_row(c_, k_, l_)))
        sync_tracked(self._pitfalls_layout, self._pit_tracked, want)
        # 首屏错峰入场（"只首屏"在基类 stagger_cards 里一处实现）
        self.stagger_cards(self._pitfalls_layout)
        # 避坑卡（归堆 + 折叠态，结构简单）仍全量重建：先清后渲
        self._clear_layout(self._friction_layout)
        self._render_friction(friction_items)
        self._pitfalls_card.setVisible(bool(want))
        self._render_query_chips(items)

    def _pitfall_row(self, c: dict, kind: str, line: str) -> QWidget:
        """坑卡单行（原 _refresh_pitfalls 内联逻辑抽出，供增量渲染工厂复用）。"""
        label = f"「{kind}」{line}"
        if int(c.get("sessions") or 0) > 1:
            label += f" · {t('复现 {n} 次', n=int(c.get('count') or 1))}"
        btn = QPushButton(t("查看会话"))
        btn.setFixedHeight(D.BTN_H_XS)
        btn.setStyleSheet(f"""
            QPushButton {{ background: {C.brand_50}; color: {C.brand_700};
                border: none; border-radius: {R.sm}px; font-weight: 600; }}
            QPushButton:hover {{ background: {C.brand_100}; }}
        """)
        btn.clicked.connect(lambda _=False, ag=c.get("agent"),
                            sid=c.get("session_id"): self._open_session(ag, sid))
        return list_row("EXPLORE_OUTLINED", label, trailing=btn)

    def _render_friction(self, friction_items: list[dict]) -> None:
        """避坑卡同类归堆（方案 B）：报错原文挪悬停、默认露前
        _FRICTION_SHOWN 类其余折叠、「查看会话」收成底部一个入口（跳成长页）。"""
        from .rule_render import group_friction
        buckets = group_friction(friction_items)
        self._friction_card.setVisible(bool(buckets))
        if not buckets:
            return
        total = sum(b["count"] for b in buckets)
        self._friction_caption.setText(t(
            "{c} 次小毛病归成 {k} 类，都在自动改进 · 不用你操心",
            c=total, k=len(buckets)))
        mx = buckets[0]["count"]
        rows = [self._friction_row(b, mx) for b in buckets]
        for w in rows:
            self._friction_layout.addWidget(w)
        hidden = rows[_FRICTION_SHOWN:]
        for w in hidden:
            w.setVisible(False)  # 默认折叠（页面此时已可见，须显式藏）
        if hidden:
            fold = QWidget()
            fl = QHBoxLayout(fold)
            fl.setContentsMargins(S.s2, 0, S.s2, 0)
            fl.setSpacing(S.s2)
            fl.addWidget(txt(t("还有 {n} 类 · 合计 {c} 次",
                               n=len(hidden),
                               c=sum(b["count"] for b in buckets[_FRICTION_SHOWN:])),
                            F.caption, color=C.ink_500))
            fl.addStretch(1)
            btn = btn_flat(t("展开"))

            def toggle(_checked: bool = False) -> None:
                show = not hidden[0].isVisible()
                for w in hidden:
                    w.setVisible(show)
                btn.setText(t("收起") if show else t("展开"))

            btn.clicked.connect(toggle)
            fl.addWidget(btn)
            self._friction_layout.addWidget(fold)
        link = QWidget()
        ll = QHBoxLayout(link)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addStretch(1)
        ll.addWidget(btn_flat(t("查看相关会话记录"),
                              on_click=lambda: self.go("growth")))
        self._friction_layout.addWidget(link)

    def _friction_row(self, b: dict, mx: int) -> QWidget:
        """归堆行三要素：短标题 + 建议一句话 + 次数徽章，底部占比细条；
        悬停看该桶原始报错样例（最多 3 条，数据不丢、版面不占）。"""
        row = QWidget()
        v = QVBoxLayout(row)
        v.setContentsMargins(S.s2, S.s1, S.s2, S.s1)
        v.setSpacing(S.s1)
        top = QHBoxLayout()
        top.setSpacing(S.s2)
        top.addWidget(status_dot("ok"), 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(txt(t(b["title"]), F.body, 600))
        col.addWidget(txt(t(b["advice"]), F.caption, color=C.ink_500))
        top.addLayout(col, 1)
        top.addWidget(chip(t("{n} 次", n=b["count"]), "ink"), 0, Qt.AlignTop)
        v.addLayout(top)
        v.addWidget(_RatioBar(b["count"] / mx if mx else 0.0))
        if b["samples"]:
            row.setToolTip("\n".join(b["samples"][:3]))
        return row

    def _render_query_chips(self, rule_items: list[dict]) -> None:
        """示例查询 chips：取真实高频「报错」坑卡，一点即搜（只留 code_lesson，
        标签走本地语言；AI 自己的工具摩擦/环境噪音/源码回声不当首页搜索入口）。"""
        clear_layout(self._chip_q_lay)
        for c in rule_items:
            sig = str(c.get("state") or "").strip()
            if not sig or str(c.get("rule_kind")) != "error_sig":
                continue
            # 价值闸门：friction/env/garbage 都不当"真实报错"入口（方案）
            if str(c.get("value_class") or "") in ("agent_friction", "env_transient",
                                                   "signature_garbage"):
                continue
            kw = re.sub(r"^(sig:|Error:\s*|error:\s*)+", "", sig).strip()[:20]
            b = btn_flat(t("常见报错：{kw}", kw=kw),
                         on_click=lambda _=False, text=sig[:24]: self._run_search(text))
            self._chip_q_lay.addWidget(b)
            if self._chip_q_lay.count() >= 3:  # stretch 占 1 位，chips 最多 2
                break
        self._chip_q_lay.addStretch(1)
        self._chip_q_holder.setVisible(self._chip_q_lay.count() > 1)

    def _do_search(self) -> None:
        self._run_search(self._search_tf.text())

    def _run_search(self, q: str) -> None:
        """搜索执行（后台线程）：结果渲染进搜索卡；chip 点击同步输入框。"""
        q = (q or "").strip()
        if not q:
            return
        if not self._search_tf.text().strip():
            self._search_tf.setText(q)
        self.set_status(t("正在搜索…"))

        def on_done(r: dict) -> None:
            self._render_search_results(q, (r or {}).get("items") or [])

        def on_error(err: str) -> None:
            self.set_status(t("搜索失败：{err}", err=err))

        self.run_async(lambda: self.api.search(q, limit=12), on_done, on_error)

    def _render_search_results(self, q: str, items: list[dict]) -> None:
        self._clear_layout(self._search_layout)
        self._search_title.setText(t("搜索结果：{q}", q=q[:20]))
        for it in items:
            meta = " · ".join(x for x in (
                str(it.get("agent") or ""),
                str(it.get("started_at") or "")[:10],
                str(it.get("project") or "").rsplit("/", 1)[-1]) if x)
            col = QVBoxLayout()
            col.setSpacing(S.s1)
            col.addWidget(txt(str(it.get("snippet") or "")[:160], F.body, wrap=True))
            col.addWidget(txt(meta, F.caption, color=C.ink_500))
            box = QWidget()
            box.setLayout(col)
            row = QHBoxLayout()
            row.setSpacing(S.s1)
            row.addWidget(box, 1)
            btn = QPushButton(t("打开"))
            btn.setFixedHeight(D.BTN_H_XS)
            btn.setStyleSheet(f"""
                QPushButton {{ background: {C.brand_50}; color: {C.brand_700};
                    border: none; border-radius: {R.sm}px; font-weight: 600; }}
                QPushButton:hover {{ background: {C.brand_100}; }}
            """)
            btn.clicked.connect(lambda _=False, ag=it.get("agent"),
                                sid=it.get("session_id"): self._open_session(ag, sid))
            row.addWidget(btn)
            holder = QWidget()
            holder.setLayout(row)
            self._search_layout.addWidget(holder)
        if not items:
            self._search_layout.addWidget(txt(
                t("没有找到「{q}」——换个词试试，报错原文里的词最准", q=q[:20]),
                F.caption, color=C.ink_500))
        self._search_card.setVisible(True)

    def _open_session(self, agent: str | None, sid: str | None) -> None:
        """下钻抽屉：拉取会话现场（后台线程），成功后弹只读对话框。"""
        if not agent or not sid:
            return

        def on_done(data: dict) -> None:
            from .session_drawer import SessionDrawer
            # 口径：exec 后释放（持整份转录；M8 补，
            # 与 experience_detail 同型）
            drawer = SessionDrawer(data, self)
            drawer.exec()
            drawer.deleteLater()

        self.run_async(lambda: self.api.session_view(agent, sid), on_done,
                       on_error=lambda e: self.set_status(t("读取会话失败：{err}", err=e)))

    def _refresh_tiers(self, led: dict, model_connected: bool) -> None:
        """双档卡：上半先报本机已产出的量，下半只在未接模型时亮。

        - 上半「本机已可用」：账本数字（坑/记录）真实报量；机器上还没有任何
          会话时不亮（空态卡是行动邀请，不是接模型广告）。
        - 下半「接入模型后更强」：归纳类能力的增强邀约，附待提炼片段计数；
          接入后自动收起（不刷存在感）。
        """
        n_sessions = int(led.get("sessions") or 0)
        n_pitfalls = int(led.get("rule_cards") or 0)
        self._local_body.setText(
            t("本机已整理 {p} 条坑、{s} 场记录", p=n_pitfalls, s=n_sessions))
        self._local_card.setVisible(n_sessions > 0)
        if model_connected or n_sessions <= 0:
            self._enhance_card.setVisible(False)
            return
        n = int(led.get("pending_fragments") or 0)
        self._enhance_pending_line.setText(
            t("已攒下 {n} 条待提炼片段，接入后自动整理", n=n) if n
            else t("接入后开始把本机记录归纳成方法"))
        self._enhance_card.setVisible(True)

    def _enhance_summarize(self) -> None:
        """增强卡的生成类入口：统一走 require_model 门禁。

        无模型 → 门禁弹窗引导去「接入」页，**不发蒸馏请求**；有模型 → 直接
        对第一组待总结经验开跑（与「待总结的经验」卡同一执行路径）。"""
        if not self.require_model(t("总结成方法")):
            return
        if not self._pending_groups:
            self.set_status(t("还没有待总结的经验——先让 AI 干点活"), "info")
            return
        trunk, category = self._pending_groups[0]
        self._distill(trunk, category, self._enhance_btn)

    def _render_memory_mix(self, data: dict | None) -> None:
        """六层存量渲染：全 0（或取数失败）时整卡不出现——它是补充信息，
        不该在还没积累时占一块位置，更不该显示假的 0。

        提示句的唯一判据是"经验攒够而方法卡为空"：这是六层视角能直接给出的
        行动，其余情况留白（不拿"记忆分六层"这类解释性文案占位）。
        """
        layers = (data or {}).get("layers") or {}
        if not isinstance(layers, dict) or not layers:
            self._mix_card.setVisible(False)
            return
        total = 0
        for code, _name in _MIX_CELLS:
            n = int((layers.get(code) or {}).get("count") or 0)
            total += n
            self.set_count(self._mix_values[code], n)
        self._mix_card.setVisible(total > 0)
        exps = int((layers.get("L2") or {}).get("count") or 0)
        skills = int((layers.get("L5") or {}).get("count") or 0)
        if exps >= _MIX_DISTILL_MIN and skills == 0:
            self._mix_hint.setText(t("经验攒够了，可以总结成方法"))
            self._mix_hint.show()
        else:
            self._mix_hint.hide()

    def _render_draft_alert(self, n: int) -> None:
        """S5 待放行经验提示条（处理完/忽略后即隐藏）。"""
        if n > 0:
            self._draft_alert_txt.setText(
                t("有 {n} 条经验上报待你确认", n=n))
            self._draft_alert.setVisible(True)
        else:
            self._draft_alert.setVisible(False)

    def retranslateUi(self) -> None:
        """重新应用翻译：更新所有静态文本后刷新数据。"""
        self._running_label.setText(t("运行中"))
        self._stat_captions["sessions"].setText(t("AI 干过·场"))
        self._stat_captions["rounds"].setText(t("协作轮次·轮"))
        self._stat_captions["pitfalls"].setText(t("记下的坑·个"))
        self._empty_title.setText(t("还没有记录"))
        self._empty_body.setText(t("去让任意 AI 工具干个活，它的操作会自动出现在这里——"
                                   "踩了什么坑、怎么改好的，一目了然"))
        self._empty_btn.setText(t("怎么用"))
        self._findings_title.setText(t("本周发现"))
        self._search_tf.setPlaceholderText(t("搜历史会话：报错、命令、项目…"))
        self._search_title.setText(t("搜索结果"))
        self._pitfalls_title.setText(t("刚发现的坑"))
        self._pitfalls_caption.setText(t("从你的 AI 工作记录里直接看出来的，不接模型也在记"))
        self._local_title.setText(t("本机已可用"))
        self._local_caption.setText(
            t("搜索、筛选、原始记录、坑卡都是本机能力，不接模型也能用"))
        self._enhance_title.setText(t("接入模型后更强"))
        self._enhance_body.setText(
            t("把踩过的坑归纳成方法正文、写成长叙事、让 AI 重写总结——这些"
              "「归纳类」能力需要模型；接入后，本机攒下的记录会被整理成它们"))
        self._enhance_btn.setText(t("总结成方法"))
        self._insights_title.setText(t("洞察"))
        self._pending_title.setText(t("待总结的经验"))
        self._pending_caption.setText(t("按任务类型分组，点右侧「总结成方法」"))
        # 记忆构成卡标题漏了重译——_mix_title 此前赋值后无人读，
        # 切语言后这张卡标题滞留旧语言直到重启
        if hasattr(self, "_mix_title"):
            self._mix_title.setText(t("记忆构成"))
        self.refresh()

    def _set_chip(self, n: int) -> None:
        self._clear_layout(self._chip_lay)
        self._chip_lay.addWidget(
            chip(f"{t('自动记录')} · {t('{n} 个 agent', n=n)}", "brand",
                 "SENSORS_OUTLINED"))

    def _refresh_agent_row(self, cap: dict | None = None) -> None:
        """当前 agent 行：优先"系统进程正在运行的 agent"；其次 24h 采集命中；
        都没有则隐藏整行（不显示误导"—"）。

        running_agents() 内部 subprocess.run tasklist
        （timeout=5s）不再在主线程同步调——先显示「检测中…」占位，进程探测
        挪到 run_async 后台线程（8s TTL 缓存保留）；探测失败降级采集命中。"""
        self._model_label.setText(t("检测中…"))
        self._agent_row.setVisible(True)

        def on_done(running: list) -> None:
            if running:
                labels = "、".join(agent_display_name(n) for n in running)
                self._model_label.setText(t("正在运行：{agents}", agents=labels))
            else:
                self._render_capture_agent(cap)

        def on_error(_err: str) -> None:
            self._render_capture_agent(cap)

        self.run_async(running_agents, on_done, on_error)

    def _render_capture_agent(self, cap: dict | None) -> None:
        """进程探测无命中/失败 → 回退 24h 采集最活跃 agent（无则隐藏整行）。"""
        try:
            cap_data = cap if cap is not None else self.api.capture_status()
        except Exception as exc:  # 回退不再静默，留痕便于排查"引擎未连/取数失败"
            _logger.debug("采集状态取数失败，回退空： %s", exc)
            cap_data = {}
        best_agent, best_n = None, 0
        for name, a in (cap_data.get("agents") or {}).items():
            n24 = int(a.get("hits_24h") or 0)
            if n24 > best_n:
                best_agent, best_n = name, n24
        try:
            if best_agent:
                self._model_label.setText(
                    t("当前 agent：{agent}", agent=best_agent))
                self._agent_row.setVisible(True)
            else:
                self._agent_row.setVisible(False)
        except Exception as exc:  # UI 更新异常留痕，不再吞掉
            _logger.debug("采集 agent 行渲染异常： %s", exc)

    def _refresh_recent_line(self, cap: dict | None = None) -> None:
        """W1-07：24h 内有命中的最活跃 agent；无命中不显示，不刷存在感。"""
        recent_line = None
        try:
            best_agent, best_n = None, 0
            agents_map = cap if cap is not None else self.api.capture_status()
            for name, a in (agents_map.get("agents") or {}).items():
                n24 = int(a.get("hits_24h") or 0)
                if n24 > best_n:
                    best_agent, best_n = name, n24
            if best_agent:
                recent_line = t("最近记录：{agent} {n} 次",
                                agent=best_agent, n=best_n)
        except Exception as exc:  # 取数失败不再静默，留痕
            _logger.debug("最近记录行取数异常： %s", exc)
        if recent_line:
            self._recent_line.setText(recent_line)
            self._recent_line.show()
        else:
            self._recent_line.hide()

    def _refresh_findings(self, n_exps: int, growth: dict | None = None) -> None:
        """P3-05 本周发现：有真实进步数据才显示话术（v2 口径 = 磨合差值，
）；否则给预期不给假数字。"""
        body = None
        try:
            best = None
            g = growth if growth is not None else self.api.growth()
            for key, a in (g.get("affinity") or {}).items():
                if (a.get("n", 0) >= 3 and not a.get("excluded")
                        and int(a.get("diff") or 0) >= 1
                        and (best is None or a["diff"] > best["diff"])):
                    best = (key, a)
            if best:
                key, a = best
                # affinity 键 = agent/trunk/category，主角名 = agent·category
                cat = affinity_display(key)
                body = t("你在『{name}』上比最初几次平均少 {n} 轮修正（基线后 5 次）",
                         name=cat, n=a["diff"])
        except Exception:
            _logger.warning("成长数据加载失败，按空数据对待")
        if body is None:
            body = t("数据积累中：再完成 {n} 次同类任务，就能看到熟练度变化",
                     n=max(1, 3 - n_exps))
        self._findings_label.setText(body)
        # 设计方案 F-B3：无有效数据时也显示（不隐藏，给预期话术）

    def _refresh_insights(self, insights: dict | None = None) -> None:
        """W4-04：洞察行（最多 2 条未处理建议 + 三选一；无建议不显示）。"""
        try:
            d = insights if insights is not None else self.api.insights()
            items = d.get("items", [])[:2]
        except Exception:
            items = []
        self._clear_layout(self._insights_layout)
        for c in items:
            row = QHBoxLayout()
            row.setSpacing(S.s1)
            row.addWidget(txt(c.get("text", ""), F.body), 1)
            row.addWidget(btn_flat(
                t("应用"), on_click=lambda _=False, c_=c: self._insight_act(c_, "apply")))
            row.addWidget(btn_flat(
                t("忽略"), on_click=lambda _=False, c_=c: self._insight_act(c_, "dismiss")))
            row.addWidget(btn_flat(
                t("稍后"), on_click=lambda _=False, c_=c: self._insight_act(c_, "defer")))
            box = QWidget()
            box.setLayout(row)
            self._insights_layout.addWidget(box)
        self._insights_card.setVisible(bool(items))

    def _insight_act(self, c: dict, action: str) -> None:
        """后台执行洞察操作，完成后重刷洞察区。"""
        self.run_async(
            lambda: self.api.insight_act(c["id"], action),
            on_done=lambda _r: self._refresh_insights(),
            on_error=lambda _e: self._refresh_insights(),
        )

    def _refresh_pending(self, exps: list[dict]) -> None:
        """待蒸馏：按 (trunk, category) 分组。"""
        pending: dict[tuple[str, str], int] = {}
        for e in exps:
            if e.get("distilled"):
                continue
            key = (e.get("trunk") or "?", e.get("category") or "?")
            pending[key] = pending.get(key, 0) + 1
        self._pending_count = sum(pending.values())
        self._pending_groups = [k for k, _n in sorted(pending.items())]
        self._clear_layout(self._pending_layout)
        for (trunk, category), n in sorted(pending.items()):
            btn = QPushButton(t("总结成方法"))
            btn.setFixedHeight(D.BTN_H_XS)
            btn.setStyleSheet(f"""
                QPushButton {{ background: {C.brand_50}; color: {C.brand_700};
                    border: none; border-radius: {R.sm}px; font-weight: 600; }}
                QPushButton:hover {{ background: {C.brand_100}; }}
                QPushButton:disabled {{ color: {C.ink_500}; background: {C.surface_2}; }}
            """)
            btn.clicked.connect(
                lambda _=False, t_=trunk, c_=category, b=btn: self._distill(t_, c_, b))
            self._pending_layout.addWidget(list_row(
                "AUTO_AWESOME_OUTLINED",
                t("{trunk} / {category}：{n} 条", trunk=trunk, category=category, n=n),
                trailing=btn))
        # 设计方案 U-B4：无待总结时整卡隐藏
        self._pending_card.setVisible(bool(pending))

    def _distill(self, trunk: str, category: str, btn: QPushButton) -> None:
        """后台蒸馏；成功显示 ✓ 总结完成，4 秒后整页刷新。

        无模型 → 门禁拦截（require_model）或引擎回 ``model_required``
        结构化拒绝；两者都不产出任何正文（不做本机兜底）。"""
        if not self.require_model(t("总结成方法")):
            return
        btn.setText(t("正在总结…"))
        btn.setEnabled(False)

        def on_done(r) -> None:
            if self._reject_model_required(r):
                btn.setText(t("总结成方法"))
                btn.setEnabled(True)
                return
            btn.setText(f"✓ {t('总结完成')}")
            QTimer.singleShot(4000, self._safe_refresh_later)

        def on_error(err: str) -> None:
            btn.setText(t("总结失败：{err}", err=err))
            btn.setEnabled(True)

        self.run_async(lambda: self.api.distill(trunk, category), on_done, on_error)

    def _safe_refresh_later(self) -> None:
        """蒸馏完成 4s 后的延时刷新：页面可能已被
        语言/主题切换销毁（_rebuild_visited_pages → deleteLater），
        C++ 对象失效时静默跳过，不把 RuntimeError 抛进 Qt 事件循环。"""
        try:
            self.refresh()
        except RuntimeError:
            pass

    def _reject_model_required(self, r) -> bool:
        """引擎返回 ``status == "model_required"`` → 如实告知，不假装已总结。"""
        if not isinstance(r, dict) or r.get("status") != "model_required":
            return False
        msg = str(r.get("message") or t("未接入模型，无法归纳成方法"))
        if r.get("kept_previous"):
            msg = f"{msg} {t('已保留上次内容')}"
        self.set_status(msg, "warn")
        self.toast(msg)
        return True

    # ---------- 工具 ----------

    @staticmethod
    def _clear_layout(lay: QVBoxLayout) -> None:
        clear_layout(lay)