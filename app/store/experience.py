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
import uuid

from ._shared import utcnow

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
        """档 C 经验条目老化（C1-1，距上次被注入命中 ≥90 天）：
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

    # ---------- P0-3 演化链 / 遗忘 / 回滚（纪律 D4 合并、D5 冲突、D6 遗忘） ----------

    def _chain_head(self, exp_id: str) -> dict | None:
        """顺着 superseded_by 走到链的当前头。成环则停在环外（防御性，不设死循环）。"""
        cur = self.find_experience(exp_id)
        if cur is None:
            return None
        seen = {str(cur.get("id") or "")}
        while cur.get("superseded_by"):
            nxt = str(cur["superseded_by"])
            if not nxt or nxt in seen:
                break
            seen.add(nxt)
            found = self.find_experience(nxt)
            if found is None:
                break
            cur = found
        return cur

    def supersede_experience(self, exp_id: str, new_rec: dict,
                             reason: str = "") -> dict:
        """用新内容**替代**一条经验：旧头进版本快照并标 superseded_by，新版成为链头。

        与 `update_experience` 的分界（这是本方法的全部意义）：
        - `update_experience` = 原地补字段（改 G / dismissed / 归类），内容主体不变；
        - `supersede_experience` = 内容换代（action/state/outcome 被改写），旧版留痕。

        为什么必须分开：LLM 措辞每次漂移，若让漂移直接改写已沉淀资产就是污染
        （dedupe 里"文本不覆盖"守的是同一条；这里守的是"换代必须留痕"）。
        换代永远产生新 id + revision+1，**绝不原地覆盖**。

        返回新头记录。链头找不到或已被遗忘 → KeyError。
        """
        with self._write_lock:
            head = self._chain_head(exp_id)
            if head is None:
                raise KeyError(f"经验不存在或已被移除: {exp_id}")
            if int(head.get("tombstone") or 0):
                raise KeyError(f"经验已被遗忘（先从回收中恢复再换代）: {exp_id}")

            head_id = str(head.get("id"))
            root = str(head.get("root_id") or head_id)
            try:
                next_rev = int(head.get("revision") or 1) + 1
            except (TypeError, ValueError):
                next_rev = 2

            rec = dict(new_rec or {})
            rec["id"] = str(rec.get("id") or uuid.uuid4())
            # 身份字段：调用方没显式给就继承旧头——换代不该把归属改丢
            for key in ("agent", "trunk", "category", "task", "project"):
                if not rec.get(key):
                    rec[key] = head.get(key)
            rec.update({
                "revision": next_rev,
                "root_id": root,
                "supersedes": [head_id],
                "superseded_by": "",
                "tombstone": 0,
                "ts": utcnow(),
            })
            rec.setdefault("count", int(head.get("count") or 1))
            rec.setdefault("G", float(head.get("G") or 0))
            rec.setdefault("g_source", head.get("g_source") or "auto")

            # 1) 旧头入快照——先存后写：崩在两步之间旧头仍是主行，可重跑。
            # 标 superseded_by 与邻域同口径：SQLite 不可用时回退 JSONL——
            # 之前这里裸写，降级模式下旧头不标 → JSONL 读路径双头。
            if not self._write_experiences_sqlite(
                    {head_id: {**head, "superseded_by": rec["id"]}}):
                self._update_jsonl("experience.jsonl",
                                   {head_id: {**head, "superseded_by": rec["id"]}})
            db = getattr(self, "_expdb", None)
            if db is not None:
                try:
                    db.save_revision(head, reason=reason)
                except Exception as exc:  # noqa: BLE001 快照失败不阻断换代主流程
                    logger.warning("经验版本快照写入失败（不影响换代）: %s", exc)
            # 2) 新头落库（SQLite 为唯一事实源；JSONL 由定期快照导出对齐）
            if not self._write_experiences_sqlite({rec["id"]: rec}, line_delta=1):
                self._append_experience_jsonl(rec)
        if str(rec.get("trunk") or "") != str(head.get("trunk") or "") or \
                str(rec.get("category") or "") != str(head.get("category") or ""):
            self.rebuild_category_index()
        return rec

    def forget_experience(self, exp_id: str, hard: bool = False) -> bool:
        """用户显式遗忘（D6）。默认软忘，可逆。

        软忘：`tombstone=1`，行仍在库里但默认读路径一律不返回（含检索/注入/GUI），
        `restore_experience` 可一键捞回；同时往 deprecated 留一份可读副本。
        硬删：仅在用户二次确认且允许时——移入 deprecated（30 天可恢复）后删主行，
        与 `retire_experience` 同一套"先归档后删"安全序。

        与 `retire_experience`（90 天未命中自动老化）的区别：那是系统行为，
        这是**用户意图**。两者都走 deprecated，但语义、入口、可逆性不同。
        """
        with self._write_lock:
            item = self.find_experience(exp_id)
            if item is None:
                return False
            if not hard and int(item.get("tombstone") or 0):
                return False  # 幂等：已经忘了就别再归档一次
            if self._archive_forgotten(item):
                if hard:
                    if not self._write_experiences_sqlite(
                            {str(item.get("id")): None}, line_delta=-1):
                        self._update_jsonl("experience.jsonl",
                                           {str(item.get("id")): None})
                else:
                    # 软忘：索引不可用时回退 JSONL——否则返回 True 但
                    # tombstone 没落任何库（用户以为忘了其实没忘）
                    if not self._write_experiences_sqlite(
                            {str(item.get("id")): {**item, "tombstone": 1}}):
                        self._update_jsonl(
                            "experience.jsonl",
                            {str(item.get("id")): {**item, "tombstone": 1}})
                return True
            # 归档没成功 → 状态一点都不能动（"先归档后改状态"的安全序）
            return False

    def restore_experience(self, exp_id: str) -> bool:
        """撤销软忘（tombstone 1 → 0）。硬删的找 deprecated，不走这里。"""
        with self._write_lock:
            item = self.find_experience(exp_id)
            if item is None or not int(item.get("tombstone") or 0):
                return False
            # 与软忘同口径：索引不可用回退 JSONL
            if not self._write_experiences_sqlite(
                    {str(item.get("id")): {**item, "tombstone": 0}}):
                self._update_jsonl("experience.jsonl",
                                   {str(item.get("id")): {**item, "tombstone": 0}})
        return True

    def rollback_experience(self, exp_id: str, revision: int) -> dict:
        """回到某个历史版本——以**新版本**的形式，不是改写历史。

        历史 append-only：回滚 = 把旧快照内容作为 revision+1 的新链头写入，
        旧头照旧入快照。这样"回滚过几次、每次回到哪"本身也可追溯。
        """
        with self._write_lock:
            head = self._chain_head(exp_id)
            if head is None:
                raise KeyError(f"经验不存在或已被移除: {exp_id}")
            root = str(head.get("root_id") or head.get("id"))
            db = getattr(self, "_expdb", None)
            snap = db.get_revision(root, int(revision)) if db is not None else None
            if snap is None:
                raise KeyError(f"没有该历史版本: {root}#{revision}")
            if int(snap.get("tombstone") or 0):
                raise KeyError("不能回滚到已被遗忘的版本")
        return self.supersede_experience(
            # id 必须置空：supersede 对调用方给的 id 照单全收，而快照带的是旧
            # 头的 id——复用会让 UPSERT 原地顶掉刚标了 superseded_by 的旧头
            # 主行（"换代绝不原地覆盖"的注释被破）。置空后
            # supersede 的 `or uuid4()` 生成新 id。
            exp_id, {**snap, "id": "", "tombstone": 0,
                     "rollback_of": f"{root}#{revision}"},
            reason=f"rollback to {root}#{revision}")

    def experience_chain(self, exp_id: str) -> dict | None:
        """整条链的视图：历史版本（旧）+ 当前头。给 GUI/接口用，纯读。"""
        head = self._chain_head(exp_id)
        if head is None:
            return None
        root = str(head.get("root_id") or head.get("id"))
        db = getattr(self, "_expdb", None)
        revisions = db.iter_revisions(root) if db is not None else []
        return {
            "root_id": root,
            "depth": len(revisions) + 1,
            "revisions": revisions,
            "current": head,
        }

    def _archive_forgotten(self, item: dict) -> bool:
        """把一条经验写进 deprecated/<日期>/experiences.jsonl（幂等，先归档后改状态）。

        单独写而不复用 `retire_experience` 里那段：那边顺手删主行，复用它会把
        "软忘"变成"直接老化"，路径被绑死。这里只归档、不动主行，删除由调用方决定。
        安全序与 retire 一致：**archived flush + fsync 之后**才允许改主行状态，
        否则断电时归档还在 OS 页缓存里、主行已标 tombstone → 两头都不见。
        """
        exp_id = str(item.get("id") or "")
        if not exp_id:
            return False
        day_dir = self.deprecated_day_dir()
        dest = day_dir / "experiences.jsonl"
        try:
            already = False
            if dest.exists():
                for line in dest.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        if str(json.loads(line).get("id") or "") == exp_id:
                            already = True
                            break
                    except json.JSONDecodeError:
                        continue
            if not already:
                with dest.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(item, ensure_ascii=False) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
        except OSError as exc:
            logger.warning("遗忘归档失败（保持原状态）: %s", exc)
            return False
        return True
