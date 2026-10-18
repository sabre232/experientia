"""JSONL 文本系解析基类（T1）。

Claude Code / OpenClaw / QClaw / WorkBuddy / CodeBuddy / Qoder / Codex 共用的骨架：
- discover：根目录探测（环境变量可覆盖）+ glob + stat + SessionRef 构造；
  若 session_roots 找不到，触发自动搜索（search_common_locations）在所有常见路径下找 .jsonl。
- parse：读 → 逐行 → 坏行跳过 → _handle_event 分派 → 无有效消息返回 None
- try_formats 尝试多格式解析（主要格式 → Claude 兼容格式 → 通用 JSONL）

子类只需实现：session_roots()（返回可能的会话根目录，不存在则跳过）与
_handle_event(session, event)；glob_pattern / session_id_from_path 可按需覆盖。

Claude 系行类型（每行一个对象，type=user/assistant/summary；message.content 为
字符串或块数组 [text/tool_use/tool_result]）的公共分派在 claude_handle_event()。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections.abc import Iterator
from ...time_util import utc_str
from pathlib import Path

from ..models import AdapterBase, Message, Session, SessionRef

logger = logging.getLogger("experientia.capture.base_jsonl")


# ---------- 公共工具函数 ----------

def _resolve_home(env_var: str, default_dir: str) -> Path:
    """M-N11: 统一 adapter 路径解析——环境变量可覆盖，回退到 ~/.<default_dir>。"""
    return Path(os.environ.get(env_var, str(Path.home() / default_dir)))


# 常见平台基础目录
def _platform_base_dirs() -> list[Path]:
    """返回当前平台的所有常见数据根目录。"""
    home = Path.home()
    dirs = [home]
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        progdata = Path(os.environ.get("ProgramData", "C:\\ProgramData"))
        dirs.extend([
            appdata, local,
            appdata / "Programs",
            home / "AppData" / "Local" / "Programs",
            progdata,
            home / "Documents",
            home / "Downloads",
        ])
    elif sys.platform == "darwin":
        dirs.extend([
            home / "Library" / "Application Support",
            home / "Library" / "Preferences",
            home / "Documents",
            home / "Downloads",
        ])
    else:
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
        xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
        dirs.extend([xdg_data, xdg_config, home / ".local" / "share",
                     home / "Documents", home / "Downloads"])
    return dirs


def search_common_locations(
    agent_names: list[str],
    file_patterns: list[str],
    max_depth: int = 5,
) -> list[Path]:
    """在所有常见平台路径下搜索 agent 数据文件。

    搜索 ~, %APPDATA%, %LOCALAPPDATA%, ~/.local/share 等目录下以 agent_name
    命名的子目录，在其中查找 file_patterns 匹配的文件。

    Args:
        agent_names: agent 可能的目录名列表（如 ["hermes", "Hermes"]）
        file_patterns: 要匹配的文件模式（如 ["*.db", "state.db"]）
        max_depth: 最大搜索深度，防止遍历太深

    Returns:
        匹配的文件路径列表（按 mtime 倒序）
    """
    base_dirs = _platform_base_dirs()
    found: list[Path] = []
    seen: set[str] = set()

    for base in base_dirs:
        if not base.is_dir():
            continue
        for name in agent_names:
            target = base / name
            if not target.is_dir():
                continue
            for pattern in file_patterns:
                for path in sorted(target.rglob(pattern)):
                    if not path.is_file():
                        continue
                    key = str(path).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(path)

    # 按 mtime 倒序（最新文件优先）
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found


# b：auto_search 在"已知路径存在但无会话"时会被每轮探测反复触发并重扫平台
# 常见目录（openclaw 实测 285ms/轮，纯浪费）。**只对负结果（一个文件都没找到）
# 做 TTL 缓存**：正结果不缓存（一旦找到即正常返回，行为不变）；负结果在 TTL 内
# 复用空列表，跳过 rglob。语义代价：新出现在"非默认位置"的会话最长 TTL 秒后
# 才被发现——与探测降频（DETECT_INTERVAL_SECONDS=300）同量级，属已接受窗口。
_AUTOSEARCH_NEG_TTL = 300.0
_autosearch_neg: dict[tuple, float] = {}
_autosearch_neg_lock = threading.Lock()


# ---------- 全盘深度扫描 ----------

# 系统目录排除列表（各平台）
_SYSTEM_DIRS_WIN = (
    "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
    "C:\\ProgramData\\Microsoft", "C:\\$Recycle.Bin", "C:\\System Volume Information",
    "C:\\Recovery", "C:\\Intel", "C:\\PerfLogs",
)
_SYSTEM_DIRS_MAC = (
    "/System", "/Library", "/private/var/db", "/private/var/log",
    "/private/var/tmp", "/cores", "/dev", "/Volumes/Recovery",
)
_SYSTEM_DIRS_LINUX = (
    "/proc", "/sys", "/dev", "/run", "/boot", "/lost+found",
    "/var/log", "/var/cache", "/var/tmp", "/tmp",
)

# 已知 agent 目录名模式（用于 deep_scan 快速排除非 agent 目录）
_KNOWN_AGENT_PREFIXES = (
    ".",  # 所有 .agentname 目录
    "Trae", "Cursor", "Windsurf", "Code", "Code - Insiders",
)


def _is_system_dir(path: Path) -> bool:
    """判断路径是否在系统目录排除列表中。"""
    try:
        resolved = str(path.resolve()).rstrip("\\/")
    except OSError:
        return True  # 解析失败视为系统目录，跳过
    if sys.platform == "win32":
        # Windows 匹配排除列表 + 判断是否系统盘
        for d in _SYSTEM_DIRS_WIN:
            if resolved.lower().startswith(d.lower()):
                return True
        # 排除非用户盘（只扫 C: 和用户有写入权限的盘）
        if resolved[1:2] == ":" and resolved[2:3] == "\\" and resolved[0].lower() not in ("c",):
            return True  # 只扫 C 盘，其他盘需要用户手动配置
        return False
    elif sys.platform == "darwin":
        for d in _SYSTEM_DIRS_MAC:
            if resolved.startswith(d):
                return True
        return False
    else:
        for d in _SYSTEM_DIRS_LINUX:
            if resolved.startswith(d):
                return True
        return False


def _agent_dir_match(name: str, agent_names: list[str]) -> bool:
    """判断目录名是否匹配已知 agent 模式。
    
    agent_names 含 .agent 前缀时（如 [".claude", ".qclaw"]），
    匹配目录名完全等于 .claude 或 .qclaw；
    不含前缀时（如 ["claude"]），匹配 claude 或 .claude。
    """
    lower = name.lower()
    for agent in agent_names:
        a = agent.lower()
        if a.startswith("."):
            # 精确匹配 .xx
            if lower == a:
                return True
        else:
            # 匹配 xx 或 .xx
            if lower == a or lower == "." + a:
                return True
    return False


def deep_scan(
    agent_names: list[str],
    file_patterns: list[str],
    max_depth: int = 12,
    drives: list[str] | None = None,
) -> list[Path]:
    """全盘深度扫描，在系统各驱动器根目录下搜索 agent 数据文件。

    设计原则：
    - **勿扰**：限深 + 排除系统目录，不会扫到不该扫的地方
    - **广度优先**：先扫快速路径，再扫深层目录
    - **按 agent 目录名快速剪枝**：只进名字匹配 agent 的目录下钻

    Args:
        agent_names: agent 可能的目录名列表（如 ["claude", "ClaudeCode"]）
        file_patterns: 要匹配的文件模式（如 ["*.jsonl", "*.db"]）
        max_depth: 最大搜索深度，防止遍历太深（默认 12 层）
        drives: 指定搜索的驱动器根目录列表（默认自动探测）

    Returns:
        匹配的文件路径列表（按 mtime 倒序）
    """
    found: list[Path] = []
    seen: set[str] = set()

    # 确定搜索根目录
    if drives is None:
        drives = _detect_scan_roots()

    for root in drives:
        if not root.is_dir():
            continue
        try:
            _deep_scan_walk(root, agent_names, file_patterns, max_depth, found, seen)
        except PermissionError:
            logger.debug("deep_scan 无权限访问 %s，跳过", root)
        except OSError:
            continue

    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found


def _detect_scan_roots() -> list[Path]:
    """自动探测全盘扫描的根目录。

    Windows: 所有固定驱动器（C: D: 等，跳过光驱/软驱/网络映射）
    macOS: /Users + /（根目录，但排除系统目录）
    Linux: /home + /（根目录，但排除系统目录）
    """
    roots: list[Path] = []
    if sys.platform == "win32":
        import string

        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if Path(drive).is_dir():
                # 用 GetDriveType 可更好区分，但简单判断目录存在即可
                roots.append(Path(drive))
    else:
        # macOS/Linux: 用户目录 + /
        roots.append(Path.home())
        # 也扫根目录（但排除系统目录）
        roots.append(Path("/"))
    return roots


def _deep_scan_walk(
    root: Path,
    agent_names: list[str],
    file_patterns: list[str],
    max_depth: int,
    found: list[Path],
    seen: set[str],
    _depth: int = 0,
) -> None:
    """递归扫描目录树，深度优先 + 剪枝。"""
    if _depth > max_depth:
        return
    if _is_system_dir(root):
        return

    try:
        entries = list(root.iterdir())
    except (PermissionError, OSError):
        return

    # 先检查当前目录是否匹配 agent 模式
    dir_name = root.name
    if _depth > 0 and _agent_dir_match(dir_name, agent_names):
        # 在这个目录下搜文件
        for pattern in file_patterns:
            try:
                for path in root.rglob(pattern):
                    if not path.is_file():
                        continue
                    key = str(path).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(path)
            except (PermissionError, OSError):
                continue
        # 不继续下钻子目录（rglob 已经递归了）
        return

    # 只在 _depth <= 1 时递归子目录发现 agent 目录
    # 深度 0/1 只进非系统目录发现 agent 目录；深度 1 后不再下钻
    if _depth <= 1:
        for entry in entries:
            if not entry.is_dir():
                continue
            # 快速剪枝：跳过隐藏目录（除非是 .agentname 模式）
            if entry.name.startswith(".") and not _agent_dir_match(entry.name, agent_names):
                continue
            _deep_scan_walk(entry, agent_names, file_patterns, max_depth,
                           found, seen, _depth + 1)


# ---------- Claude 系（claude-code / openclaw / qclaw / workbuddy / codebuddy / qoder）公共逻辑 ----------

def _text_of(content) -> str:
    """Claude 系 content：字符串，或块数组（只取 text 块）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
        ]
        return "\n".join(parts)
    return ""


