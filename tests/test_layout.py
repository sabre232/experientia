"""layout.py 护栏（章程）：C 类窗口 clamp + 屏工作区查询。

Windows 屏工作区走 Win32 SPI_GETWORKAREA（旧 GUI 栈无屏尺寸 API 时引入并沿用），
其他平台 None → 默认窗口尺寸（与现状一致，不猜不崩）。
"""

import sys

from app.gui import layout


def test_initial_window_size_no_screen_keeps_defaults():
    """取不到屏尺寸 → 原样返回默认/最小（行为与 P2 前一致）。"""
    assert layout.initial_window_size(None) == (1200, 800, 1000, 640)


def test_initial_window_size_clamps_to_small_screen():
    """小屏（1366×768 @150% → 工作区约 1280×676 逻辑）：高度顶到屏，宽度不动。"""
    w, h, mw, mh = layout.initial_window_size((1280, 676))
    assert (w, h, mw, mh) == (1200, 676, 1000, 640)


def test_initial_window_size_clamps_to_very_small_screen():
    """1024×768 级小屏：宽高与最小值一起 clamp 到屏内。"""
    w, h, mw, mh = layout.initial_window_size((1024, 728))
    assert (w, h, mw, mh) == (1024, 728, 1000, 640)
    assert mw <= w and mh <= h  # 最小值不得反超大值（否则窗口管理器行为未定义）


def test_initial_window_size_large_screen_unchanged():
    """大屏（2560×1440 级）：默认值原样生效。"""
    assert layout.initial_window_size((2300, 1250)) == (1200, 800, 1000, 640)


# ---------- P3：对话框/代码框 C 类（章程） ----------

def test_dialog_width_clamps():
    """对话框宽 = 窗口宽 85%，夹 [420, 720]（overlay 居中全窗口，不减导航宽）。"""
    assert layout.dialog_width((1200, 800)) == 720   # 1020 → 顶到上限
    assert layout.dialog_width((1000, 640)) == 720   # 850 → 顶到上限
    assert layout.dialog_width((700, 500)) == 595   # 595，区间内
    assert layout.dialog_width((400, 300)) == 420   # 340 → 抬到下限


def test_code_box_size_clamps():
    """代码框 = (窗口宽 60%, 窗口高 55%)，夹 [480,680]×[240,460]。"""
    assert layout.code_box_size((1200, 800)) == (680, 440)  # 720→680 / 440
    assert layout.code_box_size((1000, 640)) == (600, 352)  # 区间内
    assert layout.code_box_size((700, 500)) == (480, 275)   # 420→480 / 275
    assert layout.code_box_size((400, 300)) == (480, 240)   # 双下限


def test_code_box_fits_dialog_at_min_window():
    """不变量：最小窗口下代码框放得进对话框（对话框内容区 = 对话框宽 - 2×S.s3）。"""
    from app.gui.theme import S
    win = (1000, 640)
    dlg = layout.dialog_width(win)
    cw, _ch = layout.code_box_size(win)
    assert cw <= dlg - 2 * S.s3, (
        f"最小窗口下代码框 {cw} 超出对话框内容区 {dlg - 2 * S.s3}——会顶边")


# ---------- P5：C 类 clamp 不变量护栏（章程） ----------

def test_c_class_clamp_invariants_across_window_sizes():
    """P5 护栏（章程）：C 类函数对**任意**窗口尺寸，输出都落在 clamp 区间内。

    扫一大片窗口宽/高（含极小/极大/奇数），断言：
    - dialog_width ∈ [420, 720]
    - code_box w ∈ [480, 680]、h ∈ [240, 460]
    - 且对话框放得进窗口：dialog_width + 2×24(对话框自身 padding) ≤ 窗口宽
      （窗口 ≥ min_width 1000 时恒成立——这是"不顶边"的数学保证）
    谁改了比例/clamp 常量导致某窗口下越界或顶边，立刻红。
    """
    widths = [400, 480, 600, 700, 768, 800, 900, 1000, 1001, 1185, 1200,
              1280, 1600, 1920, 2560, 3840]
    heights = [300, 400, 500, 600, 640, 700, 763, 800, 900, 1080, 1440, 2160]
    for w in widths:
        for h in heights:
            dw = layout.dialog_width((w, h))
            assert 420 <= dw <= 720, f"dialog_width({w},{h})={dw} 越界 [420,720]"
            cw, ch = layout.code_box_size((w, h))
            assert 480 <= cw <= 680, f"code_box_w({w},{h})={cw} 越界 [480,680]"
            assert 240 <= ch <= 460, f"code_box_h({w},{h})={ch} 越界 [240,460]"
            # 不顶边：对话框表面（宽 + 2×24 自身 padding）≤ 窗口宽（窗口≥最小宽时）
            if w >= layout.WINDOW_MIN[0]:
                surface = dw + 2 * 24
                assert surface <= w, (
                    f"窗口 {w} 下对话框表面 {surface} 顶边/超出窗口宽")


def test_screen_work_area_contract():
    """契约：win32 → 正整数逻辑尺寸（或 None）；非 win32 → None（不引入平台依赖）。"""
    sa = layout.screen_work_area()
    if sys.platform == "win32":
        assert sa is None or (
            isinstance(sa, tuple) and len(sa) == 2
            and all(isinstance(v, int) and v >= 400 for v in sa)
        ), f"win32 屏工作区查询返回异常值：{sa!r}"
    else:
        assert sa is None
