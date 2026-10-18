"""纠正 = 改内容：编辑端点落库口径 + 编辑框写回。

覆盖三条关键约定：
- 改后的文本成为正式内容（展示与 *_raw 同源，展开不再翻出旧字）；
- 旧值进 previous 快照，且每个字段只记首次被改前的值（= 最初的错内容）；
- 失败分析师读旧值——"什么不能做"记的是被改掉的错内容。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.store.store import Store
from conftest import local_api_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def client(tmp_path, monkeypatch):
    keys: dict[str, str] = {}
    import keyring

    monkeypatch.setattr(keyring, "set_password", lambda svc, name, pw: keys.update({name: pw}))
    monkeypatch.setattr(keyring, "get_password", lambda svc, name: keys.get(name))
    monkeypatch.setattr(keyring, "delete_password", lambda svc, name: keys.pop(name, None))
    store = Store(tmp_path)
    store.ensure_layout()
    return local_api_client(store), store, keys


def _seed(store: Store) -> str:
    store.append_experience({
        "agent": "workbuddy", "task": "原任务（错的说法）", "state": "原踩坑",
        "action": "原做法", "outcome": "原结果",
        "task_raw": "原任务原文", "state_raw": "原踩坑原文",
        "action_raw": "原做法原文", "outcome_raw": "原结果原文",
        "trunk": "其他", "category": "未分类", "G": 0.8, "distilled": True,
    })
    return store.iter_experiences(include_distilled=True).__next__()["id"]


def test_edit_updates_content_and_keeps_previous_snapshot(client):
    c, store, _ = client
    eid = _seed(store)

    r = c.post(f"/api/experiences/{eid}/edit",
               json={"task": "新任务", "action": "新做法"})
    assert r.status_code == 200, r.text
    rec = store.find_experience(eid)
    # 改对的文本即权威内容：展示字段与 *_raw 同步（展开不会翻出旧字）
    assert rec["task"] == "新任务" and rec["task_raw"] == "新任务"
    assert rec["action"] == "新做法" and rec["action_raw"] == "新做法"
    # 没动过的字段原样保留
    assert rec["state"] == "原踩坑" and rec["state_raw"] == "原踩坑原文"
    # 旧值进快照，每个字段只记首次被改前的值
    assert rec["previous"] == {"task": "原任务（错的说法）", "action": "原做法"}
    # 保存后仍算纠正：G 落 L1 纠正档 + 回炉重蒸馏
    assert rec["G"] == 0.2 and rec["corrected"] is True
    assert rec["g_source"] == "user" and rec["distilled"] is False


def test_edit_keeps_first_snapshot_on_second_edit(client):
    """二次编辑同一字段：previous 里留的仍是最初那版错内容，不被中间版覆盖。"""
    c, store, _ = client
    eid = _seed(store)
    c.post(f"/api/experiences/{eid}/edit", json={"action": "第一版改法"})
    c.post(f"/api/experiences/{eid}/edit", json={"action": "第二版改法"})
    rec = store.find_experience(eid)
    assert rec["action"] == "第二版改法"
    assert rec["previous"] == {"action": "原做法"}


def test_edit_without_change_is_noop(client):
    c, store, _ = client
    eid = _seed(store)
    r = c.post(f"/api/experiences/{eid}/edit", json={"task": "原任务（错的说法）"})
    assert r.status_code == 200
    assert r.json()["message"] == "内容未变化"
    rec = store.find_experience(eid)
    assert rec["G"] == 0.8 and "previous" not in rec


def test_edit_unknown_id_404(client):
    c, _store, _ = client
    assert c.post("/api/experiences/nope/edit", json={"task": "x"}).status_code == 404


def test_failure_analysis_reads_previous_values(client):
    """失败分析师读旧值：教训是被改掉的错内容，不是用户改对后的文本。"""
    from app.distill import engine_curation

    c, store, _ = client
    eid = _seed(store)
    c.post(f"/api/experiences/{eid}/edit",
           json={"state": "改对的踩坑", "action": "改对的做法"})
    rec = store.find_experience(eid)

    line = engine_curation._fmt_experience(rec)
    assert "原做法" in line and "改对的做法" not in line
    assert "原踩坑" in line and "改对的踩坑" not in line

    body = engine_curation._fallback_fixes_body([rec])
    assert "原踩坑" in body and "原做法" in body
    assert "改对的踩坑" not in body


# ---------- 编辑对话框 ----------

class _StubApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def edit_experience(self, exp_id: str, fields: dict) -> dict:
        self.calls.append((exp_id, dict(fields)))
        return {"ok": True}


def _rec() -> dict:
    return {"id": "e1", "task": "旧标题", "task_raw": "旧标题原文",
            "state": "旧踩坑", "action": "旧做法", "outcome": "旧结果",
            "agent": "workbuddy", "ts": "2026-09-11T10:00:00"}


def test_dialog_prefills_raw_and_saves_changed_fields(qapp):
    pytest.importorskip("PySide6")
    from app.gui.experience_edit import ExperienceEditDialog

    api = _StubApi()
    dlg = ExperienceEditDialog(api, [_rec()])
    # 预填原文优先（用户看到的就是卡片展开后的全文）
    assert dlg._edits[0]["task"].toPlainText() == "旧标题原文"
    dlg._edits[0]["task"].setPlainText("新标题")
    dlg._save()
    assert api.calls == [("e1", {"task": "新标题"})]


def test_dialog_saves_every_record_in_group(qapp):
    """一张卡合并多条记录（多个做法）→ 逐条列出、逐条写回，不改错条。"""
    from app.gui.experience_edit import ExperienceEditDialog

    api = _StubApi()
    recs = [_rec(), {**_rec(), "id": "e2", "action": "第二个做法",
                     "action_raw": "第二个做法原文"}]
    dlg = ExperienceEditDialog(api, recs)
    assert len(dlg._edits) == 2
    dlg._edits[1]["action"].setPlainText("第二个做法（改）")
    dlg._save()
    assert api.calls == [("e2", {"action": "第二个做法（改）"})]


def test_dialog_no_change_sends_nothing(qapp):
    from app.gui.experience_edit import ExperienceEditDialog

    api = _StubApi()
    dlg = ExperienceEditDialog(api, [_rec()])
    dlg._save()
    assert api.calls == []
