"""经验链路修复 · 存量迁移 CLI（app/store/migrations.py 的运维薄壳）。

同样的逻辑引擎启动时会自动跑一次（版本门控，-P1-8）；本脚本用于
发版前排演（dry-run）与手动重放（幂等，已迁移则只报现状 + 可重跑回采）。

用法：
  uv run python scripts/migrate_rule_pipeline.py             # dry-run 统计
  uv run python scripts/migrate_rule_pipeline.py --apply     # 真跑（含回采）
  uv run python scripts/migrate_rule_pipeline.py --apply --skip-backfill
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.store import migrations as mig  # noqa: E402
from app.store.store import Store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="真跑（默认 dry-run，只打印统计）")
    ap.add_argument("--limit", type=int, default=0, help="回采会话数上限（0=全量）")
    ap.add_argument("--skip-backfill", action="store_true", help="只轻相，不回采")
    args = ap.parse_args()

    store = Store()
    exp_path = store.data_dir / "experience.jsonl"
    records = ([json.loads(l) for l in
                exp_path.read_text(encoding="utf-8").splitlines() if l.strip()]
               if exp_path.exists() else [])
    cutoff = datetime.now(timezone.utc) - timedelta(days=mig.EVIDENCE_WINDOW_DAYS)
    hist_n = sum(1 for s in store.list_sessions()
                 if int(s.get("correction_hits") or 0) > 0
                 and not mig._iso_older(str(s.get("started_at") or ""), cutoff))
    ev_n = sum(1 for s in store.list_sessions() if s.get("events"))
    print(f"现状：经验库 {len(records)} 条 · 会话 {len(store.list_sessions())} "
          f"（含事件行 {ev_n}）· 已挂起 {len(store.load_pending_reviews())} · "
          f"近{mig.EVIDENCE_WINDOW_DAYS}天纠正命中会话 {hist_n} · "
          f"data_version={store.load_meta().get('data_version', 0)}")
    if not args.apply:
        print("dry-run 结束（加 --apply 真跑）")
        return 0

    summary = mig.run_startup_migrations(store)
    print(f"轻相：{summary}")
    if args.skip_backfill:
        store.save_meta({"backfill_pending": False})
        print("已按 --skip-backfill 跳过回采（旗标清除）")
    else:
        # 幂等：轻相已跑过也可单独重放回采（seen_in 并集不虚构复现）
        sess_n, cards_n = mig.backfill_from_archive(store, limit=args.limit)
        store.save_meta({"backfill_pending": False})
        print(f"回采：会话 {sess_n} 个 · 坑卡 {cards_n} 条")
    from app.distill import mining
    stats = mining.rule_stats(store)
    print(f"完成。rule 坑卡：{stats['by_kind']}（可注入 {stats['injectable']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
