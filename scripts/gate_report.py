"""记忆纪律闸门回测报告（只读，P0-1~P1-2 落地后的验收工具）。

为什么需要它：注意力闸（D1）和证据闸（D3）是新接进主链路的，方案里写了
"先小步验证，跑一轮真实捕获看入库量变化"——这个脚本就是干这个的。它回答
四个问题：

1. **拦了多少**：现有库里有多少条按今天的口径会被拒 / 转避坑 / 转草稿；
2. **误拦多少**：被判 reject/advice 的样本逐条列出来，供人工核对（判据是
   关键词表，误伤只能靠人眼发现）；
3. **证据覆盖率**：多少经验带原话、多少能定位回原会话；
4. **取用守不守预算**：逐类建胶囊，统计 token/加权成本与截断率；
5. **召回要多久**：调 MCP 检索的真实入口，量 p50/p95（那条 100ms 的尺子）。

**只读**：全程不写数据目录（连 SQLite 都只是读）。默认读真实数据目录，
可用 `EXPERIENTIA_HOME` 或 `--data-dir` 指到别处。

用法：
    uv run python scripts/gate_report.py
    uv run python scripts/gate_report.py --json report.json --sample 10
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import memory_discipline as md  # noqa: E402
from app.distill import capsule, evidence, layers  # noqa: E402
from app.store.store import Store  # noqa: E402

# 单次最多建多少类别的胶囊（防大库跑太久）
MAX_CAPSULE_SAMPLES = 20
# 每类最多列出多少个样本供人工核对
DEFAULT_SAMPLE = 5
# 召回延迟默认测多少次查询
DEFAULT_LATENCY_QUERIES = 30
# 的延迟目标（千级经验下的 p95）
LATENCY_TARGET_MS = 100.0


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 报告工具：任何一项统计失败都不该整份报告挂掉
        return default


def gate_backtest(store, sample: int = DEFAULT_SAMPLE) -> dict:
    """注意力闸回测（D1）：把库里每条经验重新过一遍闸，看按今天的口径会怎样。

    注意这是**回测**不是改数：库里已存在的记录不会被移动，只是告诉你
    "如果今天再来一遍会怎样"。
    """
    routes = Counter()
    samples = {"reject": [], "advice": []}
    total = 0
    for rec in store.iter_experiences(include_distilled=True,
                                      show_superseded=True):
        total += 1
        out = md.admit(rec)
        routes[out["route"]] += 1
        if out["route"] in samples and len(samples[out["route"]]) < sample * 3:
            samples[out["route"]].append({
                "action": str(rec.get("action") or "")[:60],
                "state": str(rec.get("state") or "")[:60],
                "value_class": out["value_class"],
            })
    return {"total": total, "routes": dict(routes), "samples": samples}


def evidence_coverage(store) -> dict:
    """证据闸（D3）：非用户确认的经验里，多少带了能定位的原话。"""
    stats = Counter()
    for rec in store.iter_experiences(include_distilled=True,
                                      show_superseded=True):
        if str(rec.get("g_source") or "") == "user":
            stats["user_confirmed_exempt"] += 1
            continue
        ev = evidence.normalize(rec.get("evidence"))
        if not ev or not str(ev.get("quote") or "").strip():
            stats["no_quote"] += 1
            continue
        stats["has_quote"] += 1
        if isinstance(rec.get("evidence"), dict):
            stats["structured"] += 1
        else:
            stats["legacy_string"] += 1
        if ev.get("locatable") is True:
            stats["locatable"] += 1
        elif ev.get("locatable") is None:
            stats["locatable_unknown"] += 1
        else:
            stats["not_locatable"] += 1
    return dict(stats)


def chain_stats(store) -> dict:
    """演化链（D4/D5）：换代过多少、链有多深。"""
    revisions = Counter()
    superseded = 0
    max_depth = 1
    for rec in store.iter_experiences(include_distilled=True,
                                      show_superseded=True):
        revisions[int(rec.get("revision") or 1)] += 1
        if str(rec.get("superseded_by") or ""):
            superseded += 1
        root = str(rec.get("root_id") or rec.get("id") or "")
        if root:
            try:
                depth = store._expdb.revision_count(root) + 1 \
                    if getattr(store, "_expdb", None) is not None else 1
            except Exception:  # noqa: BLE001
                depth = 1
            max_depth = max(max_depth, depth)
    return {"revisions": {str(k): v for k, v in sorted(revisions.items())},
            "superseded": superseded, "max_chain_depth": max_depth}


def forget_stats(store) -> dict:
    """遗忘（D6）：软忘多少、硬删留了多少归档。"""
    tombstoned = 0
    for rec in store.iter_experiences(include_distilled=True,
                                      show_superseded=True,
                                      show_tombstoned=True):
        if int(rec.get("tombstone") or 0):
            tombstoned += 1
    archived = 0
    dep_dir = store.data_dir / "deprecated"
    if dep_dir.is_dir():
        for path in dep_dir.rglob("experiences.jsonl"):
            try:
                with path.open(encoding="utf-8") as fh:
                    archived += sum(1 for line in fh if line.strip())
            except OSError:
                continue
    return {"tombstoned": tombstoned, "archived_in_deprecated": archived}


def retrieval_stats(store, budget: int) -> dict:
    """取用（D7）：逐类建胶囊，看预算遵守率与截断率。"""
    cats = []
    for s in _safe(lambda: store.list_skills(), []) or []:
        cats.append((s.get("trunk"), s.get("category")))
    cats = [c for c in cats if c[0] and c[1]][:MAX_CAPSULE_SAMPLES]
    over = 0
    truncated = 0
    worst_cost = 0
    for trunk, category in cats:
        cap = _safe(lambda: capsule.build_capsule(store, trunk, category,
                                                  budget_tokens=budget), None)
        if not cap:
            continue
        if cap["cost"] > budget:
            over += 1
        if cap["truncated"]:
            truncated += 1
        worst_cost = max(worst_cost, cap["cost"])
    return {"sampled_categories": len(cats), "over_budget": over,
            "truncated": truncated, "worst_cost": worst_cost,
            "budget": budget}


def retrieval_latency(store, queries: int = DEFAULT_LATENCY_QUERIES) -> dict:
    """召回延迟（D7 /）：量 MCP 检索一次要多久。

    走协议层 `tools/call`（含 JSON 编解码），不是直接调内部函数——要量的是
    客户端实际等多久。查询集取库里真实 `task` 原文，不是造的短查询：
    "用户一句话找经验"才是真实负载。冷启一次不计入（首次要开 SQLite）。
    """
    from app import mcp_server as mcp

    recs = list(store.iter_experiences(include_distilled=True,
                                      show_superseded=True))
    qs: list[str] = []
    for rec in recs:
        text = str(rec.get("task") or "").strip()
        if len(text) >= 6:
            qs.append(text[:80])
        if len(qs) >= queries:
            break
    if not qs:
        return {}

    server = mcp.McpServer(store)

    def request(query: str) -> dict:
        return {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "experientia_search",
                           "arguments": {"query": query, "limit": 10}}}

    server.handle(request(qs[0]))          # 冷启不计
    lat: list[float] = []
    for q in qs:
        t0 = perf_counter()
        server.handle(request(q))
        lat.append((perf_counter() - t0) * 1000)
    lat.sort()

    def pct(p: float) -> float:
        return round(lat[min(len(lat) - 1, int(round(p / 100 * (len(lat) - 1))))], 2)

    return {"library": len(recs), "queries": len(lat),
            "p50_ms": pct(50), "p95_ms": pct(95), "max_ms": round(lat[-1], 2),
            "target_ms": LATENCY_TARGET_MS}


def build_report(store, budget: int = 800,
                 latency_queries: int = DEFAULT_LATENCY_QUERIES,
                 sample: int = DEFAULT_SAMPLE) -> dict:
    return {
        "data_dir": str(store.data_dir),
        "layers": _safe(lambda: layers.inventory(store), {}),
        "attention_gate": _safe(lambda: gate_backtest(store, sample), {}),
        "evidence": _safe(lambda: evidence_coverage(store), {}),
        "chain": _safe(lambda: chain_stats(store), {}),
        "forget": _safe(lambda: forget_stats(store), {}),
        "retrieval": _safe(lambda: retrieval_stats(store, budget), {}),
        "latency": (_safe(lambda: retrieval_latency(store, latency_queries), {})
                    if latency_queries > 0 else {}),
    }


def _print_text(rep: dict, sample: int = DEFAULT_SAMPLE) -> None:
    """文本报告。sample 由调用方显式传入（L15：不再用 global 隐式数据流）。"""
    print(f"数据目录：{rep['data_dir']}\n")

    print("— 六层存量 —")
    for k in ("L1", "L2", "L3", "L4", "L5", "L6"):
        d = (rep.get("layers") or {}).get(k) or {}
        print(f"  {k} {d.get('name', '?'):<6} {d.get('count', 0):>6}")

    g = rep.get("attention_gate") or {}
    print(f"\n— 注意力闸回测（共 {g.get('total', 0)} 条）—")
    for route, n in (g.get("routes") or {}).items():
        print(f"  {route:<12} {n}")
    for route in ("reject", "advice"):
        rows = (g.get("samples") or {}).get(route) or []
        if rows:
            print(f"  【{route}】样本（供人工核对误判）：")
            for r in rows[:sample]:
                print(f"    · [{r['value_class']}] {r['action'] or r['state']}")

    e = rep.get("evidence") or {}
    print("\n— 证据覆盖 —")
    for k, v in sorted(e.items()):
        print(f"  {k:<22} {v}")

    c = rep.get("chain") or {}
    print("\n— 演化链 —")
    print(f"  版本分布 {c.get('revisions')}")
    print(f"  已被换代 {c.get('superseded')}   最深链 {c.get('max_chain_depth')}")

    f = rep.get("forget") or {}
    print("\n— 遗忘 —")
    print(f"  软忘(tombstone) {f.get('tombstoned')}   "
          f"deprecated 归档 {f.get('archived_in_deprecated')}")

    r = rep.get("retrieval") or {}
    print("\n— 取用预算 —")
    print(f"  抽样 {r.get('sampled_categories')} 类：超预算 {r.get('over_budget')}，"
          f"发生截断 {r.get('truncated')}，最大成本 {r.get('worst_cost')}"
          f"（预算 {r.get('budget')}）")

    lat = rep.get("latency") or {}
    print("\n— 召回延迟（MCP search，走协议层）—")
    if lat:
        verdict = "达标" if lat["p95_ms"] < lat["target_ms"] else "越线"
        print(f"  库 {lat['library']} 条 / 查询 {lat['queries']} 次："
              f"p50 {lat['p50_ms']}ms  p95 {lat['p95_ms']}ms  "
              f"max {lat['max_ms']}ms（目标 <{lat['target_ms']:.0f}ms，{verdict}）")
        if lat["p95_ms"] >= lat["target_ms"]:
            print("  越线时先看扫描条数：代价是 O(扫描条数)，与库大小成正比")
    else:
        print("  库内没有可用问句（经验为空或全无 task），跳过")

    print("\n— 看着不对时该改哪 —")
    print("  · reject / advice 太多（误拦）：改 app/distill/value_gate.py 的")
    print("    _ENV_PATTERNS / _FRICTION_PATTERNS（闸门本身不用动）")
    print("  · no_quote 太多：复盘提示词已要求模型逐字摘原话——先看模型有没有照做，")
    print("    再看 app/distill/evidence.py 的 QUOTE_MAX / _MIN_LOCATE_LEN 是否卡太死")
    print("  · locatable_unknown 多：那是老格式字符串证据（没验过），属正常；")
    print("    跑一次 store.export_experience_snapshot() 也不会补验——它是历史数据")
    print("  · 超预算 / 截断多：调 --budget，或改 app/distill/layers.py 的层权重")
    print("  · 召回 p95 越线：先看扫描条数（SEARCH_SCAN_LIMIT 与库规模），再看缓存")
    print("    是否命中（app/proxy/detect.py 的 _cached_token_set、"
          "app/distill/entities.py 的 cached_keys_of_text）")


def main() -> int:
    ap = argparse.ArgumentParser(description="记忆纪律闸门回测报告（只读）")
    ap.add_argument("--data-dir", default=None,
                    help="数据目录；缺省按 EXPERIENTIA_HOME / ~/.experientia 解析")
    ap.add_argument("--json", default=None, help="同时把报告写成 JSON 文件")
    ap.add_argument("--budget", type=int, default=800,
                    help="胶囊预算（默认 800 token）")
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                    help="每类列出多少样本供人工核对")
    ap.add_argument("--latency", type=int, default=DEFAULT_LATENCY_QUERIES,
                    help="召回延迟测多少次查询（0 = 不测）")
    args = ap.parse_args()
    sample = max(1, args.sample)

    store = Store(args.data_dir) if args.data_dir else Store()
    rep = build_report(store, args.budget, args.latency, sample)
    _print_text(rep, sample)

    if args.json:
        Path(args.json).write_text(
            json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 已写入 {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
