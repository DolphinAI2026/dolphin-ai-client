"""_call_llm_stream 把 usage chunk 的 token 透到 done 事件。"""
from __future__ import annotations

import asyncio
import json
import types

import pytest

import app.ai_chat.agent as agent_mod


class _FakeStreamResp:
    """假 httpx 流式 response：模拟 OpenAI include_usage 的 chunk 序列。"""

    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln

    async def aread(self):
        return b""

    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, lines):
        self._lines = lines
        self.sent_payload = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, headers=None, json=None):
        self.sent_payload = json
        return _FakeStreamResp(self._lines)


@pytest.mark.asyncio
async def test_stream_captures_usage_into_done(monkeypatch):
    # content chunk → usage chunk（choices 空）→ [DONE]
    lines = [
        'data: ' + json.dumps({"choices": [{"delta": {"content": "你好"}}]}),
        'data: ' + json.dumps({"choices": [], "usage": {"prompt_tokens": 111, "completion_tokens": 22, "total_tokens": 133}}),
        'data: [DONE]',
    ]
    captured = {}

    def _fake_async_client(*a, **kw):
        c = _FakeClient(lines)
        captured["client"] = c
        return c

    monkeypatch.setattr(agent_mod.httpx, "AsyncClient", _fake_async_client)

    cfg = types.SimpleNamespace(
        model="gpt-5.5", temperature=0.2, max_tokens=2048,
        base_url="http://llm", api_key="k",
    )
    # _apply_provider_payload_compat 读 cfg 的若干属性，给个 no-op 替身省事
    monkeypatch.setattr(agent_mod, "_apply_provider_payload_compat", lambda c, p: None)

    abort = asyncio.Event()
    events = []
    async for ev in agent_mod._call_llm_stream(cfg, [{"role": "user", "content": "hi"}], [], abort):
        events.append(ev)

    # payload 里带了 include_usage
    assert captured["client"].sent_payload["stream_options"] == {"include_usage": True}

    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1
    assert done[0]["usage"] == {"prompt_tokens": 111, "completion_tokens": 22, "total_tokens": 133}
    assert done[0]["message"]["content"] == "你好"
