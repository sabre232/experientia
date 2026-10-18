"""通用对话框工厂（迁移清单 ，替代 ui.py 的 dialog 函数）。

confirm/info/input 三个基础弹层用自定义 QDialog 组装：主题化暖色外观 +
i18n 按钮（原生 QMessageBox/QInputDialog 在中文界面显示英文 Yes/No/OK/Cancel，
且图标风格与吉祥物设计家族冲突）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from .i18n import t
from .layout import code_box_size as _layout_code_size
from .layout import dialog_width as _layout_dialog_width
from .qt_theme import status_tone, txt
from .theme import C, F, R, S


def _parent_size(parent):
    """父窗口逻辑尺寸（C 类尺寸派生底料）；取不到返回 None。"""
    if parent is None:
        return None
    w = parent.window()
    if w is None:
        return None
    s = w.size()
    return (s.width(), s.height()) if s.width() > 0 else None


def _dlg_w(parent, fallback: int) -> int:
    """对话框最小宽：窗口宽 85% 夹 [420,720]（C 类）；取不到父窗用 fallback。"""
    sz = _parent_size(parent)
    return _layout_dialog_width(sz) if sz else fallback


def _code_size(parent) -> tuple[int, int]:
    """代码框（宽,高）：窗口 60%×55% 夹取；取不到父窗用默认。"""
    sz = _parent_size(parent)
    return _layout_code_size(sz) if sz else (640, 480)


def _btn_row(dlg: QDialog, buttons: list[tuple[str, str]]) -> QHBoxLayout:
    """右对齐按钮行：[(标签, objectName)]，返回的布局已 addWidget 各按钮。"""
    row = QHBoxLayout()
    row.setSpacing(S.s2)
    row.addStretch(1)
    for label, name in buttons:
        b = QPushButton(label)
        b.setObjectName(name)
        b.setFixedHeight(S.s8)
        row.addWidget(b)
    return row


def confirm_dialog(title: str, message: str, parent=None) -> bool:
    """确认对话框（主题化 + i18n），返回 True/False。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(_dlg_w(parent, 400))
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(S.s6, S.s6, S.s6, S.s6)
    lay.setSpacing(S.s4)
    lay.addWidget(txt(title, F.h2, 600))
    body = txt(message, F.body, color=C.ink_700)
    body.setWordWrap(True)
    lay.addWidget(body)
    lay.addLayout(_btn_row(dlg, [(t("取消"), "no"), (t("确认"), "yes")]))
    yes, no = dlg.findChild(QPushButton, "yes"), dlg.findChild(QPushButton, "no")
    yes.setDefault(True)
    yes.setStyleSheet(
        f"QPushButton {{ background: {C.primary_fill}; color: {C.on_brand};"
        f" border: none; border-radius: {R.md}px; font-weight: 600; }}")
    no.clicked.connect(dlg.reject)
    yes.clicked.connect(dlg.accept)
    # 先取结果再释放（exec 返回即已完结）
    accepted = dlg.exec() == QDialog.Accepted
    dlg.deleteLater()
    return accepted


def info_dialog(title: str, message: str, parent=None) -> None:
    """信息提示弹层（主题化 + i18n）。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(_dlg_w(parent, 400))
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(S.s4, S.s4, S.s4, S.s4)
    lay.setSpacing(S.s4)
    lay.addWidget(txt(title, F.h2, 600))
    body = txt(message, F.body, color=C.ink_700)
    body.setWordWrap(True)
    lay.addWidget(body)
    lay.addLayout(_btn_row(dlg, [(t("确认"), "ok")]))
    ok = dlg.findChild(QPushButton, "ok")
    ok.setDefault(True)
    ok.setStyleSheet(
        f"QPushButton {{ background: {C.primary_fill}; color: {C.on_brand};"
        f" border: none; border-radius: {R.md}px; font-weight: 600; }}")
    ok.clicked.connect(dlg.accept)
    dlg.exec()
    # exec 后显式释放——带 parent 的 QDialog 不删会作为
    # 子控件挂在页面上只增不减（与 models/methods/export_page 同一范式）。
    dlg.deleteLater()


def rich_info_dialog(title: str, html: str, parent=None) -> None:
    """富文本信息弹层（主题化 + i18n）：替代原生 QMessageBox。

    原生 QMessageBox 的按钮在中文界面显示英文
    Yes/No/OK/Cancel、图标风格与品牌冲突，是 qt_dialogs 要替代的形态；
    原 growth/experiences 两处 QMessageBox 还都不释放（叠加 M13）。
    html 由调用方负责转义（内容来自模型解释，已限纯文本拼接）。
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(_dlg_w(parent, 440))
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(S.s6, S.s6, S.s6, S.s6)
    lay.setSpacing(S.s4)
    lay.addWidget(txt(title, F.h2, 600))
    body = QLabel(html)
    body.setTextFormat(Qt.RichText)
    body.setWordWrap(True)
    body.setTextInteractionFlags(Qt.TextBrowserInteraction)
    body.setStyleSheet(f"color: {C.ink_700}; font-size: {F.body}px;")
    lay.addWidget(body)
    lay.addLayout(_btn_row(dlg, [(t("确认"), "ok")]))
    ok = dlg.findChild(QPushButton, "ok")
    ok.setDefault(True)
    ok.setStyleSheet(
        f"QPushButton {{ background: {C.primary_fill}; color: {C.on_brand};"
        f" border: none; border-radius: {R.md}px; font-weight: 600; }}")
    ok.clicked.connect(dlg.accept)
    dlg.exec()
    dlg.deleteLater()


