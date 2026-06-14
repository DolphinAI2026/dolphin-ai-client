"""operations/permissions.py 特征测试 —— Phase 3 执行器收敛安全网。

锁住收口后 _parse_permission_ops 的 canonical 行为:
- str 输入: 与两侧旧实现逐字等价(收口零行为变化)。
- list/tuple/set 输入: 取 step_executor 超集行为(修旧 generator_v2 对非 str 丢 ops 的 bug)。
两条 0-1 生成路径(generator_v2 一把梭 / step_executor 分步)现共享此实现。
"""
from __future__ import annotations

from app.operations.permissions import _parse_permission_ops


def test_str_comma_split_strip():
    """str 逗号串: 拆分/去空白/丢空 —— 两侧旧实现都这样,收口等价。"""
    assert _parse_permission_ops("add, edit ,del") == {"add", "edit", "del"}
    assert _parse_permission_ops("view") == {"view"}
    assert _parse_permission_ops("a,,b, ") == {"a", "b"}


def test_str_no_comma_single_op():
    assert _parse_permission_ops("all") == {"all"}


def test_list_tuple_set_preserved():
    """list/tuple/set: 保留真实 ops(旧 generator_v2 会错误返回 {'all'})。"""
    assert _parse_permission_ops(["add", "edit"]) == {"add", "edit"}
    assert _parse_permission_ops(("view",)) == {"view"}
    assert _parse_permission_ops({"del", "add"}) == {"del", "add"}


def test_non_iterable_fallback_all():
    assert _parse_permission_ops(None) == {"all"}
    assert _parse_permission_ops(123) == {"all"}


def test_both_engines_import_same_object():
    """两条生成路径 import 的是同一个对象(真收口,非各自副本)。"""
    from app import generator_v2, step_executor
    assert generator_v2._parse_permission_ops is _parse_permission_ops
    assert step_executor._parse_permission_ops is _parse_permission_ops
