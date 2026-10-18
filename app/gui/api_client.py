"""GUI → 本地 API 客户端（外壳不 import 引擎，只走 HTTP）。"""

from __future__ import annotations

import os
import threading
import time

import httpx

from ..net_util import DIRECT_LOOPBACK

from .i18n import t

DEFAULT_BASE = "http://127.0.0.1:8101"


def local_api_listening(base_url: str = DEFAULT_BASE) -> bool:
    """本地 API 是否已在监听（毫秒级、不出站、纯本机 socket 调用）。

    做法：往同一地址 bind——绑得上 = 端口空闲 = 引擎还没开始监听；绑不上 =
    已经有人在听。**这是启动提速的关键**：对"还没开始监听"的本机端口发 HTTP，
    本机安全软件会在返回拒绝前先审计（实测 2.03s vs 已监听 0.002s），主线程上
    一次就冻 2 秒（引擎线程刚起、uvicorn 还没 bind 的启动窗口必然撞上）。
    调用方据此避开注定白等的请求，等引擎就绪后再走正常 HTTP 路径。

    注意：不要加 SO_REUSEADDR——Windows 上它允许绑到已被占用的端口，
    会把"有人在听"误判成"端口空闲"，探测直接失效。
    """
    import socket
    from urllib.parse import urlparse

    u = urlparse(base_url)
    host = u.hostname or "127.0.0.1"
    port = u.port or (443 if u.scheme == "https" else 80)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        try:
            s.close()
        except OSError:
            pass


# 8101 鉴权 token 常量唯一来源在 app/token_util.py（轻量、非引擎模块，
# 外壳可安全 import；不再字面复制防漂移）
from ..token_util import (TOKEN_ENV as _TOKEN_ENV,  # noqa: E402
                          TOKEN_KEYRING_SERVICE as _TOKEN_KEYRING_SERVICE,
                          TOKEN_KEYRING_USER as _TOKEN_KEYRING_USER)


class LocalApiError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail

    def localized(self) -> str:
        """服务端原因的显示文案：查词典翻译，查不到就原样返回。

        服务端按分层只管数据，错误 detail 是中文源串；翻译是外壳（UI 层）
        的事，所以在这里过一遍 `t()`。未登记的串 gettext 原样返回，行为与
        不翻译时一致——不会有"没词条就变空白"的回归。
        """
        return t(self.detail)


