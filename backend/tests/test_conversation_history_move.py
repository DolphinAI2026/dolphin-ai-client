"""共享 helper get_conversation_history 迁出 pipeline.py — Phase 1' Task 2。

退役 coding 流水线前,把 read_query 仍要用的 helper 搬到中立模块,
pipeline 仅 re-export(零破坏)。
"""
from __future__ import annotations


def test_get_conversation_history_importable_from_new_module():
    from app.coding.conversation_history import get_conversation_history
    assert callable(get_conversation_history)


def test_pipeline_still_reexports_same_object():
    # pipeline 内部 3 处 + 老的 `from app.coding.pipeline import get_conversation_history`
    # 都不能破:re-export 必须是同一个对象(不是各写一份导致分叉)。
    from app.coding.pipeline import get_conversation_history as from_pipeline
    from app.coding.conversation_history import get_conversation_history as from_new
    assert from_pipeline is from_new


def test_read_query_imports_from_neutral_module():
    # read_query 退役 pipeline 后不能再依赖 pipeline 提供这个 helper。
    import inspect
    import app.coding.read_query as rq
    src = inspect.getsource(rq)
    assert "from app.coding.conversation_history import get_conversation_history" in src
    assert "from app.coding.pipeline import get_conversation_history" not in src
