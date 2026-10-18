"""单实例引擎进程锁（M-4）：防 GUI+headless 或双击启动同时跑两套引擎。

两套引擎并存 = 双份捕获/蒸馏 + 8101 绑定冲突静默死线程。锁文件
<data_dir>/engine.lock 用 OS 级字节锁（不自造 PID 文件——PID 复用会把
已死实例误判为存活）：
- Windows: msvcrt.locking(LK_NBLCK)
- POSIX:   fcntl.flock(LOCK_EX | LOCK_NB)
两种锁都随进程死亡由内核释放 → 崩溃不留陈旧锁。
拿不到锁 = 有活进程持有同一数据目录 → 调用方决定退出路径（GUI/headless）。
"""

from __future__ import annotations

import os
from pathlib import Path

LOCK_FILE_NAME = "engine.lock"


class EngineLock:
    def __init__(self, data_dir: str | Path) -> None:
        self._path = Path(data_dir) / LOCK_FILE_NAME
        self._fh = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def held(self) -> bool:
        return self._fh is not None

    def acquire(self) -> bool:
        """非阻塞获取；失败返回 False（不抛——调用方按"已有实例"处理）。"""
        if self._fh is not None:
            return True
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self._path, "a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                if fh.tell() == 0:  # 空文件没有字节可锁，先垫一个
                    fh.write("1")
                    fh.flush()
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fh = fh
            return True
        except OSError:
            try:
                fh.close()
            except OSError:
                pass  # 锁文件本身读写异常时，close 也可能复抛；acquire 承诺只返回 bool
            return False

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None
