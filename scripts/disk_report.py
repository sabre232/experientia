"""磁盘体检：产品数据 / 项目内产物 / 系统临时目录的体积构成（只统计，不删除）。

原名 `tmp_report.py` 名字像一次性产物，实为常用运维
脚本，故改名 `disk_report.py`。

    .venv/Scripts/python.exe scripts/disk_report.py

四块内容：
1. 产品数据（~/.experientia）：分层体积 + 会话归档年龄分布。保留期由档 C
   每日执行（sessions/ 归档 mtime >90 天删除，产品文档），这里只报
   数字——超过 90 天还留着说明档 C 没跑到，不是脚本该管的事；
2. 归档容量预览：档 C 的三条容量闸（总量 2GB / 条数 4000 / 单文件 100MB）
   现在跑会裁掉什么（dry-run，不落盘）；
3. 项目内产物：.pytest_tmp（测试临时根）/ build / dist / spark-output；
4. 系统临时目录：%TEMP%/pytest-of-<user>（pytest 默认临时根，回收被拦时
   会一路堆积）。

结尾给出三处的删除命令，脚本自己一行都不删。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.distill import maintenance  # noqa: E402
from app.store.store import Store  # noqa: E402

MB = 1048576
RETENTION_DAYS = 90  # 产品文档：sessions/ 归档保留期，档 C 每日执行


def _scan(path: Path) -> tuple[int, int, int]:
    """返回 (文件数, 目录数, 字节数)；路径不存在返回全 0。"""
    files = dirs = size = 0
    if not path.exists():
        return 0, 0, 0
    for dp, dn, fn in os.walk(path):
        dirs += len(dn)
        files += len(fn)
        for f in fn:
            try:
                size += (Path(dp) / f).stat().st_size
            except OSError:
                pass
    return files, dirs, size


def _row(label: str, files: int, dirs: int, size: int) -> str:
    return f"  {label:<26} 文件 {files:>6}  目录 {dirs:>6}  {size / MB:8.1f} MB"


def _age_buckets(base: Path) -> tuple[dict[str, list[int]], int]:
    """按 mtime 年龄分桶统计（桶值 = [文件数, 字节数]），返回 (桶, 总字节)。"""
    now = time.time()
    buckets: dict[str, list[int]] = {}
    total = 0
    for dp, _dn, fn in os.walk(base):
        for f in fn:
            p = Path(dp) / f
            try:
                st = p.stat()
            except OSError:
                continue
            days = (now - st.st_mtime) / 86400
            if days > RETENTION_DAYS:
                key = f">{RETENTION_DAYS} 天（超保留期）"
            elif days > 30:
                key = "31-90 天"
            else:
                key = "<=30 天"
            slot = buckets.setdefault(key, [0, 0])
            slot[0] += 1
            slot[1] += st.st_size
            total += st.st_size
    return buckets, total


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    store = Store()
    data = store.data_dir
    print(f"产品数据目录：{data}")
    entries = sorted(data.iterdir()) if data.exists() else []
    total_files = total_dirs = 0
    total_size = 0
    for e in entries:
        if e.is_dir():
            files, dirs, size = _scan(e)
        else:
            try:
                files, dirs, size = 1, 0, e.stat().st_size
            except OSError:
                continue
        total_files += files
        total_dirs += dirs
        total_size += size
        print(_row(e.name, files, dirs, size))
    print(_row("合计", total_files, total_dirs, total_size))

    archives = data / "sessions"
    buckets, arc_total = _age_buckets(archives)
    print(f"\n会话归档年龄分布（{archives}，共 {arc_total / MB:.1f} MB）：")
    for key in ("<=30 天", "31-90 天", f">{RETENTION_DAYS} 天（超保留期）"):
        if key in buckets:
            files, size = buckets[key]
            print(f"  {key:<22} 文件 {files:>6}  {size / MB:8.1f} MB")

    plan = maintenance.plan_session_archive_cleanup(store)
    print("\n归档容量闸预览（dry-run，不删任何文件）：")
    print(f"  当前归档 {plan['files']} 个 / {plan['bytes'] / MB:.1f} MB"
          f"（孤儿 {plan['orphans']} 个）")
    if not plan["triggers"]:
        print("  未触发任何容量闸，本轮不会裁剪")
    else:
        print(f"  触发：{' + '.join(plan['triggers'])} → 拟裁 "
              f"{plan['evicted_files']} 个 / {plan['evicted_bytes'] / MB:.1f} MB，"
              f"剩余 {plan['kept_files']} 个 / {plan['kept_bytes'] / MB:.1f} MB")
        for line in plan["evicted"][:5]:
            print(f"    - {line}")
        if plan["evicted_files"] > 5:
            print(f"    - …… 另有 {plan['evicted_files'] - 5} 个")

    print("\n项目内产物：")
    for rel in (".pytest_tmp", "build", "dist", "spark-output"):
        files, dirs, size = _scan(ROOT / rel)
        print(_row(rel, files, dirs, size))

    temp_root = Path(os.path.expandvars("%TEMP%"))
    print(f"\n系统临时目录（{temp_root}）：")
    found = sorted(temp_root.glob("pytest-of-*"))
    if not found:
        print("  （无 pytest 临时根残留）")
    for p in found:
        files, dirs, size = _scan(p)
        print(_row(p.name, files, dirs, size))

    print("\n清理命令（脚本不删，需自己执行）：")
    print('  Remove-Item -Recurse -Force "%TEMP%\\pytest-of-$env:USERNAME"')
    print(f'  Remove-Item -Recurse -Force "{ROOT / ".pytest_tmp"}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
