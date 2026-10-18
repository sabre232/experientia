"""MCP 只读召回服务（P0-1，补方案里最大的缺口：召回面）。

让任何支持 MCP 的 AI 客户端（CodeBuddy / Claude Code / Codex / Cursor …）能**按需查询**
本地经验库，而不必等代理转发 / hook 回灌这种被动推送。

传输：stdio，换行分隔的 JSON-RPC 2.0 消息（MCP 标准传输方式，无 HTTP、无端口）。
日志：一律走 stderr，**stdout 只承载协议消息**——往 stdout 打任何一行都会污染协议流。

三条硬约束：

1. **只读**：不暴露任何写工具；Store 被 `_ReadOnlyStore` 代理包一层，白名单之外的
   方法直接 `PermissionError`。"默认只读"是机制，不是口头约定。新增读需求 = 往
   白名单显式加一行，不会因为忘记约束而漏出写能力。
2. **不联网**：不下载、不安装、不检查更新，符合写入面红线。本模块也不开端口。
3. **fail-open**：任何单条请求异常只让该请求返回 isError，绝不带崩服务进程。

纪律对应：D7 取用纪律（G<0.5 永不出现、输出有界、每条带 id）、D2 归位（胶囊层序）。

用法（客户端配置片段，需要用户自行写入自己的 MCP 配置，本服务不自动改用户环境）：

    {
      "mcpServers": {
        "experientia": {
          "command": "experientia-mcp"
        }
      }
    }
"""

from __future__ import annotations

import json
import logging
import os
import sys

from .distill import entities as _entities
from .distill.capsule import (DEFAULT_BUDGET_TOKENS, build_capsule,
                              resolve_scope)
from .distill.gsignal import G_MIN_INJECT
from .time_util import parse_ts

logger = logging.getLogger("experientia.mcp")

SERVER_NAME = "experientia-mcp"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# search 单次最多扫多少条经验（防大库时一次查询把 CPU 拖死）
SEARCH_SCAN_LIMIT = 3000
# 相关性下限：查询词的覆盖率 ≥ 该值才算命中。
# 不设阈值的后果（冒烟实测）：查 "AVIF 懒加载" 会命中 "压缩图片"——两者只共享
# "加载" 一个二元组，覆盖率 1/3 也算命中，召回一堆半相关的噪音。
# 口径与 app/semantic/router.py 的"宁缺毋滥"一致：宁可少给，不给凑数的。
SEARCH_MIN_SCORE = 0.5
# 实体键命中的加分（P1-4）：命中一条键就 +0.5，直接把"同一个报错/同一条命令"
# 的记录顶过相关性门槛——字面不重叠才更要靠键认亲
ENTITY_BONUS = 0.5
# 工具返回的单字段最大长度（防一条异常长的经验把响应撑爆）
FIELD_MAX_CHARS = 500


# ---------- 只读代理：把"默认只读"从约定变成机制 ----------

class _ReadOnlyStore:
    """Store 的只读视图。

    白名单只放召回链路会用到的读方法；其余属性访问一律 raise PermissionError。
    内部调用（如 `load_category_index` 内部再调 `read_text_cached`）发生在
    Store 本体上，不过本代理，故只需列"链路入口"这一层。
    """

    _ALLOWED = frozenset({
        # 配置 / 覆盖层
        "load_config", "load_overrides", "load_rules",
        # 偏好画像
        "read_preferences", "list_preference_trunks",
        # 方法卡 / 纠正补丁
        "read_skill", "read_fixes", "list_skills",
        # 经验读路径
        "iter_experiences", "find_experience", "experience_categories",
        # 意图读路径（intentions 工具 + 胶囊 include_intents）
        "list_intentions",
        # 回炉治理状态（注入预览与召回必须同一口径，见 M1 修复）
        "load_injection_hits",
        # 语义归类读的派生索引
        "load_category_index",
        # 资源定位（embedder 探测模型文件）
        "dir",
    })

    def __init__(self, store):
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name):
        if name not in self._ALLOWED:
            raise PermissionError(f"MCP 召回通道为只读：拒绝访问 store.{name}")
        return getattr(object.__getattribute__(self, "_store"), name)

    def __setattr__(self, name, value):
        raise PermissionError("MCP 召回通道为只读：禁止写 Store 属性")


