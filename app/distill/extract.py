"""技术把手抽取（蒸馏兜底方案）：兜底最该保住的是能复用/检索的硬信息。

抽什么（全部确定性 regex，不碰模型）：文件路径 / 错误信息 / 参数取值 /
URL / 版本号。只读原文（采集层 Message.content / tool_result.output），
不写回采集层 schema（防歪 #7）。
"""

from __future__ import annotations

import re

# 文件路径（相对 app/a.py / 绝对 /a/b.py / 盘符 F:\a\b.py；
# 后缀白名单防误伤普通词；lookbehind 防从路径中间起匹配）
_PATH_RE = re.compile(
    r"(?<![\w/.])(?:(?:[A-Za-z]:[/\\])|(?:[\w.-]+[/\\])?)"
    r"[\w./\\-]*\.(?:py|ts|tsx|js|jsx|md|json|ya?ml|sql|sh|go|rs|java|toml)\b")
# 错误信息：关键词后的短段（到行尾，限长防吞整段日志）；
# 逐字符负向断言遇 URL 即停——URL 单独成把手，错误段不整段吞掉
# （否则 URL 被 span 重叠规则挡住抽不出来）
_ERR_RE = re.compile(r"\b(?:Error|Exception|Traceback|HTTP \d{3})[:：]?\s*(?:(?!https?://)[^\n]){3,120}")
# 参数/取值：port=8100、timeout=1800 这类 key=数值
_PARAM_RE = re.compile(r"\b[a-z][a-z0-9_]{1,30}=\d+(?:\.\d+)?[kKmM]?\b")
_URL_RE = re.compile(r"https?://[^\s\"'`<>)\]]+")
_VER_RE = re.compile(r"\bv?\d+\.\d+\.\d+\b")

MAX_HANDLES = 10  # 单条经验把手上限（防记录膨胀）
HANDLE_MAX_LEN = 120


def extract_handles(text: str) -> list[str]:
    """从原文抽技术把手：按出现顺序去重，≤ MAX_HANDLES 条、单条限长。"""
    text = text or ""
    found: list[str] = []
    spans: list[tuple[int, int]] = []

    def _add(m: re.Match[str]) -> None:
        s = m.group(0).strip().rstrip("。；;,.")
        if not s or len(s) > HANDLE_MAX_LEN:
            return
        # 与已抽把手重叠（错误段包含 URL/路径）→ 跳过
        for a, b in spans:
            if m.start() < b and m.end() > a:
                return
        if s in found:
            return
        found.append(s)
        spans.append((m.start(), m.end()))

    # 顺序即优先级：先抽的占 span，后抽的重叠项被挡（URL 先于参数，
    # 防 url?port=8100 里的参数被误抽成独立把手）
    for rx in (_URL_RE, _PATH_RE, _ERR_RE, _VER_RE, _PARAM_RE):
        for m in rx.finditer(text):
            _add(m)
            if len(found) >= MAX_HANDLES:
                return found
    return found
