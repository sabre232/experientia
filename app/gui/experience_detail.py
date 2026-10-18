"""经验详情 / 演化链对话框（P0-3 的用户可见出口）。

回答三个问题，都是用户在经验库里最常问的：

1. **这条经验凭什么这么写？** —— 证据区：原话引文 + 来源（模型引用 / 验收收尾 /
   原文兜底）+ "看原话"钻回当时的会话现场。
2. **它被改过吗？** —— 演化区：历史版本 + 当前头，标出每版的 revision 与做法。
3. **想反悔怎么办？** —— 操作区：回滚到某一旧版（以新版本落库，历史不被改写）、
   遗忘（软忘可逆，当场就能恢复；硬删需二次确认）。

设计约束（沿用项目既有口径）：

- 只读展示 + 显式操作，**没有"顺手改内容"**——改内容走纠正对话框，
  这里只做"看"与"回滚/遗忘"，两类用户意图不混在一个入口。
- 所有文案走 `t()`；UI 组件全部复用 qt_theme，不裸写样式。
- 每个操作失败都把服务端原因原样显示，不静默吞。
- 构造期与点击期的取数都走后台线程：本地 API 无响应时开窗不卡死 UI，
  主线程零 HTTP；取数落定由信号回填。
- 成功回执交上层页面状态行：回滚 / 硬删 / 恢复三类成功都紧接着关窗，
  写在窗内状态行用户根本看不到。
"""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QHBoxLayout, QScrollArea,
                               QVBoxLayout, QWidget)

from .api_client import LocalApi, LocalApiError
from .i18n import t
from .page_base import ApiWorker, clear_layout
from .qt_dialogs import confirm_dialog
from .qt_theme import btn_flat, btn_primary, btn_secondary, card, chip, mono, txt
from .theme import C, F, S

# 动态键：值是中文源串、运行时才套 t()，AST 守卫抓不到（与 connect_page 的
# _TOOL_DESC 同型）。tests/test_i18n.py 对此表有定点守卫，改文案要同步补 7 语。
_SOURCE_LABEL = {
    "session": "会话原话",
    "capture": "上报原文",
    "user": "用户确认",
}


def _localized_work(fn):
    """工作线程里的 ``LocalApiError`` → 显示文案再抛（L11/L12）。

    ``ApiWorker`` 的 error 信号只带 ``str(exc)``，而 LocalApiError 的 str 就是
    服务端中文源串；GUI 显示一律过 ``t()``（翻译是外壳的事）。
    """
    def run():
        try:
            return fn()
        except LocalApiError as exc:
            raise RuntimeError(exc.localized()) from None
    return run