class LocalApi:
    def __init__(self, base_url: str = DEFAULT_BASE):
        self.base = base_url.rstrip("/")
        self._token = self._resolve_token()
        self._client = httpx.Client(base_url=self.base, timeout=15.0,
                                    mounts=DIRECT_LOOPBACK,
                                    # 显式回环连接池上限——首页一次并发 9 请求，
                                    # 默认池在极端情况下会排队；10 keep-alive / 20 上限。
                                    limits=httpx.Limits(max_keepalive_connections=10,
                                                        max_connections=20))
        if self._token:
            self._client.headers["Authorization"] = f"Bearer {self._token}"

    @staticmethod
    def _resolve_token() -> str | None:
        """env（main.py 启动时注入）→ keyring（同用户会话自取）→ 无（401 自现）。"""
        tok = os.environ.get(_TOKEN_ENV)
        if tok:
            return tok
        try:
            import keyring

            return keyring.get_password(_TOKEN_KEYRING_SERVICE, _TOKEN_KEYRING_USER)
        except Exception:
            return None

    def _request(self, method: str, path: str, json: dict | None = None,
                 params: dict | None = None, timeout: float | None = None) -> dict:
        try:
            r = self._client.request(method, path, json=json, params=params, timeout=timeout)
        except httpx.ConnectError:
            raise LocalApiError(0, t("本地 API 未连接")) from None
        except httpx.HTTPError as exc:  # 超时/读断/协议错——httpx 异常族全收口
            raise LocalApiError(0, f"{t('本地 API 未连接')}：{type(exc).__name__}") from None
        if r.status_code == 401:
            raise LocalApiError(401, t("本地 API 鉴权失败（token 不一致，请重启应用）")) from None
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise LocalApiError(r.status_code, str(detail))
        return r.json()

    # ---------- 状态 ----------

    def status(self) -> dict:
        return self._request("GET", "/api/status")

    def plugin_generate(self) -> dict:
        """C-2：生成 Claude 官方插件包（阶段 C，POST /api/hooks/plugin/generate）。"""
        return self._request("POST", "/api/hooks/plugin/generate")

    def workspaces(self) -> dict:
        """E-1：按工作区聚合的会话索引（GET /api/workspaces）。"""
        return self._request("GET", "/api/workspaces")

    def capture_status(self) -> dict:
        return self._request("GET", "/api/capture/status")

    def capture(self) -> dict:
        return self._request("GET", "/api/capture")

    # ---------- 账本与坑卡（修复方案首屏素材） ----------

    def ledger(self) -> dict:
        return self._request("GET", "/api/ledger")

    def rule_cards(self, limit: int = 8) -> dict:
        return self._request("GET", "/api/rule-cards", params={"limit": limit})

    def pending_fragments(self) -> dict:
        return self._request("GET", "/api/pending-fragments")

    def session_view(self, agent: str, sid: str) -> dict:
        return self._request("GET", "/api/session-view",
                             params={"agent": agent, "sid": sid})

    def search(self, q: str, limit: int = 20) -> dict:
        return self._request("GET", "/api/search",
                             params={"q": q, "limit": limit})

    def set_capture(self, name: str, enabled: bool) -> dict:
        return self._request("POST", "/api/capture",
                             json={"name": name, "enabled": enabled})

    # ---------- 模型 ----------

    def models(self) -> dict:
        return self._request("GET", "/api/models")

    def add_model(self, name: str, endpoint: str, model: str,
                  mtype: str = "cloud", key: str | None = None) -> dict:
        return self._request("POST", "/api/models", json={
            "name": name, "endpoint": endpoint, "model": model,
            "type": mtype, "key": key,
        })

    def check_model(self) -> dict:
        return self._request("POST", "/api/models/check", timeout=60.0)

    def set_default(self, name: str) -> dict:
        return self._request("POST", f"/api/models/{name}/set-default")

    def set_distill(self, name: str) -> dict:
        return self._request("POST", f"/api/models/{name}/set-distill")

    def clear_distill(self) -> dict:
        return self._request("POST", "/api/models/clear-distill")

    def remove_model(self, name: str) -> dict:
        return self._request("DELETE", f"/api/models/{name}")

    # ---------- 经验 ----------

    def experiences(self, trunk: str | None = None, category: str | None = None,
                    agent: str | None = None, q: str | None = None,
                    include_distilled: bool = True, limit: int = 300) -> dict:
        params = {"include_distilled": include_distilled, "limit": limit}
        if trunk:
            params["trunk"] = trunk
        if category:
            params["category"] = category
        if agent:
            params["agent"] = agent
        if q:
            params["q"] = q
        return self._request("GET", "/api/experiences", params=params)

    def feedback(self, exp_id: str, kind: str) -> dict:
        return self._request("POST", f"/api/experiences/{exp_id}/feedback",
                             json={"feedback": kind})

    def edit_experience(self, exp_id: str, fields: dict) -> dict:
        """纠正 = 改内容：只传要改的字段，服务端存旧值快照。"""
        return self._request("POST", f"/api/experiences/{exp_id}/edit",
                             json=dict(fields))

    # ---------- 经验演化链 / 遗忘 / 回滚（P0-3） ----------

    def experience_chain(self, exp_id: str) -> dict:
        """一条经验的完整链：历史版本 + 当前头（含证据锚点）。"""
        return self._request("GET", f"/api/experiences/{exp_id}/chain")

    def forget_experience(self, exp_id: str, hard: bool = False) -> dict:
        """用户显式遗忘。hard=True 为不可逆硬删（需二次确认）。"""
        return self._request("POST", f"/api/experiences/{exp_id}/forget",
                             json={"hard": hard})

    def unforget_experience(self, exp_id: str) -> dict:
        """撤销软忘。路径不复用 /restore——那个是"取消不采纳"，另一回事。"""
        return self._request("POST", f"/api/experiences/{exp_id}/unforget")

    def rollback_experience(self, exp_id: str, revision: int) -> dict:
        return self._request("POST", f"/api/experiences/{exp_id}/rollback",
                             json={"revision": revision})

    # ---------- L6 前瞻意图 + 六层存量（P1-1） ----------

    def intentions(self, trunk: str | None = None, limit: int = 50) -> dict:
        params = {"limit": limit}
        if trunk:
            params["trunk"] = trunk
        return self._request("GET", "/api/intentions", params=params)

    def dismiss_intention(self, intention_id: str) -> dict:
        return self._request("POST", f"/api/intentions/{intention_id}/dismiss")

    def layer_inventory(self) -> dict:
        return self._request("GET", "/api/layers")

    def categorize_experience(self, exp_id: str, category: str,
                              trunk: str | None = None) -> dict:
        payload = {"category": category}
        if trunk:
            payload["trunk"] = trunk
        return self._request("POST",
                             f"/api/experiences/{exp_id}/categorize",
                             json=payload)

    def dismiss_experience(self, exp_id: str) -> dict:
        return self._request("POST",
                             f"/api/experiences/{exp_id}/dismiss")

    def restore_experience(self, exp_id: str) -> dict:
        return self._request("POST",
                             f"/api/experiences/{exp_id}/restore")

    def experience_categories(self) -> dict:
        return self._request("GET", "/api/experience-categories")

    # ---------- 方法 ----------

    def skills(self) -> dict:
        return self._request("GET", "/api/skills")

    def read_skill(self, trunk: str, category: str) -> dict:
        return self._request("GET", f"/api/skills/{trunk}/{category}")

    def skill_sources(self, trunk: str, category: str) -> dict:
        return self._request("GET", f"/api/skills/{trunk}/{category}/sources")

    def skill_agents(self, trunk: str, category: str) -> dict:
        """R3：这个方法从哪些 agent 跑出来的（agent 分布 + 最近一次）。"""
        return self._request("GET", f"/api/skills/{trunk}/{category}/agents")

    def skill_rename(self, trunk: str, category: str,
                     name: str | None, new_category: str | None) -> dict:
        """R2：改显示名和/或迁移分类（两者至少一个）。"""
        return self._request("PUT", f"/api/skills/{trunk}/{category}/rename",
                             json={"name": name, "category": new_category})

    def insights(self) -> dict:
        return self._request("GET", "/api/insights")

    def insight_act(self, insight_id: str, action: str) -> dict:
        return self._request("POST", f"/api/insights/{insight_id}/{action}")

    def distill(self, trunk: str, category: str,
                force: bool = False) -> dict:
        """总结成方法；force=用全部经验重蒸馏（修被写坏的空卡）。

        蒸馏要调模型：本地长超时（对齐 llm.py 的 1800s 口径）。"""
        return self._request("POST", "/api/skills/distill",
                             json={"trunk": trunk, "category": category,
                                   "force": force},
                             timeout=1830.0)

    # ---------- AI 重写（第二项蒸馏：预览→采纳两段式） ----------

    def ai_polish_experiences(self, ids: list[str]) -> dict:
        # 提案要调模型：与 distill 同口径长超时
        return self._request("POST", "/api/experiences/ai-polish",
                             json={"ids": ids}, timeout=1830.0)

    def ai_apply_experience(self, exp_id: str, fields: dict) -> dict:
        return self._request("POST", f"/api/experiences/{exp_id}/ai-apply",
                             json=fields)

    def experience_explain(self, exp_id: str, lang: str = "zh") -> dict:
        # 讲人话要调模型：与重写同口径长超时
        return self._request("POST", f"/api/experiences/{exp_id}/explain",
                             params={"lang": lang}, timeout=1830.0)

    def ai_polish_failure(self, trunk: str, category: str, text: str) -> dict:
        return self._request("POST",
                             f"/api/failure-modes/{trunk}/{category}/ai-polish",
                             json={"text": text}, timeout=1830.0)

    def ai_apply_failure(self, trunk: str, category: str,
                         old_text: str, new_text: str) -> dict:
        return self._request("POST",
                             f"/api/failure-modes/{trunk}/{category}/ai-apply",
                             json={"old_text": old_text, "new_text": new_text})

    def skill_rewrite_preview(self, trunk: str, category: str) -> dict:
        return self._request("POST", "/api/skills/rewrite-preview",
                             json={"trunk": trunk, "category": category},
                             timeout=1830.0)

    def skill_rewrite_apply(self, trunk: str, category: str, md: str) -> dict:
        return self._request("POST", "/api/skills/rewrite-apply",
                             json={"trunk": trunk, "category": category,
                                   "md": md})

    # ---------- 配置 ----------

    def config(self) -> dict:
        return self._request("GET", "/api/config")

    def update_config(self, patch: dict) -> dict:
        return self._request("PUT", "/api/config", json=patch)

    def wipe(self, confirm: str) -> dict:
        """一键彻底删除：confirm 为用户手动输入的确认口令。"""
        return self._request("POST", "/api/wipe", json={"confirm": confirm})

    def data_dir_migrate(self, target: str,
                         confirm_outside_home: bool = False) -> dict:
        """更换数据目录：整体搬迁现有数据到 target，重启后生效。

        目标在用户主目录之外时传 True 才会真正迁
        （后端强制；GUI 已本地镜像判据拼过提示文案）。"""
        return self._request("POST", "/api/data-dir/migrate",
                             json={"target": target,
                                   "confirm_outside_home": confirm_outside_home},
                             timeout=600.0)

    def app_relaunch(self) -> dict:
        """重启应用（更换数据目录后生效）：引擎侧拉起分离 helper。"""
        return self._request("POST", "/api/app/relaunch", timeout=30.0)

    # ---------- 失败模式 ----------

    def failure_modes(self) -> dict:
        return self._request("GET", "/api/failure-modes")

    def failure_mode_trajectory(self, trunk: str, category: str) -> dict:
        return self._request(
            "GET", f"/api/failure-modes/{trunk}/{category}/trajectory")

    def reject_failure_mode(self, trunk: str, category: str, text: str) -> dict:
        return self._request(
            "POST", f"/api/failure-modes/{trunk}/{category}/reject",
            json={"text": text})

    # ---------- 我的偏好 ----------

    def preferences(self) -> dict:
        return self._request("GET", "/api/preferences")

    def save_preferences(self, trunk: str, md: str) -> dict:
        return self._request("POST", f"/api/preferences/{trunk}", json={"md": md})

    def reinduct_preferences(self, trunk: str) -> dict:
        return self._request("POST", f"/api/preferences/{trunk}/reinduct",
                             timeout=1830.0)

    # ---------- 成长 ----------

    def growth(self, days: int = 30) -> dict:
        return self._request("GET", "/api/growth", params={"days": days})

    def changelog_edit(self, idx: int, text: str) -> dict:
        return self._request("POST", f"/api/changelog/{idx}", json={"text": text})

    def changelog_delete(self, idx: int) -> dict:
        return self._request("DELETE", f"/api/changelog/{idx}")

    # ---------- Hooks ----------

    def rules(self) -> dict:
        return self._request("GET", "/api/rules")

    def add_rule(self, rule: dict) -> dict:
        return self._request("POST", "/api/rules", json=rule)

    def update_rule(self, rule_id: str, rule: dict) -> dict:
        return self._request("PUT", f"/api/rules/{rule_id}", json=rule)

    def remove_rule(self, rule_id: str) -> dict:
        return self._request("DELETE", f"/api/rules/{rule_id}")

    def rule_agents(self) -> dict:
        """H-A0 按工具视图的工具清单（detect 模式 ∪ 实际接入过的 agent）。"""
        return self._request("GET", "/api/rules/agents")

    def templates(self, lang: str) -> dict:
        return self._request("GET", "/api/rules/templates", params={"lang": lang})

    def import_template(self, template_id: str, trigger: str | None,
                        lang: str, keyword: str | None = None) -> dict:
        return self._request("POST", "/api/rules/templates/import",
                             json={"template_id": template_id, "trigger": trigger,
                                   "lang": lang, "keyword": keyword})

    def restore_template(self, template_id: str, lang: str) -> dict:
        return self._request("POST", f"/api/rules/templates/{template_id}/restore-default",
                             params={"lang": lang})

    # ---------- 模型会看到什么 ----------

    def injection_preview(self, trunk: str, category: str) -> dict:
        return self._request("GET", "/api/injection-preview",
                             params={"trunk": trunk, "category": category})

    def set_override(self, entry_id: str, enabled: bool | None = None,
                     text: str | None = None) -> dict:
        return self._request("PUT", "/api/injection-preview/override",
                             json={"id": entry_id, "enabled": enabled, "text": text})

    def clear_override(self, entry_id: str) -> dict:
        return self._request("DELETE", f"/api/injection-preview/override/{entry_id}")

    def optimize_override(self, text: str) -> dict:
        return self._request("POST", "/api/injection-preview/optimize",
                             json={"text": text}, timeout=1830.0)

    def clear_stale_overrides(self) -> dict:
        return self._request("POST", "/api/injection-preview/clear-stale")

    # ---------- 回炉治理（第⑤环） ----------

    def refutation(self) -> dict:
        return self._request("GET", "/api/refutation")

    def refutation_restore(self, trunk: str, category: str,
                           item_id: str) -> dict:
        return self._request("POST", "/api/refutation/restore",
                             json={"trunk": trunk, "category": category,
                                   "item_id": item_id})

    # ---------- 整理 Skill ----------

    def skill_generate(self, trunk: str | None = None, category: str | None = None,
                       selected: list[dict] | None = None, name: str | None = None,
                       description: str | None = None,
                       version: str | None = None) -> dict:
        return self._request("POST", "/api/skills/generate", json={
            "trunk": trunk, "category": category, "selected": selected,
            "name": name, "description": description, "version": version,
        }, timeout=1830.0)

    def skill_versions(self, name: str) -> dict:
        return self._request("GET", f"/api/skills/versions/{name}")

    def skill_version(self, name: str, n: int) -> dict:
        return self._request("GET", f"/api/skills/versions/{name}/{n}")

    def skill_version_diff(self, name: str, old: int, new: int) -> dict:
        return self._request("GET", f"/api/skills/versions/{name}/diff/{old}/{new}")

    def skill_save(self, name: str, md: str, description: str | None = None,
                   source_count: int | None = None) -> dict:
        return self._request("POST", "/api/skills/save", json={
            "name": name, "md": md, "description": description,
            "source_count": source_count})

    # ---------- 导出 ----------

    def export(self, granularity: str, trunk: str | None = None,
               category: str | None = None, since: str | None = None,
               until: str | None = None, days: int | None = None,
               ids: list[str] | None = None,
               playbooks: list[dict] | None = None) -> dict:
        return self._request("POST", "/api/export", json={
            "granularity": granularity, "trunk": trunk, "category": category,
            "since": since, "until": until, "days": days,
            "ids": ids, "playbooks": playbooks})

    def export_all(self) -> dict:
        return self._request("POST", "/api/export/all")

    def open_export(self, path: str) -> dict:
        return self._request("POST", "/api/exports/open", json={"path": path})

    # ---------- 开机自启 ----------

    def autostart(self, enabled: bool) -> dict:
        return self._request("POST", "/api/autostart",
                             json={"enabled": enabled}, timeout=60.0)

    # ---------- Hook 通道（通道 3，Claude Code） ----------

    def hooks_config(self) -> dict:
        return self._request("GET", "/api/hooks/config")

    def hooks_apply(self) -> dict:
        return self._request("POST", "/api/hooks/apply", timeout=60.0)

    def hooks_remove(self) -> dict:
        return self._request("POST", "/api/hooks/remove", timeout=60.0)

    # ---------- Agent hook 统一管理（总方案 ，hooks 栏） ----------

    def hooks_admin(self, agent: str) -> dict:
        return self._request("GET", f"/api/hooks/admin/{agent}")

    def hooks_admin_overview(self) -> dict:
        return self._request("GET", "/api/hooks/admin/overview")

    def hooks_admin_install(self, agent: str) -> dict:
        return self._request("POST", "/api/hooks/admin/install",
                             json={"agent": agent}, timeout=60.0)

    def hooks_admin_remove(self, agent: str) -> dict:
        return self._request("POST", "/api/hooks/admin/remove",
                             json={"agent": agent}, timeout=60.0)

    def hooks_admin_install_all(self) -> dict:
        return self._request("POST", "/api/hooks/admin/install-all", timeout=60.0)

    def hooks_admin_remove_all(self) -> dict:
        return self._request("POST", "/api/hooks/admin/remove-all", timeout=60.0)

    def hooks_admin_delete(self, agent: str, entry_id: str) -> dict:
        return self._request("POST", "/api/hooks/admin/delete",
                             json={"agent": agent, "entry_id": entry_id},
                             timeout=60.0)

    def hooks_admin_toggle(self, agent: str, entry_id: str, enabled: bool) -> dict:
        return self._request("POST", "/api/hooks/admin/toggle",
                             json={"agent": agent, "entry_id": entry_id,
                                   "enabled": enabled}, timeout=60.0)

    def hooks_admin_explain(self, agent: str, entry_id: str) -> dict:
        """LLM 辅助解释某条规则（可选项，用户主动触发）：本地模型慢，长超时。"""
        return self._request("POST", "/api/hooks/admin/explain",
                             json={"agent": agent, "entry_id": entry_id},
                             timeout=1830.0)

    def hooks_admin_edit(self, agent: str, entry_id: str, updates: dict) -> dict:
        return self._request("POST", "/api/hooks/admin/edit",
                             json={"agent": agent, "entry_id": entry_id,
                                   "updates": updates}, timeout=60.0)

    def hooks_admin_add(self, agent: str, event: str, command: str) -> dict:
        return self._request("POST", "/api/hooks/admin/add",
                             json={"agent": agent, "event": event,
                                   "command": command}, timeout=60.0)

    # ---------- Skill 自报 + hook 注入（总方案 S2/S3） ----------

    def probe_status(self) -> dict:
        return self._request("GET", "/api/probe/status")

    def probe_keys(self) -> dict:
        """已吸收钥匙列表（Keys：连接页「收到的钥匙」）。"""
        return self._request("GET", "/api/probe/keys")

    def probe_key_delete(self, code: str) -> dict:
        """删除一把钥匙的历史明细（不影响已激活通道）。"""
        return self._request("DELETE", f"/api/probe/keys/{code}")

    def probe_apply(self, code: str) -> dict:
        return self._request("POST", "/api/probe/apply", json={"code": code})

    def probe_ide_apply(self, agent: str) -> dict:
        return self._request("POST", "/api/probe/ide/apply",
                             json={"agent": agent}, timeout=60.0)

    def probe_ide_remove(self, agent: str) -> dict:
        return self._request("POST", "/api/probe/ide/remove",
                             json={"agent": agent}, timeout=60.0)

    def probe_hermes_apply(self) -> dict:
        return self._request("POST", "/api/probe/hermes/apply", timeout=60.0)

    def probe_hermes_remove(self) -> dict:
        return self._request("POST", "/api/probe/hermes/remove", timeout=60.0)

    # ---------- S5 经验上报草稿（三入口提示的数据源） ----------

    def experience_drafts(self, status: str = "pending") -> dict:
        return self._request("GET", "/api/experience-drafts",
                             params={"status": status})

    def experience_draft_adopt(self, draft_id: str) -> dict:
        return self._request("POST", f"/api/experience-drafts/{draft_id}/adopt",
                             timeout=60.0)

    def experience_draft_ignore(self, draft_id: str) -> dict:
        return self._request("POST", f"/api/experience-drafts/{draft_id}/ignore",
                             timeout=60.0)

    # ---------- 通知中心 ----------

    def weekly_report(self) -> dict:
        """本周结算叙事（App 内结算卡；服务端只读，不触发成就判定）。"""
        return self._request("GET", "/api/weekly-report")

    def notifications(self, unread: bool = False, limit: int = 50) -> dict:
        return self._request("GET", "/api/notifications",
                             params={"unread": unread, "limit": limit})

    def notifications_read(self, ids: list[str] | None = None) -> dict:
        return self._request("POST", "/api/notifications/read", json={"ids": ids})


