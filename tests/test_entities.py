"""实体键（P1-4）测试：抽取规则 + 检索命中。

抽取侧的判据：**键要短语级、要抗噪、中英要归一**——整行当键等于没做（路径、
行号、措辞一变就是两个键），中文说法和英文工具输出对不上等于只认一半。

检索侧的判据：**字面几乎不重叠时，靠键把对的那条捞出来**。这是本项存在的
唯一理由——否则词元打分早就够了。
"""

from app.distill import entities
from app.mcp_server import _tool_search
from app.store.store import Store


def _store(tmp_path):
    st = Store(tmp_path / "data")
    st.ensure_layout()
    return st


# ---------- 抽取 ----------

def test_error_key_is_phrase_not_whole_line():
    """整行当键会随路径/行号漂移——必须短语级且抗噪。"""
    keys = entities.keys_of(
        {"task": "npm run build 报 ERR! Module not found at D:/a/b/c.js:12:3"})
    assert keys == ["err:module not found", "cmd:npm run build"], keys


def test_two_wordings_of_same_error_are_one_key():
    """node 说 Cannot find module、webpack 说 Module not found——同一个键。"""
    a = entities.keys_of({"task": "构建失败：Cannot find module 'axios'"})
    b = entities.keys_of({"task": "构建失败：Module not found 'axios'"})
    assert "err:module not found" in a
    assert "err:module not found" in b


def test_cmd_key_is_skeleton():
    """命令键留骨架：--watch 这类开关不参与比较。"""
    keys = entities.keys_of({"task": "npm run build --watch 很慢"})
    assert "cmd:npm run build" in keys


def test_zh_and_en_land_on_same_key():
    """中文说法与英文工具输出归一到同一规范值，两边才能互相认。"""
    zh = entities.keys_of({"task": "接口请求超时"})
    en = entities.keys_of({"task": "request timed out"})
    assert zh == ["err:timeout"], zh
    assert en == ["err:timeout"], en


def test_project_key_is_basename():
    """项目键只取最后一段：机器路径进键会让键在换机器后失效。"""
    keys = entities.keys_of({"task": "改样式", "project": "F:/work/demo/web"})
    assert keys == ["proj:web"], keys


def test_zh_error_phrases_pass_gate_without_signal_word():
    """：中文报错短语自己就是证据。

    "权限不足：chmod 777 试试" 同行没有报错/失败/超时等信号词——门禁只认
    信号词时，短语表里的权限不足/内存不足/连接被拒绝永远抽不出键。
    """
    assert entities.keys_of({"task": "权限不足：chmod 777 试试"}) == \
        ["err:permission denied"]
    assert entities.keys_of({"task": "uv pip install 时内存不足"}) == \
        ["err:out of memory", "cmd:uv pip install"]
    assert "err:connection refused" in entities.keys_of(
        {"task": "连接被拒绝，服务没起"})


def test_cmd_key_skips_english_stopwords():
    """：make/node/go/uv 与英文常用词碰撞。

    "make sure the config is right" 曾是 cmd:make sure the——动词/目标
    落进停用词表就不是命令骨架。
    """
    assert entities.keys_of({"task": "make sure the config is right"}) == []
    assert "cmd:npm run build" in entities.keys_of(
        {"task": "run npm run build for the app"})


def test_no_signal_no_key():
    assert entities.keys_of({"task": "改了配色", "action": "调成深色"}) == []


def test_exception_class_becomes_key():
    keys = entities.keys_of({"task": "跑脚本报 ModuleNotFoundError"})
    assert "err:modulenotfound" in keys


def test_keys_are_capped():
    rec = {"task": " ".join(f"第{i}步报 ERR! Module not found" for i in range(9))}
    assert len(entities.keys_of(rec)) <= entities.MAX_KEYS


def test_keys_of_never_raises():
    """读时派生：字段形状异常就是没键，绝不把检索链路带崩。"""
    assert entities.keys_of(None) == []
    assert entities.keys_of({"task": 123, "action": ["x"]}) == []
    assert entities.keys_of_query("") == []


# ---------- 检索 ----------

def test_search_rescues_hit_without_word_overlap(tmp_path):
    """词元交集不够、字面几乎不重叠时，实体键把对的那条捞出来。"""
    store = _store(tmp_path)
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "构建",
        "task": "构建失败：Cannot find module 'axios'",
        "action": "pnpm add axios", "outcome": "装好了", "G": 0.9,
    })
    res = _tool_search(store, {"query": "报 Module not found 怎么办"})
    assert res["count"] == 1, res
    assert res["results"][0]["matched_keys"] == ["err:module not found"]
    assert "pnpm add axios" in res["results"][0]["action"]


def test_search_keeps_gate_without_entity_match(tmp_path):
    """没有实体命中时，弱匹配照旧不回吐（实体加分不是放宽门槛）。"""
    store = _store(tmp_path)
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
        "task": "首屏加载很慢", "action": "压缩图片", "outcome": "LCP 降了",
        "G": 0.9,
    })
    res = _tool_search(store, {"query": "数据库连接超时怎么排查"})
    assert res["count"] == 0, res


def test_entity_match_ranks_above_plain_word_match(tmp_path):
    """同样命中，实体命中的那条排在前面。"""
    store = _store(tmp_path)
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "构建",
        "task": "构建失败：Cannot find module 'axios'",
        "action": "pnpm add axios", "outcome": "装好了", "G": 0.9,
    })
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "构建",
        "task": "Module 拆分不合理", "action": "按路由拆分", "outcome": "首屏快了",
        "G": 0.9,
    })
    res = _tool_search(store, {"query": "报 Module not found 怎么办"})
    assert res["count"] >= 1
    assert res["results"][0]["action"] == "pnpm add axios"


def test_search_result_has_no_matched_keys_when_none(tmp_path):
    """没命中就不带这个字段——调用方不必处理空列表。"""
    store = _store(tmp_path)
    store.append_experience({
        "agent": "codebuddy", "trunk": "前端", "category": "页面性能",
        "task": "首屏加载很慢", "action": "压缩图片", "outcome": "LCP 降了",
        "G": 0.9,
    })
    res = _tool_search(store, {"query": "首屏加载很慢怎么优化"})
    assert res["count"] == 1
    assert "matched_keys" not in res["results"][0]
