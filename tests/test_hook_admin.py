"""Agent hook 统一管理后端测试（总方案）。"""

import json

import pytest

from app.capture import hermes_hook as hh
from app.capture import hook_admin as ha
from app.capture import ide_hooks as ide


@pytest.fixture
def cursor_cfg(tmp_path, monkeypatch):
    """Cursor 用户级 hooks.json 指向临时文件，内含一条用户原有 hook。"""
    path = tmp_path / "cursor_hooks.json"
    path.write_text(json.dumps({
        "version": 1,
        "hooks": {"stop": [{"command": "echo user-hook", "type": "command"}]},
    }), encoding="utf-8")
    monkeypatch.setitem(ide.IDES["cursor"], "user_path", path)
    return path


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_list_entries_origins_and_install(tmp_path, monkeypatch, cursor_cfg):
    # 先接入我们的 → 出现 experientia 条目
    ide.apply_config("cursor", cursor_cfg)
    st = ha.list_agent("cursor")
    origins = {e["origin"] for e in st["entries"]}
    assert origins == {"experientia", "user"}
    assert any(e["origin"] == "user" and e["command"] == "echo user-hook"
               for e in st["entries"])
    # 空文件场景 → 无条目不崩（fake home 隔离本地启发式，防本机真装 windsurf 时扫到）
    monkeypatch.setitem(ide.IDES["windsurf"], "user_path", tmp_path / "none.json")
    assert ha.list_agent("windsurf", home=tmp_path / "isohome")["entries"] == []


def test_toggle_edit_delete_cursor(cursor_cfg):
    ide.apply_config("cursor", cursor_cfg)
    st = ha.list_agent("cursor")
    user_id = next(e["id"] for e in st["entries"] if e["origin"] == "user")
    # 逐条禁用我们注入的所有条目（多事件各一条）→ 全部 enabled=False，用户条目保留启用
    while True:
        ours = next((e for e in ha.list_agent("cursor")["entries"]
                     if e["origin"] == "experientia" and e["enabled"]), None)
        if ours is None:
            break
        assert ha.toggle_entry("cursor", ours["id"], enabled=False)["ok"] is True
    after = ha.list_agent("cursor")
    assert all(e["enabled"] is False
               for e in after["entries"] if e["origin"] == "experientia")
    assert any(e["origin"] == "user" and e["command"] == "echo user-hook"
               for e in after["entries"])
    # 重新启用第一条我们的
    dis = next(e for e in after["entries"] if e["origin"] == "experientia")
    assert ha.toggle_entry("cursor", dis["id"], enabled=True)["ok"] is True
    # 修改 user 条目命令
    assert ha.edit_entry("cursor", user_id, {"command": "echo edited",
                                             "type": "command"})["ok"] is True
    data = _read(cursor_cfg)
    assert data["hooks"]["stop"][0]["command"] == "echo edited"
    # 删除 user 条目
    assert ha.delete_entry("cursor", user_id)["removed"] is True
    assert all(e["command"] != "echo edited" for e in ha.list_agent("cursor")["entries"])


def test_remove_ours_keeps_user(cursor_cfg):
    ide.apply_config("cursor", cursor_cfg)
    assert ha.remove_ours("cursor")["ok"] is True
    data = _read(cursor_cfg)
    # 用户条目仍在，我们的没了
    assert data["hooks"] == {"stop": [{"command": "echo user-hook", "type": "command"}]}


