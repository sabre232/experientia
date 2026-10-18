"""`Store` 的「前瞻意图」域 mixin（P1-1 六层模型的 L6）。

L6 = "下一步大概率想做什么"，由 System2 从反复出现的模式里异步沉淀。它**不是
经验**：经验回答"以前怎么做是对的"，意图回答"接下来大概要处理什么"。混在一层
会让两者互相污染，所以单独一层、单独存储、单独过期。

三条硬约束（写进代码，不靠自觉）：

1. **不进注入链路**。意图只经 MCP 的 context_capsule 以最低层权重出现，
   `app/proxy/inject.py` 完全不碰本文件——意图是提示，不是指令。
2. **14 天过期**。过期即从读路径消失（`prune_expired_intentions` 物理清）。
3. **每 trunk 封顶 50 条**，近重复去重。否则长跑之后 L6 会变成第二个经验库。

约定同其余 mixin：共享状态（`data_dir` / `_write_lock` / `_iter_jsonl` /
`_cap_jsonl_lines`）留在 `Store` 主体，靠 `self` 访问，**不 import `store.py`**。
"""

from __future__ import annotations

import json
import logging
import uuid

from ._shared import utcnow

logger = logging.getLogger("experientia.store")

INTENTIONS_FILE = "intentions.jsonl"
INTENTIONS_EXPIRE_DAYS = 14      # 意图保质期：过期的下一步就不是下一步了
INTENTIONS_MAX_PER_TRUNK = 50    # 单 trunk 封顶，超出丢最旧
INTENTIONS_MAX_TOTAL = 500       # 全局封顶，防文件无界膨胀


class IntentionMixin:
    """L6 前瞻意图：增 / 查 / 过期清理 / 忽略。"""

    def _intentions_path(self):
        return self.data_dir / INTENTIONS_FILE

    def _iter_intentions_jsonl(self, include_expired: bool = False):
        """读全部意图。默认过滤已过期与已忽略；坏行跳过不中断（容错）。"""
        for item in self._iter_jsonl(INTENTIONS_FILE):
            if not isinstance(item, dict):
                continue
            if item.get("dismissed"):
                continue          # 用户明确说"别再提醒"——比过期更硬
            if not include_expired and self._intention_expired(item):
                continue
            yield item

    @staticmethod
    def _intention_expired(item: dict) -> bool:
        expires = str(item.get("expires_at") or "")
        if not expires:
            return False
        return expires <= utcnow()   # ISO 串可字典序比较（同格式、同时区）

    def list_intentions(self, trunk: str | None = None,
                        include_expired: bool = False) -> list[dict]:
        """有效意图（最新在前）。trunk 限定可选。"""
        out = [dict(i) for i in self._iter_intentions_jsonl(include_expired)]
        if trunk:
            out = [i for i in out if str(i.get("trunk") or "") == str(trunk)]
        out.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
        return out

    def add_intention(self, intent: str, trunk: str, category: str,
                      evidence_ids=None, kind: str = "pattern") -> dict | None:
        """沉淀一条前瞻意图。**只增不改、不改写别人的意图**。

        去重口径：同 (trunk, category) 下 intent 近重复（含已有的）→ 不重复加，
        只把证据 id 并进已有那条。返回新增/命中的意图；空内容 → None。
        """
        text = str(intent or "").strip()
        trunk = str(trunk or "").strip() or "其他"
        category = str(category or "").strip() or "未分类"
        if not text:
            return None
        ids = [str(x) for x in (evidence_ids or []) if x]

        with self._write_lock:
            rows = list(self._iter_jsonl(INTENTIONS_FILE))
            existing: dict | None = None
            for row in rows:
                if str(row.get("trunk") or "") != trunk:
                    continue
                if str(row.get("category") or "") != category:
                    continue
                if self._intention_expired(row) or row.get("dismissed"):
                    continue
                if str(row.get("intent") or "").strip() == text:
                    existing = row
                    break
            if existing is not None:
                merged = dict(existing)
                pool = {str(x) for x in (merged.get("evidence_ids") or []) if x}
                pool.update(ids)
                merged["evidence_ids"] = sorted(pool)[:20]
                merged["count"] = int(merged.get("count") or 1) + 1
                merged["ts"] = utcnow()
                merged["expires_at"] = self._intention_expiry()
                self._write_intentions([merged if r is existing else r
                                        for r in rows])
                return merged

            rec = {
                "id": f"int-{uuid.uuid4()}",
                "intent": text[:200],
                "kind": str(kind or "pattern"),
                "trunk": trunk, "category": category,
                "evidence_ids": ids[:20],
                "count": 1,
                "ts": utcnow(),
                "expires_at": self._intention_expiry(),
            }
            rows.append(rec)
            # 封顶：同 trunk 超限量丢最旧；全局再超量丢最旧
            rows = self._cap_intentions(rows)
            self._write_intentions(rows)
            return rec

    def dismiss_intention(self, intention_id: str) -> bool:
        """忽略一条意图（软删：标 dismissed，读路径不再返回）。

        幂等：已忽略的再调返回 False——调用方（GUI）要的是"这次有没有真的忽略"。
        """
        with self._write_lock:
            rows = list(self._iter_jsonl(INTENTIONS_FILE))
            hit = False
            out = []
            for row in rows:
                if (str(row.get("id") or "") == str(intention_id)
                        and not row.get("dismissed")):
                    row = {**row, "dismissed": True}
                    hit = True
                out.append(row)
            if hit:
                self._write_intentions(out)
            return hit

    def prune_expired_intentions(self) -> int:
        """物理清理过期/已忽略意图。返回清除条数。"""
        with self._write_lock:
            rows = list(self._iter_jsonl(INTENTIONS_FILE))
            keep = [r for r in rows
                    if not (self._intention_expired(r) or r.get("dismissed"))]
            removed = len(rows) - len(keep)
            if removed:
                self._write_intentions(keep)
            return removed

    def intention_counts(self) -> dict:
        """{total, per_trunk}（仅有效）。"""
        rows = list(self._iter_intentions_jsonl())
        per: dict[str, int] = {}
        for r in rows:
            key = str(r.get("trunk") or "其他")
            per[key] = per.get(key, 0) + 1
        return {"total": len(rows), "per_trunk": per}

    # ---------- 内部 ----------

    @staticmethod
    def _intention_expiry() -> str:
        from datetime import datetime, timedelta, timezone

        return (datetime.now(timezone.utc)
                + timedelta(days=INTENTIONS_EXPIRE_DAYS)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")

    def _cap_intentions(self, rows: list[dict]) -> list[dict]:
        """封顶裁剪：同 trunk 超出丢最旧，全局仍超再丢最旧（恒按最旧优先）。"""
        by_trunk: dict[str, list[dict]] = {}
        for r in rows:
            by_trunk.setdefault(str(r.get("trunk") or "其他"), []).append(r)
        out: list[dict] = []
        for trunk, items in by_trunk.items():
            items.sort(key=lambda x: str(x.get("ts") or ""))
            out.extend(items[-INTENTIONS_MAX_PER_TRUNK:])
        if len(out) > INTENTIONS_MAX_TOTAL:
            out.sort(key=lambda x: str(x.get("ts") or ""))
            out = out[-INTENTIONS_MAX_TOTAL:]
        return out

    def _write_intentions(self, rows: list[dict]) -> None:
        """整文件原子重写（意图量小：≤ 全局封顶 500 条，可承受）。"""
        lines = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        self._write_tmp_rename(self._intentions_path(), lines)
        self.invalidate_cache(self._intentions_path())
