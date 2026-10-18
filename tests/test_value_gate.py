"""经验价值闸门护栏（方案《研究_经验价值筛选闸门方案》v0.1）。

覆盖：四类分类器、mining 落库抑制、env/garbage 永不升档注入（store 与
gsignal 两处一致）、agent_friction 正常复现升档、v2 存量重分类迁移、
rule_render 建议口吻渲染（含 i18n）。
"""

import json

from app.distill import gsignal, mining, value_gate
from app.gui import i18n, rule_render
from app.store import migrations
from app.store.store import Store

ENV_SIG = "Error during web fetch for https:<p> fetch failed"
GARBAGE_SIG = "except ImportError:"
FRICTION_SIG = "Error: File has not been read yet: <p> Read it first before writing"
LESSON_SIG = "ModuleNotFoundError: No module named 'docx'"


def _store(tmp_path) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    return s


# ---------- 四类分类器 ----------

def test_classify_env_noise():
    for s in (ENV_SIG, "ConnectionRefusedError: 连接被拒", "EBUSY: resource busy or locked"):
        assert value_gate.classify(s) == value_gate.ENV, s
    # echo 包裹的模型服务缺失（llama-server not found）→ garbage，但同属"不入库"
    assert value_gate.is_suppressed(
        value_gate.classify("echo ERROR: llama-server.exe not found"))


def test_classify_source_echo_garbage():
    for s in (GARBAGE_SIG, "except FileNotFoundError:", "#： except OSError:",
              "if result.error:"):
        assert value_gate.classify(s) == value_gate.GARBAGE, s


def test_classify_agent_friction():
    for s in (FRICTION_SIG, "String to replace not found in file.",
              "Command blocked for security: cmd.exe cannot be used",
              'Invalid parameters provided. Reason: Parameter "url" expected string'):
        assert value_gate.classify(s) == value_gate.FRICTION, s


def test_classify_code_lesson():
    for s in (LESSON_SIG, "AttributeError: 'str' object has no attribute 'get'",
              "json.decoder.JSONDecodeError: Expecting value: line # column #",
              "IndexError: list index out of range"):
        assert value_gate.classify(s) == value_gate.LESSON, s


def test_suppressed_set():
    assert value_gate.is_suppressed(value_gate.ENV)
    assert value_gate.is_suppressed(value_gate.GARBAGE)
    assert not value_gate.is_suppressed(value_gate.FRICTION)
    assert not value_gate.is_suppressed(value_gate.LESSON)


# ---------- 展示去向 surface_of（方案 A 收口） ----------

def test_surface_error_sig_all_demoted_to_advice():
    # 纯错误复现计数：无论工具摩擦还是 Python 报错（code_lesson），都不进"你的经验"
    for vclass in (value_gate.FRICTION, value_gate.LESSON):
        rec = {"g_source": "rule", "rule_kind": "error_sig", "value_class": vclass}
        assert value_gate.surface_of(rec) == value_gate.SURFACE_ADVICE, vclass


def test_surface_env_garbage_none():
    for vclass in (value_gate.ENV, value_gate.GARBAGE):
        rec = {"g_source": "rule", "rule_kind": "error_sig", "value_class": vclass}
        assert value_gate.surface_of(rec) == value_gate.SURFACE_NONE, vclass


def test_surface_structural_and_llm_are_experience():
    # 结构化改出来的模式 + LLM 真教训 → "你的经验"
    assert value_gate.surface_of({"g_source": "rule", "rule_kind": "retry_pair"}) \
        == value_gate.SURFACE_EXPERIENCE
    assert value_gate.surface_of({"g_source": "rule", "rule_kind": "pivot"}) \
        == value_gate.SURFACE_EXPERIENCE
    assert value_gate.surface_of({"g_source": "auto", "rule_kind": None,
                                  "importance": 8}) == value_gate.SURFACE_EXPERIENCE


# ---------- mining 落库抑制 ----------

def _sess(sid, sig):
    return {"agent": "workbuddy", "session_id": sid, "trunk": "其他",
            "category": "未分类", "project": "p",
            "events": [{"sig": sig} for _ in range(3)]}


def test_mining_drops_env_and_garbage(tmp_path):
    store = _store(tmp_path)
    mining.mine_session_dicts(store, [_sess("a", ENV_SIG), _sess("b", GARBAGE_SIG)])
    stored = list(store.iter_experiences(include_distilled=True))
    assert stored == []  # 环境噪音/源码回声根本不落库


def test_mining_keeps_friction_and_lesson(tmp_path):
    store = _store(tmp_path)
    mining.mine_session_dicts(store, [_sess("a", FRICTION_SIG), _sess("b", LESSON_SIG)])
    by_class = {e.get("value_class")
                for e in store.iter_experiences(include_distilled=True)}
    assert value_gate.FRICTION in by_class
    assert value_gate.LESSON in by_class


