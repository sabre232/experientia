"""rewrite.explain_experience「讲人话」护栏（小白友好 · 第三步）。

覆盖：无模型降级、首次生成+缓存、命中缓存零模型成本、解析失败抛错、
not_found。模型调用 monkeypatch，不依赖真模型。
"""
import json

import pytest

from app.distill import llm, rewrite
from app.store.store import Store


def _store(tmp_path) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    return s


def _seed(store, **over):
    rec = {"task": "构建前端", "state": "ModuleNotFoundError: no module named vite",
           "action": "先装依赖再构建", "outcome": "构建通过", "importance": 8,
           "g_source": "auto", "agent": "codex", "trunk": "编程", "category": "构建"}
    rec.update(over)
    return store.append_experience(rec)


def test_explain_no_model(monkeypatch, tmp_path):
    store = _store(tmp_path)
    exp = _seed(store)
    monkeypatch.setattr(llm, "model_available", lambda *a, **k: False)
    r = rewrite.explain_experience(store, exp["id"])
    assert r["status"] == "no_model"


def test_explain_not_found(tmp_path):
    store = _store(tmp_path)
    assert rewrite.explain_experience(store, "nope")["status"] == "not_found"


def test_explain_generates_and_caches(monkeypatch, tmp_path):
    store = _store(tmp_path)
    exp = _seed(store)
    calls = {"n": 0}

    def fake(store_, messages, **kw):
        calls["n"] += 1
        return json.dumps({"explain": "缺了构建工具，先装再生成",
                           "advice": "开工前先确认依赖装齐"}, ensure_ascii=False)
    monkeypatch.setattr(llm, "model_available", lambda *a, **k: True)
    monkeypatch.setattr(llm, "call_model", fake)
    r = rewrite.explain_experience(store, exp["id"], lang="zh")
    assert r["status"] == "ok" and r["cached"] is False
    assert "装" in r["explain"] and "依赖" in r["advice"]
    # 缓存落到记录上
    assert store.find_experience(exp["id"])["explain"]
    # 再点命中缓存：模型不再被调用
    r2 = rewrite.explain_experience(store, exp["id"], lang="zh")
    assert r2["cached"] is True and calls["n"] == 1


def test_explain_parse_fail_raises(monkeypatch, tmp_path):
    store = _store(tmp_path)
    exp = _seed(store)
    monkeypatch.setattr(llm, "model_available", lambda *a, **k: True)
    monkeypatch.setattr(llm, "call_model", lambda *a, **k: "模型瞎说，没 JSON")
    with pytest.raises(ValueError):
        rewrite.explain_experience(store, exp["id"])


def test_explain_partial_output_raises(monkeypatch, tmp_path):
    # 只有 explain 没 advice → 视为不可用，抛错且不缓存半成品
    store = _store(tmp_path)
    exp = _seed(store)
    monkeypatch.setattr(llm, "model_available", lambda *a, **k: True)
    monkeypatch.setattr(llm, "call_model",
                        lambda *a, **k: json.dumps({"explain": "只有解释"}))
    with pytest.raises(ValueError):
        rewrite.explain_experience(store, exp["id"])
    assert not store.find_experience(exp["id"]).get("explain")
