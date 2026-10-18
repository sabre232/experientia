"""经验导出：五粒度 + 全量打包。

- 全部确定性产出标准 md（不花模型调用）；内容是"人话"版，不暴露 jsonl 原始格式
- 资产/导出内容不随界面语言变化，固定中文格式
- 落盘到数据目录 exports/，GUI 提示路径 + 打开文件夹
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import shutil
from pathlib import Path

from ..store.store import Store

logger = logging.getLogger("experientia.distill.export")

EXPORTS_DIRNAME = "exports"


def _today() -> str:
    return datetime.date.today().isoformat()


def _date_of(e: dict) -> str:
    return str(e.get("ts", ""))[:10]


def _is_failure(e: dict) -> bool:
    """踩坑经验：被用户纠正，或 G < 0.5（gsignal 口径）；
    rule 坑卡恒属失败域（复现升档≠成功经验，方案）。"""
    if e.get("corrected"):
        return True
    if str(e.get("g_source") or "") == "rule":
        return True
    g = e.get("G")
    return g is not None and float(g) < 0.5


def _exp_block(e: dict, failure: bool) -> str:
    if str(e.get("g_source") or "") == "rule":
        # 展示归一：task/action 是跨会话合并用指纹，导出文档用模板句
        from . import mining as _mining

        e = dict(e)
        e["task"] = str(e.get("task") or "").split(":", 1)[-1]
        e["action"] = _mining.rule_line_text(e)
    head = f"### {e.get('category') or '未分类'} - {e.get('task') or '?'}"
    src = " · ".join(x for x in (e.get("agent", ""), e.get("model", ""), _date_of(e)) if x)
    lines = [head, f"- 来源：{src or '未知'}"]
    if e.get("state"):
        lines.append(f"- 踩坑：{e['state']}")
    if e.get("action"):
        label = "教训" if failure else "做法"
        lines.append(f"- {label}：{e['action']}")
    if e.get("outcome"):
        lines.append(f"- 结果：{e['outcome']}")
    if int(e.get("count") or 1) > 1:
        lines.append(f"- 出现 {int(e.get('count'))} 次")
    return "\n".join(lines)


def _exps_header(title: str, exps: list[dict]) -> str:
    fails = sum(1 for e in exps if _is_failure(e))
    ok = len(exps) - fails
    return (
        f"# {title}\n\n"
        f"> 导出时间：{_today()}\n"
        f"> 经验条数：{len(exps)} 条（成功 {ok} / 避坑 {fails}）\n"
    )


def _exps_body(exps: list[dict]) -> str:
    ok = [e for e in exps if not _is_failure(e)]
    bad = [e for e in exps if _is_failure(e)]
    parts = []
    if ok:
        parts.append("## 成功经验\n" + "\n\n".join(_exp_block(e, False) for e in ok))
    if bad:
        parts.append("## 失败模式\n" + "\n\n".join(_exp_block(e, True) for e in bad))
    return "\n\n".join(parts)


def _settled_bullets(md: str) -> tuple[list[str], list[str]]:
    """playbook 提炼：成功 ← 成功要点（缺省回退标准流程）、失败 ← 失败模式。"""
    return (_bullets_of(md, "成功要点") or _bullets_of(md, "标准流程"),
            _bullets_of(md, "失败模式"))


def _settled_section(store: Store, trunk: str | None, category: str | None,
                     include: bool) -> list[str]:
    """模板「## 已沉淀的方法（如有）」节：playbook 的成功策略 / 失败模式要点。

    单一类别 → 该 playbook 的两组要点（与文档示例同构）；单一项目（无类别）→
    逐类别 `### 类别` 小节；全量/精选（ids）不附（范围与 playbook 不对应，
    避免噪音）。playbook 不存在或无可提炼内容 → 返回空（调用方不附节）。
    """
    if not include or not trunk:
        return []
    if category:
        blocks = [(None, store.read_skill(trunk, category))]
    else:
        blocks = [(s.get("category"), store.read_skill(trunk, str(s.get("category"))))
                  for s in store.list_skills() if s.get("trunk") == trunk]
    lines: list[str] = []
    for cat, md in blocks:
        if not md:
            continue
        dos, donts = _settled_bullets(str(md))
        if not (dos or donts):
            continue
        if not lines:
            lines = ["## 已沉淀的方法（如有）", ""]
        if cat:
            lines.append(f"### {cat}")
        if dos:
            lines += ["**成功策略**", *(f"- {x}" for x in dos), ""]
        if donts:
            lines += ["**失败模式**", *(f"- {x}" for x in donts), ""]
    return lines


def export_experiences(store: Store, trunk: str | None = None,
                       category: str | None = None,
                       ids: list[str] | None = None) -> dict:
    """粒度 1：某类别（或全部）经验条目原始轨迹。

    R5：ids 非空 = 精选导出（只出勾选的经验，跨类别也允许——与导出 Skill
    路径 B 同构）；缺省 = 范围内全量。
    模板：经验条（成功/失败两节）+ 已沉淀的方法（如有）——
    蒸馏过的类别把 playbook 要点附在经验后面，一份文件既有轨迹也有结论。"""
    exps = list(store.iter_experiences(trunk=trunk, category=category,
                                       include_distilled=True))
    if ids:
        idset = {str(i) for i in ids}
        exps = [e for e in exps if str(e.get("id")) in idset]
    if ids:
        title = f"经验导出：精选 {len(exps)} 条"
    elif trunk and category:
        title = f"经验导出：{trunk} / {category}"
    elif trunk:
        title = f"经验导出：{trunk}"
    else:
        title = "经验导出：全部经验"
    if not exps:
        return {"filename": _slug_filename(title) + ".md", "md": _exps_header(title, exps)}
    md = _exps_header(title, exps) + "\n" + _exps_body(exps)
    settled = _settled_section(store, trunk, category, include=not ids)
    if settled:
        md += "\n\n" + "\n".join(settled)
    return {"filename": _slug_filename(title) + ".md", "md": md + "\n"}


_CONF_LABEL = {"high": "已验证", "medium": "部分验证", "low": "待验证"}


def _head_value(md: str, key: str) -> str | None:
    m = re.search(rf"^>\s*{key}:\s*(.+?)\s*$", md, re.M)
    if not m:
        return None
    v = m.group(1).strip()
    return v or None


def _provenance_section(store: Store, trunk: str, category: str,
                        md: str) -> list[str]:
    """/ 溯源节（方案 A：弹层与 md 同口径）：首次沉淀/最近更新/
    沉淀依据（该类别全部经验，成功/踩坑拆分）/置信度。全缺 → 空。"""
    lines: list[str] = []
    created = _head_value(md, "created")
    if created:
        lines.append(f"- 首次沉淀：{created[:10]}")
    updated = _head_value(md, "updated")
    version = _head_value(md, "version")
    if updated:
        v_s = f"（v{version}）" if version else ""
        lines.append(f"- 最近更新：{updated[:10]}{v_s}")
    try:
        exps = list(store.iter_experiences(trunk=trunk, category=category,
                                           include_distilled=True))
    except Exception:
        exps = []
    if exps:
        fails = sum(1 for e in exps if _is_failure(e))
        lines.append(f"- 沉淀依据 {len(exps)} 条经验"
                     f"（成功 {len(exps) - fails} / 踩坑 {fails}），"
                     f"可在经验库按类别回看")
    conf = _head_value(md, "confidence")
    if conf in _CONF_LABEL:
        lines.append(f"- 置信度：{_CONF_LABEL[conf]}")
    if not lines:
        return []
    return ["## 溯源", ""] + lines


def export_playbook(store: Store, trunk: str, category: str) -> dict:
    """粒度 2：某类别完整 playbook（成功流程 + 失败模式）+ 溯源节。"""
    md = store.read_skill(trunk, category)
    if md is None:
        raise LookupError(f"{trunk}/{category} 还没有沉淀方法（先蒸馏）")
    parts = [f"# 方法导出：{trunk} / {category}\n\n",
             f"> 导出时间：{_today()}\n\n", md.strip()]
    prov = _provenance_section(store, trunk, category, md)
    if prov:
        parts.append("\n\n" + "\n".join(prov))
    return {"filename": f"方法-{trunk}-{category}.md", "md": "".join(parts) + "\n"}


def export_playbooks(store: Store, pairs: list[tuple[str, str]]) -> dict:
    """R5 粒度 2 精选版：多方法一次导出（每方法一节，标题 = 显示名 + 两级路径）。

    pairs = [(trunk, category), ...]；不存在的跳过；全都不存在 → LookupError。
    """
    sections = []
    for trunk, category in pairs:
        md = store.read_skill(trunk, category)
        if md is None:
            continue
        m = re.search(r"^>\s*name:\s*(.+?)\s*$", md, re.M)
        name = m.group(1).strip() if m and m.group(1).strip() else None
        sections.append((trunk, category, name, md.strip()))
    if not sections:
        raise LookupError("还没有可导出的方法（先在方法页总结）")
    lines = ["# 方法导出", "", f"> 导出时间：{_today()}",
             f"> 方法条数：{len(sections)} 个", ""]
    for trunk, category, name, md in sections:
        title = f"{name}（{trunk} / {category}）" if name else f"{trunk} / {category}"
        lines += [f"## {title}", "", md, ""]
    label = sections[0][2] if len(sections) == 1 and sections[0][2] else "精选"
    return {"filename": f"方法-{label}-{_today()}.md", "md": "\n".join(lines) + "\n"}


def export_preferences(store: Store, trunk: str) -> dict:
    """粒度 3：某主干的偏好画像（决策风格）。"""
    md = store.read_preferences(trunk)
    if md is None:
        raise LookupError(f"{trunk} 还没有偏好画像")
    return {
        "filename": f"偏好画像-{trunk}.md",
        "md": (f"# 偏好画像导出：{trunk}\n\n"
               f"> 导出时间：{_today()}\n"
               f"> 你的决策风格画像，可交给新同事 / 新 agent\n\n" + md.strip() + "\n"),
    }


def _phase_overview(exps: list[dict]) -> str:
    """阶段概览：总量（成功/避坑）+ 按类别分布——复盘先看分布再看条目。"""
    fails = sum(1 for e in exps if _is_failure(e))
    by_cat: dict[str, list[dict]] = {}
    for e in exps:
        by_cat.setdefault(f"{e.get('trunk') or '未分类'} / "
                          f"{e.get('category') or '未分类'}", []).append(e)
    lines = ["## 阶段概览", ""]
    lines.append(f"- 经验总量：{len(exps)} 条（成功 {len(exps) - fails} / 避坑 {fails}）")
    lines.append(f"- 时间范围：{min(_date_of(e) for e in exps)} ~ "
                 f"{max(_date_of(e) for e in exps)}")
    lines.append("- 类别分布：")
    for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        c_fails = sum(1 for e in items if _is_failure(e))
        lines.append(f"  - {cat}：{len(items)} 条（成功 {len(items) - c_fails} / "
                     f"避坑 {c_fails}）")
    return "\n".join(lines) + "\n"


def export_phase(store: Store, trunk: str | None = None, category: str | None = None,
                 since: str | None = None, until: str | None = None) -> dict:
    """粒度 4：阶段任务经验（某时间段汇总，默认本月）。

    模板：阶段概览（总量/时间范围/类别分布）+ 经验条（成功/失败两节）。"""
    today = datetime.date.today()
    if not until:
        until = today.isoformat()
    if not since:
        since = today.replace(day=1).isoformat()
    exps = [e for e in store.iter_experiences(trunk=trunk, category=category,
                                              include_distilled=True)
            if since <= _date_of(e) <= until]
    scope = "/".join(x for x in (trunk, category) if x) or "全部"
    title = f"阶段经验：{scope}（{since} ~ {until}）"
    if not exps:
        return {"filename": _slug_filename(title) + ".md",
                "md": _exps_header(title, exps) + "\n（该时间段内没有经验）"}
    return {"filename": _slug_filename(title) + ".md",
            "md": (_exps_header(title, exps) + "\n" + _phase_overview(exps) + "\n"
                   + _exps_body(exps) + "\n")}


def _priority_of(trigger: str) -> str:
    """自定义 Hook 缺优先级时按 trigger 降级推断（M1 信息架构重构）。"""
    return {"hard-hook": "p0", "always": "p1", "smart": "p2",
            "manual": "p4"}.get(trigger, "p2")


def _list_field(label: str, items: list[str]) -> str:
    """dos/donts 序列化：非空 = 块标量（与模板 frontmatter 同构）；空 = 键后留空。"""
    if not items:
        return f"{label}:"
    return f"{label}: |\n" + "\n".join(f"  - {x}" for x in items)


CUSTOM_RULE_CATEGORY = "custom"  # 自定义 hook 的分组键（不进模板类目 CATEGORIES）


def _rule_category(r: dict, templates) -> str:
    """hook 的导出分组：模板导入 → 模板类目（c1..c6），其余 → 自定义。"""
    if r.get("template_id"):
        tpl = templates.get_template(
            r.get("imported_from_lang") or "zh", r["template_id"])
        if tpl and tpl.get("category"):
            return str(tpl["category"])
    return CUSTOM_RULE_CATEGORY


def _hook_block(r: dict, templates) -> list[str]:
    """单 hook 导出块：frontmatter（对齐模板格式）+ ### 标题 + 规则正文。"""
    trigger = r.get("trigger", "smart")
    pri = r.get("template_priority") or _priority_of(trigger)
    dos: list[str] = []
    donts: list[str] = []
    source = "user"
    if r.get("template_id"):
        tpl = templates.get_template(
            r.get("imported_from_lang") or "zh", r["template_id"])
        if tpl:
            dos = [str(x) for x in tpl.get("dos", [])]
            donts = [str(x) for x in tpl.get("donts", [])]
            source = tpl.get("source") or "template"
    # H-A0：显式 []（未配装，软停用）保持为 none，绝不回填成 all
    agents = r.get("agents")
    if agents is None:
        agents = ["*"]
    agents_s = ("all" if agents == ["*"]
                else ", ".join(str(a) for a in agents) if agents else "none")
    scope = r.get("scope")
    globs = r.get("globs") or []
    return [
        "---",
        f"id: hook-{r.get('id', '')}",
        f"name: {r.get('name', '')}",
        f"priority: {pri}",
        f"trigger: {trigger}",
        f"agents: {agents_s}",
        *( [f"globs: [{', '.join(str(g) for g in globs)}]" ]
           if scope == "glob" and globs else [] ),
        _list_field("dos", dos),
        _list_field("donts", donts),
        f"source: {source}",
        "---",
        f"### {r.get('name', '')}",
        "",
        str(r.get("text", "")).strip(),
        "",
    ]


