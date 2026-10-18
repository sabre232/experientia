"""MCP 只读召回服务测试（P0-1）。

重点验三件事：**协议握手对不对、工具结果对不对、以及"只读"是不是机制级保证**。
第三条最关键——"默认只读"不能靠嘴说，得能在这里被证伪。
"""

import io
import json

from app import mcp_server as mcp
from app.store.store import Store

PLAYBOOK = """# 前端 / 页面性能 · playbook

> version: 1

## 失败模式
- [Solidified] 首屏图片不压缩，LCP 超 3 秒（出现 4 次）
- [Watching] 字体文件没有预加载（出现 2 次）

## 成功要点
- 大图一律转 WebP
"""


def _store(tmp_path):
    store = Store(tmp_path)
    store.ensure_layout()
    store.write_skill("前端", "页面性能", PLAYBOOK)
    store.write_preferences("前端", "- 结论先行")
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
        "task": "网页首屏加载很慢", "action": "压缩图片并转 WebP",
        "outcome": "LCP 从 4.2 秒降到 1.8 秒", "G": 0.9, "count": 3,
        "evidence": "压缩后 LCP 4.2s→1.8s",
    })
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
        "task": "样式被缓存打脸", "action": "怀疑 CSS 精灵图方案",
        "outcome": "环境抖动导致的误判", "G": 0.2,
    })
    return store


def _call(store, tool, **args):
    """直接构造请求走协议层（不走 stdio），拿解析后的 tool 结果。"""
    server = mcp.McpServer(store)
    resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": tool, "arguments": args}})
    assert "result" in resp, resp
    assert resp["result"]["isError"] is False, resp
    return json.loads(resp["result"]["content"][0]["text"])


def _snapshot(root):
    """数据资产快照。SQLite 的 -wal/-shm 记账文件不纳入口径（读操作会动它们）。"""
    out = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        name = p.name
        if name.endswith(("-wal", "-shm", "-journal")):
            continue
        st = p.stat()
        out[str(p.relative_to(root))] = (st.st_mtime_ns, st.st_size)
    return out


# ---------- 协议层 ----------

def test_initialize_echoes_protocol_version():
    resp = mcp.McpServer().handle({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05",
                   "clientInfo": {"name": "test"}},
    })
    result = resp["result"]
    assert result["protocolVersion"] == "2024-11-05"  # 回声 = 最大兼容
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["serverInfo"]["name"] == "experientia-mcp"


def test_tools_list_exposes_readonly_tools():
    """全部是只读工具。

    不断言具体数量——工具集会随功能增长；断言的是**性质**：任何一个名字带
    写语义（write/add/set/delete/remove/dismiss/forget/rollback）的都算回归。
    写操作只走本地 API（GUI），不开放给 MCP 客户端。
    """
    resp = mcp.McpServer().handle({"jsonrpc": "2.0", "id": 2,
                                   "method": "tools/list", "params": {}})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names, "工具列表不该为空"
    _WRITE_ISH = ("write", "_add", "add_", "set_", "_set", "delete",
                  "remove", "dismiss", "forget", "rollback", "update")
    leaked = {n for n in names for w in _WRITE_ISH if w in n}
    assert not leaked, f"MCP 暴露了写工具: {leaked}"
    # 已知只读工具必须在场
    assert {"experientia_search", "experientia_get",
            "experientia_context_capsule", "experientia_preferences",
            "experientia_playbook", "experientia_intentions",
            "experientia_failure_modes"} <= names


def test_notification_gets_no_response():
    assert mcp.McpServer().handle({"jsonrpc": "2.0",
                                   "method": "notifications/initialized"}) is None


def test_unknown_method_maps_to_32601():
    resp = mcp.McpServer().handle({"jsonrpc": "2.0", "id": 3,
                                   "method": "nope/whatever"})
    assert resp["error"]["code"] == mcp.METHOD_NOT_FOUND


def test_bad_json_line_reports_parse_error():
    out = io.StringIO()
    mcp._write(out, mcp.McpServer._error(None, mcp.PARSE_ERROR, "boom"))
    assert json.loads(out.getvalue().strip())["error"]["code"] == mcp.PARSE_ERROR


# ---------- 工具结果 ----------

def test_search_filters_low_g_by_default(tmp_path):
    store = _store(tmp_path)
    out = _call(store, "experientia_search", query="首屏 图片 压缩")
    assert out["count"] == 1
    assert out["results"][0]["task"] == "网页首屏加载很慢"


def test_search_can_opt_in_low_g(tmp_path):
    store = _store(tmp_path)
    out = _call(store, "experientia_search", query="CSS",
                include_low_g=True)
    gs = [float(r["g"]) for r in out["results"]]
    assert gs and min(gs) < 0.5


