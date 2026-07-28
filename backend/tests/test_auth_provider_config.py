from app.config import Settings


def test_auth_provider_defaults_to_control_plane(monkeypatch):
    monkeypatch.delenv("AUTH_PROVIDER", raising=False)

    config = Settings(_env_file=None, jwt_secret_key="test-secret")

    assert config.auth_provider == "control_plane"


def test_auth_provider_accepts_apaas_from_environment(monkeypatch):
    monkeypatch.setenv("AUTH_PROVIDER", "apaas")

    config = Settings(_env_file=None, jwt_secret_key="test-secret")

    assert config.auth_provider == "apaas"
