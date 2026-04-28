"""Authentication dependencies and context."""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Annotated
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError, jwt
from app.config import settings
from app.database import get_db
from app.models import User
from app.models.tenant import UserTenant, Role, Tenant
from app.auth import security

logger = logging.getLogger(__name__)


@dataclass
class AuthContext:
    """Authentication request context — includes tenant scope."""
    user: User  # Authenticated user
    tenant_id: int  # Current active tenant (from JWT.tid)
    tenant_role: str  # Tenant role (platform_admin/tenant_admin/member)
    org_permissions: dict  # Org-level permissions (from role.permissions)


async def resolve_default_tenant_id_for_user(db: AsyncSession, user_id: int) -> int | None:
    """Return the user's default active tenant id, falling back to the first active membership."""
    result = await db.execute(
        select(UserTenant)
        .where(
            UserTenant.user_id == user_id,
            UserTenant.status == 1,
        )
        .order_by(UserTenant.is_default.desc(), UserTenant.joined_at.asc())
    )
    membership = result.scalars().first()
    return membership.tenant_id if membership else None


async def resolve_effective_tenant_id(db: AsyncSession, ctx: AuthContext) -> int:
    """Resolve a usable tenant id for tenant-scoped settings pages.

    Some older platform-admin tokens do not carry a tenant id, and older admin
    accounts may not have a UserTenant row. Settings pages are still tenant
    scoped, so platform admins fall back to their default membership, then the
    first active tenant in the system.
    """
    if ctx.tenant_id and ctx.tenant_id > 0:
        return ctx.tenant_id

    fallback = await resolve_default_tenant_id_for_user(db, ctx.user.id)
    if fallback:
        return fallback

    if ctx.tenant_role == "platform_admin" or ctx.user.is_platform_admin:
        result = await db.execute(
            select(Tenant.id)
            .where(Tenant.status == 1)
            .order_by(Tenant.created_at.asc(), Tenant.id.asc())
        )
        tenant_id = result.scalar_one_or_none()
        if tenant_id:
            return tenant_id

    raise HTTPException(status_code=400, detail="未找到可用租户")


async def get_auth_context(
    credentials: Annotated[any, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> AuthContext:
    """Extract auth context from JWT token."""
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        tenant_id = payload.get("tid")

        if user_id is None:
            raise credentials_exception

        user_id = int(user_id)

        # Older platform-admin tokens may not carry tenant_id. Most settings
        # pages are still tenant-scoped, so resolve the admin's default tenant.
        if tenant_id is None:
            # Check if platform admin
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user or not user.is_active or not user.is_platform_admin:
                logger.warning(
                    "auth_context forbidden: token has no tenant_id but user is not platform admin user_id=%s",
                    user_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="平台管理员才能访问此资源",
                )
            resolved_tenant_id = await resolve_default_tenant_id_for_user(db, user_id)
            return AuthContext(
                user=user,
                tenant_id=resolved_tenant_id or 0,
                tenant_role="platform_admin",
                org_permissions={"*": True},
            )

        tenant_id = int(tenant_id)

    except (JWTError, ValueError):
        raise credentials_exception

    # Get user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise credentials_exception

    if user.is_platform_admin:
        return AuthContext(
            user=user,
            tenant_id=tenant_id,
            tenant_role="platform_admin",
            org_permissions={"*": True},
        )

    # Get user-tenant relationship
    result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == user_id,
            UserTenant.tenant_id == tenant_id,
            UserTenant.status == 1
        )
    )
    user_tenant = result.scalar_one_or_none()
    if not user_tenant:
        logger.warning(
            "auth_context forbidden: user is not an active tenant member user_id=%s tenant_id=%s",
            user_id,
            tenant_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你不是该租户的成员",
        )

    # Get role and permissions
    tenant_role = "member"
    org_permissions = {}

    if user_tenant.role_id:
        result = await db.execute(
            select(Role).where(Role.id == user_tenant.role_id)
        )
        role = result.scalar_one_or_none()
        if role:
            org_permissions = role.permissions or {}
            # Tenant admin has special role
            if role.role_code in ("R_tenant_admin", "admin"):
                tenant_role = "tenant_admin"
            elif role.role_code == "R_developer":
                tenant_role = "developer"
            elif role.role_code == "R_viewer":
                tenant_role = "viewer"

    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role=tenant_role,
        org_permissions=org_permissions
    )


async def get_auth_context_from_token(token: str) -> AuthContext:
    """从 token 字符串获取 auth context（供非标准路由使用，如 proxy 入口）"""
    from app.database import AsyncSessionLocal

    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    user_id = int(payload.get("sub", 0))
    raw_tenant_id = payload.get("tid")
    if not user_id:
        raise ValueError("Invalid token")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError("User not found")

        if raw_tenant_id is None:
            if user.is_platform_admin:
                tenant_id = await resolve_default_tenant_id_for_user(db, user_id) or 0
                return AuthContext(
                    user=user,
                    tenant_id=tenant_id,
                    tenant_role="platform_admin",
                    org_permissions={"*": True},
                )
            tenant_id = 0
        else:
            tenant_id = int(raw_tenant_id)

        if user.is_platform_admin:
            return AuthContext(
                user=user,
                tenant_id=tenant_id,
                tenant_role="platform_admin",
                org_permissions={"*": True},
            )
        return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


async def require_tenant_admin(
    ctx: Annotated[AuthContext, Depends(get_auth_context)]
) -> AuthContext:
    """Require tenant admin role."""
    if ctx.tenant_role not in ("platform_admin", "tenant_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要租户管理员权限",
        )
    return ctx