# ---------- 注入升档防御（两处一致） ----------

def _rule_card(sig, vclass, sessions):
    return {"task": "sig:" + sig[:40], "action": "recurring-error-signature",
            "state": sig, "outcome": "", "G": gsignal.RULE_SINGLE,
            "g_source": "rule", "rule_kind": "error_sig", "value_class": vclass,
            "corrected": False, "agent": "codex", "session_id": sessions[0],
            "seen_in": sessions}


def test_env_garbage_never_promoted_even_with_valid(tmp_path):
    store = _store(tmp_path)
    for i, vclass in enumerate((value_gate.ENV, value_gate.GARBAGE)):
        rec = _rule_card(f"sig{i}-x", vclass, [f"s{i}1", f"s{i}2", f"s{i}3", f"s{i}4"])
        rec["user_valid"] = True
        store.append_experience(rec)
    stored = list(store.iter_experiences(include_distilled=True))
    assert len(stored) == 2
    for e in stored:
        assert e.get("G") == gsignal.RULE_SINGLE
        assert gsignal.effective_g(e) < gsignal.G_MIN_INJECT


def test_friction_promotes_after_reproduction(tmp_path):
    # agent_friction 仍可注入（提醒 agent 别犯），只是不占用户经验墙
    store = _store(tmp_path)
    store.append_experience(_rule_card(FRICTION_SIG, value_gate.FRICTION,
                                       ["s1", "s2", "s3"]))
    e = list(store.iter_experiences(include_distilled=True))[0]
    assert gsignal.effective_g(e) >= gsignal.G_MIN_INJECT


def test_promote_guard_store_gsignal_consistent(tmp_path):
    # store._normalize_read_view 与 gsignal.effective_g 对 env 卡判定必须同口径
    from app.store import store as store_mod
    for vclass in (value_gate.ENV, value_gate.GARBAGE, value_gate.FRICTION,
                   value_gate.LESSON):
        rec = _rule_card("sig-x", vclass, ["s1", "s2", "s3", "s4"])
        promoted = store_mod._normalize_read_view(dict(rec))
        assert (promoted.get("G") == gsignal.RULE_PROMOTED) == \
               (gsignal.effective_g(rec) >= gsignal.G_MIN_INJECT), vclass


# ---------- v2 存量重分类迁移 ----------

def test_v2_migration_reclassifies_existing(tmp_path):
    store = _store(tmp_path)
    store.save_meta({"data_version": 1})  # 停在 v1，触发 v2
    def raw(sig):
        return {"task": "sig:" + sig[:40], "action": "recurring-error-signature",
                "state": sig, "G": 0.4, "g_source": "rule", "rule_kind": "error_sig",
                "agent": "codex", "session_id": "s", "seen_in": ["s"]}
    lines = [json.dumps(raw(sig), ensure_ascii=False) for sig in
             (ENV_SIG, GARBAGE_SIG, FRICTION_SIG, LESSON_SIG)]
    (store.data_dir / "experience.jsonl").write_text("\n".join(lines) + "\n",
                                                      encoding="utf-8")
    out = migrations.run_startup_migrations(store)
    assert out.get("value_dropped") == 2
    assert out.get("value_tagged") == 4
    remaining = [json.loads(l) for l in
                 (store.data_dir / "experience.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    classes = {r.get("value_class") for r in remaining}
    assert classes == {value_gate.FRICTION, value_gate.LESSON}
    # 下架的两条快照进 deprecated（不物理删）
    snap = list((store.data_dir / "deprecated").rglob("experience_value_gate.jsonl"))
    assert snap and len(snap[0].read_text(encoding="utf-8").splitlines()) == 2
    assert store.load_meta().get("data_version") == migrations.DATA_VERSION


def test_v2_migration_idempotent(tmp_path):
    store = _store(tmp_path)
    store.save_meta({"data_version": migrations.DATA_VERSION})
    out = migrations.run_startup_migrations(store)
    assert out == {"skipped": True}


# ---------- rule_render 建议口吻 ----------

def test_friction_advice_contains_sig_and_repro(tmp_path):
    i18n.load_catalog("zh")
    item = {"state": FRICTION_SIG, "count": 44}
    line = rule_render.friction_advice(item)
    assert "Read" in line and "44" in line  # 报错数据 + 复现次数都在
    assert rule_render.friction_advice({"state": "unknown x", "count": 2})


def test_friction_advice_i18n_switch(tmp_path):
    i18n.load_catalog("en")
    try:
        line = rule_render.friction_advice({"state": FRICTION_SIG, "count": 3})
        assert "running into" in line or "Suggestion" in line
    finally:
        i18n.load_catalog("zh")