def test_search_empty_query_is_param_error(tmp_path):
    resp = mcp.McpServer(_store(tmp_path)).handle({
        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"name": "experientia_search", "arguments": {"query": ""}},
    })
    assert resp["error"]["code"] == mcp.INVALID_PARAMS


def test_get_returns_full_record_with_evidence(tmp_path):
    store = _store(tmp_path)
    exp_id = next(iter(store.iter_experiences(include_distilled=True)))["id"]
    out = _call(store, "experientia_get", id=exp_id)
    assert out["found"] is True
    assert out["evidence"] == "压缩后 LCP 4.2s→1.8s"
    assert "record" in out


def test_search_requires_meaningful_overlap(tmp_path):
    """弱匹配不回吐：只共享一个二元组的查询不该命中（冒烟实测抓到的噪音）。"""
    store = _store(tmp_path)
    # 经验正文只有"压缩图片"，查询"AVIF 懒加载"与它只共享"加载"
    assert _call(store, "experientia_search", query="AVIF 懒加载")["count"] == 0
    # 查询词基本在场 → 命中
    assert _call(store, "experientia_search", query="图片 压缩")["count"] == 1


def test_search_ranks_by_relevance_then_quality(tmp_path):
    store = _store(tmp_path)
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
        "task": "首屏图片太大", "action": "压缩图片并转 WebP", "outcome": "LCP 降了",
        "G": 0.6, "count": 1,
    })
    out = _call(store, "experientia_search", query="图片 压缩 WebP")
    assert out["count"] == 2
    # "压缩图片并转 WebP" 覆盖率更高（G 也更高）→ 排第一
    assert out["results"][0]["action"] == "压缩图片并转 WebP"


def test_search_tie_break_prefers_newer(tmp_path):
    """L9：同分同 G 同 count 时新记录排前。

    旧实现 tie-break 用 ts 升序——同分时更旧的记录反而排在前面。两条
    文本完全相同（分必然相同）的记录靠 agent 错开防合并计数。
    """
    store = _store(tmp_path)
    for agent, ts in (("a-old", "2026-10-01T00:00:00Z"),
                      ("a-new", "2026-10-09T00:00:00Z")):
        store.append_experience({
            "agent": agent, "trunk": "前端", "category": "页面性能",
            "task": "首屏图片太大", "action": "压缩图片并转 AVIF",
            "outcome": "LCP 降了", "G": 0.6, "count": 1, "ts": ts,
        })
    out = _call(store, "experientia_search", query="图片 压缩 AVIF")
    assert out["count"] >= 2
    assert out["results"][0]["agent"] == "a-new", \
        f"同分记录未按新者在前: {[r['agent'] for r in out['results'][:2]]}"
    assert out["results"][1]["agent"] == "a-old"


def test_search_entity_key_rescues_evidence_only_phrase(tmp_path):
    """L8：实体键的文本源含 evidence——报错原话只在证据里时，词元不重叠的
    问句也靠键把它捞回来（修复前键源无 evidence，这条直接漏）。"""
    store = _store(tmp_path)
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
        "task": "页面打不开", "action": "查了一通没头绪",
        "outcome": "最后靠重装依赖解决", "G": 0.9, "count": 2,
        "evidence": "报错 Module not found: No module named 'pil'",
    })
    # 问句与正文词元几乎不重叠，但报错短语直命中（3/9 覆盖率 < 0.5 门槛，
    # 过线全靠实体键加分）
    out = _call(store, "experientia_search",
                query="上次那个 module not found 怎么修的")
    assert out["total_hits"] == 1
    assert "matched_keys" in out["results"][0], "实体键未参与召回"
    assert "err:module not found" in out["results"][0]["matched_keys"]


def test_get_unknown_id(tmp_path):
    out = _call(_store(tmp_path), "experientia_get", id="no-such-id")
    assert out["found"] is False


def test_capsule_tool_reports_detection(tmp_path):
    store = _store(tmp_path)
    out = _call(store, "experientia_context_capsule",
                task="网页首屏加载很慢怎么办", budget_tokens=400)
    assert out["trunk"] == "前端"
    assert out["category"] == "页面性能"
    assert out["scope_detected"] is True
    assert out["tokens"] <= 400
    assert any(it["id"] for it in out["items"])


def test_playbook_tool(tmp_path):
    store = _store(tmp_path)
    out = _call(store, "experientia_playbook", trunk="前端", category="页面性能")
    assert out["found"] is True
    assert "大图一律转 WebP" in out["playbook"]


