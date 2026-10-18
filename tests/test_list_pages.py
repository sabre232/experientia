"""归属测试：列表页去主线程 HTTP + 增量复用（任务书）。

三条口径：
1. `failure_modes` / `experiences` / `methods` 三页 `refresh()` 返回后，**主线程
   零 HTTP**——取数整体在工作线程（记录每次取数所在线程名断言）；
2. `export_page`：`_build()` 期零 HTTP；打开「数据导出」弹层的取数走后台线程
   （弹层先占位、落地后替换表单）；
3. 二次 `refresh()` 后列表卡片**控件对象复用**（id 集合不变 = 没整表重建）。

离屏渲染（QT_QPA_PLATFORM=offscreen），零网络（桩 API 立即返回，不发请求）。
"""

from __future__ import annotations

import os
import threading

import pytest

from PySide6.QtWidgets import QApplication, QDialog

pytest.importorskip("PySide6")

from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApi, LocalApiError  # noqa: E402


class _DeadApi(LocalApi):
    """一切未覆写的请求立即失败（不碰网络）。"""

    def _request(self, method, path, json=None, params=None, timeout=None):
        raise LocalApiError(0, "本地 API 未连接")


def _on_main(calls: list[tuple[str, str]]) -> list[str]:
    main = threading.main_thread().name
    return [name for name, tn in calls if tn == main]


def _layout_widgets(lay) -> list:
    return [lay.itemAt(i).widget() for i in range(lay.count())]


# ---------- 1. 失败模式页 ----------

class _FMRecApi(_DeadApi):
    """失败模式页桩：记录取数线程；返回 1 组三态坑卡。"""

    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8101")
        self.calls: list[tuple[str, str]] = []
        self.items = [{
            "trunk": "研发", "category": "工程实践", "name": "构建报错排查",
            "entries": [
                {"text": "npm run build 报模块缺失", "state": "solid",
                 "count": 3, "ts": "2026-09-19T00:00:00Z",
                 "last_seen": "2026-09-19"},
                {"text": "端口被占用", "state": "watch", "count": 2,
                 "ts": "2026-09-18T00:00:00Z"},
            ],
        }]

    def _note(self, name: str) -> None:
        self.calls.append((name, threading.current_thread().name))

    def failure_modes(self):
        self._note("failure_modes")
        return {"items": self.items}

    def rule_cards(self, limit: int = 8):
        self._note("rule_cards")
        return {"items": []}


def test_failure_modes_entry_text_wraps(qapp, pump_page):
    """坑卡正文/表头/元信息标签必须 `wrap=True`（数据驱动长句）。

    回归（多语言横向溢出）：坑卡正文来自数据（如「反复出现的报错「Error: String
    to replace not found…」」），不换行时标签最小宽 = 整句像素宽 → 撑爆内容列最小宽
    → 页面**横向滚动条**（实测中文也溢出 19px，德语 129px、法语 112px）。
    """
    from PySide6.QtWidgets import QLabel

    from app.gui.failure_modes import FailureModesPage

    page = FailureModesPage(_FMRecApi())
    try:
        page.resize(1000, 640)
        page.show()
        page.refresh()
        assert pump_page(page, qapp), "后台取数未在超时内完成"

        # 收集坑卡里的数据型长句标签（正文/trunk·category 表头/出现次数元信息），
        # 断言全部换行（允许短标签不换行，故按"是否可能是长句"过滤）
        suspects = [
            lb for lb in page.findChildren(QLabel)
            if lb.text() and lb.text() in ("npm run build 报模块缺失", "端口被占用")
        ]
        assert suspects, "未找到坑卡正文标签（渲染结构变了？）"
        assert all(lb.wordWrap() for lb in suspects), \
            "坑卡正文必须 wrap=True，否则德语/法语下会撑出横向滚动条"
    finally:
        page.deleteLater()


