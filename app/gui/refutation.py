"""回炉治理子页（第⑤环 · Qt 版）——「我的经验」页第 5 个 tab。

跨全库聚合 restricted/excluded 的注入条目，分「回炉受限 / 已移出」两组：
- 受限：系统判定反复用错，注入权重降半、排末易被截（经验仍注入）；
- 移出：不再注入（经验仍留库，证真后自动回归）；
每行一条治理，右侧唯一主操作「恢复注入」——用户觉得系统判断过头了可手动
放回正常注入。纯展示 + 逐条恢复，是一切经过 store 只读/写方法，零治库越权。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from .api_client import LocalApi, LocalApiError
from .i18n import t
from .page_base import (PAGE_SIDE_PAD, PageBase, clear_layout, page_scaffold)
from .qt_theme import (btn_primary, card, chip, code_box, empty_state,
                       status_text, txt)
from .qt_widgets import page_header
from .theme import C, F, S


class RefutationPage(PageBase):
    """回炉治理子页：受限/移出条目 + 逐条恢复。"""

    def __init__(self, api: LocalApi, parent=None, embedded: bool = False):
        super().__init__(api, parent)
        self._embedded = embedded
        self._build()

    # ---------- UI ----------

    def _build(self) -> None:
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setSpacing(S.s6)

        # 统一页头（S1）：嵌入容器时 dense 档（h2）；副标题改走页头统一槽位。
        head = page_header(
            t("回炉治理"),
            t("被系统判断反复用错的经验，已降权或停用；证真后自动回归，"
              "也可在这里手动恢复"),
            dense=self._embedded)
        self._title = head.findChild(QLabel, "pageTitle")
        self._subtitle = head.findChild(QLabel, "pageSubtitle")
        cl.addWidget(head)

        self._status_local = status_text("", tone="ok")
        cl.addWidget(self._status_local)

        self._groups = QVBoxLayout()
        self._groups.setSpacing(S.s6)
        cl.addLayout(self._groups)

        cl.addStretch(1)
        # S2：子页滚动区走统一骨架；嵌入容器时顶部留白归 0
        self._layout.addWidget(page_scaffold(
            cl, top=0 if self._embedded else PAGE_SIDE_PAD))

    def _set_status(self, msg: str, tone: str = "err") -> None:
        self.set_status(msg, tone)
        self._status_local.setText(msg)

    # ---------- 数据 ----------

    def refresh(self) -> None:
        self.refresh_all()

    def retranslateUi(self) -> None:
        if self._title is not None:
            self._title.setText(t("回炉治理"))
        if self._subtitle is not None:
            self._subtitle.setText(t(
                "被系统判断反复用错的经验，已降权或停用；证真后自动回归，"
                "也可在这里手动恢复"))
        self.refresh_all()

    def refresh_all(self) -> None:
        """取数进后台线程（主线程零 HTTP），渲染回主线程。"""
        # S5：补首屏骨架（此前本页取数期间无占位）
        self.fetch_and_render(
            lambda: self.api.refutation(), self._render, "refutation",
            skeleton=[24, 72, 72, 72])

    def _render(self, data: dict | None) -> None:
        """渲染回调（主线程）：**不得再发 HTTP**。"""
        clear_layout(self._groups)
        data = data or {}
        items = data.get("items", [])
        if not items:
            self._groups.addWidget(empty_state(
                t("当前没有需要回炉的经验"),
                t("当某条经验被反复用错，会自动出现在这里，供你查看或恢复")))
            return
        restricted = [e for e in items if not e.get("excluded")]
        excluded = [e for e in items if e.get("excluded")]
        if restricted:
            self._groups.addWidget(self._section_header(t("回炉受限"), len(restricted),
                                                        t("使用权重降半，预算紧张时先被截掉")))
            for e in restricted:
                self._groups.addWidget(self._item_card(e, excluded=False))
        if excluded:
            self._groups.addWidget(self._section_header(t("已移出"), len(excluded),
                                                        t("不再自动使用，经验仍保留")))
            for e in excluded:
                self._groups.addWidget(self._item_card(e, excluded=True))

    def _section_header(self, label: str, count: int, note: str) -> QWidget:
        row = QHBoxLayout()
        row.setSpacing(S.s2)
        row.addWidget(txt(label, F.h2, 600))
        row.addWidget(chip(str(count), "warn"))
        row.addSpacing(S.s2)
        row.addWidget(txt(note, F.caption, color=C.ink_500))
        row.addStretch(1)
        head = QWidget()
        head.setLayout(row)
        return head

    def _item_card(self, e: dict, excluded: bool) -> QWidget:
        c = card()
        cl = c.layout()

        # 行 1：分类环 + 证据 + 状态 chip + 恢复主操作
        r1 = QHBoxLayout()
        r1.setSpacing(S.s2)
        r1.addWidget(txt(f"{e.get('trunk')} / {e.get('category')}",
                         F.caption, color=C.ink_500))
        r1.addSpacing(S.s2)
        corr = int(e.get("corroborated") or 0)
        ref = int(e.get("refuted") or 0)
        r1.addWidget(chip(t("佐证 {corr} · 反驳 {ref}", corr=corr, ref=ref), "ink"))
        r1.addWidget(chip(t("已移出") if excluded else t("回炉受限"),
                          "err" if excluded else "warn"))
        r1.addStretch(1)
        restore = btn_primary(t("恢复使用"))
        restore.setCursor(Qt.PointingHandCursor)
        restore.clicked.connect(
            lambda _=False, e_=e: self._restore(restore, e_))
        r1.addWidget(restore)
        r1w = QWidget()
        r1w.setLayout(r1)
        cl.addWidget(r1w)

        cl.addWidget(code_box(e.get("text") or ""))
        return c

    def _restore(self, btn: QPushButton, e: dict) -> None:
        """逐条恢复：清掉受限/移出标记，回到正常注入（经验仍留库）。"""
        btn.setEnabled(False)
        btn.setText(t("正在恢复…"))

        def work():
            return self.api.refutation_restore(
                e["trunk"], e["category"], e["id"])

        def on_done(r):
            if r.get("restored"):
                self._set_status(t("已恢复到正常使用"), "ok")
                self.refresh_all()
            else:
                btn.setText(t("恢复使用"))
                btn.setEnabled(True)
                self._set_status(t("未找到该条目，可能已恢复"))

        def on_error(err):
            btn.setText(t("恢复使用"))
            btn.setEnabled(True)
            self._set_status(t("恢复失败：{err}", err=err))

        self.run_async(work, on_done, on_error)