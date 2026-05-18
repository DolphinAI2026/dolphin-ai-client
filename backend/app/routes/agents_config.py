# backend/app/routes/agents_config.py
"""V2 Agent Config CRUD — /api/agents.

`GET /api/agents` lazy-seeds the 3 default agents on first read for a tenant.
`PUT /api/agents/{agent_id}` updates model / system_prompt.
`POST /api/agents/{agent_id}/skills`   bind a skill from agent_skill_catalog.
`DELETE /api/agents/{agent_id}/skills/{code}` unbind a skill.
`POST /api/agents/{agent_id}/mcps`     bind an MCP server.
`DELETE /api/agents/{agent_id}/mcps/{mcp_id}` unbind an MCP server.

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
from app.models.skill_catalog import AgentSkillCatalog
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


class SkillAddReq(BaseModel):
    code: str  # references agent_skill_catalog.code


class McpAddReq(BaseModel):
    mcp_id: str  # references mcp_hub server id


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


async def _build_agent_resp(cfg: AgentConfig, db: AsyncSession) -> AgentConfigResp:
    """Reload skills/mcps/knowledge for a config row and shape into the API response."""
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


async def _get_agent_or_404(agent_id: str, tenant_id: int, db: AsyncSession) -> AgentConfig:
    cfg = (await db.execute(
        select(AgentConfig).where(
            AgentConfig.tenant_id == tenant_id,
            AgentConfig.agent_id == agent_id,
        )
    )).scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found for tenant {tenant_id}")
    return cfg


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
        out.append(await _build_agent_resp(cfg, db))
    return AgentListResp(agents=out)


@router.put("/{agent_id}", response_model=AgentConfigResp)
async def update_agent(
    agent_id: str,
    payload: AgentUpdateReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update model and/or system_prompt for a tenant's agent."""
    cfg = await _get_agent_or_404(agent_id, ctx.tenant_id, db)

    if payload.model is not None:
        cfg.model = payload.model
    if payload.system_prompt is not None:
        cfg.system_prompt = payload.system_prompt
    await db.commit()
    await db.refresh(cfg)

    return await _build_agent_resp(cfg, db)


@router.post("/{agent_id}/skills", response_model=AgentConfigResp)
async def add_skill(
    agent_id: str,
    payload: SkillAddReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Bind a skill (from agent_skill_catalog) to an agent."""
    cfg = await _get_agent_or_404(agent_id, ctx.tenant_id, db)

    # Look up the catalog row for canonical name/desc.
    catalog_row = (await db.execute(
        select(AgentSkillCatalog).where(AgentSkillCatalog.code == payload.code)
    )).scalar_one_or_none()
    if not catalog_row:
        raise HTTPException(status_code=404, detail=f"skill {payload.code} not in catalog")

    # Check for duplicate binding.
    existing = (await db.execute(
        select(AgentSkill).where(
            AgentSkill.agent_config_id == cfg.id,
            AgentSkill.code == payload.code,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"skill {payload.code} already bound")

    # Append at end (next order_idx).
    current = (await db.execute(
        select(AgentSkill).where(AgentSkill.agent_config_id == cfg.id)
    )).scalars().all()
    db.add(AgentSkill(
        agent_config_id=cfg.id,
        code=catalog_row.code,
        name=catalog_row.name,
        desc=catalog_row.desc or "",
        order_idx=len(current),
    ))
    await db.commit()
    return await _build_agent_resp(cfg, db)


@router.delete("/{agent_id}/skills/{code}", response_model=AgentConfigResp)
async def remove_skill(
    agent_id: str,
    code: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Unbind a skill from an agent."""
    cfg = await _get_agent_or_404(agent_id, ctx.tenant_id, db)
    row = (await db.execute(
        select(AgentSkill).where(
            AgentSkill.agent_config_id == cfg.id,
            AgentSkill.code == code,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"skill {code} not bound")
    await db.delete(row)
    await db.commit()
    return await _build_agent_resp(cfg, db)


@router.post("/{agent_id}/mcps", response_model=AgentConfigResp)
async def add_mcp(
    agent_id: str,
    payload: McpAddReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Bind an MCP server to an agent."""
    cfg = await _get_agent_or_404(agent_id, ctx.tenant_id, db)
    existing = (await db.execute(
        select(AgentMcpBinding).where(
            AgentMcpBinding.agent_config_id == cfg.id,
            AgentMcpBinding.mcp_id == payload.mcp_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"mcp {payload.mcp_id} already bound")
    bindings = (await db.execute(
        select(AgentMcpBinding).where(AgentMcpBinding.agent_config_id == cfg.id)
    )).scalars().all()
    db.add(AgentMcpBinding(
        agent_config_id=cfg.id,
        mcp_id=payload.mcp_id,
        order_idx=len(bindings),
    ))
    await db.commit()
    return await _build_agent_resp(cfg, db)


@router.delete("/{agent_id}/mcps/{mcp_id}", response_model=AgentConfigResp)
async def remove_mcp(
    agent_id: str,
    mcp_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Unbind an MCP server from an agent."""
    cfg = await _get_agent_or_404(agent_id, ctx.tenant_id, db)
    row = (await db.execute(
        select(AgentMcpBinding).where(
            AgentMcpBinding.agent_config_id == cfg.id,
            AgentMcpBinding.mcp_id == mcp_id,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"mcp {mcp_id} not bound")
    await db.delete(row)
    await db.commit()
    return await _build_agent_resp(cfg, db)
