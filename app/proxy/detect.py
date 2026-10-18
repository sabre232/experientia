"""上下文自动感知（产品文档 -15.6）：Agent / API 模型 / 任务 / Session 全自动识别。

用户只关心"我选哪个模型"，其他全部自动化（核心设计原则）。
"""

from __future__ import annotations

import re
import time
from functools import lru_cache

# 扩展 CJK 范围：包含基本区 + CJK 扩展 A + CJK 兼容 + CJK 扩展 B
# 覆盖现代中文常见汉字，确保扩展区字符能参与词集匹配
_CJK_RANGE = "\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff"

def _token_set(text: str) -> set[str]:
    """任务归类匹配用词集：ASCII 词（≥2 字符）+ CJK 字符二元组。

    中文无空格分词，整词/整句匹配都失效；二元组是零依赖的近似分词，
    覆盖率口径下对短样本（2 个二元组）也稳定。"""
    text = (text or "").lower()
    tokens = {w for w in re.findall(r"[a-z0-9_]{2,}", text)}
    cjk_runs = re.findall(f"[{_CJK_RANGE}]+", text)
    for run in cjk_runs:
        if len(run) >= 2:
            tokens.update(run[i:i + 2] for i in range(len(run) - 1))
        elif len(run) == 1:
            tokens.add(run)
    return tokens


# P-001：样本词集缓存，避免请求间重复 tokenize 相同样本文本。
# 用 lru_cache 而非手写 dict：手写版**无上限**，长会话（数月不接模型时样本持续
# 累积）会无界增长；这里给 4096 条上限，超出按最久未用淘汰。
# 注意：frozenset 不可变，多调用方共享同一实例是安全的（不要改成返回 set）。
@lru_cache(maxsize=4096)
def _cached_token_set(text: str) -> frozenset:
    """带缓存的词集计算，相同样本文本只 tokenize 一次。"""
    return frozenset(_token_set(text))

# ---------- 15.3 Agent 识别 ----------

_UA_AGENT_PATTERNS = [
    ("workbuddy", "workbuddy"),
    ("codebuddy", "codebuddy"),
    ("cursor", "cursor"),
    ("trae", "trae"),
    ("claude-code", "claude-code"),
    ("cline", "cline"),
    ("codex", "codex"),
    ("gemini", "gemini-cli"),
]


def agent_names() -> set[str]:
    """可识别的 agent 名集合（UA 模式口径），供治理视图与实际接入的
    session agent 求并集（H-A0）——外部模块不再私有引用 _UA_AGENT_PATTERNS。"""
    return {name for _pat, name in _UA_AGENT_PATTERNS}


# ---------- Agent 显示名称映射（H-A0：用户看到的是"Claude Code"而非"claude-code"）----------

_AGENT_DISPLAY_NAMES: dict[str, str] = {
    "claude-code": "Claude Code",
    "codex": "Codex",
    "codebuddy": "CodeBuddy",
    "cursor": "Cursor",
    "gemini-cli": "Gemini CLI",
    "openclaw": "OpenClaw",
    "workbuddy": "WorkBuddy",
    "hermes": "Hermes",
    "trae": "Trae",
    "cline": "Cline",
    "roo-code": "Roo Code",
    "aider": "Aider",
    "qwen-code": "Qwen Code",
    "iflow": "IFlow",
    "opencode": "OpenCode",
    "goose": "Goose",
    "kilocode": "KiloCode",
    "zed": "Zed",
    "openhands": "OpenHands",
    "dsh": "DSH",
    "copilot-cli": "Copilot CLI",
    "windsurf": "Windsurf",
    "qclaw": "QClaw",
    "qoder": "Qoder",
}


def agent_display_name(name: str) -> str:
    """内部 agent 名 → 用户友好显示名。未知名称原样返回（兼容未来新增 adapter）。"""
    return _AGENT_DISPLAY_NAMES.get(name, name)


