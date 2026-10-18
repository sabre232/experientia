"""成长页：阶段结论 → 飞轮五格 → 磨合时间图 →
经验账本 + 欠账 → 助手避坑 → 过程记录（折叠）。

三条口径铁律（设计走查的 blocker/major 落点）：
- **时间轴吃 sessions**：experience.jsonl 的 ts 是"入库当天"，回灌后全同一天，
  旧版据此显示"最近活跃 1 天"、热力图 13 空格 1 实心；会话记录才跨多周。
- **资产口径与首页同源**：走 value_gate.surface_of 拆「你的经验 / 助手能帮你
  避的坑」，不再报"累计经验 82 条"这种把 AI 手滑算进用户成长的混数。
- **按经验记录聚合**：热力条/日柱/累积横条三块图取自
  `store.growth_summary` 的 heatmap + cumulative——两者都由 experience.jsonl
  自身的 trunk/category 派生，与"有没有模型"无关（缺省兜底其他/未分类也出数）。
  模型可用时方法/技能维度仍作为增强叠加在过程记录里，不替代这三块。
  零纠正 = "本来就顺"，不再拿黄色"低"档冒充结论。

图表走 qt_theme 的 rework_chart / heat_bar / columns_chart / hbar_row。
"""

from __future__ import annotations

import re
from datetime import datetime

from PySide6.QtCore import Property, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu,
                               QVBoxLayout, QWidget)

from . import report_view
from .api_client import LocalApi, LocalApiError
from .i18n import current_language, t
from .page_base import (PageBase, clear_layout, content_sig, page_scaffold,
                        parallel_fetch, sync_tracked)
from .qt_dialogs import confirm_dialog, input_dialog, rich_info_dialog
from .qt_theme import (btn_flat, btn_secondary, card, chip, collapse_header,
                       columns_chart, ellipsis_button, empty_state, hbar_row,
                       heat_bar, rework_chart, status_dot, status_text,
                       status_tone, txt)
from .timeline import _TlRail, TimelineMixin
from .qt_widgets import RotatingIcon, page_header
from .theme import C, D, F, R, S

# 页面叙事常量（写死在展示层，不进数据层）
_INJECT_TARGET = 20    # 第⑤格出数所需的最低真实取用次数
_MIN_WEEKS_HINT = 5    # 返工对比至少要有记录的周数（与 store 口径一致）
_AGG_TOP_CATS = 6      # 聚合卡「按任务类型」最多列几类
_AGG_LABEL_MIN = 56    # 类别标签列宽下界（实测最宽，夹在 [min, max]）
_AGG_LABEL_MAX = 168


def _tail_val(seq) -> float:
    """取累积序列的末端值。

    ``cumulative`` 每项是逐日 ``(日期, 累积条数)`` 序列；引擎返回若缺字段或
    结构退化（空序列 / 元素不是二元结构 / 不可转数值），一律按 0 计——聚合图
    少一根柱子可以接受，整块成长页因一处取值抛异常而落到空状态不行。
    """
    try:
        tail = seq[-1]
        val = tail[1] if isinstance(tail, (list, tuple)) else tail
        return float(val or 0)
    except (IndexError, TypeError, ValueError):
        return 0.0


def _at(seq, i: int) -> float:
    """按天取值（热力条跨主干合计时用；序列长度不足补 0，不打越界异常）。"""
    try:
        return float(seq[i] or 0)
    except (IndexError, TypeError, ValueError):
        return 0.0


def _page_qss() -> str:
    """本页统一 QSS：替代十余处逐行 setStyleSheet。

    必须在**调用时**拼（不能做成模块常量）——`C.*` 由 `_PaletteMeta` 动态解析，
    模块级求值会把亮色板冻死（暗色模式下失配）。规则全部 id 限定，不写宽选择器，
    避免压掉 APP_STYLESHEET 里按钮/卡片的类选择器规则。
    """
    return f"""
QFrame#growthHero {{
    background: {C.surface_hero};
    border: 1px solid {C.brand_200};
    border-radius: {R.lg}px;
}}
QFrame#statDivider {{
    color: {C.line}; background: {C.line}; border: none;
}}
QFrame#gearCell[tone="done"] {{
    background: {C.brand_50}; border: 1px solid {C.brand_200};
    border-radius: {R.md}px;
}}
QFrame#gearCell[tone="bad"] {{
    background: {C.err_bg}; border: 1px solid {C.err_bg};
    border-radius: {R.md}px;
}}
QFrame#gearCell[tone="idle"] {{
    background: {C.surface}; border: 1px solid {C.line_strong};
    border-radius: {R.md}px;
}}
QFrame#phaseBand {{
    background: {C.surface_2}; border: 1px solid {C.line};
    border-radius: {R.md}px;
}}
QLabel#scoreBadge {{
    background: {C.surface_2}; color: {C.ink_700}; border: none;
    border-radius: {R.sm}px; font-size: {F.caption}px; font-weight: 800;
}}
QLabel#scoreBadge[hi="true"] {{
    background: {C.primary_fill}; color: {C.on_brand};
}}
QFrame#methodCell {{
    background: {C.surface_2}; border: 1px solid {C.line_strong};
    border-radius: {R.lg}px;
}}
QFrame#aggBlock {{
    background: {C.surface_2}; border: 1px solid {C.line};
    border-radius: {R.md}px;
}}
QWidget#tlDayFold, QWidget#tlGroup, QWidget#tlRow,
QWidget#tlSrcFold, QWidget#tlSrcRow {{
    background: transparent; border-radius: {R.md}px;
}}
QWidget#tlDayFold:hover, QWidget#tlGroup:hover, QWidget#tlRow:hover,
QWidget#tlSrcFold:hover, QWidget#tlSrcRow:hover {{
    background: {C.surface_2};
}}
"""


