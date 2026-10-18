"""单条资产 AI 改写（第二项蒸馏：用户对内部总结不满意时，接的模型再总结一遍）。

- polish_*：调模型出**提案**，完全不写盘——用户在预览里对比采纳才落库；
- apply_*：最小写入面。只重写总结层（*_raw 原文不动、不是"用户改对内容"，
  不写 previous 快照、不标 corrected、不动 G）；经验改写后 distilled=False
  回炉，下次「总结成方法」把新说法带进方法文档。
坑行改写守则：语义保持 + 关键名词原样——三态双门按 near_dup(行, 经验) 回填
证据（gate.failure_mode_states），改写离原文太远会让计数回落行内标注。
"""

from __future__ import annotations

import logging

from ..store.store import Store
from . import engine_curation, gate, llm

logger = logging.getLogger("experientia.distill.rewrite")

POLISH_FIELDS = ("task", "state", "action", "outcome")

_EXPS_PROMPT = """下面是同一张经验卡的原始记录与当前总结。用户对当前总结不满意，\
请只依据"原始记录"里的信息，重新提炼一版更准更精炼的总结。

{records}

要求：
1. 只能用原始记录里的事实，禁止臆造；原文没有的字段输出空字符串；
2. task：一句结论，不超过 30 字，讲清"做了什么 + 结果如何"；
3. action（做法）/ state（踩坑）各不超过 60 字，outcome（结果）不超过 40 字，\
具体到能直接执行，不要空话；
4. 关键名词（工具名、字段名、流程名）必须原样保留。

只输出 JSON 数组，不要任何解释：
[{{"id": "记录id", "task": "...", "action": "...", "state": "...", "outcome": "..."}}]"""

_FAILURE_PROMPT = """你在修订团队"踩过的坑"清单里的一条。把它改写得\
更具体、更可执行，但**语义不变**：

当前条目：{text}

该坑的出现轨迹（帮助理解上下文，不要引入轨迹里没有的事实）：
{trajectory}

要求：
1. 不加不减事实；关键名词（工具名、字段名、流程名）必须原样保留——\
这条要和原始经验文字保持近似，机器靠它回填出现次数；
2. 一句话、不超过 60 字、不要换行，写清"什么不能做 + 为什么会错"；
3. 如果当前条目已经足够好，原样返回。

只输出 JSON，不要任何解释：{{"new_text": "..."}}"""


_EXPLAIN_PROMPT = """把下面这条"AI 协作经验"讲给一个完全不懂技术的人听。

经验：任务={task}｜踩坑={state}｜做法={action}｜结果={outcome}（重要性 {importance}/10）

用 {lang} 大白话输出两部分，零术语、禁止复述上面的原文：
1. explain：这条经验到底在说什么（1-2 句，能用生活化类比就用）；
2. advice：给用户的一条可执行建议（下次遇到类似的事该怎么做/注意什么，1-2 句）。

只输出 JSON，不要任何解释：{{"explain": "...", "advice": "..."}}"""

_EXPLAIN_LANG = {"zh": "中文", "en": "English", "ja": "日本語", "ko": "한국어",
                 "fr": "Français", "de": "Deutsch", "es": "Español"}


def explain_experience(store: Store, exp_id: str, lang: str = "zh") -> dict:
    """单条经验"讲人话"提案：AI 大白话解释 + 一条可执行建议。

    - 结果缓存在经验记录的 explain/advice 字段（再次点开零模型成本）；
    - 这是对用户看的"解释视图"，不改 task/action 等资产字段、不动 G；
    - status: ok / no_model / not_found。"""
    item = store.find_experience(exp_id)
    if item is None:
        return {"status": "not_found"}
    cached_ex, cached_ad = (str(item.get("explain") or "").strip(),
                            str(item.get("advice") or "").strip())
    if cached_ex and cached_ad:
        return {"status": "ok", "explain": cached_ex, "advice": cached_ad,
                "cached": True}
    if not llm.model_available(store):
        return {"status": "no_model"}
    prompt = _EXPLAIN_PROMPT.format(
        task=str(item.get("task") or "")[:120],
        state=str(item.get("state") or "")[:120],
        action=str(item.get("action") or "")[:160],
        outcome=str(item.get("outcome") or "")[:80],
        importance=item.get("importance") or "-",
        lang=_EXPLAIN_LANG.get(lang, "中文"))
    raw = llm.call_model(store, [{"role": "user", "content": prompt}])
    data = llm.extract_json(raw)
    explain = str((data or {}).get("explain") or "").strip().replace("\n", " ")
    advice = str((data or {}).get("advice") or "").strip().replace("\n", " ")
    if not explain or not advice:
        raise ValueError("AI 输出无法解析为解释/建议")
    explain, advice = explain[:500], advice[:500]
    store.update_experience(exp_id, {"explain": explain, "advice": advice})
    return {"status": "ok", "explain": explain, "advice": advice, "cached": False}


def _record_block(r: dict) -> str:
    def _pair(key: str) -> str:
        return (f"- {key}: {r.get(key + '_raw') or r.get(key) or ''}")
    orig = "\n".join(_pair(k) for k in ("task", "action", "state", "outcome"))
    cur = "\n".join(f"- {k}: {str(r.get(k) or '')}" for k in
                    ("task", "action", "state", "outcome"))
    return (f"id={r.get('id')}\n原始记录：\n{orig}\n"
            f"当前总结（用户不满意，需重写）：\n{cur}")


