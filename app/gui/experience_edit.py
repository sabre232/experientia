"""经验编辑对话框：纠正 = 直接改内容。

一张卡合并了同 task 的多条记录（多个做法），这里逐条列出、各给一组可编辑
字段，保存时逐条写回——不会改错条。字段预填原文优先（卡片展开看到的全文），
没改动就不发请求；单条失败即停并提示，不静默丢改动。
"""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QHBoxLayout, QPlainTextEdit,
                               QScrollArea, QVBoxLayout, QWidget)

from .api_client import LocalApi, LocalApiError
from .i18n import t
from .qt_theme import btn_primary, btn_secondary, card, txt
from .theme import C, F, S

# 字段顺序 = 卡片展示顺序；值取原文优先（key_raw），用户看到的就是展开后的全文。
# 标签是用户可见字符串，渲染时走 t()（模块级冻结会
# 让非中文界面滞留中文；zh 恒等，「踩坑」「做法」复用既有词条，「标题」「结果」新增）。
_FIELDS = (("task", "标题"), ("state", "踩坑"), ("action", "做法"),
           ("outcome", "结果"))
_FIELD_H = {"task": 96, "state": 84, "action": 84, "outcome": 72}


class ExperienceEditDialog(QDialog):
    """纠正对话框：逐条编辑卡内全部经验记录。"""

    def __init__(self, api: LocalApi, recs: list[dict], parent=None):
        super().__init__(parent)
        self.api = api
        self._recs = list(recs)
        self._edits: list[dict[str, QPlainTextEdit]] = []
        self._status = txt("", F.caption, color=C.err_fg)
        self._status.setWordWrap(True)
        self._build()

    # ---------- 构建 ----------

    def _build(self) -> None:
        self.setWindowTitle(t("纠正经验"))
        lay = QVBoxLayout(self)
        lay.setSpacing(S.s3)
        lay.setContentsMargins(S.s4, S.s4, S.s4, S.s4)

        if len(self._recs) > 1:
            hint = t("这次任务有 {n} 个做法，逐条改，保存时一起写回",
                     n=len(self._recs))
        else:
            hint = t("改成对的内容，保存后就是这条经验的正式内容")
        hint_lbl = txt(hint, F.caption, color=C.ink_500)
        hint_lbl.setWordWrap(True)
        lay.addWidget(hint_lbl)

        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(S.s3)
        for idx, rec in enumerate(self._recs):
            col.addWidget(self._rec_card(rec, idx))
        col.addStretch(1)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(inner)
        lay.addWidget(area, 1)

        row = QHBoxLayout()
        row.setSpacing(S.s2)
        row.addStretch(1)
        row.addWidget(btn_secondary(t("取消"), on_click=self.reject))
        row.addWidget(btn_primary(t("保存"), on_click=self._save))
        lay.addLayout(row)
        lay.addWidget(self._status)
        self.resize(760, 640)

    def _rec_card(self, rec: dict, idx: int) -> QWidget:
        c = card()
        cl = c.layout()
        meta = " · ".join(x for x in (str(rec.get("agent") or ""),
                                      str(rec.get("ts") or "")[:10]) if x)
        if len(self._recs) > 1:
            head = f"{t('第 {n} 个做法', n=idx + 1)}" + (f" · {meta}" if meta else "")
            cl.addWidget(txt(head, F.caption, color=C.ink_500))
        elif meta:
            cl.addWidget(txt(meta, F.caption, color=C.ink_500))
        edits: dict[str, QPlainTextEdit] = {}
        for key, label in _FIELDS:
            value = str(rec.get(key + "_raw") or rec.get(key) or "").strip()
            cl.addWidget(txt(t(label), F.caption, color=C.ink_500))
            tf = QPlainTextEdit(value)
            tf.setFixedHeight(_FIELD_H.get(key, 84))
            cl.addWidget(tf)
            edits[key] = tf
        self._edits.append(edits)
        return c

    # ---------- 保存 ----------

    def _save(self) -> None:
        changed = 0
        for rec, edits in zip(self._recs, self._edits):
            fields: dict[str, str] = {}
            for key, tf in edits.items():
                new = tf.toPlainText().strip()
                old = str(rec.get(key + "_raw") or rec.get(key) or "").strip()
                if new != old:
                    fields[key] = new
            if not fields:
                continue
            try:
                self.api.edit_experience(str(rec.get("id")), fields)
            except LocalApiError as exc:
                self._status.setText(exc.localized())
                return
            changed += 1
        if not changed:
            self._status.setText(t("没有改动"))
            return
        self.accept()
