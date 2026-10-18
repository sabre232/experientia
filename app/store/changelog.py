"""`Store` 的「学习历程（changelog）」域 mixin。

从 `store.py` 的 `class Store` 拆出的第五个域。只做不动语义的搬家，约定：

1. 方法体逐字搬移，签名与返回值一律不变；
2. 共享状态（`data_dir`、`_write_lock`、`_write_tmp_rename`、`_cap_jsonl_lines`）
   留在 `Store` 主体，mixin 通过 `self` 访问，**不复制状态**；
3. 需要模块级小工具时从 `._shared` 取，不 import `store.py`（避免循环导入）。

本模块同时持有 changelog 机器标记的定义与解析/格式化——它们只服务于
`changelog.md`，随域走；`store.py` 保留同名再导出以兼容既有 import。

**机器标记是 changelog 的唯一事实来源**：GUI 侧只消费，不得重建正则去猜
（见报告 M4 订正：`growth._humanize_node` 因误判曾被错列为"未修"）。
"""

from __future__ import annotations

import json
import re

from ._shared import utcnow

CHANGELOG_MAX_LINES = 1000       # 成就 legacy 判定只读最近 200 条，远在窗口内
MAINTENANCE_LOG_MAX_LINES = 200  # C1 日志本身就是"最近 N 次维护"语义

CHLOG_KINDS = frozenset((
    "review", "self", "distill", "fixes", "veto", "rename",
    "pref-inc", "pref-reinduct", "pref-self", "pref-edit", "ach",
    "ai-rewrite",
    # 两个此前写不进 changelog 的 kind（append_event 会 raise ValueError，
    # 调用方各自 try/except 吞掉 → 记录静默丢失）：
    # - governance：内容治理（扫了多少张、标了多少张，只标记不删除）；
    # - guard：策展守卫告警（产出可疑/丢失已固化失败模式）。
    # 展示层对未专门分派的 kind 走通用分支（原文照显），新增不会破坏既有解析。
    "governance", "guard",
))
_CHLOG_TAG_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<kind>[a-z][a-z0-9-]*)"
    r"(?P<pairs>(?:\s+[a-z][a-z0-9-]*=[^\s\[\]]+)*?)\]\s+(?P<text>.*)$")
_CHLOG_PAIR_RE = re.compile(r"[a-z][a-z0-9-]*=[^\s\[\]]+")


def _parse_changelog_line(line: str) -> tuple[str, dict | None, str]:
    """changelog 行 → (ts, tag, text)。

    v2 标记行 → tag={"kind": ..., k: v, ...}；legacy 行（无标记）、kind 不在
    枚举、或标记解析失败 → tag=None、text 原样（不抛错、不合并、不折叠）。"""
    rest = line.lstrip("- ").strip()
    m = _CHLOG_TAG_RE.match(rest)
    if m and m["kind"] in CHLOG_KINDS:
        tag: dict[str, str] = {"kind": m["kind"]}
        for pair in _CHLOG_PAIR_RE.findall(m["pairs"]):
            k, _, v = pair.partition("=")
            tag[k] = v
        return m["ts"].strip(), tag, m["text"].strip()
    ts = ""
    if rest.startswith("[") and "] " in rest:
        ts, _, rest = rest[1:].partition("] ")
        ts = ts.strip()
    return ts, None, rest


def _read_changelog_lines(path) -> list[str]:
    """changelog.md → 非空行列表。**全文件唯一的行号口径**。

    原来 list/edit/delete 用原始行号（含用户手掺的空行），
    而 append/upsert/mark_solidified 用非空行序号——两套口径在含空行的文件上
    错位，edit/delete 会改错节点、把错行归档进 deprecated。现统一为非空行
    序号；edit/delete 落盘时顺带抹掉空行，一次性收敛到同一口径。"""
    if not path.exists():
        return []
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _format_changelog_line(ts: str, tag: dict | None, text: str) -> str:
    """(ts, tag, text) → changelog 行（tag 为 None 时即 legacy 格式）。"""
    if tag:
        pairs = " ".join(f"{k}={v}" for k, v in tag.items() if k != "kind")
        tag_str = f"[{tag['kind']}" + (f" {pairs}" if pairs else "") + "]"
        return f"- [{ts}] {tag_str} {text}"
    return f"- [{ts}] {text}"


