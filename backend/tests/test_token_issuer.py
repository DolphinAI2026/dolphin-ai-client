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


def test_assert_rejects_desktop_issuer_on_shared_backend(monkeypatch):
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder,desktop-sidecar")
    with pytest.raises(RuntimeError):
        auth.assert_shared_backend_issuer_safety()


def test_assert_passes_when_shared_backend_excludes_desktop(monkeypatch):
    # 非默认值且不含 desktop-sidecar: 断言应放行 (证明放行不是因为撞上默认值)。
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder,other-backend")
    auth.assert_shared_backend_issuer_safety()  # 不抛


def test_mcp_server_service_token_has_issuer_and_decodes(monkeypatch):
    """回归: mcp_server._sign_service_token 的内部服务 token 必须带 iss, 否则被
    decode_token 的 issuer 白名单拒(401) → 桌面 agent 所有内部调用(generate_app_from_doc 等)挂。
    """
    monkeypatch.setattr("app.config.settings.jwt_secret_key", "test-secret-svc")
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder")
    from app.mcp_server import _sign_service_token
    tok = _sign_service_token(1, 2)
    payload = auth.decode_token(tok)  # 不抛 = 过白名单
    assert payload["iss"] == "ai-builder" and payload["type"] == "mcp_service"
