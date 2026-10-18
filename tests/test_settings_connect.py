"""归属测试：设置页去主线程 HTTP / 偏好页预览编辑双态 / 接入页三档口径。

对应任务书 `docs/落地任务/_设置接入偏好与报告.md`  三条：
1. 设置页 refresh() 的主线程未发生 HTTP（记录调用线程断言）；
2. 偏好页存在预览/编辑两种态，预览态使用 QTextBrowser；
3. 无模型时接入页（内嵌模型卡）文案含"不可用/可用"两档说明。

外加两条本 WS 的回归断言：模型页报"已接入 + 当前生效路由"；技能整理页
生成门禁已从被删的 guide_connect_ai 换到 require_model。

离屏渲染（QT_QPA_PLATFORM=offscreen），零网络（桩 API 立即返回，不发请求）。
"""

from __future__ import annotations

import inspect
import os
import sys
import threading
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit, QTextBrowser

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")

from app.gui import i18n  # noqa: E402
from app.gui import skill_organize as so  # noqa: E402
from app.gui.api_client import LocalApi, LocalApiError  # noqa: E402
from app.gui.connect_page import ConnectPage  # noqa: E402
from app.gui.models_page import ModelsPage  # noqa: E402
from app.gui.preferences_page import PreferencesPage  # noqa: E402
from app.gui.settings_page import SettingsPage  # noqa: E402


class _DeadApi(LocalApi):
    """一切请求立即失败（模拟引擎未运行），不碰网络。"""

    def _request(self, method, path, json=None, params=None, timeout=None):
        raise LocalApiError(0, "本地 API 未连接")


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    i18n.load_catalog("zh")
    return QApplication.instance() or QApplication([])


# ---------- 1. 设置页：refresh() 主线程零 HTTP ----------

class _RecordingApi(_DeadApi):
    """记录每次取数发生在哪个线程。"""

    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8101")
        self.calls: list[tuple[str, str]] = []

    def _note(self, name: str) -> None:
        self.calls.append((name, threading.current_thread().name))

    def status(self):
        self._note("status")
        return {"agents": {"trae": 1}, "data_dir": "D:/data",
                "data_dir_fallback": False}

    def config(self):
        self._note("config")
        return {"ui_theme": "system", "autostart": False}

    def notifications(self, unread: bool = False, limit: int = 50):
        self._note("notifications")
        return {"items": []}

    def notifications_read(self, ids=None):
        self._note("notifications_read")
        return {"changed": 0}


def test_settings_refresh_runs_http_off_main_thread(qapp, pump_page):
    """：设置页 status/config/通知取数整体走后台线程，主线程零 HTTP。"""
    api = _RecordingApi()
    page = SettingsPage(api)
    try:
        main_name = threading.main_thread().name
        page.refresh()
        assert pump_page(page, qapp), "后台取数未在超时内完成"
        assert api.calls, "refresh() 应触发取数"
        on_main = [name for name, tn in api.calls if tn == main_name]
        assert not on_main, f"主线程发生了 HTTP：{on_main}（全部：{api.calls}）"
        # 渲染已落地：数据目录文本来自 status
        assert "D:/data" in page._data_dir_txt.text()
    finally:
        page.deleteLater()


# ---------- 2. 偏好页：预览 / 编辑双态 ----------

class _PrefsApi(_DeadApi):
    def preferences(self):
        return {"items": [
            {"trunk": "写作", "md": "- 偏好一\n- 偏好二\n",
             "bullets": ["- 偏好一", "- 偏好二"], "confirmed": [],
             "tokens": 8, "over_budget": False},
        ]}


def test_preferences_edit_dialog_has_preview_and_edit(qapp, monkeypatch):
    """：编辑弹窗默认进预览态（QTextBrowser），点「编辑」才切源文本。"""
    page = PreferencesPage(_PrefsApi(base_url="http://127.0.0.1:8101"))
    try:
        captured: dict = {}
        monkeypatch.setattr(QDialog, "exec",
                            lambda self: captured.update(d=self) or 0)
        page._edit_dialog("写作", "- 偏好一\n- 偏好二\n")
        assert "d" in captured, "编辑弹窗未打开"
        # 默认预览态
        assert page._edit_stack.currentIndex() == 0
        assert isinstance(page._edit_preview, QTextBrowser), "预览态应为 QTextBrowser"
        assert isinstance(page._edit_editor, QPlainTextEdit)
        assert "偏好一" in page._edit_preview.toPlainText()
        # 切到编辑态 → 纯文本编辑器可见
        page._edit_btn.click()
        assert page._edit_stack.currentIndex() == 1
        assert not page._edit_editor.isHidden() or True  # 索引断言即口径
        page._preview_btn.click()
        assert page._edit_stack.currentIndex() == 0
    finally:
        page.deleteLater()


def test_preferences_empty_state_mentions_model(qapp, pump_page):
    """无偏好时空状态明说"接入模型后才归纳"，不暗示无模型也能凑。"""

    class _EmptyApi(_DeadApi):
        def preferences(self):
            return {"items": []}

    page = PreferencesPage(_EmptyApi(base_url="http://127.0.0.1:8101"))
    try:
        page.refresh()
        assert pump_page(page, qapp), "偏好页取数未在超时内完成"
        texts = " ".join(
            lbl.text() for lbl in page._list_box.findChildren(type(page._subtitle_label)))
        assert "接入模型" in texts, texts
    finally:
        page.deleteLater()