def detect_agent(headers: dict[str, str]) -> str:
    """识别优先级：User-Agent 头 → 自定义头 x-agent-name → unknown。"""
    ua = headers.get("user-agent", "").lower()
    for pattern, name in _UA_AGENT_PATTERNS:
        if pattern in ua:
            return name
    if "x-workbuddy" in headers:
        return "workbuddy"
    if "x-codebuddy" in headers:
        return "codebuddy"
    if headers.get("x-agent-name"):
        return headers["x-agent-name"]
    return "unknown"


# ---------- 15.4 API/模型识别 ----------

def detect_api_and_model(model: str) -> dict:
    """model 字段前缀最可靠。"""
    m = (model or "").lower()
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3") or m.startswith("chatgpt"):
        return {"provider": "openai", "model": model}
    if m.startswith("claude"):
        return {"provider": "anthropic", "model": model}
    if m.startswith("gemini"):
        return {"provider": "google", "model": model}
    if m.startswith("deepseek"):
        return {"provider": "deepseek", "model": model}
    return {"provider": "local", "model": model}


# ---------- 15.5 任务识别（不预设行业） ----------

DEFAULT_SEED_KEYWORDS = {
    "其他": [],
}


def detect_task_context(
    messages: list[dict],
    seed_keywords: dict[str, list[str]],
    known_categories: dict[tuple[str, str], list[str]],
    store=None,
) -> dict:
    """识别优先级（最后一公里修复 -P1-1）：
    语义路由（embedding 质心 / MiniBM25 自动降级）> 历史字面覆盖（兜底）
    > 种子关键词 > 其他/未分类。"""
    content = " ".join(
        str(m.get("content", ""))
        for m in messages[:3]
        if isinstance(m, dict) and m.get("content")
    )
    content = content[:2000]
    content_tokens = _token_set(content)
    # 1a. 语义路由：BM25（IDF 加权，改写句也能命中）；开关+模型就位时
    # 走 embedding 质心。宁缺毋滥：过线且明显领先次优才归。
    if known_categories:
        try:
            from ..semantic import router as _router

            hit = _router.classify(content, known_categories, store=store)
            if hit is not None:
                return {"trunk": hit[0][0], "category": hit[0][1]}
        except Exception:
            pass  # 路由异常走旧字面兜底，绝不拦捕获
    # 1b. 旧口径兜底：历史 task 特征词覆盖率 ≥0.5（router 未命中时同义复核，
    # 行为与历史一致——只有 router 判"不明显领先"时才会落到这里）
    if known_categories:
        best_key, best_score = None, 0.0
        for (trunk, category), samples in known_categories.items():
            best_sample_score = 0.0
            for s in samples:
                s_tokens = _cached_token_set(str(s))
                if not s_tokens or not content_tokens:
                    continue
                score = len(s_tokens & content_tokens) / len(s_tokens)
                best_sample_score = max(best_sample_score, score)
            if best_sample_score > best_score:
                best_key, best_score = (trunk, category), best_sample_score
        if best_key and best_score >= 0.5:
            return {"trunk": best_key[0], "category": best_key[1]}
    # 2. 用户配置的种子关键词
    for trunk, keywords in seed_keywords.items():
        if trunk == "其他":
            continue
        if any(kw in content for kw in keywords if kw):
            return {"trunk": trunk, "category": _infer_category(content, trunk, seed_keywords)}
    # 3. 默认：暂归"其他"，积累后自动聚类成新类
    return {"trunk": "其他", "category": "未分类"}


def _infer_category(content: str, trunk: str, seed_keywords: dict[str, list[str]]) -> str:
    for name, keywords in seed_keywords.items():
        if name == trunk:
            continue
        if any(kw in content for kw in keywords if kw):
            return name
    return trunk


