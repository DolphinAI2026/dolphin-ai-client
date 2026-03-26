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
from app.models import User, Application, PlatformEnv
from app.deps import get_auth_context, AuthContext
from app.permissions import check_resource_permission, Action
from app.config_diff import compute_config_diff, ConfigDiff
from app.incremental_executor import IncrementalExecutor, ExecutionResult, fetch_remote_data
from app.apaas_client import APaaSClient
from app.config import settings
from app.app_locks import acquire_app_lock
from app.platform_sync import sync_from_platform
from app.config_version import (
    save_config_snapshot, get_version_history,
    get_snapshot_config, three_way_diff,
)
from app.models import ConfigSnapshot

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


class SelectedChange(BaseModel):
    """选中的单个变更项"""
    type: str       # "role" | "dict" | "model" | "form" | "process"
    code: str       # 资源编码
    change_type: str  # "added" | "modified" | "deleted"


class ExecuteRequest(BaseModel):
    """执行请求"""
    new_config: Dict[str, Any]
    # 可选：跳过某些变更类型
    skip_roles: bool = False
    skip_dicts: bool = False
    skip_models: bool = False
    skip_forms: bool = False
    skip_processes: bool = False
    # 可选：选择性执行（如果提供，只执行选中的变更）
    selected_changes: Optional[list] = None


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
    if app.apaas_app_id:
        try:
            client = await _get_platform_client_for_app(app, ctx.user, db)
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
    try:
        client = await _get_platform_client_for_app(app, ctx.user, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"未连接得帆云平台，请先在环境管理中添加并连接: {e}")

    try:
        remote_data = await fetch_remote_data(client, app.apaas_app_id)
    except Exception as e:
        logger.error(f"获取平台远程数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取平台数据失败: {e}")

    # 5-8: 计算差异并执行（加并发锁保护）
    async with acquire_app_lock(app_id, "增量更新执行"):
        diff = compute_config_diff(old_config, request.new_config, remote_data)

        if not diff.has_changes:
            return ExecuteResponse(
                success=True,
                results={"roles": [], "dicts": [], "models": [], "forms": [], "processes": []},
                errors=[],
                warnings=["无变更需要执行"]
            )

        # 根据跳过选项过滤变更
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

        # 选择性执行：只保留用户勾选的变更
        if request.selected_changes is not None:
            selected_set = {
                (s.get("type") if isinstance(s, dict) else s.type,
                 s.get("code") if isinstance(s, dict) else s.code)
                for s in request.selected_changes
            }
            diff.role_changes = [c for c in diff.role_changes if ("role", c.code) in selected_set]
            diff.dict_changes = [c for c in diff.dict_changes if ("dict", c.code) in selected_set]
            diff.model_changes = [c for c in diff.model_changes if ("model", c.code) in selected_set]
            diff.form_changes = [c for c in diff.form_changes if ("form", c.code) in selected_set]
            diff.process_changes = [c for c in diff.process_changes if ("process", c.code) in selected_set]

        # 执行增量更新
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

        # 更新本地配置 + 保存快照（使用编码继承修正后的配置）
        if result.success:
            save_config = diff.normalized_new_config or request.new_config
            app.config_preview = json.dumps(save_config, ensure_ascii=False)
            await save_config_snapshot(db, app_id, save_config, source="incremental", summary="增量更新")
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

    if not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用尚未在平台创建")

    # 解析新配置
    if not new_config:
        raise HTTPException(status_code=400, detail="缺少 new_config 参数")

    try:
        new_config_dict = json.loads(new_config)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="new_config 格式错误")

    client = await _get_platform_client_for_app(app, current_user, db)

    return _build_execute_stream_response(
        app_id=app_id,
        app_name=app.app_name,
        apaas_app_id=app.apaas_app_id,
        old_config_str=app.config_preview,
        apaas_base_url=client.base_url,
        apaas_tenant_id=client.tenant_id,
        apaas_token=client.token or "",
        request=ExecuteRequest(new_config=new_config_dict),
    )


