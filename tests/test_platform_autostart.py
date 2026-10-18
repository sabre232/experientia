"""开机自启：三平台注册（win schtasks / macos launchd / linux systemd）。

原随 Phase 7 更新检查一起测试；更新检查链路已于整块移除，自启保留。
"""

from app.platform import autostart


def test_autostart_windows_schtasks(monkeypatch):
    calls = []
    monkeypatch.setattr(autostart.sys, "platform", "win32")
    monkeypatch.setattr(autostart.shutil, "which", lambda n: "schtasks.exe")
    monkeypatch.setattr(autostart.subprocess, "run",
                        lambda args, **k: calls.append(args) or type("R", (), {"returncode": 0})())
    autostart.enable()
    assert any("/Create" in a for a in calls)
    autostart.disable()
    assert any("/Delete" in a for a in calls)


def test_autostart_macos_launchd(monkeypatch, tmp_path):
    calls = []
    home = tmp_path / "home"
    monkeypatch.setattr(autostart.sys, "platform", "darwin")
    monkeypatch.setattr(autostart.Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(autostart.subprocess, "run",
                        lambda args, **k: calls.append(args))
    autostart.enable()
    plist = home / "Library" / "LaunchAgents" / autostart.PLIST_NAME
    assert plist.exists()
    assert "com.experientia.daemon" in plist.read_text(encoding="utf-8")
    assert any("launchctl" in " ".join(a) for a in calls)
    autostart.disable()
    assert not plist.exists()


def test_autostart_linux_systemd(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    monkeypatch.setattr(autostart.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    class _MockProc:
        returncode = 0
        stdout = b""
        stderr = b""
    monkeypatch.setattr(autostart.subprocess, "run",
                        lambda args, **k: _MockProc())
    autostart.enable()
    unit = cfg / "systemd" / "user" / autostart.UNIT_NAME
    assert unit.exists()
    assert "[Service]" in unit.read_text(encoding="utf-8")
    assert autostart.is_enabled()
    autostart.disable()
    assert not autostart.is_enabled()
