"""成长结算叙事（单一口径）：海报、周报通知、App 内结算卡共用。

为什么要独立一个模块（设计走查海报/周报 findings）：
"成长结算"此前有**三个各自为政的生产者**——周报 weekly_report、每日档位推送
notify.growth_edges、海报 poster.growth_poster——都直接读 affinity/cumulative/
heatmap，而真机 257 会话 100% 落在"其他/未分类"（分类要 LLM，端点连不上时
不会长出来）。结果三条链路同时退化成空壳：海报渲出 4 个"未分类·低"chip，
周报四问被吞掉三问。本模块把叙事收敛成一处，数据源换成 growth_panorama
（时间口径 + 价值闸门口径，两个都不会空）。

口径纪律：
- **主句用拿得出的数**：返工率早窗口 vs 近窗口（rework），不是"某类别少 N 轮"。
- **缺数据显式降级**：injection.log 不存在时，"哪条经验在变强"明写"还没开始"，
  不许静默消失（静默 = 用户不知道少了一问）。
- **零纠正 ≠ 等级低**：state=smooth 说"本来就顺"，few 说"样本不够"。
- **成就说人话**：veteran/pit_avoider/legacy 是机器键，展示走"老练/避坑达人/传承"；
  没解锁就写"差多少解锁"，不放假庆祝。
- 文案一律返回 **zh 源串 + 参数**，由调用方套 t()：通知走 daemon（无 UI 语言，
  保持中文源串），GUI 传 app.gui.i18n.t 做本地化。
"""

from __future__ import annotations

from ..time_util import parse_ts

from . import llm, skill

# 展示模板（**只存模板 + 参数，绝不预拼中文**——预拼好的串到了非中文界面就翻不了）
NOTE_YOURS = "满分 {top} · 你纠正后定下 {corr}"
NOTE_ADVICE = "{cnt} 类 · 最多一类撞了 {top} 次"
Q_RIGHT_SOME = "这周新固化 {n} 条坑：{who}"
Q_RIGHT_NONE = "没有新固化的坑——不是坏事，说明没踩到新的"
Q_FASTER_LEAD = "{who} 从 {e} 回/次 降到 {r} 回/次"
Q_FASTER_GLOBAL = "从每次任务 {e} 回降到 {r} 回"
Q_FASTER_NONE = "有记录的周还不够多，先继续用助手干活"
Q_STRONGER_HIT = "『{who}』这周被自动带上 {n} 次"
Q_STRONGER_NONE = "还没开始——经验一次都没被带回给助手"
Q_MISUSE_SOME = "{who} 你一次都没纠正过，本来就顺"
Q_MISUSE_NONE = "没有发现用错地方的情况"
ACH_HIT = "{name}解锁了"
ACH_HIT_AGENT = "{name}解锁了：{agent}"
ACH_HIT_CAT = "{name}解锁了：{agent} 的「{who}」"
REST_IDLE = "{who} 这周没来干活"
RANGE_SHORT = "{a} – {b} · {w} 周"
COUNTS = "{agents} 个助手 · {proj} 个项目 · {days} 个活跃日"
CAT_GAIN = "『{who}』平均比最初几次少 {n} 轮修正"

# 送达通道状态（第④格与欠账卡共用一句实话：到底卡在哪一步）
DELIV_LIVE = "经验已送达助手 {n} 次（代理 {proxy} · hook {hook}）"
DELIV_NO_HOOK = ("经验自动送达还没装上——装上 Claude Code 连接，或把助手的接口地址"
                 "指向 {url}")
DELIV_NOT_OBSERVED = ("连接脚本已装上，但助手一次都没用过——"
                      "从那类工具发起一次会话就会开始记")
DELIV_IDLE = "送达通道已通，但还没有经验真正用上（可能还没有可归类的经验）"

# 无模型引导段（结算卡主句位置）。空状态三要素：正向标题 + 这里为什么空着 +
# 单一主操作——不给一个"看起来是 0"的空壳，也不拿模板话冒充模型产出。
# 两态分开说：没配 → 去接入；配了连不上 → 去检查端点。合成一句空话，用户既
# 不知道自己属于哪种，也不知道下一步干什么。
GATE_TITLE_UNCONFIGURED = "统计都在，故事要等模型接上"
GATE_BODY_UNCONFIGURED = ("接上模型后，这里会多一段叙事：这周怎么变顺的、哪条"
                          "经验在变强。下面这些数是实打实干出来的，不靠模型。")
