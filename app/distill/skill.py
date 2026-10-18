"""经验转 Skill：把经验/playbook 生成标准 SKILL.md（agentskills.io 开放标准）。

两条路径产出同一格式：
- 路径 A（一键类目）：该类别全部经验 + 现有 playbook
- 路径 B（勾选精选）：用户选中的经验列表（可跨类别）

frontmatter + 固定正文节（When to Use / Procedure / Pitfalls / Verification）。
"""

from __future__ import annotations

import difflib
import json
import re
from datetime import datetime
from pathlib import Path

from ..store.store import Store
from . import gsignal, llm

# ---------- 内容溯源（总纲：写入点在本模块） ----------

CONTENT_SOURCE_MODEL = "model"  # 模型产出（可随模型更新）
CONTENT_SOURCE_NONE = "none"    # 非模型产出（旧的本机整理产物 / 未接入模型时的历史内容）

_PLACEHOLDER = ("（无）", "(无)")


def now_iso() -> str:
    """ISO8601 本地时间（generated_at 口径；带时区偏移，展示层直接可读）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _prov_value(text: str, key: str) -> str:
    m = re.search(rf"^>\s*{key}\s*:\s*(.+?)\s*$", text or "", re.M)
    return m.group(1).strip() if m else ""


def provenance_of(md: str | None) -> tuple[str, str]:
    """读 playbook / 方法卡 frontmatter 的 ``content_source`` / ``generated_at``。

    缺失字段返回 ``""``（**来源未知**）——不报错、不补默认值，展示层据此不挂
    降级条（总纲：旧卡无该字段 → 视为未知）。
    """
    text = md or ""
    return _prov_value(text, "content_source"), _prov_value(text, "generated_at")


def set_provenance(md: str, source: str, generated_at: str = "") -> str:
    """写入/覆盖 frontmatter 的 ``content_source``（+ 可选 ``generated_at``）。

    只动头部（首个 ``## `` 之前），**章节名与正文一律不改**（防歪清单 #3）；
    已有同名键 → 原行替换，没有 → 插到头部最后一条 ``> `` 行之后
    （无 ``> `` 行则跟在标题行之后）。``source``/``generated_at`` 为空则该行不写。
    """
    lines = (md or "").splitlines()
    end = next((i for i, ln in enumerate(lines)
                if ln.strip().startswith("## ")), len(lines))
    head, rest = lines[:end], lines[end:]
    kept: list[str] = []
    for ln in head:
        if re.match(r"^>\s*(content_source|generated_at)\s*:", ln):
            continue  # 旧值丢弃，位置统一重排
        kept.append(ln)
    pos = 0
    for i, ln in enumerate(kept):
        if ln.startswith(">") or ln.startswith("#"):
            pos = i + 1
    new = []
    if source:
        new.append(f"> content_source: {source}")
    if generated_at:
        new.append(f"> generated_at: {generated_at}")
    out = "\n".join(kept[:pos] + new + kept[pos:] + rest)
    return out + ("\n" if (md or "").endswith("\n") else "")

SKILL_PROMPT = """把以下经验整理成一份标准 Skill（SKILL.md 的正文部分，不要 frontmatter）。

{context}

相关经验（G≥0.5 为成功经验，G<0.5/被纠正为踩坑经验）：
{exps}

