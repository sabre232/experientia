"""事件行派生（经验链路修复方案 R0/T1 共享底座，纯函数零 I/O）。

落库点（store.record_session）从归一化 messages 里派生紧凑「事件行」：
原始日志有数万级工具调用，但全量 messages 永不落库——
这里只留提炼挖掘所需的最小指纹：命令、文件、编辑指纹、退出码、错误签名。

事件行 schema（键名压短省字节）：
    {"t": ts, "tool": 工具名, "cmd": 命令原文(截断), "file": 文件路径(截断),
     "o": old 指纹10位, "n": new 指纹10位, "ex": 退出码|null,
     "e": 1=失败 0=成功, "sig": 错误签名归一行(截断)}
单会话字节预算 EVENTS_MAX_BYTES——超预算按信号价值取舍（错误/签名首现/
退出码铁证优先，重复成功聚合 rep 计数），绝不回退到存原文。
"""

from __future__ import annotations

import hashlib
import json
import re

EVENTS_MAX_BYTES = 8 * 1024   # 单会话事件行预算（config events.max_bytes 可覆盖）
_CMD_MAX = 160
_FILE_MAX = 200
_SIG_MAX = 120
_TOOL_MAX = 40

# 命令类参数的候选键（各家 agent 的 tool arguments 都在这几个名字里）
_CMD_KEYS = ("cmd", "command", "script", "shell", "code")
_FILE_KEYS = ("file_path", "path", "notebook_path", "target_file", "filePath")

# 退出码抽取（codex: "Process exited with code N"；claude Bash: "Exit code: N"）
_EXIT_RES = (
    re.compile(r"exited with code\s+(-?\d+)", re.I),
    re.compile(r"exit(?:ed)?\s+code:?\s*(-?\d+)", re.I),
    re.compile(r"\bexit\s*code\s*[:=]\s*(-?\d+)", re.I),
)

# 无退出码时的失败启发（宁误报不瞒报——挖掘侧要求配对有成功证据才出卡）
_FAIL_RE = re.compile(
    r"(traceback \(most recent call last\)|^\s*(error|fatal|exception)\b"
    r"|\berrno\s*\d+|error:|Error:|npm ERR|FAILED|failed:|permission denied"
    r"|no such file|not found|cannot find|unrecognized command)",
    re.M)
_OK_HINT_RE = re.compile(r"(process exited with code 0|exit code:?\s*0\b|"
                         r"^\s*(ok|success|done|passed)\b)", re.I | re.M)
# 状态回声行：退出码播报本身不是错误特征，不配当签名
_ECHO_RE = re.compile(r"^(process |command |script )?(completed|exited|finished"
                      r"|terminated)( with)? (exit )?code[:=]? ?-?\d*[.!]?(\s|$)", re.I)