GATE_ACTION_UNCONFIGURED = "去接入"
GATE_TITLE_UNREACHABLE = "统计照常算，故事等模型恢复"
GATE_BODY_UNREACHABLE = "{endpoint} 最近没响应。统计照常算，叙事等模型恢复再补。"
GATE_ACTION_UNREACHABLE = "去检查"

# 成就机器键 → 中文源串（展示名；调用方 t() 本地化）
ACH_NAME = {"veteran": "老练", "pit_avoider": "避坑达人", "legacy": "传承"}
# 这三个展示名是**以 params 形式**塞进 tpl 的（"{name}解锁了：…"），`_slot` 只翻
# tpl —— 不单独过一遍 tf 的话，非中文界面会显示一个孤零零的中文名。
ACH_DISPLAY = frozenset(ACH_NAME.values())

# 助手磨合状态 → (结论源串, 语义色)
AGENT_STATE = {
    "improved": ("明显变顺", "ok"),
    "smooth": ("本来就顺", "ink"),
    "few": ("样本不够", "info"),
    "flat": ("暂无明显变化", "ink"),
}

# 里程碑未解锁时各成就"差多少"
NEXT_VETERAN = "老练 还差 1 个任务类别出现真实改善（现在 {n} 次任务都还没分类）"
NEXT_PITAVOIDER = "避坑达人 {cnt} 类坑还在反复出现，最频繁的一类撞了 {top} 次"
NEXT_LEGACY = "传承 把一份方法导出成可复用的 Skill 就解锁"


# ---------- 原料小件 ----------

def _date_range(stage: dict) -> str:
    a, b = str(stage.get("start") or ""), str(stage.get("end") or "")
    return f"{a} ~ {b}" if a and b else ""


def _mmdd(day: str) -> str:
    """YYYY-MM-DD → M/D（"01/05"）；坏值 → 空串（不影响句子成句）。"""
    d = parse_ts(day)
    if d is None:
        return ""
    d = d.date()
    return f"{d.month}/{d.day}"


def agent_rows(g: dict) -> list[dict]:
    """四助手对照行（海报表格 / 结算卡列表共用）。"""
    out = []
    for a in g.get("agents") or []:
        label, tone = AGENT_STATE.get(str(a.get("state")), AGENT_STATE["flat"])
        early, recent = a.get("early"), a.get("recent")
        out.append({
            "name": str(a.get("agent") or ""),
            "n": a.get("n", 0), "corr": a.get("corrections", 0),
            "trend": ("{e} → {r}".format(e=early, r=recent)
                      if early is not None and recent is not None else "—"),
            "chip": label, "tone": tone,
        })
    return out


def _lead_agent(g: dict) -> str:
    """四问/主句里点出主力助手名（明显变顺的那个），没有就空。"""
    for r in agent_rows(g):
        if r["chip"] == "明显变顺":
            return f"{r['name']} "
    return ""


# ---------- 叙事各段 ----------

def headline(g: dict) -> dict:
    """主句：返工降幅（海报 hero 大数字与周报第一句共用同一个数）。"""
    rw = g.get("rework") or {}
    st = g.get("stage") or {}
    drop = rw.get("drop_pct")
    base = {"comparable": bool(rw.get("comparable")), "span": _date_range(st),
            "weeks": st.get("weeks", 0), "from": rw.get("early"),
            "to": rw.get("recent"), "drop": drop}
    if not base["comparable"]:
        sub = "同类任务多做几次，就能算出返工有没有变少"
        return {**base, "big": "", "unit": "", "label": "还在攒样本",
                "sub": sub, "sub_n": {}, "sub_text": sub}
    sub = "头两周 {en} 次任务改 {ec} 回 · 最近 {rn} 次任务改 {rc} 回"
    sub_n = {"en": rw.get("early_n", 0), "ec": rw.get("early_corr", 0),
             "rn": rw.get("recent_n", 0), "rc": rw.get("recent_corr", 0)}
    return {**base, "big": f"{drop}" if drop is not None else "", "unit": "%",
            "label": "这段时间，要你返工的次数少了",
            "sub": sub, "sub_n": sub_n, "sub_text": sub.format(**sub_n)}


