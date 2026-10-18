"""AI 重写（第二项蒸馏）链路测试：提案→预览→采纳三段口径。

覆盖 rewrite.polish/apply（经验单条、坑单条）与 engine_curation 的
distill(force, dry_run) 预览 + apply_rewritten_skill 落盘。
原则：采纳前零写盘；采纳只动总结层（G/corrected/*_raw 不碰）+ 回炉。
"""

import json

from app import notify
from app.distill import engine_curation, llm, rewrite
from app.store.store import Store


def _store(tmp_path, config: dict | None = None) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    if config:
        s.save_config(config)
    return s


WITH_MODEL = {"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                    "type": "local", "model": "qwen"}},
              "default_model": "local"}

E1 = {"id": "e1", "ts": "2026-09-01T01:00:00Z",
      "task": "写标题", "task_raw": "帮我把这次投放的标题写一下，突出限时优惠",
      "action": "利益点前置", "action_raw": "把折扣信息放到标题最前面再给两版",
      "G": 0.8, "g_source": "judge", "outcome": "点击率提升",
      "outcome_raw": "上线后点击率提升了三成",
      "trunk": "营销", "category": "文案写作", "count": 1}


# ---------- 经验单条重写 ----------

def test_polish_experiences_requires_model(tmp_path):
    store = _store(tmp_path)
    store.append_experience(dict(E1))
    assert rewrite.polish_experiences(store, ["e1"])["status"] == "no_model"


def test_polish_experiences_filters_unknown_and_parses(tmp_path, monkeypatch):
    store = _store(tmp_path, WITH_MODEL)
    store.append_experience(dict(E1))
    canned = json.dumps([
        {"id": "e1", "task": "限时优惠标题前置利益点，点击率涨三成",
         "action": "折扣信息置顶出两版", "state": "", "outcome": "点击率 +30%"},
        {"id": "ghost", "task": "幻觉记录", "action": "", "state": "",
         "outcome": ""},
    ], ensure_ascii=False)
    monkeypatch.setattr(llm, "call_model", lambda *a, **kw: f"```json\n{canned}\n```")
    r = rewrite.polish_experiences(store, ["e1", "ghost"])
    assert r["status"] == "ok"
    assert [p["id"] for p in r["proposals"]] == ["e1"]      # 未知 id 丢弃
    assert r["proposals"][0]["outcome"] == "点击率 +30%"


def test_polish_experiences_unparsable_raises(tmp_path, monkeypatch):
    store = _store(tmp_path, WITH_MODEL)
    store.append_experience(dict(E1))
    monkeypatch.setattr(llm, "call_model", lambda *a, **kw: "今天天气不错")
    try:
        rewrite.polish_experiences(store, ["e1"])
        raise AssertionError("应抛解析失败")
    except ValueError:
        pass


def test_apply_polish_touches_summary_only(tmp_path):
    """采纳口径：总结层更新 + 回炉；*_raw / G / corrected / previous 全不动。"""
    store = _store(tmp_path)
    store.append_experience(dict(E1))
    updated = rewrite.apply_polish(store, "e1", {
        "task": "限时优惠标题前置利益点", "action": "折扣信息置顶出两版",
        "state": "", "outcome": "点击率 +30%"})
    assert updated["task"] == "限时优惠标题前置利益点"
    assert updated["action"] == "折扣信息置顶出两版"
    assert updated["task_raw"] == E1["task_raw"]        # 原文不动
    assert updated["action_raw"] == E1["action_raw"]
    assert updated["G"] == 0.8 and not updated.get("corrected")
    assert updated["distilled"] is False                 # 回炉
    assert not updated.get("previous")                   # 重写 ≠ 纠错教训
    assert store.pending_experiences("营销", "文案写作")
    logs = [c["text"] for c in store.list_changelog()]
    assert any("AI 重写经验 e1" in t for t in logs)


def test_apply_polish_noop_when_identical(tmp_path):
    store = _store(tmp_path)
    store.append_experience(dict(E1))
    before = store.find_experience("e1")
    updated = rewrite.apply_polish(store, "e1", {"task": "写标题"})
    assert updated == before                             # 全等 → 零写入
    assert not any("AI 重写经验" in c["text"] for c in store.list_changelog())


# ---------- 坑单条改写 ----------

PB = ("# 营销 / 文案写作 · playbook\n\n"
      "> version: 3\n\n"
      "## 标准流程\n（无）\n"
      "## 成功要点\n- 利益点前置\n"
      "## 失败模式\n"
      "- [Solidified] 标题超 20 字被平台截断（出现 4 次）\n"
      "- [Watching] 纯情绪文案点击率低（出现 2 次）\n"
      "## 过时项标记\n（无）\n")


def test_polish_failure_mode_preview_no_write(tmp_path, monkeypatch):
    store = _store(tmp_path, WITH_MODEL)
    store.write_skill("营销", "文案写作", PB)
    canned = json.dumps({"new_text": "标题超 20 字会被平台截断，先数字数再交稿"},
                        ensure_ascii=False)
    monkeypatch.setattr(llm, "call_model", lambda *a, **kw: canned)
    r = rewrite.polish_failure_mode(store, "营销", "文案写作",
                                    "标题超 20 字被平台截断")
    assert r["status"] == "ok"
    assert "先数字数" in r["new_text"]
    assert store.read_skill("营销", "文案写作") == PB     # 预览零写盘


