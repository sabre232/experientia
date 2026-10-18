"""蒸馏兜底方案测试：switcher / 无模型复盘 / 确定性策展 / 模板 Skill /
VI-O1 洞察润色 / 技术把手 / 交叉验证。"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from app import notify
from app.distill import dedupe, engine_curation, extract, gsignal, review, skill, verify
from app.store.store import Store
from conftest import rmtree_readonly


def _store(tmp_path, config: dict | None = None) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    if config:
        s.save_config(config)
    return s


WITH_MODEL = {"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                    "type": "local", "model": "qwen"}},
              "default_model": "local"}


def _session(correction_hits: int = 1) -> dict:
    return {
        "agent": "codex", "session_id": "s-1", "model": "qwen",
        "trunk": "营销", "category": "文案写作", "project": None,
        "req_count": 3, "correction_hits": correction_hits,
        "user_messages": ["写一个投放标题", "不对，利益点没有前置"],
        "assistant_messages": ["标题 A：震撼来袭", "标题 B：限时优惠"],
    }


# ---------- D-O1：switcher + 复盘降级 ----------

def test_model_available_switcher(tmp_path):
    from app.distill import llm

    assert llm.model_available(_store(tmp_path)) is False  # 没配
    assert llm.model_available(_store(tmp_path, WITH_MODEL)) is True
    store = _store(tmp_path, {"models": {"x": {"endpoint": ""}}})
    assert llm.model_available(store) is False  # endpoint 空


def test_fallback_review_records_corrected_candidate(tmp_path):
    """新语义：无模型不再逐字落经验——命中片段挂进证据队列待重放。"""
    store = _store(tmp_path)  # 无模型
    added = asyncio.run(review.maybe_review_session(store, _session()))
    assert added == 0
    assert list(store.iter_experiences(include_distilled=True)) == []
    pend = store.load_pending_review_records()
    assert len(pend) == 1
    assert pend[0]["agent"] == "codex" and pend[0]["session_id"] == "s-1"
    assert any("不对，利益点没有前置" in s for s in pend[0]["snippets"])
    assert pend[0]["trunk"] == "营销" and pend[0]["category"] == "文案写作"


def test_fallback_review_no_correction_no_record(tmp_path):
    store = _store(tmp_path)
    assert asyncio.run(review.maybe_review_session(store, _session(0))) == 0
    assert list(store.iter_experiences(include_distilled=True)) == []
    assert store.load_pending_reviews() == []  # 无可沉淀信号（轮数 <6、无纠正、非肯定收尾）连队列都不进


def test_fallback_review_on_model_failure(tmp_path, monkeypatch):
    store = _store(tmp_path, WITH_MODEL)  # 配了但调不通 → 挂证据队列待重放

    async def _boom(*a, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("app.distill.llm.call_model_async", _boom)
    assert asyncio.run(review.maybe_review_session(store, _session())) == 0
    assert len(store.load_pending_reviews()) == 1
    assert list(store.iter_experiences(include_distilled=True)) == []


def test_fallback_review_on_unparsable_output(tmp_path, monkeypatch):
    """：模型返回不可解析输出 → 必须挂证据队列。

    旧实现这里直接 return 0，调用方随即 settle_reviewed——该会话从此永不
    重试，代理/hook 通道的可蒸馏会话静默丢失（文件通道本来就挂队列）。"""
    store = _store(tmp_path, WITH_MODEL)

    async def _garbage(*a, **kw):
        return "当然！以下是我的建议：```json\n[{坏了一半"

    monkeypatch.setattr("app.distill.llm.call_model_async", _garbage)
    assert asyncio.run(review.maybe_review_session(store, _session())) == 0
    assert len(store.load_pending_reviews()) == 1
    assert list(store.iter_experiences(include_distilled=True)) == []


def test_fallback_review_on_non_list_output(tmp_path, monkeypatch):
    """H5 同型：输出是合法 JSON 但不是列表（模型跑偏）→ 同样挂队列。"""
    store = _store(tmp_path, WITH_MODEL)

    async def _obj(*a, **kw):
        return '{"experiences": ["x"]}'

    monkeypatch.setattr("app.distill.llm.call_model_async", _obj)
    assert asyncio.run(review.maybe_review_session(store, _session())) == 0
    assert len(store.load_pending_reviews()) == 1


# ---------- 原始会话 → 一句结论（确定性压缩，摆脱 LLM 依赖） ----------

def test_compress_collapses_multiline_to_one_line():
    """用户反馈的"6 行踩坑"型：多行原始会话压成一句短结论（取首句到句读）。"""
    raw = ("我刚刚想到了，这一步其实要分2步去看 1 之前说过的，先复现问题再定位根因是更稳的做法。\n"
           "因为跳过复现直接改，往往改完还是复现不出来，白折腾一轮。\n"
           "复现这一步可以固定一套最小触发路径\n"
           "2 日志等级也有点太低了...事实上我倾向于先把关键分支的日志补上，再来谈定位。\n"
           "1.复现部分：是的，我认为其实应该是，先把触发路径固定下来再动手改")
    out = review.compress_to_line(raw, review.STATE_MAX)
    assert "\n" not in out
    assert len(out) <= review.STATE_MAX
    assert out.startswith("我刚刚想到了") and "复现问题" in out
    # 只取首句（到第一个句读），后续句子不进结论
    assert "复现这一步可以固定" not in out and "日志等级" not in out


def test_compress_strips_mentions_and_media():
    """会话 @ 引用 / 图片占位等产物被清掉，保住正文。"""
    out = review.compress_to_line("梳理登录链路 @skill:Si... 图已生成", review.TASK_MAX)
    assert "@skill" not in out and "图已生成" not in out
    assert "梳理登录链路" in out


def test_compress_passthrough_short():
    """已是短句（产品文档口径）原样通过，不自由改写（surviving vocabulary）。"""
    assert review.compress_to_line("端口被占用", review.STATE_MAX) == "端口被占用"
    assert review.compress_to_line("初版标题点击率低", review.STATE_MAX) == "初版标题点击率低"


def test_compress_hard_truncates():
    """超长无句读输入硬截断到 max_chars + …。"""
    out = review.compress_to_line("很长的" * 50, review.TASK_MAX)
    assert len(out) <= review.TASK_MAX
    assert out.endswith("…")


def test_compress_short_first_sentence_extends():
    """首句是确认词"是的。"且后文无句读 → 取整段，避免只留"是的"。"""
    assert "端口" in review.compress_to_line("是的。我们应该先把端口改掉", review.STATE_MAX)


def test_fallback_snippets_kept_verbatim(tmp_path):
    """：片段是"现场证据"原样入队（截 160），只供灰标视图展示——
    展示字段压缩（compress_to_line）是模型路径的事，队列不做加工。"""
    store = _store(tmp_path)  # 无模型
    session = _session()
    session["user_messages"] = [
        "写一个投放标题",
        "不对，利益点没有前置，应该把卖点放最前面，再补一个限时钩子",
    ]
    assert asyncio.run(review.maybe_review_session(store, session)) == 0
    pend = store.load_pending_review_records()
    assert pend[0]["snippets"][0].startswith("不对，利益点没有前置")
    assert list(store.iter_experiences(include_distilled=True)) == []


# ---------- D-O2：确定性策展 ----------

EXPS = [
    {"id": "e1", "ts": "2026-09-01T01:00:00Z", "task": "写标题",
     "action": "利益点前置 + A/B 两版", "G": 0.8, "g_source": "judge",
     "outcome": "点击率 +30%", "trunk": "营销", "category": "文案写作",
     "count": 1},
    {"id": "e2", "ts": "2026-09-01T02:00:00Z", "task": "写标题",
     "action": "纯情绪文案点击率低", "G": 0.3, "g_source": "auto",
     "corrected": True, "trunk": "营销", "category": "文案写作", "count": 1},
    {"id": "e3", "ts": "2026-09-01T03:00:00Z", "task": "写标题",
     "action": "纯情绪文案点击率偏低", "G": 0.3, "g_source": "auto",
     "corrected": True, "trunk": "营销", "category": "文案写作", "count": 1},
    {"id": "e4", "ts": "2026-09-01T04:00:00Z", "task": "写标题",
     "action": "标题超 20 字被平台截断", "G": 0.2, "g_source": "user",
     "corrected": True, "trunk": "营销", "category": "文案写作", "count": 4},
]


def _distill_store(tmp_path, config=None, monkeypatch=None):
    store = _store(tmp_path, config)
    for e in EXPS:
        store.append_experience(dict(e))
    return store


def _snapshot(path):
    """文件指纹（字节级未改动判定：mtime + 内容哈希）。"""
    import hashlib

    p = Path(path)
    if not p.exists():
        return None
    return (p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest())


def test_distill_no_model_returns_model_required(tmp_path):
    """总纲 /：无模型 → 不写卡、不覆盖、**不产出任何正文**。

    旧行为是落确定性兜底（三节写死"（无）"、原文罗列）——那正是"蒸馏出一堆
    废话和无用细节"的成因。现在必须结构化拒绝，并保留上次内容。
    """
    store = _distill_store(tmp_path)
    store.write_skill("营销", "文案写作",
                      "# 营销 / 文案写作 · playbook\n\n> version: 1\n\n"
                      "## 标准流程\n- 老步骤\n## 成功要点\n- 老要点\n"
                      "## 失败模式\n- [Watching] 老坑（出现 1 次）\n")
    before = _snapshot(store.skill_path("营销", "文案写作"))
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["status"] == "model_required" and r["ok"] is False
    assert r["kept_previous"] is True
    assert r["count"] == len(EXPS)
    assert "未接入模型" in r["message"]
    # 目标文件字节级未被修改（mtime + 哈希）
    assert _snapshot(store.skill_path("营销", "文案写作")) == before
    # 经验未被打标（没有产出，就不该消耗素材）
    assert len(store.pending_experiences("营销", "文案写作")) == len(EXPS)
    # 不出现任何占位正文
    assert "（无）" not in (store.read_skill("营销", "文案写作") or "")


def test_distill_no_model_leaves_no_card_when_none_existed(tmp_path):
    """无模型 + 从无旧卡 → 盘上仍然没有卡（不造一张空卡占位）。"""
    store = _distill_store(tmp_path)
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["status"] == "model_required" and r["kept_previous"] is False
    assert not store.skill_path("营销", "文案写作").exists()
    assert store.read_skill("营销", "文案写作") is None


def test_distill_model_failure_writes_nothing(tmp_path, monkeypatch):
    """配了模型但调不通 → 同样不写卡（不做"用规则假装归纳"的回落）。"""
    store = _distill_store(tmp_path, WITH_MODEL)
    monkeypatch.setattr("app.distill.llm.call_model",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("500")))
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["status"] == "model_failed" and r["ok"] is False
    assert r["kept_previous"] is False
    assert store.read_skill("营销", "文案写作") is None


def test_distill_with_model_keeps_manual_name(tmp_path, monkeypatch):
    """用户手起的名（name_source=manual）蒸馏不得覆盖——代码侧硬保证。"""
    store = _distill_store(tmp_path, WITH_MODEL)
    store.write_skill("营销", "文案写作",
                      "# 营销 / 文案写作 · playbook\n\n> name: 用户手起的名\n"
                      "> name_source: manual\n> version: 1\n")
    monkeypatch.setattr(
        "app.distill.llm.call_model",
        lambda *a, **kw: "## 方法名\n- 模型起的新名\n\n## 标准流程\n- 步骤\n\n"
                         "## 成功要点\n- 要点\n\n## 失败模式\n- [Watching] 坑（出现 1 次）\n")
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["status"] == "success" and r["version"] == 2
    md = store.read_skill("营销", "文案写作")
    assert "> name: 用户手起的名" in md and "> name_source: manual" in md
    assert "模型起的新名" not in md


def test_no_model_produces_no_fixes(tmp_path):
    """归纳层门禁同口径：无模型 → 连纠正补丁也不产出（不罗列冒充归纳）。"""
    store = _store(tmp_path)
    for i, state in enumerate(("利益点没有前置", "利益点还是没前置"), 1):
        store.append_experience(
            {"id": f"f{i}", "ts": f"2026-09-01T0{i}:00:00Z", "task": "写标题",
             "state": state, "action": "先堆情绪词再放卖点",
             "G": 0.2, "g_source": "user", "corrected": True,
             "trunk": "营销", "category": "文案写作", "count": 1})
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["status"] == "model_required"
    assert not r.get("fixes")
    assert store.read_fixes("营销", "文案写作") is None


# ---------- D-O2：trigram 去重阈值 ----------

def test_near_dup_threshold_085():
    assert dedupe.near_dup("纯情绪文案点击率低", "纯情绪文案点击率偏低") is True
    assert dedupe.near_dup("利益点前置 + A/B 两版", "纯情绪文案点击率低") is False
    assert dedupe.near_dup("", "x") is False  # 空串不算重复
    assert dedupe.near_dup("abc", "abc", threshold=0.5) is True
    assert len(dedupe.dedupe_lines(["a", "a", "ab", "xyz"])) == 2


# ---------- D-O3：Skill 模板降级 ----------

def test_fallback_skill_body_no_model(tmp_path):
    store = _distill_store(tmp_path)
    r = skill.generate_skill(store, trunk="营销", category="文案写作")
    md = r["md"]
    for sec in ("## When to Use（何时使用）", "## Procedure（成功做法",
                "## Pitfalls（失败模式", "## Verification（怎么确认做对了）"):
        assert sec in md
    assert "1. 利益点前置 + A/B 两版" in md
    assert "- 纯情绪文案点击率低" in md
    assert "- 点击率 +30%" in md
    assert "涉及 文案写作 类任务时使用" in md
    assert r["source_count"] == 4


# ---------- D-O4：技术把手 + 交叉验证 ----------

def test_extract_handles_kinds_and_cap():
    text = ("改 app/distill/llm.py 后报 Error: connection refused，"
            "文档见 https://example.com/docs ，版本 v1.2.3，port=8100")
    h = extract.extract_handles(text)
    assert any("llm.py" in x for x in h)
    assert any(x.startswith("Error") for x in h)
    assert "https://example.com/docs" in h
    assert "v1.2.3" in h and "port=8100" in h
    assert len(h) == len(set(h))
    assert len(extract.extract_handles("x.py " * 30)) <= extract.MAX_HANDLES
    assert extract.extract_handles("") == []


def test_verify_no_project_zero_and_file_bump(tmp_path):
    assert verify.verify_experience(None, {"action": "改 a/b.py", "project": None}) == 0.0
    # 文件路径真实存在 → bump
    f = tmp_path / "app" / "x.py"
    f.parent.mkdir(parents=True)
    f.write_text("x = 1\n", encoding="utf-8")
    bump = verify.verify_experience(None,
                                    {"action": "改 app/x.py", "project": str(tmp_path)})
    assert bump == verify.BUMP_FILE_EXISTS


@pytest.mark.skipif(shutil.which("git") is None, reason="本机没有 git")
def test_verify_git_evidence(tmp_path):
    import subprocess

    f = tmp_path / "uniq_widget_abc.py"
    f.write_text("def widget():\n    pass\n", encoding="utf-8")
    env_git = ["git", "-C", str(tmp_path)]
    subprocess.run(env_git + ["init", "-q"], check=True, capture_output=True)
    subprocess.run(env_git + ["add", "."], check=True, capture_output=True)
    # gpgsign=false：用户全局开了 commit.gpgsign 会让提交失败（与本机配置相关）
    subprocess.run(env_git + ["-c", "user.email=t@t", "-c", "user.name=t",
                              "-c", "commit.gpgsign=false",
                              "commit", "-qm", "add uniq_widget_abc"], check=True,
                   capture_output=True)
    try:
        bump = verify.verify_experience(None,
                                        {"action": "修 uniq_widget_abc 的 bug",
                                         "project": str(tmp_path)})
        assert bump >= verify.BUMP_GIT_EVIDENCE
        # 无关词 → 0
        assert verify.verify_experience(None,
                                        {"action": "zzz_no_such_word_zzz",
                                         "project": str(tmp_path)}) == 0.0
    finally:
        # git object 是 444 只读，pytest 回收不了 → 每次跑都往系统临时目录
        # 丢一个含 .git 的目录（机制说明见 conftest.rmtree_readonly）。
        rmtree_readonly(tmp_path / ".git")


def test_review_attaches_handles_and_verify(tmp_path, monkeypatch):
    """质量字段（handles）在模型路径落库时挂载（后兜底不落库，
    该护栏随主路径走）。"""
    store = _store(tmp_path, WITH_MODEL)
    session = _session()
    session["user_messages"] = ["修 app/distill/llm.py 的 bug",
                                "不对，错了，重来"]

    async def fake_call(store_, messages, **kw):
        # 注意：别在候选里用 timeout / fetch failed 一类环境抖动词——注意力闸
        # （P1-2 D1）会把它们判成 env_transient 直接拒收，那是预期行为。
        return json.dumps([
            {"task": "修 llm.py 的 bug", "state": "连不上",
             "action": "改 app/distill/llm.py 的连接复用参数",
             "outcome": "通过", "corrected": False, "causal": True,
             "evidence": "app/distill/llm.py"}], ensure_ascii=False)

    monkeypatch.setattr("app.distill.llm.call_model_async", fake_call)
    asyncio.run(review.maybe_review_session(store, session))
    e = list(store.iter_experiences(include_distilled=True))[0]
    assert e["handles"] and any("llm.py" in h for h in e["handles"])


# ---------- VI-O1：洞察主线接 rewrite_text ----------

def _freq_exps(n: int = 3) -> list[dict]:
    return [{"id": f"i{k}", "ts": f"2026-09-01T0{k}:00:00Z",
             "task": "写标题", "action": "利益点前置 + A/B 两版", "G": 0.8,
             "g_source": "judge", "trunk": "营销", "category": "文案写作"}
            for k in range(n)]


def test_suggest_no_model_uses_template(tmp_path, monkeypatch):
    from app.insight import suggest

    store = _store(tmp_path)
    monkeypatch.setattr("app.distill.llm.call_model",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("不应调模型")))
    cards = suggest.suggest(store, _freq_exps())
    assert len(cards) == 1
    assert cards[0]["text"] == suggest._template_sentence(
        {"type": "frequency", "example": "利益点前置 + A/B 两版", "occurrences": 3})


def test_suggest_with_model_polishes(tmp_path, monkeypatch):
    from app.insight import suggest

    store = _store(tmp_path, WITH_MODEL)
    monkeypatch.setattr("app.distill.llm.call_model",
                        lambda *a, **kw: "你最近老在写标题时利益点前置，要不要固定下来？")
    cards = suggest.suggest(store, _freq_exps())
    assert cards[0]["text"] == "你最近老在写标题时利益点前置，要不要固定下来？"


def test_suggest_model_failure_falls_back(tmp_path, monkeypatch):
    from app.insight import suggest

    store = _store(tmp_path, WITH_MODEL)
    monkeypatch.setattr("app.distill.llm.call_model",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("500")))
    cards = suggest.suggest(store, _freq_exps())
    # 失败回落模板句（防歪 #12：与无模型逐字一致）
    assert cards[0]["text"] == suggest._template_sentence(
        {"type": "frequency", "example": "利益点前置 + A/B 两版", "occurrences": 3})