def known_categories_from_store(store) -> dict[tuple[str, str], list[str]]:
    """从已有经验的 task 字段取"历史经验匹配"样本（每类最近 20 条 task 文本）。

    M-5：读 store 层维护的派生索引 categories_index.json（经验写口重建），
    请求路径不再全量扫 experience.jsonl；索引缺失（老数据目录/被 wipe）时
    现场重建落盘自愈。口径与全扫版完全一致（含已蒸馏、去重保序、每类 20 条）。"""
    index = store.load_category_index()
    if index is None:
        index = store.rebuild_category_index()
    if index is None:
        return {}
    known: dict[tuple[str, str], list[str]] = {}
    for key, tasks in index.items():
        if not isinstance(tasks, list) or not tasks:
            continue
        trunk, _, category = str(key).partition("/")
        known[(trunk or "其他", category or "未分类")] = [str(t) for t in tasks]
    return known


# ---------- 15.6 Session 追踪 ----------

SESSION_IDLE_TIMEOUT_SECONDS = 30 * 60  # 无请求 >30 分钟 → session 结束


# 自动 session（M-6）：同一 (agent, user, project) 只要请求间隔 ≤30 分钟
# 就续同一 session——边界判据是"间隔"，不是固定时间窗（10 分钟绝对窗会把
# 9:59:59 与 10:00:01 的连续对话切成两段）。段号 = 该段首个请求的 epoch 秒：
# 单调递增，进程重启后段号只增不撞，不会覆盖 sessions.jsonl 里的历史同 key 记录。
# 状态放进程内存：get_session_id 只有代理单进程调用（三通道中代理通道
# 是唯一自动聚合来源）；重启丢状态 = 下次请求开新段，无害。
_AUTO_SEGMENTS_MAX = 1000
_auto_segments: dict[tuple[str, str, str], tuple[int, float]] = {}


def _auto_session_id(agent: str, user_id: str, project: str,
                     now: float | None = None) -> str:
    now = time.time() if now is None else now
    key = (agent, user_id, project)
    entry = _auto_segments.get(key)
    if entry is None:
        seg = int(now)
        if len(_auto_segments) >= _AUTO_SEGMENTS_MAX:
            stale = [k for k, (_, ts) in _auto_segments.items()
                     if now - ts > SESSION_IDLE_TIMEOUT_SECONDS]
            for k in stale:
                _auto_segments.pop(k, None)
            if len(_auto_segments) >= _AUTO_SEGMENTS_MAX:
                # 没有可清的陈旧项时按最旧淘汰一例——否则
                # 超大规模 (agent,user,project) 组合下字典缓慢无界增长
                oldest = min(_auto_segments,
                             key=lambda k: _auto_segments[k][1])
                _auto_segments.pop(oldest, None)
    elif now - entry[1] > SESSION_IDLE_TIMEOUT_SECONDS:
        seg = int(now)  # 间隔超 30 分钟 → 新段（与 tracker 空闲超时同判据）
    else:
        seg = entry[0]
    _auto_segments[key] = (seg, now)
    return f"auto-{agent}-{user_id}-{project}-{seg}"


def get_session_id(headers: dict[str, str], body: dict) -> str:
    """x-session-id → metadata.thread_id → (agent, user, project) 间隔聚合。

    回退不再每请求一个新 id：典型 OpenAI 客户端不发会话头，逐请求新 session 会让
    sessions.jsonl 无界增长、Nth-vs-1st 对比口径失真（每"次"= 每请求）。"""
    sid = headers.get("x-session-id")
    if sid:
        return sid
    # 客户端发 "metadata": "x" 时原写法 AttributeError →
    # FastAPI 裸 500（违反 fail-open）；非 dict 一律按无 thread_id 处理。
    md = body.get("metadata")
    thread_id = md.get("thread_id") if isinstance(md, dict) else None
    if thread_id:
        return f"thread-{thread_id}"
    agent = detect_agent(headers)
    user_id = headers.get("x-user-id", "default")
    project = str(body.get("project") or "")
    return _auto_session_id(agent, user_id, project)
