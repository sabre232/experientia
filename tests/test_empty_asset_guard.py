"""空资产红线护栏（冒烟抓到的三个真 bug）。

真机现场：本地模型对 1 万字蒸馏提示词返回**空字符串**，旧代码原样收下 →
`parse_playbook("")` 得到三节"（无）" → 写盘、升 version、标 confidence: high、
返回 status: success。结果 playbook 被清空 → 注入块永远为空 → 成长页第④格恒 0，
而所有日志与界面都说"已经整理好了"。

锁三件事：
1. 空完成 = 失败（抛错 + 计入熔断），让既有降级链接住；
2. 模型回了字但三节皆空 = 等同失败，**不写空卡**（起不再落确定性兜底：
   归纳层无模型/无产出一律不产出，宁可诚实地空）；
3. 旧卡有内容时拒绝被空卡覆盖，并如实返回 empty_result；
   另加：growth_summary 的结果缓存签名必须含 injection.log（否则第④格看不见刚发生的回灌）。
"""

from __future__ import annotations

import json

import pytest

from app.distill import engine_curation as ec
from app.distill import llm
from app.store.store import Store

MODEL_CFG = {"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                  "type": "local", "model": "qwen"}},
             "default_model": "local"}

CARD_WITH_BODY = (
    "# 营销 / 文案写作 · playbook\n\n"
    "> name: 投放标题\n> version: 2\n> confidence: medium\n\n"
    "## 标准流程\n1. 确认投放目标\n\n"
    "## 成功要点\n- 利益点前置\n\n"
    "## 失败模式\n- [Solidified] 纯情绪文案点击率低（出现 4 次）\n"
)


def _store(tmp_path, config=None) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    s.save_config(config or {})
    return s


def _seed_experiences(store: Store, n: int = 6) -> None:
    for i in range(n):
        store.append_experience({
            "task": f"投放标题第{i}版", "state": f"点击率偏低 {i}",
            "action": f"利益点前置改写 {i}", "G": 0.4, "g_source": "judge",
            "importance": 7, "agent": "codex", "trunk": "营销",
            "category": "文案写作", "session_id": f"s{i}", "count": 4,
            "seen_in": [f"s{i}a", f"s{i}b", f"s{i}c"]})


# ---------- 1. 空完成 = 失败 ----------

def test_empty_completion_raises_and_is_not_success(tmp_path, monkeypatch):
    from app.distill.llm import EmptyResponseError

    store = _store(tmp_path, MODEL_CFG)
    monkeypatch.setattr(llm, "_call_model_async_impl",
                        lambda *a, **k: _returns(""))
    with pytest.raises(EmptyResponseError):
        llm.call_model(store, [{"role": "user", "content": "x"}])


def test_whitespace_only_completion_also_raises(tmp_path, monkeypatch):
    from app.distill.llm import EmptyResponseError

    store = _store(tmp_path, MODEL_CFG)
    monkeypatch.setattr(llm, "_call_model_async_impl",
                        lambda *a, **k: _returns("   \n  "))
    with pytest.raises(EmptyResponseError):
        llm.call_model(store, [{"role": "user", "content": "x"}])


async def _returns(text: str) -> str:
    return text


# ---------- 2. 模型回了字但三节皆空 → 等同失败，不写空卡 ----------

def test_empty_parse_writes_no_card(tmp_path, monkeypatch):
    """模型回了字但解析不出三节 → empty_result + 盘上没有卡。

     前这里是「落确定性兜底、success」；确定性兜底已删除（假蒸馏），
    护栏语义收缩为**不写空卡 / 不产「（无）」占位**——这条红线本身更强了。
    """
    store = _store(tmp_path, MODEL_CFG)
    _seed_experiences(store)
    monkeypatch.setattr(llm, "call_model", lambda s, msgs, **k: "谢谢，我已收到。")
    r = ec.distill(store, "营销", "文案写作", source="manual", force=True)
    assert r["status"] == "empty_result"
    assert r.get("ok") is False
    assert store.read_skill("营销", "文案写作") is None, \
        "三节解析为空时不应写卡（写了就是空卡占位）"


# ---------- 3. 旧卡有内容时拒绝被空卡覆盖 ----------

def test_refuses_to_collapse_non_empty_card(tmp_path, monkeypatch):
    store = _store(tmp_path, MODEL_CFG)
    store.write_skill("营销", "文案写作", CARD_WITH_BODY)
    _seed_experiences(store)
    # 让模型产不出内容（空产出）。确定性兜底已随删除，无需再打桩。
    monkeypatch.setattr(llm, "call_model", lambda s, msgs, **k: "")
    r = ec.distill(store, "营销", "文案写作", source="manual", force=True)
    assert r["status"] == "empty_result" and r.get("collapsed") is True
    kept = store.read_skill("营销", "文案写作") or ""
    assert "纯情绪文案点击率低" in kept, "旧卡内容被空卡覆盖了"


# ---------- 4. 空卡不许顶着 high ----------

def test_empty_result_leaves_no_card_to_mislabel(tmp_path, monkeypatch):
    """空产出不再写卡，「空卡标 high」这条就无从发生——卡根本不存在。

     前：空卡被写出且 confidence 降为 low（事后补救）。
     后：空产出直接不落盘，源头就没有可被误标 high 的空卡。
    """
    store = _store(tmp_path, MODEL_CFG)
    _seed_experiences(store)
    monkeypatch.setattr(llm, "call_model", lambda s, msgs, **k: "")
    ec.distill(store, "营销", "文案写作", source="manual", force=True)
    assert store.read_skill("营销", "文案写作") is None, \
        "空产出不应留下任何卡（confidence 也就没有了载体）"


# ---------- 5. 第④格缓存必须看见刚发生的回灌 ----------

def test_growth_cache_invalidated_by_injection_log(tmp_path):
    store = _store(tmp_path)
    _seed_experiences(store)
    store.record_session({"agent": "codex", "session_id": "s1", "trunk": "营销",
                          "category": "文案写作", "req_count": 3,
                          "correction_hits": 0,
                          "started_at": "2026-09-10T08:00:00Z",
                          "ended_at": "2026-09-10T08:30:00Z"})
    assert store.growth_summary(days=30)["flywheel"]["injected"] == 0
    store.record_injection("营销", "文案写作", "s1", 120, channel="hook",
                           items=[{"id": "x", "text": "利益点前置"}])
    fw = store.growth_summary(days=30)["flywheel"]
    assert fw["injected"] == 1, "写过的 injection.log 没让缓存失效——第④格会永远停在 0"
    assert fw["injected_by"]["hook"] == 1


def test_growth_cache_still_reuses_within_same_files(tmp_path):
    store = _store(tmp_path)
    _seed_experiences(store)
    a = store.growth_summary(days=30)
    b = store.growth_summary(days=30)
    assert a is b, "同签名应命中结果缓存（UI-4 的初衷不能被改掉）"