def test_hermes_manage(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    # 用户自建一个 hook 目录
    user_dir = home / "hooks" / "my-hook"
    user_dir.mkdir(parents=True)
    (user_dir / "HOOK.yaml").write_text(
        "name: my-hook\nevents:\n  - session:start\n", encoding="utf-8")
    (user_dir / "handler.py").write_text("def handle(*a, **k): return None\n",
                                         encoding="utf-8")
    # 我们的铃响 hook
    hh.write_hook(home)
    st = ha.list_agent("hermes", home)
    by = {e["id"]: e for e in st["entries"]}
    assert "hermes:experientia-event" in by and by["hermes:experientia-event"]["origin"] == "experientia"
    assert by["hermes:my-hook"]["origin"] == "user"
    # 禁用我们的（改名保留），再启用（操作必须带 home，防止落到真实用户目录）
    assert ha.toggle_entry("hermes", "hermes:experientia-event",
                           enabled=False, home=home)["ok"] is True
    assert not (home / "hooks" / "experientia-event" / "handler.py").exists()
    assert ha.toggle_entry("hermes", "hermes:experientia-event",
                           enabled=True, home=home)["ok"] is True
    assert (home / "hooks" / "experientia-event" / "handler.py").exists()
    # 删除用户目录（二次确认由 UI 负责）
    assert ha.delete_entry("hermes", "hermes:my-hook", home=home)["removed"] is True
    assert not user_dir.exists()


def test_hermes_entry_id_traversal_guard(tmp_path):
    """目录型 entry_id 路径穿越门禁。

    `hermes:../..` 这类穿越段曾可直接 rmtree hooks 根目录之外的任意目录。
    """
    home = tmp_path / "hermes"
    secret = tmp_path / "secret"
    secret.mkdir(parents=True)
    (secret / "keep.txt").write_text("x", encoding="utf-8")
    hh.write_hook(home)

    for bad in ("hermes:../..", "hermes:..", "hermes:a/b",
                "hermes:..\\evil", "hermes:", "hermes"):
        r = ha.delete_entry("hermes", bad, home=home)
        assert r.get("ok") is False and "非法条目名" in r.get("error", ""), bad
        r = ha.toggle_entry("hermes", bad, enabled=False, home=home)
        assert r.get("ok") is False and "非法条目名" in r.get("error", ""), bad

    # 穿越目标原样健在，我们的 hook 也不受影响
    assert (secret / "keep.txt").exists()
    assert (home / "hooks" / "experientia-event" / "handler.py").exists()
    # 合法名仍可正常删除
    r = ha.delete_entry("hermes", "hermes:experientia-event", home=home)
    assert r.get("removed") is True
    assert not (home / "hooks" / "experientia-event").exists()


# ---------- 自报发现 + schema 配方门控 ----------

def _fresh_store(tmp_path):
    from app.store.store import Store
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


def _save_key(store, agent, config_paths, formats, writable=None):
    """直接落一把钥匙明细（等价于自报被吸收后的 keys/ 记录）。"""
    from app.capture import probe as probe_ch
    code = probe_ch.make_code(agent)
    store.save_key_manifest(code, {
        "code": code, "at": "2026-09-06T08:00:00Z", "agent": agent,
        "mode": "hook_ready",
        "report": {"agent": agent, "hook_surface": {
            "supported": True, "ecosystem": agent,
            "config_paths": config_paths,
            "writable_paths": writable or config_paths,
            "already_injected": False,
            "formats": formats,
        }},
    })
    return code


def test_self_reported_json_agent_manageable(tmp_path):
    """自报 agent（workbuddy）json_hooks 文件 → 可列出、可禁用/删除（配方门控放行）。"""
    store = _fresh_store(tmp_path)
    cfg = tmp_path / "wb" / "settings.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"model": "x", "hooks": {
        "PreToolUse": [{"command": "echo user-wb-hook"}]}}), encoding="utf-8")
    _save_key(store, "workbuddy", [str(cfg)],
              [{"path": str(cfg), "schema": "json_hooks"}])
    st = ha.list_agent("workbuddy", store=store)
    assert st["source"] == "self_report" and st["exists"] is True
    e = st["entries"][0]
    assert e["origin"] == "user" and e["command"] == "echo user-wb-hook"
    assert ha.toggle_entry("workbuddy", e["id"], enabled=False, store=store)["ok"] is True
    st2 = ha.list_agent("workbuddy", store=store)
    assert st2["entries"][0]["enabled"] is False
    assert ha.delete_entry("workbuddy", st2["entries"][0]["id"],
                           store=store)["removed"] is True
    assert ha.list_agent("workbuddy", store=store)["entries"] == []


