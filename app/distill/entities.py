"""实体键（P1-4）：把「报错串 / 命令 / 项目」从文本里抽成可直捞的键。

为什么需要它：六层关系图里我们缺"实体"那张（其余三张：语义 = FTS + 质心
路由，时间 = 演化链 revision，因果 = supersedes）。而**"上次那个报错怎么修的"
是靠报错串直捞的，不是靠语义相似度**——"npm run build 报 Module not found"
和"删掉 node_modules 重装"的词元交集几乎为零，但它们是同一件事。

全确定性、零 LLM（纪律：记忆侧的判定不上模型）。

**读时派生，不落库**：规则会随用迭代，落库会让旧数据的键永远停在旧规则上。
与 `value_gate.surface_of` 同一口径（读时派生、纯函数、可单测）。

**但派生不等于每次重算**：实测 3000 条库单次召回里，逐条跑这套正则是 33ms
（p95 106ms 的一半），逐条重算分词同样是 33ms——两条加起来把召回拖过 100ms
红线。所以这里给结果加文本级缓存（`lru_cache`，key 就是文本本身，故不存在
"记录改了键还留旧值"的失效问题：文本变则 key 变）。命中时归零，未命中时
退回重算，结果永远正确。

键的粒度是**短语级**而非整行：整行会因为路径、行号、措辞不同而算成两个键，
那还不如不做。中英文报错归一到同一批规范值——本机会话里两者混着出现。
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

# 单条键的取值上限（兜底：键是索引不是正文）
MAX_KEY_LEN = 48
# 一条记录最多留几个键
MAX_KEYS = 6
# 文本级缓存容量。取 8192 是照"扫描上限 3000 条 × 每条 1 份文本"留了两倍余量：
# 库超过 8192 条后命中率下降（键被提前淘汰），只是退回重算，不产生错误结果。
# 与 app/proxy/detect.py 的 _cached_token_set 同为 lru_cache 而非手写 dict——
# 手写版没有上限，长会话下会无界增长。
KEY_CACHE_MAX = 8192

# 报错信号（本机会话里英文工具输出与中文描述混排，两边都要认）
_ERR_RE = re.compile(
    r"(?:(?:npm\s+)?err!|error|exception|traceback|fatal|failed|"
    r"cannot\s+find\s+module|module\s+not\s+found|no\s+such\s+file|"
    r"permission\s+denied|timed?\s?-?\s?out|"
    r"报错|出错|失败|超时|崩了|挂了)", re.I)

# 具体报错短语 → 规范值（中文说法归一到英文规范值，两边才能互相认）
_ERR_PHRASES = (
    # 这两个是同一件事的两个说法（node 与 webpack 的措辞差别），必须归一——
    # 否则"问的是 A 说法、记的是 B 说法"就互相认不出来，键白做了
    (r"module\s+not\s+found|cannot\s+find\s+module", "module not found"),
    (r"no\s+such\s+file", "no such file"),
    (r"permission\s+denied", "permission denied"),
    (r"timed?\s?-?\s?out", "timeout"),
    (r"connection\s+refused", "connection refused"),
    (r"out\s+of\s+memory", "out of memory"),
    (r"stack\s+overflow", "stack overflow"),
    (r"segmentation\s+fault", "segfault"),
    (r"build\s+failed", "build failed"),
    (r"超时", "timeout"),
    (r"内存溢出|内存不足", "out of memory"),
    (r"权限不足|没有权限", "permission denied"),
    (r"连接被拒绝", "connection refused"),
    (r"编译失败|构建失败", "build failed"),
)

# 短语表本身即报错证据：门禁 = 显式信号词 OR 短语表命中。 M2 之前
# 门禁只认显式信号词，"权限不足：chmod 777 试试"（同行无报错/失败等词）
# 这种中文说法永远抽不出 err 键——短语表列了也白列。
_ERR_PHRASE_RES = tuple(re.compile(p, re.I) for p, _c in _ERR_PHRASES)

# Python/JS 异常类名：ModuleNotFoundError → modulenotfound（去 Error/Exception 尾）
_CLS_RE = re.compile(r"\b([A-Za-z][\w]*(?:Error|Exception|Err))\b")

# 命令：工具 + 动作（+ 目标）。只留骨架，"npm run build --watch" 与
# "npm run build" 算同一条键。
_CMD_TOOLS = (r"npm|npx|yarn|pnpm|pip3?|python3?|git|mvn|gradle|cargo|"
              r"go|make|docker|kubectl|node|uv|pytest")
_CMD_RE = re.compile(
    rf"\b({_CMD_TOOLS})\s+([a-z][\w:.-]*)(?:\s+([a-z][\w:.-]*))?", re.I)

# 命令行里的开关/路径碎片不是正文
_CMD_NOISE = re.compile(r"^[-\d./]")

# 英文常用词：make/node/go/uv 与普通词碰撞（"make sure the config is right"），
# 动词或目标落进停用词表就不是命令骨架
_CMD_STOPWORDS = frozenset({
    "sure", "the", "a", "an", "it", "its", "this", "that", "these", "those",
    "to", "for", "of", "and", "or", "is", "are", "be", "been", "with",
    "on", "in", "at", "by", "from", "as", "so", "if", "then", "than",
})


def _norm(s: str) -> str:
    """键体规范化：小写、空白压缩、裁到上限。"""
    return re.sub(r"\s+", " ", str(s or "")).strip()[:MAX_KEY_LEN]


def _err_phrase(line: str) -> str:
    """一条报错行 → 规范短语（没有可归类的短语时返回空串）。"""
    for pat, canon in _ERR_PHRASES:
        if re.search(pat, line, re.I):
            return canon
    m = _CLS_RE.search(line)
    if m:
        name = m.group(1).lower()
        for suffix in ("exception", "error", "err"):
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        if name:
            return name
    return ""


def _err_keys(text: str) -> list[str]:
    out: list[str] = []
    for line in str(text or "").splitlines():
        if not (_ERR_RE.search(line)
                or any(r.search(line) for r in _ERR_PHRASE_RES)):
            continue
        # 先摘易变噪音（路径/时间戳/行号），再取短语——同一条错在不同机器上
        # 必须算出同一个键
        line = re.sub(r"[\w.-]*[/\\][\w./\\-]+", " ", line)
        line = re.sub(r"\b\d{4}-\d{2}-\d{2}[T ][\d:.]+\b", " ", line)
        line = re.sub(r":\d+:\d+", " ", line)
        phrase = _err_phrase(line)
        if phrase:
            out.append(f"err:{phrase}")
    return out


def _cmd_keys(text: str) -> list[str]:
    out: list[str] = []
    for m in _CMD_RE.finditer(str(text or "")):
        tool, verb, target = m.group(1), m.group(2), m.group(3)
        if not verb or verb.lower() in _CMD_STOPWORDS:
            continue
        parts = [tool.lower(), verb.lower()]
        if target and not _CMD_NOISE.match(target) \
                and target.lower() not in _CMD_STOPWORDS:
            parts.append(target.lower())
        out.append(f"cmd:{_norm(' '.join(parts))}")
    return out


def _proj_key(project: str) -> list[str]:
    """项目名（取路径最后一段）：同一个项目里的经验互相认得。

    路径本体不进键——用户机器路径属环境信息，进键只会让键在换机器后失效。
    """
    p = str(project or "").strip()
    if not p:
        return []
    name = os.path.basename(p.replace("\\", "/").rstrip("/"))
    return [f"proj:{_norm(name.lower())}"] if name else []


# 经验记录里参与"文本匹配"的字段。MCP 检索的 _searchable_text 与 keys_of
# 共用同一份定义（L8：此前两者各拼一次且字段集不同——实体键永远看不到
# evidence 里的报错原话，问句直捞报错串时对不上）。
TEXT_FIELDS = ("task", "action", "outcome", "state", "evidence")


def keys_of_text(text: str) -> list[str]:
    """文本 → 实体键（去重、保序、限量）。"""
    out: list[str] = []
    for key in _err_keys(text) + _cmd_keys(text):
        if key not in out:
            out.append(key)
        if len(out) >= MAX_KEYS:
            break
    return out


@lru_cache(maxsize=KEY_CACHE_MAX)
def cached_keys_of_text(text: str) -> tuple[str, ...]:
    """`keys_of_text` 的缓存版：同一段文本只跑一次正则。

    检索侧每条记录每次查询都要键，重算是 O(扫描条数) 的纯浪费——
    实测 3000 条时要 33ms，占单次召回的一半。返回 tuple 而非 list：
    不可变，多调用方共享同一实例是安全的（不要改成返回 list）。
    """
    return tuple(keys_of_text(text))


def keys_of(rec: dict) -> list[str]:
    """经验记录 → 实体键（报错 / 命令 / 项目）。读时派生，永不抛异常。

    文本源 = ``TEXT_FIELDS``（与 MCP 检索 ``_searchable_text`` 同一份字段集），
    证据原话里的报错串才能被实体键看到。
    """
    try:
        text = " ".join(str(rec.get(k) or "") for k in TEXT_FIELDS)
    except Exception:  # noqa: BLE001 读时派生：字段形状异常就是没键，不崩调用方
        return []
    return (list(cached_keys_of_text(text))
            + _proj_key(rec.get("project")))[:MAX_KEYS]


def keys_of_query(text: str) -> list[str]:
    """查询文本 → 实体键（不带项目：问句里没有项目名这个结构化来源）。"""
    return list(cached_keys_of_text(str(text or "")))
