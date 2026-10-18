"""本地 API 的「probe 自报」域（总方案 S2：扫不到的 agent 兜底入口）。

 L4 续：从 ingest.py 拆出的第二组。外部 agent 的 probe.py
直推报告（首选、用户无感），或 connect 页粘贴上报码后本地吸收（人工介质
兜底）；keys / ide / hermes 是围绕上报码与本地 hook 配置的管理端点。

⚠️ 本域需要外部注入 **`hook_event_token`**（ide / hermes 的 hook 配置写入
要用它作为 key）——由 `build_ingest_router` 透传，不去 `local_api` 里取。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ..store.store import Store

logger = logging.getLogger("experientia.local_api.ingest")


def build_probe_router(store: Store, hook_event_token: str) -> APIRouter:
    """probe 自报与上报码管理，9 个端点。"""
    router = APIRouter()
    # ---------- Skill 自报（总方案 S2：扫不到的 agent 兜底入口） ----------
    # POST /api/probe        外部 agent 的 probe.py 直推报告（首选，用户无感）
    # POST /api/probe/apply  connect 页粘贴上报码后本地吸收（人工介质兜底）

    @router.post("/api/probe")
    def probe_report(payload: dict = None):
        from ..capture import probe as probe_ch
        try:
            raw = payload or {}
            report = probe_ch.validate_report(raw)
            agent = str(raw.get("agent") or "")
            is_note = isinstance(raw.get("experience"), dict) and not raw.get("data_sources")
            if report is None and not (is_note and agent):
                return {"ok": False, "error": "报告校验不通过（路径/格式可疑）"}
            kind = "N" if is_note else probe_ch._classify_report(report)
            code = probe_ch.make_code(agent or (report or {}).get("agent") or "", kind=kind)
            store.save_incoming_report(code, raw)
            return {"ok": True, "code": code}
        except Exception:
            logger.exception("probe 落盘失败")
            return {"ok": False, "error": "服务端处理失败"}

    @router.post("/api/probe/apply")
    def probe_apply(payload: dict = None):
        from ..capture import probe as probe_ch
        try:
            return probe_ch.apply_code(store, str((payload or {}).get("code") or ""))
        except Exception:
            logger.exception("probe apply 失败")
            return {"ok": False, "error": "服务端处理失败"}

    @router.get("/api/probe/status")
    def probe_status():
        """自报吸收状态 + 各家 hook 注入状态（connect 页展示用）。"""
        from ..capture import hermes_hook as hermes_ch
        from ..capture import ide_hooks as ide_ch

        def _ide(agent):
            try:
                return ide_ch.config_status(agent, store=store)
            except Exception as exc:
                # 探测异常此前静默降级成"未安装"，与真·未安装无从
                # 区分且不留痕——补留痕（返回值口径不变：单家异常不得让端点整体 500）。
                logger.warning("probe status：%s hook 配置探测异常（降级为未安装）: %s",
                               agent, exc)
                return {"agent": agent, "installed": False, "observed": {}}

        def _hermes():
            try:
                return hermes_ch.hook_status()
            except Exception as exc:
                logger.warning("probe status：hermes hook 状态探测异常（降级为未安装）: %s",
                               exc)
                return {"installed": False}

        try:
            sr = store.load_self_reported()
        except Exception as exc:
            logger.warning("probe status：自报状态读取异常（降级为空）: %s", exc)
            sr = {}
        try:
            pending_n = store.draft_count("pending")
        except Exception as exc:
            logger.warning("probe status：草稿待处理计数异常（降级为 0）: %s", exc)
            pending_n = 0
        return {
            "self_reported": sr,
            "ide_hooks": {"cursor": _ide("cursor"), "windsurf": _ide("windsurf")},
            "hermes_hook": _hermes(),
            "draft_pending": pending_n,
        }

    @router.get("/api/probe/keys")
    def probe_keys():
        """已吸收钥匙列表（Keys：明细留在 keys/<码>.json，这里只回可展示的头部）。

        附 hook 注入面摘要（M2 元数据 → 查重/一键接入判定）：supported 是否探测到
        注入点、writable 是否可写、already_injected 是否已含 Experientia、
        installer_supported 本端是否有该 agent 的官方安装器。
        """
        try:
            keys = []
            for code in store.list_key_codes():
                m = store.load_key_manifest(code)
                if not isinstance(m, dict):
                    continue
                item = {
                    "code": code,
                    "agent": m.get("agent"),
                    "at": m.get("at"),
                    "mode": m.get("mode"),
                    "agent_version": m.get("agent_version"),
                }
                rep = m.get("report")
                hs = (rep or {}).get("hook_surface") if isinstance(rep, dict) else None
                if isinstance(hs, dict):
                    cfg = [p for p in (hs.get("config_paths") or []) if p]
                    wp = [p for p in (hs.get("writable_paths") or []) if p]
                    agent = str(item.get("agent") or "")
                    item["hook"] = {
                        "supported": bool(hs.get("supported")) and bool(cfg),
                        "writable": len(wp),
                        "already_injected": bool(hs.get("already_injected")),
                        "installer_supported": agent in ("hermes", "cursor", "windsurf"),
                    }
                keys.append(item)
            return {"keys": keys}  # list_key_codes 已按码倒序（最新在前）
        except Exception:
            logger.exception("probe keys 读取失败")
            return {"keys": []}

    @router.delete("/api/probe/keys/{code}")
    def probe_key_delete(code: str):
        """删除一把钥匙的历史明细（不触碰已激活的捕获通道/接入状态）。"""
        try:
            store.delete_key_manifest(code)
            return {"ok": True}
        except Exception:
            logger.exception("probe key 删除失败")
            return {"ok": False, "error": "删除失败"}

    @router.post("/api/probe/ide/apply")
    def probe_ide_apply(payload: dict = None):
        from ..capture import ide_hooks as ide_ch
        agent = str((payload or {}).get("agent") or "")
        if agent not in ("cursor", "windsurf"):
            return {"ok": False, "error": "agent 无效"}
        try:
            return ide_ch.apply_config(agent, key=hook_event_token)
        except Exception as exc:
            logger.exception("ide hook 注入失败")
            return {"ok": False, "error": f"写入失败：{exc}"}

    @router.post("/api/probe/ide/remove")
    def probe_ide_remove(payload: dict = None):
        from ..capture import ide_hooks as ide_ch
        agent = str((payload or {}).get("agent") or "")
        if agent not in ("cursor", "windsurf"):
            return {"ok": False, "error": "agent 无效"}
        try:
            return ide_ch.remove_config(agent)
        except Exception as exc:
            logger.exception("ide hook 移除失败")
            return {"ok": False, "error": f"移除失败：{exc}"}

    @router.post("/api/probe/hermes/apply")
    def probe_hermes_apply():
        from ..capture import hermes_hook as hermes_ch
        try:
            hermes_ch.write_hook(key=hook_event_token)
            return {"ok": True, "note": "已写入，重启 Hermes gateway 后生效"}
        except Exception as exc:
            logger.exception("hermes hook 写入失败")
            return {"ok": False, "error": f"写入失败：{exc}"}

    @router.post("/api/probe/hermes/remove")
    def probe_hermes_remove():
        from ..capture import hermes_hook as hermes_ch
        try:
            removed = hermes_ch.remove_hook()
            return {"ok": True, "removed": removed}
        except Exception as exc:
            logger.exception("hermes hook 移除失败")
            return {"ok": False, "error": f"移除失败：{exc}"}

    # ---------- 经验上报草稿（S5 ：无 LLM 时的手动放行去向） ----------

    return router