def test_toml_agent_readonly_gate(tmp_path):
    """自报 codex 的 TOML hooks.* → 只读列出；写操作被门控拒绝，文件不动。"""
    store = _fresh_store(tmp_path)
    cfg = tmp_path / "codex" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('[model]\nname = "x"\n\n'
                   "[hooks.user-prompt-submit]\ncommand = \"echo codex-hook\"\n",
                   encoding="utf-8")
    _save_key(store, "codex", [str(cfg)],
              [{"path": str(cfg), "schema": "toml_hooks"}])
    st = ha.list_agent("codex", store=store)
    assert st["kind"] == "toml" and st["source"] == "self_report"
    assert st["entries"] and st["entries"][0]["event"] == "user-prompt-submit"
    assert st["entries"][0]["command"] == "echo codex-hook"
    eid = st["entries"][0]["id"]
    with pytest.raises(ValueError, match="TOML"):
        ha.toggle_entry("codex", eid, enabled=False, store=store)
    with pytest.raises(ValueError, match="TOML"):
        ha.delete_entry("codex", eid, store=store)
    assert "hooks.user-prompt-submit" in cfg.read_text(encoding="utf-8")


def test_builtin_priority_and_self_report_fallback(tmp_path, monkeypatch):
    """已知 agent：内置路径存在 → 用内置；内置缺失 → 自报路径兜底。"""
    from app.capture import ide_hooks as ide

    store = _fresh_store(tmp_path)
    fake = tmp_path / "fake" / "hooks.json"
    fake.parent.mkdir(parents=True)
    fake.write_text(json.dumps({"hooks": {"stop": [{"command": "echo fake"}]}}),
                    encoding="utf-8")
    _save_key(store, "cursor", [str(fake)],
              [{"path": str(fake), "schema": "json_hooks"}])
    builtin = tmp_path / "builtin_cursor.json"
    builtin.write_text(json.dumps({"hooks": {"stop": [{"command": "echo builtin"}]}}),
                       encoding="utf-8")
    monkeypatch.setitem(ide.IDES["cursor"], "user_path", builtin)
    st = ha.list_agent("cursor", store=store)
    assert st["source"] == "builtin" and st["path"] == str(builtin)
    # 内置文件没了（自定义配置目录场景）→ 自报兜底
    builtin.unlink()
    st = ha.list_agent("cursor", store=store)
    assert st["source"] == "self_report" and st["path"] == str(fake)
    assert st["entries"][0]["command"] == "echo fake"


def test_unknown_agent_without_self_report_raises(tmp_path):
    store = _fresh_store(tmp_path)
    with pytest.raises(ValueError, match="自报"):
        ha.list_agent("some-new-agent", store=store)
    with pytest.raises(ValueError):
        ha.list_agent("some-new-agent")


def test_overview_includes_self_reported_agents(tmp_path):
    store = _fresh_store(tmp_path)
    cfg = tmp_path / "wb" / "settings.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"hooks": {"stop": [{"command": "echo wb"}]}}),
                   encoding="utf-8")
    _save_key(store, "workbuddy", [str(cfg)],
              [{"path": str(cfg), "schema": "json_hooks"}])
    ov = ha.overview(store=store)
    assert "workbuddy" in ov
    assert ov["workbuddy"]["source"] == "self_report"
    assert ov["workbuddy"]["writable"] is True
    assert ov["workbuddy"]["entries"][0]["command"] == "echo wb"


