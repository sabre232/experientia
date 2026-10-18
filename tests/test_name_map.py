"""app/gui/_name_map.py：方法显示名缓存的唯一收口点（去重 R2）。

钉两类契约：
1. 行为契约——增量补 / 全量重建 / 失效的语义，以及 dict 与 list 两种入参形状；
2. 收口契约——GUI 层不许再各自缓存一份 name_map。
   病灶：原先 skill_organize 与 inject_preview 各存一份，失效函数只作废了前者，
   导致改名后注入预览页的类别下拉在进程存续期内永远是旧名。靠 review 记不住，靠测试。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.gui import _name_map as name_map

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean():
    """每个用例跑前清空——这是模块级单例，不隔离会互相污染。"""
    name_map.invalidate()
    yield
    name_map.invalidate()


def _skill(trunk, category, name):
    return {"trunk": trunk, "category": category, "name": name}


class TestShapes:
    def test_accepts_item_dict(self):
        name_map.update({"items": [_skill("t", "c", "显示名")]})
        assert name_map.get_name("t", "c") == "显示名"

    def test_accepts_bare_list(self):
        """两个调用方历史上给的形状不一样（一个 dict、一个 list），都得认。"""
        name_map.update([_skill("t", "c", "显示名")])
        assert name_map.get_name("t", "c") == "显示名"

    def test_tolerates_junk_entries(self):
        assert name_map.update([None, "x", {}, {"trunk": "t"}]) is None
        assert name_map.get() == {}

    def test_get_name_missing(self):
        assert name_map.get_name("nope", "nope") is None


class TestUpdateVsReplace:
    def test_update_keeps_other_entries(self):
        name_map.update([_skill("a", "1", "甲")])
        name_map.update([_skill("b", "2", "乙")])
        assert len(name_map.get()) == 2

    def test_replace_drops_stale_entries(self):
        """改名后的核心诉求：旧的 (trunk, category) 键必须消失。

        这里正是原先 inject_preview 那份的病灶——它只做增量、从不 clear，
        旧键会在进程内存里一直留着。
        """
        name_map.replace([_skill("a", "old-cat", "旧名")])
        assert name_map.get_name("a", "old-cat") == "旧名"

        name_map.replace([_skill("a", "new-cat", "新名")])
        assert name_map.get_name("a", "new-cat") == "新名"
        assert name_map.get_name("a", "old-cat") is None, "旧键必须随 replace 消失"
        assert len(name_map.get()) == 1


class TestInvalidate:
    def test_invalidate_clears(self):
        name_map.update([_skill("a", "1", "甲")])
        name_map.invalidate()
        assert name_map.get() == {}

    def test_single_source_shared_by_both_consumers(self):
        """合并的目的：一次失效，两边同时生效。

        原先 skill_organize 的 `_name_map` 与 inject_preview 的 `_name_map_cache`
        是两个互不相干的 dict，失效函数够不着后者。
        """
        first = name_map.get()
        name_map.update([_skill("a", "1", "甲")])
        second = name_map.get()
        assert first is second, "get() 必须始终返回同一个 dict，否则又成了两份"
        name_map.invalidate()
        assert not first


class TestNoDuplicateCache:
    def test_no_second_name_map_cache(self):
        """收口契约：app/gui 下不许再出现第二份 name_map 缓存。"""
        offenders: list[str] = []
        for py in sorted((ROOT / "app" / "gui").rglob("*.py")):
            if py.name == "_name_map.py" or "__pycache__" in py.parts:
                continue
            for i, line in enumerate(
                    py.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if "_name_map_cache" in line or "_name_map_cached" in line:
                    offenders.append(f"{py.relative_to(ROOT)}:{i}")
        assert not offenders, (
            "发现第二份 name_map 缓存，改用 app/gui/_name_map.py: "
            + ", ".join(offenders))

    def test_invalidators_call_shared_module(self):
        """失效调用方必须从共享模块取 reset，而不是某个页面的私有函数。"""
        for mod in ("qt_dialogs.py", "methods.py"):
            text = (ROOT / "app" / "gui" / mod).read_text(encoding="utf-8")
            if "skill_organize import invalidate_name_map" in text:
                pytest.fail(
                    f"{mod} 仍从 skill_organize 取失效函数，"
                    "那只作废了其中一份，应改 from ._name_map import invalidate")