# ---------------------------------------------------------------------------
# 进程内内存缓存（只读优化，不落盘）。
# 设计口径：GUI 与引擎同机走 127.0.0.1，"离线降级/磁盘缓存"是过度设计；
# 这里只把"每次切页/轮询都要重复拉的只读口径"在进程内按 TTL 缓存，写操作按
# 资源根失效，避免用户刚改完就看到旧数据。活数据页轮询 30s > TTL，天然保持新鲜。
# ---------------------------------------------------------------------------

# GET 缓存 TTL（秒）。活数据端点 TTL < 轮询间隔 30s → 每轮仍能拿到新数据，
# 但同一轮内导航+轮询的重叠请求可合并，冷缓存窗口（探测 1.7-2.4s）不再重复触发。
_GET_TTL: dict[str, float] = {
    "/api/status": 20.0,
    "/api/capture/status": 20.0,
    "/api/capture": 20.0,
    "/api/growth": 20.0,
    "/api/insights": 20.0,
    "/api/experiences": 20.0,
    "/api/skills": 30.0,
    "/api/rules": 60.0,
    "/api/rules/agents": 120.0,
    "/api/rules/templates": 60.0,
    "/api/config": 60.0,
    "/api/models": 60.0,
    "/api/preferences": 60.0,
    "/api/failure-modes": 60.0,
    "/api/notifications": 45.0,   # 轮询周期 60s——TTL 必须 ≥ 周期否则每次轮询都是真 HTTP
    "/api/hooks/config": 60.0,
    "/api/hooks/admin/overview": 20.0,   # 此前不在白名单，30s 轮询全量重拉
    "/api/probe/status": 20.0,
    "/api/injection-preview": 30.0,
    "/api/refutation": 30.0,
    "/api/ledger": 20.0,          # 首页轮询端点
    "/api/workspaces": 20.0,      # 工作区索引（只读口径）
}