def test_local_scan_discovers_nested_agent(tmp_path):
    """③级本地启发式：agent 装在本机（无 skill 自报）→ app 扫描发现；嵌套结构自动识别。

    夹具与真实 workbuddy 的 settings.json 同构（command 在 hooks[0].command）。
    """
    fakehome = tmp_path / "fakehome"
    wb = fakehome / ".workbuddy"
    wb.mkdir(parents=True)
    (wb / "settings.json").write_text(json.dumps({
        "sandbox": {"extraAllowWrite": []},
        "hooks": {
            "PreToolUse": [{"matcher": "Write", "hooks": [
                {"type": "command", "command": "node validator.js PreToolUse"}]}],
            "Stop": [{"hooks": [
                {"type": "command", "command": "node validator.js Stop"}]}],
        }}, ensure_ascii=False), encoding="utf-8")
    st = ha.list_agent("workbuddy", home=fakehome)
    assert st["source"] == "local_scan" and st["exists"] is True
    assert st["path"] == str(wb / "settings.json")
    cmds = {e["event"]: e["command"] for e in st["entries"]}
    assert cmds == {"PreToolUse": "node validator.js PreToolUse",
                    "Stop": "node validator.js Stop"}
    assert all(e["origin"] == "user" for e in st["entries"])
    # 禁用（嵌套条目移入保留段不丢）→ 其余字段保留 → 删除
    eid = st["entries"][0]["id"]
    ev0 = st["entries"][0]["event"]
    assert ha.toggle_entry("workbuddy", eid, enabled=False,
                           home=fakehome)["ok"] is True
    data = json.loads((wb / "settings.json").read_text(encoding="utf-8"))
    assert "sandbox" in data and "_experientia_disabled" in data
    st2 = ha.list_agent("workbuddy", home=fakehome)
    disabled = [e for e in st2["entries"] if not e["enabled"]]
    assert len(disabled) == 1 and disabled[0]["event"] == ev0
    assert ha.delete_entry("workbuddy", disabled[0]["id"],
                           home=fakehome)["removed"] is True
    data = json.loads((wb / "settings.json").read_text(encoding="utf-8"))
    assert "_experientia_disabled" not in data  # 保留段空了不残留空键
    # 删掉被禁用的那条后，另一条（Stop）仍在
    st3 = ha.list_agent("workbuddy", home=fakehome)
    assert len(st3["entries"]) == 1 and st3["entries"][0]["event"] == "Stop"
    assert ha.delete_entry("workbuddy", st3["entries"][0]["id"],
                           home=fakehome)["removed"] is True
    assert ha.list_agent("workbuddy", home=fakehome)["entries"] == []


def test_edit_nested_writes_to_inner_command_level(tmp_path):
    """回归：嵌套结构（workbuddy/claude 同族）edit command 必须写到 hooks[0].command，
    不能写到外层 item.command（写外层 = 改了不生效，读通写断）。"""
    fakehome = tmp_path / "fakehome"
    wb = fakehome / ".workbuddy"
    wb.mkdir(parents=True)
    (wb / "settings.json").write_text(json.dumps({
        "hooks": {
            "PreToolUse": [{"matcher": "Write", "hooks": [
                {"type": "command", "command": "node validator.js PreToolUse"}]}],
        }}, ensure_ascii=False), encoding="utf-8")
    eid = "workbuddy:PreToolUse:0"
    assert ha.edit_entry("workbuddy", eid,
                         {"command": "node NEW.js PreToolUse"},
                         home=fakehome)["ok"] is True
    data = json.loads((wb / "settings.json").read_text(encoding="utf-8"))
    item = data["hooks"]["PreToolUse"][0]
    # 内层命令被改写（真正生效的那层）
    assert item["hooks"][0]["command"] == "node NEW.js PreToolUse"
    # 外层不得残留 command 键（写错层的铁证）
    assert "command" not in item
    # 列表读回也是新命令（读写对齐）
    st = ha.list_agent("workbuddy", home=fakehome)
    assert st["entries"][0]["command"] == "node NEW.js PreToolUse"


