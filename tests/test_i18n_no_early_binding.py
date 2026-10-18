"""i18n 早绑定守卫（用户实测反馈驱动）。

背景：设置页「通知」卡片在英文首屏显示中文——根因是 `_NOTIFY_ITEMS` 在
**模块级**调 `t()`，import 时语言目录未加载，取到的中文源串被冻住；前人只在
`retranslateUi` 里手写 12 行 if/elif 补救"切语言后"，首屏依旧中文。

本文件三面锁：
1. AST 守卫：app/gui 下不得在模块级/类级调 t()（常量存 msgid，用时才 t()）；
2. 行为：英文首屏构建的通知卡片必须是英文（不是冻住的中文）；
3. 行为：切语言后通知卡片跟着变（删掉 if/elif 补丁后不能回归）。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("PySide6")

from app.gui import i18n  # noqa: E402
from app.gui.api_client import LocalApi, LocalApiError  # noqa: E402
from app.gui.settings_page import SettingsPage  # noqa: E402

CJK = re.compile(r"[\u4e00-\u9fff]")


class _DeadApi(LocalApi):
    """一切请求立即失败（引擎未运行），不碰网络。"""

    def _request(self, method, path, json=None, params=None, timeout=None):
        raise LocalApiError(0, "本地 API 未连接")


# ---------- 1. AST 守卫：模块级/类级不得调 t() ----------

def _t_calls_in(node: ast.AST) -> bool:
    return any(isinstance(s, ast.Call) and isinstance(s.func, ast.Name)
               and s.func.id == "t" for s in ast.walk(node))


def test_no_module_or_class_level_t_calls():
    """app/gui 下 t() 只允许出现在函数体内。

    模块级/类级求值发生在 import 时，彼时 `i18n.load_catalog()` 多半还没跑，
    t() 只能返回中文源串并被冻住——首屏渲染冻住的串，语言切换也不更新。
    正确做法：模块级常量存 msgid，渲染与 retranslateUi 在使用时才 t()。
    """
    root = Path(__file__).resolve().parent.parent / "app" / "gui"
    bad: list[str] = []

    def visit(body, in_func: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(node.body, True)
                continue
            if isinstance(node, ast.ClassDef):
                visit(node.body, in_func)  # 类级同样在 import 时求值
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr)) \
                    and not in_func and _t_calls_in(node.value):
                bad.append(f"{node.lineno}")

    for p in sorted(root.rglob("*.py")):
        before = len(bad)
        visit(ast.parse(p.read_text(encoding="utf-8")).body, False)
        for ln in bad[before:]:
            bad[bad.index(ln)] = f"{p.name}:{ln}"

    assert not bad, (
        "以下位置在模块级/类级调 t()（import 时早绑定，首屏会是冻住的中文）："
        + ", ".join(bad))


# ---------- 2/3. 行为：首屏与切语言都必须是当前语言 ----------

def test_notify_cards_translated_on_first_render(qapp):
    """英文环境下**首屏构建**的通知卡片必须是英文（用户实测反馈的那条）。"""
    i18n.load_catalog("zh")
    try:
        i18n.load_catalog("en")
        page = SettingsPage(_DeadApi())
        try:
            assert page._notify_labels, "通知卡片没建起来"
            for key, (title_lab, hint_lab) in page._notify_labels.items():
                for lab in (title_lab, hint_lab):
                    text = lab.text()
                    assert text, f"{key} 标签为空"
                    assert not CJK.search(text), \
                        f"{key} 首屏仍是中文（早绑定未修）：{text!r}"
        finally:
            page.deleteLater()
    finally:
        i18n.load_catalog("zh")


def test_notify_cards_follow_language_switch(qapp):
    """切语言后通知卡片跟着变（删掉 if/elif 补丁后不能回归）。"""
    i18n.load_catalog("zh")
    page = SettingsPage(_DeadApi())
    try:
        first_zh = {k: v[0].text() for k, v in page._notify_labels.items()}
        assert any(CJK.search(s) for s in first_zh.values()), "中文首屏应有中文"

        i18n.load_catalog("en")
        page.retranslateUi()
        for key, (title_lab, _hint) in page._notify_labels.items():
            assert not CJK.search(title_lab.text()), \
                f"{key} 切英文后仍是中文：{title_lab.text()!r}"

        i18n.load_catalog("zh")
        page.retranslateUi()
        for key, (title_lab, _hint) in page._notify_labels.items():
            assert title_lab.text() == first_zh[key], \
                f"{key} 切回中文后与首屏不一致"
    finally:
        i18n.load_catalog("zh")
        page.deleteLater()


def test_notification_list_type_label_is_translated(qapp):
    """最近通知列表的类型标签也走渲染时 t()（_NTYPE_LABEL 存 msgid）。"""
    i18n.load_catalog("en")
    try:
        page = SettingsPage(_DeadApi())
        try:
            # 直接喂一条通知，走渲染路径
            page._render_notifications([
                {"type": "method_update", "title": "x", "body": "y",
                 "ts": "2026-10-16T00:00:00Z"}])
            texts = [lb.text() for lb in page._notif_box.findChildren(type(page._notif_head))]
            blob = " ".join(texts)
            assert blob, "通知列表没渲染"
            assert not CJK.search(blob), f"类型标签仍是中文：{blob!r}"
        finally:
            page.deleteLater()
    finally:
        i18n.load_catalog("zh")
