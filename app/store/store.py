"""唯一数据访问层——所有读写走这里（产品文档引擎/外壳分层、用户数据目录）。

事实来源（source of truth）：
- experience.jsonl            经验原料，append-only，schema（持久事实源，格式不变）
- experience.db               SQLite 经验读索引
- skills/<trunk>/<category>.md   playbook 资产
- preferences/<trunk>.md         偏好画像
- deprecated/                 淘汰资产，保留 30 天可恢复
- changelog.md                playbook 升级历史
- sessions.jsonl              session 追踪，三通道统一格式
- injection_overrides.json    注入用户覆盖层
- rules.json                  规则通道
- config.json                 配置（API Key 走 keyring，不落此文件）

并发约定：SQLite WAL + 单写队列（本进程内 _write_lock 串行），
写事务保持短（事务内只做落盘/insert，不调模型、不等网络）。

经验索引分层：
- **experience.db（SQLite WAL）是唯一持久事实源**：读路径全走它；写路径只落它
  （**新增**记录同时 append 一行 JSONL 作低成本备份，更新/删除不重写 JSONL）；
- **experience.jsonl 降级为导出/备份格式**：运行期不再被任何读路径消费（仅
  `_expdb is None` 的降级/重建路径读它），由 `export_experience_snapshot`
  定期（脏计数阈值）或显式动作原子导出对齐；
- 事实源标志：index meta `experience_source`。缺该标志 = 迁移前（JSONL 仍是事实源，
  启动按 (size, mtime_ns) 指纹决定是否 `rebuild_if_stale`）；迁移 v4 盖上
  `"sqlite"` 后，`rebuild_if_stale` **绝不按陈旧 JSONL 重建**（否则会用低频快照
  覆盖库、丢掉未导出的更新 —— 数据丢失！）；
- 索引必须 fail-open：初始化或写失败 → 降级/自愈，绝不能让应用因索引故障不可用
  。
"""

from __future__ import annotations

import json
import logging
import re
import os
import secrets
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..time_util import parse_ts
from typing import Callable, Iterable, Iterator

logger = logging.getLogger("experientia.store")

# 红线：G<0.5 永不注入。gsignal 是纯常量叶子模块（不依赖本层），
# 直接复用同一阈值，避免数据层与蒸馏层口径分叉。
from ..distill.gsignal import G_MIN_INJECT  # noqa: E402
from ..fs_util import REPLACE_BACKOFF_S, REPLACE_RETRIES, replace_atomic  # noqa: E402,F401
from .experience_db import ExperienceDB  # noqa: E402

# DATA_DIR_NAME / ASSET_DIRS 已下沉到 app/store/_shared.py
#（数据目录域 mixin 要用，不能反向 import 本文件）。这里保留同名再导出。
from ._shared import ASSET_DIRS, DATA_DIR_NAME  # noqa: E402,F401

# incoming 上报码字符集（大写字母+数字+短横线），防路径穿越
_CODE_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")

# DATA-5：rules.json 容器 schema 版本 + 集中迁移注册表（版本升序；无老用户 → v0→v1 空迁移）。
# 未来加迁移：_register_rule_migration(v, fn) 注册一行 + RULES_SCHEMA_VERSION += 1。
# rules schema 版本与迁移注册表已随「规则通道」域搬到
# app/store/rules.py——它们只服务于 rules.json。`utcnow` 抽到 _shared.py
# （多个 mixin 共用）。这里保留同名再导出，兼容既有 import。
# _safe_int / _safe_float / _session_ident 已下沉到 _shared.py
#（Store 主体与各 mixin 共用），这里取回供本文件剩余用法使用。
from ._shared import (_safe_float,  # noqa: E402,F401
                      _safe_int,  # noqa: E402,F401
                      _session_ident)  # noqa: E402,F401
from ._shared import utcnow  # noqa: E402,F401
from .rules import (RULES_SCHEMA_VERSION,  # noqa: E402,F401
                    _RULES_MIGRATIONS,  # noqa: E402,F401
                    _register_rule_migration)


# 原子替换的收口点在 app/fs_util.py（Windows 瞬时锁重试的来龙去脉见其模块说明）。
# 这里 re-export 三个名字，让既有 `from app.store.store import REPLACE_RETRIES`
# 继续可用；真正的实现只有一份——store 数据层与 capture 层三处 hook 写入共用同一套
# 重试参数，避免调一处漏两处。


# 保留策略（低5）：sessions.jsonl / notifications.jsonl 保留 90 天；
# session 消息每角色只留最近 20 条、每条截 200 字（record_session 是落库单点，
# 复盘管线用内存全文，不受影响）。
SESSION_RETENTION_DAYS = 90
NOTIFY_RETENTION_DAYS = 90
SESSION_MSG_KEEP = 20
SESSION_MSG_MAX_CHARS = 200

# 归档容量三闸（对标 OpenClaw session.maintenance 的 maxDiskBytes / highWaterBytes /
# rotateBytes）：**保留期只挡时间，挡不住写入速率**——90 天内照样能长到几十 GB。
# 三闸各接一种膨胀，缺一个就有绕过路径：
# 体积闸  sessions/ 总量 > SESSIONS_MAX_DISK_BYTES → 削到 SESSIONS_HIGH_WATER_BYTES
# 留 20% 缓冲（滞回）：削到刚好等于上限会变成"每天削一点点"反复触发；
# 条数闸归档文件数 > SESSIONS_MAX_FILES → 削（高频小会话：体积不涨、条目暴涨，
# 目录遍历与孤儿判定成本随之线性上升）；
# 单文件闸单个归档 > SESSION_ARCHIVE_MAX_FILE_BYTES → 不拷（容器库整库拷贝，
# Cursor state.vscdb 实测 283 MB，是归档体积的大头）。
# 裁剪恒按"最旧优先"，且只删归档副本——源文件在用户机器上，一律不动。
SESSIONS_MAX_DISK_BYTES = 2 * 1024 ** 3
SESSIONS_HIGH_WATER_BYTES = SESSIONS_MAX_DISK_BYTES * 4 // 5  # 80%
SESSIONS_MAX_FILES = 4000
SESSION_ARCHIVE_MAX_FILE_BYTES = 100 * 1024 ** 2

# ----------  字段契约（断链修复方案 M1：写口契约，防无界字段复现） ----------
# record_session 只接受下列字段，超纲字段丢弃 + warning（不静默）；原始 messages
# 明确不在契约内（431MB 事故的直接来源）。契约维护为本常量 + 注释表；
# 新增字段必须先改契约再改调用方。三通道（capture/hook/proxy）共用这一个
# choke point，未来新增通道也无法绕过。
# 身份：agent, session_id, channel, project
# 时间：started_at, ended_at
# 指标：req_count, correction_hits, tokens_in, tokens_out
# 归类：trunk, category
# 来源：model
# 转录（有界）：user_messages, assistant_messages
SESSION_RECORD_FIELDS = frozenset((
    "agent", "session_id", "channel", "project",
    "started_at", "ended_at",
    "req_count", "correction_hits", "tokens_in", "tokens_out",
    "tokens",  # 部分 adapter 只有聚合 token 数（无 in/out 分列）——ledger 按
               # 80/20 估算；回采重解析时丢了会让账本花费整列归零
    "trunk", "category",
    "model",
    "user_messages", "assistant_messages",
    "events",  # R0 事件行（capture/events.py 派生，有预算；原始 messages 恒不落库）
))

# 容量断路器：落库序列化后记录超此大小 → 二阶段强制截断 + warning。
# 白名单（契约）防"已知超纲"，断路器防"未知膨胀"，两层各接一种漂移。
SESSION_RECORD_MAX_BYTES = 32 * 1024

# 数据生命周期（断链修复方案 M3）：审计展示层条数封顶（写点裁剪，
# 保留最新 N 条 + 原子替换；与 CAPTURE_HITS_MAX_LINES 同风格）。
NOTIFICATIONS_MAX_LINES = 500    # 可重建的展示层，丢失不伤资产
DRAFTS_MAX_LINES = 200           # 草稿是待处理行动项，>200 条即长期无人处理
# CHANGELOG_MAX_LINES / CHLOG_KINDS / _parse_changelog_line / _format_changelog_line
# 已随「学习历程」域搬到 app/store/changelog.py——均只服务于
# changelog.md。这里保留同名再导出，兼容既有 import。
from .changelog import (CHANGELOG_MAX_LINES,  # noqa: E402,F401
                        CHLOG_KINDS,  # noqa: E402,F401
                        MAINTENANCE_LOG_MAX_LINES,  # noqa: E402,F401
                        _format_changelog_line,  # noqa: E402,F401
                        _parse_changelog_line)
# MAINTENANCE_LOG_MAX_LINES 已随「学习历程」域搬到 app/store/changelog.py（同上），
# 这里保留同名再导出。
TRIGGER_LOG_MAX_LINES = 500

# ---------- changelog v2 机器标记（学习历程信息量控制，方案） ----------
# 行格式：- [ts] [kind k=v k=v ...] 人话文本
# 标记是机器状态，文本是用户陈述，两者独立：n（累计条数）/times（复盘次数）/
# solidified（固化到的版本）只活在标记里；edit_changelog 只动文本段，标记段原样
# 保留。值可含中文与 /，不含空格、方括号；sid 存完整 session_id（防前缀碰撞）。
# 无标记行按 legacy 读取（tag=None），永不回写。
CHLOG_KINDS = frozenset((
    "review", "self", "distill", "fixes", "veto", "rename",
    "pref-inc", "pref-reinduct", "pref-self", "pref-edit", "ach",
    "ai-rewrite",
    # 两个此前写不进 changelog 的 kind（append_event 会 raise ValueError，
    # 调用方各自 try/except 吞掉 → 记录静默丢失）：
    # - governance：内容治理（扫了多少张、标了多少张，只标记不删除）；
    # - guard：策展守卫告警（产出可疑/丢失已固化失败模式）。
    # 展示层对未专门分派的 kind 走通用分支（原文照显），新增不会破坏既有解析。
    "governance", "guard",
))
_CHLOG_TAG_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<kind>[a-z][a-z0-9-]*)"
    r"(?P<pairs>(?:\s+[a-z][a-z0-9-]*=[^\s\[\]]+)*?)\]\s+(?P<text>.*)$")