# ---------- 工具定义 ----------

_TOOLS: list[dict] = [
    {
        "name": "experientia_search",
        "description": (
            "在本地经验库里搜相关经验（坑 / 做法 / 决策）。默认只返回 G≥0.5 的"
            "可信经验，G<0.5 的低可信条目默认排除。适合动手前先查有没有踩过同样的坑。"
            "直接贴报错原文（如 Module not found、超时）或命令（如 npm run build）"
            "效果最好——同报错同命令的记录会按实体键直捞，不受措辞差异影响。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要查的问题或任务描述"},
                "trunk": {"type": "string", "description": "限定主干（可选）"},
                "category": {"type": "string", "description": "限定类别（可选）"},
                "agent": {"type": "string", "description": "限定来源 agent（可选）"},
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                "include_low_g": {
                    "type": "boolean", "default": False,
                    "description": "是否连 G<0.5 的低可信经验一起返回（默认否）",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "experientia_get",
        "description": "按 id 取单条经验全文（含证据与原话锚点）。",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "experientia_context_capsule",
        "description": (
            "取一段有上限的上下文胶囊：偏好 → 失败模式 → 纠正补丁 → 标准流程 → 经验要点，"
            "按预算截断，每条带 id。不传 trunk/category 时从任务文本推断范围。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "当前任务描述（用于推断范围）"},
                "trunk": {"type": "string"},
                "category": {"type": "string"},
                "budget_tokens": {
                    "type": "integer", "default": DEFAULT_BUDGET_TOKENS,
                    "minimum": 0, "maximum": 8000,
                },
                "include_intents": {
                    "type": "boolean", "default": False,
                    "description": "是否附带 L6 前瞻意图（“接下来可能要处理什么”）——"
                                   "低权重尾层，不是指令",
                },
                "refill": {
                    "type": "boolean", "default": False,
                    "description": "范围是从任务文本猜的（scope_detected）时自动开启："
                                   "首轮条目不足 2 条，再捞一轮高可信经验补齐，"
                                   "共用同一预算",
                },
            },
        },
    },
    {
        "name": "experientia_preferences",
        "description": "读偏好画像。给 trunk 读一个，不给就读全部。",
        "inputSchema": {
            "type": "object",
            "properties": {"trunk": {"type": "string"}},
        },
    },
    {
        "name": "experientia_playbook",
        "description": "读某个 trunk/category 的方法卡（失败模式 / 纠正补丁 / 标准流程 / 成功要点）。",
        "inputSchema": {
            "type": "object",
            "properties": {"trunk": {"type": "string"}, "category": {"type": "string"}},
            "required": ["trunk", "category"],
        },
    },
    {
        "name": "experientia_intentions",
        "description": (
            "读 L6 前瞻意图：从反复出现的模式里沉淀的“接下来可能要处理什么”。"
            "意图**不是指令**，别照着改用户的目标。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "trunk": {"type": "string", "description": "限定主干（可选）"},
            },
        },
    },
    {
        "name": "experientia_failure_modes",
        "description": (
            "某个 trunk/category 下失败模式的实时三态（watch / pending / solid）。"
            "只有 solid 是可信的；watch/pending 仅供了解，别当结论用。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"trunk": {"type": "string"}, "category": {"type": "string"}},
            "required": ["trunk", "category"],
        },
    },
]

_TOOL_NAMES = frozenset(t["name"] for t in _TOOLS)


# ---------- 工具实现（全部只读，全部不抛异常） ----------

def _clip(text, limit: int = FIELD_MAX_CHARS) -> str:
    s = "" if text is None else str(text)
    return s if len(s) <= limit else s[:limit] + "…"


def _evidence_text(rec: dict) -> str:
    """evidence 可能是旧版纯字符串，也可能是 P0-2 之后的结构体——统一取引文。

    口径只此一份（app/distill/evidence.py），召回侧与写入侧不许各写一套。
    """
    from .distill import evidence as _evidence

    return _clip(_evidence.quote_of(rec))


