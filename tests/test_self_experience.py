"""经验上报分流后端测试（总方案  / S5）。"""

import pytest

from app.capture import probe as probe_ch
from app.capture import self_experience as se
from app.store.store import Store


@pytest.fixture
def store(tmp_path):
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


def _note(**kw):
    note = {"task": "接入新模型", "conclusion": "用 A 方式配置最稳",
            "pitfalls": "别用 B，会报错"}
    note.update(kw)
    return note


def test_discipline_reject_and_pending_no_model(store):
    # 无模型（默认无路由）→ 合法内容一律 pending 草稿
    r = se.process(store, "trae", _note())
    assert r["status"] == "pending"
    # 重复 → rejected
    r = se.process(store, "trae", _note())
    assert r["status"] == "rejected" and "重复" in r["reason"]
    # 含密钥样式 → rejected
    r = se.process(store, "hermes", _note(conclusion="密钥 sk-1234567890abcdefghij"))
    assert r["status"] == "rejected" and "密钥" in r["reason"]
    # 同 agent pending 达到阈值后继续来 → 拒收（填满 5 条后再来第 6 条）
    for i in range(se._MAX_PENDING_PER_AGENT):
        se.process(store, "cursor", _note(task=f"t{i}", conclusion=f"做法 {i}"))
    assert store.draft_count("pending") == 1 + se._MAX_PENDING_PER_AGENT
    r = se.process(store, "cursor", _note(task="over", conclusion="再一条"))
    assert r["status"] == "rejected" and "过多" in r["reason"]


def test_adopt_and_ignore(store):
    r = se.process(store, "trae", _note())
    draft = r["draft"]
    assert store.draft_count("pending") == 1
    # 放行 → 进正式经验库（用户确认 = G=1, g_source=user）
    res = se.adopt(store, draft["id"])
    assert res["ok"] is True
    exps = list(store.iter_experiences())
    assert any(e.get("g_source") == "user" and "A 方式配置最稳" in e.get("action", "")
               for e in exps)
    assert store.draft_count("pending") == 0
    # 忽略另一条
    r2 = se.process(store, "windsurf", _note(task="t2"))
    assert se.ignore(store, r2["draft"]["id"])["ok"] is True
    assert store.draft_count("pending") == 0
    assert store.draft_count("ignored") == 1


def test_adopt_structured_draft_from_review(store):
    """复盘通道的缺证据草稿（commit_candidate 形状）也能一键放行。

     H3 之前 adopt 只认自报草稿的 text/note 形状，结构化草稿
    （task/action/outcome）放行必失败——草稿列表每条按钮都点不动。
    """
    from app.distill import review

    rec = {"agent": "trae", "task": "排查构建失败", "state": "",
           "action": "清理缓存后重跑构建", "outcome": "构建通过",
           "trunk": "其他", "category": "未分类", "G": 0.9}
    draft, route = review.commit_candidate(rec, store)
    assert route == "draft" and draft is not None
    assert store.draft_count("pending") == 1

    res = se.adopt(store, draft["id"])
    assert res["ok"] is True
    exps = list(store.iter_experiences())
    hit = next(e for e in exps if e.get("action") == "清理缓存后重跑构建")
    assert hit["g_source"] == "user" and hit["G"] == 1.0
    assert store.draft_count("pending") == 0


def test_incoming_experience_roundtrip(store):
    """纯经验上报（session_note，无 data_sources）经 incoming 吸收 → 草稿。"""
    code = probe_ch.make_code("trae")
    store.save_incoming_report(code, {
        "report_version": 1, "agent": "trae", "report_type": "session_note",
        "experience": _note(),
    })
    assert probe_ch.run_incoming(store) == 1
    assert store.list_incoming_codes() == []
    assert store.draft_count("pending") == 1
    d = store.list_drafts("pending")[0]
    assert d["agent"] == "trae"
    assert "A 方式" in d["text"]
    # apply 同路径（粘贴码）
    code2 = probe_ch.make_code("trae")
    store.save_incoming_report(code2, {
        "report_version": 1, "agent": "trae", "report_type": "session_note",
        "experience": _note(task="another"),
    })
    res = probe_ch.apply_code(store, code2)
    assert res["ok"] is True
    assert res["status"]["mode"] == "pending"
    assert store.draft_count("pending") == 2


def test_api_drafts_adopt_ignore(tmp_path):
    from fastapi.testclient import TestClient

    from app.local_api import create_local_app
    from conftest import TEST_API_TOKEN

    store = Store(tmp_path / "data")
    store.ensure_layout()
    client = TestClient(create_local_app(store, api_token=TEST_API_TOKEN))
    auth = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
    r = se.process(store, "trae", _note(task="api 放行"))
    d = r["draft"]
    # 无 token → 401
    assert client.get("/api/experience-drafts").status_code == 401
    rows = client.get("/api/experience-drafts", headers=auth).json()
    assert rows["count"] == 1 and rows["items"][0]["id"] == d["id"]
    assert client.post(f"/api/experience-drafts/{d['id']}/adopt",
                       headers=auth).json()["ok"] is True
    assert client.get("/api/experience-drafts", headers=auth).json()["count"] == 0
    r2 = se.process(store, "windsurf", _note(task="api 忽略"))
    assert client.post(f"/api/experience-drafts/{r2['draft']['id']}/ignore",
                       headers=auth).json()["ok"] is True
