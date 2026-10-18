"""报告海报：一份 spec，两个渲染器（应用内 Qt 弹层 + PIL PNG 导出）。

设计口径（frontend-design / taste-skill / ui-ux-pro-max 收敛，token 全部走 theme）：
- 海报有主角：改善最大的类别用 display 级大数字（方向色配数字+箭头，不只靠颜色）
- 结构即信息：眉条（14 格热度）→ 主角 → 佐证（横条/柱状图）→ 溯源脚注
- Qt 与 PNG 同一 spec 同一布局常量（D.POSTER_*），所见即所导
- 无 LLM；Qt 侧仅主角块一次入场淡入（PNG 无动画，静态图不需要）
- 无模型且仍有历史内容 → 顶部挂溯源条（provenance_bar 口径单一出口）
- PNG 用系统 CJK 字体（只按路径探测，不打包字体）
"""

from __future__ import annotations

import datetime
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QVBoxLayout, QWidget)


from .i18n import t
from .qt_icons import icon_widget
from .qt_theme import chip, provenance_bar, rework_chart, txt
from .theme import ANIMATION, C, D, F, R, S, SIZES, MASCOTS, motion_ok

# ---------- 溯源（契约见总纲 /） ----------


def _prov_state(src, gen, has_content: bool) -> dict:
    """海报/周卡共用的 provenance_bar 入参（口径同）。"""
    return {"content_source": str(src or ""),
            "generated_at": str(gen or ""),
            "has_content": bool(has_content)}


def _provnote_block(state: dict, tf) -> dict | None:
    """无模型且有历史内容 → 一条顶部降级条 block；否则 None（不打扰）。

    block 同时带 ``state``（Qt 侧交给 ``provenance_bar`` 渲染，口径单一出口）
    与 ``text``（PNG 侧没有 QWidget，用同一句文案画带）。
    """
    if str(state.get("content_source") or "") != "none" or not state.get("has_content"):
        return None
    gen = str(state.get("generated_at") or "").strip()
    # 占位符刻意叫 at 不叫 t：t 是本项目的翻译函数名，同名占位符一旦被误写成
    # 位置传参就会把函数本身格式化进正文。
    text = (tf("未接入模型 · 内容为 {at} 生成 · 接入后可更新", at=gen) if gen
            else tf("未接入模型 · 内容为上次生成 · 接入后可更新"))
    return {"type": "provnote", "state": state, "text": text}


def _poster_entrance(widget: QWidget) -> None:
    """海报主角出场：透明度 0→1（``motion_ok()`` 为假则不动，直接终态）。

    只挂主角块一个控件——``QGraphicsOpacityEffect`` 对整页/滚动区开销大且
    易与子控件绘制冲突（见 qt_widgets.AnimatedStack 的同一取舍）。
    """
    if not motion_ok():
        return
    try:
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", widget)
        anim.setDuration(int(ANIMATION.DURATION_DIALOG * 1000))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        try:
            anim.setEasingCurve(QEasingCurve(
                getattr(QEasingCurve.Type, ANIMATION.EASE_OUT_CUBIC)))
        except Exception:  # noqa: BLE001 令牌异常退回线性，不阻断出场
            anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.Linear))
        widget._entrance_anim = anim  # 保引用防 GC
        anim.start()
    except Exception:  # noqa: BLE001 fail-open：动画失败也必须可见
        widget.setGraphicsEffect(None)

# ---------- spec 构建（纯数据：report_model 输出 + 视图层拼好的文案） ----------


