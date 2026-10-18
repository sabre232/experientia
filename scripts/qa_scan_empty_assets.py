# -*- coding: utf-8 -*-
"""只读盘点：数据目录里还有没有"空资产被当成果"（事故的同类风险面）。

事故现场：本地模型返回空字符串 → 方法卡被写成三节"（无）"、升版本、标 confidence: high、
还报 success。方法卡这一层已加护栏（`engine_curation.playbook_has_body`，见 746464f 与
本次提交），本脚本排查**其余资产**有没有同样的口子：

① 空方法卡（skills/*/*.md 三节皆无正文）
② 空纠正补丁（skills/*/*_fixes.md）
③ 空偏好画像（preferences/*.md）
④ rules.json 存在但 0 条规则 / 规则正文为空
⑤ 已生成但为空的导出（exports/*.md）
⑥ 已生成但为空的 Skill 版本（generated_skills/*/v*.md）

只报告、不改写盘行为（方案：先只加告警）。

只读保证：
- 打桩 `Store._init_expdb`——宁可停用 SQLite 索引也不触发重建，避免与在跑的引擎
  抢 experience.db / engine.lock（方案的只读口径）；
- 只调 store 的读方法 + 只列目录，不写任何文件。
  注：`store.load_rules()` 可能触发 store 自身的幂等 schema 迁移写，与引擎启动同路径。

用法：uv run python scripts/_qa_scan_empty_assets.py [数据目录]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PLACEHOLDERS = ("（无）", "(无)")


def _is_blank(text: str | None) -> bool:
    t = (text or "").strip()
    return (not t) or t in PLACEHOLDERS


def _body_chars(text: str | None) -> int:
    """正文字数：去掉空行、frontmatter/引用行（>）、标题行（#）与"（无）"占位行。

    占位行必须去掉—— 事故的本质就是"（无）"被当成了内容。
    """
    keep = [ln for ln in (text or "").splitlines()
            if ln.strip() and ln.strip() not in PLACEHOLDERS
            and not ln.lstrip().startswith((">", "#"))]
    return len("\n".join(keep).strip())


def main(argv: list[str]) -> int:
    data_dir = (Path(argv[1]) if len(argv) > 1
                else Path(os.path.expanduser("~/.experientia")))

    import app.store.store as ss
    ss.Store._init_expdb = lambda self: None  # type: ignore[method-assign]  # noqa: E731

    from app.distill.engine_curation import playbook_has_body
    from app.distill.export import EXPORTS_DIRNAME
    from app.distill.skill import GENERATED_DIR

    store = ss.Store(data_dir)
    if not data_dir.is_dir():
        print(f"数据目录不存在：{data_dir}")
        return 1

    findings: list[tuple[str, str, str]] = []  # (类别, 位置, 说明)
    checked = 0

    # ① 方法卡 + ② 纠正补丁
    for s in store.list_skills():
        trunk, category = s.get("trunk"), s.get("category")
        checked += 1
        md = store.read_skill(trunk, category) or ""
        if not md.strip():
            findings.append(("方法卡", f"skills/{trunk}/{category}.md", "文件不存在或全空"))
        elif not playbook_has_body(md):
            findings.append(("方法卡", f"skills/{trunk}/{category}.md",
                             "三节皆无正文（空卡顶着 confidence）"))
        fixes = store.read_fixes(trunk, category)
        if fixes is not None and _is_blank(fixes):
            findings.append(("纠正补丁", f"skills/{trunk}/{category}_fixes.md",
                             "文件存在但正文为空/占位"))

    # ③ 偏好画像
    for trunk in store.list_preference_trunks():
        checked += 1
        md = store.read_preferences(trunk)
        if md is not None and _body_chars(md) == 0:
            findings.append(("偏好画像", f"preferences/{trunk}.md", "正文为空/占位"))

    # ④ 规则
    rules = store.load_rules()
    checked += 1
    if (data_dir / "rules.json").is_file() and not rules:
        findings.append(("规则", "rules.json", "容器存在但 0 条规则"))
    for r in rules:
        if _is_blank(r.get("text")) and r.get("enabled", True):
            findings.append(("规则", f"rules.json#{r.get('id')}",
                             f"已启用但正文为空：{r.get('name')!r}"))

    # ⑤ 导出产物
    exports = data_dir / EXPORTS_DIRNAME
    if exports.is_dir():
        for f in sorted(exports.glob("*.md")):
            checked += 1
            if _body_chars(f.read_text(encoding="utf-8", errors="replace")) == 0:
                findings.append(("导出", f"{EXPORTS_DIRNAME}/{f.name}", "导出成功但正文为空"))

    # ⑥ 生成的 Skill 版本
    gen = data_dir / GENERATED_DIR
    if gen.is_dir():
        for f in sorted(gen.glob("*/v*.md")):
            checked += 1
            if _body_chars(f.read_text(encoding="utf-8", errors="replace")) == 0:
                findings.append(("生成 Skill", f"{GENERATED_DIR}/{f.parent.name}/{f.name}",
                                 "版本已落盘但正文为空"))

    print(f"数据目录：{data_dir}")
    print(f"盘点对象：{checked} 项（方法卡/补丁/偏好/规则/导出/生成 Skill）")
    if not findings:
        print("结论：未发现 playbook 之外的同类「空资产被当成果」——干净。")
        return 0
    print(f"结论：发现 {len(findings)} 处同类风险：")
    by_kind: dict[str, int] = {}
    for kind, where, why in findings:
        by_kind[kind] = by_kind.get(kind, 0) + 1
        print(f"  [{kind}] {where} —— {why}")
    print("分项：" + "，".join(f"{k} {v} 处" for k, v in sorted(by_kind.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
