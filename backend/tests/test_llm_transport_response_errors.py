import httpx
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