def growth_poster(m: dict, t) -> dict:
    """growth 报告模型 → 海报 spec（m = report_model.growth_report_model 输出）。

    t = 当前语言的 i18n 函数（PNG 与弹层同一语言）。

    重构思：主角从"某类别磨合差值"换成**返工降幅**（growth_story 单一
    口径）。旧版真机渲出来是空壳——4 个「未分类·低」chip + 1 根条 + 13 空 1 满
    柱图，因为按类别聚合的维度还没长出来。新区块顺序：
    主句（大数字）→ 迷你周图 → 飞轮四格 → 资产两格 → 助手对照 → 最值钱三条
    → 里程碑（没解锁就说差多少）→ 溯源脚注。"""
    s = m.get("story") or {}
    h = s.get("headline") or {}
    blocks: list[dict] = []

    if not s.get("has_data"):
        blocks.append({"type": "band"})
        blocks.append({"type": "note", "tone": "neutral",
                       "text": t("（还没有成长记录——用 agent 干几个活，这张图就有内容了）")})
        return {"kind": "growth", "title": t("成长报告"), "blocks": blocks,
                "has_significant_improvement": False}

    # ⓪ 溯源条：无模型且仍有历史内容时置顶说明"内容为上次生成"；
    # 正常态（有模型/来源未知）→ None，不打扰（旧响应没有该字段 = 来源未知）。
    prov = _provnote_block(_prov_state(m.get("content_source"),
                                       m.get("generated_at"),
                                       bool(s.get("has_data"))), t)
    if prov:
        blocks.append(prov)

    # ① 主句：大数字 + 早/近窗口对照（海报唯一主角）
    blocks.append({
        "type": "headline",
        "label": h.get("label") or "",
        "big": h.get("big") or "", "unit": h.get("unit") or "",
        "sub": h.get("sub") or "",
        "from": h.get("from"), "to": h.get("to"),
        "range": s.get("range_short", ""),
    })
    # ② 迷你周图：柱 = 每周任务数，线 = 每任务返工回数（空周不连线）
    if s.get("spark"):
        blocks.append({"type": "spark", "rows": s["spark"],
                       "caption": t("柱 = 每周任务数 · 线 = 返工回/次")})
    # ③ 飞轮四格
    blocks.append({"type": "cells", "label": t("经验飞轮转到哪了"),
                   "items": [{"k": x["k"], "v": x["v"], "u": x["u"],
                             "note": x["note"], "tone": x["tone"]}
                            for x in s.get("gears") or []]})
    # ④ 资产两格（与首页同口径）
    blocks.append({"type": "cells", "label": t("这段时间攒下的东西"),
                   "wide": True,
                   "items": [{"k": x["k"], "v": x["v"], "u": x["u"],
                             "note": x["note"], "tone": x["tone"]}
                            for x in s.get("assets") or []]})
    # ⑤ 助手对照（B 的表格：谁真的变顺了、谁本来就顺、谁样本不够）
    if s.get("agents"):
        blocks.append({"type": "rows", "label": t("几个助手各自的磨合"),
                       "head": [t("助手"), t("任务"), t("纠正"), t("头两周 → 最近")],
                       "rows": [{"name": r["name"],
                                 "cols": [f"{r['n']}", f"{r['corr']}", r["trend"]],
                                 "chip": r["chip"], "tone": r["tone"]}
                                for r in s["agents"]]})
    # ⑤.5 按任务类别的磨合差值
    if s.get("category_gain"):
        blocks.append({"type": "section", "tone": "plain",
                       "label": t("按任务的磨合"), "items": list(s["category_gain"])})
    # ⑥ 最值钱的三条（plain 段：不画勾，避免"已验证"的误读）
    if s.get("top"):
        blocks.append({"type": "section", "tone": "plain",
                       "label": t("最值钱的三条经验"),
                       # 「N 分 · 标题」原为 f-string 硬编码中文，
                       # 非中文界面里"分"与"·"滞留——改走词条（分隔符也译）。
                       "items": [t("{badge} 分 · {text}", badge=x["badge"],
                                   text=x["text"]) for x in s["top"]]})
    # ⑦ 里程碑：解锁了就庆祝，没解锁就写差多少
    ms = s.get("milestones") or {}
    lines = ms.get("unlocked") or ms.get("next") or []
    blocks.append({"type": "section", "tone": "plain",
                   "label": (t("里程碑") if ms.get("unlocked")
                             else t("里程碑 · 还没解锁")),
                   "items": list(lines)})
    # ⑧ 脚注
    blocks.append({"type": "prov", "items": [s.get("counts") or ""]})
    return {"kind": "growth", "title": t("成长报告"), "blocks": blocks,
            "has_significant_improvement": bool(ms.get("has_new"))}


def method_poster(model: dict, exps: list[dict], t, fallback: str | None = None) -> dict:
    """方法论报告模型 → 海报 spec（model = report_model.parse_playbook 输出）。

    exps = 该类别经验列表（溯源用，口径与 report_view._prov_lines 相同）；
    fallback = playbook 无显示名时的标题（两级路径 trunk / category）。"""
    head = model["head"]
    # 眉条：品牌色 14 格渐段（纯装饰，非数据）——与 Flet 版同口径（原 _ft_band）
    blocks: list[dict] = [{"type": "band"}]
    meta = []
    if head.get("updated"):
        meta.append(t("v{v} · 更新 {d}", v=head.get("version") or "?",
                      d=head["updated"][:10]))
    if model["source_n"]:
        meta.append(t("来自 {n} 条记录", n=model["source_n"]))
    blocks.append({"type": "meta",
                   "conf": head.get("confidence"),
                   "text": " · ".join(meta)})
    # 溯源条：正文是旧的本机产物（无模型）时置顶说明；正常态不打扰。
    has_body = bool(head.get("name")) or any(model["sections"].values())
    provnote = _provnote_block(_prov_state(head.get("content_source"),
                                           head.get("generated_at"), has_body), t)
    if provnote:
        blocks.append(provnote)
    for name, lines in _method_sections(model):
        blocks.append({"type": "section", "label": t(name),
                       "tone": "err" if name == "失败模式" else "neutral",
                       "items": lines[:6]})
    prov = _prov_lines(head, exps, t)
    if prov:
        blocks.append({"type": "prov", "items": prov})
    if not model["head"].get("name") and not any(
            b["type"] == "section" for b in blocks):
        blocks.append({"type": "note", "tone": "neutral",
                       "text": t("（这个方法的正文还是空的，先总结一次）")})
    name = head.get("name") or fallback or t("方法")
    return {"kind": "method", "title": name, "blocks": blocks}


