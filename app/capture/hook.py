"""Hook 通道（产品文档通道 3，Claude Code 首发，阶段 B 扩事件）。

无代理用户的增强通道（文件捕获之外的第二条腿）：
- SessionStart：实时 session 追踪 + transcript 即时归档（抢在 30 天清理前）
- UserPromptSubmit：additionalContext 注入规则 + 经验 = 无代理用户的「硬钩子」等价物
- PostToolUse：工具调用完成事件——只做生效验证（observed），不在热路径加负载
- Stop：轮毕信号——实时触发「复盘写经验」（与代理通道会话结束同一条管线，
  review.maybe_review_session；独立 worker 线程跑，hook 立即返回不阻塞 agent）

契约按 Claude Code 官方 hooks 文档（code.claude.com/docs/hooks）：
- 输入：stdin JSON（session_id / transcript_path / cwd / prompt / hook_event_name）
- 输出：stdout JSON；SessionStart / UserPromptSubmit 支持
  {"hookSpecificOutput": {"hookEventName": ..., "additionalContext": "..."}}
- 容错口径：任何异常都返回空 dict（curl 退出码 0）——hook 失败绝不阻塞用户的 agent。
- 可回滚：Stop 自动复盘由 config `capture.hook_stop_review` 开关（缺省 True）保护，
  置 False 即恢复旧行为（复盘仍由文件通道每 60s 兜底）。

一键 settings.json 配置（GUI 按钮）：
- 写用户级 ~/.claude/settings.json；合并保留用户既有配置，写前备份 .experientia.bak
- 幂等：以命令里含 /api/hooks/ 识别本通道条目，重跑不重复追加；移除按钮精确清掉
"""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import threading
from collections import OrderedDict
from pathlib import Path

from ..fs_util import replace_atomic
from ..proxy import detect, inject
from ..store.store import Store, utcnow
from . import archive, registry
from .models import SessionRef

logger = logging.getLogger("experientia.capture.hook")

LOCAL_API_PORT = 8101  # 与 daemon.LOCAL_API_PORT 一致（本地 API 固定端口）
AGENT = "claude-code"
DEFAULT_AGENT = AGENT

# 客户端注册表（memorax 借鉴 A1：加一种 hook 可达的 agent = 加一行）。
# 每行：label（UI 显示）+ events（PascalCase 事件名 → /api/hooks 端点 slug）。
# 目前首发 Claude Code（阶段 B 扩到 4 事件：PostToolUse 生效验证 / Stop 轮毕复盘写经验）。
# Codex/OpenCode 经官方文档核实无声明式 shell hook（各自只能走插件/代理/文件），不在本表。
# 各客户端自己的"配置落点/发现/幂等识别"仍由本文件底部对应函数提供（settings.json 形态），
# 与 adapter 注册表同构：行为按注册表参数化，不写死第二个客户端。
HOOK_CLIENTS: dict[str, dict] = {
    AGENT: {
        "label": "Claude Code",
        "events": (("SessionStart", "session-start"),
                   ("UserPromptSubmit", "user-prompt-submit"),
                   ("PostToolUse", "post-tool-use"),
                   ("Stop", "stop")),
    },
}

# ---------- Stop 轮毕后台复盘（B：队列化，hook 立即返回不阻塞 agent） ----------
# 单 worker + FIFO；LLM 复盘最长可达分钟级（daemon.py 同款口径），不能阻塞 curl。
# 内容增长去重：同一 session 只在新增了用户消息后再复盘（防 Stop 每轮重复刷 LLM）；
# 队列有界：满则本轮放弃，文件通道（60s 扫描）仍兜底复盘。

_REVIEW_QUEUE_MAX = 16
_review_lock = threading.Lock()
_reviewed_upto: dict[str, int] = {}          # session_id → 已复盘时的用户消息数
_review_queue: queue.Queue = queue.Queue(maxsize=_REVIEW_QUEUE_MAX)
_review_worker: threading.Thread | None = None


