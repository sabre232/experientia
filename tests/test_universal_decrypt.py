"""统一解密框架补测（重构报告 TEST-2）：检测决策树 + 策略注册/分派/兜底 + 硬编码 roundtrip。

不依赖真实 SQLCipher 进程内存扫描（那需要运行中 Trae + 平台权限）；
用确定性输入覆盖模块全部公开判定与分派逻辑。真实 Trae 解密由 ProcessMemory
策略在具备运行环境时走 trae_decrypt（trae.py 已有集成路径）。
"""

from pathlib import Path

import pytest

from app.capture.adapters import universal_decrypt as ud


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


# ---------- detect_encryption 决策树 ----------

def test_detect_sqlite_plaintext(tmp_path):
    p = _write(tmp_path, "plain.db", b"SQLite format 3\x00" + b"\x00" * 80)
    assert ud.detect_encryption(p) is ud.EncryptionType.PLAINTEXT


def test_detect_sqlcipher4_page_multiple(tmp_path):
    p = _write(tmp_path, "enc.db", b"\x01" * 4096)  # 非 SQLite 头 + 4096 整倍
    assert ud.detect_encryption(p) is ud.EncryptionType.SQLCIPHER_4


def test_detect_aes_gcm_small(tmp_path):
    p = _write(tmp_path, "traj.pb", b"\x00" * 100)  # 小文件非 SQLite 头
    assert ud.detect_encryption(p) is ud.EncryptionType.AES_GCM


def test_detect_unknown_missing_or_empty(tmp_path):
    assert ud.detect_encryption(tmp_path / "nope.db") is ud.EncryptionType.UNKNOWN
    assert ud.detect_encryption(_write(tmp_path, "empty", b"")) is ud.EncryptionType.UNKNOWN


def test_detect_human_labels(tmp_path):
    p = _write(tmp_path, "a.db", b"SQLite format 3\x00" + b"\x00" * 8)
    assert "明文" in ud.detect_encryption_human(p)
    assert ud.detect_encryption_human(tmp_path / "x.db") == "未知格式"


# ---------- 策略注册/分派顺序 ----------

class _FakeStrategy(ud.DecryptStrategy):
    """可控假策略：只接受指定 agent、按需成功/失败。"""

    def __init__(self, name: str, agent: str | None, result: Path | None,
                 side_effect: Exception | None = None):
        self._name = name
        self._agent = agent
        self._result = result
        self._exc = side_effect
        self.calls: list[tuple[Path, str | None]] = []

    @property
    def name(self) -> str:
        return self._name

    def can_decrypt(self, path: Path, agent: str | None = None) -> bool:
        return self._agent is None or agent == self._agent

    def decrypt(self, path: Path, **kwargs) -> Path | None:
        self.calls.append((path, kwargs.get("agent")))
        if self._exc is not None:
            raise self._exc
        return self._result


def test_registry_agent_specific_before_global(tmp_path):
    hit = _write(tmp_path, "h.db", b"\x01" * 4096)
    registry = ud.DecryptRegistry()
    agent = _FakeStrategy("agent", "trae", hit)
    glob = _FakeStrategy("global", None, hit)
    registry.register("trae", agent)
    registry.register_global(glob)
    assert registry.try_any_decrypt(hit, "trae") == hit
    assert agent.calls and not glob.calls  # agent 专属命中后全局不再尝试


def test_registry_falls_through_to_global_and_community(tmp_path):
    p = _write(tmp_path, "x.db", b"\x01" * 4096)
    dec = tmp_path / "x.decrypted.db"
    dec.write_bytes(b"dec")
    registry = ud.DecryptRegistry()
    # 专属策略判定命中但解密返回 None → 继续往下尝试（兜底链）
    failing = _FakeStrategy("failing", "trae", None)
    registry.register("trae", failing)
    community = _FakeStrategy("community", None, dec)  # 全局兜底不受 agent 限制
    registry.register("_fallback", community)
    assert registry.try_any_decrypt(p, "trae") == dec
    assert community.calls  # 兜底被触达


def test_registry_none_when_all_fail(tmp_path):
    p = _write(tmp_path, "y.db", b"\x01" * 4096)
    registry = ud.DecryptRegistry()
    registry.register("trae", _FakeStrategy("no", "trae", None))
    assert registry.try_any_decrypt(p, "trae") is None
    assert registry.strategies_for("trae")


# ---------- 便捷入口与社区预解密兜底 ----------