def gears(g: dict) -> list[dict]:
    """飞轮四格（第五格"少返工"就是主句那个大数字，不再重复摆）。"""
    fw = g.get("flywheel") or {}
    injected = int(fw.get("injected") or 0)
    return [
        {"k": "收进来", "v": f"{fw.get('collected', 0)}", "u": "次",
         "note": "你干的活都被看见", "tone": "done"},
        {"k": "提炼出", "v": f"{fw.get('distilled', 0)}", "u": "条",
         "note": "从这些活里总结出做法",
         "tone": "done" if fw.get("distilled") else "idle"},
        {"k": "判轻重", "v": f"{fw.get('judged', 0)}", "u": "条",
         "note": "AI 打了重要性分",
         "tone": "done" if fw.get("judged") else "idle"},
        {"k": "带回给 AI", "v": f"{injected}", "u": "次",
         "note": "还没接到你的助手会话里" if not injected else "助手已取用这些经验",
         "tone": "done" if injected else "bad"},
    ]


def assets(g: dict) -> list[dict]:
    """资产两格（与首页同口径：value_gate.surface_of 派生，不混 AI 手滑）。"""
    a = g.get("assets") or {}
    top = max((int(i.get("count") or 0)
               for i in (g.get("advice_items") or [])), default=0)
    return [
        {"k": "你的经验", "v": f"{a.get('experience', 0)}", "u": "条",
         "note": NOTE_YOURS, "note_n": {"top": a.get("top", 0),
                                        "corr": a.get("corrected", 0)},
         "tone": "ink"},
        {"k": "助手替你挡的坑", "v": f"{a.get('advice_hits', 0)}", "u": "次",
         "note": NOTE_ADVICE, "note_n": {"cnt": a.get("advice", 0), "top": top},
         "tone": "soft"},
    ]


def spark(g: dict) -> list[dict]:
    """迷你周图原料：柱 = 每周任务数，点 = 每任务返工回数（空周 rate=None）。"""
    return [{"week": w.get("week"), "sessions": int(w.get("sessions") or 0),
             "rate": w.get("rate")} for w in (g.get("weekly") or [])]


def top_experiences(g: dict, n: int = 3) -> list[dict]:
    """最值钱的几条经验（账本 top N；task 是资产标题，不加工）。"""
    return [{"badge": int(e.get("importance") or 0),
             "text": str(e.get("task") or ""), "id": e.get("id")}
            for e in (g.get("ledger") or [])[:n] if e.get("task")]


def questions(g: dict, *, solid_new: int = 0, solid_names: list | None = None,
              strongest: str = "") -> list[dict]:
    """人话四问。每问必有一条答案——没信号也要说清"为什么没有"。

    solid_new / solid_names / strongest 由调用方算（要读 playbook 与注入日志，
    本模块保持纯函数）。tone: ok 有改善 / err 断链待补 / info 中性事实 / ink 无内容。"""
    fw = g.get("flywheel") or {}
    rw = g.get("rework") or {}
    inj = int(fw.get("injected") or 0)
    out = []
    names = [str(x) for x in (solid_names or [])][:2]
    out.append({
        "id": "right", "title": "做对了吗", "tone": "ok" if solid_new else "ink",
        "body": Q_RIGHT_SOME if solid_new else Q_RIGHT_NONE,
        "body_n": ({"n": solid_new, "who": "、".join(names)} if solid_new else {})})
    if rw.get("comparable"):
        # 主力助手有自己的一对数就用它自己的，避免"workbuddy 2.14"这种张冠李戴
        lead = next((r for r in agent_rows(g) if r["chip"] == "明显变顺"), None)
        if lead and "→" in lead["trend"]:
            e, _, r = (x.strip() for x in lead["trend"].partition("→"))
            tpl, params = Q_FASTER_LEAD, {"who": lead["name"], "e": e, "r": r}
        else:
            tpl, params = Q_FASTER_GLOBAL, {"e": rw.get("early"),
                                            "r": rw.get("recent")}
        out.append({"id": "faster", "title": "更快了吗", "tone": "ok",
                    "body": tpl, "body_n": params})
    else:
        out.append({"id": "faster", "title": "更快了吗", "tone": "ink",
                    "body": Q_FASTER_NONE, "body_n": {}})
    out.append({
        "id": "stronger", "title": "哪条经验在变强",
        "tone": "err" if not inj else "ok",
        "body": Q_STRONGER_HIT if inj else Q_STRONGER_NONE,
        "body_n": ({"who": strongest or "经验", "n": inj} if inj else {}),
        "action": "" if inj else "看怎么接上"})
    smooth = [r["name"] for r in agent_rows(g) if r["chip"] == "本来就顺"]
    out.append({
        "id": "misuse", "title": "有没有用错地方",
        "tone": "info" if smooth else "ink",
        "body": Q_MISUSE_SOME if smooth else Q_MISUSE_NONE,
        "body_n": ({"who": "、".join(smooth[:3])} if smooth else {})})
    return out