def export_hooks(store: Store, ids: list[str] | None = None) -> dict:
    """粒度 6（M1 信息架构重构）：「我的 Hooks」整体导出为单个 md。

    每 hook 一节：frontmatter 对齐模板格式（id/name/priority/trigger/dos/
    donts/source）+ 规则正文。模板导入的 hook 从模板库补 dos/donts（P0 的
    donts 由模板保证必填）；自定义 hook 缺字段 → 空，priority 按 trigger
    降级推断。

    R5：ids 非空 = 只导出勾选的 hook（与导出 Skill 的精选同构）；
    H-A0：frontmatter 带 agents（生效工具，["*"] = 全部工具）。
    第 6 轮：按类目分组（对齐 Skill/md 导出的"分类 + 随意选"口径）——
    模板导入的 hook 按模板类目（CATEGORIES 顺序）归组，自定义 hook 归
    「自定义」组垫底；类目 = ## 节，hook 降为 ### 节（frontmatter 跟随 hook）。
    """
    from ..rules import registry as templates  # 延迟导入（引擎层内部依赖）

    rules = store.load_rules()
    if ids:
        idset = {str(i) for i in ids}
        rules = [r for r in rules if str(r.get("id")) in idset]
    label = f"（精选 {len(rules)} 条）" if ids else ""
    lines = [
        "# Hooks 导出",
        "",
        f"> 导出时间：{_today()}",
        f"> Hook 条数：{len(rules)} 条{label}",
        "",
    ]
    if not rules:
        lines.append("（还没有 Hook）")
    else:
        cat_label = {cid: zh for cid, zh in templates.CATEGORIES}
        groups: dict[str, list[dict]] = {}
        for r in rules:
            groups.setdefault(_rule_category(r, templates), []).append(r)
        order = [cid for cid, _ in templates.CATEGORIES
                 if cid in groups] + \
                ([CUSTOM_RULE_CATEGORY] if CUSTOM_RULE_CATEGORY in groups else [])
        for cid in order:
            lines += [f"## {cat_label.get(cid, '自定义')}", ""]
            for r in groups[cid]:
                lines += _hook_block(r, templates)
    return {"filename": f"Hooks导出-{_today()}.md",
            "md": "\n".join(lines) + "\n"}