def _method_sections(model: dict) -> list[tuple[str, list[str]]]:
    from .report_model import method_sections
    return method_sections(model)


def _prov_lines(head: dict, exps: list[dict], t) -> list[str]:
    """溯源行（与 report_view._prov_lines / export.py 同口径，方案 A）。"""
    out: list[str] = []
    if head.get("created"):
        out.append(t("首次沉淀：{d}", d=head["created"][:10]))
    if head.get("updated"):
        out.append(t("最近更新：{d}（v{v}）", d=head["updated"][:10],
                     v=head.get("version"))
                   if head.get("version") else t("最近更新：{d}", d=head["updated"][:10]))
    if exps:
        fails = sum(1 for e in exps if (e.get("corrected") or
                    (e.get("G") is not None and float(e["G"]) < 0.5)))
        out.append(t("沉淀依据 {n} 条经验（成功 {s} / 踩坑 {f}），可在经验库按类别回看",
                     n=len(exps), s=len(exps) - fails, f=fails))
    conf = head.get("confidence")
    if conf in ("high", "medium", "low"):
        label = {"high": "已验证", "medium": "部分验证", "low": "待验证"}[conf]
        out.append(t("置信度：{c}", c=t(label)))
    return out


# ---------- Qt 渲染器（弹层内容） ----------


def _col(*children, spacing: int = S.s1) -> QWidget:
    """垂直容器（对应 ft.Column）。"""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for c in children:
        lay.addWidget(c)
    return box


def _row(*children, spacing: int = S.s2) -> QWidget:
    """水平容器（对应 ft.Row）。"""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for c in children:
        lay.addWidget(c)
    return box


def to_controls(spec: dict) -> tuple[list[QWidget], list[QWidget], list[QWidget]]:
    """三层结构：(layer_1, layer_2, layer_3)。
    layer_1: 眉条/热度（band/masthead）
    layer_2: 主角区（meta + hero + chips + note）
    layer_3: 佐证区（hbars + columns + section + prov）
    """
    l1, l2, l3 = [], [], []
    for b in spec["blocks"]:
        bt = b["type"]
        if bt == "band":
            l1.append(heat_row(_BAND_SCALE))
        elif bt == "meta":
            items = []
            if b.get("conf") in ("high", "medium", "low"):
                label = {"high": "已验证", "medium": "部分验证", "low": "待验证"}[b["conf"]]
                tone = {"high": "ok", "medium": "warn", "low": "brand"}[b["conf"]]
                items.append(chip(t(label), tone))
            if b.get("text"):
                items.append(txt(b["text"], F.caption, color=C.ink_500))
            if items:
                l2.append(_row(*items, spacing=S.s2))
        elif bt == "section":
            is_err = b.get("tone") == "err"
            bar = QFrame()
            bar.setFixedWidth(D.BORDER_W)
            bar.setFixedHeight(F.h2)
            bar.setStyleSheet(
                f"background: {C.err_fg if is_err else C.line}; border: none;"
                f"border-radius: {D.BORDER_W}px;")
            rows = [_row(bar, txt(b["label"], F.h2, 600, C.ink_700),
                         spacing=S.s2)]
            plain = b.get("tone") == "plain"
            for line in b["items"]:
                if plain:
                    # plain 段不画勾/叹号：列表内容本身不是"已验证"的断言
                    rows.append(txt(line, F.body))
                    continue
                ic_name = "WARNING_OUTLINED" if is_err else "CHECK_CIRCLE_OUTLINED"
                ic_color = C.warn_fg if is_err else C.ok_fg
                rows.append(_row(icon_widget(ic_name, SIZES.ICON_LIST, ic_color),
                                 txt(line, F.body), spacing=S.s1))
            l3.append(_col(*rows, spacing=S.s1))
        elif bt == "prov":
            if len(b["items"]) == 1:
                l3.append(txt(b["items"][0], F.micro, color=C.ink_700))
            else:
                l3.append(_col(*[txt(x, F.micro, color=C.ink_700)
                                 for x in b["items"]], spacing=S.s1))
        elif bt == "headline":
            l2.append(_headline_qt(b))
        elif bt == "provnote":
            # 溯源条唯一出口是 qt_theme.provenance_bar（口径与一致）；
            # 万一 state 不满足（理论上不会，block 已在构建期过滤）退回一句文案。
            bar = provenance_bar(b.get("state") or {})
            if bar is not None:
                l2.append(bar)
            elif b.get("text"):
                l2.append(txt(b["text"], F.caption, color=C.warn_fg))
        elif bt == "spark":
            l3.append(_col(txt(b["caption"], F.caption, color=C.ink_500),
                           rework_chart(b["rows"]), spacing=S.s1))
        elif bt == "cells":
            items = []
            for x in b["items"]:
                items.append(_cell_qt(x, wide=bool(b.get("wide"))))
            l3.append(_col(txt(b["label"], F.h2, 600, C.ink_700),
                           _row(*items, spacing=S.s2), spacing=S.s2))
        elif bt == "rows":
            l3.append(_rows_qt(b))
        elif bt == "note":
            l2.append(txt(b["text"], F.body, color=C.ink_500, italic=True))
    return l1, l2, l3


