"""桌面产品账号: 建号(带独立租户) + 校验。与 aPaaS 登录链路完全无关。"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_password_hash, verify_password
from app.models import User
from app.models.tenant import Tenant, UserTenant, Role
from app.seed_data import seed_default_roles


class AccountExistsError(Exception):
    pass


async def _unique_tenant_code(db: AsyncSession, base: str) -> str:
    code = base
    n = 1
    while (await db.execute(select(Tenant).where(Tenant.tenant_code == code))).scalar_one_or_none():
        n += 1
        code = f"{base}-{n}"
    return code


async def _provision(
    db: AsyncSession, username: str, password: str, *, is_platform_admin: bool
) -> User:
    existing = (await db.execute(
        select(User).where(User.username == username, User.account_source == "desktop")
    )).scalar_one_or_none()
    if existing:
        raise AccountExistsError(username)
    code = await _unique_tenant_code(db, f"desktop-{username}")
    tenant = Tenant(tenant_name=f"{username} 的工作空间", tenant_code=code, status=1, max_applications=100)
    db.add(tenant)
    await db.flush()
    await seed_default_roles(db, tenant.id, commit=False)
    user = User(
        username=username, display_name=username,
        hashed_password=get_password_hash(password),
        is_active=True, is_platform_admin=is_platform_admin, account_source="desktop",
    )
    db.add(user)
    await db.flush()
    admin_role = (await db.execute(
        select(Role).where(Role.tenant_id == tenant.id, Role.role_code == "R_tenant_admin")
    )).scalar_one_or_none()
    if admin_role is None:
        # 不能静默降级为无角色成员 —— 否则用户进自己租户却过不了 require_tenant_admin(403)。
        raise RuntimeError(f"seed_default_roles 未产出 R_tenant_admin (tenant {tenant.id})")
    db.add(UserTenant(
        user_id=user.id, tenant_id=tenant.id,
        role_id=admin_role.id,
        is_default=True, status=1,
    ))
    await db.flush()
    return user


async def provision_desktop_account(db: AsyncSession, username: str, password: str) -> User:
    """federation 镜像 + 公网 admin 开号。**永远 is_platform_admin=False** —— 结构上
    不接受该参, 杜绝跨 federation 提权 (信任边界铁律)。

    只 flush 不 commit —— 事务边界由调用方负责(便于组合进更大事务)。
    """
    return await _provision(db, username, password, is_platform_admin=False)


async def provision_local_admin_account(db: AsyncSession, username: str, password: str) -> User:
    """仅本机 authority 单机自洽开号 (seed_desktop_account.py): 本机管理员。
    绝不可经任何公网/federation 路径调用。

    只 flush 不 commit —— 事务边界由调用方负责(便于组合进更大事务)。
    """
    return await _provision(db, username, password, is_platform_admin=True)


async def verify_desktop_account(db: AsyncSession, username: str, password: str) -> Optional[User]:
    user = (await db.execute(
        select(User).where(User.username == username, User.account_source == "desktop")
    )).scalar_one_or_none()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
