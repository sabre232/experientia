"""注入组装（产品文档 //）。

两个独立通道：经验注入（预算默认 800 token）+ 规则通道（独立预算 400 token）。
优先级：用户当前消息 > 规则（硬钩子 > 普通规则）> 经验。
压缩走 compaction ladder 两级：预算分层截断（零成本）→ 蒸馏时预压缩。
不设"注入时 LLM 摘要"（判定为过度设计，勿在热路径调模型）；两级仍超预算
时按分层截断到底。

稳定格式原则（防缓存失效）：注入块结构固定
（规则 → 偏好 → 失败模式 → 标准流程，顺序不变），条目按文件顺序（稳定）。

用户覆盖层：条目 id（文本的 sha1 前缀）→ {enabled, text}。
覆盖层与资产文件解耦：蒸馏不动覆盖层；条目被淘汰后覆盖 stale（预览页提示一次）。
"""

from __future__ import annotations

import hashlib
import logging
import re

logger = logging.getLogger("experientia.proxy.inject")

# normalize_rule 定义在 store（M2，消反向依赖），测试直接 import store.normalize_rule。
# 本文件不再 re-export（D-02）

INJECTION_MARKER = "<!-- injected by experientia v1 -->"
EXPERIENCE_BUDGET_TOKENS = 800  #
RULES_BUDGET_TOKENS = 400  #

# ---------- 判定键（资产文件里的机器标记，不随语言走——ASCII 常量，7 语统一） ----------
# 2026-09 R6 判定键剥离：旧版是中文键，会"本地化破坏识别 + 非中文用户看不懂"，
# 统一为 ASCII 键；旧资产读取时用 normalize_marks 归一化兼容（存量不丢）。
FAILURE_SOLID_MARK = "[Solidified]"    # 失败模式「已固化」（计数 + 复现双门都过）
FAILURE_PENDING_MARK = "[Pending]"     # 失败模式「待验证」（≥3 次但复现未过，不注入）
FAILURE_WATCH_MARK = "[Watching]"      # 失败模式「观察中」（<3 次，只记录不注入）
USER_CONFIRM_MARK = "[UserConfirmed]"  # 偏好行尾「用户确认」标记（受保护不覆盖）
NEW_POINT_MARK = "[NewPoint]"          # 成功要点「新要点·待复现」（单次来源，注入权重降半）

# 旧版中文判定键（2026-09 前的资产格式），读取时归一化到 ASCII 键
_MARK_LEGACY = {
    "[已固化]": FAILURE_SOLID_MARK,
    "[观察中]": FAILURE_WATCH_MARK,
    "（待验证）": FAILURE_PENDING_MARK,
    "（用户确认）": USER_CONFIRM_MARK,
    "（新要点·待复现）": NEW_POINT_MARK,
}


def normalize_marks(text: str) -> str:
    """把旧版中文判定键归一化为 ASCII 键（存量数据兼容；新文本原样返回）。"""
    for old, new in _MARK_LEGACY.items():
        text = text.replace(old, new)
    return text


