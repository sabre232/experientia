"""T1 结构事实挖掘（经验链路修复方案）：确定性、零 LLM、零幻觉。

从落库事件行（capture/events.py 派生）里挖四类结构事实，产出 rule 源坑卡：
  retry_pair  同命令归一化后连败 ≥2 → 显式退出码 0 成功，参数变化即修复动作
  error_sig   同一归一化错误签名跨会话/高频次复现
  revert      同一文件编辑指纹 A→B→A 复原（改动被推翻）
  pivot       文件路径找不到 → 同文件名经扫描/换路径成功（失败后转向）

坑卡身份 = (agent, task, action) 恒定文本（跨会话合并进 append_experience
现有精确去重：count 复现计数 + seen_in 跨会话复现集，读取侧过 3 会话升
G=0.55 注入档）。task/action 是数据层指纹不是文案——模板用 ASCII 短语，
GUI 按 rule_kind 渲染平实名（防语言漂移击穿跨会话合并）；playbook/注入/
蒸馏素材等人可读场合一律用 rule_line_text() 模板句，指纹不外漏。

触发：run_scan 对新解析会话增量调用（与档 A 复盘同生命周期，每会话一次）；
全量重挖仅由迁移/回采脚本调用（seen_in 幂等合并，count 会随重复挖+1，
所以不做常态化全量）。
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from ..capture.events import command_key
from ..store.store import Store
from . import gsignal, value_gate

logger = logging.getLogger("experientia.distill.mining")

RULE_G = gsignal.RULE_SINGLE  # 恒 0.4：复现门之前不可注入（红线自动成立）

_NOT_FOUND_RE = re.compile(r"(no such file|not found|enoent|cannot find|不存在|找不到)", re.I)
_CMD_FAIL_MIN = 2          # 连败门槛：≥2 次失败后成功才算"改出来的"
_SIG_SESSION_MIN = 2       # 错误签名跨会话门槛
_SIG_COUNT_MIN = 3         # 或同签名累计次数门槛

_PATH_SEP_RE = re.compile(r"[\\/]+")


def _fpkey(path: str) -> str:
    """文件路径归一（大小写/分隔符折叠），只作分组键，不进展示文本。"""
    return _PATH_SEP_RE.sub("/", str(path or "")).lower().rstrip("/")


def _fname(path: str) -> str:
    p = _fpkey(path)
    return p.rsplit("/", 1)[-1] if p else ""


def _record_from(cand: dict, sess: dict) -> dict:
    # 价值闸门只对「错误签名卡」生效——retry_pair/pivot/revert 本身就是
    # "失败后改出来的做法"（教训本体），env/friction 噪音只从 error_sig 混进来。
    vclass = (value_gate.classify(str(cand.get("state", "")))
              if cand["rule_kind"] == "error_sig" else value_gate.LESSON)
    return {
        "task": cand["task"][:120],
        "state": cand.get("state", "")[:120],
        "action": cand["action"][:120],
        "outcome": cand.get("outcome", "")[:120],
        "G": RULE_G,
        "g_source": "rule",
        "rule_kind": cand["rule_kind"],
        "value_class": vclass,
        "corrected": False,
        "agent": sess.get("agent", "unknown"),
        "model": "",
        "session_id": str(sess.get("session_id", "")),
        "project": sess.get("project"),
        "trunk": sess.get("trunk") or "其他",
        "category": sess.get("category") or "未分类",
        "seen_in": [str(sess.get("session_id", ""))],
    }


def rule_line_text(exp: dict) -> str:
    """rule 坑卡 → 确定性模板句（方案）。

    落库 task/action 是跨会话合并用的稳定 ASCII 指纹，绝不能直接进
    playbook/注入（那是给 agent 读的"人话"）——展示与蒸馏素材统一走
    这里：按 rule_kind 组句，术语原样保留（surviving vocabulary）。"""
    kind = str(exp.get("rule_kind") or "")
    task = str(exp.get("task") or "")
    bare = task.split(":", 1)[-1].strip() if ":" in task else task
    state = str(exp.get("state") or "")
    if kind == "retry_pair":
        line = f"命令「{bare}」反复失败，改参重试后才通过"
        if state and state != "path-not-found":
            line += f"（常见报错：{state[:60]}）"
    elif kind == "error_sig":
        line = f"反复出现的报错「{state[:80] or bare}」——同类任务先查它"
    elif kind == "revert":
        line = f"对「{bare}」的改动被回滚推翻（A→B→A），该做法大概率是错路"
    elif kind == "pivot":
        line = f"「{bare}」按原路径找不到，换途径扫描才命中——先扫描再猜路径"
    else:
        line = bare or state
    return line[:140]


# ---------- 四类挖掘（单会话事件行 → 候选卡） ----------

def _mine_retry_pair(session: dict, events: list[dict]) -> list[dict]:
    """连败簇 → 其后的显式退出码成功（同键或前缀关系）＝改了参数才通。

    前缀关系覆盖最常见的两类修复：追加参数（加 --fix/换 flag）与删参数。
    只认带退出码铁证的配对（e 启发不进对，防误报）。"""
    coded = [(command_key(e.get("cmd") or ""), e) for e in events
             if e.get("cmd") and e.get("ex") is not None]
    fails: dict[str, list[dict]] = defaultdict(list)
    succs: list[tuple[str, dict]] = []
    for key, ev in coded:
        if len(key.strip()) < 4:
            continue  # 整条命令被掩码打光（纯路径/纯数字调用）：键无区分度，进对必假
        if ev.get("ex"):
            fails[key].append(ev)
        else:
            succs.append((key, ev))
    succs_t = [(k, str(e.get("t") or "")) for k, e in succs]
    out = []
    for key, seq in fails.items():
        if len(seq) < _CMD_FAIL_MIN:
            continue
        last_fail_t = str(seq[-1].get("t") or "")
        fixed = any(st > last_fail_t and (k == key or k.startswith(key + " ")
                                          or key.startswith(k + " "))
                    for k, st in succs_t)
        if not fixed:
            continue
        sig = next((f.get("sig", "") for f in reversed(seq) if f.get("sig")), "")
        out.append({
            "rule_kind": "retry_pair",
            "task": f"cmd:{key[:80]}",
            "state": sig or f"fails {len(seq)}x",
            "action": "fix:retry-with-changed-args",
            "outcome": "exit0",
        })
    return out


def _mine_error_sig(session: dict, events: list[dict]) -> list[dict]:
    """同错误签名在本会话内足够高频（跨会话门槛由合并后的 count/seen_in 承担）。"""
    counts: dict[str, int] = defaultdict(int)
    for ev in events:
        sig = ev.get("sig")
        if sig:
            counts[sig] += 1
    out = []
    for sig, n in counts.items():
        if n >= _SIG_COUNT_MIN:
            out.append({
                "rule_kind": "error_sig",
                "task": f"sig:{sig[:90]}",
                "state": sig[:120],
                "action": "recurring-error-signature",
                "outcome": "",
            })
    return out


def _mine_revert(session: dict, events: list[dict]) -> list[dict]:
    """同文件编辑指纹 A→B→A：改动被推翻（MSR'26 口径的 transcript 近似）。"""
    by_file: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for ev in events:
        f = ev.get("file")
        o, n = ev.get("o"), ev.get("n")
        if f and o and n:
            by_file[_fpkey(f)].append((o, n))
    out = []
    for fkey, edits in by_file.items():
        hit = False
        for i in range(2, len(edits) + 1):
            prev_o, prev_n = edits[i - 2]
            cur_o, cur_n = edits[i - 1]
            # 严格 A→B→A：前一次把 A 改成 B，后一次把 B 改回 A
            if cur_o == prev_n and cur_n == prev_o and prev_n != cur_n:
                hit = True
                break
        if hit and fkey:
            out.append({
                "rule_kind": "revert",
                "task": f"file:{_fname(fkey)[:80]}",
                "state": "",
                "action": "edit-reverted-A-B-A",
                "outcome": "",
            })
    return out


