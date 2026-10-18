"""捕获扫描编排：注册表探测 → 增量解析 → 归档 → session 落库。

增量策略（文件类按 mtime+size 增量）：
- 状态存 store.load_capture_state()，key=原始文件路径，value=[size, mtime]
- 未变化 → 跳过；变化或新增 → 解析 → 归档 → 落 sessions.jsonl
- 解析失败 → 不更新状态（下轮重试），连续失败由上层做黄标（容错）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..store.store import Store
from . import archive
from .models import Session, SessionRef
from .registry import (DETECT_INTERVAL_SECONDS, REGISTRY, detect,
                       merge_channel_refs, prime_cache)

logger = logging.getLogger("experientia.capture")

# 同一 agent 连续 N 轮扫描全部解析失败 → 黄标（格式漂移信号，容错）。
# 只提示不阻塞：下轮解析成功即自动消标。
YELLOW_FLAG_THRESHOLD = 3


@dataclass
class ScanResult:
    new_sessions: dict[str, int] = field(default_factory=dict)
    parse_failures: dict[str, int] = field(default_factory=dict)
    skipped: int = 0
    # 入队瘦身：队列存 review dict（已被契约 + 20×200 截断约束，
    # 单条 <32KB）而非完整 Session 对象（workbuddy 单条含 2–6MB 原始消息）
    new_session_dicts: list[dict] = field(default_factory=list)


def session_to_review_dict(session: Session, store: Store) -> dict:
    """归一化 Session → 复盘/落库共用 dict（三通道统一口径）。

    文件通道补齐代理通道同名的 trunk/category/req_count/correction_hits：
    - trunk/category 走 detect_task_context（历史经验词级匹配 > 种子关键词 > 其他/未分类）；
    - req_count = user 轮数（与代理通道"请求数"同为协作深度口径，供磨合度/空转判定）；
    - correction_hits = user 消息否定词命中数（与代理通道 record_exchange 同口径）。
    """
    from ..proxy import detect as proxy_detect
    from ..distill.review import _FALLBACK_NEGATION_DEFAULTS

    user_msgs = [str(m.content or "") for m in session.messages
                 if m.role == "user" and str(m.content or "").strip()]
    asst_msgs = [str(m.content or "") for m in session.messages
                 if m.role == "assistant" and str(m.content or "").strip()]
    config = store.load_config()
    negation = [w for w in (config.get("negation_words") or _FALLBACK_NEGATION_DEFAULTS) if w]
    task = proxy_detect.detect_task_context(
        [{"content": m} for m in user_msgs[-3:]],
        config.get("seed_keywords", proxy_detect.DEFAULT_SEED_KEYWORDS),
        proxy_detect.known_categories_from_store(store),
        store=store,
    )
    d = session.to_dict()
    d.update({
        "trunk": task["trunk"],
        "category": task["category"],
        "req_count": len(user_msgs),
        "correction_hits": sum(1 for m in user_msgs if any(w in m for w in negation)),
        "user_messages": user_msgs,
        "assistant_messages": asst_msgs,
    })
    return d


def review_dict_for_replay(store: Store, rec: dict) -> dict:
    """重放素材回读原文（-P1-4，Zep episode 范式）。

    落库转录是截断口径（20×200，展示用）；复盘素材必须尽量回到全文——
    按证据队列条目 ref（或 <agent>/<sid>.jsonl 惯例路径）回读归档原件，
    用与首次捕获完全相同的解析链重建 review dict；原件不在/解析失败
    回退落库记录（宁降级不阻塞重放）。"""
    if not rec:
        return rec
    agent = str(rec.get("agent") or "")
    sid = str(rec.get("session_id") or "")
    rel = str(rec.get("ref") or f"sessions/{agent}/{sid}.jsonl")
    root = store.data_dir.resolve()
    path = (root / rel).resolve()
    # 字符串前缀可被同前缀目录穿透（如 .experientia-evil）；
    # 改路径分段比较（Python 3.11+ is_relative_to）。
    if not path.is_relative_to(root):
        return rec
    if not path.exists():
        # ② 归档压缩：旧档可能已转 <name>.zst（原件已删）——同一解析链照读，
        # `.zst` 由 JsonlAdapterBase._open_text 流式解压（复盘素材质量不因压缩而降级）
        compressed = path.with_name(path.name + ".zst")
        if not compressed.exists():
            return rec
        path = compressed
    adapter_cls = REGISTRY.get(agent)
    if adapter_cls is None:
        return rec
    try:
        ref = SessionRef(agent=agent, session_id=sid, path=path,
                         size=path.stat().st_size, mtime=path.stat().st_mtime)
        for session in adapter_cls().parse_sessions(ref):
            if session and session.session_id == sid:
                d = session_to_review_dict(session, store)
                d["ref"] = rel
                return d
    except Exception as exc:
        logger.info("重放回读原件失败（回退落库记录）%s/%s: %s",
                    agent, sid[:12], exc)
    return rec


def settle_reviewed(store: Store, session_dicts: list[dict]) -> None:
    """复盘**成功**后的收口：标已复盘 + 摘掉「在飞」标记。

    与入队侧的 mark_review_queued 成对。两种情况**不标记**：

    1. 复盘抛异常——调用方用 try 包着，这里根本进不来，在飞标记保留 → 超过
       REVIEW_RETRY_AFTER_S 后自动重试；
    2. **无模型 / 熔断 open**——这不是失败，是 review_sessions 里设计好的降级
       路径（走 review.defer_to_replay 挂队列待重放，见本文件
       review_sessions）。它**不抛异常**，只靠 try 判断不出来；若在此标记，
       无模型的会话就永远不再复盘了，恰好违背 H7 的"失败要能重试"。
    """
    from ..distill import llm

    if not llm.model_available(store) or llm.circuit_open(store):
        return
    for d in session_dicts:
        sid = str(d.get("session_id") or "")
        if not sid:
            continue
        store.mark_reviewed(d.get("agent"), sid)
        store.clear_review_queued(d.get("agent"), sid)


def review_sessions(store: Store, session_dicts: list[dict]) -> int:
    """文件通道 review dict → 候选经验（档 A 复盘，与代理通道同一套逻辑）。

    同步入口（CLI scan / daemon 复盘工作线程）：内部走 llm.call_model 同步包装。
    M3：直接收 review dict（run_scan 落库前已构建，零额外成本；队列满恢复路径
    复用的是同一"从落库 dict 复盘"入口，两条路径合一）。
    空转会话（轮数 <2 且无纠正）零成本跳过；无模型/熔断 open → 降级只记 L2 纠正候选。
    返回新增经验条数。
    """
    from ..distill import llm, review

    total = 0
    for session_dict in session_dicts:
        try:
            if not review.has_distillable_signals(session_dict):
                continue
            trunk, category = session_dict["trunk"], session_dict["category"]
            prompt = review.REVIEW_PROMPT.format(
                trunk=trunk, category=category,
                req_count=session_dict["req_count"],
                correction_hits=session_dict["correction_hits"],
                digest=review._digest(session_dict),
            )
            added = 0
            drafted = 0
            rejected = 0
            if not llm.model_available(store) or llm.circuit_open(store):
                # 无模型不产经验，挂队列待重放（口径与
                # has_distillable_signals 对齐，不再要求有纠正片段）
                review.defer_to_replay(store, session_dict)
            else:
                candidates = None
                for _attempt in range(2):  # 空输出/截断解析失败 → 重试一次（本地小模型抖动）
                    try:
                        raw = llm.call_model(store, [{"role": "user", "content": prompt}])
                    except Exception as exc:
                        # 蒸馏兜底方案：配了调不通也要接回落（
                        # 文件通道此前异常直接跳过，而会话已标 reviewed，将永久漏蒸）
                        logger.warning("文件通道复盘模型调用失败 %s: %s",
                                       session_dict.get("session_id", "?"), exc)
                        raw = None
                    if raw is not None:
                        try:
                            candidates = llm.extract_json(raw)
                            break  # 解析成功（含截断修复）→ 不再重试
                        except ValueError as exc:
                            logger.warning("文件通道复盘输出无法解析(attempt %d) %s: %s",
                                           _attempt + 1, session_dict.get("session_id", "?"), exc)
                if isinstance(candidates, list):
                    for cand in candidates[:10]:
                        rec = review._process_candidate(cand, session_dict, store)
                        if rec is None:
                            continue
                        # 写入总闸：注意力闸（D1）→ 证据闸（D3）→ 合并落库（D4）
                        _stored, route = review.commit_candidate(rec, store)
                        if route == "draft":
                            drafted += 1
                        elif route == "rejected":
                            rejected += 1
                        else:
                            added += 1
                else:
                    # 模型调用失败/输出不可解析 → 挂队列待重放
                    #（；会话已标 reviewed，队列是唯一兜底机会，不得静默丢弃）
                    review.defer_to_replay(store, session_dict)
            if added or drafted or rejected:
                tails = []
                if drafted:
                    tails.append(f"{drafted} 条缺原话证据转草稿")
                if rejected:
                    tails.append(f"{rejected} 条被判为环境噪音未入库")
                tail = "；".join(tails)
                if tail:
                    tail = "（" + tail + "）"
                # 会话级 upsert（信息量控制·阀门一）：文件通道与代理/hook 通道
                # 共用 (agent, sid) 机器身份，同会话重复复盘只更新计数
                store.upsert_review_node(
                    session_dict.get("agent", "?"),
                    session_dict.get("session_id", ""),
                    added,
                    f"复盘 {session_dict.get('agent', '?')} 会话 "
                    f"{str(session_dict.get('session_id', ''))[:12]}… → "
                    f"{trunk}/{category} 入库 {added} 条（文件通道）{tail}",
                )
                total += added
        except Exception as exc:
            logger.warning("文件通道复盘失败 %s: %s",
                           session_dict.get("session_id", "?"), exc)
    return total


def _triage_empty_ref(agent: str, ref, sig: list, state: dict, result: ScanResult,
                      parse_error: bool, verbose: bool) -> bool:
    """解析出 0 会话时的三分叉（从 run_scan 抽出的密集分支）。

    三种情形语义不同，混在一起很容易改错——每轮扫描都会走到，改错的后果是
    **黄标机制失效**（失败计数无限增长，或"已知不可解"被永久钉死）：

    - 解析**抛异常** = 真失败（格式漂移/读不了）：计失败、**不更新签名** → 下轮重试；
    - 适配器已探测到**加密**（如 Trae 的 SQLCipher 库）且当前解密路径不可用 =
      显式跳过（断链修复方案）：更新签名、不计失败。否则该 ref 每轮解析必
      失败，失败计数无限增长（实测 trae 7668 轮）。重试条件：文件签名变化
      （size/mtime，如 agent 重写库或用户用社区工具生成预解密文件后 db 被替换）；
    - **解析成功但 0 会话**（新建空文件/空库）：「空库≠失败」——与加密分支
      对称，更新签名后跳过。

    返回 True = 该 ref 计入本 agent 的失败（仅第一种情形）。调用方三种情形都
    应 `continue`。
    """
    key = str(ref.path)
    if parse_error:
        result.parse_failures[agent] = result.parse_failures.get(agent, 0) + 1
        return True
    state[key] = sig
    result.skipped += 1
    if ref.encrypted:
        if verbose:
            print(f"[capture] {agent} 加密库显式跳过（更新签名，不计失败）: "
                  f"{ref.path.name}")
    else:
        if verbose:
            print(f"[capture] {agent} 空文件跳过（解析成功 0 会话，更新签名不计失败）: "
                  f"{ref.path.name}")
    return False


def run_scan(store: Store, verbose: bool = True, review: bool = True) -> ScanResult:
    # S2：先吸收 skill 自报（incoming），再跑常规文件探测——自报可补适配器盲区
    try:
        from . import probe as probe_ch
        incoming_n = probe_ch.run_incoming(store)
        if incoming_n and verbose:
            print(f"[capture] 自报吸收 {incoming_n} 份（skill 兜底通道）")
    except Exception as exc:
        logger.warning("incoming 自报吸收失败（不影响扫描）: %s", exc)
    result = ScanResult()
    state = store.load_capture_state()
    failures = store.load_capture_failures()
    # W2-01：采集开关（config capture.enabled，缺省=全启用）。
    # 过滤在解析层而不是 detect() 层：禁用的 agent 仍留在 detected 里，
    # 函数末尾的 stale-clear 不会清掉它的失败计数 → 黄标冻结不清零（W2-04）。
    enabled_map = (store.load_config().get("capture") or {}).get("enabled") or {}
    # 权威探测但按 DETECT_INTERVAL_SECONDS 节流（捕获扫描仍 60s 一轮，
    # 探测降到 300s 一次；窗口内复用上轮 refs，state 未变即全跳过，零重解析）。
    detected = detect(force=True, min_interval=DETECT_INTERVAL_SECONDS)
    # Keys 捕获通道：skill 自报已激活的可扫来源并入本轮 → 常态化捕获（吸收即行动，
    # 下一轮起不再依赖 skill 重复上报；路径已消失的文件本轮跳过）
    try:
        detected = merge_channel_refs(detected, store.load_capture_channels())
    except Exception as exc:  # noqa: BLE001 通道合并失败不影响常规探测
        logger.warning("钥匙通道合并失败（不影响扫描）: %s", exc)
    # 权威探测结果回填 GUI 的 TTL 缓存：/api/status 命中缓存，免主线程重复全盘扫
    prime_cache(detected)
    for agent, refs in detected.items():
        if enabled_map.get(agent, True) is False:
            continue
        adapter = REGISTRY[agent]()
        agent_ok = False
        agent_processed = False  # 本轮是否有 ref 真正参与解析（全跳过 ≠ 失败）
        agent_failed = False  # 是否有 ref 真失败（显式跳过不计）
        agent_hit_path: str | None = None  # W1-05：每轮每 agent 至多一行命中流水
        agent_events = 0
        for ref in refs:
            key = str(ref.path)
            sig = [ref.size, ref.mtime]
            if state.get(key) == sig:
                result.skipped += 1
                continue
            agent_processed = True
            parse_error = False
            try:
                sessions = adapter.parse_sessions(ref)  # 默认 = [parse(ref)]（多会话 SQLite 类覆盖）
            except Exception as exc:
                sessions = []
                parse_error = True
                if verbose:
                    print(f"[capture] {agent} 解析异常 {ref.path}: {exc}")
            if not sessions:
                if _triage_empty_ref(agent, ref, sig, state, result,
                                     parse_error, verbose):
                    agent_failed = True
                continue  # 真失败不更新状态 → 下轮重试；显式/空文件跳过已更新
            agent_ok = True
            # 单条归档/落库失败只跳过该条，不断整轮——原来
            # 任一异常会中断本轮剩余 agent（state 未保存，60s 后重试自愈，但期间
            # 捕获延迟；模块承诺的"单条跳过"此前只覆盖 parse 层）。
            try:
                archive.archive_ref(ref, sessions, store.dir("sessions"))  # 每 ref 至多一份（M-3）
            except Exception as exc:
                logger.warning("归档失败（跳过本条归档，继续落库）%s: %s",
                               ref.path, exc)
            for session in sessions:
                # review dict 构建一次：落库（store 内部截断副本）与入队复盘共用
                session_dict = session_to_review_dict(session, store)
                try:
                    store.record_session(session_dict)
                except Exception as exc:
                    logger.warning("会话落库失败（跳过本条）%s/%s: %s",
                                   session.agent, session.session_id, exc)
                    continue
                # 档 A「触发一次」：每个会话只复盘一次。活会话文件持续
                # 增长（每轮扫描 size/mtime 变化）只刷新落库记录，不再重复入队
                # ——否则 LLM 反复提炼同一会话，措辞漂移击穿经验侧精确去重，
                # 经验库落下重复行（经验 tab 重复卡片）。
                # ，用户拍板）：**入队不再等于已复盘**。
                # 以前这里直接 mark_reviewed —— 复盘失败/未跑完的会话也被标记成
                # 已复盘，从此再不会重试（H7 原始问题）。现在入队只记「在飞」，
                # 由 settle_reviewed() 在复盘成功侧真正标记。
                # 「不重复入队」的语义靠 should_enqueue_review 的窗口保证
                # （在飞未超 REVIEW_RETRY_AFTER_S 不再入队），见其 docstring。
                if store.should_enqueue_review(session.agent, session.session_id):
                    store.mark_review_queued(session.agent, session.session_id)
                    result.new_session_dicts.append(session_dict)
            state[key] = sig
            result.new_sessions[agent] = result.new_sessions.get(agent, 0) + len(sessions)
            if agent_hit_path is None:
                agent_hit_path = str(ref.path)
            agent_events += sum(len(s.messages) for s in sessions)
            if verbose:
                print(
                    f"[capture] {agent} {len(sessions)} 个会话 "
                    f"({', '.join(s.session_id[:12] for s in sessions[:3])}{'…' if len(sessions) > 3 else ''})"
                )
        if agent_processed:
            if agent_ok:
                if failures.get(agent):
                    logger.info("黄标解除：%s 解析恢复", agent)
                failures[agent] = 0
                if agent_hit_path is not None and agent_events > 0:
                    store.record_capture_hit(agent, agent_hit_path, agent_events)
            elif agent_failed:
                # 全部 ref 显式跳过（加密不可解）不算失败——计数冻结
                failures[agent] = failures.get(agent, 0) + 1
                if failures[agent] == YELLOW_FLAG_THRESHOLD:
                    logger.warning(
                        "黄标：%s 连续 %d 轮扫描全部解析失败——可能格式漂移"
                        "（社区口径解析器为实验性）",
                        agent, failures[agent],
                    )
    # agent 不再被探测到（卸载/目录消失）→ 清掉失败计数，避免陈旧黄标
    for agent in [a for a in failures if failures[a] and a not in detected]:
        del failures[agent]
    store.save_capture_failures({a: n for a, n in failures.items() if n})
    store.save_capture_state(state)
    # 第 6 轮：把"实际在跑"（探测到真实会话文件）的 agent 集合落盘，
    # /api/capture 只列这些——不再铺全 REGISTRY 名字清单（用户反馈噪音）。
    store.save_detected_agents(sorted(detected.keys()))
    # 探测结果快照（agent → 会话数 + 采集时间）——/api/status、/api/agents
    # 只读此快照，绝不在 GUI 请求线程触发全量探测。
    store.save_agents_snapshot({a: len(refs) for a, refs in detected.items()})
    # 文件捕获零配置出经验（验收）：新 session 走档 A 复盘。
    # daemon 传 review=False（复盘进独立工作线程，不阻塞扫描循环）；CLI scan 同步跑。
    if review and result.new_session_dicts:
        try:
            reviewed = review_sessions(store, result.new_session_dicts)
            settle_reviewed(store, result.new_session_dicts)
            if reviewed and verbose:
                print(f"[capture] 复盘：新增 {reviewed} 条候选经验")
        except Exception as exc:
            logger.warning("文件通道复盘失败（不影响捕获）: %s", exc)
        # T1 结构事实挖掘（修复方案）：确定性零 LLM，与档 A 复盘同
        # 生命周期（new_session_dicts 每会话只出现一次，天然幂等）
        try:
            from ..distill.mining import mine_session_dicts
            cards = mine_session_dicts(store, result.new_session_dicts)
            if cards and verbose:
                print(f"[capture] T1 挖掘：{cards} 条坑卡落库/合并")
        except Exception as exc:
            logger.warning("T1 挖掘失败（不影响捕获）: %s", exc)
    return result
