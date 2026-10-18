# -*- coding: utf-8 -*-
"""i18n 孤儿词条扫描：找出「词典里还挂着、源码里再没人要」的 msgid。

背景：历次界面改版只往 .po 里加词、从不删词（只进不出），护栏又是单向检查
（源码 t() 的字面量必须在词典里，反之不管），孤儿会一直积灰。

存活判定（保守，宁漏不误杀）：msgid 只要命中以下任意一条就算**活着**——
  ① app/**/*.py 里任何一个字符串常量与其相等（覆盖 t("字面量") 和
     _TOOL_DESC 这类"变量传 t()"的数据表——后者 AST 抓不到 t() 调用，
     但字串本身是模块级常量）；
  ② app/rules/templates/**/*.md frontmatter 的 tags/keywords 分号项
     （hooks_page 领域下拉 t(tag) 数据传词，实测抓到 21 个 slug 差点误杀）；
  ③ 出现在 KEEP 白名单（运行时拼接等静态扫不到的特例）。
默认 dry-run 只报告；--apply 才从 7 份 .po 真删并重写（字节写，保 LF）。
删完必须跑 scripts/compile_locales.py 重编译 .mo。
用法：uv run --with babel python scripts/i18n_orphan_scan.py [--apply]
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
TEMPLATES = APP / "rules" / "templates"
LOCALES = ROOT / "app" / "gui" / "locales"
LANGS = ["de", "en", "es", "fr", "ja", "ko", "zh"]

# 静态扫不到但确实活着的特例（当前为空——发现一例登记一例，写明理由）
KEEP: set[str] = set()


def _live_strings() -> set[str]:
    """app/**/*.py 全部字符串常量 + 模板 frontmatter tags/keywords 项。"""
    out: set[str] = set()
    for py in APP.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            print(f"解析失败（跳过存活源收集）: {py}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.add(node.value)
    if TEMPLATES.exists():
        for md in TEMPLATES.rglob("*.md"):
            in_fm = False
            for line in md.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s == "---":
                    if in_fm:
                        break
                    in_fm = True
                    continue
                if in_fm and (s.startswith("tags:") or s.startswith("keywords:")):
                    val = s.split(":", 1)[1]
                    out.update(t.strip() for t in val.split(";") if t.strip())
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真删（默认只报告）")
    args = ap.parse_args()

    live = _live_strings() | KEEP
    # 逐语言收集孤儿，取并集报告（正常应 7 语一致；不一致本身就是词典漂移）
    orphans: dict[str, set[str]] = {}
    catalogs: dict[str, tuple[Path, object]] = {}
    for lang in LANGS:
        po = LOCALES / lang / "LC_MESSAGES" / "messages.po"
        with po.open("rb") as fh:
            cat = read_po(fh, locale=lang)
        catalogs[lang] = (po, cat)
        orphans[lang] = {
            # babel 的 Catalog 迭代本身不含 obsolete（它们躺在 catalog.obsolete
            # 里单独一格），故无需额外过滤
            str(m.id) for m in cat
            if m.id and str(m.id) not in live
        }

    union = set().union(*orphans.values())
    for mid in sorted(union):
        langs_hit = ",".join(l for l in LANGS if mid in orphans[l])
        print(f"孤儿: {mid[:64]!r}  [{langs_hit}]")
    print(f"共 {len(union)} 条孤儿")
    if len(union) > 1 and not union <= orphans.get("zh", set()):
        print("⚠ 各语言孤儿集合不一致（词典漂移），请人工核对")

    if not args.apply or not union:
        print("dry-run 结束（--apply 才删）" if union else "无孤儿，词典干净")
        return 0
    for lang in LANGS:
        po, cat = catalogs[lang]
        drop = orphans[lang]
        if not drop:
            continue
        for mid in drop:
            del cat[mid]
        with po.open("wb") as fh:  # 字节写：.po LF 铁律
            write_po(fh, cat, width=0)
        print(f"[{lang}] 已删 {len(drop)} 条")
    print("完成——请跑 scripts/compile_locales.py 重编译 .mo，再跑 tests/test_i18n.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
