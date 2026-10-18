"""报告海报单测：spec 构建（确定性）+ PIL PNG 渲染（像素级断言）+ 落盘去重。

spec 与 PNG（PIL）同一 spec 同一布局常量（D.POSTER_*）：
spec 层只测数据与排序，渲染层只测"该出现的颜色/尺寸真的出现了"。
（旧 flet 图表工厂测试已随 flet 栈裁撤删除。）
"""

from app.gui import poster, report_model, theme
import json

from app.gui.i18n import t

GROWTH = {
    "days": 30,
    "cumulative": {"营销/文案写作": [["2026-08-01", 1], ["2026-08-28", 5]]},
    "heatmap": {"trunks": ["营销"], "grid": {"营销": [0.0] * 12 + [1.6, 0.8]},
                "dates": [f"2026-08-{d:02d}" for d in range(15, 29)]},
    # ---------- 全景口径（growth_panorama，海报主角） ----------
    "stage": {"start": "2026-07-04", "end": "2026-09-20", "weeks": 12,
              "active_days": 39, "sessions": 257, "agents": 4, "projects": 59},
    "flywheel": {"collected": 257, "distilled": 82, "judged": 51,
                 "injected": 0, "improved": None},
    "assets": {"experience": 52, "advice": 30, "corrected": 14, "judged": 51,
               "top": 10, "high": 31, "feedback": 0, "total": 82,
               "advice_hits": 172},
    "rework": {"early": 2.14, "recent": 0.35, "drop_pct": 84, "early_n": 14,
               "recent_n": 199, "early_corr": 30, "recent_corr": 69,
               "comparable": True},
    "weekly": [{"week": "2026-08-31", "sessions": 107, "corrections": 28,
                "rate": 0.26},
               {"week": "2026-09-07", "sessions": 65, "corrections": 31,
                "rate": 0.48}],
    "phases": [{"month": "2026-09", "sessions": 185, "corrections": 69,
                "days": 20}],
    "agents": [{"agent": "workbuddy", "n": 236, "corrections": 112,
                "projects": 56, "last": "2026-09-20", "early": 5.0,
                "recent": 0.35, "state": "improved"},
               {"agent": "hermes", "n": 3, "corrections": 0, "projects": 2,
                "last": "2026-08-14", "early": None, "recent": None,
                "state": "few"}],
    "ledger": [{"id": "e1", "task": "跨会话先写交接单", "action": "a",
                "importance": 9, "agent": "workbuddy", "corrected": True,
                "seen": 0, "count": 1, "session_id": "s1"}],
    "advice_items": [{"id": "e2", "task": "sig:Error: File has not been read yet",
                      "state": "Error: File has not been read yet",
                      "count": 44, "seen": 23}],
    "achievements": [],
    # ---------- 旧口径仍在（周报/notify 依赖 + 海报"按任务的磨合"加项） ----------
    "affinity": {
        "codex/营销/文案写作": {"n": 5, "level": "高", "diff": 2,
                            "rounds_diff": -8, "excluded": False,
                            "baseline": {"fix": 5, "req": 12, "tokens": 12000,
                                         "n": 3, "at": "2026-08-11"},
                            "recent": {"fix": 3, "req": 4, "tokens": 9000,
                                       "n": 2, "at": "2026-08-28"},
                            "rounds_pct": -50, "corrections_pct": -40,
                            "sample_note": False,
                            "first": {"req_count": 12, "correction_hits": 5,
                                      "tokens": 12000, "at": "2026-08-11"},
                            "last": {"req_count": 4, "correction_hits": 3,
                                     "tokens": 9000, "at": "2026-08-28"},
                            "timeline": []},
    },
}

PLAYBOOK_MD = (
    "# 营销 / 文案写作 · playbook\n\n"
    "> name: 投放标题方法\n"
    "> created: 2026-06-11\n"
    "> version: 3\n"
    "> updated: 2026-08-21T09:00:00Z\n"
    "> source_exps: e1, e2, e3, e4\n"
    "> confidence: high\n\n"
    "## 标准流程\n1. 确认投放目标\n2. 利益点前置\n\n"
    "## 成功要点\n- 两版 A/B\n\n"
    "## 失败模式\n（无）\n\n"
    "## 偏好增量\n- 结论先行\n"
)


def _growth_spec():
    return poster.growth_poster(report_model.growth_report_model(GROWTH), t)


# ---------- spec 构建（确定性） ----------

def test_growth_poster_block_order():
    """新区块顺序：主句 → 周图 → 飞轮 → 资产 → 助手 → 类别判据 → 三条 → 里程碑 → 脚注。"""
    kinds = [b["type"] for b in _growth_spec()["blocks"]]
    assert kinds == ["headline", "spark", "cells", "cells", "rows", "section",
                     "section", "section", "prov"]


def test_growth_poster_headline_is_rework_drop():
    """海报主角 = 返工降幅（旧版是"某类别少 N 轮"，分类没长出来时永远空壳）。"""
    h = _growth_spec()["blocks"][0]
    assert h["big"] == "84" and h["unit"] == "%"
    assert h["from"] == 2.14 and h["to"] == 0.35
    assert "头两周 14 次任务改 30 回" in h["sub"]


def test_growth_poster_flywheel_shows_zero_injection():
    """第④格 0 必须显式出现在海报上（旧版整条断链无人说）。"""
    gears = _growth_spec()["blocks"][2]["items"]
    assert [g["k"] for g in gears] == ["收进来", "提炼出", "判轻重", "带回给 AI"]
    assert gears[3]["v"] == "0" and gears[3]["tone"] == "bad"