def _client(agent: str | None) -> str:
    a = agent or DEFAULT_AGENT
    return a if a in HOOK_CLIENTS else DEFAULT_AGENT


# ---------- settings.json 一键配置 ----------

def hook_command(event: str, port: int = LOCAL_API_PORT,
                 key: str | None = None) -> str:
    """平台对应的 curl 命令：stdin 管道 hook JSON → POST 本地 API。

    --max-time 15：引擎无响应时不拖慢用户 agent；curl 无 --fail，HTTP 错误码
    不影响退出码（Claude Code 只看退出码 0/2，0 = 非阻塞）。

    key：事件通道防伪令牌，以 ?key= 查询参数带上——外部
    agent 的 curl 无法携带 Bearer token，用低权限独立令牌挡下无令牌的伪造事件。
    """
    url = f"http://127.0.0.1:{port}/api/hooks/{event}"
    if key:
        url = f"{url}?key={key}"
    if os.name == "nt":
        return (f'curl.exe -s --max-time 15 -X POST "{url}" '
                f'-H "Content-Type: application/json" --data-binary @-')
    return (f"curl -s --max-time 15 -X POST {url} "
            f"-H 'Content-Type: application/json' --data-binary @-")


def hook_config(port: int = LOCAL_API_PORT,
                agent: str | None = None,
                key: str | None = None) -> dict:
    """某客户端的 hook 段（事件名用官方 PascalCase，Claude Code settings.json）。"""
    client = HOOK_CLIENTS[_client(agent)]
    return {
        "hooks": {
            pascal: [{"hooks": [{"type": "command",
                                 "command": hook_command(endpoint, port, key)}]}]
            for pascal, endpoint in client["events"]
        }
    }


def default_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _is_ours(command: object, port: int) -> bool:
    """识别本通道写入的条目（按 URL 特征，不污染 hook 条目 schema）。"""
    return f"127.0.0.1:{port}/api/hooks/" in str(command)


def _matcher_is_ours(matcher: dict, port: int) -> bool:
    inner = matcher.get("hooks")
    return (isinstance(inner, list) and bool(inner)
            and all(isinstance(h, dict) and _is_ours(h.get("command"), port)
                    for h in inner))


