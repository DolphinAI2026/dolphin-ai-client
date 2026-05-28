"""租户资源配额校验。

3 类资源：
  - applications：低代码应用（applications 表，按 tenant_id 计数）
  - workspaces：Vibe Coding 工作区（文件系统 _online_coding/<tenant>/oc_xxx）
  - components：自开发组件（marketplace_components 表）

配额字段位于 tenants 表（max_applications / max_workspaces / max_components）。
平台管理员代客户操作时也按 ctx.tenant_id 当前租户的配额计；调整配额是显式工作流。
"""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, MarketplaceComponent
from app.models.tenant import Tenant, UserTenant


ResourceKind = Literal["applications", "workspaces", "components"]

_LIMIT_FIELD: dict[ResourceKind, str] = {
    "applications": "max_applications",
    "workspaces": "max_workspaces",
    "components": "max_components",
}

_LABEL_CN: dict[ResourceKind, str] = {
    "applications": "低代码应用",
    "workspaces": "Vibe Coding 工作区",
    "components": "自开发组件",
}


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
    """Vibe Coding workspace 是文件系统态，扫 meta 数。"""
    # 延迟 import 避免循环依赖
    from app.routes.online_coding import _iter_workspace_meta_dirs, _meta_path
    import json

    count = 0
    for ws_dir in _iter_workspace_meta_dirs():
        try:
            meta = json.loads(_meta_path(ws_dir).read_text(encoding="utf-8"))
        except Exception:
            continue
        if int(meta.get("tenant_id") or 0) == int(tenant_id):
            count += 1
    return count


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
    """资源创建前调用：超额时 raise 409。"""
    tenant = await get_tenant_or_404(db, tenant_id)
    if tenant.status != 1:
        raise HTTPException(status_code=403, detail="租户已被禁用，无法创建新资源")

    if resource == "applications":
        used = await _count_applications(db, tenant_id)
    elif resource == "components":
        used = await _count_components(db, tenant_id)
    elif resource == "workspaces":
        used = _count_workspaces(tenant_id)
    else:
        raise ValueError(f"未知资源类型: {resource}")

    limit = getattr(tenant, _LIMIT_FIELD[resource])
    # 2026-05-28: limit <= 0 / None = 不限制 (off switch). 给某租户设 max_applications=0
    # 即"该租户应用数量无上限" —— trial / 内部测试租户用, 不必再撞 10 上限。
    if limit and limit > 0 and used >= limit:
        raise HTTPException(
            status_code=409,
            detail=(
                f"租户「{tenant.tenant_name}」已达{_LABEL_CN[resource]}数量上限"
                f"（{used}/{limit}），请联系平台管理员调整配额"
            ),
        )
