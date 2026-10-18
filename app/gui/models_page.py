"""模型管理页——Qt 版（迁移自 Flet models_page.py）。

路由 CRUD + 蒸馏用模型下拉 + Agent 接入指引卡。
硬身区（deck）：数据/路由页，无宇航员、无 emoji，简洁清晰。
此页会被 ConnectPage 内嵌（self.content 直接加入外层滚动），也独立可用。

小白向引导：内嵌卡常驻接入页后，未接任何模型时列表上方亮出
「两种接法二选一」大白话引导（云端 API / 本地模型），接上后自动收起；
添加弹窗的类型下拉下挂随选随变的解释行。内嵌时不再重复渲染
Agent 接入指引卡（地址与分工具说明由接入页总况条/高级设置承载）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
                               QWidget)

from .api_client import LocalApi, LocalApiError
from .i18n import t
from .page_base import PageBase, build_centered_scroll
from .qt_dialogs import confirm_dialog
from .qt_theme import (btn_primary, btn_secondary, card, chip, icon_button,
                       status_text, status_tone, txt)
from .qt_widgets import SelectButton, ShadowCard, hover_lift
from .theme import C, D, F, S


class ModelsPage(PageBase):
    """模型与接入：路由列表 + 添加/删除 + 设为默认/蒸馏 + 接入自检。"""

    def __init__(self, api: LocalApi, parent: QWidget | None = None,
                 embedded: bool = False):
        super().__init__(api, parent)
        self._embedded = embedded
        self._build()
        # 懒加载下构建阶段零 API：内嵌于 ConnectPage，由它的 refresh 统一填充

    # ---------- 构建 ----------

    def _build(self) -> None:
        self.content = QWidget()
        self._cl = QVBoxLayout(self.content)
        self._cl.setContentsMargins(0, 0, 0, 0)
        self._cl.setSpacing(S.s6)

        # 标题行：模型与接入 + 接入自检 + 添加模型
        head = QHBoxLayout()
        head.setSpacing(S.s2)
        self._head_text = txt(t("模型与接入"),
                           F.h2 if self._embedded else F.h1, 800)
        head.addWidget(self._head_text)
        head.addStretch(1)
        self._check_btn = btn_secondary(t("接入自检"), "VERIFIED_OUTLINED",
                                        self._check_click)
        head.addWidget(self._check_btn)
        self._add_btn = btn_primary(t("添加模型"), "ADD_OUTLINED",
                                   self._open_add)
        head.addWidget(self._add_btn)
        head_box = QWidget()
        head_box.setLayout(head)
        self._cl.addWidget(head_box)

        # 模型接入状态（总纲三档口径）：
        # 无模型 → 明说缺什么（归纳类不可用 / 事实类本机可用），一键去配置入口
        # 就是同屏的「添加模型」主按钮；
        # 有模型 → 展示已接入 + 当前生效的模型路由。
        self._state_txt = txt("", F.body, color=C.ink_700, wrap=True)
        self._cl.addWidget(self._state_txt)

        # 小白向引导（未接任何模型时显示，接上自动收起）：两条路各自对应一类人，
        # 用工具名（生态词）当锚点，不解释协议名词。行结构存 _guide_lbls 供重译。
        self._guide_box = QWidget()
        gb = QVBoxLayout(self._guide_box)
        gb.setContentsMargins(0, 0, 0, 0)
        gb.setSpacing(S.s1)
        self._guide_lbls = [
            txt(t("第一次接模型？两种接法二选一，点「添加模型」开始："),
                F.body, 600, C.ink_700, wrap=True),
            txt(t("① 有 DeepSeek、OpenAI、通义、Kimi 等家的 API Key："
                  "类型选「云端 API」，把 Key 粘进去就能用"),
                F.body, color=C.ink_500, wrap=True),
            txt(t("② 电脑上装了 Ollama、LM Studio：类型选「本地模型」，"
                  "免费、不用联网"),
                F.body, color=C.ink_500, wrap=True),
        ]
        for lbl in self._guide_lbls:
            gb.addWidget(lbl)
        self._guide_box.hide()  # 首帧未知状态，refresh 时按路由数点亮
        self._cl.addWidget(self._guide_box)

        # 模型列表
        self._list_box = QWidget()
        self._list_layout = QVBoxLayout(self._list_box)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(S.s2)
        self._cl.addWidget(self._list_box)

        # 蒸馏模型下拉
        distill_box = QWidget()
        distill_lay = QVBoxLayout(distill_box)
        distill_lay.setContentsMargins(0, 0, 0, 0)
        distill_lay.setSpacing(S.s1)
        row = QHBoxLayout()
        row.setSpacing(S.s2)
        self._distill_label = txt(t("总结用模型"), F.body, color=C.ink_700)
        row.addWidget(self._distill_label)
        # 页面滚动区内的选择器用 SelectButton（QMenu 顶层弹层，-fix-2）
        self._distill_dd = SelectButton(width=D.DD_W_LG)
        self._distill_dd.currentIndexChanged.connect(self._distill_change)
        row.addWidget(self._distill_dd)
        row.addStretch(1)
        distill_lay.addLayout(row)
        # 口径与 _render_state 同源（总纲三档）：归纳类要模型，事实类本机可用。
        # 旧文案把"不接也能继续用"说成"总结照常产出"，与"无模型不产出归纳内容"矛盾。
        self._distill_desc = txt(
            t("接入模型用于归纳类内容（方法正文 / 成长叙事 / AI 重写）；"
              "不接也能用：经验照常记录，账本、坑卡、原始记录、搜索都在本机可用。"),
            F.caption, color=C.ink_500, wrap=True)
        distill_lay.addWidget(self._distill_desc)
        self._cl.addWidget(distill_box)

        # Agent 接入指引卡：内嵌接入页时不建（地址展示与总况条重复、分工具说明
        # 已在高级设置常驻），仅独立可用时给出
        self._guide_card = None
        if not self._embedded:
            self._guide_card = self._build_guide_card()
            self._cl.addWidget(self._guide_card)

        # 状态行
        self._flash = status_text()
        self._cl.addWidget(self._flash)

        # 尾部 stretch：内容不足时靠顶排布，避免卡片被视口拉高（同 home 收尾）
        self._cl.addStretch(1)

        # 内嵌时必须跳过：build_centered_scroll 会把 _cl 搬进内部滚动区（挂在
        # 不可见的本页根上），外层取 self.content 就成了空壳—— 前
        # 接入页模型区渲染空白的真因。独立可用时才包自己的滚动。
        if not self._embedded:
            self._wrap_scroll()

    def _build_guide_card(self) -> QFrame:
        # 构建阶段不调 API（懒加载下首帧零阻塞）：地址用默认兜底，
        # 真实值由 set_proxy_url() 在 refresh 时填充。
        base_url = "http://127.0.0.1:8100"
        c = card(title=t("Agent 接入指引（一键复制）"), secondary=True)
        self._guide_card_title = c.layout().itemAt(0).widget() if c.layout().count() > 0 else None
        lay = c.layout()
        self._guide_rows: list[tuple[QLabel, str]] = []
        for label, text in [
            (t("其他 OpenAI 兼容工具：OPENAI_BASE_URL={url}", url=base_url),
             f"OPENAI_BASE_URL={base_url}"),
            (t("Claude Code：ANTHROPIC_BASE_URL={url}", url=base_url),
             f"ANTHROPIC_BASE_URL={base_url}"),
            (t("Cursor：Settings → Models 填 {url}", url=base_url), base_url),
        ]:
            row = QHBoxLayout()
            row.setSpacing(S.s2)
            label_w = txt(label, F.body, color=C.ink_700)
            row.addWidget(label_w, 1)
            row.addWidget(icon_button("CONTENT_COPY_OUTLINED", t("复制"),
                                      lambda _=False, s=text: self._copy(s)))
            box = QWidget()
            box.setLayout(row)
            lay.addWidget(box)
            self._guide_rows.append((label_w, text))
        return c

    def set_proxy_url(self, url: str) -> None:
        """刷新接入指引卡里的地址（构建时不调 API，真实值在这里补上）。"""
        for label_w, text in getattr(self, "_guide_rows", []):
            label_w.setText(text.replace("http://127.0.0.1:8100", url))

    def _wrap_scroll(self) -> None:
        """独立可用时的滚动包装（内嵌 ConnectPage 时外层统一滚动，不走这里）。"""
        self._cl.setContentsMargins(S.s8, S.s8, S.s8, S.s8)
        scroll = build_centered_scroll(self._cl)
        self._layout.addWidget(scroll)

    # ---------- 数据 ----------

    def refresh(self) -> None:
        """切页刷新：取数进后台线程（主线程零 HTTP），渲染回主线程。"""
        # S5：补首屏骨架（此前本页取数期间无占位）
        self.fetch_and_render(self.api.models, self._render, "models",
                              skeleton=[24, 72, 72])

    def _render(self, info: dict | None) -> None:
        """渲染回调（主线程）：**不得再发 HTTP**。"""
        if info is None:
            self.set_flash(t("（读取失败）"))
            return
        self._clear(self._list_layout)
        routes = info.get("routes", [])
        self._render_state(routes)
        # 引导块随状态走：一个模型都没接 → 亮出双路径引导；接了 → 收起不噪
        self._guide_box.setVisible(not routes)
        if not routes:
            self._list_layout.addWidget(
                txt(t("未配置模型"), color=C.ink_500, italic=True))
        for r in routes:
            self._list_layout.addWidget(self._route_card(r))
        # 首屏错峰入场（"只首屏"在基类 stagger_cards 里一处实现）
        self.stagger_cards(self._list_layout)
        # 蒸馏下拉（blockSignals 避免重填触发保存）
        self._distill_dd.blockSignals(True)
        self._distill_dd.clear()
        self._distill_dd.addItem(t("默认"), "__default__")
        for r in routes:
            self._distill_dd.addItem(r["name"], r["name"])
        idx = self._distill_dd.findData(info.get("distill_model")
                                        or "__default__")
        self._distill_dd.setCurrentIndex(idx if idx >= 0 else 0)
        self._distill_dd.blockSignals(False)

    # ---------- 模型接入状态（三档口径） ----------

    def _render_state(self, routes: list) -> None:
        """模型接入状态行（总纲三档口径）。

        无模型 → 明说归纳类不可用、事实类本机可用（一键去配置入口 = 同屏
        「添加模型」主按钮）；有模型 → 报当前生效的模型路由（优先蒸馏专用路由）。
        """
        if not routes:
            self._state_txt.setText(t(
                "未接入模型：归纳类内容（方法正文 / 成长叙事 / AI 重写）不可用；"
                "事实类内容（账本 / 坑卡 / 原始记录 / 搜索）本机完全可用"))
            status_tone(self._state_txt, C.ink_700)
            return
        active = (next((r for r in routes if r.get("is_distill")), None)
                  or next((r for r in routes if r.get("is_default")), None)
                  or routes[0])
        self._state_txt.setText(t(
            "已接入 · 当前生效的模型路由：{name}（{endpoint}）",
            name=str(active.get("name") or ""),
            endpoint=str(active.get("endpoint") or "")))
        status_tone(self._state_txt, C.ok_fg)

    # ---------- 重新翻译 ----------

    def retranslateUi(self) -> None:
        """语言切换时更新静态文字并刷新内容。"""
        self._head_text.setText(t("模型与接入"))
        # _check_btn/_add_btn have icons, so find child QLabel
        check_label = self._check_btn.layout().itemAt(1).widget()
        check_label.setText(t("接入自检"))
        add_label = self._add_btn.layout().itemAt(1).widget()
        add_label.setText(t("添加模型"))
        self._distill_label.setText(t("总结用模型"))
        self._distill_desc.setText(
            t("接入模型用于归纳类内容（方法正文 / 成长叙事 / AI 重写）；"
              "不接也能用：经验照常记录，账本、坑卡、原始记录、搜索都在本机可用。"))
        for lbl, key in zip(
                self._guide_lbls,
                (t("第一次接模型？两种接法二选一，点「添加模型」开始："),
                 t("① 有 DeepSeek、OpenAI、通义、Kimi 等家的 API Key："
                   "类型选「云端 API」，把 Key 粘进去就能用"),
                 t("② 电脑上装了 Ollama、LM Studio：类型选「本地模型」，"
                   "免费、不用联网"))):
            lbl.setText(key)
        guide_card_title = getattr(self, "_guide_card_title", None)
        if guide_card_title is not None:
            guide_card_title.setText(t("Agent 接入指引（一键复制）"))
        # 重新生成 guide rows 标签
        base_url = "http://127.0.0.1:8100"
        for i, (label_w, _) in enumerate(getattr(self, "_guide_rows", [])):
            texts = [
                t("其他 OpenAI 兼容工具：OPENAI_BASE_URL={url}", url=base_url),
                t("Claude Code：ANTHROPIC_BASE_URL={url}", url=base_url),
                t("Cursor：Settings → Models 填 {url}", url=base_url),
            ]
            if i < len(texts):
                label_w.setText(texts[i])
        self.refresh()

    def _route_card(self, r: dict) -> QWidget:
        type_labels = {"local": t("本地模型"), "cloud": t("云端 API"),
                       "anthropic": t("Anthropic API")}
        # 密钥存哪：只说结果不说机制（keyring/明文是安全内部细节）
        key_labels = {"keyring": t("（密钥在系统钥匙串）"),
                      "plaintext": t("（密钥存在配置里）"), "none": ""}
        marks = " · ".join(
            m for m, on in ((t("默认"), r["is_default"]),
                            (t("总结用"), r["is_distill"])) if on)
        # 档 2 试点页：自绘投影卡片（省掉逐控件 QGraphicsDropShadowEffect 的
        # CPU 合成，实测 300 张卡绘制 13 ms → 54 ms）。观感与 card() 一致，代价是
        # 控件为投影留 8px 边。确认后再铺开到其余列表页。
        c = ShadowCard()
        lay = c.layout()
        row = QHBoxLayout()
        row.setSpacing(S.s2)
        col = QVBoxLayout()
        col.setSpacing(S.s1)
        col.addWidget(txt(
            f"{r['name']}  {type_labels.get(r['type'], r['type'])}  "
            f"{r['endpoint']}", F.body, 600))
        col.addWidget(txt(
            f"model={r['model']}  {key_labels.get(r['key_source'], '')}",
            F.caption, color=C.ink_500))
        row.addLayout(col, 1)
        if marks:
            row.addWidget(chip(marks, "brand"))
        if not r["is_default"]:
            row.addWidget(btn_secondary(t("设为默认"),
                                        on_click=lambda _=False,
                                        n=r["name"]: self._set_default(n)))
        row.addWidget(icon_button("DELETE_OUTLINED", t("删除"),
                                  lambda _=False, n=r["name"]:
                                  self._confirm_delete(n)))
        lay.addLayout(row)
        hover_lift(c)  # 卡片级 hover 抬升（克制：只卡片）
        return c

    def set_flash(self, msg: str, tone: str = "err") -> None:
        colors = {"ok": C.ok_fg, "err": C.err_fg, "warn": C.warn_fg,
                  "info": C.info_fg}
        self._flash.setText(msg)
        status_tone(self._flash, colors[tone])

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                ModelsPage._clear(item.layout())

    # ---------- 操作 ----------

    def _copy(self, text: str) -> None:
        try:
            QApplication.clipboard().setText(text)
        except Exception:
            pass

    def _set_default(self, name: str) -> None:
        try:
            self.api.set_default(name)
            self.refresh()
        except LocalApiError as exc:
            self.set_flash(str(exc.detail))

    def _confirm_delete(self, name: str) -> None:
        ok = confirm_dialog(
            t("删除"),
            t("删除模型「{name}」？连带删除钥匙串里的 key", name=name), self)
        if not ok:
            return
        try:
            self.api.remove_model(name)
            self.refresh()
        except LocalApiError as exc:
            self.set_flash(str(exc.detail))

    def _open_add(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(t("添加模型"))
        lay = QVBoxLayout(dlg)
        lay.setSpacing(S.s2)

        type_dd = QComboBox()
        type_dd.addItem(t("本地模型"), "local")
        type_dd.addItem(t("云端 API"), "cloud")
        type_dd.addItem("Anthropic API", "anthropic")
        type_dd.setCurrentIndex(1)  # cloud 默认
        endpoint = QLineEdit("http://127.0.0.1:8080/v1")
        endpoint.setPlaceholderText(t("接口地址（URL）"))
        name_tf = QLineEdit()
        name_tf.setPlaceholderText(t("模型名"))
        route_name = QLineEdit()
        route_name.setPlaceholderText(t("名称"))
        key_tf = QLineEdit()
        key_tf.setEchoMode(QLineEdit.EchoMode.Password)
        key_tf.setPlaceholderText(t("API Key（填一次，存系统钥匙串）"))

        # 类型解释行：随选随变，替小白回答"我该选哪个"（协议名词不再出现）
        type_hint = txt("", F.caption, color=C.ink_500, wrap=True)

        def on_type_change() -> None:
            data = type_dd.currentData()
            key_tf.setVisible(data in ("cloud", "anthropic"))
            if data == "local":
                type_hint.setText(t("电脑上装了 Ollama、LM Studio？选这个，"
                                    "免费、不用联网"))
            elif data == "anthropic":
                type_hint.setText(t("有 Anthropic（Claude）的 API Key？选这个"))
            else:
                type_hint.setText(t("有 DeepSeek、OpenAI、通义、Kimi 等家的 "
                                    "API Key？选这个，粘贴进来就能用"))

        type_dd.currentIndexChanged.connect(lambda _: on_type_change())
        on_type_change()

        for label, w in [(t("名称"), route_name), (t("类型"), type_dd),
                         (t("接口地址（URL）"), endpoint), (t("模型名"), name_tf),
                         (t("API Key（填一次，存系统钥匙串）"), key_tf)]:
            lay.addWidget(txt(label, F.caption, 600, C.ink_700))
            lay.addWidget(w)
            if w is type_dd:
                lay.addWidget(type_hint)  # 紧跟类型下拉，解释"选哪个"

        # 对话框内联错误行（红字）——校验失败与服务端
        # 报错都落在弹窗里，不再 set_flash 写在模态框背后看不见。
        err_lbl = txt("", F.caption, color=C.err_fg)
        err_lbl.setWordWrap(True)
        err_lbl.hide()

        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_secondary(t("取消"), on_click=dlg.reject))
        btn_row.addStretch(1)

        def show_err(msg: str) -> None:
            err_lbl.setText(msg)
            err_lbl.show()

        def save() -> None:
            # 提交前校验必填：route 名、endpoint 前缀 http(s)://、model 非空
            name = route_name.text().strip()
            url = endpoint.text().strip()
            model = name_tf.text().strip()
            if not name:
                show_err(t("请填写名称"))
                return
            if not (url.startswith("http://") or url.startswith("https://")):
                show_err(t("接口地址需以 http:// 或 https:// 开头"))
                return
            if not model:
                show_err(t("请填写模型名"))
                return
            try:
                self.api.add_model(name, url, model,
                                   type_dd.currentData(),
                                   key_tf.text().strip() or None)
            except LocalApiError as exc:
                show_err(str(exc.detail))
                return
            dlg.accept()
            self.refresh()

        btn_row.addWidget(btn_primary(t("保存"), on_click=save))
        lay.addWidget(err_lbl)
        lay.addLayout(btn_row)
        dlg.exec()
        dlg.deleteLater()

    def _distill_change(self, _idx: int) -> None:
        val = self._distill_dd.currentData()
        try:
            if val == "__default__":
                self.api.clear_distill()
            else:
                self.api.set_distill(val)
            self.refresh()
        except LocalApiError as exc:
            self.set_flash(str(exc.detail))

    def _check_click(self) -> None:
        """接入自检（W1-08）：1-token 最小补全，结果带可操作指引。"""
        self._check_btn.setEnabled(False)
        self.set_flash(t("正在检查接入…"), "info")
        self.run_async(self.api.check_model,
                       self._on_check_done, self._on_check_fail)

    def _on_check_done(self, res: dict) -> None:
        if res.get("ok"):
            self.set_flash(t("接入正常"), "ok")
        else:
            # 与「总结失败：{err}」同模式：固定前缀走 t()，动态细节保留原文
            self.set_flash(t("接入失败：{detail}",
                             detail=str(res.get("message", ""))), "err")
        self._check_btn.setEnabled(True)

    def _on_check_fail(self, err: str) -> None:
        self.set_flash(str(err), "err")
        self._check_btn.setEnabled(True)
