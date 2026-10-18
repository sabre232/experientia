"""W4 工作流洞察：确定性检测器 + 建议卡三选一 + auto_check 集成 + 本地 API。"""

import pytest

from app.distill import engine_curation
from app.insight import patterns, suggest
from app.store.store import Store
from conftest import local_api_client


def _store(tmp_path, exps):
    store = Store(tmp_path)
    store.ensure_layout()
    for e in exps:
        store.append_experience(dict(e))
    return store


def _exp(action="利益点前置", trunk="营销", category="文案写作", **kw):
    base = {"agent": "codex", "task": "写投放标题", "action": action,
            "G": 0.7, "g_source": "judge", "trunk": trunk, "category": category,
            "session_id": "s-1", "ts": "2026-08-28T08:00:00Z"}
    base.update(kw)
    return base


# ---------- W4-01：三个确定性检测器 ----------

def test_frequency_detector():
    exps = [_exp("利益点前置 + A/B 两版"), _exp("利益点前置+AB两版", count=2),
            _exp("完全不同的另一类做法")]
    out = patterns.detect_frequency(exps)
    assert any(p["type"] == "frequency" and p["occurrences"] >= 2 for p in out)
    # 孤例不报
    cats = {p["category"] for p in out if p["type"] == "frequency"}
    assert "文案写作" in cats


def test_frequency_no_false_positive():
    exps = [_exp("做法一"), _exp("做法二"), _exp("做法三")]
    assert patterns.detect_frequency(exps) == []


def test_path_detector_lcs():
    a = ["确认目标", "产出初稿", "A/B 测试", "优化投放"]
    b = ["确认目标", "产出初稿", "A/B 测试", "复盘数据"]
    assert patterns._lcs_length(a, b) == 3
    exps = []
    for sid, seq in (("s-1", a), ("s-2", b)):
        for i, act in enumerate(seq):
            exps.append(_exp(action=act, session_id=sid,
                             ts=f"2026-08-28T0{i}:00:00Z", task="写投放标题"))
    out = patterns.detect_path(exps)
    assert any(p["type"] == "path" for p in out)


def test_corrections_detector():
    exps = [_exp(action="纯情绪文案", state="点击率低", corrected=True, G=0.2,
                 session_id="s-1"),
            _exp(action="又写纯情绪", state="点击率还是低", corrected=True, G=0.2,
                 session_id="s-2")]
    out = patterns.detect_corrections(exps)
    assert any(p["type"] == "correction" and p["occurrences"] == 2 for p in out)


def test_corrections_single_not_reported():
    exps = [_exp(state="点击率低", corrected=True)]
    assert patterns.detect_corrections(exps) == []


# ---------- W4-02/03：建议卡 + 三选一 + 持久化 ----------

def test_suggest_creates_cards_and_dedups(tmp_path):
    store = _store(tmp_path, [_exp("利益点前置 + A/B 两版"), _exp("利益点前置 + A/B 双版", count=2)])
    new = suggest.suggest(store, list(store.iter_experiences(include_distilled=True)))
    assert len(new) == 1
    # 同 type+trunk 未处理 → 再跑不重复提示
    again = suggest.suggest(store, list(store.iter_experiences(include_distilled=True)))
    assert again == []
    # 落盘了
    assert len(store.load_insights()) == 1


def test_apply_writes_rule(tmp_path):
    store = _store(tmp_path, [_exp("利益点前置 + A/B 两版"), _exp("利益点前置 + A/B 双版", count=2)])
    card = suggest.suggest(store, list(store.iter_experiences(include_distilled=True)))[0]
    rule = suggest.apply_card(store, card)
    assert rule["enabled"] is True
    rules = store.load_rules()
    assert any(r.get("id") == rule["id"] for r in rules)
    updated = store.load_insights()[0]
    assert updated["action"] == "applied"