def test_growth_poster_keeps_category_gain_when_present():
    """类别判据是加项不是弃项：有真实改善就出现在海报上。"""
    sec = [b for b in _growth_spec()["blocks"]
           if b.get("label") == "按任务的磨合"]
    assert sec and "少 2 轮修正" in sec[0]["items"][0]


def test_growth_poster_never_leaks_internal_labels():
    """海报不得出现裸内部串（"未分类" / agent 键 / sig: 前缀）。"""
    blob = json.dumps(_growth_spec(), ensure_ascii=False)
    for bad in ("未分类", "sig:", "code_lesson", "agent_friction"):
        assert bad not in blob, bad


def test_growth_poster_empty_only_note_and_band():
    spec = poster.growth_poster(report_model.growth_report_model({"days": 30}), t)
    kinds = [b["type"] for b in spec["blocks"]]
    assert kinds == ["band", "note"]
    assert "还没有成长记录" in spec["blocks"][1]["text"]


def test_growth_poster_celebrates_only_real_unlocks():
    """里程碑庆祝只在真解锁时弹；旧版按 diff≥2 弹。"""
    base = report_model.growth_report_model(GROWTH)
    assert poster.growth_poster(base, t)["has_significant_improvement"] is False
    from datetime import datetime, timezone
    recent = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fresh = dict(GROWTH, achievements=[{"id": "veteran/x", "type": "veteran",
                                        "scope": "codex/营销/文案写作",
                                        "unlocked_at": recent}])
    spec = poster.growth_poster(report_model.growth_report_model(fresh), t)
    assert spec["has_significant_improvement"] is True
    ms = [b for b in spec["blocks"] if "里程碑" in b.get("label", "")]
    assert ms and "老练" in ms[0]["items"][0] and "未分类" not in ms[0]["items"][0]



def test_method_poster_blocks():
    from app.gui import i18n

    i18n.load_catalog("zh")  # t() 占位符格式化依赖 catalog 已加载（不靠其他测试的加载顺序）
    model = report_model.parse_playbook(PLAYBOOK_MD)
    exps = [{"corrected": False, "G": 0.9}, {"corrected": True, "G": 0.9}]
    spec = poster.method_poster(model, exps, t)
    kinds = [b["type"] for b in spec["blocks"]]
    assert kinds[0] == "band"  # 眉条（品牌色渐段）打头
    assert kinds[1] == "meta" and spec["blocks"][1]["conf"] == "high"
    assert kinds[2] == "section"
    sections = [b for b in spec["blocks"] if b["type"] == "section"]
    # 失败模式（无）被跳过；标准流程在前
    assert [s["label"] for s in sections] == ["标准流程", "成功要点", "偏好增量"]
    prov = [b for b in spec["blocks"] if b["type"] == "prov"]
    assert prov and "首次沉淀" in prov[0]["items"][0]
    assert "成功 1 / 踩坑 1" in prov[0]["items"][-2]


# ---------- PNG 渲染（像素级断言） ----------

def _has_color(path, hex_color, step=4):
    from PIL import Image
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    im = Image.open(path)
    px = im.load()
    for y in range(0, im.height, step):
        for x in range(0, im.width, step):
            pr, pg, pb = px[x, y][:3]
            if abs(pr - r) < 12 and abs(pg - g) < 12 and abs(pb - b) < 12:
                return True
    return False


def test_render_png_growth_scale_and_colors(tmp_path):
    """PNG 与弹层同一 spec：宽度 = 720×2；高度只做结构断言（不再锁 1000 魔数）。"""
    spec = _growth_spec()
    out = tmp_path / "g.png"
    poster.render_png(spec, out, scale=2)
    from PIL import Image
    im = Image.open(out)
    assert im.size[0] == theme.D.REPORT_W * 2
    assert im.size[1] > theme.D.REPORT_W  # 内容比画布宽 → 区块确实画出来了
    assert _has_color(out, theme.C.surface)
    assert _has_color(out, theme.C.brand_700)   # 主句大数字
    assert _has_color(out, theme.C.err_bg)      # 第④格红底（回灌 0）
    assert _has_color(out, theme.C.brand_50)    # 飞轮已完成格
    assert _has_color(out, theme.C.ok_fg)       # "明显变顺" chip 字


def test_render_png_method(tmp_path):
    model = report_model.parse_playbook(PLAYBOOK_MD)
    spec = poster.method_poster(model, [], t)
    out = tmp_path / "m.png"
    poster.render_png(spec, out, scale=1)
    from PIL import Image
    im = Image.open(out)
    assert im.size[0] == theme.D.REPORT_W
    # 眉条品牌色（section 圆点） + 置信度 chip 绿底（high → ok_bg）
    assert _has_color(out, theme.C.brand_600)
    assert _has_color(out, theme.C.ok_bg)


def test_render_png_empty_growth_no_crash(tmp_path):
    spec = poster.growth_poster(
        report_model.growth_report_model({"days": 30}), t)
    out = tmp_path / "e.png"
    poster.render_png(spec, out, scale=2)
    from PIL import Image
    assert Image.open(out).size[0] == theme.D.REPORT_W * 2


def test_save_png_dedup_names(tmp_path):
    p1 = poster.save_png(str(tmp_path), "成长报告-2026-08-31.png")
    p1.parent.mkdir(parents=True, exist_ok=True)
    p1.write_bytes(b"x")
    p2 = poster.save_png(str(tmp_path), "成长报告-2026-08-31.png")
    assert p2.name == "成长报告-2026-08-31-1.png"
