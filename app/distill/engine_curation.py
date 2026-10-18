"""引擎 A：增量策展（日常档，默认，产品文档 /）。

方法论可换，数据和资产不动。本引擎吃"经验流 + 现有资产"，
吐资产 delta；资产 schema 开放（章节是集合不是定死五节）。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from ..store.store import Store, utcnow
from ..proxy.inject import (FAILURE_PENDING_MARK, FAILURE_SOLID_MARK,
                            FAILURE_WATCH_MARK, USER_CONFIRM_MARK,
                            normalize_marks, parse_playbook)
from . import gate, gsignal, llm, skill

logger = logging.getLogger("experientia.distill.curation")

# 归纳层不做"假蒸馏"（总纲）：无模型 → 不产出任何方法正文，结构化拒绝并引导接入。
# 文案与总纲的 model_required 结构同源，页面直接用 message 提示用户。
MODEL_REQUIRED_MESSAGE = ("未接入模型，无法归纳成方法。已保留上次内容；"
                          "去「接入」页接一个本地模型或 API 后即可更新。")
# 有模型但这次没拿到内容（调不通 / 返回空 / 三节皆空）——同样**不写卡**，如实返回。
MODEL_FAILED_MESSAGE = "这次没拿到模型的产出，方法卡保持原样——可以重试或换模型。"
# 与 /api/skills/distill 的 503 文案同源（"已保住…不被覆盖"是既有对外口径，
# 别改词：WS-INT 的 test_rebuild_entry 按"保住"断言，改了就是白白制造非归属失败）
EMPTY_RESULT_MESSAGE = "这次总结没拿到内容，已保住原方法卡不被覆盖——可以重试或换模型。"

def _parse_version(md: str | None) -> int:
    """从 playbook frontmatter 读取 version 并递增，无旧文件时返回 1。"""
    if not md:
        return 1
    m = re.search(r"version:\s*(\d+)", md)
    return int(m.group(1)) + 1 if m else 2


_VERSION_HEAD_RE = re.compile(r"^>\s*version:\s*(\d+)", re.M)


def _playbook_head(trunk: str, category: str, version: int, updated: str,
                   source_exps: str, confidence: str,
                   name: str | None = None, name_source: str = "auto",
                   created: str | None = None,
                   content_source: str = "", generated_at: str = "") -> str:
    """playbook 头部。R1：`> name:` 是说人话的短名（AI 蒸馏时起名 / 用户手改），
    未命名时整行省略——展示层回退到「项目 / 类别」两级路径。
    `> created:` 首次沉淀日期（溯源用；老文件没有此行 → 展示层省略）。

    `content_source` / `generated_at`：内容溯源（总纲），写入点收敛在
    `skill.set_provenance`（本处只负责传值）；两者都空 = 来源未知，不写这两行
    （旧卡保持原样，展示层不挂降级条）。
    """
    lines = [f"# {trunk} / {category} · playbook", ""]
    if name:
        lines += [f"> name: {name}", f"> name_source: {name_source}"]
    if created:
        lines.append(f"> created: {created}")
    lines += [f"> version: {version}", f"> updated: {updated}",
              f"> source_exps: {source_exps}", f"> confidence: {confidence}", ""]
    head = "\n".join(lines)
    if content_source or generated_at:
        head = skill.set_provenance(head, content_source, generated_at)
    return head

FIXES_HEAD = """# {trunk} / {category} · 纠正补丁

> version: {version}
> updated: {updated}

"""

DISTILL_PROMPT = """基于以下经验，更新该类别的 playbook。这是增量更新，不是重写：
旧 playbook 中未被新经验推翻的条目必须原样保留（可合并近义条目，不可丢长尾细节）。

当前 playbook（旧版；若为"（无）"则首次蒸馏，全量写）：
{existing}

高 G 经验（成功）：
{high_g}

低 G 经验（失败/被纠正）：
{low_g}

输出格式（严格按以下章节输出，无内容的章节写"（无）"）：
## 方法名
- 给这份方法起一个 4-14 字的中文短名：像给同事一句话讲清"这是干嘛的"，说人话（例：投标书报价核算、周报数据核对）
- 不要出现机制词（playbook、蒸馏、类别、方法论、skill 等）、不要包含项目名（项目名会另外显示）、不要以"的"开头或结尾
{name_hint}
## 标准流程
- 参数化步骤（具体值替换为 {{变量}}）
## 成功要点
- 从成功经验提炼
## 失败模式
- 每条一行，格式固定：- [标记] 什么不能做 + 为什么（出现 N 次）
- 标记三选一（ASCII，必须原样输出，不要换成中文，机器按它识别；最终以机器复核为准）：
  [Solidified] 已固化（坐实的坑，会注入给 agent）/ [Pending] 待验证（出现 ≥{solidify_count} 次但还没验证会不会再踩）/ [Watching] 观察中（<{solidify_count} 次）
- 出现次数：同类失败经验的 count 之和
## 过时项标记
- 旧 playbook 中被新经验推翻的条目（标注原因）
## 偏好增量
- 用户决策风格的可归纳模式（没有则写"（无）"）
"""

COMPRESS_PROMPT = """playbook 超过长度上限，做压缩：合并近义条目、保留最高 G 的来源信息、
保持章节结构与失败模式行格式（[Solidified]/[Pending]/[Watching] + 出现次数）
以及成功要点的 [NewPoint] 标记不变。ASCII 标记必须原样保留。直接输出压缩后的全文。