# ---------- 成长海报新区块（重构思） ----------

def _headline_qt(b: dict) -> QWidget:
    """主句：一句标签 + display 级大数字（右侧早→近对照）+ 支撑小字。"""
    box = QWidget()
    box.setObjectName("posterHeadline")
    box.setStyleSheet(f"QWidget#posterHeadline {{ background: {C.surface_hero};"
                      f" border: none; border-radius: {R.lg}px; }}")
    v = QVBoxLayout(box)
    v.setContentsMargins(D.POSTER_PAD, D.POSTER_PAD, D.POSTER_PAD, D.POSTER_PAD)
    v.setSpacing(S.s1)
    v.addWidget(txt(b["label"], F.body, color=C.ink_500))
    line = _row(spacing=S.s2)
    lb = QHBoxLayout()
    lb.setContentsMargins(0, 0, 0, 0)
    lb.setSpacing(S.s1)
    lb.addWidget(txt(b["big"] or "—", F.display, 800, C.brand_700))
    if b.get("unit"):
        lb.addWidget(txt(b["unit"], F.h1, 800, C.brand_700), 0, Qt.AlignBottom)
    lb.addStretch(1)
    line.layout().addLayout(lb, 1)
    if b.get("from") is not None and b.get("to") is not None:
        rb = QVBoxLayout()
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(0)
        rb.addWidget(txt(f"{b['from']}", F.h1, 800, C.ink_900), 0, Qt.AlignRight)
        rb.addWidget(txt(f"→ {b['to']}", F.h1, 800, C.ok_fg), 0, Qt.AlignRight)
        line.layout().addLayout(rb, 0)
    v.addWidget(line)
    if b.get("sub"):
        v.addWidget(txt(b["sub"], F.caption, color=C.ink_500))
    _poster_entrance(box)   # 主角出场：reduced-motion 下不动，直接终态
    return box


def _cell_tone(tone: str) -> tuple:
    """格态 → (底色, 描边)。调用时解析 C.*：模块级求值会冻结亮色板。"""
    return {"done": (C.brand_50, C.brand_200), "bad": (C.err_bg, C.err_bg),
            "idle": (C.surface, C.line_strong), "ink": (C.surface_2, C.line),
            "soft": (C.surface_2, C.line)}.get(tone, (C.surface_2, C.line))


def _cell_qt(item: dict, wide: bool = False) -> QWidget:
    """一格数字（飞轮四格 / 资产两格共用）。"""
    bg, border = _cell_tone(item.get("tone", "ink"))
    box = QFrame()
    box.setObjectName("posterCell")
    box.setStyleSheet(f"QFrame#posterCell {{ background: {bg};"
                      f" border: 1px solid {border}; border-radius: {R.md}px; }}")
    v = QVBoxLayout(box)
    v.setContentsMargins(S.s3, S.s3, S.s3, S.s3)
    v.setSpacing(S.s1)
    v.addWidget(txt(item["k"], F.caption, color=C.ink_500))
    vh = QHBoxLayout()
    vh.setContentsMargins(0, 0, 0, 0)
    vh.setSpacing(S.s1)
    vh.addWidget(txt(item["v"], F.h1, 800))
    if item.get("u"):
        vh.addWidget(txt(item["u"], F.caption, 600, C.ink_500), 0, Qt.AlignBottom)
    vh.addStretch(1)
    v.addLayout(vh)
    v.addWidget(txt(item.get("note") or "", F.caption, color=C.ink_500,
                    wrap=True))
    box.setMinimumHeight(D.POSTER_CELL_H)
    if wide:
        box.setMinimumWidth(D.CHART_LABEL_W)
    return box


def _rows_qt(b: dict) -> QWidget:
    """助手对照表：表头与数据行同一套列宽（只显第一个表头 = 半个表格）。"""
    head = b.get("head") or []
    rows = []
    if head:
        hr = _row(spacing=S.s2)
        hlay = hr.layout()
        name = txt(head[0], F.caption, color=C.ink_500)
        name.setMinimumWidth(D.CHART_LABEL_W_MD)
        hlay.addWidget(name)
        for h in head[1:4]:
            cell = txt(h, F.caption, color=C.ink_500)
            cell.setMinimumWidth(D.CHART_LABEL_W_SM)
            hlay.addWidget(cell)
        hlay.addStretch(1)
        rows.append(hr)
    rows += [_agent_row_qt(r) for r in b["rows"]]
    return _col(txt(b["label"], F.h2, 600, C.ink_700), *rows, spacing=S.s1)


