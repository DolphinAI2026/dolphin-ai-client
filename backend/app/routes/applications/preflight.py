"""首次部署前的冲突预检 & 批量 rename。

场景：用户点击"开始构建"准备首次部署新应用到平台前，需要检查 v2_config
里的模型 code 是否和平台其他应用已有的模型撞车（租户级命名空间）。

两条路由：
  POST /{app_id}/preflight-conflicts  —— 扫租户模型 → 求交 → 返回冲突清单
  POST /{app_id}/apply-code-rename    —— 按用户确认的映射批量改 config_preview

仅用于首次部署（apaas_app_id 为空时）。已部署应用的"增量更新"不走此链路。
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apaas_client import APaaSClient
from app.crypto import decrypt_password
from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.json_utils import loads_if_str
from app.models import Application, PlatformEnv
from app.permissions import Action, check_resource_permission
from app.platform_conflict_checker import (
    apply_model_code_rename,
    collect_tenant_model_codes,
    find_model_conflicts,
)

from ._helpers import _dump_preview_config

logger = logging.getLogger(__name__)
router = APIRouter()


class PreflightConflictItem(BaseModel):
    resource_type: str
    name: str
    original_code: str
    suggested_code: str


class PreflightConflictsResponse(BaseModel):
    has_conflicts: bool
    skipped: str | None = None  # e.g. "already_deployed" / "no_env" / "scan_failed"
    conflicts: List[PreflightConflictItem] = Field(default_factory=list)
    scanned_remote_count: int = 0


class ApplyRenameRequest(BaseModel):
    # {original_code: new_code}
    renames: Dict[str, str]


class ApplyRenameResponse(BaseModel):
    ok: bool
    changed_count: int
    applied_renames: Dict[str, str]


async def _load_app_and_env(
    app_id: int,
    ctx: AuthContext,
    db: AsyncSession,
) -> tuple[Application, PlatformEnv | None]:
    """加载应用并检查权限；同时取其绑定的 platform env（可能为空）。"""
    r = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = r.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    env: PlatformEnv | None = None
    if app.platform_env_id:
        er = await db.execute(
            select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id)
        )
        env = er.scalar_one_or_none()
    return app, env


@router.post("/{app_id}/preflight-conflicts", response_model=PreflightConflictsResponse)
async def preflight_conflicts(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PreflightConflictsResponse:
    """首次部署前预检：扫租户所有模型 code，和本地 v2_config 求交。"""
    app, env = await _load_app_and_env(app_id, ctx, db)

    # 只在首次部署时跑：已绑定 apaas_app_id 的应用跳过（自己模型会被误识别成"已存在"）
    if app.apaas_app_id:
        return PreflightConflictsResponse(
            has_conflicts=False,
            skipped="already_deployed",
        )

    # 需要环境 & 登录态
    if not env or not env.token:
        return PreflightConflictsResponse(
            has_conflicts=False,
            skipped="no_env",
        )

    # 读 config_preview
    if not app.config_preview:
        return PreflightConflictsResponse(has_conflicts=False, skipped="no_config")
    try:
        loaded = loads_if_str(app.config_preview)
        v2_config = loaded.get("data", loaded) if isinstance(loaded, dict) else {}
    except Exception as e:
        logger.warning(f"preflight: 解析 config_preview 失败：{e}")
        return PreflightConflictsResponse(has_conflicts=False, skipped="bad_config")

    # 扫租户
    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
    client.token = env.token
    existing_codes = await collect_tenant_model_codes(client)
    if not existing_codes:
        # 查询失败或真的空——查询失败 collect_* 已记 warning
        return PreflightConflictsResponse(
            has_conflicts=False,
            skipped="scan_failed_or_empty",
            scanned_remote_count=0,
        )

    conflicts_raw = find_model_conflicts(v2_config, existing_codes)
    return PreflightConflictsResponse(
        has_conflicts=bool(conflicts_raw),
        conflicts=[PreflightConflictItem(**c) for c in conflicts_raw],
        scanned_remote_count=len(existing_codes),
    )


@router.post("/{app_id}/apply-code-rename", response_model=ApplyRenameResponse)
async def apply_code_rename(
    app_id: int,
    body: ApplyRenameRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplyRenameResponse:
    """把用户确认的 {old_code: new_code} 应用到 config_preview。

    只改模型 code 以及所有引用该 code 的地方（ref.model / sub_code / form.model_code / ...）。
    """
    app, _env = await _load_app_and_env(app_id, ctx, db)

    renames = {
        str(k).strip(): str(v).strip()
        for k, v in (body.renames or {}).items()
        if str(k).strip() and str(v).strip() and str(k).strip() != str(v).strip()
    }
    if not renames:
        return ApplyRenameResponse(ok=True, changed_count=0, applied_renames={})

    if not app.config_preview:
        raise HTTPException(status_code=400, detail="应用没有预览配置")

    try:
        loaded = loads_if_str(app.config_preview)
        # config_preview 可能是 {"type":"preview","data":{...}} 外壳
        if isinstance(loaded, dict) and "data" in loaded and isinstance(loaded["data"], dict):
            v2_config = loaded["data"]
            wrapped = True
        else:
            v2_config = loaded if isinstance(loaded, dict) else {}
            wrapped = False
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"config_preview 解析失败：{e}")

    new_config, changed = apply_model_code_rename(v2_config, renames)

    if wrapped:
        loaded["data"] = new_config
        app.config_preview = _dump_preview_config(new_config) if changed else app.config_preview
        # _dump_preview_config 已包含 {"type":"preview","data":...} 外壳，直接覆写
    else:
        app.config_preview = _dump_preview_config(new_config) if changed else app.config_preview

    await db.commit()
    logger.info(
        f"应用 {app_id} 模型 code rename 应用完成: changed={changed}, renames={renames}"
    )
    return ApplyRenameResponse(
        ok=True,
        changed_count=changed,
        applied_renames=renames,
    )
