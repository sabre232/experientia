"""通知中心二期：优先级裁决 / 磨合度新高 / 蒸馏触发 / 每日检查。"""

from datetime import datetime

from app import notify
from app.notify import push
from app.store.store import Store


def _store(tmp_path) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    return s


# ---------- 优先级裁决（每日上限） ----------

def test_over_cap_stays_in_list_without_slot(tmp_path):
    store = _store(tmp_path)
    push(store, "daily_summary", "总结")
    push(store, "system_notice", "洞察")
    rec = push(store, "method_update", "新方法")
    assert rec is not None and rec["counted"] is True
    items = {it["title"]: it for it in notify.list_notifications(store)}
    # 高优先级挤掉当天最低的一条（洞察 > 总结的低者 = 洞察）
    assert items["洞察"]["counted"] is False
    assert items["总结"]["counted"] is True
    assert items["新方法"]["counted"] is True


def test_cap_full_of_higher_prio_keeps_new_in_list_only(tmp_path):
    store = _store(tmp_path)
    push(store, "method_update", "沉淀")
    push(store, "method_update", "新方法")
    # 第三条与已有最高优先级相同，无更低优先级可挤，只进列表
    rec = push(store, "method_update", "新坑")
    assert rec is not None and rec["counted"] is False
    items = {it["title"]: it for it in notify.list_notifications(store)}
    assert items["沉淀"]["counted"] is True
    assert items["新方法"]["counted"] is True
    assert items["新坑"]["counted"] is False


def test_push_records_target(tmp_path):
    store = _store(tmp_path)
    rec = push(store, "method_update", "x", target="methods")
    assert rec["target"] == "methods"


# ---------- 托盘弹窗受每日额度约束（M5：弹窗与列表同受 DAILY_CAP 管） ----------

def _popup_filter():
    """延迟 import：staticmethod 不需要 QApplication，但模块 import 会拉 PySide6。"""
    from app.gui.main_window import MainWindow

    return MainWindow._poppable_notices


def test_over_cap_notice_not_poppable(tmp_path):
    """第三条 method_update 超额度（counted=False）→ 不进弹窗，只躺在列表。"""
    store = _store(tmp_path)
    push(store, "method_update", "沉淀")
    push(store, "method_update", "升级")
    push(store, "method_update", "新坑")   # 超 2 条额度，counted=False
    items = notify.list_notifications(store)
    poppable = {it["title"] for it in _popup_filter()(items)}
    assert poppable == {"沉淀", "升级"}          # 占额度的两条才弹
    assert "新坑" not in poppable


def test_system_notice_always_poppable_even_uncounted(tmp_path):
    """系统通知不计入每日上限：counted=False 也照样弹窗。"""
    store = _store(tmp_path)
    rec = push(store, "system_notice", "洞察")
    assert rec["counted"] is False
    poppable = {it["title"] for it in _popup_filter()(
        notify.list_notifications(store))}
    assert poppable == {"洞察"}


def test_poppable_count_never_exceeds_daily_cap(tmp_path):
    """一天推满 6 条普通通知，弹窗候选（占额度）始终 ≤ DAILY_CAP=2。"""
    store = _store(tmp_path)
    for i in range(6):
        push(store, "daily_summary", f"s{i}")
    poppable = _popup_filter()(notify.list_notifications(store))
    assert len(poppable) <= notify.DAILY_CAP



def test_notify_config_only_carries_type_switches():
    """配置只输出「内容类型」开关，残留的推送形态类键（desktop_popup）被过滤。"""
    assert set(notify.notify_config({})) == set(notify.NOTIFY_TYPES)
    cfg = notify.notify_config({"notify": {"desktop_popup": False,
                                           "method_update": False}})
    assert "desktop_popup" not in cfg
    assert cfg["method_update"] is False


# ---------- 磨合度新高（档位记忆 + 上升沿） ----------

def _aff(level, key="codex/营销/文案写作"):
    # affinity 键 = agent/trunk/category（3 段；2 段会被迁移检测误判）
    return {key: {"level": level, "n": 5, "rounds_pct": -40,
                  "first": {"req_count": 12, "at": "2026-08-01"},
                  "last": {"req_count": 6, "at": "2026-08-28"}}}