def test_apply_correction_uses_hard_hook(tmp_path):
    # action 必须不同且互不相似：相同 action 会被 append_experience 合并成一条（count=2），
    # 相似 action 会先触发 frequency 检测器，correction 卡就排不到第一位。
    store = _store(tmp_path, [_exp(action="纯情绪文案", state="点击率低", corrected=True, G=0.2, session_id="s-1"),
                              _exp(action="标题党开头", state="点击率还是低", corrected=True, G=0.2, session_id="s-2")])
    card = suggest.suggest(store, list(store.iter_experiences(include_distilled=True)))[0]
    assert card["type"] == "correction"
    rule = suggest.apply_card(store, card)
    assert rule["trigger"] == "hard-hook"


def test_dismiss_downweights_same_type_trunk(tmp_path):
    store = _store(tmp_path, [_exp("利益点前置 + A/B 两版"), _exp("利益点前置 + A/B 双版", count=2)])
    card = suggest.suggest(store, list(store.iter_experiences(include_distilled=True)))[0]
    suggest.dismiss_card(store, card["id"])
    # 新的同 type+trunk 模式不再提示（忽略 = 降权）
    store.append_experience(_exp("另一个相似做法 X"))
    again = suggest.suggest(store, list(store.iter_experiences(include_distilled=True)))
    assert again == []


def test_defer_marks_card_and_notifies(tmp_path):
    store = _store(tmp_path, [_exp("利益点前置 + A/B 两版"), _exp("利益点前置 + A/B 双版", count=2)])
    card = suggest.suggest(store, list(store.iter_experiences(include_distilled=True)))[0]
    suggest.defer_card(store, card["id"], card)
    updated = store.load_insights()[0]
    assert updated["action"] == "deferred"
    # deferred 不再占首页未处理位
    assert suggest.unhandled_cards(store) == []
    # 通知中心留痕（insight 类型）
    from app import notify

    notes = notify.list_notifications(store, limit=50)
    assert any(n.get("type") == "system_notice" for n in notes)


# ---------- W4 验收：auto_check 集成 ----------

def test_auto_check_produces_insight(tmp_path, monkeypatch):
    """构造 3 次同类任务 → auto_check 后产出 ≥1 条建议卡。"""
    store = _store(tmp_path, [
        _exp("利益点前置 + A/B 两版", session_id="s-1", ts="2026-08-26T08:00:00Z"),
        _exp("利益点前置+A/B两版", session_id="s-2", ts="2026-08-27T08:00:00Z", count=2),
        _exp("利益点前置 A/B 双版", session_id="s-3", ts="2026-08-28T08:00:00Z"),
    ])
    # 阈值兜底蒸馏不触发（高 G <3），只跑洞察
    engine_curation.auto_check(store, verbose=False)
    cards = store.load_insights()
    assert len(cards) >= 1
    assert cards[0]["evidence"]


# ---------- W4-04：本地 API 三选一 ----------

@pytest.fixture
def client(tmp_path):
    store = _store(tmp_path, [_exp("利益点前置 + A/B 两版"), _exp("利益点前置 + A/B 双版", count=2)])
    suggest.suggest(store, list(store.iter_experiences(include_distilled=True)))
    return local_api_client(store), store


def test_insights_api_flow(client):
    c, store = client
    body = c.get("/api/insights").json()
    assert body["total"] == 1
    cid = body["items"][0]["id"]
    r = c.post(f"/api/insights/{cid}/apply")
    assert r.status_code == 200 and "rule" in r.json()
    assert c.get("/api/insights").json()["total"] == 0


def test_insights_api_dismiss_and_404(client):
    c, store = client
    cid = c.get("/api/insights").json()["items"][0]["id"]
    assert c.post(f"/api/insights/{cid}/dismiss").status_code == 200
    assert c.post(f"/api/insights/{cid}/defer").status_code == 404  # 已处理


def test_insights_api_bad_action_400(client):
    c, _ = client
    cid = c.get("/api/insights").json()["items"][0]["id"]
    assert c.post(f"/api/insights/{cid}/bogus").status_code == 400