def _mine_pivot(session: dict, events: list[dict]) -> list[dict]:
    """路径落空后同文件名换途径成功（如 Glob 精确名未命中→扫描命中）。"""
    out, seen_file = [], set()
    for i, ev in enumerate(events):
        f = ev.get("file")
        if not f or ev.get("e") != 1:
            continue
        sig = ev.get("sig", "")
        if not _NOT_FOUND_RE.search(f"{sig} {f}"):
            continue
        name = _fpkey(f).rsplit("/", 1)[-1]
        if not name or name in seen_file:
            continue
        for later in events[i + 1:i + 7]:
            lf = later.get("file")
            if lf and _fpkey(lf).endswith("/" + name) and later.get("e") == 0:
                seen_file.add(name)
                out.append({
                    "rule_kind": "pivot",
                    "task": f"file:{name[:80]}",
                    "state": "path-not-found",
                    "action": "found-via-scatter-search",
                    "outcome": "",
                })
                break
    return out


# ---------- 编排 ----------

def mine_session_dicts(store: Store, session_dicts: list[dict]) -> int:
    """对给定会话的事件行跑四类挖掘并落坑卡。返回新落/合并的候选条数。

    每会话只挖一次（由调用方 run_scan 的 reviewed 台账保证）；异常单条跳过
    不中断（容错约定）。"""
    total = 0
    for sess in session_dicts:
        events = sess.get("events")
        if not isinstance(events, list) or not events:
            continue
        try:
            cands = []
            cands += _mine_retry_pair(sess, events)
            cands += _mine_error_sig(sess, events)
            cands += _mine_revert(sess, events)
            cands += _mine_pivot(sess, events)
        except Exception as exc:
            logger.warning("T1 挖掘跳过会话 %s: %s", sess.get("session_id", "?"), exc)
            continue
        for cand in cands[:8]:  # 单会话产出上限，防一次长会话刷屏
            try:
                rec = _record_from(cand, sess)
                if value_gate.is_suppressed(rec["value_class"]):
                    continue  # 环境抖动/源码回声：不是经验，落库前直接丢
                store.append_experience(rec)
                total += 1
            except Exception as exc:
                logger.warning("坑卡落库失败(%s): %s", cand.get("rule_kind"), exc)
    return total


