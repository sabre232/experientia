"""：事件上报通道防伪令牌。

覆盖三层：
- Store.hook_ingest_token()：一次生成、跨实例稳定、按数据目录隔离、URL 安全；
- 三家 hook 生成器把令牌写进 ?key=，且幂等识别（_is_ours/_ours_in）不被破坏，
  IDE 重贴会把旧的无令牌条目刷新成带令牌条目（迁移落地）；
- 8101 事件端点校验：正确令牌放行、错误令牌 401、缺令牌放行但限频告警
  （非破坏式：未重贴 hook 的旧安装不断捕获）；/api/status 的 data_dir 仅对
  带有效 Bearer 的调用方回显。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.capture import hermes_hook as hh
from app.capture import hook as hook
from app.capture.hook_plugin import hooks_config
from app.capture import ide_hooks as ih
from app.local_api import create_local_app
from app.store.store import Store
from conftest import TEST_API_TOKEN


# ---------- Store 令牌 ----------

def _store(tmp_path):
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


def test_hook_ingest_token_stable_and_persisted(tmp_path):
    st = _store(tmp_path)
    tok = st.hook_ingest_token()
    assert tok and st.hook_ingest_token() == tok  # 幂等
    # 落盘且重启后同值（另一 Store 实例读同一数据目录）
    assert (st.data_dir / Store.HOOK_TOKEN_FILE).is_file()
    assert Store(tmp_path / "data").hook_ingest_token() == tok
    # URL 安全：不含需要转义的字符，可直接拼进 ?key=
    assert set(tok) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def test_hook_ingest_token_isolated_per_data_dir(tmp_path):
    a = _store(tmp_path / "a")
    b = _store(tmp_path / "b")
    assert a.hook_ingest_token() != b.hook_ingest_token()


def test_hook_ingest_token_concurrent_single_value(tmp_path):
    import threading

    st = _store(tmp_path)
    seen: list[str] = []
    lock = threading.Lock()

    def worker():
        v = st.hook_ingest_token()
        with lock:
            seen.append(v)

    ts = [threading.Thread(target=worker) for _ in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(set(seen)) == 1


# ---------- 生成器带 ?key= 且不破坏幂等识别 ----------

def test_hook_command_carries_key_and_still_detected():
    cmd = hook.hook_command("stop", key="SECRET123")
    assert "?key=SECRET123" in cmd
    assert hook._is_ours(cmd, hook.LOCAL_API_PORT)  # 幂等识别仍成立
    # 不带 key：URL 干净（旧测试/展示口径不变）
    assert "?key=" not in hook.hook_command("stop")


def test_apply_hook_config_writes_key(tmp_path):
    p = tmp_path / "settings.json"
    hook.apply_hook_config(p, key="ABC")
    data = json.loads(p.read_text(encoding="utf-8"))
    all_cmds = [h["command"] for ev in data["hooks"].values()
                for m in ev for h in m["hooks"]]
    assert all_cmds and all("?key=ABC" in c for c in all_cmds)


def test_ide_apply_writes_key_and_refreshes_on_reapply(tmp_path):
    p = tmp_path / "hooks.json"
    ih.apply_config("cursor", p, key="K1")
    txt = json.dumps(json.loads(p.read_text(encoding="utf-8")))
    assert "?key=K1" in txt
    # 重贴换新令牌：旧无/带令牌的自己条目被刷新成最新一条，不叠加
    ih.apply_config("cursor", p, key="K2")
    data = json.loads(p.read_text(encoding="utf-8"))
    ev = data["hooks"]["sessionStart"]
    ours = [x for x in ev if ih._ours_in(x, "cursor-event")]
    assert len(ours) == 1 and "?key=K2" in ours[0]["command"]
    assert "key=K1" not in json.dumps(data)


def test_ide_preserves_user_entries_when_refreshing(tmp_path):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"stop": [{"command": "echo mine", "type": "command"}]},
    }), encoding="utf-8")
    ih.apply_config("cursor", p, key="KX")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert any("echo mine" in str(x.get("command")) for x in data["hooks"]["stop"])


def test_hermes_handler_url_carries_key(tmp_path):
    home = tmp_path / "hermes"
    d = hh.write_hook(home, key="HK")
    handler = (d / "handler.py").read_text(encoding="utf-8")
    assert "?key=HK" in handler
    # 无 key：默认上报 URL 与 HOOK_URL 完全一致（向后兼容既有断言）
    assert hh.hermes_event_url() == hh.HOOK_URL
    d2 = hh.write_hook(tmp_path / "h2")
    assert f'"{hh.HOOK_URL}"' in (d2 / "handler.py").read_text(encoding="utf-8")


def test_plugin_http_url_carries_key():
    h = hooks_config(key="PK")["hooks"]
    urls = [inner["url"] for ev in h.values() for inner in ev[0]["hooks"]]
    assert urls and all("?key=PK" in u for u in urls)
    # 无 key：干净 URL
    plain = hooks_config()["hooks"]
    assert all("?key=" not in inner["url"]
               for ev in plain.values() for inner in ev[0]["hooks"])


# ---------- 8101 事件端点校验 ----------

def _client(tmp_path):
    st = _store(tmp_path)
    return st, TestClient(create_local_app(st, api_token=TEST_API_TOKEN))


def test_event_endpoint_correct_key_passes(tmp_path):
    st, client = _client(tmp_path)
    tok = st.hook_ingest_token()
    r = client.post("/api/hooks/cursor-event", params={"key": tok},
                    json={"hook_event_name": "stop"})
    assert r.status_code == 200
    assert "cursor:stop" in st.load_hook_observed()


def test_event_endpoint_wrong_key_rejected(tmp_path):
    st, client = _client(tmp_path)
    for path in ("/api/hooks/cursor-event", "/api/hooks/stop",
                 "/api/hooks/hermes-event", "/api/hooks/post-tool-use"):
        r = client.post(path, params={"key": "not-my-token"}, json={})
        assert r.status_code == 401, path


def test_event_endpoint_missing_key_still_open(tmp_path):
    """非破坏式迁移：缺令牌放行（旧安装未重贴 hook 前不断捕获）。"""
    st, client = _client(tmp_path)
    r = client.post("/api/hooks/cursor-event", json={"hook_event_name": "stop"})
    assert r.status_code == 200
    assert "cursor:stop" in st.load_hook_observed()


def test_event_endpoint_missing_key_warns_once(tmp_path, caplog):
    import logging

    st, client = _client(tmp_path)
    with caplog.at_level(logging.WARNING, logger="experientia.local_api"):
        client.post("/api/hooks/stop", json={})
        client.post("/api/hooks/stop", json={})  # 60s 内不重复刷屏
    warns = [rec for rec in caplog.records
             if "未带防伪令牌" in rec.getMessage()]
    assert len(warns) == 1


def test_protected_and_exempt_paths_unchanged(tmp_path):
    """写端点仍要 Bearer；config 状态仍免鉴权。"""
    st, client = _client(tmp_path)
    assert client.post("/api/hooks/apply", json={}).status_code == 401
    assert client.get("/api/hooks/config").status_code == 200
    auth = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
    assert client.post("/api/hooks/apply", headers=auth).status_code == 200


# ---------- /api/status 的 data_dir 门控 ----------

def test_status_data_dir_only_for_authenticated(tmp_path):
    st = _store(tmp_path)
    app = create_local_app(st, api_token=TEST_API_TOKEN)
    authed = TestClient(app)
    authed.headers["Authorization"] = f"Bearer {TEST_API_TOKEN}"
    bare = TestClient(app)

    body = authed.get("/api/status").json()
    assert body["data_dir"] == str(st.data_dir)

    anon = bare.get("/api/status")
    assert anon.status_code == 200            # 探活端点整体仍免鉴权
    assert anon.json()["version"]
    assert "data_dir" not in anon.json()      # 但未鉴权拿不到绝对路径
    assert "data_dir_fallback" not in anon.json()


def test_status_lite_probe_still_200_without_token(tmp_path):
    st = _store(tmp_path)
    bare = TestClient(create_local_app(st, api_token=TEST_API_TOKEN))
    r = bare.get("/api/status", params={"lite": 1})
    assert r.status_code == 200
    assert "data_dir" not in r.json()
