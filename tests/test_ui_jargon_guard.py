""" #3「零概念」守卫：用户可见串不得含内部术语。

 验收时发现：13+ 条用户可见串含"引擎/注入"（接入页、回炉页、经验页、
成长叙事、hooks 页），德/法/西语译文还带对应译词，且**没有任何测试管这件事**。
本文件堵住这个口子，两层扫描：

1. **语言包层**：7 个 .po 的 msgstr 按各语言违禁词表扫描（拉丁语系用正则防误伤，
   如 engineering 不是 Engine）；
2. **代码层**：app/ 下所有 t("…") 字面量按中文违禁词表扫描——新键即使还没进
   语言包也当场红（折叠串取首行，跨行折行术语由语言包层兜底）。

违禁词口径 =  #3（引擎/注入/隔离/G 信号/蒸馏原理）+ "回灌"（本产品对"经验送回
agent"的内部叫法，已统一改为"送达/用上"）。如出现正当用法，改测试前
先想清楚是否该放进用户视野——默认答案是不该。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LOCALES = REPO / "app" / "gui" / "locales"

# 中文违禁词
ZH_TERMS = ("引擎", "注入", "隔离", "G 信号", "蒸馏原理", "回灌")

# 其他语言对应词；拉丁语系用正则（\b 防 engineering 这类误伤，前缀覆盖变格）
LANG_TERMS: dict[str, tuple[str, ...]] = {
    "en": (r"(?i)\bengine\b", r"(?i)\binject", r"(?i)reinject"),
    "ja": ("エンジン", "注入", "隔離", "還流"),
    "ko": ("엔진", "주입", "격리", "회류"),
    "fr": (r"(?i)\bmoteur\b", r"(?i)\binject", r"(?i)réinjection",
           r"(?i)\bisolation\b"),
    "de": (r"(?i)\bengine\b", r"(?i)injekt", r"(?i)injizier",
           r"(?i)\bisolation\b", r"(?i)rückgabe"),
    "es": (r"(?i)\bmotor\b", r"(?i)inyecc", r"(?i)\baislamiento\b",
           r"(?i)reinyecci"),
}

_ENTRY_RE = re.compile(
    r'msgid\s+((?:"(?:[^"\\]|\\.)*"\s*)+)\nmsgstr\s+((?:"(?:[^"\\]|\\.)*"\s*)+)')
_QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _entries(po_path: Path) -> list[tuple[str, str]]:
    """.po → [(msgid, msgstr)]（跳过空 msgstr，即未翻译条目不误伤）。"""
    text = po_path.read_text(encoding="utf-8")
    out = []
    for mid, mstr in _ENTRY_RE.findall(text):
        key = "".join(_QUOTED_RE.findall(mid))
        val = "".join(_QUOTED_RE.findall(mstr))
        if val:
            out.append((key, val))
    return out


def test_zh_catalog_has_no_internal_terms():
    po = LOCALES / "zh" / "LC_MESSAGES" / "messages.po"
    bad = [(k, s) for k, s in _entries(po)
           if any(t in s for t in ZH_TERMS)]
    assert not bad, "中文用户可见串含内部术语：\n" + "\n".join(
        f"  [{t}] {s[:60]}" for k, s in bad for t in ZH_TERMS if t in s)


@pytest.mark.parametrize("lang", sorted(LANG_TERMS))
def test_translation_catalogs_have_no_jargon(lang: str):
    po = LOCALES / lang / "LC_MESSAGES" / "messages.po"
    terms = LANG_TERMS[lang]
    bad = []
    for k, s in _entries(po):
        for t in terms:
            if re.search(t, s):
                bad.append((t, s[:60]))
                break
    assert not bad, f"{lang} 译文含内部术语：\n" + "\n".join(
        f"  [{t}] {s}" for t, s in bad)


def test_code_t_keys_have_no_internal_terms():
    """代码里 t("…") 的字面量键也不许含违禁词（新键未进语言包也拦得住）。"""
    bad = []
    for py in sorted((REPO / "app").rglob("*.py")):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            m = re.search(r't\(\s*"([^"]*)"', line)
            if not m:
                continue
            key = m.group(1)
            hit = next((t for t in ZH_TERMS if t in key), None)
            if hit:
                bad.append(f"  {py.name}:{i} [{hit}] {key[:50]}")
    assert not bad, "代码 t() 键含内部术语：\n" + "\n".join(bad)
