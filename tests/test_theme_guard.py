"""设计家族护栏（deck  红线的代码强制，《设计家族》）。

已转 theme 的文件里：
- R10：禁止裸 hex 颜色（一切走 theme.C）
- R6/：禁止 ft.Icon 直建（走 theme.icon，尺寸三档）+ 禁 OUTLINE/ROUNDED 混族
- ：禁止裸 ft.Text（走 theme.txt，字号五档 + 字体栈）
随逐页改版，把文件加进 CONVERTED 即可扩大护栏覆盖。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

GUI = Path(__file__).resolve().parents[1] / "app" / "gui"

CONVERTED = (
    "home.py", "onboarding.py",
    "models_page.py", "experiences.py", "methods.py", "failure_modes.py",
    "preferences_page.py", "growth.py", "hooks_page.py",
    "skill_organize.py", "inject_preview.py", "settings_page.py",
    "connect_page.py", "export_page.py", "report_view.py",
)

HEX_RE = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
BAD_ICON_SUFFIX_RE = re.compile(r"ft\.Icons\.[A-Z0-9_]+(?:OUTLINE|ROUNDED)\b")


def _source(name: str) -> str:
    return (GUI / name).read_text(encoding="utf-8")


def test_converted_files_exist() -> None:
    for name in CONVERTED:
        assert (GUI / name).exists(), name


def test_no_raw_hex_in_converted_pages() -> None:
    for name in CONVERTED:
        for i, line in enumerate(_source(name).splitlines(), 1):
            if HEX_RE.search(line):
                raise AssertionError(f"{name}:{i} 裸 hex 颜色（R10：走 theme.C）: {line.strip()}")


def test_no_mixed_icon_families_in_converted_pages() -> None:
    for name in CONVERTED:
        for i, line in enumerate(_source(name).splitlines(), 1):
            m = BAD_ICON_SUFFIX_RE.search(line)
            if m:
                raise AssertionError(
                    f"{name}:{i} 图标族混用（只许 *_OUTLINED 或裸名 Filled）: {m.group(0)}")


def test_no_direct_icon_or_text_in_converted_pages() -> None:
    for name in CONVERTED:
        src = _source(name)
        assert "ft.Icon(" not in src, f"{name}: 直接建 ft.Icon（走 theme.icon）"
        assert "ft.Text(" not in src, f"{name}: 直接建 ft.Text（走 theme.txt）"


# flet 0.86.5 Windows 渲染地雷：Text(text_align=...) 与同树 ft.Button 共存时
# 整页静默不绘制（背景/文字/按钮大面积缺失，无异常，截图见 session 记录）。
# 居中一律靠父级 Column/Row 的 horizontal_alignment，不显式设 text_align。
TEXT_ALIGN_RE = re.compile(r"text_align\s*=\s*ft\.TextAlign\.")


def test_no_explicit_text_align_in_converted_pages() -> None:
    for name in (*CONVERTED, "theme.py"):
        src = _source(name)
        for i, line in enumerate(src.splitlines(), 1):
            if TEXT_ALIGN_RE.search(line):
                raise AssertionError(
                    f"{name}:{i} 显式 text_align（0.86.5 Windows 上同树 Button 会"
                    f"触发整页渲染静默失败；居中走父级 alignment）: {line.strip()}")


def test_only_outlined_icons_outside_nav() -> None:
    """P4-06 AST 护栏：禁止裸 Filled 图标（覆盖 gui 全部 .py，含新文件）。

    匹配 ``ft.Icons.<NAME>`` 属性链；NAME 不以 ``_OUTLINED`` 结尾即违规。
    AST 走查天然跳过注释/字符串。（旧 flet 栈已裁撤：任何 ft.Icons 出现即违规。）
    """
    for path in sorted(GUI.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            base = node.value
            if not (isinstance(base, ast.Attribute) and base.attr == "Icons"
                    and isinstance(base.value, ast.Name) and base.value.id == "ft"):
                continue
            if node.attr.endswith("_OUTLINED"):
                continue
            raise AssertionError(
                f"{path.name}:{node.lineno} 裸 Filled 图标 ft.Icons.{node.attr}"
                f"（P4-06：只许 *_OUTLINED）")


# P5 护栏（章程）：结构尺寸必须走 token，不许裸 int 字面量（第四类违规：
# "在一台机器上量出来的像素写死"）。width/height/min_*/max_* 的值必须是
# token 引用（D.*/S.*）、B/C 类函数调用（layout.*）或 0（空位占位，非尺寸）。
_SIZE_KWARGS = {"width", "height", "min_width", "min_height", "max_width", "max_height"}


def test_no_bare_int_structural_size_in_gui() -> None:
    """AST 走查：gui 全部 .py 里 width/height 等结构尺寸 kwarg 不得是裸 int。

    裸 int（如 width=100）就是"写死的像素"——换台机器/分辨率就错。必须：
    - 结构 token（D.ICON_BOX / D.BORDER_W / S.s3 …）
    - B/C 类函数（layout.dialog_width / code_box_size / _rail_width …）
    - 0（空位占位，models_page 的"非尺寸"占位容器，注释已标明）
    谁新增一个裸 int 尺寸，这条立刻红（章程验收：故意写裸字面量 → 红）。
    """
    for path in sorted(GUI.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword) or node.arg not in _SIZE_KWARGS:
                continue
            v = node.value
            if isinstance(v, ast.Constant) and isinstance(v.value, int):
                if v.value == 0:  # 空位占位（非尺寸），放行
                    continue
                raise AssertionError(
                    f"{path.name}:{node.lineno} 裸 int 结构尺寸 {node.arg}={v.value}"
                    f"（结构尺寸走 token 或 B/C 函数，不许写死像素）")


def test_spacing_and_shape_tokens_exist() -> None:
    """S./R./F./D. 只能引用真实存在的 token（防 S.s5 这类拼错=运行时 AttributeError）。

    真机踩坑：qt_dialogs.info_dialog 写了 S.s5——间距表只有
    s1/s2/s3/s4/s6/s8，报告弹层一打开就 AttributeError。AST 全量扫，谁写
    不存在的 token 立刻红。"""
    import sys

    sys.path.insert(0, str(GUI.parents[1]))
    from app.gui.theme import D, F, R, S

    tables = {"S": S, "R": R, "F": F, "D": D}
    for path in sorted(GUI.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            base = node.value
            if not (isinstance(base, ast.Name) and base.id in tables):
                continue
            if not hasattr(tables[base.id], node.attr):
                raise AssertionError(
                    f"{path.name}:{node.lineno} 引用不存在的 token "
                    f"{base.id}.{node.attr}（{tables[base.id].__name__} 表里没有）")
