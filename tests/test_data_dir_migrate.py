"""数据目录更换测试：指针解析 / 整体迁移 / 冷启动清理。

验收口径（产品文档 「更换数据目录」）：
- 更换后新位置数据完整、旧位置只剩指针、重启后各功能正常；
- 模拟迁移失败 → 旧目录原样、报错；
- 指针失效（目标目录不存在）→ 回退默认位置并提示。
"""

import json
from pathlib import Path

import pytest

from app.store.store import (Store, cleanup_pending_data_dir,
                             resolve_data_dir)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Path.home() 指向临时目录 + 清掉 EXPERIENTIA_HOME（指针解析依赖两者）。"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.delenv("EXPERIENTIA_HOME", raising=False)
    return home


def _seed(store: Store) -> None:
    store.ensure_layout()
    store.append_experience({"agent": "codex", "task": "t", "action": "a",
                             "G": 0.7, "trunk": "营销", "category": "文案写作"})
    store.write_skill("营销", "文案写作", "# playbook")


# ---------- L9g：主目录之外要显式确认 ----------

def test_migrate_outside_home_requires_confirm(tmp_path, fake_home):
    """目标在用户主目录之外（D 盘/移动盘/网络盘）→ 不确认就拒绝，且不留任何
    副作用；显式确认后才真迁。防"拔盘失忆"（盘不在线时软件读不到经验库）。"""
    from app.store import data_dir as dd

    store = Store(tmp_path / "data")
    _seed(store)
    outside = tmp_path / "outside"  # 不在 fake_home 下
    with pytest.raises(dd.OutsideHomeConfirmRequired):
        store.migrate_data_dir(outside)
    assert not outside.exists(), "被拒绝时不得创建目标目录/拷贝数据"
    # 显式确认后放行
    r = store.migrate_data_dir(outside, confirm_outside_home=True)
    assert r["files"] >= 1, r
    assert Path(r["dir"]) == outside.resolve()


def test_migrate_inside_home_needs_no_confirm(tmp_path, fake_home):
    """回归：搬到主目录之内（含默认位置）不需要额外确认——主要用途不受影响。"""
    store = Store(tmp_path / "data")
    _seed(store)
    inside = fake_home / "mylib"
    r = store.migrate_data_dir(inside)
    assert r["files"] >= 1, r
    assert Path(r["dir"]) == inside.resolve()


def test_migrate_outside_home_guard_precedes_copy(tmp_path, fake_home):
    """闸门必须在开拷之前：被拒时旧目录数据原样、新目录不存在。"""
    from app.store import data_dir as dd

    store = Store(tmp_path / "data")
    _seed(store)
    outside = tmp_path / "outside2"
    with pytest.raises(dd.OutsideHomeConfirmRequired):
        store.migrate_data_dir(outside)
    assert list(store.iter_experiences(include_distilled=True)), "旧库数据被动过"
    assert not outside.exists()


def test_api_migrate_outside_home_returns_400(tmp_path, fake_home):
    """API 层：未确认的主目录外目标 → 400 + 可读文案（GUI 直接展示即可）。

    OutsideHomeConfirmRequired 继承 ValueError，走路由既有分支；这里锁住
    "不会 500、不会真迁" 的行为（CLI/其他 API 调用方同样受益）。"""
    from fastapi import HTTPException

    from app.local_api_routers.app_ops import (DataDirMigrateIn,
                                               build_app_ops_router)

    store = Store(tmp_path / "data")
    _seed(store)
    router = build_app_ops_router(store)
    ep = next(r.endpoint for r in router.routes
              if getattr(r, "path", "") == "/api/data-dir/migrate")

    outside = tmp_path / "outside-api"
    with pytest.raises(HTTPException) as ei:
        ep(DataDirMigrateIn(target=str(outside)))
    assert ei.value.status_code == 400, ei.value.detail
    assert "用户主目录" in str(ei.value.detail)
    assert not outside.exists(), "被拒时不得真迁"
    # 带确认字段即放行
    r = ep(DataDirMigrateIn(target=str(outside), confirm_outside_home=True))
    assert r["files"] >= 1, r


# ---------- 指针解析 ----------

def test_resolve_default_when_no_pointer(fake_home):
    d, fb = resolve_data_dir()
    assert d == fake_home / ".experientia"
    assert fb is False


def test_resolve_env_overrides_pointer(fake_home, monkeypatch):
    default = fake_home / ".experientia"
    default.mkdir()
    (default / "config.json").write_text(
        json.dumps({"data_dir": str(fake_home / "elsewhere")}), encoding="utf-8")
    monkeypatch.setenv("EXPERIENTIA_HOME", str(fake_home / "envdir"))
    d, fb = resolve_data_dir()
    assert d == fake_home / "envdir"
    assert fb is False


def test_resolve_follows_valid_pointer(fake_home):
    default = fake_home / ".experientia"
    target = fake_home / "data2"
    default.mkdir()
    target.mkdir()
    (default / "config.json").write_text(
        json.dumps({"data_dir": str(target)}), encoding="utf-8")
    d, fb = resolve_data_dir()
    assert d == target
    assert fb is False


def test_resolve_fallback_when_pointer_target_missing(fake_home):
    default = fake_home / ".experientia"
    default.mkdir()
    (default / "config.json").write_text(
        json.dumps({"data_dir": str(fake_home / "gone")}), encoding="utf-8")
    d, fb = resolve_data_dir()
    assert d == default
    assert fb is True


