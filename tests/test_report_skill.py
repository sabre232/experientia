"""experientia-report 技能包：生成结构完整 + 现场自检脚本真能跑出“一行结果”。"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys


def _make_sqlite(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.commit()
    conn.close()


def test_package_structure(tmp_path):
    """write_report_skill 生成标准包结构：SKILL.md + scripts/probe.py。"""
    from app.report_skill import SKILL_DIRNAME, write_report_skill

    skill = write_report_skill(tmp_path / "out")
    assert skill.parent.name == SKILL_DIRNAME
    assert (skill.parent / "scripts" / "probe.py").is_file()
    md = skill.read_text(encoding="utf-8")
    assert md.startswith("---")
    assert "name: experientia-report" in md
    assert "## When to Use" in md and "## Procedure" in md


def test_probe_script_runs_and_outputs_one_line(tmp_path):
    """生成的 probe.py 在同机可用 Python 下能现场自检并输出一行结果。

    --path 显式指向一个真实明文 sqlite，绕过候选表：离线时落 EXPERIENTIA_HOME，
    在线（8101 可达）时打印 “已上报 OK”。断言只认这两类终态，不展开细节。
    """
    from app.report_skill import write_report_skill

    skill = write_report_skill(tmp_path / "out")
    probe = skill.parent / "scripts" / "probe.py"
    db = tmp_path / "h" / "state.db"
    _make_sqlite(db)
    env = dict(os.environ)
    env["EXPERIENTIA_HOME"] = str(tmp_path / "exp-home")  # 隔离落盘兜底目录
    r = subprocess.run(
        [sys.executable, str(probe), "--agent", "hermes", "--path", str(db)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                           env={**env, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, f"probe 脚本异常退出: {r.stdout}\n{r.stderr}"
    assert "上报码: " in r.stdout or "已上报 OK" in r.stdout, \
        f"输出契约不符（应只回一行结果）: {r.stdout}"


def test_probe_report_carries_m2_meta(tmp_path):
    """M2：--debug 输出的报告含现场元数据——finder_hash、每条来源所在盘、env。

    从调试 JSON 里断言（忽略其后可能打印的一行结果）。"""
    import json

    from app.report_skill import write_report_skill

    skill = write_report_skill(tmp_path / "out")
    probe = skill.parent / "scripts" / "probe.py"
    db = tmp_path / "h" / "state.db"
    _make_sqlite(db)
    env = dict(os.environ)
    env["EXPERIENTIA_HOME"] = str(tmp_path / "exp-home")
    r = subprocess.run(
        [sys.executable, str(probe), "--agent", "hermes", "--path", str(db),
         "--debug"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                           env={**env, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, r.stderr
    start = r.stdout.find("{")
    end = r.stdout.rfind("}")
    assert start != -1 and end > start, f"debug 输出缺 JSON: {r.stdout[:400]}"
    report = json.loads(r.stdout[start:end + 1])
    assert isinstance(report.get("finder_hash"), str) and len(report["finder_hash"]) == 16
    paths = [s["path"] for s in report["data_sources"]]
    assert str(db) in paths                              # 手动指定路径已纳入
    assert all("drive" in s for s in report["data_sources"])  # 每条来源标所在盘
    assert isinstance(report.get("env"), dict)           # 现场环境（drives/关键 env）
    assert "drives" in report["env"]


def test_probe_discovers_hook_surface_heuristically(tmp_path):
    """通用启发式：候选表之外的 agent 现场探明 hook 配置根 + schema 识别。

    把 home（USERPROFILE/HOME）指到临时目录，隔离真实用户目录；
    表外 agent 名下 .<agent>/settings.json（顶层 hooks 结构）应被发现为 json_hooks。
    """
    import json

    from app.report_skill import write_report_skill

    skill = write_report_skill(tmp_path / "out")
    probe = skill.parent / "scripts" / "probe.py"
    fakehome = tmp_path / "fakehome"
    root = fakehome / ".brandnewagent"
    root.mkdir(parents=True)
    (root / "settings.json").write_text(
        json.dumps({"model": "m", "hooks": {"PreToolUse": []}}), encoding="utf-8")
    env = dict(os.environ)
    env["EXPERIENTIA_HOME"] = str(tmp_path / "exp-home")
    env["HOME"] = str(fakehome)
    env["USERPROFILE"] = str(fakehome)
    for v in ("HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA"):
        env.pop(v, None)
    r = subprocess.run(
        [sys.executable, str(probe), "--agent", "brandnewagent", "--debug"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                           env={**env, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, r.stderr
    start, end = r.stdout.find("{"), r.stdout.rfind("}")
    assert start != -1 and end > start, f"debug 输出缺 JSON: {r.stdout[:400]}"
    report = json.loads(r.stdout[start:end + 1])
    hs = report["hook_surface"]
    assert hs["supported"] is True
    target = str(root / "settings.json")
    assert target in hs["config_paths"]
    fmt = next(f for f in hs["formats"] if f["path"] == target)
    assert fmt["schema"] == "json_hooks"


def test_probe_unknown_agent_prints_guidance(tmp_path):
    """未知名 agent / 默认位置都找不到 → 打印 --path 定位指引，不编造码。"""
    from app.report_skill import write_report_skill

    skill = write_report_skill(tmp_path / "out")
    probe = skill.parent / "scripts" / "probe.py"
    env = dict(os.environ)
    env["EXPERIENTIA_HOME"] = str(tmp_path / "exp-home")
    r = subprocess.run(
        [sys.executable, str(probe), "--agent", "completely-unknown-xyz-2026"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                           env={**env, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 2, r.stdout
    assert "--path" in r.stdout and "未探测到" in r.stdout
