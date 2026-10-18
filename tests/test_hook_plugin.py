"""Claude 官方插件包生成（阶段 C：.claude-plugin + hooks/http）。

校验：manifest 字段符合官方 schema（name 必填 kebab-case、路径 ./ 开头）；
hooks.json 与 hook 注册表同构（4 事件 → http hook → /api/hooks slug）；
落盘结构 = .claude-plugin/plugin.json + hooks/hooks.json。
真实装/卸走官方 `claude plugin install/uninstall`，由手动验收覆盖。
"""

import json
from pathlib import Path

from app.capture import hook
from app.capture import hook_plugin as hp

EVENTS = {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"}


def test_manifest_shape():
    m = hp.plugin_manifest()
    assert m["name"] == "experientia"
    assert m["name"] == m["name"].lower().replace("_", "-")  # kebab-case
    assert "version" in m and "displayName" in m and "description" in m
    assert m["hooks"].startswith("./")  # 路径相对插件根


def test_hooks_config_matches_registry():
    h = hp.hooks_config()["hooks"]
    assert set(h) == EVENTS
    # 注册表事件 → /api/hooks slug 一一对应（官方 schema 用 pascal 名，端点为 slug）
    for pascal, endpoint in hook.HOOK_CLIENTS["claude-code"]["events"]:
        entries = h[pascal]
        assert len(entries) == 1
        inner = entries[0]["hooks"][0]
        assert inner["type"] == "http"
        assert inner["url"] == f"http://127.0.0.1:8101/api/hooks/{endpoint}"


def test_write_package_structure(tmp_path):
    target = tmp_path / "plugin-dist"
    root = hp.write_plugin_package(target)
    manifest_p = root / hp.MANIFEST_DIR / "plugin.json"
    hooks_p = root / hp.HOOKS_REL
    assert manifest_p.exists() and hooks_p.exists()
    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert manifest["name"] == "experientia"
    assert manifest["hooks"] == "./hooks/hooks.json"  # 与真实落盘位置一致
    h = json.loads(hooks_p.read_text(encoding="utf-8"))["hooks"]
    assert set(h) == EVENTS
    # 幂等覆盖
    hp.write_plugin_package(target)
    assert manifest_p.exists()


def test_plugin_package_has_no_extra_hook_events_than_registry(tmp_path):
    target = tmp_path / "p"
    hp.write_plugin_package(target)
    events = set(json.loads(
        (target / hp.HOOKS_REL).read_text(encoding="utf-8"))["hooks"])
    assert events <= EVENTS


# ---------- C-2a：本地 API 端点 ----------

def test_api_plugin_generate_endpoint(tmp_path):
    from app.store.store import Store
    from conftest import local_api_client

    s = Store(data_dir=tmp_path / "data")
    s.ensure_layout()
    client = local_api_client(s)
    r = client.post("/api/hooks/plugin/generate").json()
    root = r["dir"]
    assert (Path(root) / hp.MANIFEST_DIR / "plugin.json").is_file()
    assert (Path(root) / hp.HOOKS_REL).is_file()
    assert r["install_hint"].startswith('claude plugin install "')
    # 引擎端路径 = 数据目录 exports/claude-plugin（用户可带走/重生成）
    assert "claude-plugin" in root

