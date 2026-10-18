"""extract_json 截断修复护栏（治本地小模型 max_tokens 砍断 JSON）。

核心安全约束：只保留截断点前**完整**的元素，半截对象绝不收（防污染经验库）。
"""
import pytest

from app.distill import llm


def test_complete_array_unchanged():
    out = '[{"task":"a","importance":8},{"task":"b","importance":6}]'
    assert llm.extract_json(out) == [{"task": "a", "importance": 8},
                                     {"task": "b", "importance": 6}]


def test_fence_and_prose_still_work():
    out = '好的，以下是经验：\n```json\n[{"task":"x","importance":7}]\n```'
    assert llm.extract_json(out) == [{"task": "x", "importance": 7}]


def test_truncated_array_recovers_complete_elements():
    # 第三个对象被 max_tokens 砍在半路（"Unterminated string" 的真实形态）
    out = ('[{"task":"a","action":"do-a","importance":9},'
           '{"task":"b","action":"do-b","importance":8},'
           '{"task":"c","action":"this got cut off mid stri')
    got = llm.extract_json(out)
    assert isinstance(got, list) and len(got) == 2
    assert [g["task"] for g in got] == ["a", "b"]


def test_truncated_with_trailing_comma_and_bracket():
    out = '[{"task":"a","importance":8},{"task":"b","importance":7},'
    got = llm.extract_json(out)
    assert len(got) == 2


def test_nested_braces_inside_string_not_broken():
    # 字符串值里含 {} [ ] 与转义引号，切点判定不能被带偏
    out = '[{"task":"含 { 和 ] 和 括号","importance":9},{"task":"x","importance":5'
    got = llm.extract_json(out)
    assert got == [{"task": "含 { 和 ] 和 括号", "importance": 9}]


def test_no_complete_element_raises_not_empty_list():
    # 第一个对象就没写完 → 无完整元素可救，必须抛（不得静默返回 []）
    with pytest.raises(ValueError):
        llm.extract_json('[{"task":"only a partial, never closed')


def test_empty_output_raises():
    with pytest.raises(ValueError):
        llm.extract_json("   ")


def test_no_json_raises():
    with pytest.raises(ValueError):
        llm.extract_json("模型啥也没说，纯自然语言，没数组")
