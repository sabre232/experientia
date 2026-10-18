"""`Store` 的「规则通道」域（rules.json + 规则正文 md）与「注入覆盖层」。

从 `store.py` 的 `class Store`（原 2796 行 / 148 方法）拆出的
第二、三个域。只做不动语义的搬家，约定：

1. 方法体逐字搬移，签名与返回值一律不变；
2. 共享状态（`data_dir`、`_write_lock`、`_write_json_tmp_rename`、`read_text_cached`
   / `invalidate_cache`）留在 `Store` 主体，mixin 通过 `self` 访问，**不复制状态**；
3. 需要模块级小工具时从 `._shared` 取，不 import `store.py`（避免循环导入）。

本模块同时持有规则 schema 版本与迁移注册表——它们只服务于 `rules.json`，随域走；
`store.py` 保留同名再导出以兼容既有 import。
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ._shared import utcnow

logger = logging.getLogger("experientia.store.rules")

RULES_SCHEMA_VERSION = 1
_RULES_MIGRATIONS: dict[int, Callable[[list], None]] = {}


def _register_rule_migration(version: int, fn: Callable[[list], None]) -> None:
    """登记 rules schema 迁移（版本号唯一、升序；load_rules 落后时自动跑）。"""
    if version in _RULES_MIGRATIONS:
        raise ValueError(f"rules schema migration v{version} 已注册")
    _RULES_MIGRATIONS[version] = fn


def normalize_rule(rule: dict) -> dict:
    """rule 字段归一化（H-A0）：缺 `agents`（旧 rules.json）→ ["*"]；
    显式 `[]`（未配装，软停用）保持为 []，绝不回填成全局。
    `scope`/`globs` 只规范化类型，不改语义。

    下沉到 store（数据层铁律）：规则归一化是数据口径，注入层只消费，
    不再由 proxy 层持有（消除 store→inject 反向依赖）。
    """
    if not isinstance(rule, dict):
        return rule
    out = dict(rule)
    agents = out.get("agents")
    if agents is None:
        out["agents"] = ["*"]
    elif isinstance(agents, list):
        out["agents"] = [str(a) for a in agents]
    if out.get("scope") == "glob":
        globs = out.get("globs")
        out["globs"] = [str(g) for g in globs if g] if isinstance(globs, list) else []
    return out


class OverridesMixin:
    """`injection_overrides.json` 的读写（条目 id → {enabled, text}）。

    覆盖层与资产文件解耦：蒸馏/升级 playbook 不动此文件；条目被淘汰后覆盖
    自动失效（stale，由 `inject.stale_override_ids` 判定）。
    """

    def load_overrides(self) -> dict:
        """条目 id → {"enabled": bool, "text": str|None}。与资产文件解耦：
        蒸馏/升级 playbook 不动此文件；条目被淘汰后覆盖自动失效（stale）。"""
        path = self.data_dir / "injection_overrides.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def save_overrides(self, data: dict) -> None:
        self._write_json_tmp_rename(self.data_dir / "injection_overrides.json", data)

    def upsert_override(self, entry_id: str, enabled: bool | None = None,
                        text: str | None = None) -> dict:
        with self._write_lock:
            data = self.load_overrides()
            cur = data.get(entry_id, {})
            if enabled is not None:
                cur["enabled"] = bool(enabled)
            if text is not None:
                cur["text"] = text
            data[entry_id] = cur
            self.save_overrides(data)
        return cur

    def remove_override(self, entry_id: str) -> None:
        with self._write_lock:
            data = self.load_overrides()
            if entry_id in data:
                del data[entry_id]
                self.save_overrides(data)


class RulesMixin:
    """`rules.json` 与规则正文 md 的读写。"""

    def _read_rules_raw(self) -> tuple[list[dict], int]:
        """纯读 rules.json → (rules, schema_version)；无迁移、无写盘、无缓存。

        供**已持写锁**的调用方（upsert_rule / remove_rule）使用：它们不能走
        `load_rules`——后者在版本落后时会写盘，自取锁就重入死锁（Lock 不可重入，