def _read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_settings(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    replace_atomic(tmp, path)  # Windows 瞬时锁（AV 扫描）重试，见 app/fs_util.py


def apply_hook_config(path: str | Path | None = None,
                      port: int = LOCAL_API_PORT,
                      key: str | None = None) -> dict:
    """合并写入 ~/.claude/settings.json（幂等 + 写前备份 + 原子替换）。

    key：事件通道防伪令牌，注入到各条 curl 命令的 ?key= 参数。"""
    p = Path(path) if path else default_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = _read_settings(p)
    if p.exists():
        shutil.copy2(p, p.with_name(p.name + ".experientia.bak"))

    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks
    for event, matchers in hook_config(port, key=key)["hooks"].items():
        existing = hooks.get(event)
        if not isinstance(existing, list):
            existing = []
        # 移除本通道旧条目（幂等），保留用户其他条目
        kept = [m for m in existing
                if not (isinstance(m, dict) and _matcher_is_ours(m, port))]
        hooks[event] = kept + matchers
    _write_settings(p, data)
    return {"path": str(p), "events": list(hook_config(port)["hooks"])}


def remove_hook_config(path: str | Path | None = None,
                       port: int = LOCAL_API_PORT) -> dict:
    """移除本通道写入的 hook 条目（用户其他条目不动）。"""
    p = Path(path) if path else default_settings_path()
    if not p.exists():
        return {"path": str(p), "removed": False}
    data = _read_settings(p)
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else None
    removed = False
    if hooks is not None:
        for event in list(hooks):
            matchers = hooks.get(event)
            if not isinstance(matchers, list):
                continue
            kept = [m for m in matchers
                    if not (isinstance(m, dict) and _matcher_is_ours(m, port))]
            if len(kept) != len(matchers):
                hooks[event] = kept
                removed = True
    if removed:
        _write_settings(p, data)
    return {"path": str(p), "removed": removed}


def _iso_age_seconds(ts_iso: str) -> float | None:
    """ISO 时间戳距现在的秒数（尾 Z 按 UTC）；解析失败 → None。

    去重 R1：解析统一走 time_util。**注意本处不做 max(0.0, …) 截断**——
    未来时间戳会得到负数，调用方据此判"时钟异常"，别顺手加下限。
    """
    from datetime import datetime, timezone

    from ..time_util import parse_ts

    dt = parse_ts(ts_iso)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def hook_status(path: str | Path | None = None,
                port: int = LOCAL_API_PORT,
                store: Store | None = None) -> dict:
    """当前配置状态（GUI 显示 + 一键按钮状态）+ observed 生效验证（memorax 借鉴 A2）。

    返回字段：
    - configured / path / events / config：既有；
    - observed：{PascalCase 事件: ISO ts}——最近一次收到该 hook 事件的时刻；
    - last_observed_ago_s：最近一次事件距今秒数（None = 从未收到）。
    """
    p = Path(path) if path else default_settings_path()
    data = _read_settings(p)
    events: list[str] = []
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else None
    if hooks is not None:
        for event, matchers in hooks.items():
            if isinstance(matchers, list) and any(
                    isinstance(m, dict) and _matcher_is_ours(m, port)
                    for m in matchers):
                events.append(event)
    # observed：本地 API 端收到真实 hook 事件才算生效（installed→observed）
    observed: dict[str, str] = {}
    last_ago: float | None = None
    if store is not None:
        raw = store.load_hook_observed()
        for pascal, endpoint in HOOK_CLIENTS[DEFAULT_AGENT]["events"]:
            ts = raw.get(f"{DEFAULT_AGENT}:{endpoint}")
            if ts:
                observed[pascal] = ts
                ago = _iso_age_seconds(ts)
                if ago is not None and (last_ago is None or ago < last_ago):
                    last_ago = ago
    return {"configured": bool(events), "path": str(p),
            "events": events, "config": hook_config(port),
            "observed": observed, "last_observed_ago_s": last_ago}


# ---------- 注入上下文（UserPromptSubmit 的 additionalContext） ----------

# 与代理通道 s.injected_task 同语义：同一 session 的同一归类只真实注入一次
# 。本进程常驻，用有界集合去重，不给热路径加 IO。
_injected_memo: OrderedDict[tuple[str, str, str], bool] = OrderedDict()
_INJECTED_MEMO_MAX = 2000


def _mark_injected(session_id: str, trunk: str, category: str) -> bool:
    """返回 True = 本次是该 session 该归类的首次注入（该记账）。"""
    key = (str(session_id or ""), str(trunk or ""), str(category or ""))
    if key in _injected_memo:
        return False
    _injected_memo[key] = True
    while len(_injected_memo) > _INJECTED_MEMO_MAX:
        _injected_memo.popitem(last=False)
    return True


def build_hook_context(store: Store, prompt: str = "",
                       session_id: str | None = None) -> str:
    """组装 hook 注入文本：规则通道 + 经验块（复用代理通道同一套逻辑，/）。

    任务归类走与代理通道完全一致的 detect_task_context（历史经验匹配 >
    种子关键词 > 其他/未分类）；经验块走同一预算分层截断。
    非中文 locale 下附加翻译免责声明。

    **注入即记账**：经验块真的进了 additionalContext 时，
    与代理通道一样落 injection.log + 条目命中（channel="hook"）。此前这条通道
    只注入不记账，导致飞轮第④格、周报"哪条经验在变强"、档 C 条目老化
    全部看不到 hook 通道的送达——送达了却没留痕，等于没送达。"""
    prompt = (prompt or "")[:2000]
    parts: list[str] = []
    task: dict = {}
    exp_block = ""
    try:
        # H-A0：hook 通道写在 Claude Code 的 settings.json 里，只有 Claude Code 会调用，
        # agent 是确定的（= AGENT），不是 unknown——指定 claude-code 的规则在此通道也要生效
        # （否则"不走代理的 hook 通道"会静默丢掉指定规则）。
        rules_block = inject.assemble_rules_block(
            store, user_content=prompt, agent=AGENT,
            files=inject.extract_file_context(prompt))
        if rules_block:
            parts.append(rules_block)
        config = store.load_config()
        task = detect.detect_task_context(
            [{"content": prompt}],
            config.get("seed_keywords", detect.DEFAULT_SEED_KEYWORDS),
            detect.known_categories_from_store(store),
            store=store,
        )
        exp_block = inject.assemble_experience_block(
            store, task["trunk"], task["category"], task_text=prompt)
        if exp_block:
            parts.append(exp_block)
    except Exception as exc:
        logger.warning("hook 注入组装失败（fail-open，跳过注入）：%s", exc)
        return ""
    if exp_block and session_id and _mark_injected(
            session_id, task.get("trunk", ""), task.get("category", "")):
        try:
            store.record_injection(
                str(task.get("trunk") or ""), str(task.get("category") or ""),
                str(session_id), inject.estimate_tokens(exp_block),
                items=inject.selected_experience_items(
                    store, str(task.get("trunk") or ""),
                    str(task.get("category") or ""), task_text=prompt),
                channel="hook")
        except Exception as exc:  # 记账失败不阻断注入（与代理通道同口径）
            logger.warning("hook 注入命中落盘失败（不影响注入）: %s", exc)
    if not parts:
        return ""
    header = ("[Experientia 经验与规则（本地经验飞轮注入；硬钩子规则每次必须遵守）]\n\n")
    # 非中文 locale 下附加翻译免责声明——AI 翻译的内容可能不准确
    try:
        _locale = (store.load_config().get("locale") or "").split("_")[0].split("-")[0]
        if _locale and _locale != "zh":
            header += (
                "⚠️ 免责声明：以下内容由 AI 从中文翻译而来，时效性和准确性无法 100% 保证。\n"
                "请在使用前自行核实，特别是涉及代码、配置和关键决策的内容。\n\n"
            )
    except Exception as exc:  # 裸 except 留痕（fail-open 不变）
        logger.debug("hook 注入 locale 读取失败（跳过免责声明，不影响注入）: %s", exc)
    return header + "\n\n".join(parts)


# ---------- 事件处理（本地 API /api/hooks/* 调用） ----------

def _has_session(store: Store, session_id: str) -> bool:
    return any(s.get("agent") == AGENT and s.get("session_id") == session_id
               for s in store.list_sessions())


def handle_session_start(store: Store, payload: dict) -> dict:
    """SessionStart：实时落 session + transcript 即时归档（抢在 30 天清理前）。

    优先解析 transcript 全量落库（与文件捕获同格式）；解析不到才记一条
    事件级记录。返回 {}（SessionStart 首版不注入，注入由 UserPromptSubmit 承担）。
    """
    payload = payload or {}
    sid = payload.get("session_id")
    if not sid:
        return {}
    try:
        store.record_hook_observed(AGENT, "session-start")  # installed→observed
    except Exception as exc:  # 裸 except 留痕（fail-open 不变）
        logger.debug("hook session-start observed 记录失败（不阻断）: %s", exc)
    tp = payload.get("transcript_path")
    parsed = 0
    if tp:
        tpath = Path(tp)
        try:
            if tpath.exists():
                st = tpath.stat()
                ref = SessionRef(agent=AGENT, session_id=sid, path=tpath,
                                 size=st.st_size, mtime=st.st_mtime)
                for session in registry.REGISTRY[AGENT]().parse_sessions(ref):
                    store.record_session(session.to_dict())
                    archive.archive_session(ref, session, store.dir("sessions"))
                    parsed += 1
        except Exception:
            logger.exception("hook transcript 解析失败（不影响会话继续）")
    if parsed == 0:
        store.record_session({
            "agent": AGENT,
            "session_id": sid,
            "channel": "hook",
            "project": payload.get("cwd"),
            "transcript_path": tp,
            "started_at": utcnow(),
        })
    return {}


def handle_user_prompt_submit(store: Store, payload: dict) -> dict:
    """UserPromptSubmit：返回 additionalContext（规则 + 经验，硬钩子等价物）。

    顺带实时补记 session（仅当该 session 尚无记录——不降级代理/文件通道的富记录，
     冲突合并：代理通道字段更全、优先）。
    """
    payload = payload or {}
    try:
        store.record_hook_observed(AGENT, "user-prompt-submit")  # installed→observed
    except Exception as exc:  # 裸 except 留痕（fail-open 不变）
        logger.debug("hook user-prompt-submit observed 记录失败（不阻断）: %s", exc)
    sid = payload.get("session_id")
    if sid and not _has_session(store, sid):
        store.record_session({
            "agent": AGENT,
            "session_id": sid,
            "channel": "hook",
            "project": payload.get("cwd"),
            "transcript_path": payload.get("transcript_path"),
            "started_at": utcnow(),
        })
    context = build_hook_context(store, payload.get("prompt") or "",
                                  session_id=sid)
    if not context:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }


