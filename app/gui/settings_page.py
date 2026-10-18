"""设置页——Qt 版（迁移自 Flet settings_page.py）。

只留「偏好 + 状态」：运行状态（含 shell_mode「已连接运行中实例」）/
数据目录 / 版本号 / 界面语言（7 语）/ 开机自启 / 通知中心 / 数据主权。
接入/模型/采集/注入预览五区已移入接入页。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout,
                               QLabel, QVBoxLayout, QWidget)

from . import i18n
from .api_client import LocalApi, LocalApiError
from .i18n import t
from .page_base import (PageBase, clear_layout, page_scaffold,
                        parallel_fetch)
from .qt_dialogs import confirm_dialog, input_dialog
from .qt_widgets import SelectButton, page_header
from .qt_theme import (btn_danger, btn_secondary, card, divider, status_tone,
                       switch, txt)
from .theme import C, D, F, S

from ..version import VERSION as _APP_VERSION  # 版本唯一来源（app/version.py）

logger = logging.getLogger("experientia.gui.settings")

# 语言名用内源名（各语言自称）——这是惯例，不做翻译
_ENDONYMS = {"zh": "简体中文", "en": "English", "ja": "日本語",
             "ko": "한국어", "fr": "Français", "de": "Deutsch", "es": "Español"}


def _open_folder(path: str) -> None:
    """在系统文件管理器中打开目录。"""
    if not path:
        return
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass


def available_languages() -> list[str]:
    """有编译好 .mo 的语言（7 语全量）。"""
    out = []
    for lang in i18n.SUPPORTED:
        if (i18n.LOCALES_DIR / lang / "LC_MESSAGES"
                / (i18n.DOMAIN + ".mo")).exists():
            out.append(lang)
    return out or ["zh"]


# 通知中心
#
# ⚠️ 这里存的是 **msgid（中文源串）**，不是 t() 的结果：
# 模块级常量在 import 时求值，彼时语言目录多半还没加载，t() 取到的源串会被
# **冻住**——首屏拿冻住的串渲染（英文用户看到中文卡片），切语言后
# retranslateUi 还得为每个常量手写一遍 if/elif 补救。现在渲染与 retranslateUi
# 都在**使用时**才 t()，首屏与语言切换走同一条路，补丁式 if/elif 随之删除。
_NOTIFY_DEFAULTS = {
    "method_update": True, "daily_summary": True,
    "growth_report": True, "system_notice": True,
}
_NOTIFY_ITEMS = [
    ("method_update", "方法动态", "方法沉淀/升级、新坑固化、偏好新增时推送"),
    ("daily_summary", "每日总结", "每天 21:00 推送积累概况（当天无积累不发）"),
    ("growth_report", "成长动态", "熟练度档位升档（中/高）时推送"),
    ("system_notice", "系统通知", "版本更新、洞察提醒等系统消息（不计入每日上限）"),
]
# 通知类型 → 类型标签 msgid（与 _NOTIFY_ITEMS 同口径）；渲染处包 t()
_NTYPE_LABEL = {k: label for k, label, _h in _NOTIFY_ITEMS}

# 遗留：通知 target 可点击跳页的白名单 = 主窗页面键 + 旧名
# 映射键（与 main_window.PAGES/_LEGACY 同口径；此处显式复制——main_window
# 懒加载本页，GUI 子页对其做模块级 import 有循环引用风险，故不直接引用）。
# target 为空或不在表内 → 该行不可跳（不挂点击）。
_NOTIF_NAV_TARGETS = frozenset({
    "home", "mine", "growth", "hooks", "export", "connect", "settings",
    "experiences", "methods", "failures", "prefs", "preferences",
    "models", "preview", "skill", "rules", "share",
})


class _NotifRow(QWidget):
    """可点击的通知行（遗留）：整行响应左键点击跳转 target 页。"""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802（Qt 虚函数覆写）
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class SettingsPage(PageBase):
    """设置页：运行状态 / 语言 / 自启 / 通知 / 数据主权。"""

    def __init__(self, api: LocalApi, parent: QWidget | None = None):
        super().__init__(api, parent)
        self._loading = False
        self._lang_guard = False
        self._theme_guard = False
        self._data_dir = ""  # refresh 缓存的 data_dir（打开文件夹按钮零阻塞取数）
        self._build()
        # 懒加载下构建阶段零 API（settings.refresh 调 /api/status 全盘探测）：
        # 数据由主窗口的延迟 refresh 填充

    # ---------- 构建 ----------

    def _build(self) -> None:
        self.content = QWidget()
        self._cl = QVBoxLayout(self.content)
        self._cl.setContentsMargins(0, 0, 0, 0)
        self._cl.setSpacing(S.s6)

        # 统一页头（S1）
        head = page_header(t("设置"))
        self._settings_heading = head.findChild(QLabel, "pageTitle")
        self._cl.addWidget(head)

        # 运行状态（shell_mode 时如实换文案）
        self._shell = os.environ.get("EXPERIENTIA_SHELL_MODE") == "1"
        run_card = card(title=t("运行状态"))
        self._run_card_title = run_card.layout().itemAt(0).widget()
        run_lay = run_card.layout()

        running = QWidget()
        running_lay = QHBoxLayout(running)
        running_lay.setContentsMargins(0, 0, 0, 0)
        running_lay.setSpacing(S.s1)
        dot = QLabel()
        dot.setFixedSize(D.DOT, D.DOT)
        dot.setStyleSheet(f"background: {C.ok_fg}; border-radius: {D.DOT // 2}px;")
        running_lay.addWidget(dot)
        self._running_txt = txt(
            t("已连接运行中实例") if self._shell else t("运行中"),
            F.body, 600, C.ok_fg)
        running_lay.addWidget(self._running_txt)
        running_lay.addSpacing(S.s1)
        self._agent_count_txt = txt("", F.body, color=C.ink_500)
        running_lay.addWidget(self._agent_count_txt)
        running_lay.addStretch(1)
        run_lay.addWidget(running)

        # 已探测 agent
        agents_row = QHBoxLayout()
        agents_row.setSpacing(S.s2)
        self._detected_agents_label = txt(t("已探测 agent"), F.body, color=C.ink_700)
        agents_row.addWidget(self._detected_agents_label)
        self._agents_txt = txt("", F.body, color=C.ink_500)
        agents_row.addWidget(self._agents_txt)
        agents_row.addStretch(1)
        run_lay.addLayout(agents_row)

        # 数据目录
        data_row = QHBoxLayout()
        data_row.setSpacing(S.s2)
        self._data_dir_txt = txt("", F.body, color=C.ink_700)
        data_row.addWidget(self._data_dir_txt, 1)
        self._data_dir_btn = btn_secondary(t("打开文件夹"), "FOLDER_OPEN_OUTLINED",
                                           self._open_data_dir)
        data_row.addWidget(self._data_dir_btn)
        self._data_dir_change_btn = btn_secondary(t("更换目录"), "folder-move-outline",
                                                  self._change_data_dir)
        data_row.addWidget(self._data_dir_change_btn)
        run_lay.addLayout(data_row)
        # 更换结果行（迁移状态 / 指针失效提示）+ 重启行
        self._data_dir_status = txt("", F.caption, color=C.info_fg)
        self._data_dir_status.setWordWrap(True)
        run_lay.addWidget(self._data_dir_status)
        self._data_dir_restart_row = QWidget()
        _rr = QHBoxLayout(self._data_dir_restart_row)
        _rr.setContentsMargins(0, 0, 0, 0)
        _rr.setSpacing(S.s2)
        self._data_dir_restart_btn = btn_secondary(t("立即重启"), "restart",
                                                   self._do_relaunch)
        _rr.addWidget(self._data_dir_restart_btn)
        _rr.addStretch(1)
        self._data_dir_restart_row.hide()
        run_lay.addWidget(self._data_dir_restart_row)

        # 版本号（只展示：更新检查链路已整块移除，见产品文档）
        self._version_txt = txt(f"{t('版本')}：{_APP_VERSION}", F.caption,
                                color=C.ink_500)
        run_lay.addWidget(self._version_txt)
        self._cl.addWidget(run_card)

        # 界面语言 + 开机自启
        pref_card = card(title=t("偏好"))
        self._pref_card_title = pref_card.layout().itemAt(0).widget()
        pref_lay = pref_card.layout()

        lang_row = QHBoxLayout()
        lang_row.setSpacing(S.s2)
        self._lang_label = txt(t("界面语言"), F.body, color=C.ink_700)
        lang_row.addWidget(self._lang_label)
        self._lang_dd = SelectButton(width=D.DD_W_SM)
        for l in available_languages():
            self._lang_dd.addItem(_ENDONYMS.get(l, l), l)
        self._lang_dd.setCurrentIndex(
            self._lang_dd.findData(i18n.current_language()))
        self._lang_dd.currentIndexChanged.connect(self._change_language)
        lang_row.addWidget(self._lang_dd)
        lang_row.addStretch(1)
        pref_lay.addLayout(lang_row)

        # 界面外观（亮/暗，dark mode：跟随系统 / 亮色 / 深色）
        theme_row = QHBoxLayout()
        theme_row.setSpacing(S.s2)
        self._theme_label = txt(t("界面外观"), F.body, color=C.ink_700)
        theme_row.addWidget(self._theme_label)
        self._theme_dd = SelectButton(width=D.DD_W_SM)
        for label, val in ((t("跟随系统"), "system"), (t("亮色"), "light"),
                           (t("深色"), "dark")):
            self._theme_dd.addItem(label, val)
        self._theme_dd.currentIndexChanged.connect(self._change_theme)
        theme_row.addWidget(self._theme_dd)
        theme_row.addStretch(1)
        pref_lay.addLayout(theme_row)

        # 开机自启：单点启停走 switch()（方框复选框留给"选择"语义，不撞形）
        autostart_row = QHBoxLayout()
        autostart_row.setSpacing(S.s2)
        self._autostart_sw = switch(on_toggled=self._change_autostart)
        autostart_row.addWidget(self._autostart_sw)
        self._autostart_label = txt(t("开机自启"), F.body, color=C.ink_700)
        autostart_row.addWidget(self._autostart_label)
        autostart_row.addStretch(1)
        pref_lay.addLayout(autostart_row)
        self._cl.addWidget(pref_card)

        # 通知中心
        self._cl.addWidget(self._build_notify())

        # 数据主权
        self._cl.addWidget(self._build_wipe_card())

        # 尾部 stretch：内容不足时靠顶排布，避免卡片被视口拉高（同 home 收尾）
        self._cl.addStretch(1)

        self._wrap_scroll()

    def _wrap_scroll(self) -> None:
        """用 page_scaffold 包装内容层，居中 + 最大宽度限制。"""
        # S2：统一骨架（顶边 32px 由页头给）
        scroll = page_scaffold(self._cl, top=0)
        self._layout.addWidget(scroll)

    # ---------- 状态行（数据主权操作反馈） ----------

    def _set_wipe_status(self, msg: str, tone: str = "ok") -> None:
        colors = {"ok": C.ok_fg, "err": C.err_fg, "warn": C.warn_fg,
                  "info": C.info_fg}
        self._wipe_status.setText(msg)
        status_tone(self._wipe_status, colors[tone])

    # ---------- 语言 / 自启 ----------

    def _change_language(self, _idx: int) -> None:
        if self._lang_guard:
            return
        locale = self._lang_dd.currentData()
        mw = self._mw
        if mw is None:
            return
        self._lang_guard = True
        try:
            self.api.update_config({"locale": locale})
        except Exception:
            self._lang_dd.setCurrentIndex(
                self._lang_dd.findData(i18n.current_language()))
            self._lang_guard = False
            self.set_status(t("语言切换失败"), "err")
            return
        self._lang_guard = False
        mw.switch_language(locale)

    def _change_theme(self, _idx: int) -> None:
        """界面外观切换：写配置 → 主窗口重建（C 色板已切换并重应用样式）。"""
        if self._theme_guard:
            return
        mode = self._theme_dd.currentData()
        mw = self._mw
        if mw is None:
            return
        self._theme_guard = True
        try:
            self.api.update_config({"ui_theme": mode})
        except Exception:
            self._theme_guard = False
            self.set_status(t("外观切换失败"), "err")
            return
        self._theme_guard = False
        mw.switch_theme(mode)

    def _change_autostart(self, checked: bool) -> None:
        if self._loading:
            return
        # autostart 端点 60s 超时原是同步调用，跑在 UI
        # 线程——注册表/系统服务探活卡住时整窗冻结。改后台执行；失败回滚开关
        # （与 _save_notify 的失败回滚同范式），不让开关停留在"假生效"状态。
        sw = self._autostart_sw
        try:
            sw.setEnabled(False)
        except RuntimeError:
            sw = None  # 控件已销毁（页面刚被重建），只做后台调用
        self.set_status(t("正在处理…"), "info")

        def work():
            self.api.autostart(bool(checked))

        def done(_r) -> None:
            if sw is not None:
                try:
                    sw.setEnabled(True)
                except RuntimeError:
                    pass

        def err(e) -> None:
            if sw is not None:
                try:
                    sw.setChecked(not checked)  # 回滚到操作前状态
                    sw.setEnabled(True)
                except RuntimeError:
                    pass
            logger.warning("自启设置失败: %s", e)
            self.set_status(t("自启设置失败：{err}", err=e), "err")

        self.run_async(work, done, err)

    # ---------- 通知中心 ----------

    def _build_notify(self) -> QFrame:
        c = card(secondary=True)
        lay = c.layout()
        self._notify_heading = txt(t("通知"), F.h2, 600, C.ink_700)
        lay.addWidget(self._notify_heading)
        # 一键静音：总开关（switch），与下方 5 条单项开关同形态
        mute_row = QHBoxLayout()
        mute_row.setSpacing(S.s2)
        self._mute_sw = switch(on_toggled=self._toggle_mute)
        mute_row.addWidget(self._mute_sw)
        self._mute_label = txt(t("全部关闭（一键静音）"), F.body,
                               color=C.ink_700)
        mute_row.addWidget(self._mute_label)
        mute_row.addStretch(1)
        lay.addLayout(mute_row)
        self._notify_switches: dict[str, QWidget] = {}
        self._notify_labels: dict[str, tuple] = {}
        # msgid 与控件分开存：retranslateUi 靠它重新 t()
        self._notify_msgs: dict[str, tuple[str, str]] = {}
        for key, label, hint in _NOTIFY_ITEMS:
            sw = switch()
            sw.toggled.connect(
                lambda checked, k=key: self._save_notify(k, checked))
            self._notify_switches[key] = sw
            row = QHBoxLayout()
            row.setSpacing(S.s2)
            row.addWidget(sw)
            col = QVBoxLayout()
            col.setSpacing(S.s1)
            title_lab = txt(t(label), F.body)
            hint_lab = txt(t(hint), F.caption, color=C.ink_500)
            col.addWidget(title_lab)
            col.addWidget(hint_lab)
            self._notify_labels[key] = (title_lab, hint_lab)
            self._notify_msgs[key] = (label, hint)
            row.addLayout(col, 1)
            box = QWidget()
            box.setLayout(row)
            # 每条通知项加 1px 下分隔线（最后一条不加）+ 左右内边距，
            # 让通知项从一坨变成清晰的列表感；直接对 box 设属性避免裸 QWidget{} 选择器
            items_count = len(_NOTIFY_ITEMS)
            idx = len(self._notify_switches)  # 已处理条数（含当前）
            if idx < items_count:  # 非最后一条
                box.setStyleSheet(
                    f"border-bottom: 1px solid {C.line};"
                    f" padding: {S.s2}px {S.s3}px;"
                    f" background: transparent;")
            else:
                box.setStyleSheet(
                    f"padding: {S.s2}px {S.s3}px; background: transparent;")
            lay.addWidget(box)
        self._notify_form_txt = txt(
            t("推送以系统级原生通知弹出（像 Windows 通知那样）"),
            F.caption, color=C.ink_500)
        lay.addWidget(self._notify_form_txt)
        self._notify_limit_txt = txt(t("推送上限：每天 2 条（「系统通知」不计入）"),
                                     F.caption, color=C.ink_500)
        lay.addWidget(self._notify_limit_txt)
        # 最近通知列表（历史通知无处查看、未读只增不减
        # 的最小实现）——复用既有 GET /api/notifications + POST /api/notifications/
        # read 端点，服务端零改动。位置收在「通知」卡内（通知开关正下方）：用户
        # 对通知的心智都在这一个区块，不另开导航项。
        lay.addWidget(divider())
        self._notif_head = txt(t("最近通知"), F.body, 600, C.ink_700)
        lay.addWidget(self._notif_head)
        self._notif_box = QWidget()
        self._notif_lay = QVBoxLayout(self._notif_box)
        self._notif_lay.setContentsMargins(0, 0, 0, 0)
        self._notif_lay.setSpacing(S.s1)
        lay.addWidget(self._notif_box)
        return c

    def _fetch_notifications(self) -> list:
        """后台线程取最近 20 条通知，并调 notifications_read 标记全部已读
        （主窗口未读轮询的基线随之清零，未读不再只增不减）。取数段在
        ``_fetch`` 的工作线程内执行，主线程零 HTTP。"""
        try:
            items = self.api.notifications(limit=20).get("items", [])
        except LocalApiError:
            items = []
        try:
            self.api.notifications_read()
        except LocalApiError:
            pass  # 标记已读失败不挡列表展示（下轮再标）
        return items

    def _render_notifications(self, items: list) -> None:
        """主线程渲染通知列表（纯填控件，不发 HTTP）。"""
        clear_layout(self._notif_lay)
        # 遗留：渲染时记录 (行控件, target)，供测试与调试；
        # target 为空/未知 → 挂普通 QWidget（不可点、箭头光标）
        self._notif_rows = []
        if not items:
            self._notif_lay.addWidget(txt(t("暂无通知"), F.caption,
                                          color=C.ink_500, italic=True))
            return
        for it in items:
            typ = str(it.get("type") or "")
            # _NTYPE_LABEL 存 msgid，这里才 t()——原实现存的是
            # import 时冻住的译文，语言切换后通知列表的类型标签仍是中文
            label = t(_NTYPE_LABEL.get(typ, typ))
            col = QVBoxLayout()
            col.setSpacing(S.s1)
            col.addWidget(txt(f"{label} · {it.get('title') or ''}", F.body, 600))
            body = str(it.get("body") or "")
            if body:
                b = txt(body, F.caption, color=C.ink_500)
                b.setWordWrap(True)
                col.addWidget(b)
            row = QHBoxLayout()
            row.setSpacing(S.s2)
            row.addLayout(col, 1)
            row.addWidget(txt(str(it.get("ts") or "")[:16].replace("T", " "),
                              F.caption, color=C.ink_500))
            target = str(it.get("target") or "")
            if typ == "growth_report":
                # 周报通知：点开本周结算卡，而不是只跳页
                box = _NotifRow()
                box.setToolTip(t("点开看本周结算"))
                box.clicked.connect(lambda _=False: self._open_weekly_card())
            elif target in _NOTIF_NAV_TARGETS:
                # 可跳行：手型光标 + 点击经 PageBase.go → 主窗 go（含
                # _LEGACY 旧名映射，如 methods → mine）
                box = _NotifRow()
                box.setToolTip(t("点击前往相关页面"))
                box.clicked.connect(lambda _=False, tg=target: self.go(tg))
            else:
                box = QWidget()
            box.setLayout(row)
            self._notif_rows.append(
                (box, target if target in _NOTIF_NAV_TARGETS else None))
            self._notif_lay.addWidget(box)

    def _open_weekly_card(self) -> None:
        from .weekly_card import open_weekly_card

        open_weekly_card(self.api, self)

    def _refresh_notify(self, config: dict) -> None:
        notify_cfg = dict(_NOTIFY_DEFAULTS)
        notify_cfg.update(config.get("notify") or {})
        muted = bool(config.get("notify_muted"))
        self._mute_sw.setChecked(muted)
        for key, sw in self._notify_switches.items():
            sw.setChecked(bool(notify_cfg.get(key, True)))
            sw.setEnabled(not muted)

    def _save_notify(self, key: str, value: bool) -> None:
        if self._loading:
            return
        sw = self._notify_switches[key]
        try:
            cur = dict(_NOTIFY_DEFAULTS)
            try:
                saved = self.api.config().get("notify") or {}
            except Exception:
                saved = {}
            # 只回写仍生效的键：残留的已删项（如 v1.x 的 desktop_popup）顺带清掉
            cur.update({k: v for k, v in saved.items() if k in _NOTIFY_DEFAULTS})
            cur[key] = bool(value)
            patch = {"notify": cur}
            if self._mute_sw.isChecked() and value:
                # 静音中单独打开某项 = 解除静音
                patch["notify_muted"] = False
            self.api.update_config(patch)
        except Exception:
            # 保存失败不再静默——开关回滚 + 状态行提示
            sw.blockSignals(True)
            sw.setChecked(not value)
            sw.blockSignals(False)
            self.set_status(t("通知设置保存失败"), "err")

    def _toggle_mute(self, checked: bool) -> None:
        if self._loading:
            return
        saved_cfg = None
        try:
            # 静音时把全部通知项关掉，并保存到后端
            notify_cfg = dict(_NOTIFY_DEFAULTS)
            try:
                saved = self.api.config().get("notify") or {}
                saved_cfg = dict(saved)
            except Exception:
                saved = {}
            notify_cfg.update({k: v for k, v in saved.items()
                               if k in _NOTIFY_DEFAULTS})
            if checked:
                for key in notify_cfg:
                    notify_cfg[key] = False
                self.api.update_config({"notify": notify_cfg, "notify_muted": True})
            else:
                self.api.update_config({"notify_muted": False})
        except Exception:
            # 失败回滚静音开关 + 状态行提示（不静默）
            self._mute_sw.blockSignals(True)
            self._mute_sw.setChecked(not checked)
            self._mute_sw.blockSignals(False)
            self.set_status(t("通知设置保存失败"), "err")
            return
        # 成功路径：单项开关随静音态联动（失败时保持原状，不误导）
        for key, sw in self._notify_switches.items():
            sw.blockSignals(True)
            if checked:
                sw.setChecked(False)
            elif saved_cfg:
                sw.setChecked(bool(saved_cfg.get(key, True)))
            sw.setEnabled(not checked)
            sw.blockSignals(False)

    # ---------- 数据主权 ----------

    def _build_wipe_card(self) -> QFrame:
        c = card(secondary=True)
        lay = c.layout()
        head = QHBoxLayout()
        head.setSpacing(S.s2)
        self._wipe_heading = txt(t("数据主权"), F.h2, 600, C.ink_700)
        head.addWidget(self._wipe_heading)
        head.addStretch(1)
        self._wipe_btn = btn_danger(t("一键彻底删除"), "DELETE_OUTLINED",
                                    self._open_wipe)
        head.addWidget(self._wipe_btn)
        lay.addLayout(head)
        self._wipe_desc = txt(t("你的数据只在本机：一键导出带走，一键彻底删除不留痕。"),
                              F.caption, color=C.ink_500)
        lay.addWidget(self._wipe_desc)
        self._wipe_status = txt("", F.caption, color=C.info_fg)
        self._wipe_status.setWordWrap(True)
        lay.addWidget(self._wipe_status)
        return c

    def _open_wipe(self) -> None:
        ok = confirm_dialog(
            t("确认删除"),
            t("将删除数据目录里的全部数据（经验、方法、偏好、规则、会话记录、"
              "配置），不可撤销。删除前可先在导出页做全量导出备份。"), self)
        if not ok:
            return
        # 安全：服务端要求用户手动输入 WIPE 作为第二道防线，
        # 此处必须校验用户键入，不得代填（否则误触即全库删除）。
        typed = input_dialog(
            t("二次确认"),
            t("请输入 WIPE 以确认彻底删除全部数据："), self)
        if typed != "WIPE":
            return
        self._set_wipe_status(t("删除中…"), "info")
        self.run_async(
            lambda: self.api.wipe("WIPE"),
            self._on_wipe_done, lambda err: self._set_wipe_status(str(err), "err"))

    def _on_wipe_done(self, r: dict) -> None:
        leftovers = (r or {}).get("leftovers") or []
        if leftovers:
            # 被进程占用的文件（如 engine.lock）删不掉——如实上报，不谎报"全部"
            self._set_wipe_status(t(
                "数据已删除，{n} 个占用中文件未删：{names}",
                n=len(leftovers), names=", ".join(leftovers[:3])), "warn")
        else:
            self._set_wipe_status(t("全部数据已彻底删除"), "ok")

    # ---------- 刷新 ----------

    def refresh(self) -> None:
        """设置页刷新：status/config/通知三项取数整体挪后台线程，
        渲染回调只填文本与开关状态，主线程零 HTTP。"""
        self.fetch_and_render(self._fetch, self._render, "settings",
                              skeleton=[24, 72, 72, 72])

    def _fetch(self) -> dict:
        """工作线程取数（绝不触碰 widget）。"""
        return parallel_fetch({
            "status": self.api.status,
            "config": self.api.config,
            "notif": self._fetch_notifications,
        })

    def _render(self, res: dict | None) -> None:
        """主线程渲染：只填文本/开关，不再发 HTTP。"""
        res = res or {}
        status, config = res.get("status"), res.get("config")
        if status is None or config is None:
            self._loading = False
            self.set_status(t("设置加载失败，稍后重试"), "err")
            return
        self._loading = True
        try:
            agents = status.get("agents", {}) or {}
            self._agent_count_txt.setText(
                f"（{t('自动记录')} {t('{n} 个 agent', n=len(agents))}）")
            self._agents_txt.setText(", ".join(sorted(agents)) or "—")
            self._data_dir = str(status.get("data_dir", "") or "")
            self._data_dir_txt.setText(f"{t('数据目录')}：{self._data_dir}")
            # 指针失效回退默认位置（如实提示，不假装没发生）
            if status.get("data_dir_fallback"):
                self._data_dir_status.setText(t(
                    "数据目录指针失效（目标目录不存在），已回退默认位置"))
                status_tone(self._data_dir_status, C.warn_fg)
            # 界面外观（config 值 system/light/dark；blockSignals 防切换触发重建）
            self._theme_dd.blockSignals(True)
            self._theme_dd.setCurrentIndex(
                self._theme_dd.findData(config.get("ui_theme") or "system"))
            self._theme_dd.blockSignals(False)
            self._autostart_sw.setChecked(bool(config.get("autostart")))
            self._refresh_notify(config)
            self._render_notifications(res.get("notif") or [])
        finally:
            self._loading = False

    def retranslateUi(self) -> None:
        """重新调用 t() 更新所有静态 widget 文本。"""
        self._settings_heading.setText(t("设置"))
        self._run_card_title.setText(t("运行状态"))
        self._running_txt.setText(
            t("已连接运行中实例") if self._shell else t("运行中"))
        self._detected_agents_label.setText(t("已探测 agent"))
        # _data_dir_btn has icon, find child QLabel
        data_dir_label = self._data_dir_btn.layout().itemAt(1).widget()
        data_dir_label.setText(t("打开文件夹"))
        # _data_dir_change_btn has icon, find child QLabel
        change_label = self._data_dir_change_btn.layout().itemAt(1).widget()
        change_label.setText(t("更换目录"))
        # _data_dir_restart_btn has icon, find child QLabel
        restart_label = self._data_dir_restart_btn.layout().itemAt(1).widget()
        restart_label.setText(t("立即重启"))
        self._version_txt.setText(f"{t('版本')}：{_APP_VERSION}")
        self._pref_card_title.setText(t("偏好"))
        self._lang_label.setText(t("界面语言"))
        self._theme_label.setText(t("界面外观"))
        self._theme_dd.setItemText(0, t("跟随系统"))
        self._theme_dd.setItemText(1, t("亮色"))
        self._theme_dd.setItemText(2, t("深色"))
        self._autostart_label.setText(t("开机自启"))
        self._notify_heading.setText(t("通知"))
        self._mute_label.setText(t("全部关闭（一键静音）"))
        # 通知项：与首屏同一条路——从 msgid 重新 t()（原来是
        # 模块级常量 import 时 t() 冻住源串，这里手写 if/elif 逐个补救）
        for key, (title_lab, hint_lab) in self._notify_labels.items():
            label, hint = self._notify_msgs[key]
            title_lab.setText(t(label))
            hint_lab.setText(t(hint))
        self._notify_form_txt.setText(
            t("推送以系统级原生通知弹出（像 Windows 通知那样）"))
        self._notify_limit_txt.setText(
            t("推送上限：每天 2 条（「系统通知」不计入）"))
        self._notif_head.setText(t("最近通知"))
        # 通知列表为动态数据，走 refresh() 重拉（类型标签经 _NTYPE_LABEL
        # 在渲染时取 t() 词条）；刷新已改异步，主线程零 HTTP
        self.refresh()
        self._wipe_heading.setText(t("数据主权"))
        # _wipe_btn has icon
        wipe_label = self._wipe_btn.layout().itemAt(1).widget()
        wipe_label.setText(t("一键彻底删除"))
        self._wipe_desc.setText(
            t("你的数据只在本机：一键导出带走，一键彻底删除不留痕。"))

    def _open_data_dir(self) -> None:
        """打开数据目录：用 refresh 缓存的值（点击不再阻塞主线程取数）；
        缓存尚未填充时走后台线程补取一次。"""
        path = getattr(self, "_data_dir", "")
        if path:
            _open_folder(path)
            return
        self.run_async(lambda: self.api.status().get("data_dir", ""),
                       _open_folder)

    # ---------- 更换数据目录 ----------

    def _change_data_dir(self) -> None:
        """目录选择 → 确认迁移语义 → 异步整体搬迁（引擎侧执行）。

        目标在用户主目录之外时（D 盘/移动盘/网络盘），
        确认框里多讲一句"盘不在线就读不到经验库"——后端是同一判据的强制闸，
        这里本地镜像只为把风险在同一句里说清（用户一次看完再决定）。"""
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        target = QFileDialog.getExistingDirectory(
            self, t("选择新的数据目录"), str(Path.home()))
        if not target:
            return
        body = t("将把现有数据整体搬到 {path}（原位置重启后只留一个指针文件）。"
                 "确定继续？", path=target)
        outside_home = False
        try:
            outside_home = not Path(target).resolve().is_relative_to(
                Path.home().resolve())
        except OSError:
            outside_home = True  # 解析不了 → 按"主目录之外"从严提示
        if outside_home:
            body += "\n\n" + t(
                "注意：这个位置在用户主目录之外（可能是移动盘或网络盘）——"
                "盘不在线时软件会读不到经验库。")
        ok = confirm_dialog(t("更换数据目录"), body, self)
        if not ok:
            return
        self._data_dir_status.setText(t("正在迁移数据…"))
        status_tone(self._data_dir_status, C.info_fg)
        self._data_dir_restart_row.hide()
        self.run_async(
            lambda: self.api.data_dir_migrate(target, outside_home),
            self._on_data_dir_migrated, self._on_data_dir_migrate_failed)

    def _on_data_dir_migrated(self, r: dict) -> None:
        self._data_dir_status.setText(t(
            "已更换数据目录到 {path}，重启后生效", path=r.get("dir", "")))
        status_tone(self._data_dir_status, C.ok_fg)
        if not self._shell:
            # 纯壳模式（引擎是独立常驻进程）：壳无法代重启引擎，不显示按钮，
            # 由用户托盘退出后重新打开
            self._data_dir_restart_row.show()

    def _on_data_dir_migrate_failed(self, err: str) -> None:
        self._data_dir_status.setText(t("更换数据目录失败：{err}", err=err))
        status_tone(self._data_dir_status, C.err_fg)

    def _do_relaunch(self) -> None:
        """立即重启：引擎侧拉起分离 helper，
        本进程退出后由 helper 拉起新实例。"""
        try:
            self.api.app_relaunch()
        except LocalApiError as exc:
            self._data_dir_status.setText(t("重启失败：{err}", err=exc.detail))
            status_tone(self._data_dir_status, C.err_fg)
            return
        mw = self._mw
        if mw is not None:
            mw._allow_quit = True  # 绕过"关闭藏托盘"拦截（同托盘退出）
        QApplication.quit()
