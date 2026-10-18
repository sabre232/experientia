"""规模基准（波 3 /）：波 2 的"与内容量解耦"必须以**行为**钉住，不能只靠墙钟。

判据（确定性，抗 CI 抖动）：
- `stats()` / `experience_categories()` / `iter_experiences(surface, limit)`
  在索引可用时**绝不回读 experience.jsonl**——setup 阶段构建一次索引即可，
  之后这些路径必须走 SQLite（O(1)/O(distinct)/O(limit)）。
- 另加一条**宽松**的墙钟比值断言（100k 相对 1k 倍数 < 6）作兜底：若哪天被改回
  全量 O(N)，比值会立刻爆表被抓。
- ④ 搜索索引增量维护：用 sqlite3 trace 数"追加 1 条会话"的写入语句数，
  50 条与 500 条规模下必须完全相同（O(变化) 而非 O(N) 全量重建）。

不依赖宿主机真实状态（AGENTS 铁律 5）：一律临时数据目录 + 直接落 JSONL + Store 建索引。
"""

from __future__ import annotations

import json
import time

from app.store.store import Store
from app.distill import value_gate as _vg


def _make_store(tmp_path, n: int) -> Store:
    """直接构造 n 条 experience.jsonl（快，避免逐条 append 的 O(N²)），再建索引。"""
    lines = [
        json.dumps({"id": f"e{i}", "agent": "a", "trunk": "编程", "category": "调试",
                    "task": f"任务{i}", "action": "解决", "state": f"err{i}",
                    "G": 0.9}, ensure_ascii=False)
        for i in range(n)
    ]
    (tmp_path / "experience.jsonl").write_text("\n".join(lines) + "\n",
                                               encoding="utf-8")
    store = Store(tmp_path)          # 构造即 rebuild_if_stale → 建索引
    store.ensure_layout()
    assert store._expdb is not None, "索引未建立，规模判据失去意义"
    return store


def _count_jsonl_reads(store: Store) -> dict:
    """包装 _iter_jsonl，只统计 experience.jsonl 的读取次数（sessions 等不计）。"""
    counter = {"n": 0}
    orig = store._iter_jsonl

    def counting(fname):
        if fname == "experience.jsonl":
            counter["n"] += 1
        return orig(fname)

    store._iter_jsonl = counting  # 实例级覆盖，不改类
    return counter


def test_scaling_paths_never_reread_jsonl(tmp_path):
    """索引可用时：stats / 分类 / 首页列表都不回读 experience.jsonl（与条数无关）。"""
    store = _make_store(tmp_path, 2000)
    counter = _count_jsonl_reads(store)

    st = store.stats()
    assert st["experiences"] == 2000 and st["pending"] == 2000
    cats = store.experience_categories()
    assert cats == ["调试"]
    items = list(store.iter_experiences(surface=_vg.SURFACE_EXPERIENCE, limit=300))
    assert len(items) == 300, "LIMIT 未按预期下推/生效"

    assert counter["n"] == 0, (
        f"回退到 JSONL 全量读（{counter['n']} 次）——波 2 的 O(N)→O(1) 出现回退")


def test_list_limit_is_pushed_down(tmp_path):
    """surface + limit 下推：只返回前 limit 条（写入序），且不触发全表 Python 过滤。"""
    store = _make_store(tmp_path, 1000)
    got = list(store.iter_experiences(surface=_vg.SURFACE_EXPERIENCE, limit=10))
    assert [x["id"] for x in got] == [f"e{i}" for i in range(10)]


def test_growth_ratio_bounded(tmp_path):
    """宽松兜底（抗 CI 抖动），两层判据：

    1. `iter_experiences(surface, limit)` 是**真 O(limit)**（SQL 索引命中）→
       100k 相对 1k 倍数 < 6；
    2. `stats()` / `experience_categories()` 走 SQLite（SQL 级 O(N) 扫描，常数极小，
       ~10ms/10万条）——给**绝对**宽松上限（< 80ms）。真被改回"JSONL 全量解析"
       时这两条会到数百 ms 级，立刻被抓。"""
    small_dir = tmp_path / "small"
    big_dir = tmp_path / "big"
    small_dir.mkdir()
    big_dir.mkdir()
    s_small = _make_store(small_dir, 1000)
    s_big = _make_store(big_dir, 100_000)

    def _min_ms(fn, repeats: int = 3) -> float:
        best = float("inf")
        for _ in range(repeats):
            t = time.perf_counter()
            fn()
            best = min(best, time.perf_counter() - t)
        return best * 1000.0

    def _list(store: Store):
        return list(store.iter_experiences(surface=_vg.SURFACE_EXPERIENCE, limit=300))

    _list(s_small), _list(s_big)  # 预热（首连/语句编译）
    t_list_small = _min_ms(lambda: _list(s_small))
    t_list_big = _min_ms(lambda: _list(s_big))
    ratio = t_list_big / max(t_list_small, 1e-3)
    assert ratio < 6.0, (
        f"列表疑似退化为 O(N)：100k/1k 倍数={ratio:.1f} "
        f"（{t_list_big:.1f}ms vs {t_list_small:.1f}ms）")

    t_stats_big = _min_ms(s_big.stats)
    t_cats_big = _min_ms(s_big.experience_categories)
    assert t_stats_big < 80.0, f"stats() 10万条耗时 {t_stats_big:.1f}ms —— 疑似回退 JSONL 全量解析"
    assert t_cats_big < 80.0, f"分类 10万条耗时 {t_cats_big:.1f}ms —— 疑似回退 Python 全量遍历"


def _search_sessions(n: int) -> list[dict]:
    return [{"agent": "a", "session_id": f"s{i}", "user_messages": [f"内容{i}"],
             "assistant_messages": [], "events": []} for i in range(n)]


def test_search_index_incremental_writes_are_scale_independent(tmp_path):
    """④：追加 1 条会话时，写入语句数必须**与索引规模无关**（O(变化) 而非 O(N)）。

    判据（确定性，不靠墙钟）：用 sqlite3 trace 数一次增量对齐里落到
    `sess_fts` / `sess_rows` 的写语句——50 条与 500 条规模下应**完全相同**，
    且恰好 = 「1 行 FTS 插入 + 1 行映射插入」。若哪天退回"整表 DELETE + 全量重插"，
    big 会变成 ~500，立刻被抓。
    """
    from app.store.search_index import SearchIndex

    def _writes_for(n: int) -> dict:
        d = tmp_path / f"n{n}"
        d.mkdir()
        idx = SearchIndex(d)
        base = _search_sessions(n)
        (d / "sessions.jsonl").write_bytes(b"x" * 1)
        idx.search(base, "内容0")          # 建索引（首次连接）
        assert idx._conn is not None
        (d / "sessions.jsonl").write_bytes(b"x" * 2)   # 指纹变化 → 触发一次增量对齐

        counts = {"fts": 0, "rows": 0}

        def _rec(sql: str) -> None:
            low = sql.lower()
            if low.startswith(("insert", "update", "delete")):
                if "sess_fts" in low:
                    counts["fts"] += 1
                elif "sess_rows" in low:
                    counts["rows"] += 1

        idx._conn.set_trace_callback(_rec)
        try:
            idx.search(base + _search_sessions(n + 1), "内容1")
        finally:
            idx._conn.set_trace_callback(None)
        return counts

    small = _writes_for(50)
    big = _writes_for(500)
    assert small == big, (
        f"追加 1 条的写入语句随规模变化：{small} vs {big}（疑似退化为全量重建）")
    assert small == {"fts": 1, "rows": 1}, f"追加 1 条应恰好写 1 行，实际 {small}"