def polish_experiences(store: Store, ids: list[str]) -> dict:
    """经验卡单条 AI 重写提案（不落库）。status: ok / no_model / not_found。"""
    if not llm.model_available(store):
        return {"status": "no_model"}
    recs = [r for r in (store.find_experience(str(i)) for i in ids) if r]
    if not recs:
        return {"status": "not_found"}
    prompt = _EXPS_PROMPT.format(
        records="\n\n".join(_record_block(r) for r in recs))
    raw = llm.call_model(store, [{"role": "user", "content": prompt}])
    data = llm.extract_json(raw)
    if isinstance(data, dict):
        data = [data]
    known = {str(r.get("id")) for r in recs}
    proposals: list[dict] = []
    for item in data or []:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "")
        if pid not in known:
            continue
        proposals.append({"id": pid, **{
            k: str(item.get(k) or "").strip().replace("\n", " ")[:200]
            for k in POLISH_FIELDS}})
    if not proposals:
        raise ValueError("AI 输出无法解析为重写提案")
    return {"status": "ok", "proposals": proposals}


def apply_polish(store: Store, exp_id: str, fields: dict) -> dict | None:
    """采纳经验重写：只更新总结层（*_raw 不动），distilled=False 回炉。

    与「纠正」的区别：纠正=用户改对内容（G 落纠正档 + previous 快照）；
    重写=措辞/提炼质量提升，事实未变，故 G/corrected/raw/快照全不动。
    """
    item = store.find_experience(exp_id)
    if item is None:
        return None
    patch: dict = {}
    for key in POLISH_FIELDS:
        new = str(fields.get(key) or "").strip()
        if not new or new == str(item.get(key) or "").strip():
            continue
        patch[key] = new
    if not patch:
        return item
    patch["distilled"] = False  # 回炉：下次总结把新说法带进方法文档
    updated = store.update_experience(exp_id, patch)
    if updated is not None:
        store.append_event(
            "ai-rewrite",
            f"AI 重写经验 {exp_id}：更新 {('、'.join(k for k in POLISH_FIELDS if k in patch))}",
            id=exp_id, trunk=str(item.get("trunk") or ""),
            category=str(item.get("category") or ""))
    return updated


def _failure_line_map(store: Store, trunk: str,
                      category: str) -> dict[str, str]:
    """{去标记去次数的行正文: 原始行}（失败模式节内）。"""
    md = store.read_skill(trunk, category) or ""
    lines = [ln for ln in md.splitlines() if ln.strip().startswith("-")]
    out: dict[str, str] = {}
    for ln in lines:
        key = gate._strip_count(gate._line_body(ln))
        if key:
            out[key] = ln
    return out


def _failure_descs(store: Store, trunk: str, category: str) -> list[str]:
    """该类别 playbook 失败模式节的行正文清单（给轨迹对照用）。"""
    md = store.read_skill(trunk, category) or ""
    from ..proxy.inject import parse_playbook

    section = parse_playbook(md).get("失败模式") or ""
    return [gate._strip_count(gate._line_body(ln))
            for ln in section.splitlines() if ln.strip().startswith("-")]


def polish_failure_mode(store: Store, trunk: str, category: str,
                        text: str) -> dict:
    """单条坑改写提案（不落库）。status: ok / no_model / not_found。"""
    if not llm.model_available(store):
        return {"status": "no_model"}
    old = gate._strip_count((text or "").strip())
    if not old or old not in _failure_line_map(store, trunk, category):
        return {"status": "not_found"}
    traj = engine_curation.failure_mode_trajectory(store, trunk, category)
    lines = []
    for it in traj[:10]:
        if isinstance(it, dict):
            lines.append(f"· {str(it.get('ts') or '')[:10]} "
                         f"{it.get('task') or ''}（出现 {it.get('count') or 1} 次）")
        else:
            lines.append(f"· {it}")
    prompt = _FAILURE_PROMPT.format(text=old,
                                     trajectory="\n".join(lines) or "（无）")
    raw = llm.call_model(store, [{"role": "user", "content": prompt}])
    data = llm.extract_json(raw)
    new_text = str((data or {}).get("new_text") or "").strip().replace("\n", " ")
    if not new_text:
        raise ValueError("AI 输出无法解析为改写条目")
    return {"status": "ok", "old_text": old,
            "new_text": new_text[:200]}


def apply_polish_failure(store: Store, trunk: str, category: str,
                         old_text: str, new_text: str) -> bool:
    """采纳坑改写：整行原位替换（三态标记与行内"（出现 N 次）"保持原样）。"""
    old = gate._strip_count((old_text or "").strip())
    new = gate._strip_count((new_text or "").strip().replace("\n", " "))
    if not old or not new:
        return False
    md = store.read_skill(trunk, category)
    if not md:
        return False
    hit = _failure_line_map(store, trunk, category).get(old)
    if hit is None:
        return False
    new_line = hit.replace(old, new, 1)
    md_new = "\n".join(new_line if ln == hit else ln
                       for ln in md.splitlines()) + "\n"
    store.write_skill(trunk, category, md_new)
    store.append_event("ai-rewrite",
                       f"AI 重写坑条目 {trunk}/{category}：{new[:60]}",
                       path=f"{trunk}/{category}")
    return True
