"""记忆引擎升级的**界面**出口测试（P0-3 详情对话框 / P1-1 意图区）。

这两处此前只有 API 侧测试：接口对了，界面却可能不显示、按钮点了没反应、
服务端返回的原因被吞掉。本文件钉的是界面行为三件事：

1. **看得到**：有证据就显示引文与来源、有链就显示版本、没料就整块不出现；
2. **点了有反应**：「不再提醒」「回到这版」「忘了这条」真的打到对应接口；
3. **失败不吞**：服务端原因原样显示，页面不假装成功。

离屏渲染（QT_QPA_PLATFORM=offscreen），零网络（桩 API 立即返回，不发请求）。
"""

from __future__ import annotations


import pytest

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

pytest.importorskip("PySide6")

from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApiError  # noqa: E402
from conftest import OfflineApi as _BaseApi  # noqa: E402
from conftest import pump_until  # noqa: E402


def _labels(w) -> list[str]:
    return [l.text() for l in w.findChildren(QLabel)]


def _buttons(w) -> list[QPushButton]:
    return list(w.findChildren(QPushButton))


def _btn_texts(w) -> list[str]:
    return [b.text() for b in _buttons(w)]


# ---------- 经验详情对话框（P0-3） ----------

REC = {
    "id": "e1", "agent": "codebuddy", "ts": "2026-10-18T01:02:03Z",
    "trunk": "前端", "category": "页面性能", "session_id": "s1",
    "evidence": {"quote": "先测 Lighthouse 基线", "source": "session"},
}

CHAIN_2 = {"chain": {
    "current": {"revision": 2, "action": "图片转 AVIF 并加懒加载"},
    "revisions": [{"revision": 1, "action": "压缩图片"}], "depth": 2}}
CHAIN_1 = {"chain": {
    "current": {"revision": 1, "action": "压缩图片"},
    "revisions": [], "depth": 1}}


class _DetailApi(_BaseApi):
    """详情对话框桩：五个接口全记账，按需抛 LocalApiError。

    `op_error` 让三个写操作（回滚 / 遗忘 / 恢复）统一失败——失败回显是
    「失败不得静默」这条设计承诺的落点，此前三个分支都无测试。
    """

    def __init__(self, chain=None, chain_error=None, op_error=None):
        super().__init__(base_url="http://fake")
        self.chain = CHAIN_1 if chain is None else chain
        self.chain_error = chain_error
        self.op_error = op_error
        self.calls: list[tuple] = []

    def experience_chain(self, exp_id):
        self.calls.append(("chain", exp_id))
        if self.chain_error:
            raise self.chain_error
        return self.chain

    def session_view(self, agent, session_id):
        self.calls.append(("session", agent, session_id))
        return {"agent": agent, "session_id": session_id, "turns": []}

    def rollback_experience(self, exp_id, revision):
        self.calls.append(("rollback", exp_id, revision))
        if self.op_error:
            raise self.op_error
        return {"revision": revision}

    def forget_experience(self, exp_id, hard=False):
        self.calls.append(("forget", exp_id, bool(hard)))
        if self.op_error:
            raise self.op_error
        return {}

    def unforget_experience(self, exp_id):
        self.calls.append(("unforget", exp_id))
        if self.op_error:
            raise self.op_error
        return {}


def _open_detail(qapp, api, rec=None):
    from app.gui.experience_detail import ExperienceDetailDialog

    dlg = ExperienceDetailDialog(api, dict(rec or REC))
    # 演化链改后台取数——构造返回时链可能还在飞，泵到收尾再断言
    assert pump_until(lambda: not dlg._workers, qapp), "取链线程未收尾"
    return dlg


def test_detail_shows_quote_and_source(qapp):
    """有证据 → 引文 + 来源标签 +「看原话」都在界面上。"""
    api = _DetailApi()
    dlg = _open_detail(qapp, api)
    try:
        texts = _labels(dlg)
        assert any("先测 Lighthouse 基线" in t for t in texts)
        assert "会话原话" in texts          # 来源标签（字典值，曾漏翻）
        assert "看原话" in _btn_texts(dlg)
    finally:
        dlg.deleteLater()


def test_detail_says_so_when_no_quote(qapp):
    """没证据 → 如实说"没有原话证据"，不编造、也不留空标签。"""
    rec = dict(REC, evidence=None, session_id="")
    dlg = _open_detail(qapp, _DetailApi(), rec)
    try:
        texts = _labels(dlg)
        assert any("这条经验没有带原话证据" in t for t in texts)
        assert "会话原话" not in texts
        assert "看原话" not in _btn_texts(dlg)
    finally:
        dlg.deleteLater()


