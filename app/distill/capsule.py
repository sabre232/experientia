"""有上限上下文胶囊（P0-1，借鉴 phsanqi/memhub 的 Context Capsule，对应纪律 D2/D7）。

回答一个问题：**给定 trunk/category，用多少 token、带哪些条目、以什么顺序**。

与 `app/proxy/inject.py` 的分工：
- `inject` 服务**推送**通道（代理转发 / hook 回灌），产出塞进请求体的文本块；
- 本模块服务**按需召回**通道（MCP 等拉取方式），产出结构化条目 + 组装文本，
  每条带 id，供调用方溯源。

两者共用同一份条目来源（`inject.iter_injection_items`）与同一套口径，保证
"预览看到的 = MCP 召回到的"，不会两条通道各报各的数：
- 覆盖层（用户关掉 / 改过措辞）——`load_overrides`
- 回炉移出条目不召回——`excluded`
- 受限条目排最后——`restricted`
- 新要点·待复现权重降半（成本 ×2）——`new_point`

两个**有意为之**的口径差：
1. 新要点/受限的降权按**条目**计（inject 按块计）。召回是逐条消费的，
   按条计粒度更细、预算更省；代价是两者在极端边界上的截断结果可能差几条。
2. 召回文本不带 `INJECTION_MARKER`——那标记是给推送通道识别自己人用的，
   召回出去的内容不需要它。

纪律：
- D2 归位——层序常量 `LAYER_ORDER` / `LAYER_WEIGHT` 是唯一权威；
- D7 取用——输出必须封顶（`budget`），每条带来源 id，`G<0.5` 永不进入胶囊
  （经验侧 G 过滤在 `experience` 检索路径，本模块只重组已蒸馏资产）。
"""

from __future__ import annotations

import logging

from ..proxy import inject as _inject
from . import layers as _layers
from .gsignal import G_MIN_INJECT

logger = logging.getLogger("experientia.distill.capsule")

# ---------- 层序（D2：唯一权威在 app/distill/layers.py，改那里） ----------
LAYER_ORDER = tuple(_layers.KIND_LAYER[k] for k in
                    ("pref", "failure", "fix", "flow", "insight")
                    if k in _layers.KIND_LAYER)
# 注入链路的 kind → 层权重；intention不在此表——它只在显式开启时作为
# 最低权重尾层追加，绝不挤占 L3/L5 的位置。
LAYER_WEIGHT = {k: _layers.weight_of_layer(_layers.layer_of_kind(k))
                for k in ("pref", "failure", "fix", "flow", "insight")}
DEFAULT_BUDGET_TOKENS = 800
FALLBACK_TRUNK = "其他"
FALLBACK_CATEGORY = "未分类"

# 补捞（P1-3）：首轮太薄时放宽一层再捞一轮。三条硬约束——
# ① 最多两轮（首轮 + 一次补捞），共用一个预算；
# ② 只补 L2 经验（不跨类别乱捞：注入胶囊是给 agent 的工作记忆，
# 塞进别的类别的方法卡比不塞更糟）；
# ③ 被截断（候选比预算多）时不补——那种情况不缺料，缺的是预算。
REFILL_MIN_ITEMS = 2
REFILL_MAX_EXPS = 3


def _layer_weight(kind: str) -> float:
    """kind → 层权重（D2：唯一权威在 layers.py）。

    未在 `KIND_LAYER` 登记的 kind 按 0 算（垫底），不冒用 L2 的分量——
    `layer_of_kind` 对未知 kind 回落 L2 是防"谎报成方法卡"，不是给权重用的。
    """
    layer = _layers.KIND_LAYER.get(kind)
    return _layers.weight_of_layer(layer) if layer else 0.0


def _order_key(row: dict) -> tuple:
    """层权重大 → 小；同层内：已复现 → 待复现；同层末端：受限垫底。"""
    return (
        -_layer_weight(row["kind"]),
        1 if row["new_point"] else 0,
        1 if row["restricted"] else 0,
    )


def _multiplier(row: dict) -> int:
    """加权倍率：新要点·待复现 / 回炉受限都按"权重降半"计 → 成本 ×2。"""
    return 2 if (row.get("new_point") or row.get("restricted")) else 1


def _cost_of(row: dict) -> int:
    """条目成本 = token 估算 × 加权倍率（与 inject 的"成本按 2 倍计"同口径）。"""
    return max(1, _inject.estimate_tokens(row["text"]) * _multiplier(row))


def _bullet(section: str, text: str) -> str:
    """标准流程是编号行，其余加 bullet（与 inject 组装口径一致）。"""
    return text if section.startswith("标准流程") else f"- {text}"


