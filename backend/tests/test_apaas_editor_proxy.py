from __future__ import annotations

from app.routes import runtime_proxy


def test_editor_session_bootstrap_writes_platform_vuex_state():
    sid = runtime_proxy.register_editor_session(
        host="https://apaas.example.com",
        token="token-123",
        tenant_id="tenant-456",
    )

    creds = runtime_proxy._editor_sessions[sid]
    script = runtime_proxy._platform_auth_bootstrap_script(creds)

    assert "__vuex__local" in script
    assert "__vuex__session" in script
    assert "token-123" in script
    assert "tenant-456" in script
    assert "tenantBlock" in script
    assert "platformBlock" in script
