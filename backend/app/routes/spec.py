"""REST API for SPEC objects.

POST   /spec                           → create empty spec for current user
GET    /spec/{id}                      → load full spec
PUT    /spec/{id}/phase                → user-driven phase transition
PUT    /spec/{id}/items/{type}/{code}  → user confirm/edit/dismiss single item

The "items" endpoint dispatches to the same tool functions the agent uses,
so behavior stays consistent.
"""

from __future__ import annotations
from typing import Annotated, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.spec.persistence import load_spec, save_spec, empty_spec
from app.spec.tools import dispatch_tool, ToolError
from app.spec.schema import Phase

router = APIRouter(prefix="/spec", tags=["spec"])


class CreateSpecRequest(BaseModel):
    application_id: Optional[int] = None


@router.post("")
async def create_spec(
    body: CreateSpecRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    spec = empty_spec(created_by=ctx.user.id, application_id=body.application_id)
    await save_spec(db, spec, tenant_id=ctx.tenant_id)
    return {"id": spec.id, "phase": spec.phase.value}


class PhaseTransition(BaseModel):
    target: Literal["gathering", "drafting", "generating", "ready"]
    reason: str = "user request"


class ItemAction(BaseModel):
    action: Literal["confirm", "dismiss", "update"]
    payload: dict = {}


@router.get("/{spec_id}")
async def get_spec(
    spec_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    spec = await load_spec(db, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"spec {spec_id} not found")
    return spec.model_dump(mode="json")


@router.put("/{spec_id}/phase")
async def transition_phase(
    spec_id: str,
    body: PhaseTransition,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    spec = await load_spec(db, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"spec {spec_id} not found")
    try:
        spec = dispatch_tool(spec, "transition_phase",
                             {"target": body.target, "reason": body.reason})
    except ToolError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await save_spec(db, spec, tenant_id=ctx.tenant_id)
    return spec.model_dump(mode="json")


@router.put("/{spec_id}/items/{item_type}/{item_code}")
async def update_item(
    spec_id: str,
    item_type: Literal["role", "object", "field", "dict", "permission"],
    item_code: str,
    body: ItemAction,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Map (item_type, action) → tool name and dispatch."""
    spec = await load_spec(db, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"spec {spec_id} not found")

    tool_map = {
        ("role", "confirm"): ("confirm_role", {"code": item_code}),
        ("role", "dismiss"): ("dismiss_role", {"code": item_code}),
        ("role", "update"): ("update_role", {"code": item_code, **body.payload}),
        ("object", "confirm"): ("confirm_object", {"code": item_code}),
        ("object", "dismiss"): ("dismiss_object", {"code": item_code}),
        ("dict", "confirm"): ("confirm_dict", {"code": item_code}),
        ("dict", "dismiss"): ("dismiss_dict", {"code": item_code}),
        ("permission", "confirm"): ("confirm_permission", {"object_code": item_code}),
        ("permission", "dismiss"): ("dismiss_permission", {"object_code": item_code}),
        # field needs object_code in body.payload
        ("field", "confirm"): ("confirm_field",
                               {"object_code": body.payload.get("object_code"), "field_code": item_code}),
        ("field", "dismiss"): ("dismiss_field",
                               {"object_code": body.payload.get("object_code"), "field_code": item_code}),
        ("field", "update"): ("update_field",
                              {"object_code": body.payload.get("object_code"),
                               "field_code": item_code,
                               **{k: v for k, v in body.payload.items() if k != "object_code"}}),
    }
    key = (item_type, body.action)
    if key not in tool_map:
        raise HTTPException(status_code=400, detail=f"Unsupported {item_type}/{body.action}")
    tool_name, tool_args = tool_map[key]
    try:
        spec = dispatch_tool(spec, tool_name, tool_args)
    except ToolError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await save_spec(db, spec, tenant_id=ctx.tenant_id)
    return spec.model_dump(mode="json")