def delivery(g: dict, hook: dict | None = None) -> dict:
    """第④格的实话：经验到底有没有、走哪条路到达助手。

    两条送达通道都算数：proxy = 助手把请求指到 8100，我们在转发时改写
    上下文；hook = Claude Code 的 UserPromptSubmit 回灌 additionalContext。
    没送达时不写"0"就完事——说清卡在哪一步（没装 / 装了没回调 / 通了没内容），
    否则用户对着一个 0 不知道该干什么。"""
    fw = g.get("flywheel") or {}
    by = fw.get("injected_by") or {}
    n = int(fw.get("injected") or 0)
    if n:
        return {"state": "live", "tpl": DELIV_LIVE,
                "params": {"n": n, "proxy": int(by.get("proxy") or 0),
                           "hook": int(by.get("hook") or 0)}, "action": ""}
    hook = hook or {}
    if not hook.get("configured"):
        return {"state": "no_hook", "tpl": DELIV_NO_HOOK,
                "params": {"url": "127.0.0.1:8100"}, "action": "去接上"}
    if not hook.get("observed"):
        return {"state": "not_observed", "tpl": DELIV_NOT_OBSERVED,
                "params": {}, "action": ""}
    return {"state": "idle", "tpl": DELIV_IDLE, "params": {}, "action": ""}


def milestones(g: dict, unlocked: list[dict] | None = None) -> dict:
    """里程碑：解锁了就具象说，没解锁就写"差多少"。

    unlocked 元素带 fresh=True 的算本周新解锁（决定海报要不要庆祝）。"""
    st = g.get("stage") or {}
    a = g.get("assets") or {}
    # "最频繁的一类坑撞了几次"自己算，不靠调用方传（少一个能传错的口子）
    top_count = max((int(i.get("count") or 0)
                     for i in (g.get("advice_items") or [])), default=0)
    unlocked = unlocked or []
    items = []
    for rec in unlocked[:3]:
        name = ACH_NAME.get(str(rec.get("type")), str(rec.get("type") or ""))
        scope = str(rec.get("scope") or "")
        agent, _, tail = scope.partition("/")
        who = tail.rsplit("/", 1)[-1] if tail else ""
        if "未分类" in who:
            who = ""
        if who:
            tpl, params = ACH_HIT_CAT, {"name": name, "agent": agent, "who": who}
        elif agent and agent != "global":
            tpl, params = ACH_HIT_AGENT, {"name": name, "agent": agent}
        else:
            tpl, params = ACH_HIT, {"name": name}
        items.append({"tpl": tpl, "params": params})
    if items:
        return {"unlocked": items, "next": [],
                "has_new": any(r.get("fresh") for r in unlocked)}
    return {"unlocked": [], "has_new": False, "next": [
        {"tpl": NEXT_VETERAN, "params": {"n": st.get("sessions", 0)}},
        {"tpl": NEXT_PITAVOIDER, "params": {"cnt": a.get("advice", 0),
                                            "top": top_count}},
        {"tpl": NEXT_LEGACY, "params": {}}]}


def rest(g: dict, active_agents: list[str] | None = None) -> list[str]:
    """休整段（中性）：这周没来的助手，而不是"某类别没新任务"。

    旧版按 affinity 键逐类播报"『hermes · 未分类』没有新任务"——分类没长出来时
    全是噪音。改成按助手播报，是真信号（哪个工具这周没被用）。"""
    if active_agents is None:
        return []
    rows = [r["name"] for r in agent_rows(g)]
    idle = [n for n in rows if n and n not in set(active_agents)]
    return [{"tpl": REST_IDLE, "params": {"who": n}} for n in idle[:3]]