def _bullets_of(md: str, section: str, limit: int = 5) -> list[str]:
    """取某 `## <section>` 节内的列表行（去编号/前缀，截断超长，最多 limit 条）。"""
    m = re.search(rf"^##\s+{re.escape(section)}[^\n]*\n(.*?)(?=^##\s|\Z)",
                  md, re.DOTALL | re.MULTILINE)
    if not m:
        return []
    out: list[str] = []
    for line in m.group(1).splitlines():
        s = line.strip()
        if s in ("", "（无）") or not re.match(r"^([-*]|\d+\.)\s+", s):
            continue
        s = re.sub(r"^([-*]|\d+\.)\s+", "", s).strip()
        if s and s not in out:
            out.append(s[:80])
        if len(out) >= limit:
            break
    return out


def with_skill_dodonts(md: str) -> str:
    """E-05（M1 信息架构重构）：给 SKILL.md frontmatter 补 dos/donts。

    从方法正文归纳：dos ← Procedure 节步骤、donts ← Pitfalls 节条目（各 ≤5
    条，块标量格式 = 模板 frontmatter 同构，走 Hooks 模板重设计）。
    正文某节无内容 → 对应字段留空键；frontmatter 已有 dos/donts 则不覆盖
    （幂等——重新生成/手动改过都不破坏）。
    """
    m = re.match(r"^---\n(.*?)\n---\n", md, re.DOTALL)
    if not m:
        return md
    head = m.group(1)
    if re.search(r"^(?:dos|donts):", head, re.MULTILINE):
        return md
    dos = _bullets_of(md, "Procedure")
    donts = _bullets_of(md, "Pitfalls")

    def _field(label: str, items: list[str]) -> str:
        if not items:
            return f"{label}:"
        return f"{label}: |\n" + "\n".join(f"  - {x}" for x in items)

    return ("---\n" + head + "\n" + _field("dos", dos) + "\n"
            + _field("donts", donts) + md[m.end(1):])