@router.post("/{app_id}/incremental/execute-stream")
async def execute_update_stream_post(
    app_id: int,
    request: ExecuteRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """流式执行增量更新（POST），避免大配置走 query string 导致连接失败。"""
    app = await _get_application(app_id, ctx.tenant_id, db)
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    if not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用尚未在平台创建")

    client = await _get_platform_client_for_app(app, ctx.user, db)

    return _build_execute_stream_response(
        app_id=app_id,
        app_name=app.app_name,
        apaas_app_id=app.apaas_app_id,
        old_config_str=app.config_preview,
        apaas_base_url=client.base_url,
        apaas_tenant_id=client.tenant_id,
        apaas_token=client.token or "",
        request=request,
    )


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

    if not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用尚未在平台创建")

    client = await _get_platform_client_for_app(app, ctx.user, db)

    try:
        remote_data = await fetch_remote_data(client, app.apaas_app_id)
        return remote_data
    except Exception as e:
        logger.error(f"获取平台远程数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取平台数据失败: {e}")


# ==================== 平台同步 ====================

class SyncApplyRequest(BaseModel):
    """同步应用请求"""
    strategy: str = "platform_wins"  # "platform_wins" | "local_wins"


@router.get("/{app_id}/incremental/sync-preview")
async def sync_preview(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    预览平台同步：对比平台当前状态与本地配置的差异

    返回：平台配置 + diff 报告
    """
    app = await _get_application(app_id, ctx.tenant_id, db)
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    if not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用尚未在平台创建")

    client = await _get_platform_client_for_app(app, ctx.user, db)

    try:
        platform_config = await sync_from_platform(client, app.apaas_app_id, app.app_name or "")
    except Exception as e:
        logger.error(f"平台同步失败: {e}")
        raise HTTPException(status_code=500, detail=f"平台同步失败: {e}")

    # 本地配置
    local_config = None
    if app.config_preview:
        try:
            local_config = json.loads(app.config_preview) if isinstance(app.config_preview, str) else app.config_preview
        except Exception:
            pass

    # 计算差异：以本地为 old，平台为 new
    diff = compute_config_diff(local_config, platform_config)

    return {
        "platform_config": platform_config,
        "local_config": local_config,
        "diff": diff.to_dict(),
    }


@router.post("/{app_id}/incremental/sync-apply")
async def sync_apply(
    app_id: int,
    request: SyncApplyRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    应用平台同步结果

    strategy:
    - "platform_wins": 用平台配置覆盖本地（拉取）
    - "local_wins": 保持本地配置不变（忽略平台差异）
    """
    app = await _get_application(app_id, ctx.tenant_id, db)
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    if request.strategy == "platform_wins":
        if not app.apaas_app_id:
            raise HTTPException(status_code=400, detail="应用尚未在平台创建")

        client = await _get_platform_client_for_app(app, ctx.user, db)

        try:
            platform_config = await sync_from_platform(client, app.apaas_app_id, app.app_name or "")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"平台同步失败: {e}")

        app.config_preview = json.dumps(platform_config, ensure_ascii=False)
        await save_config_snapshot(db, app_id, platform_config, source="sync", summary="平台同步(platform_wins)")
        await db.commit()
        logger.info(f"应用 {app_id} 已同步为平台配置 (platform_wins)")

        return {"success": True, "message": "已同步为平台配置", "config": platform_config}

    elif request.strategy == "local_wins":
        return {"success": True, "message": "保持本地配置不变"}

    else:
        raise HTTPException(status_code=400, detail=f"未知同步策略: {request.strategy}")


# ==================== 版本管理 ====================

@router.get("/{app_id}/incremental/versions")
async def list_versions(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(50, le=100),
):
    """获取配置版本历史"""
    app = await _get_application(app_id, ctx.tenant_id, db)
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)
    history = await get_version_history(db, app_id, limit)
    return {"versions": history}