def _summarize(rec: dict) -> dict:
    return {
        "id": rec.get("id"),
        "agent": rec.get("agent"),
        "trunk": rec.get("trunk"),
        "category": rec.get("category"),
        "task": _clip(rec.get("task")),
        "action": _clip(rec.get("action")),
        "outcome": _clip(rec.get("outcome")),
        "state": _clip(rec.get("state")),
        "g": rec.get("G"),
        "count": rec.get("count"),
        "ts": rec.get("ts"),
        "session_id": rec.get("session_id"),
        "evidence": _evidence_text(rec),
    }


def _searchable_text(rec: dict) -> str:
    # 字段集与 entities.TEXT_FIELDS 同一份定义：词元匹配与实体键必须看同一段
    # 文本（L8：此前两者各拼一次且字段集不同——实体键永远看不到 evidence）。
    return " ".join(str(rec.get(k) or "") for k in _entities.TEXT_FIELDS)


def _ts_rank(rec: dict) -> float:
    """tie-break 时间序：同分同 G 同 count 时**新**记录排前。

    元组升序排序里前三个元素都取负实现降序，时间戳取负走 epoch；解析不了
    的给 0.0——大于任何有效取负值，排最后（缺时间戳不该反而插到最前）。
    """
    dt = parse_ts(rec.get("ts"))
    return -dt.timestamp() if dt is not None else 0.0


def _tool_search(store, args: dict) -> dict:
    # 缓存版而非重算版：同一条记录会被连续多次查询反复扫到，逐条重算分词
    # 在 3000 条库上是 33ms（p95 的一半）。检测侧早就用缓存版，这里原来漏了。
    from .proxy.detect import _cached_token_set

    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("query 不能为空")
    limit = int(args.get("limit") or 10)
    limit = max(1, min(50, limit))
    include_low_g = bool(args.get("include_low_g"))

    q = _cached_token_set(query)
    raw = query.lower()
    qkeys = _entities.keys_of_query(query)
    scanned = 0
    hits: list[tuple[tuple, dict]] = []
    for rec in store.iter_experiences(
            trunk=args.get("trunk") or None,
            category=args.get("category") or None,
            agent=args.get("agent") or None,
            include_distilled=True):
        scanned += 1
        if scanned > SEARCH_SCAN_LIMIT:
            break
        # dismissed 复查已删——`iter_experiences` 默认就滤掉已忽略的
        # （SQLite 下推到 WHERE，JSONL 回退在循环里跳），这里再查一遍是纯冗余。
        # D7：默认只给可信经验
        if not include_low_g:
            try:
                if float(rec.get("G") or 0) < G_MIN_INJECT:
                    continue
            except (TypeError, ValueError):
                continue
        text = _searchable_text(rec)
        doc = _cached_token_set(text)
        inter = len(q & doc)
        # 实体键（P1-4）："上次那个报错怎么修的"靠报错串直捞，不靠词元相似度——
        # 问句与记录往往字面完全不同（"报 Module not found" vs "重装依赖"）。
        matched = sorted(set(qkeys) & set(_entities.keys_of(rec)))
        if inter == 0:
            # 分词毫无交集时先看整串包含，再看实体命中（罕见但强相关）
            if raw and raw in text.lower():
                inter = len(q) or 1
            elif not matched:
                continue
        score = inter / (len(q) or 1)
        if raw and raw in text.lower():
            score += 0.2
        if matched:
            score += ENTITY_BONUS  # 实体命中直接过门槛，且排在词元命中之前
        if score < SEARCH_MIN_SCORE:
            continue  # 弱匹配不回吐：凑数的结果比没有更糟
        key = (-round(score, 6), -float(rec.get("G") or 0),
               -int(rec.get("count") or 1), _ts_rank(rec))
        out = _summarize(rec)
        if matched:
            out["matched_keys"] = matched
        hits.append((key, out))

    hits.sort(key=lambda kv: kv[0])
    return {
        "query": query,
        "scanned": min(scanned, SEARCH_SCAN_LIMIT),
        "count": min(len(hits), limit),
        "total_hits": len(hits),
        "results": [rec for _k, rec in hits[:limit]],
    }


