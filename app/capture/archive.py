"""捕获即归档——解析成功的会话拷贝进 ~/.experientia/sessions/<agent>/。

防 agent 自清理（如 Claude Code 30 天 purge）/卸载丢数据，
同时强化"可带走"护城河。归档副本 = 最新完整状态（size 变化才重写，由扫描层判定）。

归档单位 = 文件而不是会话（M-3）：SQLite 类一个 ref 是一整个库（Cursor
state.vscdb 可能几百 MB），按会话归档 = 库内 N 个会话拷 N 份整库。
1:1 文件（session_id 即文件名）保持 <session_id>.jsonl 旧布局；
容器库统一拷一份 <原文件名>。

单文件闸（SESSION_ARCHIVE_MAX_FILE_BYTES）：超限不拷，返回 None。容器库整库
拷贝是归档体积的大头，而它的价值只是"防源端自清理"——落库记录已带截断转录，
不值得为它占用几百 MB。**只拦新拷贝**，已有超限副本不主动删（删除统一交给档 C
的容量裁剪，按最旧优先、且只在真超预算时执行）。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..store.store import SESSION_ARCHIVE_MAX_FILE_BYTES
from .models import Session, SessionRef

logger = logging.getLogger("experientia.capture.archive")

# 压缩归档的后缀（与 distill.maintenance 的压缩实现同约定：<name>.jsonl.zst）。
# 这里独立声明而不 import maintenance：capture 层不该依赖 distill 层。
_ARCHIVE_COMPRESS_SUFFIX = ".zst"


def _compressed_sibling(dest: Path) -> Path:
    """压缩归档路径（<dest>.zst）。"""
    return dest.with_name(dest.name + _ARCHIVE_COMPRESS_SUFFIX)


def _copy_if_changed(src: Path, dest: Path, size: int) -> Path | None:
    """size 与目标不一致才重拷；超单文件闸返回 None（不拷贝、不删已有副本）。

    **压缩档要一并认**（实测的坑）：档 C 把 <dest> 压成 <dest>.zst 后
    原件就没了，`dest.exists()` 变 False → 下一次归档原样复活一份未压缩副本，
    与**已过期**的 .zst 并存（源没变也会复活，判据只看存在性）。扫描层按
    「源 size+mtime 未变」跳过能掩盖它，但源一旦被碰（会话续写、agent 重写）
    就中招：磁盘不减反增，且 .zst 里躺着旧内容。
    判据用 mtime：压缩实现保留了原档 mtime（见 maintenance._compress_archive），
    故「源 mtime 不新于压缩档」= 源没变过。
    """
    if size > SESSION_ARCHIVE_MAX_FILE_BYTES:
        logger.info(
            "归档跳过（单文件 %d 字节 > 上限 %d）: %s",
            size, SESSION_ARCHIVE_MAX_FILE_BYTES, src.name)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    zst = _compressed_sibling(dest)
    if not dest.exists():
        if zst.exists():
            try:
                stale = src.stat().st_mtime > zst.stat().st_mtime + 1
            except OSError:
                stale = False
            if not stale:
                return zst          # 归档就是它，且仍是最新 → 不复活未压缩副本
            # 源更新过 → 压缩档过期。不做"解压 + 追加"：整档重写比重拷更贵，
            # 且归档只是"防源端自清理"的可带走副本，不是唯一事实源（库里有记录）。
            try:
                zst.unlink()
            except OSError as exc:
                logger.warning("过期压缩档删除失败（将重写未压缩副本）: %s: %s",
                               zst.name, exc)
        shutil.copy2(src, dest)
        return dest
    if dest.stat().st_size == size:
        return dest
    if zst.exists():                # 源变了 → 顺带清掉过期压缩档，防两份并存
        try:
            zst.unlink()
        except OSError as exc:
            logger.warning("重写归档前清理压缩档失败: %s: %s", zst.name, exc)
    shutil.copy2(src, dest)
    return dest


def archive_session(ref: SessionRef, session: Session, sessions_dir: Path) -> Path | None:
    """1:1 文件通道（hook transcript 等）：按会话归档，布局 <session_id>.jsonl。

    sessions_dir = 用户数据目录的 sessions 子目录（Store.dir("sessions")）。
    超单文件闸返回 None。
    """
    dest = sessions_dir / session.agent / (session.session_id + ".jsonl")
    return _copy_if_changed(ref.path, dest, ref.size)


def archive_ref(ref: SessionRef, sessions: list[Session], sessions_dir: Path) -> Path | None:
    """文件通道（run_scan 每 ref 调一次）：整个 ref 至多产生一份归档副本。

    - 1:1（单会话且 session_id == ref.session_id）：<session_id>.jsonl，与旧布局一致；
    - 容器库（多会话 / id 与文件名不符）：<原文件名>（如 state.vscdb）一份。
    sessions_dir = 用户数据目录的 sessions 子目录（Store.dir("sessions")）。
    超单文件闸返回 None。
    """
    dest_dir = sessions_dir / ref.agent
    if len(sessions) == 1 and sessions[0].session_id == ref.session_id:
        dest = dest_dir / (ref.session_id + ".jsonl")
    else:
        dest = dest_dir / ref.path.name
    return _copy_if_changed(ref.path, dest, ref.size)
