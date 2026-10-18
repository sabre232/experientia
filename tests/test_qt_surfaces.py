"""P0/P1 新 GUI 面回归。

沿用仓库手动 QApplication 模式（不引 pytest-qt 依赖）：
- 首页账本三数字 / 刚发现的坑洞察卡 / 双档卡（本机已可用 / 接入模型后更强） /
  搜索区与 chips / 空态口径；
- 经验库「未提炼片段」灰标区；踩坑 tab 的 T1 兜底；
- 三处 AI 按钮的前端门禁（旧 `guide_connect_ai` / 新 `require_model` 两口径；非绑定
  方法直调，不弹窗不建页——headless 下模态框必挂，绝不真实 exec）；
- 会话下钻抽屉渲染。
"""

import os
import time
import types

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (QApplication, QLabel,  # noqa: E402
                               QPushButton, QTextBrowser)

from app.gui.api_client import LocalApi  # noqa: E402
from app.gui.page_base import PageBase  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from app.gui import i18n
    i18n.load_catalog("zh")
    return QApplication.instance() or QApplication([])


LEDGER = {"sessions": 6, "rounds": 12, "tokens": 900, "cost_usd_est": 1.75,
          "cost_priced_share": 1.0, "rule_cards": 3, "rule_injectable": 2,
          "pending_fragments": 1}
RULE_ITEMS = [
    {"id": "r1", "rule_kind": "retry_pair", "task": "cmd:npm run build",
     "state": "ERR! Module not found", "action": "fix:retry-with-changed-args",
     "count": 3, "sessions": 3, "G": 0.55, "injectable": True,
     "ts": "2026-09-19T00:00:00Z", "agent": "codex", "session_id": "s1",
     "project": "F:/demo"},
    {"id": "r2", "rule_kind": "error_sig", "task": "sig:boom",
     "state": "boom sig", "action": "recurring-error-signature",
     "count": 2, "sessions": 2, "G": 0.4, "injectable": False,
     "ts": "2026-09-19T00:00:00Z", "agent": "codex", "session_id": "s2",
     "project": "F:/demo"},
]


class FakeApi(LocalApi):
    """按路径返回 canned 数据；记录被调用的路径（门禁断言用）。"""

    def __init__(self, model_connected=False, search_items=None,
                 ledger_data=None):
        super().__init__(base_url="http://fake")
        self.calls = []
        self.model_connected = model_connected
        self.search_items = search_items or []
        self.ledger_data = ledger_data or dict(LEDGER)

    def _request(self, method, path, json=None, params=None, timeout=None):
        self.calls.append(path)
        p = path.split("?")[0]
        if p == "/api/status":
            return {"agents": {"codex": {"running": True}}}
        if p == "/api/models":
            routes = ([{"name": "m", "endpoint": "http://x/v1"}]
                      if self.model_connected else [{"name": "m", "endpoint": ""}])
            return {"routes": routes}
        if p == "/api/capture/status":
            return {"agents": {"codex": {"hits_24h": 9}}}
        if p == "/api/growth":
            return {"affinity": {}, "cumulative": {}, "heatmap": {}}
        if p == "/api/insights":
            return {"items": [], "total": 0}
        if p == "/api/experience_drafts":
            return {"count": 0, "items": []}
        if p == "/api/ledger":
            return dict(self.ledger_data)
        if p == "/api/rule-cards":
            return {"items": list(RULE_ITEMS), "total": len(RULE_ITEMS)}
        if p == "/api/pending-fragments":
            return {"items": [{"agent": "workbuddy", "session_id": "w1",
                               "snippets": ["不对，重来一次"], "trunk": "编程",
                               "category": "构建", "ts": "2026-09-19T00:00:00Z"}]}
        if p == "/api/search":
            return {"items": list(self.search_items)}
        if p == "/api/experiences":
            return {"items": [], "count": 0}
        if p == "/api/skills":
            return {"items": []}
        if p == "/api/failure-modes":
            return {"items": []}
        return {}


def _spin(app, n=10):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.02)


def _mk(page, app):
    page.resize(1000, 900)
    page.show()  # 离屏也必须 show：未经历布局的控件 findChildren 尺寸不可信
    page.refresh()
    _spin(app)
    return page


# ---------- 首页：账本 / 洞察卡 / 锁定卡 / 空态口径 ----------

