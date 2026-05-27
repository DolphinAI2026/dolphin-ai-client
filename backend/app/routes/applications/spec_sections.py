"""SpecSection HTTP endpoints — spec-driven 草稿层 (O1)

URL prefix:  /applications/{app_id}/spec-sections/{section_type}/{section_key}

4 条:
  GET    .../                          → 读草稿
  POST   .../init-from-apaas           → 从 apaas 拉取初始化
  PUT    .../                          → 改草稿 (draft_version+1)
  GET    .../diff                      → SPEC 草稿 vs apaas 真状态 diff

所有 endpoint 鉴权：要求 ctx.tenant_id 与 Application.tenant_id 一致。
真实业务逻辑全部委托给 app.mcp_spec_sections 的 4 个工具函数。
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Application
from app.deps import get_auth_context, AuthContext
from app.permissions import check_resource_permission, Action
from app.mcp_spec_sections import (
    read_spec_section,
    init_spec_section_from_apaas,
    update_spec_section,
    diff_spec_vs_apaas,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic body schemas
# ---------------------------------------------------------------------------


class InitFromApaasBody(BaseModel):
    env_id: int
    apaas_app_id: str


class UpdateSpecSectionBody(BaseModel):
    spec_json: Any  # dict / list / JSON 字符串都接受
    diff_summary: Optional[str] = ""


# ---------------------------------------------------------------------------
# 共享 helper — 加载应用 + 权限校验
# ---------------------------------------------------------------------------


async def _load_app(
    app_id: int, ctx: AuthContext, db: AsyncSession, action: Action
) -> Application:
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", action)
    return app


def _raise_if_tool_error(result: dict) -> None:
    """工具返 ok:False 时按 error_code 映射到合适的 HTTPException."""
    if result.get("ok"):
        return
    code = result.get("error_code") or "BUSINESS_ERROR"
    if code == "INVALID_SECTION_TYPE":
        raise HTTPException(status_code=400, detail=result)
    if code == "INVALID_JSON":
        raise HTTPException(status_code=400, detail=result)
    if code == "NOT_FOUND":
        raise HTTPException(status_code=404, detail=result)
    if code == "ENV_NOT_FOUND":
        raise HTTPException(status_code=404, detail=result)
    if code == "ENV_NOT_CONNECTED":
        raise HTTPException(status_code=400, detail=result)
    if code == "ENV_REQUIRED":
        raise HTTPException(status_code=400, detail=result)
    if code == "NOT_IMPLEMENTED":
        raise HTTPException(status_code=501, detail=result)
    if code == "APAAS_MODEL_NOT_FOUND":
        raise HTTPException(status_code=404, detail=result)
    if code == "APAAS_FETCH_FAILED":
        raise HTTPException(status_code=502, detail=result)
    raise HTTPException(status_code=400, detail=result)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{app_id}/spec-sections/{section_type}/{section_key}")
async def get_spec_section(
    app_id: int,
    section_type: str,
    section_key: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """读应用某 section 的草稿 SPEC."""
    await _load_app(app_id, ctx, db, Action.VIEW)
    result = await read_spec_section(db, app_id, section_type, section_key)
    _raise_if_tool_error(result)
    return result


@router.post("/{app_id}/spec-sections/{section_type}/{section_key}/init-from-apaas")
async def init_spec_section_endpoint(
    app_id: int,
    section_type: str,
    section_key: str,
    body: InitFromApaasBody,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """从 apaas 拉真状态初始化 spec (base_version=1)。已存在不覆盖。"""
    await _load_app(app_id, ctx, db, Action.EDIT)
    result = await init_spec_section_from_apaas(
        db,
        env_id=body.env_id,
        apaas_app_id=body.apaas_app_id,
        app_id=app_id,
        section_type=section_type,
        section_key=section_key,
    )
    _raise_if_tool_error(result)
    return result


@router.put("/{app_id}/spec-sections/{section_type}/{section_key}")
async def update_spec_section_endpoint(
    app_id: int,
    section_type: str,
    section_key: str,
    body: UpdateSpecSectionBody,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """修改 spec_json 草稿 (draft_version+1)."""
    await _load_app(app_id, ctx, db, Action.EDIT)
    result = await update_spec_section(
        db,
        app_id=app_id,
        section_type=section_type,
        section_key=section_key,
        spec_json=body.spec_json,
        diff_summary=body.diff_summary or "",
    )
    _raise_if_tool_error(result)
    return result


@router.get("/{app_id}/spec-sections/{section_type}/{section_key}/diff")
async def diff_spec_section_endpoint(
    app_id: int,
    section_type: str,
    section_key: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    env_id: Optional[int] = None,
    apaas_app_id: Optional[str] = None,
):
    """SPEC 草稿 vs apaas 真状态 diff (O1 阶段只 form 类型)."""
    app = await _load_app(app_id, ctx, db, Action.VIEW)
    # 调用方未传 env_id / apaas_app_id 时，尝试从 Application 反查
    effective_env_id = env_id if env_id is not None else app.platform_env_id
    effective_apaas_app_id = apaas_app_id if apaas_app_id is not None else app.apaas_app_id
    result = await diff_spec_vs_apaas(
        db,
        app_id=app_id,
        section_type=section_type,
        section_key=section_key,
        env_id=effective_env_id,
        apaas_app_id=effective_apaas_app_id,
    )
    _raise_if_tool_error(result)
    return result
