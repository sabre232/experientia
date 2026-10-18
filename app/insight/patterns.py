"""模式检测器（W4-01）：全部确定性规则，不依赖 LLM。

三个维度（路线图文档）：
- 频率：同 trunk+category 下 action 文本相似度 ≥ 阈值的重复 ≥ 2 次
  （"至少发生 2 次"筛选标准）
- 路径：同 task 前缀下 action 序列的最长公共子序列 ≥ 3 步且出现 ≥ 2 次
  （session 内经验按 ts 排序构成 action 序列）
- 纠正：同 trunk 下 corrected 经验 ≥ 2 条且 state 文本聚类相似

相似度量 = difflib.SequenceMatcher 比率（标准库，零依赖，可复现）。
"""

from __future__ import annotations

import difflib
import hashlib
from collections import defaultdict

ACTION_SIM_THRESHOLD = 0.7   # 频率/路径：action 文本相似阈值（0.6 会让「做法一/做法二」这类
                             # 短串因共享 2 字前缀达到 0.667 而误聚，取 0.7 留出区分度）
STATE_SIM_THRESHOLD = 0.5    # 纠正：state 文本聚类阈值
PATH_MIN_STEPS = 3           # 路径：LCS 最少步数
PATH_PREFIX_CHARS = 8        # 路径："同 task 前缀"的截断长度


def _sim(a: str, b: str) -> float:
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _lcs_length(a: list[str], b: list[str]) -> int:
    """最长公共子序列长度（序列元素为 action 文本，精确匹配）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if x == y:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = max(prev[j], cur[j - 1])
        prev = cur
    return prev[-1]


def detect_frequency(exps: list[dict]) -> list[dict]:
    """同 trunk+category 下相似 action 重复 ≥ 2 次 → 候选固化模式。"""
    by_cat: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in exps:
        by_cat[(e.get("trunk") or "其他", e.get("category") or "未分类")].append(e)
    out = []
    for (trunk, category), items in sorted(by_cat.items()):
        # 取最高频的相似簇：第一条未归簇的经验为锚，后续相似的并入
        clustered: list[dict] = []
        for e in items:
            action = str(e.get("action", ""))
            for c in clustered:
                if _sim(action, str(c[0].get("action", ""))) >= ACTION_SIM_THRESHOLD:
                    c.append(e)
                    break
            else:
                clustered.append([e])
        for c in clustered:
            if len(c) < 2:
                continue
            n = sum(int(x.get("count") or 1) for x in c)
            out.append({
                "type": "frequency", "trunk": trunk, "category": category,
                "example": str(c[0].get("action", ""))[:120],
                "occurrences": n,
                "evidence": [x.get("id") for x in c if x.get("id")],
            })
    return out


def detect_path(exps: list[dict]) -> list[dict]:
    """同 task 前缀下，≥2 个 session 的 action 序列 LCS ≥ 3 步 → 可提炼 SOP。"""
    by_session: dict[str, list[str]] = defaultdict(list)
    for e in sorted(exps, key=lambda x: str(x.get("ts", ""))):
        sid = str(e.get("session_id") or "")
        action = str(e.get("action", "")).strip()
        if sid and action:
            by_session[sid].append(action)
    sequences = {sid: seq for sid, seq in by_session.items() if len(seq) >= PATH_MIN_STEPS}
    out = []
    sids = sorted(sequences)
    for i in range(len(sids)):
        for j in range(i + 1, len(sids)):
            a, b = sequences[sids[i]], sequences[sids[j]]
            lcs = _lcs_length(a, b)
            if lcs >= PATH_MIN_STEPS:
                out.append({
                    "type": "path", "trunk": "", "category": "",
                    "example": " → ".join(a[:PATH_MIN_STEPS + 1])[:160],
                    "occurrences": 2,
                    "evidence": [sids[i], sids[j]],
                })
    # 去重（同一对 session 只报一次，上面循环结构天然保证）
    seen, dedup = set(), []
    for p in out:
        key = (tuple(sorted(p["evidence"])), p["example"])
        if key not in seen:
            seen.add(key)
            dedup.append(p)
    return dedup


def detect_corrections(exps: list[dict]) -> list[dict]:
    """同 trunk 下 corrected ≥ 2 条且 state 相似聚类 → 用户反复纠正同一类问题。"""
    by_trunk: dict[str, list[dict]] = defaultdict(list)
    for e in exps:
        if e.get("corrected"):
            by_trunk[e.get("trunk") or "其他"].append(e)
    out = []
    for trunk, items in sorted(by_trunk.items()):
        clustered: list[dict] = []
        for e in items:
            state = str(e.get("state", ""))
            for c in clustered:
                if _sim(state, str(c[0].get("state", ""))) >= STATE_SIM_THRESHOLD:
                    c.append(e)
                    break
            else:
                clustered.append([e])
        for c in clustered:
            if len(c) < 2:
                continue
            cats = {e.get("category", "") for e in c}
            cat = next(iter(cats)) if len(cats) == 1 else ""
            out.append({
                "type": "correction", "trunk": trunk, "category": cat,
                "example": str(c[0].get("state", ""))[:120],
                "occurrences": len(c),
                "evidence": [x.get("id") for x in c if x.get("id")],
            })
    return out


# P1: 检测结果缓存——经验列表不变时直接返回上次结果，避免 O(n²) 全量重算
_detect_cache: dict[str, list[dict]] = {}


def _cache_key(exps: list[dict]) -> str:
    ids = sorted(e.get("id", "") for e in exps if e.get("id"))
    return hashlib.md5("|".join(ids).encode()).hexdigest()


def detect_all(exps: list[dict]) -> list[dict]:
    """三个检测器全跑，按类型聚合。

    rule 坑卡不参与模式挖掘：其 action 是跨会话合并用的共享指纹串
    （如 fix:retry-with-changed-args），会被误判成"同一做法反复出现"；
    坑卡已有专属展示/蒸馏通道（修复方案）。"""
    exps = [e for e in exps if str(e.get("g_source") or "") != "rule"]
    key = _cache_key(exps)
    if key in _detect_cache:
        return _detect_cache[key]
    result = detect_frequency(exps) + detect_path(exps) + detect_corrections(exps)
    _detect_cache.clear()
    _detect_cache[key] = result
    return result
