"""/api/industry — pack catalog + ontology + per-tenant install.

Three endpoints:
- GET  /industry/packs                       — list all packs, with per-tenant installed flag
- GET  /industry/packs/{pack_id}/ontology    — fetch full ontology JSON for one pack
- POST /industry/packs/{pack_id}/install     — mark this pack installed for ctx.tenant_id

Router prefix `/industry`; main.py mounts with `prefix="/api"` (coordinator pass).
Lazy-seeded: `list_packs` checks if `industry_packs` is empty and calls
`seed_industry_packs(db)` before the SELECT — keeps startup hook untouched.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models.industry import IndustryPack, IndustryPackInstall
from app.services.industry_seed import seed_industry_packs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/industry", tags=["industry"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class IndustryStatsResp(BaseModel):
    entities: int
    relations: int
    workflows: int
    dicts: int
    forms: int
    roles: int


class IndustryPackResp(BaseModel):
    id: str
    name: str
    code: str
    tone: str
    version: str
    installed: bool
    default: bool
    summary: str
    stats: IndustryStatsResp
    adopted: list[str]
    maintainer: str
    updated: str


class IndustryPackListResp(BaseModel):
    packs: list[IndustryPackResp]


class OntologyResp(BaseModel):
    pack: str
    entities: list[dict[str, Any]]
    relations: list[dict[str, Any]]
    workflows: list[dict[str, Any]]
    dictHighlight: list[dict[str, Any]]


class InstallResp(BaseModel):
    ok: bool
    installed: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/packs", response_model=IndustryPackListResp)
async def list_packs(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IndustryPackListResp:
    """List all industry packs, with `installed` resolved against ctx.tenant_id."""
    # Lazy seed: if the table is empty, populate the 4 defaults before reading.
    await seed_industry_packs(db)

    packs = (await db.execute(select(IndustryPack))).scalars().all()
    installs = (
        await db.execute(
            select(IndustryPackInstall).where(
                IndustryPackInstall.tenant_id == ctx.tenant_id
            )
        )
    ).scalars().all()
    installed_ids = {i.pack_id for i in installs}

    return IndustryPackListResp(
        packs=[
            IndustryPackResp(
                id=p.id,
                name=p.name,
                code=p.code,
                tone=p.tone,
                version=p.version,
                installed=p.id in installed_ids,
                default=p.is_default,
                summary=p.summary,
                stats=IndustryStatsResp(
                    entities=p.entities_count,
                    relations=p.relations_count,
                    workflows=p.workflows_count,
                    dicts=p.dicts_count,
                    forms=p.forms_count,
                    roles=p.roles_count,
                ),
                adopted=list(p.adopted or []),
                maintainer=p.maintainer,
                updated=p.updated,
            )
            for p in packs
        ]
    )


@router.get("/packs/{pack_id}/ontology", response_model=OntologyResp)
async def get_ontology(
    pack_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OntologyResp:
    """Return the ontology JSON for one pack. Empty lists if the pack has no ontology yet."""
    pack = (
        await db.execute(select(IndustryPack).where(IndustryPack.id == pack_id))
    ).scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail=f"pack {pack_id} not found")
    ont = pack.ontology or {}
    return OntologyResp(
        pack=pack_id,
        entities=ont.get("entities", []),
        relations=ont.get("relations", []),
        workflows=ont.get("workflows", []),
        dictHighlight=ont.get("dictHighlight", []),
    )


@router.post("/packs/{pack_id}/install", response_model=InstallResp)
async def install_pack(
    pack_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InstallResp:
    """Idempotently mark the pack as installed for the caller's tenant."""
    pack = (
        await db.execute(select(IndustryPack).where(IndustryPack.id == pack_id))
    ).scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail=f"pack {pack_id} not found")

    existing = (
        await db.execute(
            select(IndustryPackInstall).where(
                IndustryPackInstall.tenant_id == ctx.tenant_id,
                IndustryPackInstall.pack_id == pack_id,
            )
        )
    ).scalar_one_or_none()
    if not existing:
        db.add(IndustryPackInstall(tenant_id=ctx.tenant_id, pack_id=pack_id))
        await db.commit()
        logger.info(
            "industry_install: pack=%s tenant=%s by user=%s",
            pack_id,
            ctx.tenant_id,
            ctx.user.id,
        )
    return InstallResp(ok=True, installed=True)
