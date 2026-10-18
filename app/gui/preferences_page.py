"""我的偏好页——Qt 版（原 Flet 源文件 preferences_page.py）。

偏好画像查看/编辑/重新归纳 + 预算占用 + 超限提示。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..proxy.inject import USER_CONFIRM_MARK
from .api_client import LocalApi, LocalApiError
from .i18n import t
from .page_base import (PAGE_SIDE_PAD, PageBase, clear_layout, page_scaffold)
from .qt_theme import (btn_flat, btn_primary, btn_secondary, chip,
                       empty_state, md_view, provenance_bar, txt)
from .qt_widgets import ShadowCard, hover_lift, page_header
from .theme import C, D, F, S


class PreferencesPage(PageBase):
    """偏好子页。"""

    def __init__(self, api: LocalApi, parent=None, embedded: bool = False):
        super().__init__(api, parent)
        self._embedded = embedded
        self._build()

    # ---------- UI 构建 ----------

    def _build(self) -> None:
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(S.s6)

        # 统一页头（S1）：嵌入容器时 dense 档（h2）。
        # 原副标题挂在标题行右侧，现统一到页头下方（与其它页一致）。
        head = page_header(
            t("我的偏好"),
            t("自动归纳，可编辑；标「用户确认」的条目不会被后续归纳覆盖"),
            dense=self._embedded)
        self._title_label = head.findChild(QLabel, "pageTitle")
        self._subtitle_label = head.findChild(QLabel, "pageSubtitle")
        lay.addWidget(head)

        # 顶部溯源条槽位：偏好来自蒸馏 → 带 content_source /
        # generated_at；引擎未透出这两字段时 provenance_bar 返回 None（来源未知
        # 不打扰，契约见 qt_theme.provenance_bar）
        self._prov_box = QWidget()
        self._prov_lay = QVBoxLayout(self._prov_box)
        self._prov_lay.setContentsMargins(0, 0, 0, 0)
        self._prov_lay.setSpacing(S.s2)
        lay.addWidget(self._prov_box)

        # 列表容器
        self._list_box = QWidget()
        self._list_layout = QVBoxLayout(self._list_box)
        self._list_layout.setSpacing(S.s4)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._list_box, 1)

        # P1-2 + S2：子页滚动区走统一骨架；嵌入容器时顶部留白归 0
        self._layout.addWidget(page_scaffold(
            lay, top=0 if self._embedded else PAGE_SIDE_PAD))

        # 懒加载下构建阶段零 API：数据由 MyExperiencePage 的延迟 refresh 填充

    # ---------- 数据刷新 ----------

    def refresh(self) -> None:
        """取数进后台线程（主线程零 HTTP），渲染回主线程。"""
        # S5：补首屏骨架（此前本页取数期间无占位）
        self.fetch_and_render(
            lambda: self.api.preferences(), self._render, "pref",
            skeleton=[24, 88, 88, 88])

    def _render(self, data: dict | None) -> None:
        """渲染回调（主线程）：**不得再发 HTTP**。取数失败 data 为 None。"""
        if data is None:
            return
        items = (data or {}).get("items", [])
        self._render_provenance(items)
        self._clear_layout(self._list_layout)
        if not items:
            self._list_layout.addWidget(empty_state(
                t("还没有偏好"),
                t("偏好会在接入模型后，从你的纠正里归纳出来"),
                mascot="think"))
            return
        for it in items:
            self._list_layout.addWidget(self._pref_card(it))
        # 首屏错峰入场（"只首屏"在基类 stagger_cards 里一处实现）
        self.stagger_cards(self._list_layout)

    def _render_provenance(self, items: list) -> None:
        """顶部溯源条：偏好来自蒸馏 → 读 content_source / generated_at。

        偏好由蒸馏归纳产出 → content_source 标 "model"（可随模型更新）或
        "none"（未接模型，内容为上次生成），provenance_bar 据此决定是否挂条。
        来源未知（旧数据、无字段）时返回 None，不打扰。"""
        clear_layout(self._prov_lay)
        src, gen = "", ""
        for it in items:
            src = str(it.get("content_source") or "")
            gen = str(it.get("generated_at") or "")
            if src:
                break
        bar = provenance_bar({"content_source": src, "generated_at": gen,
                              "has_content": bool(items)})
        if bar is not None:
            self._prov_lay.addWidget(bar)

    # ---------- 重新翻译 ----------

    def retranslateUi(self) -> None:
        if self._title_label is not None:
            self._title_label.setText(t("我的偏好"))
        sub = self._subtitle_label
        if sub is not None:
            sub.setText(t(
                "自动归纳，可编辑；标「用户确认」的条目不会被后续归纳覆盖"))

    def _pref_card(self, it: dict) -> QFrame:
        """单条偏好卡：trunk + 条数 + 编辑 + 重新归纳 + bullets。"""
        bullets = it.get("bullets", [])
        confirmed = set(it.get("confirmed", []))
        trunk = it["trunk"]
        over = it.get("over_budget")

        # 档 2：自绘投影卡片（省逐控件 QGraphicsDropShadowEffect 的 CPU 合成）
        c = ShadowCard()
        cl = c.layout()

        head = QHBoxLayout()
        head.setSpacing(S.s2)
        head.addWidget(txt(trunk, F.h2, 600))
        head.addWidget(txt(
            f" · {t('{n} 条', n=len(bullets))}"
            + (f" {t('（超出自整理阈值）')}" if over else ""),
            F.caption, color=C.ink_500))
        head.addStretch(1)
        head.addWidget(btn_flat(
            t("编辑"), on_click=lambda _=False, tr=trunk,
            md=it["md"]: self._edit_dialog(tr, md)))
        reinduct_btn = btn_flat(t("重新归纳"))
        reinduct_btn.setFixedHeight(D.BTN_H_SM)
        reinduct_btn.clicked.connect(
            lambda _=False, tr=trunk, b=reinduct_btn: self._reinduct(tr, b))
        head.addWidget(reinduct_btn)
        cl.addLayout(head)

        for b in bullets:
            row = QHBoxLayout()
            row.setSpacing(S.s1)
            row.addWidget(txt("·", F.body, color=C.brand_600))
            row.addWidget(txt(b, F.body), 1)
            if b in confirmed:
                row.addWidget(chip(t("用户确认"), "info"), 0, Qt.AlignVCenter)
            row_box = QWidget()
            row_box.setLayout(row)
            cl.addWidget(row_box)
        hover_lift(c)  # 卡片级 hover 抬升（克制：只卡片）
        return c

    # ---------- 编辑 / 重新归纳 ----------

    def _edit_dialog(self, trunk: str, md: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{t('编辑偏好')} · {trunk}")
        lay = QVBoxLayout(dlg)
        lay.setSpacing(S.s2)

        # 预览 / 编辑双态：默认预览（用户主要是读），点「编辑」才切
        # 到 Markdown 源文本编辑（编辑源文本用纯文本编辑器是合理的）
        self._edit_stack = QStackedWidget()
        self._edit_preview = md_view(md)
        self._edit_editor = QPlainTextEdit(md)
        self._edit_editor.setPlaceholderText(t("偏好全文（Markdown）"))
        self._edit_stack.addWidget(self._edit_preview)   # 0 = 预览
        self._edit_stack.addWidget(self._edit_editor)    # 1 = 编辑
        lay.addWidget(self._edit_stack, 1)

        toggle = QHBoxLayout()
        toggle.setSpacing(S.s2)
        self._preview_btn = btn_flat(t("预览"))
        self._edit_btn = btn_flat(t("编辑"))
        toggle.addWidget(self._preview_btn)
        toggle.addWidget(self._edit_btn)
        toggle.addStretch(1)
        lay.addLayout(toggle)

        def switch(mode: str) -> None:
            preview = mode == "preview"
            self._edit_stack.setCurrentIndex(0 if preview else 1)
            self._preview_btn.setEnabled(not preview)
            self._edit_btn.setEnabled(preview)

        self._preview_btn.clicked.connect(lambda: switch("preview"))
        self._edit_btn.clicked.connect(lambda: switch("edit"))
        switch("preview")

        # R6：判定键改 ASCII——行尾标记字面量是 USER_CONFIRM_MARK，
        # 经 t() 的 {mark} 占位填充（同一 msgid 全语言只用句子骨架，标记不参与翻译）
        lay.addWidget(txt(t("行尾加「{mark}」= 该条权重更高，后续归纳不覆盖",
                            mark=USER_CONFIRM_MARK),
                          F.caption, color=C.ink_500))

        btn_row = QHBoxLayout()
        btn_row.setSpacing(S.s2)
        btn_row.addWidget(btn_secondary(t("取消"), on_click=dlg.reject))
        btn_row.addWidget(btn_primary(
            t("保存"),
            on_click=lambda: self._save_prefs(dlg, trunk, self._edit_editor)))
        lay.addLayout(btn_row)
        dlg.resize(560, 460)
        dlg.exec()
        dlg.deleteLater()

    def _save_prefs(self, dlg: QDialog, trunk: str, tf: QPlainTextEdit) -> None:
        try:
            self.api.save_preferences(trunk, tf.toPlainText())
        except LocalApiError as exc:
            self.set_status(str(exc.detail))
            return
        dlg.accept()
        self.set_status(t("偏好已保存"), "ok")
        self.refresh()

    def _reinduct(self, trunk: str, btn: QPushButton) -> None:
        """重新归纳（长耗时：后台线程跑）。"""
        btn.setText(t("正在重新归纳…"))
        btn.setEnabled(False)

        def on_done(r: dict) -> None:
            btn.setText(t("归纳完成：保留 {a} 条确认 / 新 {b} 条",
                          a=r.get("confirmed", 0), b=r.get("inducted", 0)))
            btn.setEnabled(True)
            self.set_status(t("偏好已重新归纳"), "ok")
            self.refresh()

        def on_error(err: str) -> None:
            btn.setText(t("重新归纳"))
            btn.setEnabled(True)
            self.set_status(err)
            self.refresh()

        self.run_async(lambda: self.api.reinduct_preferences(trunk),
                       on_done, on_error)

    # ---------- 工具 ----------

    @staticmethod
    def _clear_layout(lay: QVBoxLayout) -> None:
        clear_layout(lay)
