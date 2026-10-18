"""会话下钻抽屉（修复方案洞察卡配套）：从事件行回溯到当时的现场。

只读渲染落库截断转录 + 事件行——统计必须能点进具体会话才算洞察。
视觉方向 C「卡片面板」：顶部数据条 +
对话面板 + 操作时间线面板，角色用色标签、操作带 exit 徽标。系统注入噪音过滤、
长文折叠（正文走 md_view 富文本，超长给「展开全文」而非硬切），
全部复用 qt_theme 组件与设计 token，不裸 dump 内部结构。
"""

from __future__ import annotations

import re
from itertools import zip_longest

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QScrollArea,
                               QVBoxLayout, QWidget)

from .i18n import t
from .qt_theme import btn_flat, card, chip, icon_widget, md_view, mono, txt
from .theme import C, F, S

# 单条消息默认展示字数上限（超出折叠成"展开全文"，不再硬切丢正文）
_MSG_LIMIT = 1200

# 系统注入噪音：环境上下文 / 工具协议块等，不是用户真的说过的话
_SYS_NOISE_RE = re.compile(
    r"^\s*<\s*(environment_context|system|tool_response|function_calls|"
    r"instructions|context)\b", re.I)


def _is_system_noise(text: str) -> bool:
    s = str(text or "").strip()
    return bool(s) and bool(_SYS_NOISE_RE.match(s))


def _basename(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/").rstrip("/")
    return p.rsplit("/", 1)[-1] if p else ""


def _ts(ev: dict) -> str:
    return str(ev.get("t") or "")[11:19]


def _vline() -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.VLine)
    ln.setStyleSheet(f"QFrame {{ color: {C.line}; background: {C.line}; border: none; }}")
    ln.setFixedWidth(1)
    return ln


