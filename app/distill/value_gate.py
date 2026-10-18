"""经验价值闸门（方案《研究_经验价值筛选闸门方案》v0.1，纯确定性、零 LLM）。

背景（实证）：本机模型端点连不上 + 熔断（state=open）时，AI 复盘
管线整条离线，只剩 rule 错误计数器按"出现次数"收卡，把「AI 自己手笨的工具错误」
和「环境抖动」全当经验吐给用户 → 用户反馈"梳理下来的都是鸡毛蒜皮"。

本模块只回答一个问题：**一条候选经验，值不值得、以什么身份摆到用户面前？**
四类 value_class（优先级自上而下，先命中先定）：

- ``signature_garbage``  源码回声/纯退出码播报（``except ImportError:``、
  ``if result.error:``）——不是错误，是代码被 echo 回来。落库前直接拒。
- ``env_transient``      环境抖动（网络/fetch failed/连接被拒/EBUSY/EPERM/
  限流 429/超时/本地模型服务没起 llama-server not found）——对齐 REVIEW_PROMPT
  "环境噪音不是经验"，无模型时也先本地挡，不入库不打扰。
- ``agent_friction``     助手自己手笨（Edit 未先 Read、String to replace not
  found、replace_all is false、Command blocked for security、参数类型传错、
  找不到 skill）——移出"你的经验"，转"助手能自动帮你避的坑·建议口吻"通道
  （Reflexion arXiv:2303.11366：Agent 自身失败轨迹转成自我提醒式建议，而非
  当用户经验展示）。仍可注入（提醒 agent 别犯），但不占用户经验墙。
- ``code_lesson``        默认真·教训（Python 异常类、缺模块 ModuleNotFound、
  业务报错的可复用修法）——进"你的经验"。

分类表本地可维护（改这几张表即可），不依赖模型。模型回来时本闸门退化为
LLM 的**前置降噪**（env/garbage 根本不送 LLM 省 token），importance 打分再对
code_lesson/边界 friction 精修（沿用 -P1-3 ≤2 不入库）。
"""

from __future__ import annotations

import re

# ── 四类取值 ────────────────────────────────────────────────────────────
GARBAGE = "signature_garbage"
ENV = "env_transient"
FRICTION = "agent_friction"
LESSON = "code_lesson"

# 入库前直接丢弃的两类（新数据不写；存量迁移下架）
SUPPRESSED = frozenset({GARBAGE, ENV})

# ── 关键词表（小写子串命中；均取自真机 49 条校准，勿凭感觉加）──────────

# 环境抖动：网络/抓取/锁/权限抖动/连接被拒/限流/超时/本地模型服务缺失
_ENV_PATTERNS = (
    "fetch failed", "web fetch", "connection refused", "连接被拒", "无法连接",
    "maxretry", "httpsconnectionpool", "urlopen error", "upstream error",
    "upstream connect", "ebusy", "resource busy or locked", "eperm",
    "operation not permitted", "timed out", "timeout", "connection reset",
    "temporarily unavailable", "rate limit", "429", "too many requests",
    "llama-server", "gateway not started", "not started", "memory_store import failed",
    "adaptive-proxy", "import failed", "connection aborted", "broken pipe",
    "ssl", "certificate verify failed", "name or service not known",
    "getaddrinfo failed", "dns resolution", "eof occurred",
)

# 助手自己手笨：编辑/读文件顺序、替换没找到、参数传错、命令被安全闸拦、缺 skill
_FRICTION_PATTERNS = (
    "has not been read yet", "read it first before", "modified since read",
    "string to replace not found", "no changes to make", "replace_all is false",
    "found # matches", "command blocked for security", "blocked for security",
    "expected string, but received", "expected string but received",
    "invalid parameters provided", "parameter \"url\"", "parameter \"query\"",
    "parameter \"file_path\"", "can not find skill", "cannot find skill",
    "read it again before", "must read before",
)

