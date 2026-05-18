"""
/api/specs-v2 — SPEC 列表（v2 SpecsPage 视图）

每个应用合成一个版本占位 (v1)，状态依据 apaas_app_id 是否存在决定是 draft
还是 prod。真实多版本 + diff 后续由专门的 SPEC 版本管理接力。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models import Application

router = APIRouter(prefix="/specs-v2", tags=["specs-v2"])


class SpecVersionItem(BaseModel):
    v: int
    status: str  # draft / test / prod / archived
    note: str
    author: str
    date: str


class SpecSection(BaseModel):
    name: str
    count: int


class SpecListItem(BaseModel):
    id: str
    app_id: int
    app_name: str
    latest: int
    diff_add: int
    diff_mod: int
    origin: str
    versions: list[SpecVersionItem]
    sections: list[SpecSection]
    excerpt: str = ""


class SpecListResponse(BaseModel):
    specs: list[SpecListItem]
    total: int


@router.get("", response_model=SpecListResponse)
async def list_specs(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SpecListResponse:
    """列出当前租户所有应用对应的 SPEC（每个应用一个合成版本）。"""
    apps_result = await db.execute(
        select(Application)
        .where(Application.tenant_id == ctx.tenant_id)
        .order_by(Application.updated_at.desc())
    )
    apps = apps_result.scalars().all()

    out: list[SpecListItem] = []
    author_name = getattr(ctx.user, "username", "—") or "—"

    for app in apps:
        date_str = "—"
        if getattr(app, "updated_at", None):
            try:
                date_str = app.updated_at.strftime("%Y-%m-%d")
            except Exception:
                date_str = "—"

        is_deployed = bool(getattr(app, "apaas_app_id", None))
        out.append(SpecListItem(
            id=f"spec-{app.id}",
            app_id=app.id,
            app_name=app.app_name,
            latest=1,
            diff_add=0,
            diff_mod=0,
            origin="—",
            versions=[SpecVersionItem(
                v=1,
                status="prod" if is_deployed else "draft",
                note="—",
                author=author_name,
                date=date_str,
            )],
            sections=[
                SpecSection(name="需求摘要", count=1),
                SpecSection(name="数据模型", count=0),
                SpecSection(name="表单", count=0),
                SpecSection(name="流程", count=0),
                SpecSection(name="角色权限", count=0),
                SpecSection(name="字典", count=0),
            ],
            excerpt="",
        ))

    return SpecListResponse(specs=out, total=len(out))