class SessionDrawer(QDialog):
    """一个会话的现场速览（数据条 + 对话面板 + 操作时间线面板）。"""

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        agent = str(data.get("agent") or "?")
        sid = str(data.get("session_id") or "")
        self.setWindowTitle(t("会话现场"))
        self.resize(820, 700)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(S.s6, S.s6, S.s6, S.s6)
        lay.setSpacing(S.s4)

        lay.addWidget(self._header(agent, sid, str(data.get("model") or "")))
        lay.addWidget(self._stats_strip(data))

        body = QVBoxLayout()
        body.setSpacing(S.s4)
        tp = self._transcript_panel(data)
        if tp is not None:
            body.addWidget(tp)
        ep = self._events_panel(data)
        if ep is not None:
            body.addWidget(ep)
        if tp is None and ep is None:
            body.addWidget(txt(t("这个会话没有留下可展示的现场记录"),
                               F.body, color=C.ink_500))
        body.addStretch(1)

        holder = QWidget()
        holder.setLayout(body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)
        # 内容宽度锁视口宽：让换行标签按可视宽折行，杜绝左右滑动（宽度自适应）
        self._scroll = scroll
        self._holder = holder
        scroll.viewport().installEventFilter(self)
        self._sync_width()

    def _sync_width(self) -> None:
        # 下限从 max 改为 min——原来内容恒 ≥320px，用户把
        # 抽屉拖窄到 <322px 时右侧被裁，而横向滚动条又被显式关掉（内容不可达，
        # 违反布局章程"可收缩 + 滚动，不能溢出裁切"）。取 min 后窄窗时内容跟随
        # 视口收窄、靠换行呈现。
        self._holder.setFixedWidth(min(320, self._scroll.viewport().width() - 2))

    def eventFilter(self, obj, ev) -> bool:
        if obj is self._scroll.viewport() and ev.type() == QEvent.Resize:
            self._sync_width()
        return super().eventFilter(obj, ev)

    # ---------- 头部 ----------

    def _header(self, agent: str, sid: str, model: str) -> QWidget:
        row = QHBoxLayout()
        row.setSpacing(S.s2)
        row.addWidget(icon_widget("AUTO_AWESOME_OUTLINED", 22, C.brand_700))
        row.addWidget(txt(t("会话现场"), F.h2, 700, C.ink_900))
        row.addWidget(chip(agent, "brand"))
        if sid:
            row.addWidget(chip(sid[:8], "ink"))
        mb = _basename(model)
        if mb:
            row.addWidget(chip(mb[:26], "info"))
        row.addStretch(1)
        w = QWidget()
        w.setLayout(row)
        return w

    # ---------- 顶部数据条 ----------

    def _stats_strip(self, data: dict) -> QWidget:
        req = int(data.get("req_count") or 0)
        corr = int(data.get("correction_hits") or 0)
        n_ev = len([e for e in (data.get("events") or []) if isinstance(e, dict)])
        proj = _basename(str(data.get("project") or ""))
        cells = [(str(req), t("轮次")), (str(corr), t("纠正")),
                 (str(n_ev), t("操作")), (proj[:10] or "—", t("项目"))]
        strip = card(secondary=True)
        inner = QHBoxLayout()
        inner.setSpacing(0)
        inner.setContentsMargins(0, 0, 0, 0)
        for i, (val, key) in enumerate(cells):
            if i:
                inner.addWidget(_vline())
            cell = QVBoxLayout()
            cell.setSpacing(S.s1)
            v = txt(val, F.h1, 800, C.brand_700)
            v.setAlignment(Qt.AlignHCenter)
            k = txt(key, F.caption, 500, C.ink_500)
            k.setAlignment(Qt.AlignHCenter)
            cell.addWidget(v)
            cell.addWidget(k)
            cw = QWidget()
            cw.setLayout(cell)
            inner.addWidget(cw, 1)
        holder = QWidget()
        holder.setLayout(inner)
        strip.layout().addWidget(holder)
        return strip

    # ---------- 面板外壳 ----------

    def _panel(self, icon: str, title: str, count: int):
        c = card()
        head = QHBoxLayout()
        head.setSpacing(S.s1)
        head.addWidget(icon_widget(icon, 18, C.ink_500))
        head.addWidget(txt(title, F.body, 700, C.ink_700))
        head.addWidget(txt(f"· {count}", F.caption, 500, C.ink_300))
        head.addStretch(1)
        hw = QWidget()
        hw.setLayout(head)
        c.layout().addWidget(hw)
        body = QVBoxLayout()
        body.setSpacing(0)
        c.layout().addLayout(body)
        return c, body

    # ---------- 对话面板 ----------

    def _transcript_panel(self, data: dict):
        users = [m for m in (data.get("user_messages") or [])
                 if not _is_system_noise(m) and str(m).strip()]
        ai = [m for m in (data.get("assistant_messages") or []) if str(m).strip()]
        # 按回合交替配对（user[i] → ai[i]），不再"全部用户+全部AI"拼接后切尾丢用户
        msgs = []
        for u, a in zip_longest(users, ai):
            if u is not None:
                msgs.append(("user", str(u)))
            if a is not None:
                msgs.append(("ai", str(a)))
        if not msgs:
            return None
        c, body = self._panel("EDIT_OUTLINED", t("对话"), len(msgs))
        collapsed = len(msgs) > 14
        for role, m in (msgs[-14:] if collapsed else msgs):
            body.addWidget(self._msg_row(role, m))
        if collapsed:
            body.addWidget(txt(t("（仅显示最近 14 条，向上滚动看更早）"),
                               F.caption, 400, C.ink_500))
        return c

    def _msg_row(self, role: str, text: str) -> QWidget:
        is_user = role == "user"
        row = QHBoxLayout()
        row.setContentsMargins(0, S.s3, 0, S.s3)
        row.setSpacing(S.s3)
        tag = txt(t("你") if is_user else t("AI"), F.caption, 800,
                  C.brand_700 if is_user else C.info_fg)
        tag.setFixedWidth(24)
        tag.setAlignment(Qt.AlignTop)
        row.addWidget(tag)
        row.addWidget(self._msg_body(text), 1)
        w = QWidget()
        w.setLayout(row)
        return w

    def _msg_body(self, text: str) -> QWidget:
        """一条消息正文：Markdown 富文本（``md_view``）。

        旧版 ``txt(text[:1200])`` 硬切：既切在句子中间，又永远看不到全文。
        改为超长时先折叠、给「展开全文（还有 N 字）」按钮，点开换成完整正文。
        """
        full = str(text or "")
        if len(full) <= _MSG_LIMIT:
            return md_view(full, compact=True)
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(S.s1)
        v.addWidget(md_view(full[:_MSG_LIMIT], compact=True))
        btn = btn_flat(t("展开全文（还有 {n} 字）", n=len(full) - _MSG_LIMIT))
        btn.clicked.connect(lambda: self._expand_msg(holder, full))
        btn_w = QWidget()
        bl = QHBoxLayout(btn_w)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(btn)
        bl.addStretch(1)
        v.addWidget(btn_w)
        return holder

    @staticmethod
    def _expand_msg(holder: QWidget, full: str) -> None:
        """折叠 → 全文：清空子件换成完整 md_view（读态，不再截断）。"""
        lay = holder.layout()
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        lay.addWidget(md_view(full, compact=True))

    # ---------- 操作时间线面板 ----------

    def _events_panel(self, data: dict):
        events = [e for e in (data.get("events") or []) if isinstance(e, dict)]
        if not events:
            return None
        c, body = self._panel("TERMINAL_OUTLINED", t("操作时间线"), len(events))
        collapsed = len(events) > 15
        for ev in (events[-15:] if collapsed else events):
            body.addWidget(self._event_row(ev))
        if collapsed:
            body.addWidget(txt(t("（仅显示最近 15 步）"),
                               F.caption, 400, C.ink_500))
        return c

    def _event_row(self, ev: dict) -> QWidget:
        if ev.get("ex") is not None:
            ok = ev.get("ex") == 0
        else:
            ok = not ev.get("e")
        row = QHBoxLayout()
        row.setContentsMargins(0, S.s3, 0, S.s3)
        row.setSpacing(S.s2)
        row.addWidget(chip(t("成功") if ok else t("失败"), "ok" if ok else "err"))
        ts = _ts(ev)
        if ts:
            row.addWidget(txt(ts, F.caption, 500, C.ink_300))
        row.addWidget(chip(str(ev.get("tool") or "?")[:14], "ink"))
        detail = str(ev.get("cmd") or ev.get("file") or "")
        sig = str(ev.get("sig") or "")
        if detail:
            lab = mono(detail[:60])
            lab.setToolTip(detail if not sig else f"{detail}\n{sig}")
            row.addWidget(lab, 1)
        else:
            row.addStretch(1)
        if sig and not ok:
            sl = txt(sig[:40], F.caption, 400, C.err_fg)
            sl.setToolTip(sig)
            row.addWidget(sl)
        w = QWidget()
        w.setLayout(row)
        return w
