"""rule 坑卡统一渲染（同一坑两处展示、两套状态词 → 收敛一处）。

首页「刚发现的坑」、踩坑 tab T1 兜底、（经 API 归一的）经验库卡片共用
本模块：kind 标签 + 模板句正文 + 状态词，口径改一处全变。
"""

from __future__ import annotations

from ..distill.mining import rule_line_text
from .i18n import t

KIND_LABEL = {
    "retry_pair": "命令连败后修好",
    "error_sig": "反复出现的报错",
    "revert": "改动被推翻",
    "pivot": "路径落空转好",
}

# 助手手笨（agent_friction）→ 建议口吻话术。key = 中文源串（过 t() 译 7 语），
# 原始报错串作为数据嵌入框架，符合 「经验正文不翻译、UI 话术才翻译」。
# 三元组（报错特征, 桶短标题, 建议句）：桶短标题为"同类归堆"（方案 B）
# 新增，建议句沿用既有词条；同一桶的多条特征行短标题/建议句重复填写（表薄，不抽象）。
_FRICTION_ADVICE = (
    ("has not been read yet", "编辑前没先读文件", "编辑前先读文件再改"),
    ("string to replace not found", "替换没匹配上", "替换前先核对原文是否已变"),
    ("edit error on", "替换没匹配上", "替换前先核对原文是否已变"),
    ("command blocked for security", "命令被安全策略拦下", "改用合规的命令写法"),
    ("modified since read", "拿着旧内容改文件", "改动前重新读取最新内容"),
    ("read it again", "拿着旧内容改文件", "改动前重新读取最新内容"),
    ("expected string", "传的参数类型不对", "调用前检查参数类型"),
    ("invalid parameters", "传的参数类型不对", "调用前检查参数类型"),
    ("can not find skill", "要用的技能没装", "先确认所需技能已安装"),
    ("cannot find skill", "要用的技能没装", "先确认所需技能已安装"),
    ("replace_all is false", "一处改还是全改没说清", "多处匹配时明确替换范围"),
    ("found # matches", "一处改还是全改没说清", "多处匹配时明确替换范围"),
    ("no changes to make", "其实没改动却提交", "提交前先确认确有改动"),
)

# 未命中任何特征时的兜底通用桶（FileNotFoundError、SyntaxError 等常规异常
# 与将来的新报错种类都落这里）——保证归堆后次数与明细严格守恒。
_FRICTION_GENERIC = ("操作顺序或参数不对", "遇到这类工具报错前先自查操作顺序与参数")


def rule_display(item: dict) -> tuple[str, str]:
    """坑卡 → (类型标签, 人读正文)。正文用确定性模板句（指纹不外漏）。"""
    kind = t(KIND_LABEL.get(str(item.get("rule_kind") or ""), "坑"))
    return kind, rule_line_text(item)


def friction_advice(item: dict) -> str:
    """agent_friction 坑卡 → 一句建议口吻（助手第一人称，指向它自己该怎么改）。

    匹配不到具体子类时回落到通用建议句。所有句柄均为 t() 中文源串。
     同类归堆后首页/成长页改用 group_friction；本函数保留至确认
    再无引用后清理。"""
    state = str(item.get("state") or item.get("task") or "").lower()
    n = int(item.get("count") or 1)
    advice_key = _FRICTION_GENERIC[1]
    for pat, _title, phrase in _FRICTION_ADVICE:
        if pat in state:
            advice_key = phrase
            break
    return t("我发现自己常在「{sig}」上反复栽跟头（共 {n} 次），建议{advice}。",
             sig=_bare_sig(item), n=n, advice=t(advice_key))


def friction_bucket(item: dict) -> tuple[str, str]:
    """一张避坑卡 → (桶短标题, 建议句) 中文源串（未过 t()）。

    复用 _FRICTION_ADVICE 的特征匹配；未命中落通用桶，永远不会漏计数。"""
    state = str(item.get("state") or item.get("task") or "").lower()
    for pat, title, advice in _FRICTION_ADVICE:
        if pat in state:
            return (title, advice)
    return _FRICTION_GENERIC


def group_friction(items: list[dict]) -> list[dict]:
    """避坑明细 → 按桶聚合（次数降序）。

    归堆只发生在展示层：数据层一条记录都不合并（注入/闸门/幂等/试用期都以
    明细为依据）。每桶 {title, advice, count, sessions, samples}，次数严格
    守恒 sum(桶) == sum(明细)。"""
    buckets: dict[str, dict] = {}
    for it in items:
        title, advice = friction_bucket(it)
        b = buckets.setdefault(title, {"title": title, "advice": advice,
                                       "count": 0, "sessions": [],
                                       "samples": []})
        b["count"] += int(it.get("count") or 1)
        sid = str(it.get("session_id") or "")
        if sid and sid not in b["sessions"]:
            b["sessions"].append(sid)
        sig = _bare_sig(it)
        if sig and sig not in b["samples"]:
            b["samples"].append(sig)
    return sorted(buckets.values(), key=lambda b: -b["count"])


def _bare_sig(item: dict) -> str:
    """从坑卡取一段可读报错串（去 sig: 前缀），仅截断，不改写（数据层）。"""
    raw = str(item.get("state") or item.get("task") or "")
    if raw.startswith("sig:"):
        raw = raw[4:]
    return raw[:60].strip()


def state_word(injectable: bool) -> tuple[str, str]:
    """状态词（与 playbook 三态同字表）：injectable → 记住了，否则留意中。"""
    return (t("记住了"), "err") if injectable else (t("留意中"), "warn")
