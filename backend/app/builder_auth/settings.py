from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.crypto import decrypt_password, encrypt_password
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

BUILDER_AUTH_SETTINGS_KEY = "builder_auth_settings"
ALLOWED_LOGIN_PROVIDERS = {"apaas", "platform"}
_CACHE_TTL_SEC = 5
_cached_config: BuilderAuthConfig | None = None
_cache_expires_at = 0.0


class ProductSwitch(BaseModel):
    enabled: bool = True


class ProductSwitches(BaseModel):
    builder: ProductSwitch = Field(default_factory=ProductSwitch)
    code: ProductSwitch = Field(default_factory=ProductSwitch)


class ProviderSettings(BaseModel):
    label: str = ""
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class BuilderAuthSettings(BaseModel):
    default_login_provider: Literal["apaas", "platform"] = "platform"
    enabled_login_providers: list[Literal["apaas", "platform"]] = Field(default_factory=lambda: ["platform"])
    products: ProductSwitches = Field(default_factory=ProductSwitches)
    providers: dict[str, ProviderSettings] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_settings(self) -> "BuilderAuthSettings":
        normalized_enabled: list[Literal["apaas", "platform"]] = []
        for provider in self.enabled_login_providers:
            if provider not in normalized_enabled:
                normalized_enabled.append(provider)
        self.enabled_login_providers = normalized_enabled

        if self.default_login_provider not in self.enabled_login_providers:
            raise ValueError("enabled_login_providers must include default_login_provider")
        if not (self.products.builder.enabled or self.products.code.enabled):
            raise ValueError("at least one product must be enabled")

        defaults = {
            "apaas": ProviderSettings(label="aPaaS 账号", enabled="apaas" in self.enabled_login_providers),
            "platform": ProviderSettings(label="平台账号", enabled="platform" in self.enabled_login_providers, config={"mode": "local"}),
        }
        merged = {**defaults, **self.providers}
        for provider in ALLOWED_LOGIN_PROVIDERS:
            if not merged[provider].label:
                merged[provider].label = defaults[provider].label
        self.providers = merged
        return self


class PublicProductSwitch(BaseModel):
    enabled: bool


class PublicProductSwitches(BaseModel):
    builder: PublicProductSwitch
    code: PublicProductSwitch


class PublicProviderSettings(BaseModel):
    provider: Literal["apaas", "platform"]
    label: str
    enabled: bool
    default: bool


class PublicBuilderAuthSettings(BaseModel):
    default_login_provider: Literal["apaas", "platform"]
    enabled_login_providers: list[Literal["apaas", "platform"]]
    products: PublicProductSwitches
    providers: list[PublicProviderSettings]


@dataclass(frozen=True)
class BuilderAuthConfig:
    settings: BuilderAuthSettings
    source: Literal["database", "env"]


def _normalize_legacy_provider(value: str | None) -> str:
    provider = (value or "").strip().lower()
    return {
        "self": "local",
        "own": "local",
        "native": "local",
        "builtin": "local",
    }.get(provider, provider)


def _parse_provider_csv(raw: str | None) -> list[Literal["apaas", "platform"]]:
    result: list[Literal["apaas", "platform"]] = []
    for item in (raw or "").replace("\n", ",").split(","):
        provider = item.strip().lower()
        if provider not in ALLOWED_LOGIN_PROVIDERS or provider in result:
            continue
        result.append(provider)  # type: ignore[arg-type]
    return result


def _has_explicit_file_config() -> bool:
    return bool(
        str(getattr(app_settings, "builder_auth_default_login_provider", "") or "").strip()
        or str(getattr(app_settings, "builder_auth_enabled_login_providers", "") or "").strip()
        or str(getattr(app_settings, "builder_auth_platform_mode", "") or "").strip()
    )


def _settings_from_explicit_file_config() -> BuilderAuthSettings:
    default_provider = str(getattr(app_settings, "builder_auth_default_login_provider", "") or "").strip().lower()
    enabled = _parse_provider_csv(getattr(app_settings, "builder_auth_enabled_login_providers", ""))

    if default_provider and default_provider not in ALLOWED_LOGIN_PROVIDERS:
        raise ValueError("BUILDER_AUTH_DEFAULT_LOGIN_PROVIDER must be apaas or platform")
    if not default_provider:
        default_provider = enabled[0] if enabled else "platform"
    if not enabled:
        enabled = [default_provider]  # type: ignore[list-item]

    platform_mode = str(getattr(app_settings, "builder_auth_platform_mode", "") or "local").strip().lower()
    if platform_mode not in {"local", "coding"}:
        platform_mode = "local"

    return BuilderAuthSettings(
        default_login_provider=default_provider,  # type: ignore[arg-type]
        enabled_login_providers=enabled,
        products=ProductSwitches(
            builder=ProductSwitch(enabled=bool(getattr(app_settings, "builder_product_builder_enabled", True))),
            code=ProductSwitch(enabled=bool(getattr(app_settings, "builder_product_code_enabled", True))),
        ),
        providers={
            "apaas": ProviderSettings(
                label=str(getattr(app_settings, "builder_auth_apaas_label", "aPaaS 账号") or "aPaaS 账号"),
                enabled="apaas" in enabled,
            ),
            "platform": ProviderSettings(
                label=str(getattr(app_settings, "builder_auth_platform_label", "平台账号") or "平台账号"),
                enabled="platform" in enabled,
                config={"mode": platform_mode},
            ),
        },
    )


