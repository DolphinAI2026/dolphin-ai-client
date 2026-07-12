import pytest


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_fetch_dolphin_captcha_uses_full_workspace_auth_api(monkeypatch):
    from app.code_runtime import auth as coding_auth
    from app.config import settings

    calls = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse({
                "captcha_id": "captcha-1",
                "image_data": "data:image/svg+xml;base64,PHN2Zy8+",
            })

    monkeypatch.setattr(coding_auth.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        settings,
        "dolphin_workspace_base_url",
        "https://dolphin.example.com/",
        raising=False,
    )

    result = await coding_auth.fetch_dolphin_captcha()

    assert result == {
        "captcha_id": "captcha-1",
        "image_data": "data:image/svg+xml;base64,PHN2Zy8+",
    }
    assert calls == [("https://dolphin.example.com/api/auth/captcha", {})]


@pytest.mark.asyncio
async def test_login_to_control_plane_uses_dolphin_token_and_current_user(monkeypatch):
    from app.code_runtime import auth as coding_auth
    from app.config import settings

    calls = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            assert url == "https://dolphin.example.com/api/auth/login"
            assert kwargs["json"] == {
                "username": "admin",
                "password": "password",
                "captcha_id": "captcha-1",
                "captcha_code": "0854",
            }
            return FakeResponse({
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "token_type": "bearer",
                "requires_tenant_selection": False,
            })

        async def get(self, url, **kwargs):
            calls.append(("GET", url, kwargs))
            assert url == "https://dolphin.example.com/api/auth/me"
            assert kwargs["headers"] == {"Authorization": "Bearer access-1"}
            return FakeResponse({
                "id": 7,
                "username": "admin",
                "nickname": "Platform Admin",
                "role": "platform_admin",
                "org_permissions": {"system.*": True},
                "tenant_id": "default",
                "tenant_name": "Default Tenant",
                "tenants": [{
                    "tenant_id": "default",
                    "tenant_name": "Default Tenant",
                    "is_default": True,
                }],
            })

    monkeypatch.setattr(coding_auth.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        settings,
        "dolphin_workspace_base_url",
        "https://dolphin.example.com",
        raising=False,
    )

    result = await coding_auth.login_to_control_plane(
        "admin",
        "password",
        "captcha-1",
        "0854",
    )

    assert result.username == "admin"
    assert result.display_name == "Platform Admin"
    assert result.external_user_id == "7"
    assert result.roles == ["platform_admin"]
    assert result.org_permissions == {"system.*": True}
    assert result.tenant_id == "default"
    assert result.access_token == "access-1"
    assert result.refresh_token == "refresh-1"
    assert [method for method, _url, _kwargs in calls] == ["POST", "GET"]


@pytest.mark.asyncio
async def test_refresh_control_plane_token_uses_dolphin_refresh_api(monkeypatch):
    from app.code_runtime import auth as coding_auth
    from app.config import settings

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **kwargs):
            assert url == "https://dolphin.example.com/api/auth/refresh"
            assert kwargs["json"] == {"refresh_token": "refresh-1"}
            return FakeResponse({
                "access_token": "access-2",
                "refresh_token": "refresh-2",
            })

    monkeypatch.setattr(coding_auth.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        settings,
        "dolphin_workspace_base_url",
        "https://dolphin.example.com",
        raising=False,
    )

    result = await coding_auth.refresh_control_plane_token("refresh-1")

    assert result.access_token == "access-2"
    assert result.refresh_token == "refresh-2"


@pytest.mark.asyncio
async def test_exchange_apaas_token_uses_dolphin_binding_api(monkeypatch):
    from app.code_runtime import auth as coding_auth
    from app.config import settings

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **kwargs):
            assert url == "https://dolphin.example.com/api/auth/apaas/exchange"
            assert kwargs["json"] == {
                "apaas_token": "apaas-token",
                "apaas_tenant_id": "apaas-tenant-1",
            }
            return FakeResponse({
                "access_token": "workspace-access",
                "refresh_token": "workspace-refresh",
                "tenant_id": "default",
            })

    monkeypatch.setattr(coding_auth.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        settings,
        "dolphin_workspace_base_url",
        "https://dolphin.example.com",
    )

    result = await coding_auth.exchange_apaas_token("apaas-token", "apaas-tenant-1")

    assert result.access_token == "workspace-access"
    assert result.refresh_token == "workspace-refresh"
    assert result.tenant_id == "default"
