import asyncio

import httpx
import pytest

from app.ai_chat import agent


@pytest.mark.asyncio
async def test_stream_gateway_5xx_falls_back_to_regular_completion(monkeypatch):
    cfg = agent.LLMConfigSnapshot(
        base_url="https://model.example/v1",
        api_key="test-key",
        model="test-model",
        max_tokens=100,
        temperature=0.3,
    )

    async def fail_stream(*_args, **_kwargs):
        response = httpx.Response(
            502,
            request=httpx.Request("POST", "https://model.example/v1/chat/completions"),
        )
        raise httpx.HTTPStatusError("bad gateway", request=response.request, response=response)
        yield  # pragma: no cover - keeps this an async generator

    completion_calls = []

    async def regular_completion(*_args, **kwargs):
        completion_calls.append(kwargs)
        return {"content": "fallback answer", "tool_calls": None}

    monkeypatch.setattr(agent, "_call_llm_stream", fail_stream)
    monkeypatch.setattr(agent, "_call_llm", regular_completion)

    events = [
        event async for event in agent._call_llm_stream_with_fallback(
            cfg, [{"role": "user", "content": "hello"}], [], asyncio.Event(),
        )
    ]

    assert events == [
        {"type": "content_delta", "text": "fallback answer"},
        {
            "type": "done",
            "message": {"content": "fallback answer", "tool_calls": None},
            "usage": None,
        },
    ]
    assert completion_calls == [{"timeout": 180, "omit_generation_controls": True}]


@pytest.mark.asyncio
async def test_empty_non_stream_fallback_retries_without_explicit_tool_choice(monkeypatch):
    cfg = agent.LLMConfigSnapshot(
        base_url="https://model.example/v1",
        api_key="test-key",
        model="test-model",
        max_tokens=100,
        temperature=0.3,
    )

    async def fail_stream(*_args, **_kwargs):
        response = httpx.Response(
            502,
            request=httpx.Request("POST", "https://model.example/v1/chat/completions"),
        )
        raise httpx.HTTPStatusError("bad gateway", request=response.request, response=response)
        yield  # pragma: no cover - keeps this an async generator

    completion_calls = []

    async def regular_completion(*_args, **kwargs):
        completion_calls.append(kwargs)
        if len(completion_calls) == 1:
            raise agent.llm_transport.LLMEmptyResponseError("HTTP 200 empty")
        return {"content": "recovered", "tool_calls": None}

    monkeypatch.setattr(agent, "_call_llm_stream", fail_stream)
    monkeypatch.setattr(agent, "_call_llm", regular_completion)

    events = [
        event async for event in agent._call_llm_stream_with_fallback(
            cfg,
            [{"role": "user", "content": "disable the seed"}],
            [{"type": "function", "function": {"name": "change_system_asset_status"}}],
            asyncio.Event(),
        )
    ]

    assert events[-1] == {
        "type": "done",
        "message": {"content": "recovered", "tool_calls": None},
        "usage": None,
    }
    assert completion_calls == [
        {"timeout": 180, "omit_generation_controls": True},
        {
            "timeout": 180,
            "omit_generation_controls": True,
            "omit_tool_choice": True,
        },
    ]