_CHLOG_PAIR_RE = re.compile(r"[a-z][a-z0-9-]*=[^\s\[\]]+")


def _parse_changelog_line(line: str) -> tuple[str, dict | None, str]:
    """changelog 行 → (ts, tag, text)。

    v2 标记行 → tag={"kind": ..., k: v, ...}；legacy 行（无标记）、kind 不在
    枚举、或标记解析失败 → tag=None、text 原样（不抛错、不合并、不折叠）。"""
    rest = line.lstrip("- ").strip()
    m = _CHLOG_TAG_RE.match(rest)
    if m and m["kind"] in CHLOG_KINDS:
        tag: dict[str, str] = {"kind": m["kind"]}
        for pair in _CHLOG_PAIR_RE.findall(m["pairs"]):
            k, _, v = pair.partition("=")
            tag[k] = v
        return m["ts"].strip(), tag, m["text"].strip()
    ts = ""
    if rest.startswith("[") and "] " in rest:
        ts, _, rest = rest[1:].partition("] ")
        ts = ts.strip()
    return ts, None, rest


def _format_changelog_line(ts: str, tag: dict | None, text: str) -> str:
    """(ts, tag, text) → changelog 行（tag 为 None 时即 legacy 格式）。"""
    if tag:
        pairs = " ".join(f"{k}={v}" for k, v in tag.items() if k != "kind")
        tag_str = f"[{tag['kind']}" + (f" {pairs}" if pairs else "") + "]"
        return f"- [{ts}] {tag_str} {text}"
    return f"- [{ts}] {text}"


# rule 源读取侧升级（修复方案）：T1 坑卡落库恒 G=0.4，seen_in 独立会话数
# ≥3 时在读取视图升为可注入档。store 不 import distill——两常量以护栏测试
# （tests/test_value_gate.py + test_rule_pipeline.py）锁定与
# gsignal.RULE_PROMOTED/RULE_PROMOTE_SESSIONS 对齐。
_RULE_PROMOTED_G = 0.55
_RULE_PROMOTE_SESSIONS = 3


def _normalize_read_view(exp: dict) -> dict:
    """iter_experiences 唯一收口：契约内保证数值字段可读 + rule 源读取侧升档。
    SQLite 主读路径的 data 列存整条原 JSON、JSONL 回退读
    原样解析——存量/外部编辑的坏 G/importance/count 在这里统一净化（坏值按
    0/1），下游十余处裸 float(e["G"])/int(e["count"]) 消费方不必各自设防。
    命中才复制 dict，干净数据零开销直通。
    rule 源升档口径（修复方案）：复现集 = seen_in ∪ {自身 session_id}；
    user_valid 直接过线、user_rejected 压回——与 gsignal.effective_g 一致
    （护栏测试锁定）。T1 坑卡落库恒 G=0.4，独立会话数 ≥3 升为可注入档。"""
    g_raw, g_val = exp.get("G"), None
    try:
        g_val = float(g_raw or 0)
    except (TypeError, ValueError):
        g_val = 0.0
    imp_raw = exp.get("importance")
    imp = None
    if imp_raw is not None:
        try:
            imp = int(float(imp_raw))
        except (TypeError, ValueError):
            imp = 0
    count_raw = exp.get("count")
    count = None
    try:
        count = int(count_raw or 1)
    except (TypeError, ValueError):
        count = 1

    promote = False
    if (exp.get("g_source") == "rule" and g_val < _RULE_PROMOTED_G
            and not exp.get("user_rejected")):
        # 价值闸门防御（方案）：环境抖动/源码回声即便残留在库也永不升档注入。
        if exp.get("value_class") not in ("env_transient", "signature_garbage"):
            if exp.get("user_valid"):
                promote = True
            else:
                seen = exp.get("seen_in")
                ids = {str(s) for s in (seen if isinstance(seen, list) else []) if s}
                if exp.get("session_id"):
                    ids.add(str(exp["session_id"]))
                promote = len(ids) >= _RULE_PROMOTE_SESSIONS

    dirty = (g_raw is not None and g_val != g_raw) or (imp_raw is not None and imp != imp_raw) \
        or ("count" not in exp) or (count_raw is not None and count != count_raw) or promote
    if not dirty:
        return exp
    out = dict(exp)
    out["G"] = g_val
    if imp_raw is not None:
        out["importance"] = imp
    out["count"] = count
    if promote:
        out["G"] = _RULE_PROMOTED_G
    return out


# record_session 超纲字段 warning 去重（进程内每字段名一次，防逐记录刷屏）
_warned_session_fields: set[str] = set()

# M-5：经验类别派生索引（categories_index.json）——请求路径读小索引，
# 不再每请求全量扫 experience.jsonl；索引只依赖 trunk/category/task 三字段，
# 全部经验写口重建（低频），读口缺失时现场重建自愈。
CATEGORY_INDEX_NAME = "categories_index.json"
CATEGORY_TASK_KEEP = 20

# 经验文本字段长度上限（task/action/outcome，超出截断）
_EXP_FIELD_MAX = 8000


# _SKILL_CREATED_RE / _skill_created_date 已随「方法卡」域搬到
# app/store/skill.py（成长域 growth_summary 从那里取）。
# _median 已随「成长页」域搬到 app/store/growth.py。


def affinity_display(key: str) -> str:
    """affinity 键 `agent/trunk/category` → 展示串 `agent · category`。

    语义是"和*某个 agent*协作这类任务的顺度"，展示突出 agent 与类别两级；
    agent 缺失（unknown 桶）只展示类别（"unknown"不是人话）；两段键（旧格式
    兜底）同样只取末段类别。纯函数无 I/O，放 store 是因为键格式在此定义。"""
    parts = key.split("/")
    if len(parts) == 3 and parts[0] not in ("", "unknown"):
        return f"{parts[0]} · {parts[2]}"
    return parts[-1]


# ---------- 成长页全景口径（重构思） ----------

# 成长页口径常量（_REWORK_* / _WEEKLY_MAX / _LEDGER_TOP_N）已随
# 「成长页」域搬到 app/store/growth.py；_safe_int / _safe_float / _sess_stamp 是
# 跨域共用件，已下沉到 app/store/_shared.py（store 与各 mixin 都从那里取）。

_LIST_FIELDS = ("user_messages", "assistant_messages", "events")


def _merge_session_record(base: dict, incoming: dict) -> tuple[dict, bool]:
    """同一会话的两版记录做**字段级合并**，不是整行替换。

    两边各自缺不同的字段是常态：扫描通道有 started_at 没有 req_count，代理通道
    相反。整行替换必然丢一半——实测：代理通道那条有 req_count 却丢了时间戳，
    rank 更高，把后来带 ts 的扫描记录挡在外面，结果没有任何一版是完整的。

    合并规则（CDC/MERGE 口径，不靠到达顺序决胜负）：
    - 转录类列表（user/assistant/events）取更长的一版（后一轮扫描通常更全）；
    - 其余字段 incoming 有值就用 incoming（它代表更新的观测），否则保留 base；
    - 返回 (合并结果, 是否有变化)，无变化时调用方不写盘——append-only 冗余的
      主要来源就是反复落内容相同的行。
    """
    out = dict(base)
    changed = False
    for k, v in incoming.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        if k in _LIST_FIELDS:
            if len(v) > len(out.get(k) or []):
                out[k] = v
                changed = True
            continue
        if out.get(k) != v:
            out[k] = v
            changed = True
    return out, changed


# _session_ident 已下沉到 app/store/_shared.py（Store 主体与
# 成长域共用）；_session_day / _week_of 随「成长页」域搬到 app/store/growth.py。


# 成长页全景口径 growth_panorama() 已随「成长页」域搬到
# app/store/growth.py（store 侧保留同名再导出，见下方 import）。


def _ts_older_than(ts: str, cutoff: datetime) -> bool:
    """ISO 时间戳（尾 Z 按 UTC）是否早于 cutoff；空/解析失败 → False（保留）。

    去重 R1：解析统一走 app.time_util.parse_ts（返回值必为 aware UTC），
    此处再去掉时区与 naive 的 cutoff 对齐比较。
    """
    dt = parse_ts(ts)
    if dt is None:
        return False
    return dt.replace(tzinfo=None) < cutoff


# `_safe` 已抽到 app/store/_shared.py——`Store` 按域拆 mixin 后，
# 各 mixin 要用它但不能反向 import 本模块（循环导入），故集中放置后共同引用。
from ._shared import _safe  # noqa: E402,F401


# normalize_rule 已随「规则通道」域搬到 app/store/rules.py，
# 这里保留同名再导出，兼容既有 import。
from .rules import normalize_rule  # noqa: E402,F401


# default_data_dir / resolve_data_dir / _dir_stats / cleanup_pending_data_dir
# 已随域搬到 app/store/data_dir.py，这里保留同名再导出
# （main.py / daemon.py / tests 都从 app.store.store import 它们）。
from .data_dir import (DataDirMixin,  # noqa: E402
                       cleanup_pending_data_dir,  # noqa: E402,F401
                       default_data_dir,  # noqa: E402,F401
                       default_engine_log_file,  # noqa: E402,F401
                       default_log_file,  # noqa: E402,F401
                       resolve_data_dir)  # noqa: E402,F401


