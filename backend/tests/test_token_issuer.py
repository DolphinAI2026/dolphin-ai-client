import pytest
from jose import JWTError

from app import auth


def _token(monkeypatch, issuer):
    monkeypatch.setattr("app.config.settings.jwt_secret_key", "test-secret-xyz")
    return auth.create_access_token(1, tenant_id=1, issuer=issuer)


def test_decode_accepts_default_issuer(monkeypatch):
    monkeypatch.setattr("app.config.settings.jwt_secret_key", "test-secret-xyz")
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder")
    tok = auth.create_access_token(1, tenant_id=1)  # 默认 iss=ai-builder
    payload = auth.decode_token(tok)
    assert payload["iss"] == "ai-builder"


def test_decode_rejects_desktop_issuer_on_shared_backend(monkeypatch):
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder")
    tok = _token(monkeypatch, "desktop-sidecar")
    with pytest.raises(JWTError):
        auth.decode_token(tok)


def test_decode_accepts_desktop_issuer_when_whitelisted(monkeypatch):
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder,desktop-sidecar")
    tok = _token(monkeypatch, "desktop-sidecar")
    payload = auth.decode_token(tok)
    assert payload["iss"] == "desktop-sidecar"


def test_decode_rejects_token_without_issuer(monkeypatch):
    """无 iss claim 的票 (老票/伪造票) 在默认白名单下被拒。"""
    from jose import jwt as _jwt
    monkeypatch.setattr("app.config.settings.jwt_secret_key", "test-secret-xyz")
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder")
    raw = _jwt.encode({"sub": "1", "type": "access"}, "test-secret-xyz", algorithm="HS256")
    with pytest.raises(JWTError):
        auth.decode_token(raw)
