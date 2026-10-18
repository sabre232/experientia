"""「重建空方法卡」入口护栏。

真机现场：本地模型对长提示词返回空字符串，把 `skills/其他/未分类.md` 写成
三节"（无）"还报 success；而那张卡名下的经验**全被标成已总结**（pending=0）——
点「总结成方法」只会回一句 409，应用里没有任何自救入口。

修好写入路径只保证"以后不再写坏"，本文件锁的是**已经写坏的资产如何自救**：

1. 接口层三态：
   - 非 force 且无待总结（都被标过）→ 409，且文案指向「重建」；
   - force 且"旧卡有内容、新卡全空"→ 503，保住原卡不被覆盖；
   - force 正常 → 200 且落盘有内容（空卡被修回来）。
2. 客户端层：force 必须原样透传（漏传 = 按钮点了还是走老路）。
"""

from __future__ import annotations

import pytest

from app.distill import engine_curation as ec
from app.distill import llm
from app.gui.api_client import LocalApi
from app.store.store import Store

MODEL_CFG = {"models": {"local": {"endpoint": "http://127.0.0.1:8081/v1",
                                  "type": "local", "model": "qwen"}},
             "default_model": "local"}

# 被写坏的空卡：frontmatter 齐全（还顶着 confidence: high），三节全是"（无）"
EMPTY_CARD = (
    "# 其他 / 未分类 · playbook\n\n"
    "> name: 常见报错排查\n> version: 3\n> confidence: high\n\n"
    "## 标准流程\n（无）\n## 成功要点\n（无）\n## 失败模式\n（无）\n"
)

CARD_WITH_BODY = EMPTY_CARD.replace("（无）\n## 成功要点", "1. 先看日志\n## 成功要点") \
                            .replace("（无）\n## 失败模式", "- 别硬改引号\n## 失败模式") \
                            .replace("（无）\n", "- [Solidified] 纯情绪文案点击率低（出现 4 次）\n")

MODEL_MD = (
    "## 标准流程\n1. 先复现报错再动代码\n\n"
    "## 成功要点\n- 从日志尾行倒推\n\n"
    "## 失败模式\n- [Solidified] 直接改引号导致新报错（出现 3 次）\n"
)


@pytest.fixture
def store(tmp_path) -> Store:
    st = Store(tmp_path / "data")
    st.ensure_layout()
    st.save_config(MODEL_CFG)
    return st


def _seed_distilled(store: Store, n: int = 4) -> None:
    """塞已总结的经验：复现"卡坏了但 pending=0"的死局现场。"""
    for i in range(n):
        store.append_experience({
            "task": f"排查报错第{i}次", "state": f"报错复现 {i}",
            "action": f"看日志定位第{i}次", "G": 0.6, "g_source": "judge",
            "importance": 7, "agent": "codex", "trunk": "其他",
            "category": "未分类", "session_id": f"s{i}", "count": 3,
            "distilled": True,
            "seen_in": [f"s{i}a", f"s{i}b", f"s{i}c"]})


def _client(store: Store):
    from conftest import local_api_client

    return local_api_client(store)


# ---------- 1. 无待总结 → 409，且文案指向自救路径 ----------

def test_no_pending_409_points_to_rebuild(store):
    """真机死局的直接映射：经验都在但全标过 → 老按钮只能 409，文案必须指路。"""
    _seed_distilled(store)
    assert store.pending_experiences("其他", "未分类") == []  # 现场前提：pending=0
    resp = _client(store).post("/api/skills/distill",
                               json={"trunk": "其他", "category": "未分类"})
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "重建" in detail, f"409 文案没指向自救路径：{detail}"


def test_force_has_material_where_pending_is_empty(store):
    """force 的语义保证：pending=0 时仍能取到该类目"全部"经验（含已总结）。"""
    _seed_distilled(store)
    assert store.pending_experiences("其他", "未分类") == []
    all_exp = list(store.iter_experiences(trunk="其他", category="未分类",
                                          include_distilled=True))
    assert len(all_exp) == 4


# ---------- 2. force 且新旧都空 → 503，保住原卡 ----------

def test_force_empty_result_is_503_and_keeps_card(store, monkeypatch):
    """模型产不出内容 → 503 如实说话，绝不把有内容的旧卡覆盖掉。

    确定性兜底已随删除，无需再给它打桩：空产出本身就是 empty_result。
    """
    store.write_skill("其他", "未分类", CARD_WITH_BODY)
    _seed_distilled(store)
    monkeypatch.setattr(llm, "call_model", lambda s, msgs, **k: "")
    resp = _client(store).post("/api/skills/distill",
                               json={"trunk": "其他", "category": "未分类",
                                     "force": True})
    assert resp.status_code == 503
    assert "保住" in resp.json()["detail"], resp.json()["detail"]
    kept = store.read_skill("其他", "未分类") or ""
    assert "纯情绪文案点击率低" in kept, "旧卡被空产物覆盖了"


# ---------- 3. force 正常 → 200，空卡被修回来 ----------

def test_force_rebuild_repairs_empty_card(store, monkeypatch):
    """正路：空卡 + force → 200，盘上卡从"三节（无）"变成真有内容。"""
    store.write_skill("其他", "未分类", EMPTY_CARD)
    _seed_distilled(store)
    monkeypatch.setattr(llm, "call_model", lambda s, msgs, **k: MODEL_MD)
    resp = _client(store).post("/api/skills/distill",
                               json={"trunk": "其他", "category": "未分类",
                                     "force": True})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    md = store.read_skill("其他", "未分类") or ""
    assert ec.playbook_has_body(md), f"重建后卡还是空的：{md[:160]}"
    assert "先复现报错再动代码" in md


# ---------- 4. 客户端透传（漏传 force = 点按钮还是走 409 老路） ----------

class _FakeResp:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def json(self) -> dict:
        return self._payload


class _CountingClient:
    def __init__(self):
        self.calls: list[tuple] = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return _FakeResp({"ok": True})


def _fake_api(monkeypatch):
    monkeypatch.setenv("EXPERIENTIA_API_TOKEN", "test-token")
    api = LocalApi(base_url="http://127.0.0.1:8101")
    fake = _CountingClient()
    api._client = fake  # type: ignore[assignment]
    return api, fake


def test_api_client_passes_force(monkeypatch):
    api, fake = _fake_api(monkeypatch)
    api.distill("其他", "未分类", force=True)
    assert fake.calls[-1][2]["json"] == {"trunk": "其他", "category": "未分类",
                                         "force": True}
    api.distill("其他", "未分类")
    assert fake.calls[-1][2]["json"]["force"] is False, "默认必须是非强制"


# ---------- 5. 判空口径：GUI 靠它决定要不要给「重建」 ----------

@pytest.mark.parametrize("md,has_body", [
    (EMPTY_CARD, False),
    (CARD_WITH_BODY, True),
    ("", False),
    ("## 标准流程\n（无）\n## 成功要点\n（无）\n## 失败模式\n- 有一条\n", True),
])
def test_playbook_has_body_verdict(md, has_body):
    assert ec.playbook_has_body(md) is has_body
