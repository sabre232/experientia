"""P2 生命周期护栏。

probation 试用-转正-出局 / 零采纳降级 / 逐条判据 / 三因子排序 /
numeric 键 / 语义 upsert / 事件按价值裁剪 / 队列归档降级 / 模型下载器校验。
"""

import json

from app.capture.events import derive_events
from app.config_schema import NUMERIC_DEFAULTS, numeric
from app.distill import dedupe, maintenance
from app.proxy import inject
from app.store.store import Store

ITEM = {"id": "i1", "text": "命令「npm run build」反复失败，改参重试后才通过"}


def _store(tmp_path, cfg=None):
    s = Store(tmp_path)
    s.ensure_layout()
    if cfg:
        s.save_config(cfg)
    return s


def _entry(store, key="方法/投标", iid="i1"):
    return store.load_injection_hits().get(key, {}).get("items", {}).get(iid, {})


# ---------- P2-6 probation：首次出场带试用数、期满转正、期内反驳即移出 ----------

def test_probation_lifecycle_promote(tmp_path):
    store = _store(tmp_path)
    store.record_injection("方法", "投标", "s0", tokens=5, items=[ITEM])
    e = _entry(store)
    assert e["probation_left"] == 2                       # 首注入即消耗一格（3-1）
    store.record_injection("方法", "投标", "s1", tokens=5, items=[ITEM])
    assert _entry(store)["probation_left"] == 1
    store.record_injection("方法", "投标", "s2", tokens=5, items=[ITEM])
    assert _entry(store).get("probation_left") is None    # 满 3 次注入 → 转正

def test_probation_refute_excludes_immediately(tmp_path):
    store = _store(tmp_path)
    store.record_injection("方法", "投标", "s0", tokens=5, items=[ITEM])
    store.append_experience({"trunk": "方法", "category": "投标",
                             "action": ITEM["text"], "G": 0.3,
                             "corrected": True, "session_id": "x1"})
    e = _entry(store)
    assert e.get("excluded") == 1                        # 试用失败直接移出
    assert e.get("probation_left") is None
    assert "i1" not in [it["id"] for it in
                        inject.selected_experience_items(store, "方法", "投标")]

def test_probation_disabled_by_config(tmp_path):
    store = _store(tmp_path, {"solidify": {"probation_sessions": 0}})
    store.record_injection("方法", "投标", "s0", tokens=5, items=[ITEM])
    assert _entry(store).get("probation_left") is None   # 关掉=不试用


# ---------- P2-7 零采纳降级 ----------

def test_adoption_zero_corroborated_downgrades(tmp_path):
    store = _store(tmp_path, {"solidify": {"probation_sessions": 0}})
    for i in range(5):
        store.record_injection("方法", "投标", f"s{i}", tokens=5, items=[ITEM])
    assert maintenance._evaluate_adoption(store) == (1, 0)
    assert _entry(store)["restricted"] == 1
    for i in range(5, 10):
        store.record_injection("方法", "投标", f"s{i}", tokens=5, items=[ITEM])
    assert maintenance._evaluate_adoption(store) == (0, 1)
    assert _entry(store)["excluded"] == 1

def test_adoption_exempt_when_corroborated(tmp_path):
    store = _store(tmp_path, {"solidify": {"probation_sessions": 0}})
    for i in range(6):
        store.record_injection("方法", "投标", f"s{i}", tokens=5, items=[ITEM])
    store.append_experience({"trunk": "方法", "category": "投标",
                             "action": ITEM["text"], "G": 0.9,
                             "session_id": "use1"})
    assert maintenance._evaluate_adoption(store) == (0, 0)
    assert not _entry(store).get("restricted")


# ---------- P2-8 逐条判据 ----------

def test_item_effect_written_with_enough_sessions(tmp_path):
    store = _store(tmp_path, {"solidify": {"probation_sessions": 0}})
    base = {"agent": "codex", "trunk": "方法", "category": "投标",
            "req_count": 4, "started_at": "2026-09-15T00:00:00Z"}
    for sid, corr in (("w1", 0), ("w2", 1), ("w3", 5), ("w4", 6)):
        store.record_session(dict(base, session_id=sid, correction_hits=corr,
                                  user_messages=["x"], assistant_messages=[]))
    for sid in ("w1", "w2"):                             # 条目只进低修正会话
        store.record_injection("方法", "投标", sid, tokens=5, items=[ITEM])
    assert maintenance._item_effect(store) == 1
    eff = _entry(store)["effect"]
    assert eff["n"] == 2 and eff["delta"] > 0            # 0.5 < 基线 3.0


# ---------- P1-2 三因子排序 + numeric ----------

def _pairs(*texts):
    return [({"id": f"x{i}", "kind": "failure", "last": None,
              "importance": 0}, t) for i, t in enumerate(texts)]

def test_rank_select_relevance_first():
    ps = _pairs("写投标方案先看竞品报价", "npm 构建失败要清缓存", "报销流程走财务系统")
    out = inject._rank_select(ps, "帮我看看npm构建又挂了", top_k=3)
    assert out[0][1].startswith("npm")                   # 相关条目排最前

def test_rank_select_keeps_order_without_task():
    ps = _pairs("a 一", "b 二")
    assert inject._rank_select(ps, None, top_k=3) == ps  # 预览零回归