def test_home_ledger_and_pitfalls_render(qapp, monkeypatch):
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")  # 关数字滚动 → 同步断言
    from app.gui.home import HomePage
    h = _mk(HomePage(FakeApi()), qapp)
    # 花费格已下线（只接本地模型时结构性恒为 0.00），账本行只剩三格
    assert "cost" not in h._stat_values
    assert h._stat_values["sessions"].text() == "6"
    assert h._stat_values["rounds"].text() == "12"
    assert h._stat_values["pitfalls"].text() == "3"
    assert h._pitfalls_card.isVisible()
    texts = [l.text() for l in h._pitfalls_card.findChildren(QLabel)]
    assert any("npm run build" in x for x in texts)
    assert any("复现 3 次" in x for x in texts)


def test_home_tier_cards_visibility_tracks_model(qapp):
    """双档（旧「锁定卡」已废）：无模型时两档都亮——先报本机产出，
    再给「接模型更强」的邀约；接入后增强档收起，本机档照常。"""
    from app.gui.home import HomePage
    off = _mk(HomePage(FakeApi(model_connected=False)), qapp)
    assert off._local_card.isVisible()
    assert off._enhance_card.isVisible()
    on = _mk(HomePage(FakeApi(model_connected=True)), qapp)
    assert on._local_card.isVisible()
    assert not on._enhance_card.isVisible()


def test_home_empty_state_only_without_sessions(qapp):
    """有会话但零经验 = 正常账本形态，不得演成空态（第一印象核心）。"""
    from app.gui.home import HomePage
    h = _mk(HomePage(FakeApi()), qapp)
    assert not h._empty_card.isVisible()
    zero = _mk(HomePage(FakeApi(search_items=[],
                                ledger_data=dict(LEDGER, sessions=0, rounds=0,
                                                 cost_usd_est=0.0,
                                                 rule_cards=0))),
               qapp)
    assert zero._empty_card.isVisible()


# ---------- 首页：搜索区与 chips ----------

def test_home_search_renders_results(qapp):
    from app.gui.home import HomePage
    items = [{"agent": "codex", "session_id": "s1", "score": 2.0,
              "snippet": "命中【conftest】的片段", "project": "F:/demo",
              "started_at": "2026-09-15T00:00:00Z"}]
    h = _mk(HomePage(FakeApi(search_items=items)), qapp)
    h._search_tf.setText("conftest")
    h._do_search()
    _spin(qapp, 20)
    assert h._search_card.isVisible()
    texts = [l.text() for l in h._search_card.findChildren(QLabel)]
    assert any("conftest" in x for x in texts)
    assert any("codex" in x for x in texts)


def test_home_search_empty_message(qapp):
    from app.gui.home import HomePage
    h = _mk(HomePage(FakeApi(search_items=[])), qapp)
    h._run_search("不存在词")
    _spin(qapp, 20)
    assert h._search_card.isVisible()
    texts = [l.text() for l in h._search_card.findChildren(QLabel)]
    assert any("没有找到" in x for x in texts)


def test_home_query_chips_from_real_sig(qapp):
    """chips 取真实高频报错签名（error_sig 卡 state），标签走本地语言外壳、一点即搜。"""
    from app.gui.home import HomePage
    h = _mk(HomePage(FakeApi()), qapp)
    assert h._chip_q_holder.isVisible()
    labels = [b.text() for b in h._chip_q_holder.findChildren(QPushButton)]
    assert any("boom sig" in x for x in labels)   # r2 的 state（r1 非 error_sig 不出 chip）
    assert any(x.startswith("常见报错") for x in labels)  # 本地语言外壳
    h._chip_q_lay.itemAt(0).widget().click()
    _spin(qapp, 20)
    assert h._search_card.isVisible()    # chip 点击即触发搜索


# ---------- 经验库片段区 / 踩坑 tab ----------

def test_experiences_fragments_section(qapp):
    from app.gui.experiences import ExperiencesPage
    pg = _mk(ExperiencesPage(FakeApi()), qapp)
    assert pg._frag_section.isVisible()
    texts = [l.text() for l in pg._frag_section.findChildren(QLabel)]
    assert any("不对，重来一次" in x for x in texts)
    assert any("不是经验" in x for x in texts)   # 定位声明必须在场


def test_failure_modes_t1_fallback(qapp):
    from app.gui.failure_modes import FailureModesPage
    pg = _mk(FailureModesPage(FakeApi()), qapp)
    texts = [l.text() for l in pg.findChildren(QLabel)]
    assert any("npm run build" in x for x in texts)  # 不再恒空
    assert any("记住了" in x for x in texts)          # injectable 状态词