def test_store_init_exposes_fallback(fake_home):
    default = fake_home / ".experientia"
    default.mkdir()
    (default / "config.json").write_text(
        json.dumps({"data_dir": str(fake_home / "gone")}), encoding="utf-8")
    store = Store()
    assert store.data_dir == default
    assert store.data_dir_fallback is True
    # 显式 data_dir 不受指针影响
    s2 = Store(fake_home / "explicit")
    assert s2.data_dir_fallback is False


# ---------- 迁移 ----------

def test_migrate_default_to_custom(fake_home):
    default = fake_home / ".experientia"
    store = Store(default)
    _seed(store)
    target = fake_home / "D" / "data"  # 不存在 → 自动创建
    r = store.migrate_data_dir(target)
    assert r["restart_required"] is True
    assert r["dir"] == str(target.resolve())
    # 新位置数据完整
    assert (target / "experience.jsonl").exists()
    assert (target / "skills" / "营销" / "文案写作.md").exists()
    # 新位置 config 带 data_dir
    cfg = json.loads((target / "config.json").read_text(encoding="utf-8"))
    assert cfg["data_dir"] == str(target.resolve())
    # 默认位置留指针（新路径 + pending_cleanup 旧路径）
    pointer = json.loads((default / "config.json").read_text(encoding="utf-8"))
    assert pointer["data_dir"] == str(target.resolve())
    assert pointer["pending_cleanup"] == str(default.resolve())
    # 旧目录进程内不删（冷启动清理）
    assert (default / "experience.jsonl").exists()


def test_migrate_rejects_nonempty_target(fake_home):
    default = fake_home / ".experientia"
    store = Store(default)
    _seed(store)
    target = fake_home / "busy"
    target.mkdir()
    (target / "userfile.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        store.migrate_data_dir(target)
    # 旧目录原样，目标未被写入
    assert (default / "experience.jsonl").exists()
    assert not (target / "experience.jsonl").exists()


def test_migrate_rejects_target_inside_current(fake_home):
    default = fake_home / ".experientia"
    store = Store(default)
    _seed(store)
    with pytest.raises(ValueError):
        store.migrate_data_dir(default / "sub")


def test_migrate_rejects_same_dir(fake_home):
    default = fake_home / ".experientia"
    store = Store(default)
    _seed(store)
    with pytest.raises(ValueError):
        store.migrate_data_dir(default)


def test_migrate_back_to_default(fake_home):
    default = fake_home / ".experientia"
    custom = fake_home / "custom"
    custom.mkdir()
    store = Store(custom)
    _seed(store)
    # 默认位置已有指针（模拟上次从默认位置迁出）
    default.mkdir()
    (default / "config.json").write_text(
        json.dumps({"data_dir": str(custom.resolve()),
                    "pending_cleanup": str(custom.resolve())}), encoding="utf-8")
    r = store.migrate_data_dir(default)
    assert r["dir"] == str(default.resolve())
    # 默认位置 config = 完整配置（无 data_dir 指针字段）+ pending_cleanup
    cfg = json.loads((default / "config.json").read_text(encoding="utf-8"))
    assert "data_dir" not in cfg
    assert cfg["pending_cleanup"] == str(custom.resolve())
    # 默认位置数据完整；旧 custom 进程内不删
    assert (default / "experience.jsonl").exists()
    assert (custom / "experience.jsonl").exists()


# ---------- 冷启动清理 ----------

def test_cleanup_removes_old_dir_and_pointer_field(fake_home):
    default = fake_home / ".experientia"
    custom = fake_home / "custom"
    custom.mkdir(parents=True)
    (custom / "experience.jsonl").write_text("x", encoding="utf-8")
    default.mkdir()
    (default / "config.json").write_text(
        json.dumps({"data_dir": str(default.resolve()),
                    "pending_cleanup": str(custom.resolve())}), encoding="utf-8")
    cleanup_pending_data_dir()
    assert not custom.exists()
    cfg = json.loads((default / "config.json").read_text(encoding="utf-8"))
    assert "pending_cleanup" not in cfg


def test_cleanup_keeps_pointer_when_old_is_default(fake_home):
    default = fake_home / ".experientia"
    default.mkdir()
    (default / "experience.jsonl").write_text("x", encoding="utf-8")
    (default / "config.json").write_text(
        json.dumps({"data_dir": str(fake_home / "new"),
                    "pending_cleanup": str(default.resolve())}), encoding="utf-8")
    cleanup_pending_data_dir()
    # 指针 config.json 保留，其余旧文件删除
    assert (default / "config.json").exists()
    assert not (default / "experience.jsonl").exists()
    cfg = json.loads((default / "config.json").read_text(encoding="utf-8"))
    assert cfg["data_dir"] == str(fake_home / "new")
    assert "pending_cleanup" not in cfg


def test_cleanup_noop_without_pending(fake_home):
    default = fake_home / ".experientia"
    default.mkdir()
    (default / "config.json").write_text(
        json.dumps({"locale": "zh"}), encoding="utf-8")
    cleanup_pending_data_dir()
    cfg = json.loads((default / "config.json").read_text(encoding="utf-8"))
    assert cfg == {"locale": "zh"}
