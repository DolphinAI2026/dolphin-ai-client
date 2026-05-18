# backend/app/routes/agents_config.py
"""V2 Agent Config CRUD — /api/agents.

`GET /api/agents` lazy-seeds the 3 default agents on first read for a tenant.
`PUT /api/agents/{agent_id}` updates model / system_prompt.

Router prefix here is `/agents` — `app.include_router(..., prefix="/api")` in
main.py adds the `/api` segment.
"""
from __future__ import annotations
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models.agent_config import (
    AgentConfig, AgentSkill, AgentMcpBinding, AgentKnowledgeBinding,
)
from app.services.agent_seed import seed_agents_for_tenant

router = APIRouter(prefix="/agents", tags=["agents-v2"])


class SkillItem(BaseModel):
    code: str
    name: str
    desc: str


class AgentKnowledge(BaseModel):
    industry_packs: list[str]
    spec_templates: list[str]


class AgentConfigResp(BaseModel):
    id: str
    name: str
    role: str
    desc: str
    tone: str
    icon: str
    model: str
    model_options: list[str]
    system_prompt: str
    context_window: int
    max_output: int
    active_calls: int
    today_calls: int
    skills: list[SkillItem]
    mcps: list[str]
    knowledge: AgentKnowledge


class AgentListResp(BaseModel):
    agents: list[AgentConfigResp]


class AgentUpdateReq(BaseModel):
    model: Optional[str] = None
    system_prompt: Optional[str] = None


def _to_resp(
    cfg: AgentConfig,
    skills: list[AgentSkill],
    mcps: list[AgentMcpBinding],
    knowledge: list[AgentKnowledgeBinding],
) -> AgentConfigResp:
    industry_packs = [k.ref_id for k in sorted(knowledge, key=lambda x: x.order_idx) if k.kind == "industry_pack"]
    spec_templates = [k.ref_id for k in sorted(knowledge, key=lambda x: x.order_idx) if k.kind == "spec_template"]
    return AgentConfigResp(
        id=cfg.agent_id,
        name=cfg.name,
        role=cfg.role,
        desc=cfg.desc or "",
        tone=cfg.tone,
        icon=cfg.icon,
        model=cfg.model,
        model_options=cfg.model_options or [],
        system_prompt=cfg.system_prompt or "",
        context_window=cfg.context_window,
        max_output=cfg.max_output,
        active_calls=cfg.active_calls,
        today_calls=cfg.today_calls,
        skills=[
            SkillItem(code=s.code, name=s.name, desc=s.desc or "")
            for s in sorted(skills, key=lambda x: x.order_idx)
        ],
        mcps=[m.mcp_id for m in sorted(mcps, key=lambda x: x.order_idx)],
        knowledge=AgentKnowledge(industry_packs=industry_packs, spec_templates=spec_templates),
    )


@router.get("", response_model=AgentListResp)
async def list_agents(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List agents for the current tenant. Lazy-seeds defaults on first read."""
    rows = (await db.execute(
        select(AgentConfig).where(AgentConfig.tenant_id == ctx.tenant_id)
    )).scalars().all()
    if not rows:
        await seed_agents_for_tenant(db, ctx.tenant_id)
        rows = (await db.execute(
            select(AgentConfig).where(AgentConfig.tenant_id == ctx.tenant_id)
        )).scalars().all()

    out: list[AgentConfigResp] = []
    for cfg in rows:
        skills = (await db.execute(
            select(AgentSkill).where(AgentSkill.agent_config_id == cfg.id)
        )).scalars().all()
        mcps = (await db.execute(
            select(AgentMcpBinding).where(AgentMcpBinding.agent_config_id == cfg.id)
        )).scalars().all()
        knowledge = (await db.execute(
            select(AgentKnowledgeBinding).where(AgentKnowledgeBinding.agent_config_id == cfg.id)
        )).scalars().all()
        out.append(_to_resp(cfg, list(skills), list(mcps), list(knowledge)))
    return AgentListResp(agents=out)


@router.put("/{agent_id}", response_model=AgentConfigResp)
async def update_agent(
    agent_id: str,
    payload: AgentUpdateReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update model and/or system_prompt for a tenant's agent."""
    cfg = (await db.execute(
        select(AgentConfig).where(
            AgentConfig.tenant_id == ctx.tenant_id,
            AgentConfig.agent_id == agent_id,
        )
    )).scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found for tenant {ctx.tenant_id}")

    if payload.model is not None:
        cfg.model = payload.model
    if payload.system_prompt is not None:
        cfg.system_prompt = payload.system_prompt
    await db.commit()
    await db.refresh(cfg)

    skills = (await db.execute(
        select(AgentSkill).where(AgentSkill.agent_config_id == cfg.id)
    )).scalars().all()
    mcps = (await db.execute(
        select(AgentMcpBinding).where(AgentMcpBinding.agent_config_id == cfg.id)
    )).scalars().all()
    knowledge = (await db.execute(
        select(AgentKnowledgeBinding).where(AgentKnowledgeBinding.agent_config_id == cfg.id)
    )).scalars().all()
    return _to_resp(cfg, list(skills), list(mcps), list(knowledge))