def input_dialog(title: str, label: str, parent=None, default: str = "") -> str | None:
    """单行输入对话框（主题化 + i18n），返回输入文本或 None。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(_dlg_w(parent, 420))
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(S.s6, S.s6, S.s6, S.s6)
    lay.setSpacing(S.s3)
    lay.addWidget(txt(title, F.h2, 600))
    if label:
        lay.addWidget(txt(label, F.caption, color=C.ink_500))
    edit = QLineEdit(default)
    edit.selectAll()
    edit.setFocus()
    lay.addWidget(edit)
    lay.addLayout(_btn_row(dlg, [(t("取消"), "cancel"), (t("确认"), "ok")]))
    ok, cancel = dlg.findChild(QPushButton, "ok"), dlg.findChild(QPushButton, "cancel")
    ok.setDefault(True)
    ok.setStyleSheet(
        f"QPushButton {{ background: {C.primary_fill}; color: {C.on_brand};"
        f" border: none; border-radius: {R.md}px; font-weight: 600; }}")
    cancel.clicked.connect(dlg.reject)
    ok.clicked.connect(dlg.accept)
    if dlg.exec() == QDialog.Accepted:
        text = edit.text()
        dlg.deleteLater()  # exec 后释放
        return text if text else None
    dlg.deleteLater()
    return None


# ======== Skill 预览 / 版本历史 / 来源（方法页与整理 Skill 区共用） ========

def confirm_skill_export(parent, scope: str | None, items: list[dict],
                         name: str | None = None, description: str | None = None,
                         out_of_scope: int = 0) -> bool:
    """导出前确认弹层：展示将打包的范围与数量，确认才继续。

    - scope：路径 A 传类别显示名（「类别：xxx」）；路径 B 传 None（显示条数）。
    - items：本次实际将打包的经验（计数用）。
    - out_of_scope：已选但在当前筛选范围外、不会被打包的条数（>0 时给提示）。
    返回 True=确认生成 / False=取消。
    """
    from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout

    from .qt_theme import btn_primary, btn_secondary

    dlg = QDialog(parent)
    dlg.setWindowTitle(t("导出 Skill"))
    lay = QVBoxLayout(dlg)
    lay.setSpacing(S.s3)

    cats = len({(e.get("trunk") or "其他", e.get("category") or "未分类")
                for e in items})
    if scope:
        head = f"{t('类别：{name}', name=scope)} · {t('{n} 条', n=len(items))}"
    else:
        head = t("将打包 {n} 条经验（跨 {c} 个类别）", n=len(items), c=cats)
    lay.addWidget(txt(head, F.body, 600, C.ink_900))
    if name:
        lay.addWidget(txt(t("Skill 名：{name}", name=name), F.body,
                          color=C.ink_700))
    if description:
        lay.addWidget(txt(t("描述：{desc}", desc=description), F.caption,
                          color=C.ink_500))
    if out_of_scope > 0:
        lay.addWidget(txt(t("另有 {n} 条已选不在当前范围，不会打包——切到「全部」可一起导出",
                            n=out_of_scope), F.caption, color=C.warn_fg))

    btn_row = QHBoxLayout()
    btn_row.setSpacing(S.s2)
    cancel = btn_secondary(t("取消"))
    cancel.clicked.connect(dlg.reject)
    ok = btn_primary(t("确认导出"))
    ok.clicked.connect(dlg.accept)
    btn_row.addWidget(cancel)
    btn_row.addStretch(1)
    btn_row.addWidget(ok)
    lay.addLayout(btn_row)
    # 先取结果再释放
    accepted = dlg.exec() == QDialog.DialogCode.Accepted
    dlg.deleteLater()
    return accepted


def _dlg(parent, title: str, body: QWidget, actions: list[QPushButton],
         width: int | None = None) -> QDialog:
    """标准弹层组装。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    lay.setSpacing(S.s3)
    lay.addWidget(body)
    btn_row = QHBoxLayout()
    btn_row.setSpacing(S.s2)
    for b in actions:
        btn_row.addWidget(b)
    lay.addLayout(btn_row)
    if width:
        dlg.setMinimumWidth(width)
    return dlg


