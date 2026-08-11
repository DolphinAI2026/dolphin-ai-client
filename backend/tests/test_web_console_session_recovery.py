from types import SimpleNamespace

import pytest

from app.deps import AuthContext
from app.models import User
from app.routes.auth.web_console_session import create_web_console_session


@pytest.mark.asyncio
async def test_existing_apaas_builder_session_can_recover_web_console_session(monkeypatch):
    captured = {}

    async def fake_exchange(**kwargs):
        captured.update(kwargs)
        return {
            "access_token": "web-console-token",
            "tenant_id": "840289793437859841",
        }

    monkeypatch.setattr(
        "app.routes.auth.web_console_session.exchange_web_console_session",
        fake_exchange,
    )
    user = User(
        id=17,
        username="admin",
        hashed_password="unused",
        account_source="apaas",
        apaas_user_id="100169876816012509184",
        apaas_token="apaas-token",
        apaas_tenant_id="840289793437859841",
    )
    context = AuthContext(
        user=user,
        tenant_id=3,
        tenant_role="tenant_admin",
        org_permissions={},
        apaas_user_id=user.apaas_user_id,
        apaas_tenant_id=user.apaas_tenant_id,
    )

    response = await create_web_console_session(context)

    assert response.access_token == "web-console-token"
    assert response.tenant_id == "840289793437859841"
    assert captured == {
        "user_id": "100169876816012509184",
        "username": "admin",
        "apaas_access_token": "apaas-token",
        "apaas_tenant_id": "840289793437859841",
    }
