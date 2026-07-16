from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.builder_auth.settings import (
    BuilderAuthSettings,
    PublicBuilderAuthSettings,
    get_builder_auth_config,
    get_public_builder_auth_settings,
    save_builder_auth_settings,
    to_public_builder_auth_settings,
)
from app.database import get_db
from app.deps import AuthContext, get_auth_context

public_router = APIRouter(tags=["认证配置"])
admin_router = APIRouter(tags=["认证配置"])


def _require_platform_admin(ctx: AuthContext) -> None:
    if ctx.user.is_platform_admin or ctx.tenant_role == "platform_admin":
        return
    raise HTTPException(status_code=403, detail="平台管理员才能访问此资源")


@public_router.get("/settings/public", response_model=PublicBuilderAuthSettings)
async def get_public_auth_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublicBuilderAuthSettings:
    return await get_public_builder_auth_settings(db)


@admin_router.get("/settings", response_model=BuilderAuthSettings)
async def get_admin_auth_settings(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BuilderAuthSettings:
    _require_platform_admin(ctx)
    return (await get_builder_auth_config(db)).settings


@admin_router.put("/settings", response_model=PublicBuilderAuthSettings)
async def put_admin_auth_settings(
    data: BuilderAuthSettings,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublicBuilderAuthSettings:
    _require_platform_admin(ctx)
    config = await save_builder_auth_settings(db, data, updated_by_user_id=ctx.user.id)
    return to_public_builder_auth_settings(config.settings)
