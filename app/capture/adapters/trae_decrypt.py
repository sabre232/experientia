"""Trae CN 加密数据库解密模块（Windows 仅限）。

技术原理（来自 Oh-My-Trae/trae-db-decrypt + ZedeX/trae-chat-decrypt）：
- Trae CN 的 ai_agent.dll 进程内存中保存着 SQLCipher 4 的原始 32 字节密钥
- 通过 ReadProcessMemory 扫描进程内存，搜索 `x'<64 hex>'` 模式
- 用 HMAC-SHA512 验证密钥是否正确（校验数据库第一页的 HMAC 签名）
- 纯 Python 逐页 AES-256-CBC 解密

SQLCipher 4 配置：
  - 版本：SQLCipher 4
  - 加密：AES-256-CBC
  - KDF：PBKDF2-HMAC-SHA512, 256000 次迭代
  - HMAC：每页 HMAC-SHA512
  - 页大小：4096 字节
  - 密钥格式：原始 32 字节 hex

依赖：pycryptodome 可选（`pip install pycryptodome`）。
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger("experientia.capture.trae_decrypt")

# SQLCipher 4 常量
SQLCIPHER_PAGE_SIZE = 4096          # 默认页大小（SQLCipher 默认）
SQLCIPHER_KDF_ITER = 256000
SQLCIPHER_RESERVE_SIZE = 16  # salt 在保留区域（第一页头部）
SQLCIPHER_HMAC_SIZE = 32     # 每页前 32 字节是 HMAC

# F-1 页大小泛化：真实库可能用非默认页大小（Trae 版本/配置差异），
# 校验第一页 HMAC 来确定真实页大小（4096 优先 = 最常见，减少无谓尝试）
SQLCIPHER_PAGE_SIZE_CANDIDATES = (
    4096, 8192, 16384, 32768, 65536, 2048, 1024,
)

# 进程内存中的密钥模式：x'<64 hex chars>'
_KEY_PATTERN = re.compile(rb"x'([0-9a-fA-F]{64,192})'")

# 尝试导入 pycryptodome
try:
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import PBKDF2
    from Crypto.Hash import HMAC, SHA512

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    AES = None
    PBKDF2 = None
    HMAC = None
    SHA512 = None


def _try_import_ctypes() -> bool:
    """尝试导入 ctypes + Windows API（仅限 Windows）。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        return True
    except ImportError:
        return False


def _find_trae_process() -> int | None:
    """返回 Trae CN 进程 PID，或 None。

    尝试多种策略：
    1. EnumProcesses API（最快）
    2. tasklist 命令（最可靠，兜底）
    """
    if sys.platform != "win32":
        return None
    # 策略 1：EnumProcesses API
    pid = _find_trae_process_api()
    if pid is not None:
        return pid
    # 策略 2：tasklist 命令
    return _find_trae_process_tasklist()


def _find_trae_process_api() -> int | None:
    """通过 Windows API EnumProcesses 查找 Trae 进程。"""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi

        MAX_PROCESSES = 1024
        pids = (ctypes.c_uint32 * MAX_PROCESSES)()
        needed = ctypes.c_uint32()
        if not psapi.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids),
                                   ctypes.byref(needed)):
            return None
        count = needed.value // ctypes.sizeof(ctypes.c_uint32)

        for i in range(count):
            pid = pids[i]
            if pid == 0:
                continue
            handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:
                continue
            try:
                exe_name = (ctypes.c_char * 260)()
                size = ctypes.c_uint32(260)
                if psapi.GetModuleBaseNameA(handle, None, exe_name, size):
                    name = exe_name.value.decode("ascii", errors="replace").lower()
                    if "trae" in name:
                        return pid
            finally:
                kernel32.CloseHandle(handle)
        return None
    except Exception:
        return None


def _find_trae_process_tasklist() -> int | None:
    """通过 tasklist 命令查找 Trae 进程（兜底方案）。"""
    try:
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10)
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2:
                name = parts[0].strip('"').lower()
                if "trae" in name:
                    try:
                        return int(parts[1].strip('"'))
                    except (ValueError, IndexError):
                        pass
        return None
    except Exception:
        return None