def skill_preview_dialog(api, md: str, name: str = "", source_count: int = 0,
                         description: str = "", parent=None,
                         on_saved=None) -> QDialog:
    """SKILL.md 预览弹层：代码框 + 状态行 + 关闭/版本历史/复制/保存。

    对应 ui.skill_preview_dialog。on_saved(r) 保存成功后回调。
    """
    from PySide6.QtWidgets import QApplication, QPlainTextEdit

    from .api_client import LocalApiError
    from .qt_theme import btn_primary, btn_secondary

    msg = txt("", F.caption, color=C.info_fg)
    dlg = QDialog(parent)
    dlg.setWindowTitle(t(f"{t('SKILL.md 预览')} · {name}") if name else t("SKILL.md 预览"))
    lay = QVBoxLayout(dlg)
    lay.setSpacing(S.s2)

    edit = QPlainTextEdit(md)
    edit.setReadOnly(True)
    _w, _h = _code_size(parent)
    edit.setFixedSize(_w, _h)
    edit.setStyleSheet(f"""
        QPlainTextEdit {{
            font-family: "Consolas", "Menlo", monospace;
            font-size: {F.caption}px;
            background: {C.surface_2};
            border: 1px solid {C.line};
            border-radius: {R.md}px;
            padding: 12px;
            color: {C.ink_700};
        }}
    """)
    lay.addWidget(edit)
    lay.addWidget(msg)

    def set_msg(m: str, tone: str = "err") -> None:
        msg.setText(m)
        status_tone(msg, C.err_fg if tone == "err" else C.ok_fg)

    def copy() -> None:
        QApplication.clipboard().setText(md)
        set_msg(t("已复制到剪贴板"), "ok")

    def save() -> None:
        if not name:
            set_msg(t("先填 Skill 名再保存"))
            return
        try:
            r = api.skill_save(name, md, description=description or None,
                               source_count=source_count)
            # skill_save 会新建/更新方法名 → 作废 name_map。
            # 去重 R2：原先只有 skill_organize 那份被作废，inject_preview 的类别
            # 下拉仍顶着旧名；现在两份合成一份，这里一次作废两边同时生效。
            from ._name_map import invalidate
            invalidate()
            set_msg(t("已保存为 {name} v{n}", name=name, n=r["version"]), "ok")
            if on_saved:
                on_saved(r)
        except LocalApiError as exc:
            set_msg(exc.localized())

    def versions() -> None:
        if not name:
            set_msg(t("先填 Skill 名再查看版本"))
            return
        try:
            r = api.skill_versions(name)
        except LocalApiError as exc:
            set_msg(exc.localized())
            return
        skill_versions_dialog(
            api, name, r.get("versions", []), dlg,
            on_view_md=lambda m, n: skill_preview_dialog(
                api, m, n, 0, "", dlg, on_saved),
            on_error=set_msg)

    btn_row = QHBoxLayout()
    close = QPushButton(t("关闭"))
    close.clicked.connect(dlg.reject)
    btn_row.addWidget(close)
    btn_row.addWidget(btn_secondary(t("版本历史"), versions))
    btn_row.addStretch(1)
    copy_btn = QPushButton(t("复制"))
    copy_btn.clicked.connect(copy)
    btn_row.addWidget(copy_btn)
    btn_row.addWidget(btn_primary(t("保存"), None, save))
    lay.addLayout(btn_row)
    dlg.setMinimumWidth(_w)
    return dlg


