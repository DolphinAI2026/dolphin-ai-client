"""Authentication dependencies and context."""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Annotated, Optional
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError
from app.database import get_db
from app.models import User
from app.models.tenant import UserTenant, Role, Tenant
from app.auth import security, decode_token

logger = logging.getLogger(__name__)


@dataclass
class AuthContext:
    """Authentication request context — includes tenant scope.

    2026-05-10 Phase 2 双 ID：apaas_user_id / apaas_tenant_id 跟着 JWT 一起来。
    JWT.apaas_sub / apaas_tid 优先；老 JWT 缺这俩 claim 时回退到从 User 行读
    apaas_user_id / apaas_tenant_id 字段。
    """
    user: User  # Authenticated user
    tenant_id: int  # Current active tenant (from JWT.tid)
    tenant_role: str  # Tenant role (platform_admin/tenant_admin/member)
    org_permissions: dict  # Org-level permissions (from role.permissions)
    apaas_user_id: Optional[str] = None  # aPaaS 平台 user_id（21 位 string）
    apaas_tenant_id: Optional[str] = None  # aPaaS 平台 tenant_id（21 位 string）


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
            .limit(1)
        )
        tenant_id = result.scalar_one_or_none()
        if tenant_id:
            return tenant_id

    raise HTTPException(status_code=400, detail="未找到可用租户")


async def _resolve_role_context(db: AsyncSession, role_id: int | None) -> tuple[str, dict]:
    """role_id → (tenant_role, org_permissions)。

    header 路径 (get_auth_context) 与 query-token 路径 (get_auth_context_from_token)
    共用同一份角色解析，避免两边漂移 —— 旧实现 token 路径漏查 Role 直接硬编码
    member/{} ，导致自开发整页预览 (custom-page-host) 对非平台管理员一律 403。
    """
    tenant_role = "member"
    org_permissions: dict = {}
    if role_id:
        result = await db.execute(select(Role).where(Role.id == role_id))
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
    return tenant_role, org_permissions


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
        payload = decode_token(token)
        user_id = payload.get("sub")
        tenant_id = payload.get("tid")
        token_type = payload.get("type")
        # Phase 2 新 claim：apaas 双 ID（access type 才填）
        jwt_apaas_uid = payload.get("apaas_sub")
        jwt_apaas_tid = payload.get("apaas_tid")

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
                apaas_user_id=jwt_apaas_uid or user.apaas_user_id or None,
                apaas_tenant_id=jwt_apaas_tid or user.apaas_tenant_id or None,
            )

        tenant_id = int(tenant_id)

    except (JWTError, ValueError):
        raise credentials_exception

    # Get user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise credentials_exception

    # 双 ID 解析：JWT 优先，回退 user 行
    eff_apaas_uid = jwt_apaas_uid or user.apaas_user_id or None
    eff_apaas_tid = jwt_apaas_tid or user.apaas_tenant_id or None

    # MCP 后端内部互调短票：由服务端自己签发，只用于调用内部 HTTP endpoint。
    # 它表达的是“服务代表该 tenant 执行落库/解析/部署”，不能再按最终用户租户成员
    # 关系去卡，否则 MCP 原生 aPaaS token 场景会在 /applications/upload-doc 误报
    # “你不是该租户的成员”。
    if token_type == "mcp_service":
        return AuthContext(
            user=user,
            tenant_id=tenant_id,
            tenant_role="platform_admin",
            org_permissions={"*": True},
            apaas_user_id=eff_apaas_uid,
            apaas_tenant_id=eff_apaas_tid,
        )

    if user.is_platform_admin:
        return AuthContext(
            user=user,
            tenant_id=tenant_id,
            tenant_role="platform_admin",
            org_permissions={"*": True},
            apaas_user_id=eff_apaas_uid,
            apaas_tenant_id=eff_apaas_tid,
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

    # Get role and permissions (shared resolver — keep header/token paths in sync)
    tenant_role, org_permissions = await _resolve_role_context(db, user_tenant.role_id)

    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role=tenant_role,
        org_permissions=org_permissions,
        apaas_user_id=eff_apaas_uid,
        apaas_tenant_id=eff_apaas_tid,
    )


async def get_auth_context_from_token(token: str) -> AuthContext:
    """从 token 字符串获取 auth context（供非标准路由使用，如 proxy 入口）"""
    from app.database import AsyncSessionLocal

    payload = decode_token(token)
    user_id = int(payload.get("sub", 0))
    raw_tenant_id = payload.get("tid")
    token_type = payload.get("type")
    jwt_apaas_uid = payload.get("apaas_sub")
    jwt_apaas_tid = payload.get("apaas_tid")
    if not user_id:
        raise ValueError("Invalid token")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError("User not found")

        eff_apaas_uid = jwt_apaas_uid or user.apaas_user_id or None
        eff_apaas_tid = jwt_apaas_tid or user.apaas_tenant_id or None

        if raw_tenant_id is None:
            if user.is_platform_admin:
                tenant_id = await resolve_default_tenant_id_for_user(db, user_id) or 0
                return AuthContext(
                    user=user,
                    tenant_id=tenant_id,
                    tenant_role="platform_admin",
                    org_permissions={"*": True},
                    apaas_user_id=eff_apaas_uid,
                    apaas_tenant_id=eff_apaas_tid,
                )
            tenant_id = 0
        else:
            tenant_id = int(raw_tenant_id)

        if token_type == "mcp_service":
            return AuthContext(
                user=user,
                tenant_id=tenant_id,
                tenant_role="platform_admin",
                org_permissions={"*": True},
                apaas_user_id=eff_apaas_uid,
                apaas_tenant_id=eff_apaas_tid,
            )

        if user.is_platform_admin:
            return AuthContext(
                user=user,
                tenant_id=tenant_id,
                tenant_role="platform_admin",
                org_permissions={"*": True},
                apaas_user_id=eff_apaas_uid,
                apaas_tenant_id=eff_apaas_tid,
            )
        # 普通租户用户：查 UserTenant→Role 拿真实角色权限，与 header 路径一致。
        # （旧实现硬编码 member/{} → 自开发整页预览/SSE 等 query-token 入口丢权限。）
        result = await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == user_id,
                UserTenant.tenant_id == tenant_id,
                UserTenant.status == 1,
            )
        )
        user_tenant = result.scalar_one_or_none()
        tenant_role, org_permissions = await _resolve_role_context(
            db, user_tenant.role_id if user_tenant else None
        )
        return AuthContext(
            user=user,
            tenant_id=tenant_id,
            tenant_role=tenant_role,
            org_permissions=org_permissions,
            apaas_user_id=eff_apaas_uid,
            apaas_tenant_id=eff_apaas_tid,
        )


async def auth_from_header_or_query(request: Request) -> AuthContext:
    """从 `Authorization: Bearer` header（优先）或 `?token=` query 解析 AuthContext。

    浏览器原生 GET（SSE EventSource、`<a download>` 直链等）无法带自定义 header，
    所以需要 `?token=` 作后备通道。SSE 与二进制产物下载入口共用此实现，避免漂移。
    """
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    token: Optional[str] = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(None, 1)[1].strip()
    if not token:
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证 token（header 或 ?token= 均可）",
        )
    try:
        return await get_auth_context_from_token(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的 token")


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
