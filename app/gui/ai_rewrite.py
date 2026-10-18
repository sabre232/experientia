"""AI 重写预览弹层（第二项蒸馏的"采纳前对比"关口）。

三种形态共用同一套返回码：Accepted(1)=采纳写库 / Rejected(0)=保留现状 /
REDO(2)=重写一遍（再调一次模型）。提案在采纳前绝不落库——用户拍板才算数。
"""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QHBoxLayout, QPlainTextEdit,
                               QScrollArea, QVBoxLayout, QWidget)

from .i18n import t
from .qt_theme import btn_primary, btn_secondary, card, txt
from .theme import C, F, S

REDO = 2  # QDialog.exec() 返回码：重写一遍


def model_required_result() -> dict:
    """无模型 → 结构化拒绝（总纲同型）。

    调用方拿到它**必须提示并引导接入**，不得退回"原样展示"当成功——把没改过的
    原文当 AI 结果给用户，比直接说"做不了"更伤信任（总纲）。
    文案**复用既有目录 key**（不新增近似文案：一条近似句 = 7 份可能漂移的翻译）；
    要带"去「接入」页配置吗"的一步引导，用 `page_base.require_model` 的既有弹窗。
    """
    return {"ok": False, "status": "model_required",
            "message": t("未接入模型，无法完成这一步")}


def is_model_required(payload) -> bool:
    """响应体是否是"没接模型"的结构化拒绝（引擎侧同 status，跨层口径一致）。"""
    return isinstance(payload, dict) and payload.get("status") == "model_required"

# 字段顺序/标签与纠正对话框同源（experience_edit）：标题/踩坑/做法/结果
_FIELDS = (("task", "标题"), ("state", "踩坑"), ("action", "做法"),
           ("outcome", "结果"))


def _action_row(dlg: QDialog, allow_adopt: bool = True) -> QHBoxLayout:
    """右下角三键：不用了 / 重写一遍 / 采纳 AI 结果（主按钮）。"""
    row = QHBoxLayout()
    row.setSpacing(S.s2)
    row.addStretch(1)
    b_no = btn_secondary(t("不用了"))
    b_no.clicked.connect(dlg.reject)
    b_redo = btn_secondary(t("重写一遍"))
    b_redo.clicked.connect(lambda _=False: dlg.done(REDO))
    b_ok = btn_primary(t("采纳 AI 结果"))
    b_ok.clicked.connect(dlg.accept)
    if not allow_adopt:
        b_ok.setEnabled(False)
    row.addWidget(b_no)
    row.addWidget(b_redo)
    row.addWidget(b_ok)
    return row


class ExperienceRewriteDialog(QDialog):
    """经验卡 AI 重写预览：逐条、逐字段"当前值 → AI 建议"对比。"""

    def __init__(self, recs: list[dict], proposals: list[dict], parent=None):
        super().__init__(parent)
        by_id = {str(p.get("id")): p for p in proposals}
        self._build(recs, by_id)

    def _build(self, recs: list[dict], by_id: dict[str, dict]) -> None:
        self.setWindowTitle(t("AI 重写预览"))
        lay = QVBoxLayout(self)
        lay.setSpacing(S.s3)
        lay.setContentsMargins(S.s4, S.s4, S.s4, S.s4)
        hint = txt(t("AI 基于原始记录重写了总结，采纳前不会改动任何内容"),
                   F.caption, color=C.ink_500)
        hint.setWordWrap(True)
        lay.addWidget(hint)

        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(S.s3)
        n_changed = 0
        for idx, rec in enumerate(recs):
            p = by_id.get(str(rec.get("id"))) or {}
            diffs = [(label, str(rec.get(key) or "").strip(),
                      str(p.get(key) or "").strip())
                     for key, label in _FIELDS
                     if str(p.get(key) or "").strip()
                     and str(p.get(key) or "").strip()
                     != str(rec.get(key) or "").strip()]
            if not diffs:
                continue
            n_changed += len(diffs)
            c = card()
            cl = c.layout()
            if len(recs) > 1:
                cl.addWidget(txt(t("第 {n} 个做法", n=idx + 1),
                                 F.caption, color=C.ink_500))
            for label, old, new in diffs:
                cl.addWidget(txt(t(label), F.caption, 600, C.ink_700))
                old_lbl = txt(f"{t('当前值')}：{old or '—'}",
                              F.caption, color=C.ink_500)
                old_lbl.setWordWrap(True)
                cl.addWidget(old_lbl)
                new_lbl = txt(f"{t('AI 建议')}：{new}", F.body,
                              color=C.brand_700)
                new_lbl.setWordWrap(True)
                cl.addWidget(new_lbl)
            col.addWidget(c)
        if not n_changed:
            col.addWidget(txt(t("AI 认为现在的总结已经够好"), F.body,
                              color=C.ink_500))
        col.addStretch(1)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(inner)
        lay.addWidget(area, 1)
        lay.addLayout(_action_row(self, allow_adopt=bool(n_changed)))
        self.resize(720, 560)


def line_rewrite_dialog(parent, old_text: str, new_text: str) -> int:
    """单条坑改写预览：一行当前值 vs 一行 AI 建议。返回 0/1/2。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(t("AI 重写预览"))
    lay = QVBoxLayout(dlg)
    lay.setSpacing(S.s3)
    lay.setContentsMargins(S.s4, S.s4, S.s4, S.s4)
    hint = txt(t("改写保持原意和关键名词，出现次数照常统计"),
               F.caption, color=C.ink_500)
    hint.setWordWrap(True)
    lay.addWidget(hint)
    old_lbl = txt(f"{t('当前值')}：{old_text}", F.body, color=C.ink_500)
    old_lbl.setWordWrap(True)
    lay.addWidget(old_lbl)
    new_lbl = txt(f"{t('AI 建议')}：{new_text}", F.body, 600, C.brand_700)
    new_lbl.setWordWrap(True)
    lay.addWidget(new_lbl)
    lay.addLayout(_action_row(dlg))
    dlg.setMinimumWidth(520)
    return dlg.exec()


def md_rewrite_dialog(parent, new_md: str, old_md: str) -> int:
    """整方法 AI 重写预览：新 playbook 全文 + 当前版本对照。返回 0/1/2。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(t("AI 重写预览"))
    lay = QVBoxLayout(dlg)
    lay.setSpacing(S.s3)
    lay.setContentsMargins(S.s4, S.s4, S.s4, S.s4)
    hint = txt(t("AI 基于该类别全部经验重新总结。采纳前方法保持原样；"
                 "采纳后旧版留快照，可回退"), F.caption, color=C.ink_500)
    hint.setWordWrap(True)
    lay.addWidget(hint)

    def _box(label: str, content: str, h: int) -> None:
        lay.addWidget(txt(t(label), F.caption, 600, C.ink_700))
        tf = QPlainTextEdit(content)
        tf.setReadOnly(True)
        tf.setFixedHeight(h)
        tf.setStyleSheet(
            f"QPlainTextEdit {{ background: {C.surface_2};"
            f" border: 1px solid {C.line}; color: {C.ink_700};"
            f" font-size: {F.caption}px; }}")
        lay.addWidget(tf)

    _box("AI 建议", new_md, 340)
    _box("当前值", old_md, 160)
    lay.addLayout(_action_row(dlg))
    dlg.setMinimumWidth(760)
    return dlg.exec()
