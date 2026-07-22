import logging
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import get_password_hash
from app.models import User
from app.models.tenant import Tenant, UserTenant, Role
from app.deps import (
    AuthContext,
    get_platform_auth_context,
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Helpers (imported from tenants_admin to avoid duplication) ───────────────

def _require_platform_admin(ctx: AuthContext) -> None:
    if ctx.user.is_platform_admin or ctx.tenant_role == "platform_admin":
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台管理员可执行此操作")


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


# ─── Pydantic models ───────────────────────────────────────────────────────────

class TenantMemberAddRequest(BaseModel):
    username: str
    password: Optional[str] = None
    role_code: Optional[str] = None  # 默认 R_developer


class TenantMemberItem(BaseModel):
    user_id: int
    username: str
    display_name: Optional[str] = None
    is_active: bool
    is_platform_admin: bool
    tenant_role: str  # tenant_admin / developer / viewer / member
    role_code: Optional[str] = None
    role_name: Optional[str] = None
    joined_at: Optional[str] = None
    is_default: bool = False


class TenantMemberRoleUpdateRequest(BaseModel):
    role_code: str


# ─── Helper functions ──────────────────────────────────────────────────────────

def _serialize_tenant_member(
    user: User, membership: UserTenant, role: Optional[Role]
) -> TenantMemberItem:
    tenant_role, role_name, _perms = _resolve_tenant_role(role)
    return TenantMemberItem(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        is_active=user.is_active,
        is_platform_admin=user.is_platform_admin,
        tenant_role=tenant_role,
        role_code=role.role_code if role else None,
        role_name=role_name,
        joined_at=membership.joined_at.isoformat() if membership.joined_at else None,
        is_default=bool(membership.is_default),
    )


# ─── Routes ────────────────────────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/members", response_model=list[TenantMemberItem])
async def list_tenant_members(
    tenant_id: int,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出指定租户的成员（仅平台管理员）。"""
    _require_platform_admin(ctx)
    # tenant 存在性
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    rows = (
        await db.execute(
            select(UserTenant, User, Role)
            .join(User, User.id == UserTenant.user_id)
            .outerjoin(Role, Role.id == UserTenant.role_id)
            .where(UserTenant.tenant_id == tenant_id, UserTenant.status == 1)
            .order_by(UserTenant.joined_at.asc())
        )
    ).all()
    return [_serialize_tenant_member(user, m, role) for m, user, role in rows]


@router.get("/tenants/{tenant_id}/roles")
async def list_roles_for_tenant(
    tenant_id: int,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出指定租户角色（仅平台管理员）。

    平台管理页在任意租户下添加/调整成员时不能使用当前 token 的租户角色，
    必须读取目标租户自己的角色清单。
    """
    _require_platform_admin(ctx)
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    rows = (
        await db.execute(
            select(Role)
            .where(Role.tenant_id == tenant_id)
            .order_by(Role.is_system.desc(), Role.created_at.asc(), Role.id.asc())
        )
    ).scalars().all()
    return [
        {
            "id": role.id,
            "role_code": role.role_code,
            "role_name": role.role_name,
            "is_system": role.is_system,
            "permissions": role.permissions or {},
        }
        for role in rows
    ]


@router.post("/tenants/{tenant_id}/members", response_model=TenantMemberItem)
async def add_tenant_member(
    tenant_id: int,
    data: TenantMemberAddRequest,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """跨租户给指定租户加成员（仅平台管理员）。

    若用户名不存在则用 password 新建账号；已存在则只建/激活 UserTenant 关系。
    role_code 默认 R_developer，可传 R_tenant_admin / R_developer / R_viewer / member。
    """
    _require_platform_admin(ctx)

    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    username = (data.username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")

    role_code = (data.role_code or "R_developer").strip() or "R_developer"
    role = (
        await db.execute(
            select(Role).where(Role.tenant_id == tenant_id, Role.role_code == role_code)
        )
    ).scalar_one_or_none()
    if not role:
        # 找不到该 tenant 的同 code 角色，按优先级回退（兼容 init_db 种的 admin / 新版 seed 种的 R_tenant_admin）
        for fallback in ("R_developer", "R_tenant_admin", "admin"):
            role = (
                await db.execute(
                    select(Role).where(Role.tenant_id == tenant_id, Role.role_code == fallback)
                )
            ).scalar_one_or_none()
            if role:
                break
    if not role:
        raise HTTPException(status_code=404, detail="该租户未配置角色，请先创建角色")

    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if not user:
        if not data.password:
            raise HTTPException(status_code=400, detail="用户不存在，请提供初始密码创建账号")
        user = User(username=username, hashed_password=get_password_hash(data.password), is_active=True)
        db.add(user)
        await db.flush()

    membership = (
        await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == user.id, UserTenant.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if membership:
        membership.status = 1
        membership.role_id = role.id
    else:
        # 用户没有任何 active membership 时把这条设为 default
        existing_default = (
            await db.execute(
                select(UserTenant).where(
                    UserTenant.user_id == user.id, UserTenant.status == 1
                )
            )
        ).scalars().all()
        membership = UserTenant(
            user_id=user.id,
            tenant_id=tenant_id,
            role_id=role.id,
            is_default=not existing_default,
            status=1,
        )
        db.add(membership)

    await db.commit()
    await db.refresh(membership)
    return _serialize_tenant_member(user, membership, role)


@router.put("/tenants/{tenant_id}/members/{user_id}/role", response_model=TenantMemberItem)
async def update_tenant_member_role(
    tenant_id: int,
    user_id: int,
    data: TenantMemberRoleUpdateRequest,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """改租户内某个成员的角色（仅平台管理员）。

    防呆：不能把自己（当前激活租户里）从管理员降级成普通成员，避免锁死。
    """
    _require_platform_admin(ctx)

    role_code = (data.role_code or "").strip()
    if not role_code:
        raise HTTPException(status_code=400, detail="role_code 不能为空")

    # 查 membership
    res = await db.execute(
        select(UserTenant, User)
        .join(User, User.id == UserTenant.user_id)
        .where(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id)
    )
    row = res.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="该用户不是该租户成员")
    membership, user = row

    # 查 role
    role = (
        await db.execute(
            select(Role).where(Role.tenant_id == tenant_id, Role.role_code == role_code)
        )
    ).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail=f"该租户下没有角色 '{role_code}'")

    # 防呆：不能把自己从当前激活的租户管理员降级（避免操作完发现自己没权限）
    if (
        ctx.user.id == user_id
        and ctx.tenant_id == tenant_id
        and role_code not in ("admin", "R_tenant_admin")
    ):
        # 看一下被改的当前角色是不是 admin
        old_role = (
            await db.execute(select(Role).where(Role.id == membership.role_id))
        ).scalar_one_or_none()
        if old_role and old_role.role_code in ("admin", "R_tenant_admin"):
            raise HTTPException(
                status_code=400,
                detail="不能把自己从当前激活租户的管理员降级，请先切换租户后再改",
            )

    membership.role_id = role.id
    await db.commit()
    await db.refresh(membership)
    return _serialize_tenant_member(user, membership, role)


@router.delete("/tenants/{tenant_id}/members/{user_id}")
async def remove_tenant_member(
    tenant_id: int,
    user_id: int,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """把成员从租户移除（仅平台管理员）。

    硬删 UserTenant 行（不是软删）；不动 User 账号本身。
    保护：不能把自己从当前激活租户移除。
    """
    _require_platform_admin(ctx)

    if ctx.user.id == user_id and ctx.tenant_id == tenant_id:
        raise HTTPException(status_code=400, detail="不能把自己从当前激活的租户中移除")

    membership = (
        await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=404, detail="该用户不是该租户成员")

    await db.delete(membership)
    await db.commit()
    return {"ok": True, "tenant_id": tenant_id, "user_id": user_id}