def test_growth_edges_fire_only_rise_to_mid_or_high(tmp_path):
    store = _store(tmp_path)
    assert notify.growth_edges(store, _aff("低")) == []  # 低档不推
    assert notify.growth_edges(store, _aff("中")) == [
        ("codex/营销/文案写作", "低", "中")]
    assert notify.growth_edges(store, _aff("中")) == []  # 同档不重推
    assert notify.growth_edges(store, _aff("高")) == [
        ("codex/营销/文案写作", "中", "高")]
    assert notify.growth_edges(store, _aff("低")) == []  # 回落静默
    assert notify.growth_edges(store, _aff("中")) == [
        ("codex/营销/文案写作", "低", "中")]  # 再升可重推


# ---------- 蒸馏触发（method_new / upgrade / failure_new / preference_new） ----------

CANNED_V1 = (
    "## 标准流程\n1. 确认投放目标\n\n## 成功要点\n- 利益点前置\n\n"
    "## 失败模式\n- [Solidified] 纯情绪文案点击率低（出现 3 次）\n\n"
    "## 偏好增量\n- 结论先行\n"
)
CANNED_V2 = (
    "## 标准流程\n1. 确认投放目标\n2. 利益点前置\n\n## 成功要点\n- 两版 A/B\n\n"
    "## 失败模式\n- [Solidified] 纯情绪文案点击率低（出现 3 次）\n"
    "- [Solidified] 标题超 20 字被截断（出现 2 次）\n\n## 偏好增量\n（无）\n"
)


def _distill_store(tmp_path, monkeypatch, canned):
    # 模型路径需要配置（switcher：没配走确定性降级，canned 的失败模式/偏好不会出现）
    store = _store(tmp_path)
    store.save_config({"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                            "type": "local", "model": "qwen"}},
                       "default_model": "local"})
    store.append_experience({"agent": "codex", "task": "写标题",
                             "action": "利益点前置", "G": 0.8, "g_source": "judge",
                             "trunk": "营销", "category": "文案写作"})
    monkeypatch.setattr("app.distill.llm.call_model",
                        lambda store, messages, **kw: canned)
    return store


def _titles(store):
    return [it["title"] for it in notify.list_notifications(store)]


def test_distill_first_pushes_method_new_failure_pref(tmp_path, monkeypatch):
    from app.distill import engine_curation

    store = _distill_store(tmp_path, monkeypatch, CANNED_V1)
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["version"] == 1
    items = notify.list_notifications(store)
    # 统一为 method_update 类型，标题含新坑和偏好数
    assert any(it["title"].startswith("方法动态：营销/文案写作") for it in items)
    body = items[0].get("body", "")
    assert "新方法沉淀" in body
    assert "新坑固化" in body
    assert "偏好新增" in body


def test_distill_second_pushes_upgrade_and_new_failure_only(tmp_path, monkeypatch):
    from app.distill import engine_curation

    store = _distill_store(tmp_path, monkeypatch, CANNED_V1)
    engine_curation.distill(store, "营销", "文案写作")
    store.append_experience({"agent": "codex", "task": "第二个标题",
                             "action": "A/B 两版", "G": 0.7, "g_source": "judge",
                             "trunk": "营销", "category": "文案写作"})
    monkeypatch.setattr("app.distill.llm.call_model",
                        lambda store, messages, **kw: CANNED_V2)
    r = engine_curation.distill(store, "营销", "文案写作")
    assert r["version"] == 2
    items = notify.list_notifications(store)
    # 两次蒸馏各 1 条 method_update（升级 + 新坑）
    assert sum(1 for it in items if it["type"] == "method_update") >= 1
    latest = items[0]  # 新在前
    assert latest["title"].startswith("方法动态：营销/文案写作")
    body = latest.get("body", "")
    assert "方法升级" in body
    assert "标题超 20 字被截断" in body or "标题超" in body


# ---------- 每日检查（21:00 总结 + 成长扫描，幂等） ----------

