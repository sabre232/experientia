"""归档策略（M-3）：归档单位 = 文件，不是会话。

根因：run_scan 曾对每个解析出的会话各拷一次 ref.path——SQLite 容器库
（Cursor state.vscdb 可达数百 MB）N 个会话 = N 份整库副本。
修复：每 ref 至多一份归档；1:1 文件保持 <session_id>.jsonl 旧布局，
容器库统一一份 <原文件名>。
"""

from pathlib import Path

from app.capture import archive
from app.capture.models import Session, SessionRef

DB = b"FAKE-DB-BYTES" * 100


def _ref(tmp_path: Path, agent: str, sid: str, name: str = "state.vscdb") -> SessionRef:
    p = tmp_path / name
    p.write_bytes(DB)
    return SessionRef(agent=agent, session_id=sid, path=p,
                      size=len(DB), mtime=p.stat().st_mtime)


def test_container_ref_one_copy_per_file(tmp_path):
    ref = _ref(tmp_path, "cursor", "state.vscdb")
    sessions = [Session(agent="cursor", session_id="conv-1"),
                Session(agent="cursor", session_id="conv-2")]
    dest = archive.archive_ref(ref, sessions, tmp_path / "data" / "sessions")
    assert dest.name == "state.vscdb"
    assert dest.read_bytes() == DB
    listed = sorted(p.name for p in (tmp_path / "data" / "sessions" / "cursor").iterdir())
    assert listed == ["state.vscdb"]  # 不是 conv-1.jsonl / conv-2.jsonl 两份整库


def test_single_session_container_still_one_copy(tmp_path):
    """容器库里只有 1 个会话（session_id ≠ 文件名）→ 仍按文件归档一份。"""
    ref = _ref(tmp_path, "cursor", "state.vscdb")
    sessions = [Session(agent="cursor", session_id="conv-only")]
    dest = archive.archive_ref(ref, sessions, tmp_path / "data" / "sessions")
    assert dest.name == "state.vscdb"
    listed = sorted(p.name for p in (tmp_path / "data" / "sessions" / "cursor").iterdir())
    assert listed == ["state.vscdb"]


def test_one_to_one_file_keeps_legacy_layout(tmp_path):
    ref = _ref(tmp_path, "claude", "abc-123", name="abc-123.jsonl")
    sessions = [Session(agent="claude", session_id="abc-123")]
    dest = archive.archive_ref(ref, sessions, tmp_path / "data" / "sessions")
    assert dest.name == "abc-123.jsonl"


def test_no_recopy_when_size_unchanged(tmp_path, monkeypatch):
    copies = []
    real_copy2 = archive.shutil.copy2

    def counting_copy2(src, dst):
        copies.append((src, dst))
        return real_copy2(src, dst)

    monkeypatch.setattr(archive.shutil, "copy2", counting_copy2)
    ref = _ref(tmp_path, "cursor", "state.vscdb")
    sessions = [Session(agent="cursor", session_id="conv-1")]
    archive.archive_ref(ref, sessions, tmp_path / "data" / "sessions")
    archive.archive_ref(ref, sessions, tmp_path / "data" / "sessions")  # size 未变 → 不重写
    assert len(copies) == 1


def test_recopy_when_size_changes(tmp_path, monkeypatch):
    copies = []
    real_copy2 = archive.shutil.copy2

    def counting_copy2(src, dst):
        copies.append((src, dst))
        return real_copy2(src, dst)

    monkeypatch.setattr(archive.shutil, "copy2", counting_copy2)
    ref = _ref(tmp_path, "cursor", "state.vscdb")
    sessions = [Session(agent="cursor", session_id="conv-1")]
    dest = archive.archive_ref(ref, sessions, tmp_path / "data" / "sessions")
    ref.path.write_bytes(DB + b"MORE")
    ref.size = len(DB) + 4
    archive.archive_ref(ref, sessions, tmp_path / "data" / "sessions")
    assert len(copies) == 2
    assert dest.read_bytes() == DB + b"MORE"


def test_archive_session_one_to_one_hook_path(tmp_path):
    """hook 通道（Claude Code transcript）保持 1:1 按会话归档。"""
    ref = _ref(tmp_path, "claude", "sid-9", name="sid-9.jsonl")
    dest = archive.archive_session(ref, Session(agent="claude", session_id="sid-9"),
                                   tmp_path / "data" / "sessions")
    assert dest.name == "sid-9.jsonl"
    assert dest.read_bytes() == DB


# ---------- 压缩档不得被"复活" ----------
#
# 档 C 把 <dest> 压成 <dest>.zst 后原件就没了，若归档层只看 dest.exists()，
# 下一次归档会原样复活一份未压缩副本、与**已过期**的 .zst 并存（源没变也会
# 复活）。扫描层按「源 size+mtime 未变」跳过能掩盖它，源一被碰就中招。


def test_compressed_archive_is_not_resurrected(tmp_path, monkeypatch):
    """压缩后再次归档：直接复用 .zst，不复活未压缩副本、不发生第二次拷贝。"""
    from app.distill import maintenance

    copies = []
    real_copy2 = archive.shutil.copy2

    def counting_copy2(src, dst):
        copies.append((src, dst))
        return real_copy2(src, dst)

    monkeypatch.setattr(archive.shutil, "copy2", counting_copy2)
    ref = _ref(tmp_path, "claude", "abc-123", name="abc-123.jsonl")
    sessions = [Session(agent="claude", session_id="abc-123")]
    sdir = tmp_path / "data" / "sessions"

    dest = archive.archive_ref(ref, sessions, sdir)
    assert copies == [(ref.path, dest)]
    maintenance._compress_archive(dest)          # 压掉原件，只留 .jsonl.zst
    zst = archive._compressed_sibling(dest)
    assert zst.exists() and not dest.exists()

    out = archive.archive_ref(ref, sessions, sdir)     # 源未变
    assert out == zst, "应复用压缩档"
    assert not dest.exists(), "不得复活未压缩副本"
    assert len(copies) == 1, "不该发生第二次拷贝"
    assert sorted(p.name for p in dest.parent.iterdir()) == ["abc-123.jsonl.zst"]


def test_stale_compressed_archive_replaced_when_source_grows(tmp_path):
    """源变了（会话续写）→ 过期 .zst 清掉、写新副本，不留两份并存。"""
    import os
    import time

    from app.distill import maintenance

    ref = _ref(tmp_path, "claude", "abc-123", name="abc-123.jsonl")
    sessions = [Session(agent="claude", session_id="abc-123")]
    sdir = tmp_path / "data" / "sessions"

    dest = archive.archive_ref(ref, sessions, sdir)
    maintenance._compress_archive(dest)
    zst = archive._compressed_sibling(dest)
    assert zst.exists()

    ref.path.write_bytes(DB + b"MORE")
    ref.size = len(DB) + 4
    future = time.time() + 3600                  # 源比压缩档新 = 源变过
    os.utime(ref.path, (future, future))

    out = archive.archive_ref(ref, sessions, sdir)
    assert out.name == "abc-123.jsonl"
    assert dest.read_bytes() == DB + b"MORE"
    assert not zst.exists(), "过期压缩档应被清掉，避免两份并存"