{playbook}
"""

FIXES_PROMPT = """你是失败分析师。下面是一个类别里"被用户纠正过 / 低价值"的经验和它们对应的失败轨迹。
用户纠正过的事情比"坑是什么"更有价值——请提炼成**纠正补丁**：遇到某情况时，不要怎么做、应该改成怎么做。

输出格式（严格按以下结构，无内容写"（无）"；每条一行，以"- "开头）：
## 纠正补丁
- 遇到 {{场景/信号}}，不要 {{错误做法}}，改为 {{正确做法}}
- 遇到 …

要求：
1. 只写能从给定经验里找得出依据的条目，不要臆造；
2. "不要 Y"和"改为 Z"都要具体到能直接执行，不要空话；
3. 同类纠正合并成一条，不超过 8 条；
4. 没有可提炼的纠正时，整节只写"（无）"。

被纠正/低价值经验：
{exps}

对应失败模式（来自 playbook 失败模式节，可参照其"什么不能做"）：
{failure_modes}
"""


def _prior_value(e: dict, key: str) -> str:
    """失败分析读侧：被编辑过的经验优先读 previous 快照里的旧值。

    用户点「纠正」把内容改对之后，旧内容（错的那版）留在 previous 快照——
    "什么不能做"记的应该是被改掉的错内容，别把改对的文本当成教训。"""
    prev = e.get("previous")
    if isinstance(prev, dict):
        old = str(prev.get(key) or "").strip()
        if old:
            return old
    return str(e.get(key) or "").strip()


def _fmt_experience(e: dict) -> str:
    low = not gsignal.high_value_eligible(e)
    if gsignal.is_rule(e):
        # rule 坑卡：task/action 是合并用指纹，素材/展示统一走模板句
        from . import mining

        parts = [mining.rule_line_text(e), f"G={e.get('G')}"]
        if int(e.get("count") or 1) > 1:
            parts.append(f"出现{e['count']}次")
        return " | ".join(str(p) for p in parts)
    action = _prior_value(e, "action") if low else str(e.get("action") or "")
    parts = [f"{e.get('task', '?')}: {action or '?'}"]
    if not low:
        parts.append(f"G={e.get('G')}")
        if e.get("outcome"):
            parts.append(f"结果={e['outcome']}")
    else:
        parts.append(f"G={e.get('G')}")
        state = _prior_value(e, "state")
        if state:
            parts.append(f"状态={state}")
        if e.get("corrected"):
            parts.append("被用户纠正")
    if int(e.get("count") or 1) > 1:
        parts.append(f"出现{e['count']}次")
    return " | ".join(str(p) for p in parts)


def _parse_name_head(md: str | None) -> tuple[str | None, str | None]:
    """R1：从 playbook 头部读 (name, name_source)；没有 = (None, None)。"""
    import re as _re

    if not md:
        return None, None
    n = _re.search(r"^>\s*name:\s*(.+?)\s*$", md, _re.M)
    s = _re.search(r"^>\s*name_source:\s*(\S+)", md, _re.M)
    name = n.group(1).strip() if n else None
    if not name or name in ("（无）", "(无)"):
        name = None
    return name, (s.group(1) if s else None)


def _name_hint(existing: str | None) -> str:
    """R1：蒸馏 prompt 的命名指引——用户手起的名字必须保留（代码侧也有硬保证）。"""
    name, source = _parse_name_head(existing)
    if not existing or not name:
        return "- 这是首次蒸馏，请起一个符合上面要求的名字\n"
    if source == "manual":
        return f"- 现有名字是「{name}」（用户自己起的，必须原样保留，不要改）\n"
    return (f"- 现有名字是「{name}」：方法内容没有明显变化就沿用原名；"
            f"明显变化了再按上面的要求起新名\n")


def build_distill_prompt(experiences: list[dict], existing: str | None) -> str:
    high = [_fmt_experience(e) for e in experiences if gsignal.high_value_eligible(e)]
    low = [_fmt_experience(e) for e in experiences if not gsignal.high_value_eligible(e)]
    # R6：喂给模型的旧资产先归一化旧中文键 → ASCII 键，防模型照抄旧格式
    existing = normalize_marks(existing or "")
    return DISTILL_PROMPT.format(
        existing=existing or "（无）",
        high_g="\n".join(f"{i + 1}. {x}" for i, x in enumerate(high)) or "（无）",
        low_g="\n".join(f"{i + 1}. {x}" for i, x in enumerate(low)) or "（无）",
        solidify_count=gsignal.FAILURE_SOLIDIFY_COUNT,
        name_hint=_name_hint(existing),
    )


def _merge_preferences(store: Store, trunk: str, increments: str) -> None:
    """偏好增量合并进 preferences/<trunk>.md；用户确认过的条目不被覆盖。"""
    increments = (increments or "").strip()
    if not increments or increments in ("（无）", "(无)"):
        return
    existing = store.read_preferences(trunk) or ""
    confirmed_lines = {
        ln.strip() for ln in normalize_marks(existing).splitlines()
        if USER_CONFIRM_MARK in ln
    }
    new_lines = []
    for ln in increments.splitlines():
        ln = ln.strip()
        if not ln.startswith("-"):
            continue
        text = ln.lstrip("- ").strip()
        if any(text in c for c in confirmed_lines):
            continue  # 用户确认过的不覆盖
        if any(text in l for l in existing.splitlines()):
            continue  # 已存在
        new_lines.append(ln)
    if new_lines:
        base = existing.rstrip() + "\n" if existing else f"# {trunk} · 偏好画像\n\n> 自动归纳，可编辑\n\n"
        store.write_preferences(trunk, base + "\n".join(new_lines) + "\n")
        store.append_event("pref-inc", f"偏好增量合并 {trunk}：+{len(new_lines)} 条",
                           trunk=trunk, n=len(new_lines))


def _fallback_fixes_body(experiences: list[dict]) -> str:
    """无模型纠正补丁（蒸馏兜底方案）：被纠正经验原样罗列，不归纳。

    "遇到 {state}，不要 {action}" 是纠正的直接含义（state=用户纠正原话，
    action=被纠正的做法原文），surviving vocabulary 不改写；trigram 去重。
    两个字段都走 _prior_value——用户改对了内容之后，教训仍是那版错内容。
    """
    from . import dedupe

    lines: list[str] = []
    kept: list[str] = []
    for e in sorted(experiences, key=lambda x: str(x.get("ts", ""))):
        if not e.get("corrected"):
            continue
        state = _prior_value(e, "state")
        action = _prior_value(e, "action")
        text = f"遇到 {state}，不要 {action}" if state and action else (state or action)
        if not text or any(dedupe.near_dup(text, k) for k in kept):
            continue
        lines.append(f"- {text[:200]}")
        kept.append(text)
    return "\n".join(lines)


def _gen_fixes(store: Store, trunk: str, category: str,
               experiences: list[dict]) -> str | None:
    """W3-01 失败分析师：从 corrected/低 G 经验 + 失败轨迹提炼纠正补丁（_fixes.md）。

    与成功分支同次蒸馏内调用（非两次用户点击）；无 corrected 经验 → 不产出
    （不写空补丁文件）。无模型 → 不产出（归纳层门禁，总纲）。
    返回补丁文件路径或 None。
    """
    low = [e for e in experiences
           if e.get("corrected") or float(e.get("G") or 0) < 0.5]
    if not any(e.get("corrected") for e in low):
        return None  # 无用户纠正 → 不产出空补丁
    if not llm.model_available(store):
        return None  # 无模型 → 不归纳纠正补丁（与"不假蒸馏"同口径）
    existing = store.read_fixes(trunk, category)
    version = 1
    if existing:
        import re as _re

        m = _re.search(r"version:\s*(\d+)", existing)
        version = int(m.group(1)) + 1 if m else 2
    exp_lines = [_fmt_experience(e) for e in low]
    fail_lines = [f"- {x}" for x in
                  failure_mode_trajectory(store, trunk, category)[:20]]
    prompt = FIXES_PROMPT.format(
        exps="\n".join(f"{i + 1}. {x}" for i, x in enumerate(exp_lines)),
        failure_modes="\n".join(fail_lines) or "（无）",
    )
    try:
        raw = llm.call_model(store, [{"role": "user", "content": prompt}])
        sections = parse_playbook(raw)
        body = (sections.get("纠正补丁") or "（无）").strip()
        if not body or body in ("（无）", "(无)"):
            return None  # 模型也没提炼出条目 → 不落空文件
    except Exception as exc:
        logger.warning("纠正补丁模型调用失败，落入原样罗列: %s", exc)
        body = _fallback_fixes_body(experiences)
    if not body:
        return None
    head = FIXES_HEAD.format(trunk=trunk, category=category, version=version,
                             updated=utcnow())
    path = store.write_fixes(trunk, category, head + f"## 纠正补丁\n{body}\n")
    store.append_event(
        "fixes", f"纠正补丁 {trunk}/{category}：{body.count(chr(10)) + 1} 条 → v{version}",
        path=f"{trunk}/{category}", ver=f"v{version}",
        n=body.count(chr(10)) + 1)
    return str(path)


def _failure_solid_entries(md: str | None) -> list[str]:
    """playbook 失败模式节里的 [Solidified] 条目（按出现顺序，正文去前缀；兼容旧中文键）。"""
    out = []
    in_sec = False
    prefix = f"- {FAILURE_SOLID_MARK}"
    for line in (md or "").splitlines():
        s = normalize_marks(line.strip())
        if s.startswith("## "):
            in_sec = s[3:].strip() == "失败模式"
            continue
        if in_sec and s.startswith(prefix):
            body = s[len(prefix):].strip()
            if body:
                out.append(body)
    return out


def _push_distill_notices(store: Store, trunk: str, category: str, version: int,
                          count: int, confidence: str, name: str | None,
                          old_md: str | None, new_md: str,
                          pref_before: str, pref_after: str) -> None:
    """蒸馏成功后的通知：统一走 method_update。"""
    try:
        from .. import notify

        label = f"{trunk}/{category}"
        display = f"{name}（{label}）" if name else label
        parts = []
        if version == 1:
            parts.append(f"新方法沉淀：{display}（从 {count} 条经验蒸馏 → v1，置信度 {confidence}）")
        else:
            parts.append(f"方法升级：{display} → v{version}（合并 {count} 条新经验，置信度 {confidence}）")
        old_solid = set(_failure_solid_entries(old_md))
        fresh = [x for x in _failure_solid_entries(new_md) if x not in old_solid]
        if fresh:
            parts.append(f"新坑固化：{label} · 「{fresh[0][:40]}」")
            parts.append("新坑明细：" + " | ".join(x[:40] for x in fresh[:3]))
            if len(fresh) > 3:
                parts[-1] += f"（+{len(fresh)-3} 条）"
        old_pref = {ln.strip() for ln in (pref_before or "").splitlines()
                    if ln.strip().startswith("-")}
        fresh_pref = [ln.strip() for ln in (pref_after or "").splitlines()
                      if ln.strip().startswith("-") and ln.strip() not in old_pref]
        if fresh_pref:
            total = sum(1 for ln in (pref_after or "").splitlines()
                        if ln.strip().startswith("-"))
            parts.append(f"偏好新增：「{trunk}」新归纳 {len(fresh_pref)} 条（累计 {total} 条）")
        if parts:
            body = "\n".join(parts)
            title = f"方法动态：{display}"
            if fresh:
                title += f" · {len(fresh)} 个新坑"
            if fresh_pref:
                title += f" · {len(fresh_pref)} 条新偏好"
            notify.push(store, "method_update", title, body, target="methods")
    except Exception as exc:
        logger.warning("蒸馏通知推送失败（不影响蒸馏）: %s", exc)


_BODY_SECTIONS = ("标准流程", "成功要点", "失败模式")


def _has_content(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and t not in ("（无）", "(无)")


def _sections_have_body(sections: dict | None) -> bool:
    return any(_has_content((sections or {}).get(k)) for k in _BODY_SECTIONS)


def playbook_has_body(md: str) -> bool:
    """方法卡是否真有内容（GUI 用它决定要不要给「重建」入口）。"""
    return _sections_have_body(parse_playbook(md or ""))


def _no_content_result(status: str, message: str, count: int,
                       existing: str | None) -> dict:
    """没拿到模型产出（无模型 / 调不通 / 三节皆空）的统一拒绝体（总纲同型）。

    **不写卡、不覆盖、不写"（无）"占位**（总纲）——宁可诚实地空，也不用规则
    假装归纳。``kept_previous`` 告诉调用方旧卡还在，UI 据此提示"已保留上次内容"。
    """
    return {"ok": False, "status": status, "file": None, "count": count,
            "message": message, "version": None, "fixes": None,
            "kept_previous": bool(playbook_has_body(existing or "")),
            "collapsed": bool(playbook_has_body(existing or "")),
            "generated_at": skill.provenance_of(existing)[1]}


def distill(store: Store, trunk: str, category: str, source: str = "manual",
            force: bool = False, dry_run: bool = False) -> dict:
    """一次蒸馏 = 一次模型调用产出全部资产节→ 增量策展落盘。

    force：整文档重总结（AI 改写方法）——该类别**全部**经验（含已总结）作素材；
    dry_run：只产新 md 不写盘（预览与落盘逐字一致，用户采纳走 apply_rewritten_skill）。

    归纳层门禁（总纲 /）：无模型 → 直接返回 ``model_required``，
    **不产出任何方法正文**（旧卡原样保留）；有模型但这次没拿到内容 →
    ``model_failed`` / ``empty_result``，同样不写卡。方法正文只有模型能产。
    """
    if force:
        experiences = list(store.iter_experiences(
            trunk=trunk, category=category, include_distilled=True))
    else:
        experiences = store.pending_experiences(trunk, category)
    if not experiences:
        return {"status": "no_pending", "file": None, "count": 0}
    # 触发日志：档 A 复盘 / 档 B 阈值触发留审计件——
    # 回查"这条固化是被哪个触发器、在什么计数状态下放进来的"
    if source != "manual":
        try:
            store.log_trigger(f"{source}_distill",
                              {"trunk": trunk, "category": category,
                               "pending": len(experiences)})
        except Exception as exc:
            logger.warning("触发日志落盘失败（不影响蒸馏）: %s", exc)

    existing = store.read_skill(trunk, category)
    # 归纳层门禁（总纲）：没接模型 → 不写卡、不覆盖、不产出任何正文，
    # 只如实回一句"要接模型"并保留上次内容（kept_previous 供 UI 提示）。
    if not llm.model_available(store):
        logger.info("未接入模型，跳过蒸馏 %s/%s（保留上次内容）", trunk, category)
        return {"ok": False, "status": "model_required", "file": None,
                "count": len(experiences), "message": MODEL_REQUIRED_MESSAGE,
                "kept_previous": bool((existing or "").strip()),
                "generated_at": skill.provenance_of(existing)[1]}
    sections: dict[str, str] | None = None
    model_ok = False
    call_failed = False
    prompt = build_distill_prompt(experiences, existing)
    try:
        raw = llm.call_model(store, [{"role": "user", "content": prompt}])
        sections = parse_playbook(raw)
        if _sections_have_body(sections):
            model_ok = True
        else:
            # 模型回了字但三节皆空（照抄标题／只回免责声明／格式跑偏都算）——
            # 与"没回"同等对待，绝不写一张空卡冒充成果
            logger.warning("模型输出解析后三节皆空，本次不产出方法卡")
            sections = None
    except Exception as exc:
        call_failed = True
        logger.warning("蒸馏模型调用失败，本次不产出方法卡: %s", exc)
    if dry_run:
        # 预览必须是真·AI 产物：调不通就直说，不拿别的东西冒充
        if not model_ok:
            return _no_content_result("model_failed", MODEL_FAILED_MESSAGE,
                                      len(experiences), existing)
    if sections is None:
        # 没拿到模型产出 → 不落卡（"配了但调不通"与"回了空"都不写）
        return _no_content_result(
            "model_failed" if call_failed else "empty_result",
            MODEL_FAILED_MESSAGE if call_failed else EMPTY_RESULT_MESSAGE,
            len(experiences), existing)

    # 首次蒸馏无旧文件时全量写入；否则 delta 合并（模型已在 prompt 里拿到旧版）
    version = _parse_version(existing)

    # W3-03/05：frontmatter 记录来源经验 id（下钻引用链）+ 质量评分
    # （high = 来源 ≥3 且含用户确认；medium = 来源 ≥3；low = 来源 <3）
    # 用户确认 = 用户反馈（g_source=user）或被纠正（corrected，用户纠正即确认）
    ids = [str(e["id"]) for e in experiences if e.get("id")]
    n_user = sum(1 for e in experiences
                 if e.get("g_source") == "user" or e.get("corrected")
                 or e.get("user_valid"))
    if len(ids) >= 3 and n_user:
        confidence = "high"
    elif len(ids) >= 3:
        confidence = "medium"
    else:
        confidence = "low"
    # R1 智能命名：蒸馏同一次模型调用里起名（说人话的短名，非术语）。
    # 用户手改过名字（name_source=manual）→ 代码侧硬保证不覆盖，模型输出作废。
    old_name, old_source = _parse_name_head(existing)
    raw_name = (sections.get("方法名") or "").strip()
    if raw_name:
        raw_name = raw_name.splitlines()[0].lstrip("- ").strip()
    name = None
    name_source = "auto"
    if old_source == "manual" and old_name:
        name, name_source = old_name, "manual"
    elif raw_name and raw_name not in ("（无）", "(无)"):
        name, name_source = raw_name, "auto"
    elif old_name:
        name, name_source = old_name, (old_source or "auto")
    # 溯源：created = 首次蒸馏日期（旧文件读回沿用；没有 → 今天）
    import re as _re2

    created = None
    if existing:
        m_created = _re2.search(r"^>\s*created:\s*(\S+)", existing, _re2.M)
        if m_created:
            created = m_created.group(1)
    now = datetime.now(timezone.utc)
    head = _playbook_head(
        trunk, category, version=version,
        updated=utcnow(),
        source_exps=", ".join(ids) or "（无）", confidence=confidence,
        name=name, name_source=name_source,
        created=created or now.strftime("%Y-%m-%d"),
        # 内容溯源（总纲）：能走到这里的正文一定来自模型
        content_source=skill.CONTENT_SOURCE_MODEL, generated_at=skill.now_iso())
    body_sections = []
    for sec_name in ("标准流程", "成功要点", "失败模式"):
        content = (sections.get(sec_name) or "（无）").strip()
        body_sections.append(f"## {sec_name}\n{content}")
    deprecated_note = (sections.get("过时项标记") or "（无）").strip()

    # 淘汰保护：旧 playbook 全文快照进 deprecated/（30 天可恢复）
    # （dry_run 预览零写盘，快照也跳过——采纳时由 apply_rewritten_skill 补）
    if existing and not dry_run:
        store.snapshot_skill(trunk, category, version, existing)

    md = head + "\n".join(body_sections) + "\n"
    # 空卡红线（真机：模型返回空 → 旧卡被三节"（无）"覆盖，还报 success）
    # 模型给了字但拼出来仍三节皆空 → 拒绝落盘（不复写旧卡、也不写空卡占位）
    if not playbook_has_body(md):
        logger.warning("蒸馏产物三节皆空，拒绝落盘 %s/%s", trunk, category)
        return _no_content_result("empty_result", EMPTY_RESULT_MESSAGE,
                                  len(experiences), existing)
    # 超阈值压缩
    if len(md.splitlines()) > 200:
        try:
            md = llm.call_model(store, [{"role": "user", "content": COMPRESS_PROMPT.format(playbook=md)}])
            md = head + md
        except Exception as exc:
            logger.warning("playbook 压缩失败，保留原样: %s", exc)

    # R6：写盘前兜底归一化旧中文键 → ASCII 键（模型照抄旧资产/压缩残留都转干净）
    md = normalize_marks(md)
    # 双门机器复标：失败模式三态 + 成功要点新要点标记，
    # 在压缩之后做——模型只写正文，标记与计数由确定性规则最终判定
    try:
        md = gate.remark_playbook(md, store, trunk, category)
    except Exception as exc:
        logger.warning("双门复标失败，沿用模型标记: %s", exc)
    if dry_run:
        # 预览到此为止：返回的 md 与正常落盘逐字一致（同一 head/压缩/复标链）
        return {"status": "preview", "md": md, "old_md": existing or "",
                "count": len(experiences), "version": version}
    path = store.write_skill(trunk, category, md)

    # —— 策展守卫：经验→playbook 这步的可审计映射 + 保真兜底 ——
    # 纯确定性：新增行是否有来源依据、旧版已固化失败是否被整批丢弃（坍缩）。
    # 只判不杀：可疑落 guard 事件+通知，回滚走 write_skill 前已留的 deprecated 快照。
    guard_report = None
    try:
        from . import curation_guard

        guard_report = curation_guard.check_distill(md, existing, experiences)
        if guard_report["verdict"] == "suspicious":
            _warn = (f"策展守卫：{trunk}/{category} 产出可疑"
                     f"（无源行 {int(guard_report['unsupported_ratio'] * 100)}%）")
            if guard_report["lost_solidified"]:
                _warn += ("；丢失已固化失败 "
                          f"{len(guard_report['lost_solidified'])} 条、无淘汰声明")
            _warn += "——可回退 deprecated 快照核验"
            store.append_event("guard", _warn, path=f"{trunk}/{category}",
                               n=len(guard_report.get("unsupported") or []))
    except Exception as exc:
        logger.warning("策展守卫异常（不影响蒸馏）: %s", exc)

    # W3-01：失败分支——纠正补丁与 playbook 同次蒸馏产出
    fixes_file = None
    try:
        fixes_file = _gen_fixes(store, trunk, category, experiences)
    except Exception as exc:
        logger.warning("纠正补丁蒸馏失败（playbook 不受影响）: %s", exc)

    # 偏好增量（先留旧版快照供通知 diff）
    pref_before = store.read_preferences(trunk) or ""
    _merge_preferences(store, trunk, sections.get("偏好增量", ""))

    # 偏好超预算自整理
    try:
        compact_preferences(store, trunk)
    except Exception as exc:
        logger.warning("偏好自整理失败（保留原样）: %s", exc)
    pref_after = store.read_preferences(trunk) or ""

    # changelog（每次策展记录改了什么；蒸馏节点携带版本号，
    # 固化时回填标记源复盘节点——学习历程可看来源轨迹）
    entry = f"蒸馏 {trunk}/{category}（{source}）：{len(experiences)} 条经验 → v{version}"
    if deprecated_note and deprecated_note not in ("（无）", "(无)"):
        entry += f"；淘汰：{deprecated_note[:120]}"
    if fixes_file:
        entry += "；纠正补丁已更新"
    store.append_event("distill", entry, path=f"{trunk}/{category}",
                       ver=f"v{version}", src=source, n=len(experiences))

    # 打标已蒸馏
    store.mark_experiences_distilled([e["id"] for e in experiences if e.get("id")])

    # 固化回填（信息量控制·阀门二；：严格双门）——只给实际
    # 支撑了「已固化」失败模式（计数门+复现门通过）的批次经验来源
    # 复盘节点标 solidified=v{version}；蒸馏仅有 [Watching]/[Pending] 产出时
    # 不再提前标固化。节点缺失（被删/被封顶裁掉）静默 False，不中断蒸馏。
    for agent, sid in sorted(gate.solid_backed_session_ids(
            store, trunk, category, experiences)):
        store.mark_solidified(agent, sid, f"v{version}")

    # 通知中心：首次沉淀 / 升级 / 新坑固化 / 偏好新增
    _push_distill_notices(store, trunk, category, version, len(experiences),
                          confidence, name, existing, md,
                          pref_before, pref_after)

    return {"ok": True, "status": "success", "file": str(path),
            "count": len(experiences), "version": version, "fixes": fixes_file,
            "confidence": confidence, "name": name, "guard": guard_report,
            "content_source": skill.CONTENT_SOURCE_MODEL}


def apply_rewritten_skill(store: Store, trunk: str, category: str,
                          md: str) -> dict | None:
    """整文档 AI 重写的预览被用户采纳后落盘。

    预览 md 自带头部（版本号在预览时已定）→ 逐字写入不再加工；
    旧版先进 deprecated/ 快照（与蒸馏管道同款淘汰保护，30 天可恢复）。
    不重复打标/通知/补丁/偏好——那些是蒸馏副作用，重写只换文档正文。
    """
    if not md or not md.strip():
        return None
    existing = store.read_skill(trunk, category)
    md = normalize_marks(md)
    m = _VERSION_HEAD_RE.search(md)
    if m:
        version = int(m.group(1))
    elif existing:
        version = _parse_version(existing)
    else:
        version = 1
    if existing:
        store.snapshot_skill(trunk, category, version, existing)
    path = store.write_skill(trunk, category, md)
    store.append_event(
        "distill", f"AI 整方法重写 {trunk}/{category}（用户采纳预览）→ v{version}",
        path=f"{trunk}/{category}", ver=f"v{version}")
    return {"file": str(path), "version": version}


# ---------- 档 B：阈值兜底 ----------

AUTO_HIGH_G_THRESHOLD = 3    # 高 G 经验 ≥3 条（旧口径，保留供其它处参考）
AUTO_PENDING_THRESHOLD = 10  # 或待蒸馏总数 ≥10 条


def _should_auto_distill(exps: list[dict]) -> bool:
    """证据加权门槛。

    - ≥1 条 L1（用户显式）→ 触发
    - ≥2 条 L2（会话确定性成功）→ 触发
    - ≥4 条 L3（模型自评）且来自 ≥2 个不同 session → 触发；session 只见一个
      （含全缺失，说明无法核验独立性）→ 需 ≥5 条，防"同场景湊数"。
    中性收尾（neutral）不计入正证据（没被骂≠成功）。
    """
    high = [e for e in exps
            if gsignal.should_inject(float(e.get("G") or 0)) and not e.get("neutral")]
    n_l1 = n_l2 = n_l3 = 0
    sessions: set[str] = set()
    for e in high:
        st = gsignal.evidence_strength(e)
        if st == "l1":
            n_l1 += 1
        elif st == "l2":
            n_l2 += 1
        elif st == "l3":
            n_l3 += 1
        if e.get("session_id"):
            sessions.add(str(e["session_id"]))
    # rule 坑卡走读取视图已是升档 G（复现≥3 或 user_valid → 0.55），故已并入
    # 上面的 high：用户确认坑 = l1、跨会话复现坑 = l2 → 天然触发。
    # 未复现的单次坑卡（G=0.4）不进 high，不促蒸馏（宁缺毋滥）。
    if n_l1 >= 1 or n_l2 >= 2:
        return True
    return n_l3 >= (4 if len(sessions) >= 2 else 5)


def pending_categories(store: Store) -> list[tuple[str, str]]:
    cats: dict[tuple[str, str], int] = {}
    for e in store.iter_experiences():
        key = (e.get("trunk") or "其他", e.get("category") or "未分类")
        cats[key] = cats.get(key, 0) + 1
    return list(cats.keys())


def auto_check(store: Store, verbose: bool = False) -> list[dict]:
    """阈值兜底蒸馏（防 session 边界识别不到时漏蒸馏）。返回执行结果。"""
    results = []
    for trunk, category in pending_categories(store):
        exps = store.pending_experiences(trunk, category)
        if not _should_auto_distill(exps) and len(exps) < AUTO_PENDING_THRESHOLD:
            continue
        try:
            r = distill(store, trunk, category, source="threshold")
            results.append(r)
            if verbose and r.get("status") == "success":
                print(f"[distill] 阈值兜底 {trunk}/{category}: {r['count']} 条 → {r['file']}")
        except Exception as exc:
            logger.warning("自动蒸馏失败 %s/%s: %s", trunk, category, exc)
            results.append({"status": "error", "trunk": trunk, "category": category, "error": str(exc)})
    # W4：工作流洞察检测（确定性规则，与蒸馏同轮；失败不杀循环）
    try:
        from ..insight import suggest

        new_cards = suggest.suggest(store, list(store.iter_experiences(include_distilled=True)))
        for c in new_cards:
            if verbose:
                print(f"[insight] 新建议卡（{c['type']}）：{c['text'][:60]}")
    except Exception as exc:
        logger.warning("洞察检测失败（不杀常驻）: %s", exc)
    return results


# ---------- 失败模式否决 ----------

def remove_failure_mode(store: Store, trunk: str, category: str, text: str) -> bool:
    """用户否决：从 playbook 失败模式节删除对应条目（三态标记均可，兼容旧中文键）。

    人的判断压过机器归纳；changelog 留痕，条目进不了 deprecated
    （playbook 是活文件，整文件淘汰保护已在每次蒸馏前做快照）。
    """
    md = store.read_skill(trunk, category)
    if not md:
        return False
    text = text.strip()
    kept, removed = [], False
    prefixes = (f"- {FAILURE_SOLID_MARK}", f"- {FAILURE_PENDING_MARK}",
                f"- {FAILURE_WATCH_MARK}")
    for line in md.splitlines():
        s = normalize_marks(line.strip())
        if s.startswith(prefixes):
            body = s
            for p in prefixes:
                body = body.removeprefix(p).strip()
            if body == text or body.startswith(text):
                removed = True
                continue
        kept.append(line)
    if not removed:
        return False
    store.write_skill(trunk, category, "\n".join(kept) + "\n")
    store.append_event("veto", f"用户否决失败模式 {trunk}/{category}：{text[:60]}",
                       path=f"{trunk}/{category}")
    return True


def failure_mode_trajectory(store: Store, trunk: str, category: str) -> list[dict]:
    """「查看轨迹」：回溯到原始低 G 经验（失败模式的来源池）。

    playbook 条目是模型抽象，不保留与原始经验的精确映射——轨迹展示该类别
    全部低 G/被纠正经验（按时间倒序），诚实呈现"教训从哪些经历来"。
    """
    out = []
    for e in store.iter_experiences(trunk=trunk, category=category, include_distilled=True):
        if not gsignal.is_rule(e) and float(e.get("G") or 0) >= 0.5 \
                and not e.get("corrected"):
            continue
        if gsignal.is_rule(e):
            from . import mining as _mining

            out.append({
                "id": e.get("id"),
                "task": str(e.get("task") or "").split(":", 1)[-1],
                "state": str(e.get("state") or ""),
                "action": _mining.rule_line_text(e), "G": e.get("G"),
                "agent": e.get("agent", ""), "ts": str(e.get("ts", ""))[:10],
                "count": int(e.get("count") or 1),
            })
            continue
        out.append({
            "id": e.get("id"), "task": e.get("task", ""),
            "state": _prior_value(e, "state"),
            "action": _prior_value(e, "action"), "G": e.get("G"),
            "agent": e.get("agent", ""), "ts": str(e.get("ts", ""))[:10],
            "count": int(e.get("count") or 1),
        })
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


# ---------- 偏好重新归纳 / 自整理 ----------

PREFERENCE_BUDGET_TOKENS = 400  # 偏好节超一半总预算时自整理

PREF_REINDUCT_PROMPT = """用户在「{trunk}」类任务上的历史经验中，以下条目被用户纠正过或价值较低，
说明它们反映了用户的真实偏好（用户觉得该怎么做、反感什么）。

