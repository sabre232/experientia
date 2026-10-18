"""跨平台原子落盘的一处坑：Windows 的 os.replace 会撞瞬时文件锁。

现象：`os.replace(tmp, dest)` 偶发 `PermissionError [WinError 5] 拒绝访问`。
目标是刚写完的临时文件，**没有任何进程持有它**——真正持锁的是杀毒软件、
Windows 搜索索引、备份/同步工具：它们扫描到新文件会在毫秒级窗口内打开它。
实锤路径：changelog 封顶测试连续 1001 次原子替换，同一台机器同一个文件连跑
三次能炸一次，且每次炸的不是同一条用例（随机性来自 AV 扫描时机，不来自代码）。

这类锁是瞬时的 → 重试即可；风险不对等的另一侧是：**重试耗尽必须照原样抛出**，
绝不能吞掉异常假装写成功（写失败强于写坏数据）。

只重试 `PermissionError`：其他 `OSError`（目录不可写、跨设备、路径是目录）
重试没有意义，只会让真失败慢 0.09 秒。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

REPLACE_RETRIES = 4                      # 总尝试次数（首次 + 3 次重试）
REPLACE_BACKOFF_S = (0.005, 0.02, 0.06)  # 各次重试前等待，累计约 0.09s


def replace_atomic(tmp: Path, dest: Path) -> None:
    """带瞬时锁重试的 os.replace。**全项目原子替换的唯一收口点。**

    tmp 必须先写完并 fsync 过（rename 只保证目录项原子替换，不保证数据落盘——
    断电会留下截断文件，而 JSONL 读侧静默跳过坏行 = 无声丢数据）。
    失败时 tmp 的清理由调用方负责（各写路径的失败语义不同：有的要留现场、
    有的要立刻 unlink，统一在这里清理会把差异抹掉）。
    """
    for attempt in range(REPLACE_RETRIES):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if attempt >= REPLACE_RETRIES - 1:
                raise
            time.sleep(REPLACE_BACKOFF_S[min(attempt, len(REPLACE_BACKOFF_S) - 1)])