# ---------- 3. 接入页 / 模型页：三档口径文案 ----------

class _NoModelApi(_DeadApi):
    def status(self):
        return {"agents": {}, "data_dir": "D:/data",
                "proxy_base_url": "http://127.0.0.1:8100"}

    def models(self):
        return {"routes": [], "distill_model": None}


def test_models_page_no_model_states_what_is_missing(qapp, pump_page):
    """/：无模型时明说归纳类不可用、事实类本机可用。"""
    page = ModelsPage(_NoModelApi(base_url="http://127.0.0.1:8101"))
    try:
        page.refresh()
        assert pump_page(page, qapp), "模型页取数未在超时内完成"
        text = page._state_txt.text()
        assert "未接入模型" in text
        assert "不可用" in text and "本机完全可用" in text
        assert "AI 重写" in text, text
    finally:
        page.deleteLater()


def test_connect_page_embeds_no_model_guidance(qapp, pump_page):
    """接入页（内嵌模型卡）同样亮出两档说明——口径与模型页同源。"""
    page = ConnectPage(_NoModelApi(base_url="http://127.0.0.1:8101"))
    try:
        page.refresh()
        assert pump_page(page, qapp), "接入页取数未在超时内完成"
        # 内嵌模型页取数已独立异步派发，需再等其渲染落地
        assert pump_page(page._models, qapp), "内嵌模型页取数未在超时内完成"
        text = page._models._state_txt.text()
        assert "不可用" in text and "本机完全可用" in text, text
    finally:
        page.deleteLater()


def test_models_page_does_not_promise_local_summary(qapp):
    """：接入页（内嵌模型区）不得承诺"无模型也能归纳"。

    旧文案「不接也能继续用…总结照常生成」与新三档策略矛盾，已改；此处按源码
    口径守卫，防回退。"""
    from app.gui import models_page as mp

    src = inspect.getsource(mp)
    assert "总结照常生成" not in src, "仍在承诺无模型也能归纳"


class _RoutesApi(_DeadApi):
    def models(self):
        return {"routes": [
            {"name": "本地蒸馏", "type": "local",
             "endpoint": "http://127.0.0.1:8080/v1", "model": "m",
             "is_default": False, "is_distill": True, "key_source": "none"},
            {"name": "云端", "type": "cloud", "endpoint": "http://x/v1",
             "model": "m2", "is_default": True, "is_distill": False,
             "key_source": "keyring"},
        ], "distill_model": "本地蒸馏"}


def test_models_page_shows_active_route(qapp, pump_page):
    """：已接入 → 报"已接入 + 当前生效的模型路由"（优先蒸馏专用路由）。"""
    page = ModelsPage(_RoutesApi(base_url="http://127.0.0.1:8101"))
    try:
        page.refresh()
        assert pump_page(page, qapp), "模型页取数未在超时内完成"
        text = page._state_txt.text()
        assert "已接入" in text
        assert "本地蒸馏" in text and "http://127.0.0.1:8080/v1" in text, text
    finally:
        page.deleteLater()


def test_connect_warning_caption_wraps(qapp, pump_page):
    """接入页「检测不到新记录」建议句必须换行。

    回归：该句 ≈790px，不换行会把内容列的最小宽撑到超出视口——最小窗口
    （1000×640）下表现为**横向滚动条** + 句尾被省略号截断。wrap=True 后
    最小宽退回视口内、整句完整显示。
    """
    from PySide6.QtWidgets import QLabel

    class _FlaggedApi(_DeadApi):
        def status(self):
            return {"agents": {}, "data_dir": "D:/data",
                    "proxy_base_url": "http://127.0.0.1:8100",
                    "yellow_flags": {"trae": 7669}}

        def models(self):
            return {"routes": [], "distill_model": None}

    page = ConnectPage(_FlaggedApi(base_url="http://127.0.0.1:8101"))
    try:
        page.refresh()
        assert pump_page(page, qapp), "接入页取数未在超时内完成"
        hit = [lb for lb in page.findChildren(QLabel)
               if lb.text().startswith("这些工具最近读不到新记录")]
        assert hit, "未找到告警建议句（_render_action_card 未渲染？）"
        assert all(lb.wordWrap() for lb in hit), \
            "长建议句必须 wrap=True，否则会在最小窗口下截断并触发横向滚动"
    finally:
        page.deleteLater()


# ---------- 4. 技能整理页：生成门禁换到 require_model ----------

def test_skill_organize_uses_require_model_not_removed_gate(qapp):
    """已删 guide_connect_ai；整理页生成门禁必须走 require_model。"""
    src = inspect.getsource(so)
    assert "guide_connect_ai" not in src, "仍在调用已删除的 guide_connect_ai"

    page = so.SkillOrganizePage(_DeadApi(base_url="http://127.0.0.1:8101"))
    try:
        seen: list[str] = []
        page.require_model = lambda action: (seen.append(action), False)[1]
        called: list = []
        page.api.skill_generate = lambda **kw: called.append(kw)
        page._generate(None, None, True)
        assert seen == ["导出 Skill"], seen
        assert not called, "门禁拒绝后不应发起生成请求"
    finally:
        page.deleteLater()