"""模板库注册表（+ W4 矩阵重设计）：读取 app/rules/templates/<lang>/<id>.md。

- 6 类目（c1 架构与设计 … c6 工作流与流程）× 5 优先级（p0 红线 … p4 优化），
  旧领域（营销/写作/…）降级为 tags（映射）
- 每个模板每种支持语言一版；C5 红线 7 语全量，结构层 zh/en 全量、
  其余 5 语缺原生范本时回退 en 并标注 native=False（降级标注工作流）
- 导入 = 模板正文拷贝到用户数据目录 rules/<id>.md（用户可直接改，改完即生效）
  + 写 rules.json（生效方式四档；hard-hook 仅 P0 可用且 P0 强制，file 已废弃）
"""

from __future__ import annotations

from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"
FALLBACK_LANG = "en"
SUPPORTED_LANGS = {"zh", "en", "de", "es", "fr", "ja", "ko"}

# 类目 id → UI 文案 key（zh 源串，走 t() 翻译）；顺序即展示顺序
CATEGORIES: list[tuple[str, str]] = [
    ("c1", "架构与设计"),
    ("c2", "代码风格与格式"),
    ("c3", "测试与验证"),
    ("c4", "文档与沟通"),
    ("c5", "安全与合规"),
    ("c6", "工作流与流程"),
]

# 优先级 → UI 文案 key；P0 在前（红标），同类目内按此顺序排模板
PRIORITIES: list[tuple[str, str]] = [
    ("p0", "P0 红线"),
    ("p1", "P1 必须"),
    ("p2", "P2 应该"),
    ("p3", "P3 建议"),
    ("p4", "P4 优化"),
]

