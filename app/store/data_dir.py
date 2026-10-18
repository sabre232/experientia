"""`Store` 的「数据目录」域 mixin + 目录解析 / 冷启动清理。

从 `store.py` 拆出的第九个域，承载两件事：

- **模块级**：数据目录定位与迁移遗留清理（`default_data_dir` / `resolve_data_dir`
  / `cleanup_pending_data_dir`）。`main.py` / `daemon.py` /
  `app/capture/adapters/base_sqlite.py` 在 `Store` 实例化**之前**就要用它们，
  故保持模块级函数；`store.py` 保留同名再导出以兼容既有 import。
- **`DataDirMixin`**：`migrate_data_dir` / `wipe_all` / `_wipe_leftovers`——需要
  `self.data_dir` / `self._write_lock` / `self.load_config` 的方法。

约定与其余 mixin 一致：方法体逐字搬移、签名与返回值不变；共享状态留在 `Store`
主体、靠 `self` 访问；**不 import `store.py`**（避免与 `class Store` 的组装形成
循环导入）。

⚠️ 本模块的「更换数据目录」与 `app/store/migrations.py` 的「启动时按 data_version
跑数据迁移」是**两件不同的事**，不要合并。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from ..fs_util import replace_atomic
from ._shared import ASSET_DIRS, DATA_DIR_NAME

logger = logging.getLogger("experientia.store")


def default_data_dir() -> Path:
    """默认数据目录（三平台统一 ~/.experientia/）。"""
    return Path.home() / DATA_DIR_NAME


def resolve_data_dir() -> tuple[Path, bool]:
    """数据目录解析，优先级：

    1. EXPERIENTIA_HOME 环境变量（开发者侧覆盖，既有行为，最高优先）
    2. 默认位置 config.json 的指针（data_dir 字段；仅当目标目录存在时有效）
    3. 默认位置 ~/.experientia

    返回 (data_dir, pointer_invalid)；pointer_invalid=True 表示指针存在但
    目标目录不存在（已回退默认位置，调用方应提示用户）。
    """
    env = os.environ.get("EXPERIENTIA_HOME")
    if env:
        return Path(env), False
    default = default_data_dir()
    try:
        cfg = json.loads((default / "config.json").read_text(encoding="utf-8"))
        p = str(cfg.get("data_dir") or "").strip()
        if p:
            target = Path(p).expanduser()
            if target.is_dir():
                return target, False
            return default, True
    except (OSError, json.JSONDecodeError):
        pass
    return default, False


def default_log_file() -> Path:
    """GUI 启动/切页打点日志的落盘路径（数据目录下 logs/gui.log）。

    与 resolve_data_dir 同源：Store 实例化**之前**就要用（main.py 在
    setup_logging 时即需落盘路径）。日志不是业务资产（不进 ASSET_DIRS），
    目录由 RotatingFileHandler 自行建立；数据目录本体的读写口径不变。
    """
    return resolve_data_dir()[0] / "logs" / "gui.log"


def default_engine_log_file() -> Path:
    """引擎进程的落盘日志路径（数据目录下 logs/engine.log）。

     起 GUI 与引擎分属两个进程：GUI 落 gui.log、引擎落 engine.log——
    分文件避免两进程写同一文件时 RotatingFileHandler 轮转互踩（重命名/截断
    在另一进程的 fd 上表现为写丢或写坏）。口径与 default_log_file 一致。
    """
    return resolve_data_dir()[0] / "logs" / "engine.log"


# 遗留：目录迁移排除的 SQLite 主库与侧车文件名（数据目录根下）。
# 主库 sha 失配时下次启动 rebuild_if_stale 会自动重建索引（JSONL 是事实源，
# 无数据风险）；排除是避免拷贝运行中被写入的库文件/侧车产生半成品。
_MIGRATION_EXCLUDE_DB_NAMES = ("experience.db", "experience.db-wal",
                               "experience.db-shm")


def _is_under_home(p: Path) -> bool:
    """路径是否在用户主目录之下（迁移目标的软约束判据）。

    默认数据目录（~/.experientia）本身就在主目录下，所以"搬回默认位置"
    永远不需要额外确认；需要确认的是 D 盘 / 移动盘 / 网络盘这类位置。"""
    try:
        return p.resolve().is_relative_to(Path.home().resolve())
    except OSError:
        return False  # 解析不了（权限/路径过长）→ 保守视为"不在主目录下"


class OutsideHomeConfirmRequired(ValueError):
    """迁移目标在用户主目录之外、且调用方未显式确认。

    继承 ValueError：`data_dir_migrate` 路由层已有的 `except ValueError` 分支
    会自动把它转成 400 + 可读文案，无需改路由；CLI/API 调用方看到同一文案。
    携带 `target` 便于将来做结构化错误码（GUI 目前本地镜像判断，不解析它）。"""

    def __init__(self, target: Path):
        super().__init__(
            f"目标 {target} 在用户主目录之外（可能是移动盘/网络盘）——"
            "盘不在线时软件会读不到经验库；如仍要迁移请显式确认")
        self.target = target


def _dir_stats(root: Path) -> tuple[int, int]:
    """目录文件数 + 总字节数（迁移校验用）。

    排除 config.json：源目录可能没有它而目标（默认位置）有指针文件，
    且 config.json 在迁移校验后单独重写，不参与拷贝完整性比对。
     遗留：同样排除 experience.db 及其 -wal/-shm 侧车
    （与 migrate_data_dir 的 copytree 排除同口径，否则文件数校验必失败）。"""
    n = 0
    size = 0
    for p in root.rglob("*"):
        if p.is_file() and p.name != "config.json" \
                and p.name not in _MIGRATION_EXCLUDE_DB_NAMES:
            n += 1
            try:
                size += p.stat().st_size
            except OSError:
                pass
    return n, size


def _atomic_write_text(path: Path, text: str) -> None:
    """模块级原子写：Store 实例化之前也要用的指针文件。

    口径与 Store._write_tmp_rename 一致（唯一 tmp 名 + replace），但这里是
    纯函数、拿不到 Store 实例——`cleanup_pending_data_dir` 在引擎启动前跑，
    指针 config 截断 = 下次启动解析错数据目录，不能原地写。"""
    import uuid

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(text)
        replace_atomic(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def cleanup_pending_data_dir() -> None:
    """冷启动清理：删除迁移遗留的旧数据目录。

    必须在引擎启动前调用（此时无文件锁；运行中引擎持有旧目录文件，
    进程内不删）。旧目录是默认位置时保留指针 config.json。清理成功后
    从默认位置 config.json 移除 pending_cleanup 字段。失败不阻塞启动
    （旧目录只是残留，不影响新位置使用）。
    """
    default = default_data_dir()
    pointer_path = default / "config.json"
    try:
        cfg = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(cfg, dict):
        return
    pending = str(cfg.get("pending_cleanup") or "").strip()
    if not pending:
        return
    old = Path(pending)
    try:
        if old.is_dir():
            if old.resolve() == default.resolve():
                for entry in old.iterdir():
                    if entry.name == "config.json":
                        continue  # 指针文件保留
                    if entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=True)
                    else:
                        entry.unlink(missing_ok=True)
            else:
                shutil.rmtree(old, ignore_errors=True)
        cfg.pop("pending_cleanup", None)
        # 指针 config 走原子写（截断 = 启动解析错目录）
        _atomic_write_text(pointer_path,
                           json.dumps(cfg, ensure_ascii=False, indent=2))
        logger.info("已清理迁移遗留的旧数据目录: %s", old)
    except OSError as exc:
        logger.warning("旧数据目录清理失败（不影响启动）: %s", exc)


class DataDirMixin:
    """数据目录的迁移（换位置）与彻底清空。"""

    def migrate_data_dir(self, target: str | Path, *,
                         confirm_outside_home: bool = False) -> dict:
        """更换数据目录：把已有数据整体搬到 target。

        校验：target 须为空或不存在（不存在自动创建；非空拒绝，防覆盖已有
        文件）；不得在当前数据目录内部；允许是默认位置（其指针文件自动
        合并，不视为非空）。
        流程：复制 → 校验（文件数+总大小）→ 新位置 config.json 写 data_dir
        → 默认位置留指针（新路径 + pending_cleanup 旧路径）→ 旧目录由下次
        冷启动清理（cleanup_pending_data_dir；运行中引擎持有文件，进程内不删）。
        中途失败：旧目录原样保留、部分拷贝清理、默认位置指针还原，抛异常。
        返回 {"dir", "files", "bytes", "restart_required"}。

        `confirm_outside_home=True` 才允许搬到用户主目录
        之外（移动盘/网络盘）——不确认时抛 OutsideHomeConfirmRequired。
        """
        target_p = Path(target).expanduser()
        try:
            target_p = target_p.resolve()
        except OSError:
            pass
        current = self.data_dir.resolve()
        default = default_data_dir().resolve()

        if target_p == current:
            raise ValueError("目标目录与当前数据目录相同")
        if current in target_p.parents:
            raise ValueError("目标目录不能在当前数据目录内部")
        if target_p.exists() and not target_p.is_dir():
            raise ValueError("目标路径已存在且不是目录")
        if target_p.is_dir():
            if target_p == default:
                extras = [e for e in target_p.iterdir() if e.name != "config.json"]
            else:
                extras = list(target_p.iterdir())
            if extras:
                raise ValueError("目标目录非空（防覆盖已有文件），请换一个空目录")

        # ，允许任意位置，但主目录外要显式确认）。
        # 放在所有现有校验之后、开拷之前：先挡掉"等于当前目录/非空"这类硬错误，
        # 再问"你确定要搬去主目录之外吗"。GUI 侧本地镜像同一判据拼提示文案并
        # 传 confirm_outside_home；这里的强制是给 CLI/API 调用方和防口径漂移的。
        if not _is_under_home(target_p) and not confirm_outside_home:
            raise OutsideHomeConfirmRequired(target_p)

        # 默认位置指针文件快照（target 是默认位置时失败需还原）
        pointer_path = default / "config.json"
        old_pointer_text = None
        if pointer_path.is_file():
            try:
                old_pointer_text = pointer_path.read_text(encoding="utf-8")
            except OSError:
                old_pointer_text = None

        created = not target_p.exists()
        # 重活（copytree + 两次全树 stat 校验，1.59 GB 级）**移出写锁**——
        # 迁移期间不再独占写锁，读路径（api/status 等）照常响应；锁内只留
        # "指针切换"这一步临界区。源文件均走原子替换/追加，锁外拷贝读到的是完整
        # 文件或有效前缀（坏行读侧跳过），数据完整性可接受。
        try:
            # 遗留：排除 experience.db/-wal/-shm——目标库由下次启动
            # rebuild_if_stale 按 JSONL 重建，避免拷进行中侧车被实时写入导致半成品
            #（_dir_stats 已同口径排除）。
            shutil.copytree(current, target_p, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(
                                *_MIGRATION_EXCLUDE_DB_NAMES))
            n_src, size_src = _dir_stats(current)
            n_dst, size_dst = _dir_stats(target_p)
            if (n_dst, size_dst) != (n_src, size_src):
                raise RuntimeError(
                    f"迁移校验失败（文件数 {n_src}→{n_dst}，"
                    f"大小 {size_src}→{size_dst}）")
        except Exception:
            if created:
                shutil.rmtree(target_p, ignore_errors=True)
            raise

        try:
            # 临界区（锁内）：写目标 config + 默认位置指针——纯小文件写入，极快
            with self._write_lock:
                cfg = self.load_config()
                if target_p == default:
                    # 搬回默认位置：去掉指针字段，旧目录清理任务记进本配置
                    cfg.pop("data_dir", None)
                    cfg["pending_cleanup"] = str(current)
                else:
                    cfg["data_dir"] = str(target_p)
                # 新位置 config 与默认位置指针都走原子写——
                # 原地 write_text 崩在中间会留下截断的指针 config，下次启动
                # resolve_data_dir 直接解析错数据目录（指到半个文件）。
                self._write_tmp_rename(
                    target_p / "config.json",
                    json.dumps(cfg, ensure_ascii=False, indent=2))
                if target_p != default:
                    pointer = {"data_dir": str(target_p),
                               "pending_cleanup": str(current)}
                    pointer_path.parent.mkdir(parents=True, exist_ok=True)
                    self._write_tmp_rename(
                        pointer_path,
                        json.dumps(pointer, ensure_ascii=False, indent=2))
        except Exception:
            if created:
                shutil.rmtree(target_p, ignore_errors=True)
            elif target_p == default and old_pointer_text is not None:
                try:
                    pointer_path.write_text(old_pointer_text, encoding="utf-8")
                except OSError:
                    pass
            raise

        return {"dir": str(target_p), "files": n_src, "bytes": size_src,
                "restart_required": True}

    def wipe_all(self) -> list[str]:
        """一键彻底删除：清空数据目录全部内容，重建初始布局。

        目录本体保留（权限/路径稳定）；config.json 一并清除（模型路由、
        API key 只留 keyring 引用，引用随配置消失即失效）。调用方负责二次确认。
        返回删不掉的相对路径清单（被引擎进程占用的文件，如 engine.lock——
        Windows 上本进程持有的锁文件删不掉，属预期态，调用方展示为提示
        而非失败）。删除后做剩余校验，不靠"没抛异常"当成功。
        """
        with self._write_lock:
            # 索引连接持有 experience.db 句柄，先统一关闭（Windows 下才删得掉）
            expdb = self._expdb
            self._expdb = None
            if expdb is not None:
                try:
                    expdb.close_all()
                except Exception:
                    # 删库前关索引连接失败若无痕吞掉，Windows 下
                    # 句柄未释放会让后续 unlink 静默失败、经验库没删净却无迹可循——补留痕。
                    logger.warning("wipe_all 关闭 SQLite 索引连接失败（可能残留 .db 句柄）",
                                   exc_info=True)
            # search.db 的连接同样要先关——用户用过会话搜索
            # 之后再"彻底删除"，Windows 上删不掉被占用的 search.db/-wal/-shm，
            # _wipe_leftovers 会把它们报成"删不掉"（假告警），旧连接还继续指向
            # 已删除的文件。
            sidx = getattr(self, "_searchidx", None)
            self._searchidx = None
            if sidx is not None:
                try:
                    sidx.close()
                except Exception:
                    logger.warning("wipe_all 关闭会话搜索索引失败（可能残留 .db 句柄）",
                                   exc_info=True)
            if self.data_dir.exists():
                for entry in self.data_dir.iterdir():
                    if entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=True)
                    else:
                        try:
                            entry.unlink()
                        except OSError:
                            pass  # 占用中的文件 → 下面校验环节收集上报
            # 进程内派生缓存全部作废。不清理的后果：
            # `_dup_index` 仍映射着旧经验 → 索引一旦降级，新经验会被"合并"进
            # 已删除的记录（复活其 count/G）；复盘台账/成长缓存同理顶着旧库。
            self._dup_index = None
            self._reviewed = None
            self._queued_reviews = None
            self._growth_cache = None
            self._workspace_cache = None
            self.invalidate_cache()
            self.ensure_layout()
            leftovers = self._wipe_leftovers()
            # 索引文件已随目录清掉，重建空索引（在 leftover 校验之后，索引不算残留）
            self._expdb = self._init_expdb()
            return leftovers

    def _wipe_leftovers(self) -> list[str]:
        """wipe 后校验：初始布局之外的剩余文件 = 删不掉（被进程占用）。"""
        expected = (
            {self.data_dir / n for n in ("experience.jsonl", "sessions.jsonl", "changelog.md")}
            | {self.data_dir / d for d in ASSET_DIRS}
        )
        out = []
        for p in sorted(self.data_dir.rglob("*")):
            if p in expected:
                continue
            out.append(str(p.relative_to(self.data_dir)))
        return out
