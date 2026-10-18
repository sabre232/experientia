"""档 A：会话结束复盘（产品文档 ，默认开）。

每个已捕获 session 结束后触发一次；输入 = 本次 session 的 digest，
有可沉淀信号才实际蒸馏，没有则跳过（空转会话零成本）。
用当前接入模型跑。复盘只产出"候选经验"，G 门禁决定学进去的是否为真——
复盘决定"什么时候学"，门禁决定"学进去的必须是真的"（与 Hermes 的关键差异）。
"""

from __future__ import annotations

import asyncio
import logging
import re

from .. import memory_discipline
from ..store.store import Store
from . import dedupe, evidence, extract, gsignal, llm, verify

logger = logging.getLogger("experientia.distill.review")

# ---------- 原始会话文本 → 一句结论（确定性，不碰模型） ----------
# 蒸馏兜底方案的提取式思路：折叠空白 → 清会话产物 → 取首句 → 硬截断。
# 保 surviving vocabulary（术语/错误串/路径），不自由改写——卡片展示的
# 标题/踩坑/做法本就是"一句结论"（产品文档），把捕获的原始多行会话
# 压成它。无模型时这是主路径（摆脱对 LLM 的依赖），有模型时是护栏
# （模型偶尔多行输出也会被压回一句）。

# 会话 @ 引用产物：@skill:xxx / @skill_name / @user
_MENTION_RE = re.compile(r"@\w+(?::[\w.-]+)?")
# 图片/附件/链接占位：图已生成 / ![alt](url) / [text](url)
_MEDIA_RE = re.compile(r"图已生成|!\[[^\]]*\]\([^)]*\)|\[[^\]]*\]\([^)]*\)")
# 句读（取首句的边界；冒号不算，它是提示不是断句）
_SENT_END_RE = re.compile(r"[。！？!?；;]")
# 行首列表编号：1. / 1) / 1、/ 1． / 1:
_LEAD_NUM_RE = re.compile(r"^\d{1,2}[.)、．:：]\s*")

# 字段结论长度上限（卡片一行放得下的量，CJK 按字符计）
TASK_MAX, STATE_MAX, ACTION_MAX, OUTCOME_MAX = 40, 60, 60, 40


