"""成长页的「学习历程时间轴」区（Qt 版）。

 拆分：从 `app/gui/growth.py` 搬出的第二个区块，含两部分：

- **`_TlRail`**（原 L130-175）：时间轴轨道组件，1px 竖线 + 类型色圆点，
  圆点半径随入场动画进度从 0 长到终值；
- **`TimelineMixin`**（原 L1193-1860，约 660 行 / 19 个方法 + 16 个类级常量）：
  按天分组、人话化节点标题、×N 合并签名、折叠展开、右键编辑菜单。

约定与 store 侧 mixin 一致：方法体**逐字搬移**、签名与返回值不变；共享状态
（`api` / 各 `_tl_*` 实例属性）留在 `GrowthPage` 主体、靠 `self` 访问；
**不 import growth_page**（避免循环）。`_animate_progress` 本就来自
`qt_widgets`（非 growth.py 本地函数），故 `_TlRail` 搬走不产生新依赖。
"""

from __future__ import annotations

from datetime import datetime
import re

from PySide6.QtCore import Property, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QMenu, QVBoxLayout, QWidget

from .i18n import t
from .qt_theme import btn_flat, card, chip, ellipsis_button, txt
from .qt_widgets import RotatingIcon, _animate_progress
from .theme import C, F, S

class _TlRail(QWidget):
    """时间轴轨道：1px 竖线 + 类型色圆点（last=True 时线到圆点为止；
    dot=False 只画线，供固化源复盘子块行保持竖线连续）。

    入场动画：圆点半径随 `progress` 从 0 长到终值（与图表件同口径）。
    """

    RAIL_W = 14
    _DOT_R = 3.5           # 终态半径（直径 7，圆心 6.5/8.5）

    def __init__(self, dot_color: str, last: bool, parent=None,
                 dot: bool = True):
        super().__init__(parent)
        self._dot = dot_color
        self._last = last
        self._dot_on = dot
        self._progress = 1.0   # fail-open：未调用 animate_in 时就是终态
        self.setFixedWidth(self.RAIL_W)

    # 入场动画进度（0→1）；初值 1.0，见 _animate_progress 的 fail-open 约定
    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, v: float) -> None:
        self._progress = max(0.0, min(1.0, float(v)))
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def animate_in(self, duration: float | None = None) -> None:
        """入场动画：圆点从 0 长到终值（motion_ok() 为假则不动，保持 1.0）。"""
        _animate_progress(self, duration)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x = 6  # 线心（1px 宽，占 6-7）
        bottom = 11 if self._last else self.height()
        p.setPen(QPen(QColor(C.line), 1))
        p.drawLine(x, 0, x, bottom)
        if self._dot_on:
            r = self._DOT_R * self._progress
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self._dot))
            p.drawEllipse(QRectF(6.5 - r, 8.5 - r, r * 2, r * 2))
        p.end()


