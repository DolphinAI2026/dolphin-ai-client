from __future__ import annotations

from unittest.mock import patch

import pytest

from app.apaas_client import APaaSClient


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"code": "ok", "table": [{"id": "1"}], "total": 1}


class _FakeHttp:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, headers=None, params=None, json=None):
        self.calls.append({"url": url, "headers": headers, "params": params, "json": json})
        return _FakeResponse()


@pytest.mark.asyncio
async def test_query_operate_logs_calls_tenant_operate_log_endpoint():
    fake = _FakeHttp()
    client = APaaSClient(
        base_url="https://apaas.example/backend",
        tenant_id="tenant-1",
        token="tok-1",
    )

    with patch("app.apaas_client.httpx.AsyncClient", lambda *args, **kwargs: fake):
        resp = await client.query_operate_logs(
            page=2,
            page_size=20,
            filters={"operationType": "EDIT", "functionMenu": "SELF_DEVELOPMENT_MANAGEMENT"},
        )

    assert resp["total"] == 1
    assert fake.calls[0]["url"] == "https://apaas.example/backend/xdap-app/operateLog/query/operateLogs"
    assert fake.calls[0]["headers"]["xdaptenantid"] == "tenant-1"
    assert fake.calls[0]["headers"]["xdaptoken"] == "tok-1"
    assert fake.calls[0]["params"] is None
    assert fake.calls[0]["json"] == {
        "page": 2,
        "pageSize": 20,
        "order": "DESC",
        "operationUsers": [],
        "functionMenu": "SELF_DEVELOPMENT_MANAGEMENT",
        "operationType": "EDIT",
        "operationObject": "",
    }