def _agent_row_qt(r: dict) -> QWidget:
    row = _row(spacing=S.s2)
    lay = row.layout()
    name = txt(r["name"], F.body, 700)
    name.setMinimumWidth(D.CHART_LABEL_W_MD)
    lay.addWidget(name)
    for c in r["cols"]:
        cell = txt(c, F.caption, color=C.ink_700)
        cell.setMinimumWidth(D.CHART_LABEL_W_SM)
        lay.addWidget(cell)
    lay.addStretch(1)
    lay.addWidget(chip(r["chip"], r.get("tone", "ink")))
    return row


# 方法论海报眉条品牌色 14 格渐段（纯装饰，非数据；与原 _ft_band 同列表）
_BAND_SCALE = (C.brand_50, C.brand_100, C.brand_100, C.brand_500,
               C.brand_500, C.brand_600, C.brand_600, C.brand_700,
               C.brand_700, C.brand_700, C.brand_800, C.brand_800,
               C.brand_800, C.brand_800)


def heat_row(colors) -> QWidget:
    """14 格圆角色块行（对应原 heat_row）。"""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(D.CHART_GAP)
    for c in colors:
        cell = QLabel()
        cell.setFixedSize(D.CHART_CELL, D.POSTER_MASTHEAD_H)
        cell.setStyleSheet(
            f"background: {c}; border: none;"
            f"border-radius: {D.POSTER_MASTHEAD_H // 2}px;")
        lay.addWidget(cell)
    return row


def t_zh(s: str, **kw) -> str:
    return t(s, **kw)


def png_spec_data_dir(spec: dict, kind: str) -> str:
    """PNG 文件名（与 md 导出命名同风格）。kind = growth/method。

    前缀原为 f-string 硬编码中文（英文用户的导出目录里躺着
    「成长报告-…png」）——改走词条，与海报标题同口径。"""
    today = datetime.date.today().isoformat()
    if kind == "growth":
        return f"{t('成长报告-')}{today}.png"
    safe = (spec["title"].replace("/", "·").replace("\\", "·").strip()
            or "方法")
    return f"{t('方法-')}{safe}-{today}.png"


def render_png_to_spec(spec: dict, data_dir: str, kind: str) -> Path:
    """PNG 一键落盘（GUI 按钮用）：渲染 + 去重落 exports/。"""
    path = save_png(data_dir, png_spec_data_dir(spec, kind))
    return render_png(spec, path)


# ---------- PNG 渲染器（PIL） ----------

_PIL = None


def _pil():
    global _PIL
    if _PIL is None:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
        _PIL = (Image, ImageDraw, ImageFont)
    return _PIL


_FONT_CACHE: dict[tuple[str, int], object] = {}

