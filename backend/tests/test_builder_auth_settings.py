from __future__ import annotations

import pytest

from app.config import settings as app_settings
from app.builder_auth.settings import (
    BuilderAuthSettings,
    ProductSwitch,
    ProductSwitches,
    ProviderSettings,
    get_builder_auth_config,
    get_public_builder_auth_settings,
    save_builder_auth_settings,
)


@pytest.mark.asyncio
async def test_save_and_load_builder_auth_settings_hide_secrets(db_session):
    settings = BuilderAuthSettings(
        default_login_provider="apaas",
        enabled_login_providers=["apaas", "platform"],
        products=ProductSwitches(
            builder=ProductSwitch(enabled=True),
            code=ProductSwitch(enabled=False),
        ),
        providers={
            "apaas": ProviderSettings(
                label="aPaaS 账号",
                enabled=True,
                config={"base_url": "http://apaas", "secret": "s1"},
            ),
            "platform": ProviderSettings(
                label="平台账号",
                enabled=True,
                config={"mode": "local"},
            ),
        },
    )

    saved = await save_builder_auth_settings(db_session, settings, updated_by_user_id=1)
    loaded = await get_builder_auth_config(db_session, use_cache=False)
    public = await get_public_builder_auth_settings(db_session, use_cache=False)

    assert saved.source == "database"
    assert loaded.source == "database"
    assert loaded.settings.default_login_provider == "apaas"
    assert public.default_login_provider == "apaas"
    assert public.products.code.enabled is False
    assert [provider.provider for provider in public.providers] == ["apaas", "platform"]
    assert "s1" not in public.model_dump_json()
    assert "secret" not in public.model_dump_json()


@pytest.mark.asyncio
async def test_builder_auth_settings_fallback_to_env_provider(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "auth_provider", "coding", raising=False)

    config = await get_builder_auth_config(db_session, use_cache=False)

    assert config.source == "env"
    assert config.settings.default_login_provider == "platform"
    assert config.settings.enabled_login_providers == ["platform"]
    assert config.settings.providers["platform"].config["mode"] == "coding"


@pytest.mark.asyncio
async def test_public_builder_auth_settings_omit_disabled_providers(db_session):
    await save_builder_auth_settings(
        db_session,
        BuilderAuthSettings(
            default_login_provider="platform",
            enabled_login_providers=["platform"],
            providers={
                "apaas": ProviderSettings(label="aPaaS 账号", enabled=False),
                "platform": ProviderSettings(label="Control Plane 账号", enabled=True, config={"mode": "coding"}),
            },
        ),
    )

    public = await get_public_builder_auth_settings(db_session, use_cache=False)

    assert public.default_login_provider == "platform"
    assert [provider.provider for provider in public.providers] == ["platform"]
    assert public.providers[0].label == "Control Plane 账号"


@pytest.mark.asyncio
async def test_builder_auth_settings_reads_explicit_config_file_fields(db_session, monkeypatch):
    monkeypatch.setattr(
        app_settings.__class__,
        "builder_auth_default_login_provider",
        property(lambda _settings: "apaas"),
        raising=False,
    )
    monkeypatch.setattr(
        app_settings.__class__,
        "builder_auth_enabled_login_providers",
        property(lambda _settings: "apaas,platform"),
        raising=False,
    )
    monkeypatch.setattr(
        app_settings.__class__,
        "builder_product_builder_enabled",
        property(lambda _settings: True),
        raising=False,
    )
    monkeypatch.setattr(
        app_settings.__class__,
        "builder_product_code_enabled",
        property(lambda _settings: False),
        raising=False,
    )
    monkeypatch.setattr(
        app_settings.__class__,
        "builder_auth_platform_mode",
        property(lambda _settings: "coding"),
        raising=False,
    )

    config = await get_builder_auth_config(db_session, use_cache=False)

    assert config.source == "env"
    assert config.settings.default_login_provider == "apaas"
    assert config.settings.enabled_login_providers == ["apaas", "platform"]
    assert config.settings.products.builder.enabled is True
    assert config.settings.products.code.enabled is False
    assert config.settings.providers["apaas"].enabled is True
    assert config.settings.providers["platform"].enabled is True
    assert config.settings.providers["platform"].config["mode"] == "coding"


@pytest.mark.asyncio
async def test_explicit_config_file_fields_override_database_settings(db_session, monkeypatch):
    await save_builder_auth_settings(
        db_session,
        BuilderAuthSettings(
            default_login_provider="platform",
            enabled_login_providers=["platform"],
            providers={
                "apaas": ProviderSettings(label="aPaaS 账号", enabled=False),
                "platform": ProviderSettings(label="平台账号", enabled=True, config={"mode": "local"}),
            },
        ),
    )
    monkeypatch.setattr(
        app_settings.__class__,
        "builder_auth_default_login_provider",
        property(lambda _settings: "apaas"),
        raising=False,
    )
    monkeypatch.setattr(
        app_settings.__class__,
        "builder_auth_enabled_login_providers",
        property(lambda _settings: "apaas,platform"),
        raising=False,
    )

    config = await get_builder_auth_config(db_session, use_cache=False)

    assert config.source == "env"
    assert config.settings.default_login_provider == "apaas"
    assert config.settings.enabled_login_providers == ["apaas", "platform"]