）。"""
        text = self.read_text_cached(self.data_dir / "rules.json")
        if text is None:
            return [], RULES_SCHEMA_VERSION
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return [], RULES_SCHEMA_VERSION
        if isinstance(data, dict):
            version = int(data.get("schema_version") or 0)
            rules = data.get("rules", [])
        elif isinstance(data, list):
            version, rules = 0, data
        else:
            return [], RULES_SCHEMA_VERSION
        return [r for r in rules if isinstance(r, dict)], version

    def _write_rules_unlocked(self, rules: list[dict]) -> None:
        """写 rules.json（原子替换 + 缓存失效）。调用方须持写锁，或确认无并发。"""
        path = self.data_dir / "rules.json"
        # DATA-5：容器带 schema_version，load_rules 据此跑集中迁移
        self._write_json_tmp_rename(
            path, {"schema_version": RULES_SCHEMA_VERSION, "rules": rules}, indent=2)
        self.invalidate_cache(path)

    def load_rules(self) -> list[dict]:
        """读 rules.json；模板规则（带 file 字段）优先读数据目录里的 md——
        md 是权威来源（用户改完文件即生效），text 字段是导入时快照回退。
        返回前做 H-A0 归一化（缺 agents → ["*"]）。文件走 mtime 缓存（M-5）。
        DATA-5：容器带 schema_version，版本落后时先跑集中迁移注册表再升级写回
        （无老用户 → v0→v1 为空迁移；未来加迁移 = 注册一行 + 版本 +1）。

        迁移写盘**进写锁**（原来是读路径里的无锁写，与
        upsert_rule 的持锁读-改-写并发会丢规则）；锁内双检版本，避免并发下
        重复迁移/覆盖。
        唯一实现：注入路径与 API/export/迁移全走这里，口径统一。
        （此前 inject.load_rules 与本方法是双实现，API/export 用的是旧快照 text。）
        """
        rules, schema_version = self._read_rules_raw()
        if schema_version < RULES_SCHEMA_VERSION:
            with self._write_lock:
                rules2, version2 = self._read_rules_raw()
                if version2 < RULES_SCHEMA_VERSION:
                    # 版本升序迁移：注册表里有多少跑多少，然后升级容器版本（幂等一次）
                    for _v in range(version2 + 1, RULES_SCHEMA_VERSION + 1):
                        fn = _RULES_MIGRATIONS.get(_v)
                        if fn:
                            try:
                                fn(rules2)
                            except Exception as exc:
                                logger.warning(
                                    "rules schema v%d 迁移失败（继续读原始数据）: %s",
                                    _v, exc)
                    self._write_rules_unlocked(rules2)
                rules = rules2
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rel = rule.get("file")
            if not rel:
                continue
            if os.path.isabs(rel):
                continue
            full = (self.data_dir / rel).resolve()
            if not full.is_relative_to(self.data_dir.resolve()):
                continue
            t = self.read_text_cached(full)
            if t is not None:
                rule["text"] = t.strip()
        return [normalize_rule(r) for r in rules]

    def save_rules(self, rules: list[dict]) -> None:
        """整表覆盖写 rules.json。：自取写锁——此前不加锁，
        并发调用（API 保存 vs 注入热路径）会互相覆盖，文件本身不坏但丢更新。"""
        with self._write_lock:
            self._write_rules_unlocked(rules)

    def upsert_rule(self, rule: dict, force: bool = False) -> dict:
        rule = dict(rule)
        rule.setdefault("id", str(uuid.uuid4()))
        rule.setdefault("enabled", True)
        rule.setdefault("trigger", "smart")
        # H-O2：创建时间用于"从未命中 + 规则已存在 N 天"的过时判定
        rule.setdefault("created_at", utcnow())
        # H-A0：作用工具缺省 = 全部工具；显式 []（未配装）是有意状态，不回填
        if rule.get("agents") is None:
            rule["agents"] = ["*"]
        # H-O3：hard-hook 约束——仅 P0 可用且 P0 强制 hard-hook
        if not force:
            trigger = rule.get("trigger", "smart")
            priority = rule.get("template_priority", "")
            if priority == "p0":
                rule["trigger"] = "hard-hook"
            elif trigger == "hard-hook":
                # 非 P0 规则不允许 hard-hook（手动创建或 API 直写），force=True 可绕过
                rule["trigger"] = "smart"
        with self._write_lock:
            # 已持锁 → 走纯读口 + 无锁写口（load_rules/
            # save_rules 自取锁，重入即死锁）
            rules, _ver = self._read_rules_raw()
            for i, r in enumerate(rules):
                if r.get("id") == rule["id"]:
                    merged = {**r, **rule}
                    rules[i] = merged
                    self._write_rules_unlocked(rules)
                    return merged
            rules.append(rule)
            self._write_rules_unlocked(rules)
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        with self._write_lock:
            rules, _ver = self._read_rules_raw()  # 已持锁，用纯读口
            kept = [r for r in rules if r.get("id") != rule_id]
            if len(kept) == len(rules):
                return False
            self._write_rules_unlocked(kept)
        self.purge_rule_hit(rule_id)  # H-O2：命中记录连带清理（锁外，避免重入）
        return True

    def write_rule_file(self, rel: str, text: str) -> Path:
        """写规则 md（data_dir/<rel>）并清缓存（M2：规则文件落盘收口 store——
        模板导入与恢复默认都走这里，不再各处裸 write_text）。"""
        path = self.data_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写——规则正文是注入读路径的权威来源
        self._write_tmp_rename(path, text)
        self.invalidate_cache(path)
        return path

    def rename_rule_file(self, old_rel: str, new_rel: str) -> None:
        """规则正文文件改名（数据迁移用，W4-07）：收口 store，避免迁移层裸拼
        data_dir 路径。旧不存在 → no-op；目标已存在 → 保留目标不覆盖。"""
        old_f = self.data_dir / old_rel
        new_f = self.data_dir / new_rel
        if not old_f.exists() or new_f.exists():
            return
        new_f.parent.mkdir(parents=True, exist_ok=True)
        old_f.rename(new_f)
        self.invalidate_cache(old_f)
        self.invalidate_cache(new_f)

    # ---------- 规则注入命中（H-O2 生命周期治理：命中/过时） ----------

    def record_rule_hits(self, rule_ids: list[str]) -> None:
        """规则注入命中累计：rule_hits.json = {rule_id: {"count", "last"}}。

        由 assemble_rules_block 在真实注入路径（代理/hook 通道）调用，
        注入预览不记（预览不是真实注入）。单次请求同规则去重。"""
        ids = [str(i) for i in rule_ids if i]
        if not ids:
            return
        with self._write_lock:
            self._bump_rule_hits_locked(ids, utcnow())

    def _bump_rule_hits_locked(self, ids: list[str], now: str) -> None:
        pathf = self.data_dir / "rule_hits.json"
        data: dict = {}
        if pathf.exists():
            try:
                data = json.loads(pathf.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except json.JSONDecodeError:
                data = {}
        for rid in dict.fromkeys(ids):
            e = data.get(rid)
            if not isinstance(e, dict):
                e = {"count": 0, "last": None}
            e["count"] = int(e.get("count", 0)) + 1
            e["last"] = now
            # 近7天命中分桶：按 UTC 日期累计，供 Hooks 页判断每条 Hook 是高频还是低频。
            # 旧数据（无 days）自动初始化；窗口外的历史桶丢弃，防文件无限膨胀。
            day = str(now)[:10]
            days = e.get("days")
            if not isinstance(days, dict):
                days = {}
            days[day] = int(days.get(day, 0)) + 1
            cutoff = (datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y-%m-%d")
            e["days"] = {k: v for k, v in days.items() if k >= cutoff}
            data[rid] = e
        self._write_json_tmp_rename(pathf, data, indent=2)

    def load_rule_hits(self) -> dict:
        """{rule_id: {"count": int, "last": ts|None}}；文件损坏 → 空。"""
        pathf = self.data_dir / "rule_hits.json"
        if not pathf.exists():
            return {}
        try:
            data = json.loads(pathf.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def purge_rule_hit(self, rule_id: str) -> None:
        """规则删除时连带清理命中记录（幂等；调用方不得已持有 _write_lock）。"""
        with self._write_lock:
            pathf = self.data_dir / "rule_hits.json"
            if not pathf.exists():
                return
            try:
                data = json.loads(pathf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return
            if isinstance(data, dict) and data.pop(rule_id, None) is not None:
                self._write_json_tmp_rename(pathf, data)