def _tok_fmt(v: int | float) -> str:
    """token 数人话：≥1万 → N.N万。"""
    v = int(v or 0)
    return f"{v / 10000:.1f}万" if v >= 10000 else str(v)


def _affinity_block(key: str, a: dict) -> list[str]:
    """磨合度单类块：v2 口径——基线（前 3 个独立实例中位数）vs
    近期窗口（最近 5 个）中位数，主指标 = 磨合差值；百分比仅辅助展示。"""
    n = a.get("n", 0)
    if a.get("level") == "待积累":
        return [f"### {key.replace('/', ' / ')}", "",
                f"经验不足（{n} 次）→ 待积累"]
    base, recent = a.get("baseline") or {}, a.get("recent") or {}
    diff = int(a.get("diff") or 0)
    lines = [
        f"### {key.replace('/', ' / ')} · 磨合差值 {diff:+d}"
        f"（基线 {str(base.get('at', ''))[:10]} → 近期 {str(recent.get('at', ''))[:10]}）",
        "",
        f"- 修正轮数：基线中位 {base.get('fix', 0)} → 近期中位 {recent.get('fix', 0)}"
        f"（差值 {diff:+d}）",
        f"- 协作轮数：{base.get('req', 0)} → {recent.get('req', 0)}"
        f"（差值 {int(a.get('rounds_diff') or 0):+d}）",
    ]
    if (base.get("tokens") or recent.get("tokens")):
        lines.append(f"- token：{_tok_fmt(base.get('tokens', 0))} → "
                     f"{_tok_fmt(recent.get('tokens', 0))}")
    lines.append(f"- 磨合度：{a.get('level')}（样本 {n} 次）")
    if a.get("excluded"):
        lines.append("- 负例自查：基线本来就顺（修正中位数 0），不算改善样本")
    if a.get("sample_note"):
        lines.append(f"- 样本 {n} 次，结论仅供参考")
    return lines


