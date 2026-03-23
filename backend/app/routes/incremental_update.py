"""
增量更新 API 路由

提供配置差异计算、预览和执行的接口
"""

from __future__ import annotations
import json
import logging
from typing import Annotated, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from jose import JWTError, jwt

from app.database import get_db, AsyncSessionLocal
from app.models import User, Application
from app.deps import get_auth_context, AuthContext
from app.permissions import check_resource_permission, Action
from app.config_diff import compute_config_diff, ConfigDiff
from app.incremental_executor import IncrementalExecutor, ExecutionResult, fetch_remote_data
from app.apaas_client import APaaSClient
from app.config import settings

router = APIRouter(prefix="/applications", tags=["增量更新"])
logger = logging.getLogger(__name__)


# ==================== 请求/响应模型 ====================

class DiffRequest(BaseModel):
    """差异计算请求"""
    new_config: Dict[str, Any]


class DiffResponse(BaseModel):
    """差异计算响应"""
    has_changes: bool
    summary: str
    role_changes: list
    dict_changes: list
    model_changes: list
    form_changes: list
    process_changes: list
    warnings: list
    unsupported_changes: list


class ExecuteRequest(BaseModel):
    """执行请求"""
    new_config: Dict[str, Any]
    # 可选：跳过某些变更类型
    skip_roles: bool = False
    skip_dicts: bool = False
    skip_models: bool = False
    skip_forms: bool = False
    skip_processes: bool = False


class ExecuteResponse(BaseModel):
    """执行响应"""
    success: bool
    results: Dict[str, list]
    errors: list
    warnings: list


# ==================== API 路由 ====================

