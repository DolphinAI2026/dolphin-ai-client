"""describe_exception：空 message 的异常(超时类常见)不再被吞成空串。

根因：BaseAgent 失败时 _publish("failed", {"error": str(e)})，超时类异常 str(e) 为空，
经 adapter 回退成无信息量的「unknown error」。改用 describe_exception：空则退回异常类型名。
"""
from __future__ import annotations

import asyncio

from app.agents.base import describe_exception


def test_uses_message_when_present():
    assert describe_exception(ValueError("boom")) == "boom"


def test_falls_back_to_type_name_when_empty():
    # 无参异常 str() 为空 → 退回类型名，而不是空串
    assert describe_exception(TimeoutError()) == "TimeoutError"


def test_whitespace_only_message_falls_back_to_type_name():
    assert describe_exception(RuntimeError("   ")) == "RuntimeError"


def test_asyncio_timeout_describes_as_type_name():
    # 用户现场命中的就是这类：32s 后超时、str() 为空
    assert describe_exception(asyncio.TimeoutError()) == "TimeoutError"


def test_never_returns_empty():
    for e in (Exception(), TimeoutError(), RuntimeError(""), OSError()):
        assert describe_exception(e).strip() != ""