def export_growth(store: Store, days: int = 30) -> dict:
    """粒度 5：成长报告（md）。

     重做：正文换成 growth_story 单一口径（结论 → 飞轮 → 资产 → 各助手
    → 每周 → 高分经验 → 里程碑），旧"按类别磨合度"降为文末附录——它仍是 
    的正式判据，但在"分类还没长出来"的库上会整节空掉，不该再当报告主体。
    md 里不画字符画（人读不懂终端块）：数值一律表格或数值行。
    """
    from . import growth_story

    s = store.growth_summary(days=days)
    today = datetime.date.today()
    from datetime import timedelta

    st = s.get("stage") or {}
    # md 导出固定中文口径：先本地化（否则 counts/range_short 会把模板字典打出来）
    story = growth_story.localize(growth_story.build(s), growth_story._zh)
    h = story["headline"]
    win = (f"{st.get('start', '')} ~ {st.get('end', '')}" if st.get("start")
           else f"{(today - timedelta(days=days - 1)).isoformat()} ~ "
                f"{today.isoformat()}")
    lines = [
        f"# 成长报告（{win}）",
        "",
        f"> 导出时间：{today.isoformat()}",
        f"> 覆盖：{story['counts']}",
        "",
        "## 结论",
        "",
    ]
    # 主句可能有多行：时间口径一句 +  类别判据加项（只取 [0] 会把判据丢掉）
    lines += growth_story.sections_text(story)["main"] + [""]
    if h.get("comparable"):
        lines += [f"- {h['sub_text']}",
                  f"- 平均：{h['from']} 回/次 → {h['to']} 回/次"]
        if h.get("drop") is not None:
            lines.append(f"- 降幅 {h['drop']}%")
    else:
        lines.append(f"- {h.get('sub_text', '')}")
    lines += ["", "## 经验飞轮", "", "| 环节 | 数量 |", "|---|---|"]
    for g in story["gears"]:
        lines.append(f"| {g['k']} | {g['v']} {g['u']} |")
    lines += ["", "## 攒下的东西", ""]
    for a in story["assets"]:
        lines.append(f"- {a['k']}：{a['v']} {a['u']}（{a['note']}）")
    if story["agents"]:
        lines += ["", "## 各助手磨合", "",
                  "| 助手 | 任务 | 纠正 | 头两周 → 最近 | 结论 |",
                  "|---|---|---|---|---|"]
        for r in story["agents"]:
            lines.append(f"| {r['name']} | {r['n']} | {r['corr']} "
                         f"| {r['trend']} | {r['chip']} |")
    if story["spark"]:
        lines += ["", "## 每周", "", "| 周 | 任务 | 返工回/次 |", "|---|---|---|"]
        for w in story["spark"]:
            lines.append(f"| {w['week']} | {w['sessions']} "
                         f"| {'—' if w['rate'] is None else w['rate']} |")
    if story["top"]:
        lines += ["", "## 最值钱的几条经验", ""]
        for x in story["top"]:
            lines.append(f"- {x['badge']} 分 · {x['text']}")
    ms = story["milestones"]
    lines += ["", f"## 里程碑{'（已解锁）' if ms['unlocked'] else '（还没解锁）'}", ""]
    lines += [f"- {x}" for x in (ms["unlocked"] or ms["next"])]
    if story["rest"]:
        lines += ["", "## 休整", ""]
        lines += [f"- {x}" for x in story["rest"]]

    # ---- 附录：按类别的磨合度明细 ----
    lines += ["", "---", "",
              "## 附：磨合度（基线前 3 次中位数 − 基线后 5 次中位数）",
              ""]
    affinity = s.get("affinity") or {}
    if not affinity:
        lines.append("（代理通道 session 不足，磨合度待积累——多跑几个同类任务即可）")
    else:
        improved = [int(a.get("diff") or 0) for a in affinity.values()
                    if not a.get("excluded") and int(a.get("diff") or 0) >= 1]
        if improved:
            avg = round(sum(improved) / len(improved))
            lines += [f"变好的类别平均比最初几次少走 {avg} 轮修正"
                      f"（仅统计变好的类别）", ""]
    level_rank = {"高": 0, "中": 1, "低": 2}
    for key, a in sorted(affinity.items(),
                         key=lambda kv: (level_rank.get(kv[1].get("level"), 9),
                                         kv[1].get("level") == "待积累", kv[0])):
        lines += _affinity_block(key, a) + [""]

    cumulative = s.get("cumulative") or {}
    if cumulative:
        total = sum(int(series[-1][1]) for series in cumulative.values())
        lines += [f"## 经验累积（共 {total} 条）", ""]
        for key, series in sorted(cumulative.items(), key=lambda kv: -kv[1][-1][1]):
            lines.append(f"- {key}：{int(series[-1][1])} 条 / {days} 天")

    # 成就记录
    try:
        from . import weekly_report
        ach = weekly_report.load_achievements(store)
    except Exception:
        ach = []
    if ach:
        lines += ["", "## 成就记录", ""]
        for a in ach:
            name = growth_story.ACH_NAME.get(str(a.get("type")),
                                             str(a.get("type") or ""))
            scope = a.get("scope", "")
            detail = (a.get("detail") or {}).get("text", "")
            lines.append(f"- {name}（{scope}）"
                         f" · 解锁于 {str(a.get('unlocked_at', ''))[:10]}"
                         + (f" · {detail}" if detail else ""))

    return {"filename": f"成长报告-{days}天-{today.isoformat()}.md",
            "md": "\n".join(lines) + "\n"}