def test_detail_lists_revisions_with_rollback(qapp):
    """改过 → 列出历史版本，每版一个「回到这版」。"""
    dlg = _open_detail(qapp, _DetailApi(chain=CHAIN_2))
    try:
        texts = _labels(dlg)
        assert any("共 2 版" in t for t in texts)
        assert "当前" in texts               # 头版本标记
        assert "图片转 AVIF 并加懒加载" in " ".join(texts)
        assert "回到这版" in _btn_texts(dlg)
    finally:
        dlg.deleteLater()


def test_detail_says_first_version(qapp):
    """没改过 → 说清楚是第 1 版，不摆一排空按钮。"""
    dlg = _open_detail(qapp, _DetailApi(chain=CHAIN_1))
    try:
        assert any("还没被改过" in t for t in _labels(dlg))
        assert "回到这版" not in _btn_texts(dlg)
    finally:
        dlg.deleteLater()


def test_detail_rollback_confirmed_calls_api(qapp, monkeypatch):
    monkeypatch.setattr("app.gui.experience_detail.confirm_dialog",
                        lambda *a, **k: True)
    api = _DetailApi(chain=CHAIN_2)
    dlg = _open_detail(qapp, api)
    try:
        dlg._rollback(1)
        assert ("rollback", "e1", 1) in api.calls
        assert dlg._status.text() == "已回到第 1 版"
    finally:
        dlg.deleteLater()


def test_detail_rollback_aborted_without_confirm(qapp, monkeypatch):
    monkeypatch.setattr("app.gui.experience_detail.confirm_dialog",
                        lambda *a, **k: False)
    api = _DetailApi(chain=CHAIN_2)
    dlg = _open_detail(qapp, api)
    try:
        dlg._rollback(1)
        assert [c for c in api.calls if c[0] == "rollback"] == []
    finally:
        dlg.deleteLater()


def test_detail_soft_forget_keeps_it_recoverable(qapp):
    api = _DetailApi()
    dlg = _open_detail(qapp, api)
    try:
        dlg._forget(False)
        assert ("forget", "e1", False) in api.calls
        assert "可从回收恢复" in dlg._status.text()
    finally:
        dlg.deleteLater()


def test_detail_hard_delete_needs_second_confirm(qapp, monkeypatch):
    api = _DetailApi()
    dlg = _open_detail(qapp, api)
    try:
        monkeypatch.setattr("app.gui.experience_detail.confirm_dialog",
                            lambda *a, **k: False)
        dlg._forget(True)
        assert [c for c in api.calls if c[0] == "forget"] == []
        monkeypatch.setattr("app.gui.experience_detail.confirm_dialog",
                            lambda *a, **k: True)
        dlg._forget(True)
        assert ("forget", "e1", True) in api.calls
        assert dlg._status.text() == "已彻底删除"
    finally:
        dlg.deleteLater()


def test_detail_shows_server_reason_on_chain_failure(qapp):
    """取链失败：服务端原因原样显示，不吞、不假装没链。"""
    api = _DetailApi(chain_error=LocalApiError(404, "经验不存在"))
    dlg = _open_detail(qapp, api)
    try:
        assert any("读不到演化链：经验不存在" in t for t in _labels(dlg))
    finally:
        dlg.deleteLater()


def test_detail_see_original_opens_session(qapp, monkeypatch):
    """「看原话」→ 后台取那场会话再开抽屉（L11：点击期不卡主线程）。"""
    opened: list[dict] = []

    class _FakeDrawer:
        def __init__(self, data, parent=None):
            opened.append(data)

        def exec(self):
            return 0

        def deleteLater(self):
            pass  # 口径：exec 后释放（生产代码  M8 补上）

    monkeypatch.setattr("app.gui.session_drawer.SessionDrawer", _FakeDrawer)
    api = _DetailApi()
    dlg = _open_detail(qapp, api)
    try:
        btn = next(b for b in _buttons(dlg) if b.text() == "看原话")
        btn.click()
        assert pump_until(
            lambda: ("session", "codebuddy", "s1") in api.calls
            and not dlg._workers, qapp), "会话取数线程未收尾"
        assert opened and opened[0]["session_id"] == "s1"
        assert dlg._status.text() == ""  # 进行时提示已清
    finally:
        dlg.deleteLater()