def test_failure_modes_refresh_http_off_main_thread(qapp, pump_page):
    """：坑卡页取数整体在工作线程，主线程零 HTTP。"""
    from app.gui.failure_modes import FailureModesPage

    api = _FMRecApi()
    page = FailureModesPage(api)
    try:
        page.resize(1200, 800)
        page.refresh()
        assert pump_page(page, qapp), "后台取数未在超时内完成"
        assert api.calls, "refresh() 应触发取数"
        assert not _on_main(api.calls), \
            f"主线程发生了 HTTP：{_on_main(api.calls)}（全部：{api.calls}）"
        # 渲染已落地：三态坑卡出现
        assert page._list_layout.count() >= 2
    finally:
        page.deleteLater()


def test_failure_modes_second_refresh_reuses_cards(qapp, pump_page):
    """：数据未变 → 二次刷新卡片对象恒等（未整表重建）。"""
    from app.gui.failure_modes import FailureModesPage

    page = FailureModesPage(_FMRecApi())
    try:
        page.resize(1200, 800)
        page.refresh()
        assert pump_page(page, qapp)
        before = _layout_widgets(page._list_layout)
        assert before and all(w is not None for w in before)
        page.refresh()
        assert pump_page(page, qapp)
        after = _layout_widgets(page._list_layout)
        assert [id(w) for w in after] == [id(w) for w in before], \
            "数据未变应原地复用——回到整表重建即回归"
    finally:
        page.deleteLater()


# ---------- 2. 经验库页 ----------

class _ExpRecApi(_DeadApi):
    """经验库页桩：记录取数线程；含 1 个多做法 task + 1 条独立经验。"""

    ITEMS = [
        {"id": "e1", "category": "模型", "task": "modelscope 登录状态检测",
         "agent": "hermes", "model": "Qwen", "ts": "2026-09-04T10:00:00",
         "trunk": "模型", "state": "curl 超时",
         "action": "subprocess 调 curl", "outcome": "拿到 200",
         "distilled": True, "G": 0.8},
        {"id": "e2", "category": "模型", "task": "modelscope 登录状态检测",
         "agent": "hermes", "model": "Qwen", "ts": "2026-09-04T11:00:00",
         "trunk": "模型", "state": "", "action": "os.popen 调 curl",
         "outcome": "", "distilled": False, "G": 0.6},
        {"id": "e3", "category": "基础设施", "task": "llama-server 端口被占用",
         "agent": "cursor", "model": "Qwen", "ts": "2026-09-03T09:00:00",
         "trunk": "基础设施", "state": "8080 被占用", "action": "换端口 8081",
         "outcome": "启动成功", "distilled": True, "G": 0.7},
    ]

    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8101")
        self.calls: list[tuple[str, str]] = []
        self.items = [dict(x) for x in self.ITEMS]

    def _note(self, name: str) -> None:
        self.calls.append((name, threading.current_thread().name))

    def experiences(self, trunk=None, category=None, agent=None, q=None,
                    include_distilled=True, limit=300):
        self._note("experiences")
        return {"items": self.items[:limit]}

    def experience_drafts(self, status="pending"):
        self._note("experience_drafts")
        return {"items": []}

    def pending_fragments(self):
        self._note("pending_fragments")
        return {"items": []}

    def models(self):
        self._note("models")
        return {"routes": []}


def test_experiences_refresh_http_off_main_thread(qapp, pump_page):
    """：下拉元数据与列表合并进同一次并行取数，主线程零 HTTP。"""
    from app.gui.experiences import ExperiencesPage

    api = _ExpRecApi()
    page = ExperiencesPage(api)
    try:
        page.resize(1200, 800)
        page.refresh()
        assert pump_page(page, qapp), "后台取数未在超时内完成"
        assert api.calls
        assert not _on_main(api.calls), \
            f"主线程发生了 HTTP：{_on_main(api.calls)}（全部：{api.calls}）"
        # 首刷带下 meta：trunk 下拉已补齐
        assert page._trunk_combo.count() > 0
        assert page._list_layout.count() == 2  # 2 个 (类别, task) 组
    finally:
        page.deleteLater()


