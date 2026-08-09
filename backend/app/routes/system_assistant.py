"""Read-only P0 bootstrap endpoint for the Code system assistant."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.system_assistant.baseline_service import (
    build_baseline_snapshot,
    collect_baseline_facts,
    unavailable_bootstrap,
)

router = APIRouter(prefix="/system-assistant", tags=["system-assistant"])


@router.get("/bootstrap")
async def bootstrap(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return a tenant-scoped baseline snapshot without creating a plan."""

    try:
        facts = await collect_baseline_facts(db, ctx)
        return build_baseline_snapshot(facts, tenant_id=int(getattr(ctx, "tenant_id", 0) or 0))
    except Exception:
        # A source outage must remain visible as unavailable. P0 has no write
        # path and therefore cannot repair or synthesize a missing source.
        return unavailable_bootstrap(tenant_id=int(getattr(ctx, "tenant_id", 0) or 0))
