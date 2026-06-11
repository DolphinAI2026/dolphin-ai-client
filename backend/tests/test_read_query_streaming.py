"""read_query 流式调用 — OpenAI chunk 合并与 _stream_llm 单测。"""
import json

import httpx
import pytest

from app.coding.read_query import _stream_llm, merge_stream_tool_call_delta


def test_merge_tool_call_delta_accumulates_by_index():
    acc: list[dict] = []
    merge_stream_tool_call_delta(acc, [
        {"index": 0, "id": "call_1", "function": {"name": "read_", "arguments": '{"fi'}},
    ])
    merge_stream_tool_call_delta(acc, [
        {"index": 0, "function": {"name": "workspace_file", "arguments": 'le_path": "a.js"}'}},
    ])
    merge_stream_tool_call_delta(acc, [
        {"index": 1, "id": "call_2", "function": {"name": "search_workspace_code", "arguments": "{}"}},
    ])
    assert acc[0]["id"] == "call_1"
    assert acc[0]["function"]["name"] == "read_workspace_file"
    assert json.loads(acc[0]["function"]["arguments"]) == {"file_path": "a.js"}
    assert acc[1]["id"] == "call_2"
    assert acc[1]["function"]["name"] == "search_workspace_code"


def test_merge_tool_call_delta_tolerates_bad_index():
    acc: list[dict] = []
    merge_stream_tool_call_delta(acc, [{"index": None, "function": {"name": "f"}}])
    assert acc[0]["function"]["name"] == "f"


@pytest.mark.asyncio
async def test_stream_llm_yields_content_and_collects_tool_calls(monkeypatch):
    sse = b"".join([
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"f","arguments":"{}"}}]}}]}\n\n',
        b"data: [DONE]\n\n",
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    orig_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: orig_client(transport=transport, **kw),
    )

    sink: dict = {}
    pieces = [p async for p in _stream_llm("http://gw/v1", "key", {"model": "m", "messages": []}, sink)]
    assert pieces == ["Hel", "lo"]
    assert sink["content"] == "Hello"
    assert sink["tool_calls"][0]["function"]["name"] == "f"