输出格式（严格按以下要求，无内容的章节写"（无）"）：
第一行：name: 给这个 skill 起一个 4-14 字的中文短名（像给同事一句话讲清"这是干嘛的"，例：投标书报价核算；不要出现 skill/playbook/蒸馏/类别 等机制词，不要包含项目名）
第二行：alias: 英文别名（只允许小写字母、数字、连字符，≤30 字符，不能以连字符开头/结尾或出现连续连字符）
第三行起空一行，按以下章节输出：
## When to Use（何时使用）
- 什么任务/场景该用这个 skill
## Procedure（成功做法，来自 N 条验证经验）
1. 可执行的步骤（具体、参数化）
## Pitfalls（失败模式，来自 N 条踩坑经验）
- 什么不能做 + 为什么
## Verification（怎么确认做对了）
- 可检查的完成标准"""


def _split_skill_name(raw: str) -> tuple[str | None, str | None, str]:
    """R1：从模型输出头部抽 `name:`（说人话短名）/ `alias:`（ASCII 别名）两行。

    模型没按格式输出时安全降级：两值 None，正文原样返回。
    """
    lines = raw.splitlines()
    name = alias = None
    idx = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        m = re.match(r"^(name|alias)\s*[:：]\s*(.+)$", s, re.IGNORECASE)
        if m and (name is None or alias is None):
            key, val = m.group(1).lower(), m.group(2).strip()
            if key == "name" and name is None:
                name = val
            elif key == "alias" and alias is None:
                alias = val
            idx = i + 1
        else:
            break
    return name, alias, "\n".join(lines[idx:]).lstrip("\n")


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name.strip()).strip("-")
    return s or "skill"


def _valid_alias(s: str) -> bool:
    """agentskills.io 规范：name 字段 1-64 字符，仅 [a-z0-9-]，不以连字符
    开头/结尾、无连续连字符。别名 ≤30 字符（留足规范上限）。"""
    return bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s or "")) and len(s) <= 30


def _ascii_fallback(base: str) -> str:
    """没有合规 ASCII 名时的确定性兜底：小写化 + 非 [a-z0-9] 转连字符。"""
    s = re.sub(r"[^a-z0-9]+", "-", (base or "").lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")[:30].strip("-")
    return s or "experientia-skill"


def _fmt(e: dict) -> str:
    parts = [f"[G={e.get('G')}] {e.get('task', '?')}: {e.get('action', '?')}"]
    if e.get("state"):
        parts.append(f"踩坑={e['state']}")
    if e.get("outcome"):
        parts.append(f"结果={e['outcome']}")
    if e.get("corrected"):
        parts.append("被用户纠正")
    return " | ".join(str(p) for p in parts)


def _display(e: dict) -> dict:
    """rule 坑卡展示归一：task/action 是合并用指纹，SKILL.md 用模板句。"""
    if gsignal.is_rule(e):
        from . import mining

        e = dict(e)
        e["task"] = str(e.get("task") or "").split(":", 1)[-1]
        e["action"] = mining.rule_line_text(e)
    return e


def _fallback_skill_body(exps: list[dict], category: str | None) -> str:
    """模板版正文（蒸馏兜底方案）：原文罗列，不归纳。

    章节名与模型版输出一致（When to Use / Procedure / Pitfalls / Verification）；
    命名/版本化/frontmatter 复用不动（本函数只产正文）。
    """
    from . import dedupe

    exps = [_display(e) for e in exps]
    # rule 卡恒属失败域：进 Pitfalls，绝不因复现升档混成 Procedure
    high = [e for e in exps if gsignal.high_value_eligible(e)]
    low = [e for e in exps if not gsignal.high_value_eligible(e)]

    when = f"涉及 {category} 类任务时使用。" if category else "涉及同类任务时使用。"

    proc = dedupe.dedupe_lines(
        [(e.get("action") or "").strip() for e in high if (e.get("action") or "").strip()])
    proc_block = "\n".join(f"{i + 1}. {x}" for i, x in enumerate(proc)) or "（无）"

    pit_lines: list[str] = []
    kept: list[str] = []
    for e in low:
        text = (e.get("state") or e.get("action") or "").strip()
        if not text or any(dedupe.near_dup(text, k) for k in kept):
            continue
        pit_lines.append(f"- {text}")
        kept.append(text)
    pit_block = "\n".join(pit_lines) or "（无）"

    verify = dedupe.dedupe_lines(
        [(e.get("outcome") or "").strip() for e in high if (e.get("outcome") or "").strip()])
    verify_block = "\n".join(f"- {x}" for x in verify) or "（无）"

    return (
        f"## When to Use（何时使用）\n{when}\n\n"
        f"## Procedure（成功做法，来自 {len(high)} 条验证经验）\n{proc_block}\n\n"
        f"## Pitfalls（失败模式，来自 {len(low)} 条踩坑经验）\n{pit_block}\n\n"
        f"## Verification（怎么确认做对了）\n{verify_block}"
    )


def generate_skill(
    store: Store,
    trunk: str | None = None,
    category: str | None = None,
    selected: list[dict] | None = None,
    name: str | None = None,
    description: str | None = None,
    version: str = "1.0.0",
) -> dict:
    """生成 SKILL.md。selected 非空 = 路径 B（勾选，可跨类别）；否则路径 A（类别全量）。

    返回 {"md", "name", "description", "source_count"}；无模型/无经验时抛 RuntimeError。
    """
    pb_name = None  # 方法的显示名（frontmatter > name:）
    if selected:
        exps = selected
        context = "用户从经验库中精选了以下条目（可跨类别），整理成一份综合 skill。"
        default_name = name or _slug(trunk or "精选")
    else:
        if not trunk or not category:
            raise RuntimeError("缺少 trunk/category")
        exps = list(store.iter_experiences(trunk=trunk, category=category,
                                           include_distilled=True))
        playbook = store.read_skill(trunk, category)
        context = f"类别 {trunk}/{category}" + (
            f"的现有 playbook（已验证的方法，优先沿用）：\n{playbook}" if playbook else "")
        m = re.search(r"^>\s*name:\s*(.+?)\s*$", playbook, re.M) if playbook else None
        pb_name = m.group(1).strip() if m and m.group(1).strip() else None
        default_name = name or pb_name or _slug(f"{trunk}-{category}")
    if not exps and not (trunk and category and store.read_skill(trunk, category)):
        raise RuntimeError("没有可整理的经验")
    exps = [_display(e) for e in exps]  # rule 卡指纹→模板句（LLM 素材与兜底正文统一）

    # 蒸馏兜底方案 /：没配（switcher）/ 配了调不通（异常）→ 模板版正文
    m_name: str | None = None
    m_alias: str | None = None
    if llm.model_available(store):
        prompt = SKILL_PROMPT.format(
            context=context or "（无）",
            exps="\n".join(f"{i + 1}. {_fmt(e)}" for i, e in enumerate(exps[:50])) or "（无）",
        )
        try:
            raw = llm.call_model(store, [{"role": "user", "content": prompt}])
            m_name, m_alias, body = _split_skill_name(raw)
        except Exception:
            body = _fallback_skill_body(exps, category)
    else:
        body = _fallback_skill_body(exps, category)

    # R1 命名优先级：用户指定 > 方法显示名（已随方法页展示，保持一致）
    # > 模型起的说人话短名（路径 B 或方法未命名时）> 机械兜底（项目-类别）。
    display = ((name or "").strip() or (pb_name or "").strip()
               or (m_name or "").strip() or default_name)
    display = display.strip("「」\"'").strip() or default_name
    if len(display) > 40:
        display = display[:40]
    # agentskills.io 规范：frontmatter name 必须 ASCII（a-z0-9-），中文展示名
    # 进 metadata.display_name（规范允许的附加字段位）
    ascii_name = next((c.strip() for c in (name, m_alias)
                       if c and _valid_alias(c.strip())), None) \
        or _ascii_fallback(display)

    if not description:
        if selected:
            description = (f"从 {len(exps)} 条精选经验整理的方法、步骤与避坑清单。")
        elif trunk and category:
            description = f"{trunk}/{category} 类任务的方法、步骤与避坑清单。"
        else:
            description = "从经验整理的方法、步骤与避坑清单。"
    md = (
        f"---\n"
        f"name: {ascii_name}\n"
        f"description: {description}\n"
        f"metadata:\n"
        f"  version: \"{version}\"\n"
        f"  display_name: {display}\n"
        f"---\n\n"
        f"# {display}\n\n"
        f"{body.strip()}\n"
    )
    return {"md": md, "name": display, "alias": ascii_name,
            "description": description, "source_count": len(exps)}


# ---------- 版本化 ----------

GENERATED_DIR = "generated_skills"


def _skill_dir(store: Store, name: str) -> Path:
    return store.dir(GENERATED_DIR) / _slug(name)


def _skill_md_has_body(md: str) -> bool:
    """SKILL.md 去掉 YAML frontmatter 后是否还有真实正文——空卡守卫。"""
    if not md or not md.strip():
        return False
    body = md
    if md.lstrip().startswith("---"):
        parts = md.split("---", 2)
        if len(parts) >= 3:
            body = parts[2]
    return bool(body.strip())


def save_skill_version(store: Store, name: str, md: str, description: str,
                       source_count: int, created_at: str | None = None) -> dict:
    """把一份 SKILL.md 存为版本 N（N = 已有版本数 + 1）。返回版本信息。

    M2 空卡守卫（同 llm/engine_curation 的拒塌缩红线）：正文为空则抛 ValueError，
    绝不产出空版本、不覆盖已有资产；v{n}.md 与 meta.json 各自原子写
    （走 store._write_tmp_rename），先写内容后写索引——崩溃只留一个可被下一版
    复用的孤儿 v{n}.md，meta 失配窗口不存在。
    """
    from datetime import datetime, timezone

    if not _skill_md_has_body(md):
        raise ValueError("Skill 内容为空，未保存任何版本")

    d = _skill_dir(store, name)
    d.mkdir(parents=True, exist_ok=True)
    meta_file = d / "meta.json"
    meta = {}
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    versions = meta.get("versions", [])
    n = len(versions) + 1
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    store._write_tmp_rename(d / f"v{n}.md", md)
    versions.append({"n": n, "created_at": created_at,
                     "description": description, "source_count": source_count})
    meta["name"] = name
    meta["versions"] = versions
    store._write_tmp_rename(
        meta_file, json.dumps(meta, ensure_ascii=False, indent=2))
    return {"name": name, "version": n, "created_at": created_at,
            "file": str(d / f"v{n}.md")}


def list_skill_versions(store: Store, name: str) -> list[dict]:
    """某 skill 的版本清单（新在前）。"""
    meta_file = _skill_dir(store, name) / "meta.json"
    if not meta_file.exists():
        return []
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(reversed(meta.get("versions", [])))


def read_skill_version(store: Store, name: str, n: int) -> str | None:
    f = _skill_dir(store, name) / f"v{n}.md"
    return f.read_text(encoding="utf-8") if f.exists() else None


def diff_versions(store: Store, name: str, old: int, new: int) -> str:
    """两版 unified diff（供 GUI 回看）。"""
    a = read_skill_version(store, name, old) or ""
    b = read_skill_version(store, name, new) or ""
    lines = difflib.unified_diff(a.splitlines(), b.splitlines(),
                                 fromfile=f"v{old}", tofile=f"v{new}", lineterm="")
    out = "\n".join(lines)
    return out or "（两版内容相同）"