def tool_use_message(tool_use: dict, ts: str | None) -> Message:
    return Message(
        role="assistant",
        tool_use={
            "name": tool_use.get("name"),
            "arguments": tool_use.get("input") or tool_use.get("arguments"),
            "call_id": tool_use.get("id") or tool_use.get("call_id"),
        },
        ts=ts,
    )


def tool_result_message(tool_result: dict, ts: str | None) -> Message:
    output = tool_result.get("content")
    if isinstance(output, list):
        parts = []
        for b in output:
            if isinstance(b, dict):
                if b.get("type") == "text" and b.get("text"):
                    parts.append(b["text"])
                elif b.get("content") is not None:
                    parts.append(_text_of(b.get("content")))
            else:
                parts.append(_text_of(b))
        output = "\n".join(parts)
    return Message(
        role="tool",
        tool_result={
            "call_id": tool_result.get("tool_use_id") or tool_result.get("call_id"),
            "output": output,
        },
        ts=ts,
    )


def _append_blocks(session: Session, role: str, content: list, ts: str | None) -> None:
    """按块原始顺序落消息：text 块连续合并为一条，tool_use/tool_result 各成一条。"""
    text_parts: list[str] = []

    def _flush_text() -> None:
        if text_parts:
            session.messages.append(
                Message(role=role, content="\n".join(text_parts), ts=ts)
            )
            text_parts.clear()

    for b in content:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "tool_use":
            _flush_text()
            session.messages.append(tool_use_message(b, ts))
        elif btype == "tool_result":
            _flush_text()
            session.messages.append(tool_result_message(b, ts))
        elif btype == "text" and b.get("text"):
            text_parts.append(b["text"])
    _flush_text()