# 错误签名归一：变量位一律打掉，同型报错跨会话可聚
_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\|/)[^\s'\"`]+")
_NUM_RE = re.compile(r"\d+")
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{6,}\b")
_WS_RE = re.compile(r"\s+")

_EDIT_OLD_KEYS = ("old_string", "old_str", "original_text", "oldText")
_EDIT_NEW_KEYS = ("new_string", "new_str", "new_text", "newText", "content", "file_content")


def normalize_error_line(text: str) -> str:
    """报错原文 → 归一签名（路径/数字/hex 打占位符，取首个含错字行，≤120 字）。"""
    if not text:
        return ""
    line = ""
    for cand in str(text).splitlines():
        s = cand.strip()
        if s and _FAIL_RE.search(s):
            line = s
            break
    if not line:
        # 无典型错字行 → 不产签名（旧版回退首行制造了 "Chunk ID: <h>" 这类
        # 垃圾聚类——真机数据实证，Sentry 口径：message 兜底都不如放弃）
        return ""
    line = _PATH_RE.sub("<p>", line)
    line = _HEX_RE.sub("<h>", line)
    line = _NUM_RE.sub("#", line)
    line = _WS_RE.sub(" ", line).strip()
    # 纯退出码回声（"Command completed with exit code 1" 等）：状态播报不是错误特征
    if _ECHO_RE.match(line):
        return ""
    # 信息量门槛（Drain3 防模板退化的 minimum information 口径）：
    # 掩码归一后仍要有 ≥2 个含字母的实义词元（<p>/<h>/# 不算）
    informative = [w for w in re.split(r"\s+", line)
                   if re.search(r"[A-Za-z\u4e00-\u9fff]", w)
                   and w not in ("<p>", "<h>", "error:", "Error:", "ERROR")]
    if len(informative) < 2:
        return ""
    return line[:_SIG_MAX]


def command_key(cmd: str) -> str:
    """命令 → 重试归一键：参数里的数字/路径/hex 打掉，大小写敏感（命令区分大小写）。"""
    if not cmd:
        return ""
    s = _PATH_RE.sub("<p>", str(cmd).strip())
    s = _HEX_RE.sub("<h>", s)
    s = _NUM_RE.sub("#", s)
    s = _WS_RE.sub(" ", s)
    return s[:_CMD_MAX]


def _fp(text) -> str:
    if text is None:
        return ""
    return hashlib.sha1(str(text).encode("utf-8", "replace")).hexdigest()[:10]


def _first(args: dict, keys: tuple) -> str:
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _parse_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
            # 少数 agent arguments 是 JSON 数组/字符串——原样带进 cmd
            return {"cmd": raw.strip()}
        except json.JSONDecodeError:
            return {"cmd": raw.strip()}
    return {}


def _classify_result(output: str) -> tuple[int | None, int]:
    """工具输出 → (退出码|None, e 失败标记)。"""
    text = str(output or "")
    for rx in _EXIT_RES:
        m = rx.search(text)
        if m:
            code = int(m.group(1))
            return code, 1 if code != 0 else 0
    if _OK_HINT_RE.search(text):
        return None, 0
    if _FAIL_RE.search(text):
        return None, 1
    return None, 0


def _aggregate_repeats(events: list[dict]) -> list[dict]:
    """连续同命令同结果的成功行聚合为一条 + rep 计数（重复成功无增量）。"""
    out: list[dict] = []
    for ev in events:
        prev = out[-1] if out else None
        if (prev is not None and prev.get("e") == 0 and ev.get("e") == 0
                and prev.get("tool") == ev.get("tool")
                and prev.get("cmd") == ev.get("cmd") and ev.get("cmd")):
            prev["rep"] = int(prev.get("rep", 1)) + 1
            prev["t"] = ev.get("t") or prev.get("t")  # 时间推进到最后一次
            continue
        out.append(dict(ev))
    return out


def _value_score(ev: dict, idx: int, total: int, seen_sig: set) -> float:
    """信号价值分：错误行 > 签名首现 > 退出码铁证 > 普通成功（新近微权重）。"""
    s = idx / max(total, 1)
    if ev.get("e"):
        s += 8.0
    sig = str(ev.get("sig") or "")
    if sig and sig not in seen_sig:
        s += 4.0
    if ev.get("ex") is not None:
        s += 2.0
    return s


def _trim_to_budget(events: list[dict], budget: int) -> list[dict]:
    """超预算按价值分从低到高淘汰（保持时间序），至少保 1 条。"""
    def size(evs):
        return len(json.dumps(evs, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")) + 2
    evs = list(events)
    while size(evs) > budget and len(evs) > 1:
        seen: set = set()
        scored = []
        for i, ev in enumerate(evs):
            scored.append((_value_score(ev, i, len(evs), seen), i))
            sig = str(ev.get("sig") or "")
            if sig:
                seen.add(sig)
        scored.sort(key=lambda x: (x[0], x[1]))   # 最低分、最旧的先淘汰
        evs.pop(scored[0][1])
    return evs


def derive_events(messages: list[dict], max_bytes: int = EVENTS_MAX_BYTES) -> list[dict]:
    """归一化 messages（dict 形态，含 tool_use/tool_result）→ 事件行列表。

    预算内按信号价值取舍（错误/签名首现/退出码铁证优先，重复成功聚合
    rep 计数），早期踩坑不被挤掉。异常静默跳过单条——事件行是增强数据，
    绝不允许把正常落库流程带崩。"""
    if not messages:
        return []
    results: dict[str, tuple[str, str]] = {}
    for m in messages:
        tr = m.get("tool_result") if isinstance(m, dict) else None
        if isinstance(tr, dict):
            results[str(tr.get("call_id") or "")] = (
                str(tr.get("output") or "")[:2000], str(m.get("ts") or ""))
    events: list[dict] = []
    try:
        for m in messages:
            if not isinstance(m, dict):
                continue
            tu = m.get("tool_use")
            if not isinstance(tu, dict):
                continue
            name = str(tu.get("name") or "")[:_TOOL_MAX]
            args = _parse_args(tu.get("arguments"))
            out, rts = results.get(str(tu.get("call_id") or ""), ("", ""))
            ev: dict = {"t": str(m.get("ts") or rts or "")[:20], "tool": name}
            cmd = _first(args, _CMD_KEYS)
            if cmd:
                ev["cmd"] = cmd[:_CMD_MAX]
            fp = _first(args, _FILE_KEYS)
            if fp:
                ev["file"] = fp[:_FILE_MAX]
            old = _first(args, _EDIT_OLD_KEYS)
            new = _first(args, _EDIT_NEW_KEYS)
            if old:
                ev["o"] = _fp(old)
            if new and ("o" in ev or fp):
                ev["n"] = _fp(new)
            if out:
                ex, e = _classify_result(out)
                if ex is not None:
                    ev["ex"] = ex
                ev["e"] = e
                if e:
                    sig = normalize_error_line(out)
                    if sig:
                        ev["sig"] = sig
            events.append(ev)
    except Exception:
        # 派生失败＝本轮没有事件行，主流程照常（增强层不伤人）
        return []
    # 预算：先聚合重复成功
    # （同命令连续 e=0 无信息增量 → 一条 + rep 计数），超预算再按信号
    # 价值从低到高淘汰——错误行、每种签名首条、带退出码的铁证行优先保，
    # 早期踩坑不再被"一刀切保尾"挤掉
    budget = max(256, int(max_bytes))
    events = _aggregate_repeats(events)
    return _trim_to_budget(events, budget)