def test_detail_soft_forget_then_restore(qapp):
    """软忘后出现「恢复」入口，点了真的撤消（L13：兑现"可从回收恢复"）。"""
    api = _DetailApi()
    dlg = _open_detail(qapp, api)
    try:
        dlg._forget(False)
        assert "可从回收恢复" in dlg._status.text()
        forget = next(b for b in _buttons(dlg) if b.text() == "忘了这条")
        hard = next(b for b in _buttons(dlg) if b.text() == "彻底删除")
        restore = next(b for b in _buttons(dlg) if b.text() == "恢复")
        assert forget.isHidden() and hard.isHidden(), "软忘后两个删除入口应收起"
        assert not restore.isHidden(), "恢复入口应现身"
        restore.click()
        assert ("unforget", "e1") in api.calls
        assert dlg._status.text() == "已恢复"
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize("op", ["rollback", "forget", "restore"])
def test_detail_operation_failure_shows_server_reason(qapp, monkeypatch, op):
    """三个写操作失败：当场说出服务端原因，界面不假装成功、也不关窗。

    设计承诺是「每个操作失败都把服务端原因原样显示，不静默吞」；静默失败
    最坏的形态是有副作用却无提示，用户会反复点。
    """
    monkeypatch.setattr("app.gui.experience_detail.confirm_dialog",
                        lambda *a, **k: True)
    api = _DetailApi(chain=CHAIN_2,
                     op_error=LocalApiError(500, "库写不进去"))
    dlg = _open_detail(qapp, api)
    try:
        if op == "rollback":
            dlg._rollback(1)
        elif op == "forget":
            dlg._forget(False)
        else:
            # 恢复只在「已忘」状态下出现：先成功软忘，再让 unforget 失败
            api.op_error = None
            dlg._forget(False)
            api.op_error = LocalApiError(500, "库写不进去")
            dlg._restore()

        assert {"rollback": "rollback", "forget": "forget",
                "restore": "unforget"}[op] in [c[0] for c in api.calls], \
            f"{op} 没打到接口"
        assert "库写不进去" in dlg._status.text()
        assert dlg.result() == 0, "失败时不许关窗"
        if op == "forget":
            assert dlg._btn_restore.isHidden(), "失败不该切到「已遗忘」形态"
    finally:
        dlg.deleteLater()


def test_detail_success_goes_to_caller_status_line(qapp, monkeypatch):
    """L10：成功回执经 on_done 交上层页面状态行，窗内不再重复写。

    本窗紧接着 accept() 就销毁，写在自己状态行上的文案用户看不到。
    """
    monkeypatch.setattr("app.gui.experience_detail.confirm_dialog",
                        lambda *a, **k: True)
    from app.gui.experience_detail import ExperienceDetailDialog

    got: list[str] = []
    api = _DetailApi(chain=CHAIN_2)
    dlg = ExperienceDetailDialog(api, dict(REC), on_done=got.append)
    assert pump_until(lambda: not dlg._workers, qapp), "取链线程未收尾"
    try:
        dlg._rollback(1)
        assert got == ["已回到第 1 版"]
        assert dlg._status.text() == ""
    finally:
        dlg.deleteLater()


def test_detail_see_original_without_session_does_nothing(qapp):
    """记录缺 agent/session_id：点「看原话」什么都不做，不打接口也不起线程。"""
    api = _DetailApi()
    dlg = _open_detail(qapp, api, dict(REC, agent="", session_id=""))
    try:
        dlg._open_session()
        assert not dlg._workers
        assert [c for c in api.calls if c[0] == "session"] == []
        assert dlg._status.text() == ""
    finally:
        dlg.deleteLater()


def test_detail_tolerates_non_dict_evidence(qapp):
    """证据字段形状坏了（不是 dict、是裸串）：仍当作没来源标签，不崩。"""
    dlg = _open_detail(qapp, _DetailApi(), dict(REC, evidence="早期格式的原话"))
    try:
        texts = _labels(dlg)
        assert any("早期格式的原话" in t for t in texts)
        assert "会话原话" not in texts, "拿不到 source 不该瞎标来源"
    finally:
        dlg.deleteLater()


def test_detail_close_waits_for_inflight_workers(qapp):
    """关窗前逐条等在飞取数线程（Qt 红线：运行中的 QThread 随对话框析构
    会直接 abort，无 Python 栈、极难查）。

    用哑对象代替真线程：这里钉的是「关窗先等」这条顺序，不拿线程调度做判据
    （计时型断言在 CI 上会抖）。等待抛错也不许卡住关窗。
    """
    dlg = _open_detail(qapp, _DetailApi())
    waited: list[int] = []

    class _Pending:
        def wait(self, ms):
            waited.append(ms)
            return True

    class _Boom:
        def wait(self, ms):
            raise RuntimeError("线程已结束")

    try:
        dlg._workers.extend([_Pending(), _Boom()])
        dlg.done(0)
        assert waited == [5000], "关窗前没等线程"
        assert dlg.result() == 0
    finally:
        dlg.deleteLater()