# 源码回声 / 状态播报（非真实报错）
_GARBAGE_RE = re.compile(
    r"^\s*(?:#\S*\s*)?(?:except|else|elif|try|finally|for|while|def|class|"
    r"import|from|return|yield|with|raise|pass)\b[\s:]"
    r"|^\s*(?:#\S*\s*)?if\s+\w+[\.\[].*(?:\)|:)\s*$"
    r"|^\s*(?:#\S*\s*)?(?:echo|print)\b",
    re.I,
)

# 真·教训：Python 运行时/导入异常特征（默认为 lesson，此表用于命中即锁定 lesson，
# 抢在 friction/env 因含零碎词误判之前）
_LESSON_RE = re.compile(
    r"\b(moduleNotFoundError|importerror|attributeError|typeError|valueError|"
    r"indexError|keyError|nameError|syntaxError|indentationError|"
    r"json\.decoder\.JSONDecodeError|UnicodeDecodeError|UnicodeEncodeError|"
    r"zeroDivisionError|StopIteration|AssertionError|NotImplementedError)\b",
    re.I,
)


def classify(text: str) -> str:
    """候选文本（state/task 原始报错串）→ value_class 四类之一。

    纯函数、无副作用、无 I/O。判定优先级：garbage → env → lesson → friction。
    lesson 抢在 friction 前：一条真·Python 异常即便夹带 "read" 等碎词，也不该被
    误降级成"助手手笨"；garbage/env 抢在最前因为它们连"是不是错误"都存疑。"""
    s = str(text or "")
    if not s.strip():
        return GARBAGE
    if _GARBAGE_RE.match(s.strip()):
        return GARBAGE
    low = s.lower()
    if any(p in low for p in _ENV_PATTERNS):
        # 但"真·Python 异常"里恰好含 env 碎词（如 timeoutError 业务码）不误伤：
        # 命中 lesson 特征则仍算 lesson（用户可复用的做法教训）
        return ENV if not _LESSON_RE.search(s) else LESSON
    if _LESSON_RE.search(s):
        return LESSON
    if any(p in low for p in _FRICTION_PATTERNS):
        return FRICTION
    return LESSON


def is_suppressed(value_class: str) -> bool:
    """该价值类是否在入库前被直接丢弃（env 噪音 + 源码回声）。"""
    return value_class in SUPPRESSED


# 展示去向（surface）：一条经验该摆在哪——"你的经验"墙 / "助手避坑"建议栏 / 不展示。
# 判据（方案 A 收口）：
# none       env/garbage（正常已在库外，此处兜底）
# advice     纯错误复现计数（rule error_sig）——只说"又报了这个错"、没给可复用修法，
# 无论工具摩擦还是 Python 报错，都归"助手能自动帮你避的坑"建议口吻，
# 不占用户经验墙（"频率≠价值"，方案 /L2 的彻底落地）
# experience LLM 真教训（g_source≠rule）+ 结构化"改出来的"模式（retry_pair/pivot/revert）
SURFACE_EXPERIENCE = "experience"
SURFACE_ADVICE = "advice"
SURFACE_NONE = "none"


def surface_of(rec: dict) -> str:
    """经验记录 → 展示去向。纯函数，读时派生（不落库、不需迁移）。"""
    if str(rec.get("value_class") or "") in SUPPRESSED:
        return SURFACE_NONE
    # 助手自身摩擦（编辑前没读、替换没匹配、参数传错…）不占用户经验墙——
    # 与 rule 侧 error_sig 同一去处：仍可注入（提醒 agent 别犯），但口吻是"避坑建议"。
    if str(rec.get("value_class") or "") == FRICTION:
        return SURFACE_ADVICE
    if str(rec.get("g_source") or "") != "rule":
        return SURFACE_EXPERIENCE  # LLM 提炼的真教训
    if str(rec.get("rule_kind") or "") == "error_sig":
        return SURFACE_ADVICE      # 纯复现计数 → 助手避坑
    return SURFACE_EXPERIENCE      # retry_pair/pivot/revert = 有做法的结构化模式
