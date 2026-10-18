"""token_util 文件兜底测试：Windows DPAPI 加密、
旧明文迁移、损坏密文回退；POSIX 明文口径保持。"""

import sys

import pytest

from app import token_util
from app.token_util import _TOKEN_BIN_MAGIC, ensure_api_token


def _no_keyring(monkeypatch):
    """让 ensure_api_token 里的 `import keyring` 失败（sys.modules 塞 None）。"""
    monkeypatch.setitem(sys.modules, "keyring", None)


@pytest.fixture(autouse=True)
def _no_token_env(monkeypatch):
    """H4：ensure_api_token 现在 env 优先——本模块测的是 keyring/文件兜底链路，
    统一清掉环境变量避免被短路。"""
    monkeypatch.delenv(token_util.TOKEN_ENV, raising=False)


def _is_win() -> bool:
    return sys.platform == "win32"


@pytest.mark.skipif(not _is_win(), reason="DPAPI 仅 Windows")
def test_dpapi_bin_roundtrip(tmp_path, monkeypatch):
    """keyring 不可用 → DPAPI 加密落 .bin；再次 ensure 读回同一 token。"""
    _no_keyring(monkeypatch)
    t1 = ensure_api_token(tmp_path)
    assert t1
    bin_file = tmp_path / "local_api_token.bin"
    assert bin_file.exists()
    raw = bin_file.read_bytes()
    assert raw.startswith(_TOKEN_BIN_MAGIC)          # magic 头区分格式
    assert t1.encode() not in raw                    # 明文不在盘上
    assert not (tmp_path / "local_api_token").exists()
    assert ensure_api_token(tmp_path) == t1          # 读取一致（幂等）


@pytest.mark.skipif(not _is_win(), reason="DPAPI 迁移仅 Windows")
def test_legacy_plaintext_migrated(tmp_path, monkeypatch):
    """旧明文 local_api_token → 读到后加密迁移 .bin 并删除明文，值不变。"""
    _no_keyring(monkeypatch)
    legacy = tmp_path / "local_api_token"
    legacy.write_text("legacy-token-123", encoding="utf-8")
    assert ensure_api_token(tmp_path) == "legacy-token-123"
    assert not legacy.exists()                       # 明文已删
    assert (tmp_path / "local_api_token.bin").exists()
    # 迁移后再次读取仍一致（走 .bin 新格式）
    assert ensure_api_token(tmp_path) == "legacy-token-123"


@pytest.mark.skipif(not _is_win(), reason="DPAPI 回退仅 Windows")
def test_corrupted_bin_falls_back_and_regenerates(tmp_path, monkeypatch):
    """损坏的 .bin：有旧明文 → 回退旧明文口径；无明文 → 重新生成且读回一致。"""
    _no_keyring(monkeypatch)
    # 1) 损坏 .bin + 有效旧明文 → 回退明文值
    (tmp_path / "local_api_token.bin").write_bytes(
        _TOKEN_BIN_MAGIC + b"\x00\x01garbage-not-dpapi")
    (tmp_path / "local_api_token").write_text("fallback-token", encoding="utf-8")
    assert ensure_api_token(tmp_path) == "fallback-token"
    # 2) 损坏 .bin 且无明文 → 生成新 token（覆盖坏 .bin），读回一致
    (tmp_path / "local_api_token.bin").write_bytes(b"NOTMAGIC" + b"\x00" * 32)
    t = ensure_api_token(tmp_path)
    assert t and t != "fallback-token"
    assert ensure_api_token(tmp_path) == t


def test_dpapi_helpers_direct(tmp_path):
    """_dpapi_protect/_unprotect 往返一致；损坏密文解密返回 None（不抛）。"""
    blob = token_util._dpapi_protect("secret".encode("utf-8"))
    if not _is_win():
        assert blob is None
        pytest.skip("DPAPI 仅 Windows")
    assert blob and token_util._dpapi_unprotect(blob) == b"secret"
    assert token_util._dpapi_unprotect(b"garbage") is None
    assert token_util._dpapi_protect(b"x") is not None


@pytest.mark.skipif(_is_win(), reason="POSIX 明文口径")
def test_posix_plaintext_unchanged(tmp_path, monkeypatch):
    """POSIX：维持明文 local_api_token + 0600，行为与旧版一致。"""
    import stat

    _no_keyring(monkeypatch)
    t1 = ensure_api_token(tmp_path)
    f = tmp_path / "local_api_token"
    assert f.exists()
    assert f.read_text(encoding="utf-8").strip() == t1
    # 文件以 0600 建，非「先默认权限再 chmod」的可读窗口
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert ensure_api_token(tmp_path) == t1


# ---------- M12：provider key 兜底保护 protect/resolve_fallback_secret ----------

def test_fallback_secret_roundtrip():
    """protect → resolve 永远读回原值（两种平台都对）。"""
    fields = token_util.protect_fallback_secret("sk-abcd1234")
    assert token_util.resolve_fallback_secret(fields) == "sk-abcd1234"


@pytest.mark.skipif(not _is_win(), reason="DPAPI 兜底仅 Windows")
def test_fallback_secret_dpapi_not_plaintext_on_windows():
    """Windows：兜底落盘是 DPAPI 密文（api_key_enc），明文串不在字段值里。"""
    fields = token_util.protect_fallback_secret("sk-secret-value")
    assert "api_key_enc" in fields and "api_key" not in fields
    assert "sk-secret-value" not in fields["api_key_enc"]


@pytest.mark.skipif(_is_win(), reason="POSIX 兜底走明文 + 0600")
def test_fallback_secret_plaintext_on_posix():
    """POSIX：0600 有效，兜底沿用明文 api_key 字段。"""
    fields = token_util.protect_fallback_secret("sk-secret-value")
    assert fields == {"api_key": "sk-secret-value"}


def test_resolve_fallback_legacy_plaintext_compat():
    """向后兼容：旧配置里只有明文 api_key → resolve 直接读到。"""
    assert token_util.resolve_fallback_secret({"api_key": "sk-old"}) == "sk-old"
    assert token_util.resolve_fallback_secret({}) is None


def test_resolve_fallback_corrupt_returns_none():
    """密文/base64 损坏或解不开 → None（当作无 key，不抛）。"""
    assert token_util.resolve_fallback_secret({"api_key_enc": "!!!not-base64"}) is None
    assert token_util.resolve_fallback_secret(
        {"api_key_enc": token_util.base64.b64encode(b"garbage-blob").decode()}) is None


@pytest.mark.skipif(not _is_win(), reason="DPAPI 端到端仅 Windows 有加密路径")
def test_forwarding_uses_encrypted_fallback_key():
    """兜底密文经代理转发/蒸馏两处读回，都能拼出正确 Authorization（端到端）。"""
    from app.distill import llm
    from app.proxy import server

    route = {"route_name": "gpt", "model": "gpt-4o",
             **token_util.protect_fallback_secret("sk-e2e-xyz")}
    assert route.get("api_key_enc")            # 确认走的是加密兜底而非明文
    assert server._upstream_headers(route, None)["Authorization"] == "Bearer sk-e2e-xyz"
    assert llm._resolve_key(route) == "sk-e2e-xyz"

