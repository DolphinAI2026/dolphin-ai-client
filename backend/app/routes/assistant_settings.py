"""External assistant integration settings."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AliasChoices, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context, require_tenant_admin, resolve_effective_tenant_id
from app.models.assistant_settings import AssistantSetting

router = APIRouter(prefix="/assistant-settings", tags=["assistant-settings"])

DEFAULT_DOLPHIN_SERVER_URL = "https://dolphin-trial.definesys.cn"
DEFAULT_DOLPHIN_BUTTON_TEXT = "得小帆"


class DolphinSettingPayload(BaseModel):
    enabled: bool = False
    server_url: str = DEFAULT_DOLPHIN_SERVER_URL
    agent_code: str = ""
    apaas_tenant_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("apaas_tenant_id", "apaasTenantId"),
    )
    button_text: str = DEFAULT_DOLPHIN_BUTTON_TEXT


def _normalize_url(value: str) -> str:
    text = (value or "").strip().rstrip("/")
    if not text:
        return DEFAULT_DOLPHIN_SERVER_URL
    if not (text.startswith("http://") or text.startswith("https://")):
        raise HTTPException(status_code=400, detail="server_url 必须以 http:// 或 https:// 开头")
    return text


def _to_response(row: AssistantSetting | None, tenant_id: int = 0) -> dict:
    if not row:
        return {
            "tenant_id": tenant_id,
            "scope": "global",
            "enabled": False,
            "server_url": DEFAULT_DOLPHIN_SERVER_URL,
            "agent_code": "",
            "apaas_tenant_id": "",
            "button_text": DEFAULT_DOLPHIN_BUTTON_TEXT,
            "configured": False,
        }
    button_text = (row.button_text or "").strip()
    if not button_text or button_text == "问题助手":
        button_text = DEFAULT_DOLPHIN_BUTTON_TEXT
    return {
        "tenant_id": row.tenant_id,
        "scope": "global",
        "enabled": bool(row.enabled),
        "server_url": row.server_url,
        "agent_code": row.agent_code,
        "apaas_tenant_id": row.apaas_tenant_id,
        "button_text": button_text,
        "configured": bool(row.agent_code.strip() and row.apaas_tenant_id.strip()),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _get_dolphin_setting(db: AsyncSession) -> AssistantSetting | None:
    """Return the single platform-wide Dolphin setting.

    The table still has tenant_id for historical compatibility, but this
    setting is a platform management feature and must not change when the
    active Builder tenant changes.
    """
    return (await db.execute(
        select(AssistantSetting)
        .where(AssistantSetting.kind == "dolphin")
        .order_by(
            AssistantSetting.enabled.desc(),
            AssistantSetting.updated_at.desc(),
            AssistantSetting.id.asc(),
        )
        .limit(1)
    )).scalar_one_or_none()


@router.get("/dolphin/public")
async def get_dolphin_public_setting(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await _get_dolphin_setting(db)
    return _to_response(row, ctx.tenant_id or 0)


@router.get("/dolphin")
async def get_dolphin_setting(
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await _get_dolphin_setting(db)
    return _to_response(row, ctx.tenant_id or 0)


@router.put("/dolphin")
async def put_dolphin_setting(
    payload: DolphinSettingPayload,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    server_url = _normalize_url(payload.server_url)
    agent_code = (payload.agent_code or "").strip()
    button_text = (payload.button_text or "").strip() or DEFAULT_DOLPHIN_BUTTON_TEXT

    row = await _get_dolphin_setting(db)
    if not row:
        tenant_id = ctx.tenant_id if ctx.tenant_id and ctx.tenant_id > 0 else await resolve_effective_tenant_id(db, ctx)
        row = AssistantSetting(tenant_id=tenant_id, kind="dolphin")
        db.add(row)

    fields_set = getattr(payload, "model_fields_set", set())
    has_apaas_tenant_id = "apaas_tenant_id" in fields_set
    apaas_tenant_id = (
        (payload.apaas_tenant_id or "").strip()
        if has_apaas_tenant_id
        else (row.apaas_tenant_id or "").strip()
    )
    if payload.enabled and not agent_code:
        raise HTTPException(status_code=400, detail="启用得小帆前请填写 Agent Code")
    if payload.enabled and not apaas_tenant_id:
        raise HTTPException(status_code=400, detail="启用得小帆前请填写 aPaaS 租户ID")

    row.enabled = bool(payload.enabled)
    row.server_url = server_url
    row.agent_code = agent_code
    if has_apaas_tenant_id:
        row.apaas_tenant_id = apaas_tenant_id[:120]
    row.button_text = button_text[:80]
    await db.commit()
    await db.refresh(row)
    return _to_response(row)
