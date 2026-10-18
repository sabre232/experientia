"""接入页的「探针接入 + 钥匙管理」区 mixin（Qt 版）。

 拆分：从 `app/gui/connect_page.py` 的 `class ConnectPage` 搬出的
第三个区块（原 L934-1486，553 行 / 19 个方法）。承载三块：

- **探针接入卡**：自报工具（self_reported）的步骤引导、连接码、导出；
- **钥匙管理**：已吸收的钥匙按工具聚合成可折叠栏，展开预览 + 展开全部；
- **probe 状态刷新**：refresh_probe 消费本地 API 数据，纯内存渲染零 HTTP。

约定与 store 侧 mixin 一致：方法体**逐字搬移**、签名与返回值不变；共享状态
（`api` / `go` / 各 `_probe_*` `_keys_*` `_step*` 实例属性、以及 `_clear`）
留在 `ConnectPage` 主体、靠 `self` 访问；**不 import connect_page**（避免循环）。

搬移时改了一处：区块内的 `ConnectPage._clear(lay)` 是静态方法经**类名**调用，
mixin 里改为 `self._clear(lay)`——对 staticmethod 等价，且免去对原类的 import。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMenu, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..proxy.detect import agent_display_name as _agent_display
from ..report_skill import SKILL_DIRNAME, write_report_skill
from ._ago import _ts_ago
from .api_client import LocalApiError
from .i18n import t
from .qt_theme import (btn_flat, btn_primary, btn_secondary, card, chip,
                       divider, icon_button, txt)
from .qt_widgets import RotatingIcon
from .theme import C, D, F, FONT, R, S

# 钥匙分组：同一工具收起成一栏；展开时先给 10 把预览，更多走「展开全部」。
_KEYS_INLINE = 10


class ProbeCardMixin:
    """探针接入卡与钥匙管理（接入页的「需要你处理 / 已接入钥匙」两区）。"""


    def _build_probe_card(self) -> QWidget:
        """新增工具卡：副标题 + 三步条 + 动作区 + 独立状态区 + 详细说明折叠。

        Orange-as-live-only：实心橙只给「第 ③ 步徽章 + 连接主按钮」两处；①② 徽章
        浅橙底。状态区 mode 文字升级为语义 chip（_probe_mode_chip 是唯一映射出口）。
        """
        c = card(title=t("新增工具"), secondary=True)
        self._probe_card_title = c.layout().itemAt(0).widget()
        lay = c.layout()

        # 标题行：右侧中性 chip「读不到的工具专用」（适用对象前置）
        lay.removeWidget(self._probe_card_title)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(S.s2)
        title_row.addWidget(self._probe_card_title, 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        self._probe_scope_chip = self._neutral_chip(t("读不到的工具专用"))
        title_row.addWidget(self._probe_scope_chip, 0, Qt.AlignVCenter)
        title_box = QWidget()
        title_box.setLayout(title_row)
        lay.insertWidget(0, title_box)

        # 副标题：3 行导语压成 1 句（保留原因 + 动作，结果句由三步条表达）
        self._probe_intro = txt(t(
            "少数 AI 工具的会话被加密或格式不通用，装个小技能就能接进来。"),
            F.body, color=C.ink_500)
        self._probe_intro.setWordWrap(True)
        lay.addWidget(self._probe_intro)

        # 三步条：白色块容器 + 三列并排（徽章 + 标题 + 副标题）
        self._probe_steps = QFrame()
        self._probe_steps.setStyleSheet(
            f"QFrame {{ background: {C.surface};"
            f" border: {D.BORDER_W}px solid {C.line_strong};"
            f" border-radius: {R.md}px; }}")
        steps_lay = QHBoxLayout(self._probe_steps)
        steps_lay.setContentsMargins(S.s2, S.s2, S.s2, S.s2)
        steps_lay.setSpacing(S.s2)
        self._step1 = self._step_line("1", t("导出技能"),
                                      t("下载技能包"), active=False)
        steps_lay.addWidget(self._step1, 1)
        self._step2 = self._step_line("2", t("运行一次"),
                                      t("工具自动上报"), active=False)
        steps_lay.addWidget(self._step2, 1)
        self._step3 = self._step_line("3", t("粘贴连接"),
                                      t("连接码自动送达"), active=True)
        steps_lay.addWidget(self._step3, 1)
        lay.addWidget(self._probe_steps)

        # 步骤 ① 动作（导出）：按钮 + 一行短说明；完整细节进按钮 tooltip
        export_row = QHBoxLayout()
        export_row.setSpacing(S.s2)
        self._probe_export_btn = btn_secondary(t("导出上报技能"), "DOWNLOAD_OUTLINED")
        self._probe_export_btn.setFixedHeight(D.BTN_H)
        self._probe_export_btn.setToolTip(t(
            "点「导出上报技能」导出一个 experientia-report 文件夹，放进那个 AI 工具"
            "能加载技能的位置（一般是它的 skills 或插件目录），然后让它运行一次任意任务。"))
        self._probe_export_btn.clicked.connect(self.do_probe_export)
        export_row.addWidget(self._probe_export_btn)
        self._probe_export_hint = txt(
            t("导出 experientia-report 文件夹，放进工具的技能目录"),
            F.body, color=C.ink_500)
        export_row.addWidget(self._probe_export_hint, 1)
        export_box = QWidget()
        export_box.setLayout(export_row)
        lay.addWidget(export_box)

        # 步骤 ③ 动作（连接）：输入框 + 实心主按钮
        paste_row = QHBoxLayout()
        paste_row.setSpacing(S.s2)
        self._probe_code = QLineEdit()
        self._probe_code.setPlaceholderText(t("粘贴返回的连接码"))
        self._probe_code.setFixedHeight(D.BTN_H)
        self._probe_code.returnPressed.connect(self.do_probe_apply)
        paste_row.addWidget(self._probe_code, 1)
        # 唯一主操作「连接」→ 实心 btn_primary
        self._probe_connect_btn = btn_primary(t("连接"),
                                              on_click=self.do_probe_apply)
        paste_row.addWidget(self._probe_connect_btn)
        box = QWidget()
        box.setLayout(paste_row)
        lay.addWidget(box)

        self._probe_feedback = txt("", F.caption, color=C.info_fg)
        self._probe_feedback.setWordWrap(True)
        lay.addWidget(self._probe_feedback)

        # S5 待放行经验提示（三入口之一：connect 卡）
        self._probe_pending = QWidget()
        _pp = QHBoxLayout(self._probe_pending)
        _pp.setContentsMargins(0, 0, 0, 0)
        _pp.setSpacing(S.s2)
        self._probe_pending_txt = txt("", F.caption, color=C.warn_fg)
        self._probe_pending_txt.setWordWrap(True)
        _pp.addWidget(self._probe_pending_txt, 1)
        self._probe_pending_btn = btn_flat(t("去处理"),
                                           on_click=lambda: self.go("mine"))
        self._probe_pending_btn.setFixedHeight(D.BTN_H_SM)
        _pp.addWidget(self._probe_pending_btn)
        lay.addWidget(self._probe_pending)
        self._probe_pending.setVisible(False)

        # 分隔线：向导区与状态区切开
        lay.addWidget(divider())

        # 状态区小节头：「接入状态」+ 计数 chip（数量 0 时不显示计数）
        state_head = QHBoxLayout()
        state_head.setContentsMargins(0, 0, 0, 0)
        state_head.setSpacing(S.s2)
        self._probe_state_header = txt(t("接入状态"), F.body, 600, C.ink_700)
        state_head.addWidget(self._probe_state_header)
        self._probe_count_chip = self._neutral_chip("")
        self._probe_count_chip.hide()
        state_head.addWidget(self._probe_count_chip, 0, Qt.AlignVCenter)
        state_head.addStretch(1)
        state_box = QWidget()
        state_box.setLayout(state_head)
        lay.addWidget(state_box)
        self._probe_list = QWidget()
        self._probe_list_layout = QVBoxLayout(self._probe_list)
        self._probe_list_layout.setContentsMargins(0, 0, 0, 0)
        self._probe_list_layout.setSpacing(S.s1)
        lay.addWidget(self._probe_list)

        # 详细说明折叠：三处被删长文合并进正文，避免信息丢失
        self._probe_why_btn = btn_flat(t("为什么需要？"),
                                       on_click=self._toggle_probe_why)
        lay.addWidget(self._probe_why_btn, 0, Qt.AlignLeft)
        self._probe_why_body = txt(t(
            "少数 AI 工具的会话被加密或格式不通用，Experientia 直接读不到，需要工具"
            "主动上报。正常情况下连接码会自动送达、无需手动粘贴；只有下方列表一直没"
            "出现它时，才需要把工具返回的连接码粘到输入框，再点「连接」。如果你常用"
            "某个工具但上方「已接入」里一直没有它，多半就是这一类——给它装一次小技能"
            "即可。"),
            F.body, color=C.ink_500, wrap=True)
        self._probe_why_expanded = False  # 显式状态（同 _toggle_tools：isVisible 在页未显示时恒 False）
        self._probe_why_body.hide()
        lay.addWidget(self._probe_why_body)
        return c

    @staticmethod
    def _step_badge(number: str, active: bool) -> QLabel:
        """步骤徽章：D.BADGE_STEP 正圆（圆角 = 边长//2 在调用处算）。

        active（第 ③ 步"当前"）= 实心橙底白字（Orange-as-live-only）；
        未激活 = 浅橙底 brand 字（已设计好的前置步骤，不抢焦点）。"""
        s = D.BADGE_STEP
        bg = C.primary_fill if active else C.brand_100
        fg = C.on_brand if active else C.brand_700
        b = QLabel(number)
        b.setFixedSize(s, s)
        b.setAlignment(Qt.AlignCenter)
        font = QFont(FONT, F.body)
        font.setWeight(QFont.Weight(600))
        b.setFont(font)
        b.setStyleSheet(
            f"background: {bg}; color: {fg}; border: none;"
            f" border-radius: {s // 2}px;")
        return b

    @staticmethod
    def _neutral_chip(label: str) -> QFrame:
        """页内中性 chip（标题行适用对象标注 / 状态区计数）：米底 + ink_700 字。

        不进公共工厂（组件审批流程）：与 chip() 同骨架，但 tone 恒为中性灰底。"""
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {C.surface_2}; border: none;"
            f" border-radius: {R.sm}px; }}")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(D.CHIP_PAD_X, D.CHIP_PAD_Y,
                               D.CHIP_PAD_X, D.CHIP_PAD_Y)
        lay.setSpacing(S.s1)
        lay.addWidget(txt(label, F.caption, 600, C.ink_700))
        frame.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        return frame

    # 步骤列结构：[badge, title_label, sub_label]（retranslate 按此改子标签）
    _STEP_TITLE_IDX, _STEP_SUB_IDX = 1, 2

    def _step_line(self, no: str, title: str, sub: str,
                   active: bool = False) -> QWidget:
        """三步条一列：徽章 + 步骤标题 + 一行副标题（居中）。"""
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(S.s1)
        badge = self._step_badge(no, active)
        v.addWidget(badge, 0, Qt.AlignHCenter)
        v.addWidget(txt(title, F.body, 600), 0, Qt.AlignHCenter)
        v.addWidget(txt(sub, F.caption, color=C.ink_500), 0, Qt.AlignHCenter)
        return col

    def _toggle_probe_why(self) -> None:
        """折叠链：展开/收起详细说明（setVisible 直落，reduced-motion 同口径）。

        用显式状态变量（同 _toggle_tools）：页面未 show 时 isVisible() 恒 False，
        据它判断会把折叠永久锁死在展开态。"""
        self._probe_why_expanded = not self._probe_why_expanded
        self._probe_why_body.setVisible(self._probe_why_expanded)

    def _probe_mode_chip(self, mode: str) -> QFrame:
        """self_reported / keys 行的 mode 状态 chip（原描述进 tooltip）。

        mode 映射的唯一出口：橙只表活跃，"兜底"这类中性能力说明走 brand 档
        （brand_100 底，非状态强调）；未知 mode 按兜底上报处理。文案用直接
        t() 调用（字面量），保证 Babel 可提取、渲染时按当前语言求值。"""
        if mode in ("hook_ready", "scan_covered"):
            w = chip(t("已连接"), "ok")
            w.setToolTip(t("可实时捕获") if mode == "hook_ready"
                         else t("可自动捕获"))
        elif mode == "decrypt_ready":
            w = chip(t("待授权"), "warn")
            w.setToolTip(t("已加密，可授权解密"))
        elif mode == "report_only":
            w = chip(t("兜底上报"), "brand")
            w.setToolTip(t("经验上报兜底"))
        else:  # 未知 mode：按兜底能力中性展示，无 tooltip
            w = chip(t("经验上报兜底"), "brand")
        return w

    def do_probe_apply(self) -> None:
        code = self._probe_code.text().strip()
        if not code:
            self._probe_feedback.setText(t("粘贴返回的连接码"))
            return
        try:
            r = self.api.probe_apply(code)
        except LocalApiError:
            self._probe_feedback.setText(t("连接失败"))
            return
        r = r or {}
        if not r.get("ok"):
            err = r.get("error") or t("连接失败")
            self._probe_feedback.setText(err)
            return
        st = r.get("status") or {}
        agent = str(st.get("agent") or "")
        msg = t("已连接 {name}", name=_agent_display(agent) or agent)
        # 官方实时 Hook：不再弹确认框打断，统一到「我的 Hooks」页一键接入
        if st.get("mode") == "hook_ready":
            msg += " · " + t("可在「我的 Hooks」页一键接入实时捕获")
        self._probe_feedback.setText(msg)
        self._reload_probe()  # 状态 + 钥匙一并刷新（注入回流立即可见）

    def do_probe_export(self) -> None:
        """把 experientia-report 技能包导出到用户选择的目录（装进目标 AI 工具用）。

        本地直接生成（report_skill 只用标准库，纯文件写，无需走引擎/网络）：
        选择目录 → 生成 <目录>/experientia-report/{SKILL.md, scripts/probe.py} →
        打开所在文件夹并回显三步提示。
        """
        import os
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        from ..report_skill import SKILL_DIRNAME, write_report_skill

        start = str(Path.home() / "Downloads")
        if not Path(start).is_dir():
            start = str(Path.home())
        target = QFileDialog.getExistingDirectory(
            self, t("选择导出目录（将生成 {dir} 文件夹）", dir=SKILL_DIRNAME), start)
        if not target:
            return
        try:
            skill_md = write_report_skill(target)  # 幂等：覆盖同名包，不伤其它文件
        except OSError as exc:
            self._probe_feedback.setText(t("导出失败：{err}", err=str(exc)))
            return
        out = skill_md.parent
        self._probe_feedback.setText(t(
            "已导出到 {path}。现在把它装进目标 AI 工具 → 让它运行一次 → "
            "回来粘贴返回的连接码。", path=str(out)))
        self._probe_last_export = out
        # 帮用户直接打开所在目录，少一步“自己找”
        try:
            if os.name == "nt":
                os.startfile(str(out))  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(out)])
        except OSError:
            pass

    # ---------- 钥匙行操作 / 统一刷新 ----------

    @staticmethod
    def _keys_action(text: str, name: str, on_click) -> QPushButton:
        """钥匙行内小操作按钮（复制/删除），objectName 供测试与主题钩子用。"""
        b = btn_flat(text, on_click=on_click)
        b.setObjectName(name)
        b.setFixedHeight(D.BTN_H_SM)
        return b

    def _reload_probe(self) -> None:
        """连接码动作后统一刷新：probe 状态 + 收到的钥匙（注入回流即时可见）。

        两个同步调用串在 UI 线程（各 15s 超时）——引擎
        未起时点任一连接码动作冻结界面最长 30 秒。改一次后台取数把两个结果
        一起带回来（内部按原口径逐项降级：失败单项置空，不影响另一项）。"""
        def work():
            try:
                st = self.api.probe_status()
            except LocalApiError:
                st = None
            try:
                keys = (self.api.probe_keys() or {}).get("keys") or []
            except LocalApiError:
                keys = None
            return st, keys

        def done(result) -> None:
            st, keys = result
            self.refresh_probe(st, keys)

        def err(e) -> None:
            self._probe_feedback.setText(str(e))

        self.run_async(work, done, err)

    def _copy_key_code(self, code: str) -> None:
        QApplication.clipboard().setText(code)
        self._probe_feedback.setText(t("已复制到剪贴板"))

    def _delete_key(self, code: str) -> None:
        """删除钥匙历史明细：二次确认后删除。"""
        from .qt_dialogs import confirm_dialog

        ok = confirm_dialog(t("删除"),
                            t("删除这把钥匙的历史记录？已接入的工具不受影响。"),
                            self)
        if not ok:
            return
        try:
            self.api.probe_key_delete(code)
        except LocalApiError as exc:
            self._probe_feedback.setText(str(exc.detail))
            return
        self._probe_feedback.setText(t("已删除"))
        self._reload_probe()

    @staticmethod
    def _set_neutral_chip_label(frame: QFrame, text: str) -> None:
        """更新页内中性 chip 文字（标签是子 QLabel，见 _neutral_chip）。"""
        lay = frame.layout()
        if lay is None:
            return
        w = lay.itemAt(0).widget()
        if isinstance(w, QLabel):
            w.setText(text)

    # ---------- 收到的钥匙：按工具分组，收起成一个折叠栏 ----------

    def _render_keys(self, keys: list | None) -> None:
        """在接入列表尾部渲染「收到的钥匙」区。

        keys=None 且已有缓存 → 复用上次（语言切换重渲）；空列表 → 清空。
        同一工具的 N 把钥匙**不逐行平铺**（那是用户吐槽的"同一模型一屏 28 行"），
        而是按工具聚合成一个可折叠栏，默认收起；展开后先给 `_KEYS_INLINE` 把
        预览，更多走「展开全部」。"""
        if keys is None:
            keys = getattr(self, "_last_keys", None) or []
        else:
            keys = keys or []
        self._last_keys = keys
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(S.s2)
        if keys:
            bl.addWidget(txt(t("收到的钥匙（{n}）", n=len(keys)),
                             F.body, 600, C.ink_700))
            by_agent: dict[str, list] = {}
            for k in keys:
                a = str(k.get("agent") or "—")
                by_agent.setdefault(a, []).append(k)
            for agent, gk in sorted(by_agent.items()):
                header, body = self._build_key_group(agent, gk)
                bl.addWidget(header)
                bl.addWidget(body)
        lay = self._probe_list_layout
        old = self._keys_box
        idx = -1
        if old is not None:
            for i in range(lay.count()):
                if lay.itemAt(i).widget() is old:
                    idx = i
                    break
        if idx >= 0:
            hit = lay.takeAt(idx)
            if hit.widget() is not None:
                # 三步撤销：先脱离父层级（findChildren 立即可见消失），再延迟销毁
                hit.widget().setParent(None)
                hit.widget().deleteLater()
            lay.insertWidget(idx, box)
        else:
            lay.addWidget(box)
        self._keys_box = box

    def _build_key_group(self, agent: str, gk: list) -> tuple[QWidget, QWidget]:
        """单个工具的折叠栏：表头（chevron + 工具名 + 数量 chip + 能力 chip +
        「最近」相对时间）+ 折叠的身体（钥匙行）。返回 (header, body)。"""
        display = _agent_display(agent) or agent or "—"
        # 默认收起规则：≤10 把直接展开（少就不藏），更多则收起（避免一眼叠 28 行）
        if agent not in self._keys_group_expanded:
            self._keys_group_expanded[agent] = len(gk) <= _KEYS_INLINE
        expanded = self._keys_group_expanded[agent]

        header = QWidget()
        header.setObjectName("keyGroupHeader")
        header.setAttribute(Qt.WA_Hover, True)
        header.setCursor(Qt.PointingHandCursor)
        hh = QHBoxLayout(header)
        hh.setContentsMargins(S.s2, S.s1, S.s2, S.s1)
        hh.setSpacing(S.s2)
        icon = RotatingIcon("EXPAND_MORE_OUTLINED", 18, C.ink_500)
        if expanded:
            icon.setRotation(180)
        hh.addWidget(icon)
        hh.addWidget(txt(display, F.body, 600))
        hh.addWidget(self._neutral_chip(t("{n} 把钥匙", n=len(gk))))
        for cw in self._key_capability_chips(gk):
            hh.addWidget(cw, 0, Qt.AlignVCenter)
        hh.addStretch(1)
        rel, abs_t = _ts_ago(
            max((str(k.get("at") or "") for k in gk), default=""))
        if rel:
            tl = txt(t("最近 {at}", at=rel), F.caption, color=C.ink_500)
            if abs_t:
                tl.setToolTip(abs_t)
            hh.addWidget(tl, 0, Qt.AlignVCenter)
        header.setStyleSheet(
            f"QWidget#keyGroupHeader {{ border-radius: {R.sm}px;"
            f" background: transparent; }}"
            f"QWidget#keyGroupHeader:hover {{ background: {C.surface_2}; }}")

        body = QWidget()
        body.setObjectName("keyGroupBody")
        bb = QVBoxLayout(body)
        bb.setContentsMargins(S.s3, 0, S.s3, 0)
        bb.setSpacing(S.s1)
        show_all = self._keys_group_full.get(agent, False)
        rows = gk if show_all else gk[:_KEYS_INLINE]
        for k in rows:
            bb.addWidget(self._build_key_row(k))
        if len(gk) > _KEYS_INLINE and not show_all:
            more = btn_flat(t("展开全部（{n} 把）", n=len(gk)))
            more.setObjectName("keyExpandAllBtn")
            more.setFixedHeight(D.BTN_H_SM)
            more.clicked.connect(lambda _=False, a=agent: self._key_expand_all(a))
            bb.addWidget(more)
        bb.addStretch(1)

        def _toggle(_ev=None):
            self._keys_group_expanded[agent] = not self._keys_group_expanded[agent]
            cur = self._keys_group_expanded[agent]
            body.setVisible(cur)
            icon.setRotation(180 if cur else 0)

        header.mousePressEvent = _toggle
        body.setVisible(expanded)
        return header, body

    def _build_key_row(self, k: dict) -> QWidget:
        """单把钥匙行：连接码（唯一标识，被突出）+ 相对时间 + 复制 + ⋯（删除）。

        工具名/能力收在分组表头，行内不再重复（one-element-one-function：
        行内只剩“这把钥匙是谁”与其生命周期动作）。"""
        code = str(k.get("code") or "")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(S.s2)
        if code:
            kc = txt(code, F.caption, 600, C.ink_900, selectable=True)
            kc.setToolTip(code)
            rl.addWidget(kc, 0, Qt.AlignVCenter)
        rl.addStretch(1)
        rel, abs_t = _ts_ago(str(k.get("at") or ""))
        if rel:
            tl = txt(t("最近 {at}", at=rel), F.caption, color=C.ink_500)
            if abs_t:
                tl.setToolTip(abs_t)
            rl.addWidget(tl, 0, Qt.AlignVCenter)
        if code:
            rl.addWidget(self._keys_action(
                t("复制"), "keyCopyBtn",
                lambda _=False, c=code: self._copy_key_code(c)))
            more = icon_button("dots-vertical", t("更多操作"))
            more.setObjectName("keyMenuBtn")
            menu = QMenu(more)
            act = menu.addAction(t("删除"))
            act.setObjectName("keyDeleteAction")
            act.triggered.connect(lambda: self._delete_key(code))
            more.setMenu(menu)
            rl.addWidget(more)
        return row

    def _key_capability_chips(self, gk: list) -> list[QFrame]:
        """分组表头的“能力”chip：只对**非正常连接**的 key 模式展示。

        hook_ready/scan_covered（可实时/可自动捕获）是全页默认态，28 把逐行说
        「已连接」正是用户眼中的噪音——正常连接不重复，异常（待授权/兜底）才提。
        """
        normal = {"hook_ready", "scan_covered"}
        seen: set[str] = set()
        out: list[QFrame] = []
        for k in gk:
            mode = str(k.get("mode") or "")
            if mode in normal or mode in seen:
                continue
            seen.add(mode)
            out.append(self._probe_mode_chip(mode))
        return out

    def _key_expand_all(self, agent: str) -> None:
        """展开全部：把该工具的钥匙全部列出（不再停在 10 把预览）。"""
        self._keys_group_full[agent] = True
        self._render_keys(self._last_keys)

    def refresh_probe(self, data: dict | None, keys: list | None = None) -> None:
        data = data or {}
        self._last_probe = data
        lay = self._probe_list_layout
        self._clear(lay)
        self._keys_box = None  # _clear 已删除旧钥匙区；_render_keys 会重建
        n = int(data.get("draft_pending") or 0)
        if getattr(self, "_probe_pending", None) is not None:
            if n > 0:
                self._probe_pending_txt.setText(
                    t("{n} 条经验待你放行", n=n))
                self._probe_pending.setVisible(True)
            else:
                self._probe_pending.setVisible(False)
        sr = data.get("self_reported") or {}
        # 小节头计数 chip（数量 0 不显示，保留「无需手动接入」空态）
        if getattr(self, "_probe_count_chip", None) is not None:
            if sr:
                self._set_neutral_chip_label(
                    self._probe_count_chip, t("{n} 个工具", n=len(sr)))
                self._probe_count_chip.show()
            else:
                self._probe_count_chip.hide()
        if not sr:
            lay.addWidget(txt(t("无需手动接入"), F.caption,
                              color=C.ink_500, italic=True))
        for agent, info in sorted(sr.items()):
            row = QHBoxLayout()
            row.setSpacing(S.s2)
            row.addWidget(txt(_agent_display(agent) or agent, F.body))
            row.addStretch(1)
            mode = str(info.get("mode") or "")
            row.addWidget(self._probe_mode_chip(mode), 0, Qt.AlignVCenter)
            at = str(info.get("at") or "")[:16].replace("T", " ")
            if at:
                row.addWidget(txt(t("最近 {at}", at=at),
                                  F.caption, color=C.ink_500))
            w = QWidget()
            w.setLayout(row)
            lay.addWidget(w)

        # Keys：已吸收的钥匙按“收到顺序”列出（连接码即钥匙寻址；M3 只读展示）
        self._render_keys(keys)
        pass  # 实时 Hook 接入已统一到「我的 Hooks」页，接入页不再重复渲染