def test_failure_modes_three_states(tmp_path):
    """三态是**实时复算**，不是读 playbook 标记：

    playbook 行内标了 4 次，但库里没有支撑经验 + 没有同类成功轨迹
    → 复现门不过 → 仍算 pending，不因"出现次数多"而被抬成 solid。
    """
    store = _store(tmp_path)
    out = _call(store, "experientia_failure_modes",
                trunk="前端", category="页面性能")
    assert out["counts"]["watch"] == 1
    assert out["counts"]["solid"] == 0
    assert out["counts"]["pending"] == 1
    assert out["states"]["pending"][0]["text"].startswith("首屏图片不压缩")


def test_failure_modes_solid_requires_reproduction(tmp_path):
    """补上"同类成功轨迹在坑之后"这条证据，才升 solid（双门同口径）。

    注意：坑与成功经验的 ts 必须显式错开——`utcnow()` 只到秒，同秒写入时
    复现门（后出现 > 最后见坑）判不过来，测试会把"时间太挤"误当成逻辑错。

    另一点：支撑经验的 action/state 必须与 playbook 行正文**近重复**才算"回撑"
    （口径 `dedupe.near_dup`，阈值 0.85）——只写前几个字匹配不上。
    """
    store = _store(tmp_path)
    for i in range(3):
        store.append_experience({
            "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
            "task": f"首屏又超时 {i}", "action": "首屏图片不压缩，LCP 超 3 秒",
            "state": "首屏图片不压缩，LCP 超 3 秒", "outcome": "被用户指出", "G": 0.2,
            "ts": "2026-10-01T00:00:00Z",
        })
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
        "task": "首屏优化完成", "action": "压缩图片并转 WebP",
        "outcome": "LCP 达标", "G": 0.9, "ts": "2026-10-05T00:00:00Z",
    })
    out = _call(store, "experientia_failure_modes",
                trunk="前端", category="页面性能")
    assert out["counts"]["solid"] == 1
    assert out["states"]["solid"][0]["text"].startswith("首屏图片不压缩")
    assert out["states"]["solid"][0]["repro_clear"] is True


def test_preferences_tool_all_and_single(tmp_path):
    store = _store(tmp_path)
    assert "前端" in _call(store, "experientia_preferences")["trunks"]
    single = _call(store, "experientia_preferences", trunk="前端")
    assert "结论先行" in single["trunks"]["前端"]


# ---------- 只读是机制，不是约定 ----------

def test_readonly_proxy_blocks_writes(tmp_path):
    store = _store(tmp_path)
    ro = mcp._ReadOnlyStore(store)
    for name, args in (("write_preferences", ("前端", "- x")),
                       ("append_experience", ({"task": "t"})),
                       ("upsert_override", ("id", True)),
                       ("wipe_all", ())):
        try:
            getattr(ro, name)(*args)
        except PermissionError:
            continue
        raise AssertionError(f"只读代理放行了 store.{name}")
    # 读方法照常放行
    assert ro.read_skill("前端", "页面性能")


def test_tool_calls_do_not_write_data_dir(tmp_path):
    """全链路工具调用后，数据资产必须一字节未动。"""
    store = _store(tmp_path)
    # 先跑一次带范围推断的调用：语义归类可能现场重建类别索引（读侧自愈），
    # 这属于"第一次读触发的自愈"，不是 MCP 写的；先让它落定再快照。
    _call(store, "experientia_context_capsule", task="首屏加载很慢", budget_tokens=200)
    before = _snapshot(store.data_dir)

    _call(store, "experientia_search", query="图片 压缩")
    _call(store, "experientia_get",
          id=next(iter(store.iter_experiences(include_distilled=True)))["id"])
    _call(store, "experientia_context_capsule", task="首屏加载很慢", budget_tokens=200)
    _call(store, "experientia_preferences", trunk="前端")
    _call(store, "experientia_playbook", trunk="前端", category="页面性能")
    _call(store, "experientia_failure_modes", trunk="前端", category="页面性能")

    assert _snapshot(store.data_dir) == before


def test_serve_roundtrip_over_stdio(tmp_path):
    """走完整逐行循环：initialize → 通知(不应答) → tools/list → tools/call → 坏行。"""
    store = _store(tmp_path)
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "experientia_search",
                               "arguments": {"query": "图片 压缩"}}}),
        "",  # 空行静默跳过
        "not json at all",
    ]
    src = io.StringIO("\n".join(lines))
    dst = io.StringIO()

    assert mcp.serve(src, dst, store=store) == 0

    responses = [json.loads(ln) for ln in dst.getvalue().splitlines() if ln.strip()]
    assert [r["id"] for r in responses] == [1, 2, 3, None]
    assert responses[0]["result"]["serverInfo"]["name"] == "experientia-mcp"
    assert len(responses[1]["result"]["tools"]) >= 6   # 工具数会长，别写死
    payload = json.loads(responses[2]["result"]["content"][0]["text"])
    assert payload["count"] >= 1
    assert responses[3]["error"]["code"] == mcp.PARSE_ERROR


