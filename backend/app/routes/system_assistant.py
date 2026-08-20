"""Read-only P0 bootstrap endpoint for the Code system assistant."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app import runtime
from app.deps import AuthContext, get_auth_context, is_control_plane_context
from app.system_assistant.baseline_service import (
    build_baseline_snapshot,
    collect_baseline_facts,
)
from app.system_assistant.contracts import BootstrapResponse, SystemAssistantExecution
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
    response = build_baseline_snapshot(facts, tenant_id=int(getattr(ctx, "tenant_id", 0) or 0))
    response["execution"] = SystemAssistantExecution(
        configured_mode=runtime.system_assistant_execution_mode(),
        remote_runtime_available=runtime.system_assistant_remote_enabled(),
        local_directory_access=(
            runtime.is_desktop()
            and runtime.system_assistant_execution_mode() == "local"
        ),
    )
    return response


@router.get("/models", response_model=list[LLMConfigOptionResponse])
async def list_models(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the Coding model catalog used by system-assistant sessions."""

    tenant_id = int(getattr(ctx, "tenant_id", 0) or 0)
    # Desktop conversations may use either a locally configured provider or a
    # model supplied by the signed-in Control Plane account.  The old early
    # return below exposed only the latter, which made a valid local model
    # impossible to select in the Code system assistant.
    local_options: list[LLMConfigOptionResponse] = []
    if not is_control_plane_context(ctx) or runtime.is_desktop():
        rows = await list_llm_configs_for_purpose(db, tenant_id or None, "coding")
        if not rows and tenant_id:
            rows = await list_llm_configs_for_purpose(db, None, "coding")
        local_options = [LLMConfigOptionResponse.from_db(row) for row in rows]

    if is_control_plane_context(ctx):
        from app.routes.code_runtime import _control_plane_request_auth

        authorization, _auth_provider = await _control_plane_request_auth(
            type("Request", (), {"headers": {}})(),
            ctx,
            db,
        )
        if not authorization:
            return local_options
        try:
            options = await list_control_plane_model_options(
                purpose="coding",
                authorization_header=authorization,
                delegated_context=ctx,
            )
        except Exception:
            # A remote catalogue outage must not hide a working local model.
            # The agent resolver still reports the remote error when that
            # remote model was explicitly selected.
            if local_options:
                return local_options
            raise
        seen_ids = {option.id for option in local_options}
        remote_options = [
            LLMConfigOptionResponse(**option)
            for option in options
            if option.get("id") not in seen_ids
        ]
        return [*local_options, *remote_options]

    return local_options
