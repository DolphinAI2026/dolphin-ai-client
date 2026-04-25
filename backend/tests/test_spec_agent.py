"""Tests for SpecAgent — drives a mocked LLM tool loop and asserts spec mutations."""

from __future__ import annotations
import json
import pytest
from unittest.mock import patch

from app.spec.agent import SpecAgent
from app.spec.persistence import empty_spec


class FakeLLMStream:
    """Async-iterable that yields pre-recorded SSE lines.

    Mirrors what httpx's `stream.aiter_lines()` returns to the agent's
    `async for line in stream:` loop. We define `__aiter__` as an async
    generator method so `async for` finds an async iterator with __anext__.
    """

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks

    async def __aiter__(self):
        for c in self.chunks:
            yield "data: " + json.dumps(c)
        yield "data: [DONE]"


def _tool_call_chunk(idx: int, call_id: str, name: str, args_json: str) -> dict:
    return {"choices": [{"delta": {"tool_calls": [{
        "index": idx, "id": call_id,
        "function": {"name": name, "arguments": args_json},
    }]}}]}


def _content_chunk(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}}]}


def _empty_finish_chunk() -> dict:
    return {"choices": [{"delta": {}}]}


def _make_open_stream_mock(streams_per_turn: list[FakeLLMStream]):
    """Returns a sync function suitable for `patch(..., side_effect=...)`.

    Each call returns the next FakeLLMStream. Since `_open_stream` is an
    async-generator factory in production, the agent code does
    `stream = _open_stream(...)` (no await) then `async for ...`. A sync
    side_effect returning an async-iterable matches that contract.
    """
    iterator = iter(streams_per_turn)

    def _fake(*args, **kwargs):
        return next(iterator)

    return _fake


@pytest.mark.asyncio
async def test_agent_runs_clarifying_questions_first_turn():
    """LLM emits 3 ask_clarifying_question tool_calls in turn 1, then a final
    assistant message with no tool_calls in turn 2. Agent should append all 3
    decisions to the spec and yield a final event."""
    spec = empty_spec(created_by=1)

    turn1_chunks = [
        _tool_call_chunk(0, "call_a", "ask_clarifying_question",
                         json.dumps({"topic": "周期颗粒度", "blocking": True})),
        _tool_call_chunk(1, "call_b", "ask_clarifying_question",
                         json.dumps({"topic": "数据来源", "blocking": True})),
        _tool_call_chunk(2, "call_c", "ask_clarifying_question",
                         json.dumps({"topic": "口径", "blocking": False})),
    ]
    turn2_chunks = [_content_chunk("好的，请回答上述 3 个问题。"), _empty_finish_chunk()]

    agent = SpecAgent(
        llm_base_url="http://fake", llm_api_key="fake", llm_model="fake-model",
    )

    fake = _make_open_stream_mock([
        FakeLLMStream(turn1_chunks),
        FakeLLMStream(turn2_chunks),
    ])
    with patch("app.spec.agent._open_stream", side_effect=fake):
        events = []
        async for ev in agent.run(spec, user_message="我想做预算管理系统"):
            events.append(ev)

    final_spec = next(e.spec for e in reversed(events) if e.kind == "final")
    assert len(final_spec.decisions_pending) == 3
    assert final_spec.decisions_pending[0].topic == "周期颗粒度"
    # Final event present
    assert events[-1].kind == "final"


@pytest.mark.asyncio
async def test_agent_rejects_set_goal_in_first_turn_with_zero_completeness():
    """LLM tries to call set_goal in gathering first turn → tool returns error,
    agent feeds error back; we verify the spec is unchanged (no goal set) and a
    tool_error event surfaced."""
    spec = empty_spec(created_by=1)
    turn1_chunks = [
        _tool_call_chunk(0, "call_x", "set_goal",
                         json.dumps({"title": "预算", "summary": "x", "business_problem": "y"})),
    ]
    turn2_chunks = [_content_chunk("好的，先问几个问题。"), _empty_finish_chunk()]

    agent = SpecAgent(
        llm_base_url="http://fake", llm_api_key="fake", llm_model="fake-model",
    )
    fake = _make_open_stream_mock([
        FakeLLMStream(turn1_chunks),
        FakeLLMStream(turn2_chunks),
    ])
    with patch("app.spec.agent._open_stream", side_effect=fake):
        events = []
        async for ev in agent.run(spec, user_message="我想做预算管理系统"):
            events.append(ev)

    final_spec = next(e.spec for e in reversed(events) if e.kind == "final")
    assert final_spec.goal is None  # set_goal was rejected
    # Tool error surfaced; the error message references ask_clarifying_question
    assert any(
        e.kind == "tool_error" and "ask_clarifying_question" in (e.message or "")
        for e in events
    )