class ChangelogMixin:
    """`changelog.md` 的追加 / 事件标记 / 复盘节点 upsert。"""

    def _append_changelog_line(self, line: str) -> int:
        """追加一行 changelog 并封顶，返回新行的行号 idx（调用方持有 _write_lock）。

        封顶后文件保留最新 CHANGELOG_MAX_LINES 行，新行恒在末行。"""
        path = self.data_dir / "changelog.md"
        existing = 0
        if path.exists():
            existing = len(_read_changelog_lines(path))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        # 写点封顶 1000 行（留最新；成就 legacy 判定只读最近 200 条，
        # 远在窗口内）
        self._cap_jsonl_lines(path, CHANGELOG_MAX_LINES)
        return min(existing, CHANGELOG_MAX_LINES - 1)

    def append_changelog(self, entry: str) -> int:
        with self._write_lock:
            return self._append_changelog_line(f"- [{utcnow()}] {entry}")

    def append_event(self, kind: str, text: str, **fields) -> int:
        """追加带 v2 机器标记的节点 `- [ts] [kind k=v ...] text`，返回行号 idx。

        标记值是机器身份（不含空格/方括号）；人话文本是用户陈述，两者独立。
        空值字段跳过。1000 行封顶行为与 append_changelog 一致（只作用于新事件）。
        """
        if kind not in CHLOG_KINDS:
            raise ValueError(f"未知 changelog kind: {kind!r}")
        pairs = " ".join(f"{k}={v}" for k, v in fields.items()
                         if v not in (None, ""))
        tag_str = f"[{kind}" + (f" {pairs}" if pairs else "") + "]"
        with self._write_lock:
            return self._append_changelog_line(
                f"- [{utcnow()}] {tag_str} {text}")

    def upsert_review_node(self, agent: str, session_id: str, added: int,
                           text: str) -> int:
        """复盘节点 upsert（学习历程信息量控制·阀门一），返回行号 idx。

        持 _write_lock 扫 changelog 全部行，找 kind=review 且 agent/sid 匹配的
        最新行：
          命中 → 原地改标记：n += added、times += 1（文本段字节不动，保留首次
                 通道的措辞——通道是机制词，展示不关心通道）
          未命中（含用户已删除该节点）→ append 新节点，text = 传入的既有模板
        不依赖复盘台账做去重：台账语义是「入队一次」，台账挤出 / hook 重启都会
        让同一会话合法地再复盘一次——upsert 是展示层兜底，与台账正交，台账照跑。
        用户删过该节点 → 未命中 → append：删除语义是「这条别给我看」，新发生的
        事件仍要出现。session_id 为空 → 无机器身份，合并会误并不同会话，
        降级为普通 append（legacy 行）。"""
        sid = str(session_id)
        added = max(0, int(added))
        with self._write_lock:
            path = self.data_dir / "changelog.md"
            lines = _read_changelog_lines(path)
            if sid:
                hit = None
                for i in range(len(lines) - 1, -1, -1):
                    _ts, tag, _text = _parse_changelog_line(lines[i])
                    if (tag and tag.get("kind") == "review"
                            and tag.get("agent") == agent
                            and tag.get("sid") == sid):
                        hit = i
                        break
                if hit is not None:
                    ts, tag, node_text = _parse_changelog_line(lines[hit])
                    tag["n"] = str(int(tag.get("n") or 0) + added)
                    tag["times"] = str(int(tag.get("times") or 1) + 1)
                    lines[hit] = _format_changelog_line(ts, tag, node_text)
                    self._write_tmp_rename(path, "\n".join(lines) + "\n")
                    return hit
            return self._append_changelog_line(
                f"- [{utcnow()}] [review agent={agent} sid={sid} "
                f"n={added} times=1] {text}" if sid
                else f"- [{utcnow()}] {text}")

    def list_changelog(self) -> list[dict]:
        """changelog.md 逐行 → [{idx, ts, text, tag}]（idx = 行号，供编辑/删除定位）。

        tag：v2 机器标记 dict|None（见 _parse_changelog_line）；legacy 行（无标记）
        为 None，展示层回退人话化正则，不合并、不折叠。"""
        path = self.data_dir / "changelog.md"
        if not path.exists():
            return []
        out = []
        # idx = 非空行序号（与 append/upsert/edit/delete
        # 同一口径）；原实现用原始行号，用户手掺空行后全部错位。
        for i, line in enumerate(_read_changelog_lines(path)):
            ts, tag, text = _parse_changelog_line(line)
            out.append({"idx": i, "ts": ts, "text": text, "tag": tag})
        return out

    def edit_changelog(self, idx: int, text: str) -> bool:
        """编辑节点文本段；[ts] 前缀与 v2 标记段原样保留（标记是机器状态，
        文本是用户陈述，两者独立）。"""
        with self._write_lock:
            path = self.data_dir / "changelog.md"
            if not path.exists():
                return False
            # 非空行序号口径（与 list_changelog 一致）；
            # 落盘顺带抹掉用户手掺的空行，一次性收敛。
            lines = _read_changelog_lines(path)
            if idx >= len(lines):
                return False
            old = lines[idx]
            if old.startswith("- "):
                ts, tag, _old_text = _parse_changelog_line(old)
                prefix = ""
                if ts:
                    prefix += f"[{ts}] "
                if tag:
                    pairs = " ".join(f"{k}={v}" for k, v in tag.items()
                                     if k != "kind")
                    tag_str = f"[{tag['kind']}" + (f" {pairs}" if pairs else "") + "]"
                    prefix += f"{tag_str} "
                body = f"- {prefix}{text}"
            else:
                body = text if text.startswith("- ") else f"- {text}"
            lines[idx] = body
            self._write_tmp_rename(path, "\n".join(lines) + "\n")
        return True

    # ---------- 整理日志（maintenance.log，档 C  C1-4） ----------

    def log_maintenance(self, actions: dict) -> None:
        """档 C 每次跑完落一行（时间 + 各动作前后计数，C1-4）。"""
        with self._write_lock:
            with (self.data_dir / "maintenance.log").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": utcnow(), **actions},
                                    ensure_ascii=False) + "\n")
            # 写点封顶 200 行（C1 日志本身就是"最近 N 次维护"语义）
            self._cap_jsonl_lines(self.data_dir / "maintenance.log",
                                  MAINTENANCE_LOG_MAX_LINES)

    def read_maintenance(self, limit: int = 50) -> list[dict]:
        """整理日志（新在前）；坏行跳过。成长页时间线展示用。"""
        out = [r for r in self._iter_jsonl("maintenance.log") if isinstance(r, dict)]
        return out[-limit:][::-1]

    def delete_changelog(self, idx: int) -> bool:
        """删除 = 归档（进 deprecated/ 保留 30 天可恢复，/），不物理删。"""
        with self._write_lock:
            path = self.data_dir / "changelog.md"
            if not path.exists():
                return False
            # 非空行序号口径（与 list_changelog 一致）。
            lines = _read_changelog_lines(path)
            if idx >= len(lines):
                return False
            removed = lines.pop(idx)
            day_dir = self.deprecated_day_dir()
            dest = day_dir / "changelog"
            # 归档文件也走原子写——原地 write_text 崩在
            # 中间会留下半截归档，30 天可恢复机制直接失效
            # 当日首次删除时归档文件尚不存在（直接 read 会 FileNotFoundError）
            archived = dest.read_text(encoding="utf-8") if dest.exists() else ""
            self._write_tmp_rename(dest, archived + removed + "\n")
            self._write_tmp_rename(path, "\n".join(lines) + "\n")
        return True

    def mark_solidified(self, agent: str, session_id: str, ver: str) -> bool:
        """给 (agent, sid) 对应的 review 节点标记追加 solidified=ver（阀门二回填，
        只改标记段，文本字节不动）。节点不存在（被删/被封顶裁掉）→ False，
        静默（蒸馏流程不中断）。"""
        sid = str(session_id)
        if not sid:
            return False
        with self._write_lock:
            path = self.data_dir / "changelog.md"
            if not path.exists():
                return False
            lines = _read_changelog_lines(path)
            for i in range(len(lines) - 1, -1, -1):
                ts, tag, text = _parse_changelog_line(lines[i])
                if (tag and tag.get("kind") == "review"
                        and tag.get("agent") == agent
                        and tag.get("sid") == sid):
                    tag["solidified"] = ver
                    lines[i] = _format_changelog_line(ts, tag, text)
                    self._write_tmp_rename(path, "\n".join(lines) + "\n")
                    return True
        return False
