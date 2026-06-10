"""租户资源使用统计与创建保护。

历史上这里会按 tenants.max_* 字段拦截资源创建。当前部署形态不再限制
低代码应用 / 工作区 / 组件数量，因此创建前只检查租户是否启用。
"""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, MarketplaceComponent
from app.models.tenant import Tenant, UserTenant


ResourceKind = Literal["applications", "workspaces", "components"]

async def _count_applications(db: AsyncSession, tenant_id: int) -> int:
    res = await db.execute(
        select(func.count(Application.id)).where(Application.tenant_id == tenant_id)
    )
    return int(res.scalar() or 0)


async def _count_components(db: AsyncSession, tenant_id: int) -> int:
    res = await db.execute(
        select(func.count(MarketplaceComponent.id)).where(
            MarketplaceComponent.tenant_id == tenant_id
        )
    )
    return int(res.scalar() or 0)


def _count_workspaces(tenant_id: int) -> int:
    """Vibe Coding 已下线（2026-05-29），工作区统计恒为 0。"""
    return 0


async def _count_members(db: AsyncSession, tenant_id: int) -> int:
    res = await db.execute(
        select(func.count(UserTenant.id)).where(
            UserTenant.tenant_id == tenant_id, UserTenant.status == 1
        )
    )
    return int(res.scalar() or 0)


async def get_tenant_or_404(db: AsyncSession, tenant_id: int) -> Tenant:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")
    return tenant


async def get_tenant_usage(db: AsyncSession, tenant_id: int) -> dict:
    """返回当前租户各资源使用情况。

    形如 {applications: {used, max}, workspaces: ..., components: ..., members: int}
    """
    tenant = await get_tenant_or_404(db, tenant_id)
    apps = await _count_applications(db, tenant_id)
    comps = await _count_components(db, tenant_id)
    workspaces = _count_workspaces(tenant_id)
    members = await _count_members(db, tenant_id)
    return {
        "applications": {"used": apps, "max": tenant.max_applications},
        "workspaces": {"used": workspaces, "max": tenant.max_workspaces},
        "components": {"used": comps, "max": tenant.max_components},
        "members": members,
    }


async def assert_tenant_quota(
    db: AsyncSession, tenant_id: int, resource: ResourceKind
) -> None:
    """资源创建前调用：只校验租户启用状态，不做数量上限拦截。"""
    tenant = await get_tenant_or_404(db, tenant_id)
    if tenant.status != 1:
        raise HTTPException(status_code=403, detail="租户已被禁用，无法创建新资源")
    if resource not in ("applications", "components", "workspaces"):
        raise ValueError(f"未知资源类型: {resource}")