def test_experiences_second_refresh_reuses_cards(qapp, pump_page):
    """：数据未变 → 二次刷新卡片对象恒等。"""
    from app.gui.experiences import ExperiencesPage

    page = ExperiencesPage(_ExpRecApi())
    try:
        page.resize(1200, 800)
        page.refresh()
        assert pump_page(page, qapp)
        before = _layout_widgets(page._list_layout)
        assert len(before) == 2
        page.refresh()
        assert pump_page(page, qapp)
        after = _layout_widgets(page._list_layout)
        assert [id(w) for w in after] == [id(w) for w in before]
    finally:
        page.deleteLater()


def test_experience_card_detail_opens_drawer_then_dialog(qapp, pump_page,
                                                         monkeypatch):
    """：卡片「详情」→ 统一下钻抽屉 → 「详情 / 演化」→ 详情对话框。

    此前两个 `_open_detail` 同名，后定义的对话框版把抽屉版整体遮蔽：卡片按钮
    被静默改行为、抽屉 46 行代码永不执行，且无任何测试覆盖这条路径。
    """
    import time

    from PySide6.QtWidgets import QPushButton

    from app.gui.experiences import ExperiencesPage

    opened: list[str] = []

    class _FakeDialog:
        def __init__(self, api, rec, parent=None, on_done=None):
            opened.append("dialog")
            self.rec = rec
            self._on_done = on_done

        def exec(self):
            opened.append("exec")
            return 0

        def deleteLater(self):
            pass

    monkeypatch.setattr("app.gui.experience_detail.ExperienceDetailDialog",
                        _FakeDialog)

    page = ExperiencesPage(_ExpRecApi())
    try:
        page.resize(1200, 800)
        page.refresh()
        assert pump_page(page, qapp)

        def spin(n=8):
            for _ in range(n):
                qapp.processEvents()
                time.sleep(0.01)

        # 1. 点卡片「详情」→ 统一下钻抽屉开出（修前 _drawer 恒为 None：
        # 对话框版同名遮蔽，卡片按钮直达对话框）
        btns = [b for b in page.findChildren(QPushButton) if b.text() == "详情"]
        assert btns, "卡片上没有「详情」按钮"
        btns[0].click()
        spin()
        assert page._drawer is not None, "卡片详情没进抽屉（_drawer 未被创建）"
        assert page._drawer._kind == "experience"
        assert opened == [], "卡片详情应进抽屉，不该直达对话框"

        # 2. 抽屉操作槽点「详情 / 演化」→ 详情对话框
        act = [b for b in page._drawer.findChildren(QPushButton)
               if b.text() == "详情 / 演化"]
        assert act, "抽屉操作槽里没有「详情 / 演化」按钮"
        act[0].click()
        spin()
        assert opened == ["dialog", "exec"], f"对话框未按预期打开：{opened}"
    finally:
        page.deleteLater()


# ---------- 3. 我的方法页 ----------

_SKILL_MD = ("# 研发 / 工程实践 · playbook\n\n"
             "> name: 构建报错排查\n> version: 2\n> confidence: high\n"
             "> source_exps: e1,e2\n\n"
             "## 标准流程\n1. 先看第一条报错\n\n"
             "## 成功要点\n- 最小可运行版本优先\n")


class _MethodRecApi(_DeadApi):
    """方法页桩：记录取数线程；1 份方法 + 2 条待总结经验。"""

    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8101")
        self.calls: list[tuple[str, str]] = []

    def _note(self, name: str) -> None:
        self.calls.append((name, threading.current_thread().name))

    def experiences(self, trunk=None, category=None, agent=None, q=None,
                    include_distilled=True, limit=300):
        self._note("experiences")
        return {"items": [
            {"id": "e1", "trunk": "研发", "category": "工程实践",
             "task": "构建报错", "distilled": False, "G": 0.6},
            {"id": "e2", "trunk": "研发", "category": "工程实践",
             "task": "构建报错2", "distilled": False, "G": 0.6},
        ]}

    def skills(self):
        self._note("skills")
        return {"items": [{"trunk": "研发", "category": "工程实践",
                           "name": "构建报错排查",
                           "content_source": "model",
                           "generated_at": "2026-09-19T00:00:00Z"}]}

    def read_skill(self, trunk, category):
        self._note("read_skill")
        return {"md": _SKILL_MD}

    def skill_agents(self, trunk, category):
        self._note("skill_agents")
        return {"agents": [{"agent": "codex", "count": 2}]}


