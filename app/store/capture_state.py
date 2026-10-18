"""`Store` 的「捕获状态」域 mixin（增量扫描水位 + hooks 观测）。

从 `store.py` 的 `class Store` 拆出的第十个域。承载两块：

- **增量扫描水位**：`capture_state.json` / `capture_failures.json` /
  `detected_agents.json` / `capture_hits.json`——扫描靠 size+mtime 判断"这轮
  要不要重读"，这些是它的记忆。
- **hooks 观测与令牌**：`record_hook_observed` / `load_hook_observed` /
  `hook_ingest_token`（注入通道的防伪令牌）。

约定与其余 mixin 一致：方法体逐字搬移、签名与返回值不变；共享状态（`data_dir`、
`_write_lock`、`_iter_jsonl`、`_cap_jsonl_lines`）留在 `Store` 主体、靠 `self`
访问；**不 import `store.py`**（避免与 `class Store` 的组装形成循环导入）。
"""

from __future__ import annotations

import json
import os
import secrets

from ._shared import utcnow


class CaptureStateMixin:
    """扫描增量水位与 hooks 观测的读写。"""

    def load_capture_state(self) -> dict:
        path = self.data_dir / "capture_state.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def save_capture_state(self, state: dict) -> None:
        self._write_json_tmp_rename(self.data_dir / "capture_state.json", state)

    def load_capture_failures(self) -> dict:
        """agent → 连续解析失败轮数（格式漂移黄标用）。"""
        path = self.data_dir / "capture_failures.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def save_capture_failures(self, failures: dict) -> None:
        self._write_json_tmp_rename(self.data_dir / "capture_failures.json", failures)

    def load_detected_agents(self) -> set[str]:
        """最近一轮扫描探测到真实会话文件的 agent 集合（第 6 轮：采集清单
        只列"实际在跑"的 agent，不再铺全 REGISTRY）。扫描循环每轮更新。"""
        path = self.data_dir / "detected_agents.json"
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {str(x) for x in data} if isinstance(data, list) else set()
        except json.JSONDecodeError:
            return set()

    def save_detected_agents(self, names: list[str]) -> None:
        self._write_json_tmp_rename(self.data_dir / "detected_agents.json",
                                    sorted(set(names)))

    # ---------- 探测结果快照（GUI 启动直读，不触发全量探测） ----------

    AGENTS_SNAPSHOT_FILE = "agents_snapshot.json"

    def save_agents_snapshot(self, counts: dict[str, int]) -> None:
        """agent → 会话引用数的落盘快照 + 采集时间。

        由权威探测处（扫描循环 / 启动预热线程）每次探测后覆盖写入；
        `/api/status`、`/api/agents` 只读它，绝不在请求线程触发 detect()。
        """
        safe = {}
        for k, v in (counts or {}).items():
            try:
                safe[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        self._write_json_tmp_rename(self.data_dir / self.AGENTS_SNAPSHOT_FILE,
                                    {"agents": safe, "at": utcnow()})

    def load_agents_snapshot(self) -> dict:
        """{agents: {agent: count}, at: ISO}；缺文件/坏文件/坏形状 → {}。"""
        path = self.data_dir / self.AGENTS_SNAPSHOT_FILE
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(data, dict):
            return {}
        raw = data.get("agents")
        if not isinstance(raw, dict):
            return {}
        agents: dict[str, int] = {}
        for k, v in raw.items():
            try:
                agents[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        return {"agents": agents, "at": str(data.get("at") or "")}

    # ---------- 捕获命中流水（W1-05：轻量 jsonl，滚动截断防膨胀） ----------

    CAPTURE_HITS_MAX_LINES = 1000

    def record_capture_hit(self, agent: str, path: str, events: int) -> None:
        """扫描命中一行：{agent, path, ts, events}。调用方保证每轮每 agent ≤1 行。"""
        rec = {
            "agent": agent,
            "path": str(path),
            "events": int(events or 0),
            "ts": utcnow(),
        }
        with self._write_lock:
            self._append_jsonl_capped(self.data_dir / "capture_hits.jsonl",
                                      rec, self.CAPTURE_HITS_MAX_LINES)

    def load_capture_hits(self, limit: int = 200) -> list[dict]:
        """命中流水（新在后）；坏行跳过。"""
        out = []
        for rec in self._iter_jsonl("capture_hits.jsonl"):
            if isinstance(rec, dict) and rec.get("agent"):
                out.append(rec)
        return out[-limit:]

    # ---------- Hook 生效（observed，memorax 借鉴 A2）：installed→observed 验证 ----------

    HOOK_OBSERVED_FILE = "hook_observed.json"

    def record_hook_observed(self, agent: str, event: str) -> None:
        """记录一次真实 hook 事件已到达（agent:event → ISO ts，原子写）。

        供 GUI「已写入配置 / 已生效」两态判断：只写配置不算数，收到过一次
        SessionStart/UserPromptSubmit 才算 observed（与 memorax installed→observed 同口径）。
        """
        if not agent or not event:
            return
        with self._write_lock:
            pathf = self.data_dir / self.HOOK_OBSERVED_FILE
            data: dict = {}
            if pathf.exists():
                try:
                    raw = json.loads(pathf.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        data = raw
                except (json.JSONDecodeError, OSError):
                    data = {}
            data[f"{agent}:{event}"] = utcnow()
            self._write_json_tmp_rename(pathf, data)

    def load_hook_observed(self) -> dict:
        """{agent:event: ISO ts}；坏文件/缺文件 → 空。"""
        pathf = self.data_dir / self.HOOK_OBSERVED_FILE
        if not pathf.exists():
            return {}
        try:
            data = json.loads(pathf.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    # ---------- Hook 事件通道防伪令牌 ----------
    # 8101 的 /api/hooks/*-event 端点无 Bearer 鉴权（外部 agent 的 curl / http
    # hook 带不了主 API token），任何本机进程可伪造事件灌进复盘通道。用一个独立
    # 的低权限"报信令牌"：注入 hook 命令时以 ?key= 查询参数带上，事件端点校验之。
    # 与主 API token 分离——泄漏只影响 fail-open 的事件通道，不会交出整个本地 API。
    HOOK_TOKEN_FILE = "hook_ingest.key"

    def hook_ingest_token(self) -> str:
        """事件通道防伪令牌：首次调用生成并落 data_dir（尽力 0600），之后原样返回。

        幂等 + 并发安全（创建在 _write_lock 内、双检）。这里刻意不做 DPAPI 加密：
        令牌值本就随 hook 命令明文写进第三方配置文件（~/.claude、~/.cursor…），
        再加密本地副本意义有限；安全价值在"每次安装随机、本机其它进程猜不到"，
        不在本地静态保密。POSIX 收紧 0600，Windows 无 POSIX 权限位（best-effort）。"""
        path = self.data_dir / self.HOOK_TOKEN_FILE
        try:
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except (FileNotFoundError, OSError):
            existing = ""
        with self._write_lock:
            if existing:
                return existing
            # 双检：等锁期间可能另一线程已创建
            try:
                again = path.read_text(encoding="utf-8").strip()
            except (FileNotFoundError, OSError):
                again = ""
            if again:
                return again
            token = secrets.token_urlsafe(24)
            self._write_tmp_rename(path, token)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return token

