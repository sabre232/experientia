"""GUI API 客户端测试：CachedApi 内存缓存行为（命中 / TTL / 写失效 / 参数键）。

只验证缓存逻辑，不发起真实网络请求：用假 httpx 响应替换 LocalApi 的 client。
"""

from __future__ import annotations

import pytest

from app.gui import api_client
from app.gui.api_client import CachedApi


class _FakeResp:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.text = ""

    def json(self) -> dict:
        return self._payload


class _CountingClient:
    """计数假 client：每次 request 计数并返回固定响应。"""

    def __init__(self, payload: dict):
        self._payload = payload
        self.calls: list[tuple] = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return _FakeResp(self._payload)


@pytest.fixture
def cached_api(monkeypatch) -> CachedApi:
    monkeypatch.setenv("EXPERIENTIA_API_TOKEN", "test-token")
    api = CachedApi()
    api._client = _CountingClient({"ok": True})  # type: ignore[assignment]
    return api


def test_cache_hit_within_ttl(cached_api) -> None:
    """同一 GET 在 TTL 内第二次命中缓存，不再打 client。"""
    assert cached_api._request("GET", "/api/config") == {"ok": True}
    assert cached_api._request("GET", "/api/config") == {"ok": True}
    assert len(cached_api._client.calls) == 1  # type: ignore[attr-defined]


def test_non_cached_path_no_cache(cached_api) -> None:
    """不在 _GET_TTL 白名单的 GET 不缓存。"""
    for _ in range(2):
        cached_api._request("GET", "/api/experiences/xxx")  # 不在白名单
    assert len(cached_api._client.calls) == 2  # type: ignore[attr-defined]


def test_write_invalidates_resource_family(cached_api) -> None:
    """写操作后同资源族缓存失效：config 被 PUT 清掉。"""
    cached_api._request("GET", "/api/config")
    assert len(cached_api._client.calls) == 1  # type: ignore[attr-defined]
    cached_api._request("PUT", "/api/config", json={"locale": "en"})
    cached_api._request("GET", "/api/config")
    assert len(cached_api._client.calls) == 3  # type: ignore[attr-defined]


def test_skills_write_purges_coupled_roots(cached_api) -> None:
    """skills 写（如蒸馏成功）会连带失效 experiences/growth/insights 缓存。"""
    for p in ("/api/skills", "/api/experiences", "/api/growth"):
        cached_api._request("GET", p)
    assert len(cached_api._client.calls) == 3  # type: ignore[attr-defined]
    cached_api._request("POST", "/api/skills/distill", json={})
    for p in ("/api/skills", "/api/experiences", "/api/growth"):
        cached_api._request("GET", p)
    assert len(cached_api._client.calls) == 7  # type: ignore[attr-defined]


def test_params_part_of_cache_key(cached_api) -> None:
    """不同查询参数（如 growth days）使用独立缓存键。"""
    cached_api._request("GET", "/api/growth", params={"days": 30})
    cached_api._request("GET", "/api/growth", params={"days": 7})
    assert len(cached_api._client.calls) == 2  # type: ignore[attr-defined]
    # 再次请求 days=30 命中
    cached_api._request("GET", "/api/growth", params={"days": 30})
    assert len(cached_api._client.calls) == 2  # type: ignore[attr-defined]


def test_wipe_clears_all(cached_api) -> None:
    cached_api._request("GET", "/api/config")
    cached_api._request("POST", "/api/wipe", json={"confirm": "x"})
    cached_api._request("GET", "/api/config")
    assert len(cached_api._client.calls) == 3  # type: ignore[attr-defined]


def test_ttl_expiry(monkeypatch, cached_api) -> None:
    """TTL 过期后重新请求。"""
    cached_api._request("GET", "/api/config")
    assert len(cached_api._client.calls) == 1  # type: ignore[attr-defined]
    ttl = api_client._GET_TTL["/api/config"]
    # 把缓存时间拨回过期
    with cached_api._lock:
        key = cached_api._cache_key("/api/config", None)
        hit = cached_api._cache[key]
        cached_api._cache[key] = (hit[0] - ttl - 1, hit[1])
    cached_api._request("GET", "/api/config")
    assert len(cached_api._client.calls) == 2  # type: ignore[attr-defined]


# ---------- ：写路径缓存失效 ----------

def test_probe_writes_invalidate_status_cache(cached_api) -> None:
    """/api/probe/* 写（apply / ide / hermes）失效 /api/probe/status。"""
    for write in ("POST /api/probe/apply", "POST /api/probe/ide/apply",
                  "POST /api/probe/hermes/apply"):
        method, path = write.split()
        cached_api.clear_cache()  # 上一轮回填的缓存仍在 TTL 内，先清
        cached_api._client.calls.clear()  # type: ignore[attr-defined]
        cached_api._request("GET", "/api/probe/status")
        cached_api._request(method, path, json={})
        cached_api._request("GET", "/api/probe/status")
        assert len(cached_api._client.calls) == 3, write  # type: ignore[attr-defined]


def test_hook_apply_invalidates_hooks_config(cached_api) -> None:
    """/api/hooks/apply 同样无同名 GET 根，必须失效 /api/hooks/config。"""
    cached_api._request("GET", "/api/hooks/config")
    cached_api._request("POST", "/api/hooks/apply")
    cached_api._request("GET", "/api/hooks/config")
    assert len(cached_api._client.calls) == 3  # type: ignore[attr-defined]


def test_experience_draft_adopt_invalidates_experiences(cached_api) -> None:
    """草稿放行后经验列表缓存同步失效（放行 = 新经验入库）。"""
    cached_api._request("GET", "/api/experiences")
    cached_api._request("POST", "/api/experience-drafts/d1/adopt")
    cached_api._request("GET", "/api/experiences")
    assert len(cached_api._client.calls) == 3  # type: ignore[attr-defined]
