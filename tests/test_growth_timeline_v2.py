"""学习历程信息量控制 UI 验证（离屏渲染，QT_QPA_PLATFORM=offscreen）。

阀门一：review 节点 times≥2 → 标题带「（复盘 {times} 次）」；times=1 文案不变。
阀门二：带 solidified 的复盘节点挂到对应 distill 里程碑下作「源复盘」子块
（默认折叠成一行，点击展开逐条，每条保留自己的 ⋯ 菜单）；里程碑缺失
（被删/被封顶）→ 普通节点 +「已固化 v{ver}」chip。
legacy 行（无标记）走人话化正则，不合并、不折叠。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from app.gui import growth, i18n  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    i18n.load_catalog("zh")
    return QApplication.instance() or QApplication([])


# ---------- 数据 ----------

_REVIEW_TEXT = ("复盘 workbuddy 会话 00000000-000… "
                "→ 其他/未分类 新增 1 条候选经验 [auto]")


def _node(idx, ts, text, tag):
    return {"idx": idx, "ts": ts, "text": text, "tag": tag}


def _nodes_with_milestone() -> list[dict]:
    """新在前：蒸馏里程碑（更新）在上，两条已固化的源复盘在下。"""
    return [
        _node(0, "2026-09-12T10:00:00",
              "蒸馏 其他/未分类（review）：3 条经验 → v3",
              {"kind": "distill", "path": "其他/未分类", "ver": "v3",
               "src": "review", "n": "3"}),
        _node(1, "2026-09-11T15:00:00", _REVIEW_TEXT,
              {"kind": "review", "agent": "workbuddy", "sid": "00000000",
               "n": "2", "times": "1", "solidified": "v3"}),
        _node(2, "2026-09-11T14:00:00",
              "复盘 claude-code 会话 aabbcc-999… → 其他/未分类 "
              "新增 1 条候选经验（文件通道）",
              {"kind": "review", "agent": "claude-code", "sid": "aabbcc999",
               "n": "1", "times": "1", "solidified": "v3"}),
    ]


class _FakeGrowthApi:
    """零网络：growth()/skills() 返回预制 payload。"""

    def __init__(self, changelog: list[dict]):
        self._cl = changelog

    def growth(self):
        return {"days": 30, "cumulative": {},
                "heatmap": {"trunks": [], "grid": {}},
                "affinity": {}, "changelog": self._cl, "maintenance": []}

    def skills(self):
        return {"items": []}


def _build_page(nodes: list[dict]) -> growth.GrowthPage:
    page = growth.GrowthPage(_FakeGrowthApi(nodes))
    page._render(_FakeGrowthApi(nodes).growth(), [])
    return page


def _object_names(page: growth.GrowthPage) -> list[str]:
    return [w.objectName() for w in page._tl_box.findChildren(QWidget)]


def _label_texts(page: growth.GrowthPage) -> list[str]:
    return [l.text() for l in page._tl_box.findChildren(QLabel)]


# ---------- 阀门一：times 展示口径 ----------

def test_review_times2_title(qapp):
    """times≥2 → 「从 {agent} 的会话学到 {n} 条新经验（复盘 {times} 次）」；
    n 取标记值（文本里的条数只是首轮的）。"""
    nodes = [_node(0, "2026-09-11T14:22:55", _REVIEW_TEXT,
                   {"kind": "review", "agent": "workbuddy",
                    "sid": "00000000", "n": "3", "times": "2"})]
    days = growth.GrowthPage._tl_group_by_day(nodes)
    (day, groups) = days[0]
    assert groups[0]["title"] == \
        "从 workbuddy 的会话学到 3 条新经验（复盘 2 次）"


def test_review_times1_title_unchanged(qapp):
    """times=1 → 现文案不变。"""
    nodes = [_node(0, "2026-09-11T14:22:55", _REVIEW_TEXT,
                   {"kind": "review", "agent": "workbuddy",
                    "sid": "00000000", "n": "1", "times": "1"})]
    days = growth.GrowthPage._tl_group_by_day(nodes)
    assert days[0][1][0]["title"] == "从 workbuddy 的一次会话学到 1 条新经验"


# ---------- 阀门二：固化子块 ----------

def test_solidified_review_folds_under_milestone(qapp):
    """带 solidified 的复盘节点摘出挂到同 path 里程碑下；里程碑 meta 带交代。"""
    days = growth.GrowthPage._tl_group_by_day(_nodes_with_milestone())
    items = [it for _d, groups in days for g in groups for it in g["items"]]
    # 源复盘被摘出，日分组里只剩里程碑
    assert [it["idx"] for it in items] == [0]
    milestone = items[0]
    assert [s["idx"] for s in milestone["sources"]] == [1, 2]
    assert "含 2 条源复盘" in milestone["meta"]


def test_solidified_without_milestone_stays_normal(qapp):
    """匹配不到里程碑（被删/被封顶）→ 留在原日，普通节点 + chip 数据。"""
    nodes = [_node(0, "2026-09-11T14:00:00", _REVIEW_TEXT,
                   {"kind": "review", "agent": "workbuddy",
                    "sid": "00000000", "n": "1", "times": "1",
                    "solidified": "v3"})]
    days = growth.GrowthPage._tl_group_by_day(nodes)
    item = days[0][1][0]["items"][0]
    assert item["solidified"] == "v3"
    assert not item.get("sources")


def test_source_block_renders_and_toggles(qapp):
    """折叠成一行「源复盘 ×2」；点击展开逐条（各带 ⋯ 菜单），再收起复原。"""
    page = _build_page(_nodes_with_milestone())
    names = _object_names(page)
    assert "tlSrcFold" in names
    assert names.count("tlSrcRow") == 0
    assert any("源复盘" in x for x in _label_texts(page))
    # 展开
    page._tl_toggle_source(0)
    assert page._tl_expanded_sources == {0}
    names = _object_names(page)
    assert "tlSrcFold" not in names
    assert names.count("tlSrcRow") == 2
    # 收起复原
    page._tl_toggle_source(0)
    assert _object_names(page).count("tlSrcFold") == 1
    page.deleteLater()


def test_show_all_expands_source_blocks(qapp):
    """「展开全部 N 个节点」= 真正全部：源复盘子块一并展开；
    「收起」恢复默认（子块重新折叠）。"""
    page = _build_page(_nodes_with_milestone())
    assert _object_names(page).count("tlSrcFold") == 1  # 默认折叠
    page._tl_toggle_all()
    assert page._tl_show_all is True
    names = _object_names(page)
    assert "tlSrcFold" not in names
    assert names.count("tlSrcRow") == 2
    page._tl_toggle_all()
    assert page._tl_show_all is False
    assert _object_names(page).count("tlSrcFold") == 1
    page.deleteLater()


def test_unmatched_solidified_shows_chip(qapp):
    """无里程碑的已固化节点 → 节点行带「已固化 v3」chip。"""
    nodes = [_node(0, "2026-09-11T14:00:00", _REVIEW_TEXT,
                   {"kind": "review", "agent": "workbuddy",
                    "sid": "00000000", "n": "1", "times": "1",
                    "solidified": "v3"})]
    page = _build_page(nodes)
    assert any("已固化 v3" in x for x in _label_texts(page))
    page.deleteLater()


# ---------- legacy 兜底 ----------

def test_legacy_review_line_regex_no_merge(qapp):
    """legacy 行（无标记）→ 走人话化正则，sig 正常、无 solidified。"""
    info = growth.GrowthPage._humanize_node(
        _node(0, "2026-09-11T14:00:00", _REVIEW_TEXT, None))
    assert info["sig"] == ("review", "其他/未分类")
    assert info["parse"]["n"] == 1
    assert not info.get("solidified")


def test_edited_tagged_node_shows_raw_text(qapp):
    """用户改过文本的标记行 → 原文照显、不合并（编辑语义零破坏）。"""
    info = growth.GrowthPage._humanize_node(
        _node(0, "2026-09-11T14:00:00", "我改写的节点文本",
              {"kind": "review", "agent": "workbuddy", "sid": "x",
               "n": "3", "times": "2", "solidified": "v3"}))
    assert info["title"] == "我改写的节点文本"
    assert info["sig"] is None
    # 标记仍在：固化匹配与 chip 不受影响
    assert info["solidified"] == "v3"


# ---------- ：机器标记优先，正则仅作 legacy 回退 ----------

def test_tagged_self_uses_tag_fields(qapp):
    """kind=self：agent/path/n 吃标记（文本措辞变了也不影响分类与合并）。"""
    info = growth.GrowthPage._humanize_node(
        _node(0, "2026-09-11T14:00:00", "完全被用户改过的自报文本",
              {"kind": "self", "agent": "hermes",
               "path": "其他/未分类", "n": "1"}))
    assert info["kind"] == "learn"
    assert info["title"] == "hermes 自报 1 条经验，已自动入库"
    assert info["meta"] == "其他/未分类"
    assert info["sig"] == ("self", "其他/未分类", "hermes")
    assert info["parse"] == {"n": 1}


def test_tagged_fixes_uses_tag_fields(qapp):
    """kind=fixes：path/ver/n 吃标记，不依赖正则命中人话模板。"""
    info = growth.GrowthPage._humanize_node(
        _node(0, "2026-09-11T14:00:00", "纠正补丁文本被编辑过",
              {"kind": "fixes", "path": "营销/文案", "ver": "v2", "n": "5"}))
    assert info["kind"] == "method"
    assert "营销/文案" in info["title"] and "v2" in info["title"]
    assert "5" in info["meta"]


def test_tagged_pref_inc_merges_by_tag(qapp):
    """kind=pref-inc：trunk/n 吃标记，sig 正常参与 ×N 合并。"""
    info = growth.GrowthPage._humanize_node(
        _node(0, "2026-09-11T14:00:00", "偏好文本被改",
              {"kind": "pref-inc", "trunk": "营销", "n": "4"}))
    assert info["kind"] == "pref"
    assert info["title"] == "偏好画像「营销」自动归纳 4 条新偏好"
    assert info["sig"] == ("pref-inc", "营销")
    assert info["parse"] == {"n": 4}


def test_tagged_veto_detail_from_text(qapp):
    """kind=veto：身份吃标记；否决内容（标记里没有）从人话文本「：」后段补充。"""
    info = growth.GrowthPage._humanize_node(
        _node(0, "2026-09-11T14:00:00",
              "用户否决失败模式 营销/文案：绝不夸大促销效果",
              {"kind": "veto", "path": "营销/文案"}))
    assert info["kind"] == "method"
    assert info["title"] == "你否决了 1 条失败模式"
    assert "营销/文案" in info["meta"] and "绝不夸大促销效果" in info["meta"]
    assert info["sig"] is None


def test_tagged_ach_n_from_tag(qapp):
    """kind=ach：成就个数吃标记 n（文本只是首轮措辞）。"""
    info = growth.GrowthPage._humanize_node(
        _node(0, "2026-09-11T14:00:00", "成就解锁 1 个：连胜",
              {"kind": "ach", "n": "3"}))
    assert info["kind"] == "ach"
    assert info["title"] == "解锁 3 个成就"


def test_tagged_pref_reinduct_falls_back_meta(qapp):
    """kind=pref-reinduct：kept/new 条数不在标记里——文本可解析则补充，
    文本被改坏时降级为 trunk，不崩、分类正确。"""
    base = {"kind": "pref-reinduct", "trunk": "研发"}
    ok = growth.GrowthPage._humanize_node(
        _node(0, "2026-09-11T14:00:00",
              "偏好重新归纳 研发：3 条确认保留 / 5 条新归纳", base))
    assert ok["kind"] == "pref" and "3" in ok["meta"] and "5" in ok["meta"]
    broken = growth.GrowthPage._humanize_node(
        _node(1, "2026-09-11T14:00:00", "改坏了的文本", base))
    assert broken["kind"] == "pref" and broken["meta"] == "研发"


def test_legacy_regex_chain_still_works_for_untagged(qapp):
    """legacy 行（tag=None）回退人话化正则（既有行为不回归）。"""
    info = growth.GrowthPage._humanize_node(
        _node(0, "2026-09-11T14:00:00",
              "纠正补丁 营销/文案：7 条 → v2", None))
    assert info["kind"] == "method"
    assert "营销/文案" in info["title"]