def _fallback_settings_from_env() -> BuilderAuthSettings:
    if _has_explicit_file_config():
        return _settings_from_explicit_file_config()

    provider = _normalize_legacy_provider(getattr(app_settings, "auth_provider", ""))
    if provider == "apaas":
        return BuilderAuthSettings(
            default_login_provider="apaas",
            enabled_login_providers=["apaas"],
            providers={
                "apaas": ProviderSettings(label="aPaaS 账号", enabled=True),
                "platform": ProviderSettings(label="平台账号", enabled=False, config={"mode": "local"}),
            },
        )
    if provider == "coding":
        return BuilderAuthSettings(
            default_login_provider="platform",
            enabled_login_providers=["platform"],
            providers={
                "apaas": ProviderSettings(label="aPaaS 账号", enabled=False),
                "platform": ProviderSettings(label="平台账号", enabled=True, config={"mode": "coding"}),
            },
        )

    return BuilderAuthSettings(
        default_login_provider="platform",
        enabled_login_providers=["platform"],
        providers={
            "apaas": ProviderSettings(label="aPaaS 账号", enabled=False),
            "platform": ProviderSettings(label="平台账号", enabled=True, config={"mode": "local"}),
        },
    )


async def _read_database_settings(db: AsyncSession) -> BuilderAuthSettings | None:
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == BUILDER_AUTH_SETTINGS_KEY))
    if not row or not row.value_enc:
        return None
    raw = decrypt_password(row.value_enc)
    return BuilderAuthSettings.model_validate(json.loads(raw))


async def get_builder_auth_config(
    db: AsyncSession | None = None,
    *,
    use_cache: bool = True,
) -> BuilderAuthConfig:
    global _cached_config, _cache_expires_at

    now = time.monotonic()
    if use_cache and db is None and _cached_config is not None and now < _cache_expires_at:
        return _cached_config

    try:
        if _has_explicit_file_config():
            config = BuilderAuthConfig(settings=_settings_from_explicit_file_config(), source="env")
        elif db is not None:
            database_settings = await _read_database_settings(db)
            if database_settings is not None:
                config = BuilderAuthConfig(settings=database_settings, source="database")
            else:
                config = BuilderAuthConfig(settings=_fallback_settings_from_env(), source="env")
        else:
            from app.database import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                database_settings = await _read_database_settings(session)
            if database_settings is not None:
                config = BuilderAuthConfig(settings=database_settings, source="database")
            else:
                config = BuilderAuthConfig(settings=_fallback_settings_from_env(), source="env")
    except Exception as exc:
        logger.warning("读取 builder 鉴权配置失败，降级使用环境变量: %s", exc)
        config = BuilderAuthConfig(settings=_fallback_settings_from_env(), source="env")

    if db is None:
        _cached_config = config
        _cache_expires_at = now + _CACHE_TTL_SEC
    return config


def to_public_builder_auth_settings(settings: BuilderAuthSettings) -> PublicBuilderAuthSettings:
    providers: list[PublicProviderSettings] = []
    for provider in ("apaas", "platform"):
        item = settings.providers.get(provider) or ProviderSettings()
        enabled = bool(item.enabled and provider in settings.enabled_login_providers)
        if not enabled:
            continue
        providers.append(
            PublicProviderSettings(
                provider=provider,
                label=item.label or ("aPaaS 账号" if provider == "apaas" else "平台账号"),
                enabled=True,
                default=provider == settings.default_login_provider,
            )
        )

    return PublicBuilderAuthSettings(
        default_login_provider=settings.default_login_provider,
        enabled_login_providers=list(settings.enabled_login_providers),
        products=PublicProductSwitches(
            builder=PublicProductSwitch(enabled=settings.products.builder.enabled),
            code=PublicProductSwitch(enabled=settings.products.code.enabled),
        ),
        providers=providers,
    )


async def get_public_builder_auth_settings(
    db: AsyncSession | None = None,
    *,
    use_cache: bool = True,
) -> PublicBuilderAuthSettings:
    config = await get_builder_auth_config(db, use_cache=use_cache)
    return to_public_builder_auth_settings(config.settings)


async def save_builder_auth_settings(
    db: AsyncSession,
    settings: BuilderAuthSettings,
    *,
    updated_by_user_id: int | None = None,
) -> BuilderAuthConfig:
    global _cached_config, _cache_expires_at

    validated = BuilderAuthSettings.model_validate(settings.model_dump())
    raw = json.dumps(validated.model_dump(), ensure_ascii=False, sort_keys=True)
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == BUILDER_AUTH_SETTINGS_KEY))
    if row is None:
        row = SystemSetting(
            key=BUILDER_AUTH_SETTINGS_KEY,
            value_enc=encrypt_password(raw),
            description="Builder login providers and product switches",
            updated_by_user_id=updated_by_user_id,
        )
        db.add(row)
    else:
        row.value_enc = encrypt_password(raw)
        row.description = "Builder login providers and product switches"
        row.updated_by_user_id = updated_by_user_id

    await db.commit()
    config = BuilderAuthConfig(settings=validated, source="database")
    _cached_config = config
    _cache_expires_at = time.monotonic() + _CACHE_TTL_SEC
    return config
