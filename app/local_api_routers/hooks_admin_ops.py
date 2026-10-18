"""本地 API 的「hooks 管理·操作」域：安装 / 移除 / 启停 / 增删。

 L4 续：从 hooks_admin.py 拆出的第二组。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ..capture import hook as hook_channel
from ..store.store import Store

logger = logging.getLogger("experientia.local_api.hooks")


def build_hooks_admin_ops_router(store: Store, hook_event_token: str) -> APIRouter:
    """hooks 管理操作，8 个端点。"""
    router = APIRouter()
    @router.post("/api/hooks/admin/install")
    def hooks_admin_install(payload: dict = None):
        """一键接入官方 Hook（含钥匙兜底查重）。

        Keys 兜底：若最新钥匙已确认该 agent 注入面含 Experientia → 幂等跳过，不再
        重复写（即使前端 gate 被绕过也安全）。写成功后再把状态回写钥匙明细，
        下一次 probe 前 UI 即显示「已接入」。
        """
        from ..capture import hook_admin as ha
        from ..capture import probe as probe_ch

        agent = str((payload or {}).get("agent") or "")
        st = probe_ch.key_hook_state(store, agent)
        if st and st.get("already_injected"):
            return {"ok": True, "already": True,
                    "note": "已接入（钥匙元数据查重）"}
        result = ha.install_ours(agent, key=hook_event_token)
        try:
            if isinstance(result, dict) and result.get("ok") is not False:
                probe_ch.mark_key_hook_injected(store, agent)
        except Exception:  # noqa: BLE001 状态回写失败不影响注入结果
            logger.warning("钥匙已注入状态回写失败: %s", agent)
        return result

    @router.post("/api/hooks/admin/remove")
    def hooks_admin_remove(payload: dict = None):
        from ..capture import hook_admin as ha
        return ha.remove_ours(str((payload or {}).get("agent") or ""))

    @router.post("/api/hooks/admin/install-all")
    def hooks_admin_install_all():
        from ..capture import hook_admin as ha
        return ha.install_all(key=hook_event_token)

    @router.post("/api/hooks/admin/remove-all")
    def hooks_admin_remove_all():
        from ..capture import hook_admin as ha
        return ha.remove_all()

    @router.post("/api/hooks/admin/delete")
    def hooks_admin_delete(payload: dict = None):
        from ..capture import hook_admin as ha
        p = payload or {}
        return ha.delete_entry(str(p.get("agent") or ""),
                               str(p.get("entry_id") or ""), store=store)

    @router.post("/api/hooks/admin/toggle")
    def hooks_admin_toggle(payload: dict = None):
        from ..capture import hook_admin as ha
        p = payload or {}
        return ha.toggle_entry(str(p.get("agent") or ""),
                               str(p.get("entry_id") or ""),
                               bool(p.get("enabled")), store=store)

    @router.post("/api/hooks/admin/edit")
    def hooks_admin_edit(payload: dict = None):
        from ..capture import hook_admin as ha
        p = payload or {}
        return ha.edit_entry(str(p.get("agent") or ""),
                             str(p.get("entry_id") or ""),
                             p.get("updates") or {}, store=store)

    @router.post("/api/hooks/admin/add")
    def hooks_admin_add(payload: dict = None):
        """手动新增一条 hook 条目（仅 JSON 系；TOML/unknown → 400 只读门控）。"""
        from ..capture import hook_admin as ha
        p = payload or {}
        return ha.add_entry(str(p.get("agent") or ""),
                            str(p.get("event") or ""),
                            str(p.get("command") or ""), store=store)

    # ---------- 本机 hook 配置（Claude Code settings.json） ----------

    return router
