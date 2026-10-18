"""省略文本兜底护栏（结构性）：凡被省略，必可点开看全。

对应的线上缺陷：旧记录没有 *_raw 字段时，长文本只能显示前几行，点不开、
也看不到全文——"没有一套机制遏制这种现象"。机制下沉到 ClampedLabel 后，
本文件盯住它不再退化：省略即可展开、展开可收起、宽度变化后重新判定。

另有一条高度护栏：max_lines 是上限而非固定高——短标题不得预留空行
（否则卡片里标题与副行之间出现大片空白）。

注意导入顺序：内嵌字体在 qt_theme 导入时注册，而注册要求 QApplication 已存在。
所以本文件先建 QApplication 再导入 GUI 模块——否则字体未注册、度量恒为 0，
省略判定测不出来（既可能假绿也可能假红）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QFontMetrics, QMouseEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from app.gui.api_client import LocalApi  # noqa: E402
from app.gui.experiences import ExperiencesPage  # noqa: E402
from app.gui.i18n import t  # noqa: E402
from app.gui.qt_theme import (ClampedLabel, expandable_clamped,  # noqa: E402
                              txt_clamped)
from app.gui.theme import F  # noqa: E402

# 样本必须"任何字体度量下都必然溢出"——脱离对具体字体宽度的假设。
DENSE = "这一段用于验证省略兜底的样本文字，重复填充到足够长。" * 15
MID = "短句样本" * 4
SHORT_TITLE = "看看「接任执行交接单_2026-09-09.md」"

_HOLDERS: list[QWidget] = []  # 持有宿主窗口，防局部变量回收把内部控件一起析构


def _click(widget: QWidget) -> None:
    ev = QMouseEvent(QEvent.MouseButtonPress, QPoint(4, 4), Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    widget.mousePressEvent(ev)


def _show(qapp, widget: QWidget, width: int = 500, height: int = 900) -> QWidget:
    """放进宿主布局并显示；末尾留 stretch，控件高度才反映自身而非撑满宿主。"""
    holder = QWidget()
    holder.resize(width, height)
    lay = QVBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(widget)
    lay.addStretch(1)
    holder.show()
    _relayout(qapp, holder)
    _HOLDERS.append(holder)
    return holder


def _relayout(qapp, holder: QWidget) -> None:
    holder.layout().activate()
    for _ in range(4):
        qapp.processEvents()


def test_omitted_text_is_expandable_without_raw(qapp):
    """老数据（display == full，没有 *_raw）被省略时必须可展开看全。"""
    lab = txt_clamped(DENSE, F.h2, 600, None, 3)
    _show(qapp, lab)
    assert lab.is_omitted(), "样本没被省略，测不到兜底"
    assert lab.is_expandable()
    assert lab.cursor().shape() == Qt.PointingHandCursor
    assert lab.toolTip() == t("点击展开全文")

    collapsed = lab.height()
    _click(lab)
    qapp.processEvents()
    assert lab.is_expanded()
    assert lab.height() > collapsed, "展开了但高度没变——全文仍被裁在盒子里"
    assert lab.toolTip() == t("点击收起")

    _click(lab)
    qapp.processEvents()
    assert not lab.is_expanded()
    assert lab.height() == collapsed


def test_short_text_stays_static(qapp):
    """没被省略、也没有更长全文 → 不可点、无手型光标（不该满屏都像链接）。"""
    lab = txt_clamped("短结论", F.body, 400, None, 2)
    _show(qapp, lab)
    assert not lab.is_omitted()
    assert not lab.is_expandable()
    assert lab.cursor().shape() != Qt.PointingHandCursor
    assert lab.toolTip() == ""


def test_longer_full_text_is_expandable(qapp):
    """短结论 + 长原文：结论本身没省略，也要能点开看原文。"""
    box = expandable_clamped("改了 references 排版", DENSE, F.body, 400, None, 2)
    _show(qapp, box)
    assert box.is_expandable()
    collapsed = box.height()
    _click(box)
    qapp.processEvents()
    assert box.is_expanded()
    assert box.height() > collapsed, "展开了但整块没长高，原文仍看不见"


def test_width_shrink_reenables_expandable(qapp):
    """窗口变窄后原本不省略的文本被省略 → 立刻可展开（判定跟着宽度走）。"""
    lab = txt_clamped(MID, F.body, 400, None, 2)
    holder = _show(qapp, lab, width=1600, height=900)
    assert not lab.is_omitted(), "宽容器下不该省略"
    holder.resize(60, 900)
    _relayout(qapp, holder)
    assert lab.is_omitted(), "窄容器下必然省略"
    assert lab.is_expandable()


def test_short_text_does_not_reserve_blank_lines(qapp):
    """max_lines 是上限不是固定高：短标题只占一行，不留空行（卡片大片空白）。"""
    lab = txt_clamped(SHORT_TITLE, F.h2, 600, None, 3)
    _show(qapp, lab, width=880, height=400)
    fm = QFontMetrics(lab.font())
    assert lab._line_count(lab.text(), lab.width()) == 1
    assert lab.height() == fm.lineSpacing(), "短文本按 max_lines 预留了空行"

    long_lab = txt_clamped(DENSE, F.h2, 600, None, 3)
    _show(qapp, long_lab, width=500, height=900)
    assert long_lab.height() == 3 * fm.lineSpacing(), "溢出文本仍应占满上限行数"


def test_experience_card_long_text_is_expandable(qapp):
    """回归用户报的显示问题：旧记录（无 *_raw）在经验卡里被省略时也要能点开看全。"""

    class _NoApi(LocalApi):
        def _request(self, *a, **kw):
            raise AssertionError("渲染卡片不应发请求")

    page = ExperiencesPage(_NoApi(base_url="http://127.0.0.1:8101"))
    rec = {"id": "e1", "task": DENSE, "state": DENSE, "action": DENSE,
           "outcome": DENSE, "agent": "workbuddy", "model": "hy3",
           "ts": "2026-09-11T10:00:00", "distilled": False}
    card = page._exp_card([rec])
    _show(qapp, card, width=620, height=2400)
    labels = card.findChildren(ClampedLabel)
    omitted = [x for x in labels if x.is_omitted()]
    assert omitted, "样本未被省略，兜底路径没被测到"
    assert all(x.is_expandable() for x in omitted), "卡片里有被省略却点不开的文本"
