"""Read-only P0 bootstrap endpoint for the Code system assistant."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context, is_control_plane_context
from app.system_assistant.baseline_service import (
    build_baseline_snapshot,
    collect_baseline_facts,
)
from app.system_assistant.contracts import BootstrapResponse
from app.routes.llm_configs import LLMConfigOptionResponse, list_llm_configs_for_purpose
from app.code_runtime.control_plane_models import list_control_plane_model_options

router = APIRouter(prefix="/system-assistant", tags=["system-assistant"])


@router.get("/bootstrap", response_model=BootstrapResponse)
async def bootstrap(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return a tenant-scoped baseline snapshot without creating a plan."""

    facts = await collect_baseline_facts(db, ctx)
    return build_baseline_snapshot(facts, tenant_id=int(getattr(ctx, "tenant_id", 0) or 0))


@router.get("/models", response_model=list[LLMConfigOptionResponse])
async def list_models(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the Coding model catalog used by system-assistant sessions."""

    if is_control_plane_context(ctx):
        from app.routes.code_runtime import _control_plane_request_auth

        authorization, _auth_provider = await _control_plane_request_auth(
            type("Request", (), {"headers": {}})(),
            ctx,
            db,
        )
        if not authorization:
            return []
        options = await list_control_plane_model_options(
            purpose="coding",
            authorization_header=authorization,
            delegated_context=ctx,
        )
        return [LLMConfigOptionResponse(**option) for option in options]

    tenant_id = int(getattr(ctx, "tenant_id", 0) or 0)
    rows = await list_llm_configs_for_purpose(db, tenant_id or None, "coding")
    if not rows and tenant_id:
        rows = await list_llm_configs_for_purpose(db, None, "coding")
    return [LLMConfigOptionResponse.from_db(row) for row in rows]
