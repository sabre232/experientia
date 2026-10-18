"""app/fs_util.py：全项目原子替换的唯一收口点。

两条契约都必须钉住：
1. 行为契约——瞬时 PermissionError 重试、耗尽照抛、非 PermissionError 不空转；
2. 收口契约——业务层的原子替换不许再出现裸 os.replace。
   第 2 条防的是"某天有人新写一处又把重试漏掉"，靠 review 记不住，靠测试。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.fs_util import REPLACE_BACKOFF_S, REPLACE_RETRIES, replace_atomic

ROOT = Path(__file__).resolve().parents[1]


def _lock_once(state: dict, real_replace):
    """前 state['fail'] 次调用抛 PermissionError，之后放行。"""

    def _replace(src, dst):
        if state["fail"] > 0:
            state["fail"] -= 1
            raise PermissionError(5, "拒绝访问", str(dst), None)
        return real_replace(src, dst)
    return _replace


def test_transient_lock_recovers(tmp_path, monkeypatch):
    src = tmp_path / "f.tmp"
    src.write_text("new", encoding="utf-8")
    dest = tmp_path / "f.json"
    dest.write_text("old", encoding="utf-8")
    real = os.replace
    monkeypatch.setattr(os, "replace", _lock_once({"fail": 2}, real))
    replace_atomic(src, dest)
    monkeypatch.undo()
    assert dest.read_text(encoding="utf-8") == "new"
    assert not src.exists()


def test_exhausted_retries_reraise_original(tmp_path, monkeypatch):
    """锁一直不释放 → 尝试满 REPLACE_RETRIES 次后抛原异常（不吞、不降级）。"""
    src = tmp_path / "f.tmp"
    src.write_text("new", encoding="utf-8")
    dest = tmp_path / "f.json"
    dest.write_text("old", encoding="utf-8")
    attempts = []

    def _locked(_src, dst):
        attempts.append(1)
        raise PermissionError(5, "拒绝访问", str(dst), None)

    monkeypatch.setattr(os, "replace", _locked)
    with pytest.raises(PermissionError):
        replace_atomic(src, dest)
    monkeypatch.undo()
    assert len(attempts) == REPLACE_RETRIES
    assert dest.read_text(encoding="utf-8") == "old"  # 失败不碰正式文件


def test_non_permission_error_not_retried(tmp_path, monkeypatch):
    """目录不可写 / 跨设备之类重试没有意义，一次就该失败。"""
    src = tmp_path / "f.tmp"
    src.write_text("new", encoding="utf-8")
    attempts = []

    def _boom(_src, dst):
        attempts.append(1)
        raise OSError("cross-device link")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        replace_atomic(src, src.parent / "f.json")
    monkeypatch.undo()
    assert len(attempts) == 1


def test_backoff_sequence_matches_retry_count():
    """退避序列必须与重试次数对齐（少一项 → IndexError，多一项 → 白等）。"""
    assert len(REPLACE_BACKOFF_S) == REPLACE_RETRIES - 1
    assert all(s > 0 for s in REPLACE_BACKOFF_S)
    assert sum(REPLACE_BACKOFF_S) < 0.5, "累计等待不该超过半秒"


def test_no_bare_os_replace_in_write_layers():
    """收口契约：业务层与运维脚本里的原子替换必须全部走 replace_atomic。

    app/ 按子包逐个扫（避免把 fs_util 自己的实现算进来），scripts/ 是整个目录——
    运维脚本同样写用户数据，踩的是同一个瞬时锁。
    """
    offenders: list[str] = []
    roots = [ROOT / "app" / sub for sub in
             ("store", "capture", "gui", "distill", "proxy", "semantic",
              "insight", "platform", "rules")]
    roots.append(ROOT / "scripts")
    files: list[Path] = []
    for base in roots:
        if not base.exists():
            continue
        files.extend(base.rglob("*.py"))
    # app/ 根级模块（local_api / ledger / wrap / memory_skill / report_skill …）
    # 同样写用户数据，此前未纳入扫描。fs_util 自身除外：
    # 它就是 replace_atomic 的实现，os.replace 只应出现在这里。
    files.extend(p for p in (ROOT / "app").glob("*.py")
                 if p.name != "fs_util.py")
    for py in files:
            for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                # 匹配 "os.replace(" 而不是 "os.replace"：文档注释里会提到这个名字，
                # 只有带括号才是真调用（"写路径 os.replace 必变 inode" 是散文）
                if "os.replace(" in line:
                    offenders.append(f"{py.relative_to(ROOT)}:{i}")
    assert not offenders, (
        "发现裸 os.replace（瞬时锁重试会被绕过），改用 app.fs_util.replace_atomic: "
        + ", ".join(offenders))
