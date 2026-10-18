"""P1a 存量清理：重写 sessions.jsonl（断链修复方案 P1a-3，431MB → 预计 <5MB）。

一次性运维脚本（跑完即弃）：
- 按 (agent, session_id) 取最新一条（与 _build_session_index 同口径：
  带 req_count 的代理通道记录优先，不被缺字段记录降级替换）；
- 每条记录走与 record_session 完全同一条处理链（_trim_session_messages：
  hook 形态记录现场派生截断 user/assistant → 截断 20×200 → pop 原始
  messages）——清理后口径与新增记录一致；
- 重写前留 sessions.jsonl.bak；临时文件 + 原子替换。

用法：
  uv run python scripts/clean_sessions.py            # dry-run：只打印统计
  uv run python scripts/clean_sessions.py --apply    # 真跑（留 .bak 可整体回滚）
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.fs_util import replace_atomic  # noqa: E402
from app.store.store import Store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="真跑重写（默认 dry-run，只打印统计）")
    args = ap.parse_args()

    store = Store()
    path = store.data_dir / "sessions.jsonl"
    if not path.exists():
        print("sessions.jsonl 不存在，无需清理")
        return 0

    total_lines = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                total_lines += 1
    before_bytes = path.stat().st_size

    # 与 _build_session_index 同口径的去重（读时去重逻辑的磁盘化）
    idx = store._build_session_index()
    records = list(idx.values())
    kept = [store._trim_session_messages(rec) for rec in records]
    after_bytes = sum(
        len(json.dumps(r, ensure_ascii=False).encode("utf-8")) + 1
        for r in kept)
    no_ts = sum(1 for r in kept if not r.get("started_at"))

    print(f"数据目录: {store.data_dir}")
    print(f"现有行数: {total_lines}  去重后: {len(kept)}  无 started_at: {no_ts}")
    print(f"体积: {before_bytes / 1048576:.1f}MB → 预计 {after_bytes / 1024:.0f}KB")

    if not args.apply:
        print("dry-run 结束（加 --apply 真跑；重写前留 sessions.jsonl.bak）")
        return 0

    bak = path.with_suffix(".jsonl.bak")
    shutil.copy2(path, bak)
    print(f"已备份: {bak}")

    # 临时文件 + 原子替换（同 _write_tmp_rename 口径，但文件大，不走 Store 缓存）
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            for r in kept:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            # fsync 必须在 rename 前：rename 只保证目录项原子替换，不保证数据落盘，
            # 断电会留下截断文件（同为 store._write_tmp_rename 的口径）
            fh.flush()
            os.fsync(fh.fileno())
        replace_atomic(tmp, path)  # Windows 瞬时锁重试，见 app/fs_util.py
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    print(f"完成: {path.stat().st_size / 1048576:.2f}MB（.bak 可整体回滚）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
