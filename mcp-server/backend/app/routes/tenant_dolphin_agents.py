"""tenant_dolphin_agents CRUD endpoints — 2026-05-11

dolphin agent 配置升级为 per-tenant N 行表，本路由提供 list/create/update/delete。
权限分级：
- list: 当前 tenant 成员可看（NavRail / 浮窗都要拉）
- create/update/delete: tenant_admin 改自己 tenant；platform_admin 改所有 tenant

唯一约束：(tenant_id, agent_code) — 同一租户内同一 agent code 不能重复挂多次。
is_default：每个 tenant 最多一行可为 True（保存时自动把其他行置 False）。
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models import Tenant, TenantDolphinAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenant-dolphin-agents", tags=["tenant-dolphin-agents"])


# ─────────────── 权限工具 ───────────────


def _can_admin_tenant(ctx: AuthContext, tenant_id: int) -> bool:
    """platform_admin 改所有；tenant_admin 改自己当前 tenant。"""
    if ctx.user.is_platform_admin:
        return True
    if ctx.tenant_role == "tenant_admin" and ctx.tenant_id == tenant_id:
        return True
    return False


def _require_admin(ctx: AuthContext, tenant_id: int) -> None:
    if not _can_admin_tenant(ctx, tenant_id):
        raise HTTPException(status_code=403, detail="需要平台管理员或当前租户管理员权限")


# ─────────────── pydantic schemas ───────────────


class AgentItem(BaseModel):
    id: int
    tenant_id: int
    agent_code: str
    instance_id: str
    display_name: str
    description: Optional[str] = None
    nav_path: Optional[str] = None
    nav_icon: Optional[str] = None
    sort_order: int = 100
    button_text: Optional[str] = None
    is_default: bool = False
    status: int = 1


class AgentCreatePayload(BaseModel):
    tenant_id: Optional[int] = None  # 不传用 ctx.tenant_id
    agent_code: str
    instance_id: str
    display_name: str
    description: Optional[str] = None
    nav_path: Optional[str] = None
    nav_icon: Optional[str] = None
    sort_order: int = 100
    button_text: Optional[str] = None
    is_default: bool = False
    status: int = 1


class AgentUpdatePayload(BaseModel):
    agent_code: Optional[str] = None
    instance_id: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    nav_path: Optional[str] = None
    nav_icon: Optional[str] = None
    sort_order: Optional[int] = None
    button_text: Optional[str] = None
    is_default: Optional[bool] = None
    status: Optional[int] = None


def _serialize(a: TenantDolphinAgent) -> AgentItem:
    return AgentItem(
        id=a.id,
        tenant_id=a.tenant_id,
        agent_code=a.agent_code,
        instance_id=a.instance_id,
        display_name=a.display_name,
        description=a.description,
        nav_path=a.nav_path,
        nav_icon=a.nav_icon,
        sort_order=a.sort_order,
        button_text=a.button_text,
        is_default=bool(a.is_default),
        status=a.status,
    )


# ─────────────── endpoints ───────────────


@router.get("", response_model=list[AgentItem])
async def list_agents(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Optional[int] = None,
    only_nav: bool = False,
):
    """列出 agent 入口（默认当前 tenant；platform_admin 可指定 tenant_id）.

    only_nav=true 时仅返回 nav_path 非空 + status=1 的 entry（NavRail 用）。
    """
    target_tid = tenant_id if tenant_id else ctx.tenant_id
    if tenant_id and tenant_id != ctx.tenant_id and not ctx.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="跨 tenant 查询需平台管理员权限")

    stmt = (
        select(TenantDolphinAgent)
        .where(TenantDolphinAgent.tenant_id == target_tid)
        .order_by(TenantDolphinAgent.sort_order, TenantDolphinAgent.id)
    )
    if only_nav:
        stmt = stmt.where(
            TenantDolphinAgent.nav_path.is_not(None),
            TenantDolphinAgent.status == 1,
        )
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize(a) for a in rows]


@router.post("", response_model=AgentItem)
async def create_agent(
    data: AgentCreatePayload,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """新建 agent 入口."""
    target_tid = data.tenant_id if data.tenant_id else ctx.tenant_id
    _require_admin(ctx, target_tid)

    # 校验 tenant 存在
    t = (await db.execute(select(Tenant).where(Tenant.id == target_tid))).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail=f"tenant_id={target_tid} 不存在")

    # 唯一约束 (tenant_id, agent_code)
    code = (data.agent_code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="agent_code 必填")
    existing = (
        await db.execute(
            select(TenantDolphinAgent).where(
                TenantDolphinAgent.tenant_id == target_tid,
                TenantDolphinAgent.agent_code == code,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"tenant {target_tid} 已有 agent_code={code} 的入口，不能重复添加",
        )

    if not (data.instance_id or "").strip():
        raise HTTPException(status_code=400, detail="instance_id 必填")
    if not (data.display_name or "").strip():
        raise HTTPException(status_code=400, detail="display_name 必填")

    row = TenantDolphinAgent(
        tenant_id=target_tid,
        agent_code=code,
        instance_id=data.instance_id.strip(),
        display_name=data.display_name.strip(),
        description=(data.description or "").strip() or None,
        nav_path=(data.nav_path or "").strip() or None,
        nav_icon=(data.nav_icon or "").strip() or None,
        sort_order=data.sort_order if data.sort_order is not None else 100,
        button_text=(data.button_text or "").strip() or None,
        is_default=bool(data.is_default),
        status=int(data.status) if data.status is not None else 1,
    )
    db.add(row)

    # is_default 互斥：本行=True 时把同 tenant 其他行置 False
    if row.is_default:
        await db.execute(
            sql_update(TenantDolphinAgent)
            .where(TenantDolphinAgent.tenant_id == target_tid)
            .values(is_default=False)
        )
        row.is_default = True

    await db.commit()
    await db.refresh(row)
    logger.info(
        "tenant_dolphin_agents create tenant=%s agent_code=%s nav_path=%s by user=%s",
        target_tid, code, row.nav_path, ctx.user.id,
    )
    return _serialize(row)


@router.put("/{agent_id}", response_model=AgentItem)
async def update_agent(
    agent_id: int,
    data: AgentUpdatePayload,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """编辑 agent 入口."""
    row = (
        await db.execute(select(TenantDolphinAgent).where(TenantDolphinAgent.id == agent_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="agent 入口不存在")
    _require_admin(ctx, row.tenant_id)

    # 修改 agent_code 时检查唯一性（同 tenant 不能重复）
    if data.agent_code is not None and data.agent_code.strip() != row.agent_code:
        new_code = data.agent_code.strip()
        if not new_code:
            raise HTTPException(status_code=400, detail="agent_code 不能空")
        dup = (
            await db.execute(
                select(TenantDolphinAgent).where(
                    TenantDolphinAgent.tenant_id == row.tenant_id,
                    TenantDolphinAgent.agent_code == new_code,
                    TenantDolphinAgent.id != agent_id,
                )
            )
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"tenant {row.tenant_id} 已有 agent_code={new_code} 的入口",
            )
        row.agent_code = new_code

    for field in ("instance_id", "display_name"):
        val = getattr(data, field)
        if val is not None:
            stripped = val.strip()
            if not stripped:
                raise HTTPException(status_code=400, detail=f"{field} 不能空")
            setattr(row, field, stripped)

    for field in ("description", "nav_path", "nav_icon", "button_text"):
        val = getattr(data, field)
        if val is not None:
            setattr(row, field, val.strip() or None)

    if data.sort_order is not None:
        row.sort_order = int(data.sort_order)
    if data.status is not None:
        row.status = int(data.status)

    if data.is_default is not None:
        if data.is_default:
            # 同 tenant 其他行置 False
            await db.execute(
                sql_update(TenantDolphinAgent)
                .where(
                    TenantDolphinAgent.tenant_id == row.tenant_id,
                    TenantDolphinAgent.id != agent_id,
                )
                .values(is_default=False)
            )
        row.is_default = bool(data.is_default)

    await db.commit()
    await db.refresh(row)
    logger.info(
        "tenant_dolphin_agents update id=%s tenant=%s by user=%s",
        agent_id, row.tenant_id, ctx.user.id,
    )
    return _serialize(row)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除 agent 入口."""
    row = (
        await db.execute(select(TenantDolphinAgent).where(TenantDolphinAgent.id == agent_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="agent 入口不存在")
    _require_admin(ctx, row.tenant_id)

    await db.delete(row)
    await db.commit()
    logger.info(
        "tenant_dolphin_agents delete id=%s tenant=%s by user=%s",
        agent_id, row.tenant_id, ctx.user.id,
    )
    return {"ok": True}