# 写操作 → 需一并失效的缓存资源根（近似：同资源族 + 依赖它的聚合口径）。
_COUPLED: dict[str, tuple[str, ...]] = {
    "/api/wipe": (),                      # 清全库
    "/api/config": ("/api/config", "/api/status"),
    "/api/capture": ("/api/capture", "/api/capture/status", "/api/status"),
    "/api/models": ("/api/models", "/api/status"),
    "/api/hooks": ("/api/hooks", "/api/rules", "/api/status",
                   "/api/hooks/admin/overview"),
    "/api/hooks/admin": ("/api/hooks", "/api/rules", "/api/status",
                         "/api/hooks/admin/overview"),
    "/api/probe": ("/api/probe/status",),
    "/api/autostart": ("/api/config", "/api/status"),
    "/api/data-dir": ("/api/status", "/api/config"),
    "/api/experience-drafts": ("/api/experience-drafts", "/api/experiences",
                               "/api/status"),
    "/api/rules": ("/api/rules", "/api/rules/agents"),
    "/api/skills": ("/api/skills", "/api/experiences", "/api/growth",
                    "/api/insights", "/api/failure-modes", "/api/preferences"),
    "/api/experiences": ("/api/experiences", "/api/skills"),
    "/api/insights": ("/api/insights", "/api/skills", "/api/status"),
    "/api/injection-preview": ("/api/injection-preview", "/api/skills"),
    "/api/refutation": ("/api/refutation",),
    "/api/failure-modes": ("/api/failure-modes", "/api/experiences"),
    "/api/preferences": ("/api/preferences", "/api/skills"),
    "/api/changelog": ("/api/growth",),
    "/api/notifications": ("/api/notifications",),
}