def skill_versions_dialog(api, name: str, versions: list[dict], parent=None,
                          on_view_md=None, on_error=None) -> QDialog:
    """版本历史弹层（v2/v3 可回看、与上一版 diff）。

    对应 ui.skill_versions_dialog。on_view_md(md, name) 打开某版内容。
    """
    from .api_client import LocalApiError
    from .qt_theme import code_box

    def set_err(m: str) -> None:
        if on_error:
            on_error(m)

    dlg = QDialog(parent)
    dlg.setWindowTitle(f"{name} · {t('版本历史')}")
    lay = QVBoxLayout(dlg)
    lay.setSpacing(S.s2)
    body = QVBoxLayout()
    body.setSpacing(S.s1)

    def show_diff(old: int, new: int) -> None:
        try:
            r = api.skill_version_diff(name, old, new)
        except LocalApiError as exc:
            set_err(exc.localized())
            return
        sub = _dlg(dlg, t("版本对比 v{old} → v{new}", old=old, new=new),
                   code_box(r["diff"]), [QPushButton(t("关闭"))],
                   _dlg_w(dlg, 680))
        sub.findChildren(QPushButton)[0].clicked.connect(sub.reject)
        sub.exec()
        sub.deleteLater()  # 子弹层也要释放

    def show_md(n: int) -> None:
        try:
            r = api.skill_version(name, n)
        except LocalApiError as exc:
            set_err(exc.localized())
            return
        if on_view_md:
            on_view_md(r["md"], name)

    if not versions:
        body.addWidget(txt(t("还没有保存过版本"), color=C.ink_500))
    for v in versions:
        row = QHBoxLayout()
        row.addWidget(txt(f"v{v['n']} · {str(v['created_at'])[:10]}", F.body, 600))
        row.addWidget(txt(str(v.get("description", ""))[:60], F.caption,
                          color=C.ink_500))
        row.addStretch(1)
        view = QPushButton(t("查看"))
        view.clicked.connect(lambda _=False, n=v["n"]: show_md(n))
        row.addWidget(view)
        if v["n"] > 1:
            diff = QPushButton(t("对比上一版"))
            diff.clicked.connect(lambda _=False, n=v["n"]: show_diff(n - 1, n))
            row.addWidget(diff)
        row_box = QWidget()
        row_box.setLayout(row)
        body.addWidget(row_box)
    body.addStretch(1)

    body_box = QWidget()
    body_box.setLayout(body)
    lay.addWidget(body_box)
    close = QPushButton(t("关闭"))
    close.clicked.connect(dlg.reject)
    lay.addWidget(close, 0)
    dlg.setMinimumWidth(_dlg_w(parent, 620))
    return dlg


def sources_dialog(api, trunk: str, category: str, n: int,
                   parent=None) -> QDialog:
    """方法 → 来源经验(L1) → session 摘要(L0) 下钻弹层（W3-04）。

    对应 methods._sources_dialog。数据为快速 HTTP 调用，同步加载。
    """
    from PySide6.QtWidgets import QScrollArea

    from .api_client import LocalApiError
    from .qt_theme import code_box  # noqa: F401  （统一视觉用；此处不用）

    dlg = QDialog(parent)
    dlg.setWindowTitle(t("{trunk} / {category}：来自 {n} 条记录",
                         trunk=trunk, category=category, n=n))
    dlg.setMinimumWidth(_dlg_w(parent, 560))
    lay = QVBoxLayout(dlg)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    body = QWidget()
    body_lay = QVBoxLayout(body)
    body_lay.setSpacing(S.s2)
    body_lay.setContentsMargins(0, 0, 0, 0)

    try:
        r = api.skill_sources(trunk, category)
    except LocalApiError as exc:
        body_lay.addWidget(txt(exc.localized(), color=C.err_fg))
        scroll.setWidget(body)
        lay.addWidget(scroll)
        close = QPushButton(t("关闭"))
        close.clicked.connect(dlg.reject)
        lay.addWidget(close)
        return dlg

    for e in r.get("exps", []):
        lines = QVBoxLayout()
        lines.setSpacing(S.s1)
        h = QHBoxLayout()
        h.addWidget(txt(e.get("task", ""), F.body, 600))
        h.addStretch(1)
        h.addWidget(txt(str(e.get("ts", "")), F.caption, color=C.ink_500))
        lines.addLayout(h)
        if e.get("state"):
            lines.addWidget(txt(f"{t('状态')}：{e['state']}", F.caption,
                                color=C.ink_700))
        if e.get("action"):
            lines.addWidget(txt(f"{t('做法')}：{e['action']}", F.caption,
                                color=C.ink_700))
        s = e.get("session")
        if s:
            lines.addWidget(txt(
                t("来自 {agent}（{at}，{n} 轮）：「{first}」",
                  agent=s.get("agent", "?"),
                  at=(str(s.get("started_at") or "")[5:16].replace("T", " ")
                   or t("未知时间")),
                  n=s.get("req_count") or "?", first=s.get("first_msg", "")),
                F.caption, color=C.ink_500))
        box = QWidget()
        box.setObjectName("expSourceBox")
        # #id 限定：裸 QWidget 会给层内每条 txt label 套上 1px 边框
        box.setStyleSheet(f"""
            QWidget#expSourceBox {{ background: {C.surface_2};
                border: 1px solid {C.line}; border-radius: {R.sm}px; }}
        """)
        box.setLayout(lines)
        body_lay.addWidget(box)
    if not r.get("exps"):
        body_lay.addWidget(txt(t("来源记录已不在经验库（可能已被合并淘汰）"),
                               F.caption, color=C.ink_500))
    body_lay.addStretch(1)

    scroll.setWidget(body)
    lay.addWidget(scroll)
    close = QPushButton(t("关闭"))
    close.clicked.connect(dlg.reject)
    lay.addWidget(close)
    dlg.resize(*_code_size(parent))
    return dlg