@router.get("/{app_id}/incremental/versions/{version}")
async def get_version(
    app_id: int,
    version: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取指定版本的配置内容"""
    app = await _get_application(app_id, ctx.tenant_id, db)
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)
    config = await get_snapshot_config(db, app_id, version)
    if config is None:
        raise HTTPException(status_code=404, detail=f"版本 {version} 不存在")
    return {"version": version, "config": config}


class RollbackRequest(BaseModel):
    target_version: int


@router.post("/{app_id}/incremental/rollback")
async def rollback_version(
    app_id: int,
    request: RollbackRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    回滚到指定版本

    1. 加载目标版本配置
    2. 计算当前 → 目标的 diff（用于展示）
    3. 更新 config_preview 为目标版本
    4. 保存新快照（source=rollback）
    """
    app = await _get_application(app_id, ctx.tenant_id, db)
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    target_config = await get_snapshot_config(db, app_id, request.target_version)
    if target_config is None:
        raise HTTPException(status_code=404, detail=f"版本 {request.target_version} 不存在")

    # 当前配置
    current_config = None
    if app.config_preview:
        try:
            current_config = json.loads(app.config_preview) if isinstance(app.config_preview, str) else app.config_preview
        except Exception:
            pass

    # 计算 diff（仅供参考）
    diff = compute_config_diff(current_config, target_config)

    # 执行回滚
    async with acquire_app_lock(app_id, "版本回滚"):
        app.config_preview = json.dumps(target_config, ensure_ascii=False)
        await save_config_snapshot(
            db, app_id, target_config,
            source="rollback",
            summary=f"回滚到 v{request.target_version}",
        )
        await db.commit()

    logger.info(f"应用 {app_id} 已回滚到 v{request.target_version}")

    return {
        "success": True,
        "message": f"已回滚到 v{request.target_version}",
        "diff": diff.to_dict(),
        "config": target_config,
    }


class ConflictCheckRequest(BaseModel):
    """冲突检测请求"""
    incoming_config: Dict[str, Any]
    base_version: Optional[int] = None  # 如果不指定，用上一次文档版本


@router.post("/{app_id}/incremental/check-conflicts")
async def check_conflicts(
    app_id: int,
    request: ConflictCheckRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    三方冲突检测

    对比 base（公共基础） vs current（当前本地） vs incoming（新来源），
    检测双方都修改了同一资源的冲突。
    """
    app = await _get_application(app_id, ctx.tenant_id, db)
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    # 当前配置
    current_config = None
    if app.config_preview:
        try:
            current_config = json.loads(app.config_preview) if isinstance(app.config_preview, str) else app.config_preview
        except Exception:
            pass

    # 基础版本
    base_config = None
    if request.base_version:
        base_config = await get_snapshot_config(db, app_id, request.base_version)
    else:
        # 找最近的 document 来源快照作为 base
        result = await db.execute(
            select(ConfigSnapshot)
            .where(
                ConfigSnapshot.application_id == app_id,
                ConfigSnapshot.source == "document",
            )
            .order_by(ConfigSnapshot.version.desc())
            .limit(1)
        )
        snapshot = result.scalar_one_or_none()
        if snapshot:
            try:
                base_config = json.loads(snapshot.config_json)
            except Exception:
                pass

    # 三方 diff
    result = three_way_diff(base_config, current_config, request.incoming_config)

    return result


# ==================== 辅助函数 ====================

async def _get_platform_client_for_app(
    app: Application,
    user: User,
    db: AsyncSession,
) -> APaaSClient:
    """优先按应用绑定/默认平台环境获取连接，回退到用户级连接。"""
    env = None

    if getattr(app, "platform_env_id", None):
        env_result = await db.execute(
            select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id)
        )
        env = env_result.scalar_one_or_none()

    if not env:
        env_result = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == app.tenant_id,
                PlatformEnv.is_default == True,
            )
        )
        env = env_result.scalar_one_or_none()

    if not env:
        env_result = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == app.tenant_id,
                PlatformEnv.status == "connected",
            ).limit(1)
        )
        env = env_result.scalar_one_or_none()

    if env and env.token:
        return APaaSClient(
            base_url=env.base_url,
            tenant_id=env.platform_tenant_id,
            token=env.token,
        )

    if user.apaas_token and user.apaas_base_url and user.apaas_tenant_id:
        return APaaSClient(
            base_url=user.apaas_base_url,
            tenant_id=user.apaas_tenant_id,
            token=user.apaas_token,
        )

    raise HTTPException(status_code=400, detail="未配置平台环境，请在环境管理中添加并连接")

def _build_execute_stream_response(
    app_id: int,
    app_name: str,
    apaas_app_id: str,
    old_config_str: Optional[str],
    apaas_base_url: str,
    apaas_tenant_id: str,
    apaas_token: str,
    request: ExecuteRequest,
) -> EventSourceResponse:
    async def event_generator():
        async with AsyncSessionLocal() as session:
            try:
                async with acquire_app_lock(app_id, "增量更新流式执行"):
                    old_config = None
                    if old_config_str:
                        try:
                            old_config = json.loads(old_config_str) if isinstance(old_config_str, str) else old_config_str
                        except Exception:
                            pass

                    yield {
                        "event": "progress",
                        "data": json.dumps({"stage": "init", "status": "running", "step": "初始化..."}, ensure_ascii=False),
                    }

                    client = APaaSClient(
                        base_url=apaas_base_url,
                        tenant_id=apaas_tenant_id,
                        token=apaas_token,
                    )

                    yield {
                        "event": "progress",
                        "data": json.dumps({"stage": "init", "status": "running", "step": "获取平台数据..."}, ensure_ascii=False),
                    }
                    remote_data = await fetch_remote_data(client, apaas_app_id)

                    yield {
                        "event": "progress",
                        "data": json.dumps({"stage": "init", "status": "running", "step": "计算配置差异..."}, ensure_ascii=False),
                    }
                    diff = compute_config_diff(old_config, request.new_config, remote_data)

                    if not diff.has_changes:
                        yield {
                            "event": "done",
                            "data": json.dumps({
                                "type": "complete",
                                "message": "无变更需要执行",
                                "result": {"success": True, "results": {}, "errors": [], "warnings": []},
                            }, ensure_ascii=False),
                        }
                        return

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

                    if request.selected_changes is not None:
                        selected_set = {
                            (s.get("type") if isinstance(s, dict) else s.type,
                             s.get("code") if isinstance(s, dict) else s.code)
                            for s in request.selected_changes
                        }
                        diff.role_changes = [c for c in diff.role_changes if ("role", c.code) in selected_set]
                        diff.dict_changes = [c for c in diff.dict_changes if ("dict", c.code) in selected_set]
                        diff.model_changes = [c for c in diff.model_changes if ("model", c.code) in selected_set]
                        diff.form_changes = [c for c in diff.form_changes if ("form", c.code) in selected_set]
                        diff.process_changes = [c for c in diff.process_changes if ("process", c.code) in selected_set]

                    yield {
                        "event": "progress",
                        "data": json.dumps({"stage": "init", "status": "done", "step": f"发现 {diff.summary}"}, ensure_ascii=False),
                    }

                    executor = IncrementalExecutor(
                        client=client,
                        app_id=apaas_app_id,
                        app_name=app_name,
                    )
                    save_config = diff.normalized_new_config or request.new_config

                    async for event in executor.execute_diff_stream(diff):
                        if event.get("type") == "complete":
                            result = await session.execute(
                                select(Application).where(Application.id == app_id)
                            )
                            app_obj = result.scalar_one()
                            app_obj.config_preview = json.dumps(save_config, ensure_ascii=False)
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
