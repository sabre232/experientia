"""Skill 自报吸收链路测试（总方案 S2）：report 校验 / 上报码 / run_incoming / apply_code。"""

import sqlite3

import pytest

from app.capture import probe as probe_ch
from app.capture.adapters.hermes import _home as _hermes_home  # noqa: F401 (确保注册表加载)
from app.store.store import Store


@pytest.fixture
def store(tmp_path):
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


def _make_sqlite(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.commit()
    conn.close()


def _hermes_report(db_path, agent="hermes"):
    return {
        "report_version": 1,
        "agent": agent,
        "agent_version": "1.2.3",
        "at": "2026-09-05T10:00:00Z",
        "data_sources": [
            {"kind": "sessions", "path": str(db_path),
             "format": "plaintext_sqlite", "note": "state.db"},
        ],
        "hook_surface": {"supported": False, "ecosystem": "unknown", "config_paths": []},
    }


def test_validate_ok_and_invalid(tmp_path):
    db = tmp_path / "h" / "state.db"
    _make_sqlite(db)
    r = probe_ch.validate_report(_hermes_report(db))
    assert r is not None and r["agent"] == "hermes"
    assert r["data_sources"][0]["format"] == "plaintext_sqlite"

    # 路径不存在 → 拒绝
    bad = _hermes_report(tmp_path / "nope" / "state.db")
    assert probe_ch.validate_report(bad) is None

    # 声称明文 SQLite 但实为假头 → 拒绝
    fake = tmp_path / "h" / "fake.db"
    fake.write_bytes(b"NOTSQLITE" + b"\x00" * 4000)
    assert probe_ch.validate_report(_hermes_report(fake)) is None

    # agent 为空 → 拒绝
    r = dict(_hermes_report(db))
    r["agent"] = ""
    assert probe_ch.validate_report(r) is None


def test_validate_keeps_hook_formats(tmp_path):
    """hook_surface.formats 校验保留：只收已存在的 config_paths + 合法 schema（防注入）。"""
    db = tmp_path / "h" / "state.db"
    _make_sqlite(db)
    hooks = tmp_path / "h" / "hooks.json"
    hooks.write_text("{}", encoding="utf-8")
    raw = _hermes_report(db)
    raw["hook_surface"] = {"supported": True, "ecosystem": "hermes",
                           "config_paths": [str(hooks)],
                           "writable_paths": [str(hooks)],
                           "already_injected": False,
                           "formats": [
                               {"path": str(hooks), "schema": "json_hooks"},
                               {"path": "C:/fake/nonexistent.json", "schema": "json_hooks"},
                               {"path": str(hooks), "schema": "evil-schema"},
                               "not-a-dict",
                           ]}
    r = probe_ch.validate_report(raw)
    assert r is not None
    assert r["hook_surface"]["formats"] == [
        {"path": str(hooks), "schema": "json_hooks"}]


def test_code_roundtrip_and_tamper():
    code = probe_ch.make_code("hermes")
    info = probe_ch.decode_code(code)
    assert info is not None and info["agent"] == "hermes" and info["slug"] == "HMS"
    assert len(info["report_id"]) == 8
    # 篡改（任一字符）→ 解码失败
    assert probe_ch.decode_code(code[:-1] + ("0" if code[-1] != "0" else "1")) is None
    assert probe_ch.decode_code("") is None
    assert probe_ch.decode_code("NOT-A-CODE") is None


def test_run_incoming_absorbs_and_self_reported(store, tmp_path):
    db = tmp_path / "h" / "state.db"
    _make_sqlite(db)
    code = probe_ch.make_code("hermes")
    store.save_incoming_report(code, _hermes_report(db))
    assert probe_ch.run_incoming(store) == 1
    # 已吸收并删除；self_reported 落盘；hermes 已被扫描覆盖 → scan_covered
    assert store.list_incoming_codes() == []
    reported = store.load_self_reported()
    assert "hermes" in reported and reported["hermes"]["mode"] == "scan_covered"
    assert "无需 skill" in reported["hermes"]["note"]


def test_run_incoming_drops_invalid(store, tmp_path):
    code = probe_ch.make_code("trae")
    store.save_incoming_report(code, {"report_version": 1, "agent": "trae",
                                      "data_sources": [{"path": "C:/nope/x.db",
                                                        "format": "encrypted"}]})
    assert probe_ch.run_incoming(store) == 0
    assert store.list_incoming_codes() == []  # 无效报告被清理防堆积


def test_report_only_for_unknown_agent(store, tmp_path):
    txt = tmp_path / "t.log"
    txt.write_text("line\n", encoding="utf-8")
    code = probe_ch.make_code("mystery-x")
    store.save_incoming_report(code, {
        "report_version": 1, "agent": "mystery-x", "data_sources": [
            {"path": str(txt), "format": "plaintext"}]})
    assert probe_ch.run_incoming(store) == 1
    mode = store.load_self_reported()["mystery-x"]["mode"]
    assert mode == "report_only"


def test_apply_code_end_to_end(store, tmp_path):
    db = tmp_path / "h" / "state.db"
    _make_sqlite(db)
    code = probe_ch.make_code("hermes")
    store.save_incoming_report(code, _hermes_report(db))
    res = probe_ch.apply_code(store, code)
    assert res["ok"] is True and res["status"]["mode"] == "scan_covered"
    # 二次 apply（文件已被删）→ 明确提示"未收到数据"
    res = probe_ch.apply_code(store, code)
    assert res["ok"] is False and "未收到" in res["error"]


def test_local_api_probe_endpoints(store, tmp_path):
    """8101 端到端：agent 直传 /api/probe → connect 页 /api/probe/apply 粘贴码吸收。"""
    from fastapi.testclient import TestClient

    from app.local_api import create_local_app

    from conftest import TEST_API_TOKEN

    db = tmp_path / "h" / "state.db"
    _make_sqlite(db)
    client = TestClient(create_local_app(store, api_token=TEST_API_TOKEN))
    auth = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
    resp = client.post("/api/probe", json=_hermes_report(db))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and "code" in body
    code = body["code"]
    # 报告已按码落盘
    assert store.load_incoming_report(code) is not None
    # 粘贴码吸收（写端点需 token）→ scan_covered（hermes 已被扫描覆盖，无需 skill）
    rr = client.post("/api/probe/apply", json={"code": code}, headers=auth)
    assert rr.status_code == 200
    assert rr.json()["ok"] is True
    assert rr.json()["status"]["mode"] == "scan_covered"
    assert store.list_incoming_codes() == []


# ---------- M2：现场元数据（env/盘符/注入可写性/finder_hash）清洗透传 ----------


def test_key_hook_state_and_mark(store, tmp_path):
    """后端兜底查重辅助：key_hook_state 读最新钥匙注入面状态；注入成功后
    mark_key_hook_injected 回写 already_injected（幂等）；无钥匙 agent 不拦截。"""
    db = tmp_path / "h" / "state.db"
    hooks = tmp_path / "h" / "hooks.json"
    _make_sqlite(db)
    hooks.write_text("{}", encoding="utf-8")
    raw = _hermes_report(db)
    raw["hook_surface"] = {"supported": True, "ecosystem": "hermes",
                           "config_paths": [str(hooks)],
                           "writable_paths": [str(hooks)],
                           "already_injected": False}
    code = probe_ch.make_code("hermes")
    store.save_incoming_report(code, raw)
    assert probe_ch.run_incoming(store) == 1

    st = probe_ch.key_hook_state(store, "hermes")
    assert st == {"already_injected": False, "writable": 1, "supported": True}
    assert probe_ch.mark_key_hook_injected(store, "hermes") is True
    assert probe_ch.key_hook_state(store, "hermes")["already_injected"] is True
    assert probe_ch.mark_key_hook_injected(store, "hermes") is True  # 幂等

    assert probe_ch.key_hook_state(store, "no-such-agent") is None
    assert probe_ch.mark_key_hook_injected(store, "no-such-agent") is False


def test_admin_install_skips_when_key_already_injected(store, tmp_path):
    """/api/hooks/admin/install 后端兜底：钥匙已确认注入 → 幂等跳过，不再写盘。"""
    from fastapi.testclient import TestClient

    from app.local_api import create_local_app

    from conftest import TEST_API_TOKEN

    db = tmp_path / "h" / "state.db"
    hooks = tmp_path / "h" / "hooks.json"
    _make_sqlite(db)
    hooks.write_text("{}", encoding="utf-8")
    raw = _hermes_report(db)
    raw["hook_surface"] = {"supported": True, "ecosystem": "hermes",
                           "config_paths": [str(hooks)],
                           "writable_paths": [str(hooks)],
                           "already_injected": True}
    code = probe_ch.make_code("hermes")
    store.save_incoming_report(code, raw)
    assert probe_ch.run_incoming(store) == 1

    client = TestClient(create_local_app(store, api_token=TEST_API_TOKEN))
    auth = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
    r = client.post("/api/hooks/admin/install", json={"agent": "hermes"},
                    headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True and body.get("already") is True
    assert "查重" in body.get("note", "")


def test_probe_key_delete_endpoint(store, tmp_path):
    """DELETE /api/probe/keys/{code}：删历史明细（keys/），不影响其它状态文件。"""
    from fastapi.testclient import TestClient

    from app.local_api import create_local_app

    from conftest import TEST_API_TOKEN

    db = tmp_path / "h" / "state.db"
    _make_sqlite(db)
    raw = _hermes_report(db)
    raw["hook_surface"] = {"supported": False, "ecosystem": "unknown",
                           "config_paths": []}
    code = probe_ch.make_code("hermes")
    store.save_incoming_report(code, raw)
    assert probe_ch.run_incoming(store) == 1
    assert store.load_key_manifest(code) is not None

    client = TestClient(create_local_app(store, api_token=TEST_API_TOKEN))
    auth = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
    r = client.delete(f"/api/probe/keys/{code}", headers=auth)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert store.load_key_manifest(code) is None
    # 不存在的合法码 → 幂等返回 ok（不报错）
    assert client.delete(f"/api/probe/keys/{probe_ch.make_code('cursor')}",
                         headers=auth).json()["ok"] is True


def test_validate_meta_fields(tmp_path):
    """validate_report 透传并清洗 M2 新字段：env 白名单 + 单字母盘符、
    来源 drive、注入点可写性 + already_injected、finder_hash；坏数据清成 None/空。"""
    db = tmp_path / "h" / "state.db"
    hooks = tmp_path / "h" / "hooks.json"
    _make_sqlite(db)
    hooks.write_text('{"hooks":[{"type":"EventSubscription","matcher":"experientia"}]}',
                     encoding="utf-8")

    raw = _hermes_report(db)
    raw["report_version"] = 2
    raw["env"] = {"os": "nt", "drives": ["C", "AB", "d"], "home": "C:/Users/x"}
    raw["finder_hash"] = "AABBCCDDEEFF0011"
    raw["data_sources"][0]["drive"] = "c"
    raw["hook_surface"] = {"supported": True, "ecosystem": "hermes",
                           "config_paths": [str(hooks)],
                           "writable_paths": [str(hooks)],
                           "already_injected": True}
    r = probe_ch.validate_report(raw)
    assert r is not None
    assert r["env"]["drives"] == ["C", "D"]
    assert r["env"]["home"] == "C:/Users/x"
    assert r["finder_hash"] == "AABBCCDDEEFF0011"
    assert r["data_sources"][0]["drive"] == "C"
    assert r["hook_surface"]["writable_paths"] == [str(hooks)]
    assert r["hook_surface"]["already_injected"] is True

    # 坏指纹 / 非法 env / 超集盘符 → 清洗成 None
    raw2 = dict(_hermes_report(db))
    raw2["finder_hash"] = "bad!"
    raw2["env"] = {"os": 3, "drives": [""]}
    r2 = probe_ch.validate_report(raw2)
    assert r2["finder_hash"] is None and r2["env"] is None


# ---------- 钥匙（Keys：吸收后明细落库 + 通道激活 → 常态化捕获） ----------


def test_key_manifest_channel_and_merge(store, tmp_path):
    """吸收一份可扫明文自报后：① keys 明细全量落库不丢；② 捕获通道激活；
    ③ detect 合并函数把该来源变成扫描 ref（同机场景下常态化捕获的入口）。"""
    from app.capture.registry import merge_channel_refs

    db = tmp_path / "h" / "state.db"
    _make_sqlite(db)
    code = probe_ch.make_code("hermes")
    store.save_incoming_report(code, _hermes_report(db))
    assert probe_ch.run_incoming(store) == 1
    # ① Keys 明细落库（完整接入情报，不再“吸收即丢”）
    m = store.load_key_manifest(code)
    assert m is not None
    assert m["agent"] == "hermes" and m["mode"] == "scan_covered"
    assert m["report"]["data_sources"][0]["path"] == str(db)
    # ② 捕获通道激活（可扫明文并入 scan 通道）
    ch = store.load_capture_channels()
    assert ch["hermes"]["mode"] == "scan_covered"
    assert str(db) in {s["path"] for s in ch["hermes"]["sources"]}
    # ③ detect 合并：REGISTRY agent 的钥匙来源成为扫描 ref
    merged = merge_channel_refs({}, ch)
    assert any(r.agent == "hermes" and str(r.path) == str(db)
               for r in merged.get("hermes", []))


def test_merge_channels_skips_unregistered_and_missing(tmp_path):
    """通道合并只认 REGISTRY 内 agent + 当轮仍存在的文件：
    未知生态（无解析器）与已消失路径都不并入，避免无谓解析/黄标噪音。"""
    from app.capture.registry import merge_channel_refs

    db = tmp_path / "h" / "state.db"
    _make_sqlite(db)
    channels = {
        "mystery-x": {"mode": "scan_covered", "sources": [{"path": str(db)}]},
        "hermes": {"mode": "scan_covered",
                   "sources": [{"path": str(tmp_path / "gone" / "x.jsonl")}]},
    }
    assert merge_channel_refs({}, channels) == {}


def test_probe_keys_endpoint(store, tmp_path):
    """已吸收钥匙可经 /api/probe/keys 回读（连接页“收到的钥匙”入口的读取侧）。"""
    from fastapi.testclient import TestClient

    from app.local_api import create_local_app

    from conftest import TEST_API_TOKEN

    db = tmp_path / "h" / "state.db"
    _make_sqlite(db)
    code = probe_ch.make_code("hermes")
    store.save_incoming_report(code, _hermes_report(db))
    assert probe_ch.apply_code(store, code)["ok"] is True

    client = TestClient(create_local_app(store, api_token=TEST_API_TOKEN))
    auth = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
    r = client.get("/api/probe/keys", headers=auth)
    assert r.status_code == 200
    keys = r.json()["keys"]
    assert any(k["code"] == code and k["agent"] == "hermes"
               for k in keys)


def test_probe_keys_hook_summary(store, tmp_path):
    """keys 头部带 hook 注入面摘要（M2 元数据 → 查重 + 一键接入判定）。"""
    from fastapi.testclient import TestClient

    from app.local_api import create_local_app

    from conftest import TEST_API_TOKEN

    db = tmp_path / "h" / "state.db"
    hooks = tmp_path / "h" / "hooks.json"
    _make_sqlite(db)
    hooks.write_text("{}", encoding="utf-8")
    raw = _hermes_report(db)
    raw["hook_surface"] = {"supported": True, "ecosystem": "hermes",
                           "config_paths": [str(hooks)],
                           "writable_paths": [str(hooks)],
                           "already_injected": False}
    code = probe_ch.make_code("hermes")
    store.save_incoming_report(code, raw)
    assert probe_ch.apply_code(store, code)["ok"] is True

    client = TestClient(create_local_app(store, api_token=TEST_API_TOKEN))
    auth = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
    r = client.get("/api/probe/keys", headers=auth)
    item = next(k for k in r.json()["keys"] if k["code"] == code)
    assert item["hook"] == {"supported": True, "writable": 1,
                            "already_injected": False,
                            "installer_supported": True}