# ---------- 一次算全 ----------

def model_gate(state: str, endpoint: str = "") -> dict:
    """无模型引导段（结算卡主句位置）：为什么这里没有故事 + 下一步做什么。

    ``state`` 取 ``llm.MODEL_STATE_*`` 并原样回填（展示层据此判断要不要渲染）；
    只有被门禁挡下的两态才带标题/说明/动作，可用态与"未判"三项全空。
    """
    if state == llm.MODEL_STATE_UNREACHABLE:
        return {"state": state, "tpl": GATE_TITLE_UNREACHABLE,
                "body": GATE_BODY_UNREACHABLE,
                "body_n": {"endpoint": endpoint or "模型端点"},
                "action": GATE_ACTION_UNREACHABLE}
    if state == llm.MODEL_STATE_UNCONFIGURED:
        return {"state": state, "tpl": GATE_TITLE_UNCONFIGURED,
                "body": GATE_BODY_UNCONFIGURED, "body_n": {},
                "action": GATE_ACTION_UNCONFIGURED}
    return {"state": state or "", "tpl": "", "body": "",
            "body_n": {}, "action": ""}


# 会被门禁挡下、需要渲染引导段的两态（展示层判断用，避免各处抄字符串）
MODEL_GATE_BLOCKED = (llm.MODEL_STATE_UNCONFIGURED, llm.MODEL_STATE_UNREACHABLE)


def _empty_story(g: dict, state: str = "", endpoint: str = "") -> dict:
    """无模型 → **不生成叙事**（总纲归纳层）：结构与 build() 完全同形、
    叙事各段为空，**绝不拼模板假话**。

    同形是硬要求：`localize()` / `sections_text()` / 海报与结算卡都按固定键取值，
    缺键会让展示层炸；这里给的是"结构齐全但叙事无正文"。

    **统计照给**：区间、底栏计数、里程碑都是零 LLM 就能算的数，
    用户干了活却在卡上看到"0 个助手 · 0 个项目 · 0 个活跃日"是假话——
    掐掉的只有叙事（headline / questions / gears / assets / top）。

    注意 ``has_data`` 恒 False：它表示"没有可展示的叙事内容"，不是"你没干活"，
    `provenance_bar` 据此不挂"内容为上次生成"那条（无模型时从未生成过）。
    """
    st = g.get("stage") or {}
    return {
        "content_source": skill.CONTENT_SOURCE_NONE,
        "generated_at": "",
        "text": "",
        "has_data": False,
        "stage": st,
        "range": _date_range(st),
        "range_short": {"tpl": RANGE_SHORT, "params": {
            "a": _mmdd(str(st.get("start") or "")),
            "b": _mmdd(str(st.get("end") or "")), "w": st.get("weeks", 0)}},
        "counts": {"tpl": COUNTS, "params": {
            "agents": st.get("agents", 0), "proj": st.get("projects", 0),
            "days": st.get("active_days", 0)}},
        "headline": {"comparable": False, "span": "", "weeks": 0, "from": None,
                     "to": None, "drop": None, "big": "", "unit": "", "label": "",
                     "sub": "", "sub_n": {}, "sub_text": ""},
        "gears": [], "assets": [], "agents": [], "spark": [], "top": [],
        "questions": [],
        # 里程碑属统计（"差多少解锁"由 stage/assets 算出）→ 照给，不放假庆祝
        "milestones": milestones(g),
        "rest": [],
        # 送达通道一句实话也不说：没生成叙事时不猜"卡在哪一步"
        "delivery": {"state": "none", "tpl": "", "params": {}, "action": ""},
        "category_gain": [],
        "model_gate": model_gate(state, endpoint),
    }