def _truncate_to_tokens(text: str, budget: int) -> str:
    """按行截到预算内（估算口径与 `inject.estimate_tokens` 一致）。

    与 `inject._truncate_to_tokens` 的一个有意差别：那边首行就超预算时会整行返回
    （规则预算 400、行都短，踩不到）；这边显式处理——**首行超预算时按字符硬裁**。
    否则"预算遵守率 100%"这个指标在超长单行（如一条 200 字意图）面前就是假的。
    """
    if budget <= 0:
        return ""
    out: list[str] = []
    used = 0
    for line in str(text or "").splitlines() or [""]:
        cost = _inject.estimate_tokens(line)
        if used + cost <= budget:
            out.append(line)
            used += cost
            continue
        if not out:
            out.append(line[:budget])   # 首行就超：CJK 每字约 1 token，裁到预算字符数
        break
    return "\n".join(out).strip()


def assemble_text(items: list[dict]) -> str:
    """已选条目 → 分节文本（同一 section 连续合并，用空行分节）。"""
    blocks: list[tuple[str, list[str]]] = []
    for it in items:
        if not blocks or blocks[-1][0] != it["section"]:
            blocks.append((it["section"], []))
        blocks[-1][1].append(_bullet(it["section"], it["text"]))
    return "\n\n".join(
        f"[{sec}]\n" + "\n".join(lines) for sec, lines in blocks
    )


def prepare_items(store, trunk: str, category: str) -> list[dict]:
    """候选条目：过覆盖层、去回炉移出、套用覆盖文本；随后由调用方排序。"""
    try:
        overrides = store.load_overrides()
    except Exception:
        overrides = {}
    rows: list[dict] = []
    for it in _inject.iter_injection_items(store, trunk, category):
        ov = overrides.get(it["id"]) or {}
        if not isinstance(ov, dict):
            continue
        if ov.get("enabled") is False:
            continue  # 用户显式关掉：召回与推送同样尊重
        if it.get("excluded"):
            continue  # 回炉移出：证真后才回归
        rows.append({
            "id": it["id"],
            "kind": it["kind"],
            "section": it.get("section") or "",
            "text": str(ov.get("text") or it["text"]),
            "new_point": bool(it.get("new_point")),
            "restricted": bool(it.get("restricted")),
        })
    return rows


def build_capsule(store, trunk: str, category: str,
                  budget_tokens: int | None = DEFAULT_BUDGET_TOKENS,
                  include_intents: bool = False,
                  refill: bool = False) -> dict:
    """组装有上限胶囊。永不抛异常（调用方是 MCP/CLI，崩了比空结果更糟）。

    返回：
        {trunk, category, budget, tokens, cost, truncated, skipped, refilled,
         items: [{id, kind, section, text, cost, new_point, restricted}],
         text}

        `tokens` = 实际 token 量；`cost` = 加权成本（新要点/受限按 2 倍计，
        与 inject 同口径）。**封顶判在 `cost` 上**——加权系数恒 ≥1，所以
        cost ≤ budget 必然推出 tokens ≤ budget，两个指标都不说谎。

    `include_intents=True` 时把 L6 前瞻意图作为**最低权重尾层**追加（默认关）。
    意图只是"接下来可能要处理什么"，不是指令——挤占 L3/L5 的位置是滥用。

    `refill=True` 时启用补捞（P1-3）：首轮命中少于 `REFILL_MIN_ITEMS` 且没被
    预算截断 → 再捞一轮 L2 经验（G 门槛同注入红线），与首轮共用同一预算。
    """
    trunk = (str(trunk) or "").strip() or FALLBACK_TRUNK
    category = (str(category) or "").strip() or FALLBACK_CATEGORY
    try:
        budget = int(budget_tokens)
    except (TypeError, ValueError):
        budget = DEFAULT_BUDGET_TOKENS
    budget = max(0, budget)

    try:
        rows = prepare_items(store, trunk, category)
    except Exception:
        rows = []
    if include_intents:
        rows = rows + _intent_rows(store, trunk, category)

    picked: list[dict] = []
    acc = {"cost": 0, "tokens": 0, "truncated": False, "refilled": False}

    def _take(row: dict) -> bool:
        """按成本预算挑一条；装不下完整内容时硬裁。返回是否收入。"""
        cost = _cost_of(row)
        if acc["cost"] and acc["cost"] + cost > budget:
            acc["truncated"] = True
            return False
        if not acc["cost"] and cost > budget:
            # 一条都装不下完整内容时硬裁。"至少给一条"不能凌驾于封顶之上——
            # 否则 token 预算遵守率这个指标是假的。裁剪目标按倍率折算，并给
            # `estimate_tokens` 的 +1 尾差预留 1 个字符额度，让裁完的
            # **加权成本**也进预算（倍率 2 的条目只给一半字符额度）。
            raw_budget = budget // _multiplier(row) - 1
            if raw_budget <= 0:
                acc["truncated"] = True
                return False
            clipped = _truncate_to_tokens(row["text"], raw_budget).strip()
            if not clipped:
                acc["truncated"] = True
                return False
            row = {**row, "text": clipped}
            cost = _cost_of(row)
        acc["cost"] += cost
        acc["tokens"] += _inject.estimate_tokens(row["text"])
        picked.append({**row, "cost": cost})
        return True

    for row in sorted(rows, key=_order_key):  # 稳定排序：同键保持文件序
        _take(row)

    extra: list[dict] = []
    if refill and len(picked) < REFILL_MIN_ITEMS and not acc["truncated"]:
        extra = _experience_rows(store, trunk, category)
        for row in sorted(extra, key=_order_key):
            if _take(row):
                acc["refilled"] = True

    return {
        "trunk": trunk,
        "category": category,
        "budget": budget,
        "tokens": acc["tokens"],
        "cost": acc["cost"],
        "truncated": acc["truncated"],
        "skipped": len(rows) + len(extra) - len(picked),
        "refilled": acc["refilled"],
        "items": picked,
        "text": assemble_text(picked) if picked else "",
    }


