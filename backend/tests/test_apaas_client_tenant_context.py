from app.apaas_client import APaaSClient
from app.config import settings


def test_apaas_client_does_not_fallback_to_config_tenant(monkeypatch):
    monkeypatch.setattr(settings, "apaas_tenant_id", "config-tenant")

    client = APaaSClient(base_url="https://apaas.example/backend")

    assert client.tenant_id == ""
    assert client._get_headers()["xdaptenantid"] == ""


def test_apaas_client_uses_explicit_dynamic_tenant(monkeypatch):
    monkeypatch.setattr(settings, "apaas_tenant_id", "config-tenant")

    client = APaaSClient(base_url="https://apaas.example/backend", tenant_id=" user-tenant ")

    assert client.tenant_id == "user-tenant"
    assert client._get_headers()["xdaptenantid"] == "user-tenant"