def mine_all(store: Store) -> int:
    """全量重挖（仅迁移/回采脚本用——重复挖会推高 count，见模块 docstring）。

    除逐会话四类外，追加全局错误签名 pass：真机数据实证"每会话 ≥3 次"门槛
    会把跨会话高频坑（如 Edit 未先 Read x16 但每会话 1-2 次）整类挡掉——
    全局按 occurrences≥3 或跨 ≥2 会话聚类补卡，task 文本与单会话卡一致，
    经 append_experience 精确去重自动合并（seen_in 并集）。"""
    total = mine_session_dicts(store, store.list_sessions())
    stats: dict[str, dict] = {}
    for sess in store.list_sessions():
        sid = str(sess.get("session_id") or "")
        for ev in (sess.get("events") or []):
            sig = str(ev.get("sig") or "")
            if not sig:
                continue
            st = stats.setdefault(sig, {"n": 0, "sessions": [], "sess": sess})
            st["n"] += 1
            if sid and sid not in st["sessions"]:
                st["sessions"].append(sid)
    for sig, st in stats.items():
        if st["n"] < _SIG_COUNT_MIN and len(st["sessions"]) < _SIG_SESSION_MIN:
            continue
        sess = st["sess"]
        cand = {"rule_kind": "error_sig", "task": f"sig:{sig[:90]}",
                "state": sig[:120], "action": "recurring-error-signature",
                "outcome": ""}
        try:
            rec = _record_from(cand, sess)
            if value_gate.is_suppressed(rec["value_class"]):
                continue  # 全局 pass 同口径：env 噪音/源码回声不落库
            rec["seen_in"] = st["sessions"][:30]
            rec["count"] = max(st["n"], len(st["sessions"]))
            store.append_experience(rec)
            total += 1
        except Exception as exc:
            logger.warning("全局签名卡落库失败: %s", exc)
    return total


def rule_stats(store: Store) -> dict:
    """rule 坑卡按类型计数 + 可注入（复现升档后）数，供首屏洞察卡与统计盘。"""
    by_kind: dict[str, int] = defaultdict(int)
    injectable = 0
    for e in store.iter_experiences(include_distilled=True):
        if e.get("g_source") != "rule":
            continue
        by_kind[str(e.get("rule_kind") or "?")] += 1
        if gsignal.effective_g(e) >= gsignal.G_MIN_INJECT:
            injectable += 1
    return {"by_kind": dict(by_kind), "injectable": injectable,
            "sessions_pending": len(store.load_pending_reviews())}