def _ts_to_iso(ts) -> str | None:
    """事件时间戳 → ISO UTC（epoch 数值或 ISO 字符串都收）。

    epoch 毫秒（workbuddy/providerData 口径）与 ISO 字符串（Claude Code 系
    timestamp 口径）两种都在用；秒级 epoch 与毫秒级靠数量级区分。
    无法识别时返回 None——**绝不返回原样字符串**：写进去一个非 ISO 的值会让
    prune_sessions 的时间比较失效。
    """
    # 去重 R1：数值判定（含"数字字符串也按 epoch"这条既有口径）、秒/毫秒换算、
    # 尾 Z、时区归一全部收到 time_util.utc_str；本函数只保留一层语义差异——
    # 失败返回 None（utc_str 返回空串），下游拿 None 才知道"这条别写"。
    out = utc_str(ts)
    return out or None


def claude_handle_event(session: Session, event: dict) -> None:
    """Claude Code 系行分派：user / assistant 消息行；summary 等元数据行不进经验流。

    **这里不负责 started_at**——有具体口径的适配器（qclaw 取 message 行的时间戳、
    workbuddy 转 epoch 毫秒）自己在 _handle_event 里提取，它们知道该用哪个事件。
    基类的兜底放在 JsonlAdapterBase.parse 的收尾处：整个会话解析完还是空时才填。
    """
    etype = event.get("type")
    ts = event.get("timestamp") or event.get("ts")
    if etype not in ("user", "assistant"):
        return
    msg = event.get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        _append_blocks(session, etype, content, ts)
    else:
        text = _text_of(content)
        if text:
            session.messages.append(Message(role=etype, content=text, ts=ts))
    model = msg.get("model")
    if isinstance(model, str) and model and not session.model:
        session.model = model


