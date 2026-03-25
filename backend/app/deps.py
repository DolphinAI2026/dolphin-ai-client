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
from app.models.tenant import UserTenant, Role
from app.auth import security

logger = logging.getLogger(__name__)


@dataclass
class AuthContext:
    """Authentication request context — includes tenant scope."""
    user: User  # Authenticated user
    tenant_id: int  # Current active tenant (from JWT.tid)
    tenant_role: str  # Tenant role (platform_admin/tenant_admin/member)
    org_permissions: dict  # Org-level permissions (from role.permissions)


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

        # Platform admin has no tenant_id
        if tenant_id is None:
            # Check if platform admin
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user or not user.is_platform_admin:
                logger.warning(
                    "auth_context forbidden: token has no tenant_id but user is not platform admin user_id=%s",
                    user_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="平台管理员才能访问此资源",
                )
            return AuthContext(
                user=user,
                tenant_id=0,  # No tenant
                tenant_role="platform_admin",
                org_permissions={}
            )

        tenant_id = int(tenant_id)

    except (JWTError, ValueError):
        raise credentials_exception

    # Get user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise credentials_exception

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
            if role.role_code == "R_tenant_admin":
                tenant_role = "tenant_admin"

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
    tenant_id = int(payload.get("tid", 0))
    if not user_id:
        raise ValueError("Invalid token")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError("User not found")
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
