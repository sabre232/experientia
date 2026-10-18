"""M10：/api/status 热路径 detect() 的进程内 TTL 缓存行为。

缓存是模块级全局，跨测试串味由 conftest 的 autouse fixture 兜底清空。
这里只测 detect() 自身的缓存语义：命中 / 过期 / force 旁路 / 过滤路径 / 返回隔离。
"""

from app.capture import registry


def _patch_all(monkeypatch, counter, make):
    def fake_all():
        counter["n"] += 1
        return make(counter["n"])
    monkeypatch.setattr(registry, "_detect_all", fake_all)
    return counter


def test_cache_hits_within_ttl(monkeypatch):
    """全量 detect() TTL 内复用结果：~21 个 adapter 只 discover 一次。"""
    c = _patch_all(monkeypatch, {"n": 0}, lambda i: {"codex": [i], "cursor": [i]})
    a = registry.detect()
    b = registry.detect()
    assert a == b == {"codex": [1], "cursor": [1]}
    assert c["n"] == 1, "TTL 内第二次调用应命中缓存，不再 discover"


def test_cache_expires_after_ttl(monkeypatch):
    """缓存时间戳早于 TTL 窗口 → 过期重探。"""
    c = _patch_all(monkeypatch, {"n": 0}, lambda i: {"codex": [i]})
    registry.detect()  # 写入一条缓存
    # 把缓存时间戳回拨到 TTL 之前（不依赖墙钟分辨率）
    ts, val = registry._detect_cache
    registry._detect_cache = (ts - registry.DETECT_CACHE_TTL - 1.0, val)
    b = registry.detect()
    assert b == {"codex": [2]}, "过期的缓存应触发重探"
    assert c["n"] == 2


def test_force_bypasses_cache(monkeypatch):
    """force=True 不读缓存也不写缓存（scan_loop 的权威探测走这条）。"""
    c = _patch_all(monkeypatch, {"n": 0}, lambda i: {"codex": [i]})
    a = registry.detect()          # 写缓存
    b = registry.detect(force=True)  # 旁路
    assert a != b, "force=True 应重探而非读缓存"
    assert c["n"] == 2
    # force 的结果不污染缓存：下一次普通调用仍拿到第一次的值
    assert registry.detect() == a


def test_enabled_filter_not_cached(monkeypatch):
    """带 enabled 过滤的路径不读写全量缓存（每次重算，过滤在结果上）。"""
    c = _patch_all(monkeypatch, {"n": 0},
                   lambda i: {"codex": [1], "cursor": [2]})
    a = registry.detect(enabled={"codex"})
    b = registry.detect(enabled={"cursor"})
    assert a == {"codex": [1]}
    assert b == {"cursor": [2]}
    assert c["n"] == 2, "过滤路径每次重算，不吃全量缓存"


def test_cache_returns_top_level_copy(monkeypatch):
    """返回顶层 dict 浅拷贝：调用方注入新 agent 键不污染缓存。"""
    _patch_all(monkeypatch, {"n": 0}, lambda i: {"codex": [1]})
    a = registry.detect()
    a["injected"] = [0]
    assert registry.detect() == {"codex": [1]}


def test_detect_all_isolates_and_logs_adapter_error(monkeypatch, caplog):
    """单个 adapter discover 抛异常：只跳过该 adapter 且必须留痕（ERROR 日志
    含 agent 名与异常信息），其余 adapter 正常返回，不污染结果键。"""
    import logging
    from pathlib import Path

    from app.capture.models import SessionRef

    class _Boom:
        def discover(self):
            raise RuntimeError("boom-模拟探测失败")

    class _Ok:
        def discover(self):
            return [SessionRef(agent="ok-agent", session_id="s1",
                               path=Path("x.jsonl"))]

    monkeypatch.setattr(registry, "REGISTRY",
                        {"bad-agent": _Boom, "ok-agent": _Ok})
    with caplog.at_level(logging.ERROR,
                         logger="experientia.capture.registry"):
        found = registry._detect_all()
    assert "bad-agent" not in found, "出错的 adapter 不得出现在结果里"
    assert set(found) == {"ok-agent"}
    assert len(found["ok-agent"]) == 1
    assert "bad-agent" in caplog.text, "日志必须写明是哪个 agent 出的错"
    assert "boom-模拟探测失败" in caplog.text, "异常信息必须进日志"