def compress_to_line(text: str, max_chars: int) -> str:
    """把多行原始会话文本压成一句短结论（确定性，不碰模型）。

    折叠空白 → 去 @ 引用/媒体占位 → 取首句（无句读取整段；首句过短延长到
    第二句）→ 去行首编号 → 硬截断到 max_chars（超出补 …）。提取式而非生成式：
    保住术语/错误串/路径，不自由改写。已是短句的输入（如"端口被占用"）原样通过。
    """
    if not text:
        return ""
    s = re.sub(r"\s+", " ", str(text)).strip()
    if not s:
        return ""
    s = _MENTION_RE.sub(" ", s)
    s = _MEDIA_RE.sub(" ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    m = _SENT_END_RE.search(s)
    if m and m.start() > 0:
        core = s[: m.end()]
        # 首句过短（"是的。""对。"等确认词）→ 延长到第二句；第二句也无句读
        # 则取整段（避免只留下"是的。"这种空泛首句）
        if len(core.rstrip("。！？!?；; ")) < 8:
            m2 = _SENT_END_RE.search(s[m.end():])
            core = s[: m.end() + m2.end()] if m2 else s
    else:
        core = s
    core = core.strip().rstrip("，,、：: ")
    core = _LEAD_NUM_RE.sub("", core).strip()
    if len(core) > max_chars:
        core = core[: max_chars - 1].rstrip() + "…"
    return core.strip()


def _process_candidate(cand: dict, session_dict: dict, store: Store) -> dict | None:
    """从候选词条构建经验记录（G 值映射、质量字段、append）。

    用于统一 review.py maybe_review_session（async）和 scan.py review_sessions（sync）的候选处理逻辑。
    两入口的差异（async to_thread）由调用方处理。

     确定性优先：LLM 的 corrected/causal 自评降为"软证据"，硬证据是
    用户 L1 反馈与会话确定性信号。causal（自称果因）必须附 evidence 原文引用，
    或在会话明确验收收尾时按确定性成功记——否则降级"待验证"(G<0.5)。
    """
    if not isinstance(cand, dict) or not cand.get("action"):
        return None
    # importance（-P1-3）：1-10 自评分，≤2 = 只对本轮有意义，不入库；
    # 缺省 5 兼容旧模型输出（没带该字段不惩罚）
    try:
        imp = int(float(cand.get("importance")))
    except (TypeError, ValueError):
        imp = 5
    if cand.get("importance") is None:
        imp = 5
    if imp <= 2:
        return None
    corrected = bool(cand.get("corrected"))
    causal = bool(cand.get("causal"))
    evidence_text = str(cand.get("evidence") or "").strip()
    # 引用了原话却在会话里定位不到 = 引用不可信（防幻觉）：按"未附证据"对待，
    # 不给 L3_CAUSAL 的信任分。定位判定复用 evidence 模块，口径只此一份。
    quote_verified = bool(evidence_text) and \
        evidence.from_candidate(cand, session_dict) is not None
    confirm = gsignal._is_confirmatory_closing(session_dict)
    if corrected:
        g, source = gsignal.L2_CORRECTED, "auto"
    elif causal:
        if quote_verified:
            g, source = gsignal.L3_CAUSAL, "judge"   # LLM 自评 + **已核实**的原文证据
        elif confirm:
            g, source = gsignal.L2_CLEAN, "auto"      # 确定性成功收尾
        else:
            g, source = gsignal.L3_WEAK, "judge"      # 无证据自评 → 待验证(G<0.5)
    elif confirm:
        g, source = gsignal.L2_CLEAN, "auto"
    else:
        g, source = gsignal.L3_WEAK, "auto"           # 中性收尾，不计作成功
    # 展示字段压成一句结论（compress_to_line），原文另存 *_raw 供卡片下钻
    # —— 模型偶尔多行输出在这里被护栏压回一句（蒸馏兜底方案提取式）。
    raw_task = str(cand.get("task", ""))
    raw_state = str(cand.get("state", ""))
    raw_action = str(cand.get("action", ""))
    raw_outcome = str(cand.get("outcome", ""))
    rec = {
        "task": compress_to_line(raw_task, TASK_MAX),
        "task_raw": raw_task[:400],
        "state": compress_to_line(raw_state, STATE_MAX),
        "state_raw": raw_state[:500],
        "action": compress_to_line(raw_action, ACTION_MAX),
        "action_raw": raw_action[:600],
        "outcome": compress_to_line(raw_outcome, OUTCOME_MAX),
        "outcome_raw": raw_outcome[:400],
        "G": g, "g_source": source, "corrected": corrected,
        "importance": max(1, min(10, imp)),
        "agent": session_dict.get("agent", "unknown"),
        "model": session_dict.get("model", ""),
        "session_id": session_dict.get("session_id", ""),
        "project": session_dict.get("project"),
        "trunk": session_dict.get("trunk") or "其他",
        "category": session_dict.get("category") or "未分类",
    }
    # 证据锚点（D3）：模型明确引用 > 会话验收锚点 > 原文兜底（仅自报场景开启）。
    # 找不到证据时先落个 evidence_state 标记——放行与否由 commit_candidate 的
    # 写入闸决定，不在这里判（本函数仍是纯构建，不决定去向）。
    ev, ev_kind = evidence.resolve(cand, session_dict)
    if ev is not None:
        rec["evidence"] = ev
        rec["evidence_kind"] = ev_kind
    elif source != "user":
        rec["evidence_state"] = "missing"
    if source == "auto" and not corrected and g <= gsignal.G_MIN_INJECT:
        rec["neutral"] = True   # 中性收尾：不算确定性成功（证据强度 = none）；
                                  # <= 把 L2_NEUTRAL(0.5) 一并标中性，防"没否定≠成功"漏网
    rec.update(_quality_fields(rec, store))
    return rec


def commit_candidate(rec: dict, store: Store) -> tuple[dict | None, str]:
    """候选经验入库前的最后两道闸。返回 (落库记录, 去向)。

    去向 ∈ "experience" | "draft" | "rejected" | "advice"。

    三道闸的顺序是刻意的（先粗后细、先分类后取证）：

    1. **注意力闸（D1）** `memory_discipline.admit`——值不值得占地方。
       环境抖动 / 源码回声直接拒；助手自身摩擦转避坑通道（不占经验墙）。
    2. **证据闸（D3）** `evidence.gate`——有没有原话。无证据且非用户确认 → 转草稿，
       用户看过原话再放行，比"悄悄不记"诚实。
    3. 前两道都过 → `dedupe.upsert_experience` 落库（D4 合并纪律）。

    三条候选入口（review.maybe_review_session / capture.scan.review_sessions /
    capture.self_experience.process）都必须走这里，禁止各自 append。
    """
    if not isinstance(rec, dict):
        return None, "draft"
    admission = memory_discipline.admit(rec)
    rec = {**rec, "value_class": admission["value_class"]} \
        if admission["value_class"] else dict(rec)
    if admission["route"] == memory_discipline.ADMIT_REJECT:
        logger.debug("注意力闸拒收（%s）：%s",
                     admission["value_class"], str(rec.get("action"))[:40])
        return None, "rejected"
    if admission["route"] == memory_discipline.ADMIT_ADVICE:
        # 助手自身摩擦：可注入但不占经验墙（surface 由 value_class 派生为 advice）
        rec["value_class"] = admission["value_class"]
        return dedupe.upsert_experience(store, rec)[0], "advice"
    ok, reason = evidence.gate(rec)
    if not ok:
        return store.append_experience_draft(
            {**rec, "draft_reason": reason, "evidence_state": "missing"}), "draft"
    return dedupe.upsert_experience(store, rec)[0], "experience"


def _quality_fields(exp: dict, store: Store) -> dict:
    """只读质量字段（蒸馏兜底方案 /）：技术把手 + 交叉验证增量。

    handles 供日后检索命中；verify 供 G 门禁/UI 来源可信度使用（不改变 G 值，
    防歪 #9）。失败安全：抽取/验证内部均已兜底，这里再包一层防杀主流程。
    """
    out: dict = {}
    try:
        # 把手优先从原文抽——压缩（取首句/硬截断）可能截掉句中的路径/错误串，
        # 用 *_raw 保住检索完整性；无 raw（老数据）时退回展示字段
        raw_keys = ("action_raw", "state_raw", "outcome_raw")
        if any(exp.get(k) for k in raw_keys):
            blob = " ".join(str(exp.get(k) or "") for k in raw_keys)
        else:
            blob = " ".join(str(exp.get(k) or "") for k in
                            ("action", "state", "outcome"))
        handles = extract.extract_handles(blob)
        if handles:
            out["handles"] = handles
        bump = verify.verify_experience(store, {**exp, **out})
        if bump > 0:
            out["verify"] = bump
    except Exception as exc:
        # 失败安全的设计不变（不杀主流程），但静默吞掉会让
        # "这张卡为什么没有把手/交叉验证"无从追查——至少留一条 debug。
        logger.debug("质量字段抽取失败（不影响复盘主流程）: %s", exc)
    return out

REVIEW_PROMPT = """你在复盘一次人机协作会话，目标是提炼"对下次做同类任务有参考价值"的经验。
只提取具体、可复用的做法与教训，不提取一次性细节。

任务归类：{trunk} / {category}
协作轮数：{req_count}  用户纠正/否定次数：{correction_hits}

会话内容（用户消息 U / 助手回复 A，已截断）：
{digest}

输出 JSON 数组（没有可沉淀经验则输出空数组 []），每项：
{{"task": "任务一句话", "state": "当时的问题/状态", "action": "采取的具体做法",
  "outcome": "结果（尽量带数字）", "importance": 1-10,
  "corrected": true/false, "causal": true/false,
  "evidence": "从上面会话内容里逐字摘出的一句原话"}}
corrected = 该做法被用户纠正/否定过；causal = 该做法直接导致了所述结果（二值判定，G 信号 L3）。
evidence = 从上方会话内容中**逐字**摘一句能支撑本条结论的原话（用户说的或助手说的都行）。
必须是原文引文，不许改写、不许自己编——定位不到原话的引用会被整段丢弃并把本条降为待验证。
没有合适的原话就留空字符串 ""，不要硬凑。
importance = 对下次同类任务的参考价值（1-10 整数）：9-10=跨项目通用的规律；
5-8=这类任务用得上的做法；1-4=只对这一次有意义（宁可不输出）。
action 写成可泛化的做法：去掉只属于这一次的路径/文件名/编号（用占位表述），
专业术语和报错关键串原样保留。
环境噪音不是经验：API 报错、限流（如 429）、网络中断、工具自身崩溃——这些
不是用户对 agent 的纠正，"等它恢复再试"也不是做法教训；此类内容直接跳过。
task / state / action / outcome 各为一句短结论：说人话、不换行、不复述原始对话，
只写"结论/教训"不贴会话原文（每张经验卡只展示一句，原文由系统另行保留）。
"""


def _digest(session_dict: dict, max_chars: int = 6000) -> str:
    lines = []
    for i, m in enumerate(session_dict.get("user_messages", [])[-15:]):
        lines.append(f"U{i + 1}: {str(m)[:800]}")
    for i, m in enumerate(session_dict.get("assistant_messages", [])[-15:]):
        lines.append(f"A{i + 1}: {str(m)[:500]}")
    text = "\n".join(lines)
    return text[-max_chars:]


def has_distillable_signals(session_dict: dict) -> bool:
    """空转零成本：有可沉淀信号才实际蒸馏（信号触发 + 轮数 ≥6 兜底）。

    信号 = 有纠正（correction_hits > 0）或明确成功收尾（用户最后一条
    ≤40 字肯定语，gsignal._is_confirmatory_closing）；无信号的长会话
    （req_count ≥ 6）也兜底复盘——覆盖"没踩坑但内容多"的会话。
    每次调用都是一次含 6000 字 digest 的 LLM 成本，宁缺毋滥。
    """
    if session_dict.get("correction_hits", 0) > 0:
        return True
    if gsignal._is_confirmatory_closing(session_dict):
        return True
    return session_dict.get("req_count", 0) >= 6


_FALLBACK_NEGATION_DEFAULTS = (
    "不对", "错了", "重来", "不是这个意思", "不要这样", "wrong", "redo",
)


def _negation_snippets(store: Store, session_dict: dict) -> list[str]:
    """命中否定词的片段。只给「未提炼片段」视图看——永不注入、永不进经验。"""
    negation = store.load_config().get("negation_words") or _FALLBACK_NEGATION_DEFAULTS
    negation = [w for w in negation if w]
    user_msgs = [str(m) for m in session_dict.get("user_messages", [])]
    return [m.strip()[:160] for m in user_msgs
            if any(w in m for w in negation)][:4]


def enqueue_for_replay(store: Store, session_dict: dict) -> int:
    """把一条会话挂进重放队列（无模型 / 模型失败时的唯一兜底），1=新挂起。

    入队口径：资格由调用方已判过的 `has_distillable_signals()`
    决定，这里不再附加"有纠正且摘得出否定词片段"的额外条件。旧口径把
    `req_count≥6` 的干净长会话挡在门外，而调用方紧接着就会 `settle_reviewed`，
    该会话从此永不重来，静默丢失——正是 System1「没模型也不丢数据」的反面。

    片段只是展示材料，取不到就留空，不影响挂起本身。
    """
    return int(store.append_pending_review(
        session_dict.get("agent", "unknown"),
        str(session_dict.get("session_id", "")),
        snippets=_negation_snippets(store, session_dict) or None,
        trunk=session_dict.get("trunk") or "其他",
        category=session_dict.get("category") or "未分类",
    ))


def defer_to_replay(store: Store, session_dict: dict) -> int:
    """生产侧挂起入口：统一走 System1 编排（`pipeline.system1_intake`）。

    三条降级路径（无模型 / 调用异常 / 输出不可解析）与文件通道共用它，
    避免"哪个入口该挂、挂什么口径"各写一遍。返回本次新挂起条数。
    `system1_intake` 自身 fail-open（不抛），调用方不必再包一层。
    """
    from .pipeline import system1_intake  # 懒导入：pipeline 反过来要用本模块

    return int(system1_intake(store, session_dict).get("queued") or 0)


def replay_pending(store: Store, limit: int = 10) -> int:
    """证据队列重放：模型在场时把挂起片段走完整复盘管线。

    触发点：模型路由保存成功后（models_service）+ 每日维护。逐条从落库
    记录重建 review dict（唯一无损来源），走 review_sessions；
    复盘正常完成（含"模型判定无可沉淀"）即出队；模型中途不可用/熔断/
    异常 → 保留条目，本批就此打住（下轮再来）。返回成功出队条数。
    """
    from ..capture.scan import review_sessions, review_dict_for_replay  # 懒导入防循环

    if not llm.model_available(store) or llm.circuit_open(store):
        return 0
    by_key = {(str(s.get("agent", "")), str(s.get("session_id", ""))): s
              for s in store.list_sessions()}
    done = 0
    for agent, sid in store.load_pending_reviews()[:limit]:
        rec = by_key.get((agent, sid))
        if rec is None:
            store.drop_pending_review(agent, sid)  # 落库记录已不存在，队列自愈
            continue
        rec = review_dict_for_replay(store, rec)  # -P1-4 回读归档原文
        if not has_distillable_signals(rec):
            store.drop_pending_review(agent, sid)  # 重建后已无信号，空转不出队
            continue
        try:
            review_sessions(store, [rec])
        except Exception as exc:
            logger.warning("证据队列重放失败 %s/%s: %s", agent, sid[:12], exc)
            return done
        if not llm.model_available(store) or llm.circuit_open(store):
            return done  # 中途熔断：该条留在队列（复盘内部会再挂起，同键去重）
        store.drop_pending_review(agent, sid)
        done += 1
    return done


async def maybe_review_session(store: Store, session_dict: dict) -> int:
    """会话结束钩子（async，代理 sweeper 调用）。返回新增经验条数。"""
    if not has_distillable_signals(session_dict):
        return 0
    # E-2（默认关）：会话有可沉淀信号 → 按需提醒写仓库记忆（防噪音、失败不影响复盘）
    try:
        from app.memory_skill import maybe_remind_store

        maybe_remind_store(store, session_dict)
    except Exception as exc:
        logger.warning("仓库记忆提醒异常: %s", exc)
    trunk = session_dict.get("trunk") or "其他"
    category = session_dict.get("category") or "未分类"
    prompt = REVIEW_PROMPT.format(
        trunk=trunk,
        category=category,
        req_count=session_dict.get("req_count", 0),
        correction_hits=session_dict.get("correction_hits", 0),
        digest=_digest(session_dict),
    )
    # 经验链路修复方案：没配（switcher）/ 配了调不通（异常）/ 熔断 open
    # 三条路都只挂队列（不产经验、不落库），接模型后 replay_pending 重放。
    # to_thread：挂起有文件写，不能阻塞代理事件循环。
    if not llm.model_available(store) or llm.circuit_open(store):
        await asyncio.to_thread(defer_to_replay, store, session_dict)
        return 0
    try:
        raw = await llm.call_model_async(store, [{"role": "user", "content": prompt}])
    except Exception as exc:
        logger.warning("复盘模型调用失败，挂起待重放: %s", exc)
        await asyncio.to_thread(defer_to_replay, store, session_dict)
        return 0
    try:
        candidates = llm.extract_json(raw)
    except ValueError as exc:
        # 解析失败与文件通道（scan.py:191-194）对齐——
        # 挂证据队列待重放。原来这里直接 return 0，调用方
        # （proxy on_session_end / hook _run_stop_review）随即 settle_reviewed，
        # 该会话从此永不重试，可蒸馏会话静默丢失。
        logger.warning("复盘输出无法解析，挂起待重放: %s", exc)
        await asyncio.to_thread(defer_to_replay, store, session_dict)
        return 0
    if not isinstance(candidates, list):
        # 同上：非 list 输出（模型跑偏）也是"跑了但没产出"，挂队列不静默
        logger.warning("复盘输出不是列表，挂起待重放")
        await asyncio.to_thread(defer_to_replay, store, session_dict)
        return 0

    added = 0        # 真正入库（含转避坑通道的 friction）
    drafted = 0      # 无原话证据，转草稿待用户确认
    rejected = 0     # 注意力闸判定为环境噪音/源码回声
    for cand in candidates[:10]:  # 单次上限，防失控
        rec = await asyncio.to_thread(_process_candidate, cand, session_dict, store)
        if rec is None:
            continue
        # 写入总闸：注意力闸（D1）→ 证据闸（D3）→ 合并落库（D4）。
        # commit_candidate 是唯一入口，三条候选通道都走它。
        _stored, route = await asyncio.to_thread(commit_candidate, rec, store)
        if route == "draft":
            drafted += 1
        elif route == "rejected":
            rejected += 1
        else:
            added += 1
    if added or drafted or rejected:
        tails = []
        if drafted:
            tails.append(f"{drafted} 条缺原话证据，转草稿待确认")
        if rejected:
            tails.append(f"{rejected} 条被判为环境噪音未入库")
        tail = "；".join(tails)
        if tail:
            tail = "（" + tail + "）"
        # 会话级 upsert（信息量控制·阀门一）：同一会话重复复盘只更新计数，不新增行
        store.upsert_review_node(
            session_dict.get("agent", "?"),
            session_dict.get("session_id", ""),
            added,
            f"复盘 {session_dict.get('agent', '?')} 会话 {str(session_dict.get('session_id', ''))[:12]}… "
            f"→ {trunk}/{category} 入库 {added} 条 [auto]{tail}",
        )
    return added