# ---------- JSONL 基类 ----------

class JsonlAdapterBase(AdapterBase):
    """JSONL 会话解析器基类。子类实现 session_roots() 与 _handle_event()。"""

    name: str = ""
    glob_pattern: str = "**/*.jsonl"
    # 自动搜索用：agent 可能的目录名列表（主名 + 常见变体）
    search_names: list[str] = []
    # 是否启用自动搜索（首次 discover 无结果时触发）
    auto_search: bool = True

    def session_roots(self) -> list[Path]:
        """所有可能的会话根目录（含环境变量覆盖）；调用方对不存在的路径跳过。"""
        raise NotImplementedError

    def session_id_from_path(self, path: Path) -> str:
        return path.stem

    def discover(self) -> list[SessionRef]:
        refs: list[SessionRef] = []
        seen: set[str] = set()
        for root in self.session_roots():
            if not root.is_dir():
                continue
            for path in sorted(root.rglob(self.glob_pattern)):
                if not path.is_file():
                    continue
                key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    st = path.stat()
                except OSError:
                    continue
                refs.append(
                    SessionRef(
                        agent=self.name,
                        session_id=self.session_id_from_path(path),
                        path=path,
                        size=st.st_size,
                        mtime=st.st_mtime,
                    )
                )
        # 自动搜索回退：已知路径找不到时，搜所有常见位置
        if not refs and self.auto_search and self.search_names:
            # b：负结果 TTL 缓存——上轮没找到且未过期则跳过这轮 rglob
            neg_key = (self.name, tuple(self.search_names), self.glob_pattern)
            now = time.monotonic()
            with _autosearch_neg_lock:
                cached_at = _autosearch_neg.get(neg_key)
            if cached_at is None or now - cached_at > _AUTOSEARCH_NEG_TTL:
                auto_paths = search_common_locations(
                    self.search_names, [self.glob_pattern]
                )
                if auto_paths:
                    with _autosearch_neg_lock:
                        _autosearch_neg.pop(neg_key, None)
                    for path in auto_paths:
                        key = str(path)
                        if key in seen:
                            continue
                        seen.add(key)
                        try:
                            st = path.stat()
                        except OSError:
                            continue
                        refs.append(
                            SessionRef(
                                agent=self.name,
                                session_id=self.session_id_from_path(path),
                                path=path,
                                size=st.st_size,
                                mtime=st.st_mtime,
                            )
                        )
                else:
                    with _autosearch_neg_lock:
                        _autosearch_neg[neg_key] = now
        return refs

    def try_formats(self, ref: SessionRef) -> list[Session]:
        """尝试多种格式解析。

        1. 主格式（_handle_event）
        2. Claude 兼容格式（claude_handle_event）
        3. 通用 JSONL（每行尝试作为消息）

        两种格式各自流式读取：会话 JSONL 单条可达数 MB、
        整库数百 MB，不再整文件 read_text 常驻内存；仅格式 1 无产出时才
        付出第二次流式扫描的成本。
        """
        sessions = []
        # 格式 1：主格式
        s = self.parse(ref)
        if s is not None:
            sessions.append(s)
            return sessions
        # 格式 2：Claude 兼容格式
        session = Session(agent=self.name, session_id=ref.session_id)
        for event in self._iter_events_file(ref.path):
            claude_handle_event(session, event)
        if session.messages:
            return [session]
        return sessions

    def _open_text(self, path: Path):
        """打开会话文件为文本流（``.zst`` 冷档走 zstd 流式解压）。

        ``.zst`` 两处来源共用这条出口：源端冷档（如 codex 官方把
        rollout-*.jsonl 压成 .zst）+ 本仓归档压缩（②，旧归档转 .zst）。
        流式解压，不整包驻留内存。子类仍可覆盖（如 SQLite 类适配器另有路径）。

        errors="replace"：坏字节不再让整个文件解析失败，与 
        「单条坏行跳过不中断」同口径（此前整文件 read_text 遇坏字节即全失败）。
        """
        if path.name.endswith(".zst"):
            import io

            import zstandard

            raw = zstandard.ZstdDecompressor().stream_reader(
                path.open("rb"), closefd=True)
            return io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
        return path.open("r", encoding="utf-8", errors="replace")

    def _iter_events_file(self, path: Path) -> Iterator[dict]:
        """流式逐行解析：逐行产出 JSON 事件 dict（不整文件驻留内存）。

        OSError（文件消失/无权限）→ 静默结束；坏行跳过不中断。
        """
        try:
            with self._open_text(path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # 单条坏行跳过，不中断整体
                    if isinstance(event, dict):
                        yield event
        except OSError:
            return

    def parse(self, ref: SessionRef) -> Session | None:
        # 契约声明：空文件/空库（0 字节、无有效行、解析成功但
        # 0 条消息）→ 本基类返回 None（parse_sessions 归一化为 []），绝不抛异常、
        # 绝不返回非列表——调用方（scan.run_scan）据此区分「空库」与「真失败」。
        session = Session(agent=self.name, session_id=ref.session_id)
        first_ts = None
        for event in self._iter_events_file(ref.path):
            if first_ts is None:
                first_ts = event.get("timestamp") or event.get("ts")
            self._handle_event(session, event)
        # started_at 兜底（放在基类收尾，而不是让各子类各抄一遍）：它是 90 天保留期
        # 的唯一依据，缺了它会话永久滞留、永不清理。历史上这一步只写在 workbuddy
        # 里，后加的 qoder 直接漏抄 → 实测中有会话因此恒为 null。放在基类
        # 收尾，只当具体口径的适配器都没填上时才兜上，不抢它们的语义。
        if not session.started_at and first_ts is not None:
            session.started_at = _ts_to_iso(first_ts)
        return session if session.messages else None

    def _handle_event(self, session: Session, event: dict) -> None:
        raise NotImplementedError


class ClaudeFamilyAdapter(JsonlAdapterBase):
    """Claude Code 系（claude-code / openclaw / qclaw / workbuddy / codebuddy / qoder）：
    行分派 = claude_handle_event + 行内 cwd 提取为 project。子类只给 name 与路径。"""

    def _handle_event(self, session: Session, event: dict) -> None:
        cwd = event.get("cwd")
        if isinstance(cwd, str) and cwd and not session.project:
            session.project = cwd
        claude_handle_event(session, event)
