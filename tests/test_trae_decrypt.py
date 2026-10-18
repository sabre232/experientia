"""Trae/Windsurf 解密硬化补测（重构报告 F-1/F-2）。

F-1：候选密钥提取过滤/去重 + 页大小反推对非 SQLCipher 文件拒绝；
F-2：windsurf 密钥版本表唯一事实源。
真实 SQLCipher 内存扫描需 Windows + 运行中 Trae + 管理员权限——不进单测，
由通用 roundtrip（universal_decrypt 补测）与手动验收覆盖。
"""

from pathlib import Path

from app.capture.adapters import trae_decrypt as td
from app.capture.adapters import universal_decrypt as ud


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


# ---------- F-1：候选密钥提取 ----------

def test_extract_keys_filters_length_and_dedupes():
    good = b"00" * 32
    chunks = [
        b"x'" + good + b"' first",
        b"x'" + good + b"' duplicate",          # 重复 → 去重
        b"x'zzz' short",                          # 非 hex
        b"x'" + b"11" * 16 + b"' too-short-key",  # 长度非 32 字节
    ]
    keys = td._extract_keys(chunks)
    assert keys == [bytes.fromhex(good.decode())]


def test_key_pattern_matches_64_hex():
    m = td._KEY_PATTERN.search(b"prefix x'" + b"ab" * 32 + b"' suffix")
    assert m is not None
    assert m.group(1) == b"ab" * 32


# ---------- F-1：页大小反推拒绝非 SQLCipher ----------

def test_detect_page_size_rejects_plaintext_sqlite(tmp_path):
    p = _write(tmp_path, "plain.db",
               b"SQLite format 3\x00" + b"\x00" * 65540)
    key = b"k" * 32
    assert td.detect_page_size(key, p) is None


def test_detect_page_size_rejects_garbage(tmp_path):
    p = _write(tmp_path, "garbage.bin", b"\xff" * 70000)
    assert td.detect_page_size(b"k" * 32, p) is None


def test_detect_page_size_none_on_missing(tmp_path):
    assert td.detect_page_size(b"k" * 32, tmp_path / "nope.db") is None


# ---------- F-2：windsurf 密钥版本表 ----------

def test_windsurf_known_keys_single_source():
    keys = ud.windsurf_known_keys()
    assert b"safeCodeiumworldKeYsecretBalloon" in keys  # v1 仍在
    # 表是唯一事实源：windsurf.py 不再本地复制（_WINDSURF_AES_KEY 已删）
    import app.capture.adapters.windsurf as ws
    assert not hasattr(ws, "_WINDSURF_AES_KEY")
    # 全部 32 字节（AES-256）
    assert all(len(k) == 32 for k in keys)
