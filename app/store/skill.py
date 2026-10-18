"""`Store` 的「方法卡（playbook）+ 纠正补丁」域 mixin。

从 `store.py` 的 `class Store` 拆出的第六个域。只做不动语义的搬家，约定：

1. 方法体逐字搬移，签名与返回值一律不变；
2. 共享状态（`data_dir`、`read_text_cached` / `invalidate_cache`、`_write_lock`）
   留在 `Store` 主体，mixin 通过 `self` 访问，**不复制状态**；
3. 需要模块级小工具时从 `._shared` 取，不 import `store.py`（避免循环导入）。

`*_fixes.md`（纠正补丁）与 playbook 同目录，但不属于方法清单（W3-01）。
"""

from __future__ import annotations

import logging
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from ._shared import _safe

logger = logging.getLogger("experientia.store")

# 从 store.py 随「方法卡」域搬来（growth_summary 的防作弊
# 判据要用它读 playbook 创建日期，见）。
_SKILL_CREATED_RE = re.compile(r"^>\s*created:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)


def _skill_created_date(md: str | None) -> str | None:
    """playbook frontmatter 的 `> created:` 日期（YYYY-MM-DD；无/解析失败 → None）。

     防作弊判据用：基线窗口内 playbook 已存在 → 基线不成立（growth_summary）。"""
    if not md:
        return None
    m = _SKILL_CREATED_RE.search(md)
    return m.group(1) if m else None


class SkillMixin:
    """`skills/<trunk>/<category>.md` 与 `*_fixes.md` 的路径 / 读 / 写 / 列。"""

    def skill_path(self, trunk: str, category: str) -> Path:
        return self.data_dir / "skills" / _safe(trunk) / (_safe(category) + ".md")

    def read_skill(self, trunk: str, category: str) -> str | None:
        return self.read_text_cached(self.skill_path(trunk, category))

    def list_skills(self) -> list[dict]:
        """playbook 清单（skills/<trunk>/<category>.md），方法页数据源。

        W3-01：`*_fixes.md`（纠正补丁）与 playbook 同目录，不属于方法清单。
        R1：frontmatter 的 `> name:`（AI/用户起的说人话名字）读出为 `name` 字段；
        没有 = None，展示层回退到「项目 / 类别」两级路径。
        """
        out: list[dict] = []
        root = self.data_dir / "skills"
        if not root.is_dir():
            return out
        for f in sorted(root.glob("*/*.md")):
            if f.name.endswith("_fixes.md"):
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            name = None
            try:
                m = re.search(r"^>\s*name:\s*(.+?)\s*$",
                               f.read_text(encoding="utf-8"), re.M)
                if m and m.group(1).strip():
                    name = m.group(1).strip()
            except OSError:
                pass
            out.append({"trunk": f.parent.name, "category": f.stem,
                        "path": str(f), "size": st.st_size, "mtime": st.st_mtime,
                        "name": name})
        return out

    # ---------- 纠正补丁（W3-01：skills/<trunk>/<category>_fixes.md） ----------

    def fixes_path(self, trunk: str, category: str) -> Path:
        return self.data_dir / "skills" / _safe(trunk) / (_safe(category) + "_fixes.md")

    def read_fixes(self, trunk: str, category: str) -> str | None:
        return self.read_text_cached(self.fixes_path(trunk, category))

    def write_fixes(self, trunk: str, category: str, md: str) -> Path:
        path = self.fixes_path(trunk, category)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写（同 write_preferences 的理由）
        self._write_tmp_rename(path, md)
        self.invalidate_cache(path)
        return path

    def write_skill(self, trunk: str, category: str, md: str) -> Path:
        path = self.skill_path(trunk, category)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写——方法卡是注入读路径的权威来源，
        # 半截文件会被直接注入给用户
        self._write_tmp_rename(path, md)
        self.invalidate_cache(path)
        return path

    def rename_skill(self, trunk: str, old_category: str, name: str | None,
                     new_category: str | None) -> dict:
        """R2 改名：改显示名，和/或迁移分类（两者至少给一个）。

        分类迁移范围：
        - playbook / *_fixes.md 文件移动，标题行重写为新类别；
        - experience.jsonl / sessions.jsonl 的 category 字段重写
          （成长/磨合度/洞察都是读时计算，自动跟随；changelog 是历史，原样保留）；
        - 既有注入覆盖（条目 id 内嵌 trunk/category）自动失效（stale），
          数量返回给 GUI 提示清理。
        迁移目标不得冲突：目标 playbook / 纠正补丁 / 该类别经验已存在 → ValueError。
        显示名写 frontmatter `> name:`（name_source=manual，后续蒸馏不覆盖）。
        """
        new_category = (new_category or "").strip() or old_category
        if name is None and new_category == old_category:
            raise ValueError("显示名和分类都没有变化")
        if name is not None and new_category == old_category:
                md = self.read_skill(trunk, old_category)
                m = re.search(r"^>\s*name:\s*(.+?)\s*$", md, re.M) if md else None
                cur_name = m.group(1).strip() if m else None
                if name.strip() in ("", cur_name):
                    raise ValueError("显示名和分类都没有变化")
        if new_category != old_category:
            if self.skill_path(trunk, new_category).exists():
                raise ValueError(f"类别「{new_category}」已存在方法文件，不能迁移过去")
            if self.fixes_path(trunk, new_category).exists():
                raise ValueError(f"类别「{new_category}」已有纠正补丁，不能迁移过去")
            if any(e.get("trunk") == trunk and e.get("category") == new_category
                   for e in self.iter_experiences(include_distilled=True)):
                raise ValueError(f"类别「{new_category}」下已有经验，不能迁移过去")

        # 将失效的注入覆盖数（id = sha1(kind|trunk|category|text)，旧类别不再匹配）
        stale = 0
        try:
            from ..proxy.inject import iter_injection_items

            overrides = self.load_overrides()
            stale = sum(1 for it in iter_injection_items(self, trunk, old_category)
                        if it["id"] in overrides)
        except Exception as exc:
            logger.warning("rename_skill 统计 stale 注入覆盖失败（GUI 提示会缺该项）: %s", exc)

        with self._write_lock:
            # ① 文件移动（playbook + 纠正补丁），标题行重写
            if new_category != old_category:
                self.invalidate_cache()  # 文件改名 → 全清（旧路径键不再有效）
                for read, write, path_fn in ((self.read_skill, self.write_skill, self.skill_path),
                                             (self.read_fixes, self.write_fixes, self.fixes_path)):
                    md = read(trunk, old_category)
                    if md is None:
                        continue
                    md = md.replace(f"# {trunk} / {old_category} ·",
                                    f"# {trunk} / {new_category} ·", 1)
                    write(trunk, new_category, md)
                    path_fn(trunk, old_category).unlink(missing_ok=True)
                # ② 经验 / session 的 category 字段重写（成长等读时计算自动跟随）
                # 经验只改 SQLite（唯一事实源，不再整文件重写 JSONL）；
                # 索引不可用才回退 JSONL 重写。sessions.jsonl 无索引，始终按行重写。
                if self._expdb is not None:
                    self._sync_experience_index_category(trunk, old_category,
                                                         new_category)
                else:
                    self._rewrite_category_field("experience.jsonl", trunk,
                                                 old_category, new_category)
                self._rewrite_category_field("sessions.jsonl", trunk,
                                             old_category, new_category)
                self.rebuild_category_index()  # ③ 类别索引随迁移重建（M-5）

            # ③ 显示名（frontmatter name 行，manual 来源蒸馏不覆盖）
            if name is not None:
                name = name.strip()
                if not name:
                    raise ValueError("显示名不能为空")
                md = self.read_skill(trunk, new_category)
                if md is None:
                    raise ValueError("方法文件不存在，无法改显示名（先总结成方法）")
                if re.search(r"^>\s*name:", md, re.M):
                    md = re.sub(r"^>\s*name:.*$", f"> name: {name}", md,
                                 count=1, flags=re.M)
                    md = re.sub(r"^>\s*name_source:.*$",
                                 "> name_source: manual", md, count=1, flags=re.M)
                else:
                    md = md.replace("\n> version:",
                                    f"\n> name: {name}\n> name_source: manual\n> version:",
                                    1)
                self.write_skill(trunk, new_category, md)

        self.append_event(
            "rename",
            f"改名 {trunk}/{old_category} → "
            f"{'「' + name + '」' if name is not None else ''}"
            f"{f' → 类别 {new_category}' if new_category != old_category else ''}"
            + (f"；{stale} 条已改写的注入条目失效（可在「模型会看到什么」页清理）"
               if stale else ""),
            path=f"{trunk}/{new_category}")
        return {"trunk": trunk, "category": new_category,
                "name": name, "stale_overrides": stale}

    def _rewrite_category_field(self, fname: str, trunk: str,
                                old_category: str, new_category: str) -> None:
        """把 jsonl 里 (trunk, old_category) 记录的 category 字段改成 new_category。

        按行重写（不依赖 id 字段，sessions.jsonl 无 id）。调用方持有 _write_lock。
        """
        def _rewrite(item):
            if item.get("trunk") == trunk and item.get("category") == old_category:
                item["category"] = new_category
            return item
        self._read_write_jsonl(self.data_dir / fname, _rewrite, trailing_newline=False)

    # 偏好画像的路径/读/写已搬到 app/store/preferences.py 的 PreferencesMixin。

    # ---------- deprecated 与 changelog ----------

    def deprecated_day_dir(self, *subparts: str) -> Path:
        """`deprecated/<UTC 日期>[/<子路径>]` 目录（含 mkdir）。

        淘汰/归档/坏行救回/迁移快照统一入口，日期口径集中在此。"""
        d = (self.dir("deprecated")
             / datetime.now(timezone.utc).strftime("%Y%m%d"))
        if subparts:
            d = d.joinpath(*subparts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def snapshot_skill(self, trunk: str | None, category: str | None,
                       version: int, content: str) -> Path:
        """旧 playbook 全文快照进 `deprecated/skills/<trunk>/`（30 天可恢复）。

        蒸馏重写与整方法采纳两条路径共用（原为逐字复制的内联写盘，且绕过数据层铁律）。"""
        dest_dir = self.dir("deprecated") / "skills" / (trunk or "其他")
        dest_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        dest = dest_dir / f"{category or '未分类'}-v{version - 1}-{ts}.md"
        self._write_tmp_rename(dest, content)
        return dest

    def retire_asset(self, path: Path) -> Path:
        """淘汰条目进 deprecated/<日期>/，保留 30 天可恢复，不直接删。"""
        dest_dir = self.deprecated_day_dir()
        dest = dest_dir / path.name
        shutil.move(str(path), str(dest))
        self.invalidate_cache(path)
        return dest

    def clean_deprecated(self, days: int = 30) -> int:
        cutoff = time.time() - days * 86400
        removed = 0
        base = self.data_dir / "deprecated"
        if not base.exists():
            return 0
        for day_dir in base.iterdir():
            if day_dir.is_dir() and day_dir.stat().st_mtime < cutoff:
                shutil.rmtree(day_dir)
                removed += 1
        return removed
