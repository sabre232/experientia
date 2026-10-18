"""热路径文本缓存（M-5）：注入每次 LLM 请求组装，stat 校验防陈旧读。

命中 = 1 次 stat；未命中才 open+read。写口失效 + mtime/size 校验双保险：
绕过 Store 写口的外部修改（mtime 变化）下一读即重读。
"""

from app.store.store import Store


def _store(tmp_path) -> Store:
    s = Store(tmp_path)
    s.ensure_layout()
    return s


def test_cached_read_and_invalidation_on_write(tmp_path):
    s = _store(tmp_path)
    s.write_skill("营销", "文案", "v1")
    assert s.read_skill("营销", "文案") == "v1"
    assert s.read_skill("营销", "文案") == "v1"  # 第二次走缓存
    assert len(s._file_cache) == 1
    s.write_skill("营销", "文案", "v2")
    assert s.read_skill("营销", "文案") == "v2"  # 写口失效


def test_external_write_detected_by_mtime(tmp_path):
    s = _store(tmp_path)
    p = s.write_skill("营销", "文案", "v1")
    assert s.read_skill("营销", "文案") == "v1"
    p.write_text("v2-longer")  # 绕过 Store 写口（外部工具/手改）
    assert s.read_skill("营销", "文案") == "v2-longer"  # mtime+size 变化 → 重读


def test_missing_file_returns_none(tmp_path):
    s = _store(tmp_path)
    assert s.read_skill("营销", "不存在") is None
    assert s.read_text_cached(tmp_path / "ghost.md") is None
    assert len(s._file_cache) == 0  # 未命中不进缓存


def test_wipe_all_clears_cache(tmp_path):
    s = _store(tmp_path)
    s.write_skill("营销", "文案", "v1")
    assert s.read_skill("营销", "文案") == "v1"
    s.wipe_all()
    assert len(s._file_cache) == 0
    assert s.read_skill("营销", "文案") is None
