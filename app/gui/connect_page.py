"""接入页（接入页设计优化方案融合第二稿）——Qt 版。

降噪重构：9 区段收敛成「3 层 + 3 区」，从上到下 =
  接入总况条（签名/第一层）→ 模型与接入（常驻卡：Experientia 自己的 AI 引擎，
  小白接 API / 本地模型的入口）→ ① 已接入 → ② 采集 → ③ 需要你处理 →
  新增工具向导 → 高级设置（第三层折叠：分工具说明 / 注入预览）。

模型卡常驻的由来：接 API / 接本地大模型此前藏在
高级设置折叠里，用户找不到；升为总况条下方的常驻卡，未接模型时卡内自带
大白话双路径引导（云端 API / 本地模型），接上后引导自动收起。

约束：左侧功能导航栏不改动；改动严格限定在接入页主内容区。
状态只用三色语义圆点 + 文字标签（橙只表活跃，需用关注用 warn 黄）；
技术细节（SessionStart 等）默认收进第三层折叠。
"""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QPlainTextEdit, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ._ago import _ago_text, _ts_ago
from .api_client import LocalApi, LocalApiError
from .connect_probe import ProbeCardMixin
from .i18n import t
from .inject_preview import InjectPreviewPage
from .models_page import ModelsPage
from .page_base import PageBase, page_scaffold, parallel_fetch
from .qt_icons import icon_glyph, icon_font
from .qt_theme import (btn_flat, btn_pill, btn_primary, btn_secondary, card,
                       chip, code_box, collapse_header, divider, icon_button,
                       icon_widget, mascot_image, mono, row_select_button,
                       row_select_style, status_dot, status_tone, switch,
                       txt, url_bar)
from .qt_widgets import RotatingIcon, page_header
from .theme import ANIMATION, C, D, F, FONT, R, S, SIZES, TONE_FG, motion_ok

# agent 显示名统一从 proxy/detect.py 导入，避免两处维护
from ..proxy.detect import agent_display_name as _agent_display

# 分工具说明（分区 2）：生态词保留原文；机制按官方文档核实
_CODING_TOOLS = (
    "Claude Code", "Codex", "CodeBuddy", "Cursor", "Gemini CLI", "OpenCode",
)
_HARNESS_TOOLS = (
    "DeepSeek Harness", "OpenClaw", "Hermes", "WorkBuddy",
)

# 工具名（生态词，不进 i18n）→ 说明文字键（zh 源串，：key = 中文源串）。
# 术语降级（方案）：SessionStart/UserPromptSubmit/PostToolUse 等裸钩子名
# 收进「高级」标注，正文用平实名（开始任务时记录等）。
_TOOL_DESC = {
    "Claude Code": "把环境变量 ANTHROPIC_BASE_URL 指到上面的地址（ANTHROPIC_API_KEY 填本页的接入令牌；真正生效的 Key 是你在 Experientia 里配的模型）。",
    "Codex": "在配置文件 ~/.codex/config.toml 里加一段 [model_providers.experientia]：base_url 填上面的地址、wire_api = \"chat\"，再在文件顶部把 model_provider 设为 experientia。",
    "CodeBuddy": "在 ~/.codebuddy/models.json 的 models 里加一条模型，url 填 http://127.0.0.1:8100/v1/chat/completions（必须是完整接口路径），apiKey 填本页的接入令牌。",
    "Cursor": "暂不支持自定义地址（只接受官方模型的 Key，且请求经 Cursor 服务器中转），无法指到这里；它的会话可自动记录，见下方「采集」。",
    "Gemini CLI": "只支持官方 Gemini 协议，没有可改的兼容地址入口，无法指到这里；它的会话可自动记录，见下方「采集」。",
    "OpenCode": "在项目 opencode.json 加自定义 provider：npm 用 @ai-sdk/openai-compatible，options.baseURL 填上面的地址再加 /v1，apiKey 填本页的接入令牌，模型 ID 填你配的模型名；它的会话可自动记录，见下方「采集」。（模型列表见 /v1/models）",
    "DeepSeek Harness": "把环境变量 DEEPSEEK_BASE_URL 指到上面的地址（或在配置里设 baseURL），Key 填本页的接入令牌。",
    "OpenClaw": "在配置里加一个自定义 provider（models.providers 下）：baseUrl 填上面的地址、api 选 openai-completions、Key 填本页的接入令牌，再选它作为模型。",
    "Hermes": "在 ~/.hermes/.env 里设 OPENAI_BASE_URL 为上面的地址，OPENAI_API_KEY 填本页的接入令牌（或在 hermes model 里选 Custom endpoint）。",
    "WorkBuddy": "设置 → 模型 → 添加自定义模型：URL 填上面的地址、Key 填本页的接入令牌、模型名任选。",
}

# 每工具一个专有图标（MDI 名，icon_widget 自动经 FT 映射）：装饰性、以区分度
# 为主，替代旧版的同质方块；未命中回落通用 console。生态词工具名不进 i18n。
_TOOL_ICON = {
    "Claude Code": "robot-outline",
    "Codex": "code-tags",
    "CodeBuddy": "code-braces",
    "Cursor": "cursor-move",
    "Gemini CLI": "star-four-points",
    "OpenCode": "code-json",
    "DeepSeek Harness": "tools",
    "OpenClaw": "paw",
    "Hermes": "run-fast",
    "WorkBuddy": "briefcase-outline",
}

# 不支持自定义代理地址、只走官方接口的工具：说明区用中性 chip 常驻标注，
# 避免用户误以为是自己配置错了（Orange-as-live-only：不表状态色，只表信息）。
_ONLY_OFFICIAL = ("Cursor", "Gemini CLI")

# 分工具向导（左右分栏）：把上面长句里
# "改哪里"结构成三字段——kind（人读分类，zh 源串走 t()，AST 抓不到须手工
# 登记 i18n）/ target（文件或环境变量名，数据不译）/ code（配置片段，数据
# 不译，；<TOKEN> 占位符指页头接入令牌，步骤话术里用 t() 说明）。
# 原长句不删：降级为详情面板底部的补充说明，信息零丢失。
# 仅官方工具无向导条目（详情 = 仅官方接入 chip + 长句）。
_TOOL_GUIDE = {
    "Claude Code": ("环境变量", "ANTHROPIC_BASE_URL",
                    "ANTHROPIC_BASE_URL = http://127.0.0.1:8100\n"
                    "ANTHROPIC_API_KEY = <TOKEN>"),
    "Codex": ("配置文件", "~/.codex/config.toml",
              "[model_providers.experientia]\n"
              'base_url = "http://127.0.0.1:8100"\n'
              'wire_api = "chat"\n\n'
              'model_provider = "experientia"'),
    "CodeBuddy": ("配置文件", "~/.codebuddy/models.json",
                  '"url": "http://127.0.0.1:8100/v1/chat/completions",\n'
                  '"apiKey": "<TOKEN>"'),
    "OpenCode": ("配置文件", "opencode.json",
                 '"provider": { "experientia": {\n'
                 '  "npm": "@ai-sdk/openai-compatible",\n'
                 '  "options": { "baseURL": "http://127.0.0.1:8100/v1",\n'
                 '               "apiKey": "<TOKEN>" } } }'),
    "DeepSeek Harness": ("环境变量", "DEEPSEEK_BASE_URL",
                         "DEEPSEEK_BASE_URL = http://127.0.0.1:8100\n"
                         "Key = <TOKEN>"),
    "OpenClaw": ("配置文件", "models.providers",
                 "models.providers.experientia = {\n"
                 '  baseUrl: "http://127.0.0.1:8100",\n'
                 '  api: "openai-completions", key: "<TOKEN>" }'),
    "Hermes": ("环境变量", "~/.hermes/.env",
               "OPENAI_BASE_URL = http://127.0.0.1:8100\n"
               "OPENAI_API_KEY = <TOKEN>"),
    "WorkBuddy": ("软件内设置", "",
                  "URL = http://127.0.0.1:8100\n"
                  "Key = <TOKEN>"),
}



