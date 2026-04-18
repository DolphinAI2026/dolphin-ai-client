"""变更计划（change plans）相关路由。

4 条：
  GET    /{app_id}/change-plans/{plan_id}
  PUT    /{app_id}/change-plans/{plan_id}/selections
  POST   /{app_id}/change-plans/{plan_id}/cancel
  POST   /{app_id}/change-plans/{plan_id}/execute

从 applications.__init__ 拆出；对外 URL 与契约保持不变（由 routes_inventory snapshot 兜底）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.database import get_db
from app.models import Application, ChangePlan, DocumentVersion
from app.deps import get_auth_context, AuthContext
from app.permissions import check_resource_permission, Action
from app.json_utils import loads_if_str

router = APIRouter()
logger = logging.getLogger(__name__)


class SelectionsUpdate(BaseModel):
    """更新 change plan 中 actions 的选择状态"""
    selections: dict  # {action_id: bool}


@router.get("/{app_id}/change-plans/{plan_id}")
async def get_change_plan(
    app_id: int,
    plan_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取变更计划详情"""
    # 验证应用权限
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    result = await db.execute(
        select(ChangePlan).where(ChangePlan.id == plan_id, ChangePlan.application_id == app_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="变更计划不存在")

    return {
        "id": plan.id,
        "application_id": plan.application_id,
        "conversation_id": plan.conversation_id,
        "from_version": plan.from_version,
        "to_version": plan.to_version,
        "diff_summary": loads_if_str(plan.diff_summary),
        "actions": loads_if_str(plan.actions),
        "status": plan.status,
        "created_at": str(plan.created_at) if plan.created_at else None,
        "executed_at": str(plan.executed_at) if plan.executed_at else None,
    }


@router.put("/{app_id}/change-plans/{plan_id}/selections")
async def update_change_plan_selections(
    app_id: int,
    plan_id: int,
    body: SelectionsUpdate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """更新变更计划中各 action 的勾选状态"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    result = await db.execute(
        select(ChangePlan).where(ChangePlan.id == plan_id, ChangePlan.application_id == app_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="变更计划不存在")
    if plan.status != "pending":
        raise HTTPException(status_code=400, detail=f"变更计划状态为 {plan.status}，不能修改")

    actions = loads_if_str(plan.actions)
    for action in actions:
        aid = action.get("id")
        if aid and aid in body.selections:
            action["selected"] = body.selections[aid]

    plan.actions = json.dumps(actions, ensure_ascii=False)
    await db.commit()
    return {"ok": True, "actions": actions}


@router.post("/{app_id}/change-plans/{plan_id}/cancel")
async def cancel_change_plan(
    app_id: int,
    plan_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """取消变更计划：
    - 标记 ChangePlan.status = cancelled
    - 应用 status 回到 completed
    - current_doc_version + config_preview 回滚到 plan.from_version
      （V2 文档保留在历史里，只是不再作为当前版本）
    """
    from . import _dump_preview_config

    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    result = await db.execute(
        select(ChangePlan).where(ChangePlan.id == plan_id, ChangePlan.application_id == app_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="变更计划不存在")
    if plan.status not in ("pending", "confirmed"):
        raise HTTPException(status_code=400, detail=f"变更计划状态为 {plan.status}，不能取消")

    # 回滚到 from_version 的文档版本（V1）的 parsed_config
    from_version = plan.from_version
    if from_version:
        v1_result = await db.execute(
            select(DocumentVersion).where(
                DocumentVersion.application_id == app_id,
                DocumentVersion.version == from_version,
            )
        )
        v1_doc = v1_result.scalar_one_or_none()
        if v1_doc and v1_doc.parsed_config:
            try:
                v1_config = loads_if_str(v1_doc.parsed_config)
                if app.app_name:
                    v1_config["appName"] = app.app_name
                app.config_preview = _dump_preview_config(v1_config)
                app.current_doc_version = from_version
            except Exception as e:
                logger.warning(f"取消变更计划时回滚 config_preview 失败: {e}")

    plan.status = "cancelled"
    if app.status == "updating":
        app.status = "completed"

    await db.commit()
    return {"ok": True, "app_status": app.status, "current_doc_version": app.current_doc_version}


@router.post("/{app_id}/change-plans/{plan_id}/execute")
async def execute_change_plan(
    app_id: int,
    plan_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """执行变更计划，将选中的 actions 应用到 config_preview 并同步到得帆云平台（SSE 流式返回进度）"""
    # _dump_preview_config 位于 parent package __init__.py（避免循环依赖放在函数体内 import）
    from . import _dump_preview_config

    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    result = await db.execute(
        select(ChangePlan).where(ChangePlan.id == plan_id, ChangePlan.application_id == app_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="变更计划不存在")
    if plan.status not in ("pending", "confirmed"):
        raise HTTPException(status_code=400, detail=f"变更计划状态为 {plan.status}，不能执行")

    apaas_app_id = app.apaas_app_id
    app_name = app.app_name
    apaas_token = None
    apaas_base_url = None
    apaas_tenant_id = None
    platform_client_error = None

    try:
        from app.routes.incremental_update import _get_platform_client_for_app
        platform_client = await _get_platform_client_for_app(app, ctx.user, db)
        apaas_token = getattr(platform_client, "token", None)
        apaas_base_url = getattr(platform_client, "base_url", None)
        apaas_tenant_id = getattr(platform_client, "tenant_id", None)
    except Exception as e:
        platform_client_error = str(e)
        logger.warning(f"执行变更计划时获取平台连接失败: {e}")

    app_id_val = app.id
    current_config_str = app.config_preview
    plan_id_val = plan.id
    actions_str = plan.actions
    plan_from_version = plan.from_version
    plan_to_version = plan.to_version

    async def event_generator():
        from app.database import AsyncSessionLocal
        from app.doc_differ import apply_actions_to_config
        from app.apaas_client import APaaSClient
        from app.config_diff import compute_config_diff
        from app.incremental_executor import IncrementalExecutor, fetch_remote_data

        try:
            yield {"event": "progress", "data": json.dumps({"step": "加载当前配置..."}, ensure_ascii=False)}

            # 加载基础配置：优先使用 from_version 的 parsed_config（避免 config_preview 已被更新为 V2 导致 apply_actions 重复）
            current_config: dict = {}
            async with AsyncSessionLocal() as session:
                from_doc = await session.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.application_id == app_id_val,
                        DocumentVersion.version == plan_from_version
                    )
                )
                from_doc_obj = from_doc.scalar_one_or_none()
                if from_doc_obj and from_doc_obj.parsed_config:
                    try:
                        current_config = loads_if_str(from_doc_obj.parsed_config)
                    except Exception:
                        pass

            # 回退：如果没有找到 from_version 的配置，使用 config_preview
            if not current_config and current_config_str:
                try:
                    loaded = loads_if_str(current_config_str)
                    current_config = loaded.get("data", loaded)
                except Exception:
                    pass

            actions = loads_if_str(actions_str)
            selected = [a for a in actions if a.get("selected", True)]

            yield {"event": "progress", "data": json.dumps({"step": f"应用 {len(selected)} 项变更..."}, ensure_ascii=False)}

            # 应用 patch 得到 new_config（基于 from_version 的配置）
            new_config = apply_actions_to_config(current_config, actions)

            # 判断是否需要同步到平台
            can_sync = apaas_token and apaas_base_url and apaas_app_id
            sync_result = None
            sync_errors = []

            if can_sync:
                yield {"event": "progress", "data": json.dumps({"step": "同步到得帆云平台..."}, ensure_ascii=False)}
                try:
                    # 创建 APaaSClient
                    client = APaaSClient(
                        base_url=apaas_base_url,
                        token=apaas_token,
                        tenant_id=apaas_tenant_id
                    )

                    # 获取远程数据
                    yield {"event": "progress", "data": json.dumps({"step": "获取平台现有资源..."}, ensure_ascii=False)}
                    remote_data = await fetch_remote_data(client, apaas_app_id)

                    # 计算差异（会自动完成编码继承）
                    yield {"event": "progress", "data": json.dumps({"step": "计算资源变更差异..."}, ensure_ascii=False)}
                    diff = compute_config_diff(current_config, new_config, remote_data)
                    # 使用编码继承后的配置，确保 V1 的 code 被保留
                    if diff.normalized_new_config:
                        new_config = diff.normalized_new_config

                    if diff.has_changes:
                        # 创建执行器并执行
                        executor = IncrementalExecutor(
                            client,
                            apaas_app_id,
                            app_name,
                            target_config=new_config,
                        )

                        # 流式执行差异
                        async for progress in executor.execute_diff_stream(diff):
                            if progress.get("type") == "complete":
                                sync_result = progress.get("result", {})
                                if not sync_result.get("success", True):
                                    sync_errors.extend(sync_result.get("errors", []) or ["平台同步失败"])
                            elif progress.get("type") == "error":
                                sync_errors.append(progress.get("message", "未知错误"))
                            else:
                                # 转发执行进度
                                step_msg = progress.get("step", "")
                                yield {"event": "progress", "data": json.dumps({"step": f"平台同步: {step_msg}"}, ensure_ascii=False)}
                    else:
                        logger.info("无平台资源变更需要同步")
                        sync_result = {"message": "无变更需要同步"}

                except Exception as e:
                    logger.warning(f"平台同步失败: {e}", exc_info=True)
                    sync_errors.append(str(e))
            else:
                if apaas_app_id and (not apaas_token or not apaas_base_url):
                    missing_parts = []
                    if not apaas_token:
                        missing_parts.append("平台登录凭证")
                    if not apaas_base_url:
                        missing_parts.append("平台地址")
                    detail = f"缺少{ '、'.join(missing_parts) }，无法同步到平台"
                    if platform_client_error:
                        detail = f"{detail}（{platform_client_error}）"
                    sync_errors.append(detail)
                elif not apaas_app_id:
                    sync_errors.append("应用尚未关联平台应用，无法执行平台更新")

            if sync_errors:
                detail = "；".join([str(err) for err in sync_errors if err]) or "平台同步失败"
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "message": f"平台执行失败：{detail}",
                        "sync_errors": sync_errors,
                        "sync_result": sync_result,
                    }, ensure_ascii=False),
                }
                return

            yield {"event": "progress", "data": json.dumps({"step": "保存本地配置..."}, ensure_ascii=False)}

            # 保存本地配置
            async with AsyncSessionLocal() as session:
                app_result = await session.execute(
                    select(Application).where(Application.id == app_id_val)
                )
                app_obj = app_result.scalar_one()
                app_obj.config_preview = _dump_preview_config(new_config)

                plan_result = await session.execute(
                    select(ChangePlan).where(ChangePlan.id == plan_id_val)
                )
                plan_obj = plan_result.scalar_one()
                plan_obj.status = "completed"
                plan_obj.executed_at = datetime.utcnow()

                # 更新应用状态为已部署
                app_result = await session.execute(
                    select(Application).where(Application.id == app_id)
                )
                app_obj = app_result.scalar_one()
                app_obj.status = "completed"

                await session.commit()

            # 构建响应数据
            response_data = {
                "config": new_config,
                "applied_count": len(selected),
                "total_count": len(actions),
                "platform_synced": can_sync and not sync_errors,
            }
            if sync_result:
                response_data["sync_result"] = sync_result
            if sync_errors:
                response_data["sync_errors"] = sync_errors

            yield {
                "event": "done",
                "data": json.dumps(response_data, ensure_ascii=False),
            }

        except Exception as e:
            logger.error(f"变更计划执行失败: {e}", exc_info=True)
            yield {"event": "error", "data": json.dumps({"message": f"执行失败: {str(e)}"}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())