# ---------- 三处 AI 按钮前端门禁（非绑定直调：不建页不弹窗） ----------

def _gated_self():
    calls = []
    # 生成类入口统一走 require_model（起旧门禁 guide_connect_ai 已删除，
    # 各页均已迁移）。桩返回 False = 无模型，动作应被拦下。
    ns = types.SimpleNamespace(
        require_model=lambda *a, **k: (calls.append("gate"), False)[1],
        api=FakeApi(),
        _set_status=lambda *a, **k: None,
        set_status=lambda *a, **k: None,
        run_async=lambda *a, **k: calls.append("async"),
    )
    return ns, calls


def test_hooks_explain_gated():
    from app.gui.hooks_page import HooksPage
    ns, calls = _gated_self()
    HooksPage._entry_explain(ns, "codex", "e1", QLabel(), None)
    assert calls == ["gate"]  # 门禁拦截后不得再走 run_async


def test_inject_optimize_gated():
    from app.gui.inject_preview import InjectPreviewPage
    ns, calls = _gated_self()
    InjectPreviewPage._optimize_item(
        ns, {"id": "x", "effective_text": "t"}, QPushButton())
    assert calls == ["gate"]


def test_skill_generate_gated():
    from app.gui.skill_organize import SkillOrganizePage
    ns, calls = _gated_self()
    SkillOrganizePage._generate(ns, "t", "c", False)
    assert calls == ["gate"]


# ---------- 会话下钻抽屉（构造断言，不 exec） ----------

def _drawer_texts(d) -> str:
    """抽屉全部可见文本。

     起消息正文由 ``txt``（QLabel）改为 ``md_view``（QTextBrowser 富文本），
    只收 QLabel 会漏掉对话正文——两处都收，护栏语义（用户回合在 / 噪音被滤）不变。
    """
    return " ".join([l.text() for l in d.findChildren(QLabel)]
                    + [b.toPlainText() for b in d.findChildren(QTextBrowser)])


def test_session_drawer_renders(qapp):
    from app.gui.session_drawer import SessionDrawer
    d = SessionDrawer({"agent": "codex", "session_id": "abcdef1234",
                       "project": "F:/demo", "started_at": "2026-09-15T00:00:00Z",
                       "model": "claude-sonnet", "req_count": 3,
                       "correction_hits": 1, "trunk": "编程", "category": "构建",
                       "user_messages": ["跑一下测试"],
                       "assistant_messages": ["好的"],
                       "events": [{"t": "2026-09-15T00:00:01Z", "tool": "Bash",
                                   "cmd": "pytest -q", "ex": 1, "e": 1,
                                   "sig": "FAILED"}]}, parent=None)
    texts = [l.text() for l in d.findChildren(QLabel)]
    assert any("pytest -q" in x for x in texts)
    assert any("FAILED" in x for x in texts)
    d.close()


def test_session_drawer_filters_system_noise(qapp):
    """设计走查 blocker：环境上下文等系统注入块不得倒给用户。"""
    from app.gui.session_drawer import SessionDrawer, _is_system_noise
    assert _is_system_noise("<environment_context>\n<cwd>C:/x</cwd>")
    assert not _is_system_noise("帮我改一下配置")
    d = SessionDrawer({"agent": "codex", "session_id": "abc12345",
                       "req_count": 2, "user_messages": [
                           "<environment_context><cwd>C:/x</cwd></environment_context>",
                           "真实的一句话"],
                       "assistant_messages": ["好的"], "events": []}, parent=None)
    texts = _drawer_texts(d)
    assert "environment_context" not in texts and "cwd" not in texts
    assert "真实的一句话" in texts
    d.close()


def test_session_drawer_shows_user_turns(qapp):
    """回归护栏：多轮会话里"你"的消息不能被切掉（曾误把用户+AI 拼接取尾=全 AI）。"""
    from app.gui.session_drawer import SessionDrawer
    d = SessionDrawer({"agent": "codex", "session_id": "abc12345", "req_count": 3,
                       "user_messages": ["第一句", "第二句", "第三句"],
                       "assistant_messages": ["回一", "回二", "回三"],
                       "events": []}, parent=None)
    texts = _drawer_texts(d)
    assert "第一句" in texts and "第三句" in texts   # 用户回合在
    assert "回三" in texts                            # AI 回合也在
    d.close()
