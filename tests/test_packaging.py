"""Phase 8b：打包运行时检测 + 开机自启命令。

打包运行时检测统一走 PyInstaller 的 sys.frozen（见 experientia.spec）；
自动更新链路（RELEASE.json 生成、下载/轮换/回滚）已于移除。
"""

import sys
from pathlib import Path

from app.platform import autostart

REPO_ROOT = Path(__file__).resolve().parent.parent


def _clear_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("FLET_PLATFORM", raising=False)


def test_daemon_command_source_mode(monkeypatch):
    """源码模式 = 解释器 + 仓库根 daemon.py 绝对路径
    （`python -m experientia.daemon` 指向不存在的模块，注册后必然失败）。"""
    _clear_frozen(monkeypatch)
    cmd = autostart._daemon_command()
    assert cmd == [sys.executable, str(REPO_ROOT / "daemon.py")]


def test_daemon_command_arg_quoting(monkeypatch):
    """含空格路径逐参数加引号（schtasks /TR 同口径），无空格路径不加。"""
    assert autostart._quote_arg(r"C:\Program Files\Python\python.exe") == \
        '"C:\\Program Files\\Python\\python.exe"'
    assert autostart._quote_arg("/usr/bin/python3") == "/usr/bin/python3"


def test_daemon_command_packaged(monkeypatch, tmp_path):
    _clear_frozen(monkeypatch)
    fake = tmp_path / "experientia.exe"
    fake.write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake))
    assert autostart._daemon_command() == [str(fake), "--headless"]


def test_main_is_packaged_follows_env(monkeypatch):
    """Qt/PyInstaller 迁移后：main.is_packaged() 只看 sys.frozen。

    flet 嵌入运行时的 FLET_PLATFORM 判定已随迁移废弃；打包运行时检测
    统一走 PyInstaller 的 sys.frozen（见 experientia.spec）。
    """
    import main

    _clear_frozen(monkeypatch)
    assert main.is_packaged() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert main.is_packaged() is True

