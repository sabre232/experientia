"""skill 自报吸收（捕获接入总方案 S2：扫不到的 agent 才走这条兜底）。

职责四块：
1. report 校验（不盲信：路径真实存在、明文库文件头对得上；防 prompt 注入乱报）；
2. 上报码编解码（短人工介质：{slug}-{report_id8}-{crc4}，只寻址，数据本体在 incoming）；
3. 吸收（consume）：校验 → 记录 self_reported → 选档提示（scan_covered / decrypt_ready /
   hook_ready / report_only），UI 只给一句人话；
4. run_incoming：scan_loop 每轮清扫 incoming 目录（8101 直传之外的落盘主路）。

skill 输出契约：对外只回一行码（或 "已上报 ✓"），探测细节永不出现在用户面前。
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import secrets
import zlib
from pathlib import Path

logger = logging.getLogger("experientia.capture.probe")

_STATUS_NOTE = {"auto": "已自动入库", "pending": "已存为草稿，可在经验页一键放行",
                "rejected": "未通过纪律检查，未入库"}

_SQLITE_HEADER = b"SQLite format 3\0"
_PLAINTEXT_FORMATS = ("plaintext_sqlite", "sqlite", "jsonl", "json", "plaintext")
_VALID_FORMATS = ("encrypted",) + _PLAINTEXT_FORMATS + ("unknown",)
# hook 配置的 schema 类型（skill 探测脚本现场识别，hook 管理按此门控写配方）
_VALID_HOOK_SCHEMAS = ("json_hooks", "toml_hooks", "hook_dir", "unknown")

# ---------- 上报码 ----------

_AGENT_SLUGS = {
    "claude-code": "CLD", "claude": "CLD", "codex": "CDX", "hermes": "HMS",
    "trae": "TRA", "cursor": "CRS", "windsurf": "WND", "openclaw": "OCL",
    "opencode": "OPC", "qclaw": "QCL", "codebuddy": "CBD", "gemini-cli": "GEM",
    "cline": "CLI", "roo-code": "ROO", "aider": "AID", "openhands": "OHD",
    "goose": "GSE", "kilocode": "KIL", "zed": "ZED", "dsh": "DSH",
    "copilot-cli": "CPL", "workbuddy": "WRK", "qoder": "QDR", "qwen-code": "QWC",
    "iflow": "IFL",
}
_REV_SLUGS = {v: k for k, v in _AGENT_SLUGS.items()}
# 形态位：码是"钥匙"，单靠码即可分派，不依赖 LLM/数据文件。
# P=明文可扫描 E=加密(类型按 agent 已知表) H=仅官方 hook 面 N=仅经验上报 U=未知
KIND_CLASS = {"P": "可扫描", "E": "已加密", "H": "可接实时 Hook", "N": "经验上报", "U": "未知"}
_CODE_RE = re.compile(
    r"^[A-Z0-9]{2,5}-[A-Z]-[0-9A-F]{8}-[0-9A-F]{4}$")
_CODE_RE_V1 = re.compile(r"^[A-Z0-9]{2,5}-[0-9A-F]{8}-[0-9A-F]{4}$")


def _slug_for(agent: str) -> str:
    if agent in _AGENT_SLUGS:
        return _AGENT_SLUGS[agent]
    slug = re.sub(r"[^A-Z0-9]", "", (agent or "agent").upper())[:4]
    return slug or "AGX"


def _crc(slug: str, report_id: str) -> str:
    return f"{zlib.crc32((slug + report_id).encode()) & 0xFFFF:04X}"


def _classify_report(report: dict) -> str:
    """按报告数据形态定形态位（N=经验上报优先，其次 H/P/E/U）。"""
    if isinstance(report.get("experience"), dict):
        return "N"
    hs = report.get("hook_surface")
    if hs and isinstance(hs, dict) and hs.get("supported"):
        return "H"
    fmts = {str(s.get("format")) for s in (report.get("data_sources") or [])}
    if fmts & {"plaintext_sqlite", "sqlite", "jsonl", "json", "plaintext"}:
        return "P"
    if "encrypted" in fmts:
        return "E"
    return "U"


def make_code(agent: str, report_id: str | None = None,
              kind: str | None = None) -> str:
    """生成自解释上报码：{slug}-{形态位}-{8hex}-{4hex}。

    kind ∈ P/E/H/N/U；旧版三段的码仍可解码（视为 U）。形态位即"钥匙说明"，
    程序不读数据文件也能据此路由（可扫/加密/接 hook/经验/未知）。
    """
    slug = _slug_for(agent)
    cls = kind if kind in KIND_CLASS else "U"
    rid = (report_id or secrets.token_hex(4)).upper()
    return f"{slug}-{cls}-{rid}-{_crc(slug, rid)}"


def decode_code(code: str) -> dict | None:
    """解码上报码 → {agent?, slug, report_id, kind, class}；格式错/校验失败 → None。

    兼容 v1（三段，无形态位）→ kind=U。仅靠码即可给出情况说明与建议动作。
    """
    code = (code or "").strip().upper()
    m = _CODE_RE.match(code)
    if m:
        slug, cls, rid, cs = code.split("-")
    else:
        m = _CODE_RE_V1.match(code)
        if not m:
            return None
        slug, rid, cs = code.split("-")
        cls = "U"
    if cs != _crc(slug, rid):
        return None
    return {"agent": _REV_SLUGS.get(slug, slug.lower()),
            "slug": slug, "report_id": rid, "kind": cls,
            "class": KIND_CLASS.get(cls, "未知")}


# 路径集合指纹只收 hex；环境键白名单 + 单字母盘符（防注入任意结构）
_FINDER_HASH_RE = re.compile(r"^[0-9A-F]{8,64}$")


def _clean_finder_hash(raw) -> str | None:
    if isinstance(raw, str):
        s = raw.strip().upper()
        if _FINDER_HASH_RE.match(s):
            return s
    return None


def _clean_env(raw) -> dict | None:
    """清洗 probe 现场环境：只收白名单键（字符串截断）与单字母盘符列表。"""
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    for key in ("os", "home", "localappdata", "appdata", "userprofile"):
        v = raw.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()[:500]
    drives = raw.get("drives")
    if isinstance(drives, list):
        d = sorted({str(x).strip().upper() for x in drives
                    if isinstance(x, str) and len(x.strip()) == 1
                    and x.strip().isalpha()})
        if d:
            out["drives"] = d
    return out or None


# ---------- report 校验（v1，不盲信） ----------

def validate_report(raw: dict | None) -> dict | None:
    """校验 + 清洗一份自报报告；不合格 → None。

    校验点：agent 非空；data_sources 非空且逐条做"路径真实存在 + 文件头对得上"；
    hook_surface.config_paths 只保留真实存在的注入点。任何可疑条目丢弃并记 warning，
    不因单条可疑就推翻整份报告，但全部可疑则整份拒绝。
    """
    if not isinstance(raw, dict):
        return None
    agent = str(raw.get("agent") or "").strip()
    if not agent:
        return None
    warnings: list[str] = []
    sources = raw.get("data_sources")
    if not isinstance(sources, list):
        return None
    kept: list[dict] = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        path = str(s.get("path") or "").strip()
        fmt = str(s.get("format") or "unknown").strip()
        p = Path(path)
        ok, why = _check_source(p, fmt, s)
        if not ok:
            warnings.append(f"{path}: {why}")
            continue
        item = {"kind": str(s.get("kind") or "unknown"), "path": path, "format": fmt}
        if s.get("note"):
            item["note"] = str(s["note"])[:200]
        if s.get("drive"):  # 来源实际所在盘（Windows 盘符，探测现场标记）
            drive = str(s["drive"]).strip().upper()[:4]
            if drive:
                item["drive"] = drive
        kept.append(item)
    if not kept:
        return None
    hook = raw.get("hook_surface")
    hook_surface = None
    if isinstance(hook, dict) and isinstance(hook.get("supported"), bool):
        existing = [str(c) for c in (hook.get("config_paths") or [])
                    if isinstance(c, str) and Path(c).exists()]
        writable = [str(c) for c in (hook.get("writable_paths") or [])
                    if isinstance(c, str) and Path(c).exists() and c in existing]
        # formats：路径+schema 列表（hook 管理按 schema 门控写配方的依据；
        # 只收已存在的 config_paths 与合法 schema 值，防注入任意结构）
        fmts: list[dict] = []
        for f in (hook.get("formats") or []):
            if not isinstance(f, dict):
                continue
            fp = str(f.get("path") or "")
            sch = str(f.get("schema") or "")
            if fp in existing and sch in _VALID_HOOK_SCHEMAS:
                fmts.append({"path": fp, "schema": sch})
        hook_surface = {
            "supported": bool(hook["supported"]) and bool(existing or hook.get("config_paths") is not None),
            "ecosystem": str(hook.get("ecosystem") or "unknown"),
            "config_paths": existing,
            # 注入点可写性 / 是否已含 Experientia（自动注入前判断，避免重复注入）
            "writable_paths": writable,
            "already_injected": bool(hook.get("already_injected")) and bool(existing),
            "formats": fmts,
        }
    return {
        "report_version": int(raw.get("report_version") or 1),
        "agent": agent,
        "agent_version": str(raw.get("agent_version") or "").strip()[:64] or None,
        "at": str(raw.get("at") or "")[:32] or None,
        # 现场环境（盘符/关键 env）与路径集合指纹（去重/异盘判断用）
        "env": _clean_env(raw.get("env")),
        "finder_hash": _clean_finder_hash(raw.get("finder_hash")),
        "data_sources": kept,
        "hook_surface": hook_surface,
        "warnings": warnings,
    }


def _check_source(p: Path, fmt: str, src: dict) -> tuple[bool, str]:
    """路径存在性 + 文件头一致性（不盲信）。未知格式只要求存在。"""
    if not p.is_file():
        return False, "路径不存在或不是文件"
    if fmt not in _VALID_FORMATS:
        return False, f"未知格式 {fmt!r}"
    try:
        with p.open("rb") as fh:
            head = fh.read(16)
    except (OSError, PermissionError):
        return False, "不可读"
    if fmt in ("plaintext_sqlite", "sqlite"):
        if head != _SQLITE_HEADER:
            return False, "声称明文 SQLite 但文件头不符"
    elif fmt == "encrypted":
        if head == _SQLITE_HEADER:
            return False, "声称加密但实为明文 SQLite"
        if p.stat().st_size < 4096:
            return False, "加密文件应 ≥4096 字节"
    elif fmt in ("jsonl", "json"):
        if head.startswith(_SQLITE_HEADER):
            return False, "声称文本但实为 SQLite"
    return True, ""


# ---------- 吸收 + 选档（scan 每轮调用 / apply 码时调用） ----------

def _channel_for(agent: str, report: dict) -> dict:
    """选档（MVP：只给结论不给动作；注入/解密动作在 S3/S4）。"""
    fmts = {s["format"] for s in report["data_sources"]}
    try:
        from .registry import REGISTRY
        covered = agent in REGISTRY
    except Exception:
        covered = False
    hs = report.get("hook_surface")
    hookable = agent in ("hermes", "cursor", "windsurf")
    # 可注入官方 hook 的 agent 优先提示"实时接入"（连文件捕获都增强为实时）
    if hookable and hs and isinstance(hs, dict) and hs.get("supported"):
        return {"mode": "hook_ready",
                "note": f"发现 {agent} 的官方 hook 注入点：可一次确认后自动接入实时捕获。"}
    if covered and (fmts & set(_PLAINTEXT_FORMATS)):
        return {"mode": "scan_covered",
                "note": f"已识别 {agent}：会话文件可直接扫描，无需 skill，会自动开始捕获。"}
    if covered and "encrypted" in fmts and agent in ("trae", "windsurf"):
        return {"mode": "decrypt_ready",
                "note": f"{agent} 会话库已加密：可在连接页开启一次解密授权。"}
    if hs and isinstance(hs, dict) and hs.get("supported"):
        return {"mode": "hook_ready",
                "note": f"发现 {agent} 的官方 hook 注入点，可接入实时捕获。"}
    return {"mode": "report_only",
            "note": f"{agent} 暂无可直接扫描的文件；将用每轮经验上报兜底（收尾自动记一条）。"}


def consume_report(store, report: dict, code: str | None = None) -> dict:
    """校验通过的自报 → 钥匙落库（明细 + 捕获通道）→ 记录 self_reported → 返回选档。

    code 是该份报告的寻址码（直传/落盘同一码）。同机假设下明细留在本机 keys/，
    吸收即行动：可扫明文（scan_covered）来源并入捕获通道，scan 下一轮常态化捕获，
    不必再靠 skill 重复上报。
    """
    st = _channel_for(report["agent"], report)
    _persist_key(store, code, report, st["mode"])
    _activate_channel(store, code, report, st["mode"])
    summary = {
        "mode": st["mode"], "note": st["note"],
        "agent_version": report.get("agent_version"),
        "at": report.get("at"),
        "warnings": report.get("warnings") or [],
    }
    if code:
        summary["key"] = code
    store.record_self_reported(report["agent"], summary)
    return {"agent": report["agent"], "key": code, **st}


# ---------- 钥匙：落库 + 通道激活（同机假设，吸收即行动） ----------

def _persist_key(store, code: str | None, report: dict, mode: str) -> None:
    """把一份已吸收的自报存成钥匙明细（keys/<code>.json，含完整接入情报）。"""
    if not code:
        return
    from ..store.store import utcnow
    store.save_key_manifest(code, {
        "code": code,
        "at": utcnow(),
        "agent": str(report.get("agent") or ""),
        "agent_version": report.get("agent_version"),
        "mode": mode,
        "env": _env_brief(),
        "report": report,
    })


def _env_brief() -> dict:
    """本机环境底座摘要（只存最小字段；不包含主机名/序列号等敏感信息）。"""
    out = {"os": platform.system()}
    for field, var in (("home", "HOME"), ("localappdata", "LOCALAPPDATA"),
                       ("appdata", "APPDATA"), ("userprofile", "USERPROFILE")):
        val = os.environ.get(var) or ""
        if val:
            out[field] = val
    return out


def _activate_channel(store, code: str | None, report: dict, mode: str) -> None:
    """把可扫明文的来源并入捕获通道（capture_channels.json）。

    M1 只激活 scan_covered（agent 已有适配器但 discover 没扫到的非常规路径，
    由钥匙补充后下一轮 detect 即常态化认它）。加密/注入类通道的动作（一次授权、
    一键注入）仍走既有半自动入口，此处不强行并入避免无谓解析噪音。
    """
    if mode != "scan_covered":
        return
    sources = [{"path": s["path"], "format": s["format"],
                "kind": str(s.get("kind") or "unknown")}
               for s in (report.get("data_sources") or []) if s.get("path")]
    if not sources:
        return
    channels = store.load_capture_channels()
    agent = str(report.get("agent") or "")
    cur = channels.setdefault(agent, {"key": code or "", "mode": mode})
    src_map = {s["path"]: s for s in cur.get("sources", [])}
    for s in sources:
        src_map[s["path"]] = s
    cur["sources"] = sorted(src_map.values(), key=lambda s: str(s["path"]))
    cur["mode"] = mode
    if code:
        cur["key"] = code
    from ..store.store import utcnow
    cur["at"] = utcnow()
    store.save_capture_channels(channels)


def _latest_key_for(store, agent: str) -> tuple[str | None, dict | None]:
    """该 agent 最新一把钥匙（list_key_codes 新码在前）。"""
    for code in store.list_key_codes():
        m = store.load_key_manifest(code)
        if isinstance(m, dict) and str(m.get("agent") or "") == str(agent):
            return code, m
    return None, None


def key_hook_state(store, agent: str) -> dict | None:
    """从最新钥匙读出该 agent 注入面状态（注入兜底查重用）。

    返回 {already_injected, writable, supported}；无钥匙记录 → None（不拦截手动接入）。
    """
    _, m = _latest_key_for(store, agent)
    if m is None:
        return None
    rep = m.get("report")
    hs = rep.get("hook_surface") if isinstance(rep, dict) else None
    if not isinstance(hs, dict):
        return {"already_injected": False, "writable": 0, "supported": False}
    cfg = [p for p in (hs.get("config_paths") or []) if p]
    wp = [p for p in (hs.get("writable_paths") or []) if p]
    return {"already_injected": bool(hs.get("already_injected")),
            "writable": len(wp),
            "supported": bool(hs.get("supported")) and bool(cfg)}


def mark_key_hook_injected(store, agent: str) -> bool:
    """注入写成功后，把最新钥匙的 already_injected 置真（状态回流，幂等）。

    返回是否有钥匙被更新；无钥匙记录/无 hook 面 → False（不误建结构）。
    """
    code, m = _latest_key_for(store, agent)
    if m is None:
        return False
    rep = m.get("report")
    hs = rep.get("hook_surface") if isinstance(rep, dict) else None
    if not isinstance(hs, dict):
        return False
    if hs.get("already_injected"):
        return True
    hs["already_injected"] = True
    store.save_key_manifest(code, m)
    return True


def run_incoming(store) -> int:
    """scan_loop 每轮清扫 incoming：校验→吸收→删除；无效报告删除防堆积。"""
    n = 0
    for code in store.list_incoming_codes():
        raw = store.load_incoming_report(code)
        if not isinstance(raw, dict):
            store.drop_incoming_report(code)
            continue
        # S5：纯经验上报（session_note，无 data_sources）→ 经验分流管线
        if isinstance(raw.get("experience"), dict) and not raw.get("data_sources"):
            try:
                from .self_experience import process as se_process
                se_process(store, str(raw.get("agent") or "unknown"),
                           raw["experience"])
            except Exception as exc:
                logger.warning("incoming %s 经验上报处理失败: %s", code, exc)
                continue  # 保留下轮重试
            store.drop_incoming_report(code)
            n += 1
            continue
        report = validate_report(raw)
        if report is None:
            logger.warning("incoming %s 校验不通过，已丢弃", code)
            store.drop_incoming_report(code)
            continue
        try:
            consume_report(store, report, code)
            n += 1
        except Exception as exc:  # 吸收失败保留文件，下轮重试
            logger.warning("incoming %s 吸收失败: %s", code, exc)
            continue
        store.drop_incoming_report(code)
    return n


def apply_code(store, code: str) -> dict:
    """connect 页粘贴上报码：解码 → 定位 incoming 报告 → 校验吸收。"""
    info = decode_code(code)
    if info is None:
        return {"ok": False, "error": "上报码无效或已损坏"}
    raw = store.load_incoming_report(code)
    if not isinstance(raw, dict):
        return {"ok": False, "error": "未收到该码对应的数据（agent 侧 8101 直传或落盘未成功）",
                "info": info}
    # S5：纯经验上报（session_note）
    if isinstance(raw.get("experience"), dict) and not raw.get("data_sources"):
        try:
            from .self_experience import process as se_process
            res = se_process(store, str(raw.get("agent") or "unknown"),
                             raw["experience"])
        except Exception as exc:
            logger.warning("经验上报 apply 失败: %s", exc)
            return {"ok": False, "error": "经验上报处理失败", "info": info}
        store.drop_incoming_report(code)
        return {"ok": True, "status": {"agent": raw.get("agent"),
                                        "mode": res.get("status", "pending"),
                                        "note": _STATUS_NOTE.get(res.get("status"),
                                                                 res.get("reason", ""))}}
    report = validate_report(raw)
    if report is None:
        store.drop_incoming_report(code)
        return {"ok": False, "error": "报告校验不通过", "info": info}
    st = consume_report(store, report, code)
    store.drop_incoming_report(code)
    return {"ok": True, "status": st}