# 写资源根：写失效按 _COUPLED 键做最长前缀命中，
# 不再从 _GET_TTL 键反推——/api/probe 这类写路径没有同名 GET 资源根
# （TTL 表只有 /api/probe/status），旧实现查根返回 None → 写后缓存不失效，
# 用户改完看到旧数据。
_WRITE_ROOTS = tuple(
    sorted(_COUPLED.keys(),
           key=lambda p: (-len(p), p)))

# 只读资源根（GET 键）：写路径查不到写根时的兜底归属
_CACHE_ROOTS = tuple(
    sorted(_GET_TTL.keys(),
           key=lambda p: (-len(p), p)))


def _match_root(path: str, roots: tuple[str, ...]) -> str | None:
    for root in roots:
        if path == root or path.startswith(root + "/"):
            return root
    return None


def _resource_root(path: str) -> str | None:
    """返回写 path 归属的资源根（用于写失效）：_COUPLED 写根最长前缀命中，
    未命中再按 GET 资源根兜底（如未登记的新写路径落在已缓存资源族下）。"""
    return _match_root(path, _WRITE_ROOTS) or _match_root(path, _CACHE_ROOTS)


def _wipe_path(path: str) -> bool:
    return path == "/api/wipe" or path.startswith("/api/wipe/")