def test_try_any_decrypt_uses_global_singleton(tmp_path, monkeypatch):
    p = _write(tmp_path, "c.db", b"\x01" * 4096)
    dec = tmp_path / "c.plain.db"
    dec.write_bytes(b"ok")
    registry = ud.DecryptRegistry()
    registry.register("_fallback", ud.CommunityToolStrategy())
    monkeypatch.setattr(ud, "DECRYPT_REGISTRY", registry)
    assert ud.try_any_decrypt(p, "trae") == dec


# ---------- HardcodedKeyStrategy AES-GCM roundtrip ----------

@pytest.fixture
def controlled_tmp(tmp_path, monkeypatch):
    """：把解密明文临时目录指向用例内受控目录（不落真实数据目录）。"""
    from app.capture.adapters import base_sqlite

    d = tmp_path / "decrypt_tmp"
    d.mkdir(parents=True)
    monkeypatch.setattr(base_sqlite, "_decrypt_tmp_dir_override", d)
    return d


def test_windsurf_hardcoded_roundtrip(tmp_path, controlled_tmp):
    """用同一硬编码密钥加密 → 策略能解回原文（跳过无 cryptography 的环境）。

    M12：解密产物必须落在受控 decrypt_tmp/ 目录（<源>.decrypted.pb 不再写
    第三方工具目录），文件名带源路径指纹防同名冲突。"""
    AESGCM = pytest.importorskip(
        "cryptography.hazmat.primitives.ciphers.aead", reason="需要 cryptography").AESGCM
    key = b"safeCodeiumworldKeYsecretBalloon"
    plain = b'{"trajectory": [1,2,3]}'
    nonce = b"\x11" * 12
    ct = AESGCM(key).encrypt(nonce, plain, None)
    sub = tmp_path / "third_party_dir"
    sub.mkdir()
    p = sub / "traj.pb"
    p.write_bytes(nonce + ct)
    out = ud.HardcodedKeyStrategy().decrypt(p)
    assert out is not None
    assert out.read_bytes() == plain
    # 核心断言：不再写源文件旁，落受控目录
    assert out.parent == controlled_tmp
    assert out.parent != sub
    assert out.name.endswith(".decrypted.pb")
    assert out.name != "traj.decrypted.pb"  # 带指纹，不同目录同名源不互撞
    assert ud.detect_encryption(p) is ud.EncryptionType.AES_GCM


# ---------- ：解密前清扫崩溃遗留明文临时文件 ----------

def test_try_any_decrypt_sweeps_stale_temp_files(tmp_path, controlled_tmp):
    """try_any_decrypt 入口清扫 decrypt_tmp/ 内 *.decrypted.*（进程崩溃残留）；
    第三方工具预解密文件（源旁）不受清扫影响。"""
    stale_db = controlled_tmp / "state-12345678.decrypted.db"
    stale_pb = controlled_tmp / "traj-87654321.decrypted.pb"
    stale_db.write_bytes(b"leftover-plaintext")
    stale_pb.write_bytes(b"leftover-plaintext")
    p = _write(tmp_path, "z.db", b"\x01" * 4096)
    registry = ud.DecryptRegistry()
    registry.register("trae", _FakeStrategy("no", "trae", None))
    assert registry.try_any_decrypt(p, "trae") is None
    # 清扫发生在策略尝试前 → 遗留明文已删
    assert not stale_db.exists()
    assert not stale_pb.exists()
    # 源目录（第三方工具场景）未被误扫
    assert p.exists()


def test_trae_decrypt_to_file_default_lands_controlled_dir(
        tmp_path, controlled_tmp, monkeypatch):
    """M12：trae_decrypt.decrypt_to_file 缺省输出落引擎 decrypt_tmp/（带指纹名），
    不再写 <原库>.decrypted.db。"""
    from app.capture.adapters import trae_decrypt as td

    monkeypatch.setattr(td, "decrypt_database",
                        lambda db, key, page_size=None: b"plain-bytes")
    db = _write(tmp_path, "state.db", b"\x01" * 4096)
    out = td.decrypt_to_file(db, b"k" * 32)
    assert out is not None
    assert out.parent == controlled_tmp
    assert out.name.startswith("state-") and out.name.endswith(".decrypted.db")
    assert out.read_bytes() == b"plain-bytes"
    # 源目录不产生任何解密产物
    assert not (tmp_path / "state.decrypted.db").exists()
