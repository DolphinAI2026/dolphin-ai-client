import pytest


@pytest.mark.asyncio
async def test_login_to_control_plane_runs_builder_password_oauth_chain(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.config import settings
    from app.code_runtime import auth as coding_auth

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    public_body = coding_auth.normalize_spki_public_key_body(public_pem)
    calls = []

    class FakeResponse:
        status_code = 200
        text = ""

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url, **kwargs):
            calls.append(("GET", url, kwargs))
            if url.endswith("/api/builder-auth/oauth/login-key"):
                return FakeResponse({
                    "code": "OK",
                    "data": {
                        "keyId": "key-1",
                        "algorithm": "RSA",
                        "publicKey": public_pem,
                        "status": "ACTIVE",
                    },
                })
            if url.endswith("/api/builder-auth/me"):
                assert kwargs["headers"]["Authorization"] == "Bearer access-1"
                assert kwargs["headers"]["X-Auth-Provider"] == "builder-control-plane"
                return FakeResponse({
                    "code": "OK",
                    "data": {
                        "userId": "user-1",
                        "username": "system_admin",
                        "displayName": "System Admin",
                        "roles": ["ADMIN"],
                        "status": "ENABLED",
                    },
                })
            raise AssertionError(url)

        async def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            body = kwargs.get("json") or {}
            if url.endswith("/api/builder-auth/oauth/authorize"):
                assert "clientId" not in body
                assert "redirectUri" not in body
                assert body["scopes"] == ["profile", "admin:control-plane"]
                return FakeResponse({
                    "code": "OK",
                    "data": {
                        "loginRequired": True,
                        "authorizationRequestId": "authz-1",
                        "state": body["state"],
                    },
                })
            if url.endswith("/api/builder-auth/oauth/login"):
                assert body["authorizationRequestId"] == "authz-1"
                assert body["username"] == "system_admin"
                assert body["encryptedPassword"] != "password"
                assert body["keyId"] == "key-1"
                assert kwargs["headers"]["rsa-public-key"] == public_body
                authorize_body = calls[1][2]["json"]
                return FakeResponse({
                    "code": "OK",
                    "data": {
                        "code": "auth-code-1",
                        "state": authorize_body["state"],
                        "sessionId": "session-1",
                    },
                })
            if url.endswith("/api/builder-auth/oauth/token"):
                assert body["grantType"] == "authorization_code"
                assert body["code"] == "auth-code-1"
                assert "clientId" not in body
                assert "redirectUri" not in body
                assert body["codeVerifier"]
                return FakeResponse({
                    "code": "OK",
                    "data": {
                        "accessToken": "access-1",
                        "tokenType": "Bearer",
                        "expiresIn": 3600,
                        "refreshToken": "refresh-1",
                        "refreshExpiresIn": 7200,
                        "scopes": ["profile", "admin:control-plane"],
                    },
                })
            raise AssertionError(url)

    monkeypatch.setattr(coding_auth.httpx, "AsyncClient", FakeClient)
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com")
    monkeypatch.setattr(settings, "dolphin_code_auth_scopes", "profile,admin:control-plane", raising=False)

    result = await coding_auth.login_to_control_plane("system_admin", "password")

    assert result.username == "system_admin"
    assert result.display_name == "System Admin"
    assert result.external_user_id == "user-1"
    assert result.roles == ["ADMIN"]
    assert result.access_token == "access-1"
    assert result.refresh_token == "refresh-1"
    assert [method for method, _url, _kwargs in calls] == ["GET", "POST", "POST", "POST", "GET"]


@pytest.mark.asyncio
async def test_exchange_apaas_identity_returns_binding_challenge(monkeypatch):
    from app.code_runtime import auth as control_plane_auth

    calls = []

    class FakeResponse:
        status_code = 200
        text = ""

        def __init__(self, data):
            self.data = data

        def json(self):
            return {
                "code": "OK",
                "data": self.data,
            }

    exchange_data = {
        "status": "BINDING_REQUIRED",
        "bindingChallenge": "challenge-1",
        "errorCode": "ACCOUNT_BINDING_REQUIRED",
        "message": "Binding is required",
        "traceId": "trace-1",
    }
    bind_data = {
        "bound": True,
        "tokenResponse": {
            "accessToken": "bound-access-token",
            "refreshToken": "bound-refresh-token",
        },
        "traceId": "trace-1",
    }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/api/builder-auth/federation/apaas/bind"):
                return FakeResponse(bind_data)
            return FakeResponse(exchange_data)

    monkeypatch.setattr(control_plane_auth.httpx, "AsyncClient", FakeClient)
    monkeypatch.setenv("DOLPHIN_CODE_CONTROL_PLANE_URL", "https://code.example.com")

    result = await control_plane_auth.exchange_apaas_identity("apaas-token", "tenant-1")

    assert result.status == "BINDING_REQUIRED"
    assert result.binding_challenge == "challenge-1"
    bound = await control_plane_auth.bind_apaas_identity(
        result.binding_challenge,
        "control-plane-proof",
        "tenant-1",
        result.trace_id,
    )

    assert bound.access_token == "bound-access-token"
    assert calls[0][0] == "https://code.example.com/api/builder-auth/federation/apaas/exchange"
    assert calls[0][1]["json"] == {
        "subjectToken": "apaas-token",
        "tenantId": "tenant-1",
    }
    assert calls[0][1]["headers"]["X-Trace-Id"]
    assert calls[1] == (
        "https://code.example.com/api/builder-auth/federation/apaas/bind",
        {
            "json": {
                "bindingChallenge": "challenge-1",
                "controlPlaneProofToken": "control-plane-proof",
                "tenantId": "tenant-1",
            },
            "headers": {"X-Trace-Id": result.trace_id},
        },
    )
