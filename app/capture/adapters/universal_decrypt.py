"""统一解密框架：组合多种 agent 数据库解密策略。

设计原则：
1. **策略模式**：每种解密方法是一个 DecryptStrategy，各自独立
2. **注册表机制**：按 agent 名注册对应策略，detect() 自动分派
3. **串联尝试**：try_any_decrypt() 按优先级依次尝试，直到成功
4. **勿扰**：所有策略都不阻塞主线程，失败静默返回 None

当前支持的 agent 及策略：
  - Trae CN：SQLCipher 4 → ProcessMemoryStrategy（进程内存扫描）
  - Windsurf：AES-256-GCM → HardcodedKeyStrategy（全局硬编码密钥）

参考来源：
  - trae-db-decrypt (https://github.com/Oh-My-Trae/trae-db-decrypt)
  - trae-chat-decrypt (https://github.com/ZedeX/trae-chat-decrypt)
  - windsurf-local-user-data-decryption (https://github.com/dayearleo/windsurf-local-user-data-decryption)
  - ghosttype RESEARCH.md (https://github.com/xFreed0m/ghosttype)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum, auto
from pathlib import Path

logger = logging.getLogger("experientia.capture.universal_decrypt")


# ---------- 加密类型检测 ----------


class EncryptionType(Enum):
    """加密类型枚举，用于 detect_encryption() 的返回值。"""
    PLAINTEXT = auto()
    """标准 SQLite 格式（头部 SQLite format 3\\0），无需解密"""
    SQLCIPHER_4 = auto()
    """SQLCipher 4 加密：AES-256-CBC, PBKDF2-HMAC-SHA512, 页 HMAC"""
    AES_GCM = auto()
    """AES-256-GCM 加密：12 字节 nonce + 密文 + 16 字节 tag（如 Windsurf .pb）"""
    UNKNOWN = auto()
    """无法识别的格式"""


def detect_encryption(path: Path) -> EncryptionType:
    """检测文件的加密类型。

    策略：
    1. 读前 16 字节 → 是 SQLite 格式 → PLAINTEXT
    2. 文件 ≥ 4096 且大小是 4096 的整数倍且非 SQLite 头部 → SQLCIPHER_4
    3. 文件小（< 4096）且非 SQLite 头部 → 可能是 AES_GCM（如 .pb 文件）
    4. 其他 → UNKNOWN
    """
    if not path.is_file():
        return EncryptionType.UNKNOWN
    try:
        with path.open("rb") as fh:
            header = fh.read(16)
    except (OSError, PermissionError):
        return EncryptionType.UNKNOWN

    if header == b"SQLite format 3\0":
        return EncryptionType.PLAINTEXT

    try:
        size = path.stat().st_size
    except OSError:
        return EncryptionType.UNKNOWN

    # SQLCipher 4 特征：非 SQLite 头部 + 大小是 4096 的整数倍
    if size >= 4096 and size % 4096 == 0:
        return EncryptionType.SQLCIPHER_4

    # AES-GCM 特征：小文件（typical < 1MB），非 SQLite 头部
    if size > 0:
        return EncryptionType.AES_GCM

    return EncryptionType.UNKNOWN


# ---------- 策略基类 ----------


class DecryptStrategy(ABC):
    """解密策略基类。

    每个策略实现两个方法：
    - can_decrypt(path, agent)：判断是否适用于这个文件
    - decrypt(path)：执行解密，返回解密后的文件路径或 None
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称（用于日志和调试）。"""
        ...

    @abstractmethod
    def can_decrypt(self, path: Path, agent: str | None = None) -> bool:
        """判断本策略是否适用于此文件。"""
        ...

    @abstractmethod
    def decrypt(self, path: Path, **kwargs) -> Path | None:
        """执行解密，返回解密后的文件路径（临时文件），或 None。

        调用方负责在解密文件使用后清理。
        """
        ...


# ---------- 策略：进程内存扫描（Trae CN SQLCipher 4）----------


class ProcessMemoryStrategy(DecryptStrategy):
    """进程内存扫描策略——适用于 Trae CN 的 SQLCipher 4 加密数据库。

    原理：
    - Trae 的 ai_agent.dll 进程内存中保存着原始 32 字节密钥，格式为 x'<64 hex>'
    - 通过 ReadProcessMemory API 扫描内存，提取候选密钥
    - 用 HMAC-SHA512 验证密钥是否正确
    - 纯 Python AES-256-CBC 逐页解密

    依赖：pycryptodome（pip install pycryptodome）
    平台：仅 Windows（需要 ReadProcessMemory API）
    条件：Trae 进程必须正在运行
    """

    @property
    def name(self) -> str:
        return "process_memory"

    def can_decrypt(self, path: Path, agent: str | None = None) -> bool:
        if agent is not None and agent != "trae":
            return False
        from .base_sqlite import is_encrypted
        enc = is_encrypted(path)
        return enc and path.suffix == ".db"

    def decrypt(self, path: Path, **kwargs) -> Path | None:
        try:
            from .trae_decrypt import try_decrypt as _trae_decrypt
            # 明文临时库落引擎数据目录 decrypt_tmp/，
            # 不再写 <原库>.decrypted.db（第三方工具目录残留隐患）
            from .base_sqlite import decrypt_tmp_dir
            return _trae_decrypt(path, out_dir=decrypt_tmp_dir())
        except ImportError:
            logger.info("ProcessMemoryStrategy: trae_decrypt 模块不可用")
            return None
        except Exception as exc:
            logger.warning("ProcessMemoryStrategy 解密失败: %s", exc)
            return None


# ---------- 策略：硬编码密钥（Windsurf AES-256-GCM）----------


# Windsurf 全局硬编码 AES-256-GCM 密钥表（来源：windsurf-local-user-data-decryption）
# F-2：版本表化——上游升级换 key = 在此追加一行（新版本在前），decrypt 逐个尝试；
# 不再允许 windsurf.py / 其它模块各自再复制一份硬编码。
_WINDSURF_AES_KEYS: tuple[tuple[bytes, str], ...] = (
    (b"safeCodeiumworldKeYsecretBalloon", "v1"),
)


def windsurf_known_keys() -> list[bytes]:
    """Windsurf 已知密钥列表（唯一事实源；windsurf.py 收敛共用，F-2）。"""
    return [k for k, _ in _WINDSURF_AES_KEYS]


class HardcodedKeyStrategy(DecryptStrategy):
    """硬编码密钥策略——适用于已知密钥的 AES-GCM 加密文件。

    当前支持的 agent：
    - Windsurf：AES-256-GCM，密钥 `safeCodeiumworldKeYsecretBalloon`
    """

    @property
    def name(self) -> str:
        return "hardcoded_key"

    def can_decrypt(self, path: Path, agent: str | None = None) -> bool:
        if agent is not None and agent != "windsurf":
            return False
        return path.suffix == ".pb"

    def decrypt(self, path: Path, **kwargs) -> Path | None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            logger.info("HardcodedKeyStrategy: cryptography 模块不可用")
            return None

        try:
            data = path.read_bytes()
            if len(data) < 12 + 16:
                return None
            nonce = data[:12]
            ciphertext = data[12:]
            # F-2：逐版本尝试（换 key 后旧文件仍可解），全部失败才落 debug
            for version, (key, _label) in enumerate(_WINDSURF_AES_KEYS, 1):
                try:
                    plain = AESGCM(key).decrypt(nonce, ciphertext, None)
                except Exception:
                    continue
                # 明文临时文件落引擎数据目录 decrypt_tmp/，
                # 不再写 <原文件>.decrypted.pb（第三方工具目录残留隐患）
                from .base_sqlite import _decrypted_tmp_name, decrypt_tmp_dir

                out_dir = decrypt_tmp_dir()
                try:
                    out_dir.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    logger.warning("创建解密临时目录失败: %s", exc)
                    return None
                out = out_dir / _decrypted_tmp_name(path, path.suffix or ".pb")
                out.write_bytes(plain)
                logger.info("HardcodedKeyStrategy 解密完成 (key v%d): %s", version, out)
                return out
            return None
        except Exception as exc:
            logger.debug("HardcodedKeyStrategy 解密失败 %s: %s", path, exc)
            return None


# ---------- 策略：社区工具预解密文件 ----------


class CommunityToolStrategy(DecryptStrategy):
    """社区工具策略——查找第三方工具已生成的解密文件。

    适用场景：用户已通过 trae-db-decrypt、windsurf-local-user-data-decryption
    等社区工具解密了数据库，本策略直接查找这些已解密文件，避免重复解密。
    """

    @property
    def name(self) -> str:
        return "community_tool"

    def can_decrypt(self, path: Path, agent: str | None = None) -> bool:
        return True  # 始终尝试，失败返回 None

    def decrypt(self, path: Path, **kwargs) -> Path | None:
        candidates = [
            path.with_suffix(".decrypted.db"),
            path.with_suffix(".plain.db"),
            path.parent / "database_decrypted.db",
            path.with_suffix(".decrypted.pb"),
        ]
        for cand in candidates:
            if cand.is_file() and cand.stat().st_size > 0:
                logger.info("CommunityToolStrategy 找到预解密文件: %s", cand)
                return cand
        return None


# ---------- 策略注册表 ----------


class DecryptRegistry:
    """解密策略注册表。

    按 agent 名注册策略，try_any_decrypt() 按注册顺序依次尝试。

    用法：
        registry = DecryptRegistry()
        registry.register("trae", ProcessMemoryStrategy())
        registry.register("windsurf", HardcodedKeyStrategy())
        result = registry.try_any_decrypt(path, "trae")
    """

    def __init__(self):
        self._strategies: dict[str, list[DecryptStrategy]] = {}
        self._global_strategies: list[DecryptStrategy] = []

    def register(self, agent_name: str, strategy: DecryptStrategy) -> None:
        """为指定 agent 注册一个解密策略。"""
        self._strategies.setdefault(agent_name, []).append(strategy)

    def register_global(self, strategy: DecryptStrategy) -> None:
        """注册全局策略（对所有 agent 都尝试）。"""
        self._global_strategies.append(strategy)

    def try_any_decrypt(
        self, path: Path, agent_name: str | None = None,
    ) -> Path | None:
        """尝试所有可能的解密策略，直到成功。

        优先级：
        1. agent 专属策略（按注册顺序）
        2. 全局策略（按注册顺序）
        3. 社区工具预解密文件查找

        Args:
            path: 加密文件路径
            agent_name: agent 名称（None = 尝试所有全局策略）

        Returns:
            解密后的文件路径，或 None（全部失败）
        """
        # 0. ：解密前清扫本模块遗留的 *.decrypted.* 明文
        # 临时文件（进程崩溃残留；daemon 启动清扫不可行 → 每次解密入口兜底）
        try:
            from .base_sqlite import sweep_stale_decrypt_tmp

            sweep_stale_decrypt_tmp()
        except Exception as exc:
            logger.debug("解密临时文件清扫失败（不影响解密）: %s", exc)

        # 1. Agent 专属策略
        if agent_name is not None:
            for strategy in self._strategies.get(agent_name, []):
                if strategy.can_decrypt(path, agent_name):
                    result = strategy.decrypt(path)
                    if result is not None:
                        return result

        # 2. 全局策略
        for strategy in self._global_strategies:
            if strategy.can_decrypt(path, agent_name):
                result = strategy.decrypt(path)
                if result is not None:
                    return result

        # 3. 兜底：社区工具预解密文件
        for strategy in self._strategies.get("_fallback", []):
            if strategy.can_decrypt(path, agent_name):
                result = strategy.decrypt(path)
                if result is not None:
                    return result

        return None

    def strategies_for(self, agent_name: str) -> list[DecryptStrategy]:
        """返回指定 agent 的所有已注册策略。"""
        return list(self._strategies.get(agent_name, []))


# ---------- 全局单例 ----------

DECRYPT_REGISTRY = DecryptRegistry()
"""全局解密注册表单例。应用启动时自动注册已知策略。"""


def _init_registry() -> None:
    """初始化全局注册表，注册所有已知策略。"""
    from . import trae_decrypt  # noqa: F401 — 确保解密模块可用

    DECRYPT_REGISTRY.register("trae", ProcessMemoryStrategy())
    DECRYPT_REGISTRY.register("windsurf", HardcodedKeyStrategy())
    # 全局兜底：社区工具预解密文件
    DECRYPT_REGISTRY.register("_fallback", CommunityToolStrategy())


# 模块加载时自动初始化
_init_registry()


def try_any_decrypt(path: Path, agent_name: str | None = None) -> Path | None:
    """便捷函数：全局注册表串联尝试所有解密策略。

    等效于 DECRYPT_REGISTRY.try_any_decrypt(path, agent_name)。
    """
    return DECRYPT_REGISTRY.try_any_decrypt(path, agent_name)


def detect_encryption_human(path: Path) -> str:
    """返回人类可读的加密类型描述（用于 UI 展示）。"""
    enc = detect_encryption(path)
    if enc == EncryptionType.PLAINTEXT:
        return "明文 SQLite"
    elif enc == EncryptionType.SQLCIPHER_4:
        return "SQLCipher 4 加密"
    elif enc == EncryptionType.AES_GCM:
        return "AES-256-GCM 加密"
    return "未知格式"