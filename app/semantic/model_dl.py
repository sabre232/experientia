"""embedding 模型自动下载器（首启下载 + 缓存 + 校验和，缺一不可）。

拍板纪律"无校验和不下载"落地：源与 sha256 在本文件钉死（ModelScope
Maiteka/bge-small-zh-v1.5-onnx，国内可达、CDN 302 跟随），流式下载边写
边算哈希，不符即丢弃重下——防半截文件、防源内容被替换。

文件落 data_dir/models/，命名与 embedder 约定一致：
  bge-small-zh-int8.onnx / bge-small-zh-int8.tokenizer.json
开关（features.semantic_embedding）开启后 embedder 探测到文件即生效；
下载失败静默（系统级一直有 BM25 降级，不构成故障）。
"""

from __future__ import annotations

import hashlib
import logging
import threading
import urllib.request

from ..fs_util import replace_atomic

logger = logging.getLogger("experientia.semantic.model_dl")

SOURCE = "https://modelscope.cn/models/Maiteka/bge-small-zh-v1.5-onnx/resolve/master/"

# 文件名 → (源文件, sha256, 字节数)
PINNED = {
    "bge-small-zh-int8.onnx": (
        "model_qint8.onnx",
        "bcb1f7d6cf43a0ddf3775439da04d4eef5f0e60dcb05796ff1218e9ab9dc23c4",
        23_942_540),
    "bge-small-zh-int8.tokenizer.json": (
        "tokenizer.json",
        "48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26",
        439_125),
}

_CHUNK = 256 * 1024
_lock = threading.Lock()
_thread: threading.Thread | None = None


def missing_files(store) -> list[str]:
    models_dir = store.dir("models")
    return [name for name in PINNED if not (models_dir / name).exists()]


def _fetch_one(url: str, dest, want_sha: str, want_size: int) -> bool:
    """流式下载 → 边写边哈希 → 校验通过才原子落位（.part 残留即弃）。"""
    part = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    got = 0
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, \
                part.open("wb") as fh:
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
                fh.write(chunk)
                got += len(chunk)
        if got != want_size or h.hexdigest() != want_sha:
            logger.warning("模型校验失败 %s（%d/%d 字节，sha %s）",
                           dest.name, got, want_size, h.hexdigest()[:12])
            return False
        # 用 replace_atomic：刚下完的几百 MB 文件正是 AV 扫描的重点对象，
        # 瞬时锁失败会让用户白等一次完整重下（见 app/fs_util.py 说明）。
        replace_atomic(part, dest)
        logger.info("模型就位: %s", dest.name)
        return True
    except Exception as exc:
        logger.info("模型下载失败 %s: %s", dest.name, exc)
        return False
    finally:
        try:
            if part.exists():
                part.unlink()
        except OSError:
            pass


def ensure_model(store) -> bool:
    """补齐缺失的模型文件（哈希钉死）。全部就位/成功 → True。"""
    ok = True
    models_dir = store.dir("models")
    models_dir.mkdir(parents=True, exist_ok=True)
    for name, (src, sha, size) in PINNED.items():
        dest = models_dir / name
        if dest.exists():
            continue
        if not _fetch_one(SOURCE + src, dest, sha, size):
            ok = False
    return ok


def spawn_model_download(store) -> bool:
    """引擎启动接线：开关开 + 文件缺 → 后台下载一次（不阻塞捕获循环）。

    返回是否起了线程。下载完成后 embedder 的按次探测自然生效。"""
    global _thread
    try:
        from ..config_schema import feature_enabled
        if not feature_enabled(store.load_config(), "semantic_embedding",
                               default=False):
            return False
        if not missing_files(store):
            return False
    except Exception:
        return False
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        from ..thread_util import spawn
        # spawn 兜底：下载失败虽静默是设计（BM25 一直在），但 ensure_model 自身
        # 抛异常（磁盘/权限等）时会连"为什么没下下来"的日志都没有。
        _thread = spawn(ensure_model, store, name="experientia-model-dl")
    return True
