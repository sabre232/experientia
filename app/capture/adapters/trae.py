"""Trae（字节跳动 AI IDE）会话解析器（T2，社区实证口径，**实验性**）。

实证（2026-08 修订，agentsview #1210/#1217 + AgentLedger #20 双项目实测）：
- 现行 `%APPDATA%\\<Trae 目录>\\ModularData\\ai-agent\\database.db` 为**加密存储**
  （SQLCipher，无 SQLite 文件头）→ 无密钥不可解析，本 adapter 不假装有此能力
  （探测到但无 SQLite magic 的文件静默跳过，文档已注明）。
- 旧版布局（可解析）：`%APPDATA%\\<Trae 目录>\\User\\workspaceStorage\\<hash>\\state.vscdb`
  （明文 SQLite），ItemTable 键 `memento/icube-ai-agent-storage` 的值为**明文 JSON**，
  无压缩（agentsview trae_provider.go 实证）。
- 文档旧版"LZString 解压"说法经检索查无实证，已移除。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

from ..models import AdapterBase, Session, SessionRef
from .base_sqlite import (build_session, connect_ro, extract_messages,
                          is_encrypted, json_cell, table_exists)

logger = logging.getLogger("experientia.capture.trae")

MEMENTO_KEY_PREFIX = "memento/icube-ai-agent-storage"

# 解密尝试节流（进程内）：db 路径 → 上次尝试的 epoch 秒
_DECRYPT_THROTTLE_SECONDS = 3600
_DECRYPT_ATTEMPTS: dict[str, float] = {}


def _trae_dirs() -> list[Path]:
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        base = appdata
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        base = Path(xdg)
    out = []
    if base.is_dir():
        out.extend(sorted(d for d in base.glob("Trae*") if d.is_dir()))
        # Add Trae CN explicitly
        trae_cn = base / "Trae CN"
        if trae_cn.is_dir() and trae_cn not in out:
            out.append(trae_cn)
    return out


def _modular_data_dirs() -> list[Path]:
    """Trae 新版 SQLCipher 加密库路径：ModularData/ai-agent/database.db"""
    dirs = []
    for trae_dir in _trae_dirs():
        md = trae_dir / "ModularData" / "ai-agent"
        if md.is_dir():
            dirs.append(md)
    return dirs


def _is_sqlite_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(16).startswith(b"SQLite format 3")
    except OSError:
        return False


def _has_ai_sessions(db: Path) -> bool:
    """workspaceStorage 库里是否存在可解析出消息的 AI 会话 blob。

    判据 = parse 实际消费的 extract_messages 非空（discover 与 parse 同口径，
    构造上不会报出"解析必空"的 ref）。新版 Trae 的聊天正文在
    ModularData/ai-agent/database.db（SQLCipher 加密），workspaceStorage 的
    memento 值退化为会话索引（list[].messages 全空）或只剩 UI 状态键——
    这类库若仍作为 ref 上报，每轮解析失败会无限推高 agent 失败计数
    （断链修复方案：止住失败循环）。库小（KB 级），每轮查询成本可
    忽略；旧版 Trae 写入带正文的 memento 键后下轮 discover 自然纳入。
    """
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT value FROM ItemTable WHERE key LIKE ?",
                (MEMENTO_KEY_PREFIX + "%",)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    for (value,) in rows:
        blob = json_cell(value)
        if blob is not None and extract_messages(blob):
            return True
    return False


class TraeAdapter(AdapterBase):
    name = "trae"
    search_names = ["trae", "Trae", "Trae CN"]

    def discover(self) -> list[SessionRef]:
        refs: list[SessionRef] = []
        seen: set[str] = set()

        # 1. 旧版：workspaceStorage 下各工作区的 state.vscdb（明文，可解析）
        for base in _trae_dirs():
            for db in sorted((base / "User" / "workspaceStorage").glob("*/state.vscdb")) \
                    if (base / "User" / "workspaceStorage").is_dir() else []:
                if not _is_sqlite_file(db):
                    continue
                if not _has_ai_sessions(db):
                    continue  # 无会话键（新版布局只存 UI 状态）→ 不作 ref
                key = str(db)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    st = db.stat()
                except OSError:
                    continue
                refs.append(SessionRef(
                    agent=self.name, session_id=db.parent.name, path=db,
                    size=st.st_size, mtime=st.st_mtime,
                ))

        # 2. 新版：ModularData/ai-agent/database.db（SQLCipher 加密）
        for base in _modular_data_dirs():
            for db in sorted(base.glob("*.db")):
                key = str(db)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    st = db.stat()
                except OSError:
                    continue
                enc = is_encrypted(db)
                refs.append(SessionRef(
                    agent=self.name, session_id=db.stem, path=db,
                    size=st.st_size, mtime=st.st_mtime,
                    encrypted=enc, parse_error="encrypted" if enc else None,
                ))

        return refs

    def parse(self, ref) -> Session | None:
        if ref.encrypted:
            # 解密尝试节流：密钥按安装稳定，不随库写入变化——运行中的
            # Trae 每轮对话都会改 db（签名变化→重新解析），不节流则每轮
            # 都全量扫进程内存（GB 级，分钟级），拖死 60s 扫描循环
            now = time.time()
            last = _DECRYPT_ATTEMPTS.get(str(ref.path), 0.0)
            if now - last < _DECRYPT_THROTTLE_SECONDS:
                return None
            _DECRYPT_ATTEMPTS[str(ref.path)] = now
            # 尝试解密 Trae CN 加密数据库
            decrypted = self._try_decrypt(ref.path)
            if decrypted is None:
                return None  # 解密失败，由 registry 层给出提示
            # 用解密后的临时文件解析
            try:
                conn = connect_ro(decrypted)
            except sqlite3.Error:
                return None
        else:
            try:
                conn = connect_ro(ref.path)
            except sqlite3.Error:
                return None
        try:
            if not table_exists(conn, "ItemTable"):
                return None
            for key, value in conn.execute("SELECT key, value FROM ItemTable"):
                if not isinstance(key, str) or not key.startswith(MEMENTO_KEY_PREFIX):
                    continue
                blob = json_cell(value)
                if blob is None:
                    continue
                sid = ref.session_id
                if isinstance(blob, dict):
                    sid = str(blob.get("session_id") or blob.get("id") or ref.session_id)
                s = build_session(self.name, sid, blob)
                if s:
                    return s
            return None
        except sqlite3.Error:
            return None
        finally:
            conn.close()
            # 清理解密后的临时文件（明文临时物残留是隐患，失败不可静默）
            if ref.encrypted and decrypted is not None:
                try:
                    decrypted.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("解密临时文件清理失败（明文残留，建议手动删除）: %s", exc)

    @staticmethod
    def _try_decrypt(db_path: Path) -> Path | None:
        """尝试解密 Trae CN 加密数据库，返回解密后的临时文件路径。

        现在使用统一解密框架 (universal_decrypt) 作为主要路径，
        保留原有社区工具预解密文件查找作为兜底。
        """
        # 主路径：统一解密框架（注册了 ProcessMemoryStrategy + CommunityToolStrategy）
        framework_ran = False
        try:
            from .universal_decrypt import try_any_decrypt as _try_any

            result = _try_any(db_path, "trae")
            framework_ran = True
            if result is not None:
                return result
        except ImportError:
            logger.debug("统一解密框架不可用，回退旧方案")
        except Exception as exc:
            framework_ran = True
            logger.debug("统一解密框架异常: %s（回退到旧方案）", exc)

        # 兜底：直接查找社区工具预生成的解密文件
        try:
            from .trae_decrypt import find_key_from_process, decrypt_to_file

            # 策略 1：进程内存扫描——仅当框架从未跑过时。框架的
            # ProcessMemoryStrategy 调用的就是同一个 find_key_from_process，
            # 重复扫一遍 GB 级进程内存是纯浪费（实测一次 ~分钟级）
            if not framework_ran:
                key = find_key_from_process(db_path)
                if key is not None:
                    # 遗留：旧兜底分支此前把明文临时库写在
                    # 第三方工具源目录（<原库>.decrypted.tmp.db），与
                    # base_sqlite.py 的受控目录机制（decrypt_tmp_dir() +
                    # _decrypted_tmp_name()）口径不一致，明文残留隐患同源。
                    # 仅改本「import 失败兜底」路径的输出位置，其余策略不动。
                    from .base_sqlite import _decrypted_tmp_name, decrypt_tmp_dir

                    out = decrypt_tmp_dir() / _decrypted_tmp_name(db_path, ".db")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    result = decrypt_to_file(db_path, key, out)
                    if result is not None:
                        return result
        except ImportError:
            logger.debug("trae_decrypt 模块不可用，跳过进程内存扫描")
        except Exception as exc:
            logger.debug("进程内存扫描异常: %s", exc)

        # 策略 2：查找社区工具预生成的解密文件
        for cand in (
            db_path.with_suffix(".decrypted.db"),
            db_path.with_suffix(".plain.db"),
            db_path.parent / "database_decrypted.db",
        ):
            if cand.is_file() and cand.stat().st_size > 0:
                return cand

        logger.info("Trae 解密失败：未找到密钥（Trae 需运行中 + 管理员权限）")
        return None

    def parse_sessions(self, ref) -> list:
        s = self.parse(ref)
        return [s] if s is not None else []