@router.post("/{app_id}/incremental/diff", response_model=DiffResponse)
async def compute_diff(
    app_id: int,
    request: DiffRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    对比新旧配置，返回差异报告

    - 获取应用当前配置（old_config）
    - 与请求中的新配置（new_config）对比
    - 返回详细的变更列表
    """
    # 1. 获取应用
    app = await _get_application(app_id, ctx.tenant_id, db)
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    # 2. 获取旧配置
    old_config = None
    if app.config_preview:
        try:
            old_config = json.loads(app.config_preview) if isinstance(app.config_preview, str) else app.config_preview
        except Exception:
            pass

    # 3. 获取平台远程数据（用于填充 remote_id）
    remote_data = None
    if app.apaas_app_id and ctx.user.apaas_token:
        try:
            client = APaaSClient(
                base_url=ctx.user.apaas_base_url,
                tenant_id=ctx.user.apaas_tenant_id,
                token=ctx.user.apaas_token
            )
            remote_data = await fetch_remote_data(client, app.apaas_app_id)
        except Exception as e:
            logger.warning(f"获取平台远程数据失败: {e}")

    # 4. 计算差异
    diff = compute_config_diff(old_config, request.new_config, remote_data)

    logger.info(
        f"应用 {app_id} 配置差异计算完成: has_changes={diff.has_changes}, summary={diff.summary}"
    )

    return DiffResponse(**diff.to_dict())


@router.post("/{app_id}/incremental/preview", response_model=DiffResponse)
async def preview_update(
    app_id: int,
    request: DiffRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    预览增量更新（与 /diff 相同，但语义上用于执行前预览）

    返回将要执行的变更列表，供用户确认
    """
    return await compute_diff(app_id, request, ctx, db)


@router.post("/{app_id}/incremental/execute", response_model=ExecuteResponse)
async def execute_update(
    app_id: int,
    request: ExecuteRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    执行增量更新

    - 计算配置差异
    - 调用平台 API 执行变更
    - 更新本地配置
    """
    # 1. 获取应用
    app = await _get_application(app_id, ctx.tenant_id, db)
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    # 2. 检查是否已连接平台
    if not ctx.user.apaas_token:
        raise HTTPException(status_code=400, detail="未连接得帆云平台，请先在设置中连接APaaS平台")

    if not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用尚未在平台创建，请先完成首次生成")

    # 3. 获取旧配置
    old_config = None
    if app.config_preview:
        try:
            old_config = json.loads(app.config_preview) if isinstance(app.config_preview, str) else app.config_preview
        except Exception:
            pass

    # 4. 获取平台远程数据
    client = APaaSClient(
        base_url=ctx.user.apaas_base_url,
        tenant_id=ctx.user.apaas_tenant_id,
        token=ctx.user.apaas_token
    )

    try:
        remote_data = await fetch_remote_data(client, app.apaas_app_id)
    except Exception as e:
        logger.error(f"获取平台远程数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取平台数据失败: {e}")

    # 5. 计算差异
    diff = compute_config_diff(old_config, request.new_config, remote_data)

    if not diff.has_changes:
        return ExecuteResponse(
            success=True,
            results={"roles": [], "dicts": [], "models": [], "forms": [], "processes": []},
            errors=[],
            warnings=["无变更需要执行"]
        )

    # 6. 根据跳过选项过滤变更
    if request.skip_roles:
        diff.role_changes = []
    if request.skip_dicts:
        diff.dict_changes = []
    if request.skip_models:
        diff.model_changes = []
    if request.skip_forms:
        diff.form_changes = []
    if request.skip_processes:
        diff.process_changes = []

    # 7. 执行增量更新
    executor = IncrementalExecutor(
        client=client,
        app_id=app.apaas_app_id,
        app_name=app.app_name
    )

    try:
        result = await executor.execute_diff(diff)
    except Exception as e:
        logger.error(f"增量更新执行失败: {e}")
        raise HTTPException(status_code=500, detail=f"增量更新执行失败: {e}")

    # 8. 更新本地配置
    if result.success:
        app.config_preview = json.dumps(request.new_config, ensure_ascii=False)
        await db.commit()
        logger.info(f"应用 {app_id} 配置已更新")

    return ExecuteResponse(**result.to_dict())


@router.get("/{app_id}/incremental/execute-stream")
async def execute_update_stream(
    app_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Optional[str] = Query(None),
    new_config: Optional[str] = Query(None),
):
    """
    流式执行增量更新（SSE）

    通过 Server-Sent Events 返回实时进度：
    - event: progress / data: {"stage": "roles", "status": "running", "step": "..."}
    - event: done / data: {"type": "complete", "result": {...}}
    - event: error / data: {"type": "error", "message": "..."}

    注意：SSE 不支持 POST body，配置通过 query 参数 new_config 传递（URL 编码的 JSON）
    """
    # SSE 不支持 Authorization header，通过 query param 传 token
    if not token:
        raise HTTPException(status_code=401, detail="缺少认证token")

    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = int(payload.get("sub", 0))
        tenant_id = payload.get("tid")
        if tenant_id is None:
            raise HTTPException(status_code=403, detail="平台管理员无法执行此操作")
        tenant_id = int(tenant_id)
    except (JWTError, Exception):
        raise HTTPException(status_code=401, detail="无效的认证凭证")

    # 获取用户
    result = await db.execute(select(User).where(User.id == user_id))
    current_user = result.scalar_one_or_none()
    if not current_user:
        raise HTTPException(status_code=401, detail="用户不存在")

    # 获取应用
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == tenant_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    if not current_user.apaas_token:
        raise HTTPException(status_code=400, detail="未连接得帆云平台")

    if not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用尚未在平台创建")

    # 解析新配置
    if not new_config:
        raise HTTPException(status_code=400, detail="缺少 new_config 参数")

    try:
        new_config_dict = json.loads(new_config)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="new_config 格式错误")

    # 保存需要的变量
    apaas_app_id = app.apaas_app_id
    app_name = app.app_name
    old_config_str = app.config_preview
    apaas_base_url = current_user.apaas_base_url
    apaas_tenant_id = current_user.apaas_tenant_id
    apaas_token = current_user.apaas_token

    async def event_generator():
        async with AsyncSessionLocal() as session:
            try:
                # 1. 获取旧配置
                old_config = None
                if old_config_str:
                    try:
                        old_config = json.loads(old_config_str) if isinstance(old_config_str, str) else old_config_str
                    except Exception:
                        pass

                yield {"event": "progress", "data": json.dumps({"stage": "init", "status": "running", "step": "初始化..."}, ensure_ascii=False)}

                # 2. 创建客户端并获取远程数据
                client = APaaSClient(
                    base_url=apaas_base_url,
                    tenant_id=apaas_tenant_id,
                    token=apaas_token
                )

                yield {"event": "progress", "data": json.dumps({"stage": "init", "status": "running", "step": "获取平台数据..."}, ensure_ascii=False)}

                remote_data = await fetch_remote_data(client, apaas_app_id)

                # 3. 计算差异
                yield {"event": "progress", "data": json.dumps({"stage": "init", "status": "running", "step": "计算配置差异..."}, ensure_ascii=False)}

                diff = compute_config_diff(old_config, new_config_dict, remote_data)

                if not diff.has_changes:
                    yield {"event": "done", "data": json.dumps({"type": "complete", "message": "无变更需要执行", "result": {"success": True, "results": {}, "errors": [], "warnings": []}}, ensure_ascii=False)}
                    return

                yield {"event": "progress", "data": json.dumps({"stage": "init", "status": "done", "step": f"发现 {diff.summary}"}, ensure_ascii=False)}

                # 4. 执行增量更新（流式）
                executor = IncrementalExecutor(
                    client=client,
                    app_id=apaas_app_id,
                    app_name=app_name
                )

                async for event in executor.execute_diff_stream(diff):
                    if event.get("type") == "complete":
                        # 更新本地配置
                        result = await session.execute(
                            select(Application).where(Application.id == app_id)
                        )
                        app_obj = result.scalar_one()
                        app_obj.config_preview = json.dumps(new_config_dict, ensure_ascii=False)
                        await session.commit()
                        logger.info(f"应用 {app_id} 配置已更新")

                        yield {"event": "done", "data": json.dumps(event, ensure_ascii=False)}
                    elif event.get("type") == "error":
                        yield {"event": "error", "data": json.dumps(event, ensure_ascii=False)}
                    else:
                        yield {"event": "progress", "data": json.dumps(event, ensure_ascii=False)}

            except Exception as e:
                logger.exception(f"增量更新失败: {e}")
                yield {"event": "error", "data": json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.get("/{app_id}/incremental/remote-data")
async def get_remote_data(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    获取应用在平台上的远程数据

    用于调试或手动对比
    """
    app = await _get_application(app_id, ctx.tenant_id, db)
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    if not ctx.user.apaas_token:
        raise HTTPException(status_code=400, detail="未连接得帆云平台")

    if not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用尚未在平台创建")

    client = APaaSClient(
        base_url=ctx.user.apaas_base_url,
        tenant_id=ctx.user.apaas_tenant_id,
        token=ctx.user.apaas_token
    )

    try:
        remote_data = await fetch_remote_data(client, app.apaas_app_id)
        return remote_data
    except Exception as e:
        logger.error(f"获取平台远程数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取平台数据失败: {e}")


# ==================== 辅助函数 ====================

async def _get_application(app_id: int, tenant_id: int, db: AsyncSession) -> Application:
    """获取应用，不存在则抛出 404"""
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == tenant_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    return app
