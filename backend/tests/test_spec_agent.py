"""Tests for SpecAgent — drives a mocked LLM tool loop and asserts spec mutations."""

from __future__ import annotations
import json
import pytest
from unittest.mock import patch

from app.spec.agent import SpecAgent
from app.spec.persistence import empty_spec
from app.spec.schema import Phase


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


@pytest.mark.asyncio
async def test_bootstrap_from_doc_silent_produces_ready_spec():
    """Silent bootstrap: complete doc → fully populated SPEC, all confirmed=true, phase=ready."""
    spec = empty_spec(created_by=1)
    doc_text = """# 预算管理系统

## 角色
- 财务负责人 (finance_lead): 全部数据
- 销售总监 (sales_director): 本部门数据

## 数据对象
### 季度预测 (t_quarter_forecast)
- 预测编号 (forecast_no): 单据号 必填
- 金额 (amount): 数字 必填
- 状态 (status): 下拉单选 → forecast_status

## 字典
- 预测状态 (forecast_status): 草稿/已确认/已审批

## 权限
- t_quarter_forecast: finance_lead 全操作 ALL；sales_director 编辑 DEPT
"""

    # LLM responds with a single shot: 1 set_goal + 2 add_role + 1 add_object (with fields) +
    # 1 add_dict + 1 add_permission + 5 confirm_* + 1 transition_phase("ready")
    turn1_chunks = [
        _tool_call_chunk(0, "c0", "set_goal", json.dumps({
            "title": "预算管理系统", "summary": "季度预测", "business_problem": "对齐财务"
        })),
        _tool_call_chunk(1, "c1", "add_role", json.dumps({
            "code": "finance_lead", "name": "财务负责人", "scope": "ALL",
        })),
        _tool_call_chunk(2, "c2", "add_role", json.dumps({
            "code": "sales_director", "name": "销售总监", "scope": "DEPT",
        })),
        _tool_call_chunk(3, "c3", "add_object", json.dumps({
            "code": "t_quarter_forecast", "name": "季度预测",
            "fields": [
                {"code": "forecast_no", "name": "预测编号", "type": "单据号", "required": True},
                {"code": "amount", "name": "金额", "type": "数字", "required": True},
                {"code": "status", "name": "状态", "type": "下拉单选", "dict_code": "forecast_status"},
            ],
        })),
        _tool_call_chunk(4, "c4", "add_dict", json.dumps({
            "code": "forecast_status", "name": "预测状态",
            "options": [
                {"code": "draft", "name": "草稿"},
                {"code": "confirmed", "name": "已确认"},
                {"code": "approved", "name": "已审批"},
            ],
        })),
        _tool_call_chunk(5, "c5", "add_permission", json.dumps({
            "object_code": "t_quarter_forecast",
            "rules": [
                {"role": "finance_lead", "op": "all", "data": "ALL"},
                {"role": "sales_director", "op": "edit", "data": "DEPT"},
            ],
        })),
    ]
    # Second turn: confirm everything + transition_phase
    turn2_chunks = [
        _tool_call_chunk(0, "c9", "confirm_goal", json.dumps({})),
        _tool_call_chunk(1, "c10", "confirm_role", json.dumps({"code": "finance_lead"})),
        _tool_call_chunk(2, "c11", "confirm_role", json.dumps({"code": "sales_director"})),
        _tool_call_chunk(3, "c12", "confirm_object", json.dumps({"code": "t_quarter_forecast"})),
        _tool_call_chunk(4, "c13", "confirm_dict", json.dumps({"code": "forecast_status"})),
        _tool_call_chunk(5, "c14", "confirm_permission", json.dumps({"object_code": "t_quarter_forecast"})),
        _tool_call_chunk(6, "c15", "transition_phase", json.dumps({"target": "ready", "reason": "doc bootstrap"})),
    ]
    turn3_chunks = [_content_chunk("已完成"), _empty_finish_chunk()]

    agent = SpecAgent(llm_base_url="http://fake", llm_api_key="fake", llm_model="fake-model")
    fake = _make_open_stream_mock([
        FakeLLMStream(turn1_chunks),
        FakeLLMStream(turn2_chunks),
        FakeLLMStream(turn3_chunks),
    ])
    with patch("app.spec.agent._open_stream", side_effect=fake):
        events = []
        async for ev in agent.bootstrap_from_doc(spec, doc_text=doc_text, silent=True):
            events.append(ev)

    final = next(e.spec for e in reversed(events) if e.kind == "final")
    assert final.phase == Phase.READY
    assert final.goal is not None and final.goal.confirmed is True
    assert len(final.roles) == 2 and all(r.confirmed for r in final.roles)
    assert len(final.objects) == 1 and final.objects[0].confirmed
    assert len(final.dicts) == 1 and final.dicts[0].confirmed
    assert len(final.permissions) == 1 and final.permissions[0].confirmed