class GrowthPage(TimelineMixin, PageBase):
    """成长页：阶段结论 + 飞轮五格 + 磨合时间图 + 经验账本 + 过程记录。"""

    def __init__(self, api: LocalApi, parent: QWidget | None = None):
        super().__init__(api, parent)
        self._proc_open = False   # 过程记录折叠状态（重开页保持）
        self._model_ok = True     # 模型可用性（refresh 时探一次，探不到按可用）
        self._hook: dict = {}     # 回灌通道状态（configured / observed）
        self._poster_days = 30    # 海报窗口：跟随页面实际覆盖的阶段跨度
        # 入场动画指纹：数据没变就不重放——本页在 LIVE_PAGES 轮询里，
        # 每 30s 一次 refresh，逐次重放动画会变成持续闪烁。
        self._viz_sig: tuple | None = None
        self._tl_sig: tuple | None = None
        self._tl_animate_pending = False
        self._tl_anim = False   # 本轮重建是否播轨道入场（展开/收起不重播）
        self._blocks: dict[str, dict] = {}  # 增量 diff：块 key → {w, sig}
        self._build()

    # ---------- UI ----------

    def _build(self) -> None:
        """构建静态 UI（数据在 refresh 中加载，不在构造函数发请求）。"""
        # 页级统一 QSS：本页所有自定义皮肤规则集中在此
        self.setStyleSheet(_page_qss())
        cl = QVBoxLayout()
        cl.setSpacing(S.s6)

        # 统一页头（S1）：标题 + 覆盖区间（副标题）+ 两个次按钮。
        # 区间即"本阶段"的上下文（海报共用它），故与页头同处一屏。
        # 本周结算卡：通知负责提醒，这张卡负责看懂
        self._growth_week_btn = btn_secondary(t("本周结算"))
        self._growth_week_btn.clicked.connect(self._open_weekly)
        # 融合后唯一 #：海报作为“生成/导出图片”入口；里程碑庆祝只在生成海报时
        # 弹（用户主动触发才有上下文），进页不再自动弹遮罩
        self._growth_poster_btn = btn_secondary(t("生成本阶段海报"))
        self._growth_poster_btn.clicked.connect(self._open_poster)
        head = page_header(t("成长"), actions=[self._growth_week_btn,
                                             self._growth_poster_btn])
        self._growth_title = head.findChild(QLabel, "pageTitle")
        cl.addWidget(head)
        # 区间标签独立一行（内容由 refresh 动态填，故不并入页头副标题槽）
        self._growth_range = txt("", F.caption, color=C.ink_500)
        cl.addWidget(self._growth_range)

        # 行内状态行（与主窗口状态行同步显示）
        self._status_local = status_text("", tone="ok")
        cl.addWidget(self._status_local)

        # 数据区（refresh 重建）
        self._body = QVBoxLayout()
        cl.addLayout(self._body)
        cl.addStretch(1)

        # S2：统一骨架（顶边 32px 由页头给）
        self._layout.addWidget(page_scaffold(cl, top=0))

    def _open_poster(self) -> None:
        """海报窗口 = 本页正在展示的阶段跨度（不再写死 30 天）。"""
        report_view.open_growth_report(self.api, self._poster_days, self)

    def _open_weekly(self) -> None:
        """本周结算卡（服务端 peek 只读，不触发成就判定与推送）。"""
        from .weekly_card import open_weekly_card

        open_weekly_card(self.api, self)

    def _set_status(self, msg: str, tone: str = "err") -> None:
        """写主窗口状态行 + 本页行内状态行。"""
        self.set_status(msg, tone)
        self._status_local.setText(msg)
        color = {"ok": C.ok_fg, "err": C.err_fg,
                 "warn": C.warn_fg, "info": C.info_fg}[tone]
        # 保留 txt() 内联字号（status_tone 只改色，见 qt_theme）
        status_tone(self._status_local, color)

    # ---------- 数据 ----------

    def refresh(self) -> None:
        """：4 段只读取数挪后台线程，主线程只渲染——
        本页在 LIVE_PAGES 轮询里，旧写法每个周期冻结一次 growth+skills。"""
        # S5：补首屏骨架（与其它数据页口径一致）——此前本页取数期间无任何占位
        self.fetch_and_render(self._fetch, self._render_all,
                              skeleton=[24, 96, 88, 120, 96])

    def _fetch(self) -> dict:
        return parallel_fetch({
            "growth": self.api.growth,
            "skills": self.api.skills,
            # 模型可用性只探一次（欠账卡用它说"为什么分类还没长出来"）；
            # 探不到（接口异常）按可用处理——宁可少提示，不误报熔断。
            "model_ok": lambda: self._model_available_safe(),
            # 回灌通道状态（欠账卡用它说清第④格卡在哪一步）；探不到按未知
            "hook": self.api.hooks_config,
        })

    def _model_available_safe(self) -> bool:
        try:
            return bool(self._model_available())
        except Exception:
            return True

    def _render_all(self, res: dict | None) -> None:
        res = res or {}
        g = res.get("growth")
        if g is None:
            self._set_status(t("本地 API 未连接"))
            return
        self._model_ok = bool(res.get("model_ok"))
        hook = res.get("hook")
        self._hook = hook if isinstance(hook, dict) and hook else {}
        skills = (res.get("skills") or {}).get("items", [])
        self._render(g, skills)

    def _render(self, g: dict, skills: list) -> None:
        hm = g.get("heatmap", {})
        trunks = hm.get("trunks", [])
        cum = g.get("cumulative", {})
        aff = g.get("affinity", {})
        nodes = g.get("changelog", [])
        stage = g.get("stage") or {}
        weekly = g.get("weekly") or []

        # 有数据 = 任一口径有料。账本/避坑同属事实层（零模型也在），不能被
        # "还没有会话"一起清空——否则只有经验记录的新装机看到的是空壳。
        has_data = bool(stage.get("sessions") or trunks or cum or aff or nodes
                        or g.get("ledger") or g.get("advice_items"))
        # 标题旁的覆盖区间 + 海报窗口跟着阶段跨度走
        if stage.get("start"):
            self._growth_range.setText(
                t("本阶段 {a} – {b} · {w} 周", a=stage["start"],
                  b=stage.get("end", ""), w=stage.get("weeks", 0)))
            self._poster_days = max(7, min(365, int(stage.get("weeks", 0)) * 7))
        else:
            self._growth_range.setText("")

        if not has_data:
            sync_tracked(self._body, self._blocks, [(
                "__empty__", "empty",
                lambda: empty_state(
                    t("数据积累中"),
                    t("用 agent 干活后这里会出现成长曲线"),
                    mascot="think"))])
            return

        # 动画指纹：与上一次渲染一致 → 不重放（轮询 refresh 不得持续闪烁）
        viz_sig = (self._poster_days,
                   tuple((w.get("week"), w.get("sessions"), w.get("corrections"))
                         for w in weekly),
                   tuple(sorted((k, _tail_val(s))
                                for k, s in cum.items())),
                   tuple(sorted((tr, tuple(v))
                                for tr, v in (hm.get("grid") or {}).items())))
        animate = viz_sig != self._viz_sig
        self._viz_sig = viz_sig
        tl_sig = tuple((n.get("idx"), n.get("ts")) for n in nodes)
        self._tl_animate_pending = bool(nodes) and tl_sig != self._tl_sig
        self._tl_sig = tl_sig

        # 七大块按 key + 数据签名增量同步（替代原来的「清空 + 全建」）：
        # 只有数据真的变了的块才重建，其余控件原地不动——不丢 hover、不丢
        # 过程记录的折叠状态，也不会每 30s 轮询把整页重建一遍。
        # 签名取自各块真实消费的数据，factory 返回的控件不得为 None（下面
        # 每个块的准入条件都与其构造函数的返回 None 条件严格对齐）。
        want: list[tuple[str, str, object]] = []
        # ① 阶段结论（会话口径：时间与返工；没有会话就没有这条时间线）
        if stage.get("sessions"):
            want.append((
                "hero", content_sig((stage, g.get("assets"), g.get("rework"))),
                lambda g_=g: self._hero_card(g_)))
            # ② 飞轮五格（转到哪一格、断在哪一格）
            want.append(("gears", content_sig(g.get("flywheel")),
                         lambda g_=g: self._gears_card(g_)))
            # ③ 磨合时间图（周柱 + 返工率折线）
            if weekly:
                want.append((
                    "chart",
                    content_sig((weekly, g.get("rework"), g.get("flywheel"), stage)),
                    lambda g_=g, a=animate: self._chart_card(g_, a)))
        # ④ 按经验记录自身的 trunk/category 聚合（零模型也在的事实层）
        # 准入条件与 _aggregate_card 的「无数据返回 None」一致
        if cum or (hm.get("grid") or {}):
            want.append((
                "agg", content_sig((cum, hm.get("grid"))),
                lambda g_=g, a=animate: self._aggregate_card(g_, a)))
        # ⑤ 经验账本 + 侧栏（欠账摊开 / 各助手磨合）
        if g.get("ledger") or g.get("agents") or stage.get("sessions"):
            want.append((
                "ledger", content_sig((g.get("ledger"), g.get("agents"))),
                lambda g_=g: self._ledger_row(g_)))
        # ⑥ 助手能自动帮你避的坑（与首页同口径，不占"你的经验"）
        if g.get("advice_items"):
            want.append(("advice", content_sig(g.get("advice_items")),
                         lambda g_=g: self._advice_card(g_)))
        # ⑦ 过程记录（学习历程 / 方法沉淀 / 后台整理）——默认折叠，不跟主角抢地方
        want.append(("process", content_sig((skills, nodes)),
                     lambda g_=g, s_=skills, n_=nodes: self._process_card(g_, s_, n_)))
        sync_tracked(self._body, self._blocks, want)
        # 首屏错峰入场（"只首屏"在基类 stagger_cards 里一处实现）
        self.stagger_cards(self._body)

    @staticmethod
    def _wrap_title(box: QWidget) -> QWidget:
        """窄栏卡片标题允许折行（card() 标题默认不折，侧栏长句会被裁掉）。"""
        item = box.layout().itemAt(0)
        lab = item.widget() if item else None
        if isinstance(lab, QLabel):
            lab.setWordWrap(True)
        return box

    # ---------- ① 阶段结论 ----------

    def _hero_card(self, g: dict) -> QWidget:
        """一句话结论 + 四个支撑数字（先给答案，再摊证据）。"""
        st = g.get("stage") or {}
        a = g.get("assets") or {}
        rw = g.get("rework") or {}
        box = QFrame()
        box.setObjectName("growthHero")
        v = QVBoxLayout(box)
        v.setContentsMargins(S.s6, S.s6, S.s6, S.s6)
        v.setSpacing(S.s2)
        v.addWidget(txt(t("阶段结论 · 自动生成"), F.caption, color=C.ink_500))
        v.addWidget(txt(
            t("你带着 {n} 个 AI 助手跑了 {s} 次活，攒下 {e} 条真算你的经验",
              n=st.get("agents", 0), s=st.get("sessions", 0),
              e=a.get("experience", 0)), F.display, 800, wrap=True))
        # 两句分开摆：拼成一行会在拉丁语里少个空格（"…(84% less)Strictly…"）
        for line in self._hero_sub(g):
            v.addWidget(txt(line, F.body, color=C.ink_500, wrap=True))
        v.addSpacing(S.s2)
        recent = rw.get("recent")
        stats = [
            (f"{st.get('sessions', 0)}", t("次任务"),
             t("{n} 个助手 · {p} 个项目", n=st.get("agents", 0),
               p=st.get("projects", 0))),
            (f"{st.get('active_days', 0)}", t("天"),
             t("{w} 周里活跃 {d} 天", w=st.get("weeks", 0),
               d=st.get("active_days", 0))),
            (f"{a.get('experience', 0)}", t("条"),
             t("你的经验（{n} 条 ≥8 分）", n=self._high_count(a))),
            (recent if recent is not None else "—", t("回/次"),
             t("最近平均返工")),
        ]
        v.addLayout(self._stat_row(stats))
        return box

    @staticmethod
    def _high_count(a: dict) -> int:
        """≥8 分条数（store.assets.high）。"""
        return int(a.get("high") or 0)

    def _hero_sub(self, g: dict) -> list[str]:
        """结论副句（一到两行）：有数就说数，没回灌就点破"功劳还不能记在经验头上"。"""
        rw = g.get("rework") or {}
        fw = g.get("flywheel") or {}
        if not rw.get("comparable"):
            return [t("还在攒样本：同类任务多做几次，这里就能告诉你返工有没有变少。")]
        early, recent, drop = rw.get("early"), rw.get("recent"), rw.get("drop_pct")
        args = {"e": early, "r": recent}
        line = (t("返工确实少了：最早每次任务平均纠正 {e} 回，最近 {r} 回（少 {p}%）。",
                  p=drop, **args) if drop else
                t("返工确实少了：最早每次任务平均纠正 {e} 回，最近 {r} 回。", **args))
        if not fw.get("injected"):
            return [line, t("不过严格讲，这功劳还不能记在经验头上——它们一次都没被带回"
                            "给你的助手，见下面第 ④ 格。")]
        return [line, t("这段时间经验被带回给助手 {n} 次。", n=fw.get("injected"))]

    def _stat_row(self, stats: list[tuple]) -> QHBoxLayout:
        """一行大数字 + 小注（竖线分隔），数字走 tabular 对齐。

        M2：数字走 `set_count`（首屏从 0 滚到终值）；非数字（如 "—"）由它兜底直写。
        故本方法从 `@staticmethod` 改为实例方法（要 `self.set_count`）。
        """
        row = QHBoxLayout()
        row.setSpacing(S.s6)
        for i, (val, unit, note) in enumerate(stats):
            col = QVBoxLayout()
            col.setSpacing(S.s1)
            vh = QHBoxLayout()
            vh.setSpacing(S.s1)
            num = txt(str(val), F.h1, 800)
            self.set_count(num, val, size=F.h1)
            vh.addWidget(num)
            vh.addWidget(txt(unit, F.caption, 600, C.ink_500), 0, Qt.AlignBottom)
            vh.addStretch(1)
            col.addLayout(vh)
            lab = txt(note, F.caption, color=C.ink_500, wrap=True)
            col.addWidget(lab)
            wrap = QWidget()
            wrap.setLayout(col)
            row.addWidget(wrap, 1)
            if i < len(stats) - 1:
                line = QFrame()
                line.setObjectName("statDivider")
                line.setFrameShape(QFrame.VLine)
                row.addWidget(line, 0)
        return row

    # ---------- ② 飞轮五格 ----------

    _GEAR_DOT = {"done": "ok", "bad": "err", "idle": "ink"}

    def _gears_card(self, g: dict) -> QWidget:
        """经验飞轮五格：收进来 → 提炼出 → 判轻重 → 带回给 AI → 少返工。

        第④格（回灌）此前在页面上完全不可见——injection.log 缺失被当成
        "没有这回事"，而不是"这一格还没转"。现在它是一级信息。"""
        fw = g.get("flywheel") or {}
        injected = int(fw.get("injected") or 0)
        improved = fw.get("improved")
        cells = [
            (t("① 收进来"), f"{fw.get('collected', 0)}", t("次"),
             t("你干的活都被看见，不用手动记"), "done"),
            (t("② 提炼出"), f"{fw.get('distilled', 0)}", t("条"),
             t("从这些活里总结出可复用的做法"),
             "done" if fw.get("distilled") else "idle"),
            (t("③ 判轻重"), f"{fw.get('judged', 0)}", t("条"),
             t("AI 打了重要性分"), "done" if fw.get("judged") else "idle"),
            (t("④ 带回给 AI"), f"{injected}", t("次"),
             t("还没接到你的助手会话里 —— 当前最该修的一环") if not injected
             else t("这些经验已被助手取用"),
             "done" if injected else "bad"),
            (t("⑤ 少返工"), f"−{improved}%" if improved else "—", "",
             t("等第 ④ 格跑起来，这里给同类任务的对比") if improved is None
             else t("同类任务返工降幅"),
             "done" if improved else "idle"),
        ]
        box = card(title=t("经验飞轮转到哪一格了"))
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(S.s4)
        for i, (k, val, unit, note, tone) in enumerate(cells):
            hl.addWidget(self._gear_cell(k, val, unit, note, tone), 1)
            if i < len(cells) - 1:
                hl.addWidget(txt("›", F.h2, 600, C.ink_300), 0, Qt.AlignVCenter)
        box.layout().addWidget(row)
        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(S.s3)
        if not injected:
            fl.addWidget(txt(
                t("第 ④ 格为什么是 0：你的助手还没从这里取过经验。接上之后每次开工"
                  "它先带着这些教训，你不用重复交代。"), F.caption,
                color=C.ink_500, wrap=True), 1)
            btn = btn_secondary(t("看怎么接上"))
            btn.clicked.connect(lambda: self.go("connect"))
            fl.addWidget(btn, 0, Qt.AlignVCenter)
        else:
            fl.addWidget(txt(
                t("经验已用上 {n} 次；样本攒够后第 ⑤ 格会给出同类任务的返工对比。",
                  n=injected), F.caption, color=C.ink_500, wrap=True))
        box.layout().addWidget(foot)
        return box

    def _gear_cell(self, label: str, value: str, unit: str, note: str,
                   tone: str) -> QWidget:
        cell = QFrame()
        cell.setObjectName("gearCell")
        # 格态走动态属性（页级 QSS 的 [tone=...] 规则），不再逐格 setStyleSheet
        cell.setProperty("tone", tone)
        cell.style().unpolish(cell)
        cell.style().polish(cell)
        v = QVBoxLayout(cell)
        v.setContentsMargins(S.s3, S.s3, S.s3, S.s3)
        v.setSpacing(S.s1)
        head = QHBoxLayout()
        head.setSpacing(S.s2)
        head.addWidget(status_dot(self._GEAR_DOT[tone]), 0, Qt.AlignVCenter)
        head.addWidget(txt(label, F.caption, 600, C.ink_700))
        head.addStretch(1)
        v.addLayout(head)
        vh = QHBoxLayout()
        vh.setSpacing(S.s1)
        vh.addWidget(txt(value, F.h2, 800))
        if unit:
            vh.addWidget(txt(unit, F.caption, 600, C.ink_500), 0, Qt.AlignBottom)
        vh.addStretch(1)
        v.addLayout(vh)
        v.addWidget(txt(note, F.caption, color=C.ink_500, wrap=True))
        return cell

    # ---------- ③ 磨合时间图 ----------

    def _chart_card(self, g: dict, animate: bool = False) -> QWidget:
        """周柱（任务量）+ 折线（返工率）：要的成长曲线，吃会话口径。"""
        rw = g.get("rework") or {}
        st = g.get("stage") or {}
        box = card(title=t("你干活的量 vs 要你返工的次数"))
        leg = QWidget()
        ll = QHBoxLayout(leg)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(S.s2)
        ll.addWidget(status_dot("brand"), 0, Qt.AlignVCenter)
        ll.addWidget(txt(t("每周任务数"), F.caption, color=C.ink_500))
        ll.addSpacing(S.s3)
        ll.addWidget(status_dot("info"), 0, Qt.AlignVCenter)
        ll.addWidget(txt(t("平均每个任务被你纠正几回"), F.caption,
                         color=C.ink_500))
        ll.addStretch(1)
        ll.addWidget(txt(
            t("覆盖 {a} – {b}", a=st.get("start", ""), b=st.get("end", "")),
            F.caption, color=C.ink_500))
        box.layout().addWidget(leg)
        chart = rework_chart(g.get("weekly") or [])
        box.layout().addWidget(chart)
        if animate:
            chart.animate_in()

        read = QWidget()
        rl = QHBoxLayout(read)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(S.s6)
        rl.addWidget(self._chart_note(
            t("变顺只发生了一次") if rw.get("comparable") else t("还在攒样本"),
            self._chart_left(g)), 1)
        rl.addWidget(self._chart_note(t("为什么平了，以及还不能算证据"),
                                      self._chart_right(g)), 1)
        box.layout().addWidget(read)
        box.layout().addWidget(self._phase_band(g.get("phases") or []))
        return box

    @staticmethod
    def _chart_note(title: str, body: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(S.s1)
        v.addWidget(txt(title, F.h2, 700, C.ink_700))
        v.addWidget(txt(body, F.caption, color=C.ink_500, wrap=True))
        return w

    def _chart_left(self, g: dict) -> str:
        rw = g.get("rework") or {}
        if not rw.get("comparable"):
            return t("有记录的周还不够多（需要至少 {n} 个），先继续用助手干活。",
                     n=_MIN_WEEKS_HINT)
        return t("头 {e} 次任务你纠正了 {er} 回（平均 {early} 回/次），"
                 "最近 {r} 次任务只纠正 {rr} 回（{recent} 回/次）。",
                 e=rw.get("early_n", 0), er=rw.get("early_corr", 0),
                 early=rw.get("early"), r=rw.get("recent_n", 0),
                 rr=rw.get("recent_corr", 0), recent=rw.get("recent"))

    def _chart_right(self, g: dict) -> str:
        fw = g.get("flywheel") or {}
        st = g.get("stage") or {}
        injected = int(fw.get("injected") or 0)
        first = (t("经验一次都没被带回给助手，降下来靠的是你自己反复交代")
                 if not injected else
                 t("经验已被助手取用 {n} 次，效果还要再攒样本", n=injected))
        return t("{a}；{b} 次任务还都在“未分类”一个桶里，没法按同类任务做"
                 "严格对比 —— 这条线现在只能当参考，不能当证据。",
                 a=first, b=st.get("sessions", 0))

    @staticmethod
    def _phase_band(phases: list[dict]) -> QWidget:
        """按月阶段带。"""
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, S.s2, 0, 0)
        hl.setSpacing(S.s2)
        for ph in phases[-6:]:
            band = QFrame()
            band.setObjectName("phaseBand")
            v = QVBoxLayout(band)
            v.setContentsMargins(S.s3, S.s2, S.s3, S.s2)
            v.setSpacing(S.s1)
            mon = str(ph.get("month") or "")
            v.addWidget(txt(
                t("{y} 年 {m} 月", y=mon[:4],
                  m=f"{int(mon[5:7] or 0):02d}") if mon
                else t("无月份"), F.caption, 700, C.ink_700))
            v.addWidget(txt(
                t("{s} 次任务 · 活跃 {d} 天 · 纠正 {c} 回",
                  s=ph.get("sessions", 0), d=ph.get("days", 0),
                  c=ph.get("corrections", 0)), F.caption, color=C.ink_500,
                wrap=True))
            hl.addWidget(band, 1)
        return row

    # ---------- ③.5 按经验记录聚合（零模型也在的事实层） ----------

    def _aggregate_card(self, g: dict, animate: bool = False) -> QWidget | None:
        """三块聚合图：热力条 / 日柱 / 累积横条，口径 = 经验记录自身。

        `cumulative`（每类逐日累积条数）与 `heatmap`（近 14 天 × 主干 G 加权）
        都由 store.growth_summary 从 experience.jsonl 的 `trunk` / `category`
        现算——采集层写入时已确定性赋值（缺省兜底其他/未分类），所以**无模型
        也有数**；模型可用时方法/技能维度只是过程记录里的增强，不替代这里。

        无任何经验记录（两块都空）→ 返回 None，不画假图。
        """
        cum = g.get("cumulative") or {}
        hm = g.get("heatmap") or {}
        grid = hm.get("grid") or {}
        dates = hm.get("dates") or []
        if not cum and not grid:
            return None

        box = card(title=t("你的经验按任务类型长出来"))
        box.layout().addWidget(txt(
            t("这些是你收进来的活本身，跟模型通不通没关系"), F.caption,
            color=C.ink_500))

        # ① 日柱：最近 14 天每天收进多少条（跨类别合计，逐日增量）
        n_days = len(dates) or 14
        daily = self._daily_totals(cum, n_days)
        if any(v > 0 for v in daily):
            block, bv = self._agg_block()
            bv.addWidget(txt(t("近 {n} 天每天收进多少条", n=n_days),
                             F.caption, color=C.ink_700))
            cc = columns_chart(daily)
            bv.addWidget(cc)
            box.layout().addWidget(block)
            if animate:
                cc.animate_in()

        # ② 热力条：最近 14 天活跃度（G 加权，跨主干合计）
        if grid:
            heat = [sum(_at(grid.get(tr) or (), i) for tr in grid)
                    for i in range(n_days)]
            block, bv = self._agg_block()
            bv.addWidget(txt(t("近 {n} 天活跃度", n=n_days), F.caption,
                             color=C.ink_700))
            hb = heat_bar(heat, dates)
            bv.addWidget(hb)
            box.layout().addWidget(block)
            if animate:
                hb.animate_in()

        # ③ 累积横条：按任务类型的总条数（top N，标签列宽按实测最宽）
        cats = [(self._cat_label(k), int(_tail_val(s)))
                for k, s in cum.items()]
        cats = [c for c in sorted(cats, key=lambda kv: -kv[1])[:_AGG_TOP_CATS]
                if c[1] > 0]
        if cats:
            label_w = self._label_col_w([k for k, _ in cats],
                                        _AGG_LABEL_MIN, _AGG_LABEL_MAX)
            block, bv = self._agg_block()
            bv.addWidget(txt(t("按任务类型攒下的条数"), F.caption,
                             color=C.ink_700))
            mx = cats[0][1]
            for label, val in cats:
                bv.addWidget(hbar_row(label, val, mx, label_w))
            box.layout().addWidget(block)
        return box

    @staticmethod
    def _agg_block() -> tuple[QWidget, QVBoxLayout]:
        """聚合卡里的一个小节（浅底块，把三块图视觉分开）。"""
        block = QFrame()
        block.setObjectName("aggBlock")
        v = QVBoxLayout(block)
        v.setContentsMargins(S.s3, S.s3, S.s3, S.s3)
        v.setSpacing(S.s2)
        return block, v

    @staticmethod
    def _cat_label(key: str) -> str:
        """`trunk/category` → 展示串（分隔符换中点，与 affinity_display 同风格）。"""
        trunk, _, cat = str(key).partition("/")
        return f"{trunk} · {cat}" if cat else str(key)

    @staticmethod
    def _daily_totals(cum: dict, n_days: int) -> list[int]:
        """每类累积序列 → 窗口内逐日增量合计（取右端 n_days 天）。"""
        out = [0] * n_days
        for series in cum.values():
            if not series:
                continue
            tail = series[-(n_days + 1):]
            base = int(tail[0][1]) if len(tail) > n_days else 0
            vals = [int(v) for _, v in tail[-n_days:]]
            prev = base
            off = n_days - len(vals)
            for i, v in enumerate(vals):
                out[off + i] += v - prev
                prev = v
        return out

    # ---------- ④ 经验账本 + 侧栏 ----------

    def _ledger_row(self, g: dict) -> QWidget:
        """账本（事实层，只要有经验就渲染）+ 侧栏（欠账 / 各助手磨合）。

        侧栏两块各自有前提：欠账卡说的是"会话怎么还没长出来"，没有会话时
        这句话本身不成立（0 次任务谈不上挤在未分类），故只在有会话时挂。
        """
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(S.s4)
        hl.addWidget(self._ledger_card(g), 8)
        has_gaps = bool((g.get("stage") or {}).get("sessions"))
        if has_gaps or g.get("agents"):
            side = QWidget()
            sv = QVBoxLayout(side)
            sv.setContentsMargins(0, 0, 0, 0)
            sv.setSpacing(S.s4)
            if has_gaps:
                sv.addWidget(self._gaps_card(g))
            if g.get("agents"):
                sv.addWidget(self._agents_card(g))
            sv.addStretch(1)
            hl.addWidget(side, 5)
        return row

    def _ledger_card(self, g: dict) -> QWidget:
        a = g.get("assets") or {}
        box = card(title=t("你的经验账本"))
        strip = QWidget()
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(S.s3)
        for val, label, note, tone in (
                (a.get("experience", 0), t("你的经验"),
                 t("AI 判过轻重 + 反复撞见的做法"), "ink"),
                (a.get("corrected", 0), t("你纠正后定下"),
                 t("你说过“不对，应该这样”"), "ink"),
                (a.get("advice", 0), t("助手替你挡的坑"),
                 t("它自己手滑，不算你的"), "ink"),
                (a.get("feedback", 0), t("你表过态的"),
                 t("点一次“有用”，排序听你的"),
                 "brand" if not a.get("feedback") else "ink")):
            sl.addWidget(self._mini_stat(val, label, note, tone), 1)
        box.layout().addWidget(strip)
        box.layout().addWidget(txt(
            t("满分 {n} 的 {c} 条，先看前 {m} 条", n=9,
              c=a.get("top", 0), m=len(g.get("ledger") or [])),
            F.caption, color=C.ink_500))
        for it in g.get("ledger") or []:
            box.layout().addWidget(self._ledger_row_item(it))
        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(txt(t("共 {n} 条属于你的经验", n=a.get("experience", 0)),
                         F.caption, color=C.ink_500))
        fl.addStretch(1)
        btn = btn_flat(t("去经验库看全部"))
        btn.clicked.connect(lambda: self.go("mine"))
        fl.addWidget(btn)
        box.layout().addWidget(foot)
        return box

    @staticmethod
    def _mini_stat(val, label: str, note: str, tone: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(S.s1)
        v.addWidget(txt(label, F.caption, color=C.ink_500, wrap=True))
        vh = QHBoxLayout()
        vh.setSpacing(S.s1)
        vh.addWidget(txt(str(val), F.h1, 800,
                         C.brand_700 if tone == "brand" else C.ink_900))
        vh.addStretch(1)
        v.addLayout(vh)
        v.addWidget(txt(note, F.caption, color=C.ink_500, wrap=True))
        return w

    def _ledger_row_item(self, it: dict) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, S.s2, 0, S.s2)
        hl.setSpacing(S.s3)
        hl.addWidget(self._score_badge(int(it.get("importance") or 0)), 0,
                     Qt.AlignTop)
        col = QWidget()
        cv = QVBoxLayout(col)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(S.s1)
        cv.addWidget(txt(str(it.get("task") or ""), F.body, 700, wrap=True))
        if it.get("action"):
            cv.addWidget(txt(str(it["action"]), F.caption, color=C.ink_500,
                             wrap=True))
        chips = QWidget()
        ch = QHBoxLayout(chips)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(S.s1)
        if it.get("importance") is not None:
            ch.addWidget(chip(t("AI 判定 {n} 分", n=it["importance"]), "brand"))
        if it.get("corrected"):
            ch.addWidget(chip(t("你纠正后定下"), "ok"))
        if int(it.get("seen") or 0) >= 3:
            ch.addWidget(chip(t("同类情况遇到 {n} 次", n=it["seen"]), "info"))
        if it.get("agent"):
            ch.addWidget(chip(str(it["agent"]), "ink"))
        ch.addStretch(1)
        cv.addWidget(chips)
        hl.addWidget(col, 1)
        ops = QWidget()
        ov = QVBoxLayout(ops)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(S.s1)
        eb = btn_flat(t("讲人话"))
        eb.clicked.connect(lambda _=False, x=it: self._explain(x))
        ov.addWidget(eb)
        if it.get("agent"):
            vb = btn_flat(t("看现场"))
            vb.clicked.connect(lambda _=False, ag=it.get("agent"),
                               sid=it.get("session_id"): self._open_session(ag, sid))
            ov.addWidget(vb)
        hl.addWidget(ops, 0, Qt.AlignTop)
        return row

    @staticmethod
    def _score_badge(score: int) -> QLabel:
        lab = QLabel(str(score) if score else "·")
        lab.setObjectName("scoreBadge")
        lab.setFixedSize(D.BADGE_STEP, D.BADGE_STEP)
        lab.setAlignment(Qt.AlignCenter)
        # 高分态走动态属性（页级 QSS 的 #scoreBadge[hi="true"]），不再逐格 setStyleSheet
        lab.setProperty("hi", "true" if score >= 8 else "false")
        lab.style().unpolish(lab)
        lab.style().polish(lab)
        return lab

    # ---------- ④ 侧栏：欠账 + 各助手磨合 ----------

    def _gaps_card(self, g: dict) -> QWidget:
        """欠账即内容：三件没到位的事各说清缺哪份数据、卡在哪一步。

        第②件不写"0 次"就完事——用 growth_story.delivery 说清到底卡在哪：
        没装回灌 / 装了但助手没回调 / 通道通了但没内容可注入。三种下一步不同，
        只给一个 0 等于把诊断责任推给用户。"""
        from ..distill import growth_story

        fw = g.get("flywheel") or {}
        st = g.get("stage") or {}
        inj = int(fw.get("injected") or 0)
        dv = growth_story.delivery(g, self._hook)
        box = card(title=t("还差这三件，才能给你看证据"))
        if inj:
            by = fw.get("injected_by") or {}
            second = (t("{n} 次已送达（代理 {p} · hook {h}）/ 需要 {need} 次，"
                        "第 ⑤ 格才会有数字", n=inj, p=by.get("proxy", 0),
                        h=by.get("hook", 0), need=_INJECT_TARGET), "ok")
        else:
            second = (t(dv["tpl"], **dv.get("params", {})),
                      "ink" if dv["state"] == "idle" else "err")
        gaps = [
            (t("分出任务类型"),
             t("{n} 次任务现在全挤在“未分类”一个桶里，所以“某类任务越做越顺”"
               "给不了分项对比", n=st.get("sessions", 0)), "ink"),
            (t("让经验回到会话里"), second[0], second[1]),
            (t("听你说哪条真有用"),
             t("你还没点过“有用 / 没用”，AI 只能自己猜"), "ink"),
        ]
        for title, note, tone in gaps:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(S.s2)
            hl.addWidget(status_dot(tone), 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(S.s1)
            col.addWidget(txt(title, F.body, 700))
            col.addWidget(txt(note, F.caption, color=C.ink_500, wrap=True))
            hl.addLayout(col, 1)
            box.layout().addWidget(row)
        if not self._model_ok:
            box.layout().addWidget(chip(t("当前模型端点连不上 · 已熔断"), "err"))
        box.layout().addWidget(txt(
            t("第一件连上 AI 就自动补，后两件各点几下就行。已经自动做好的："
              "把干过的活收进来（{n} 次）。", n=st.get("sessions", 0)),
            F.caption, color=C.ink_500, wrap=True))
        if dv.get("action"):
            btn = btn_secondary(t(dv["action"]))
            btn.clicked.connect(lambda: self.go("connect"))
            box.layout().addWidget(btn, 0, Qt.AlignLeft)
        return self._wrap_title(box)

    _AGENT_STATE = {
        "improved": ("明显变顺", "ok"),
        "smooth": ("本来就顺", "ink"),
        "few": ("样本不够", "info"),
        "flat": ("暂无明显变化", "ink"),
    }

    def _agents_card(self, g: dict) -> QWidget:
        box = card(title=t("几个助手各自的磨合"))
        box.layout().addWidget(txt(
            t("样本不够的直接说不够，不拿进度条装样子"), F.caption,
            color=C.ink_500))
        for a in g.get("agents") or []:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, S.s1, 0, S.s1)
            hl.setSpacing(S.s2)
            col = QVBoxLayout()
            col.setSpacing(S.s1)
            col.addWidget(txt(str(a.get("agent") or ""), F.body, 700))
            col.addWidget(txt(
                t("{n} 次任务 · 纠正 {c} 回 · 最近 {d}", n=a.get("n", 0),
                  c=a.get("corrections", 0), d=a.get("last", "")),
                F.caption, color=C.ink_500, wrap=True))
            early, recent = a.get("early"), a.get("recent")
            if early is not None and recent is not None:
                col.addWidget(txt(
                    t("返工 {e} 回/次 → {r} 回/次", e=early, r=recent),
                    F.caption, color=C.ink_700, wrap=True))
            hl.addLayout(col, 1)
            label, tone = self._AGENT_STATE.get(
                str(a.get("state")), self._AGENT_STATE["flat"])
            hl.addWidget(chip(t(label), tone), 0, Qt.AlignTop)
            box.layout().addWidget(row)
        return self._wrap_title(box)

    # ---------- ⑤ 助手避坑 ----------

    def _advice_card(self, g: dict) -> QWidget:
        """助手避坑（同类归堆）：与首页共用 group_friction，
        同一份数据两页口径一致。"""
        from . import rule_render

        a = g.get("assets") or {}
        buckets = rule_render.group_friction(g.get("advice_items") or [])
        box = card(title=t("助手能自动帮你避的坑"))
        box.layout().addWidget(txt(
            t("这 {n} 条不是你的教训，是它自己手滑，你不用管",
              n=a.get("advice", 0)), F.caption, color=C.ink_500))
        for b in buckets:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, S.s1, 0, S.s1)
            hl.setSpacing(S.s2)
            hl.addWidget(status_dot("ok"), 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(txt(t(b["title"]), F.body, 600))
            col.addWidget(txt(t(b["advice"]), F.caption, color=C.ink_500))
            hl.addLayout(col, 1)
            hl.addWidget(txt(t("{n} 次", n=b["count"]), F.caption,
                             color=C.ink_700), 0, Qt.AlignTop)
            box.layout().addWidget(row)
        box.layout().addWidget(txt(
            t("共 {n} 类、累计撞见 {c} 次，已自动生效",
              n=len(buckets), c=a.get("advice_hits", 0)),
            F.caption, color=C.ink_500))
        return box

    # ---------- 下钻：讲人话 / 看现场（复用经验库与会话抽屉链路） ----------

    def _explain(self, it: dict) -> None:
        """一条经验送模型讲人话；结果缓存在记录上，再点零成本。"""
        # 已删 guide_connect_ai，统一改 require_model 门禁
        if not self.require_model(t("让 AI 讲人话")):
            return
        eid = str(it.get("id") or "")
        if not eid:
            return
        self.set_status(t("正在让 AI 讲人话…"), "info")

        def work():
            return self.api.experience_explain(eid, current_language())

        def on_done(res):
            res = res or {}
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

    def _open_session(self, agent, sid) -> None:
        """下钻会话现场（与首页同一只读抽屉）。"""
        if not agent or not sid:
            self.set_status(t("这条经验没记下来源会话"))
            return

        def on_done(data: dict) -> None:
            from .session_drawer import SessionDrawer
            # 抽屉 exec 后释放（含整份转录，长会话反复
            # 查看会持续吃内存）
            drawer = SessionDrawer(data, self)
            drawer.exec()
            drawer.deleteLater()

        self.run_async(
            lambda: self.api.session_view(agent, sid), on_done,
            on_error=lambda e: self.set_status(t("读取会话失败：{err}", err=e)))

    # ---------- ⑥ 过程记录（折叠） ----------

    def _process_card(self, g: dict, skills: list, nodes: list) -> QWidget:
        """学习历程 / 方法沉淀 / 后台整理：默认收起，widgets 照建（可检视）。"""
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(S.s2)
        head, icon = collapse_header(t("过程记录"), expanded=self._proc_open)
        hint = txt(t("学习历程 / 方法沉淀 / 后台整理"), F.caption,
                   color=C.ink_500)
        v.addWidget(head)
        v.addWidget(hint)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(S.s4)
        if skills:
            bv.addWidget(self._section(
                t("方法沉淀"), self._method_section(skills, g.get("affinity") or {})))
        if nodes:
            bv.addWidget(self._timeline(nodes))
        maint = g.get("maintenance") or []
        if maint:
            bv.addWidget(self._section(
                t("后台整理（自动）"), self._maintenance_rows(maint)))
        body.setVisible(self._proc_open)
        v.addWidget(body)

        def _toggle():
            self._proc_open = not self._proc_open
            icon.setRotation(180 if self._proc_open else 0)
            body.setVisible(self._proc_open)
            hint.setText(t("学习历程 / 方法沉淀 / 后台整理") if self._proc_open
                         else t("点开展开：学习历程 / 方法沉淀 / 后台整理"))

        head.mousePressEvent = lambda e: _toggle()
        return wrap

    # ---------- 方法沉淀（④.5） ----------

    def _method_section(self, skills: list, aff: dict) -> QWidget:
        total = len(skills)
        total_failures = sum(
            len(s.get("failure_solid", [])) + len(s.get("failure_watching", []))
            for s in skills)
        total_confirmed = sum(
            len(s.get("preferences", {}).get("confirmed", []))
            for s in skills if s.get("preferences"))
        growth_total = sum(
            1 for a in aff.values()
            if (a or {}).get("level") in ("中", "高"))
        cells = [
            (t("方法总数"), str(total)),
            (t("新坑"), str(total_failures)),
            (t("已确认偏好"), str(total_confirmed)),
            (t("熟练类别"), str(growth_total)),
        ]
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setSpacing(S.s2)
        for label, value in cells:
            c = QFrame()
            c.setObjectName("methodCell")
            vl = QVBoxLayout(c)
            vl.setContentsMargins(S.s3, S.s2, S.s3, S.s2)
            vl.setSpacing(S.s1)
            vl.addWidget(txt(label, F.caption, color=C.ink_500))
            vl.addWidget(txt(value, F.body, 700, C.ink_900))
            hl.addWidget(c, 1)
        return box

    # ---------- 后台整理日志（⑥，档 C [auto] 标，C1-4） ----------

    def _maintenance_rows(self, maint: list) -> QWidget:
        box = QWidget()
        vl = QVBoxLayout(box)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(S.s1)
        for rec in maint[:10]:
            ts = str(rec.get("ts", ""))[:16].replace("T", " ")
            parts = []
            if rec.get("aged_demoted"):
                parts.append(t("降权 {n} 条", n=rec["aged_demoted"]))
            if rec.get("aged_retired"):
                parts.append(t("归档 {n} 条", n=rec["aged_retired"]))
            if rec.get("obs_expired"):
                parts.append(t("观察过期 {n} 条", n=rec["obs_expired"]))
            if rec.get("deprecated_removed"):
                parts.append(t("清理 {n} 条", n=rec["deprecated_removed"]))
            summary = "、".join(parts) or t("无变化")
            vl.addWidget(txt(f"[auto] {ts}  {summary}", F.caption,
                             color=C.ink_500))
        # M1③：最近一条存储自检（C1 每轮追加；maint 新在前，取首条带 storage 的）
        for rec in maint[:10]:
            st = rec.get("storage")
            if isinstance(st, dict) and st:
                vl.addWidget(txt(self._storage_health_line(st), F.caption,
                                 color=C.ink_500))
                break
        return box

    @staticmethod
    def _storage_health_line(st: dict) -> str:
        """存储自检条目 → 展示行（体积/最大单行/黄标/超容量）。"""
        def _mb(name: str) -> float:
            return round((st.get(name) or {}).get("bytes", 0) / 1048576, 1)

        max_kb = round(
            max(((v.get("max_line_bytes", 0))
                 for v in st.values() if isinstance(v, dict)),
                default=0) / 1024, 1)
        line = t("存储自检：会话 {a}MB · 经验 {b}MB · 通知 {c}MB（最大单行 {d}KB）",
                 a=_mb("sessions.jsonl"), b=_mb("experience.jsonl"),
                 c=_mb("notifications.jsonl"), d=max_kb)
        no_ts = int(st.get("sessions_no_ts") or 0)
        if no_ts:
            line += " " + t("{n} 条无时间戳（黄标）", n=no_ts)
        oversized = int((st.get("sessions.jsonl") or {}).get("oversized") or 0)
        if oversized:
            line += " " + t("超容量 {n} 条", n=oversized)
        return line

    def retranslateUi(self) -> None:
        """重新应用翻译：更新所有静态文本后刷新数据。"""
        self._growth_title.setText(t("成长"))
        self._growth_week_btn.setText(t("本周结算"))
        self._growth_poster_btn.setText(t("生成本阶段海报"))
        self.refresh()

    # ---------- 辅助 ----------

    def _clear_body(self) -> None:
        """清空数据区（走基类统一入口；嵌套子布局也会被逐层销毁）。"""
        clear_layout(self._body)

    def _section(self, title: str, content_widget: QWidget) -> QWidget:
        """区块：节标题卡 + 内容。

        S4：本页原先自建 `card(title=…)` 包装，现统一委托共享 `section()`
        （节标题规格与 `card(title=…)` 一致，故为**纯重构、视觉无变化**）。
        """
        from .qt_widgets import section

        return section(title, content=content_widget)

    @staticmethod
    def _label_col_w(labels: list[str], lo: int, hi: int) -> int:
        """R4：label 列宽 = 本组 label 实测最宽（B 类内容派生，夹在 [lo, hi]），
        全量显示不截断——替代旧版 tk[:8]/key[:16] 的硬切片。"""
        fm = QFontMetrics(txt("").font())
        w = max((fm.horizontalAdvance(x) for x in labels), default=float(lo))
        return int(max(lo, min(hi, w)))

    # ---------- 时间线编辑/删除 ----------

    def _edit_node(self, idx: int, text: str) -> None:
        new_text = input_dialog(t("编辑时间线节点"), t("节点内容"), self,
                                default=text)
        if new_text is None:
            return
        try:
            self.api.changelog_edit(idx, new_text)
            self._set_status(t("已保存"), "ok")
            self.refresh()
        except LocalApiError as exc:
            self._set_status(str(exc.detail))

    def _delete_node(self, idx: int) -> None:
        ok = confirm_dialog(
            t("删除这个节点？"),
            t("删除 = 归档（30 天内可恢复），删掉的条目立即停止自动带上"), self)
        if not ok:
            return
        try:
            self.api.changelog_delete(idx)
            self._set_status(t("已删除（归档 30 天可恢复）"), "ok")
            self.refresh()
        except LocalApiError as exc:
            self._set_status(str(exc.detail))
