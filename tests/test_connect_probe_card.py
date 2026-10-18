"""「新增工具」卡结构断言（接入页_新增工具卡重设计方案）。

验收三条：
1. probe 卡内恰好 3 个步骤徽章，且第 ③ 个为激活态（C.primary_fill）；
2. refresh_probe 注入 decrypt_ready 模式时，行内出现 warn 档 chip；
3. 重新翻译（_retranslate_probe）后三个步骤标题文本与 zh 新 key 一致。

外加两条方案行为断言：计数 chip 随 self_reported 数量显隐；折叠链可展开收起。
离屏渲染（QT_QPA_PLATFORM=offscreen），零网络（_DeadApi 立即抛错）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication, QLabel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")

from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApi, LocalApiError  # noqa: E402
from app.gui.connect_page import ConnectPage  # noqa: E402
from app.gui.theme import C, D  # noqa: E402


class _DeadApi(LocalApi):
    """一切请求立即失败（模拟引擎未运行），不碰网络。"""

    def _request(self, method, path, json=None, params=None, timeout=None):
        raise LocalApiError(0, "本地 API 未连接")


@pytest.fixture
def page(dead_api: _DeadApi):
    p = ConnectPage(dead_api)
    yield p
    p.deleteLater()


@pytest.fixture(scope="session")
def dead_api() -> _DeadApi:
    return _DeadApi(base_url="http://127.0.0.1:8101")


def _step_columns(page: ConnectPage):
    lay = page._probe_steps.layout()
    return [lay.itemAt(i).widget() for i in range(lay.count())]


def _step_labels(col):
    lay = col.layout()
    return [lay.itemAt(i).widget() for i in range(lay.count())]


def test_probe_card_three_step_badges_third_active(qapp, page):
    """-1：恰好 3 个步骤徽章（D.BADGE_STEP 正圆），第 ③ 个激活态。"""
    cols = _step_columns(page)
    assert len(cols) == 3, f"三步条应恰好 3 列，实际 {len(cols)}"
    badges, titles, subs = [], [], []
    for col in cols:
        badge, title, sub = _step_labels(col)
        assert isinstance(badge, QLabel)
        assert badge.width() == D.BADGE_STEP == badge.height()
        assert badge.styleSheet().find(f"border-radius: {D.BADGE_STEP // 2}px") >= 0
        badges.append(badge)
        titles.append(title.text())
        subs.append(sub.text())
    # 激活态：实心橙（Orange-as-live-only）只给第 ③ 步。
    # 按 background: 断言（亮色下 brand_700 与 primary_fill 同值 #C2410C，
    # 查颜色串存在与否会有歧义）。
    assert f"background: {C.primary_fill}" in badges[2].styleSheet()
    assert f"background: {C.brand_100}" in badges[0].styleSheet()
    assert f"background: {C.brand_100}" in badges[1].styleSheet()
    # 步骤文案（表格）
    assert titles == ["导出技能", "运行一次", "粘贴连接"]
    assert subs == ["下载技能包", "工具自动上报", "连接码自动送达"]
    assert [b.text() for b in badges] == ["1", "2", "3"]


def test_probe_mode_chip_decrypt_ready_warn(qapp, page):
    """-2：decrypt_ready 模式 → 行内 warn 档 chip（待授权），描述进 tooltip。"""
    page.refresh_probe({
        "self_reported": {"hermes": {
            "mode": "decrypt_ready", "at": "2026-09-05T10:00:00Z"}},
        "draft_pending": 0,
    }, None)
    qapp.processEvents()
    labels = [l.text() for l in page._probe_list.findChildren(QLabel)]
    assert "待授权" in labels, f"decrypt_ready 行内应出现「待授权」chip: {labels}"
    # chip 工厂的 warn 档底色 + tooltip 保留原描述
    frame = None
    for l in page._probe_list.findChildren(QLabel):
        if l.text() == "待授权":
            frame = l.parent()
            break
    assert frame is not None
    assert C.warn_bg in frame.styleSheet()
    assert frame.toolTip() == "已加密，可授权解密"
    # 计数 chip：1 个工具
    assert page._probe_count_chip.isHidden() is False
    chip_labels = [l.text() for l in page._probe_count_chip.findChildren(QLabel)]
    assert chip_labels == ["1 个工具"]


def test_probe_mode_chip_fallback_modes(qapp, page):
    """映射表：hook_ready/scan_covered → ok；report_only → brand；
    未知 mode → 「经验上报兜底」中性 chip 且无 tooltip。"""
    page.refresh_probe({
        "self_reported": {
            "openclaw": {"mode": "hook_ready", "at": ""},
            "trae": {"mode": "weird_mode", "at": ""},
        },
        "draft_pending": 0,
    }, [
        {"code": "HMS-P-AAAA0000-1111", "agent": "hermes",
         "mode": "report_only", "at": ""},
    ])
    qapp.processEvents()
    labels = [l.text() for l in page._probe_list.findChildren(QLabel)]
    assert labels.count("已连接") == 1  # hook_ready
    assert "经验上报兜底" in labels  # 未知 mode
    assert "兜底上报" in labels  # keys 行 report_only
    # 未知 mode 的 chip 无 tooltip（—）
    for l in page._probe_list.findChildren(QLabel):
        if l.text() == "经验上报兜底":
            assert l.parent().toolTip() == ""
    # hook_ready 的 tooltip 是「可实时捕获」
    for l in page._probe_list.findChildren(QLabel):
        if l.text() == "已连接":
            assert l.parent().toolTip() == "可实时捕获"


def test_probe_count_chip_hidden_when_empty(qapp, page):
    """：self_reported 为空 → 计数 chip 隐藏，保留「无需手动接入」空态。"""
    page.refresh_probe({"self_reported": {}, "draft_pending": 0}, None)
    qapp.processEvents()
    assert page._probe_count_chip.isHidden()
    labels = [l.text() for l in page._probe_list.findChildren(QLabel)]
    assert "无需手动接入" in labels


def test_probe_retranslate_updates_steps(qapp, page):
    """-3：_retranslate_probe 后步骤标题/副标题、副标题、chip 与 zh 新 key 一致。"""
    page._retranslate_probe()
    cols = _step_columns(page)
    titles = [_step_labels(c)[1].text() for c in cols]
    subs = [_step_labels(c)[2].text() for c in cols]
    assert titles == ["导出技能", "运行一次", "粘贴连接"]
    assert subs == ["下载技能包", "工具自动上报", "连接码自动送达"]
    # 副标题是压缩后的 1 句（旧 3 行导语 key 已废弃）
    assert page._probe_intro.text() == (
        "少数 AI 工具的会话被加密或格式不通用，装个小技能就能接进来。")
    # 标题行中性 chip + 折叠链
    chip_labels = [l.text() for l in page._probe_scope_chip.findChildren(QLabel)]
    assert chip_labels == ["读不到的工具专用"]
    assert page._probe_why_btn.text() == "为什么需要？"


def test_probe_why_collapse_toggle(qapp, page):
    """：折叠链默认收起，点击展开/收起（setVisible 直落）。"""
    assert page._probe_why_body.isHidden()
    page._toggle_probe_why()
    qapp.processEvents()
    assert not page._probe_why_body.isHidden()
    page._toggle_probe_why()
    qapp.processEvents()
    assert page._probe_why_body.isHidden()
