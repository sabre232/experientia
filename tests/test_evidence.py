"""证据锚点测试（P0-2，纪律 D3：没有原话就不入库）。

覆盖三件事：定位判定准不准、写入闸拦不拦、以及"用户确认豁免"这条后门
不会被顺手焊死。
"""

from app.distill import evidence, gsignal, review
from app.capture import self_experience as se
from app.store.store import Store

SESSION = {
    "agent": "codebuddy", "session_id": "s-1", "trunk": "前端", "category": "性能",
    "user_messages": ["首屏很慢，帮我看看", "这样改可以了"],
    "assistant_messages": ["我把图片转成了 WebP，LCP 从 4.2s 降到 1.8s"],
    "correction_hits": 0, "req_count": 3,
}


def _store(tmp_path):
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


# ---------- 定位 ----------

def test_locate_finds_quote_with_role_and_index():
    hit = evidence.locate(SESSION, "我把图片转成了 WebP")
    assert hit["role"] == "assistant" and hit["index"] == 0
    u = evidence.locate(SESSION, "首屏很慢")
    assert u["role"] == "user" and u["index"] == 0


def test_locate_misses_fabricated_quote():
    """编出来的引用定位不到——这正是防幻觉要的那种"定位不到"。"""
    assert evidence.locate(SESSION, "用户说这个方案绝对没问题") is None
    assert evidence.locate(SESSION, "") is None
    assert evidence.locate("not a dict", "首屏") is None


def test_from_candidate_rejects_short_fabricated_quote():
    """：短引用当不了候选证据。

    模型编个 2 字引用（"好的"）即可被任意消息包含 → quote_verified=True →
    进 L3_CAUSAL 高信任档。locate 本身保持纯定位语义（确认短句是合法原话），
    长度闸拦在候选边界。
    """
    assert evidence.from_candidate({"evidence": "好的"}, SESSION) is None
    assert evidence.from_candidate({"evidence": "很慢"}, SESSION) is None
    # 足够长的真实引用不受影响
    assert evidence.from_candidate({"evidence": "我把图片转成了 WebP"},
                                   SESSION) is not None


def test_locate_tolerates_whitespace_diff():
    assert evidence.locate(SESSION, "我把图片  转成了\nWebP，LCP 从 4.2s 降到 1.8s") is not None


# ---------- 构造 ----------

def test_from_candidate_requires_locatable():
    assert evidence.from_candidate({"evidence": "我把图片转成了 WebP"}, SESSION) is not None
    assert evidence.from_candidate({"evidence": "用户非常满意"}, SESSION) is None
    assert evidence.from_candidate({}, SESSION) is None


def test_from_confirm_close_uses_last_user_message():
    ev = evidence.from_confirm_close(SESSION)
    assert ev["quote"] == "这样改可以了"
    assert ev["source"] == "session"
    assert ev["at"]["role"] == "user" and ev["at"]["index"] == 1


def test_capture_fallback_requires_explicit_flag():
    """兜底只在调用方声明"原文即证据"时启用——否则任何会话都能靠兜底过关。"""
    # 用"没有明确验收收尾"的会话：否则 confirm 优先级更高，根本走不到 capture
    plain = {**SESSION, "user_messages": ["首屏很慢，帮我看看", "先这样吧"]}
    assert "先这样吧" not in gsignal._CONFIRM_CLOSE_WORDS
    assert not gsignal._is_confirmatory_closing(plain)
    sess = dict(plain, evidence_fallback="capture")
    assert evidence.from_capture(plain) is not None
    ev, kind = evidence.resolve({}, sess)
    assert (kind, ev["source"]) == ("capture", "capture")
    # 没声明 → 不给兜底
    ev2, kind2 = evidence.resolve({}, plain)
    assert (ev2, kind2) == (None, "none")


def test_resolve_priority_candidate_over_confirm():
    ev, kind = evidence.resolve({"evidence": "我把图片转成了 WebP"}, SESSION)
    assert kind == "candidate"


# ---------- 存量兼容 ----------

def test_normalize_wraps_old_string_evidence():
    ev = evidence.normalize("一条老字符串证据")
    assert ev["quote"] == "一条老字符串证据" and ev["locatable"] is None
    assert evidence.normalize(None) is None
    assert evidence.normalize({"quote": "结构体原样"})["quote"] == "结构体原样"
    assert evidence.quote_of({"evidence": "老字符串"}) == "老字符串"
    assert evidence.quote_of({"evidence": {"quote": "结构体"}}) == "结构体"
    assert evidence.quote_of({}) == ""


# ---------- 写入闸 ----------

def test_gate_user_confirmation_is_exempt():
    """用户确认 = 最高信任，不要求带 quote（这条后门不能焊死）。"""
    ok, why = evidence.gate({"G": 1.0, "g_source": "user", "trunk": "其他"})
    assert ok is True and why == "user"


def test_gate_lets_below_threshold_through():
    """G 本就不达标的记录走失败候选池，闸门不再重复设卡。"""
    ok, why = evidence.gate({"G": 0.2, "g_source": "auto"})
    assert ok is True and why == "below-threshold"


def test_gate_blocks_injectable_without_quote():
    ok, why = evidence.gate({"G": 0.7, "g_source": "auto", "evidence_state": "missing"})
    assert ok is False and why == "no-evidence"
    ok2, _ = evidence.gate({"G": 0.8, "g_source": "judge"})
    assert ok2 is False


# ---------- 与复盘/提交流程的衔接 ----------

