# backend/app/routes/agent_prompts.py
"""V2 Agent Prompt CRUD — /api/agent-prompts/:agent_id.

`GET  /api/agent-prompts/{agent_id}`          — list per-phase prompts.
`PUT  /api/agent-prompts/{agent_id}/{phase}`  — update one phase's template.

For agent_id='builder', if no rows exist for the current tenant the
endpoint lazy-seeds them from `app.builder_spec.agent` module constants
so the admin UI never sees an empty list on first load.

NOTE: this router is NOT yet registered in main.py — Phase E coordinator
will mount it together with the binding UI work.
"""
from __future__ import annotations
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models.agent_prompt import AgentPrompt
from app.services.agent_prompt_seed import seed_agent_prompts_for_tenant

router = APIRouter(prefix="/agent-prompts", tags=["agent-prompts"])


class PromptItem(BaseModel):
    phase: str
    template: str
    notes: Optional[str] = None
    version: int


class PromptListResp(BaseModel):
    agent_id: str
    prompts: list[PromptItem]


class PromptUpdateReq(BaseModel):
    template: str
    notes: Optional[str] = None


@router.get("/{agent_id}", response_model=PromptListResp)
async def list_prompts(
    agent_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Lazy seed so admin always sees defaults on first load:
    #   builder            → seed_agent_prompts_for_tenant (builder_spec module constants)
    #   whale / unified    → seed_coding_prompts_for_tenant (coding + unified constants)
    has_any = (await db.execute(
        select(AgentPrompt).where(
            AgentPrompt.tenant_id == ctx.tenant_id,
            AgentPrompt.agent_id == agent_id,
        ).limit(1)
    )).scalar_one_or_none()
    if not has_any:
        if agent_id == "builder":
            await seed_agent_prompts_for_tenant(db, ctx.tenant_id)
        elif agent_id in ("whale", "unified"):
            from app.services.coding_prompt_seed import seed_coding_prompts_for_tenant
            await seed_coding_prompts_for_tenant(db, ctx.tenant_id)

    rows = (await db.execute(
        select(AgentPrompt)
        .where(
            AgentPrompt.tenant_id == ctx.tenant_id,
            AgentPrompt.agent_id == agent_id,
        )
        .order_by(AgentPrompt.phase)
    )).scalars().all()
    return PromptListResp(
        agent_id=agent_id,
        prompts=[
            PromptItem(
                phase=r.phase,
                template=r.template,
                notes=r.notes,
                version=r.version,
            )
            for r in rows
        ],
    )


@router.put("/{agent_id}/{phase}", response_model=PromptItem)
async def update_prompt(
    agent_id: str,
    phase: str,
    payload: PromptUpdateReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = (await db.execute(
        select(AgentPrompt).where(
            AgentPrompt.tenant_id == ctx.tenant_id,
            AgentPrompt.agent_id == agent_id,
            AgentPrompt.phase == phase,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, f"prompt {agent_id}/{phase} not found")
    row.template = payload.template
    if payload.notes is not None:
        row.notes = payload.notes
    row.version += 1
    await db.commit()
    await db.refresh(row)
    return PromptItem(
        phase=row.phase,
        template=row.template,
        notes=row.notes,
        version=row.version,
    )
