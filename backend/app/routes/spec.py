"""REST API for SPEC objects.

POST   /spec                           → create empty spec for current user
GET    /spec/{id}                      → load full spec
PUT    /spec/{id}/phase                → user-driven phase transition
PUT    /spec/{id}/items/{type}/{code}  → user confirm/edit/dismiss single item
PUT    /spec/{id}/confirm-all          → user confirm the full generated draft
POST   /spec/{id}/generate-config      → convert confirmed draft into config preview

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
from app.json_utils import loads_if_str
from app.builder_spec.persistence import load_spec, save_spec, empty_spec
from app.builder_spec.converter import spec_to_config
from app.builder_spec.tools import dispatch_tool, ToolError
from app.builder_spec.schema import Phase

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


class GenerateConfigResponse(BaseModel):
    spec: dict
    config: dict


class UpgradeFromLegacyRequest(BaseModel):
    application_id: int


def _load_legacy_config_from_application(app) -> dict:
    """Return the legacy app config payload from the current Application model."""
    raw = getattr(app, "config_preview", None) or getattr(app, "config", None)
    if not raw:
        return {}
    parsed = loads_if_str(raw, default={})
    if not isinstance(parsed, dict):
        return {}
    data = parsed.get("data", parsed)
    return data if isinstance(data, dict) else {}


@router.post("/upgrade-from-legacy")
async def upgrade_from_legacy_config(
    body: UpgradeFromLegacyRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Reverse-engineer a Spec from an existing Application.config_preview and link it."""
    from app.models import Application
    from app.builder_spec.persistence import bootstrap_from_legacy_config

    app = await db.get(Application, body.application_id)
    if not app or app.tenant_id != ctx.tenant_id:
        raise HTTPException(404, detail="应用不存在")
    if app.canonical_spec_id:
        raise HTTPException(409, detail="应用已升级，请直接编辑")
    try:
        legacy = _load_legacy_config_from_application(app)
    except Exception as exc:
        raise HTTPException(400, detail=f"应用 config_preview 解析失败: {exc}") from exc
    if not legacy:
        raise HTTPException(400, detail="应用无 config_preview 可反推")

    spec = bootstrap_from_legacy_config(
        application_id=app.id,
        legacy_config=legacy,
        created_by=ctx.user.id,
    )
    await save_spec(db, spec, tenant_id=ctx.tenant_id)
    app.canonical_spec_id = spec.id
    await db.commit()
    return {"id": spec.id, "phase": spec.phase.value}


@router.get("/{spec_id}")
async def get_spec(
    spec_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    spec = await load_spec(db, spec_id, tenant_id=ctx.tenant_id)
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
    spec = await load_spec(db, spec_id, tenant_id=ctx.tenant_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"spec {spec_id} not found")
    try:
        spec = dispatch_tool(spec, "transition_phase",
                             {"target": body.target, "reason": body.reason})
    except ToolError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await save_spec(db, spec, tenant_id=ctx.tenant_id)
    return spec.model_dump(mode="json")


@router.put("/{spec_id}/confirm-all")
async def confirm_all_items(
    spec_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Confirm the current AI draft as one coherent version.

    The normal UX is document-first: users review the full draft, then confirm the
    version instead of clicking every generated role/object/field one by one.
    """
    spec = await load_spec(db, spec_id, tenant_id=ctx.tenant_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"spec {spec_id} not found")

    try:
        if spec.goal and not spec.goal.confirmed:
            spec = dispatch_tool(spec, "confirm_goal", {})
        for role in list(spec.roles):
            if not role.confirmed:
                spec = dispatch_tool(spec, "confirm_role", {"code": role.code})
        for obj in list(spec.objects):
            if not obj.confirmed:
                spec = dispatch_tool(spec, "confirm_object", {"code": obj.code})
            for field in list(obj.fields):
                if not field.confirmed:
                    spec = dispatch_tool(
                        spec,
                        "confirm_field",
                        {"object_code": obj.code, "field_code": field.code},
                    )
        for dict_item in list(spec.dicts):
            if not dict_item.confirmed:
                spec = dispatch_tool(spec, "confirm_dict", {"code": dict_item.code})
        for permission in list(spec.permissions):
            if not permission.confirmed:
                spec = dispatch_tool(
                    spec,
                    "confirm_permission",
                    {"object_code": permission.object_code},
                )
    except ToolError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if (
        spec.completeness.total > 0
        and spec.completeness.confirmed >= spec.completeness.total
        and spec.completeness.blocking_decisions == 0
        and spec.phase in {Phase.GATHERING, Phase.DRAFTING}
    ):
        spec = dispatch_tool(
            spec,
            "transition_phase",
            {"target": Phase.GENERATING.value, "reason": "user confirmed full draft"},
        )

    await save_spec(db, spec, tenant_id=ctx.tenant_id)
    return spec.model_dump(mode="json")


@router.post("/{spec_id}/generate-config", response_model=GenerateConfigResponse)
async def generate_config_from_spec(
    spec_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Convert the confirmed SPEC draft into low-code config preview data."""
    spec = await load_spec(db, spec_id, tenant_id=ctx.tenant_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"spec {spec_id} not found")

    if spec.completeness.total == 0:
        raise HTTPException(status_code=409, detail="SPEC 还没有可生成的设计内容")
    if spec.completeness.confirmed < spec.completeness.total:
        raise HTTPException(status_code=409, detail="请先确认当前设计文档版本")
    if spec.completeness.blocking_decisions:
        raise HTTPException(status_code=409, detail="仍有阻塞决策未确认")

    try:
        if spec.phase not in {Phase.GENERATING, Phase.READY}:
            spec = dispatch_tool(
                spec,
                "transition_phase",
                {"target": Phase.GENERATING.value, "reason": "start config generation"},
            )
        config = spec_to_config(spec)
        if spec.phase != Phase.READY:
            spec = dispatch_tool(
                spec,
                "transition_phase",
                {"target": Phase.READY.value, "reason": "config preview generated"},
            )
    except ToolError as e:
        raise HTTPException(status_code=409, detail=str(e))

    await save_spec(db, spec, tenant_id=ctx.tenant_id)
    return {"spec": spec.model_dump(mode="json"), "config": config}


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
    spec = await load_spec(db, spec_id, tenant_id=ctx.tenant_id)
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