def _tool_get(store, args: dict) -> dict:
    rec_id = str(args.get("id") or "").strip()
    if not rec_id:
        raise ValueError("id 不能为空")
    rec = store.find_experience(rec_id)
    # 与 search 同一口径（D6：默认读路径一律不返回已遗忘/已忽略/已换代）——
    # find_experience 保持不限（演化链/回滚要能看到），只读出口在此过滤。
    if rec is not None and (rec.get("tombstone") or rec.get("dismissed")
                            or str(rec.get("superseded_by") or "")):
        rec = None
    if rec is None:
        return {"id": rec_id, "found": False}
    out = {"id": rec_id, "found": True}
    out.update(_summarize(rec))
    out["record"] = _clip(json.dumps(rec, ensure_ascii=False, default=str),
                          FIELD_MAX_CHARS * 6)
    return out


def _tool_capsule(store, args: dict) -> dict:
    task = args.get("task")
    trunk, category, detected = resolve_scope(
        store, str(task or "").strip() or None,
        trunk=args.get("trunk"), category=args.get("category"))
    # 补捞（P1-3）：范围是猜来的才补——猜偏了最容易空手而归；调用方显式给了
    # trunk/category 就别自作主张放宽（"宁缺毋滥"是取用纪律 D7 的老规矩）。
    cap = build_capsule(store, trunk, category, args.get("budget_tokens"),
                        include_intents=bool(args.get("include_intents")),
                        refill=detected or bool(args.get("refill")))
    cap["scope_detected"] = detected
    return cap


def _tool_preferences(store, args: dict) -> dict:
    trunks = [str(args.get("trunk")).strip()] if args.get("trunk") \
        else store.list_preference_trunks()
    out = {}
    for trunk in trunks:
        md = trunk and (store.read_preferences(trunk) or "")
        out[trunk or ""] = md or ""
    return {"trunks": out}


def _tool_playbook(store, args: dict) -> dict:
    trunk = str(args.get("trunk") or "").strip()
    category = str(args.get("category") or "").strip()
    if not trunk or not category:
        raise ValueError("trunk 与 category 必填")
    md = store.read_skill(trunk, category) or ""
    fixes = store.read_fixes(trunk, category) or ""
    return {"trunk": trunk, "category": category, "found": bool(md),
            "playbook": md, "fixes": fixes}


def _tool_intentions(store, args: dict) -> dict:
    trunk = (args.get("trunk") or "").strip()
    items = store.list_intentions(trunk or None)
    return {
        "trunk": trunk or None,
        "count": len(items),
        "intentions": [{"id": it.get("id"), "intent": it.get("intent"),
                        "trunk": it.get("trunk"), "category": it.get("category"),
                        "occurrences": it.get("count"),
                        "expires_at": it.get("expires_at")} for it in items],
    }


def _tool_failure_modes(store, args: dict) -> dict:
    from .distill import gate

    trunk = str(args.get("trunk") or "").strip()
    category = str(args.get("category") or "").strip()
    if not trunk or not category:
        raise ValueError("trunk 与 category 必填")
    states = gate.failure_mode_states(store, trunk, category)
    grouped: dict[str, list[dict]] = {"solid": [], "pending": [], "watch": []}
    for desc, st in states.items():
        state = str(st.get("state") or "watch")
        grouped.setdefault(state, []).append({"text": desc, **st})
    return {"trunk": trunk, "category": category,
            "counts": {k: len(v) for k, v in grouped.items()},
            "states": grouped}


_HANDLERS = {
    "experientia_search": _tool_search,
    "experientia_get": _tool_get,
    "experientia_context_capsule": _tool_capsule,
    "experientia_preferences": _tool_preferences,
    "experientia_playbook": _tool_playbook,
    "experientia_intentions": _tool_intentions,
    "experientia_failure_modes": _tool_failure_modes,
}


# ---------- MCP 协议层 ----------