class TimelineMixin:
    """学习历程时间轴：按天分组 + 人话化 + ×N 合并（成长页的⑤区）。"""


    # ---------- 学习历程时间轴（⑤：按天分组 + 人话化 + ×N 合并） ----------
    # 展示层 best-effort 解析：自动生成的节点匹配已知模板 → 人话标题 + 类型标签
    # + 合并签名；用户编辑过的节点不匹配 → 原文照显、不合并（零风险）。
    # 数据层不动：idx 仍是 changelog.md 行号，编辑/删除/归档 30 天语义原样保留。

    _REVIEW_RE = re.compile(
        r"^复盘 (?P<agent>\S+) 会话 (?P<sid>\S+?)…?\s*→\s*(?P<path>.+?)"
        r" 新增 (?P<n>\d+) 条候选经验(?:（文件通道）|\s*\[auto\])\s*$")
    _SELF_RE = re.compile(r"^自报经验自动入库 (?P<agent>\S+) → (?P<path>.+)$")
    _DISTILL_RE = re.compile(
        r"^蒸馏 (?P<path>.+?)（(?P<src>[^）]+)）：(?P<n>\d+) 条经验 → (?P<tail>.+)$")
    _FIXES_RE = re.compile(r"^纠正补丁 (?P<path>.+?)：(?P<n>\d+) 条 → v(?P<ver>\S+)\s*$")
    _VETO_RE = re.compile(r"^用户否决失败模式 (?P<path>.+?)：(?P<text>.+)$")
    _RENAME_RE = re.compile(r"^改名 (?P<path>.+?) →(?P<rest>.*)$")
    _PREF_INC_RE = re.compile(r"^偏好增量合并 (?P<trunk>[^：]+)：\+(?P<n>\d+) 条$")
    _PREF_REINDUCT_RE = re.compile(
        r"^偏好重新归纳 (?P<trunk>[^：]+)：(?P<kept>\d+) 条确认保留 / (?P<new>\d+) 条新归纳$")
    _PREF_SELF_RE = re.compile(
        r"^偏好自整理 (?P<trunk>[^：]+)：(?P<before>\d+) 条 → (?P<after>\d+) 条$")
    _PREF_EDIT_RE = re.compile(r"^用户编辑偏好画像 (?P<trunk>\S+)$")
    _ACH_RE = re.compile(r"^成就解锁 (?P<n>\d+) 个：(?P<names>.+)$")
    _VER_TAIL_RE = re.compile(
        r"^v(?P<ver>[^；]+)(?:；淘汰：(?P<dep>.+?))?(?:；纠正补丁已更新)?$")
    _NAME_RE = re.compile(r"^「(?P<name>[^」]+)」")

    # 节点类型 → (chip 语义色, 轨道圆点色 token 名)：颜色在渲染时解析（暗色不冻结）
    _KIND_TONE = {"learn": "brand", "method": "ok", "pref": "info",
                  "ach": "warn", "other": "ink"}
    _KIND_DOT = {"learn": "brand_500", "method": "ok_fg", "pref": "info_fg",
                 "ach": "warn_fg", "other": "ink_300"}
    _KIND_LABEL = {"learn": "新经验", "method": "方法升级", "pref": "偏好归纳",
                   "ach": "成就", "other": "记录"}

    def _timeline(self, nodes: list) -> QWidget:
        self._tl_nodes = list(nodes)
        self._tl_total = len(nodes)
        self._tl_groups = self._tl_group_by_day(nodes)
        first_day = self._tl_groups[0][0] if self._tl_groups else ""
        self._tl_expanded_days: set[str] = {first_day}
        self._tl_expanded_groups: set[tuple] = set()
        self._tl_expanded_sources: set[int] = set()
        self._tl_show_all = False
        # 卡头：标题 + 右上说明（操作说明不再挤进标题）
        outer = card()
        head_w = QWidget()
        hl = QHBoxLayout(head_w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(S.s2)
        hl.addWidget(txt(t("学习历程"), F.h2, 600, C.ink_700))
        hl.addStretch(1)
        hl.addWidget(txt(t("共 {n} 个节点 · 删除=归档，30 天可恢复", n=self._tl_total),
                         F.caption, color=C.ink_500))
        outer.layout().addWidget(head_w)
        self._tl_box = QWidget()
        self._tl_lay = QVBoxLayout(self._tl_box)
        self._tl_lay.setContentsMargins(0, 0, 0, 0)
        self._tl_lay.setSpacing(0)
        outer.layout().addWidget(self._tl_box)
        # 数据变了才播轨道入场；消费后清零，展开/收起走 _tl_rebuild 默认态
        self._tl_rebuild(self._tl_animate_pending)
        self._tl_animate_pending = False
        return outer

    # ---------- 节点人话化（best-effort，解析失败回退原文） ----------

    @classmethod
    def _humanize_node(cls, nd: dict) -> dict:
        """changelog 节点 → {kind, title, meta, is_auto, sig, parse, ...}。

        机器标记（tag.kind + k=v 字段，store.append_event
        契约）优先——节点身份（kind/agent/path/trunk/n/ver）一律吃标记，正则只在
        标记缺展示细节（veto 文本、rename 名、pref 条数）时作文本级补充；
        legacy 行（tag=None）才整体走人话化正则。v2 标记行：review/distill 的
        机器状态（n/times/solidified/path/ver）优先吃标记——文本里的条数只是
        首轮的，累计值只活在标记里；用户编辑过的文本（正则失配）原文照显、
        不合并（编辑语义零破坏），标记仍供固化匹配。
        sig=None 表示不参与 ×N 合并（用户编辑的节点、一次性事件）。"""
        text = nd.get("text", "")
        tag = nd.get("tag") or {}
        k = tag.get("kind")

        if k == "review":
            n = int(tag.get("n") or 0)
            times = int(tag.get("times") or 1)
            solidified = tag.get("solidified", "")
            m = cls._REVIEW_RE.match(text)
            if not m:
                # 用户改过文本：原文照显、不合并（n/times 仍在标记里，不丢）
                return {"kind": "learn", "title": text, "meta": "",
                        "is_auto": True, "sig": None, "parse": {},
                        "solidified": solidified, "_src_path": ""}
            path = m["path"]
            chan = t("文件通道") if "（文件通道）" in text else t("会话复盘")
            if times >= 2:
                title = t("从 {agent} 的会话学到 {n} 条新经验（复盘 {times} 次）",
                          agent=tag.get("agent", "?"), n=n, times=times)
            else:
                title = t("从 {agent} 的一次会话学到 {n} 条新经验",
                          agent=tag.get("agent", "?"), n=n)
            return {"kind": "learn", "title": title,
                    "meta": f"{path} · {chan}",
                    "is_auto": True, "sig": ("review", path),
                    "parse": {"n": n}, "times": times,
                    "solidified": solidified, "_src_path": path}

        if k == "distill":
            path = tag.get("path", "")
            ver = tag.get("ver", "")
            out = {"sig": None, "parse": {},
                   "distill_path": path, "distill_ver": ver}
            m = cls._DISTILL_RE.match(text)
            if not m:
                # 用户改过文本：原文照显（标记仍供源复盘折叠匹配）
                out.update({"kind": "method", "title": text, "meta": "",
                            "is_auto": False})
                return out
            n = int(tag.get("n") or m["n"])
            src = tag.get("src") or m["src"]
            dep = ""
            tail = cls._VER_TAIL_RE.match(m["tail"].strip())
            if tail:
                dep = (tail.group("dep") if tail else "") or ""
                if not ver:
                    ver = tail.group("ver") or m["tail"].strip()
            if not path:
                path = m["path"]
                out["distill_path"] = path
            src_label = {"review": t("会话复盘"),
                         "threshold": t("数量达标")}.get(src, src)
            meta = t("由 {n} 条经验蒸馏 · {src}", n=n, src=src_label)
            if dep:
                meta += " · " + t("淘汰：{text}", text=dep[:40])
            out.update({"kind": "method",
                        "title": t("方法「{path}」升级到 v{ver}",
                                   path=path, ver=ver.lstrip("v")),
                        "meta": meta, "is_auto": src in ("review", "threshold")})
            return out

        # ---------- M22：其余 kind 的机器标记分支（store.append_event 契约） ----------
        # 节点身份（kind/agent/path/trunk/n/ver）吃标记；标记里没有的展示细节
        # （veto 文本、rename 名、pref 条数）从人话文本作 best-effort 补充，
        # 补不出就少显示，不影响分类与合并语义。
        if k == "self":
            agent = tag.get("agent") or "?"
            path = tag.get("path") or ""
            n = int(tag.get("n") or 1)
            return {"kind": "learn",
                    "title": t("{agent} 自报 {n} 条经验，已自动入库",
                               agent=agent, n=n),
                    "meta": path, "is_auto": True,
                    "sig": ("self", path, agent), "parse": {"n": n}}
        if k == "fixes":
            path = tag.get("path") or ""
            ver = str(tag.get("ver") or "").lstrip("v")
            n = int(tag.get("n") or 0)
            return {"kind": "method",
                    "title": t("方法「{path}」更新纠正补丁（v{ver}）",
                               path=path, ver=ver),
                    "meta": t("来自 {n} 条纠正记录", n=n),
                    "is_auto": True, "sig": None, "parse": {}}
        if k == "veto":
            path = tag.get("path") or ""
            # 标记只带 path；否决的内容在人话文本「：」后段（展示细节）
            detail = text.split("：", 1)[-1][:40] if "：" in text else ""
            return {"kind": "method",
                    "title": t("你否决了 1 条失败模式"),
                    "meta": f"{path} · {detail}" if detail else path,
                    "is_auto": False, "sig": None, "parse": {}}
        if k == "rename":
            path = tag.get("path") or ""
            rest = text.split("→", 1)[-1].strip() if "→" in text else ""
            nm = cls._NAME_RE.match(rest)
            if nm:
                return {"kind": "method",
                        "title": t("方法改名为「{name}」", name=nm["name"]),
                        "meta": path, "is_auto": False,
                        "sig": None, "parse": {}}
            return {"kind": "method", "title": t("方法类别调整"),
                    "meta": path, "is_auto": False, "sig": None, "parse": {}}
        if k == "pref-inc":
            trunk = tag.get("trunk") or ""
            n = int(tag.get("n") or 0)
            return {"kind": "pref",
                    "title": t("偏好画像「{trunk}」自动归纳 {n} 条新偏好",
                               trunk=trunk, n=n),
                    "meta": trunk, "is_auto": True,
                    "sig": ("pref-inc", trunk), "parse": {"n": n}}
        if k == "pref-reinduct":
            trunk = tag.get("trunk") or ""
            m = cls._PREF_REINDUCT_RE.match(text)  # kept/new 条数不在标记里
            meta = (t("{kept} 条确认保留 · {new} 条新归纳",
                      kept=m["kept"], new=m["new"]) if m else trunk)
            return {"kind": "pref",
                    "title": t("偏好画像「{trunk}」重新归纳", trunk=trunk),
                    "meta": meta, "is_auto": True, "sig": None, "parse": {}}
        if k == "pref-self":
            trunk = tag.get("trunk") or ""
            m = cls._PREF_SELF_RE.match(text)  # before/after 条数不在标记里
            meta = (t("{before} 条 → {after} 条",
                      before=m["before"], after=m["after"]) if m else trunk)
            return {"kind": "pref",
                    "title": t("偏好画像「{trunk}」自动整理", trunk=trunk),
                    "meta": meta, "is_auto": True, "sig": None, "parse": {}}
        if k == "pref-edit":
            trunk = tag.get("trunk") or text.strip()
            return {"kind": "pref",
                    "title": t("你编辑了偏好画像「{trunk}」", trunk=trunk),
                    "meta": "", "is_auto": False, "sig": None, "parse": {}}
        if k == "ach":
            n = int(tag.get("n") or 0)
            names = text.split("：", 1)[-1] if "：" in text else ""
            return {"kind": "ach",
                    "title": t("解锁 {n} 个成就", n=n),
                    "meta": names, "is_auto": True, "sig": None, "parse": {}}

        # legacy 行（无标记）：人话文本模板未变，正则照旧
        m = cls._REVIEW_RE.match(text)
        if m:
            chan = t("文件通道") if "（文件通道）" in text else t("会话复盘")
            return {"kind": "learn",
                    "title": t("从 {agent} 的一次会话学到 {n} 条新经验",
                               agent=m["agent"], n=int(m["n"])),
                    "meta": f"{m['path']} · {chan}",
                    "is_auto": True, "sig": ("review", m["path"]),
                    "parse": {"n": int(m["n"])}}
        m = cls._SELF_RE.match(text)
        if m:
            return {"kind": "learn",
                    "title": t("{agent} 自报 {n} 条经验，已自动入库",
                               agent=m["agent"], n=1),
                    "meta": m["path"], "is_auto": True,
                    "sig": ("self", m["path"], m["agent"]),
                    "parse": {"n": 1}}
        m = cls._DISTILL_RE.match(text)
        if m:
            tail = cls._VER_TAIL_RE.match(m["tail"].strip())
            ver = tail.group("ver") if tail else m["tail"].strip()
            dep = (tail.group("dep") if tail else "") or ""
            src = m["src"]
            src_label = {"review": t("会话复盘"),
                         "threshold": t("数量达标")}.get(src, src)
            meta = t("由 {n} 条经验蒸馏 · {src}", n=m["n"], src=src_label)
            if dep:
                meta += " · " + t("淘汰：{text}", text=dep[:40])
            return {"kind": "method",
                    "title": t("方法「{path}」升级到 v{ver}",
                               path=m["path"], ver=ver),
                    "meta": meta, "is_auto": src in ("review", "threshold"),
                    "sig": None, "parse": {}}
        m = cls._FIXES_RE.match(text)
        if m:
            return {"kind": "method",
                    "title": t("方法「{path}」更新纠正补丁（v{ver}）",
                               path=m["path"], ver=m["ver"]),
                    "meta": t("来自 {n} 条纠正记录", n=m["n"]),
                    "is_auto": True, "sig": None, "parse": {}}
        m = cls._VETO_RE.match(text)
        if m:
            return {"kind": "method",
                    "title": t("你否决了 1 条失败模式"),
                    "meta": f"{m['path']} · {m['text'][:40]}",
                    "is_auto": False, "sig": None, "parse": {}}
        m = cls._RENAME_RE.match(text)
        if m:
            nm = cls._NAME_RE.match(m["rest"].strip())
            if nm:
                return {"kind": "method",
                        "title": t("方法改名为「{name}」", name=nm["name"]),
                        "meta": m["path"], "is_auto": False,
                        "sig": None, "parse": {}}
            return {"kind": "method", "title": t("方法类别调整"),
                    "meta": m["path"], "is_auto": False,
                    "sig": None, "parse": {}}
        m = cls._PREF_INC_RE.match(text)
        if m:
            return {"kind": "pref",
                    "title": t("偏好画像「{trunk}」自动归纳 {n} 条新偏好",
                               trunk=m["trunk"], n=int(m["n"])),
                    "meta": m["trunk"], "is_auto": True,
                    "sig": ("pref-inc", m["trunk"]),
                    "parse": {"n": int(m["n"])}}
        m = cls._PREF_REINDUCT_RE.match(text)
        if m:
            return {"kind": "pref",
                    "title": t("偏好画像「{trunk}」重新归纳", trunk=m["trunk"]),
                    "meta": t("{kept} 条确认保留 · {new} 条新归纳",
                              kept=m["kept"], new=m["new"]),
                    "is_auto": True, "sig": None, "parse": {}}
        m = cls._PREF_SELF_RE.match(text)
        if m:
            return {"kind": "pref",
                    "title": t("偏好画像「{trunk}」自动整理", trunk=m["trunk"]),
                    "meta": t("{before} 条 → {after} 条",
                              before=m["before"], after=m["after"]),
                    "is_auto": True, "sig": None, "parse": {}}
        m = cls._PREF_EDIT_RE.match(text)
        if m:
            return {"kind": "pref",
                    "title": t("你编辑了偏好画像「{trunk}」", trunk=m["trunk"]),
                    "meta": "", "is_auto": False,
                    "sig": None, "parse": {}}
        m = cls._ACH_RE.match(text)
        if m:
            return {"kind": "ach",
                    "title": t("解锁 {n} 个成就", n=m["n"]),
                    "meta": m["names"], "is_auto": True,
                    "sig": None, "parse": {}}
        # 兜底：原文照显（用户编辑过的节点 / 新模板），不参与合并
        return {"kind": "other", "title": text, "meta": "",
                "is_auto": "[auto]" in text, "sig": None, "parse": {}}

    @classmethod
    def _dot_color(cls, kind: str) -> str:
        return getattr(C, cls._KIND_DOT[kind])

    # ---------- 按天分组 + ×N 合并（纯展示层） ----------

    @classmethod
    def _tl_group_by_day(cls, nodes: list) -> list[tuple[str, list[dict]]]:
        """nodes（新在前）→ [(day, [合并组...])]。

        固化降级（阀门二）：带 solidified 的复盘节点先摘出，挂到列表中位于其
        上方（时间更新，蒸馏必晚于复盘）的同 path 最近 distill 里程碑节点下，
        作为「原料」子块（默认折叠）；匹配不到里程碑（节点被删 / 被 1000 行
        封顶裁掉）→ 留在原日按普通节点渲染 +「已固化 v{ver}」chip，不丢信息。
        """
        infos: list[dict] = []
        for nd in nodes:
            infos.append({**nd, **cls._humanize_node(nd)})
        sources_by_target: dict[int, list[dict]] = {}
        keep: list[dict] = []
        for i, info in enumerate(infos):
            if info.get("solidified") and info.get("_src_path"):
                target = None
                for j in range(i - 1, -1, -1):
                    dp = infos[j].get("distill_path")
                    if dp and dp == info["_src_path"]:
                        target = j
                        break
                if target is not None:
                    sources_by_target.setdefault(target, []).append(info)
                    continue
            keep.append(info)
        for j, srcs in sources_by_target.items():
            target = infos[j]
            target["sources"] = srcs
            # 里程碑节点 meta 追加「含 {n} 条源复盘」，让折叠块的存在有交代
            extra = t("含 {n} 条源复盘", n=len(srcs))
            target["meta"] = (f"{target['meta']} · {extra}"
                              if target.get("meta") else extra)
        days: list[tuple[str, list[dict]]] = []
        for info in keep:
            day = (info.get("ts") or "")[:10]
            if days and days[-1][0] == day:
                days[-1][1].append(info)
            else:
                days.append((day, [info]))
        return [(day, cls._tl_merge(items)) for day, items in days]

    @classmethod
    def _tl_merge(cls, items: list[dict]) -> list[dict]:
        """同日连续同 sig 节点 → 一个展示组（数据不动，编辑/删除仍逐条）。"""
        groups: list[dict] = []
        for info in items:
            sig = info["sig"]
            if sig and groups and groups[-1]["sig"] == sig:
                groups[-1]["items"].append(info)
            else:
                groups.append({"sig": sig, "items": [info]})
        for g in groups:
            grp = g["items"]
            first = grp[0]
            g["kind"] = first["kind"]
            g["meta"] = first["meta"]
            g["is_auto"] = any(i["is_auto"] for i in grp)
            g["count"] = len(grp)
            # 固化源复盘子块随单节点组（distill 里程碑）传递
            g["sources"] = first.get("sources") if len(grp) == 1 else None
            if len(grp) == 1:
                g["title"] = first["title"]
            elif g["sig"][0] == "review":
                g["title"] = t("从 {k} 次会话共学到 {n} 条新经验",
                               k=len(grp), n=sum(i["parse"]["n"] for i in grp))
            elif g["sig"][0] == "self":
                g["title"] = t("{agent} 自报 {n} 条经验，已自动入库",
                               agent=g["sig"][2], n=len(grp))
            elif g["sig"][0] == "pref-inc":
                g["title"] = t("偏好画像「{trunk}」自动归纳 {n} 条新偏好",
                               trunk=g["sig"][1],
                               n=sum(i["parse"]["n"] for i in grp))
            else:
                g["title"] = first["title"]
        return groups

    # ---------- 渲染 ----------

    def _tl_rebuild(self, animate: bool = False) -> None:
        self._tl_anim = animate   # 供 _tl_rail 决定是否播入场（数据变才播）
        while self._tl_lay.count():
            item = self._tl_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        for day, groups in self._tl_groups:
            expanded = self._tl_show_all or day in self._tl_expanded_days
            if not expanded:
                self._tl_lay.addWidget(self._tl_day_fold(day, groups))
                continue
            n_nodes = sum(g["count"] for g in groups)
            self._tl_lay.addWidget(self._tl_day_header(day, n_nodes, day == today))
            for gi, g in enumerate(groups):
                is_last_group = gi == len(groups) - 1
                if g["count"] == 1:
                    item = g["items"][0]
                    has_sources = bool(item.get("sources"))
                    # 里程碑下还有源复盘子块时，轨道线不能停在圆点（防断线）
                    self._tl_lay.addWidget(
                        self._tl_node_row(item, is_last_group and not has_sources))
                    # 固化源复盘子块（阀门二）：默认折叠成一行「源复盘 ×N」
                    if has_sources:
                        self._tl_lay.addWidget(
                            self._tl_source_block(item, is_last_group))
                elif (day, gi) in self._tl_expanded_groups:
                    for ii, item in enumerate(g["items"]):
                        self._tl_lay.addWidget(self._tl_node_row(
                            item, is_last_group and ii == len(g["items"]) - 1))
                    self._tl_lay.addWidget(
                        self._tl_group_fold_btn(day, gi, g, is_last_group))
                else:
                    self._tl_lay.addWidget(
                        self._tl_group_row(day, gi, g, is_last_group))
        btn = btn_flat(
            t("收起") if self._tl_show_all
            else t("展开全部 {n} 个节点", n=self._tl_total),
            on_click=self._tl_toggle_all)
        btn_w = QWidget()
        bl = QHBoxLayout(btn_w)
        bl.setContentsMargins(S.s2, S.s1, S.s2, S.s2)
        bl.addWidget(btn)
        self._tl_lay.addWidget(btn_w)

    def _tl_rail(self, dot_color: str, last: bool, dot: bool = True) -> _TlRail:
        """建时间轴轨道；本轮是"数据变了"的重建才播入场，
        展开/收起触发的重建不重播（避免每次点击都闪一下）。"""
        rail = _TlRail(dot_color, last, dot=dot)
        if self._tl_anim:
            rail.animate_in()
        return rail

    def _tl_day_header(self, day: str, n: int, is_today: bool) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(S.s2, S.s3, S.s2, S.s1)
        hl.setSpacing(S.s2)
        hl.addWidget(txt(day or t("无日期"), F.body, 700, C.ink_700))
        if is_today:
            hl.addWidget(chip(t("今天"), "brand"))
        hl.addStretch(1)
        hl.addWidget(txt(t("{n} 个节点", n=n), F.caption, color=C.ink_500))
        return row

    def _tl_day_fold(self, day: str, groups: list[dict]) -> QWidget:
        n = sum(g["count"] for g in groups)
        row = QWidget()
        row.setObjectName("tlDayFold")
        row.setAttribute(Qt.WA_Hover, True)
        row.setCursor(Qt.PointingHandCursor)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(S.s2, S.s2, S.s2, S.s2)
        hl.setSpacing(S.s2)
        icon = RotatingIcon("EXPAND_MORE_OUTLINED", 14, C.ink_500)
        hl.addWidget(icon, 0, Qt.AlignVCenter)
        hl.addWidget(txt(day or t("无日期"), F.body, 600, C.ink_700))
        hl.addStretch(1)
        hl.addWidget(txt(t("{n} 个节点", n=n), F.caption, color=C.ink_500))
        def _toggle():
            icon.setRotation(180)
            self._tl_expanded_days.add(day)
            self._tl_rebuild()
        row.mousePressEvent = lambda e: _toggle()
        return row

    def _tl_group_row(self, day: str, gi: int, g: dict, last: bool) -> QWidget:
        """×N 合并组的摘要行（点击整行展开逐条，chevron 提示）。"""
        key = (day, gi)
        row = QWidget()
        row.setObjectName("tlGroup")
        row.setAttribute(Qt.WA_Hover, True)
        row.setCursor(Qt.PointingHandCursor)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(S.s2, S.s1, S.s2, S.s1)
        hl.setSpacing(S.s2)
        hl.addWidget(self._tl_rail(self._dot_color(g["kind"]), last))
        body, bl = self._tl_text_body(
            g["kind"], g["title"], g["meta"], g["is_auto"], extra_chips=[
                chip(t("×{n}", n=g["count"]), "ink")])
        hl.addWidget(body, 1)
        # 与按天/源复盘折叠一致的 chevron：提示整行可点击展开逐条（数据层不动）
        hl.addWidget(RotatingIcon("EXPAND_MORE_OUTLINED", 14, C.ink_500),
                     0, Qt.AlignTop)
        row.mousePressEvent = lambda e, k=key: self._tl_toggle_group(k)
        return row

    def _tl_group_fold_btn(self, day: str, gi: int, g: dict, last: bool) -> QWidget:
        """×N 组展开后的「收起」行（缩进与节点正文对齐）。"""
        btn_w = QWidget()
        bl = QHBoxLayout(btn_w)
        indent = S.s2 + _TlRail.RAIL_W + S.s2
        bl.setContentsMargins(indent, 0, S.s2, S.s1)
        bl.addWidget(btn_flat(
            t("收起"),
            on_click=lambda _=False, k=(day, gi): self._tl_toggle_group(k)))
        return btn_w

    def _tl_node_row(self, item: dict, last: bool) -> QWidget:
        row = QWidget()
        row.setObjectName("tlRow")
        row.setAttribute(Qt.WA_Hover, True)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(S.s2, S.s1, S.s2, S.s1)
        hl.setSpacing(S.s2)
        hl.addWidget(self._tl_rail(self._dot_color(item["kind"]), last))
        extra_chips = []
        if item.get("solidified") and not item.get("sources"):
            # 匹配不到里程碑（被删/被封顶）→ 普通节点 + chip，不丢信息
            extra_chips.append(chip(
                t("已固化 v{ver}", ver=str(item["solidified"]).lstrip("v")),
                "ok"))
        body, _bl = self._tl_text_body(
            item["kind"], item["title"], item["meta"], item["is_auto"],
            extra_chips=extra_chips)
        hl.addWidget(body, 1)
        more = ellipsis_button(tooltip=t("更多操作"), size=24)
        more.clicked.connect(
            lambda _=False, i=item["idx"], a=more, tx=item.get("text", ""):
                self._tl_menu(i, tx, a))
        hl.addWidget(more, 0, Qt.AlignTop)
        return row

    def _tl_source_block(self, item: dict, last: bool) -> QWidget:
        """固化源复盘子块（阀门二）：默认折叠成一行「源复盘 ×N」（chevron
        点击展开）；展开逐条渲染源节点，每条保留自己的 ⋯ 菜单（编辑/删除
        仍按行号 idx，数据层不变）。"""
        key = item["idx"]
        sources = item.get("sources") or []
        indent = S.s2 + _TlRail.RAIL_W + S.s2
        # 「展开全部 N 个节点」= 真正全部：完全展开模式下源子块一并展开
        # （否则按钮承诺"全部节点"，源复盘仍藏在折叠行里）；「收起」回默认态
        if key in self._tl_expanded_sources or self._tl_show_all:
            w = QWidget()
            vl = QVBoxLayout(w)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(0)
            for ii, src in enumerate(sources):
                vl.addWidget(self._tl_source_row(
                    src, last and ii == len(sources) - 1))
            btn_w = QWidget()
            bl = QHBoxLayout(btn_w)
            bl.setContentsMargins(indent, 0, S.s2, S.s1)
            bl.addWidget(btn_flat(
                t("收起"),
                on_click=lambda _=False, k=key: self._tl_toggle_source(k)))
            vl.addWidget(btn_w)
            return w
        # 折叠行
        row = QWidget()
        row.setObjectName("tlSrcFold")
        row.setAttribute(Qt.WA_Hover, True)
        row.setCursor(Qt.PointingHandCursor)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(S.s2, S.s1, S.s2, S.s1)
        hl.setSpacing(S.s2)
        hl.addWidget(self._tl_rail(getattr(C, "ink_300"), last, dot=False))
        inner = QWidget()
        il = QHBoxLayout(inner)
        il.setContentsMargins(S.s2, 0, 0, 0)
        il.setSpacing(S.s1)
        il.addWidget(RotatingIcon("EXPAND_MORE_OUTLINED", 14, C.ink_500),
                     0, Qt.AlignVCenter)
        il.addWidget(txt(t("源复盘"), F.caption, 600, C.ink_500),
                     0, Qt.AlignVCenter)
        il.addWidget(chip(t("×{n}", n=len(sources)), "ink"), 0, Qt.AlignVCenter)
        il.addStretch(1)
        hl.addWidget(inner, 1)
        row.mousePressEvent = lambda e: self._tl_toggle_source(key)
        return row

    def _tl_source_row(self, src: dict, last: bool) -> QWidget:
        """源复盘子块逐条行：缩进表示从属，保留自己的 ⋯ 菜单。"""
        row = QWidget()
        row.setObjectName("tlSrcRow")
        row.setAttribute(Qt.WA_Hover, True)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(S.s2, S.s1, S.s2, S.s1)
        hl.setSpacing(S.s2)
        hl.addWidget(self._tl_rail(getattr(C, "ink_300"), last))
        body, bl = self._tl_text_body(
            src["kind"], src["title"], src["meta"], src["is_auto"])
        bl.setContentsMargins(S.s2, 0, 0, 0)  # 缩进：从属于上方里程碑
        hl.addWidget(body, 1)
        more = ellipsis_button(tooltip=t("更多操作"), size=24)
        more.clicked.connect(
            lambda _=False, i=src["idx"], a=more, tx=src.get("text", ""):
                self._tl_menu(i, tx, a))
        hl.addWidget(more, 0, Qt.AlignTop)
        return row

    @staticmethod
    def _tl_text_body(kind: str, title: str, meta: str, is_auto: bool,
                      extra_chips: list | None = None) -> tuple[QWidget, QVBoxLayout]:
        """节点正文：类型 chip +（×N）+ [auto] 标 + 标题，下方灰色 meta 行。"""
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(S.s1)
        l1 = QHBoxLayout()
        l1.setContentsMargins(0, 0, 0, 0)
        l1.setSpacing(S.s1)
        # staticmethod 里取类级常量：用本文件内的类名（原先是 GrowthPage.XXX，
        # 搬出后 GrowthPage 已不在本模块作用域）。不 import 原模块，避免循环。
        l1.addWidget(chip(t(TimelineMixin._KIND_LABEL[kind]),
                          TimelineMixin._KIND_TONE[kind]))
        for c in extra_chips or []:
            l1.addWidget(c)
        if is_auto:
            l1.addWidget(chip("[auto]", "ink"))
        tx = txt(title, F.body, 600)
        tx.setWordWrap(True)
        l1.addWidget(tx, 1, Qt.AlignTop)
        bl.addLayout(l1)
        if meta:
            bl.addWidget(txt(meta, F.caption, color=C.ink_500))
        return body, bl

    # ---------- 折叠/展开 ----------

    def _tl_toggle_group(self, key: tuple) -> None:
        if key in self._tl_expanded_groups:
            self._tl_expanded_groups.discard(key)
        else:
            self._tl_expanded_groups.add(key)
        self._tl_rebuild()

    def _tl_toggle_source(self, key: int) -> None:
        if key in self._tl_expanded_sources:
            self._tl_expanded_sources.discard(key)
        else:
            self._tl_expanded_sources.add(key)
        self._tl_rebuild()

    def _tl_toggle_all(self) -> None:
        if self._tl_show_all:
            self._tl_show_all = False
            self._tl_expanded_groups.clear()
            self._tl_expanded_sources.clear()
            first_day = self._tl_groups[0][0] if self._tl_groups else ""
            self._tl_expanded_days = {first_day}
        else:
            self._tl_show_all = True
        self._tl_rebuild()

    def _tl_menu(self, idx: int, text: str, anchor: QWidget) -> None:
        menu = QMenu(self)
        act_edit = menu.addAction(t("编辑"))
        act_edit.triggered.connect(lambda: self._edit_node(idx, text))
        act_del = menu.addAction(t("删除"))
        act_del.triggered.connect(lambda: self._delete_node(idx))
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 2)))