def test_polish_failure_mode_not_found(tmp_path, monkeypatch):
    store = _store(tmp_path, WITH_MODEL)
    store.write_skill("营销", "文案写作", PB)
    monkeypatch.setattr(llm, "call_model", lambda *a, **kw: "{}")
    r = rewrite.polish_failure_mode(store, "营销", "文案写作",
                                    "根本不存在的一条坑")
    assert r["status"] == "not_found"


def test_apply_polish_failure_keeps_mark_and_count(tmp_path):
    store = _store(tmp_path)
    store.write_skill("营销", "文案写作", PB)
    ok = rewrite.apply_polish_failure(
        store, "营销", "文案写作",
        "标题超 20 字被平台截断", "标题超 20 字会被平台截断，先数字数再交稿")
    assert ok
    md = store.read_skill("营销", "文案写作")
    assert "- [Solidified] 标题超 20 字会被平台截断，先数字数再交稿（出现 4 次）" in md
    assert "- [Watching] 纯情绪文案点击率低（出现 2 次）" in md  # 其余行不动
    # 与页面 entry.text 同口径：带次数注记的整串也能命中
    assert rewrite.apply_polish_failure(
        store, "营销", "文案写作",
        "纯情绪文案点击率低（出现 2 次）", "纯情绪文案不做利益承诺，点击率偏低")
    assert "- [Watching] 纯情绪文案不做利益承诺，点击率偏低（出现 2 次）" in \
        store.read_skill("营销", "文案写作")


# ---------- 整方法重写：distill(force, dry_run) + apply ----------

CANNED_PB = ("## 方法名\n- 投放标题写法\n"
             "## 标准流程\n- 拿需求\n"
             "## 成功要点\n- 利益点前置\n"
             "## 失败模式\n- [Watching] 标题超 20 字被平台截断（出现 1 次）\n"
             "## 过时项标记\n（无）\n"
             "## 偏好增量\n（无）\n")


def test_distill_dry_run_no_model_status(tmp_path):
    """预览也是归纳产物：无模型 → 结构化拒绝（总纲），不给半成品。"""
    store = _store(tmp_path)
    store.append_experience(dict(E1))
    r = engine_curation.distill(store, "营销", "文案写作",
                                force=True, dry_run=True)
    assert r["status"] == "model_required" and r["ok"] is False
    assert "未接入模型" in r["message"]


def test_distill_dry_run_model_failed_no_fallback_masquerade(tmp_path,
                                                            monkeypatch):
    """预览必须是真·AI 产物：配了模型但调不通 → model_failed，不拿兜底冒充。"""
    store = _store(tmp_path, WITH_MODEL)
    store.append_experience(dict(E1))
    monkeypatch.setattr(llm, "call_model",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("500")))
    r = engine_curation.distill(store, "营销", "文案写作",
                                force=True, dry_run=True)
    assert r["status"] == "model_failed"


def test_distill_force_dry_run_zero_write_then_apply(tmp_path, monkeypatch):
    store = _store(tmp_path, WITH_MODEL)
    store.append_experience(dict(E1))
    monkeypatch.setattr(llm, "call_model", lambda *a, **kw: CANNED_PB)
    engine_curation.distill(store, "营销", "文案写作")   # 正常首轮：e1 已总结
    assert store.pending_experiences("营销", "文案写作") == []
    old_md = store.read_skill("营销", "文案写作")
    r = engine_curation.distill(store, "营销", "文案写作",
                                source="manual", force=True, dry_run=True)
    assert r["status"] == "preview"
    assert store.read_skill("营销", "文案写作") == old_md   # 预览零写盘
    assert r["old_md"] == old_md
    assert store.pending_experiences("营销", "文案写作") == []  # 不回炉
    n_before = len(list(notify.list_notifications(store)))

    info = engine_curation.apply_rewritten_skill(store, "营销", "文案写作",
                                                 r["md"])
    assert info and info["version"] >= 2
    md = store.read_skill("营销", "文案写作")
    assert "投放标题写法" in md
    # 旧版进 deprecated/ 快照（30 天可恢复）
    snaps = list((store.dir("deprecated") / "skills" / "营销").glob("*.md"))
    assert snaps and old_md in snaps[0].read_text(encoding="utf-8")
    assert any("整方法重写" in c["text"] for c in store.list_changelog())
    # apply 不推蒸馏通知链（那是正常蒸馏的副作用）
    assert len(list(notify.list_notifications(store))) == n_before


def test_force_distill_sees_distilled_experiences(tmp_path, monkeypatch):
    """force 素材 = 全部经验（含已总结）；普通 distill 只看待总结。"""
    store = _store(tmp_path, WITH_MODEL)
    store.append_experience(dict(E1))
    monkeypatch.setattr(llm, "call_model", lambda *a, **kw: CANNED_PB)
    engine_curation.distill(store, "营销", "文案写作")
    seen: list[int] = []
    orig = engine_curation.build_distill_prompt

    def spy(experiences, existing):
        seen.append(len(experiences))
        return orig(experiences, existing)
    monkeypatch.setattr(engine_curation, "build_distill_prompt", spy)
    r1 = engine_curation.distill(store, "营销", "文案写作",
                                 force=True, dry_run=True)
    assert seen[-1] == 1                                   # force 吃到已总结的 e1
    store2 = _store(tmp_path / "b")
    assert engine_curation.distill(store2, "营销", "文案写作",
                                   force=True)["status"] == "no_pending"
    assert r1["count"] == 1
