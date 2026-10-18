"""L6 前瞻意图的用户可见出口测试（本地 API + MCP 工具）。

补这个域之前，意图只有引擎侧在读——用户看不见也忽略不了。这里锁死三件事：
列表/忽略真的通、MCP 能查、以及 MCP 侧**只读**（意图只有 GUI 能忽略）。

MCP 侧一律走协议层（`McpServer.handle`）：只读代理必须在被测路径上——
直调 `_tool_intentions(store, ...)` 绕过代理，白名单漏方法时测试照样绿，
而生产通道恒失败（H1 的教训）。
"""

import json

from app.store.store import Store


def _store(tmp_path):
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


def _mcp_call(store, name, arguments=None):
    """走协议层调 MCP 工具；返回解析后的工具结果。"""
    from app.mcp_server import McpServer

    resp = McpServer(store).handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}}})
    assert "error" not in resp, resp
    return json.loads(resp["result"]["content"][0]["text"])


def _seed(store):
    a = store.add_intention("把图片优化流程固化", "前端", "页面性能",
                            evidence_ids=["e1", "e2"])
    b = store.add_intention("动手前先确认边界", "Python", "修复")
    return a, b


# ---------- 本地 API ----------

def test_intentions_list_api(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    _a, _b = _seed(store)
    client = local_api_client(store)

    r = client.get("/api/intentions")
    assert r.status_code == 200
    items = r.json()["items"]
    assert {i["intent"] for i in items} == \
        {"把图片优化流程固化", "动手前先确认边界"}

    # trunk 过滤
    r2 = client.get("/api/intentions", params={"trunk": "前端"})
    assert [i["intent"] for i in r2.json()["items"]] == ["把图片优化流程固化"]


def test_intention_dismiss_api(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    a, _b = _seed(store)
    client = local_api_client(store)

    assert client.post(f"/api/intentions/{a['id']}/dismiss").status_code == 200
    assert client.get("/api/intentions").json()["count"] == 1
    # 幂等：再点一次 409（不存在或已忽略）
    assert client.post(f"/api/intentions/{a['id']}/dismiss").status_code == 409


def test_intention_dismiss_unknown_id(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    client = local_api_client(store)
    r = client.post("/api/intentions/nope/dismiss")
    assert r.status_code == 409


def test_layers_inventory_api(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    store.write_preferences("前端", "- 结论先行")
    store.write_skill("前端", "页面性能", "# p\n")
    store.add_intention("一条意图", "前端", "页面性能")
    client = local_api_client(store)

    layers = client.get("/api/layers").json()["layers"]
    assert set(layers) == {"L1", "L2", "L3", "L4", "L5", "L6"}
    assert layers["L3"]["count"] == 1
    assert layers["L5"]["count"] == 1
    assert layers["L6"]["count"] == 1
    # 每层都带"叫什么、存在哪"
    assert layers["L6"]["name"] and layers["L6"]["home"]


def test_layers_api_never_500s(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    client = local_api_client(store)
    r = client.get("/api/layers")
    assert r.status_code == 200


# ---------- MCP 侧：能查，且只读 ----------

def test_mcp_intentions_tool(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    out = _mcp_call(store, "experientia_intentions")
    assert out["count"] == 2
    assert {i["intent"] for i in out["intentions"]} == \
        {"把图片优化流程固化", "动手前先确认边界"}
    # trunk 过滤
    out2 = _mcp_call(store, "experientia_intentions", {"trunk": "Python"})
    assert out2["count"] == 1
    assert out2["intentions"][0]["occurrences"] == 1
    # expires_at 一并给出（GUI "还会提醒多久" 的数据源）
    assert all(i["expires_at"] for i in out["intentions"])


def test_mcp_has_no_intention_write_tool(tmp_path):
    """MCP 通道只读：忽略意图这种写操作只能走本地 API（GUI），不开放给客户端。"""
    from app import mcp_server as mcp

    assert not any("intent" in n and n != "experientia_intentions"
                   for n in mcp._TOOL_NAMES)
    assert "experientia_intentions" in mcp._TOOL_NAMES


def test_mcp_intentions_empty_store(tmp_path):
    store = _store(tmp_path)
    assert _mcp_call(store, "experientia_intentions")["count"] == 0
