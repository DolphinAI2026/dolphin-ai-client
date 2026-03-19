"""Seed data for multi-tenant system."""
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.tenant import Tenant, Role
from app.permissions import PERMISSION_CODES


async def seed_default_roles(db: AsyncSession, tenant_id: int):
    """创建默认角色（租户管理员、开发者、查看者）"""

    # 检查是否已存在角色
    result = await db.execute(
        select(Role).where(Role.tenant_id == tenant_id).limit(1)
    )
    if result.scalar_one_or_none():
        return  # 已有角色，跳过

    # 1. 租户管理员 — 全部权限
    admin_permissions = {code: True for code in PERMISSION_CODES}
    admin_role = Role(
        tenant_id=tenant_id,
        role_name="租户管理员",
        role_code="R_tenant_admin",
        description="租户管理员，拥有全部权限",
        permissions=admin_permissions,
        is_system=True
    )
    db.add(admin_role)

    # 2. 开发者 — 应用和对话的全部权限
    developer_permissions = {
        "application:view": True,
        "application:create": True,
        "application:edit": True,
        "application:delete": True,
        "application:clone": True,
        "conversation:view": True,
        "conversation:create": True,
        "conversation:delete": True,
        "team:view": True,
    }
    developer_role = Role(
        tenant_id=tenant_id,
        role_name="开发者",
        role_code="R_developer",
        description="开发者，可以创建和管理应用",
        permissions=developer_permissions,
        is_system=False
    )
    db.add(developer_role)

    # 3. 查看者 — 只读权限
    viewer_permissions = {
        "application:view": True,
        "conversation:view": True,
    }
    viewer_role = Role(
        tenant_id=tenant_id,
        role_name="查看者",
        role_code="R_viewer",
        description="查看者，只能查看应用和对话",
        permissions=viewer_permissions,
        is_system=False
    )
    db.add(viewer_role)

    await db.commit()
    print(f"✅ 租户 {tenant_id} 的默认角色已创建")


async def seed_initial_data(db: AsyncSession):
    """初始化种子数据"""

    # 1. 检查是否已有默认租户
    result = await db.execute(
        select(Tenant).where(Tenant.tenant_code == "default")
    )
    default_tenant = result.scalar_one_or_none()

    if not default_tenant:
        # 创建默认租户（迁移脚本已创建，这里是兜底）
        default_tenant = Tenant(
            tenant_name="Default Tenant",
            tenant_code="default",
            plan_type="free",
            max_applications=100,
            status=1
        )
        db.add(default_tenant)
        await db.commit()
        await db.refresh(default_tenant)
        print(f"✅ 默认租户已创建，ID: {default_tenant.id}")

    # 2. 为默认租户创建角色
    await seed_default_roles(db, default_tenant.id)
