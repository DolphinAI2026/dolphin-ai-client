"""Skill catalog — list available skills for /agents binding UI."""
from __future__ import annotations
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models.skill_catalog import AgentSkillCatalog
from app.services.skill_catalog_discover import discover_skills

router = APIRouter(prefix="/skills", tags=["skill-catalog"])


class SkillItem(BaseModel):
    code: str
    name: str
    desc: str
    category: str
    callable_path: str
    is_async: bool
    is_active: bool


class SkillCatalogResp(BaseModel):
    skills: list[SkillItem]
    total: int


@router.get("/catalog", response_model=SkillCatalogResp)
async def list_catalog(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Lazy discover on first call
    await discover_skills(db)

    rows = (await db.execute(
        select(AgentSkillCatalog)
        .where(AgentSkillCatalog.is_active == True)  # noqa: E712
        .order_by(AgentSkillCatalog.category, AgentSkillCatalog.code)
    )).scalars().all()
    return SkillCatalogResp(
        skills=[
            SkillItem(
                code=r.code, name=r.name, desc=r.desc, category=r.category,
                callable_path=r.callable_path, is_async=r.is_async, is_active=r.is_active,
            )
            for r in rows
        ],
        total=len(rows),
    )