def test_serve_tolerates_prefix_before_json(tmp_path):
    """framing 容错：BOM / 乱码残渣 / 杂散前缀一律切到第一个 "{"。

    Windows 管道下 stdin 编码可能不是 UTF-8，BOM 会被解成 3 个乱码字符——
    只 lstrip("\\ufeff") 挡不住，按第一个 "{" 切才稳。
    """
    store = _store(tmp_path)
    payload = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                          "params": {"name": "experientia_search",
                                     "arguments": {"query": "图片"}}})
    for prefix in ("\ufeff\ufeff", "garbage-prefix\xef\xbb"):
        src = io.StringIO(prefix + payload + "\n")
        dst = io.StringIO()
        assert mcp.serve(src, dst, store=store) == 0
        resp = json.loads(dst.getvalue().strip())
        assert resp["id"] == 7
        assert json.loads(resp["result"]["content"][0]["text"])["total_hits"] >= 1


def test_force_utf8_stdio_reconfigures_streams(tmp_path, monkeypatch):
    """Windows 管道下 Python 默认 GBK：中文查询会被解成乱码，必须显式钉 UTF-8。"""
    import sys

    path = tmp_path / "in.txt"
    path.write_text("", encoding="utf-8")
    fh = open(path, "r", encoding="ascii")
    try:
        monkeypatch.setattr(sys, "stdin", fh)
        mcp._force_utf8_stdio()
        assert fh.encoding == "utf-8"
    finally:
        fh.close()


# ---------- 召回热路径缓存（3000 条库 p95 越线后补） ----------
#
# 这两条**不靠计时**判真假：计时在 CI 上会抖，抖了就变成"有时红有时绿"的坏测试。
# 改成数调用次数——同一批记录被第二次查询扫到时，分词/抽键不该再做一遍。
# 这条判据正是 p95 越线的根因（每条记录每次查询重算，各 33ms / 3000 条）。

def _counting(module, name):
    """把 module.name 换成计数包装，返回 (计数器, 原函数)。"""
    calls = {"n": 0}
    orig = getattr(module, name)

    def wrapper(*a, **kw):
        calls["n"] += 1
        return orig(*a, **kw)

    return calls, wrapper, orig


def test_search_does_not_retokenize_documents_on_repeat(tmp_path, monkeypatch):
    """第二次查询（换了问句）只分词问句本身，不再逐条重算记录。"""
    from app.proxy import detect

    store = _store(tmp_path)
    for i in range(4):
        store.append_experience({
            "agent": "codebuddy", "trunk": "前端", "category": "构建",
            "task": f"第{i}次构建失败", "action": "清缓存重装依赖",
            "outcome": "恢复", "G": 0.8,
        })
    detect._cached_token_set.cache_clear()
    calls, wrapper, _orig = _counting(detect, "_token_set")
    monkeypatch.setattr(detect, "_token_set", wrapper)

    mcp._tool_search(store, {"query": "构建失败怎么办"})
    first = calls["n"]
    calls["n"] = 0
    mcp._tool_search(store, {"query": "依赖装不上怎么办"})
    second = calls["n"]

    # 1 次问句 + 5 条记录：`_store` 的第二条 G=0.2，在分词之前就被门禁挡掉，
    # 不进分词——所以是 6 不是 7（L15：注释与数字曾对不上）。
    assert first == 6, f"首轮应分词 1 次问句 + 5 条过闸记录，实际 {first}"
    assert second == 1, f"第二轮只该分词新问句，实际 {second} 次（记录被重算了）"
    detect._cached_token_set.cache_clear()


def test_search_does_not_reextract_entity_keys_on_repeat(tmp_path, monkeypatch):
    """实体键同理：第二次查询不再逐条跑正则。"""
    from app.distill import entities

    store = _store(tmp_path)
    for i in range(4):
        store.append_experience({
            "agent": "codebuddy", "trunk": "前端", "category": "构建",
            "task": f"构建报 ERR! Module not found（第{i}次）",
            "action": "重装依赖", "outcome": "恢复", "G": 0.8,
        })
    entities.cached_keys_of_text.cache_clear()
    calls, wrapper, _orig = _counting(entities, "keys_of_text")
    monkeypatch.setattr(entities, "keys_of_text", wrapper)

    mcp._tool_search(store, {"query": "Module not found 怎么修"})
    first = calls["n"]
    calls["n"] = 0
    mcp._tool_search(store, {"query": "构建报错怎么办"})
    second = calls["n"]

    # 同上一例：G=0.2 那条在抽键之前就被挡掉，故 1 + 5 = 6。
    assert first == 6, f"首轮应抽 1 次问句 + 5 条过闸记录的键，实际 {first}"
    assert second == 1, f"第二轮只该抽问句的键，实际 {second} 次"
    entities.cached_keys_of_text.cache_clear()
