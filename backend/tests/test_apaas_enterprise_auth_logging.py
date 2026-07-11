import logging

import pytest

from app import apaas_client


@pytest.mark.asyncio
async def test_enterprise_apaas_login_uses_tls_and_does_not_record_token(
    monkeypatch,
    caplog,
):
    client_kwargs = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": "ok",
                "data": {
                    "token": "enterprise-token-secret",
                    "user": {"id": "user-1"},
                },
            }

    class FakeClient:
        def __init__(self, **kwargs):
            client_kwargs.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    apaas_client.flush_call_logs()
    monkeypatch.setattr(apaas_client.httpx, "AsyncClient", FakeClient)
    client = apaas_client.APaaSClient(
        "https://apaas.example.com",
        "tenant-1",
        verify_tls=True,
        record_call_logs=False,
    )
    monkeypatch.setattr(
        client,
        "_encrypt_password",
        lambda _password, _public_key: "encrypted-password",
    )

    with caplog.at_level(logging.DEBUG, logger="app.apaas_client"):
        result = await client.login("builder", "password-secret")

    assert result["token"] == "enterprise-token-secret"
    assert client_kwargs == [{"verify": True, "timeout": 45.0}]
    assert apaas_client.flush_call_logs() == []
    assert "enterprise-token-secret" not in caplog.text