def _scan_process_memory(pid: int) -> list[bytes]:
    """扫描指定进程的所有可读内存区域，返回包含密钥模式的块。"""
    if sys.platform != "win32":
        return []
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # 显式声明 restype：默认 c_int 会把 64 位句柄截断（argtypes 在结构
        # 定义后再设）
        kernel32.OpenProcess.restype = ctypes.c_void_p

        PROCESS_VM_READ = 0x0010
        PROCESS_QUERY_INFORMATION = 0x0400

        handle = kernel32.OpenProcess(
            PROCESS_VM_READ | PROCESS_QUERY_INFORMATION,
            False, pid)
        if not handle:
            logger.warning("无法打开 Trae 进程（PID %d），需要管理员权限", pid)
            return []

        try:
            # 内存状态结构
            class MEMORY_BASIC_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BaseAddress", ctypes.c_void_p),
                    ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", ctypes.c_uint32),
                    ("RegionSize", ctypes.c_size_t),
                    ("State", ctypes.c_uint32),
                    ("Protect", ctypes.c_uint32),
                    ("Type", ctypes.c_uint32),
                ]

            # 显式声明 API 签名：默认 restype/argtypes 是 c_int，会把
            # 64 位句柄/地址截断（高地址 OverflowError）
            kernel32.VirtualQueryEx.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
            kernel32.ReadProcessMemory.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

            MEM_COMMIT = 0x1000
            PAGE_READABLE = 0x02  # PAGE_READONLY
            PAGE_READWRITE = 0x04
            PAGE_EXECUTE_READ = 0x20
            PAGE_EXECUTE_READWRITE = 0x40

            addr = ctypes.c_void_p(0)
            mbi = MEMORY_BASIC_INFORMATION()
            found = []

            while True:
                ret = kernel32.VirtualQueryEx(
                    handle, addr, ctypes.byref(mbi),
                    ctypes.sizeof(mbi))
                if not ret:
                    break

                # 只读已提交的可读内存
                if (mbi.State == MEM_COMMIT
                        and mbi.Protect in (PAGE_READABLE, PAGE_READWRITE,
                                            PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE)):
                    # 超大块跳过（防单块 2GB 级提交区把内存吃光；密钥不会
                    # 落在比进程工作集大得多的块里）
                    if mbi.RegionSize > 1 << 30:
                        pass
                    else:
                        buf = (ctypes.c_char * mbi.RegionSize)()
                        bytes_read = ctypes.c_size_t()
                        # 64 位地址必须显式 c_void_p 传递（默认 c_int 截断
                        # → 高地址 OverflowError）
                        if kernel32.ReadProcessMemory(
                                handle, ctypes.c_void_p(mbi.BaseAddress), buf,
                                mbi.RegionSize, ctypes.byref(bytes_read)):
                            data = bytes(buf[:bytes_read.value])
                            if _KEY_PATTERN.search(data):
                                found.append(data)

                # 移到下一块。注意首块（低地址 MEM_FREE 空洞）BaseAddress 合法为
                # NULL——不能因此 break（整个扫描会停在第 1 块）；NULL 按 0 推进，
                # RegionSize 为 0 才是真异常（break 防死循环）
                base_val = ctypes.cast(mbi.BaseAddress, ctypes.c_void_p).value
                if not mbi.RegionSize:
                    break
                addr = ctypes.c_void_p((base_val or 0) + mbi.RegionSize)

            return found
        finally:
            kernel32.CloseHandle(handle)
    except Exception as exc:
        logger.warning("进程内存扫描失败: %s", exc)
        return []


def _extract_keys(memory_chunks: list[bytes]) -> list[bytes]:
    """从内存块中提取所有候选密钥（hex → bytes）。"""
    keys: list[bytes] = []
    for chunk in memory_chunks:
        for match in _KEY_PATTERN.finditer(chunk):
            hex_key = match.group(1).decode("ascii")
            try:
                key = bytes.fromhex(hex_key)
                if len(key) == 32 and key not in keys:
                    keys.append(key)
            except ValueError:
                continue
    return keys


def _derive_hmac_key(key: bytes, salt: bytes) -> bytes:
    """SQLCipher 4 的 HMAC 密钥派生：PBKDF2-HMAC-SHA512(salt XOR 0x3A, iter=2)。"""
    xored = bytes(b ^ 0x3A for b in salt)
    return PBKDF2(key, xored, dkLen=32, count=2, hmac_hash_module=SHA512)


