"""CRUD endpoints for native designer panels — 2026-05-26 P2-D.

包现有 MCP 工具 (add_apaas_model_field / update_apaas_model_field /
disable_apaas_model_field / add_apaas_dict_option / update_apaas_dict_option /
create_apaas_app_roles), 暴露 REST endpoint 让 FormDesignerPanel / DictEditorPanel /
RoleManagePanel 直接调.

所有 endpoint:
- 检 EDIT 权限 (因为是 mutation)
- 包 try/except MCP error
- 200 + ok=false + error_code 兜底, 不 raise 500
- 写完日志 (logger.info) 让审计可追

route prefix: /applications/{app_id}/crud/
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models import Application
from app.permissions import Action

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Shared helpers ──────────────────────────────────────────────────────────

async def _load_app_and_check_edit(
    app_id: int, ctx: AuthContext, db: AsyncSession,
) -> Application:
    """EDIT 权限检查 + 应用未部署兜底.

    不通过返 HTTPException 403/404. 调用方不用再 check.
    """
    r = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = r.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    from app.routes.applications import _require_application_permission
    await _require_application_permission(ctx, db, app, Action.EDIT)
    return app


def _app_not_deployed_err() -> dict:
    return {
        "ok": False,
        "error_code": "APP_NOT_DEPLOYED",
        "message": "应用尚未部署到 aPaaS 平台 — 部署后才能修改资源",
    }


async def _safe_mcp_call(tool_name: str, **kwargs) -> dict:
    """统一调 MCP 工具 + 异常兜底."""
    try:
        from app import mcp_server as _mcp
    except Exception as exc:
        return {"ok": False, "error_code": "MCP_MODULE_LOAD_FAILED", "message": str(exc)}
    tool = getattr(_mcp, tool_name, None)
    if tool is None:
        return {
            "ok": False, "error_code": "TOOL_NOT_AVAILABLE",
            "message": f"MCP 工具 {tool_name} 未注册",
        }
    try:
        result = await tool(**kwargs)
    except Exception as exc:
        logger.warning(f"crud_endpoints: {tool_name} 抛错: {exc}")
        return {"ok": False, "error_code": "MCP_EXCEPTION", "message": str(exc)}
    if not isinstance(result, dict):
        return {"ok": False, "error_code": "MCP_UNEXPECTED_SHAPE",
                "message": f"{tool_name} 返非 dict"}
    return result


# ─── Model Field CRUD ────────────────────────────────────────────────────────

class _AddFieldReq(BaseModel):
    model_id: str = Field(..., description="模型 ID (走 list_apaas_app_models 拿)")
    model_code: str = Field(..., description="模型 code (apaas 平台 modelCode)")
    field_code: str = Field(..., min_length=1, max_length=64)
    field_name: str = Field(..., min_length=1, max_length=64)
    field_type: str = Field(default="STRING", description="STRING/NUM/DATE/DATETIME/BOOLEAN/TEXT/BIG_TEXT")
    max_length: int = Field(default=255, ge=0, le=4000)
    comment: str = Field(default="", max_length=200)


@router.post("/{app_id}/crud/model-field/add")
async def add_model_field(
    app_id: int,
    body: _AddFieldReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """给模型加一个字段. 走 add_apaas_model_field MCP."""
    app = await _load_app_and_check_edit(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed_err()
    logger.info(f"add_model_field app_id={app_id} model_code={body.model_code} field={body.field_code}")
    return await _safe_mcp_call(
        "add_apaas_model_field",
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        model_id=body.model_id.strip(),
        model_code=body.model_code.strip(),
        field_code=body.field_code.strip(),
        field_name=body.field_name.strip(),
        field_type=body.field_type,
        max_length=body.max_length,
        comment=body.comment.strip(),
    )


class _UpdateFieldReq(BaseModel):
    model_id: str = Field(...)
    field_id: str = Field(..., description="字段 ID (走 list_apaas_app_models?with_fields=true 拿)")
    field_code: str = Field(..., min_length=1, max_length=64)
    field_name: str = Field(..., min_length=1, max_length=64)
    field_type: str = Field(default="", description="留空 = 不改类型")
    max_length: int = Field(default=0, ge=0, le=4000, description="0 = 不改长度")
    comment: str = Field(default="", max_length=200)


@router.post("/{app_id}/crud/model-field/update")
async def update_model_field(
    app_id: int,
    body: _UpdateFieldReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """改字段属性 (改名/改类型/改长度)."""
    app = await _load_app_and_check_edit(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed_err()
    logger.info(f"update_model_field app_id={app_id} field_id={body.field_id}")
    return await _safe_mcp_call(
        "update_apaas_model_field",
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        model_id=body.model_id.strip(),
        field_id=body.field_id.strip(),
        field_code=body.field_code.strip(),
        field_name=body.field_name.strip(),
        field_type=body.field_type,
        max_length=body.max_length,
        comment=body.comment.strip(),
    )


class _DisableFieldReq(BaseModel):
    model_id: str = Field(...)
    field_id: str = Field(...)
    field_code: str = Field(..., min_length=1, max_length=64)
    field_name: str = Field(..., min_length=1, max_length=64)


@router.post("/{app_id}/crud/model-field/disable")
async def disable_model_field(
    app_id: int,
    body: _DisableFieldReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """禁用字段 (apaas 不能真删字段, status=DISABLE).

    note: 重新启用调 update endpoint + field_status 'ENABLE' (P1 加).
    """
    app = await _load_app_and_check_edit(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed_err()
    logger.info(f"disable_model_field app_id={app_id} field_id={body.field_id}")
    return await _safe_mcp_call(
        "disable_apaas_model_field",
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        model_id=body.model_id.strip(),
        field_id=body.field_id.strip(),
        field_code=body.field_code.strip(),
        field_name=body.field_name.strip(),
    )


# ─── Dict Option CRUD ────────────────────────────────────────────────────────

class _AddDictOptionReq(BaseModel):
    dict_id: str = Field(...)
    value_code: str = Field(..., min_length=1, max_length=64)
    value_name: str = Field(..., min_length=1, max_length=64)
    display_order: int = Field(default=0, ge=0)


@router.post("/{app_id}/crud/dict-option/add")
async def add_dict_option(
    app_id: int,
    body: _AddDictOptionReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """给字典加一个选项. 走 add_apaas_dict_option MCP."""
    app = await _load_app_and_check_edit(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed_err()
    logger.info(f"add_dict_option app_id={app_id} dict_id={body.dict_id} value={body.value_code}")
    return await _safe_mcp_call(
        "add_apaas_dict_option",
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        dict_id=body.dict_id.strip(),
        value_code=body.value_code.strip(),
        value_name=body.value_name.strip(),
        display_order=body.display_order,
    )


class _UpdateDictOptionReq(BaseModel):
    dict_id: str = Field(...)
    option_id: str = Field(...)
    value_code: str = Field(..., min_length=1, max_length=64)
    value_name: str = Field(..., min_length=1, max_length=64)
    display_order: int = Field(default=0, ge=0)
    describe: str = Field(default="", max_length=200)
    multicolor: str = Field(default="#027AFF", max_length=10)


@router.post("/{app_id}/crud/dict-option/update")
async def update_dict_option(
    app_id: int,
    body: _UpdateDictOptionReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """改字典选项."""
    app = await _load_app_and_check_edit(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed_err()
    logger.info(f"update_dict_option app_id={app_id} option_id={body.option_id}")
    return await _safe_mcp_call(
        "update_apaas_dict_option",
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        dict_id=body.dict_id.strip(),
        option_id=body.option_id.strip(),
        value_code=body.value_code.strip(),
        value_name=body.value_name.strip(),
        display_order=body.display_order,
        describe=body.describe.strip(),
        multicolor=body.multicolor,
    )


class _DisableDictOptionReq(BaseModel):
    dict_id: str = Field(...)
    option_id: str = Field(...)


@router.post("/{app_id}/crud/dict-option/disable")
async def disable_dict_option(
    app_id: int,
    body: _DisableDictOptionReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """禁用字典选项 (apaas 不能真删, 走 disable_apaas_dict_option MCP)."""
    app = await _load_app_and_check_edit(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed_err()
    logger.info(f"disable_dict_option app_id={app_id} option_id={body.option_id}")
    return await _safe_mcp_call(
        "disable_apaas_dict_option",
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        dict_id=body.dict_id.strip(),
        option_id=body.option_id.strip(),
    )


# ─── Role CRUD ───────────────────────────────────────────────────────────────

class _RoleItem(BaseModel):
    role_code: str = Field(..., min_length=1, max_length=64)
    role_name: str = Field(..., min_length=1, max_length=64)
    role_desc: str = Field(default="", max_length=200)


class _AddRolesReq(BaseModel):
    roles: list[_RoleItem] = Field(..., min_length=1, max_length=20)


@router.post("/{app_id}/crud/role/add")
async def add_roles(
    app_id: int,
    body: _AddRolesReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """批量创建角色. 走 create_apaas_app_roles MCP (本身支持 batch)."""
    app = await _load_app_and_check_edit(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return _app_not_deployed_err()
    logger.info(f"add_roles app_id={app_id} count={len(body.roles)}")
    roles_payload = [
        {"role_code": r.role_code.strip(), "role_name": r.role_name.strip(),
         "role_desc": r.role_desc.strip()}
        for r in body.roles
    ]
    return await _safe_mcp_call(
        "create_apaas_app_roles",
        env_id=app.platform_env_id,
        apaas_app_id=str(app.apaas_app_id),
        roles=roles_payload,
    )
