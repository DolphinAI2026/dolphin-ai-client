from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError
from app.database import get_db
from app.models import User
from app.models.tenant import Tenant, UserTenant, Role
from app.schemas import (
    UserLogin, Token, UserInfo,
    LoginResponse, TenantOption, TenantSelectRequest
)
from app.auth import verify_password, get_password_hash, create_access_token, create_selection_token
from app.deps import (
    AuthContext,
    get_auth_context,
    require_tenant_admin,
    resolve_default_tenant_id_for_user,
)
from app.config import settings
from app.error_messages import SELECT_TOKEN_INVALID, SELECT_TOKEN_EXPIRED
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["认证"])


def _resolve_tenant_role(role: Optional[Role]) -> tuple[str, Optional[str], dict]:
    if not role:
        return "member", None, {}
    role_code = role.role_code or ""
    if role_code in ("R_tenant_admin", "admin"):
        return "tenant_admin", role.role_name, role.permissions or {}
    if role_code == "R_developer":
        return "developer", role.role_name, role.permissions or {}
    if role_code == "R_viewer":
        return "viewer", role.role_name, role.permissions or {}
    return "member", role.role_name, role.permissions or {}


def _serialize_tenant_user(user: User, membership: UserTenant, role: Optional[Role], tenant: Optional[Tenant] = None) -> dict:
    tenant_role, role_name, permissions = _resolve_tenant_role(role)
    return {
        "id": user.id,
        "username": user.username,
        "is_active": user.is_active,
        "is_platform_admin": user.is_platform_admin,
        "tenant_id": membership.tenant_id,
        "tenant_name": tenant.tenant_name if tenant else None,
        "tenant_summary": tenant.tenant_name if tenant else None,
        "tenant_status": membership.status,
        "tenant_role": tenant_role,
        "role_code": role.role_code if role else None,
        "role_name": role_name,
        "org_permissions": permissions,
        "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _serialize_platform_user(user: User, memberships: list[tuple[UserTenant, Tenant, Optional[Role]]]) -> dict:
    active_memberships = [m for m, _tenant, _role in memberships if m.status == 1]
    tenant_names = [tenant.tenant_name for _m, tenant, _role in memberships]
    tenant_summary = "、".join(tenant_names[:3])
    if len(tenant_names) > 3:
        tenant_summary += f" 等 {len(tenant_names)} 个组织"
    if not tenant_summary:
        tenant_summary = "未加入组织"

    tenant_role = "member"
    role_code = "normal_user"
    role_name = "普通账号"
    permissions: dict = {}
    if user.is_platform_admin:
        tenant_role = "platform_admin"
        role_code = "platform_admin"
        role_name = "平台超级管理员"
        tenant_summary = "全部组织"
    else:
        for _membership, _tenant, role in memberships:
            resolved_role, resolved_name, resolved_permissions = _resolve_tenant_role(role)
            if resolved_role == "tenant_admin":
                tenant_role = resolved_role
                role_code = role.role_code if role else "normal_user"
                role_name = resolved_name or role_name
                permissions = resolved_permissions
                break
            if resolved_role != "member" and tenant_role == "member":
                tenant_role = resolved_role
                role_code = role.role_code if role else "normal_user"
                role_name = resolved_name or role_name
                permissions = resolved_permissions

    return {
        "id": user.id,
        "username": user.username,
        "is_active": user.is_active,
        "is_platform_admin": user.is_platform_admin,
        "tenant_id": None,
        "tenant_name": None,
        "tenant_summary": tenant_summary,
        "tenant_status": 1 if user.is_active else 0,
        "tenant_role": tenant_role,
        "role_code": role_code,
        "role_name": role_name,
        "org_permissions": permissions,
        "joined_at": active_memberships[0].joined_at.isoformat() if active_memberships else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


async def _load_user_memberships(
    db: AsyncSession, user_ids: list[int]
) -> dict[int, list[tuple[UserTenant, Tenant, Optional[Role]]]]:
    if not user_ids:
        return {}
    result = await db.execute(
        select(UserTenant, Tenant, Role)
        .join(Tenant, Tenant.id == UserTenant.tenant_id)
        .outerjoin(Role, Role.id == UserTenant.role_id)
        .where(UserTenant.user_id.in_(user_ids))
        .order_by(Tenant.tenant_name.asc(), UserTenant.joined_at.asc())
    )
    grouped: dict[int, list[tuple[UserTenant, Tenant, Optional[Role]]]] = {}
    for membership, tenant, role in result.all():
        grouped.setdefault(membership.user_id, []).append((membership, tenant, role))
    return grouped


class UpdateTenantUserStatusRequest(BaseModel):
    status: int


class UpdateTenantUserRoleRequest(BaseModel):
    role_code: str


class InviteTenantUserRequest(BaseModel):
    username: str
    password: Optional[str] = None
    role_code: Optional[str] = None


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

    # 平台管理员直接进入默认租户上下文。平台管理权限仍由
    # is_platform_admin 标识提供，tenant_id 用于租户级配置页查询。
    if user.is_platform_admin:
        tenant_id = await resolve_default_tenant_id_for_user(db, user.id)
        access_token = create_access_token(data={"sub": user.id}, tenant_id=tenant_id)
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
            raise HTTPException(status_code=401, detail=SELECT_TOKEN_INVALID)
        user_id = int(payload.get("sub"))
    except JWTError:
        raise HTTPException(status_code=401, detail=SELECT_TOKEN_EXPIRED)

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


class TenantSwitchRequest(BaseModel):
    tenant_id: int


@router.post("/switch-tenant", response_model=Token)
async def switch_tenant(
    data: TenantSwitchRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """已登录用户切换 active tenant，签发携带新 tid 的 JWT。

    平台管理员可以切到任意 active 租户；普通用户仅限自己 active membership。
    """
    if ctx.user.is_platform_admin:
        tenant = (
            await db.execute(
                select(Tenant).where(Tenant.id == data.tenant_id, Tenant.status == 1)
            )
        ).scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="租户不存在或未启用")
    else:
        membership = (
            await db.execute(
                select(UserTenant).where(
                    UserTenant.user_id == ctx.user.id,
                    UserTenant.tenant_id == data.tenant_id,
                    UserTenant.status == 1,
                )
            )
        ).scalar_one_or_none()
        if not membership:
            raise HTTPException(status_code=403, detail="你不是该租户的成员")

    access_token = create_access_token(data={"sub": ctx.user.id}, tenant_id=data.tenant_id)
    return Token(access_token=access_token)


def _require_platform_admin(ctx: AuthContext) -> None:
    if ctx.user.is_platform_admin or ctx.tenant_role == "platform_admin":
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台管理员可执行此操作")


class TenantCreateRequest(BaseModel):
    tenant_name: str
    tenant_code: str
    plan_type: str = "free"
    max_applications: int = 10
    max_workspaces: int = 20
    max_components: int = 50
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None


class TenantStatusRequest(BaseModel):
    status: int  # 1=active, 0=disabled


class TenantAdminItem(BaseModel):
    id: int
    tenant_name: str
    tenant_code: str
    plan_type: str
    max_applications: int
    max_workspaces: int
    max_components: int
    status: int
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    member_count: int = 0
    created_at: Optional[str] = None


def _tenant_admin_item(t: Tenant, member_count: int) -> TenantAdminItem:
    return TenantAdminItem(
        id=t.id,
        tenant_name=t.tenant_name,
        tenant_code=t.tenant_code,
        plan_type=t.plan_type,
        max_applications=t.max_applications,
        max_workspaces=t.max_workspaces,
        max_components=t.max_components,
        status=t.status,
        contact_name=t.contact_name,
        contact_email=t.contact_email,
        member_count=member_count,
        created_at=t.created_at.isoformat() if t.created_at else None,
    )


@router.get("/tenants", response_model=list[TenantAdminItem])
async def list_all_tenants(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出所有租户（仅平台管理员），含 member_count。"""
    _require_platform_admin(ctx)

    from sqlalchemy import func as sql_func

    rows = (
        await db.execute(
            select(Tenant).order_by(Tenant.created_at.desc(), Tenant.id.desc())
        )
    ).scalars().all()

    counts_rows = (
        await db.execute(
            select(UserTenant.tenant_id, sql_func.count(UserTenant.id))
            .where(UserTenant.status == 1)
            .group_by(UserTenant.tenant_id)
        )
    ).all()
    count_map = {tid: cnt for tid, cnt in counts_rows}

    return [_tenant_admin_item(t, count_map.get(t.id, 0)) for t in rows]


@router.post("/tenants", response_model=TenantAdminItem)
async def create_new_tenant(
    data: TenantCreateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """新建租户（仅平台管理员）。"""
    _require_platform_admin(ctx)

    name = (data.tenant_name or "").strip()
    code = (data.tenant_code or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="租户名称不能为空")
    if not code or not all(ch.isalnum() or ch in "_-" for ch in code):
        raise HTTPException(status_code=400, detail="租户编码仅支持小写字母、数字、_、-")
    if data.plan_type not in {"free", "pro", "enterprise"}:
        raise HTTPException(status_code=400, detail="plan_type 仅支持 free/pro/enterprise")
    if data.max_applications < 1 or data.max_applications > 10000:
        raise HTTPException(status_code=400, detail="max_applications 范围 1-10000")
    if data.max_workspaces < 0 or data.max_workspaces > 10000:
        raise HTTPException(status_code=400, detail="max_workspaces 范围 0-10000")
    if data.max_components < 0 or data.max_components > 10000:
        raise HTTPException(status_code=400, detail="max_components 范围 0-10000")

    existing = (
        await db.execute(select(Tenant).where(Tenant.tenant_code == code))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"租户编码 '{code}' 已存在")

    t = Tenant(
        tenant_name=name,
        tenant_code=code,
        plan_type=data.plan_type,
        max_applications=data.max_applications,
        max_workspaces=data.max_workspaces,
        max_components=data.max_components,
        status=1,
        contact_name=(data.contact_name or "").strip() or None,
        contact_email=(data.contact_email or "").strip() or None,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _tenant_admin_item(t, 0)


@router.get("/tenants/{tenant_id}/usage")
async def get_tenant_usage_endpoint(
    tenant_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """返回某租户的资源使用情况（仅平台管理员）。"""
    _require_platform_admin(ctx)
    from app.tenant_quota import get_tenant_usage as _get_usage
    return await _get_usage(db, tenant_id)


@router.put("/tenants/{tenant_id}/status", response_model=TenantAdminItem)
async def update_tenant_status(
    tenant_id: int,
    data: TenantStatusRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """启用 / 禁用租户（仅平台管理员）。被禁用的租户成员仍可见但无法切入。"""
    _require_platform_admin(ctx)

    if data.status not in (0, 1):
        raise HTTPException(status_code=400, detail="status 仅支持 0 或 1")

    t = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="租户不存在")
    t.status = data.status
    await db.commit()
    await db.refresh(t)

    from sqlalchemy import func as sql_func
    cnt = (
        await db.execute(
            select(sql_func.count(UserTenant.id))
            .where(UserTenant.tenant_id == t.id, UserTenant.status == 1)
        )
    ).scalar() or 0
    return _tenant_admin_item(t, int(cnt))


@router.get("/me/tenants", response_model=list[TenantOption])
async def list_my_tenants(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """返回当前用户可切换的租户列表（用于顶栏 dropdown）。"""
    if ctx.user.is_platform_admin:
        rows = (
            await db.execute(
                select(Tenant)
                .where(Tenant.status == 1)
                .order_by(Tenant.tenant_name.asc())
            )
        ).scalars().all()
    else:
        rows = (
            await db.execute(
                select(Tenant)
                .join(UserTenant, UserTenant.tenant_id == Tenant.id)
                .where(
                    UserTenant.user_id == ctx.user.id,
                    UserTenant.status == 1,
                )
                .order_by(Tenant.tenant_name.asc())
            )
        ).scalars().all()
    return [
        TenantOption(tenant_id=t.id, tenant_name=t.tenant_name, tenant_code=t.tenant_code)
        for t in rows
    ]


@router.get("/users")
async def list_users(ctx: Annotated[AuthContext, Depends(get_auth_context)], db: Annotated[AsyncSession, Depends(get_db)]):
    """获取同租户下的所有用户（用于团队成员选择）"""
    if ctx.tenant_id:
        result = await db.execute(
            select(User.id, User.username)
            .join(UserTenant, User.id == UserTenant.user_id)
            .where(
                UserTenant.tenant_id == ctx.tenant_id,
                UserTenant.status == 1,
                User.is_active == True,
            )
        )
    else:
        result = await db.execute(select(User.id, User.username).where(User.is_active == True))
    return [{"id": row[0], "username": row[1]} for row in result.fetchall()]


@router.get("/tenant-roles")
async def list_tenant_roles(
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if ctx.tenant_role == "platform_admin":
        return [
            {
                "id": -1,
                "role_code": "normal_user",
                "role_name": "普通账号",
                "is_system": True,
                "permissions": {},
            },
            {
                "id": 0,
                "role_code": "platform_admin",
                "role_name": "平台超级管理员",
                "is_system": True,
                "permissions": {"*": True},
            },
        ]

    result = await db.execute(
        select(Role).where(Role.tenant_id == ctx.tenant_id).order_by(Role.is_system.desc(), Role.created_at.asc())
    )
    roles = result.scalars().all()
    return [
        {
            "id": role.id,
            "role_code": role.role_code,
            "role_name": role.role_name,
            "is_system": role.is_system,
            "permissions": role.permissions or {},
        }
        for role in roles
    ]


@router.get("/tenant-users")
async def list_tenant_users(
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if ctx.tenant_role == "platform_admin":
        result = await db.execute(select(User).order_by(User.created_at.asc(), User.id.asc()))
        users = result.scalars().all()
        memberships = await _load_user_memberships(db, [user.id for user in users])
        return [_serialize_platform_user(user, memberships.get(user.id, [])) for user in users]

    result = await db.execute(
        select(UserTenant, User, Tenant, Role)
        .join(User, User.id == UserTenant.user_id)
        .join(Tenant, Tenant.id == UserTenant.tenant_id)
        .outerjoin(Role, Role.id == UserTenant.role_id)
        .where(UserTenant.tenant_id == ctx.tenant_id)
        .order_by(UserTenant.joined_at.asc(), User.created_at.asc())
    )
    rows = result.all()
    return [_serialize_tenant_user(user, membership, role, tenant) for membership, user, tenant, role in rows]


@router.post("/tenant-users/invite")
async def invite_tenant_user(
    req: InviteTenantUserRequest,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    username = (req.username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")

    role_code = (req.role_code or "R_developer").strip() or "R_developer"
    if ctx.tenant_role == "platform_admin":
        if role_code not in ("platform_admin", "normal_user"):
            raise HTTPException(status_code=400, detail="平台管理员只能创建平台超级管理员或普通账号")
        user_result = await db.execute(select(User).where(User.username == username))
        user = user_result.scalar_one_or_none()
        if not user:
            if not req.password:
                raise HTTPException(status_code=400, detail="用户不存在，请提供初始密码创建账号")
            user = User(
                username=username,
                hashed_password=get_password_hash(req.password),
                is_platform_admin=role_code == "platform_admin",
            )
            db.add(user)
            await db.flush()
        else:
            if role_code == "platform_admin":
                user.is_platform_admin = True
        user.is_active = True
        await db.commit()
        await db.refresh(user)
        memberships = await _load_user_memberships(db, [user.id])
        return _serialize_platform_user(user, memberships.get(user.id, []))

    role_result = await db.execute(
        select(Role).where(
            Role.tenant_id == ctx.tenant_id,
            Role.role_code == role_code,
        )
    )
    role = role_result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    user_result = await db.execute(select(User).where(User.username == username))
    user = user_result.scalar_one_or_none()
    if not user:
        if not req.password:
            raise HTTPException(status_code=400, detail="用户不存在，请提供初始密码创建账号")
        user = User(
            username=username,
            hashed_password=get_password_hash(req.password),
        )
        db.add(user)
        await db.flush()

    membership_result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == user.id,
            UserTenant.tenant_id == ctx.tenant_id,
        )
    )
    membership = membership_result.scalar_one_or_none()
    if membership:
        membership.status = 1
        membership.role_id = role.id
    else:
        default_result = await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == user.id,
                UserTenant.status == 1,
            )
        )
        existing_memberships = default_result.scalars().all()
        membership = UserTenant(
            user_id=user.id,
            tenant_id=ctx.tenant_id,
            role_id=role.id,
            is_default=not existing_memberships,
            status=1,
        )
        db.add(membership)

    await db.commit()
    await db.refresh(membership)
    return _serialize_tenant_user(user, membership, role)


@router.put("/tenant-users/{user_id}/status")
async def update_tenant_user_status(
    user_id: int,
    req: UpdateTenantUserStatusRequest,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if req.status not in (0, 1):
        raise HTTPException(status_code=400, detail="status 只能是 0 或 1")
    if user_id == ctx.user.id:
        raise HTTPException(status_code=400, detail="不能在当前会话里禁用自己")

    if ctx.tenant_role == "platform_admin":
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        user.is_active = req.status == 1
        await db.commit()
        await db.refresh(user)
        memberships = await _load_user_memberships(db, [user.id])
        return _serialize_platform_user(user, memberships.get(user.id, []))

    result = await db.execute(
        select(UserTenant, User, Role)
        .join(User, User.id == UserTenant.user_id)
        .outerjoin(Role, Role.id == UserTenant.role_id)
        .where(
            UserTenant.tenant_id == ctx.tenant_id,
            UserTenant.user_id == user_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="租户成员不存在")

    membership, user, role = row
    membership.status = req.status
    await db.commit()
    await db.refresh(membership)
    return _serialize_tenant_user(user, membership, role)


@router.put("/tenant-users/{user_id}/role")
async def update_tenant_user_role(
    user_id: int,
    req: UpdateTenantUserRoleRequest,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if ctx.tenant_role == "platform_admin":
        if req.role_code not in ("platform_admin", "normal_user"):
            raise HTTPException(status_code=400, detail="平台管理员只能切换平台超级管理员或普通账号")
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if user_id == ctx.user.id and req.role_code != "platform_admin":
            raise HTTPException(status_code=400, detail="不能取消自己的平台超级管理员权限")
        user.is_platform_admin = req.role_code == "platform_admin"
        await db.commit()
        await db.refresh(user)
        memberships = await _load_user_memberships(db, [user.id])
        return _serialize_platform_user(user, memberships.get(user.id, []))

    membership_result = await db.execute(
        select(UserTenant, User)
        .join(User, User.id == UserTenant.user_id)
        .where(
            UserTenant.tenant_id == ctx.tenant_id,
            UserTenant.user_id == user_id,
        )
    )
    membership_row = membership_result.one_or_none()
    if not membership_row:
        raise HTTPException(status_code=404, detail="租户成员不存在")

    membership, user = membership_row
    role_result = await db.execute(
        select(Role).where(
            Role.tenant_id == ctx.tenant_id,
            Role.role_code == req.role_code,
        )
    )
    role = role_result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    if user_id == ctx.user.id and role.role_code not in ("R_tenant_admin", "admin"):
        raise HTTPException(status_code=400, detail="不能把自己降级为非管理员")

    membership.role_id = role.id
    await db.commit()
    await db.refresh(membership)
    return _serialize_tenant_user(user, membership, role)


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
        tenant_role=ctx.tenant_role,
        org_permissions=ctx.org_permissions or {}
    )
