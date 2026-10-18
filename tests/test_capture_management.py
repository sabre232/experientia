"""W2 采集管理：开关过滤 / 持久化 / 黄标冻结（scan 层）+ 本地 API 端点。"""

import pytest

from app.capture.models import Message, Session, SessionRef
from app.store.store import Store
from conftest import local_api_client


# ---------- scan 层：开关过滤 + 黄标冻结 ----------

def _fake_env(tmp_path, monkeypatch, results_box):
    """恒失败（results_box 空 → 解析抛异常）或成功（有 session）的假 agent（照 wave4 模式）。

    注：M4 后"解析成功但返回空"是跳过（新建空文件）而非失败，故"恒失败"必须靠
    parse_sessions 抛异常来表达（格式漂移/读不了），不能再用空返回。"""
    import app.capture.scan as scan_mod

    class FakeAdapter:
        name = "fake"

        def discover(self):
            return []

        def parse(self, ref):
            return None

        def parse_sessions(self, ref):
            s = results_box.get("s")
            if s is not None:
                return [s]
            raise ValueError("恒失败源（格式漂移）")

    f = tmp_path / "data.txt"
    f.write_text("raw", encoding="utf-8")
    ref = SessionRef(agent="fake", session_id="x", path=f, size=1, mtime=0)
    monkeypatch.setattr(scan_mod, "REGISTRY", {"fake": FakeAdapter})
    monkeypatch.setattr(scan_mod, "detect",
                        lambda enabled=None, force=False, min_interval=0.0: {"fake": [ref]})
    return scan_mod


def test_default_all_enabled_behavior_unchanged(tmp_path, monkeypatch):
    """W2-01：无 capture 配置 → 行为与开关引入前完全一致。"""
    store = Store(tmp_path)
    store.ensure_layout()
    box = {"s": Session(agent="fake", session_id="x",
                        messages=[Message(role="user", content="ok")])}
    scan_mod = _fake_env(tmp_path, monkeypatch, box)
    result = scan_mod.run_scan(store, verbose=False)
    assert result.new_sessions == {"fake": 1}
    assert store.load_capture_failures() == {}
    # 第 6 轮：探测到的 agent 集合随扫描落盘（api/capture 只列这些）
    assert store.load_detected_agents() == {"fake"}


def test_disabled_adapter_not_scanned(tmp_path, monkeypatch):
    """W2-01：开关关闭 → 不解析、不落库、不累计黄标。"""
    store = Store(tmp_path)
    store.ensure_layout()
    box = {"s": Session(agent="fake", session_id="x",
                        messages=[Message(role="user", content="ok")])}
    scan_mod = _fake_env(tmp_path, monkeypatch, box)
    store.save_config({"capture": {"enabled": {"fake": False}}})
    result = scan_mod.run_scan(store, verbose=False)
    assert result.new_sessions == {}
    assert result.parse_failures == {}
    assert store.load_capture_state() == {}
    assert store.load_capture_failures() == {}


def test_disabled_flag_freezes_and_resumes(tmp_path, monkeypatch):
    """W2-04：禁用 = 黄标计数冻结（不累加、不清零）；重新启用后继续累计。"""
    store = Store(tmp_path)
    store.ensure_layout()
    box = {}  # 恒失败
    scan_mod = _fake_env(tmp_path, monkeypatch, box)

    for _ in range(3):
        scan_mod.run_scan(store, verbose=False)
    assert store.load_capture_failures() == {"fake": 3}

    store.save_config({"capture": {"enabled": {"fake": False}}})
    for _ in range(3):  # 禁用期间"失败"3 轮 → 计数必须冻结在 3
        scan_mod.run_scan(store, verbose=False)
    assert store.load_capture_failures() == {"fake": 3}

    store.save_config({"capture": {"enabled": {"fake": True}}})
    scan_mod.run_scan(store, verbose=False)
    assert store.load_capture_failures() == {"fake": 4}  # 重新累计


def test_all_disabled_engine_runs_clean(tmp_path, monkeypatch):
    """验收：全禁用 → 引擎正常跑（不解析、不累加黄标、无异常）。"""
    store = Store(tmp_path)
    store.ensure_layout()
    box = {}  # 恒失败源
    scan_mod = _fake_env(tmp_path, monkeypatch, box)
    store.save_config({"capture": {"enabled": {"fake": False}}})
    result = scan_mod.run_scan(store, verbose=False)
    assert result.new_sessions == {}
    assert result.parse_failures == {}
    assert store.load_capture_failures() == {}


def test_stale_clear_still_works_when_disabled(tmp_path, monkeypatch):
    """禁用 ≠ 探测消失：stale-clear 只在 agent 真正不再被探测到时清计数。"""
    store = Store(tmp_path)
    store.ensure_layout()
    box = {}
    scan_mod = _fake_env(tmp_path, monkeypatch, box)
    for _ in range(3):
        scan_mod.run_scan(store, verbose=False)
    assert store.load_capture_failures() == {"fake": 3}

    store.save_config({"capture": {"enabled": {"fake": False}}})
    monkeypatch.setattr(scan_mod, "detect",
                        lambda enabled=None, force=False, min_interval=0.0: {})  # 目录消失
    scan_mod.run_scan(store, verbose=False)
    assert store.load_capture_failures() == {}


# ---------- 本地 API：GET/POST /api/capture ----------

@pytest.fixture
def client(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    return local_api_client(store), store


def test_get_capture_lists_only_real_agents(client):
    """第 6 轮：采集清单只列"实际在跑"的 agent（扫描落盘），不再铺全 REGISTRY。"""
    c, store = client
    r = c.get("/api/capture")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0, "未探测到 agent 时清单应为空（不列纯名字）"
    store.save_detected_agents(["codex", "cursor"])
    body = c.get("/api/capture").json()
    names = [it["name"] for it in body["items"]]
    assert names == ["codex", "cursor"]
    assert body["total"] == 2
    assert body["enabled_count"] == 2
    assert all(it["enabled"] is True for it in body["items"])
    assert all(set(it) == {"name", "enabled", "hits_24h", "last_hit",
                           "yellow_flag", "encrypted"} for it in body["items"])


def test_post_capture_toggles_and_persists(client):
    c, store = client
    store.save_detected_agents(["codex", "cursor"])
    r = c.post("/api/capture", json={"name": "codex", "enabled": False})
    assert r.status_code == 200
    # 持久化到 config.json（重启保持）
    config = store.load_config()
    assert config.get("capture", {}).get("enabled", {}).get("codex") is False
    body = c.get("/api/capture").json()
    codex = next(it for it in body["items"] if it["name"] == "codex")
    assert codex["enabled"] is False
    assert body["enabled_count"] == 1
    # 其他 adapter 不受影响
    assert all(it["enabled"] is True for it in body["items"]
               if it["name"] != "codex")


def test_post_capture_re_enable(client):
    c, store = client
    store.save_detected_agents(["codex", "cursor"])
    c.post("/api/capture", json={"name": "codex", "enabled": False})
    c.post("/api/capture", json={"name": "codex", "enabled": True})
    body = c.get("/api/capture").json()
    codex = next(it for it in body["items"] if it["name"] == "codex")
    assert codex["enabled"] is True
    assert body["enabled_count"] == 2


def test_post_capture_unknown_adapter_404(client):
    c, _ = client
    r = c.post("/api/capture", json={"name": "not-an-agent", "enabled": False})
    assert r.status_code == 404