def test_methods_refresh_http_off_main_thread(qapp, pump_page):
    """：经验 + 方法列表 + 各方法正文都在工作线程取，主线程零 HTTP。"""
    from app.gui.methods import MethodsPage

    api = _MethodRecApi()
    page = MethodsPage(api)
    try:
        page.resize(1200, 800)
        page.refresh()
        assert pump_page(page, qapp), "后台取数未在超时内完成"
        assert api.calls
        assert not _on_main(api.calls), \
            f"主线程发生了 HTTP：{_on_main(api.calls)}（全部：{api.calls}）"
        # 方法卡 + 待总结区都落地
        assert page._cards_lay.count() == 1
        assert page._pending_lay.count() == 1
    finally:
        page.deleteLater()


def test_methods_second_refresh_reuses_cards(qapp, pump_page):
    """：方法卡与待总结卡按 sig 复用，二次刷新对象恒等。"""
    from app.gui.methods import MethodsPage

    page = MethodsPage(_MethodRecApi())
    try:
        page.resize(1200, 800)
        page.refresh()
        assert pump_page(page, qapp)
        cards_before = _layout_widgets(page._cards_lay)
        pend_before = _layout_widgets(page._pending_lay)
        page.refresh()
        assert pump_page(page, qapp)
        assert [id(w) for w in _layout_widgets(page._cards_lay)] == \
            [id(w) for w in cards_before]
        assert [id(w) for w in _layout_widgets(page._pending_lay)] == \
            [id(w) for w in pend_before]
    finally:
        page.deleteLater()


# ---------- 4. 导出页 ----------

class _ExportRecApi(_DeadApi):
    """导出页桩：记录取数线程。"""

    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8101")
        self.calls: list[tuple[str, str]] = []

    def _note(self, name: str) -> None:
        self.calls.append((name, threading.current_thread().name))

    def experiences(self, trunk=None, category=None, agent=None, q=None,
                    include_distilled=True, limit=300):
        self._note("experiences")
        return {"items": [
            {"id": "e1", "trunk": "研发", "category": "工程实践",
             "task": "构建报错", "G": 0.6},
        ]}

    def skills(self):
        self._note("skills")
        return {"items": [{"trunk": "研发", "category": "工程实践",
                           "name": "构建报错排查"}]}


def test_export_build_has_no_main_thread_http(qapp):
    """：导出页 `_build()` 期不再取数（原主线程 experiences+skills）。"""
    from app.gui.export_page import ExportPage

    api = _ExportRecApi()
    page = ExportPage(api)
    try:
        page.resize(1200, 800)
        qapp.processEvents()
        assert api.calls == [], f"_build() 不应发请求，实际：{api.calls}"
    finally:
        page.deleteLater()


def test_export_dialog_fetch_off_main_thread(qapp, monkeypatch):
    """：打开「数据导出」弹层的取数走后台线程，表单在主线程落地。"""
    from app.gui.export_page import ExportPage

    api = _ExportRecApi()
    page = ExportPage(api)
    try:
        landed: dict = {}
        orig = page._build_export_section

        def spy(trunks, cats, name_map=None):
            landed["thread"] = threading.current_thread().name
            return orig(trunks, cats, name_map)

        monkeypatch.setattr(page, "_build_export_section", spy)
        monkeypatch.setattr(QDialog, "exec", lambda self: 0)  # 模态立即返回

        page._show_data_export()
        deadline = 5.0
        import time
        end = time.monotonic() + deadline
        while time.monotonic() < end and "thread" not in landed:
            qapp.processEvents()
            time.sleep(0.005)

        assert "thread" in landed, "导出表单未落地（后台取数或渲染失败）"
        assert landed["thread"] == threading.main_thread().name, \
            "表单应在主线程渲染"
        assert api.calls, "打开弹层应触发取数"
        assert not _on_main(api.calls), \
            f"主线程发生了 HTTP：{_on_main(api.calls)}（全部：{api.calls}）"
    finally:
        page.deleteLater()