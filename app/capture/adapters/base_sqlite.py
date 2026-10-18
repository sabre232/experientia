"""SQLite 系解析器公共工具（T2）。

- 只读连接 ?mode=ro（agent 运行时不锁库，WAL 约定）
- PRAGMA 表/列探测（格式漂移容错：schema 变了 → 探测失败 → 返回空 → 黄标）
- 通用 JSON blob → Message 抽取（Goose/Kilo/OpenCode/Zed/Hermes 的会话列
  都是"整会话序列化 JSON"，内部消息结构各家略有差异，按 role/content/parts 容错）
- is_encrypted：检测 SQLCipher 加密文件
- search_common_locations：自动搜索所有平台路径
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path

from ..models import AdapterBase, Message, Session, SessionRef
from .base_jsonl import _text_of

logger = logging.getLogger("experientia.capture.base_sqlite")

_SQLITE_HEADER = b"SQLite format 3\0"


def is_encrypted(path: Path) -> bool:
    """检测文件是否加密（SQLCipher 或非标准 SQLite 格式）。

    SQLCipher 数据库的第一页是 16 字节随机数据（不是 "SQLite format 3\0"），
    但文件大小至少 4096 字节（一页）。
    """
    if not path.is_file():
        return False
    try:
        with path.open("rb") as fh:
            data = fh.read(16)
    except (OSError, PermissionError):
        return True  # 无权限读 → 视为加密
    if data == _SQLITE_HEADER:
        return False
    # 非 SQLite 头部且文件 >= 4096 字节 → 可能是加密库
    return path.stat().st_size >= 4096

_ROLE_MAP = {"model": "assistant", "assistant": "assistant", "user": "user", "tool": "tool"}


def connect_ro(path: Path) -> sqlite3.Connection:
    # MX（base_sqlite URI 编码）：f"file:{path}?mode=ro" 在路径含
    # `#`/`?` 时会被 URI 语法截断解析失败。as_uri() 产 file:/// URI 并已处理
    # Windows 反斜杠与特殊字符百分号编码（含 # 和 ?）。
    return sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)


def table_columns(conn: sqlite3.Connection, table: str) -> list[str] | None:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return [r[1] for r in rows]
    except sqlite3.Error:
        return None


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def json_cell(value):
    """JSON 列/值 → 对象；已是 dict/list 直接返回；坏 JSON 返回 None。"""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


def extract_messages(blob) -> list[Message]:
    """通用会话 JSON → Message 列表（容错各家差异：messages/conversation 键、
    content 字符串或块、GenAI parts、functionCall/functionResponse）。"""
    if blob is None:
        return []
    msgs = blob
    if isinstance(blob, dict):
        msgs = blob.get("messages") or blob.get("conversation") or blob.get("history") or []
    if not isinstance(msgs, list):
        return []
    out: list[Message] = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = _ROLE_MAP.get(m.get("role") or "")
        if role is None:
            continue
        ts = m.get("timestamp") or m.get("ts") or m.get("created_at") or m.get("time_created")
        parts = m.get("parts")
        if isinstance(parts, list):
            text_parts: list[str] = []
            for p in parts:
                if not isinstance(p, dict):
                    continue
                if p.get("text"):
                    text_parts.append(p["text"])
                elif (tc := p.get("toolCall") or p.get("tool_call")) and isinstance(tc, dict):
                    out.append(
                        Message(
                            role="assistant",
                            tool_use={
                                "name": tc.get("name") or tc.get("function"),
                                "arguments": tc.get("arguments") or tc.get("args")
                                or tc.get("input"),
                                "call_id": tc.get("id") or tc.get("call_id"),
                            },
                            ts=ts,
                        )
                    )
                elif (fr := p.get("functionResponse") or p.get("function_response")) and isinstance(fr, dict):
                    out.append(
                        Message(
                            role="tool",
                            tool_result={
                                "call_id": None,
                                "output": json.dumps(fr.get("response"), ensure_ascii=False),
                            },
                            ts=ts,
                        )
                    )
                elif (tr := p.get("toolResult") or p.get("tool_result")) and isinstance(tr, dict):
                    out.append(
                        Message(
                            role="tool",
                            tool_result={"call_id": tr.get("toolCallId"),
                                         "output": _text_of(tr.get("output"))},
                            ts=ts,
                        )
                    )
            if text_parts:
                out.append(Message(role=role, content="\n".join(text_parts), ts=ts))
            continue
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    out.append(
                        Message(role="assistant",
                                tool_use={"name": b.get("name"),
                                          "arguments": b.get("input") or b.get("arguments"),
                                          "call_id": b.get("id") or b.get("call_id")},
                                ts=ts)
                    )
                elif b.get("type") == "tool_result":
                    from .base_jsonl import tool_result_message

                    out.append(tool_result_message(b, ts))
                elif b.get("type") == "text" and b.get("text"):
                    out.append(Message(role=role, content=b["text"], ts=ts))
            continue
        text = _text_of(content)
        if text:
            out.append(Message(role=role, content=text, ts=ts))
    return out


# ---------- SQLCipher 解密工具 ----------

# 解密明文临时文件落盘位置。
# 此前 trae_decrypt/universal_decrypt 把明文临时库写在第三方工具目录
# （<原库>.decrypted.db / .decrypted.pb 同目录）——进程崩溃即把明文聊天
# 记录残留在非受控目录。统一改为写引擎数据目录下的 decrypt_tmp/ 子目录，
# 且 try_any_decrypt 每次解密前清扫本目录遗留的 *.decrypted.* 临时文件。
_DECRYPT_TMP_SUBDIR = "decrypt_tmp"
# 已知解密临时文件名模式（清扫口径；CommunityToolStrategy 查找的第三方
# 预解密文件不在此列——那些是用户自建的，不归本引擎清扫）
_DECRYPT_TMP_PATTERNS = ("*.decrypted.db", "*.decrypted.pb")
# 测试/嵌入式场景可覆写落盘目录（None = 跟随引擎数据目录）
_decrypt_tmp_dir_override: Path | None = None


def set_decrypt_tmp_dir(d: Path | None) -> None:
    """覆写解密明文临时目录（仅供测试/特殊部署用；None = 恢复默认）。"""
    global _decrypt_tmp_dir_override
    _decrypt_tmp_dir_override = Path(d) if d is not None else None


def decrypt_tmp_dir() -> Path:
    """解密明文临时目录：引擎数据目录下 decrypt_tmp/（只读 store 解析，不写 store）。

    数据目录解析失败（极端环境）→ 回退 ~/.experientia——仍属引擎受控目录，
    绝不落第三方工具目录。
    """
    if _decrypt_tmp_dir_override is not None:
        return _decrypt_tmp_dir_override
    try:
        from ...store.store import resolve_data_dir

        data_dir, _ = resolve_data_dir()
    except Exception:
        data_dir = Path.home() / ".experientia"
    return data_dir / _DECRYPT_TMP_SUBDIR


def _decrypted_tmp_name(src: Path, suffix: str) -> str:
    """解密临时文件名：<源名>-<源路径指纹8位>.decrypted<源后缀>。

    指纹防同名冲突（不同目录的同名库解密产物互不覆盖）；
    后缀保留 .decrypted.db / .decrypted.pb 口径以便清扫匹配。

    刻意**不做 resolve**：这里只派生一个临时文件名，值变了无副作用（旧文件由
    sweep_stale_decrypt_tmp 清扫），反而不如容忍路径写法差异省一次 syscall。
    形似的另一份是 aider._session_id_for（算 session_id，**会** resolve），
    两者语义不同——那份的产出是落库去重键，别把两份合并成一个。
    """
    tag = hashlib.sha1(str(src).encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"{src.stem}-{tag}.decrypted{suffix}"


def sweep_stale_decrypt_tmp() -> int:
    """清扫本模块遗留的 *.decrypted.* 明文临时文件（崩溃残留）。

    只清 decrypt_tmp_dir() 内匹配已知模式的文件（该目录只有本引擎写入），
    返回删除数；失败不抛（清扫是卫生措施，不阻塞解密主流程）。
    """
    n = 0
    try:
        d = decrypt_tmp_dir()
        if d.is_dir():
            for pattern in _DECRYPT_TMP_PATTERNS:
                for p in d.glob(pattern):
                    try:
                        p.unlink(missing_ok=True)
                        n += 1
                    except OSError:
                        pass
    except Exception as exc:
        logger.debug("解密临时目录清扫失败（忽略）: %s", exc)
    if n:
        logger.info("清扫崩溃遗留的解密明文临时文件 %d 个", n)
    return n


def sqlcipher_connect(path: Path, key: bytes) -> sqlite3.Connection | None:
    """用原始密钥连接 SQLCipher 加密数据库（需要 pysqlcipher3 或 sqlcipher 扩展）。

    注意：标准 sqlite3 模块不支持 SQLCipher。此函数为预留接口，
    实际解密走 trae_decrypt 模块的进程内存扫描 + AES-CBC 解密方案。
    """
    return None


def parse_db_ref(
    adapter: AdapterBase,
    ref: SessionRef,
    is_encrypted_fn=None,
) -> Session | None:
    """通用 SQLite .db ref 解析：加密 → None，非加密 → parse_sessions 取第一条。

    这是 Hermes 修复模式的通用化版本——所有 SQLite 系适配器共用此模式，
    避免各自在不同文件里重复同样的 if-else 逻辑。

    Args:
        adapter: 适配器实例（必须有 parse_sessions 方法）
        ref: 待解析的会话引用
        is_encrypted_fn: 可选的加密检测函数，默认用 is_encrypted(ref.path)

    Returns:
        Session 或 None（加密/无消息）
    """
    # 契约声明：空库（0 表、表空、解密后 0 会话）→
    # 返回 None（调用方 parse_sessions 语义归一化为 []），不抛异常——
    # 与 base_jsonl 基类同口径：空 ≠ 失败，scan 不计黄标失败。
    enc = is_encrypted_fn(ref.path) if is_encrypted_fn else is_encrypted(ref.path)
    if enc:
        # 加密的 SQLite 容器库：先试统一解密框架（trae 进程内存 / windsurf 全局密钥 /
        # 社区工具）。无可用策略或解密失败 → None（由调用方决定是否标记"已加密"）；
        # 成功则解析解密临时文件并在 finally 清理（照 trae.parse 的临时文件生命周期）。
        # 说明：is_encrypted 是内容级判断（非 SQLite 头 + 尺寸≥4096），parse_db_ref 的
        # 调用方均为 SQLite 容器 adapter（cursor 的 state.vscdb 等），故不再限定 .db 后缀。
        try:
            from .universal_decrypt import try_any_decrypt as _try_any
        except Exception:
            _try_any = None
        if _try_any is None:
            return None
        decrypted = _try_any(ref.path, ref.agent)
        if decrypted is None:
            return None
        try:
            temp_ref = SessionRef(
                agent=ref.agent, session_id=ref.session_id,
                path=decrypted, size=decrypted.stat().st_size,
                mtime=decrypted.stat().st_mtime, encrypted=False)
            sessions = adapter.parse_sessions(temp_ref)
            return sessions[0] if sessions else None
        finally:
            try:
                decrypted.unlink(missing_ok=True)
            except OSError:
                pass
    sessions = adapter.parse_sessions(ref)
    return sessions[0] if sessions else None


def build_session(adapter_name: str, session_id: str, blob, **meta) -> Session | None:
    """通用：会话 blob → 归一化 Session（无消息 → None）。"""
    session = Session(agent=adapter_name, session_id=str(session_id))
    session.project = meta.get("project")
    session.started_at = meta.get("started_at")
    session.model = meta.get("model")
    session.messages = extract_messages(blob)
    return session if session.messages else None
