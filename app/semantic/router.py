"""语义归类路由（修复方案 -P1-1，打通注入最后一公里）。

现状病灶：detect.py 用"历史 task 原文 token 字面覆盖率 ≥0.5"归类新任务，
换一种说法就永不命中 → 坑卡做得再准也注不进去。

两级方案（同一入口，按能力自动降级）：
- 有 embedding（可选后端，features.semantic_embedding 开启 + 模型就位）：
  每类历史样本取均值成质心，新任务 cosine 最高类过阈值且明显领先次优才命中
  （semantic-router 质心法）。
- 无 embedding（默认）：MiniBM25（IDF 加权的词集打分，纯标准库零依赖）
  对每类历史样本打分取 max，同样要求"过线 + 领先"。BM25 对"换了措辞但
  关键词在"的中文短任务显著优于覆盖率口径（覆盖率要求样本一半词在场，
  改写句必挂；BM25 按稀有词加权，共同的核心词就够）。

两级都命中不了 → 返回 None，调用方落"其他/未分类"（行为与现状一致，零回归）。
"""

from __future__ import annotations

import logging
import math
import threading

from .embedder import get_embedder  # noqa: F401（对外从这里再导出）

logger = logging.getLogger("experientia.semantic.router")

# 判定参数（拍板挂 config.semantic.* 前先用保守默认，测试锁定）
BM25_MIN_SCORE = 1.0      # 命中绝对线（mini 打分：一个稀有词命中≈1+）
BM25_MARGIN = 1.4         # 最优须 ≥ 次优 ×1.4（不明显领先宁可不注）
COS_MIN = 0.50            # embedding 余弦命中线（bge 系相似句经验值）
COS_MARGIN = 1.08         # 质心 cosine 领先倍率

_k1, _b = 1.5, 0.75


class MiniBM25:
    """几十行标准库 BM25：docs 为分好词的文档集合（token set 列表）。"""

    def __init__(self, docs: list[set[str]]):
        self.docs = docs
        n = len(docs) or 1
        self.avg_len = (sum(len(d) for d in docs) / n) or 1.0
        df: dict[str, int] = {}
        for d in docs:
            for t in d:
                df[t] = df.get(t, 0) + 1
        self.idf = {t: math.log(1.0 + (n - c + 0.5) / (c + 0.5))
                    for t, c in df.items()}

    def scores(self, query: set[str]) -> list[float]:
        out = []
        for d in self.docs:
            if not d:
                out.append(0.0)
                continue
            s = 0.0
            for t in query:
                if t in d:
                    tf = 1.0  # token set 去重，tf 恒 1（口径与样本构建一致）
                    s += self.idf.get(t, 0.0) * _k1 / (_k1 * (1 - _b + _b) + 1.0)
            out.append(s)
        return out


# 进程内缓存：known_categories 内容不变不重算（捕获每轮/每请求都调，省 CPU）
_cache_lock = threading.Lock()
_cache: dict[str, tuple] = {}   # signature -> (mode, prepared)


def _signature(known: dict) -> str:
    parts = []
    for key in sorted(known):
        parts.append(f"{key[0]}/{key[1]}:" + "|".join(str(s)[:80] for s in known[key]))
    return str(hash("\n".join(parts)))


def _prepare_lexical(known: dict):
    flat: list[tuple] = []
    docs: list[set[str]] = []
    from ..proxy.detect import _token_set  # 复用同一分词口径（二元组+ASCII 词）
    for key, samples in known.items():
        for s in samples:
            flat.append(key)
            docs.append(_token_set(str(s)))
    if not docs:
        return None
    return (MiniBM25(docs), flat)


def _prepare_centroids(known: dict, embedder):
    vecs = {}
    texts = [str(s) for samples in known.values() for s in samples]
    if not texts:
        return None
    try:
        embedded = embedder.embed(texts)
    except Exception as exc:
        logger.info("embedding 批算失败，本轮走 BM25: %s", exc)
        return None
    it = iter(embedded)
    for key, samples in known.items():
        cat_vecs = [list(next(it)) for _ in samples]
        if not cat_vecs:
            continue
        dim = len(cat_vecs[0])
        cen = [sum(v[i] for v in cat_vecs) / len(cat_vecs) for i in range(dim)]
        norm = math.sqrt(sum(x * x for x in cen)) or 1.0
        vecs[key] = [x / norm for x in cen]
    return vecs or None


def classify(content: str, known_categories: dict, store=None):
    """新任务文本 → ((trunk, category), score) 或 None（调用方落未分类）。

    store 提供且 embedding 开关开+后端可用 → 质心 cosine；否则 BM25。
    两条路都要求"过绝对线 + 明显领先次优"，宁缺毋滥（错归类=错注入）。"""
    if not content or not known_categories:
        return None
    from ..proxy.detect import _token_set

    embedder = None
    if store is not None:
        try:
            embedder = get_embedder(store)
        except Exception:
            embedder = None

    sig = _signature(known_categories)
    mode = "emb" if embedder is not None else "bm25"
    with _cache_lock:
        prepared = _cache.get(sig, (None, None))
        if prepared[0] != mode:
            prepared = None
        else:
            prepared = prepared[1]
    try:
        if embedder is not None:
            if prepared is None:
                prepared = _prepare_centroids(known_categories, embedder)
                if prepared is not None:
                    with _cache_lock:
                        _cache.clear()
                        _cache[sig] = (mode, prepared)
            if prepared is not None:
                qv = embedder.embed([content])
                if qv:
                    v = list(qv[0])
                    norm = math.sqrt(sum(x * x for x in v)) or 1.0
                    v = [x / norm for x in v]
                    scored = sorted(
                        ((key, sum(a * b for a, b in zip(v, cen)))
                         for key, cen in prepared.items()),
                        key=lambda x: -x[1])
                    best, bs = scored[0]
                    second = scored[1][1] if len(scored) > 1 else 0.0
                    if bs >= COS_MIN and (second <= 0 or bs >= second * COS_MARGIN):
                        return (best, bs)
                    return None
        # BM25 路（默认/降级）
        if prepared is None:
            prepared = _prepare_lexical(known_categories)
            if prepared is None:
                return None
            with _cache_lock:
                _cache.clear()
                _cache[sig] = (mode, prepared)
        bm25, flat = prepared
        scores = bm25.scores(_token_set(content))
        best_key, best, second = None, 0.0, 0.0
        for key, sc in zip(flat, scores):
            if sc > best:
                best_key, best, second = key, sc, best
            elif sc > second:
                second = sc
        if best_key and best >= BM25_MIN_SCORE and (second <= 0 or best >= second * BM25_MARGIN):
            return (best_key, best)
    except Exception as exc:
        logger.info("语义路由异常（回落调用方原逻辑）: %s", exc)
    return None
