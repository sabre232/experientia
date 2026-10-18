"""P1b 历史会话重放（断链修复方案 ，跑完即弃，不进产品代码）。

workbuddy 断链期间（P0 修复前）落库的是空壳记录（user/assistant 文本全丢，
req_count=0），且 ref 增量签名首轮解析后已更新——常规扫描会跳过这些文件，
无法自愈。本脚本强制重解析 capture_state 里登记的全部 workbuddy/codex ref：

  修复后适配器解析 → session_to_review_dict → record_session
  （append-only，读时按 (agent, session_id) 取最新，天然覆盖旧空壳行）
  → 对 review dict 跑 review_sessions（当前无模型 → L2 纠正 fallback，
  只沉淀"被用户纠正"类候选，即失败模式的来源）。

安全：
- 默认 dry-run：只解析并打印"将落库 N 条 session / 预计新增 M 条经验"，
  不碰任何数据文件；
- --apply 真跑前：experience.jsonl 若非空先留 .bak（sessions.jsonl 的
  .bak 由 P1a 清理脚本留下，可整体回滚）；
- capture_state 不动（签名本就是当前值，重放是"忽略"而非"失效"它）。

用法：
  uv run python scripts/replay_workbuddy_sessions.py            # dry-run
  uv run python scripts/replay_workbuddy_sessions.py --apply    # 真跑
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.capture.registry import REGISTRY, detect  # noqa: E402
from app.capture.scan import review_sessions, session_to_review_dict  # noqa: E402
from app.distill.review import has_distillable_signals  # noqa: E402
from app.store.store import Store  # noqa: E402

# 方案范围：workbuddy 全部 ref + codex 顺带核对
REPLAY_AGENTS = ("workbuddy", "codex")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="真跑（默认 dry-run 只打印统计）")
    args = ap.parse_args()

    store = Store()
    state = store.load_capture_state()
    detected = detect(force=True)
    path_to_agent: dict[str, str] = {}
    for agent, refs in detected.items():
        for ref in refs:
            path_to_agent[str(ref.path)] = agent

    in_scope = 0
    missing = 0
    parse_fail: Counter[str] = Counter()
    session_dicts: list[dict] = []
    candidates = 0

    for agent in REPLAY_AGENTS:
        if agent not in detected:
            print(f"[replay] {agent} 未被探测到（目录不存在？），跳过")
            continue
        adapter = REGISTRY[agent]()
        for ref in detected[agent]:
            key = str(ref.path)
            if key not in state:
                missing += 1  # 新文件未登记（常规扫描下轮会处理），不在重放范围
                continue
            in_scope += 1
            try:
                sessions = adapter.parse_sessions(ref)
            except Exception as exc:
                sessions = []
                parse_fail[agent] += 1
                print(f"[replay] {agent} 解析异常 {ref.path}: {exc}")
            if not sessions:
                parse_fail[agent] += 1
                continue
            for session in sessions:
                d = session_to_review_dict(session, store)
                session_dicts.append(d)
                if has_distillable_signals(d) \
                        and int(d.get("correction_hits") or 0) > 0:
                    candidates += 1  # 无模型 fallback 每会话至多 1 条 L2 候选

    print(f"数据目录: {store.data_dir}")
    print(f"重放范围: {in_scope} 个 ref（未登记的新文件 {missing} 个不在范围）")
    print(f"解析: 成功 {len(session_dicts)} 条 session"
          + (f" / 失败 {dict(parse_fail)}" if parse_fail else ""))
    print(f"将落库 {len(session_dicts)} 条 session（覆盖旧空壳行）")
    print(f"预计新增 {candidates} 条经验（L2 纠正候选，req_count≥2 且含否定词）")

    if not args.apply:
        print("dry-run 结束（加 --apply 真跑）")
        return 0

    exp_path = store.data_dir / "experience.jsonl"
    if exp_path.exists() and exp_path.stat().st_size > 0:
        shutil.copy2(exp_path, exp_path.with_suffix(".jsonl.bak"))
        print(f"已备份: {exp_path.with_suffix('.jsonl.bak')}")
    for d in session_dicts:
        store.record_session(d)
    print(f"已落库 {len(session_dicts)} 条 session")
    added = review_sessions(store, session_dicts)
    print(f"复盘完成: 新增 {added} 条候选经验")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