# 复盘队列背压 / 复盘台账 / 在飞窗口已随域搬到 app/store/review_queue.py
# （L4 第十一个域）。常量与 ReviewQueueMixin 一并搬走，这里保留
# 同名再导出——app.capture.scan 与 tests/test_h7_* 从 app.store.store import 它们，
# 其中 test_h7_* 还 monkeypatch 打桩 store_mod.REVIEW_RETRY_AFTER_S（注意：常量
# 搬家后打桩目标要跟着改到 app.store.review_queue，否则改的是这个再导出副本）。
from .review_queue import (PENDING_ARCHIVE_FILE,  # noqa: E402,F401
                           PENDING_ARCHIVE_MAX_LINES,  # noqa: E402,F401
                           PENDING_REVIEWS_FILE,  # noqa: E402,F401
                           PENDING_REVIEWS_MAX_LINES,  # noqa: E402,F401
                           REVIEWED_FILE,  # noqa: E402,F401
                           REVIEWED_MAX_LINES,  # noqa: E402,F401
                           REVIEW_QUEUED_FILE,  # noqa: E402,F401
                           REVIEW_QUEUED_MAX_LINES,  # noqa: E402,F401
                           REVIEW_RETRY_AFTER_S,  # noqa: E402,F401
                           ReviewQueueMixin)  # noqa: E402


# `Store` 按域拆 mixin。原始规模 3538 行 / `class Store` 2796 行
# / 148 方法；拆分后见文末「拆分台账」。对外 API 与语义一律不变（纯搬家）。
#
# 【刻意留在主体的部分——不要为了拆而拆】
# 经验与会话的**写侧**（append_experience / _build_dup_index / _find_duplicate /
# _build_category_index / record_session / prune_sessions / _session_index …）继续
# 留在 `class Store`，原因是它们围绕 `self._write_lock`、索引缓存（`_session_index`
# / `_expdb` / `_category_index`）与文件内容三者的**更新顺序**紧密咬合：
# 1. 拆开后"先改索引还是先落文件"极易错位，错位时**测试不会变红**——只会在
# 真实使用中让索引与 JSONL 悄悄不一致，是最难发现的一类数据错误；
# 2. 收益主要只是行数（缩水已过半：3538 → 1691 行 / 148 → 77 方法）。
# 权衡下来不值得为再缩几百行去赌数据正确性。若将来要拆，前提是先把"索引更新"
# 与"文件写入"收敛成单一入口（由 Store 持有、mixin 只调用），再谈搬家。
from .changelog import ChangelogMixin  # noqa: E402
from .injection import InjectionMixin  # noqa: E402
from .preferences import PreferencesMixin  # noqa: E402
from .rules import OverridesMixin, RulesMixin  # noqa: E402
from .experience import ExperienceMixin  # noqa: E402
from .session import SessionMixin  # noqa: E402
from .skill import SkillMixin  # noqa: E402
from .capture_state import CaptureStateMixin  # noqa: E402
# growth_panorama 是模块级纯函数，成长页/周报直接用它；这里同名再导出以兼容
# 既有 `from app.store.store import growth_panorama`。
from .growth import GrowthMixin, growth_panorama  # noqa: E402,F401


