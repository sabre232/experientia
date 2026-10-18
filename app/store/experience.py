"""`Store` 的「经验」域 mixin 之一：单条经验的查找 / 老化归档 / 原地更新。

从 `store.py` 的 `class Store` 拆出的第八个域。只做不动语义的搬家，约定：

1. 方法体逐字搬移，签名与返回值一律不变；
2. 共享状态（`data_dir`、`_write_lock`、`_iter_jsonl`、`_update_jsonl`、
   `_sync_experience_index`、`deprecated_day_dir`、`rebuild_category_index`）
   留在 `Store` 主体，mixin 通过 `self` 访问，**不复制状态**；
3. 需要模块级小工具时从 `._shared` 取，不 import `store.py`（避免循环导入）。

并发语义是这里的重点，搬迁时原样保留：相关要求**载荷读取
必须在写锁内**，否则并发合并会互相覆盖（丢失更新）。
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("experientia.store")


class ExperienceMixin:
    """经验条目的查找 / 老化归档 / 原地更新。"""

    def experience_categories(self) -> list[str]:
        """出现过的分类名（去重、排序）——：走 experience.db 的
        `SELECT DISTINCT`，耗时与经验条数无关；索引不可用（fail-open 降级）→
        回退原 JSONL 全量遍历（语义与旧实现一致，宁慢不崩）。"""
        db = getattr(self, "_expdb", None)
        if db is not None:
            try:
                return db.distinct_categories()
            except Exception as exc:  # noqa: BLE001 索引异常 → 降级回退 JSONL
                logger.warning("分类索引查询失败，回退 JSONL 遍历: %s", exc)
                self._expdb = None
        return sorted({
            str(item.get("category", "未分类"))
            for item in self.iter_experiences(include_distilled=True)
        })

    def find_experience(self, exp_id: str) -> dict | None:
        """按 id 取单条（优先走 experience.db 的 O(1) 主键查；索引不可用 →
        回退 JSONL 全扫，语义不变）。"""
        db = getattr(self, "_expdb", None)
        if db is not None:
            try:
                return db.get(exp_id)
            except Exception as exc:  # noqa: BLE001 索引异常 → 降级回退 JSONL
                logger.warning("经验索引按 id 查失败，回退 JSONL: %s", exc)
                self._expdb = None
        for item in self._iter_jsonl("experience.jsonl"):
            if item.get("id") == exp_id:
                return item
        return None

    def retire_experience(self, exp_id: str) -> bool:
        """档 C 经验条目老化：
        整条移入 deprecated/<日期>/experiences.jsonl（30 天可恢复，
        与淘汰机制同一套），原文完整保留（经验流是永久资产，
        移走不是删掉）。返回是否命中。

        
        (1) 锁内重读——避免用锁外旧快照覆盖并发合并的 count/G/seen_in；
        (2) 归档前先查当日 deprecated 是否已有同 id。保留"先归档、后删主行"
            的不丢数据安全序（崩在两步之间→主行仍在、可重跑，绝不丢数据）；
            重跑时不再叠加第二份 deprecated 副本，两步最终收敛到"只在 deprecated"。
        """
        with self._write_lock:
            item = self.find_experience(exp_id)
            if item is None:
                return False
            day_dir = self.deprecated_day_dir()
            dest = day_dir / "experiences.jsonl"
            already = False
            if dest.exists():
                for line in dest.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        if str(json.loads(line).get("id") or "") == str(exp_id):
                            already = True
                            break
                    except json.JSONDecodeError:
                        continue
            if not already:
                # 归档追加必须 flush + fsync 才删主行——
                # "先归档后删"只保顺序，不落盘的话断电/蓝屏时归档还在 OS 页缓存
                # 里，deprecated 副本丢而主行已从 SQLite 删除 → 经验永久丢失，
                # 30 天可恢复形同虚设。与 migrations._append_snapshot 同口径。
                with dest.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(item, ensure_ascii=False) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            # _update_jsonl 的 updates 值 = None → _read_write_jsonl 跳过该行（整行移除）
            # 条目已移入 deprecated 留档；只写 SQLite（删行）；索引不可用才回退 JSONL
            if not self._write_experiences_sqlite({exp_id: None}, line_delta=-1):
                self._update_jsonl("experience.jsonl", {exp_id: None})
        return True

    def update_experience(self, exp_id: str, patch: dict) -> dict | None:
        """按 id 原地更新经验字段（L1 反馈改 G 值等）。

        载荷读取纳入写锁——此前 `find` 在锁外、锁内整文件重写，
        与并发 `append_experience` 的 count/G/seen_in 合并交叠时会把对方刚写入
        的字段覆盖回旧快照（丢失更新）。锁内重读后 `updated = {**当前行, **patch}`，
        patch 未点名的字段一律保留最新值。"""
        with self._write_lock:
            item = self.find_experience(exp_id)
            if item is None:
                return None
            updated = {**item, **patch}
            # 只写 SQLite（唯一事实源）；索引不可用才回退整文件重写 JSONL
            if not self._write_experiences_sqlite({exp_id: updated}):
                self._update_jsonl("experience.jsonl", {exp_id: updated})
        if set(patch) & {"trunk", "category", "task"}:  # M-5：动索引字段才重建
            self.rebuild_category_index()
        return updated