def estimate_tokens(text: str) -> int:
    """轻量 token 估算：CJK 每字约 1 token，其余约 4 字符 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff")
    return cjk + (len(text) - cjk) // 4 + 1


# ---------- playbook 解析（章节标题稳定，/） ----------

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)


def parse_playbook(md: str) -> dict[str, str]:
    """把 playbook md 切成 {章节名: 内容}。"""
    sections: dict[str, str] = {}
    if not md:
        return sections
    matches = list(_SECTION_RE.finditer(md))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        sections[m.group(1)] = md[start:end].strip()
    return sections


def failure_mode_entries(sections: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """返回 (已固化条目, 待验证条目, 观察中条目)（三态）。

    条目格式（落盘规则，R6 起用 ASCII 判定键，兼容旧中文键）：
      - [Solidified] 纯情绪文案点击率低（出现 4 次）   → 会注入
      - [Pending] 标题超 20 字会被截断（出现 3 次）    → 待验证，不注入
      - [Watching] CTA 放正文最末尾（出现 2 次）       → 观察中，不注入

    只读 playbook 落盘标记；三态的实时复算（计数/复现/过期）在
    distill.gate.failure_mode_states（门在调用方，审计口径）。
    """
    solid, pending, watching = [], [], []
    for raw in sections.get("失败模式", "").splitlines():
        line = normalize_marks(raw.strip())
        if not line.startswith("-"):
            continue
        if FAILURE_SOLID_MARK in line:
            solid.append(line.lstrip("- ").replace(FAILURE_SOLID_MARK, "").strip())
        elif FAILURE_PENDING_MARK in line:
            pending.append(line.lstrip("- ").replace(FAILURE_PENDING_MARK, "").strip())
        elif FAILURE_WATCH_MARK in line:
            watching.append(line.lstrip("- ").replace(FAILURE_WATCH_MARK, "").strip())
    return solid, pending, watching


# ---------- 条目化（覆盖层 /  预览的公共基础） ----------

def _item_id(kind: str, trunk: str, category: str, text: str) -> str:
    """条目 id = 文本的 sha1 前缀（蒸馏重写后文本变化 → 旧 id 失效 = stale）。"""
    raw = f"{kind}|{trunk}|{category}|{text}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def iter_injection_items(store, trunk: str, category: str) -> list[dict]:
    """注入条目清单（顺序即注入顺序：偏好 → 失败模式[仅固化] → 纠正补丁 → 标准流程 → 经验要点）。

    每项 {id, kind, section, text}；text 为行级内容（bullet 去前缀，流程行原样）。
    W3-02：有 `_fixes.md` 时坑与补丁成对注入（补丁紧跟坑之后，预算内优先保留）。
     成功要点复现门：[NewPoint] 行（单次来源）带 new_point=True——
    注入时排在已复现要点之后、成本按 2 倍计（权重降半）。
    """
    items: list[dict] = []
    _seen: set[tuple[str, str]] = set()  # L-N8: 去重跟踪
    # 回炉状态：受限/移出条目——检索层只读，评估写在维护层
    try:
        _st = (store.load_injection_hits().get(f"{trunk}/{category}") or {})
        _st = _st.get("items") or {}
    except Exception:
        _st = {}

    def _add(kind: str, section: str, text: str, new_point: bool = False):
        text = text.strip()
        if not text or text in ("（无）", "(无)"):
            return
        key = (section, text)
        if key in _seen:  # L-N8: 跳过重复内容，节省 token 预算
            return
        _seen.add(key)
        item = {"id": _item_id(kind, trunk, category, text),
                "kind": kind, "section": section, "text": text}
        if new_point:
            item["new_point"] = True
        st = _st.get(item["id"])
        if isinstance(st, dict):
            # 三因子排序与 probation 行为的数据源（-P1-2/P2-6）
            item["last"] = st.get("last")
            item["count"] = int(st.get("count") or 0)
            item["importance"] = int(st.get("importance") or 0)
            if st.get("probation_left") is not None:
                item["probation_left"] = int(st["probation_left"])
            if st.get("restricted"):
                item["restricted"] = True
            if st.get("excluded"):
                item["excluded"] = True
        items.append(item)

    prefs = (store.read_preferences(trunk) or "").strip()
    for line in prefs.splitlines():
        line = line.strip()
        if line.startswith("-"):
            _add("pref", "你的偏好", line.lstrip("- ").strip())

    sections = parse_playbook(store.read_skill(trunk, category) or "")
    for raw in sections.get("失败模式", "").splitlines():
        line = normalize_marks(raw.strip())
        if line.startswith(f"- {FAILURE_SOLID_MARK}"):
            # removeprefix 精确剥前缀——此前 lstrip 按
            # 字符集合剥离，英文正文以标记字符开头（如 "insufficient…"）
            # 会被连续吃掉首字符，注入内容损坏
            _add("failure", "失败模式",
                 line.removeprefix(f"- {FAILURE_SOLID_MARK}").strip())
    fixes_md = (store.read_fixes(trunk, category) or "").strip()
    if fixes_md:
        for line in parse_playbook(fixes_md).get("纠正补丁", "").splitlines():
            line = line.strip()
            if line.startswith("-"):
                _add("fix", f"纠正补丁：{category}", line.lstrip("- ").strip())
    for line in sections.get("标准流程", "").splitlines():
        line = line.strip()
        if line:
            _add("flow", f"标准流程：{category}", line)
    for line in sections.get("成功要点", "").splitlines():
        line = normalize_marks(line.strip())
        if line.startswith("-"):
            body = line.lstrip("- ").strip()
            new_point = NEW_POINT_MARK in body
            _add("insight", f"经验要点：{category}",
                 body.replace(NEW_POINT_MARK, "").strip(), new_point=new_point)
    return items


def _section_of(kind: str, category: str) -> str:
    return {"pref": "你的偏好", "failure": "失败模式",
            "fix": f"纠正补丁：{category}",
            "flow": f"标准流程：{category}", "insight": f"经验要点：{category}"}[kind]


# ---------- 经验注入块组装 ----------

def assemble_experience_block(
    store,
    trunk: str,
    category: str,
    budget: int = EXPERIENCE_BUDGET_TOKENS,
    overrides: dict | None = None,
    task_text: str | None = None,
) -> str:
    """按注入预算顺序组装（预算分层截断）。

    1. 偏好画像（最短、每次必用，最先保）
    2. 失败模式（只注入已固化条目，一行"什么不能做+为什么"；待验证不注入）
    3. 纠正补丁（W3-02：用户纠正过的事比坑本身更有价值，预算内优先于流程保留）
    4. SOP 标准流程（超预算时按行截短）
    5. 经验洞察（成功要点，兜底，超预算直接不注入；新要点·待复现排最后且
       成本按 2 倍计 = 注入权重降半）

    覆盖层：条目被关闭 → 跳过；用户改过措辞 → 用覆盖文本。
    """
    if overrides is None:
        overrides = store.load_overrides()
    return _build_experience(store, trunk, category, budget, overrides,
                             task_text)[0]


def selected_experience_items(
    store,
    trunk: str,
    category: str,
    budget: int = EXPERIENCE_BUDGET_TOKENS,
    overrides: dict | None = None,
    task_text: str | None = None,
) -> list[dict]:
    """本次真正进入注入块的经验条目（条目级命中反馈的数据源）。

    与 assemble_experience_block 走同一套预算挑选逻辑，返回入选条目
    [{id, kind, section, text}]——第⑤环拿它当佐证/反驳的锚点，
    老化第一钟（距上次注入命中 ≥30/90 天）也以此为锚。无条目时返回 []。
    """
    if overrides is None:
        overrides = store.load_overrides()
    return _build_experience(store, trunk, category, budget, overrides,
                             task_text)[1]


def _rank_select(pairs: list[tuple[dict, str]], task_text: str | None,
                 top_k: int) -> list[tuple[dict, str]]:
    """三因子排序（Generative Agents recency×importance×relevance，-P1-2）。

    只在真实注入路径（带当前任务文本）生效——预览/无 task_text 保持文件序
    （稳定格式原则，防缓存抖动）。relevance = 任务词在条目文本的命中率；
    recency = 上次被用天数衰减（从未注入 = 中性 0.5）；importance = 条目自评分。
    排完按 inject.top_k 截断：一节的坑再多，注入也只带最相关的 k 条。"""
    if not task_text or not pairs:
        return pairs
    import datetime as _dt
    import time

    from .detect import _token_set

    q = _token_set(task_text)
    now = time.time()

    def _score(pair: tuple[dict, str]) -> float:
        from ..time_util import parse_ts

        it, text = pair
        tok = _token_set(text)
        rel = (len(tok & q) / len(q)) if q and tok else 0.0
        last = str(it.get("last") or "")
        rec = 0.5
        if last:
            t = parse_ts(last)
            if t is None:
                rec = 0.3
            else:
                days = max(0.0, (now - t.timestamp()) / 86400)
                rec = 1.0 / (1.0 + days)
        try:
            imp = min(1.0, int(it.get("importance") or 0) / 10.0)
        except (TypeError, ValueError):
            imp = 0.0
        imp = imp if imp > 0 else 0.4
        return 0.5 * rel + 0.3 * rec + 0.2 * imp

    ranked = sorted(pairs, key=_score, reverse=True)
    return ranked[:max(1, int(top_k))]


def _build_experience(store, trunk, category, budget, overrides, task_text=None):
    """组装文本 + 选中条目一次算好，保证注入记录与预览同一份口径。

    task_text 在场（真实注入）→ 每节先按三因子排序再截 top_k；
    缺席（预览）→ 文件序原样，与稳定格式原则一致。"""
    from ..config_schema import numeric
    top_k = int(numeric(store.load_config(), "inject.top_k"))
    items = iter_injection_items(store, trunk, category)
    regular: list[tuple[dict, str]] = []
    restricted: dict[str, list[tuple[dict, str]]] = {}
    for it in items:
        ov = overrides.get(it["id"]) or {}
        if ov.get("enabled") is False:
            continue
        text = ov.get("text") or it["text"]
        if it.get("excluded"):
            continue  # 回炉移出：本条不再注入（经验仍留库，证真后回归）
        if it.get("restricted"):
            restricted.setdefault(it["kind"], []).append((it, text))
        else:
            regular.append((it, text))
    if not regular and not restricted:
        return "", []

    parts: list[tuple[str, int, list[tuple[dict, str]]]] = []
    for kind in ("pref", "failure", "fix", "flow", "insight"):
        eff = [(it, text) for it, text in regular if it["kind"] == kind]
        if not eff:
            continue
        eff = _rank_select(eff, task_text, top_k)  # -P1-2 三因子+top_k
        if kind == "insight":
            confirmed = [x for x in eff if not x[0].get("new_point")]
            fresh = [x for x in eff if x[0].get("new_point")]
            if confirmed:
                part = f"[{_section_of(kind, category)}]\n" + \
                    "\n".join(t for _, t in confirmed)
                parts.append((part, estimate_tokens(part), confirmed))
            if fresh:  # 新要点·待复现：独立块排最后，成本 ×2（权重降半）
                part = (f"[{_section_of(kind, category)}·新要点·待复现]\n"
                        + "\n".join(t for _, t in fresh))
                parts.append((part, 2 * estimate_tokens(part), fresh))
        else:
            texts = [t for _, t in eff]
            if kind == "flow":
                part = f"[{_section_of(kind, category)}]\n" + "\n".join(texts)
            else:
                part = f"[{_section_of(kind, category)}]\n" + \
                    "\n".join(f"- {t}" for t in texts)
            parts.append((part, estimate_tokens(part), eff))

    # 回炉受限：排在最末、成本 ×2 → 预算紧张时先被截掉（注入权重降半）
    for kind in ("pref", "failure", "fix", "flow", "insight"):
        grp = restricted.get(kind)
        if not grp:
            continue
        section = _section_of(kind, category)
        texts = [t for _, t in grp]
        part = f"[{section}·受限]\n" + \
            ("\n".join(texts)
             if kind == "flow" else "\n".join(f"- {t}" for t in texts))
        parts.append((part, 2 * estimate_tokens(part), grp))

    block_lines: list[str] = [INJECTION_MARKER]
    total = 0
    kept: list[int] = []
    for idx, (part, cost, _its) in enumerate(parts):  # 分层截断：先保 1/2，再 3，最后 4
        if total + cost > budget and kept:
            continue
        block_lines.append(part)
        total += cost
        kept.append(idx)
    if not kept and parts:
        block_lines.append(_truncate_to_tokens(parts[0][0], budget))

    selected: list[dict] = []
    for idx in kept:
        for it, text in parts[idx][2]:
            selected.append({"id": it["id"], "kind": it["kind"],
                             "section": it.get("section") or "", "text": text})
    return "\n\n".join(block_lines), selected


def injection_preview(store, trunk: str, category: str,
                      budget: int = EXPERIENCE_BUDGET_TOKENS) -> dict:
    """「模型会看到什么」预览数据：逐条目开关/覆盖状态 + 预算占用。"""
    overrides = store.load_overrides()
    items = []
    for it in iter_injection_items(store, trunk, category):
        ov = overrides.get(it["id"]) or {}
        enabled = ov.get("enabled") is not False
        text = ov.get("text") or it["text"]
        tokens = estimate_tokens(text)
        items.append({
            **it,
            "enabled": enabled,
            "overridden": bool(ov.get("text")),
            "effective_text": text,
            "tokens": tokens,
        })
    total = sum(it["tokens"] for it in items if it["enabled"])
    return {"trunk": trunk, "category": category, "budget": budget,
            "used": total, "items": items,
            "stale_overrides": stale_override_ids(store)}


def stale_override_ids(store) -> list[str]:
    """覆盖层里指向已淘汰条目的 id（条目升级淘汰后覆盖自动失效）。"""
    overrides = store.load_overrides()
    if not overrides:
        return []
    live: set[str] = set()
    for s in store.list_skills():
        live.update(it["id"] for it in
                    iter_injection_items(store, s["trunk"], s["category"]))
    for trunk in store.list_preference_trunks():
        live.update(it["id"] for it in
                    iter_injection_items(store, trunk, "未分类"))
    return sorted(oid for oid in overrides if oid not in live)


def _truncate_to_tokens(text: str, budget: int) -> str:
    # 按行截断（CJK 每字约 1 token 估算）
    lines = text.splitlines()
    out: list[str] = []
    total = 0
    for line in lines:
        cost = estimate_tokens(line)
        if total + cost > budget:
            break
        out.append(line)
        total += cost
    return "\n".join(out)


# ---------- 规则通道（+ H-A0 工具范围 + H-O1 文件范围） ----------

def _glob_match(pattern: str, path: str) -> bool:
    """文件范围 glob 匹配（H-O1）。fnmatch 语义（`**` 等价 `*`，跨目录匹配），
    与 Cursor globs 的用户预期一致；pattern/path 统一 `/` 分隔、大小写敏感。"""
    import fnmatch

    return fnmatch.fnmatchcase(path.replace("\\", "/"), pattern.replace("\\", "/"))


def load_rules(store) -> list[dict]:
    """读规则（唯一实现已下沉 store.load_rules，M2）：模板规则优先读 md
    （权威来源，用户改完文件即生效），返回前 H-A0 归一化。

    保留为薄包装：注入路径（assemble_rules_block）继续调它，落盘读全部收口
    到 store 层，不再与 store 双实现分叉。
    """
    return store.load_rules()


def _rule_matches_agent(rule: dict, agent: str) -> bool:
    """工具范围过滤（H-A0，方案 /）：
    缺省/["*"] = 全部工具；指定列表 = 仅对应工具；[]（未配装）= 任何工具都不注入；
    agent == "unknown" 时只放行 ["*"] 全局规则（宁缺毋滥，避免把"只给 A 工具"的规则错发给别的工具）。
    """
    agents = rule.get("agents")
    if agents is None:
        agents = ["*"]
    if "*" in agents:
        return True
    if agent == "unknown":
        return False
    return agent in agents


def _rule_injection_text(rule: dict) -> str:
    """H-O3 反例引导：注入文本 = 应当（text）+ 绝不（donts 列表）。

    donts 是独立字段（编辑器两栏输入 / 模板 frontmatter）；没有 donts 的规则
    注入文本不变（向后兼容旧 rules.json）。"""
    text = (rule.get("text") or "").strip()
    donts = [str(d).strip() for d in (rule.get("donts") or []) if str(d).strip()]
    if not donts:
        return text
    dont_block = "绝不：\n" + "\n".join(f"- {d}" for d in donts)
    return f"{text}\n{dont_block}" if text else dont_block


def _rule_brief(rule: dict) -> str:
    """智能应用（文档默认档）注入形态：只给描述，agent 判断相关才用。

    名字 + 正文首行截断——完整规则文本的注入成本由模型"判断相关"后承担
    （v1 近似：模型看到描述自行决定用不用，不为每条规则加模型调用）。
    """
    name = str(rule.get("name") or "").strip()
    lines = [ln.strip() for ln in str(rule.get("text") or "").strip().splitlines() if ln.strip()]
    body = lines[0][:80] if lines else ""
    if name and body:
        return f"{name}：{body}"
    return body or name


def _rule_mention_terms(rule: dict) -> list[str]:
    """手动触发（我提及时才用）的判定词：keyword > 规则名（用户最可能提名字）。"""
    terms: list[str] = []
    for v in (str(rule.get("keyword") or "").strip(), str(rule.get("name") or "").strip()):
        if v and v not in terms:
            terms.append(v)
    return terms


def _rule_matches_mention(rule: dict, user_content: str) -> bool:
    if not user_content:
        return False
    return any(t in user_content for t in _rule_mention_terms(rule))


def _rule_matches_files(rule: dict, files: list[str] | None) -> bool:
    """文件范围过滤（H-O1）：scope=glob 的规则仅在任务文件命中 globs 时注入；
    无文件上下文（files 为 None/[]）不注入——glob 规则本质是"文件驱动"。"""
    if rule.get("scope") != "glob":
        return True
    globs = rule.get("globs") or []
    if not globs or not files:
        return False
    return any(_glob_match(g, f) for g in globs for f in files)


# H-O1 v1 文件上下文：从用户当前消息里抽路径样 token（相对路径 / 绝对路径 / 盘符路径，
# 末段必须带扩展名）。只做 glob 规则过滤，抽不到就视为无文件上下文。
_FILE_REF_RE = re.compile(
    r"(?:[A-Za-z]:)?[A-Za-z0-9_@.\-\u4e00-\u9fff]*"
    r"(?:[/\\][A-Za-z0-9_@.\-\u4e00-\u9fff]+){1,12}\.[A-Za-z0-9]{1,8}"
)


def extract_file_context(text: str) -> list[str]:
    """从消息文本提取"当前任务文件"上下文（H-O1 v1）。

    返回去重、`/` 归一化后的路径列表（≤50）。只认带目录分隔符 + 扩展名的 token，
    避免把 "3.14" / "v1.2" 之类的普通词误当文件。
    """
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _FILE_REF_RE.finditer(text[:4000]):
        p = m.group(0).replace("\\", "/")
        if p not in seen:
            seen.add(p)
            out.append(p)
        if len(out) >= 50:
            break
    return out


def _filter_rules(rules: list[dict], user_content: str, agent: str,
                   files: list[str] | None) -> tuple[list[tuple[str, str]], list[tuple[str, str | None]]]:
    """按启用/工具/文件/触发方式过滤规则，返回 (hard_rules, normal_rules)。

    每项 = (注入文本, 规则 id 或 None（smart 不记命中）)。
    """
    hard: list[tuple[str, str]] = []
    normal: list[tuple[str, str | None]] = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if not _rule_matches_agent(rule, agent):
            continue
        if not _rule_matches_files(rule, files):
            continue
        text = _rule_injection_text(rule)
        if not text:
            continue
        trigger = rule.get("trigger", "always")
        if trigger == "hard-hook":
            hard.append((text, str(rule.get("id", ""))))
        elif trigger == "keyword":
            kw = str(rule.get("keyword") or "").strip()
            if kw and kw in user_content:
                normal.append((text, str(rule.get("id", ""))))
        elif trigger == "manual":
            if _rule_matches_mention(rule, user_content):
                normal.append((text, str(rule.get("id", ""))))
        elif trigger == "smart":
            brief = _rule_brief(rule)
            if brief:
                normal.append((brief, None))  # None = smart 不记命中
        else:  # always
            normal.append((text, str(rule.get("id", ""))))
    return hard, normal


def _build_rule_block(hard: list[tuple[str, str]], normal: list[tuple[str, str | None]],
                       budget: int) -> tuple[str, list[str]]:
    """从过滤结果组装注入块 + 命中 id 列表。

    硬钩子不受预算限制；普通规则按 token 估算截短，被截掉的规则不记命中。
    """
    hard_texts = [t for t, _ in hard]
    hard_ids = [rid for _, rid in hard]
    normal_texts = [t for t, _ in normal]
    normal_ids = [rid for _, rid in normal]

    parts: list[str] = []
    if hard_texts:
        parts.append("[硬钩子规则（每次必须遵守）]\n" + "\n".join(hard_texts))
    if normal_texts:
        block = "\n".join(normal_texts)
        hit_ids = [rid for rid in normal_ids if rid is not None]
        if estimate_tokens(block) > budget:
            out, total, hit_ids = [], 0, []
            for text_, rid in zip(normal_texts, normal_ids):
                cost = estimate_tokens(text_)
                if total + cost > budget:
                    break
                out.append(text_)
                total += cost
                if rid is not None:
                    hit_ids.append(rid)
            block = "\n".join(out)
        parts.append("[规则]\n" + block)
    else:
        hit_ids = []
    return "\n\n".join(parts), hard_ids + hit_ids


def assemble_rules_block(
    store,
    user_content: str = "",
    budget: int = RULES_BUDGET_TOKENS,
    agent: str = "unknown",
    files: list[str] | None = None,
) -> str:
    """组装规则注入块。

    硬钩子规则：每次请求重注入、不受预算限制（——对抗规则稀释与注意力衰减）。
    普通规则：独立预算，按一直生效 > 智能应用截短。
    生效方式五档：一直生效=全文 / 硬钩子=每次重注入 /
    智能应用=只给描述（agent 判断相关才用）/ 手动=当前消息命中 keyword 或
    规则名才注入 / 关键词（keyword 字段，旧数据兼容）=关键词命中才注入。
    工具范围（H-A0）：按 agent 过滤（见 _rule_matches_agent）。
    文件范围（H-O1）：scope=glob 按 files 过滤（见 _rule_matches_files）。
    命中追踪（H-O2）：真正进入注入块的规则记一次命中（预算截短掉的
    不算）；预览通道不走此函数，不污染计数。
    """
    rules = load_rules(store)
    hard, normal = _filter_rules(rules, user_content, agent, files)
    block, all_ids = _build_rule_block(hard, normal, budget)
    if not block:
        return ""
    try:
        store.record_rule_hits(all_ids)
    except Exception as exc:
        # 命中计数落盘失败不该挡住注入（保守方向正确），
        # 但此前完全静默——计数丢数据没人知道，这里补一条 debug。
        logger.debug("规则命中计数落盘失败（不影响本次注入）: %s", exc)
    return block


# ---------- 应用到请求体 ----------

def apply_injection_openai(body: dict, block: str) -> dict:
    """OpenAI 兼容：messages 头部 prepend 一条 system。

    已有 system → 合并进其末尾（保持前缀稳定，最大化 prompt cache 命中）。
    """
    if not block:
        return body
    body = dict(body)
    messages = list(body.get("messages") or [])
    system_content = block
    if messages and messages[0].get("role") == "system":
        old = messages[0].get("content")
        if isinstance(old, str):
            system_content = old + "\n\n" + block
        else:
            system_content = (old or []) + [{"type": "text", "text": block}]
        messages[0] = {**messages[0], "content": system_content}
    else:
        messages.insert(0, {"role": "system", "content": block})
    body["messages"] = messages
    return body


def apply_injection_anthropic(body: dict, block: str) -> dict:
    """Anthropic 原生：并入顶层 system 字段（字符串或 content blocks）。"""
    if not block:
        return body
    body = dict(body)
    system = body.get("system")
    if isinstance(system, str):
        body["system"] = system + "\n\n" + block
    elif isinstance(system, list):
        body["system"] = system + [{"type": "text", "text": block}]
    else:
        body["system"] = block
    return body
