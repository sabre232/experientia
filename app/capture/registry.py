"""自动探测注册表——默认策略：自动探测，不是选目录。

启动时逐个探测已知路径：存在即启用、不存在即忽略，用户零选择。
加 agent = adapters/ 加一个文件 + 下面 REGISTRY 加一行。
按 （修订版）分档：
  T1 JSONL：claude-code / codex / openclaw / qclaw / workbuddy / codebuddy /
    qoder / cline / roo-code / aider（Wave 1）
  T1 单 JSON（Gemini 系）：gemini-cli / qwen-code / iflow（Wave 2）
  T2 SQLite/KV：opencode / goose / kilocode / zed / hermes / openhands /
    cursor / dsh（Wave 3）
  T2 实验性：trae / windsurf / copilot-cli（Wave 4）
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from .adapters.aider import AiderAdapter
from .adapters.claude_code import ClaudeCodeAdapter
from .adapters.cline import ClineAdapter
from .adapters.codex import CodexAdapter
from .adapters.codebuddy import CodeBuddyAdapter
from .adapters.copilot_cli import CopilotCliAdapter
from .adapters.cursor import CursorAdapter
from .adapters.dsh import DshAdapter
from .adapters.gemini_family import GeminiCliAdapter, IflowAdapter, QwenCodeAdapter
from .adapters.goose import GooseAdapter
from .adapters.hermes import HermesAdapter
from .adapters.kilocode import KiloCodeAdapter
from .adapters.openhands import OpenHandsAdapter
from .adapters.opencode import OpenCodeAdapter
from .models import AdapterBase, SessionRef
from .adapters.openclaw import OpenClawAdapter
from .adapters.qclaw import QClawAdapter
from .adapters.qoder import QoderAdapter
from .adapters.roo_code import RooCodeAdapter
from .adapters.trae import TraeAdapter
from .adapters.workbuddy import WorkBuddyAdapter
from .adapters.windsurf import WindsurfAdapter
from .adapters.zed import ZedAdapter

logger = logging.getLogger("experientia.capture.registry")

REGISTRY: dict[str, type[AdapterBase]] = {
    # Wave 1（T1 文本系）
    "codex": CodexAdapter,
    "claude-code": ClaudeCodeAdapter,
    "openclaw": OpenClawAdapter,
    "qclaw": QClawAdapter,
    "workbuddy": WorkBuddyAdapter,
    "codebuddy": CodeBuddyAdapter,
    "qoder": QoderAdapter,
    "cline": ClineAdapter,
    "roo-code": RooCodeAdapter,
    "aider": AiderAdapter,
    # Wave 2（T1 单 JSON，Gemini 系）
    "gemini-cli": GeminiCliAdapter,
    "qwen-code": QwenCodeAdapter,
    "iflow": IflowAdapter,
    # Wave 3（T2 SQLite/KV）
    "opencode": OpenCodeAdapter,
    "goose": GooseAdapter,
    "kilocode": KiloCodeAdapter,
    "zed": ZedAdapter,
    "hermes": HermesAdapter,
    "openhands": OpenHandsAdapter,
    "cursor": CursorAdapter,
    "dsh": DshAdapter,
    # Wave 4（T2 实验性）
    "trae": TraeAdapter,
    "windsurf": WindsurfAdapter,
    "copilot-cli": CopilotCliAdapter,
}

# 产品文档首发列 25 家，此 REGISTRY 实装 24 家。第 25 家 QoderWork
# 刻意不注册：文档自身把它标为「待实测」（`%APPDATA%\QoderWork\data\agents.db`
# 是否加密、JSONL 布局均无官方/社区实证），凭空写投机解析器违反「文档没写的
# 不要自己发明」。拿到真实样本、确认格式后再补 adapters/qoderwork.py + 此处一行。
# 豆包工作已从首发移出，故也不探测。


# /api/status 每次切页都调 detect()（~21 个 adapter 各 discover()，
# Windows 目录遍历慢）。给无过滤的全量探测加进程内 TTL 缓存——GUI 的密集
# status 调用命中缓存，scan_loop 传 force=True 始终拿新数据（它是落盘
# detected_agents.json 的权威探测，不能吃到陈旧值）。
# TTL 15s→120s：15s 内 GUI 每次切页都可能冷缓存重扫（1.7s+ 卡主线程）；
# 120s 配合 scan_loop 每轮 prime_cache 回填，GUI 常态化命中缓存。
DETECT_CACHE_TTL = 120.0
_detect_lock = threading.Lock()
_detect_cache: tuple[float, dict[str, list[SessionRef]]] | None = None

# 权威探测（scan_loop）的节流间隔——捕获扫描仍按 SCAN_INTERVAL_SECONDS=60
# 跑，但全量探测降到 300s 一次（新会话最长 5 分钟被发现）。
# 稳态下 60s 内不会重复付探测成本，也把与 GUI 抢 GIL 的频率降 5 倍。
DETECT_INTERVAL_SECONDS = 300.0
_last_force: tuple[float, dict[str, list[SessionRef]]] | None = None

# ---------- 全盘深度扫描（勿扰模式） ----------

# 全盘深度扫描当前**全仓无调用点**（`start_deep_scan` 无人调、`_deep_scan_cache`
# 恒 None）。但一旦被接上，`base_jsonl._detect_scan_roots` 会枚举**所有固定盘符**、
# 深扫 12 层——灾难级。故此处置显式总闸（默认关闭）：启用前必须**先**满足全部条件：
# ① 受 config `capture.enabled` 约束（禁用时不扫）；
# ② 只扫用户显式配置的目录（不得默认枚举全盘）；
# ③ 分片执行并主动让出 GIL（不得长时间独占主线程）；
# ④ 全程超时熔断。
# 满足后再改 `_DEEP_SCAN_ENABLED = True`（或接入设置页开关），并补端到端手测。
_DEEP_SCAN_ENABLED = False

# 全盘扫描结果缓存（后台线程写入，detect 读取合并）
_deep_scan_cache: dict[str, list[SessionRef]] | None = None
_deep_scan_lock = threading.Lock()
_deep_scan_started = False
# 全盘扫描间隔（秒）：首次启动后延迟 30s 执行，之后每 3600s（1h）重扫
_DEEP_SCAN_INITIAL_DELAY = 30.0
_DEEP_SCAN_INTERVAL = 3600.0

# 全盘扫描的文件模式（覆盖所有已知 agent 数据文件类型）
_DEEP_SCAN_PATTERNS = ["*.jsonl", "*.json", "*.db", ".aider.chat.history.md"]


def prime_cache(found: dict[str, list[SessionRef]]) -> None:
    """把一次权威探测结果写入 TTL 缓存。

    scan_loop 每轮 run_scan 后调用：GUI 的 /api/status 命中这份新鲜数据，
    不必在主线程重复全盘探测（消除切页顿挫/启动首帧阻塞）。
    """
    global _detect_cache
    with _detect_lock:
        _detect_cache = (time.monotonic(), found)


def _collect_all_search_names() -> list[str]:
    """收集所有注册 adapter 的 search_names，去重后返回。

    用于全盘扫描：一次性扫描所有已知 agent 目录名，避免对每个 adapter 单独扫描。
    """
    seen: set[str] = set()
    names: list[str] = []
    for adapter_cls in REGISTRY.values():
        for name in getattr(adapter_cls, "search_names", []):
            key = name.lower()
            if key not in seen:
                seen.add(key)
                names.append(name)
    return names


def _agent_for_data_path(path: Path) -> str | None:
    """根据文件路径猜测属于哪个 agent。

    遍历 REGISTRY，将路径的各级目录名与 adapter 的 search_names 匹配。
    """
    path_lower = str(path).lower()
    for agent, adapter_cls in REGISTRY.items():
        for name in getattr(adapter_cls, "search_names", []):
            if name.lower() in path_lower:
                return agent
    # 兜底：按目录名匹配
    parts = path.parts
    for part in parts:
        p = part.lower().strip(".")
        for agent, adapter_cls in REGISTRY.items():
            for name in getattr(adapter_cls, "search_names", []):
                n = name.lower().strip(".")
                if p == n:
                    return agent
    return None


def _build_session_ref(
    path: Path, agent: str, session_id: str | None = None,
) -> SessionRef | None:
    """构造 SessionRef，统一处理 stat 异常。"""
    try:
        st = path.stat()
    except OSError:
        return None
    return SessionRef(
        agent=agent,
        session_id=session_id or path.stem,
        path=path,
        size=st.st_size,
        mtime=st.st_mtime,
    )


def _run_deep_scan() -> None:
    """执行全盘深度扫描（后台线程调用）。

    扫描结果写入 _deep_scan_cache，供 detect() 在常规探测后合并。
    """
    global _deep_scan_cache
    if not _DEEP_SCAN_ENABLED:  # 总闸默认关闭（见 _DEEP_SCAN_ENABLED 说明）
        return
    from .adapters.base_jsonl import deep_scan as _deep_scan

    agent_names = _collect_all_search_names()
    if not agent_names:
        return

    logger.info("全盘深度扫描启动（%d 个 agent 模式，%s）", len(agent_names), agent_names[:5])
    t0 = time.monotonic()
    try:
        found = _deep_scan(agent_names, _DEEP_SCAN_PATTERNS)
    except Exception as exc:
        logger.warning("全盘深度扫描异常: %s", exc)
        return
    elapsed = time.monotonic() - t0
    logger.info("全盘深度扫描完成（%d 个文件，耗时 %.1fs）", len(found), elapsed)

    # 按 agent 分组
    grouped: dict[str, list[SessionRef]] = {}
    seen: set[str] = set()
    for path in found:
        agent = _agent_for_data_path(path)
        if agent is None:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        ref = _build_session_ref(path, agent)
        if ref is not None:
            grouped.setdefault(agent, []).append(ref)

    with _deep_scan_lock:
        _deep_scan_cache = grouped


def _deep_scan_loop() -> None:
    """全盘深度扫描循环（后台线程）。

    首次延迟 _DEEP_SCAN_INITIAL_DELAY 秒后执行，之后每 _DEEP_SCAN_INTERVAL 秒重扫。
    """
    time.sleep(_DEEP_SCAN_INITIAL_DELAY)
    while True:
        _run_deep_scan()
        time.sleep(_DEEP_SCAN_INTERVAL)


def _ensure_deep_scan_started() -> None:
    """确保全盘深度扫描后台线程已启动（惰性启动，仅在首次 detect() 时触发）。"""
    global _deep_scan_started
    if not _DEEP_SCAN_ENABLED:  # 总闸关闭则绝不启动线程
        return
    if _deep_scan_started:
        return
    with _deep_scan_lock:
        if _deep_scan_started:
            return
        _deep_scan_started = True
        # spawn 兜底：_run_deep_scan 一旦抛异常，深扫线程会静默死亡且永不重启
        # （惰性启动只跑一次），表现为"深度扫描再也不更新"且无任何日志。
        from ..thread_util import spawn
        t = spawn(_deep_scan_loop, name="deep-scan")
        logger.debug("全盘深度扫描后台线程已启动（延迟 %.0fs 后首次执行）", _DEEP_SCAN_INITIAL_DELAY)


def _merge_deep_scan(found: dict[str, list[SessionRef]]) -> dict[str, list[SessionRef]]:
    """把全盘扫描结果合并到常规探测结果中。

    全盘扫描找到但常规探测没找到的 agent 会被追加到相应列表。
    """
    with _deep_scan_lock:
        deep = _deep_scan_cache
    if deep is None:
        return found

    merged = {agent: list(refs) for agent, refs in found.items()}
    # 全盘扫描已有路径的 seen set
    existing: set[str] = set()
    for refs in merged.values():
        for r in refs:
            existing.add(str(r.path))

    for agent, refs in deep.items():
        if agent not in merged:
            merged[agent] = []
        for r in refs:
            if str(r.path) not in existing:
                existing.add(str(r.path))
                merged[agent].append(r)

    return merged


def merge_channel_refs(found: dict[str, list[SessionRef]],
                       channels: dict) -> dict[str, list[SessionRef]]:
    """把钥匙通道（capture_channels.json，Keys 激活产物）的来源并入探测结果。

    keys: {agent: {mode, sources:[{path,...}], ...}}。只并入 REGISTRY 内 agent——
    未知生态没有解析器，并了也无法 parse；其通道信息保留在 self_reported/keys，
    等对应适配器注册后（agent 进入 REGISTRY）即自动被接管。
    存在性每轮重检：文件已消失的路径跳过（路径漂移/卸载不产生黄标噪音）。
    """
    if not channels:
        return found
    merged = {agent: list(refs) for agent, refs in found.items()}
    seen = {str(r.path) for refs in merged.values() for r in refs}
    for agent, ch in channels.items():
        if agent not in REGISTRY:
            continue
        if str(ch.get("mode") or "") != "scan_covered":
            continue
        for s in (ch.get("sources") or []):
            path = str(s.get("path") or "")
            if not path or path in seen:
                continue
            p = Path(path)
            if not p.is_file():
                continue
            ref = _build_session_ref(p, agent)
            if ref is None:
                continue
            seen.add(path)
            merged.setdefault(agent, []).append(ref)
    return merged


# 单个 adapter 的探测硬超时（秒）——防止某个 adapter 卡死（慢盘 / 网络路径 /
# 异常遍历）拖死整轮探测。探测与 GUI 同进程抢 GIL，超时即放弃该 adapter 本轮结果
# （下一轮自动重试；不引入"永久钉死"）。见 _discover_with_timeout docstring 的取舍。
PROBE_ADAPTER_TIMEOUT = 3.0


def _discover_with_timeout(adapter, agent: str) -> list[SessionRef]:
    """在独立线程里跑 adapter.discover()，最多等 PROBE_ADAPTER_TIMEOUT 秒。

    超时 → 记 WARNING 并返回空（本轮放弃该 adapter，下轮重试）。**取舍**：超时后
    工作线程无法被强杀（Python 无线程级 kill），作为 daemon 线程继续跑到自然结束；
    正常路径（实测稳态 ~63ms）不触发超时，不产生额外常驻线程。
    """
    box: dict = {}

    def _run() -> None:
        try:
            box["refs"] = adapter.discover()
        except Exception as exc:  # noqa: BLE001 带回主线程统一收口记日志
            box["err"] = exc

    th = threading.Thread(target=_run, name=f"probe-{agent}", daemon=True)
    th.start()
    th.join(PROBE_ADAPTER_TIMEOUT)
    if th.is_alive():
        logger.warning("适配器 %s 探测超时（>%.1fs），本轮放弃该 adapter（下轮重试）",
                       agent, PROBE_ADAPTER_TIMEOUT)
        return []
    err = box.get("err")
    if err is not None:
        logger.error("adapter %s discover 异常", agent, exc_info=err)
        return []
    return box.get("refs") or []


def _detect_all() -> dict[str, list[SessionRef]]:
    found: dict[str, list[SessionRef]] = {}
    for agent, adapter_cls in REGISTRY.items():
        try:
            adapter = adapter_cls()
        except Exception:
            logger.error("adapter %s 实例化异常", agent, exc_info=True)
            continue
        refs = _discover_with_timeout(adapter, agent)
        if refs:
            found[agent] = refs

    # 合并全盘扫描结果（如果有后台线程已写入缓存）
    merged = _merge_deep_scan(found)
    return merged


def detect(
    enabled: set[str] | None = None,
    force: bool = False,
    min_interval: float = 0.0,
) -> dict[str, list[SessionRef]]:
    """探测所有已注册 agent，返回 agent -> SessionRef 列表（空则不出现）。

    enabled=None 且非 force（全量）走 TTL 缓存——GUI 密集的 /api/agents 命中；
    带 enabled 过滤或 force=True（scan_loop 权威探测）直接重算，不读写缓存。
    min_interval>0（配合 force=True）对权威探测再套一层节流：距上次权威
    探测不足 min_interval 秒则复用其结果——捕获扫描每 60s 跑，探测降频到 300s。
    """
    global _detect_cache, _last_force
    if enabled is not None:
        found = _detect_all()
        return {a: r for a, r in found.items() if a in enabled}
    if force:
        if min_interval > 0:
            now = time.monotonic()
            with _detect_lock:
                hit = _last_force
            if hit is not None and now - hit[0] <= min_interval:
                return dict(hit[1])  # 节流窗口内复用上次权威结果
        found = _detect_all()
        if min_interval > 0:
            ts = time.monotonic()
            with _detect_lock:
                _last_force = (ts, found)
                # 权威结果回填 GUI 的 TTL 缓存也进同一临界区
                # ——原来在锁外赋值，与读侧并发时可能被旧值盖回去。
                _detect_cache = (ts, found)
        return dict(found)
    now = time.monotonic()
    with _detect_lock:
        hit = _detect_cache
    if hit is not None and now - hit[0] <= DETECT_CACHE_TTL:
        return dict(hit[1])  # 浅拷贝顶层 dict，防调用方注入新键污染缓存
    with _detect_lock:
        hit = _detect_cache
        if hit is not None and time.monotonic() - hit[0] <= DETECT_CACHE_TTL:
            return dict(hit[1])  # 双检：另一线程可能刚写入
        found = _detect_all()
        _detect_cache = (time.monotonic(), found)
    return dict(found)


def start_deep_scan() -> None:
    """启动全盘深度扫描后台线程（勿扰模式）。

    由应用启动时（main / API 初始化）调用，不作为 detect() 的一部分，
    避免测试时意外触发。后台线程延迟 30s 后首次执行，之后每 3600s 重扫一次。

    默认被 `_DEEP_SCAN_ENABLED` 总闸拦住（当前全仓无调用点；见该常量
    docstring 的启用前置条件）——启用前不得放开。
    """
    if not _DEEP_SCAN_ENABLED:
        logger.debug("start_deep_scan 被总闸忽略（_DEEP_SCAN_ENABLED=False）")
        return
    _ensure_deep_scan_started()