def test_overview_includes_locally_detected_agent(tmp_path, monkeypatch):
    """overview 纳入本机检测到在跑的 agent（detected_agents.json）→ 启发式发现。"""
    import app.capture.hook_discovery as hd

    store = _fresh_store(tmp_path)
    store.save_detected_agents(["workbuddy"])
    fakehome = tmp_path / "fakehome2"
    wb = fakehome / ".workbuddy"
    wb.mkdir(parents=True)
    (wb / "settings.json").write_text(json.dumps({
        "hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "node v.js Stop"}]}]}}),
        encoding="utf-8")
    monkeypatch.setattr(hd.Path, "home", staticmethod(lambda: fakehome))
    ov = ha.overview(store=store)
    assert "workbuddy" in ov
    assert ov["workbuddy"]["source"] == "local_scan"
    assert ov["workbuddy"]["entries"][0]["command"] == "node v.js Stop"


def test_codex_multi_plugin_files(tmp_path):
    """codex 插件型多配置：各插件 hooks.json 逐文件列条目；删/禁用路由回正确文件。"""
    fakehome = tmp_path / "fakehome"
    base = fakehome / ".codex" / ".tmp" / "plugins" / "plugins"
    for name, hooks in (
        ("figma", {"hooks": {"PostToolUse": [{"matcher": "Write|Edit", "hooks": [
            {"type": "command", "command": "./scripts/post_write_figma_parity_check.sh"}]}]}}),
        ("replayio", {"hooks": {
            "PostToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "./scripts/post_bash_upload.sh"}]}],
            "Stop": [{"hooks": [
                {"type": "command", "command": "./scripts/stop_close_and_upload.sh"}]}]}}),
    ):
        d = base / name
        d.mkdir(parents=True)
        (d / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")
    st = ha.list_agent("codex", home=fakehome)
    assert st["source"] == "local_scan" and st["kind"] == "json"
    cmds = {e["id"]: e["command"] for e in st["entries"]}
    assert len(cmds) == 3
    figma_id = next(i for i in cmds if "figma" in cmds[i])
    replay_stop = next(i for i in cmds if "stop_close" in cmds[i])
    # 删掉第二个文件（replayio）里的 Stop → 第一个文件（figma）不受影响
    assert ha.delete_entry("codex", replay_stop, home=fakehome)["removed"] is True
    figma_file = base / "figma" / "hooks.json"
    replay_file = base / "replayio" / "hooks.json"
    assert "PostToolUse" in json.loads(figma_file.read_text(encoding="utf-8"))["hooks"]
    assert "Stop" not in json.loads(replay_file.read_text(encoding="utf-8"))["hooks"]
    # 禁用第一个文件（figma）里的条目 → 保留段落落在 figma 文件内
    assert ha.toggle_entry("codex", figma_id, enabled=False,
                           home=fakehome)["ok"] is True
    figma_data = json.loads(figma_file.read_text(encoding="utf-8"))
    assert "_experientia_disabled" in figma_data
    assert "PostToolUse" not in figma_data.get("hooks", {})


def test_discovery_scans_beyond_100_subdirs(tmp_path):
    """codex 市场缓存实测 181 个插件目录（replayio 在第 137 位）→ 扫描上限必须覆盖。"""
    import app.capture.hook_discovery as hd

    base = tmp_path / "fakehome" / ".codex" / ".tmp" / "plugins" / "plugins"
    base.mkdir(parents=True)
    for i in range(136):
        (base / f"pad{i:03d}").mkdir()
    tgt = base / "zzz_target"  # 字母序垫底（约第 137 位）
    tgt.mkdir()
    (tgt / "hooks.json").write_text(json.dumps({
        "hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "echo x"}]}]}}), encoding="utf-8")
    found = hd.discover_hooks("codex", tmp_path / "fakehome")
    assert (str(tgt / "hooks.json"), "json_hooks") in found


def test_overview_empty_state_for_detected_agent(tmp_path, monkeypatch):
    """检测到在跑但无 hook 配置 → overview 显式空态（kind=none），不静默消失。"""
    import app.capture.hook_discovery as hd

    store = _fresh_store(tmp_path)
    store.save_detected_agents(["ghostagent"])
    monkeypatch.setattr(hd.Path, "home", staticmethod(
        lambda: tmp_path / "emptyhome"))
    ov = ha.overview(store=store)
    assert "ghostagent" in ov
    assert ov["ghostagent"]["kind"] == "none"
    assert ov["ghostagent"]["entries"] == []


def test_claude_code_full_manage(tmp_path, monkeypatch):
    """claude-code 升级全量管理：嵌套结构原有条目可禁用/删除，其余字段保留。"""
    import app.capture.hook_admin as ha_mod

    settings = tmp_path / "claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"model": "x", "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "echo user-claude-hook"}]}]}}),
        encoding="utf-8")
    monkeypatch.setattr(ha_mod, "_claude_settings", lambda: settings)
    st = ha.list_agent("claude-code")
    assert st["source"] == "builtin"
    e = st["entries"][0]
    assert e["origin"] == "user" and e["command"] == "echo user-claude-hook"
    assert ha.toggle_entry("claude-code", e["id"], enabled=False)["ok"] is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "model" in data and "_experientia_disabled" in data  # 其余字段保留
    st2 = ha.list_agent("claude-code")
    assert st2["entries"][0]["enabled"] is False  # 禁用后仍在列表（不丢）
    assert ha.delete_entry("claude-code", st2["entries"][0]["id"])["removed"] is True
    assert ha.list_agent("claude-code")["entries"] == []