class CachedApi(LocalApi):
    """LocalApi 的内存缓存子类：GET 白名单端点按 TTL 缓存，写操作按资源族失效。

    线程安全：缓存 dict 用锁保护；httpx.Client 支持多线程并发，页面并行
    fetch（page_base.parallel_fetch）可安全共用同一实例。
    """

    def __init__(self, base_url: str = DEFAULT_BASE):
        super().__init__(base_url)
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _cache_key(path: str, params: dict | None) -> str:
        if params:
            q = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            return f"{path}?{q}"
        return path

    def _request(self, method: str, path: str, json: dict | None = None,
                 params: dict | None = None, timeout: float | None = None) -> dict:
        if method == "GET":
            key = self._cache_key(path, params)
            ttl = _GET_TTL.get(path)
            if ttl:
                with self._lock:
                    hit = self._cache.get(key)
                if hit is not None and time.monotonic() - hit[0] < ttl:
                    return hit[1]
        result = super()._request(method, path, json=json,
                                  params=params, timeout=timeout)
        if method == "GET":
            ttl = _GET_TTL.get(path)
            if ttl:
                key = self._cache_key(path, params)
                with self._lock:
                    self._cache[key] = (time.monotonic(), result)
        else:
            self._invalidate(path)
        return result

    def _invalidate(self, path: str) -> None:
        """写操作后按资源族失效缓存；/api/wipe 清空全部。"""
        if _wipe_path(path):
            with self._lock:
                self._cache.clear()
            return
        root = _resource_root(path)
        if root is None:
            return
        targets = _COUPLED.get(root) or (root,)
        with self._lock:
            for key in list(self._cache):
                if any(key == t or key.startswith(t + "/") or key.startswith(t + "?")
                       for t in targets):
                    del self._cache[key]

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
