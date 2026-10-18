"""设计 token —— docs/Experientia_设计家族.md 的代码实现（deck → token → 页面）。

- deck 是单一事实来源：先改 deck，再改这里，最后改页面。
- 页面禁止裸 hex / 图标混族 / 表外字号（护栏测试 tests/test_theme_guard.py 强制）。
- 字体：西文/数字用内嵌 Manrope（SIL OFL 1.1，assets/fonts/，可变字重单文件）；
  CJK 走系统字体（微软雅黑/苹方/思源黑体）——只按名引用、不打包字体文件，
  无授权风险也无体积成本。
- 历史注：本文件曾含旧 GUI 栈的控件工厂段，Qt 迁移完成后已裁撤（控件工厂归 qt_theme.py）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------- 色板（deck ，从 assets/mascot_* 表情家族逐像素提取推导） ----------------
# 亮/暗双色板：访问 C.xxx 返回当前激活色板的值（metaclass __getattr__ 动态解析）。
# set_mode("dark"/"light") 切换后，重建窗口/重应用全局样式表即整体换肤；
# 页面一律写 C.xxx，禁止裸 hex（护栏 R10）。暗色版文字色在暗底上保持 ≥4.5:1。


class _PaletteMeta(type):
    """类属性访问重定向到激活色板；未命中走正常 AttributeError。"""

    def __getattr__(cls, name: str) -> str:
        if name.startswith("_"):
            raise AttributeError(name)
        pal = cls._active_palette()
        if name in pal:
            return pal[name]
        raise AttributeError(name)


class C(metaclass=_PaletteMeta):
    """设计色板 token（deck）。C.xxx 动态解析当前激活色板。"""

    _PALETTES = {
        "light": {
            # 品牌橙（唯一主色，8 阶平滑过渡）
            "brand_50": "#FFF7ED",    # 极浅橙 tint
            "brand_100": "#FFEDD5",   # 浅杏底
            "brand_200": "#FED7AA",   # 浅橙 tint
            "brand_300": "#FDBA74",   # 中浅橙
            "brand_400": "#FB923C",   # 中橙
            "brand_500": "#F99E51",   # 主色（保持）
            "brand_600": "#EA580C",   # 深橙红
            "brand_700": "#C2410C",   # 强调文字/图标（亮色即主按钮底色值）
            "brand_800": "#9A3412",   # 深橙褐
            "brand_900": "#7C2D12",   # 最深橙褐
            "on_brand": "#FFFFFF",    # 实心品牌底上的白字
            # 实心品牌底（承载 on_brand 白字的按钮/选中底）：两模固定 #C2410C，
            # 与暗色 brand_700(#E8732C 强调文字)解耦，保证白字 5.18:1（P2-3/B1）
            "primary_fill": "#C2410C",
            "primary_fill_hover": "#9A3412",
            # 按下态：比 hover 更深一档，给主 CTA 一个明确的"按下去"回执。
            # 两模同值（同 primary_fill 口径），白字对比度 7.86:1。
            "primary_fill_pressed": "#7C2D12",
            # 暖中性
            "ink_900": "#2A1A12",     # 主文字
            "ink_700": "#4A3527",     # 次级文字/chip 文字
            "ink_500": "#7A6552",     # 辅助文字/占位符（5.33:1）
            "ink_300": "#B4A494",     # 仅非文字：禁用图标/装饰
            "line": "#D8C7B0",        # 描边/分隔线（米白底上可见，否则卡片/空状态框边框看不清）
            "line_strong": "#D2C8BD",  # 交互控件描边（按钮/输入框/复选框；比 line 深一档，米白底上可见）
            "surface": "#FDFBF7",     # 窗口/卡片底
            "surface_2": "#F7F1E8",   # 次级卡片/hover 底
            "surface_3": "#EDE6D5",   # hover 态/下拉菜单
            "surface_hero": "#FFF5EB",  # 报告 hero 区特殊背景
            # 语义色（暖调，底/字均实测 ≥4.5:1）
            "ok_bg": "#ECF7E8", "ok_fg": "#4A7C3F",    # 暖绿
            "warn_bg": "#FEF9C3", "warn_fg": "#854D0E",  # 深黄褐
            "err_bg": "#FBE4DC", "err_fg": "#B3261E",    # 暖红（保持）
            "info_bg": "#E8EEF4", "info_fg": "#4A6FA5",  # 暖蓝
            # 图表专用 6 色板
            "chart_1": "#F99E51",   # 品牌橙，主角数据
            "chart_2": "#E8A84A",   # 暖金黄，次要系列
            "chart_3": "#D4896E",   # 暖棕橙，第三系列
            "chart_4": "#4A7C3F",   # 暖绿，正向/改善
            "chart_5": "#5A7CA8",   # 暖蓝，对比/基准
            "chart_6": "#8B7355",   # 暖褐，中性/基础
            "axis": "#F0E8DE",      # 图表网格线（同旧 CHART_AXIS_COLOR）
        },
        "dark": {
            # 品牌橙：按钮底 / 强调文字在暗底上都有 ≥4.5:1 的折中档
            "brand_50": "#3A2A1C",    # 选中 tab 底（暗版 tint）
            "brand_100": "#4A3322",   # chip / 选中 hover 底
            "brand_200": "#5C3E28",
            "brand_300": "#704A30",
            "brand_400": "#A45A2C",
            "brand_500": "#E08A4E",
            "brand_600": "#F0894A",
            "brand_700": "#E8732C",   # 仅强调文字/图标（暗底可见档）；不再作按钮底
            "brand_800": "#C75F22",
            "brand_900": "#A84E1C",
            "on_brand": "#FFFFFF",
            # 实心品牌底：同亮色固定 #C2410C（不随暗色 brand_700 提亮），
            # 白字 5.18:1 达标（P2-3/B1：两模同一品牌橙，只解耦按钮底用途）
            "primary_fill": "#C2410C",
            "primary_fill_hover": "#9A3412",
            "primary_fill_pressed": "#7C2D12",  # 按下态（M4；口径同亮色）
            # 暖中性（暗底反相）
            "ink_900": "#F3ECE3",     # 主文字（暗底 ~12:1）
            "ink_700": "#D9CFC4",
            "ink_500": "#A99B8C",
            "ink_300": "#6E6357",
            "line": "#3A322B",
            "line_strong": "#483E36",  # 交互控件描边（暗底亮一档，同 line_strong 口径）
            "surface": "#1D1813",
            "surface_2": "#262019",
            "surface_3": "#2F2820",
            "surface_hero": "#2A221A",
            # 语义色（暗底亮字）
            "ok_bg": "#1F3523", "ok_fg": "#9AD98B",
            "warn_bg": "#3A2E18", "warn_fg": "#E8C14E",
            "err_bg": "#3C211C", "err_fg": "#F29B90",
            "info_bg": "#1E2B3A", "info_fg": "#9FC0E8",
            # 图表专用 6 色板（暗底加亮）
            "chart_1": "#F99E51",
            "chart_2": "#E8A84A",
            "chart_3": "#D4896E",
            "chart_4": "#9AD98B",
            "chart_5": "#9FC0E8",
            "chart_6": "#C4A882",
            "axis": "#3A322B",        # 暗底网格线（低干扰）
        },
    }
    _mode = "light"

    @classmethod
    def _active_palette(cls) -> dict:
        return cls._PALETTES.get(cls._mode, cls._PALETTES["light"])

    @classmethod
    def set_mode(cls, mode: str) -> None:
        """切换激活色板（"light"/"dark"；未知值回落亮色）。"""
        cls._mode = mode if mode in cls._PALETTES else "light"

    @classmethod
    def current_mode(cls) -> str:
        return cls._mode


def motion_ok() -> bool:
    """reduced-motion 感知：系统关闭动画（或显式开关）→ False，调用方跳过动效。

    PySide6 6.11 未暴露 QStyleHints.prefersReducedMotion()；Windows 走注册表
    MinAnimate（0 = 关闭窗口动画）；非 Windows 无标准读法，默认放行动效。
    显式开关：环境变量 EXPERIENTIA_REDUCE_MOTION=1。
    """
    if os.environ.get("EXPERIENTIA_REDUCE_MOTION") in ("1", "true", "on"):
        return False
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Control Panel\Desktop\WindowMetrics") as k:
                return winreg.QueryValueEx(k, "MinAnimate")[0] != "0"
        except OSError:
            return True
    return True


def low_fx() -> bool:
    """低特效模式（档 1）：True 时跳过"逐控件图形特效"（卡片投影等）。

    投影走 `QGraphicsDropShadowEffect`，是 CPU 合成的逐控件开销——实测 300 张卡
    的整控件绘制 11 ms → 53 ms（约 5×），故低性能平台可整体关掉。
    **纯装饰、fail-open**：关掉只少一层投影，内容与交互一律不变。

    显式开关：环境变量 `EXPERIENTIA_LOW_FX=1`。与 `motion_ok()` 分开：
    reduced-motion 只关"动"，不关"静态投影"（既有视觉契约不变）。
    """
    return os.environ.get("EXPERIENTIA_LOW_FX") in ("1", "true", "on")


def resolve_theme_mode(mode: str, app=None) -> str:
    """配置值（"light"/"dark"/"system"）→ 激活色板名；system 跟随系统主题。

    Qt 6.5+ 的 QStyleHints.colorScheme() 读系统明暗；取不到/异常回落亮色。
    """
    if mode in ("light", "dark"):
        return mode
    try:
        if app is not None:
            from PySide6.QtCore import Qt

            sh = app.styleHints()
            if (hasattr(sh, "colorScheme")
                    and sh.colorScheme() == Qt.ColorScheme.Dark):
                return "dark"
    except Exception:
        pass
    return "light"


# ---------------- 形状 / 间距 / 字号（deck -） ----------------

class R:
    sm, md, lg, xl = 8, 12, 16, 24


class S:
    s1, s2, s3, s4, s6, s8 = 4, 8, 12, 16, 24, 32


class F:
    # 设计规范（设计家族  / deck）：display 28 / h1 20 / h2 16 / body 14 / caption 12。
    # 迁移期间曾被放大到 36/24/18 并新增 10px micro——违反 R9「禁止 <12px 文字」，
    # 现恢复规范值；micro 收编为 12（badge/图表柱顶标签并入 caption 档）。
    display, h1, h2, body, caption, micro = 28, 20, 16, 14, 12, 12


FONT = "Manrope"
FONT_FALLBACK = "Microsoft YaHei, PingFang SC, Noto Sans CJK SC, sans-serif"

ICON_SIZES = (14, 16, 18, 20, 24)  # 表格 14 / 按钮内 16 / 行内 18 / 卡片 20 / 导航 24


# 设计体系常量（尺寸/时间/阈值，集中管理，业务代码不出现裸数字）
class SIZES:
    # 吉祥物表情尺寸
    MASCOT_NAV = 28           # 导航栏品牌区
    MASCOT_STATUS = 24        # 状态行
    MASCOT_DIALOG_TITLE = 24  # 弹层标题旁
    MASCOT_TOAST = 48         # Snackbar/Toast
    MASCOT_EMPTY = 80         # 空状态
    MASCOT_MILESTONE = 80     # 里程碑遮罩
    MASCOT_DECORATION = 20    # 海报水印、装饰
    MASCOT_MICRO = 20         # 通知列表、悬浮按钮
    MASCOT_NANO = 12          # 通知红点替代
    # 图标尺寸
    ICON_NAV = 24             # 导航栏
    ICON_CARD = 20            # 卡片头部
    ICON_LIST = 18            # 列表行
    ICON_BUTTON = 16          # 按钮内
    ICON_TABLE = 14           # 表格/微标
    # 图表尺寸
    CHART_BAR_H = 14          # 横条高度
    CHART_CELL = 14           # 柱宽
    CHART_AXIS_WIDTH = 1      # 网格线粗细
    # 导航栏
    NAV_WIDTH = 120           # 导航栏宽度
    NAV_BRAND_ICON = 28       # 品牌区图标
    # 内容区
    CONTENT_FORM = 640        # 表单页最大宽度
    CONTENT_REPORT = 720      # 报告页画布宽度
    CONTENT_HOME = 880        # 首页内容列最大宽度（设计方案 V-B1）
    # 导出中心
    EXPORT_ITEM_HEIGHT = 72   # 列表项高度
    EXPORT_ACCENT_WIDTH = 3   # 左侧色条宽度
    # 列表行
    LIST_ROW_HEIGHT = 56      # 列表行高度
    LIST_ICON_BOX = 32        # 图标点击区域


class ANIMATION:
    """动效 token（时长秒 / 缓动名 / 错峰步进）。

    ⚠️ **接线状态（审计）**：下列 token 目前**尚无调用点**，是规划
    交付但"语言建好、动作未接"的部分——**属有意保留**（不是遗漏，也不是死代码）：
    ``DURATION_FAST``（按钮按下反馈）、``DURATION_SLOW``（与 ``DURATION_PAGE`` 重复，
    实际切页走后者）、``DURATION_MILESTONE``、``EASE_IN_CUBIC`` /
    ``EASE_IN_OUT_SINE``、``STAGGER_STEP_MS`` / ``MAX_STAGGER_MS``（内容入场错峰）；
    ``DURATION_FAST`` 对应的按下反馈最终以 **QSS 伪态**落地（即时、零开销），未走动画。
    它们对应「UI 统一化与动效」方案的**第 2 波动效项（M1/M4）**，M1 已接线。
    审计结论见 `Experientia_UI统一化与动效_审计与方案.md` 。
    """

    # 时长（秒）
    DURATION_FAST = 0.10      # 按钮按下（待接线：M4）
    DURATION_NORMAL = 0.15    # hover 过渡
    DURATION_SLOW = 0.20      # 页面切换（历史值；实际切页用 DURATION_PAGE）
    DURATION_DIALOG = 0.30    # 模态框/吉祥物出现
    DURATION_MILESTONE = 1.5  # 里程碑遮罩停留（待接线）
    # 时长补充（与既有 DURATION_* 同单位——秒）
    DURATION_PAGE = 0.24      # 页面切换过渡（AnimatedStack 覆盖层）
    DURATION_HOVER = 0.18     # hover 抬升过渡（hover_lift）
    DURATION_SKELETON = 1.4   # 骨架屏扫光一个周期
    DURATION_STATE = 0.12     # 三态交叉过渡（M3：骨架→内容）
    # 缓动（Flet 侧字符串；Qt 侧用 QEasingCurve(名字) 构造）
    EASE = "ease"
    EASE_OUT = "ease-out"
    EASE_IN_OUT = "ease-in-out"
    LINEAR = "linear"
    SPRING_DAMPING = 0.8      # 吉祥物弹跳阻尼
    # 缓动补充：值用 QEasingCurve 枚举名字符串——Qt 侧须经
    # qt_widgets._ease(name) 转成 QEasingCurve（Qt 不接受字符串构造）
    EASE_OUT_CUBIC = "OutCubic"
    EASE_OUT_QUART = "OutQuart"
    EASE_IN_CUBIC = "InCubic"        # 待接线
    EASE_IN_OUT_SINE = "InOutSine"   # 待接线
    # 错峰入场（列表/网格逐项延迟；待接线：M1）
    STAGGER_STEP_MS = 50
    MAX_STAGGER_MS = 300


class THRESHOLDS:
    # 图表
    BAR_LABEL_MIN_RATIO = 0.30     # 横条长度超过画布 30% 才显示数字
    CHART_GRID_LINES = 3           # 水平网格线数量
    CHART_PEAK_PROMINENCE = 1.5    # 峰值柱判定：超过平均值 1.5 倍
    # 吉祥物
    MILESTONE_IMPROVEMENT = 0.30   # 改善超过 30% 触发 celebrate
    SEARCH_WAIT_SECONDS = 3        # 搜索超过 3 秒显示 think
    # 报告
    NOTE_SAMPLE_MIN = 3            # 样本量 < 3 显示"样本不足"
    NOTE_SAMPLE_CAUTION = 10       # 样本量 3-9 显示黄色提示
    # 骨架屏：取数快于此阈值不显示骨架，避免"闪一下更差"
    SKELETON_MIN_MS = 80

# 图表轴颜色（theme.py 统一导出供 poster.py 使用）
CHART_AXIS_COLOR = "#F0E8DE"

# 语义 tone → 底/字色（原在 hooks_page.py，export_page.py 也依赖，故提至公共层）
TONE_BG = {"err": C.err_bg, "brand": C.brand_100, "warn": C.warn_bg,
           "ok": C.ok_bg, "ink": C.surface_2}
TONE_FG = {"err": C.err_fg, "brand": C.brand_700, "warn": C.warn_fg,
           "ok": C.ok_fg, "ink": C.ink_500}


# ---------------- 结构 token（布局章程：反复出现的"骨架"尺寸，A 类） ----------------
# 收编纪律：裸字面量出现 ≥2 处或属结构骨架（按钮/框/点/描边）必须进本表；
# P0 值与现状一致（像素不变），off-scale 的 10/2/6 是否贴 4px 网格是后续设计决定。
# 正圆容器的圆角 = 边长//2，在调用处算，不另存字面量。


class D:
    BORDER_W = 1      # 全局描边宽（deck ：描边统一 1px line）
    BTN_H = 36        # 主按钮高（btn_* 工厂 + 各页主操作）
    BTN_H_SM = 32     # 页面次按钮高 / 搜索框高
    BTN_H_XS = 28     # 行内小按钮高（列表行 trailing 的轻量操作）
    ICON_BOX = 32     # 图标容器边长（list_row / 导航图标盒）
    BADGE_STEP = 28   # 步骤徽章正圆边长（接入页新增工具卡三步条；圆角 = 值//2）
    MASCOT_LG = 96    # 宇航员大图（空状态 / 欢迎）；圆角 = 值//2
    MASCOT_SM = 32    # 宇航员点缀（状态行 / 回执）；圆角 = 值//2
    DOT = 8           # 状态点边长；圆角 = 值//2
    FIELD_W = 220     # 常规输入框宽（搜索、trunk 等）
    FIELD_W_LG = 280  # 长文案输入框宽（描述类）
    TEXTAREA_H_LG = 96  # 多行正文框高（Hooks「应当」区）
    TEXTAREA_H_SM = 64  # 多行反例框高（Hooks「绝不」区）
    # 对话框宽/代码框宽高是 C 类（窗口派生）：layout.dialog_width /
    # layout.code_box_size（章程），不做 token。
    CODE_BOX_H = 200  # 代码框默认高（对话框内走 C 类 layout.code_box_size）
    URL_BAR_H = 32    # 单行地址条高（P1-3 口径：单行 mono 高 32，与次按钮同高）
    DD_W_XS, DD_W_SM, DD_W, DD_W_MD, DD_W_LG = 140, 160, 180, 200, 260
    # 下拉宽五档（现状值收编；P5 起由 layout.text_width 校验"档位放得下选项"）
    SW_W_SM, SW_W_MD, SW_W_LG = 44, 52, 60  # Switch 控件宽（现状值收编）
    CHIP_PAD_X, CHIP_PAD_Y = 10, 2  # chip 内边距（现状值，off-scale 待设计决定）
    CHART_CELL, CHART_CELL_H, CHART_GAP = 14, 20, 2  # 热力图：格宽/格高/格距
    CHART_BAR_MIN, CHART_BAR_MAX, CHART_BAR_H = 8, 220, 14
    # 累计条：最小宽 / 最大宽（B 类：实际宽 ∝ 数据，夹在两档间）/ 条高
    CHART_LABEL_W_SM, CHART_LABEL_W_MD, CHART_LABEL_W = 64, 86, 130
    # 成长页折柱复合图（重构思）：绘图区高 / 柱宽档 / 折点直径 /
    # 底部周标签区高 / 左侧数值 gutter 宽
    CHART_COMBO_H, CHART_COMBO_COL_W = 168, 34
    CHART_COMBO_DOT, CHART_COMBO_AXIS_H, CHART_COMBO_GUTTER = 9, 40, 40
    # 海报迷你周图（柱+折线）绘图高；海报格子单元高
    CHART_SPARK_H, POSTER_CELL_H = 88, 68
    # 报告海报弹层：宽/高上限（C 类——渲染时按窗口夹取）；
    # POSTER_* = 海报画布内边距/条图骨架（PNG 渲染同值同布局，见 gui/poster.py）
    REPORT_W, REPORT_H, REPORT_LABEL_W = SIZES.CONTENT_REPORT, 620, 88
    POSTER_PAD, POSTER_MASTHEAD_H, POSTER_BAND_H = 24, 10, 12
    POSTER_COL_H, POSTER_COL_GAP = 96, 6
    # 图表定宽标签列（CJK 日期/文本对齐；P5 起由 text_width 校验放得下）
    NAV_GROUP_LABEL_H = 20  # 分组导航组标题行高（章程 ；间距用 S.s2、分隔线用 BORDER_W）
    NAV_ROW_H = 40          # 导航行高（设计方案 V-A1：40±4 区间取整配合 icon 格 32 上下各留 4）
    FOLD_BODY_MAX_H = 400   # Hooks 底部两入口卡正文封顶高（内容超出内部滚动，两卡不悬空）
    DRAWER_W = 360          # 右侧详情抽屉宽（接入页错误详情；窗口过窄时按可用宽夹取）


# 宇航员表情家族（软脸区插画，非图标；deck ：只进有人味场景）
# 12 种表情：smile=默认脸/欢迎，peace=放松/庆祝，think=思考/空状态，
# fail=失败/纠正，sleep=后台/空闲，celebrate=大幅改善/里程碑，
# wave=首次进入/更新提示，search=搜索中/无结果，write=报告生成/记录，
# surprise=惊喜/发现，love=收藏/好评，sweat=超时/卡住
MASCOTS = {
    name: Path(__file__).resolve().parents[2] / "assets" / f"mascot_{name}.png"
    for name in ("smile", "peace", "think", "fail", "sleep",
                 "celebrate", "wave", "search", "write", "surprise", "love", "sweat")
}


def app_icon_file() -> Path:
    """应用图标路径唯一入口：Windows 用 .ico，其余平台用 .png。

    曾散落在 main_window / qt_tray 各算一遍——统一收敛到这里。
    """
    assets = Path(__file__).resolve().parents[2] / "assets"
    ico = assets / "icon_windows.ico"
    png = assets / "icon.png"
    if sys.platform == "win32" and ico.exists():
        return ico
    if png.exists():
        return png
    return ico if ico.exists() else png

# chip 语义色映射（tone → (底, 字)）
_CHIP_TONES = {
    "brand": (C.brand_100, C.ink_700),
    "ok": (C.ok_bg, C.ok_fg),
    "warn": (C.warn_bg, C.warn_fg),
    "err": (C.err_bg, C.err_fg),
    "info": (C.info_bg, C.info_fg),
}


# 热力图 6 档阶梯（P4-01 规格：brand_50/100/500/600/700/800）；零值格用中性底。
# 纯数据 token（Qt 版 qt_theme/qt_widgets 共用）。
# 动态对象：HEAT_SCALE[i] 按激活色板解析（模块导入时冻结亮色会让暗色下图表失配）。


class _HeatScale:
    """热力 6 档色阶（跟随激活色板动态解析）。"""

    _KEYS = ("brand_50", "brand_100", "brand_500",
             "brand_600", "brand_700", "brand_800")

    def __len__(self) -> int:
        return len(self._KEYS)

    def __getitem__(self, idx: int) -> str:
        return C._active_palette()[self._KEYS[idx]]


HEAT_SCALE = _HeatScale()


def _heat_color(v: float, mx: float) -> str:
    """格值 → 6 档色阶（热力图 / 柱状图 / PNG 共用同一口径）。

    纯函数：Qt 版 poster.py 直接引用。
    """
    if v <= 0:
        return C.surface_2
    idx = min(len(HEAT_SCALE) - 1, int(v / mx * (len(HEAT_SCALE) - 1) + 0.5))
    return HEAT_SCALE[idx]