def handle_post_tool_use(store: Store, payload: dict) -> dict:
    """PostToolUse：工具调用完成事件（阶段 B）。

    只做 installed→observed 生效验证，返回 {}（不注入、不阻塞、不给热路径加负载）。
    写经验由 Stop（轮毕）统一承担——工具级事件不逐条沉淀，避免噪音候选。
    """
    try:
        store.record_hook_observed(AGENT, "post-tool-use")
    except Exception as exc:  # 裸 except 留痕（fail-open 不变）
        logger.debug("hook post-tool-use observed 记录失败（不阻断）: %s", exc)
    return {}


def _stop_review_enabled(store: Store) -> bool:
    """可回滚开关（Feature Flag）：config `capture.hook_stop_review`，缺省 True。

    置 False = 恢复阶段 A 行为（Stop 只验证生效）；复盘交给文件通道 60s 扫描兜底。
    """
    try:
        capture = store.load_config().get("capture") or {}
        return bool(capture.get("hook_stop_review", True))
    except Exception:
        return True


def _count_user_messages(session) -> int:
    return sum(1 for m in getattr(session, "messages", [])
               if getattr(m, "role", None) == "user")


def _spawn_stop_review(store: Store, session) -> bool:
    """把轮毕会话快照排队给后台复盘（台账门控 + 内容增长去重 + 队列有界）。

    返回是否入队。档 A「触发一次」：复盘台账（reviewed_sessions.json）
    门控——已复盘的 session 直接跳过，防跨通道/跨 Stop 重复提炼落重复经验行
    （LLM 措辞漂移会击穿 (agent,task,action) 精确去重）。
    内容增长去重（_reviewed_upto）仍保留：同内容重复 Stop 不再入队；
    队列满时回滚标记（下个 Stop 会再尝试）。
    """
    sid = getattr(session, "session_id", "")
    if not sid:
        return False
    # 档 A「触发一次」：台账门控（与文件通道 run_scan / 代理 on_session_end
    # 同口径）。已复盘的 session 不再二次提炼——hook 通道历史上按内容增长反复
    # 复盘，每新增一条用户消息再蒸馏一次，措辞漂移击穿 (agent,task,action)
    # 精确去重，落重复经验行（用户报「经验 tab 重复卡片」）。
    try:
        # 改为「应该入队吗」——已复盘的不入队；在飞且未超重试窗口的也不入队
        if not store.should_enqueue_review(AGENT, sid):
            return False
    except Exception as exc:
        logger.warning("hook Stop 复盘台账检查失败（不阻断，降级旧行为）: %s", exc)
    n = _count_user_messages(session)
    global _review_worker
    with _review_lock:
        if _reviewed_upto.get(sid, 0) >= n:
            return False
        _reviewed_upto[sid] = n
    if _review_queue.full():
        with _review_lock:
            _reviewed_upto[sid] = 0
        logger.warning("hook Stop 复盘队列满（容量 %d），本轮放弃，文件通道兜底",
                       _REVIEW_QUEUE_MAX)
        return False
    # 入队只记「在飞」，**复盘成功后**（worker 里 settle）才真正标记。
    # 队列满时上面已 return，台账未标 → 下个 Stop 会再尝试。
    try:
        store.mark_review_queued(AGENT, sid)
    except Exception as exc:
        logger.warning("hook Stop 复盘台账标记失败（不阻断）: %s", exc)
    _review_queue.put((store, session))
    if _review_worker is None or not _review_worker.is_alive():
        _review_worker = threading.Thread(
            target=_stop_review_worker_loop, name="experientia-hook-review",
            daemon=True)
        _review_worker.start()
    return True