# (regular, bold) 字体候选：Windows / macOS / Linux；只探测系统已有字体，不打包
_FONT_CANDIDATES = (
    (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc"),
    (r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simhei.ttf"),
    ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc"),
    ("/System/Library/Fonts/STHeiti Light.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
     "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
     "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc"),
)


def _font(Font, size: int, bold: bool = False):
    key = (str(bold), size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    reg, bld = _first_existing_fonts()
    path = bld if bold else reg
    f = None
    if path:
        try:
            f = Font.truetype(path, size)
        except Exception:
            f = None
    if f is None:
        try:
            f = Font.load_default(size=size)
        except TypeError:
            f = Font.load_default()
    _FONT_CACHE[key] = f
    return f


def _first_existing_fonts() -> tuple[str | None, str | None]:
    for reg, bld in _FONT_CANDIDATES:
        if Path(reg).exists() and (Path(bld).exists() or bld == reg):
            return reg, bld
    return None, None


def _rr(d, box, r, fill=None):
    x0, y0, x1, y1 = box
    r = min(r, (x1 - x0) // 2, (y1 - y0) // 2)
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill)


def render_png(spec: dict, out_path: str | Path, scale: int = 2) -> Path:
    """海报 spec → PNG（scale=2 默认：720 宽 spec 出 1440px，分享清晰）。

    布局常量与 Flet 版同源（D.POSTER_*），所见即所导。"""
    Image, ImageDraw, ImageFont = _pil()
    W, pad = D.REPORT_W, D.POSTER_PAD
    cw = W - 2 * pad  # 内容宽
    gap_sec = S.s4  # 块间距（与弹层 Column spacing 同档）

    # 第一遍：量高（1x 逻辑坐标）
    def block_h(b: dict) -> int:
        t = b["type"]
        if t == "band":
            return D.POSTER_BAND_H
        if t == "meta":
            return F.caption + D.CHIP_PAD_Y * 2
        if t == "section":
            return F.h2 + S.s2 + len(b["items"]) * (F.body + S.s1) - S.s1
        if t == "prov":
            return len(b["items"]) * (F.caption + S.s1) - S.s1
        if t == "provnote":
            return F.caption + S.s2 * 2
        if t == "headline":
            # 标签 + display 大数字行 + 支撑小字（+ 可选区间行）+ 上下内边距
            return S.s2 + F.body + S.s1 + F.display + S.s1 + F.caption + S.s2
        if t == "spark":
            return F.caption + S.s2 + D.CHART_SPARK_H
        if t == "cells":
            return F.h2 + S.s3 + D.POSTER_CELL_H
        if t == "rows":
            return (F.h2 + S.s3 + F.caption + S.s2
                    + len(b["rows"]) * (F.body + S.s2) - S.s2)
        # note 用 F.body 字号：行高按 body 量（CJK 字形 14px 会超出 12px 行盒，
        # 量小 2px 会让脚注重叠最后一行）
        return F.body  # note

    heights = [block_h(b) for b in spec["blocks"]]
    # H 与绘制循环严格同源：每块 = 块高 + 尾 gap（含末块），再落脚注
    H = pad + F.h1 + gap_sec
    for h in heights:
        H += h + gap_sec
    H += F.caption + pad

    img = Image.new("RGB", (W * scale, H * scale), C.surface)
    d = ImageDraw.Draw(img)
    u = lambda v: int(round(v * scale))  # noqa: E731  1x 逻辑坐标 → 像素

    def F_(s, bold=False):
        return _font(ImageFont, s * scale, bold)

    def tx(text, size, x, y, color, bold=False):
        d.text((u(x), u(y)), text, font=F_(size, bold), fill=color)

    def tw(text, size, bold=False):
        return d.textlength(text, font=F_(size, bold)) / scale

    def rr(box, r, fill=None):
        _rr(d, [u(box[0]), u(box[1]), u(box[2]), u(box[3])], u(r), fill)

    # 头：标题 + 副题（右对齐）
    y = pad
    tx(spec["title"], F.h1, pad, y, C.ink_900, bold=True)
    sub = _header_sub(spec)
    if sub:
        tx(sub, F.caption, pad + cw - tw(sub, F.caption), y + F.h1 - F.caption,
           C.ink_500)
    y += F.h1 + gap_sec

    # 每块在 y（块顶）处相对绘制，循环统一按 block_h 推进——
    # 块高公式与绘制几何必须同源，否则画布量错、块间错位
    for i, b in enumerate(spec["blocks"]):
        t = b["type"]
        if t == "band":
            _draw_band(d, u, pad, y, cw, D.POSTER_BAND_H, rr)
        elif t == "meta":
            off = 0
            if b.get("conf") in ("high", "medium", "low"):
                label = t_zh(_CONF_LABEL_PIL[b["conf"]])
                bg, fg = _CONF_BG[b["conf"]]
                wch = tw(label, F.caption) + D.CHIP_PAD_X * 2
                rr([pad + off, y, pad + off + wch,
                    y + F.caption + D.CHIP_PAD_Y * 2], R.sm, bg)
                tx(label, F.caption, pad + off + D.CHIP_PAD_X,
                   y + D.CHIP_PAD_Y, fg, bold=True)
                off += wch + S.s2
            if b.get("text"):
                tx(b["text"], F.caption, pad + off, y + D.CHIP_PAD_Y, C.ink_500)
        elif t == "section":
            plain = b.get("tone") == "plain"
            bar_color = C.err_fg if b.get("tone") == "err" else C.line
            rr([pad, y, pad + D.BORDER_W * 2, y + F.h2], D.BORDER_W, bar_color)
            tx(b["label"], F.h2, pad + D.BORDER_W + S.s2, y, C.ink_700,
               bold=True)
            yy = y + F.h2 + S.s2
            for line in b["items"]:
                if plain:
                    # plain 段不画勾/点：列表内容本身不是"已验证"的断言
                    tx(line, F.body, pad, yy, C.ink_900)
                else:
                    tx("•", F.body, pad, yy, C.brand_600)
                    tx(line, F.body, pad + F.body + S.s1, yy, C.ink_900)
                yy += F.body + S.s1
        elif t == "headline":
            hh = heights[i]
            rr([pad, y, pad + cw, y + hh], R.lg, C.surface_hero)
            tx(b["label"], F.body, pad + S.s3, y + S.s2, C.ink_500)
            big_y = y + S.s2 + F.body + S.s1
            tx(f"{b['big']}{b['unit']}", F.display, pad + S.s3, big_y,
               C.brand_700, bold=True)
            if b.get("to") is not None:
                pair = f"{b['from']} → {b['to']}"
                tx(pair, F.h1, pad + cw - S.s3 - tw(pair, F.h1, True),
                   big_y + S.s1, C.ink_700, bold=True)
            sub_y = big_y + F.display + S.s1
            tx(b["sub"], F.caption, pad + S.s3, sub_y, C.ink_500)
        elif t == "spark":
            tx(b["caption"], F.caption, pad, y, C.ink_500)
            _draw_spark(b["rows"], pad, y + F.caption + S.s2, cw,
                        D.CHART_SPARK_H, tx, tw, rr, d, u)
        elif t == "cells":
            tx(b["label"], F.h2, pad, y, C.ink_700, bold=True)
            cy = y + F.h2 + S.s3
            items = b["items"]
            n = max(1, len(items))
            gapx = S.s2
            cell = (cw - (n - 1) * gapx) / n
            for idx, x in enumerate(items):
                cx0 = pad + idx * (cell + gapx)
                bg, bd = _cell_pil(x.get("tone", "ink"))
                rr([cx0, cy, cx0 + cell, cy + D.POSTER_CELL_H], R.md, bg)
                tx(x["k"], F.caption, cx0 + S.s3, cy + S.s2, C.ink_500)
                tx(f"{x['v']}{x['u']}", F.h1, cx0 + S.s3,
                   cy + S.s2 + F.caption + S.s1, C.ink_900, bold=True)
                tx(x.get("note") or "", F.caption, cx0 + S.s3,
                   cy + D.POSTER_CELL_H - F.caption - S.s2, C.ink_500)
        elif t == "rows":
            tx(b["label"], F.h2, pad, y, C.ink_700, bold=True)
            yy = y + F.h2 + S.s3
            xs = [pad, pad + D.CHART_LABEL_W_MD,
                  pad + D.CHART_LABEL_W_MD + D.CHART_LABEL_W_SM,
                  pad + D.CHART_LABEL_W_MD + 2 * D.CHART_LABEL_W_SM]
            for j, hd in enumerate(b.get("head") or []):
                tx(hd, F.caption, xs[j], yy, C.ink_500)
            yy += F.caption + S.s2
            for r in b["rows"]:
                tx(r["name"], F.body, xs[0], yy, C.ink_900, bold=True)
                for j, c in enumerate(r["cols"][:3]):
                    tx(str(c), F.caption, xs[j + 1], yy + S.s1, C.ink_700)
                bg, fg = _CHIP_BG.get(r.get("tone", "ink"), _CHIP_BG["brand"])
                wch = tw(r["chip"], F.caption) + D.CHIP_PAD_X * 2
                rr([pad + cw - wch, yy, pad + cw,
                    yy + F.caption + D.CHIP_PAD_Y * 2], R.sm, bg)
                tx(r["chip"], F.caption, pad + cw - wch + D.CHIP_PAD_X,
                   yy + S.s1, fg, bold=True)
                yy += F.body + S.s2
        elif t == "prov":
            yy = y
            for line in b["items"]:
                tx(line, F.caption, pad, yy, C.ink_700)
                yy += F.caption + S.s1
        elif t == "provnote":
            # 与 Qt 侧 provenance_bar 同视觉：次级底 + 左侧语义色条
            hh = heights[i]
            rr([pad, y, pad + cw, y + hh], R.sm, C.warn_bg)
            rr([pad, y, pad + D.BORDER_W * 2, y + hh], D.BORDER_W, C.warn_fg)
            tx(b["text"], F.caption, pad + S.s3, y + S.s2, C.ink_700)
        elif t == "note":
            tx(b["text"], F.body, pad, y, C.ink_500)
        y += heights[i] + gap_sec

    # 脚注（海报版权行）+ 右下角品牌水印装饰
    foot = f"Experientia · {spec['title']} · {datetime.date.today().isoformat()}"
    tx(foot, F.caption, pad + cw - tw(foot, F.caption), H - pad - F.caption,
       C.ink_300)
    
    # 右下角品牌水印（love 表情，SIZES.MASCOT_DECORATION 尺寸）
    # 叠加在最顶层，半透明
    try:
        from PIL import Image
        mascot_path = MASCOTS["love"]
        if mascot_path.exists():
            mascot_img = Image.open(mascot_path).convert("RGBA")
            # 调整大小
            mascot_img = mascot_img.resize(
                (u(SIZES.MASCOT_DECORATION), u(SIZES.MASCOT_DECORATION)),
                Image.Resampling.LANCZOS
            )
            # 放置在右下角（离脚注一点距离）
            paste_x = u(W - SIZES.MASCOT_DECORATION * scale - pad)
            paste_y = u((H - F.caption - pad) - SIZES.MASCOT_DECORATION * scale)
            img.paste(mascot_img, (paste_x, paste_y), mascot_img)
    except Exception:
        pass  # 加载失败不影响，跳过水印
    
    img.save(str(out_path), "PNG")
    return Path(out_path)


# PIL chip 色（与 theme._CHIP_TONES 同值）
_CONF_BG = {"high": (C.ok_bg, C.ok_fg), "medium": (C.warn_bg, C.warn_fg),
            "low": (C.brand_100, C.ink_700)}
_CHIP_BG = {"ok": (C.ok_bg, C.ok_fg), "info": (C.info_bg, C.info_fg),
            "warn": (C.warn_bg, C.warn_fg), "err": (C.err_bg, C.err_fg),
            "brand": (C.brand_100, C.ink_700)}
_CONF_LABEL_PIL = {"high": "已验证", "medium": "部分验证", "low": "待验证"}


def _header_sub(spec: dict) -> str:
    for b in spec["blocks"]:
        if b["type"] == "headline" and b.get("range"):
            return b["range"]
    if spec["kind"] == "method":
        for b in spec["blocks"]:
            if b["type"] == "meta" and b.get("text"):
                return b["text"]
    return ""


# PIL 格子底色（与 Qt _cell_tone 同档；调用处取用，避免模块级冻结亮色板）
def _cell_pil(tone: str) -> tuple:
    return {"done": (C.brand_50, C.brand_200), "bad": (C.err_bg, C.err_bg),
            "idle": (C.surface, C.line_strong), "ink": (C.surface_2, C.line),
            "soft": (C.surface_2, C.line)}.get(tone, (C.surface_2, C.line))


def _draw_spark(rows, pad, y, cw, h, tx, tw, rr, d=None, u=None):
    """迷你周图（PIL 版 ReworkChart）：柱 = 每周任务数，线 = 每任务返工回数。

    与页面同一纪律：**空周不连线**——没有记录的周两侧断开，绝不跨零样本画直线
    （真机 7 月中间 4 周无记录，连线会把"没数据"读成"从零涨上去"）。"""
    rows = list(rows)
    n = max(1, len(rows))
    slot = cw / n
    bar_w = min(D.CHART_COMBO_COL_W, slot - S.s2)
    label_h = F.caption + S.s1
    base = y + h - label_h
    top = y + S.s2
    sess = [float(r.get("sessions") or 0) for r in rows]
    rates = [float(r["rate"]) for r in rows if r.get("rate") is not None]
    mx_s = max(sess + [1.0])
    mx_r = max(rates + [1.0])
    peak = mx_s
    seg = []
    lw = max(1, u(2)) if u else 2
    for i, r in enumerate(rows):
        cx = pad + slot * i + (slot - bar_w) / 2
        v = float(r.get("sessions") or 0)
        if v > 0:
            bh = max(2.0, v / mx_s * (base - top))
            rr([cx, base - bh, cx + bar_w, base], D.BORDER_W * 2,
               C.brand_600 if v >= peak else C.brand_300)
        rate = r.get("rate")
        if rate is None:
            _stroke_png(seg, d, lw, u)
            seg = []
            continue
        seg.append((pad + slot * i + slot / 2, base - float(rate) / mx_r * (base - top)))
    _stroke_png(seg, d, lw, u)
    for i, r in enumerate(rows):
        if r.get("rate") is None:
            continue
        cx, cy = pad + slot * i + slot / 2, base - float(r["rate"]) / mx_r * (base - top)
        rr([cx - 3, cy - 3, cx + 3, cy + 3], 3, C.info_fg)
        d_ = str(r["week"] or "")[5:].replace("-", "/")
        if i % 2 == 0 or i == len(rows) - 1:      # 隔周标日期，防挤
            tx(d_, F.caption, cx - tw(d_, F.caption) / 2, base + S.s1, C.ink_500)


def _stroke_png(pts, d, lw, u):
    """折线段：d.line 收像素坐标，逻辑坐标必须先过 u()（scale）换算。"""
    if d is None or len(pts) < 2:
        return
    d.line([(u(x), u(y)) for x, y in pts], fill=C.info_fg, width=lw)


def _draw_band(d, u, pad, y, cw, h, rr):
    n = 14
    gap = D.CHART_GAP
    cell = (cw - (n - 1) * gap) / n
    scale = (C.brand_50, C.brand_100, C.brand_100, C.brand_500,
             C.brand_500, C.brand_600, C.brand_600, C.brand_700,
             C.brand_700, C.brand_700, C.brand_800, C.brand_800,
             C.brand_800, C.brand_800)
    for i, c in enumerate(scale):
        x0 = pad + i * (cell + gap)
        rr([x0, y, x0 + cell, y + h], h // 2, c)


def save_png(data_dir: str, filename: str) -> Path:
    """PNG 落数据目录 exports/（与 save_export 同目录同去重规则）。"""
    out = Path(data_dir) / "exports"
    out.mkdir(parents=True, exist_ok=True)
    path = out / filename
    i = 1
    while path.exists():
        stem, suffix = Path(filename).stem, Path(filename).suffix
        path = out / f"{stem}-{i}{suffix}"
        i += 1
    return path
