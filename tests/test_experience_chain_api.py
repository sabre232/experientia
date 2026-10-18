"""经验演化链 / 遗忘 / 回滚的本地 API 测试（P0-3 的用户可见出口）。

重点验两件事：**链路本身对不对**，以及**`/restore`（取消不采纳）与 `/unforget`
（撤销遗忘）两条语义完全不同的路径没被搞混**。
"""

from app.store.store import Store

EXP = {
    "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
    "task": "首屏加载很慢", "action": "压缩图片", "outcome": "LCP 2.0s", "G": 0.9,
}


def _store(tmp_path):
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


def _seed(store):
    a = store.append_experience(dict(EXP))
    b = store.supersede_experience(a["id"], {"action": "图片转 AVIF + 懒加载"})
    return a, b


def test_chain_endpoint_shape(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    a, b = _seed(store)
    client = local_api_client(store)

    r = client.get(f"/api/experiences/{b['id']}/chain")
    assert r.status_code == 200
    chain = r.json()["chain"]
    assert chain["depth"] == 2
    assert chain["root_id"] == a["root_id"]
    assert chain["current"]["id"] == b["id"]
    assert [x["revision"] for x in chain["revisions"]] == [1]

    assert client.get("/api/experiences/nope/chain").status_code == 404


def test_rollback_endpoint_creates_new_head(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    a, b = _seed(store)
    client = local_api_client(store)

    r = client.post(f"/api/experiences/{b['id']}/rollback", json={"revision": 1})
    assert r.status_code == 200
    exp = r.json()["experience"]
    assert exp["action"] == a["action"]       # 内容回到旧版
    assert exp["revision"] == 3               # 但它是新版本
    assert client.get(f"/api/experiences/{exp['id']}/chain").json()["chain"]["depth"] == 3

    # 不存在的版本 → 409，不 500
    bad = client.post(f"/api/experiences/{exp['id']}/rollback", json={"revision": 99})
    assert bad.status_code == 409


def test_forget_and_unforget_endpoints(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    _a, b = _seed(store)
    client = local_api_client(store)

    assert client.post(f"/api/experiences/{b['id']}/forget",
                       json={"hard": False}).status_code == 200
    items = client.get("/api/experiences").json()["items"]
    assert b["id"] not in [x["id"] for x in items]

    assert client.post(f"/api/experiences/{b['id']}/unforget").status_code == 200
    items = client.get("/api/experiences").json()["items"]
    assert b["id"] in [x["id"] for x in items]

    # 重复撤销 → 409（不在已遗忘状态）
    assert client.post(f"/api/experiences/{b['id']}/unforget").status_code == 409


def test_hard_forget_removes_from_list(tmp_path):
    from conftest import local_api_client

    store = _store(tmp_path)
    _a, b = _seed(store)
    client = local_api_client(store)

    r = client.post(f"/api/experiences/{b['id']}/forget", json={"hard": True})
    assert r.status_code == 200
    assert client.get(f"/api/experiences/{b['id']}/chain").status_code == 404
    items = client.get("/api/experiences").json()["items"]
    assert items == []


def test_dismiss_restore_is_not_unforget(tmp_path):
    """/restore 管"取消不采纳"，/unforget 管"撤销遗忘"——同一个 id 上两者互不干扰。"""
    from conftest import local_api_client

    store = _store(tmp_path)
    _a, b = _seed(store)
    client = local_api_client(store)

    # 先不采纳
    assert client.post(f"/api/experiences/{b['id']}/dismiss").status_code == 200
    assert client.get("/api/experiences").json()["items"] == []
    # "取消不采纳"不该把已遗忘状态变没——它俩是不同字段
    assert client.post(f"/api/experiences/{b['id']}/unforget").status_code == 409
    # 取消不采纳后回到列表
    assert client.post(f"/api/experiences/{b['id']}/restore").status_code == 200
    assert b["id"] in [x["id"] for x in client.get("/api/experiences").json()["items"]]

    # 反过来：遗忘后用 /restore 也救不回来
    client.post(f"/api/experiences/{b['id']}/forget")
    assert client.post(f"/api/experiences/{b['id']}/restore").status_code == 200
    assert b["id"] not in [x["id"] for x in client.get("/api/experiences").json()["items"]]
    assert client.post(f"/api/experiences/{b['id']}/unforget").status_code == 200
    assert b["id"] in [x["id"] for x in client.get("/api/experiences").json()["items"]]
