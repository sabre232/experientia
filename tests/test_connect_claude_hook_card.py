"""Claude Code 实时钩子卡（接入页子集卡）结构与自适应断言。

背景：接入页服务**所有**在用工具的用户，而实时钩子卡只服务 Claude Code 一家。
按「子集卡」范式（同新增工具卡「读不到的工具专用」chip）落地三条：
1. 标题不撞页标题「接入」，改点明对象「实时钩子（Claude Code）」+ 作用域 chip
   「Claude Code 专用」（非 Claude 用户一眼可辨）；
2. 卡下移到 ① 已接入 / ② 采集（通用 payoff）**之后**——顶部先回答所有用户的
   问题，再给子集工具的特有增强；
3. 正文可折叠，默认态随探测结果自适应：在跑 claude-code → 展开，未在用 → 收起；
   用户手动切换后 refresh 不再覆盖其选择。

离屏渲染（QT_QPA_PLATFORM=offscreen），零网络（_DeadApi 立即抛错）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication, QLabel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")

from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApi, LocalApiError  # noqa: E402
from app.gui.connect_page import ConnectPage  # noqa: E402


class _DeadApi(LocalApi):
    """一切请求立即失败（模拟引擎未运行），不碰网络。"""

    def _request(self, method, path, json=None, params=None, timeout=None):
        raise LocalApiError(0, "本地 API 未连接")


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    i18n.load_catalog("zh")
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="session")
def dead_api() -> _DeadApi:
    return _DeadApi(base_url="http://127.0.0.1:8101")


@pytest.fixture
def page(dead_api: _DeadApi):
    p = ConnectPage(dead_api)
    yield p
    p.deleteLater()


def _chip_labels(chip) -> list[str]:
    return [l.text() for l in chip.findChildren(QLabel)]


def _layout_index_of(page: ConnectPage, descendant) -> int:
    """descendant 所属的顶层卡（page._cl 直接子项）在布局里的序号。"""
    for i in range(page._cl.count()):
        w = page._cl.itemAt(i).widget()
        if w is not None and w.isAncestorOf(descendant):
            return i
    return -1


def test_connect_card_title_not_page_title_and_has_scope_chip(qapp, page):
    """1. 标题点明对象（不撞页标题「接入」）+ 标题行挂作用域 chip。"""
    # 页标题仍是「接入」，卡标题必须与之区分
    assert page._connect_heading.text() == "接入"
    assert page._guide_card_title.text() == "实时钩子（Claude Code）"
    # 作用域 chip：Claude Code 专用（同新增工具卡「读不到的工具专用」chip 范式）
    assert _chip_labels(page._connect_scope_chip) == ["Claude Code 专用"]


def test_connect_card_below_generic_payoff(qapp, page):
    """2. 卡位于 ① 已接入 / ② 采集（通用 payoff）之后、③ 需处理之前。

    顶部先回答所有用户「谁接进来了 / 谁在记录」，再给子集工具的特有增强；
    防止这张 Claude 专属卡回潮到总况条正下方霸占首屏。"""
    overview_i = _layout_index_of(page, page._url_bar)       # 总况条
    agents_i = _layout_index_of(page, page._agent_empty)     # ① 已接入
    capture_i = _layout_index_of(page, page._capture_header)  # ② 采集
    connect_i = _layout_index_of(page, page._guide_card_title)  # 钩子卡
    action_i = _layout_index_of(page, page._action_card)     # ③ 需处理
    assert 0 <= min(overview_i, agents_i, capture_i, connect_i, action_i), \
        f"定位失败: ov={overview_i} ag={agents_i} cap={capture_i} " \
        f"con={connect_i} act={action_i}"
    # 严格顺序：总况条 < ① 已接入 < ② 采集 < 钩子卡 < ③ 需处理
    assert overview_i < agents_i < capture_i < connect_i < action_i, \
        f"顺序错乱: ov={overview_i} ag={agents_i} cap={capture_i} " \
        f"con={connect_i} act={action_i}"


def test_connect_card_default_expanded(qapp, page):
    """3a. 首帧默认展开（构建阶段无探测数据，给足信息）。"""
    assert page._connect_expanded
    assert not page._connect_body.isHidden()


def test_connect_card_collapses_when_not_using_claude(qapp, page, monkeypatch):
    """3b. 未在用 Claude Code → _apply_connect_default(False) 收起正文。"""
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")  # 关动画 → 同步断言
    page._apply_connect_default(claude_in_use=False)
    qapp.processEvents()
    assert not page._connect_expanded
    assert page._connect_body.isHidden()
    assert page._connect_expand_icon.rotation == 0.0  # chevron-down（可展开）


def test_connect_card_expands_when_using_claude(qapp, page, monkeypatch):
    """3c. 在跑 Claude Code → _apply_connect_default(True) 展开正文。"""
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    # 先收起再按探测展开，验证方向
    page._apply_connect_default(claude_in_use=False)
    page._apply_connect_default(claude_in_use=True)
    qapp.processEvents()
    assert page._connect_expanded
    assert not page._connect_body.isHidden()
    assert page._connect_expand_icon.rotation == 180.0  # chevron-up（已展开）


def test_connect_card_manual_toggle_not_overridden(qapp, page, monkeypatch):
    """3d. 用户手动展开后，refresh 的自适应不再覆盖其选择（_user_toggled）。

    场景：非 Claude 用户手动展开看了一眼花，随后 refresh（仍在跑非 Claude
    工具）不得把卡又收回去。"""
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    # 非 Claude → 收起
    page._apply_connect_default(claude_in_use=False)
    assert page._connect_body.isHidden()
    # 用户手动展开
    page._toggle_connect_card()
    assert not page._connect_body.isHidden()
    assert page._connect_user_toggled
    # 再次自适应（仍未用 Claude）：尊重用户选择，保持展开
    page._apply_connect_default(claude_in_use=False)
    qapp.processEvents()
    assert not page._connect_body.isHidden(), "用户手动展开被 refresh 覆盖"


def test_connect_card_toggle_flips_body(qapp, page, monkeypatch):
    """3e. 标题行点击在展开/收起间翻转正文。"""
    monkeypatch.setenv("EXPERIENTIA_REDUCE_MOTION", "1")
    start = page._connect_expanded
    page._toggle_connect_card()
    assert page._connect_expanded is (not start)
    page._toggle_connect_card()
    assert page._connect_expanded is start


def test_connect_card_retranslate_updates_title_and_chip(qapp, page):
    """4. retranslateUi 后标题与 chip 文案与 zh key 一致（i18n 可提取）。"""
    page.retranslateUi()
    qapp.processEvents()
    assert page._guide_card_title.text() == "实时钩子（Claude Code）"
    assert _chip_labels(page._connect_scope_chip) == ["Claude Code 专用"]
