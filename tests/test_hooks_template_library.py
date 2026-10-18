"""Hooks 页「规则模板库」的护栏（拆分前的必要前置，原先是零覆盖区块）。

拆 `app/gui/hooks_page.py` 的模板库（原 L1877-2138）为独立模块之前，先把它的
行为钉住。分两层：

1. **纯逻辑层**（`_tpl_matches` 四维筛选）——不需要 Qt，跑裸实例即可，最快；
2. **渲染/交互层**——用 qapp + 继承 `OfflineApi` 的桩驱动真实页面，锁
   「分类切换 / 过滤生效 / 导入转发」三条对外可见行为。

桩一律继承 `conftest.OfflineApi`（规矩：不许直挂 `LocalApi`，否则漏覆写的方法
会真打到 8101）。
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApiError  # noqa: E402
from app.gui.hooks_page import HooksPage  # noqa: E402
from conftest import OfflineApi  # noqa: E402


# ---------- 1. 纯逻辑：四维筛选 ----------

def _bare_page(f_state: dict | None = None) -> HooksPage:
    """不跑 __init__ 的裸实例——只测纯逻辑，避开 QWidget 构造开销。"""
    page = HooksPage.__new__(HooksPage)
    page._f_state = f_state or {"pri": "all", "tag": "all", "q": ""}
    return page


_TPL = {
    "id": "tpl1", "name": "部署前检查", "description": "部署前跑测试",
    "keywords": ["部署", "CI"], "tags": ["工作流与流程"], "priority": "p1",
    "trigger": "manual", "text": "部署前跑完整测试",
}


def test_default_state_matches_everything():
    """全 all + 空关键词 → 不过滤（默认态必须能看到全部模板）。"""
    assert _bare_page()._tpl_matches(_TPL) is True


@pytest.mark.parametrize("pri,hit", [
    ("p1", True), ("p0", False), ("all", True),
])
def test_priority_dimension(pri, hit):
    assert _bare_page({"pri": pri, "tag": "all", "q": ""})._tpl_matches(_TPL) is hit


@pytest.mark.parametrize("tag,hit", [
    ("工作流与流程", True), ("安全与合规", False), ("all", True),
])
def test_tag_dimension(tag, hit):
    """标签维度必须精确匹配 tags 列表成员，不是子串。"""
    assert _bare_page({"pri": "all", "tag": tag, "q": ""})._tpl_matches(_TPL) is hit


@pytest.mark.parametrize("q,hit", [
    ("部署", True),          # 命中 name
    ("跑测试", True),        # 命中 description
    ("ci", True),            # 命中 keywords，且大小写不敏感
    ("工作流", True),        # 命中 tags
    ("不存在的东西", False),
    ("", True),              # 空 = 不过滤
])
def test_keyword_dimension(q, hit):
    """关键词四路合并（name/description/keywords/tags）+ 大小写不敏感。"""
    assert _bare_page({"pri": "all", "tag": "all", "q": q})._tpl_matches(_TPL) is hit


def test_dimensions_are_anded():
    """三个维度是「与」关系：单维命中不够，任一不满足即出局。"""
    page = _bare_page({"pri": "p0", "tag": "工作流与流程", "q": "部署"})
    assert page._tpl_matches(_TPL) is False, "优先级不符就应被滤掉"


def test_missing_fields_do_not_crash():
    """脏数据（缺 tags/keywords/priority）不得抛——模板来自 JSON，容错是硬要求。"""
    for tpl in ({}, {"name": "x"}, {"priority": None, "tags": None},
                {"keywords": None}, {"tags": ["a"], "keywords": ["b"]}):
        assert isinstance(_bare_page()._tpl_matches(tpl), bool)


# ---------- 2. 渲染 / 交互 ----------

class _TplApi(OfflineApi):
    """只桩 templates 相关；其余一律继承 OfflineApi 的"立即失败"。"""

    def __init__(self, categories=None, import_result=None):
        self._categories = categories if categories is not None else [
            {"label_key": "安全与合规", "templates": [
                {"id": "tpl1", "name": "部署前检查", "description": "部署前跑测试",
                 "keywords": ["部署"], "tags": ["工作流与流程"], "priority": "p1",
                 "trigger": "manual", "text": "部署前跑完整测试"},
                {"id": "tpl2", "name": "禁删库", "description": "红线",
                 "keywords": ["drop"], "tags": ["安全与合规"], "priority": "p0",
                 "trigger": "hard-hook", "text": "绝不删库"},
            ]},
            {"label_key": "效率工具", "templates": [
                {"id": "tpl3", "name": "日报助手", "description": "汇总日报",
                 "keywords": [], "tags": ["效率工具"], "priority": "p2",
                 "trigger": "smart", "text": "汇总今日改动"},
            ]},
        ]
        self.imported = []
        self._import_result = import_result or {"ok": True}

    def templates(self, lang):
        return {"categories": self._categories}

    def import_template(self, template_id, trig_value, lang):
        self.imported.append((template_id, (trig_value, lang)))
        return self._import_result

    # HooksPage.refresh 会并行取一堆东西，未桩的交给 OfflineApi 失败即可；
    # 但模板区自己只依赖 templates，故这里只保证它不抛。
    def rules(self):
        return {"items": [], "budget_used": 0, "budget": 400, "stale_days": 30}

    def rule_agents(self):
        return {"agents": []}

    def hooks_admin_overview(self):
        return {}

    def capture_status(self):
        return {}


@pytest.fixture
def tpl_page(qapp):
    from tests.conftest import pump_until

    api = _TplApi()
    page = HooksPage(api)
    page.resize(1200, 800)
    page.refresh()
    assert pump_until(lambda: not page._fetches, qapp), "后台取数未收尾"
    qapp.processEvents()
    yield api, page
    page.deleteLater()


def test_templates_loaded_into_holder(tpl_page):
    """模板数据落进 _tpl_holder，且首屏渲染出列表项。"""
    _api, page = tpl_page
    assert len(page._tpl_holder) == 2, "两个类目都应加载"
    assert page._tpl_list_lay.count() >= 1, "模板未渲染"


def test_priority_filter_hides_nonmatching(tpl_page):
    """切到 p0 只剩 p0 模板——证明筛选真的接到渲染上（不只是纯函数对）。"""
    _api, page = tpl_page
    page._set_pri_filter("p0")
    page._render_tpl_list()
    names = [_tpl_name(w) for w in _labels(page._tpl_list_lay)]
    assert any("禁删库" in n for n in names)
    assert not any("部署前检查" in n for n in names)


def test_empty_filter_result_shows_placeholder(tpl_page):
    """筛到空不能留下空白区，要有「没有匹配的模板」占位（用户可见反馈）。"""
    _api, page = tpl_page
    page._f_state["q"] = "绝对不存在的关键词xyz"
    page._render_tpl_list()
    texts = _labels(page._tpl_list_lay)
    assert any("没有匹配的模板" in x for x in texts), texts


def test_category_switch_renders_that_category(tpl_page):
    """切类目后列表换成该类目的模板（第二个类目只有 1 条）。"""
    _api, page = tpl_page
    page._pick_category(1)
    page._render_tpl_list()
    texts = _labels(page._tpl_list_lay)
    assert any("日报助手" in x for x in texts), texts
    assert not any("部署前检查" in x for x in texts), texts


def test_do_import_forwards_to_api(tpl_page):
    """点导入 → 调 api.import_template 并带上模板 id 与档位（对外契约）。"""
    api, page = tpl_page
    page._do_import({"id": "tpl1", "name": "部署前检查"}, "manual")
    # 导入改后台执行（原同步 15s 跑 UI 线程会冻结），
    # 断言前等 worker 落定（仓库范式：_wait_inflight）。
    page._wait_inflight()
    assert api.imported, "import_template 未被调用"
    tid, args = api.imported[0]
    assert tid == "tpl1", tid
    assert args[0] == "manual", "第一个位置参数应是触发档位"
    assert args[1] == i18n.current_language(), "第二个位置参数应是当前语言"


def test_templates_api_failure_does_not_break_page(tpl_page):
    """模板接口失败 → 显示「模板库加载失败」且不崩（fail-open）。"""
    _api, page = tpl_page
    assert page._render_templates(None) is False
    texts = _labels(page._tpl_list_lay)
    assert any("模板库加载失败" in x for x in texts), texts


def test_render_templates_resets_category(tpl_page):
    """重载模板后类目回到第一个（换语言/刷新后不该停留在用户上次选的类目）。"""
    _api, page = tpl_page
    page._pick_category(1)
    assert page._cat_state[0] == 1
    assert page._render_templates({"categories": [
        {"label_key": "k", "templates": [
            {"id": "t9", "name": "新模板", "description": "", "keywords": [],
             "tags": [], "priority": "p2", "trigger": "smart", "text": "x"},
        ]},
    ]}) is True
    assert page._cat_state[0] == 0, "类目应复位到第一个"
    texts = _labels(page._tpl_list_lay)
    assert any("新模板" in x for x in texts), texts


# ---------- 小工具：从布局里递归取文本 ----------

def _labels(lay):
    """递归收集布局/控件树里的 QLabel 文本（模板行是嵌套结构）。"""
    from PySide6.QtWidgets import QLabel, QLayout, QWidget

    out = []

    def _walk(item):
        w = item.widget() if item is not None else None
        if w is None and isinstance(item, QLayout):
            for i in range(item.count()):
                _walk(item.itemAt(i))
            return
        if isinstance(w, QLabel):
            out.append(w.text())
        if isinstance(w, QWidget) and w.layout() is not None:
            for i in range(w.layout().count()):
                _walk(w.layout().itemAt(i))

    for i in range(lay.count()):
        _walk(lay.itemAt(i))
    return out


def _tpl_name(text):
    return text