# ---------- add_entry：手动新增一条 hook 条目（2026-09，形状自动探测） ----------

def test_add_entry_flat_cursor(cursor_cfg):
    """cursor（扁平）add → 新条目 {"command":...} 落在 hooks[event]，list 读回一致。"""
    r = ha.add_entry("cursor", "afterAgentResponse", "echo added-flat")
    assert r["ok"] is True and r["added"] is True
    data = _read(cursor_cfg)
    assert data["hooks"]["afterAgentResponse"][-1] == {"command": "echo added-flat"}
    st = ha.list_agent("cursor")
    e = next(x for x in st["entries"] if x["command"] == "echo added-flat")
    assert e["event"] == "afterAgentResponse" and e["origin"] == "user"
    # 原有 user hook 保留（add 不破坏既有条目）
    assert any(x["command"] == "echo user-hook" for x in st["entries"])


def test_add_entry_nested_claude_shape_follows_existing(tmp_path, monkeypatch):
    """claude-code（嵌套）add 新事件 → 形状从既有嵌套条目探测，写 hooks[0].command。"""
    import app.capture.hook_admin as ha_mod

    settings = tmp_path / "claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"model": "x", "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "echo existing"}]}]}}), encoding="utf-8")
    monkeypatch.setattr(ha_mod, "_claude_settings", lambda: settings)
    r = ha.add_entry("claude-code", "PostToolUse", "echo added-nested")
    assert r["ok"] is True and r["event"] == "PostToolUse"
    data = json.loads(settings.read_text(encoding="utf-8"))
    item = data["hooks"]["PostToolUse"][0]
    # 嵌套：命令落在内层 hooks[0].command（真正生效的层），外层不得残留 command
    assert item["hooks"][0]["command"] == "echo added-nested"
    assert "command" not in item
    # 读回一致（读写对齐）
    st = ha.list_agent("claude-code")
    e = next(x for x in st["entries"] if x["command"] == "echo added-nested")
    assert e["event"] == "PostToolUse" and e["origin"] == "user"
    # 既有嵌套条目保留
    assert any(x["command"] == "echo existing" for x in st["entries"])


def test_add_entry_default_flat_when_no_existing(tmp_path, monkeypatch):
    """无既有条目的 cursor 配置 → add 走扁平默认（agent != claude-code）。"""
    import app.capture.ide_hooks as ide

    path = tmp_path / "empty_hooks.json"
    path.write_text(json.dumps({"version": 1, "hooks": {}}), encoding="utf-8")
    monkeypatch.setitem(ide.IDES["cursor"], "user_path", path)
    assert ha.add_entry("cursor", "stop", "echo fresh")["added"] is True
    data = _read(path)
    assert data["hooks"]["stop"] == [{"command": "echo fresh"}]