归纳成一份偏好画像：只写可复用的决策风格/口味/取舍，每条一行，以"- "开头，
不超过 8 条，具体到能直接指导写作。不要写一次性细节。

纠正/低价值经验：
{exps}

直接输出偏好行（以"- "开头的多行文本）："""

PREF_COMPACT_PROMPT = """以下是用户的偏好画像，条目偏多会互相稀释。合并近义条目、
改写成更短的版本（每条一行，以"- "开头，不超过 8 条），不得丢失用户确认过的条目
（带「{mark}」标记的行必须原样保留，一字不改）。直接输出结果：

{prefs}"""


def reinduct_preferences(store: Store, trunk: str) -> dict:
    """手动「重新归纳」：模型从纠正/低 G 经验重生成偏好；
    带 [UserConfirmed] 的行受保护，不被覆盖。

    无模型时返回 no_model（调用方 409 兜底"先去接模型"），不裸调 call_model
    抛 RuntimeError（与 review/scan 的 model_available 守卫同型）。

    熔断 open 与"无模型"同形降级——原来只查
    model_available，冷却期内点「重新归纳」会把 CircuitOpenError 抛到 API 层
    （未处理异常 → 500），而不是 409 的可操作提示。"""
    if not llm.model_available(store) or llm.circuit_open(store):
        return {"status": "no_model"}
    exps = [e for e in store.iter_experiences(trunk=trunk, include_distilled=True)
            if e.get("corrected") or float(e.get("G") or 0) < 0.5]
    if not exps:
        return {"status": "no_data"}
    lines = []
    for e in exps[:40]:
        parts = [f"{e.get('task', '')}: {e.get('action', '')}"]
        if e.get("state"):
            parts.append(f"状态={e['state']}")
        if e.get("corrected"):
            parts.append("被纠正")
        lines.append(" | ".join(str(p) for p in parts))
    prompt = PREF_REINDUCT_PROMPT.format(trunk=trunk, exps="\n".join(f"- {x}" for x in lines))
    raw = llm.call_model(store, [{"role": "user", "content": prompt}])
    new_lines = [ln.strip() for ln in raw.splitlines()
                 if ln.strip().startswith("-") and ln.strip() != "-"]
    if not new_lines:
        return {"status": "no_data"}

    existing = normalize_marks(store.read_preferences(trunk) or "")
    confirmed = [ln for ln in existing.splitlines() if USER_CONFIRM_MARK in ln]
    body = "\n".join(confirmed + new_lines)
    head = f"# {trunk} · 偏好画像\n\n> 自动归纳，可编辑\n\n"
    store.write_preferences(trunk, head + body + "\n")
    store.append_event(
        "pref-reinduct",
        f"偏好重新归纳 {trunk}：{len(confirmed)} 条确认保留 / {len(new_lines)} 条新归纳",
        trunk=trunk)
    return {"status": "ok", "confirmed": len(confirmed), "inducted": len(new_lines)}


def compact_preferences(store: Store, trunk: str) -> dict:
    """偏好节超 400 token 时自动合并近义条目。

    用户确认过的行原样保留；其余行交模型合并成更短版本。"""
    from ..proxy.inject import estimate_tokens

    md = normalize_marks(store.read_preferences(trunk) or "")
    if not md:
        return {"status": "skipped"}
    bullets = [ln for ln in md.splitlines() if ln.strip().startswith("-")]
    if estimate_tokens("\n".join(bullets)) <= PREFERENCE_BUDGET_TOKENS:
        return {"status": "skipped"}
    prompt = PREF_COMPACT_PROMPT.format(prefs="\n".join(bullets), mark=USER_CONFIRM_MARK)
    raw = llm.call_model(store, [{"role": "user", "content": prompt}])
    new_lines = [ln.strip() for ln in raw.splitlines()
                 if ln.strip().startswith("-") and ln.strip() != "-"]
    if not new_lines:
        return {"status": "skipped"}
    confirmed = {ln.strip() for ln in bullets if USER_CONFIRM_MARK in ln}
    kept_confirmed = [ln.strip() for ln in new_lines if ln.strip() in confirmed]
    others = [ln for ln in new_lines if ln not in confirmed]
    for ln in sorted(confirmed - {x for x in kept_confirmed}):
        others.append(ln)  # 模型漏掉的确认行补回
    body = "\n".join(kept_confirmed + others)
    head_lines = [ln for ln in md.splitlines() if not ln.strip().startswith("-")]
    store.write_preferences(trunk, "\n".join(head_lines).rstrip() + "\n\n" + body + "\n")
    store.append_event(
        "pref-self",
        f"偏好自整理 {trunk}：{len(bullets)} 条 → {len(kept_confirmed) + len(others)} 条",
        trunk=trunk)
    return {"status": "ok", "before": len(bullets), "after": len(kept_confirmed) + len(others)}