def _verify_key(key: bytes, db_path: Path, page_size: int = SQLCIPHER_PAGE_SIZE) -> bool:
    """用 HMAC-SHA512 验证密钥是否正确（校验数据库第一页的 HMAC 签名）。

    SQLCipher 4 页布局（page_size 参数化，F-1 页大小泛化）：
    - 第一页前 16 字节保留区：salt
    - 其后 32 字节：页 HMAC
    - 剩余 page_size - 48 字节：AES-256-CBC 密文
    """
    if not HAS_CRYPTO:
        return False
    if key is None or len(key) != 32:
        return False
    try:
        with open(db_path, "rb") as f:
            page0 = f.read(page_size)
        if len(page0) < page_size:
            return False
    except OSError:
        return False

    # 提取 salt（前 16 字节，保留区域）
    salt = page0[:SQLCIPHER_RESERVE_SIZE]

    # 派生 HMAC 密钥
    hmac_key = _derive_hmac_key(key, salt)

    # 提取页 HMAC（保留区域后 32 字节）
    stored_hmac = page0[SQLCIPHER_RESERVE_SIZE:SQLCIPHER_RESERVE_SIZE + SQLCIPHER_HMAC_SIZE]

    # 计算期望 HMAC：HMAC-SHA512(hmac_key, page_number || page_data_without_hmac)
    # page_number = 1（第一页），编码为 32 位大端
    page_num = (1).to_bytes(4, "big")
    # 要校验的数据 = page_number + 去掉了 HMAC 的页数据
    page_data = page0[SQLCIPHER_RESERVE_SIZE + SQLCIPHER_HMAC_SIZE:page_size]
    h = HMAC.new(hmac_key, digestmod=SHA512)
    h.update(page_num)
    h.update(page_data)
    expected_hmac = h.digest()[:SQLCIPHER_HMAC_SIZE]

    return stored_hmac == expected_hmac


def detect_page_size(key: bytes, db_path: Path) -> int | None:
    """F-1：用候选页大小逐个校验第一页 HMAC，返回真实页大小（None = 全部失败）。

    页大小被加密在 SQLite 头里，无法从文件直接读出——只能靠 HMAC 校验反推。
    找不到匹配时返回 None（key 错 / 非 SQLCipher / 格式变化）。
    """
    if not HAS_CRYPTO:
        return None
    for ps in SQLCIPHER_PAGE_SIZE_CANDIDATES:
        if _verify_key(key, db_path, page_size=ps):
            return ps
    return None


def _decrypt_page(key: bytes, page: bytes, page_num: int, salt: bytes,
                  page_size: int = SQLCIPHER_PAGE_SIZE) -> bytes | None:
    """解密单个 SQLCipher 4 页（page_size 参数化，F-1）。

    AES-256-CBC：
    - IV = PBKDF2(key, salt || page_number, 1 iter, 16 bytes)
    - 数据 = 页中除去保留区域(16) + HMAC(32) 后的部分（长度 = page_size - 48）
    """
    if not HAS_CRYPTO:
        return None
    try:
        # IV 派生：PBKDF2(key, salt || page_num, 1 iter, 16 bytes)
        iv_input = salt + page_num.to_bytes(4, "big")
        iv = PBKDF2(key, iv_input, dkLen=16, count=1, hmac_hash_module=SHA512)

        # 密文 = 页中去掉保留区域(16) + HMAC(32) 后的剩余部分
        ciphertext = page[SQLCIPHER_RESERVE_SIZE + SQLCIPHER_HMAC_SIZE:page_size]

        cipher = AES.new(key, AES.MODE_CBC, iv=iv)
        plaintext = cipher.decrypt(ciphertext)
        return plaintext
    except Exception as exc:
        logger.debug("解密页 %d 失败: %s", page_num, exc)
        return None


def find_key_from_process(db_path: Path) -> bytes | None:
    """从 Trae CN 进程内存中提取 SQLCipher 密钥。

    流程：
    1. 找 Trae CN 进程
    2. 扫描进程内存，找 `x'<64 hex>'` 模式
    3. 用 HMAC-SHA512 验证每个候选密钥

    返回 32 字节密钥，或 None（未找到/非 Windows/无权限）。
    """
    if not HAS_CRYPTO:
        logger.warning("pycryptodome 未安装——无法解密 Trae 数据库（pip install pycryptodome）")
        return None
    if sys.platform != "win32":
        logger.info("Trae 解密仅支持 Windows")
        return None

    pid = _find_trae_process()
    if pid is None:
        logger.info("未找到运行中的 Trae CN 进程")
        return None

    logger.info("找到 Trae 进程 PID=%d，开始扫描内存…", pid)
    chunks = _scan_process_memory(pid)
    if not chunks:
        logger.warning("未在 Trae 进程内存中找到密钥模式")
        return None

    candidates = _extract_keys(chunks)
    if not candidates:
        logger.warning("未在内存中提取到候选密钥")
        return None

    logger.info("找到 %d 个候选密钥，开始验证…", len(candidates))
    for key in candidates:
        page_size = detect_page_size(key, db_path)
        if page_size is not None:
            logger.info("密钥验证通过！page_size=%d", page_size)
            return key

    logger.warning("所有候选密钥验证均未通过（可能是 Trae 版本变更或数据库格式变化）")
    return None


