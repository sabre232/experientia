"""(trunk, category) → 方法显示名的**进程内唯一缓存**（去重 R2）。

为什么要有这个文件
------------------
原先有两份同名不同命的模块级缓存：

- `skill_organize` 版：带失效入口 `invalidate_name_map()`，且 `_apply_name_map`
  会先 clear 再全量重建；
- `inject_preview` 版：`_update_name_map` **只做增量赋值、从不 clear**，
  而且**没有失效入口**。

`qt_dialogs.skill_save` 与 `methods.skill_rename` 都只调了前者的失效函数。
结果：方法新建或改名后，注入预览页的类别下拉仍顶着旧条目，在进程存续期间
永远不会更新（旧的 (trunk, category) key 也没被清掉）。

两份合成一份后，失效一处、两边同时生效。

API
---
- `get()` / `get_name(trunk, category)`：读
- `update(items)`：增量补（不清）
- `replace(skills)`：全量重建（先清后填，改名后必须走这个）
- `invalidate()`：作废

输入结构兼容两种（历史上两个调用方给的就不是一个形状）：
既接受 `{"items": [...]}` 这种 money dict，也接受裸 list —— 归一化在内部做，
不让调用方再记得"我这边的 skills 到底是 dict 还是 list"。
"""

from __future__ import annotations

_name_map: dict[tuple[str, str], str] = {}

__all__ = ["get", "get_name", "update", "replace", "invalidate"]


def _iter_items(skills):
    """把 dict{"items": [...]} 与裸 list 归一成条目迭代器。"""
    if isinstance(skills, dict):
        skills = skills.get("items")
    return skills or []


def get() -> dict[tuple[str, str], str]:
    """取当前映射本体。

    返回的是内部 dict **引用**（调用方只读即可，要改请用 update/replace）；
    界面侧持有它可以在渲染时零拷贝地查名。
    """
    return _name_map


def get_name(trunk, category) -> str | None:
    """查显示名；没有就 None（调用方自行回落到原始 category 文本）。"""
    return _name_map.get((trunk, category))


def update(skills) -> None:
    """增量填充：只补新条目，不清旧条目。"""
    for s in _iter_items(skills):
        if not isinstance(s, dict):
            continue
        if s.get("name") and s.get("trunk") is not None \
                and s.get("category") is not None:
            _name_map[(s["trunk"], s["category"])] = s["name"]


def replace(skills) -> None:
    """全量重建：先清后填。

    方法改名后会多出新的 (trunk, category) 键、旧键作废——只 update 不清会
    留下陈旧条目（这正是原先 inject_preview 那份的病灶）。
    """
    _name_map.clear()
    update(skills)


def invalidate() -> None:
    """作废缓存。方法新建（skill_save）/ 改名（skill_rename）后由操作方调用。"""
    _name_map.clear()