class Store(RulesMixin, SkillMixin, ExperienceMixin, SessionMixin,
            ChangelogMixin, InjectionMixin, OverridesMixin, PreferencesMixin,
            GrowthMixin, DataDirMixin, CaptureStateMixin, ReviewQueueMixin):
    """用户数据目录（默认 ~/.experientia/，可经设置页更换）的唯一读写入口。

    未来加同步只动这一层，不动资产格式。
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        if data_dir:
            self.data_dir = Path(data_dir)
            self.data_dir_fallback = False
        else:
            self.data_dir, self.data_dir_fallback = resolve_data_dir()
        self._write_lock = threading.Lock()
        # 热路径文本缓存（M-5）：str(path) → (mtime_ns, size, text)。
        # 注入每次 LLM 请求组装一次，每次重读 playbook/偏好/规则文件——
        # 有缓存后命中 = 1 次 stat，未命中才 open+read。
        self._file_cache: dict[str, tuple[int, int, str]] = {}
        # C-14：经验去重索引（(agent, task, action) → record），append_experience 写锁下使用
        self._dup_index: dict[tuple[str, str, str], dict] | None = None
        # C-15：session 去重索引（(agent, session_id) → record），record_session 写锁下使用
        self._session_index: dict[tuple[str, str | None], dict] | None = None
        # 档 A：复盘台账内存集（(agent, session_id) → 已复盘），懒加载
        self._reviewed: set[tuple[str, str]] | None = None
        self._queued_reviews: dict[tuple[str, str], str] | None = None
        # SQLite 经验读索引（experience.db）：None = 索引不可用，读路径回退 JSONL
        self._expdb = self._init_expdb()
        # 经验脏计数——每 N 次写触发一次 JSONL 快照导出（见 maybe_export_...）
        self._exp_dirty = 0
        # 经验写世代（成长域结果缓存失效用，见 growth.py）
        self._exp_write_gen = 0
        # 启动时若上次有写库失败遗留，先只插不删地补回库
        try:
            self._reconcile_jsonl_ahead()
        except Exception as exc:
            logger.warning("启动经验对账失败（保留标记待下次）: %s", exc)

    def _init_expdb(self) -> ExperienceDB | None:
        """创建 SQLite 经验读索引并按 sha256 判定是否需要重建。

        任何失败（磁盘只读 / 库损坏且无法重建等）→ 返回 None 并 warning，
        全部读路径有 _expdb is None 时走原 JSONL 逻辑的回退（fail-open）。"""
        try:
            db = ExperienceDB(self.data_dir / "experience.db", self.data_dir)
            db.rebuild_if_stale(self.data_dir / "experience.jsonl")
            return db
        except Exception as exc:
            logger.warning("SQLite 经验索引初始化失败，读路径回退 JSONL: %s", exc)
            return None

    # ---------- 经验快照导出（SQLite 唯一事实源 → JSONL 降级为导出/备份格式） ----------

    EXPERIENCE_SNAPSHOT_MIN_DIRTY = 20

    def _reconcile_jsonl_ahead(self) -> int:
        """：把 JSONL 独有的经验行补进 SQLite（**只插不删**）。

        只在待对账标记置位（某次 SQLite 写失败）时执行。语义边界：
        - 新记录写库失败 → 补插（保数据，主要场景）；
        - 更新写库失败 → 库里旧值仍在，JSONL 本就旧，无从恢复，跳过；
        - 删除写库失败 → 库里有、JSONL 也有，id 已存在 → 跳过；
        **绝不按 JSONL 反删库中行**——那会把已退休的行复活。
        返回补插条数；未补完（又失败）时保留标记留待下次。"""
        db = self._expdb
        if db is None or not db.jsonl_ahead():
            return 0
        have = db.existing_ids()
        added = 0
        for rec in self._iter_jsonl("experience.jsonl"):
            rid = str(rec.get("id") or "")
            if not rid or rid in have:
                continue
            try:
                db.update_many({rid: rec})
            except Exception as exc:
                logger.error("JSONL 待对账补齐失败（保留标记待下次）: %s", exc)
                return added
            added += 1
        db.clear_jsonl_ahead()
        if added:
            logger.info("JSONL 待对账：补齐 %d 条经验进 SQLite（只插不删）", added)
        return added

    def export_experience_snapshot(self) -> int:
        """把 SQLite 全量经验**原子导出**为 experience.jsonl（备份/回退格式）。

        仅由显式动作 / 定期快照触发；运行期任何读路径都不消费本文件（仅
        `_expdb is None` 的降级路径读它）。返回导出条数；索引不可用 → 0（不动文件）。"""
        db = self._expdb
        if db is None:
            return 0
        # 全表物化必须在写锁内——原在锁外，读表之后、
        # 持锁之前发生的 append_experience 会被快照遗漏，而它的脏计数又被
        # 下面无条件清零 → JSONL 备份长期缺行（一旦索引降级回退 JSONL 就少数据）。
        with self._write_lock:
            # 导出是"整文件从库重写"——若库正缺着 JSONL
            # 独有的行（某次写库失败），先只插不删地对账，否则这一步会抹掉它们。
            try:
                self._reconcile_jsonl_ahead()
            except Exception as exc:
                logger.warning("导出前对账失败（继续导出）: %s", exc)
            rows = list(db.all_for_category_index())
            content = "".join(
                json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
            self._write_tmp_rename(self.data_dir / "experience.jsonl", content)
            self._exp_dirty = 0
        return len(rows)

    def maybe_export_experience_snapshot(self) -> int:
        """定期快照：脏计数达 EXPERIENCE_SNAPSHOT_MIN_DIRTY 才导出（scan_loop 每轮
        调用；未达阈值零开销短路）。"""
        if self._expdb is None:
            return 0
        if getattr(self, "_exp_dirty", 0) < self.EXPERIENCE_SNAPSHOT_MIN_DIRTY:
            return 0
        return self.export_experience_snapshot()

    def _write_experiences_sqlite(self, updates: dict[str, dict | None], *,
                                  line_delta: int = 0) -> bool:
        """经验写收口：索引可用 → 只写 SQLite（唯一事实源，**不再整文件重写
        JSONL**）；索引不可用（fail-open 降级）→ 返回 False，由调用方回退原 JSONL
        写路径（绝不丢数据）。调用方须持 `_write_lock`。"""
        if self._expdb is None:
            return False
        self._sync_experience_index(updates, line_delta=line_delta)
        # 经验写世代（单调递增）——成长域结果缓存按它失效。
        # 不能用 JSONL 文件签名：SQLite 事实源模式下**更新与删除只写库**，
        # JSONL 要等 20 次脏写的快照导出才变，纯索引写连缓存都刷不掉。
        self._exp_write_gen = getattr(self, "_exp_write_gen", 0) + 1
        return True

    def _append_experience_jsonl(self, rec: dict) -> None:
        """降级路径（索引不可用）：把新记录追加进 JSONL（append-only，不丢数据）。
        调用方须持 `_write_lock`。"""
        with (self.data_dir / "experience.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _sync_experience_index(self, updates: dict[str, dict | None],
                               line_delta: int = 0) -> None:
        """写路径双写收口：JSONL 落盘后，把同批变更同步进 SQLite 读索引。

        updates 值为 None 表示删除（retire 移入 deprecated）。line_delta 传给
        mark_synced 做 meta 行数增量记账（新增 +1 / 删除 -1，原地更新为 0）。
         遗留：mark_synced 不再每写全量重算 sha256（取舍见
        ExperienceDB.mark_synced docstring）。失败自愈：先尝试
        从 JSONL 全量重建；重建也失败 → 停用索引（读路径回退 JSONL），
        下次启动 rebuild_if_stale 自动重 build。必须在 _write_lock 内调用。"""
        db = self._expdb
        if db is None or not updates:
            return
        try:
            db.update_many(updates)
            if db.is_sqlite_source:
                # 唯一事实源模式——不维护 JSONL 指纹（JSONL 是低频导出快照）。
                # 累计脏计数，达阈值由 maybe_export_experience_snapshot 触发导出。
                self._exp_dirty = getattr(self, "_exp_dirty", 0) + len(updates)
            else:
                db.mark_synced(self.data_dir / "experience.jsonl",
                               line_delta=line_delta)
        except Exception as exc:
            logger.warning("经验索引写失败: %s", exc)
            if db.is_sqlite_source:
                # 唯一事实源模式：**绝不从陈旧 JSONL 重建**（那会丢数据），也**不**
                # 停用索引（停用会让所有读路径回退到陈旧快照）——留索引，下次自愈。
                # 光"留索引"不够——新记录此时已 append 进
                # JSONL，而它不被任何读路径消费，且会被下一次快照导出整文件抹掉。
                # 置待对账标记，由 _reconcile_jsonl_ahead 只插不删地补回库。
                logger.error("SQLite 事实源模式下写入失败，置待对账标记（不回退 JSONL）")
                try:
                    db.mark_jsonl_ahead()
                except Exception as mexc:
                    logger.error("置待对账标记也失败（只能等下次写路径重试）: %s", mexc)
                return
            logger.warning("尝试从 JSONL 全量重建索引")
            try:
                db.rebuild(self._iter_jsonl("experience.jsonl"))
                db.mark_synced(self.data_dir / "experience.jsonl")
            except Exception as exc2:
                logger.warning("经验索引重建失败，停用索引（读路径回退 JSONL）: %s", exc2)
                self._expdb = None

    def _sync_experience_index_category(self, trunk: str, old_category: str,
                                        new_category: str) -> None:
        """分类迁移（rename_skill）双写：SQLite 索引内同批改写 category
        （索引列 + data JSON，与 _rewrite_category_field 的 JSONL 行为一致）。
        失败自愈策略同 _sync_experience_index。必须在 _write_lock 内调用。"""
        db = self._expdb
        if db is None:
            return
        try:
            db.rewrite_category(trunk, old_category, new_category)
            if db.is_sqlite_source:
                self._exp_dirty = getattr(self, "_exp_dirty", 0) + 1
            else:
                db.mark_synced(self.data_dir / "experience.jsonl")
        except Exception as exc:
            logger.warning("经验索引分类迁移同步失败: %s", exc)
            if db.is_sqlite_source:
                logger.error("SQLite 事实源模式下分类改写失败，保留索引待自愈")
                return
            try:
                db.rebuild(self._iter_jsonl("experience.jsonl"))
                db.mark_synced(self.data_dir / "experience.jsonl")
            except Exception as exc2:
                logger.warning("经验索引重建失败，停用索引（读路径回退 JSONL）: %s", exc2)
                self._expdb = None

    @contextmanager
    def write_lock(self):
        """公开的写锁上下文管理器（外部模块如 notify.py 使用，避免直接访问 _write_lock）。"""
        with self._write_lock:
            yield

    # ---------- 布局与配置 ----------

    def dir(self, name: str) -> Path:
        """受控子目录句柄（name ∈ ASSET_DIRS）。业务模块经此取目录，不裸拼 data_dir。
        仅在确有文件级操作需求（归档拷贝/备份快照/迁移改名）时用；解析类状态一律走本类方法。"""
        if name not in ASSET_DIRS:
            raise ValueError(f"未知数据子目录: {name}")
        p = self.data_dir / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ensure_layout(self) -> None:
        for name in ASSET_DIRS:
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
        for fname in ("experience.jsonl", "sessions.jsonl", "changelog.md"):
            path = self.data_dir / fname
            if not path.exists():
                path.touch()

    # migrate_data_dir() 已随域搬到 app/store/data_dir.py 的 DataDirMixin。

    # ---------- Incoming（skill 自报报告落地，总方案 S2） ----------

    def incoming_dir(self) -> Path:
        """skill probe 落盘目录：report 以 <上报码>.json 命名，scan 每轮吸收。"""
        p = self.data_dir / "incoming"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save_incoming_report(self, code: str, report: dict) -> Path:
        path = self.incoming_dir() / f"{code}.json"
        self._write_json_tmp_rename(path, report)
        return path

    def load_incoming_report(self, code: str) -> dict | None:
        """按上报码读回报告；码非法/文件坏 → None（码即文件名，先做字符集门禁）。"""
        code = (code or "").strip()
        if not (0 < len(code) <= 40) or any(c not in _CODE_CHARS for c in code):
            return None
        path = self.data_dir / "incoming" / f"{code}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def list_incoming_codes(self) -> list[str]:
        p = self.data_dir / "incoming"
        if not p.is_dir():
            return []
        try:
            return sorted(f.stem for f in p.glob("*.json")
                          if all(c in _CODE_CHARS for c in f.stem))[:200]
        except OSError:
            return []

    def drop_incoming_report(self, code: str) -> None:
        code = (code or "").strip()
        if not (0 < len(code) <= 40) or any(c not in _CODE_CHARS for c in code):
            return
        try:
            (self.data_dir / "incoming" / f"{code}.json").unlink(missing_ok=True)
        except OSError:
            pass

    # ---------- 钥匙明细（Keys：吸收后完整接入情报落盘，供常态化捕获复用；总方案钥匙） ----------

    def keys_dir(self) -> Path:
        """钥匙明细目录：<上报码>.json，与 incoming 同生命周期管理、吸收后保留。"""
        p = self.data_dir / "keys"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save_key_manifest(self, code: str, manifest: dict) -> None:
        """落一份钥匙明细（含 cleaned report + 本机环境底座）。码非法直接跳过。"""
        code = (code or "").strip()
        if not (0 < len(code) <= 40) or any(c not in _CODE_CHARS for c in code):
            return
        self._write_json_tmp_rename(self.keys_dir() / f"{code}.json", manifest)

    def load_key_manifest(self, code: str) -> dict | None:
        """按码读回钥匙明细；码非法/文件坏 → None。"""
        code = (code or "").strip()
        if not (0 < len(code) <= 40) or any(c not in _CODE_CHARS for c in code):
            return None
        path = self.data_dir / "keys" / f"{code}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def list_key_codes(self) -> list[str]:
        """已吸收钥匙码列表（倒序=最新在前）。"""
        p = self.data_dir / "keys"
        if not p.is_dir():
            return []
        try:
            codes = sorted((f.stem for f in p.glob("*.json")
                            if all(c in _CODE_CHARS for c in f.stem)),
                           reverse=True)[:200]
        except OSError:
            return []
        return codes

    def delete_key_manifest(self, code: str) -> None:
        """删除一份钥匙明细（仅历史记录，不影响已激活的捕获通道）。"""
        code = (code or "").strip()
        if not (0 < len(code) <= 40) or any(c not in _CODE_CHARS for c in code):
            return
        try:
            (self.data_dir / "keys" / f"{code}.json").unlink(missing_ok=True)
        except OSError:
            pass

    # ---------- 捕获通道（Keys 激活：吸收后反哺 detect，实现常态化捕获） ----------

    CAPTURE_CHANNELS_FILE = "capture_channels.json"

    def load_capture_channels(self) -> dict:
        """{agent: {key, mode, at, sources:[{path,format,kind}], hook_paths:[...]}}。"""
        path = self.data_dir / self.CAPTURE_CHANNELS_FILE
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def save_capture_channels(self, channels: dict) -> None:
        self._write_json_tmp_rename(self.data_dir / self.CAPTURE_CHANNELS_FILE,
                                    channels)

    # ---------- 自报状态（self-reported，connect 页展示；总方案 S2） ----------

    SELF_REPORTED_FILE = "self_reported.json"

    def record_self_reported(self, agent: str, summary: dict) -> None:
        """记录一次 skill 自报吸收结果（agent → {at, mode, note, …}，原子写）。"""
        if not agent:
            return
        path = self.data_dir / self.SELF_REPORTED_FILE
        with self._write_lock:
            raw: dict = {}
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                raw = data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, OSError):
                pass
            raw[str(agent)] = {"at": utcnow(), **(summary or {})}
            self._write_json_tmp_rename(path, raw)

    def load_self_reported(self) -> dict:
        """{agent: {at, mode, note, …}}；坏文件/缺文件 → 空。"""
        path = self.data_dir / self.SELF_REPORTED_FILE
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    # ---------- meta.json（数据目录级迁移版本与后台旗标） ----------

    META_FILE = "meta.json"

    def load_meta(self) -> dict:
        """{data_version, backfill_pending, ...}；坏文件/缺文件 → 空 dict。"""
        path = self.data_dir / self.META_FILE
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def save_meta(self, patch: dict) -> dict:
        """合并写回 meta.json（tmp+rename 原子替换），返回合并后容器。"""
        with self._write_lock:
            raw: dict = {}
            path = self.data_dir / self.META_FILE
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    raw = data if isinstance(data, dict) else {}
                except (json.JSONDecodeError, OSError):
                    raw = {}
            raw.update(patch or {})
            self._write_json_tmp_rename(path, raw)
            self.invalidate_cache(path)
            return raw

    def load_config(self) -> dict:
        # M-5：代理热路径每请求读多次——走 mtime+size 校验缓存，
        # save_config 的 os.replace 换 inode 必触发重读，无需显式失效。
        path = self.data_dir / "config.json"
        text = self.read_text_cached(path)
        if text is None:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    def save_config(self, config: dict) -> None:
        path = self.data_dir / "config.json"
        self._write_json_tmp_rename(path, config, indent=2)
        self.invalidate_cache(path)
        # SEC-1：config.json 可能含路由/口令类元信息 → POSIX 收紧为 0600
        # （Windows 无 POSIX 权限位，依赖用户目录 ACL；best-effort 不打断写路径）
        if os.name != "nt":
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass

    def mutate_config(self, mutate) -> dict:
        """写锁内完成 config.json 的读-改-写。

        mutate(config) 就地改或返回新 dict；返回 None = 判定无变化、不落盘。
        一切「先读后写」的并发计数/状态（如模型熔断器）必须走本入口——
        无锁读-改-写会与设置页保存互相覆盖（丢状态或丢用户刚改的路由）。
        注意：mutate 内禁止回调本 Store 的其他加锁写方法（Lock 不可重入）。"""
        with self._write_lock:
            config = self.load_config()
            result = mutate(config)
            if result is None:
                return config
            self.save_config(result)
            return result

    # wipe_all / _wipe_leftovers 已随域搬到 app/store/data_dir.py 的 DataDirMixin。

    def append_experience(self, rec: dict) -> dict:
        """追加一条经验。同 (agent, task, action) 合并计数，不重复存（count 语义）。"""
        rec = dict(rec)
        # 写口最小契约（fail-open，只归一不拒绝）——
        # G 非数字此前会在合并/读取侧 float() 时抛异常；文本字段无上限，
        # 异常载荷可把 experience.jsonl 撑爆。
        try:
            rec["G"] = float(rec.get("G") or 0)
        except (TypeError, ValueError):
            rec["G"] = 0.0
        try:
            rec["count"] = max(int(rec.get("count") or 1), 1)
        except (TypeError, ValueError):
            rec["count"] = 1
        # importance 不在写口契约内时，一条非数值脏值
        # 会在 growth_summary 读取侧 int() 抛异常击穿首页/成长 API。
        if rec.get("importance") is not None:
            try:
                rec["importance"] = int(float(rec["importance"]))
            except (TypeError, ValueError):
                rec.pop("importance", None)
        for _f in ("task", "action", "outcome"):
            _v = rec.get(_f)
            if isinstance(_v, str) and len(_v) > _EXP_FIELD_MAX:
                rec[_f] = _v[:_EXP_FIELD_MAX]
        rec.setdefault("id", str(uuid.uuid4()))
        rec.setdefault("ts", utcnow())
        rec.setdefault("count", 1)
        rebuild_cat = False  # 锁内只置标，重建在锁外做
        with self._write_lock:
            dup = self._find_duplicate(rec)
            if dup is not None:
                dup["count"] = max(int(dup.get("count", 1)) + 1,
                                   int(rec.get("count") or 0))
                dup["G"] = max(float(dup.get("G", 0)), float(rec.get("G", 0)))
                # rule 源跨会话复现追踪（seen_in 并集封顶 30）：读取侧
                # _normalize_read_view 据此把复现 ≥3 会话的坑卡升过注入门槛。
                # 来件可自带 seen_in 全集（mine_all 全局签名 pass 一次携带
                # 多会话），不只单条 session_id
                _ids = {str(rec.get("session_id") or "")}
                if isinstance(rec.get("seen_in"), list):
                    _ids |= {str(x) for x in rec["seen_in"] if x}
                _ids.discard("")
                if _ids:
                    _seen = dup.get("seen_in")
                    if not isinstance(_seen, list):
                        _seen = []
                    _kept = [str(x) for x in _seen if str(x) not in _ids]
                    dup["seen_in"] = (_kept + sorted(_ids))[-30:]
                # G/count 更新不动 trunk/category/task → 免重建索引
                # 合并且只写 SQLite（唯一事实源），不再整文件重写 JSONL
                if not self._write_experiences_sqlite({dup["id"]: dup}):
                    self._update_jsonl("experience.jsonl", {dup["id"]: dup})
                # 同步更新去重索引（写锁内，安全）
                if self._dup_index is not None:
                    key = (rec.get("agent"), rec.get("task"), rec.get("action"))
                    if all(key):
                        self._dup_index[key] = dup
                result = dup
            else:
                # 新记录 **JSONL 追加（低成本 O(1)，保留备份/遗留迁移可用）+
                # SQLite 写入（唯一事实源）**；更新类写不再重写 JSONL（消除 O(N)），
                # 由定期/显式快照导出对齐。索引不可用时 append 已保数据不丢。
                self._append_experience_jsonl(rec)
                self._write_experiences_sqlite({rec["id"]: rec}, line_delta=1)
                # 新增记录也同步去重索引
                key = (rec.get("agent"), rec.get("task"), rec.get("action"))
                if all(key) and self._dup_index is not None:
                    self._dup_index[key] = rec
                # 只有新增经验且 trunk/category/task 存在才重建索引
                # 增量写入需要重建：新增 task → 类别索引要包含它
                if rec.get("trunk") and rec.get("category") and rec.get("task"):
                    rebuild_cat = True  # 重建移出写锁（见锁后注释）
                else:
                    # 缺关键字段但仍允许写入，索引不完整由读取侧自愈重建
                    self.invalidate_cache(self.data_dir / CATEGORY_INDEX_NAME)
                result = rec
        # 类别索引重建（O(N) 全表读 + 整文件写）移出写锁。
        # 原来是持着全局写锁做：经验上千条后，每落一条经验都在锁内做全表扫，
        # 阻塞 record_session / record_rule_hits / record_injection 等所有写者。
        # 该索引是派生读侧索引，detect.py:202-204 有"读到 None 即重建"的自愈，
        # 锁外重建最多重复一次（内容相同，原子写覆盖）。
        if rebuild_cat:
            try:
                self.rebuild_category_index()
            except Exception as exc:
                logger.warning("类别索引重建失败（读取侧自愈重建）: %s", exc)
        # 锁外统一接第⑤环「注入——结果——回填」：新经验落库即回馈到它引用的
        # 注入条目（佐证/反驳）。反馈只增强不拖垮主落库——任异常静默忽略
        # （防错误传播：反馈异常不得让经验落库失败）。
        try:
            self.apply_injection_feedback(result)
        except Exception as exc:
            logger.warning("经验反馈回填异常(忽略): %s", exc)
        return result

    # ---------- 经验上报草稿（S5 ：无 LLM 时唯一去向 = 草稿待手动放行） ----------

    DRAFTS_FILE = "experience_drafts.jsonl"

    def append_experience_draft(self, rec: dict) -> dict:
        """追加一条自报经验草稿（默认 pending）。status: pending/adopted/ignored/auto/rejected。"""
        rec = dict(rec)
        rec.setdefault("id", str(uuid.uuid4()))
        rec.setdefault("status", "pending")
        rec.setdefault("ts", utcnow())
        with self._write_lock:
            with (self.data_dir / self.DRAFTS_FILE).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            # 写点封顶 200 条：草稿是待用户处理的行动项，>200 条即长期无人
            # 处理，最旧的自然失效
            self._cap_jsonl_lines(self.data_dir / self.DRAFTS_FILE, DRAFTS_MAX_LINES)
        return rec

    def iter_drafts(self, status: str | None = None):
        for item in self._iter_jsonl(self.DRAFTS_FILE):
            if status is None or item.get("status") == status:
                yield item

    def list_drafts(self, status: str | None = None) -> list[dict]:
        """最新在前。"""
        return list(self.iter_drafts(status))[::-1]

    def draft_count(self, status: str = "pending") -> int:
        return sum(1 for _ in self.iter_drafts(status))

    def set_draft_status(self, draft_id: str, status: str) -> bool:
        """按 id 更新草稿状态（整文件原子重写，草稿量小可承受）。"""
        found = False
        with self._write_lock:
            rows = list(self._iter_jsonl(self.DRAFTS_FILE))
            for r in rows:
                if r.get("id") == draft_id:
                    r["status"] = status
                    found = True
            content = "".join(
                json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
            self._write_tmp_rename(self.data_dir / self.DRAFTS_FILE, content)
        return found

    def _build_dup_index(self) -> dict[tuple[str, str, str], dict]:
        """全量构建去重索引（写锁下调用）。"""
        index: dict[tuple[str, str, str], dict] = {}
        for item in self._iter_jsonl("experience.jsonl"):
            key = (item.get("agent"), item.get("task"), item.get("action"))
            if all(key):
                index[key] = item
        return index

    def _find_duplicate(self, rec: dict) -> dict | None:
        key = (rec.get("agent"), rec.get("task"), rec.get("action"))
        if not all(key):
            # 缺字段时降级：用 session_id/project 做 fallback 合并键，避免经验库膨胀
            fallback = rec.get("session_id") or rec.get("session")
            if fallback:
                db = self._expdb
                if db is not None:
                    try:
                        return db.find_by_session(fallback)
                    except Exception as exc:
                        logger.warning("经验索引查重失败，回退 JSONL: %s", exc)
                        self._expdb = None
                for item in self._iter_jsonl("experience.jsonl"):
                    if (item.get("session_id") or item.get("session")) == fallback:
                        return item
            return None
        db = self._expdb
        if db is not None:
            # 有索引时按 agent/task/action 精确查（SQL 索引列，不全表扫）
            try:
                return db.find_duplicate(*key)
            except Exception as exc:
                logger.warning("经验索引查重失败，回退 JSONL: %s", exc)
                self._expdb = None
        if self._dup_index is None:
            self._dup_index = self._build_dup_index()
        return self._dup_index.get(key)

    def iter_experiences(
        self,
        trunk: str | None = None,
        category: str | None = None,
        agent: str | None = None,
        include_distilled: bool = False,
        show_dismissed: bool = False,
        surface: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict]:
        db = self._expdb
        if db is not None:
            # 读路径走 SQLite 索引（不再全文件读）。整体物化后再产出：
            # 迭代中途索引故障不能造成"半截结果 + JSONL 重放"的重复输出。
            # surface/limit 一并下推到 SQL（WHERE + LIMIT），不再 Python 逐条过滤。
            try:
                rows = list(db.iter_experiences(
                    include_distilled=include_distilled,
                    trunk=trunk, category=category, agent=agent,
                    show_dismissed=show_dismissed,
                    surface=surface, limit=limit))
            except Exception as exc:
                logger.warning("经验索引读失败，回退 JSONL: %s", exc)
                self._expdb = None
            else:
                yield from (_normalize_read_view(r) for r in rows)
                return
        from ..distill import value_gate
        emitted = 0
        for item in self._iter_jsonl("experience.jsonl"):
            if not show_dismissed and item.get("dismissed"):
                continue
            if not include_distilled and item.get("distilled"):
                continue
            if trunk is not None and item.get("trunk") != trunk:
                continue
            if category is not None and item.get("category") != category:
                continue
            if agent is not None and item.get("agent") != agent:
                continue
            if surface is not None and value_gate.surface_of(item) != surface:
                continue
            yield _normalize_read_view(item)
            emitted += 1
            if limit is not None and emitted >= int(limit):
                return

    def pending_experiences(self, trunk: str, category: str) -> list[dict]:
        return list(self.iter_experiences(trunk=trunk, category=category))

    def iter_dismissed_experiences(self) -> list[dict]:
        """返回所有已不采纳（dismissed=True）的经验记录。"""
        return list(self.iter_experiences(show_dismissed=True))

    # ---------- 经验类别派生索引（M-5） ----------

    def _build_category_index(self) -> dict[str, list[str]]:
        """全量扫经验库 → {"trunk/category": [最近 20 条 task 文本]}。

        数据源：有 SQLite 索引时走 experience.db，否则全量扫
        experience.jsonl。口径与 detect.known_categories_from_store 完全一致
        （含已蒸馏、task 去重保序、每类 20 条上限）；只在写路径（低频）调用。"""
        index: dict[str, list[str]] = {}
        source: Iterable[dict] | None = None
        db = self._expdb
        if db is not None:
            try:
                source = db.all_for_category_index()
                items = list(source)
            except Exception as exc:
                logger.warning("经验索引类别扫描失败，回退 JSONL: %s", exc)
                self._expdb = None
                source = None
            else:
                source = items
        if source is None:
            source = self._iter_jsonl("experience.jsonl")
        for item in source:
            trunk = str(item.get("trunk") or "其他")
            category = str(item.get("category") or "未分类")
            task = item.get("task")
            if not task:
                continue
            key = f"{trunk}/{category}"
            bucket = index.setdefault(key, [])
            task = str(task)
            if task not in bucket:
                bucket.append(task)
                if len(bucket) > CATEGORY_TASK_KEEP:
                    bucket.pop(0)
        return index

    def rebuild_category_index(self) -> dict[str, list[str]]:
        """重建并落盘类别索引（原子写 + 缓存失效），返回索引内容。

        经验写口统一调这里：append / 改 trunk·category·task 的 update /
        分类迁移；wipe_all 把索引文件随数据目录一起删掉，读口自愈重建。"""
        index = self._build_category_index()
        self._write_json_tmp_rename(self.data_dir / CATEGORY_INDEX_NAME, index)
        self.invalidate_cache(self.data_dir / CATEGORY_INDEX_NAME)
        return index

    def load_category_index(self) -> dict[str, list[str]] | None:
        """读类别索引（mtime 缓存）；文件缺失/损坏 → None（调用方重建）。"""
        text = self.read_text_cached(self.data_dir / CATEGORY_INDEX_NAME)
        if text is None:
            return None
        try:
            index = json.loads(text)
        except json.JSONDecodeError:
            return None
        return index if isinstance(index, dict) else None

    # ---------- 通用原子写工具 ----------

    def _write_tmp_rename(self, path: Path, content: str) -> None:
        """原子写文本：唯一命名 tmp → fsync → rename。

        多处需要该模式，统一复用避免重复书写相同 tmp+replace 逻辑。
        rename 只保证目录项原子替换，不保证数据已落盘——
        断电/蓝屏可留下截断的正式文件，且读侧 _iter_jsonl 会把坏行静默跳过
        （= 无声丢数据），所以 replace 前必须 fsync。临时名带 pid+随机后缀，
        防多进程并存（引擎锁失效时）互踩同一 .tmp；崩溃遗留的 *.tmp 由
        回采等扫描按后缀跳过，写前 unlink 清同名残留的旧职责一并废除。
        rename 走 fs_util.replace_atomic（带 Windows 瞬时锁重试）。"""
        tmp = path.with_name(
            f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            replace_atomic(tmp, path)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise

    def _write_json_tmp_rename(self, path: Path, data: dict | list, indent: int = 2) -> None:
        """原子写 JSON：委托 _write_tmp_rename 完成 tmp+rename。"""
        self._write_tmp_rename(path, json.dumps(data, ensure_ascii=False, indent=indent))

    def _cap_jsonl_lines(self, path: Path, max_lines: int) -> None:
        """写点封顶：保留最新 max_lines 行 + 原子替换（调用方持有 _write_lock）。

        封顶逻辑一律放 store 写方法内（数据层铁律），调用方无感。"""
        if not path.exists():
            return
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(lines) <= max_lines:
            return
        self._write_tmp_rename(path, "\n".join(lines[-max_lines:]) + "\n")
        self.invalidate_cache(path)

    def _append_jsonl_capped(self, path: Path, rec: dict, max_lines: int) -> None:
        """追加一行封顶日志：读现有非空行 → 追加 json.dumps(rec) → 超限裁尾部 →
        原子替换（调用方持有 _write_lock）。收口 record_capture_hit / record_injection
        两处逐字重复的"整读-追加-封顶-整写"样板。"""
        lines = ([l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
                 if path.exists() else [])
        lines.append(json.dumps(rec, ensure_ascii=False))
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        self._write_tmp_rename(path, "\n".join(lines) + "\n")
        self.invalidate_cache(path)

    # ---------- 洞察建议卡（W4-03：insights.jsonl） ----------

    def append_insight(self, rec: dict) -> dict:
        """追加一条建议卡（用户三选一结果 + 忽略计数落此文件）。"""
        rec = dict(rec)
        rec.setdefault("id", f"ins-{uuid.uuid4().hex[:12]}")
        with self._write_lock:
            with (self.data_dir / "insights.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def load_insights(self) -> list[dict]:
        return [x for x in self._iter_jsonl("insights.jsonl") if isinstance(x, dict)]

    def update_insight(self, insight_id: str, patch: dict) -> dict | None:
        """按 id 原地更新（action 三选一结果 / deferred 标记）。"""
        target = next((x for x in self._iter_jsonl("insights.jsonl")
                       if x.get("id") == insight_id), None)
        if target is None:
            return None
        merged = {**target, **patch}
        with self._write_lock:
            self._update_jsonl("insights.jsonl", {insight_id: merged})
        return merged

    def mark_experiences_distilled(self, ids: list[str]) -> int:
        """蒸馏完成后打标（已蒸馏条目不再参与下一次蒸馏）。

        读改走 experience.db 原始行（不回退"规范化读视图"，避免把展示期
        变换写回库）；写只落 SQLite，不再整文件重写 JSONL。"""
        idset = set(ids)
        with self._write_lock:  # 读-改-写同持锁——锁外快照会被并发合并交叠丢更新
            updates: dict[str, dict] = {}
            db = self._expdb
            src: Iterable[dict] | None = None
            if db is not None:
                try:
                    src = db.all_for_category_index()  # 全量原始行（含已蒸馏）
                except Exception as exc:  # noqa: BLE001
                    logger.warning("蒸馏打标读索引失败，回退 JSONL: %s", exc)
                    self._expdb = None
            if src is None:
                src = self._iter_jsonl("experience.jsonl")
            for item in src:
                if item.get("id") in idset and not item.get("distilled"):
                    item = dict(item)
                    item["distilled"] = True
                    updates[item["id"]] = item
            if updates:
                if not self._write_experiences_sqlite(updates):
                    self._update_jsonl("experience.jsonl", updates)
        return len(updates)

    # 单条经验的查找 / 老化归档 / 原地更新（find_experience / retire_experience /
    # update_experience）已搬到 app/store/experience.py 的 ExperienceMixin。

    def bump_experience_merge(self, exp_id: str, *, g_value=None,
                              seen_ids=None) -> dict | None:
        """并发安全的经验合并（count+1 / G 取大 / seen_in 并集封顶 30）。

        读、算、整文件重写全程持 `_write_lock`，用**当前行**
        派生 count/G/seen_in——取代 `dedupe.upsert_experience` 里"锁外快照
        算 `count=e.count+1` 再写回"的写法（那条与并发合并交叠会丢更新）。
        见 `app/distill/dedupe.py`。"""
        with self._write_lock:
            fresh = self.find_experience(exp_id)
            if fresh is None:
                return None
            merged = dict(fresh)
            merged["count"] = int(merged.get("count") or 1) + 1
            if g_value is not None:
                merged["G"] = max(_safe_float(merged.get("G")), _safe_float(g_value))
            ids = {str(x) for x in (merged.get("seen_in") or []) if x}
            if merged.get("session_id"):
                ids.add(str(merged["session_id"]))
            if seen_ids:
                ids |= {str(x) for x in seen_ids if x}
            ids.discard("")
            merged["seen_in"] = sorted(ids)[-30:]
            # 只写 SQLite（唯一事实源）；索引不可用才回退整文件重写
            if not self._write_experiences_sqlite({exp_id: merged}):
                self._update_jsonl("experience.jsonl", {exp_id: merged})
            if self._dup_index is not None:
                key = (merged.get("agent"), merged.get("task"), merged.get("action"))
                if all(key):
                    self._dup_index[key] = merged
            return merged


    def _iter_jsonl(self, fname: str) -> Iterator[dict]:
        path = self.data_dir / fname
        if not path.exists():
            return
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue  # 单条坏行跳过，不中断整体

    def _count_lines(self, path: Path) -> int:
        """非空行数（compaction 收益判定用：与去重后的会话数比大小）。"""
        try:
            with path.open(encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except OSError:
            return 0

    def _read_write_jsonl(self, path: Path, process_fn, trailing_newline: bool = True) -> None:
        """读 jsonl → 逐行解析 → process_fn(item) → 序列化 → tmp+rename 原子写回。

        process_fn 返回处理后的 item（可修改原 dict），返回 None 跳过该行。
        减少 _update_jsonl / _rewrite_category_field 等处的重复 IO 模式。
        读视图跳过坏行是约定，但整文件重写会把坏行
        物理删除——坏行可能是半写的好数据，先归档进 deprecated/<日期>/ 再丢
        （30 天可恢复由既有 clean_deprecated 治理）。"""
        if not path.exists():
            return
        out = []
        bad: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                bad.append(line)
                continue
            result = process_fn(item)
            if result is not None:
                out.append(json.dumps(result, ensure_ascii=False))
        if bad:
            self._salvage_bad_lines(path.name, bad)
        nl = "\n" if trailing_newline else ""
        self._write_tmp_rename(path, "\n".join(out) + nl)

    def _salvage_bad_lines(self, fname: str, lines: list[str]) -> None:
        """坏行归档（调用方持有 _write_lock 或启动期单线程）：落
        deprecated/<日期>/salvage-<文件名片段>.jsonl，fsync 保归档先于丢弃。"""
        day_dir = self.deprecated_day_dir()
        dest = day_dir / f"salvage-{fname.rsplit('.', 1)[0]}.jsonl"
        with dest.open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        logger.warning("整文件重写前归档 %s 的 %d 条坏行 → %s",
                       fname, len(lines), dest.relative_to(self.data_dir))

    def _update_jsonl(self, name: str, updates: dict[str, dict]) -> None:
        """按 id 原地更新行。jsonl 主体 append-only，但 count 合并 / distilled 标记
        需要原地改，用 _read_write_jsonl 统一 IO 模式。"""
        if not updates:
            return
        self._read_write_jsonl(self.data_dir / name,
                               lambda item: updates.get(item.get("id"), item))

    # ---------- session 追踪（三通道统一格式，/） ----------

    def _build_session_index(self) -> dict[tuple[str, object], dict]:
        """从 sessions.jsonl 重建去重索引（写锁外调用时注意文件一致性）。

        代理通道记录（带 req_count）与扫描通道记录（带 started_at）各自缺不同的
        字段，一律做**字段级合并**（见 _merge_session_record），不做整行替换——
        谁也不被谁的残缺版降级，也不让到达顺序决定最终状态。"""
        idx: dict[tuple[str, object], dict] = {}
        for rec in self._iter_jsonl("sessions.jsonl"):
            if not isinstance(rec, dict):
                continue
            key = (rec.get("agent"), _session_ident(rec))
            existing = idx.get(key)
            if existing is None:
                idx[key] = rec
            else:
                idx[key] = _merge_session_record(existing, rec)[0]
        return idx

    def _derive_truncated_messages(self, raw_messages: list) -> tuple[list, list]:
        """原始 messages → 有界 user/assistant 文本（hook 通道派生兜底）。

        hook 通道走 session.to_dict()：只有原始 messages、没有截断字段（P1a-2）；
        不派生则落库即空壳（user_messages 缺失 → 复盘/否定词检测无料）。
        tool_use / tool 消息不进转录（与 session_to_review_dict 口径一致）。"""
        user: list[str] = []
        asst: list[str] = []
        for m in raw_messages or []:
            if not isinstance(m, dict):
                continue
            content = str(m.get("content") or "")
            if not content.strip():
                continue
            if m.get("role") == "user":
                user.append(content)
            elif m.get("role") == "assistant":
                asst.append(content)
        return user, asst

    def _trim_session_messages(self, session: dict) -> dict:
        """落库保留：每角色只留最近 SESSION_MSG_KEEP 条、每条截 200 字（低5）。

        只在写盘处截断——复盘/蒸馏拿的是内存全文，质量不受影响；
        sessions.jsonl 因此每记录 O(40×200B) 有界。
        hook 兜底（P1a-2）：只有原始 messages 而无截断字段的记录，
        现场派生再截断，防 hook 记录变空壳。
        原始 messages 不在字段契约内：落库单点 pop（P1a-1，
        431MB 膨胀的根治点——下游只读截断字段与计数器）。"""
        out = dict(session)
        if not isinstance(out.get("user_messages"), list) \
                and isinstance(out.get("messages"), list):
            u, a = self._derive_truncated_messages(out["messages"])
            out.setdefault("user_messages", u)
            out.setdefault("assistant_messages", a)
        for field in ("user_messages", "assistant_messages"):
            msgs = out.get(field)
            if isinstance(msgs, list):
                out[field] = [str(m)[:SESSION_MSG_MAX_CHARS]
                              for m in msgs[-SESSION_MSG_KEEP:]]
        # R0：pop 原始 messages 前先派生事件行（确定性挖掘的唯一料源；
        # 派生是增强路径，异常绝不影响正常落库）
        if isinstance(out.get("messages"), list) and not out.get("events"):
            try:
                from ..capture.events import derive_events
                from ..config_schema import numeric
                max_bytes = int(numeric(self.load_config(), "events.max_bytes"))
                evs = derive_events(out["messages"], max_bytes=max_bytes)
                if evs:
                    out["events"] = evs
            except Exception:
                logger.debug("事件行派生失败（忽略，不影响落库）", exc_info=True)
        out.pop("messages", None)
        return out

    def _compress_session_record(self, session: dict) -> dict:
        """断路器二阶段强制截断：消息数组逐级压缩至预算内。

        阶段1 每角色留最近 5 条×100 字；阶段2 留最近 2 条×50 字。
        身份/时间/指标字段原样保留（复盘门槛与成长口径依赖它们）。"""
        out = dict(session)
        for keep, cut in ((5, 100), (2, 50)):
            for field in ("user_messages", "assistant_messages"):
                msgs = out.get(field)
                if isinstance(msgs, list):
                    out[field] = [str(m)[:cut] for m in msgs[-keep:]]
            if len(json.dumps(out, ensure_ascii=False).encode("utf-8")) \
                    <= SESSION_RECORD_MAX_BYTES:
                return out
        return out

    def record_session(self, session: dict) -> None:
        """session 落库：append-only + 内存索引去重。

        写入 O(1)（仅追加一行），读时通过 _session_index 去重。
        代理通道记录（带 req_count）优先，不被文件通道缺字段记录降级替换。
        字段契约：超纲字段丢弃 + warning（不静默），原始 messages 恒丢；
        容量断路器：序列化 > SESSION_RECORD_MAX_BYTES → 二阶段强制截断 + warning。"""
        session = self._trim_session_messages(session)
        extra = [k for k in session if k not in SESSION_RECORD_FIELDS]
        if extra:
            for k in extra:
                if k not in _warned_session_fields:
                    _warned_session_fields.add(k)
                    logger.warning(
                        "record_session 超纲字段已丢弃（如属需要请先加入 SESSION_RECORD_FIELDS 契约）: %s", k)
            session = {k: v for k, v in session.items() if k in SESSION_RECORD_FIELDS}
        if len(json.dumps(session, ensure_ascii=False).encode("utf-8")) \
                > SESSION_RECORD_MAX_BYTES:
            session = self._compress_session_record(session)
            logger.warning(
                "session 落库超 %d 字节，已二阶段强制截断（%s/%s）",
                SESSION_RECORD_MAX_BYTES, session.get("agent"),
                session.get("session_id"))
        key = (session.get("agent"), _session_ident(session))
        with self._write_lock:
            if self._session_index is None:
                self._session_index = self._build_session_index()
            existing = self._session_index.get(key)
            if existing is None:
                merged, changed = session, True
            else:
                # 字段级合并（不整行替换）：两版互补时合成完整记录，
                # 无信息增益时不重复落盘——append-only 冗余的主要来源。
                merged, changed = _merge_session_record(existing, session)
            if not changed:
                return
            self._session_index[key] = merged
            with (self.data_dir / "sessions.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(merged, ensure_ascii=False) + "\n")

    def list_sessions(self) -> list[dict]:
        """读时去重：返回每个 (agent, session_id) 的最新记录。

        索引构建纳入写锁（读侧旧快照会覆盖新 session 索引）。
        **快路径也要持锁**——原来"已有索引就直接
        `list(dict.values())`"与 `record_session` 的锁内插入并发时，CPython 会抛
        `RuntimeError: dictionary changed size during iteration`（API 线程/扫描
        线程/复盘 worker 共享 Store），表现为偶发 500。
        无锁调用方已核查：全部读侧消费者都不持写锁，不会死锁。"""
        with self._write_lock:
            if self._session_index is None:
                self._session_index = self._build_session_index()
            return list(self._session_index.values())

    def prune_sessions(self, days: int = SESSION_RETENTION_DAYS) -> int:
        """按 started_at 删除超保留期的 session（返回删除数；无时间戳的记录保留）。

        每日一次（daemon daily_checks 幂等门控）。**顺带做 key 级 compaction**——
        retention 与 compaction 是两个独立的判断（Kafka 口径：retention 回答"留多久"，
        compaction 回答"同一 key 留哪一版"，各自有自己的触发条件）：

        - retention：超期记录不再保留；
        - compaction：同一 (agent, session_id) 的多版本行合并成一版完整记录。

        原实现只在「有记录被删」时才重写文件，等于把两件事耦在一起：只要 90 天内
        没人超期（活跃用户的常态），append-only 的重复行就永远不被压缩。实测
        中，同一会话会累积成多行重复记录，文件体积随之膨胀。

        无收益就不重写（行数没降、也没删掉东西），避免每天无谓的全量重写。
        """
        path = self.data_dir / "sessions.jsonl"
        if not path.exists():
            return 0
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        with self._write_lock:
            if self._session_index is None:
                self._session_index = self._build_session_index()
            raw_lines = self._count_lines(path)
            kept: list[dict] = []
            dropped = 0
            for rec in self._session_index.values():
                if _ts_older_than(str(rec.get("started_at", "")), cutoff):
                    dropped += 1
                else:
                    kept.append(rec)
            if dropped or len(kept) < raw_lines:
                content = "\n".join(json.dumps(r, ensure_ascii=False) for r in kept) + "\n"
                self._write_tmp_rename(path, content)
                # 压缩后重建索引，与文件内容一致
                self._session_index = {
                    (r.get("agent"), _session_ident(r)): r for r in kept}
            return dropped

    # ---------- 热路径文本缓存（M-5） ----------

    def read_text_cached(self, path: Path) -> str | None:
        """stat 校验的文本读：(mtime_ns, size) 未变 → 直接返回缓存内容。

        校验本身是安全网——绕过本类写口的修改（mtime 变化）下一读即重读；
        写口处的 invalidate 只是省一次 stat 的保险。"""
        try:
            st = path.stat()
        except OSError:
            return None
        key = str(path)
        hit = self._file_cache.get(key)
        if hit is not None and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        self._file_cache[key] = (st.st_mtime_ns, st.st_size, text)
        return text

    def invalidate_cache(self, path: str | Path | None = None) -> None:
        """写口失效：path=None 全清（wipe/改名等批量变更）。"""
        if path is None:
            self._file_cache.clear()
            self._session_index = None
        else:
            self._file_cache.pop(str(path), None)

    # ---------- 资产（md） ----------

    # 方法卡与纠正补丁的路径/读/写/列（skill_path / read_skill / list_skills /
    # fixes_path / read_fixes / write_fixes / write_skill）已搬到
    # app/store/skill.py 的 SkillMixin。

    # 资产改名/归档（rename_skill / _rewrite_category_field /
    # deprecated_day_dir / snapshot_skill / retire_asset / clean_deprecated）
    # 已随域搬到 app/store/skill.py 的 SkillMixin。

    # changelog 追加 / 带机器标记的事件 / 复盘节点 upsert 已搬到
    # app/store/changelog.py 的 ChangelogMixin（_append_changelog_line /
    # append_changelog / append_event / upsert_review_node）。

    # mark_solidified 已随域搬到 app/store/changelog.py 的 ChangelogMixin。

    # 捕获状态（增量扫描）+ hooks 观测与令牌
    # （load_capture_state / save_capture_state / load_capture_failures /
    # save_capture_failures / load_detected_agents / save_detected_agents /
    # record_capture_hit / load_capture_hits / record_hook_observed /
    # load_hook_observed / hook_ingest_token）
    # 已随域搬到 app/store/capture_state.py 的 CaptureStateMixin。

    # ---------- 规则注入命中（H-O2 生命周期治理：命中/过时） ----------

    # 规则注入命中（record_rule_hits / _bump_rule_hits_locked / load_rule_hits /
    # purge_rule_hit）已搬到 app/store/rules.py 的 RulesMixin。

    # ---------- 注入记录（injection.log + injection_hits.json，/） ----------

    # 注入记录与治理（record_injection / _bump_injection_hits_locked /
    # injection_governed_items / apply_injection_feedback / set_injection_item_state）
    # 已随域搬到 app/store/injection.py 的 InjectionMixin。

    # ---------- 触发日志与档 C 整理日志（trigger_log / maintenance.log） ----------

    def log_trigger(self, trigger: str, snapshot: dict | None = None) -> None:
        """每次自动触发落一行（档 A 复盘 / 档 B 阈值 / 档 C 整理，全档适用）：
        时间 + 触发器编号 + 当时计数快照——回查"这条经验/这条固化是被哪个
        触发器、在什么计数状态下放进来的"。Mem0 的教训是"门在调用方=无门"，
        日志是门的审计件。"""
        with self._write_lock:
            with (self.data_dir / "trigger_log").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": utcnow(), "trigger": trigger,
                                     **(snapshot or {})},
                                    ensure_ascii=False) + "\n")
            # 写点封顶 500 行
            self._cap_jsonl_lines(self.data_dir / "trigger_log",
                                  TRIGGER_LOG_MAX_LINES)

    # 整理日志（log_maintenance / read_maintenance）也搬入 ChangelogMixin。

    def read_trigger_log(self, limit: int = 200) -> list[dict]:
        """触发日志（新在前）；坏行跳过。"""
        out = [r for r in self._iter_jsonl("trigger_log") if isinstance(r, dict)]
        return out[-limit:][::-1]

    # ---------- 注入覆盖层（injection_overrides.json） ----------

    # 注入覆盖层的读写已搬到 app/store/rules.py 的 OverridesMixin。

    # ---------- 规则通道（rules.json） ----------

    # 规则通道（rules.json 与规则 md）的读写已搬到 app/store/rules.py 的
    # RulesMixin：load_rules / save_rules / upsert_rule / remove_rule /
    # write_rule_file / rename_rule_file 六個方法。

    # ---------- 通知中心（notifications.jsonl） ----------

    def load_notifications(self) -> list[dict]:
        """通知列表（新在后）；坏行跳过（M2：列表 I/O 收口 store）。"""
        return [r for r in self._iter_jsonl("notifications.jsonl") if isinstance(r, dict)]

    def save_notifications(self, records: list[dict]) -> None:
        # 保留策略：超 90 天的记录顺手删（ts 字段；无 ts 的保留——推送入口都带 ts）
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=NOTIFY_RETENTION_DAYS)
        records = [r for r in records
                   if not _ts_older_than(str(r.get("ts", "")), cutoff)]
        # 写点封顶 500 条：可重建的展示层，丢失不伤资产
        if len(records) > NOTIFICATIONS_MAX_LINES:
            records = records[-NOTIFICATIONS_MAX_LINES:]
        # 原子写 JSONL：仍然逐个序列化再换行写入，不拆分成单个对象的 JSON
        path = self.data_dir / "notifications.jsonl"
        content = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + ("\n" if records else "")
        self._write_tmp_rename(path, content)
        self.invalidate_cache(path)

    # ---------- changelog 时间线节点 ----------

    # changelog 的列出 / 编辑 / 删除（归档）也已搬入 ChangelogMixin。

    # ---------- 偏好画像补充 ----------

    # list_preference_trunks 已搬到 PreferencesMixin（app/store/preferences.py）。

    # ---------- 成长摘要 ----------

    def _jsonl_signature(self, names: tuple[str, ...]) -> tuple:
        """结果缓存签名：源文件 (mtime_ns, size) 指纹（写路径 os.replace 必变 inode）。"""
        out: list = []
        for n in names:
            p = self.data_dir / n
            try:
                st = p.stat()
                out.append((st.st_mtime_ns, st.st_size))
            except OSError:
                out.append(None)
        return tuple(out)

    # growth_summary() 已随「成长页」域搬到
    # app/store/growth.py 的 GrowthMixin（231 行，本文件最大的两个方法之一）。

    # 会话的读侧检索视图（search_sessions / list_workspaces）已搬到
    # app/store/session.py 的 SessionMixin。写侧（record_session / 索引构建 /
    # prune_sessions）留在主体：它们围绕 _session_index 与写锁紧密协作，
    # 拆开容易让索引与文件内容的更新顺序出错。

    def stats(self) -> dict:
        # 口径对齐 list_skills：两层深度（trunk/category.md），排除 *_fixes.md 纠正补丁
        skills_root = self.data_dir / "skills"
        skills = [f for f in skills_root.glob("*/*.md") if not f.name.endswith("_fixes.md")] if skills_root.is_dir() else []
        # experiences/pending 走 experience.db 的 SQL 计数（一次查询，与经验
        # 条数无关）；索引不可用（fail-open 降级 _expdb=None）→ 回退 JSONL 全量解析，
        # 语义与旧实现一致（宁慢不崩）。
        experiences = pending = None
        db = self._expdb
        if db is not None:
            try:
                experiences, pending = db.counts()
            except Exception as exc:  # noqa: BLE001 索引异常 → 降级回退 JSONL
                logger.warning("经验索引计数失败，stats 回退 JSONL: %s", exc)
                self._expdb = None
        if experiences is None:
            exps = list(self._iter_jsonl("experience.jsonl"))
            experiences = len(exps)
            pending = sum(1 for e in exps if not e.get("distilled"))
        # 归档会话数 = 去重后的 session 记录（复用索引缓存，cli「归档会话」如实显示）
        # 懒建纳入写锁——锁外"判空→构建→整体赋值"会让
        # 锁外构建的旧快照覆盖掉 record_session 刚写入的新 session
        # （新会话从内存索引静默消失，直到进程重启）。
        with self._write_lock:
            if self._session_index is None:
                self._session_index = self._build_session_index()
            archived_sessions = len(self._session_index)
        return {
            "data_dir": str(self.data_dir),
            "experiences": experiences,
            "pending": pending,
            "archived_sessions": archived_sessions,
            "skills": len(skills),
        }


# ---------- 拆分台账 ----------
#
# 原始规模：本文件 3538 行，`class Store` 2796 行 / 148 方法。
# 拆分后：本文件约 1700 行，`class Store` 1287 行 / 77 方法（搬出 71 个）。
#
# 已拆出的域（`app/store/` 下各自一个模块，`Store` 以多继承组装）：
# rules.py         规则通道 + 注入覆盖层        18
# skill.py         方法卡 / 纠正补丁 / 归档     13
# changelog.py     学习历程 + 整理日志          10
# injection.py     注入记录与治理                8
# preferences.py   偏好画像                      4
# experience.py    经验读侧                      3
# data_dir.py      数据目录迁移 / 彻底清空        3
# capture_state.py 扫描水位 + hooks 令牌        11
# session.py       会话读侧检索                  2
# growth.py        成长页口径（231+173 行）      1
# _shared.py       —— 跨域共用小工具（非 mixin）
#
# 铁律：域模块一律**不 import 本文件**（否则与 `class Store` 的组装形成循环导入）；
# 跨域小工具放 `_shared.py`；本文件对搬走的名字保留同名再导出，兼容既有 import。
#
# 踩过的坑（留给后人）：
# · `utcnow` 是 `from ._shared import utcnow` 的**早绑定**——每个 import 它的模块
# 各持一份名字。测试要冻结时钟必须用 `tests/conftest.py::freeze_utcnow`，
# 只 patch `app.store.store.utcnow` 覆盖不到 mixin 里的写口。
# · 搬方法时**连它用到的模块级名字一起搬**（常量 / 私有助手），并逐个确认目标
# 模块的 import 齐全——`os` / `secrets` / `json` 这类漏一个就是运行期 NameError。
# 建议搬完立刻跑全量，别攒着一起跑。
