import httpx
import json
import pytest

from app import llm_transport


class _EmptyJsonResponseClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **_kwargs):
        return httpx.Response(
            200,
            content=b"",
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", "https://model.example/v1/chat/completions"),
        )


@pytest.mark.asyncio
async def test_complete_reports_empty_success_body_as_gateway_error(monkeypatch):
    monkeypatch.setattr(llm_transport.httpx, "AsyncClient", lambda **_kwargs: _EmptyJsonResponseClient())

    with pytest.raises(RuntimeError, match="HTTP 200.*响应体为空"):
        await llm_transport.complete(
            base_url="https://model.example/v1",
            api_key="test-key",
            payload={"model": "test", "messages": []},
            timeout=10,
            retry_attempts=1,
        )


@pytest.mark.asyncio
async def test_empty_response_writes_redacted_diagnostic_request_record(monkeypatch, tmp_path):
    monkeypatch.setenv("DESKTOP_MODE", "1")
    monkeypatch.setenv("SIDECAR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(llm_transport.httpx, "AsyncClient", lambda **_kwargs: _EmptyJsonResponseClient())

    with pytest.raises(RuntimeError):
        await llm_transport.complete(
            base_url="https://model.example/v1",
            api_key="api-key-must-not-be-logged",
            payload={
                "model": "test",
                "messages": [{
                    "role": "user",
                    "content": "retry this; Authorization: Bearer top-secret-value",
                }],
                "tools": [{"function": {"name": "save", "arguments": "token: another-secret"}}],
            },
            timeout=10,
            retry_attempts=1,
        )

    records = [json.loads(line) for line in (tmp_path / "logs" / "llm-diagnostics.jsonl").read_text().splitlines()]
    record = records[-1]
    serialized = json.dumps(record, ensure_ascii=False)
    assert record["event"] == "llm_request_failed"
    assert record["transport"] == "chat_completions"
    assert record["response"]["status_code"] == 200
    assert record["response"]["body_chars"] == 0
    assert "top-secret-value" not in serialized
    assert "another-secret" not in serialized
    assert "api-key-must-not-be-logged" not in serialized
    assert "<redacted>" in serialized
