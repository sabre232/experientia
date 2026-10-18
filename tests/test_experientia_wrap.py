"""experientia-wrap 命令包装（路线图 D-1）单测。

只测确定性的 env 注入决策与 CLI 骨架；exec 语义用 monkeypatch 短路，
不真起子进程（os.execvpe 替换进程语义无法在测试进程内安全发生）。
"""

import os

from app import wrap


def test_build_env_claude_code():
    delta, notes = wrap.build_env("claude-code", url="http://127.0.0.1:8100")
    assert delta == {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8100"}
    assert notes and "已注入" in notes[0]


def test_build_env_deepseek_harness_custom_url():
    delta, _ = wrap.build_env("deepseek-harness", url="http://127.0.0.1:9999")
    assert delta == {"DEEPSEEK_BASE_URL": "http://127.0.0.1:9999"}


def test_build_env_unknown_target_no_injection():
    delta, notes = wrap.build_env("cursor")
    assert delta is None
    assert notes and "不适用" in notes[0]


def test_build_env_without_target_no_injection():
    delta, notes = wrap.build_env(None)
    assert delta is None
    assert notes and "未指定" in notes[0]


def test_build_env_extra_overrides():
    delta, _ = wrap.build_env("claude-code", extra={"ANTHROPIC_BASE_URL": "http://x"})
    assert delta["ANTHROPIC_BASE_URL"] == "http://x"


def test_main_no_command_returns_2(capsys):
    assert wrap.main(["--target", "claude-code"]) == 2
    out = capsys.readouterr()
    assert "usage" in out.err


def test_main_exec_injects_env(monkeypatch):
    seen: dict = {}

    def _fake_execvpe(file, args, env):
        seen["env"] = env
        return 0

    monkeypatch.setattr(os, "execvpe", _fake_execvpe)
    rc = wrap.main(["--target", "deepseek-harness", "--", "deepseek"])
    assert rc == 0
    assert seen["env"]["DEEPSEEK_BASE_URL"] == wrap.DEFAULT_PROXY_URL


def test_main_exec_unknown_target_passthrough(monkeypatch):
    seen: dict = {}

    def _fake_execvpe(file, args, env):
        seen["env"] = dict(env)
        return 0

    monkeypatch.setattr(os, "execvpe", _fake_execvpe)
    wrap.main(["--target", "cursor", "--", "code"])
    assert "DEEPSEEK_BASE_URL" not in seen["env"]
    assert "ANTHROPIC_BASE_URL" not in seen["env"]