def _experience_row_text(rec: dict) -> str:
    """经验条目 → 一行可注入文本（任务 + 做法，缺哪段补哪段）。

    取 action（怎么改好的）为主：那是经验里唯一可复用的部分；只有 outcome
    时用它，两者都没有才退回 task。绝不把三字段硬拼成一段长文——成本翻倍、
    还把重点埋了（注入 token 预算）。
    """
    task = str(rec.get("task") or "").strip()
    action = str(rec.get("action") or "").strip()
    outcome = str(rec.get("outcome") or "").strip()
    body = action or outcome or task
    if not body:
        return ""
    return f"{task}：{body}" if task and body != task else body


def _experience_rows(store, trunk: str, category: str) -> list[dict]:
    """L2 经验 → 条目行（补捞用，P1-3）。

    门槛与注入红线一致：`G < G_MIN_INJECT(0.5)` 永不入，
    且先看未蒸馏的（已蒸馏的经验说明方法卡里已经有了，不必重复）。
    最多 `REFILL_MAX_EXPS` 条——补捞是补薄，不是把经验库搬进胶囊。
    """
    try:
        rows = list(store.iter_experiences(
            trunk=trunk, category=category, include_distilled=False,
            limit=REFILL_MAX_EXPS * 3))
    except Exception:  # noqa: BLE001 读失败就是没得补，不崩调用方
        return []
    out: list[dict] = []
    for e in rows:
        try:
            # 写口契约是大写 G，SQLite 读路径列的别名是小写 g——两处都认，
            # 缺字段按 0 算（不达门槛自然被挡在门外，不会漏进胶囊）。
            g = float(e.get("g") if e.get("g") is not None
                      else e.get("G") or 0)
        except (TypeError, ValueError):
            continue
        if g < G_MIN_INJECT:
            continue
        text = _experience_row_text(e)
        if not text:
            continue
        out.append({"id": str(e.get("id") or ""), "kind": "experience",
                    "section": "经验", "text": text,
                    "new_point": False, "restricted": False})
        if len(out) >= REFILL_MAX_EXPS:
            break
    return out


def _intent_rows(store, trunk: str, category: str) -> list[dict]:
    """L6 前瞻意图 → 条目行（无意图 → 空列表）。

    读被拒（只读代理白名单缺 list_intentions）与"没有意图"是两回事：
    前者是配置错误，留 warning——否则整节静默消失，无错误可感知。
    """
    try:
        items = store.list_intentions(trunk)
    except PermissionError as exc:
        logger.warning("意图读取被拒（只读代理白名单缺 list_intentions？）: %s", exc)
        return []
    except Exception:
        return []
    out = []
    for it in items or []:
        text = str(it.get("intent") or "").strip()
        if not text:
            continue
        if it.get("category") and str(it.get("category")) != category:
            continue  # 只带本类别的意图；跨类别的意图在这儿没有意义
        out.append({"id": str(it.get("id") or ""), "kind": "intention",
                    "section": "前瞻意图", "text": text,
                    "new_point": True,     # 权重降半：意图永远比方法论轻
                    "restricted": False})
    return out


def resolve_scope(store, task: str | None,
                  trunk: str | None = None,
                  category: str | None = None) -> tuple[str, str, bool]:
    """定任务范围。调用方给了 (trunk, category) 就用；否则从任务文本推断。

    返回 (trunk, category, detected)——detected 表示是否走了推断，
    供调用方如实告知用户"这是猜的"，别把兜底值当成确定结论。

    推断失败一律回兜底值（其他/未分类），不抛异常。
    """
    trunk = (str(trunk or "")).strip()
    category = (str(category or "")).strip()
    if trunk and category:
        return trunk, category, False
    if not task or not str(task).strip():
        return (trunk or FALLBACK_TRUNK), (category or FALLBACK_CATEGORY), False
    try:
        from ..proxy import detect as _detect

        seed = store.load_config().get(
            "seed_keywords", _detect.DEFAULT_SEED_KEYWORDS)
        ctx = _detect.detect_task_context(
            [{"content": str(task)}], seed,
            _detect.known_categories_from_store(store), store=store)
        got_trunk = str((ctx or {}).get("trunk") or "").strip()
        got_cat = str((ctx or {}).get("category") or "").strip()
    except Exception:
        got_trunk, got_cat = "", ""
    return (trunk or got_trunk or FALLBACK_TRUNK,
            category or got_cat or FALLBACK_CATEGORY, True)
