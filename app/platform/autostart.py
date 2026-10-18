"""开机自启（第 3 点，与更新流程解耦）。

三平台注册：
- Windows：任务计划程序（schtasks /Create，AtLogon 触发）
- macOS：launchd plist（~/Library/LaunchAgents/com.experientia.daemon.plist）
- Linux：systemd user unit（~/.config/systemd/user/experientia.service）

headless 形态 = `<python> <仓库根>/daemon.py`（与桌面端同包）。
开发模式（源码运行）用当前解释器 + daemon.py 绝对路径；frozen 构建用 exe 本体。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "Experientia"
TASK_NAME = "ExperientiaDaemon"
PLIST_NAME = "com.experientia.daemon.plist"
UNIT_NAME = "experientia.service"


def _is_packaged() -> bool:
    """打包运行时判定（收敛到 app.platform.runtime.is_packaged，CLN-2）。"""
    from .runtime import is_packaged as _runtime_packaged

    return _runtime_packaged()


def _repo_root() -> Path:
    """仓库根（app 包的上一级）：app/platform/autostart.py → parents[2]。"""
    return Path(__file__).resolve().parents[2]


def _daemon_command() -> list[str]:
    """headless 启动命令：打包 = exe --headless；源码 = <python> <仓库根>/daemon.py。

    源码模式用绝对路径直指 daemon.py：`python -m experientia.daemon` 指向不存在的
    模块（顶层无 experientia 包，wheel 只打包 app），注册成功但重启后必然失败；
    绝对路径同时摆脱 cwd 依赖（登录触发时 cwd 不可控）。
    """
    if _is_packaged():
        return [str(Path(sys.executable)), "--headless"]
    return [sys.executable, str(_repo_root() / "daemon.py")]


def _quote_arg(a: str) -> str:
    """含空格的参数加引号（schtasks /TR 与 systemd ExecStart 同口径）。"""
    return f'"{a}"' if " " in a else a


# ---------- Windows：任务计划程序 ----------

def _win_enable() -> None:
    exe = shutil.which("schtasks") or r"C:\WINDOWS\system32\schtasks.exe"
    # 逐参数加引号后拼接：整条包进一对引号会被当成"含空格的可执行名"
    tr = " ".join(_quote_arg(a) for a in _daemon_command())
    args = [exe, "/Create", "/F", "/TN", TASK_NAME, "/SC", "ONLOGON",
            "/RL", "LIMITED", "/TR", tr]
    subprocess.run(args, check=True, capture_output=True, timeout=30)


def _win_disable() -> None:
    exe = shutil.which("schtasks") or r"C:\WINDOWS\system32\schtasks.exe"
    # M-N13: 任务不存在时静默忽略（已卸载），其他错误（如权限不足）记日志
    import logging as _log
    r = subprocess.run([exe, "/Delete", "/F", "/TN", TASK_NAME],
                       capture_output=True, timeout=30)
    if r.returncode != 0:
        stderr = (r.stderr or b"").decode("utf-8", errors="replace").strip()
        if "does not exist" in stderr.lower() or "不存在" in stderr:
            return  # 任务不存在 = 已卸载，静默忽略
        _log.getLogger("experientia.autostart").warning(
            "关闭自启（schtasks /Delete）失败: %s", stderr)


def _win_is_enabled() -> bool:
    exe = shutil.which("schtasks") or r"C:\WINDOWS\system32\schtasks.exe"
    r = subprocess.run([exe, "/Query", "/TN", TASK_NAME],
                       capture_output=True, timeout=30)
    return r.returncode == 0


# ---------- macOS：launchd ----------

def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / PLIST_NAME


def _mac_plist_content() -> str:
    # 路径/参数做 XML 转义再拼进 plist——解释器或仓库路径
    # 含 < / & / 引号时会破坏 XML（launchctl 解析失败 = 自启静默不生效）。
    from xml.sax.saxutils import escape as _xesc

    args = "".join(f"<string>{_xesc(str(p))}</string>"
                   for p in _daemon_command())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.experientia.daemon</string>
    <key>ProgramArguments</key>
    <array>{args}</array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>{_xesc("/tmp/experientia-daemon.log")}</string>
    <key>StandardErrorPath</key><string>{_xesc("/tmp/experientia-daemon.err")}</string>
</dict>
</plist>
"""


def _mac_enable() -> None:
    p = _mac_plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_mac_plist_content(), encoding="utf-8")
    subprocess.run(["launchctl", "unload", str(p)], capture_output=True, timeout=30)
    subprocess.run(["launchctl", "load", "-w", str(p)], check=True, timeout=30)


def _mac_disable() -> None:
    p = _mac_plist_path()
    if p.exists():
        subprocess.run(["launchctl", "unload", str(p)], capture_output=True, timeout=30)
        p.unlink(missing_ok=True)


def _mac_is_enabled() -> bool:
    return _mac_plist_path().exists()


# ---------- Linux：systemd user unit ----------

def _linux_unit_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME",
                               Path.home() / ".config")) / "systemd" / "user" / UNIT_NAME


def _linux_unit_content() -> str:
    cmd = _daemon_command()
    return f"""[Unit]
Description=Experientia headless daemon (experience flywheel)
After=network.target

[Service]
Type=simple
ExecStart={" ".join(_quote_arg(a) for a in cmd)}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def _linux_enable() -> None:
    p = _linux_unit_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_linux_unit_content(), encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"],
                   capture_output=True, timeout=30)
    subprocess.run(["systemctl", "--user", "enable", "--now", UNIT_NAME],
                   check=True, capture_output=True, timeout=30)


def _linux_disable() -> None:
    import logging as _log
    r = subprocess.run(["systemctl", "--user", "disable", "--now", UNIT_NAME],
                       capture_output=True, timeout=30)
    if r.returncode != 0:
        stderr = (r.stderr or b"").decode("utf-8", errors="replace").strip()
        if "not loaded" in stderr.lower() or "没有" in stderr:
            pass  # 服务不存在 = 已卸载，静默忽略
        else:
            _log.getLogger("experientia.autostart").warning(
                "关闭自启（systemctl disable）失败: %s", stderr)
    _linux_unit_path().unlink(missing_ok=True)


def _linux_is_enabled() -> bool:
    return _linux_unit_path().exists()


# ---------- 统一入口 ----------

def enable() -> str:
    if sys.platform.startswith("win"):
        _win_enable()
    elif sys.platform == "darwin":
        _mac_enable()
    elif sys.platform.startswith("linux"):
        _linux_enable()
    else:
        raise RuntimeError("当前平台不支持开机自启")
    return "enabled"


def disable() -> str:
    if sys.platform.startswith("win"):
        _win_disable()
    elif sys.platform == "darwin":
        _mac_disable()
    elif sys.platform.startswith("linux"):
        _linux_disable()
    else:
        raise RuntimeError("当前平台不支持开机自启")
    return "disabled"


def is_enabled() -> bool:
    if sys.platform.startswith("win"):
        try:
            return _win_is_enabled()
        except (OSError, subprocess.SubprocessError):
            return False
    if sys.platform == "darwin":
        return _mac_is_enabled()
    if sys.platform.startswith("linux"):
        return _linux_is_enabled()
    return False
