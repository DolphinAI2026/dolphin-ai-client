import pytest


@pytest.mark.asyncio
async def test_login_to_coding_control_plane_runs_password_oauth_chain(monkeypatch):
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
            if url.endswith("/api/auth/login-key"):
                return FakeResponse({
                    "code": "OK",
                    "data": {
                        "keyId": "key-1",
                        "algorithm": "RSA",
                        "publicKey": public_pem,
                        "status": "ACTIVE",
                    },
                })
            if url.endswith("/api/auth/me"):
                assert kwargs["headers"]["Authorization"] == "Bearer access-1"
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
            if url.endswith("/api/auth/authorize"):
                assert body["clientId"] == "test-client"
                assert body["redirectUri"] == "http://localhost/auth/callback"
                assert body["scopes"] == ["profile", "admin:control-plane"]
                return FakeResponse({
                    "code": "OK",
                    "data": {
                        "loginRequired": True,
                        "authorizationRequestId": "authz-1",
                        "state": body["state"],
                    },
                })
            if url.endswith("/api/auth/login"):
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
            if url.endswith("/api/auth/token"):
                assert body["grantType"] == "authorization_code"
                assert body["code"] == "auth-code-1"
                assert body["clientId"] == "test-client"
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
    monkeypatch.setattr(settings, "dolphin_code_auth_client_id", "test-client", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_auth_redirect_uri", "http://localhost/auth/callback", raising=False)
    monkeypatch.setattr(settings, "dolphin_code_auth_scopes", "profile,admin:control-plane", raising=False)

    result = await coding_auth.login_to_coding_control_plane("system_admin", "password")

    assert result.username == "system_admin"
    assert result.display_name == "System Admin"
    assert result.external_user_id == "user-1"
    assert result.roles == ["ADMIN"]
    assert result.access_token == "access-1"
    assert result.refresh_token == "refresh-1"
    assert [method for method, _url, _kwargs in calls] == ["GET", "POST", "POST", "POST", "GET"]
