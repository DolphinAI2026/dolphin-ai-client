from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.models.ai_chat import AIChatSession


CAPACITY_ERROR_HEADER = "X-APAAS-Sandbox-Auth-Error"
CAPACITY_ERROR_CODE = "sandbox_session_capacity_exceeded"


def _capacity_client() -> httpx.AsyncClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            headers={CAPACITY_ERROR_HEADER: CAPACITY_ERROR_CODE},
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_bootstrap_runtime_session_normalizes_capacity_exhaustion_to_503():
    from app.code_runtime.sandbox_auth import bootstrap_runtime_session

    with pytest.raises(HTTPException) as exc_info:
        await bootstrap_runtime_session(
            "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-secret",
            client_factory=_capacity_client,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {CAPACITY_ERROR_HEADER: CAPACITY_ERROR_CODE}
    assert "entry-secret" not in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_open_code_session_propagates_runtime_session_capacity_exhaustion(
    db_session,
    monkeypatch,
):
    from app.code_runtime import service
    from app.code_runtime.sandbox_auth import bootstrap_runtime_session
    from app.code_runtime.service import open_code_session

    session = AIChatSession(
        tenant_id=7,
        user_id=11,
        external_application_id="code-app-1",
        title="客户门户 Code",
        mode="code",
        status="active",
    )
    db_session.add(session)
    await db_session.commit()
    opens = 0

    async def fake_open(_external_application_id: str, _handoff_id: str | None = None):
        nonlocal opens
        opens += 1
        return {
            "workspaceId": "ws-1",
            "specReviewUrl": (
                "https://sandbox.example.com/workspaces/ws-1/builder?token=entry-secret"
            ),
        }

    async def capacity_bootstrap(builder_url: str):
        return await bootstrap_runtime_session(
            builder_url,
            client_factory=_capacity_client,
        )

    monkeypatch.setattr(service, "bootstrap_runtime_session", capacity_bootstrap)

    with pytest.raises(HTTPException) as exc_info:
        await open_code_session(
            db=db_session,
            session_id=session.id,
            ctx=SimpleNamespace(
                user=SimpleNamespace(id=11),
                tenant_id=7,
                tenant_role="member",
            ),
            workspace_open=fake_open,
        )

    assert exc_info.value.status_code == 503
    assert (
        exc_info.value.headers or {}
    ).get(CAPACITY_ERROR_HEADER) == CAPACITY_ERROR_CODE
    assert opens == 1
