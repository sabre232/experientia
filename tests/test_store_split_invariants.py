"""`store.py` 按域拆 mixin 之后的**结构不变量**守卫。

拆分把 `class Store` 的 71 个方法搬到 `app/store/` 下 10 个域模块，搬家不改语义，
但引入了一条**新的结构约束**：域模块不能反向 import 主模块 `app.store.store`——
否则与 `class Store` 的组装形成循环导入。这条规矩写在 `store.py` 文末台账里，
**但注释不会红，测试会**。

本文件把四条不变量固化下来，后续再拆新域时它们会自动生效：

1. 域模块不反向 import 主模块（防循环导入）；
2. `class Store` 确实组装了全部 mixin（漏一个 = 那一域的方法全丢）；
3. 搬走的方法在 `Store` 上仍然可调用（对外 API 零变化的实证）；
4. 主模块仍再导出被外部 import 的名字（main.py / daemon.py / tests 在用）。

搬新域时若这里红了，按失败信息修即可，不要改测试绕过去。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.store import store as store_mod
from app.store.store import Store

ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = ROOT / "app" / "store"

# 主模块自身排除：它是被组装的那一方，本来就会被别人 import
MAIN_MODULE = "store.py"

# 非 mixin 模块，反向 import 主模块是它们的本职，且不构成环（store.py 不 import 它们）
# - __init__.py：包的对外再导出（`from .store import Store`）
# - migrations.py：启动时按 data_version 跑数据迁移，是 Store 的**消费者**，
# 由 daemon / GUI 在 Store 定义完成后调用（注意：它与「更换数据目录」的
# data_dir.py 是两件不同的事，勿合并）
NON_MIXIN_MODULES = {"__init__.py", "migrations.py"}

EXPECTED_MIXINS = (
    "RulesMixin",      # 规则通道
    "OverridesMixin",  # 注入覆盖层
    "SkillMixin",      # 方法卡 / 纠正补丁 / 归档
    "ExperienceMixin",  # 经验读侧
    "SessionMixin",    # 会话读侧检索
    "ChangelogMixin",  # 学习历程 + 整理日志
    "InjectionMixin",  # 注入记录与治理
    "PreferencesMixin",  # 偏好画像
    "GrowthMixin",     # 成长页口径
    "DataDirMixin",    # 数据目录迁移 / 彻底清空
    "CaptureStateMixin",  # 扫描水位 + hooks 令牌
    "ReviewQueueMixin",  # 复盘队列背压 + 台账 + 在飞窗口
)

# 各域的代表方法（搬家前都在 class Store 上）——抽样验证"对外 API 零变化"
MOVED_SAMPLES = (
    "load_rules", "upsert_rule",              # rules
    "load_overrides",                          # overrides
    "read_skill", "write_skill",               # skill
    "append_event", "list_changelog",          # changelog
    "record_injection", "load_injection_hits",  # injection
    "read_preferences",                        # preferences
    "growth_summary",                          # growth
    "migrate_data_dir", "wipe_all",            # data_dir
    "load_capture_state", "hook_ingest_token",  # capture_state
    "search_sessions",                         # session
    "find_experience", "update_experience",     # experience
    "append_pending_review", "load_pending_reviews",  # review_queue
    "is_reviewed", "mark_reviewed",            # review_queue
    "should_enqueue_review", "mark_review_queued",    # review_queue
    "clear_review_queued", "drop_pending_review",     # review_queue
)

# 被 main.py / daemon.py / tests 从 app.store.store 直接 import 的名字
REEXPORTED = (
    "default_data_dir", "resolve_data_dir", "cleanup_pending_data_dir",
    "normalize_rule", "RULES_SCHEMA_VERSION", "growth_panorama",
    "utcnow", "DATA_DIR_NAME", "ASSET_DIRS", "CHLOG_KINDS",
    # review_queue 域的常量：app.capture.scan 与 tests/test_h7_* 从本模块 import，
    # 且后者 monkeypatch 打桩 store_mod.REVIEW_RETRY_AFTER_S（搬家后要改打桩目标）
    "PENDING_REVIEWS_FILE", "PENDING_ARCHIVE_FILE", "REVIEWED_FILE",
    "REVIEW_QUEUED_FILE", "REVIEW_RETRY_AFTER_S",
)


def test_domain_modules_do_not_import_main_module():
    """域模块反向 import 主模块 → 与 class Store 的组装形成循环导入。"""
    offenders: list[str] = []
    for py in sorted(STORE_DIR.glob("*.py")):
        if py.name in (MAIN_MODULE,) or py.name in NON_MIXIN_MODULES:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                # 只认"落点是 store 模块"的（相对 .store 与绝对 app.store.store 同罪）
                if mod.split(".")[-1] == "store":
                    offenders.append(f"{py.name}:{node.lineno} from {mod}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[-1] == "store":
                        offenders.append(f"{py.name}:{node.lineno} import {alias.name}")
    assert not offenders, (
        "域模块不得反向 import app.store.store（会循环导入）："
        + "; ".join(offenders))


def test_store_assembles_all_mixins():
    """漏组装一个 mixin = 那一域的方法全丢，且不会报错（只是 AttributeError）。"""
    mro = {c.__name__ for c in Store.__mro__}
    missing = [m for m in EXPECTED_MIXINS if m not in mro]
    assert not missing, f"class Store 未组装这些 mixin：{missing}"


@pytest.mark.parametrize("name", MOVED_SAMPLES)
def test_moved_methods_still_on_store(name):
    """拆分是纯搬家：`Store` 上的方法名一个都不能少。"""
    assert callable(getattr(Store, name, None)), (
        f"{name} 不在 Store 上——拆分把方法搬丢了？")


def test_main_module_still_reexports_external_names():
    """外部模块从 app.store.store import 这些名字，搬走后必须保留再导出。"""
    missing = [n for n in REEXPORTED if not hasattr(store_mod, n)]
    assert not missing, f"app.store.store 未再导出这些名字，既有 import 会断：{missing}"