class McpServer:
    """一个最小 MCP 服务端：只实现 initialize / tools.list / tools.call / ping。"""

    def __init__(self, store=None):
        self._store = None if store is None else _ReadOnlyStore(store)

    # -- Store 惰性构建：只在真有请求时开库，便于测试注入 -- --
    def _store_or_open(self):
        if self._store is None:
            from .store.store import Store

            store = Store()
            store.ensure_layout()
            self._store = _ReadOnlyStore(store)
        return self._store

    # -- 消息分发：返回 None 表示这是通知，不应答 -- --
    def handle(self, message):
        if not isinstance(message, dict):
            return self._error(None, INVALID_REQUEST, "请求不是 JSON 对象")
        mid = message.get("id")
        method = str(message.get("method") or "")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        if mid is None:  # 通知：不需应答
            return None
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": str(params.get("protocolVersion")
                                           or DEFAULT_PROTOCOL_VERSION),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": _version()},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": _TOOLS}
            elif method == "tools/call":
                result = self._call_tool(params)
            else:
                return self._error(mid, METHOD_NOT_FOUND, f"未知方法: {method}")
        except PermissionError as exc:
            return self._error(mid, INVALID_PARAMS, f"被拒绝：{exc}")
        except (ValueError, KeyError, TypeError) as exc:
            return self._error(mid, INVALID_PARAMS, f"参数错误：{exc}")
        except Exception as exc:  # noqa: BLE001 单请求失败不带崩进程
            logger.warning("tools/call 处理失败: %s", exc, exc_info=True)
            return self._error(mid, INTERNAL_ERROR, f"内部错误：{exc}")
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def _call_tool(self, params: dict) -> dict:
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        if name not in _TOOL_NAMES:
            raise ValueError(f"未知工具: {name}")
        if not isinstance(args, dict):
            raise ValueError("arguments 必须是对象")
        out = _HANDLERS[name](self._store_or_open(), args)
        text = json.dumps(out, ensure_ascii=False, default=str, indent=2)
        return {"content": [{"type": "text", "text": text}], "isError": False}

    @staticmethod
    def _error(mid, code, message):
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": code, "message": message}}


def _version() -> str:
    try:
        from .version import VERSION

        return str(VERSION)
    except Exception:  # noqa: BLE001 版本号拿不到不影响服务
        return "0"


def serve(stream_in=None, stream_out=None, store=None) -> int:
    """stdio 主循环。stdout 只写协议消息；任何日志走 stderr。

    `store` 仅供测试注入（避免测试打开真实 ~/.experientia）；生产缺省为 None，
    由首个需要数据的请求惰性打开。
    """
    stream_in = stream_in if stream_in is not None else sys.stdin
    stream_out = stream_out if stream_out is not None else sys.stdout
    server = McpServer(store)
    for line in stream_in:
        # framing 容错：BOM / 编码残渣 / 杂散前缀一律切到第一个 "{"。
        # MCP stdio 规定 UTF-8，但 Windows 管道下 Python 默认取控制台代码页
        # （本机 GBK），BOM 会被解成 3 个乱码字符——只 lstrip("﻿") 挡不住。
        line = line.strip()
        brace = line.find("{")
        if brace > 0:
            line = line[brace:]
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            _write(stream_out, McpServer._error(None, PARSE_ERROR, f"JSON 解析失败: {exc}"))
            continue
        try:
            response = server.handle(message)
        except Exception as exc:  # noqa: BLE001 兜底：绝不因单条消息退出
            logger.warning("消息处理异常: %s", exc, exc_info=True)
            response = McpServer._error(
                (message or {}).get("id") if isinstance(message, dict) else None,
                INTERNAL_ERROR, f"内部错误：{exc}")
        if response is not None:
            _write(stream_out, response)
    return 0


def _write(stream, payload: dict) -> None:
    stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    stream.flush()


def _setup_debug_logging() -> None:
    """默认静默（Logger 无 handler → 走 lastResort 也只在 WARNING 以上零星打 stderr）。

    EXPERIENTIA_MCP_DEBUG=1 时把 DEBUG 及以上打到 stderr，用于排查客户端接入问题。
    """
    if os.environ.get("EXPERIENTIA_MCP_DEBUG") != "1":
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False


def _force_utf8_stdio() -> None:
    """把进程的标准输入/输出钉成 UTF-8。

    MCP stdio 规定 UTF-8，而 Windows 管道下 Python 默认取控制台代码页（本机 GBK）：
    客户端发来的中文查询会被解成乱码，BOM 更会变成 3 个乱码字符。能 reconfigure
    就改（Python 3.7+），改不了（测试注入 StringIO）就不动。
    """
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 非标准流（StringIO / 已 detach）不致命
            pass


def main(argv: list[str] | None = None) -> int:
    _setup_debug_logging()
    _force_utf8_stdio()
    logger.info("%s 启动（pid=%s）", SERVER_NAME, os.getpid())
    try:
        return serve()
    except (BrokenPipeError, KeyboardInterrupt):
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
