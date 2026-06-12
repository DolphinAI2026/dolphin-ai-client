import httpx
import pytest

from app import llm_transport


def test_write_timeout_is_retryable_and_user_facing():
    exc = httpx.WriteTimeout("write timeout")

    assert llm_transport.is_retryable_llm_error(exc) is True
    assert llm_transport.format_llm_error(exc) == "向模型网关发送请求超时，请稍后重试。"


@pytest.mark.asyncio
async def test_complete_retries_write_timeout_before_success(monkeypatch):
    calls = 0

    async def no_sleep(_attempt: int) -> None:
        return None

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.WriteTimeout("write timeout")
            return FakeResponse()

    monkeypatch.setattr(llm_transport, "sleep_before_retry", no_sleep)
    monkeypatch.setattr(llm_transport.httpx, "AsyncClient", lambda *a, **k: FakeClient())

    message = await llm_transport.complete(
        base_url="https://llm.example.test/v1",
        api_key="test-key",
        payload={"model": "test", "messages": []},
        timeout=httpx.Timeout(10),
        retry_attempts=2,
    )

    assert calls == 2
    assert message == {"content": "ok"}