def test_add_entry_readonly_gate(tmp_path):
    """TOML 型（codex）add → 门控拒绝（配方只读），文件不动。"""
    store = _fresh_store(tmp_path)
    cfg = tmp_path / "codex" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('[model]\nname = "x"\n\n'
                   "[hooks.user-prompt-submit]\ncommand = \"echo codex-hook\"\n",
                   encoding="utf-8")
    _save_key(store, "codex", [str(cfg)],
              [{"path": str(cfg), "schema": "toml_hooks"}])
    with pytest.raises(ValueError, match="TOML"):
        ha.add_entry("codex", "stop", "echo x", store=store)
    assert "hooks.user-prompt-submit" in cfg.read_text(encoding="utf-8")


def test_add_entry_empty_validation():
    """空事件 / 空命令 → ValueError（不写文件）。"""
    with pytest.raises(ValueError):
        ha.add_entry("cursor", "  ", "echo x")
    with pytest.raises(ValueError):
        ha.add_entry("cursor", "stop", "   ")


def test_add_entry_event_name_rejects_yaml_injection(tmp_path):
    """事件名含换行 / # / 超长 → ValueError，不写文件（
    原实现把 event 原样拼进 HOOK.yaml，可向用户 Hermes 配置注入任意 YAML 键）。"""
    home = tmp_path / "hermes"
    hh.write_hook(home)
    for bad in ("agent:end\n  evil: 1", "agent:end # 注释", "a" * 65, "x\ty"):
        with pytest.raises(ValueError):
            ha.add_entry("hermes", bad, "echo x", home=home)


def test_discover_hooks_rejects_unsafe_agent_name(tmp_path):
    """非法 agent 名（路径分量）→ 返回空，不做任何路径拼接（
    name 原样来自 URL，../ 之类可拼出任意目录列举）。"""
    import app.capture.hook_discovery as hd

    (tmp_path / "data-evil").mkdir()
    for bad in ("../data-evil", "..", "a/b", "a\\b", ""):
        assert hd.discover_hooks(bad, tmp_path) == []


def test_add_entry_hook_dir_hermes(tmp_path):
    """hermes（目录型 hook_dir）add → 新建 user-hook-<hex>/{HOOK.yaml,handler.py}，
    读回多一条 origin=user 条目；handler 含命令 + handle 签名；我们的铃响 hook 保留。"""
    home = tmp_path / "hermes"
    hh.write_hook(home)  # 先装我们的铃响 hook（1 条 experientia）
    before = {e["id"] for e in ha.list_agent("hermes", home)["entries"]}
    r = ha.add_entry("hermes", "agent:end", "echo done", home=home)
    assert r["ok"] is True and r["added"] is True
    after = ha.list_agent("hermes", home)["entries"]
    assert len(after) == len(before) + 1
    new = next(e for e in after if e["id"] not in before)
    assert new["origin"] == "user" and new["event"] == "agent:end"
    d = home / "hooks" / new["idx"]
    assert (d / "HOOK.yaml").is_file() and (d / "handler.py").is_file()
    handler = (d / "handler.py").read_text(encoding="utf-8")
    assert "echo done" in handler and "def handle(" in handler
    assert "agent:end" in (d / "HOOK.yaml").read_text(encoding="utf-8")
    assert any(e["id"] == "hermes:experientia-event" for e in after)


def test_add_entry_hook_dir_hermes_command_escaped(tmp_path):
    """hermes add 带特殊字符的命令 → json.dumps 安全嵌入（防注入），handler 仍是合法 Python。"""
    home = tmp_path / "hermes"
    hh.write_hook(home)
    tricky = 'echo "hi"; rm -rf /tmp/x'
    ha.add_entry("hermes", "session:end", tricky, home=home)
    after = ha.list_agent("hermes", home)["entries"]
    new = next(e for e in after if e["id"] != "hermes:experientia-event")
    handler = (home / "hooks" / new["idx"] / "handler.py").read_text(encoding="utf-8")
    # 命令带引号/分号，但被 json.dumps 包成字符串字面量 → handler 仍是合法 Python
    # （若命令能"逃逸"出字符串，这里 compile 会抛 SyntaxError）
    compile(handler, "<handler>", "exec")