def test_process_candidate_attaches_structural_evidence(tmp_path):
    """验收收尾的会话：证据 = 最后一条用户消息（零模型成本的确定性锚点）。"""
    rec = review._process_candidate(
        {"task": "优化首屏", "state": "LCP 慢", "action": "图片转 WebP",
         "outcome": "LCP 降到 1.8s"}, dict(SESSION), _store(tmp_path))
    assert rec is not None
    assert rec["evidence"]["quote"] == "这样改可以了"
    assert rec["evidence_kind"] == "confirm"
    assert "evidence_state" not in rec


def test_process_candidate_marks_missing_evidence(tmp_path):
    """没有验收收尾、模型也没引用 → 标 missing，由写入闸决定去向。"""
    sess = {**SESSION, "user_messages": ["首屏很慢，帮我看看", "先这样吧"]}
    rec = review._process_candidate(
        {"task": "优化首屏", "state": "LCP 慢", "action": "图片转 WebP",
         "outcome": "LCP 降到 1.8s", "causal": True}, sess, _store(tmp_path))
    assert rec["evidence_state"] == "missing"


def test_gate_backstop_blocks_injectable_without_quote(tmp_path):
    """写入闸的定位是**兜底**，不是主力。

    复盘管线在"引用不可信 → 扣信任分"改造后，已经产不出"会进注入块却没证据"
    的记录了；但别的入口（未来新通道、外部构造的 rec）仍可能造出这种记录，
    所以这道闸必须留着——它拦的是"万一"。
    """
    store = _store(tmp_path)
    rec = {"task": "优化首屏", "action": "图片转 WebP", "G": 0.7,
           "g_source": "auto", "trunk": "前端", "category": "页面性能"}
    stored, route = review.commit_candidate(rec, store)
    assert route == "draft"
    assert stored["draft_reason"] == "no-evidence"
    assert list(store.iter_experiences()) == []
    assert store.draft_count("pending") == 1


def test_commit_candidate_keeps_verifiable_causal(tmp_path):
    """同一场景但引文真能在会话里定位到 → 正常入库（闸门不误伤）。"""
    store = _store(tmp_path)
    rec = review._process_candidate(
        {"task": "优化首屏", "state": "LCP 慢", "action": "图片转 WebP",
         "outcome": "LCP 降到 1.8s", "causal": True,
         "evidence": "我把图片转成了 WebP，LCP 从 4.2s 降到 1.8s"},
        SESSION, store)
    assert "evidence_state" not in rec
    assert rec["evidence"]["locatable"] is True
    stored, route = review.commit_candidate(rec, store)
    assert route == "experience" and stored["id"]
    assert store.draft_count("pending") == 0


def test_fabricated_quote_gets_no_causal_credit(tmp_path):
    """引文造假 → 该候选**不按"已证实的因果"计分**，也拿不到那句假引文。

    冒烟测试抓到过这个漏洞：假引文被丢掉，但 G 仍按 0.8 发——等于造了句
    假话还拿满信任分。现在：定位不到的引用等同"没附证据"。
    """
    store = _store(tmp_path)
    rec = review._process_candidate(
        {"task": "优化首屏", "state": "LCP 慢", "action": "图片转 AVIF",
         "outcome": "更快", "causal": True, "importance": 8,
         "evidence": "用户明确说 AVIF 方案绝对没问题"},
        SESSION, store)
    # 会话有明确验收收尾 → 落在确定性成功档（0.7），而非"已证实因果"（0.8）
    assert rec["G"] == gsignal.L2_CLEAN
    assert rec["evidence_kind"] == "confirm"
    # 那句假引文一个字都不许留下
    assert "AVIF 方案" not in str(rec.get("evidence"))


def test_fabricated_quote_drops_below_threshold(tmp_path):
    """没有验收收尾兜底时，假引文直接把候选压到注入线下。"""
    store = _store(tmp_path)
    plain = {**SESSION, "user_messages": ["首屏很慢，帮我看看", "先这样吧"]}
    rec = review._process_candidate(
        {"task": "优化首屏", "state": "LCP 慢", "action": "图片转 AVIF",
         "outcome": "更快", "causal": True,
         "evidence": "用户明确说 AVIF 方案绝对没问题"},
        plain, store)
    assert rec["G"] == gsignal.L3_WEAK        # 0.4 < 0.5，入不了注入块
    assert rec["evidence_state"] == "missing"


def test_commit_candidate_keeps_quoted_ones(tmp_path):
    store = _store(tmp_path)
    rec = review._process_candidate(
        {"task": "优化首屏", "state": "LCP 慢", "action": "图片转 WebP",
         "outcome": "LCP 降到 1.8s"}, SESSION, store)
    stored, route = review.commit_candidate(rec, store)
    assert route == "experience"
    assert stored["id"]
    assert store.draft_count("pending") == 0


def test_self_report_gets_capture_evidence(tmp_path):
    """自报原文本身就是被蒸馏材料 → capture 溯源（不是模型判断可信）。"""
    store = _store(tmp_path)
    note = {"task": "接入模型", "model": "m", "session_id": "s"}
    rec = se._rec_for(store, "trae", "用 A 方式配置最稳，别用 B。", note, 0.8, "auto")
    assert rec["evidence"]["source"] == "capture"
    assert "A 方式配置最稳" in rec["evidence"]["quote"]
    stored, route = review.commit_candidate(rec, store)
    assert route == "experience"


def test_adopt_path_still_works(tmp_path):
    """用户放行（g_source=user）不受写入闸影响。"""
    store = _store(tmp_path)
    r = se.process(store, "trae", {"task": "接入新模型",
                                   "conclusion": "用 A 方式配置最稳",
                                   "pitfalls": "别用 B"})
    assert r["status"] == "pending"
    res = se.adopt(store, r["draft"]["id"])
    assert res["ok"] is True
    exp = store.find_experience(res["exp_id"])
    assert exp["g_source"] == "user" and exp["G"] == 1.0