# ---------- 经验页 L6 意图区（P1-1） ----------

INTENTS = [
    {"id": "i1", "intent": "图片优化可以直接转 AVIF",
     "trunk": "前端", "category": "页面性能", "count": 3},
    {"id": "i2", "intent": "构建失败先清 node_modules",
     "trunk": "前端", "category": "构建", "count": 2},
]


class _PageApi(_BaseApi):
    """经验页桩：只喂意图，其余取数给空（意图是附加层，失败也不该报红）。"""

    def __init__(self, intents=None, raise_on_intents=False,
                 dismiss_error=None):
        super().__init__(base_url="http://fake")
        self.intents = INTENTS if intents is None else intents
        self.raise_on_intents = raise_on_intents
        self.dismiss_error = dismiss_error
        self.calls: list[tuple] = []

    def _request(self, method, path, json=None, params=None, timeout=None):
        p = path.split("?")[0]
        self.calls.append((method, p))
        if p == "/api/intentions" and method == "GET":
            if self.raise_on_intents:
                raise LocalApiError(500, "意图取不到")
            return {"items": self.intents, "count": len(self.intents)}
        if p.startswith("/api/intentions/") and p.endswith("/dismiss"):
            if self.dismiss_error:
                raise self.dismiss_error
            return {"message": "已忽略，不再提醒"}
        if p == "/api/experiences":
            return {"items": [], "count": 0}
        if p == "/api/experience-drafts":
            return {"count": 0, "items": []}
        if p == "/api/pending-fragments":
            return {"items": []}
        if p == "/api/models":
            return {"routes": []}
        # 未知路径显式炸掉：兜底 return {} 会把意外请求连数据一起吞了，
        # 页面打了没注册的接口也看不出来
        raise AssertionError(f"意外请求: {method} {p}")


def _open_page(qapp, pump_page, api):
    from app.gui.experiences import ExperiencesPage

    page = ExperiencesPage(api)
    page.resize(1000, 900)
    page.show()
    page.refresh()
    assert pump_page(page, qapp), "经验页后台取数未在超时内完成"
    return page


def test_intents_shown_with_meta(qapp, pump_page):
    api = _PageApi()
    page = _open_page(qapp, pump_page, api)
    try:
        assert page._intent_section.isVisibleTo(page)
        texts = _labels(page._intent_section)
        assert any("图片优化可以直接转 AVIF" in t for t in texts)
        assert any("出现过 3 次" in t for t in texts)
        assert any("前端/页面性能" in t for t in texts)
        assert _btn_texts(page._intent_section).count("不再提醒") == 2
    finally:
        page.deleteLater()


def test_intents_capped_at_five(qapp, pump_page):
    many = [{"id": f"i{n}", "intent": f"第 {n} 条意图", "trunk": "前端",
             "category": "构建", "count": 1} for n in range(7)]
    page = _open_page(qapp, pump_page, _PageApi(intents=many))
    try:
        assert _btn_texts(page._intent_section).count("不再提醒") == 5
        assert any("第 4 条意图" in t for t in _labels(page._intent_section))
        assert not any("第 5 条意图" in t
                       for t in _labels(page._intent_section))
        # 封顶之外给总数提示（片段区同场景一直有，意图区此前没有）
        assert any("……还有 2 条" in t for t in _labels(page._intent_section))
    finally:
        page.deleteLater()


def test_intents_body_truncation_marked(qapp, pump_page):
    """L14：正文截断带省略号——200 字硬切此前无声无息，看不出还有下半句。"""
    long_intent = "重构" + "甲" * 300
    page = _open_page(qapp, pump_page,
                      _PageApi(intents=[{"id": "i1", "intent": long_intent,
                                         "trunk": "前端",
                                         "category": "构建"}]))
    try:
        bodies = [t for t in _labels(page._intent_section)
                  if t.startswith("重构")]
        assert bodies, "意图正文未渲染"
        assert bodies[0].endswith("…"), f"截断处无省略号: {bodies[0][-10:]}"
        assert len(bodies[0]) == 201, "应保留 200 字 + 省略号"
    finally:
        page.deleteLater()


