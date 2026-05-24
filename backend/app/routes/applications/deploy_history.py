"""部署历史 & 回滚

3 个 endpoint，挂在 /applications 下：
- GET   /{app_id}/deploy-records             列部署历史（分页）
- GET   /{app_id}/deploy-records/{record_id} 单条详情（含 SPEC snapshot content + event log）
- POST  /{app_id}/rollback                   回滚到指定 record 的 SPEC 快照

也提供 `create_deploy_record_pre` / `complete_deploy_record` 给 publish 路由调用。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Application, DeployRecord, ConfigSnapshot, User
from app.deps import get_auth_context, AuthContext
from app.permissions import check_resource_permission, Action

logger = logging.getLogger(__name__)
router = APIRouter()


# ── helper：复用给 publish_application / generate ────────────────────────────


async def create_deploy_record_pre(
    db: AsyncSession,
    app: Application,
    user: User,
    deploy_type: str = "deploy",
    version_label: Optional[str] = None,
) -> DeployRecord:
    """部署开始前调一下，记录 in_progress 状态 + 关联当前 SPEC snapshot。

    返回 DeployRecord，调用方拿到 record.id 后部署完成时调
    complete_deploy_record() 把状态推到 success/failed。
    """
    snapshot_artifact_id: Optional[int] = None
    if app.id is not None:
        snap_result = await db.execute(
            select(ConfigSnapshot.id)
            .where(ConfigSnapshot.application_id == app.id)
            .order_by(desc(ConfigSnapshot.version))
            .limit(1)
        )
        snapshot_artifact_id = snap_result.scalar_one_or_none()

    record = DeployRecord(
        app_id=app.id,
        tenant_id=app.tenant_id,
        user_id=user.id,
        version_label=version_label,
        status="in_progress",
        deploy_type=deploy_type,
        snapshot_artifact_id=snapshot_artifact_id,
        apaas_app_id_before=app.apaas_app_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def complete_deploy_record(
    db: AsyncSession,
    record: DeployRecord,
    app: Application,
    success: bool,
    error_message: Optional[str] = None,
    event_log: Optional[List[dict]] = None,
    version_label: Optional[str] = None,
) -> None:
    """部署结束后更新 DeployRecord（success / failed）"""
    record.status = "success" if success else "failed"
    record.apaas_app_id_after = app.apaas_app_id
    record.error_message = error_message
    record.completed_at = datetime.utcnow()
    if event_log is not None:
        record.event_log_json = event_log
    if version_label and not record.version_label:
        record.version_label = version_label
    await db.commit()


# ── 路由 ─────────────────────────────────────────────────────────────────────


class DeployRecordSummary(BaseModel):
    id: int
    app_id: int
    user_id: int
    version_label: Optional[str]
    status: str
    deploy_type: str
    snapshot_artifact_id: Optional[int]
    snapshot_version: Optional[int]
    snapshot_summary: Optional[str]
    snapshot_size: Optional[int]
    apaas_app_id_before: Optional[str]
    apaas_app_id_after: Optional[str]
    error_message: Optional[str]
    created_at: Optional[str]
    completed_at: Optional[str]


class DeployRecordDetail(DeployRecordSummary):
    event_log: Optional[List[dict]]
    snapshot_content: Optional[str]


@router.get("/{app_id}/deploy-records")
async def list_deploy_records(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """列出某应用的部署历史（最新在前，分页 ≤ 200）"""
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    total_result = await db.execute(
        select(sa_func.count())
        .select_from(DeployRecord)
        .where(DeployRecord.app_id == app_id)
    )
    total = total_result.scalar() or 0

    query = (
        select(DeployRecord)
        .where(DeployRecord.app_id == app_id)
        .order_by(desc(DeployRecord.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    records = result.scalars().all()

    # 一次性把所有 snapshot 拉出来（含 summary / size）
    snap_ids = [r.snapshot_artifact_id for r in records if r.snapshot_artifact_id]
    snap_map: dict[int, ConfigSnapshot] = {}
    if snap_ids:
        snap_result = await db.execute(
            select(ConfigSnapshot).where(ConfigSnapshot.id.in_(snap_ids))
        )
        for s in snap_result.scalars().all():
            snap_map[s.id] = s

    items = []
    for r in records:
        snap = snap_map.get(r.snapshot_artifact_id) if r.snapshot_artifact_id else None
        items.append({
            "id": r.id,
            "app_id": r.app_id,
            "user_id": r.user_id,
            "version_label": r.version_label,
            "status": r.status,
            "deploy_type": r.deploy_type,
            "snapshot_artifact_id": r.snapshot_artifact_id,
            "snapshot_version": snap.version if snap else None,
            "snapshot_summary": snap.summary if snap else None,
            "snapshot_size": len(snap.config_json) if snap and snap.config_json else None,
            "apaas_app_id_before": r.apaas_app_id_before,
            "apaas_app_id_after": r.apaas_app_id_after,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.get("/{app_id}/deploy-records/{record_id}")
async def get_deploy_record(
    app_id: int,
    record_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """单条部署记录详情（含 SPEC snapshot 完整 content + event log）"""
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    rec_result = await db.execute(
        select(DeployRecord).where(
            DeployRecord.id == record_id,
            DeployRecord.app_id == app_id,
        )
    )
    rec = rec_result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="部署记录不存在")

    snap = None
    if rec.snapshot_artifact_id:
        snap_result = await db.execute(
            select(ConfigSnapshot).where(ConfigSnapshot.id == rec.snapshot_artifact_id)
        )
        snap = snap_result.scalar_one_or_none()

    return {
        "id": rec.id,
        "app_id": rec.app_id,
        "user_id": rec.user_id,
        "version_label": rec.version_label,
        "status": rec.status,
        "deploy_type": rec.deploy_type,
        "snapshot_artifact_id": rec.snapshot_artifact_id,
        "snapshot_version": snap.version if snap else None,
        "snapshot_summary": snap.summary if snap else None,
        "snapshot_size": len(snap.config_json) if snap and snap.config_json else None,
        "snapshot_content": snap.config_json if snap else None,
        "apaas_app_id_before": rec.apaas_app_id_before,
        "apaas_app_id_after": rec.apaas_app_id_after,
        "error_message": rec.error_message,
        "event_log": rec.event_log_json,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
    }


class RollbackRequest(BaseModel):
    to_record_id: int


@router.post("/{app_id}/rollback")
async def rollback_application(
    app_id: int,
    body: RollbackRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """回滚应用到指定部署记录的 SPEC 快照。

    流程：
      1. 找到目标 record + 关联 snapshot
      2. 把 snapshot.config_json 写回 application.config_preview
       （requirement_doc 跟 config_preview 是同源，逻辑上回滚 config_preview 足够；
       requirement_doc 是 doc-driven flow 里同步更新的，rollback 不主动覆盖以避免
       覆盖用户线下编辑过的 md）
      3. 落一条新的 DeployRecord(deploy_type='rollback', status='success'),
         apaas_app_id 不变（回滚只是把 SPEC 切回老版本，重新 deploy 由用户后续触发）
      4. 同时把 application.status 设为 'updating'，提示用户去重新部署

    注意：本 endpoint 不直接触发 /generate SSE 真去 redeploy 到 apaas — 因为：
    a) /generate 是 SSE 长连接，POST 套不进来
    b) 用户拿到回滚成功响应后可以自己再点"部署"重新跑 generate（复用现有链路）
    """
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    rec_result = await db.execute(
        select(DeployRecord).where(
            DeployRecord.id == body.to_record_id,
            DeployRecord.app_id == app_id,
        )
    )
    rec = rec_result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="目标部署记录不存在")

    if not rec.snapshot_artifact_id:
        raise HTTPException(
            status_code=400,
            detail="目标部署记录没有可用的 SPEC 快照，无法回滚",
        )

    snap_result = await db.execute(
        select(ConfigSnapshot).where(ConfigSnapshot.id == rec.snapshot_artifact_id)
    )
    snap = snap_result.scalar_one_or_none()
    if not snap:
        raise HTTPException(
            status_code=400,
            detail="目标部署记录关联的 SPEC 快照已被删除，无法回滚",
        )

    # 1. 把 snapshot config 写回应用
    try:
        snapshot_config = json.loads(snap.config_json) if snap.config_json else None
    except json.JSONDecodeError:
        snapshot_config = None
    if not snapshot_config:
        raise HTTPException(
            status_code=400,
            detail="目标快照内容无效（JSON 解析失败）",
        )

    app.config_preview = snap.config_json
    # 标记应用为 updating 让用户去重新部署
    if app.apaas_app_id:
        app.status = "updating"

    # 2. 新建一条 rollback 类型的 record（status=success，因为回滚 SPEC 这一步本身完成了）
    new_record = DeployRecord(
        app_id=app_id,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user.id,
        version_label=f"rollback→record#{rec.id}",
        status="success",
        deploy_type="rollback",
        snapshot_artifact_id=rec.snapshot_artifact_id,
        apaas_app_id_before=app.apaas_app_id,
        apaas_app_id_after=app.apaas_app_id,
        completed_at=datetime.utcnow(),
        event_log_json=[{
            "type": "rollback",
            "target_record_id": rec.id,
            "target_snapshot_id": rec.snapshot_artifact_id,
            "target_snapshot_version": snap.version,
            "message": f"已回滚 SPEC 到 record#{rec.id} 的快照 v{snap.version}",
        }],
    )
    db.add(new_record)

    # 3. 把回滚动作也存为 ConfigSnapshot，链路上看得见
    rollback_snapshot = ConfigSnapshot(
        application_id=app_id,
        version=(snap.version or 0) + 0,  # 用同版本号，summary 解释清楚
        config_json=snap.config_json,
        source="rollback",
        summary=f"回滚到 record#{rec.id} (v{snap.version})",
    )
    # 用 max+1
    max_v_result = await db.execute(
        select(sa_func.max(ConfigSnapshot.version))
        .where(ConfigSnapshot.application_id == app_id)
    )
    max_v = max_v_result.scalar() or 0
    rollback_snapshot.version = max_v + 1
    db.add(rollback_snapshot)

    await db.commit()
    await db.refresh(new_record)

    return {
        "ok": True,
        "record_id": new_record.id,
        "snapshot_version": snap.version,
        "message": f"已回滚到 record#{rec.id} 的 SPEC 快照（v{snap.version}）。请前往应用页重新部署到平台。",
        "next_action": "需要重新点击部署按钮，把回滚后的 SPEC 推送到 aPaaS 平台",
    }
