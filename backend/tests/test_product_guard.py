from __future__ import annotations

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.builder_auth.settings import (
    BuilderAuthConfig,
    BuilderAuthSettings,
    ProductSwitch,
    ProductSwitches,
)
from app.builder_auth.product_guard import (
    ProductDisabledError,
    product_disabled_exception_handler,
    require_builder_product,
    require_code_product,
)


def _auth_config(*, builder_enabled: bool, code_enabled: bool) -> BuilderAuthConfig:
    return BuilderAuthConfig(
        settings=BuilderAuthSettings(
            products=ProductSwitches(
                builder=ProductSwitch(enabled=builder_enabled),
                code=ProductSwitch(enabled=code_enabled),
            ),
        ),
        source="env",
    )


def _guarded_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(ProductDisabledError, product_disabled_exception_handler)

    @app.get("/builder", dependencies=[Depends(require_builder_product)])
    async def builder_route():
        return {"product": "builder"}

    @app.get("/code", dependencies=[Depends(require_code_product)])
    async def code_route():
        return {"product": "code"}

    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("builder_enabled", "code_enabled", "path"),
    [
        (False, True, "/builder"),
        (True, False, "/code"),
    ],
)
async def test_disabled_product_returns_top_level_not_found_error(
    monkeypatch,
    builder_enabled: bool,
    code_enabled: bool,
    path: str,
):
    """Removing the disabled branch must expose the guarded route instead."""
    import app.builder_auth.product_guard as product_guard

    async def get_config():
        return _auth_config(builder_enabled=builder_enabled, code_enabled=code_enabled)

    monkeypatch.setattr(product_guard, "get_builder_auth_config", get_config)

    async with AsyncClient(transport=ASGITransport(app=_guarded_app()), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code == 404
    assert response.json() == {
        "detail": "product is disabled",
        "code": "PRODUCT_DISABLED",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("builder_enabled", "code_enabled", "path", "expected"),
    [
        (True, False, "/builder", {"product": "builder"}),
        (False, True, "/code", {"product": "code"}),
    ],
)
async def test_enabled_product_allows_original_route_response(
    monkeypatch,
    builder_enabled: bool,
    code_enabled: bool,
    path: str,
    expected: dict[str, str],
):
    """Removing the enabled branch must make its product route unavailable."""
    import app.builder_auth.product_guard as product_guard

    async def get_config():
        return _auth_config(builder_enabled=builder_enabled, code_enabled=code_enabled)

    monkeypatch.setattr(product_guard, "get_builder_auth_config", get_config)

    async with AsyncClient(transport=ASGITransport(app=_guarded_app()), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code == 200
    assert response.json() == expected


async def _main_app_responses(monkeypatch, *, builder_enabled: bool, code_enabled: bool):
    import app.builder_auth.product_guard as product_guard
    from app.main import app

    async def get_config():
        return _auth_config(builder_enabled=builder_enabled, code_enabled=code_enabled)

    monkeypatch.setattr(product_guard, "get_builder_auth_config", get_config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return {
            "builder": await client.get("/api/applications"),
            "code": await client.get("/api/coding/scenes"),
            "auth_settings": await client.get("/api/auth/settings/public"),
            "system_assistant": await client.get("/api/system-assistant/bootstrap"),
        }


@pytest.mark.asyncio
async def test_main_code_only_blocks_builder_routes_but_leaves_code_and_shared_routes_unguarded(monkeypatch):
    """Removing the Builder guard must expose the Builder API in Code-only mode."""
    responses = await _main_app_responses(monkeypatch, builder_enabled=False, code_enabled=True)

    assert responses["builder"].status_code == 404
    assert responses["builder"].json() == {
        "detail": "product is disabled",
        "code": "PRODUCT_DISABLED",
    }
    assert responses["code"].status_code == 200
    assert responses["code"].json() != {"detail": "product is disabled", "code": "PRODUCT_DISABLED"}
    assert responses["auth_settings"].json().get("code") != "PRODUCT_DISABLED"
    assert responses["system_assistant"].json().get("code") != "PRODUCT_DISABLED"


@pytest.mark.asyncio
async def test_main_builder_only_blocks_code_routes_but_leaves_builder_routes_unguarded(monkeypatch):
    """Removing the Code guard must expose the Code API in Builder-only mode."""
    responses = await _main_app_responses(monkeypatch, builder_enabled=True, code_enabled=False)

    assert responses["code"].status_code == 404
    assert responses["code"].json() == {
        "detail": "product is disabled",
        "code": "PRODUCT_DISABLED",
    }
    assert responses["builder"].json().get("code") != "PRODUCT_DISABLED"