def test_daily_summary_pushes_only_with_data(tmp_path):
    import daemon as engine

    empty = _store(tmp_path)
    engine._daily_summary(empty)
    assert notify.list_notifications(empty) == []

    store = _store(tmp_path)
    # ts 显式给本地今天：默认 ts 是 UTC，_daily_summary 按本地"今天"聚合
    # （面向用户语义），UTC+8 跨午夜 00:00-08:00 默认 ts 会差一天
    from datetime import datetime as _dt

    store.append_experience({"agent": "codex", "task": "写标题", "action": "x",
                             "G": 0.3, "g_source": "auto", "corrected": True,
                             "trunk": "营销", "category": "文案写作",
                             "ts": _dt.now().date().isoformat() + "T12:00:00Z"})
    engine._daily_summary(store)
    items = notify.list_notifications(store)
    assert len(items) == 1
    assert items[0]["type"] == "daily_summary"
    assert "新增 1 条经验" in items[0]["title"]
    assert "0 张坑卡" in items[0]["title"]      # 坑卡=rule 源
    assert "1 条被纠正" in items[0]["title"]
    assert "待蒸馏 1 条" in items[0]["title"]


def test_daily_checks_idempotent_and_21_gate(tmp_path, monkeypatch):
    import daemon as engine

    store = _store(tmp_path)
    store.append_experience({"agent": "codex", "task": "写标题", "action": "x",
                             "G": 0.8, "g_source": "judge",
                             "trunk": "营销", "category": "文案写作"})

    class _DT21(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 1, 21, 5)

    class _DT09(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 1, 9, 5)

    # 21:00 前：成长扫描照跑，总结不发
    monkeypatch.setattr("daemon.datetime", _DT09)
    engine.daily_checks(store)
    types9 = [it["type"] for it in notify.list_notifications(store)]
    assert "daily_summary" not in types9

    # 21:00 后：补发总结；再跑一遍幂等（不重发）
    monkeypatch.setattr("daemon.datetime", _DT21)
    engine.daily_checks(store)
    n1 = len(notify.list_notifications(store))
    engine.daily_checks(store)
    assert len(notify.list_notifications(store)) == n1
    assert "daily_summary" in [it["type"]
                               for it in notify.list_notifications(store)]


def test_growth_notice_copy_v2_diff(tmp_path, monkeypatch):
    """v2 口径：正文 = 磨合差值（少 N 轮修正），不再用百分比对比。"""
    import daemon as engine

    store = _store(tmp_path)
    # 直接喂 affinity（不依赖 growth_summary 的 session 数据）
    aff = {"营销/文案写作": {"level": "高", "n": 5, "diff": 3,
                             "excluded": False, "sample_note": True,
                             "baseline": {"fix": 5, "req": 9,
                                          "at": "2026-08-01"},
                             "recent": {"fix": 2, "req": 7,
                                       "at": "2026-08-28"}}}
    monkeypatch.setattr(Store, "growth_summary", lambda self, days=30: {"affinity": aff})
    engine._daily_growth_notices(store)
    items = notify.list_notifications(store)
    assert len(items) == 1
    assert items[0]["type"] == "growth_report"
    assert items[0]["title"] == "「文案写作」磨合度新高：待积累 → 高"
    assert "比最初几次平均少 3 轮修正（近 5 次）" in items[0]["body"]
    assert "（样本 5 次，结论仅供参考）" in items[0]["body"]
    assert items[0]["target"] == "growth"


def test_state_patch_keeps_sibling_fields(tmp_path):
    """state_patch 只动指定字段，不覆盖同一状态键里的其它字段。

    daily_checks 的四个每日任务同写 "daily"（保留清理 / 成长通知 / 今日总结 /
    档 C），各持一份过时快照时用 state_set（整字典替换）会互相回退——实测
    pruned_date 每天被成长通知抹回昨天，同一份全量清理一天白跑两遍。
    """
    store = _store(tmp_path)
    notify.state_set(store, "daily",
                     {"pruned_date": "2026-10-12", "growth_date": "2026-10-12"})

    notify.state_patch(store, "daily", growth_date="2026-10-13")

    assert notify.state_get(store, "daily") == {
        "pruned_date": "2026-10-12", "growth_date": "2026-10-13"}
    # 空补丁不落任何改动
    notify.state_patch(store, "daily")
    assert notify.state_get(store, "daily") == {
        "pruned_date": "2026-10-12", "growth_date": "2026-10-13"}
