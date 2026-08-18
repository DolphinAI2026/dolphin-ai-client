import httpx
import pytest

from app import llm_transport


class _SequenceClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **_kwargs):
        return self.response


@pytest.mark.asyncio
async def test_complete_retries_empty_200_body_before_accepting_valid_response(monkeypatch):
    request = httpx.Request("POST", "https://model.example/v1/chat/completions")
    responses = iter([
        httpx.Response(200, content=b"", request=request),
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": "recovered"}}]},
            request=request,
        ),
    ])
    monkeypatch.setattr(
        llm_transport.httpx,
        "AsyncClient",
        lambda **_kwargs: _SequenceClient(next(responses)),
    )

    async def no_sleep(_attempt):
        return None

    monkeypatch.setattr(llm_transport, "sleep_before_retry", no_sleep)

    result = await llm_transport.complete(
        base_url="https://model.example/v1",
        api_key="test-key",
        payload={"model": "test", "messages": []},
        timeout=10,
        retry_attempts=3,
    )

    assert result == {"content": "recovered"}
