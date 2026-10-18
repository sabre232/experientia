"""`Store` 的「注入记录」域 mixin（injection.log + injection_hits.json，/）。

从 `store.py` 的 `class Store` 拆出的第四个域。只做不动语义的搬家，约定：

1. 方法体逐字搬移，签名与返回值一律不变；
2. 共享状态（`data_dir`、`_write_lock`、`_iter_jsonl`、`read_text_cached` /
   `invalidate_cache`）留在 `Store` 主体，mixin 通过 `self` 访问，**不复制状态**；
3. 需要模块级小工具时从 `._shared` 取，不 import `store.py`（避免循环导入）。

与 `rules.py` 的分工：本模块管"经验条目被真实注入之后"的记账与治理视图；
`rules.py` 管规则配置本身与规则命中计数。

 L4 第二批：写口（`record_injection` / `_bump_injection_hits_locked`）
与治理（`injection_governed_items` / `apply_injection_feedback` /
`set_injection_item_state`）一并搬入，本域计 8 个方法。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

# gsignal 是纯常量叶子模块（不依赖 store 层），直接复用同一阈值，避免数据层与
# 蒸馏层口径分叉（与 store.py 同源）。
from ..distill.gsignal import G_MIN_INJECT
from ..time_util import parse_ts
from ._shared import _safe_float, _safe_int, utcnow


class InjectionMixin:
    """注入记录与注入命中的读视图。"""

    def last_injection_ts(self) -> str | None:
        """injection.log 最后一行的 ts（档 C 空闲判定："1 小时内无任何 8100 请求"）。
        空文件/坏行 → None（视为很久以前）。"""
        last = None
        for rec in self._iter_jsonl("injection.log"):
            if isinstance(rec, dict) and rec.get("ts"):
                last = str(rec["ts"])
        return last

    def read_injection(self, start: datetime, end: datetime) -> list[dict]:
        """窗口内的真实注入记录（周报"哪条经验在变强"排名数据源）。"""
        out = []
        for rec in self._iter_jsonl("injection.log"):
            if not isinstance(rec, dict):
                continue
            t = parse_ts(rec.get("ts"))
            if t is None:
                continue
            if start <= t < end:
                out.append(rec)
        return out

    def load_injection_hits(self) -> dict:
        """{f"{trunk}/{category}": {"count": int, "last": ts|None, "items": {...}}}；
        旧格式/坏文件 → 兼容为无 items。

         遗留：注入热路径每次组装都裸读磁盘 → 走
        read_text_cached（mtime+size 校验缓存）。正确性：本文件全部写口
        （_bump_injection_hits_locked / apply_injection_feedback /
        set_injection_item_state）写后都 invalidate_cache——写后读一致；
        绕过本类的修改靠 stat 校验下一读即重读兜底。"""
        pathf = self.data_dir / "injection_hits.json"
        text = self.read_text_cached(pathf)
        if text is None:
            return {}
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    INJECTION_LOG_MAX_LINES = 2000

    def record_injection(self, trunk: str, category: str, session_id: str,
                         tokens: int, files: list[str] | None = None,
                         items: list[dict] | None = None,
                         channel: str = "proxy") -> None:
        """真实注入落一行：时间/session/注入了哪些文件/token 数。

        同步累计 injection_hits.json 的 (trunk/category) 命中——档 C 经验条目
        老化判定与周报"哪条经验在变强"
        的排名数据源。注入预览不记（预览不是真实注入；与 record_rule_hits 同口径）。

        channel：经验**走哪条路到达助手**（"proxy" = 8100 转发时改写请求，
        "hook" = Claude Code UserPromptSubmit 回灌 additionalContext）。
        两条通道都会真实送达上下文，必须都记账—— 前只有代理通道记，
        hook 通道注入成功也留不下痕迹，飞轮第④格因此天生少算一条路。

        /：命中累计落到"条目"粒度（items=[{id,text}]，真正进入注入块
        的条目），让"这条真被用过"决定它的寿命，而非"它所属的类别热不热"；
        text 供第⑤环反馈回填（store.apply_injection_feedback 近重复匹配）。
        """
        rec = {"ts": utcnow(), "session": str(session_id or ""),
               "trunk": trunk, "category": category, "channel": channel,
               "tokens": int(tokens or 0),
               "files": [str(f) for f in (files or [])],
               # 条目 id 随行落盘：逐条判据要回答"这条坑卡被注入
               # 的那些会话，修正轮数是不是真的更少"——没有归因就没有判据
               "items": [str(i.get("id")) for i in (items or [])
                         if isinstance(i, dict) and i.get("id")][:20]}
        with self._write_lock:
            self._append_jsonl_capped(self.data_dir / "injection.log",
                                      rec, self.INJECTION_LOG_MAX_LINES)
            self._bump_injection_hits_locked(f"{trunk}/{category}", rec["ts"],
                                             items=items)

    def _bump_injection_hits_locked(self, key: str, now: str,
                                    items: list[dict] | None = None) -> None:
        pathf = self.data_dir / "injection_hits.json"
        data: dict = {}
        if pathf.exists():
            try:
                data = json.loads(pathf.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except json.JSONDecodeError:
                data = {}
        e = data.get(key)
        if not isinstance(e, dict):
            e = {"count": 0, "last": None, "items": {}}
            data[key] = e
        e["count"] = int(e.get("count", 0)) + 1
        e["last"] = now
        items_map = e.setdefault("items", {})
        if not isinstance(items_map, dict):
            items_map = {}
            e["items"] = items_map
        for it in (items or []):
            if not isinstance(it, dict) or not it.get("id"):
                continue
            iid = str(it["id"])
            entry = items_map.get(iid)
            if not isinstance(entry, dict):
                entry = {"text": str(it.get("text") or "")[:300],
                         "count": 0, "last": None,
                         "corroborated": 0, "refuted": 0, "importance": 0}
                # probation：条目首次随注入
                # 出场即进试用期——期内被反驳直接移出（不走受限两步），
                # 平安度过 N 次注入 = 转正（字段清除）
                try:
                    from ..config_schema import numeric
                    prob = int(numeric(self.load_config(),
                                       "solidify.probation_sessions"))
                except Exception:
                    prob = 0
                if prob > 0:
                    entry["probation_left"] = prob
                items_map[iid] = entry
            entry["count"] = int(entry.get("count", 0)) + 1
            entry["last"] = now
            if entry.get("probation_left") is not None:
                left = int(entry["probation_left"]) - 1
                if left > 0:
                    entry["probation_left"] = left
                else:
                    entry.pop("probation_left", None)  # 试用期满 → 转正
        self._write_json_tmp_rename(pathf, data, indent=2)
        # 遗留：injection_hits.json 读路径已走缓存，写后必须
        # 失效，否则同 tick 内 mtime/size 未变时读到旧计数（写后读一致性）
        self.invalidate_cache(pathf)

    # 注入记录的读视图（last_injection_ts / read_injection / load_injection_hits）
    # 已搬到 app/store/injection.py 的 InjectionMixin。

    def injection_governed_items(self) -> list[dict]:
        """第⑤环回炉治理只读视图：跨全库聚合 restricted/excluded 的
        注入条目，供 GUI 治理面板展示与逐条恢复。返回空列表则无可治理项。

        每条含 {trunk, category, id, text, count, last, corroborated, refuted,
        restricted, restricted_since, excluded, excluded_since}；仅含被治理项，
        按「受限在前、移出在后」，组内按反驳次数降序。数据层铁律：GUI/local_api
        只经此方法取治理视图，不直接解析 injection_hits 内部结构。
        """
        out = []
        for key, cat in (self.load_injection_hits() or {}).items():
            if not isinstance(cat, dict):
                continue
            items = cat.get("items")
            if not isinstance(items, dict):
                continue
            trunk, _, category = key.partition("/")
            for iid, entry in items.items():
                if not isinstance(entry, dict):
                    continue
                restricted = int(entry.get("restricted") or 0)
                excluded = int(entry.get("excluded") or 0)
                if not restricted and not excluded:
                    continue
                e = dict(entry)
                e.update({"trunk": trunk, "category": category, "id": iid,
                          "restricted": restricted, "excluded": excluded})
                out.append(e)
        out.sort(key=lambda x: (1 if x.get("excluded") else 0,
                                -(int(x.get("refuted") or 0))))
        return out

    def injected_items(self, trunk: str, category: str) -> list[dict]:
        """该类别真实注入过的条目（含 text/count/last/corroborated/refuted），
        供第⑤环反馈回填与档 C 条目级老化。返回按注入次数倒序。"""
        cat = self.load_injection_hits().get(f"{trunk}/{category}")
        items = (cat or {}).get("items")
        if not isinstance(items, dict):
            return []
        out = list(items.values())
        out.sort(key=lambda x: _safe_int(x.get("count")), reverse=True)
        return out

    def apply_injection_feedback(self, exp: dict) -> None:
        """第⑤环「注入——结果——回填」：一条新经验落库后，
        去它所属类别"真实注入过的条目"里找近重复项——

        - 经验是高 G 成功（未纠正）→ 该条目 corroborated+1（被实际佐证：用对了）
        - 经验是被纠正/低 G（指向该条目）→ 该条目 refuted+1（用错了/被纠正，回炉）

        把老化钟从"命中就算数"升级为"用而且用对了才算数"。无匹配/无注入记录
        则静默返回（不落盘）。
        """
        if not isinstance(exp, dict):
            return
        trunk = exp.get("trunk") or "其他"
        category = exp.get("category") or "未分类"
        text = str(exp.get("action") or exp.get("state") or "").strip()
        if not text:
            return
        if exp.get("neutral"):
            return   # 中性收尾：没被否定≠成功，既非佐证也非反驳，不改注入条目命运
        success = _safe_float(exp.get("G")) >= G_MIN_INJECT and not exp.get("corrected")
        with self._write_lock:
            pathf = self.data_dir / "injection_hits.json"
            if not pathf.exists():
                return
            try:
                data = json.loads(pathf.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    return
            except json.JSONDecodeError:
                return
            cat = data.get(f"{trunk}/{category}")
            items = (cat or {}).get("items")
            if not isinstance(items, dict) or not items:
                return
            changed = False
            sid = str(exp.get("session_id") or "")
            for iid, entry in list(items.items()):
                if not isinstance(entry, dict) or not entry.get("text"):
                    continue
                if not self._near_dup(entry["text"], text):
                    continue
                if success:
                    corr_ss = entry.setdefault("corr_sessions", [])
                    if sid and sid in corr_ss:
                        continue  # 同 session 反复成功只佐证一次，防虚高
                    entry["corroborated"] = int(entry.get("corroborated", 0)) + 1
                    if sid:
                        corr_ss.append(sid)
                    entry["last"] = utcnow()  # 最近佐证 → 该条目不算冷
                else:
                    ref_ss = entry.setdefault("ref_sessions", [])
                    if sid and sid in ref_ss:
                        continue  # 同 session 反复纠正只反驳一次，防刷计数
                    entry["refuted"] = int(entry.get("refuted", 0)) + 1
                    if sid:
                        ref_ss.append(sid)
                    if entry.get("probation_left") is not None:
                        # -P2-6 隔离区：试用期内就被反驳 = 试用失败，
                        # 直接移出（不等受限两步流程），转正前不给自己辩白机会
                        entry["excluded"] = 1
                        entry["excluded_since"] = utcnow()
                        entry.pop("probation_left", None)
                changed = True
            if changed:
                self._write_json_tmp_rename(pathf, data, indent=2)
                # 遗留：读路径走缓存，写后失效保写后读一致
                self.invalidate_cache(pathf)

    def set_injection_item_state(self, trunk: str, category: str, item_id: str,
                                 **updates) -> bool:
        """维护层回炉：写注入条目状态（restricted/excluded 及其 since）。

        只允许维护单条 entry，返回是否写入。updates 值传 None => 删除该字段。
        数据层铁律：回炉评估（maintenance）只经此方法改 injection_hits。
        """
        with self._write_lock:
            pathf = self.data_dir / "injection_hits.json"
            if not pathf.exists():
                return False
            try:
                data = json.loads(pathf.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    return False
            except json.JSONDecodeError:
                return False
            cat = data.get(f"{trunk}/{category}")
            items = (cat or {}).get("items")
            if not isinstance(items, dict) or item_id not in items:
                return False
            entry = items[item_id]
            if not isinstance(entry, dict):
                return False
            for k, v in updates.items():
                if v is None:
                    entry.pop(k, None)
                else:
                    entry[k] = v
            self._write_json_tmp_rename(pathf, data, indent=2)
            # 遗留：读路径走缓存，写后失效保写后读一致
            self.invalidate_cache(pathf)
            return True

    @staticmethod
    def _near_dup(a: str, b: str) -> bool:
        """近重复判定（与 distill.dedupe.near_dup 同源，手写避免反向 import）：
        相等 / 短文本(<6 字)互为子串 / 长文本 difflib 相似度 ≥0.85。"""
        import difflib

        a, b = (a or "").strip(), (b or "").strip()
        if not a or not b:
            return False
        if a == b:
            return True
        if len(a) < 6 or len(b) < 6:
            return a in b or b in a
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85