def _stop_review_worker_loop() -> None:
    while True:
        store, session = _review_queue.get()
        try:
            _run_stop_review(store, session)
        except Exception as exc:
            # 回滚本进程的"已复盘中水位"——不复滚的话该 sid
            # 永久判"无新增"（`_reviewed_upto.get(sid,0) >= n`），后续 Stop 不再
            # 入队；超过 REVIEW_RETRY_AFTER_S 后台账门控虽会放行，但被这一层挡住，
            # 只剩 60s 文件通道兜底。
            sid = str(getattr(session, "session_id", "") or "")
            if sid:
                with _review_lock:
                    _reviewed_upto[sid] = 0
            logger.warning("hook Stop 复盘异常（已回滚中水位，下个 Stop 重试）: %s", exc)


def _run_stop_review(store: Store, session) -> int:
    """单会话复盘（worker 线程内执行）：与代理通道会话结束同一条管线。

    session_to_review_dict 补齐 trunk/category/req_count/correction_hits；
    空转会话（轮数 <2）零成本跳过；无模型自动落 L2 纠正降级——全程 fail-open。
    """
    from ..distill import review as distill_review
    from .scan import session_to_review_dict, settle_reviewed

    session_dict = session_to_review_dict(session, store)
    # 无可提炼信号：与文件通道同口径——照样收口，不反复重试
    if not distill_review.has_distillable_signals(session_dict):
        settle_reviewed(store, [session_dict])
        return 0
    import asyncio

    n = asyncio.run(distill_review.maybe_review_session(store, session_dict))
    # 复盘跑完且没抛异常才标记——异常会向上抛，worker 捕获时台账未标，
    # 在飞标记保留 → 超过重试窗口后自动重来
    settle_reviewed(store, [session_dict])
    return n