class ConnectPage(ProbeCardMixin, PageBase):
    """接入页：总况条 + 已接入 + 采集 + 需处理 + 新增工具向导 + 高级设置。"""

    def __init__(self, api: LocalApi, parent: QWidget | None = None):
        super().__init__(api, parent)
        self._build()
        # 懒加载下构建阶段零 API：数据由主窗口的延迟 refresh（_select_page）填充

    # ---------- 构建 ----------

    def _build(self) -> None:
        # 构建阶段不调 API（懒加载下首帧零阻塞）：proxy_url/黄标由 refresh 填充。
        # 默认地址兜底（端口可被配置改，refresh 时若变化会更新地址条）。
        self._flags = {}
        self._proxy_url = "http://127.0.0.1:8100"
        self._last_probe = {}
        self._last_keys = None
        self._keys_group_expanded: dict = {}
        self._keys_group_full: dict = {}
        self._keys_box: QWidget | None = None

        self.content = QWidget()
        self._cl = QVBoxLayout(self.content)
        self._cl.setContentsMargins(0, 0, 0, 0)
        self._cl.setSpacing(S.s4)

        # 统一页头（S1）：标题 + 吉祥物 + 页面级说明（副标题）。
        # 页面级说明（小白友好）：一句话说清这页是干什么的、哪些要管、哪些不用管。
        # 放在总况条之上，让第一次进来的人先看懂"我在哪、该干嘛"，再看状态。
        # 副作用（有意统一）：说明字号由 F.body(14) 归到全站页头副标题口径 caption(12)。
        head = page_header(
            t("接入"),
            t("把你在用的 AI 工具接进来，Experientia 就能记录它们的经验、下次自动带上。"
              "大多数工具不用你做任何事；只有标了黄色的，才需要点一下。"),
            mascot="search")
        self._connect_heading = head.findChild(QLabel, "pageTitle")
        self._connect_mascot = head.findChild(QLabel, "pageMascot")
        self._page_sub = head.findChild(QLabel, "pageSubtitle")
        self._cl.addWidget(head)

        # ── 第一层：接入总况条（签名元素：健康度 + 核心地址 + 采集 n/m + 待处理）──
        self._cl.addWidget(self._build_overview())

        # ── 模型与接入（常驻卡）：Experientia 自己的 AI 引擎从哪来 ──
        # 接 API / 本地模型是高频要找的入口，不再收进
        # 高级设置折叠。未接模型时卡内自动亮出大白话双路径引导（ModelsPage 管理）。
        self._models = ModelsPage(self.api, self, embedded=True)
        self._cl.addWidget(card(content=self._models.content, secondary=True))

        # ── 第二层 ①：已接入 agent 清单（谁被接进来了）──
        self._cl.addWidget(self._build_agents())

        # ── 第二层 ②：采集开关（现在谁在记录）──
        self._cl.addWidget(self._build_capture())

        # ── Claude Code 实时钩子（作用域子集卡，置于 ①② 通用 payoff 之后）──
        # 这页服务所有在用工具的用户，而钩子只服务 Claude Code 一家。顶部先回答
        # 所有用户的问题（谁接进来了 / 谁在记录），再给子集工具的特有增强；
        # 卡内按探测结果自适应（未在用 Claude Code 时默认收起，不占首屏）。
        self._connect_card = self._build_connect_card()
        self._cl.addWidget(self._connect_card)

        # ── 第二层 ③：需要你处理（仅异常时渲染，按类型聚合）──
        self._action_card = card(title=t("需要你处理"), visible=False)
        self._action_card_title = self._action_card.layout().itemAt(0).widget()
        self._action_layout = self._action_card.layout()
        self._cl.addWidget(self._action_card)

        # ── 新增工具向导（醒目：编号步骤 + 连接码 + 大号主按钮）──
        self._cl.addWidget(self._build_probe_card())

        # ── 第三层：高级设置（折叠：分工具说明 / 模型 / 注入预览）──
        self._cl.addWidget(self._build_advanced())

        # 尾部 stretch：内容不足时靠顶排布，避免卡片被视口拉高（同 home 收尾）
        self._cl.addStretch(1)

        # 右侧详情抽屉（parent = 本页根；随页面重建，覆盖右缘，默认隐藏）
        self._drawer = None

        self._wrap_scroll()

    def _wrap_scroll(self) -> None:
        """用 page_scaffold 包装内容层，居中 + 最大宽度限制。

        抽屉挂在外层 self（页面根，非滚动内容）上，才能覆盖整页右缘、
        不被滚动 viewport 裁剪。"""
        # S2：统一骨架（顶边 32px 由页头给）
        scroll = page_scaffold(self._cl, top=0)
        self._layout.addWidget(scroll, 1)
        # 抽屉：父 = 页面根（self），覆盖右缘。构建时页面尚未入窗（宽 0），
        # 首次打开时按实时窗口尺寸定位（Drawer._reposition 每次打开重算）。
        if self._drawer is None:
            from .qt_theme import drawer as _drawer_factory

            self._drawer = _drawer_factory(t("详情"), self,
                                           on_close=self._on_drawer_close)

    # ---------- 第一层：接入总况条（签名元素） ----------

    def _build_overview(self) -> QWidget:
        """接入总览条（第一层签名元素）。

        顶栏讲"工具"而非"引擎"：主信息 = 实时「已接入 N 个工具」计数（切工具 /
        换模型时随 refresh 自动更新）+ 去管理胶囊；地址条整宽；引擎态 / 采集 /
        待处理降为底部一行小字（引擎正常不抢眼，连不上才变红）。"""
        c = card(secondary=True)
        lay = c.layout()
        lay.setSpacing(S.s2)

        # 上排：连接计数（主信息，左对齐）+ 去管理胶囊（紧邻主信息，不再顶到最右）
        top = QHBoxLayout()
        top.setSpacing(S.s2)
        self._ov_status_dot = status_dot("ok")
        top.addWidget(self._ov_status_dot, 0, Qt.AlignVCenter)
        self._ov_status_txt = txt(t("已接入 {n} 个工具", n=0), F.h2, 700)
        top.addWidget(self._ov_status_txt, 0, Qt.AlignVCenter)
        self._ov_go_btn = btn_pill(t("去管理"), "SETTINGS_OUTLINED",
                                   on_click=lambda: self.go("hooks"))
        top.addWidget(self._ov_go_btn, 0, Qt.AlignVCenter)
        top.addStretch(1)
        top_box = QWidget()
        top_box.setLayout(top)
        lay.addWidget(top_box)

        # 中排：核心地址（整宽）+ 复制
        mid = QHBoxLayout()
        mid.setSpacing(S.s2)
        self._url_bar = url_bar(self._proxy_url)
        mid.addWidget(self._url_bar, 1)
        self._copy_btn = icon_button("CONTENT_COPY_OUTLINED", t("复制地址"),
                                     on_click=self._copy_url, color=C.ink_500)
        self._copy_icon = self._copy_btn.findChild(QLabel)
        mid.addWidget(self._copy_btn)
        self._copied_txt = txt("", F.caption, color=C.ok_fg)
        mid.addWidget(self._copied_txt)
        mid_box = QWidget()
        mid_box.setLayout(mid)
        lay.addWidget(mid_box)

        # 8100 默认强制鉴权——外部 agent 的
        # apiKey/API_KEY/x-api-key 都要填这个令牌，接入页必须可见可复制
        self._proxy_token_str = str(getattr(self.api, "_token", "") or "")
        self._token_row = QWidget()
        tl = QHBoxLayout(self._token_row)
        tl.setSpacing(S.s2)
        self._token_lbl = txt("", F.caption, color=C.ink_500)
        tl.addWidget(self._token_lbl)
        self._token_copy_btn = icon_button(
            "CONTENT_COPY_OUTLINED", t("复制令牌"),
            on_click=self._copy_token, color=C.ink_500)
        tl.addWidget(self._token_copy_btn)
        self._token_copied_txt = txt("", F.caption, color=C.ok_fg)
        tl.addWidget(self._token_copied_txt)
        tl.addStretch(1)
        lay.addWidget(self._token_row)
        self._token_hint = txt(
            "", F.caption, color=C.ink_500)
        self._token_hint.setWordWrap(True)
        lay.addWidget(self._token_hint)
        self._render_token_row()

        # 下排：引擎态（小字）+ 采集 n/m + 待处理 n（异常才显，不给假数字）
        bot = QHBoxLayout()
        bot.setSpacing(S.s2)
        self._ov_engine_txt = txt("", F.caption, color=C.ink_500)
        bot.addWidget(self._ov_engine_txt)
        self._ov_capture_chip = txt("", F.caption, 600, C.ink_700)
        bot.addWidget(self._ov_capture_chip)
        self._ov_pending_box = QWidget()
        _pb = QHBoxLayout(self._ov_pending_box)
        _pb.setContentsMargins(0, 0, 0, 0)
        _pb.setSpacing(S.s1)
        self._ov_pending_dot = status_dot("warn")
        _pb.addWidget(self._ov_pending_dot)
        self._ov_pending_txt = txt("", F.caption, 600, C.warn_fg)
        _pb.addWidget(self._ov_pending_txt)
        self._ov_pending_box.setVisible(False)  # 无异常不显示「待处理 0」（不给假数字）
        bot.addWidget(self._ov_pending_box)
        bot.addStretch(1)
        bot_box = QWidget()
        bot_box.setLayout(bot)
        lay.addWidget(bot_box)
        return c

    def _refresh_overview(self, connected_n: int, running: bool,
                          enabled_n: int, total_n: int,
                          pending_n: int) -> None:
        """接入总览刷新：已接入 N 个工具（主）+ 引擎态（小字）+ 采集 n/m + 待处理 n。

        主信息 = 连接计数（切工具 / 换模型时随 refresh 自动更新）；运行态降级为
        小字——正常灰"运行中"不抢眼，连不上才变红"未连接"。"""
        self._ov_status_dot = self._swap_dot(
            self._ov_status_dot, "ok" if connected_n > 0 else "ink")
        self._ov_status_txt.setText(t("已接入 {n} 个工具", n=connected_n))
        if running:
            self._ov_engine_txt.setText(t("运行中"))
            status_tone(self._ov_engine_txt, C.ink_500)
        else:
            self._ov_engine_txt.setText(t("未连接"))
            status_tone(self._ov_engine_txt, C.err_fg)
        self._ov_capture_chip.setText(t("采集 {n}/{m}", n=enabled_n, m=total_n))
        if pending_n > 0:
            self._ov_pending_txt.setText(t("待处理 {n}", n=pending_n))
            self._ov_pending_box.setVisible(True)
        else:
            self._ov_pending_box.setVisible(False)

    @staticmethod
    def _swap_dot(old: QLabel, tone: str) -> QLabel:
        """替换圆点（同位置换色）：旧 dot 移出布局由调用方布局持有，这里返回新 dot。

        调用方需把新 dot 放回旧 dot 的布局位置——总况条圆点位置固定，
        直接对旧 dot 改样式更省：就地改色即可（避免布局重排）。"""
        colors = {"ok": C.ok_fg, "warn": C.warn_fg, "err": C.err_fg,
                  "info": C.info_fg, "brand": C.brand_700, "ink": C.ink_500}
        s = D.DOT
        old.setStyleSheet(
            f"background: {colors.get(tone, C.ink_500)};"
            f" border-radius: {s // 2}px; border: none;")
        return old

    def _copy_url(self) -> None:
        try:
            QApplication.clipboard().setText(self._proxy_url)
            self._copied_txt.setText(t("已复制"))
            self._set_copy_icon("check", C.ok_fg)
            QTimer.singleShot(1500, self._revert_copy)
        except Exception:
            pass

    # ---------- H4：接入令牌行（8100 默认鉴权后的取钥入口） ----------

    def _render_token_row(self) -> None:
        """令牌脱敏显示 + 可见性跟 token 走（引擎未跑/token 取不到 → 整行隐藏）。"""
        tok = getattr(self, "_proxy_token_str", "") or ""
        visible = bool(tok)
        self._token_row.setVisible(visible)
        self._token_hint.setVisible(visible)
        if not visible:
            return
        masked = f"{tok[:4]}…{tok[-4:]}" if len(tok) > 8 else tok
        self._token_lbl.setText(t("接入令牌：{tok}", tok=masked))
        self._token_hint.setText(t("外部 agent 接 8100 时，apiKey / API_KEY / "
                                   "x-api-key 填这个令牌；填错会被拒绝"))

    def _copy_token(self) -> None:
        try:
            QApplication.clipboard().setText(self._proxy_token_str)
            self._token_copied_txt.setText(t("已复制"))
            QTimer.singleShot(1500, self._clear_token_copied)
        except Exception:
            pass

    def _clear_token_copied(self) -> None:
        """令牌复制提示清除：页面可能已销毁，静默跳过。"""
        try:
            self._token_copied_txt.clear()
        except RuntimeError:
            pass

    def _revert_copy(self) -> None:
        """复制提示复原：QTimer.singleShot 可能在本页
        已销毁（语言/主题切换）后才到，C++ 对象失效时静默跳过。"""
        try:
            self._set_copy_icon("content-copy", C.ink_500)
            self._copied_txt.setText("")
        except RuntimeError:
            pass

    def _set_copy_icon(self, mdi_name: str, color: str) -> None:
        self._copy_icon.setFont(icon_font(18))
        self._copy_icon.setText(icon_glyph(mdi_name))
        self._copy_icon.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")

    # ---------- 接入（Claude Code 实时 Hook：一键配置接入/移除/插件包） ----------

    def _build_connect_card(self) -> QWidget:
        """Claude Code 实时钩子卡：自定义标题行 + 可折叠正文（作用域子集卡）。

        这页服务**所有**在用工具的用户，而本卡只服务 Claude Code 一家的用户，
        故按「子集卡」范式处理（同新增工具卡的「读不到的工具专用」chip）：
        - 标题不撞页标题「接入」，改点明对象的「实时钩子（Claude Code）」；
        - 标题行右侧挂作用域 chip「Claude Code 专用」，非 Claude 用户一眼可辨；
        - 正文（说明 + 状态 + 按钮）可折叠，默认态随探测结果自适应——
          在跑 Claude Code → 默认展开（给它最高价值的动作）；未在用 →
          默认收起（只留标题行，不占首屏、不误导），点头像可展开。
        """
        from .qt_widgets import RotatingIcon

        c = card(secondary=True)  # 无 title：自建标题行（标题 + chip + 折叠箭头）
        lay = c.layout()

        # 标题行：标题（不撞页标题）+ 作用域 chip（Claude Code 专用）+ 折叠箭头。
        # 卡内边距（card 工厂 S.s4）已处理缩进，标题行自身 margins 归零，
        # 让标题与正文左缘对齐。
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(S.s2)
        self._guide_card_title = txt(t("实时钩子（Claude Code）"), F.h2, 600,
                                     C.ink_700)
        title_row.addWidget(self._guide_card_title, 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        self._connect_scope_chip = self._neutral_chip(t("Claude Code 专用"))
        title_row.addWidget(self._connect_scope_chip, 0, Qt.AlignVCenter)
        self._connect_expand_icon = RotatingIcon("EXPAND_MORE_OUTLINED", 18,
                                                 C.ink_500)
        title_row.addWidget(self._connect_expand_icon, 0, Qt.AlignVCenter)
        title_box = QWidget()
        title_box.setObjectName("connectCardHeader")
        title_box.setCursor(Qt.PointingHandCursor)
        title_box.setAttribute(Qt.WA_Hover, True)
        title_box.setLayout(title_row)
        title_box.mousePressEvent = lambda e: self._toggle_connect_card()
        lay.addWidget(title_box)

        # 正文（说明 + 状态 + 按钮 + 插件包 + 尾注）：整体可折叠
        body = QWidget()
        self._connect_body = body
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, S.s1, 0, 0)
        body_lay.setSpacing(S.s3)

        self._guide_desc = txt(
            t("除了把地址指过去（见上方总况条），Claude Code 还能装一个实时钩子："
              "装上后，它每次开始任务、收到你的消息时都会主动把经验交给 Experientia，"
              "比只改地址更及时。点下方按钮一键装好。"),
            F.body, color=C.ink_700, wrap=True)
        body_lay.addWidget(self._guide_desc)

        # hook 状态行（已生效 / 已写入 / 未配置 / 配置失败）
        hook_status = txt("", F.caption, color=C.ink_500)
        hook_msg = txt("", F.caption, color=C.info_fg)
        self._hook_status_txt = hook_status
        self._hook_msg = hook_msg

        # 按钮行：主操作「一键配置接入」实心 btn_primary；移除弱化；插件包次级
        btn_row = QHBoxLayout()
        btn_row.setSpacing(S.s2)
        self._cfg_btn = btn_primary(t("一键配置接入"), "NOTIFICATIONS_ACTIVE_OUTLINED",
                                    self.do_hook_apply)
        btn_row.addWidget(self._cfg_btn)
        self._remove_btn = btn_flat(t("移除"), on_click=self.do_hook_remove)
        self._remove_btn.setFixedHeight(D.BTN_H)
        btn_row.addWidget(self._remove_btn)
        # C-2b：官方插件包（.claude-plugin，取代改全局 settings.json 的安装形态）
        # 图标用 MDI kebab-case 名（PACKAGE_VARIANT 不在 FT 映射里，会静默无图标）
        self._plugin_btn = btn_secondary(t("插件包"), "package-variant",
                                         self.do_plugin_generate)
        btn_row.addWidget(self._plugin_btn)
        btn_row.addStretch(1)
        btn_box = QWidget()
        btn_box.setLayout(btn_row)
        body_lay.addWidget(btn_box)
        body_lay.addWidget(hook_status)
        body_lay.addWidget(hook_msg)

        # 插件包生成结果：安装命令 + 复制
        self._plugin_copy_cmd = ""
        self._plugin_row = QWidget()
        _prow = QHBoxLayout(self._plugin_row)
        _prow.setContentsMargins(0, 0, 0, 0)
        _prow.setSpacing(S.s2)
        self._plugin_cmd_txt = txt("", F.caption, color=C.ink_700)
        self._plugin_cmd_txt.setWordWrap(True)
        _prow.addWidget(self._plugin_cmd_txt, 1)
        self._plugin_copy_btn = btn_secondary(
            t("复制命令"), "CONTENT_COPY_OUTLINED", self._copy_plugin_cmd)
        _prow.addWidget(self._plugin_copy_btn)
        self._plugin_row.hide()
        body_lay.addWidget(self._plugin_row)

        self._not_proxy_txt = txt(
            t("装了钩子的工具，即使不改地址、不走代理，经验也会自动带上"),
            F.caption, color=C.ink_500, wrap=True)
        body_lay.addWidget(self._not_proxy_txt)

        lay.addWidget(body)

        # 折叠状态：默认展开（首帧给足信息），refresh 时按探测结果自适应
        # （见 _apply_connect_default）；_user_toggled 记住用户手动选择，
        # 避免后续 refresh 覆盖用户的展开/收起。
        self._connect_expanded = True
        self._connect_user_toggled = False
        self._set_connect_body_visible(True)
        return c

    def _set_connect_body_visible(self, visible: bool) -> None:
        """折叠/展开正文（箭头随状态旋转到 0°/180°，reduced-motion 直落）。"""
        self._connect_expanded = visible
        self._connect_body.setVisible(visible)
        target = 180 if visible else 0
        if not motion_ok():
            self._connect_expand_icon.setRotation(target)
            return
        if getattr(self, "_connect_chevron_anim", None) is not None:
            self._connect_chevron_anim.stop()
        anim = QPropertyAnimation(self._connect_expand_icon, b"rotation", self)
        anim.setDuration(int(ANIMATION.DURATION_NORMAL * 1000))
        anim.setStartValue(self._connect_expand_icon.rotation)
        anim.setEndValue(target)
        anim.start()
        self._connect_chevron_anim = anim

    def _toggle_connect_card(self) -> None:
        """标题行点击：手动切换展开/收起（记住用户选择，refresh 不再覆盖）。"""
        self._connect_user_toggled = True
        self._set_connect_body_visible(not self._connect_expanded)

    def _apply_connect_default(self, claude_in_use: bool) -> None:
        """按探测结果自适应默认展开态（用户手动选择优先）。

        在跑 Claude Code → 展开（给它这页最高价值的动作）；未在用 → 收起
        （只留标题行，不占首屏）。用户已手动切换过则尊重其选择，不再覆盖。"""
        if self._connect_user_toggled:
            return
        self._set_connect_body_visible(claude_in_use)

    def refresh_hooks(self, data: dict | None = None) -> None:
        try:
            st = data if data is not None else self.api.hooks_config()
        except LocalApiError as exc:
            # SYS-5：引擎未连接时若按"未配置"展示会误导用户（以为从没接入过）。
            # 显式标"配置失败"并留 _last_error；绝不假装未配置。
            self._hook_status_txt.setText(t("配置失败：{err}", err="未连接"))
            status_tone(self._hook_status_txt, C.err_fg)
            self.report_error(t("hook 状态读取失败：{err}", err=exc.localized()))
            return
        if st.get("configured"):
            obs = st.get("observed") or {}
            ago = st.get("last_observed_ago_s")
            # 术语降级（方案）：裸钩子名（SessionStart 等）→平实名，复用 hooks_page 的映射
            from .hooks_page import _event_plain
            events_txt = _event_plain(", ".join(st.get("events", [])))
            if obs and ago is not None:
                # {ago} 来自 _ago_text，本身已含「前/ago」，模板不再叠加，避免「前前」
                self._hook_status_txt.setText(t(
                    "已生效：{events} → {path}（{ago}收到 hook 事件）",
                    events=events_txt, path=st.get("path", ""),
                    ago=_ago_text(ago)))
                status_tone(self._hook_status_txt, C.ok_fg)
            else:
                self._hook_status_txt.setText(t(
                    "已写入配置：{events}。重启 Claude Code 并开始一次会话后自动验证",
                    events=events_txt))
                status_tone(self._hook_status_txt, C.warn_fg)
        else:
            self._hook_status_txt.setText(t(
                "未配置——点「配置接入」一键写入 {path}（可重复执行，可移除）",
                path=st.get("path", "~/.claude/settings.json")))
            status_tone(self._hook_status_txt, C.ink_500)

    def do_hook_apply(self) -> None:
        self.run_async(self.api.hooks_apply,
                       self._on_hook_applied, self._on_hook_failed)

    def do_hook_remove(self) -> None:
        self.run_async(self.api.hooks_remove,
                       self._on_hook_removed, self._on_hook_failed)

    def _on_hook_applied(self, r: dict) -> None:
        self.refresh_hooks()
        self._hook_msg.setText(t(
            "已写入 {path}（事件：{events}）",
            path=r.get("path", ""),
            events=", ".join(r.get("events", []))))
        self._set_hook_msg_color(C.ok_fg)

    def _on_hook_removed(self, _r: dict) -> None:
        self.refresh_hooks()
        self._hook_msg.setText(t("已移除接入"))
        self._set_hook_msg_color(C.ok_fg)

    def _on_hook_failed(self, err: str) -> None:
        self._hook_msg.setText(t("配置失败：{err}", err=err))
        self._set_hook_msg_color(C.err_fg)

    # ---------- C-2b：Claude 官方插件包（.claude-plugin） ----------

    def do_plugin_generate(self) -> None:
        self.run_async(self.api.plugin_generate,
                       self._on_plugin_generated, self._on_plugin_failed)

    def _on_plugin_generated(self, r: dict) -> None:
        path = str(r.get("dir") or "")
        cmd = str(r.get("install_hint") or "")
        self._plugin_copy_cmd = cmd
        self._plugin_cmd_txt.setText(t("在新终端运行：{cmd}", cmd=cmd))
        self._set_plugin_copy_label(t("复制命令"))
        self._plugin_row.show()
        self._hook_msg.setText(t("插件包已生成到 {path}", path=path))
        self._set_hook_msg_color(C.ok_fg)

    def _on_plugin_failed(self, err: str) -> None:
        self._plugin_row.hide()
        self._hook_msg.setText(t("插件包生成失败：{err}", err=err))
        self._set_hook_msg_color(C.err_fg)

    def _set_plugin_copy_label(self, text: str) -> None:
        """更新复制按钮可见文字：它是带图标按钮（btn_secondary），可见文字由
        子 QLabel 渲染、按钮自身 text 已被 _apply_btn_icon 清空——直接对按钮
        setText 会双绘重影且「已复制」反馈不显示。"""
        lay = self._plugin_copy_btn.layout()
        lab = lay.itemAt(1).widget() if lay is not None else None
        if isinstance(lab, QLabel):
            lab.setText(text)
        else:
            self._plugin_copy_btn.setText(text)

    def _copy_plugin_cmd(self) -> None:
        try:
            QApplication.clipboard().setText(self._plugin_copy_cmd)
            self._set_plugin_copy_label(t("已复制"))
            QTimer.singleShot(1500, self._revert_plugin_copy)
        except Exception:
            pass

    def _revert_plugin_copy(self) -> None:
        try:
            self._set_plugin_copy_label(t("复制命令"))
        except RuntimeError:
            pass

    def _set_hook_msg_color(self, color: str) -> None:
        self._hook_msg.setStyleSheet(
            f"color: {color}; border: none; background: transparent;")

    # ---------- 第二层 ①：已接入 agent 清单 ----------

    def _build_agents(self) -> QWidget:
        c = card(title=t("已接入的 AI 工具"))
        self._agents_card_title = c.layout().itemAt(0).widget()
        lay = c.layout()
        lay.setSpacing(S.s1)
        self._agent_empty = txt(
            t("还没发现你在用的 AI 工具。随便挑一个工具跑个任务，这里就会自动出现它。"),
            F.caption, color=C.ink_500, italic=True, wrap=True)
        lay.addWidget(self._agent_empty)
        self._agent_list = QWidget()
        self._agent_layout = QVBoxLayout(self._agent_list)
        self._agent_layout.setContentsMargins(0, 0, 0, 0)
        self._agent_layout.setSpacing(S.s1)
        lay.addWidget(self._agent_list)
        return c

    def _refresh_agents(self, agents: dict, cap_items: dict, flags: dict,
                        encrypted: dict) -> None:
        """① 已接入清单：状态圆点 + 名称 + n 个会话 + 右侧 chip；问题项置顶高亮。"""
        self._clear(self._agent_layout)
        detected = [a for a in agents if agents[a] > 0]
        if not detected:
            self._agent_empty.setVisible(True)
            return
        self._agent_empty.setVisible(False)
        rows = []
        for name in detected:
            sess_n = agents[name]
            ci = cap_items.get(name, {})
            yellow = flags.get(name, 0)
            is_enc = encrypted.get(name, False)
            enabled = ci.get("enabled", True) is not False
            display = _agent_display(name)
            # 状态判定（解析失败→检测不到记录）
            if yellow >= 3:
                tone, label = "warn", t("检测不到记录")
            elif is_enc:
                tone, label = "info", t("已加密，走代理")
            elif not enabled:
                tone, label = "ink", t("已暂停")
            else:
                tone, label = "ok", t("正常")
            rows.append((name, display, sess_n, tone, label, is_enc,
                         bool(yellow >= 3), enabled, ci))
        # 排序：问题项（warn/err）置顶，其余按名称
        order = {"warn": 0, "err": 1, "info": 2, "ink": 3, "ok": 4}
        rows.sort(key=lambda r: (order.get(r[3], 9), r[1]))
        for (name, display, sess_n, tone, label, is_enc, has_issue,
             enabled, ci) in rows:
            row = QHBoxLayout()
            row.setSpacing(S.s2)
            row.addWidget(status_dot(tone))
            row.addWidget(txt(display, F.body, 600))
            row.addWidget(txt(t("{n} 个会话", n=sess_n), F.caption,
                              color=C.ink_500))
            row.addStretch(1)
            if tone in ("warn", "err"):
                # 问题项：右侧 chip(warn) + 高亮底（置顶高亮）
                row.addWidget(self._chip(t("检测不到记录"), "warn"))
            elif is_enc:
                row.addWidget(self._chip(t("已加密，走代理"), "info"))
            elif not enabled:
                row.addWidget(self._chip(t("已暂停"), "brand"))
            # 行内动作统一进 ⋯ 菜单
            more = icon_button("dots-vertical", t("更多操作"),
                               lambda _=False, n=name, d=display:
                               self._agent_menu(n, d))
            row.addWidget(more)
            row_box = QWidget()
            row_box.setObjectName("agentRow")
            if tone in ("warn", "err"):
                row_box.setStyleSheet(
                    f"QWidget#agentRow {{ background: {C.surface_2};"
                    f" border-radius: {R.sm}px; }}")
            else:
                row_box.setStyleSheet(
                    f"QWidget#agentRow {{ background: transparent;"
                    f" border-radius: {R.sm}px; }}"
                    f"QWidget#agentRow:hover {{ background: {C.surface_2}; }}")
            row_box.setLayout(row)
            self._agent_layout.addWidget(row_box)

    @staticmethod
    def _chip(label: str, tone: str) -> QWidget:
        return chip(label, tone)

    def _agent_menu(self, name: str, display: str) -> None:
        """⋯ 更多操作：查看接入详情 / 暂停或恢复采集（行内动作进菜单）。"""
        menu = QMenu(self)
        menu.addAction(t("查看详情")).triggered.connect(
            lambda: self._open_agent_drawer(name, display))
        # 暂停/恢复：按当前 enabled 状态给反向动作
        enabled = ((self._last_cap_items or {}).get(name, {})
                   .get("enabled", True) is not False)
        if enabled:
            menu.addAction(t("暂停记录")).triggered.connect(
                lambda: self._set_capture_enabled(name, False))
        else:
            menu.addAction(t("恢复记录")).triggered.connect(
                lambda: self._set_capture_enabled(name, True))
        menu.exec(self._map_menu_pos())

    def _map_menu_pos(self):
        from PySide6.QtGui import QCursor

        return QCursor.pos()

    # ---------- 第二层 ②：采集开关 ----------

    def _build_capture(self) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(S.s2)

        header = QHBoxLayout()
        self._capture_header = txt(t("采集"), F.body, 600)
        header.addWidget(self._capture_header)
        header.addStretch(1)
        self._capture_summary = txt("", F.caption, color=C.ink_500)
        header.addWidget(self._capture_summary)
        v.addLayout(header)

        self._capture_body = QWidget()
        self._capture_layout = QVBoxLayout(self._capture_body)
        self._capture_layout.setContentsMargins(0, 0, 0, 0)
        self._capture_layout.setSpacing(S.s1)
        v.addWidget(self._capture_body)
        return box

    def refresh_capture(self, data: dict | None = None) -> None:
        """② 采集行：switch + 工具名 + 最近时间（相对，绝对进 tooltip）。

        去 dot 化（方案）：不再在行内挂黄点/整句警告，问题统一进
        区 ③ 聚合 + 抽屉；行内只保留 chip(warn) 一句「检测不到记录」。"""
        try:
            cap = data if data is not None else self.api.capture()
        except LocalApiError:
            return
        items = cap.get("items") or []
        self._capture_summary.setText(t(
            "在采集 {n}/{m} 个",
            n=cap.get("enabled_count", 0),
            m=cap.get("total", len(items))))
        self._clear(self._capture_layout)
        if not items:
            self._capture_layout.addWidget(txt(
                t("还没有在记录的 AI 工具。这台机器上只要有个工具开始干活，这里就会出现。"),
                F.caption, color=C.ink_500, italic=True, wrap=True))
        for it in items:
            name = it.get("name", "")
            display_name = _agent_display(name)
            enabled = bool(it.get("enabled", True))
            row = QHBoxLayout()
            row.setSpacing(S.s2)
            # 开关在前（启停是这行的主操作）
            sw = switch(enabled)
            sw.toggled.connect(
                lambda checked, n=name: self._set_capture_enabled(n, checked))
            row.addWidget(sw, 0, Qt.AlignVCenter)
            row.addWidget(txt(display_name, F.body, 600))
            last_hit = it.get("last_hit")
            if last_hit:
                rel, abs_t = _ts_ago(last_hit)
                tlabel = txt(t("最近 {at}", at=rel), F.caption, color=C.ink_500)
                if abs_t:
                    tlabel.setToolTip(abs_t)  # 绝对时间进 tooltip（正文给相对时间）
                row.addWidget(tlabel)
            row.addStretch(1)
            if it.get("yellow_flag"):
                # chip(warn) 代替黄 dot（读得懂 + 颜色对 + 一元素一职）
                row.addWidget(self._chip(t("检测不到记录"), "warn"))
            row_box = QWidget()
            row_box.setObjectName("captureRow")
            row_box.setStyleSheet(
                f"QWidget#captureRow {{ background: transparent;"
                f" border-radius: {R.sm}px; }}"
                f"QWidget#captureRow:hover {{ background: {C.surface_2}; }}")
            row_box.setLayout(row)
            self._capture_layout.addWidget(row_box)
            # W2-04：禁用行内给一句（不拦截——用户主权）
            if not enabled:
                self._capture_layout.addWidget(txt(
                    t("暂停后 {name} 的经验将不再记录", name=display_name),
                    F.caption, color=C.ink_500))

    def _set_capture_enabled(self, name: str, enabled: bool) -> None:
        try:
            self.api.set_capture(name, enabled)
        except LocalApiError as exc:
            # 失败不得静默——否则开关被下一次 refresh
            # 悄悄还原，用户以为生效了（page_base SYS-5 契约）。
            self.report_error(t("采集开关设置失败：{err}", err=exc.localized()))
        self.refresh_capture()
        # 采集启停会改变「已接入」清单的状态标签，联动刷新
        if getattr(self, "_last_agents", None) is not None:
            self._refresh_agents(self._last_agents, self._last_cap_items,
                                 self._last_flags, self._last_encrypted)

    # ---------- 第二层 ③：需要你处理（仅异常时渲染，按类型聚合） ----------

    def refresh_capture_health(self, data: dict | None = None) -> None:
        """区 ③：按问题类型聚合（不按工具重复）+ 直达动作 + 抽屉详情。

        - 「检测不到记录」：所有 yellow_flag 的 agent 聚合成一条。
        - 无异常：整卡隐藏（不刷屏、不给假数字）。
        """
        flags = self._flags or {}
        flagged = sorted((k, v) for k, v in flags.items() if v)
        if not flagged:
            self._action_card.setVisible(False)
            return
        self._action_card.setVisible(True)
        self._clear(self._action_layout)
        names = ", ".join(_agent_display(k) for k, _ in flagged)
        total_rounds = sum(v for _, v in flagged)
        # 一句聚合结论（2 个工具检测不到记录（QClaw、Trae））
        self._action_layout.addWidget(txt(
            t("{n} 个工具检测不到新记录（{names}）",
              n=len(flagged), names=names),
            F.body, 600, C.warn_fg))
        # 一句可操作建议（不只报问题，给出路；说清"为什么会这样 + 怎么办"）
        # wrap=True：本句很长（≈790px），不换行会把内容列的最小宽撑到超出视口
        # ——最小窗口下表现为横向滚动条 + 句尾被省略号截断。
        self._action_layout.addWidget(txt(
            t("这些工具最近读不到新记录了，多半是它们升级后换了存记录的方式。"
              "先点「去暂停」让它们别记了（不影响别的工具）；通常等下个版本更新会"
              "自动恢复，点「查看详情」可看每个工具的具体情况。"),
            F.caption, color=C.ink_500, wrap=True))
        # 直达动作 + 抽屉详情（详情抽屉列出**全部**异常工具，不止首个）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(S.s2)
        pause_btn = btn_secondary(t("去暂停"), on_click=lambda:
                                  self._pause_flagged())
        btn_row.addWidget(pause_btn)
        detail_btn = btn_flat(t("查看详情"),
                              on_click=lambda: self._open_flag_drawer())
        detail_btn.setFixedHeight(D.BTN_H_SM)
        btn_row.addWidget(detail_btn)
        btn_row.addStretch(1)
        btn_box = QWidget()
        btn_box.setLayout(btn_row)
        self._action_layout.addWidget(btn_box)
        self._last_flag_total = total_rounds

    def _pause_flagged(self) -> None:
        """把所有「检测不到记录」的工具暂停（直达「去关闭」）。"""
        for k, _v in (self._flags or {}).items():
            if _v:
                try:
                    self.api.set_capture(k, False)
                except LocalApiError:
                    pass
        self.refresh_capture()
        if getattr(self, "_last_agents", None) is not None:
            self._refresh_agents(self._last_agents, self._last_cap_items,
                                 self._last_flags, self._last_encrypted)

    # ---------- 新增工具向导（三步条 + 独立状态区，新增工具卡重设计方案） ----------

    # ---------- 第三层：高级设置（折叠：分工具说明 / 注入预览） ----------

    def _build_advanced(self) -> QWidget:
        header, self._expand_icon = collapse_header(
            t("高级设置"), on_toggle=self._toggle_tools)
        self._tools_header = header.layout().itemAt(0).widget()

        self._tools_body = QWidget()
        body_lay = QVBoxLayout(self._tools_body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(S.s4)

        # 分工具接入说明（常驻可查可复制，默认隐藏；左右分栏向导，
        # 语言切换走 _rebuild_tools_inner 整卡重建）
        self._tools_body_lay = body_lay
        self._tools_card = self._build_tools_inner()
        body_lay.addWidget(self._tools_card)

        # 注入预览（内嵌 InjectPreviewPage，共用外层滚动；embedded 降级 h1→h2）
        # 注：模型与接入已升为总况条下方的常驻卡，不再收在这里
        self._inject = InjectPreviewPage(self.api, self, embedded=True)
        body_lay.addWidget(self._inject.content)

        self._tools_expanded = False  # 显式状态：isVisible 在页未显示时恒 False
        self._tools_body.hide()

        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(S.s1)
        v.addWidget(header)
        v.addWidget(self._tools_body)
        return box

    def _build_tools_inner(self) -> QWidget:
        """分工具接入说明（样板 C「左右分栏」，替代旧版 10 行长句墙）。

        左列 = 工具清单（8 个可配置在前、2 个仅官方置灰标「免配」垫底），
        右列 = 选中工具的三步接法 + 可复制配置片段 + 原长句补充说明。
        整块固定高度、永不随选中工具长高；承诺的「可复制」在这里
        真正落地（旧版只有长句、没有复制入口）。分组标题（Coding agent /
        Harness）不再需要——清单顺序本身就是分组，省掉两行小标题。
        """
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S.s2)
        lay.addWidget(txt(
            t("命令行 agent 可套 experientia-wrap 自动走上面的代理地址"),
            F.caption, color=C.ink_500, wrap=True))

        split = QFrame()
        split.setObjectName("guideSplit")
        split.setStyleSheet(
            f"QFrame#guideSplit {{ background: {C.surface};"
            f" border: 1px solid {C.line_strong};"
            f" border-radius: {R.md}px; }}")
        sh = QHBoxLayout(split)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(0)

        # 左列：清单按钮（固定宽，窄窗不挤压详情区）
        left = QWidget()
        left.setFixedWidth(216)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(S.s2, S.s2, S.s2, S.s2)
        lv.setSpacing(2)
        self._guide_btns = {}
        for n in _CODING_TOOLS + _HARNESS_TOOLS:
            if n in _ONLY_OFFICIAL:
                continue
            lv.addWidget(self._guide_row_btn(n))
        if self._guide_btns and _ONLY_OFFICIAL:
            off_div = QFrame()
            off_div.setFrameShape(QFrame.HLine)
            off_div.setStyleSheet(
                f"border: none; border-top: 1px solid {C.line};"
                f" margin: {S.s1}px {S.s3}px;")
            lv.addWidget(off_div)
        for n in _ONLY_OFFICIAL:
            lv.addWidget(self._guide_row_btn(n, official=True))
        lv.addStretch(1)
        sh.addWidget(left)

        vline = QFrame()
        vline.setFrameShape(QFrame.VLine)
        vline.setStyleSheet(f"border: none; border-left: 1px solid {C.line};")
        sh.addWidget(vline)

        # 右列：详情（minHeight 固定 → 换工具不跳版）
        det = QWidget()
        det.setMinimumHeight(330)
        det.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._guide_det_lay = QVBoxLayout(det)
        self._guide_det_lay.setContentsMargins(S.s4, S.s4, S.s4, S.s4)
        self._guide_det_lay.setSpacing(S.s2)
        sh.addWidget(det, 1)

        lay.addWidget(split)
        if getattr(self, "_guide_sel", None) not in _TOOL_GUIDE \
                and getattr(self, "_guide_sel", None) not in _ONLY_OFFICIAL:
            self._guide_sel = _CODING_TOOLS[0]
        self._sync_guide_rows()
        self._render_guide_detail()
        return card(content=inner, title=t("分工具接入说明"), secondary=True)

    def _guide_row_btn(self, name: str, official: bool = False) -> QPushButton:
        """左列一行：专有图标 + 工具名（生态词不译）+ 仅官方的「免配」尾标。"""
        btn = row_select_button()
        h = QHBoxLayout(btn)
        h.setContentsMargins(S.s3, 0, S.s3, 0)
        h.setSpacing(S.s2)
        h.addWidget(icon_widget(_TOOL_ICON.get(name, "console"),
                                SIZES.ICON_LIST,
                                C.ink_300 if official else C.brand_700))
        h.addWidget(txt(name, F.body, 600,
                        C.ink_500 if official else C.ink_900))
        h.addStretch(1)
        if official:
            # ink_300 是"仅非文字"档（P2-1 红线），文字尾标走 ink_500 辅助档
            h.addWidget(txt(t("免配"), F.caption, color=C.ink_500))
        btn.clicked.connect(lambda _=False, n=name: self._select_guide(n))
        self._guide_btns[name] = btn
        return btn

    def _select_guide(self, name: str) -> None:
        self._guide_sel = name
        self._sync_guide_rows()
        self._render_guide_detail()

    def _sync_guide_rows(self) -> None:
        for n, btn in self._guide_btns.items():
            row_select_style(btn, n == self._guide_sel)

    def _guide_steps(self, kind: str, target: str) -> list:
        """三步话术壳（走 t()）；target/代码是数据不译。"""
        s2 = t("照下面填，Key 用本页顶部的接入令牌")
        if kind == "环境变量":
            return [t("设以下环境变量"), s2,
                    t("重启该工具，回本页在「已接入」里看到它，就接好了")]
        if kind == "配置文件":
            return [t("打开配置文件 {file}", file=target), s2,
                    t("重启该工具，回本页在「已接入」里看到它，就接好了")]
        return [t("在工具里打开「设置 → 模型」，添加自定义模型"), s2,
                t("保存后立即生效")]

    def _step_row(self, no: int, label: str) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(S.s2)
        badge = QLabel(str(no))
        badge.setFixedSize(20, 20)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"background: {C.brand_100}; color: {C.brand_700};"
            f" border: none; border-radius: 10px; font-weight: 700;"
            f" font-size: {F.caption}px;")
        h.addWidget(badge, 0, Qt.AlignTop)
        lab = txt(label, F.body, color=C.ink_700, wrap=True)
        h.addWidget(lab, 1)
        return row

    def _render_guide_detail(self) -> None:
        lay = self._guide_det_lay
        ConnectPage._clear(lay)
        name = getattr(self, "_guide_sel", _CODING_TOOLS[0])
        guide = _TOOL_GUIDE.get(name)

        head = QHBoxLayout()
        head.setSpacing(S.s2)
        head.addWidget(txt(name, F.h2, 700))
        if guide is None:
            head.addWidget(chip(t("仅官方接入"), tone="ink"), 0,
                           Qt.AlignVCenter)
        head.addStretch(1)
        lay.addLayout(head)

        if guide is None:
            # 仅官方：不用配，长句解释为什么 + 会话仍自动采集
            prose = txt(t(_TOOL_DESC[name]), F.body, color=C.ink_700,
                        wrap=True)
            lay.addWidget(prose)
            lay.addStretch(1)
            return

        kind, target, code = guide
        sub = QHBoxLayout()
        sub.setSpacing(S.s2)
        sub.addWidget(chip(t(kind)))
        if target:
            sub.addWidget(mono(target, C.brand_700))
        sub.addStretch(1)
        lay.addLayout(sub)

        steps = self._guide_steps(kind, target)
        lay.addSpacing(S.s1)
        lay.addWidget(self._step_row(1, steps[0]))
        lay.addWidget(self._step_row(2, steps[1]))
        lines = code.count("\n") + 1
        # 余量含边框/padding/横向滚动条（NoWrap 下横条可能吃掉 ~16px 纵向空间，
        # 不给够会再触发纵向条，两向滚动互相激发）
        cb = code_box(code, height=max(76, 19 * lines + 48))
        # 配置片段按行读，禁折行（折行会撑出纵向滚动条、代码读不断）；
        # 窄窗时横向滚动兜底
        cb.setLineWrapMode(QPlainTextEdit.NoWrap)
        lay.addWidget(cb)
        crow = QHBoxLayout()
        crow.setSpacing(S.s2)
        crow.addStretch(1)
        self._guide_copied = txt("", F.caption, color=C.ok_fg)
        crow.addWidget(self._guide_copied)
        crow.addWidget(btn_secondary(t("复制"), "CONTENT_COPY_OUTLINED",
                                     lambda _=False, c=code:
                                     self._copy_guide_code(c)))
        lay.addLayout(crow)
        lay.addWidget(self._step_row(3, steps[2]))
        lay.addSpacing(S.s2)
        # 原长句降级为补充说明：细节（完整路径要求/文件顶部/模型列表等）不丢
        prose = txt(t(_TOOL_DESC[name]), F.caption, color=C.ink_500,
                    wrap=True)
        lay.addWidget(prose)
        lay.addStretch(1)

    def _copy_guide_code(self, code: str) -> None:
        QApplication.clipboard().setText(code)
        if getattr(self, "_guide_copied", None) is not None:
            self._guide_copied.setText(t("已复制"))

    def _rebuild_tools_inner(self) -> None:
        """语言切换整卡重建：卡内文案多为构建期 t()，重渲比逐控件补 setText 稳。"""
        old = getattr(self, "_tools_card", None)
        if old is None:
            return
        lay = self._tools_body_lay
        i = lay.indexOf(old)
        lay.removeWidget(old)
        old.setParent(None)
        old.deleteLater()
        self._tools_card = self._build_tools_inner()
        lay.insertWidget(i, self._tools_card)

    def _toggle_tools(self) -> None:
        self._tools_expanded = not self._tools_expanded
        self._tools_body.setVisible(self._tools_expanded)
        # 箭头旋转表达展开态（chevron-down 转 180° 即 chevron-up）；
        # reduced-motion 时直接落到目标角，不播动画。
        target = 180 if self._tools_expanded else 0
        if not motion_ok():
            self._expand_icon.setRotation(target)
            return
        if getattr(self, "_chevron_anim", None) is not None:
            self._chevron_anim.stop()
        anim = QPropertyAnimation(self._expand_icon, b"rotation", self)
        anim.setDuration(int(ANIMATION.DURATION_NORMAL * 1000))
        anim.setStartValue(self._expand_icon.rotation)
        anim.setEndValue(target)
        anim.start()
        self._chevron_anim = anim

    # ---------- 详情抽屉（错误详情进侧边抽屉，主列表保持干净） ----------

    def _on_drawer_close(self) -> None:
        pass

    def _agent_detail_block(self, name: str, header: bool = False,
                            forced: str | None = None) -> QWidget:
        """单个工具的详情**卡**（状态 + 加密方案 + 该工具最近命中 + 该工具工作区）。

        抽成独立卡：①「已接入」⋯菜单的单工具详情、③多工具详情抽屉都复用。
        用次级卡承载（底色分层 + 圆角）替代旧版裸标签 + 硬分隔线（设计 skill：
        边框最后手段，优先留白 + 底色）。工作区只列该工具**参与**的
        （item.agents 含它），避免把别的项目张冠李戴。

        header=True 时卡首显示工具名——③ 抽屉列 N 个工具时用户需分清每段是谁
        （单工具详情名字在抽屉标题里，不必重复）。

        forced 用于 ③「检测不到记录」抽屉：凡被列出即按该状态渲染（哪怕黄标 <3），
        消除"进了异常抽屉却显示正常"的自相矛盾（状态一致）。
        """
        display = _agent_display(name)
        # 抽屉浮层面板是次级底（surface_2），故详情卡用主底（surface）——
        # 更浅的卡在更深的面板上 + 各自边框，层次才分得开（不会融成一片）。
        c = card()
        v = c.layout()
        v.setSpacing(S.s2)
        if header:
            v.addWidget(txt(display, F.body, 700, C.ink_900))
        flags = self._flags or {}
        yellow = flags.get(name, 0)
        is_enc = (self._last_encrypted or {}).get(name, False)
        # 状态判定：forced 优先（③ 抽屉），否则按黄标 / 加密 / 正常
        if forced:
            tone, label = "warn", t(forced)
        elif yellow >= 3:
            tone, label = "warn", t("检测不到记录")
        elif is_enc:
            tone, label = "info", t("已加密")
        else:
            tone, label = "ok", t("正常")
        # 状态行：语义色点 + 标签（色点必须配文字，可访问性）
        srow = QHBoxLayout()
        srow.setSpacing(S.s1)
        srow.addWidget(status_dot(tone), 0, Qt.AlignVCenter)
        srow.addWidget(txt(label, F.body, 600, TONE_FG[tone]), 0,
                       Qt.AlignVCenter)
        srow.addStretch(1)
        v.addLayout(srow)
        if tone == "warn":
            v.addWidget(txt(
                t("连续 {n} 轮没能读到它的新记录——它保存记录的格式可能变了",
                  n=yellow), F.caption, color=C.ink_500, wrap=True))
        # 加密 agent 兜底方案
        if is_enc:
            v.addWidget(txt(t("接入方案"), F.body, 600, C.ink_700))
            for tip in self._encryption_tips(name, display):
                tip.setWordWrap(True)
                v.addWidget(tip)
        # 最近命中（只取该工具的）——用 refresh 并行取到的结果（
        # 原实现在渲染期同步再取一次，抽屉打开时主线程冻结最长 15s）。
        # 缓存缺席（测试/兼容路径直调本方法）才退回同步取一次。
        cs = getattr(self, "_last_cap_status", None)
        if cs is None:
            try:
                cs = self.api.capture_status()
            except Exception:
                cs = {}
        hits = [h for h in (cs.get("recent_hits") or [])
                if h.get("agent") == name][:3]
        if hits:
            v.addWidget(txt(t("最近命中"), F.body, 600, C.ink_700))
            for h in hits:
                rel, _abs_t = _ts_ago(str(h.get("ts", "")))
                v.addWidget(txt(t("最近 {at}", at=rel), F.caption,
                                color=C.ink_500))
        # 工作区（仅该工具参与的；无则不显示，绝不拿别的项目充数）——同样用
        # _fetch 已并行取到的结果。
        ws_all = getattr(self, "_last_workspaces", None)
        if ws_all is None:
            try:
                ws_all = (self.api.workspaces().get("items") or [])
            except Exception:
                ws_all = []
        ws_items = [w for w in ws_all if name in (w.get("agents") or [])][:2]
        for w in ws_items:
            proj = str(w.get("project") or "?")
            if len(proj) > 48:
                proj = "…" + proj[-47:]
            v.addWidget(txt(
                t("工作区：{proj}（{n} 会话）",
                  proj=proj, n=w.get("count", 0)),
                F.caption, color=C.ink_500))
        return c

    def _open_agent_drawer(self, name: str, display: str) -> None:
        """打开某 agent 的详情抽屉（⋯菜单「查看详情」，单工具）。"""
        if self._drawer is None:
            return
        self._drawer.set_title(t("详情：{name}", name=display))
        self._drawer.set_content(self._agent_detail_block(name))
        self._drawer.show_open()

    def _open_flag_drawer(self) -> None:
        """区 ③「查看详情」→ 抽屉列出**全部**检测不到记录的工具（不止首个）。

        区 ③ 按类型聚合（一张卡报 N 个工具），详情抽屉须与之一一对应地
        展示每个工具，否则用户点「查看详情」只看到第一个、其余无从查起。"""
        if self._drawer is None:
            return
        flagged = sorted((k, v) for k, v in (self._flags or {}).items() if v)
        if not flagged:
            return
        self._drawer.set_title(t("检测不到记录的工具（{n} 个）",
                                 n=len(flagged)))
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(S.s3)
        for name, _rounds in flagged:
            # forced：凡被列出即按"检测不到记录"渲染（状态一致，不显"正常"）；
            # 卡间留白即分隔（次级卡自带底色 + 圆角，不用硬 HLine）。
            v.addWidget(self._agent_detail_block(
                name, header=True, forced="检测不到记录"))
        v.addStretch(1)
        self._drawer.set_content(body)
        self._drawer.show_open()

    # ---------- 刷新 ----------

    def refresh(self) -> None:
        """接入页刷新：6 个只读请求整体挪后台线程，
        主线程按序渲染（models/inject 页仍由其自身在主线程 refresh，
        不跨线程碰 widget）。"""
        # S5：补首屏骨架（此前本页取数期间无占位）
        self.fetch_and_render(self._fetch, self._render,
                              skeleton=[28, 96, 72, 72])

    def _fetch(self) -> dict:
        return parallel_fetch({
            "status": self.api.status,
            "hooks": self.api.hooks_config,
            "capture": self.api.capture,
            "cap_status": self.api.capture_status,
            # workspaces 一并并行取——详情块原来在渲染期
            # 自己同步再取一次，抽屉/异常卡构建时主线程串行冻结。
            "workspaces": self.api.workspaces,
            "probe": self.api.probe_status,
            "keys": self.api.probe_keys,
        })

    def _render(self, res: dict | None) -> None:
        res = res or {}
        status = res.get("status")
        running = status is not None
        if not running:
            self._connect_mascot.setPixmap(
                mascot_image("sweat", SIZES.MASCOT_DIALOG_TITLE).pixmap())
            self._flags = {}
            self._refresh_overview(0, False, 0, 0, 0)
            self._refresh_agents({}, {}, {}, {})
            self._action_card.setVisible(False)
            self.refresh_hooks(res.get("hooks"))  # 引擎未连 → 标「配置失败」
            return
        self._flags = status.get("yellow_flags", {}) or {}
        new_url = status.get("proxy_base_url", "http://127.0.0.1:8100")
        if new_url != self._proxy_url:
            self._proxy_url = new_url
            if getattr(self, "_url_bar", None) is not None:
                self._url_bar.setText(new_url)

        # 取数（加密状态 + capture items）
        cap = res.get("capture") or {}
        cap_items = {i["name"]: i for i in (cap.get("items") or [])}
        self._last_cap_items = cap_items
        # 详情块渲染期原来各自同步再取一次
        # capture_status / workspaces（各 15s 超时）——抽屉打开、异常卡构建时
        # 主线程串行冻结。这里把 _fetch 已并行取到的结果缓存下来，渲染直接用。
        self._last_cap_status = res.get("cap_status")
        self._last_workspaces = (res.get("workspaces") or {}).get("items") or []
        try:
            # 渲染阶段禁 HTTP：cap_status 取数失败按无加密状态渲染
            cap_status = res.get("cap_status") or {}
            encrypted_agents = {
                name: bool(a.get("encrypted", False))
                for name, a in (cap_status.get("agents") or {}).items()
                if isinstance(a, dict)
            }
        except Exception:
            encrypted_agents = {}
        self._last_encrypted = encrypted_agents
        self._last_flags = self._flags
        agents = status.get("agents", {}) or {}
        self._last_agents = agents

        # Claude Code 实时钩子卡自适应：在跑 claude-code → 默认展开（给它最高
        # 价值的动作），未在用 → 收起（只留标题行，不占首屏）。用户手动选择优先。
        self._apply_connect_default(int(agents.get("claude-code", 0) or 0) > 0)

        # 总况条（签名）：主信息 = 已接入工具数（agents 里有会话的）
        enabled_n = cap.get("enabled_count", 0)
        total_n = cap.get("total", len(cap.get("items") or []))
        flagged = [k for k, v in self._flags.items() if v]
        pending_n = len(flagged)
        connected_n = sum(1 for a in agents.values() if a > 0)
        self._refresh_overview(connected_n, True, enabled_n, total_n,
                               pending_n)

        # 接入（hook 状态）
        self.refresh_hooks(res.get("hooks"))

        # ① 已接入清单 + ③ 需处理聚合
        self._refresh_agents(agents, cap_items, self._flags, encrypted_agents)
        self.refresh_capture_health(res.get("cap_status"))

        # ② 采集开关
        self.refresh_capture(res.get("capture"))

        # 钥匙 / probe
        keys_raw = res.get("keys") or {}
        self.refresh_probe(res.get("probe"),
                           keys_raw.get("keys") or [])

        # 模型（常驻卡）/ 注入预览（第三层内嵌子页），各自主线程 refresh
        self._models.refresh()
        if hasattr(self._models, "set_proxy_url"):
            self._models.set_proxy_url(self._proxy_url)
        self._inject.refresh()

        # 更新吉祥物表情：有 agent 在采集 → smile，否则 search
        has_agents = bool(cap.get("items"))
        new_mascot = "smile" if has_agents else "search"
        pm = mascot_image(new_mascot, SIZES.MASCOT_DIALOG_TITLE).pixmap()
        if pm is not None:
            self._connect_mascot.setPixmap(pm)

    # ---------- 重新翻译 ----------

    def _retranslate_probe(self) -> None:
        if not getattr(self, "_probe_intro", None):
            return
        self._probe_card_title.setText(t("新增工具"))
        self._set_neutral_chip_label(self._probe_scope_chip,
                                     t("读不到的工具专用"))
        self._probe_intro.setText(t(
            "少数 AI 工具的会话被加密或格式不通用，装个小技能就能接进来。"))
        # 三步条（徽章数字不随语言变，只改标题/副标题）
        self._step1 = self._rebuild_step(self._step1, "1", t("导出技能"),
                                         t("下载技能包"))
        self._step2 = self._rebuild_step(self._step2, "2", t("运行一次"),
                                         t("工具自动上报"))
        self._step3 = self._rebuild_step(self._step3, "3", t("粘贴连接"),
                                         t("连接码自动送达"))
        if getattr(self, "_probe_export_btn", None) is not None:
            self._set_btn_text(self._probe_export_btn, "导出上报技能")
            self._probe_export_btn.setToolTip(t(
                "点「导出上报技能」导出一个 experientia-report 文件夹，放进那个 AI 工具"
                "能加载技能的位置（一般是它的 skills 或插件目录），然后让它运行一次"
                "任意任务。"))
            self._probe_export_hint.setText(
                t("导出 experientia-report 文件夹，放进工具的技能目录"))
        self._probe_code.setPlaceholderText(t("粘贴返回的连接码"))
        self._probe_state_header.setText(t("接入状态"))
        # 主按钮「连接」无图标 → 直接 setText（btn_primary 未装图标时无子布局）
        self._probe_connect_btn.setText(t("连接"))
        self._probe_pending_btn.setText(t("去处理"))
        self._probe_why_btn.setText(t("为什么需要？"))
        self._probe_why_body.setText(t(
            "少数 AI 工具的会话被加密或格式不通用，Experientia 直接读不到，需要工具"
            "主动上报。正常情况下连接码会自动送达、无需手动粘贴；只有下方列表一直没"
            "出现它时，才需要把工具返回的连接码粘到输入框，再点「连接」。如果你常用"
            "某个工具但上方「已接入」里一直没有它，多半就是这一类——给它装一次小技能"
            "即可。"))
        if getattr(self, "_last_probe", None):
            self.refresh_probe(self._last_probe)

    @staticmethod
    def _rebuild_step(old: QWidget, no: str, title: str, sub: str) -> QWidget:
        """三步条列的文字更新：直接改子标签（不重建，避免布局抖动）。

        结构：[badge, title_label, sub_label]（见 _step_line）。"""
        if old is None:
            return old
        lay = old.layout()
        if lay is None:
            return old
        badge = lay.itemAt(0).widget()
        if isinstance(badge, QLabel):
            badge.setText(no)
        title_label = lay.itemAt(ConnectPage._STEP_TITLE_IDX).widget()
        sub_label = lay.itemAt(ConnectPage._STEP_SUB_IDX).widget()
        if isinstance(title_label, QLabel):
            title_label.setText(title)
        if isinstance(sub_label, QLabel):
            sub_label.setText(sub)
        return old

    def _set_btn_text(self, btn: QPushButton, key: str) -> None:
        """更新按钮文字（语言切换）：带图标子布局则改子 QLabel，否则改按钮自身 text。

        图标无效时 _apply_btn_icon 不建布局（按钮纯文本），此处兜底不崩。"""
        lay = btn.layout()
        if lay is not None:
            for i in range(lay.count()):
                w = lay.itemAt(i).widget()
                if isinstance(w, QLabel):
                    w.setText(t(key))
                    return
        btn.setText(t(key))

    def retranslateUi(self) -> None:
        """重新调用 t() 更新所有静态 widget 文本。"""
        self._connect_heading.setText(t("接入"))
        self._page_sub.setText(
            t("把你在用的 AI 工具接进来，Experientia 就能记录它们的经验、下次自动带上。"
              "大多数工具不用你做任何事；只有标了黄色的，才需要点一下。"))
        # 总况条（去管理是带图标的胶囊按钮，文字在子 QLabel 里）
        self._set_btn_text(self._ov_go_btn, "去管理")
        # 令牌行与提示语重译（脱敏文本按当前语言重排）
        if getattr(self, "_token_row", None) is not None:
            self._render_token_row()
        # Claude Code 实时钩子卡（标题 + 作用域 chip）
        if getattr(self, "_guide_card_title", None) is not None:
            self._guide_card_title.setText(t("实时钩子（Claude Code）"))
        if getattr(self, "_connect_scope_chip", None) is not None:
            self._set_neutral_chip_label(self._connect_scope_chip,
                                         t("Claude Code 专用"))
        self._guide_desc.setText(
            t("除了把地址指过去（见上方总况条），Claude Code 还能装一个实时钩子："
              "装上后，它每次开始任务、收到你的消息时都会主动把经验交给 Experientia，"
              "比只改地址更及时。点下方按钮一键装好。"))
        # 图标按钮的文字在子 QLabel 里（图标+文本布局）；无图标则直接改按钮 text
        self._set_btn_text(self._cfg_btn, "一键配置接入")
        self._remove_btn.setText(t("移除"))
        self._set_btn_text(self._plugin_btn, "插件包")
        self._set_plugin_copy_label(t("复制命令"))
        self._not_proxy_txt.setText(
            t("装了钩子的工具，即使不改地址、不走代理，经验也会自动带上"))
        # ① 已接入
        if getattr(self, "_agents_card_title", None) is not None:
            self._agents_card_title.setText(t("已接入的 AI 工具"))
        self._agent_empty.setText(t(
            "还没发现你在用的 AI 工具。随便挑一个工具跑个任务，这里就会自动出现它。"))
        # ② 采集
        self._capture_header.setText(t("采集"))
        # ③ 需处理
        if getattr(self, "_action_card_title", None) is not None:
            self._action_card_title.setText(t("需要你处理"))
        # 新增工具向导
        self._retranslate_probe()
        # 高级设置
        self._tools_header.setText(t("高级设置"))
        # 分工具向导卡内多为构建期 t()，整卡重建（保留选中工具）
        self._rebuild_tools_inner()
        # 动态卡片（③需处理 / ①已接入 / ②采集）的文字在渲染时用 t() 生成，
        # 语言切换后用缓存数据重渲一遍，避免停留在旧语言
        if getattr(self, "_last_agents", None) is not None:
            self._refresh_agents(self._last_agents, self._last_cap_items,
                                 self._last_flags, self._last_encrypted)
            self.refresh_capture_health()
        if getattr(self, "_last_cap_items", None) is not None:
            self.refresh_capture()
        if getattr(self, "_last_probe", None):
            self.refresh_probe(self._last_probe)

    # ---------- 工具 ----------

    @staticmethod
    def _encryption_tips(name: str, display: str) -> list:
        """返回加密 agent 的兜底建议文本列表（逐条 vs 逐 agent 定制）。

        每条都 wrap=True：这些是整句散文，非中文译文明显更长（实测同句
        西/德可达 860+px），不换行会撑爆所在卡片的最小宽、句尾被截断。
        """
        common = t("{name} 的数据库已加密，无法直接读取本地文件", name=display)
        if name == "trae":
            return [
                txt(common, F.caption, color=C.warn_fg, wrap=True),
                txt(
                    t("⬥ 走代理捕获：将工具代理地址设为 {url}（推荐）",
                      url="http://127.0.0.1:8100"),
                    F.caption, color=C.ink_500, wrap=True),
                txt(
                    t("⬥ 自动解密：启动 Trae 后，系统会自动尝试从进程内存提取密钥解密"),
                    F.caption, color=C.ink_500, wrap=True),
                txt(
                    t("⬥ 社区工具：Oh-My-Trae/trae-db-decrypt（需管理员权限）"),
                    F.caption, color=C.ink_500, wrap=True),
                txt(
                    t("⬥ 权限：Windows 需管理员、macOS 需关闭 SIP；失败时先抢救渲染日志/社区预解密文件（不丢数据）"),
                    F.caption, color=C.ink_500, wrap=True),
            ]
        if name == "windsurf":
            return [
                txt(common, F.caption, color=C.warn_fg, wrap=True),
                txt(
                    t("⬥ 走代理捕获：将工具代理地址设为 {url}（推荐）",
                      url="http://127.0.0.1:8100"),
                    F.caption, color=C.ink_500, wrap=True),
                txt(
                    t("⬥ 自动解密：已知全局硬编码密钥，系统会自动解密 trajectory 文件"),
                    F.caption, color=C.ink_500, wrap=True),
            ]
        # 通用加密兜底
        return [
            txt(common, F.caption, color=C.warn_fg, wrap=True),
            txt(
                t("⬥ 走代理捕获：将工具代理地址设为 {url}（推荐）",
                  url="http://127.0.0.1:8100"),
                F.caption, color=C.ink_500, wrap=True),
            txt(
                t("⬥ 暂停采集：在上方「采集」区关掉它，暂停记录"),
                F.caption, color=C.ink_500, wrap=True),
        ]

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                ConnectPage._clear(item.layout())