def decrypt_database(db_path: Path, key: bytes,
                     page_size: int | None = None) -> bytes | None:
    """用密钥解密整个 SQLCipher 数据库，返回明文 SQLite 数据。

    F-1：page_size 未显式给定时用 HMAC 校验反推真实页大小
    （默认候选含 4096；找不到匹配 → 按 4096 尝试一次兜底）。
    注意：此函数返回的是内存中的明文数据，不是写入磁盘的文件。
    """
    if not HAS_CRYPTO:
        return None
    if key is None or len(key) != 32:
        logger.error("密钥无效（需要 32 字节）")
        return None
    try:
        with open(db_path, "rb") as f:
            encrypted = f.read()
    except OSError as exc:
        logger.error("读取加密数据库失败: %s", exc)
        return None

    # 页大小反推（key 正确时 detect_page_size 稳定命中）
    if page_size is None:
        page_size = detect_page_size(key, db_path)
    if page_size is None:
        logger.warning("页大小反推失败（key 错误或格式变化），回退默认 %d 尝试",
                       SQLCIPHER_PAGE_SIZE)
        page_size = SQLCIPHER_PAGE_SIZE
    if len(encrypted) < page_size:
        logger.error("数据库文件太小（<%d 字节）", page_size)
        return None

    # 提取 salt（第一页前 16 字节）
    salt = encrypted[:SQLCIPHER_RESERVE_SIZE]

    # 逐页解密
    plaintext = bytearray()
    num_pages = len(encrypted) // page_size

    for i in range(num_pages):
        offset = i * page_size
        page = encrypted[offset:offset + page_size]
        decrypted = _decrypt_page(key, page, i + 1, salt, page_size=page_size)
        if decrypted is None:
            logger.error("解密第 %d 页失败", i + 1)
            return None
        plaintext.extend(decrypted)

    # 写入标准 SQLite 头部
    sqlite_header = b"SQLite format 3\0"
    plaintext[:16] = sqlite_header

    return bytes(plaintext)


def decrypt_to_file(db_path: Path, key: bytes, out_path: Path | None = None,
                    out_dir: Path | None = None) -> Path | None:
    """解密数据库到文件。

    默认输出位置改为引擎数据目录 decrypt_tmp/（受控目录），
    不再写 <原库>.decrypted.db（第三方工具目录，进程崩溃会残留明文聊天记录）。
    显式传 out_path 时沿用调用方指定位置（兼容旧调用）。

    参数：
        db_path: 加密数据库路径
        key: 32 字节密钥
        out_path: 输出路径（None = 自动生成在引擎 decrypt_tmp/ 目录）
        out_dir: 输出目录（None = 引擎数据目录 decrypt_tmp/；out_path 优先）
    返回：
        解密后的文件路径，或 None（失败）
    """
    plain = decrypt_database(db_path, key)
    if plain is None:
        return None

    if out_path is None:
        from .base_sqlite import _decrypted_tmp_name, decrypt_tmp_dir

        target_dir = Path(out_dir) if out_dir else decrypt_tmp_dir()
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("创建解密临时目录失败: %s", exc)
            return None
        out_path = target_dir / _decrypted_tmp_name(db_path, db_path.suffix or ".db")

    try:
        out_path.write_bytes(plain)
        logger.info("解密完成：%s → %s (%d 字节)", db_path, out_path, len(plain))
        return out_path
    except OSError as exc:
        logger.error("写入解密文件失败: %s", exc)
        return None


def try_decrypt(db_path: Path, out_dir: Path | None = None) -> Path | None:
    """尝试自动解密 Trae CN 数据库。

    一次调用完成：找进程 → 提取密钥 → 验证 → 解密 → 输出文件。
    返回解密后的文件路径，或 None（失败/不支持）。
    """
    key = find_key_from_process(db_path)
    if key is None:
        return None
    return decrypt_to_file(db_path, key, out_dir=out_dir)