class ExperienceDetailDialog(QDialog):
    """一条经验的证据 + 演化链 + 回滚/遗忘。"""

    def __init__(self, api: LocalApi, rec: dict, parent=None, on_done=None):
        super().__init__(parent)
        self.api = api
        self.rec = dict(rec or {})
        # 成功回执的落脚点。回滚 / 硬删 / 恢复成功后本窗随即 accept()
        # 关窗，写在窗内状态行等于没写；由上层页面传它的 set_status 进来，
        # 关窗后文案仍在页面状态行上。无上层（对话框被单独打开）时落窗内。
        self._on_done = on_done
        self._status = txt("", F.caption, color=C.err_fg)
        self._status.setWordWrap(True)
        self._chain: dict = {}
        # 取数线程清单（持有 Python 强引用防 GC）。done() 关窗前等在飞
        # 线程——运行中的 QThread 随对话框析构会直接 abort（Qt 生命周期红线，
        # 与 PageBase._wait_inflight 同一口径）。
        self._workers: list = []
        self._build()

    # ---------- 构建 ----------

    def _build(self) -> None:
        self.setWindowTitle(t("经验详情"))
        lay = QVBoxLayout(self)
        lay.setSpacing(S.s3)
        lay.setContentsMargins(S.s4, S.s4, S.s4, S.s4)

        meta = " · ".join(x for x in (
            str(self.rec.get("agent") or ""),
            str(self.rec.get("ts") or "")[:19],
            f"{self.rec.get('trunk') or ''}/{self.rec.get('category') or ''}",
        ) if x)
        if meta:
            lay.addWidget(txt(meta, F.caption, color=C.ink_500))

        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(S.s3)
        col.addWidget(self._evidence_card())
        col.addWidget(self._chain_card())
        col.addStretch(1)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(inner)
        lay.addWidget(area, 1)

        lay.addLayout(self._action_row())
        lay.addWidget(self._status)
        self.resize(680, 640)

    def _evidence_card(self) -> QWidget:
        c = card(title=t("凭什么这么说"))
        cl = c.layout()
        quote = self._quote()
        if not quote:
            cl.addWidget(txt(t("这条经验没有带原话证据（可能是早期数据或用户直接确认的）"),
                             F.body, color=C.ink_500))
            return c
        cl.addWidget(txt("“" + quote + "”", F.body, color=C.ink_900))
        row = QHBoxLayout()
        row.setSpacing(S.s2)
        label = _SOURCE_LABEL.get(self._source())
        if label:
            row.addWidget(chip(t(label), tone="info"))
        row.addStretch(1)
        if self.rec.get("session_id"):
            row.addWidget(btn_flat(t("看原话"),
                                   on_click=lambda _=False: self._open_session()))
        cl.addLayout(row)
        return c

    def _chain_card(self) -> QWidget:
        c = card(title=t("它被改过吗"))
        cl = c.layout()
        # 构造期不同步取链——本地 API 无响应时旧实现让开窗直接卡死。
        # 先以「读取中…」开出，取数落定再由信号回填。
        self._chain_body = QVBoxLayout()
        self._chain_body.setSpacing(S.s2)
        cl.addLayout(self._chain_body)
        self._chain_body.addWidget(
            txt(t("读取中…"), F.caption, color=C.ink_500))
        self._start_worker(
            _localized_work(
                lambda: self.api.experience_chain(str(self.rec.get("id")))),
            self._chain_loaded, self._chain_failed)
        return c

    def _chain_loaded(self, data) -> None:
        clear_layout(self._chain_body)
        self._chain = data or {}
        data = (self._chain or {}).get("chain") or {}
        current, revisions = data.get("current") or {}, data.get("revisions") or []
        depth = int(data.get("depth") or (len(revisions) + 1))
        if depth <= 1:
            self._chain_body.addWidget(
                txt(t("还没被改过，这是第 1 版"), F.body, color=C.ink_500))
            return

        self._chain_body.addWidget(txt(t("共 {n} 版，下面是历史改动",
                                         n=depth), F.caption, color=C.ink_500))
        head = QHBoxLayout()
        head.setSpacing(S.s2)
        head.addWidget(mono(f"v{current.get('revision', 1)}"))
        head.addWidget(txt(str(current.get("action") or "")[:40], F.body), 1)
        head.addWidget(chip(t("当前"), tone="ok"))
        self._chain_body.addLayout(head)

        for rev in sorted(revisions, key=lambda r: int(r.get("revision") or 0),
                          reverse=True):
            row = QHBoxLayout()
            row.setSpacing(S.s2)
            row.addWidget(mono(f"v{rev.get('revision', '?')}"))
            row.addWidget(txt(str(rev.get("action") or "")[:40], F.caption), 1)
            row.addWidget(btn_flat(
                t("回到这版"),
                on_click=lambda _=False, r=int(rev.get("revision") or 0):
                    self._rollback(r)))
            self._chain_body.addLayout(row)

    def _chain_failed(self, err: str) -> None:
        clear_layout(self._chain_body)
        self._chain_body.addWidget(
            txt(t("读不到演化链：{err}", err=err), F.caption, color=C.ink_500))

    def _action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(S.s2)
        row.addStretch(1)
        self._btn_forget = btn_flat(t("忘了这条"),
                                    on_click=lambda _=False: self._forget(False))
        self._btn_hard = btn_secondary(t("彻底删除"),
                                       on_click=lambda _=False: self._forget(True))
        # 软忘成功后才现身——unforget 此前的全仓死代码状态，靠这个入口
        # 兑现「可从回收恢复」的承诺（api_client.unforget_experience 第一个
        # 调用方）。
        self._btn_restore = btn_flat(t("恢复"),
                                     on_click=lambda _=False: self._restore())
        self._btn_restore.hide()
        for b in (self._btn_forget, self._btn_hard, self._btn_restore):
            row.addWidget(b)
        row.addWidget(btn_primary(t("关闭"), on_click=self.accept))
        return row

    # ---------- 操作 ----------

    def _open_session(self) -> None:
        agent = str(self.rec.get("agent") or "")
        sid = str(self.rec.get("session_id") or "")
        if not (agent and sid):
            return
        # 点击期也不同步 HTTP——长会话的取数会把主线程卡住（另两处
        # 同操作都走后台线程）。先亮进行时，取数落定再开抽屉。
        self._status.setText(t("正在打开当时的会话…"))
        self._start_worker(
            _localized_work(lambda: self.api.session_view(agent, sid)),
            self._session_loaded,
            lambda err: self._status.setText(
                t("打不开当时的会话：{err}", err=err)))

    def _session_loaded(self, data) -> None:
        self._status.setText("")
        from .session_drawer import SessionDrawer
        # 口径（growth.py 样板）：exec 后释放——抽屉持整份会话转录，
        # 长会话反复查看不释放会持续吃内存
        drawer = SessionDrawer(data, self)
        drawer.exec()
        drawer.deleteLater()

    def _rollback(self, revision: int) -> None:
        if not confirm_dialog(
                t("回到第 {n} 版", n=revision),
                t("会以新的一版写入（历史保留、不被覆盖），确定回滚吗？"), self):
            return
        try:
            self.api.rollback_experience(
                str(self.rec.get("id")), revision)
        except LocalApiError as exc:
            self._status.setText(exc.localized())
            return
        # 回滚改变了列表内容 → 关窗让上层刷新（与纠正对话框同一套刷新口径）。
        # 不在这里做原地重建：手工拆 layout 是 Qt 内存事故的高发区。
        # 成功文案经 _notify 交上层——本窗紧接着 accept() 就没了。
        self._notify(t("已回到第 {n} 版", n=revision))
        self.accept()

    def _forget(self, hard: bool) -> None:
        if hard and not confirm_dialog(
                t("彻底删除"),
                t("彻底删除不可撤销（只留 30 天归档副本），确定吗？"), self):
            return
        try:
            self.api.forget_experience(str(self.rec.get("id")), hard=hard)
        except LocalApiError as exc:
            self._status.setText(exc.localized())
            return
        if hard:
            self._notify(t("已彻底删除"))
            self.accept()
            return
        # 软忘不关窗：当场给出「恢复」入口——L13 之前 unforget 是全仓死代码，
        # 「可从回收恢复」这句承诺没有兑现的地方。
        self._status.setText(t("已遗忘，可从回收恢复"))
        self._btn_forget.hide()
        self._btn_hard.hide()
        self._btn_restore.show()

    def _restore(self) -> None:
        try:
            self.api.unforget_experience(str(self.rec.get("id")))
        except LocalApiError as exc:
            self._status.setText(exc.localized())
            return
        self._notify(t("已恢复"))
        self.accept()

    def _notify(self, msg: str) -> None:
        """操作成功回执的落脚点。"""
        if self._on_done is not None:
            self._on_done(msg)
        else:
            self._status.setText(msg)

    # ---------- 后台取数 ----------

    def _start_worker(self, work, on_ok, on_err) -> None:
        """后台线程取数 + 信号回填。线程引用挂本对话框清单；完成即摘除并
        deleteLater（先摘登记再释放，PageBase.run_async 同一套口径）。"""
        worker = ApiWorker(work, self)
        self._workers.append(worker)
        worker.finished.connect(on_ok)
        worker.error.connect(on_err)

        def _rel(*_a):
            try:
                self._workers.remove(worker)
            except ValueError:
                pass

        worker.finished.connect(_rel)
        worker.error.connect(_rel)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        worker.start()

    def done(self, result: int) -> None:
        # 关窗前等在飞取数线程：运行中的 QThread 随对话框析构会直接 abort
        # （无 Python 栈，难查）。等完再走正常关闭路径。
        for w in list(self._workers):
            try:
                w.wait(5000)
            except Exception:  # noqa: BLE001 收尾尽力而为，不因单条失败卡住关窗
                pass
        super().done(result)

    # ---------- 辅助 ----------

    def _quote(self) -> str:
        from ..distill import evidence as _evidence

        return _evidence.quote_of(self.rec)

    def _source(self) -> str:
        ev = self.rec.get("evidence")
        if isinstance(ev, dict):
            return str(ev.get("source") or "")
        return ""
