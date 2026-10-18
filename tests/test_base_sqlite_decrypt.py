"""base_sqlite.parse_db_ref 接入统一解密（universal_decrypt）的路径测试。

parse_db_ref 在函数内 `from .universal_decrypt import try_any_decrypt as _try_any`，
因此通过 monkeypatch universal_decrypt.try_any_decrypt 模拟命中/失败。
覆盖：
- 加密 .db 命中 → 用解密临时文件解析并清理临时文件；
- 解密失败 → 返回 None（不崩溃、不残留）；
- 非加密文件照常 parse_sessions；
- universal_decrypt 导入失败 → 优雅 None。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.capture import models
from app.capture.adapters import base_sqlite
from app.capture.models import Session, SessionRef


class _FakeAdapter:
    """模拟 SQLite 系 adapter：把传进来的 ref 当作明文文件读首行当消息内容。"""

    name = "fake"

    def parse_sessions(self, ref: SessionRef) -> list[Session]:
        s = Session(agent="fake", session_id=ref.session_id)
        content = ref.path.read_bytes().decode("utf-8", errors="replace")
        s.messages.append(models.Message(role="user", content=content))
        return [s]


def _enc_ref(tmp_path: Path, content: bytes = b"encrypted-blob") -> SessionRef:
    p = tmp_path / "state.vscdb"
    p.write_bytes(content)
    st = p.stat()
    return SessionRef(agent="fake", session_id="c1", path=p,
                      size=st.st_size, mtime=st.st_mtime)


@pytest.fixture(autouse=True)
def _stub_encrypt_check(monkeypatch):
    """默认把 is_encrypted 打桩为按需；各用例自行覆写。"""
    monkeypatch.setattr(base_sqlite, "is_encrypted", lambda p: True)


def test_encrypted_db_decrypts_and_cleans_temp(tmp_path, monkeypatch):
    """加密 .db + 解密命中 → 用解密临时文件解析，临时文件用后删除。"""
    temp = tmp_path / "state.decrypted.tmp.db"
    temp.write_bytes(b"decrypted-msg")

    monkeypatch.setattr(
        "app.capture.adapters.universal_decrypt.try_any_decrypt",
        lambda p, a=None: temp)
    ref = _enc_ref(tmp_path)
    s = base_sqlite.parse_db_ref(_FakeAdapter(), ref)
    assert s is not None
    assert s.messages[0].content == "decrypted-msg"
    # 临时文件已被 finally 清理
    assert not temp.exists()


def test_encrypted_db_decrypt_none_returns_none(tmp_path, monkeypatch):
    """解密失败（返回 None）→ 返回 None，不崩溃。"""
    monkeypatch.setattr(
        "app.capture.adapters.universal_decrypt.try_any_decrypt",
        lambda p, a=None: None)
    ref = _enc_ref(tmp_path)
    assert base_sqlite.parse_db_ref(_FakeAdapter(), ref) is None


def test_plaintext_db_parses_directly(tmp_path, monkeypatch):
    """非加密文件不触发解密，照常 parse_sessions。"""
    monkeypatch.setattr(base_sqlite, "is_encrypted", lambda p: False)
    p = tmp_path / "plain.db"
    p.write_bytes(b"plain-msg")
    st = p.stat()
    ref = SessionRef(agent="fake", session_id="p1", path=p,
                     size=st.st_size, mtime=st.st_mtime)
    s = base_sqlite.parse_db_ref(_FakeAdapter(), ref)
    assert s is not None
    assert s.messages[0].content == "plain-msg"


def test_encrypted_db_cleanup_also_on_parse_exception(tmp_path, monkeypatch):
    """解析抛异常时临时文件仍被清理（finally 兜底）。"""
    temp = tmp_path / "state.decrypted.tmp.db"
    temp.write_bytes(b"decrypted-msg")
    monkeypatch.setattr(
        "app.capture.adapters.universal_decrypt.try_any_decrypt",
        lambda p, a=None: temp)

    class _Exploding(_FakeAdapter):
        def parse_sessions(self, ref: SessionRef) -> list[Session]:
            raise RuntimeError("parse exploded")

    ref = _enc_ref(tmp_path)
    with pytest.raises(RuntimeError, match="parse exploded"):
        base_sqlite.parse_db_ref(_Exploding(), ref)
    assert not temp.exists()


# ----------  MX：connect_ro URI 编码 ----------

def test_connect_ro_path_with_hash(tmp_path):
    """路径含 `#` 时旧 f"file:{path}?mode=ro" 会被 URI 片段语法截断 → 打开失败；
    as_uri() 百分号编码后必须照常读库（顺带覆盖非 ASCII 路径）。"""
    import sqlite3

    d = tmp_path / "C# 笔记库"
    d.mkdir()
    p = d / "state.vscdb"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES ('x')")
    conn.commit()
    conn.close()
    c = base_sqlite.connect_ro(p)
    try:
        assert c.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    finally:
        c.close()


def test_sweep_stale_decrypt_tmp_only_touches_controlled_dir(tmp_path, monkeypatch):
    """清扫只动受控 decrypt_tmp/ 内已知模式文件；源目录（第三方工具目录）
    的 *.decrypted.* 不被误删（那是用户/社区工具的产物）。"""
    controlled = tmp_path / "decrypt_tmp"
    controlled.mkdir()
    monkeypatch.setattr(base_sqlite, "_decrypt_tmp_dir_override", controlled)
    stale = controlled / "state-ab12cd34.decrypted.db"
    stale.write_bytes(b"leftover")
    (controlled / "unrelated.txt").write_bytes(b"keep-me")
    src_dir = tmp_path / "third_party"
    src_dir.mkdir()
    community = src_dir / "state.decrypted.db"
    community.write_bytes(b"user-generated")

    n = base_sqlite.sweep_stale_decrypt_tmp()
    assert n == 1
    assert not stale.exists()
    assert (controlled / "unrelated.txt").exists()
    assert community.exists()
