"""本地 API 的「采集状态与管理」资源域：`/api/capture/status`、`/api/capture`。

从 `create_local_app()` 拆出的第十五个资源域，范式同 models.py
（只依赖 store 与产品层、暴露 `build_xxx_router(store)` 工厂、不反向 import
`app.local_api`）。本域私有的 `_aggregate_capture_hits` 随域搬走。

`YELLOW_FLAG_THRESHOLD`（连续失败几轮亮黄标）是本域常量，从原文件搬来。
"""

from __future__ import annotations

import datetime as _dt

from ..time_util import parse_ts

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..capture import registry
from ..capture.scan import YELLOW_FLAG_THRESHOLD
from ..store.store import Store


class CaptureIn(BaseModel):
    name: str
    enabled: bool


def _aggregate_capture_hits(hits: list[dict]) -> dict[str, dict]:
    """per-agent 命中统计（api/capture/status 与 /api/capture 共用）：
    hits_24h（近 24h 窗口计数）+ last_hit（最大 ts；ISO 串比较与文件内格式一致）。"""
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=24)
    per: dict[str, dict] = {}
    for h in hits:
        name = str(h.get("agent"))
        a = per.setdefault(name, {"hits_24h": 0, "last_hit": None})
        # 去重 R1：原写法遇上不带尾 Z 的时间戳会得到 naive datetime，与 aware 的
        # cutoff 相减直接 TypeError；统一走 time_util，返回值必为 aware UTC。
        ts = parse_ts(h.get("ts"))
        if ts is not None and ts >= cutoff:
            a["hits_24h"] += 1
        if a["last_hit"] is None or str(h.get("ts", "")) > str(a["last_hit"]):
            a["last_hit"] = h.get("ts")
    return per


def _encrypted_map_guard():
    """探测各 agent 是否存在加密库（探测失败返回空 dict，不拖垮端点）。"""
    try:
        from ..capture.registry import detect as _detect_reg
        detected = _detect_reg()
        return {agent: any(r.encrypted for r in refs)
                for agent, refs in detected.items()}
    except Exception:
        return {}


def build_capture_router(store: Store) -> APIRouter:
    """挂载采集状态 + 采集管理，共 3 个端点。"""
    router = APIRouter()

    # ---------- 采集状态（W1-06：命中流水 + 24h 计数 + 黄标） ----------

    @router.get("/api/capture/status")
    def capture_status():
        hits = store.load_capture_hits(limit=store.CAPTURE_HITS_MAX_LINES)
        agents = _aggregate_capture_hits(hits)
        failures = store.load_capture_failures()
        # 加密状态：从 detect() 获取 SessionRef 的 encrypted 标记
        encrypted_map = _encrypted_map_guard()
        for name, a in agents.items():
            a["yellow_flag"] = int(failures.get(name) or 0) >= YELLOW_FLAG_THRESHOLD
            a["encrypted"] = encrypted_map.get(name, False)
        for name, n in failures.items():  # 从未命中但带黄标的也要露出
            if n and name not in agents:
                agents[name] = {"hits_24h": 0, "last_hit": None,
                                "yellow_flag": n >= YELLOW_FLAG_THRESHOLD,
                                "encrypted": encrypted_map.get(name, False)}
        # 按时间排序取最近 10 条（文件追加序 ≠ 时间序：旧记录可能后补写）
        hits_sorted = sorted(hits, key=lambda h: str(h.get("ts", "")))
        return {"agents": agents, "recent_hits": list(reversed(hits_sorted[-10:]))}

    # ---------- 采集管理（W2：REGISTRY 全量清单 + 启用开关，config 持久化） ----------

    @router.get("/api/capture")
    def capture_list():
        enabled_map = (store.load_config().get("capture") or {}).get("enabled") or {}
        hits = store.load_capture_hits(limit=store.CAPTURE_HITS_MAX_LINES)
        per = _aggregate_capture_hits(hits)
        failures = store.load_capture_failures()
        encrypted_map = _encrypted_map_guard()
        # 第 6 轮：只列"实际在跑"的 agent——最近一轮扫描探测到真实会话文件的
        # （scan 循环每 60s 落盘 detected_agents.json）+ 近 24h 有命中的
        # （hook 通道/文件刚清但仍在活动）。全 REGISTRY 清单 = 一堆用户没在
        # 跑的名字，纯噪音（用户反馈）。API 不自己探测：不碰盘、测试确定性。
        real_names = store.load_detected_agents()
        real_names.update(n for n, a in per.items() if a["hits_24h"] > 0)
        items = []
        for name in registry.REGISTRY:
            if name not in real_names:
                continue
            a = per.get(name, {"hits_24h": 0, "last_hit": None})
            items.append({
                "name": name,
                "enabled": enabled_map.get(name, True) is not False,
                "hits_24h": a["hits_24h"],
                "last_hit": a["last_hit"],
                "yellow_flag": int(failures.get(name) or 0) >= YELLOW_FLAG_THRESHOLD,
                "encrypted": encrypted_map.get(name, False),
            })
        return {"items": items,
                "enabled_count": sum(1 for i in items if i["enabled"]),
                "total": len(items)}

    @router.post("/api/capture")
    def capture_set(body: CaptureIn):
        if body.name not in registry.REGISTRY:
            raise HTTPException(status_code=404, detail=f"未知适配器：{body.name}")
        # 读-改-写走 mutate_config（持写锁，防并发丢字段）
        def _apply(config: dict) -> dict:
            enabled = config.setdefault("capture", {}).setdefault("enabled", {})
            enabled[body.name] = bool(body.enabled)
            return config

        store.mutate_config(_apply)
        return {"message": "ok"}

    return router
