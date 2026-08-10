from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.builder_auth.settings import get_builder_auth_config


class ProductDisabledError(Exception):
    """Raised when a route belongs to a disabled product."""


async def product_disabled_exception_handler(
    _request: Request,
    _exc: ProductDisabledError,
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": "product is disabled", "code": "PRODUCT_DISABLED"},
    )


async def require_builder_product() -> None:
    config = await get_builder_auth_config()
    if not config.settings.products.builder.enabled:
        raise ProductDisabledError()


async def require_code_product() -> None:
    config = await get_builder_auth_config()
    if not config.settings.products.code.enabled:
        raise ProductDisabledError()
