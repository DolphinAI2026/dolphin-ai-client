import httpx
import json
import pytest

from app.ai_chat import agent


class _EmptyResponsesClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **_kwargs):
        return httpx.Response(
            200,
            content=b"",
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", "https://model.example/v1/responses"),
        )


@pytest.mark.asyncio
async def test_chat_completion_omits_empty_tools_and_tool_choice(monkeypatch):
    cfg = agent.LLMConfigSnapshot(
        base_url="https://model.example/v1",
        api_key="test-key",
        model="test-model",
        max_tokens=128000,
        temperature=0.7,
    )
    captured = {}

    async def fake_complete(**kwargs):
        captured.update(kwargs)
        return {"content": "ok"}

    monkeypatch.setattr(agent.llm_transport, "complete", fake_complete)

    await agent._call_llm(cfg, [{"role": "user", "content": "hello"}], [])

    assert captured["payload"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.7,
        "max_tokens": 128000,
    }


@pytest.mark.asyncio
async def test_minimal_tool_fallback_keeps_tools_but_omits_tool_choice(monkeypatch):
    cfg = agent.LLMConfigSnapshot(
        base_url="https://model.example/v1",
        api_key="test-key",
        model="test-model",
        max_tokens=128000,
        temperature=0.7,
    )
    captured = {}
    tools = [{"type": "function", "function": {"name": "change_system_asset_status"}}]

    async def fake_complete(**kwargs):
        captured.update(kwargs)
        return {"content": "ok"}

    monkeypatch.setattr(agent.llm_transport, "complete", fake_complete)

    await agent._call_llm(
        cfg,
        [{"role": "user", "content": "disable the seed"}],
        tools,
        omit_generation_controls=True,
        omit_tool_choice=True,
    )

    assert captured["payload"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "disable the seed"}],
        "tools": tools,
    }


@pytest.mark.asyncio
async def test_responses_empty_body_is_logged_with_a_redacted_request(monkeypatch, tmp_path):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("SIDECAR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **_kwargs: _EmptyResponsesClient())
    cfg = agent.LLMConfigSnapshot(
        base_url="https://model.example/v1",
        api_key="must-not-appear",
        model="test-model",
        max_tokens=64,
        temperature=0.2,
        api_format="responses",
    )

    with pytest.raises(agent.llm_transport.LLMEmptyResponseError, match="响应体为空"):
        await agent._complete_responses(
            cfg,
            {"messages": [{"role": "user", "content": "Bearer response-secret"}]},
            timeout=10,
        )

    record = json.loads((tmp_path / "logs" / "llm-diagnostics.jsonl").read_text().splitlines()[-1])
    serialized = json.dumps(record, ensure_ascii=False)
    assert record["transport"] == "responses"
    assert record["response"]["status_code"] == 200
    assert "response-secret" not in serialized
    assert "must-not-appear" not in serialized