def test_numeric_keys_registered_and_overridable():
    assert numeric({}, "inject.top_k") == 5
    assert numeric({"inject": {"top_k": 8}}, "inject.top_k") == 8
    assert numeric({"inject": {"top_k": "坏值"}}, "inject.top_k") == 5
    assert set(NUMERIC_DEFAULTS) >= {"inject.top_k", "solidify.probation_sessions",
                                     "events.max_bytes", "adopt.min_injections"}


# ---------- P1-3 语义 upsert 四操作 ----------

def test_upsert_merges_near_duplicate_text(tmp_path):
    store = _store(tmp_path)
    base = {"agent": "codex", "trunk": "编程", "category": "调试",
            "task": "修复登录接口超时问题", "action": "把网关超时从 5s 调到 30s 后通过",
            "G": 0.7, "g_source": "auto", "session_id": "s1"}
    r1, op1 = dedupe.upsert_experience(store, dict(base))
    drift = dict(base, task="修复登录接口超时问题。",
                 action="把网关超时从5s调到30s后通过",
                 session_id="s2", G=0.9)
    r2, op2 = dedupe.upsert_experience(store, drift)
    assert (op1, op2) == ("add", "merge")
    exps = list(store.iter_experiences(include_distilled=True))
    assert len(exps) == 1                                 # 措辞漂移不炸新行
    e = exps[0]
    assert e["count"] == 2 and e["G"] == 0.9
    assert e["task"] == "修复登录接口超时问题"              # 文本不覆盖
    assert e["action"] == "把网关超时从 5s 调到 30s 后通过"

def test_upsert_keeps_different_lessons_separate(tmp_path):
    store = _store(tmp_path)
    dedupe.upsert_experience(store, {"agent": "codex", "trunk": "编程",
                                     "category": "调试", "task": "修 A 坑",
                                     "action": "换依赖版本", "G": 0.7})
    _, op = dedupe.upsert_experience(store, {"agent": "codex", "trunk": "编程",
                                             "category": "调试", "task": "写周报",
                                             "action": "结论先行列数据", "G": 0.7})
    assert op == "add"


# ---------- 质量-9 事件按价值裁剪 ----------

def _bash_msgs(n, start=0, err_at=None):
    msgs = []
    for i in range(start, start + n):
        is_err = (err_at is not None and i == err_at)
        msgs += [
            {"role": "assistant", "tool_use": {"name": "Bash", "call_id": f"c{i}",
             "arguments": json.dumps({"cmd": f"tool run step{i}"})}, "ts": f"t{i:04d}"},
            {"role": "tool", "tool_result": {"call_id": f"c{i}",
             "output": ("boom error: disk full\nProcess exited with code 1"
                        if is_err else "ok\nProcess exited with code 0")},
             "ts": f"t{i:04d}"},
        ]
    return msgs

def test_value_trim_keeps_early_error():
    # 错误行在第 6/120 条（早期）：旧"保尾截头"必挤掉它，价值裁剪必须保住
    evs = derive_events(_bash_msgs(120, err_at=5), max_bytes=1200)
    assert any(e.get("e") == 1 for e in evs), \
        "早期错误行必须活过预算（旧保尾截头会把它挤掉）"

def test_repeat_success_aggregated(tmp_path):
    msgs = []
    for i in range(10):
        msgs.append({"role": "assistant", "tool_use": {
            "name": "Bash", "call_id": f"c{i}",
            "arguments": json.dumps({"cmd": "same cmd"})}, "ts": f"t{i}"})
        msgs.append({"role": "tool", "tool_result": {
            "call_id": f"c{i}", "output": "ok\nProcess exited with code 0"},
            "ts": f"t{i}"})
    evs = derive_events(msgs, max_bytes=8192)
    assert len(evs) == 1 and evs[0]["rep"] == 10          # 重复成功聚合成一条


# ---------- 质量-10 队列溢出归档 ----------

def test_pending_overflow_archived_not_dropped(tmp_path):
    store = _store(tmp_path)
    for i in range(205):
        store.append_pending_review("a", f"s{i}", snippets=["不对 x"],
                                    trunk="t", category="c")
    live = store.load_pending_reviews()
    cold = store.load_pending_archive_records()
    assert len(live) == 200                               # 主队列封顶
    assert len(cold) == 5                                 # 溢出进冷存，不静默丢
    assert cold[0]["session_id"] == "s0"                  # 最老的先进冷存


# ---------- P1-1 模型下载器：sha256 钉死 ----------

def test_model_dl_pins_and_verifies(tmp_path, monkeypatch):
    import io
    from app.semantic import model_dl

    payload = b"fake-onnx-bytes" * 10
    import hashlib
    good_sha = hashlib.sha256(payload).hexdigest()
    name, (src, _sha, _size) = next(iter(model_dl.PINNED.items()))
    monkeypatch.setitem(model_dl.PINNED, name, (src, good_sha, len(payload)))

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): self.close()

    monkeypatch.setattr(model_dl.urllib.request, "urlopen",
                        lambda url, timeout=None: Resp(payload))
    store = _store(tmp_path)
    assert model_dl._fetch_one("http://x", store.dir("models") / name,
                               good_sha, len(payload)) is True
    assert (store.dir("models") / name).read_bytes() == payload
    # 校验和不符 → 拒绝落位
    bad = Resp(b"other-bytes" * 10)
    monkeypatch.setattr(model_dl.urllib.request, "urlopen",
                        lambda url, timeout=None: bad)
    assert model_dl._fetch_one("http://x", store.dir("models") / name,
                               good_sha, len(payload)) is False
    assert not (store.dir("models") / f"{name}.part").exists()