def handle_stop(store: Store, payload: dict) -> dict:
    """Stop（轮毕）：标记 observed + 实时复盘写经验（阶段 B，fail-open）。

    复盘在独立 worker 线程执行（LLM 最长分钟级），本函数立即返回 {}
    不阻塞 Claude Code；内容去重 + 队列有界保证不会每轮重复刷同一会话。
    """
    payload = payload or {}
    try:
        store.record_hook_observed(AGENT, "stop")
    except Exception as exc:  # 裸 except 留痕（fail-open 不变）
        logger.debug("hook stop observed 记录失败（不阻断）: %s", exc)
    sid = payload.get("session_id")
    if not sid or not _stop_review_enabled(store):
        return {}
    tp = payload.get("transcript_path")
    if not tp:
        return {}
    try:
        tpath = Path(tp)
        if not tpath.exists():
            return {}
        st = tpath.stat()
        ref = SessionRef(agent=AGENT, session_id=sid, path=tpath,
                         size=st.st_size, mtime=st.st_mtime)
        sessions = registry.REGISTRY[AGENT]().parse_sessions(ref)
        target = next((s for s in sessions if s.session_id == sid), None)
        if target is None and sessions:
            target = sessions[-1]
        if target is not None:
            _spawn_stop_review(store, target)
    except Exception as exc:
        logger.warning("hook Stop 复盘触发失败（fail-open，文件通道兜底）: %s", exc)
    return {}
