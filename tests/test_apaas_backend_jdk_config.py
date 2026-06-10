from app.coding import workspace
from app.config import settings


def test_normalize_apaas_backend_jdk_version_defaults_to_17():
    assert workspace._normalize_apaas_backend_jdk_version("") == "17"
    assert workspace._normalize_apaas_backend_jdk_version("bad") == "17"


def test_normalize_apaas_backend_jdk_version_accepts_supported_values():
    assert workspace._normalize_apaas_backend_jdk_version("1.8") == "8"
    assert workspace._normalize_apaas_backend_jdk_version("jdk17") == "17"
    assert workspace._normalize_apaas_backend_jdk_version("auto") == "auto"


def test_apaas_backend_build_env_exports_configured_jdk(monkeypatch):
    monkeypatch.setattr(settings, "apaas_backend_jdk_version", "17")

    env = workspace._apaas_backend_build_env({"PATH": "/usr/bin"})

    assert env["APAAS_BACKEND_JDK_VERSION"] == "17"
    assert env["PATH"] == "/usr/bin" or env["PATH"].startswith("/opt/jdk17/bin:")
