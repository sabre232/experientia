"""本周结算卡。

周报此前只是 notifications.jsonl 里一段换行纯文本—— 设想的"数字当证据、
叙事承载仪式感"没有落地形态。本卡是同一份 growth_story 的第二个视图：
通知负责"到点提醒你"，这张卡负责"让你看懂这周发生了什么"，
底部一键把整个阶段拼成海报（第三个视图）。

数据源：GET /api/weekly-report（服务端 peek，只读，不触发成就判定与推送）。
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QScrollArea,
                               QVBoxLayout, QWidget)

from .i18n import t
from .qt_theme import (btn_primary, btn_secondary, card, chip, icon_widget,
                       provenance_bar, status_dot, txt)
from .theme import ANIMATION, C, F, R, S, SIZES, motion_ok

# 四问语义色圆点（tone → token 名）：橙色只给活跃/成就，警示用 err
_DOT = {"ok": "ok", "err": "err", "info": "info", "ink": "ink"}


class WeeklyCard(QDialog):
    """本周结算：主句 + 四问 + 攒下的东西 + 里程碑（+ 出海报入口）。"""

    def __init__(self, data: dict, parent=None, on_poster=None):
        super().__init__(parent)
        self._on_poster = on_poster
        story = data.get("story") or {}
        self.setWindowTitle(t("本周结算"))
        self.resize(560, 720)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(S.s6, S.s4, S.s4, S.s4)
        hl.addWidget(txt(t("本周结算"), F.h1, 800))
        week = str(data.get("week") or "")
        if week:
            hl.addWidget(txt(week, F.caption, color=C.ink_500), 0,
                         Qt.AlignBottom)
        hl.addStretch(1)
        close = icon_widget("CLOSE_OUTLINED", SIZES.ICON_LIST, C.ink_500)
        close.mousePressEvent = lambda _e: self.accept()
        close.setCursor(Qt.PointingHandCursor)
        hl.addWidget(close)
        lay.addWidget(head)

        # 溯源条：无模型且仍有历史内容时，顶部说明"内容为上次生成"；
        # 正常态/来源未知（旧响应无字段）→ provenance_bar 返回 None，不打扰。
        prov = provenance_bar(self._prov_state(data, story))
        if prov is not None:
            wrap = QWidget()
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(S.s6, 0, S.s6, 0)
            wl.addWidget(prov)
            lay.addWidget(wrap)

        body = QVBoxLayout()
        body.setContentsMargins(S.s6, 0, S.s6, S.s6)
        body.setSpacing(S.s3)
        body.addWidget(self._headline(story))
        qs = self._questions(story)
        if qs is not None:
            body.addWidget(qs)
        assets = self._assets(story)
        if assets is not None:
            body.addWidget(assets)
        body.addWidget(self._milestones(story))
        body.addLayout(self._footer(story))
        body.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setLayout(body)
        scroll.setWidget(inner)
        lay.addWidget(scroll)
        # 折行标签在滚动区内会被算成 0 高（文字在、看不见）——把内容宽度锁成
        # 视口宽，heightForWidth 才有依据（与会话抽屉同一处理）
        self._scroll, self._holder = scroll, inner
        scroll.viewport().installEventFilter(self)
        self._sync_width()

    def _sync_width(self) -> None:
        self._holder.setFixedWidth(max(320, self._scroll.viewport().width() - 2))

    @staticmethod
    def _prov_state(data: dict, story: dict) -> dict:
        """provenance_bar 入参：优先取响应顶层，回退叙事内字段（契约）。

        has_content = 这张卡确实有东西可看（有成长数据或四问），否则空状态由
        页面自己渲染，不该挂"内容为上次生成"的条。"""
        return {
            "content_source": str(data.get("content_source")
                                  or (story or {}).get("content_source") or ""),
            "generated_at": str(data.get("generated_at")
                                or (story or {}).get("generated_at") or ""),
            "has_content": bool((story or {}).get("has_data")
                                or (story or {}).get("questions")),
        }

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """出场动画：窗口透明度 0→1；reduced-motion 下不动，直接终态。"""
        super().showEvent(event)
        if not motion_ok():
            return
        try:
            self.setWindowOpacity(0.0)
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(int(ANIMATION.DURATION_DIALOG * 1000))
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._entrance_anim = anim   # 保引用防 GC
            anim.start()
        except Exception:  # noqa: BLE001 fail-open：动画失败也必须可见
            self.setWindowOpacity(1.0)

    def eventFilter(self, obj, ev) -> bool:
        if obj is self._scroll.viewport() and ev.type() == QEvent.Resize:
            self._sync_width()
        return super().eventFilter(obj, ev)

    # ---------- 各段 ----------

    @staticmethod
    def _headline(story: dict) -> QWidget:
        # 懒导入：与本文件 open_weekly_card 同风格，GUI 层不模块级引引擎
        from ..distill import growth_story

        gate = story.get("model_gate") or {}
        if gate.get("state") in growth_story.MODEL_GATE_BLOCKED:
            return WeeklyCard._gate_card(story, gate)
        h = story.get("headline") or {}
        box = card()
        box.setObjectName("weekHeadline")
        box.setStyleSheet(f"QFrame#weekHeadline {{ background: {C.surface_hero};"
                          f" border: 1px solid {C.brand_200};"
                          f" border-radius: {R.lg}px; }}")
        v = box.layout()
        v.setSpacing(S.s1)
        rng = str(story.get("range_short") or "")
        v.addWidget(txt(t("这段时间") + (f" · {rng}" if rng else ""),
                        F.caption, color=C.ink_500))
        v.addWidget(txt(str(h.get("label") or ""), F.h1, 800, wrap=True))
        big = str(h.get("big") or "")
        if big:
            row = QHBoxLayout()
            row.setSpacing(S.s1)
            row.addWidget(txt(big, F.display, 800, C.brand_700))
            if h.get("unit"):
                row.addWidget(txt(str(h["unit"]), F.h1, 800, C.brand_700),
                              0, Qt.AlignBottom)
            row.addStretch(1)
            v.addLayout(row)
        if h.get("from") is not None and h.get("to") is not None:
            v.addWidget(txt(t("平均每个任务：{e} 回/次 → {r} 回/次",
                              e=h["from"], r=h["to"]), F.body, color=C.ink_700))
        if h.get("sub"):
            v.addWidget(txt(str(h["sub"]), F.caption, color=C.ink_500,
                            wrap=True))
        return box

    @staticmethod
    def _gate_card(story: dict, gate: dict) -> QWidget:
        """无模型引导卡：主句位置不放空壳（空壳 = 一屏空白，用户不知道发生了什么）。

        统计照常（区间在卡头、底栏计数、里程碑在下面），只把"故事"这一块换成
        正向说明 + 单一主操作：为什么这里没有故事、怎么让它出现。"""
        box = card()
        box.setObjectName("weekGate")
        box.setStyleSheet(f"QFrame#weekGate {{ background: {C.surface_2};"
                          f" border: 1px solid {C.brand_200};"
                          f" border-radius: {R.lg}px; }}")
        v = box.layout()
        v.setSpacing(S.s2)
        rng = str(story.get("range_short") or "")
        if rng:
            v.addWidget(txt(t("这段时间") + f" · {rng}", F.caption,
                            color=C.ink_500))
        v.addWidget(txt(str(gate.get("title") or ""), F.h1, 700, wrap=True))
        body = str(gate.get("body") or "")
        if body:
            v.addWidget(txt(body, F.caption, color=C.ink_500, wrap=True))
        action = str(gate.get("action") or "")
        if action:
            btn = btn_primary(action)
            btn.clicked.connect(lambda: WeeklyCard._go_connect(box))
            v.addWidget(btn, 0, Qt.AlignLeft)
        return box

    @staticmethod
    def _questions(story: dict) -> QWidget | None:
        """四问块；无条目时整块不渲染（只留一个标题的空卡是噪音）。"""
        if not story.get("questions"):
            return None
        box = card(title=t("四个问题"))
        for q in story.get("questions") or []:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, S.s1, 0, S.s1)
            hl.setSpacing(S.s2)
            hl.addWidget(status_dot(_DOT.get(q.get("tone"), "ink")), 0,
                         Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(S.s1)
            title = txt(str(q.get("title") or ""), F.body, 700)
            col.addWidget(title)
            body = txt(str(q.get("body") or ""), F.caption, color=C.ink_500,
                       wrap=True)
            col.addWidget(body)
            if q.get("action"):
                btn = btn_secondary(str(q["action"]))
                btn.clicked.connect(lambda: WeeklyCard._go_connect(box))
                col.addWidget(btn, 0, Qt.AlignLeft)
            hl.addLayout(col, 1)
            box.layout().addWidget(row)
        return box

    @staticmethod
    def _assets(story: dict) -> QWidget | None:
        items = story.get("assets") or []
        if not items:
            return None
        box = card(title=t("这阵子攒下的东西"))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(S.s2)
        for a in items:
            row.addWidget(chip(f"{t(a['k'])} {a['v']}{a['u']}",
                               "brand" if a.get("tone") == "ink" else "ink"))
        row.addStretch(1)
        box.layout().addLayout(row)
        notes = " · ".join(t(str(a.get("note") or "")) for a in items
                           if a.get("note"))
        if notes:
            box.layout().addWidget(txt(notes, F.caption, color=C.ink_500,
                                        wrap=True))
        return box

    @staticmethod
    def _milestones(story: dict) -> QWidget:
        ms = story.get("milestones") or {}
        lines = ms.get("unlocked") or ms.get("next") or []
        box = card(title=t("里程碑 · 已解锁") if ms.get("unlocked")
                   else t("里程碑 · 还没解锁"))
        for ln in lines:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, S.s1, 0, S.s1)
            hl.setSpacing(S.s2)
            hl.addWidget(status_dot("ok" if ms.get("unlocked") else "ink"), 0,
                         Qt.AlignTop)
            hl.addWidget(txt(str(ln), F.caption, color=C.ink_500,
                             wrap=True), 1)
            box.layout().addWidget(row)
        if not ms.get("unlocked"):
            box.layout().addWidget(txt(
                t("没有新的就不庆祝——数字变大不算里程碑，具象变身才算。"),
                F.caption, color=C.ink_500, wrap=True))
        return box

    def _footer(self, story: dict) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(S.s2)
        counts = txt(str(story.get("counts") or ""), F.caption,
                     color=C.ink_500, wrap=True)
        row.addWidget(counts, 1)
        poster = btn_primary(t("拼成一张海报"))
        poster.clicked.connect(lambda: self._open_poster())
        row.addWidget(poster, 0, Qt.AlignRight)
        return row

    # ---------- 动作 ----------

    @staticmethod
    def _go_connect(widget: QWidget) -> None:
        page = widget.window()
        go = getattr(page, "go", None)
        if callable(go):
            go("connect")

    def _open_poster(self) -> None:
        if self._on_poster is not None:
            self._on_poster()


def open_weekly_card(api, parent=None) -> None:
    """入口：拉本周结算叙事并弹卡（失败写状态行，不静默）。

    weekly_report() 原同步跑在 UI 线程（15s 超时）——
    点开周卡时若引擎未起/卡住，界面冻结最长 15 秒。改走宿主页的
    `run_async` 取数（宿主是 PageBase 才有）；拿不到宿主时退回同步调用，
    至少保持可用（入口函数也可能被非页面上下文调用）。"""
    page = parent if hasattr(parent, "set_status") else None
    runner = getattr(parent, "run_async", None)

    def _fetch():
        from ..distill import growth_story
        data = api.weekly_report()
        # 服务端只回模板 + 参数，语言在这里定
        data["story"] = growth_story.localize(data.get("story") or {}, t)
        return data

    def _done(data):
        from . import report_view

        def _poster():
            # 窗口口径跟成长页当前阶段跨度走（此前写死 30 天，与页面上选的对不上）
            days = int(getattr(page or parent, "_poster_days", 30) or 30)
            report_view.open_growth_report(api, days, page or parent)

        card = WeeklyCard(data, parent, on_poster=_poster)
        card.exec()
        card.deleteLater()  # 弹后释放，周卡反复开不累积

    def _err(exc):
        if page is not None:
            page.set_status(t("读取本周结算失败：{err}", err=exc))

    if callable(runner):
        runner(_fetch, _done, _err)
        return
    try:
        _done(_fetch())
    except Exception as exc:  # noqa: BLE001（入口兜底：任何取数失败都要说话）
        _err(exc)
