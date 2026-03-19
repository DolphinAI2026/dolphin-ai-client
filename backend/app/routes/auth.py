from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError
from app.database import get_db
from app.models import User
from app.models.tenant import Tenant, UserTenant, Role
from app.schemas import (
    UserLogin, UserRegister, Token, UserInfo,
    LoginResponse, TenantOption, TenantSelectRequest
)
from app.auth import verify_password, get_password_hash, create_access_token, create_selection_token
from app.deps import get_auth_context, AuthContext
from app.config import settings

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=Token)
async def register(
    user_data: UserRegister,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    # 检查用户名是否已存在
    result = await db.execute(select(User).where(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )

    # 创建新用户
    hashed_password = get_password_hash(user_data.password)
    new_user = User(
        username=user_data.username,
        hashed_password=hashed_password
    )
    db.add(new_user)
    await db.flush()

    # 获取默认租户
    result = await db.execute(select(Tenant).where(Tenant.tenant_code == "default"))
    default_tenant = result.scalar_one_or_none()
    if not default_tenant:
        raise HTTPException(status_code=500, detail="系统未初始化")

    # 获取租户管理员角色
    result = await db.execute(
        select(Role).where(
            Role.tenant_id == default_tenant.id,
            Role.role_code == "R_tenant_admin"
        )
    )
    admin_role = result.scalar_one_or_none()

    # 将用户加入默认租户（租户管理员角色）
    user_tenant = UserTenant(
        user_id=new_user.id,
        tenant_id=default_tenant.id,
        role_id=admin_role.id if admin_role else None,
        is_default=True,
        status=1
    )
    db.add(user_tenant)
    await db.commit()

    # 直接返回 JWT（单租户）
    access_token = create_access_token(data={"sub": new_user.id}, tenant_id=default_tenant.id)
    return Token(access_token=access_token)


@router.post("/login", response_model=LoginResponse)
async def login(
    user_data: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    # 验证用户
    result = await db.execute(select(User).where(User.username == user_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用"
        )

    # 平台管理员 — 直接登录，无租户
    if user.is_platform_admin:
        access_token = create_access_token(data={"sub": user.id}, tenant_id=None)
        return LoginResponse(access_token=access_token)

    # 获取用户的租户成员关系
    result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == user.id,
            UserTenant.status == 1
        )
    )
    memberships = result.scalars().all()

    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号未关联任何租户"
        )

    if len(memberships) == 1:
        # 单租户 — 直接登录
        tenant_id = memberships[0].tenant_id
        access_token = create_access_token(data={"sub": user.id}, tenant_id=tenant_id)
        return LoginResponse(access_token=access_token)

    # 多租户 — 返回租户列表
    tenant_ids = [m.tenant_id for m in memberships]
    result = await db.execute(
        select(Tenant).where(Tenant.id.in_(tenant_ids))
    )
    tenant_map = {t.id: t for t in result.scalars().all()}

    tenants = []
    default_tid = None
    for m in memberships:
        t = tenant_map.get(m.tenant_id)
        if t:
            tenants.append(TenantOption(
                tenant_id=t.id,
                tenant_name=t.tenant_name,
                tenant_code=t.tenant_code,
            ))
            if m.is_default:
                default_tid = t.id

    # 如果有默认租户，自动选择
    if default_tid:
        access_token = create_access_token(data={"sub": user.id}, tenant_id=default_tid)
        return LoginResponse(access_token=access_token, tenants=tenants)

    # 需要用户选择租户
    selection_token = create_selection_token(user.id)
    return LoginResponse(
        requires_tenant_selection=True,
        selection_token=selection_token,
        tenants=tenants
    )


@router.post("/select-tenant", response_model=Token)
async def select_tenant(
    data: TenantSelectRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """用户选择租户，换取完整 JWT"""
    try:
        payload = jwt.decode(data.selection_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "selection":
            raise HTTPException(status_code=401, detail="无效的选择 Token")
        user_id = int(payload.get("sub"))
    except JWTError:
        raise HTTPException(status_code=401, detail="选择 Token 已过期或无效")

    # 验证用户属于该租户
    result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == user_id,
            UserTenant.tenant_id == data.tenant_id,
            UserTenant.status == 1
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="你不是该租户的成员")

    # 生成完整 JWT
    access_token = create_access_token(data={"sub": user_id}, tenant_id=data.tenant_id)
    return Token(access_token=access_token)


@router.get("/me", response_model=UserInfo)
async def get_me(ctx: Annotated[AuthContext, Depends(get_auth_context)], db: Annotated[AsyncSession, Depends(get_db)]):
    # 获取租户信息
    tenant_name = None
    if ctx.tenant_id:
        result = await db.execute(select(Tenant).where(Tenant.id == ctx.tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant:
            tenant_name = tenant.tenant_name

    return UserInfo(
        id=ctx.user.id,
        username=ctx.user.username,
        is_active=ctx.user.is_active,
        created_at=ctx.user.created_at,
        tenant_id=ctx.tenant_id if ctx.tenant_id else None,
        tenant_name=tenant_name,
        tenant_role=ctx.tenant_role
    )