def test_intents_retranslate_on_language_switch(qapp, pump_page):
    """L14：意图区标题/提示进 retranslateUi——切语言后不得滞留中文。"""
    page = _open_page(qapp, pump_page, _PageApi())
    try:
        title = page._intent_title.text()
        assert title == "接下来可能要处理"
        from app.gui import i18n as _i18n
        _i18n.load_catalog("en")
        try:
            page.retranslateUi()
            qapp.processEvents()
            assert page._intent_title.text() == "Coming up next", \
                f"切 en 后意图区标题滞留: {page._intent_title.text()}"
            assert page._intent_hint.text() and "苗头" not in \
                page._intent_hint.text(), "意图区提示未重译"
        finally:
            _i18n.load_catalog("zh")
    finally:
        page.deleteLater()


def test_dismiss_intent_hits_right_endpoint(qapp, pump_page):
    api = _PageApi()
    page = _open_page(qapp, pump_page, api)
    try:
        btns = [b for b in _buttons(page._intent_section)
                if b.text() == "不再提醒"]
        btns[0].click()
        assert ("POST", "/api/intentions/i1/dismiss") in api.calls
        # 忽略后页面自刷：这条意图随之消失（不是要点两下才生效）
        assert pump_page(page, qapp), "忽略后的刷新未在超时内完成"
        assert ("GET", "/api/intentions") in api.calls[1:]
    finally:
        page.deleteLater()


def test_intents_hidden_when_none(qapp, pump_page):
    page = _open_page(qapp, pump_page, _PageApi(intents=[]))
    try:
        assert not page._intent_section.isVisibleTo(page)
    finally:
        page.deleteLater()


def test_intents_failure_is_silent(qapp, pump_page):
    """意图是附加层：取不到就整块藏起来，不在页面上报错。"""
    api = _PageApi(raise_on_intents=True)
    page = _open_page(qapp, pump_page, api)
    try:
        assert not page._intent_section.isVisibleTo(page)
        assert "意图" not in " ".join(_labels(page))
    finally:
        page.deleteLater()


def test_intents_expiry_hint_shows_remaining_days(qapp, pump_page):
    """M10：meta 行给相对剩余时间——14 天到期后静默消失，没有倒计时就像 bug。

    多给 12 小时余量：`days` 是整数截断，正好 +5 天会在下一次取时刻度上
    退成 4 天，断言就成了计时敏感型。
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    items = [
        {"id": "i1", "intent": "甲方案", "expires_at":
            (now + timedelta(days=5, hours=12)).strftime(fmt)},
        {"id": "i2", "intent": "乙方案", "expires_at":
            (now + timedelta(hours=2)).strftime(fmt)},
        {"id": "i3", "intent": "丙方案"},          # 老数据没有到期字段
    ]
    page = _open_page(qapp, pump_page, _PageApi(intents=items))
    try:
        texts = _labels(page._intent_section)
        assert any("约 5 天后过期" in t for t in texts)
        assert any("今天过期" in t for t in texts)
        assert len([t for t in texts if "过期" in t]) == 2, \
            "没有 expires_at 的意图不该凭空出现提示"
    finally:
        page.deleteLater()


def test_dismiss_failure_is_not_silent(qapp, pump_page):
    """M9：忽略失败必须报出来。

    静默失败的后果不是"没反应"，而是下一次 refresh 把它悄悄还原，用户以为
    已经生效；意图是 L6 附加层，dismiss 是用户管理它的唯一入口。
    """
    from PySide6.QtWidgets import QLabel

    api = _PageApi(dismiss_error=LocalApiError(500, "库写不进去"))
    page = _open_page(qapp, pump_page, api)
    bar = QLabel()
    page.set_status_bar(bar)
    try:
        next(b for b in _buttons(page._intent_section)
             if b.text() == "不再提醒").click()
        assert "忽略失败" in bar.text() and "库写不进去" in bar.text()
    finally:
        page.deleteLater()


def test_dismiss_409_is_treated_as_done(qapp, pump_page):
    """M9：409 = 已经忽略过了，刷新带走即可，不该弹错误。"""
    from PySide6.QtWidgets import QLabel

    api = _PageApi(dismiss_error=LocalApiError(409, "已经忽略过了"))
    page = _open_page(qapp, pump_page, api)
    bar = QLabel()
    page.set_status_bar(bar)
    try:
        next(b for b in _buttons(page._intent_section)
             if b.text() == "不再提醒").click()
        assert pump_page(page, qapp), "409 后的刷新未在超时内完成"
        assert ("GET", "/api/intentions") in api.calls[1:]
        assert "忽略失败" not in bar.text()
    finally:
        page.deleteLater()