def build(g: dict, *, unlocked: list[dict] | None = None,
          active_agents: list[str] | None = None, hook: dict | None = None,
          solid_new: int = 0, solid_names: list | None = None,
          strongest: str = "", model_state: str | None = None,
          endpoint: str = "", generated_at: str | None = None) -> dict:
    """growth_summary 响应 + 成就记录 → 全叙事（纯函数，零 LLM、零写盘）。

    ``model_state`` = 归纳层门禁（总纲  /），取 ``llm.MODEL_STATE_*``：
    - 未配置 / 连不上 → **不生成叙事**：叙事各段为空 + ``content_source="none"``，
      但统计（区间 / 计数 / 里程碑）照给，并带一段 ``model_gate`` 引导
      （为什么空着 + 单一主操作，见 ``model_gate``）；
    - ``available``  → 正常叙事 + ``content_source="model"`` + ``generated_at``；
    - ``None``（默认）→ 调用方未判模型 → ``content_source=""``（**来源未知**，
      UI 不挂降级条）——海报 / 导出等冻结路径保持现状不受影响。

    **零 LLM 是这套叙事的固有属性**（docstring 第一行就写着），不是"接了模型才
    算得出来"——不生成是产品决定（归纳类内容必须由模型产出），不是能力限制。
    所以无模型时给得出统计就给，别把真数据抹成 0。
    """
    if model_state in (llm.MODEL_STATE_UNCONFIGURED, llm.MODEL_STATE_UNREACHABLE):
        return _empty_story(g, model_state, endpoint)
    ok = model_state == llm.MODEL_STATE_AVAILABLE
    st = g.get("stage") or {}
    ms = milestones(g, unlocked)
    return {
        "content_source": (skill.CONTENT_SOURCE_MODEL if ok else ""),
        "generated_at": (generated_at or (skill.now_iso() if ok else "")),
        "has_data": bool(st.get("sessions")),
        "stage": st,
        "range": _date_range(st),
        "range_short": {"tpl": RANGE_SHORT, "params": {
            "a": _mmdd(str(st.get("start") or "")),
            "b": _mmdd(str(st.get("end") or "")), "w": st.get("weeks", 0)}},
        "counts": {"tpl": COUNTS, "params": {
            "agents": st.get("agents", 0), "proj": st.get("projects", 0),
            "days": st.get("active_days", 0)}},
        "headline": headline(g),
        "gears": gears(g),
        "assets": assets(g),
        "agents": agent_rows(g),
        "spark": spark(g),
        "top": top_experiences(g),
        "questions": questions(g, solid_new=solid_new, solid_names=solid_names,
                              strongest=strongest),
        "milestones": ms,
        "rest": rest(g, active_agents),
        "delivery": delivery(g, hook),
        "category_gain": category_gain(g),
        "model_gate": model_gate(model_state or ""),
    }


def _zh(src: str, **kw) -> str:
    """默认"翻译"=中文源串本身（通知走 daemon，没有 UI 语言）。"""
    return src.format(**kw) if kw else src


def category_gain(g: dict) -> list[dict]:
    """按任务类别的磨合差值——有真实改善的类别才出。

    这是重做时**差点被我丢掉**的一条：新叙事改用时间口径返工率当主句，
    但类别判据才是产品文档的正式口径。两者不是替代关系——库里分类长出来了
    （模型端点可用）时这条更有价值，所以它作为主句的加项保留，
    没长出来时安静缺席，不再让整页/整份报告因为缺它而空壳。"""
    from ..store.store import affinity_display

    out = []
    for key, a in sorted((g.get("affinity") or {}).items()):
        if a.get("level") == "待积累" or a.get("excluded"):
            continue
        diff = int(a.get("diff") or 0)
        if diff >= 1:
            out.append({"tpl": CAT_GAIN,
                        "params": {"who": affinity_display(key), "n": diff}})
    return out[:3]


def _slot(item, tf):
    """{"tpl","params"} → 本地化字符串；已是字符串则直接过 tf。

    params 里属于 `ACH_DISPLAY`（成就展示名）的值单独过一次 tf——它们本身是可译
    的中文源串，靠 tpl 的翻译拿不到（tpl 只看到 `{name}` 这个坑位）。
    空串必须短路：gettext 把 msgid "" 当目录头，t("") 会吐回整段 po header。"""
    if isinstance(item, dict) and "tpl" in item:
        tpl = str(item["tpl"] or "")
        params = {k: (tf(v) if v in ACH_DISPLAY else v)
                  for k, v in (item.get("params") or {}).items()}
        return tf(tpl, **params) if tpl else ""
    text = str(item or "")
    return tf(text) if text else ""


