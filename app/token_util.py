"""8101 本地 API 鉴权 token（轻量模块，仅标准库 + 惰性 keyring）。

原实现挂在 app/local_api.py——而 local_api 会连带 import 整棵 FastAPI /
引擎服务树（实测主线程 import 约 2.1s）。main() 启动要先取 token 再拉引擎，
为了不把这段 import 压在主线程冷启动路径上，把 token 逻辑拆到本模块；
local_api / GUI api_client 保持各自的既有引用面，不再新增重复实现源。

文件兜底格式（遗留 / L9）：
- keyring 不可用时 token 落数据目录。POSIX 沿用明文 local_api_token +
  chmod 0600（该位在 POSIX 有效）；Windows 上 chmod 0600 无效，改用
  DPAPI（CryptProtectData，当前用户域）加密后落 local_api_token.bin
  （标准 ctypes，无新依赖），文件带 magic 头区分格式。
- 读取顺序：keyring → .bin（新格式）→ 旧明文文件（向后兼容）。读到旧
  明文后顺手做一次性迁移：加密写 .bin、删除明文文件；损坏的 .bin 回退
  旧口径（明文文件或重新生成），不让鉴权死锁。
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
import sys
from pathlib import Path

TOKEN_KEYRING_SERVICE = "experientia"
TOKEN_KEYRING_USER = "local_api"
TOKEN_ENV = "EXPERIENTIA_API_TOKEN"
_TOKEN_FILE_NAME = "local_api_token"
# DPAPI 加密兜底文件（Windows）：magic 头 + CryptProtectData 输出 blob
_TOKEN_BIN_NAME = "local_api_token.bin"
_TOKEN_BIN_MAGIC = b"EXPTOKEN1"

logger = logging.getLogger("experientia.token_util")

_IS_WINDOWS = sys.platform == "win32"

# ---------- DPAPI（Windows 文件兜底加密，标准 ctypes） ----------

_CRYPTPROTECT_UI_FORBIDDEN = 0x01


def _dpapi_protect(data: bytes) -> bytes | None:
    """CryptProtectData（当前用户域）加密；非 Windows / 调用失败 → None。"""
    if not _IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD),
                        ("pbData", ctypes.c_void_p)]

        def _make_blob(b: bytes) -> _DATA_BLOB:
            # create_string_buffer 的生命周期须覆盖 CryptProtectData 调用，
            # 本函数内同步完成，栈引用安全
            buf = ctypes.create_string_buffer(b, len(b))
            return _DATA_BLOB(len(b), ctypes.cast(buf, ctypes.c_void_p))

        in_blob = _make_blob(data)
        out_blob = _DATA_BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(
                ctypes.byref(in_blob), None, None, None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)):
            return None
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(out_blob.pbData))
    except Exception as exc:
        logger.debug("DPAPI 加密失败: %s", exc)
        return None


def _dpapi_unprotect(blob: bytes) -> bytes | None:
    """CryptUnprotectData 解密；非 Windows / 密文损坏 → None。"""
    if not _IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD),
                        ("pbData", ctypes.c_void_p)]

        def _make_blob(b: bytes) -> _DATA_BLOB:
            buf = ctypes.create_string_buffer(b, len(b))
            return _DATA_BLOB(len(b), ctypes.cast(buf, ctypes.c_void_p))

        in_blob = _make_blob(blob)
        out_blob = _DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(in_blob), None, None, None, None,
                _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)):
            return None
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(out_blob.pbData))
    except Exception as exc:
        logger.debug("DPAPI 解密失败: %s", exc)
        return None


# ---------- 模型 provider key 落盘兜底保护 ----------
# 主路径存系统钥匙串；仅当 keyring 不可用时才落 config.json。Windows 上
# config 的 0600 无效，故兜底值 DPAPI 加密（当前用户域）后 base64 存
# api_key_enc；POSIX 沿用明文 api_key（0600 有效）。读回见 resolve。
FALLBACK_ENC_FIELD = "api_key_enc"


def protect_fallback_secret(plaintext: str) -> dict:
    """把必须落 config 的密钥兜底成"仅当前用户可读回"的形式。

    返回可直接 merge 进 route 的字段：Windows → {api_key_enc: b64(DPAPI)}；
    POSIX / DPAPI 不可用（极端环境）→ {api_key: 明文}（可用性优先，0600 收权）。
    """
    blob = _dpapi_protect(plaintext.encode("utf-8"))
    if blob:
        return {FALLBACK_ENC_FIELD: base64.b64encode(blob).decode("ascii")}
    return {"api_key": plaintext}


def resolve_fallback_secret(route: dict) -> str | None:
    """读回兜底密钥：api_key_enc（DPAPI）优先，回退旧明文 api_key（向后兼容）。

    解不开（换机/换用户/密文损坏）→ None，由调用方按"无 key"处理，不抛。
    """
    enc = route.get(FALLBACK_ENC_FIELD)
    if enc:
        try:
            raw = _dpapi_unprotect(base64.b64decode(enc))
        except (ValueError, TypeError):
            raw = None
        if raw is not None:
            return raw.decode("utf-8")
        return None
    return route.get("api_key") or None


def _read_token_file(data_dir: Path) -> str | None:
    """读文件兜底：先试 DPAPI 新格式（.bin），失败回退旧明文文件。

    Windows 读到旧明文后顺手迁移：加密写 .bin、删除明文（失败不阻塞，
    旧文件留给下轮再迁）。返回 None = 无可用文件 token。"""
    if _IS_WINDOWS:
        bin_file = data_dir / _TOKEN_BIN_NAME
        if bin_file.exists():
            try:
                raw = bin_file.read_bytes()
            except OSError:
                raw = b""
            if raw.startswith(_TOKEN_BIN_MAGIC):
                plain = _dpapi_unprotect(raw[len(_TOKEN_BIN_MAGIC):])
                if plain:
                    try:
                        return plain.decode("utf-8")
                    except UnicodeDecodeError:
                        pass
            # magic 不对 / 密文损坏 → 视为无 .bin，走旧明文回退（见下）
            logger.warning("DPAPI token 文件损坏或不可解密，回退旧明文口径")
        # 旧明文文件（向后兼容）
        token_file = data_dir / _TOKEN_FILE_NAME
        if token_file.exists():
            try:
                existing = token_file.read_text(encoding="utf-8").strip()
            except OSError:
                existing = ""
            if existing:
                # 一次性迁移：加密落 .bin，成功即删明文（尽力而为）
                blob = _dpapi_protect(existing.encode("utf-8"))
                if blob is not None:
                    try:
                        bin_file.write_bytes(_TOKEN_BIN_MAGIC + blob)
                        try:
                            os.chmod(bin_file, 0o600)  # POSIX 语义；Windows 上无害
                        except OSError:
                            pass
                        token_file.unlink(missing_ok=True)
                        logger.info("已将明文 local_api_token 迁移为 DPAPI 加密文件")
                    except OSError as exc:
                        logger.warning("token 文件 DPAPI 迁移失败（旧明文保留）: %s", exc)
                else:
                    logger.warning("DPAPI 加密不可用，token 暂留旧明文文件")
                return existing
        return None
    # POSIX：明文 + 0600（chmod 有效，维持现状）
    token_file = data_dir / _TOKEN_FILE_NAME
    if token_file.exists():
        try:
            existing = token_file.read_text(encoding="utf-8").strip()
        except OSError:
            existing = ""
        if existing:
            return existing
    return None


def _write_private_text(path: Path, text: str) -> None:
    """以 0600 建文件后写入，避免 write_text→chmod 之间的可读窗口。"""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def _write_token_file(data_dir: Path, token: str) -> bool:
    """写文件兜底：Windows 走 DPAPI .bin；POSIX 维持明文 + 0600。成功返回 True。"""
    try:
        if _IS_WINDOWS:
            blob = _dpapi_protect(token.encode("utf-8"))
            if blob is None:
                # DPAPI 不可用（极端环境）→ 退回旧明文口径，鉴权可用性优先
                logger.warning("DPAPI 不可用，token 退回明文文件兜底")
                _write_private_text(data_dir / _TOKEN_FILE_NAME, token)
                return True
            path = data_dir / _TOKEN_BIN_NAME
            path.write_bytes(_TOKEN_BIN_MAGIC + blob)
            try:
                os.chmod(path, 0o600)  # POSIX 语义；Windows 上无害
            except OSError:
                pass
            return True
        _write_private_text(data_dir / _TOKEN_FILE_NAME, token)
        return True
    except OSError:
        return False


def ensure_api_token(data_dir: str | Path) -> str:
    """本地 API 鉴权 token：环境变量（main.py 启动注入）→ keyring →
    keyring 不可用（headless 无桌面）退回数据目录文件（Windows: DPAPI 加密
    .bin；POSIX: 0600 明文）。8101 与 8100 代理（H4 默认复用）共用同一值。
    幂等——已有 token 原样返回，引擎与 GUI 共用同一值。
    """
    tok = os.environ.get(TOKEN_ENV)
    if tok:
        return tok
    try:
        import keyring

        existing = keyring.get_password(TOKEN_KEYRING_SERVICE, TOKEN_KEYRING_USER)
        if existing:
            return existing
    except Exception as exc:
        # keyring 不可用会回退到文件落盘（设计如此），
        # 此前完全静默——补一条 debug，便于查"为什么 token 走了明文兜底"。
        logger.debug("keyring 读取失败，回退文件落盘: %s", exc)
    data_dir = Path(data_dir)
    existing = _read_token_file(data_dir)
    if existing:
        return existing
    token = secrets.token_urlsafe(32)
    try:
        import keyring

        keyring.set_password(TOKEN_KEYRING_SERVICE, TOKEN_KEYRING_USER, token)
    except Exception:
        if not _write_token_file(data_dir, token):
            logger.warning("本地 API token 既无法写入 keyring 也无法落盘（本次进程内存态）")
    return token