_PRIORITY_RANK = {p: i for i, (p, _) in enumerate(PRIORITIES)}


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    """解析 '---\\nkey: value\\n---\\n正文'。格式由本仓库控制，手工解析不引依赖。

    支持 `key: |` 块标量（dos/donts 多行列表）：后续缩进行并入该键，
    去掉行首 '- ' 后以 '; ' 连接成单串存储。
    """
    if not raw.startswith("---"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    meta: dict[str, str] = {}
    lines = parts[1].strip().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" not in line:
            i += 1
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if v == "|":
            block: list[str] = []
            i += 1
            while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
                item = lines[i].strip()
                if item.startswith("- "):
                    item = item[2:].strip()
                if item:
                    block.append(item)
                i += 1
            meta[k] = "\n".join(block)  # 换行连接：条目自身可能含分号
            continue
        meta[k] = v
        i += 1
    body = parts[2].lstrip("\n")
    return meta, body


# 模板目录含数百个 md，此前每次 list_templates / get_template
# 都全量 read_text + 解析 frontmatter（模板页每次打开/切语言都触发，且
# _load_any 会连读当前语言 + en 回退两个目录）。改为按目录内容签名缓存。
# 签名取每个文件的 (名, mtime_ns, 字节数)——用 stat 而非目录 mtime：
# Windows 上目录 mtime 不随文件内容更新，只认目录 mtime 会读到陈旧正文。
_DIR_CACHE: dict[str, tuple[tuple, dict[str, dict]]] = {}


def _dir_signature(d: Path) -> tuple:
    try:
        return tuple(sorted((f.name, st.st_mtime_ns, st.st_size)
                            for f in d.glob("*.md")
                            for st in (f.stat(),)))
    except OSError:
        return ()


def _load_dir(lang: str) -> dict[str, dict]:
    d = TEMPLATES_DIR / lang
    if not d.exists():
        _DIR_CACHE.pop(lang, None)
        return {}
    sig = _dir_signature(d)
    hit = _DIR_CACHE.get(lang)
    if hit is not None and hit[0] == sig:
        # 返回浅拷贝：调用方会给条目补 native/served_by，不能让它写进缓存
        return {tid: dict(t) for tid, t in hit[1].items()}
    out: dict[str, dict] = {}
    for f in sorted(d.glob("*.md")):
        meta, body = _parse_frontmatter(f.read_text(encoding="utf-8"))
        tid = meta.get("id", f.stem)
        out[tid] = {
            "id": tid,
            "name": meta.get("name", tid),
            "category": meta.get("category", ""),
            "priority": meta.get("priority", "p3"),
            "layer": meta.get("layer", "structure"),
            "trigger_default": meta.get("trigger_default", "smart"),
            "tags": [x.strip() for x in meta.get("tags", "").split(";") if x.strip()],
            "keywords": [k.strip() for k in meta.get("keywords", "").split(";") if k.strip()],
            "description": meta.get("description", ""),
            "dos": [x for x in meta.get("dos", "").splitlines() if x.strip()],
            "donts": [x for x in meta.get("donts", "").splitlines() if x.strip()],
            "source": meta.get("source", "built-in"),
            "from": meta.get("from", ""),  # 旧 ID 别名（W4-07 用户规则迁移用）
            "body": body.strip(),
        }
    _DIR_CACHE[lang] = (sig, out)
    return {tid: dict(t) for tid, t in out.items()}


def _load_any(lang: str) -> dict[str, dict]:
    """当前语言的模板 + 缺失键回退 en（结构层 5 语无原生范本时的降级路径）。

    每个模板带 native（是否有当前语言原生范本）与 served_by（实际内容的语言）。
    M-N9: 当 lang == FALLBACK_LANG 时避免重复遍历同一目录。"""
    if lang == FALLBACK_LANG:
        merged = _load_dir(lang)
        for tid, t in merged.items():
            t["native"] = True
            t["served_by"] = lang
    else:
        local = _load_dir(lang)
        merged = _load_dir(FALLBACK_LANG)
        merged.update(local)
        for tid, t in merged.items():
            t["native"] = tid in local
            t["served_by"] = lang if t["native"] else FALLBACK_LANG
    return merged


def list_templates(lang: str) -> list[dict]:
    """按类目分组返回（类目顺序 = CATEGORIES）；类目内按优先级排（P0 在前）+ id。"""
    by_id = _load_any(lang)
    out = []
    for cat_id, label_key in CATEGORIES:
        # M-N10: 合并过滤与排序为一次遍历（避免先过滤再排序的两遍操作）
        items = sorted(
            [v for v in by_id.values() if v["category"] == cat_id],
            key=lambda t: (_PRIORITY_RANK.get(t.get("priority", "p3"), 99), t["id"]))
        if not items:
            continue
        out.append({"id": cat_id, "label_key": label_key, "templates": items})
    return out


def get_template(lang: str, tid: str) -> dict | None:
    return _load_any(lang).get(tid)


def import_template(store, lang: str, tid: str, trigger: str | None = None,
                    keyword: str | None = None, force: bool = False) -> dict:
    """导入模板 = 拷贝正文到数据目录 rules/<tid>.md + upsert rules.json。

    返回落库的规则 dict。rule.file 指向数据目录里的 md——inject 优先读文件，
    用户改完文件即生效；text 字段保留快照作回退。force=True 绕过 hard-hook 约束。
    """
    t = get_template(lang, tid)
    if t is None:
        raise KeyError(f"未知模板: {tid}")
    if trigger == "file":
        raise ValueError("file 生效方式已废弃，请用「manual + 关键词」")
    if trigger not in (None, "always", "smart", "manual", "hard-hook"):
        raise ValueError(f"未知生效方式: {trigger}")
    # W4：hard-hook 仅 P0 红线可用；P0 导入时 trigger 锁定 hard-hook（不接受其他值）
    if t.get("priority") == "p0":
        trigger = "hard-hook"
        # H-O3：P0 红线必须带 donts 反例（规范已有，这里兜底防坏模板）
        if not t.get("donts"):
            raise ValueError(f"P0 红线模板缺 donts 反例（{tid}），不能导入")
    elif trigger == "hard-hook" and not force:
        raise ValueError("hard-hook 仅 P0 红线模板可用（force=True 可绕过）")
    store.write_rule_file(f"rules/{tid}.md", t["body"] + "\n")  # 落盘走 store
    rule = {
        "id": f"tpl-{tid}",
        "name": t["name"],
        "text": t["body"],
        "file": f"rules/{tid}.md",
        "template_id": tid,
        "template_priority": t.get("priority", ""),
        "imported_from_lang": t["served_by"],
        "trigger": trigger or t["trigger_default"],
        "keyword": keyword or (t["keywords"][0] if t["keywords"] else ""),
        "enabled": True,
        # H-O3：反例随规则落库（编辑器「绝不」栏预填 + 注入时拼在应当后）
        "donts": [str(x) for x in t.get("donts", [])],
    }
    store.upsert_rule(rule, force=force)
    return rule