def localize(story: dict, tf) -> dict:
    """叙事 → 当前语言的浅拷贝（海报 / 结算卡拿到的就是成品字符串）。

    tf = app.gui.i18n.t。服务端只存模板与参数，语言在展示侧决定，
    所以同一份 /api/weekly-report 响应可以喂任何界面语言。"""
    if not story:
        return {}
    h = dict(story.get("headline") or {})
    # 空串必须短路：gettext 把 msgid "" 当目录头，t("") 会吐回整段 po header
    h["sub"] = (tf(str(h.get("sub") or ""), **(h.get("sub_n") or {}))
                if h.get("sub") else "")
    ms = story.get("milestones") or {}
    mg = story.get("model_gate") or {}
    return {
        **story,
        "range_short": _slot(story.get("range_short"), tf),
        "counts": _slot(story.get("counts"), tf),
        "headline": h,
        "gears": [{**g, "k": tf(str(g.get("k") or "")),
                   "u": tf(str(g.get("u") or "")),
                   "note": tf(str(g.get("note") or ""))}
                  for g in story.get("gears") or []],
        "assets": [{**a, "k": tf(str(a.get("k") or "")),
                    "u": tf(str(a.get("u") or "")),
                    "note": tf(str(a.get("note") or ""),
                               **(a.get("note_n") or {}))}
                   for a in story.get("assets") or []],
        "agents": [{**r, "chip": tf(str(r.get("chip") or ""))}
                   for r in story.get("agents") or []],
        "questions": [{**q, "title": tf(str(q.get("title") or "")),
                       "body": tf(str(q.get("body") or ""),
                                  **(q.get("body_n") or {})),
                       "action": _slot(q.get("action"), tf)}
                      for q in story.get("questions") or []],
        "milestones": {"unlocked": [_slot(x, tf) for x in ms.get("unlocked") or []],
                       "next": [_slot(x, tf) for x in ms.get("next") or []],
                       "has_new": ms.get("has_new", False)},
        "rest": [_slot(x, tf) for x in story.get("rest") or []],
        "category_gain": [_slot(x, tf)
                          for x in story.get("category_gain") or []],
        "delivery": {**(story.get("delivery") or {}),
                     "text": _slot(story.get("delivery"), tf),
                     "action": tf(str((story.get("delivery") or {})
                                      .get("action") or ""))},
        # 无模型引导段（空串短路：gettext 把 msgid "" 当目录头，t("") 吐回
        # 整段 po header——有门禁才有文案，没门禁三项全空）
        "model_gate": {"state": str(mg.get("state") or ""),
                       "title": tf(str(mg.get("tpl") or "")) if mg.get("tpl") else "",
                       "body": (tf(str(mg.get("body") or ""),
                                   **(mg.get("body_n") or {}))
                                if mg.get("body") else ""),
                       "action": (tf(str(mg.get("action") or ""))
                                  if mg.get("action") else "")},
    }


def sections_text(s: dict, tf=_zh) -> dict:
    """叙事 → 四段纯文本（周报通知用；tf 传 app.gui.i18n.t 可本地化）。

    无模型的空叙事（content_source="none"）返回四段皆空——"没生成"就是没生成，
    不用"还在攒样本"这类降级文案顶替（那会让人以为数据不够、其实只是没接模型）。"""
    loc = localize(s, tf)
    if loc.get("content_source") == skill.CONTENT_SOURCE_NONE:
        return {"main": [], "questions": [], "milestones": [], "rest": []}
    h = loc["headline"]
    if h["comparable"] and h["drop"] is not None:
        main = [tf("要你返工的次数，{w} 周里少了 {p}%", w=h["weeks"], p=h["drop"])]
    elif h["comparable"]:
        main = [tf("要你返工的次数，从每次 {e} 回降到 {r} 回",
                   e=h["from"], r=h["to"])]
    else:
        main = [tf("还在攒样本：多做几次同类任务就能看出返工有没有变少")]
    # 类别判据有就追加：它是正式口径，不该被时间口径顶掉
    main += loc.get("category_gain") or []
    questions = [tf("{q}？{a}", q=q["title"], a=q["body"])
                 for q in loc["questions"]]
    ms = loc["milestones"]
    return {"main": main, "questions": questions,
            "milestones": ms["unlocked"] or ms["next"],
            "rest": loc["rest"]}