def _slug_filename(title: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "-", title).strip("-")
    return s or "export"


def save_export(store: Store, filename: str, md: str) -> Path:
    """落到数据目录 exports/，返回路径（重名自动加序号）。"""
    out = store.data_dir / EXPORTS_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    path = out / filename
    i = 1
    while path.exists():
        stem, suffix = Path(filename).stem, Path(filename).suffix
        path = out / f"{stem}-{i}{suffix}"
        i += 1
    path.write_text(md, encoding="utf-8")
    return path


def export_all(store: Store, dest: Path | None = None) -> dict:
    """全量打包：所有 md 资产（skills/preferences/rules/exports/生成的 skill）+ changelog。

    dest 缺省 = 数据目录旁的 experientia-assets-<日期>/。返回 {"dest", "files"}。
    对数据目录只读（只拷不删不改）。
    """
    stamp = _today().replace("-", "")
    dest = Path(dest) if dest else store.data_dir.parent / f"experientia-assets-{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []

    def _copy_tree(src: Path, dst: Path, rel_prefix: str):
        if not src.is_dir():
            return
        for f in sorted(src.rglob("*.md")):
            rel = f.relative_to(src).as_posix()
            target = dst / rel_prefix / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            copied.append(f"{rel_prefix}/{rel}")

    _copy_tree(store.data_dir / "skills", dest, "skills")
    _copy_tree(store.data_dir / "preferences", dest, "preferences")
    _copy_tree(store.data_dir / "rules", dest, "rules")
    _copy_tree(store.data_dir / EXPORTS_DIRNAME, dest, "exports")
    _copy_tree(store.data_dir / "generated_skills", dest, "generated_skills")

    changelog = store.data_dir / "changelog.md"
    if changelog.exists():
        shutil.copy2(changelog, dest / "changelog.md")
        copied.append("changelog.md")

    (dest / "MANIFEST.json").write_text(json.dumps(
        {"exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
         "source": str(store.data_dir), "files": copied},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return {"dest": str(dest), "files": copied}
