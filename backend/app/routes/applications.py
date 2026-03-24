from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select, desc, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from app.database import get_db
from app.models import User, Application, DocumentVersion, ChangePlan
from app.auth import get_current_user
from app.schemas import ApplicationCreate, ApplicationResponse, MergedAppResponse
from app.deps import get_auth_context, AuthContext
from app.permissions import has_org_permission, check_resource_permission, batch_get_permissions, Action
from jose import JWTError, jwt
from app.config import settings

router = APIRouter(prefix="/applications", tags=["应用"])
logger = logging.getLogger(__name__)


def _enrich(app: Application) -> ApplicationResponse:
    config = None
    models = forms = roles = dicts = 0
    if app.config_preview:
        try:
            config = json.loads(app.config_preview) if isinstance(app.config_preview, str) else app.config_preview
            data = config.get("data", config)
            models = len(data.get("models", []))
            forms = models
            roles = len(data.get("roles", []))
            dicts = len(data.get("dicts", []))
        except Exception:
            pass
    return ApplicationResponse(
        id=app.id, app_name=app.app_name, app_code=app.app_code,
        description=app.description, status=app.status,
        apaas_app_id=app.apaas_app_id, config_preview=config,
        models=models, forms=forms, roles=roles, dicts=dicts,
        created_at=app.created_at, updated_at=app.updated_at
    )


# ── 状态映射 ──

_REMOTE_STATUS_MAP = {
    "ENABLE": "已上线",
    "DISABLE": "已下线",
    "SHUTDOWN": "已下线",
}

_LOCAL_STATUS_MAP = {
    "draft": "草稿",
    "generating": "生成中",
    "completed": "已生成",
    "failed": "失败",
}


def _build_apaas_url(apaas_app_id: str) -> str:
    """得帆云平台应用直达链接"""
    return f"https://apaas-poc.definesys.cn/platform/{settings.apaas_tenant_id}/admin/app-store/{apaas_app_id}"


def _build_local(app: Application, perms: dict | None = None) -> MergedAppResponse:
    enriched = _enrich(app)
    return MergedAppResponse(
        id=str(app.id),
        app_name=enriched.app_name,
        app_code=enriched.app_code,
        description=enriched.description,
        source="local",
        status=_LOCAL_STATUS_MAP.get(app.status, app.status),
        local_status=app.status,
        apaas_app_id=app.apaas_app_id,
        conversation_id=app.conversation_id,
        models=enriched.models, forms=enriched.forms,
        roles=enriched.roles, dicts=enriched.dicts,
        config_preview=enriched.config_preview,
        permissions=perms,
        created_at=str(enriched.created_at) if enriched.created_at else None,
        updated_at=str(enriched.updated_at) if enriched.updated_at else None,
    )


def _build_linked(app: Application, remote: dict, perms: dict | None = None) -> MergedAppResponse:
    enriched = _enrich(app)
    remote_status = remote.get("status") or remote.get("appStatus") or ""
    apaas_id = str(remote.get("id", app.apaas_app_id or ""))
    return MergedAppResponse(
        id=str(app.id),
        app_name=enriched.app_name,
        app_code=enriched.app_code,
        description=enriched.description or remote.get("appDesc"),
        source="linked",
        status=_REMOTE_STATUS_MAP.get(remote_status, "已同步"),
        local_status=app.status,
        remote_status=remote_status,
        apaas_app_id=apaas_id,
        apaas_url=_build_apaas_url(apaas_id),
        conversation_id=app.conversation_id,
        models=enriched.models, forms=enriched.forms,
        roles=enriched.roles, dicts=enriched.dicts,
        config_preview=enriched.config_preview,
        permissions=perms,
        created_at=str(enriched.created_at) if enriched.created_at else None,
        updated_at=str(enriched.updated_at) if enriched.updated_at else None,
    )


def _build_remote(remote: dict) -> MergedAppResponse:
    remote_status = remote.get("status") or remote.get("appStatus") or ""
    apaas_id = str(remote.get("id", ""))
    return MergedAppResponse(
        id=f"remote_{apaas_id}",
        app_name=remote.get("appName", "未命名应用"),
        app_code=remote.get("appCode"),
        description=remote.get("remarks") or remote.get("appDesc"),
        source="remote",
        status=_REMOTE_STATUS_MAP.get(remote_status, "平台应用"),
        remote_status=remote_status,
        apaas_app_id=apaas_id,
        apaas_url=_build_apaas_url(apaas_id),
        created_at=remote.get("creationDate"),
        updated_at=remote.get("lastUpdateDate"),
    )


@router.get("", response_model=List[MergedAppResponse])
async def list_applications(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    team_scope: Optional[str] = Query(None),
    include_remote: bool = Query(True),
    source_filter: Optional[str] = Query(None),  # local / remote / linked
):
    """获取应用列表（本地 + 得帆云平台合并）"""
    # 1. 查本地应用
    query = select(Application).where(Application.tenant_id == ctx.tenant_id)
    if team_scope == "personal":
        query = query.where(Application.created_by == ctx.user.id, Application.team_id.is_(None))
    elif team_scope and team_scope.isdigit():
        query = query.where(Application.team_id == int(team_scope))
    query = query.order_by(desc(Application.updated_at))
    result = await db.execute(query)
    local_apps = result.scalars().all()

    permissions_list = await batch_get_permissions(ctx, db, local_apps, "application")

    # 2. 拉取远程应用（降级处理）
    remote_apps: list = []
    if include_remote and ctx.user.apaas_token and source_filter != "local":
        try:
            from app.apaas_client import APaaSClient
            client = APaaSClient(base_url=ctx.user.apaas_base_url, tenant_id=ctx.user.apaas_tenant_id, token=ctx.user.apaas_token)
            remote_apps = await client.query_app_list()
        except Exception as e:
            logger.warning(f"拉取得帆云应用列表失败（降级）: {e}")

    # 3. 合并
    remote_map = {}
    for r in remote_apps:
        rid = str(r.get("id", ""))
        if rid:
            remote_map[rid] = r

    merged: list[MergedAppResponse] = []
    matched_remote_ids: set[str] = set()

    for app, perms in zip(local_apps, permissions_list):
        if app.apaas_app_id and app.apaas_app_id in remote_map:
            matched_remote_ids.add(app.apaas_app_id)
            if source_filter and source_filter != "linked":
                continue
            merged.append(_build_linked(app, remote_map[app.apaas_app_id], perms))
        else:
            if source_filter and source_filter != "local":
                continue
            merged.append(_build_local(app, perms))

    # 未匹配的远程应用
    if source_filter != "local":
        for rid, remote in remote_map.items():
            if rid not in matched_remote_ids:
                if source_filter and source_filter != "remote":
                    continue
                merged.append(_build_remote(remote))

    return merged


@router.get("/{app_id}", response_model=ApplicationResponse)
async def get_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    # 检查查看权限
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    resp = _enrich(app)
    resp.permissions = (await batch_get_permissions(ctx, db, [app], "application"))[0]
    return resp


@router.post("", response_model=ApplicationResponse)
async def create_application(
    data: ApplicationCreate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    granted_permissions = sorted(
        code for code, allowed in (ctx.org_permissions or {}).items() if allowed
    )
    logger.info(
        "create_application request user_id=%s tenant_id=%s tenant_role=%s conversation_id=%s app_code=%s granted_permissions=%s",
        ctx.user.id,
        ctx.tenant_id,
        ctx.tenant_role,
        data.conversation_id,
        data.app_code,
        granted_permissions,
    )

    # 检查创建权限
    if not has_org_permission(ctx.org_permissions, "application", Action.CREATE):
        logger.warning(
            "create_application forbidden user_id=%s tenant_id=%s tenant_role=%s missing_permission=%s granted_permissions=%s",
            ctx.user.id,
            ctx.tenant_id,
            ctx.tenant_role,
            "application:create",
            granted_permissions,
        )
        raise HTTPException(status_code=403, detail="你的角色没有创建应用的权限")

    config_str = json.dumps(data.config_preview, ensure_ascii=False) if data.config_preview else None
    app = Application(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        team_id=None,  # 默认个人应用，后续可以转移到团队
        conversation_id=data.conversation_id,
        app_name=data.app_name,
        app_code=data.app_code,
        description=data.description,
        config_preview=config_str,
        status="draft"
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    logger.info(
        "create_application success app_id=%s user_id=%s tenant_id=%s app_code=%s",
        app.id,
        ctx.user.id,
        ctx.tenant_id,
        app.app_code,
    )

    # 把对话中已创建的 DocumentVersion 关联到新 Application
    if data.conversation_id:
        try:
            from sqlalchemy import update as sa_update
            result = await db.execute(
                select(DocumentVersion).where(
                    DocumentVersion.conversation_id == data.conversation_id,
                    DocumentVersion.application_id.is_(None)
                )
            )
            conv_versions = result.scalars().all()
            if conv_versions:
                for v in conv_versions:
                    v.application_id = app.id
                max_ver = max(v.version for v in conv_versions)
                app.current_doc_version = max_ver
                await db.commit()
                await db.refresh(app)
                logger.info(f"Linked {len(conv_versions)} DocumentVersion(s) to app {app.id}")
            else:
                # 兼容旧流程：如果对话中没有 DocumentVersion，尝试从 doc_raw 消息创建
                import hashlib
                from app.models import Message
                msg_result = await db.execute(
                    select(Message).where(
                        Message.conversation_id == data.conversation_id,
                        Message.role == "system",
                        Message.content.like('%doc_raw%')
                    ).order_by(Message.id.desc()).limit(1)
                )
                doc_msg = msg_result.scalar_one_or_none()
                doc_content = ""
                doc_filename = f"{data.app_name or 'design-doc'}.md"
                if doc_msg and doc_msg.content:
                    try:
                        raw = doc_msg.content
                        if '```doc_raw' in raw:
                            json_str = raw.split('```doc_raw\n', 1)[1].rsplit('\n```', 1)[0]
                        else:
                            json_str = raw
                        doc_data = json.loads(json_str)
                        doc_content = doc_data.get("raw_content", "")
                        doc_filename = doc_data.get("filename", doc_filename)
                    except (json.JSONDecodeError, IndexError, ValueError):
                        pass
                if doc_content:
                    models_count = len(data.config_preview.get('models', [])) if isinstance(data.config_preview, dict) else 0
                    dicts_count = len(data.config_preview.get('dicts', [])) if isinstance(data.config_preview, dict) else 0
                    roles_count = len(data.config_preview.get('roles', [])) if isinstance(data.config_preview, dict) else 0
                    doc_ver = DocumentVersion(
                        application_id=app.id,
                        conversation_id=data.conversation_id,
                        version=1,
                        filename=doc_filename,
                        content_hash=hashlib.sha256(doc_content.encode()).hexdigest(),
                        raw_content=doc_content,
                        parsed_config=config_str,
                        summary=f"{models_count} 模型, {dicts_count} 字典, {roles_count} 角色",
                    )
                    db.add(doc_ver)
                    app.current_doc_version = 1
                    await db.commit()
                    await db.refresh(app)
                    logger.info(f"Fallback: created DocumentVersion V1 for app {app.id}")
        except Exception as e:
            logger.warning(f"Failed to link/create DocumentVersion: {e}")

    resp = _enrich(app)
    resp.permissions = {Action.EDIT: True, Action.DELETE: True, Action.CLONE: True}  # 创建者全部权限
    return resp


class AutoCreateRequest(BaseModel):
    """前端首次生成配置时自动创建应用"""
    app_name: str
    config_preview: dict
    conversation_id: Optional[int] = None


class AutoCreateResponse(BaseModel):
    app_id: int
    app_name: str
    app_code: str
    is_new: bool  # True=新建, False=已存在


@router.post("/auto-create", response_model=AutoCreateResponse)
async def auto_create_application(
    data: AutoCreateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """首次生成配置时自动创建 Application。

    如果 conversation_id 已有关联应用，返回已有应用（不重复创建）。
    否则创建新的 draft 应用。
    """
    # 如果有 conversation_id，检查是否已有关联应用
    if data.conversation_id:
        result = await db.execute(
            select(Application).where(
                Application.conversation_id == data.conversation_id,
                Application.tenant_id == ctx.tenant_id,
            ).order_by(Application.id.desc()).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing:
            # 更新配置
            existing.config_preview = json.dumps(data.config_preview, ensure_ascii=False)
            existing.app_name = data.app_name
            await db.commit()
            return AutoCreateResponse(
                app_id=existing.id,
                app_name=existing.app_name,
                app_code=existing.app_code,
                is_new=False,
            )

    # 生成 app_code
    import hashlib
    code_base = data.app_name.lower().replace(" ", "-").replace("_", "-")
    ascii_code = ''.join(c for c in code_base if c.isascii() and (c.isalnum() or c == '-'))
    ascii_code = ascii_code.strip('-')
    if len(ascii_code) < 2:
        ascii_code = "app-" + hashlib.md5(data.app_name.encode()).hexdigest()[:6]

    config_str = json.dumps(data.config_preview, ensure_ascii=False)
    app = Application(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        conversation_id=data.conversation_id,
        app_name=data.app_name,
        app_code=ascii_code,
        config_preview=config_str,
        status="draft",
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    # 关联已有的 DocumentVersion
    if data.conversation_id:
        try:
            result = await db.execute(
                select(DocumentVersion).where(
                    DocumentVersion.conversation_id == data.conversation_id,
                    DocumentVersion.application_id.is_(None),
                )
            )
            for v in result.scalars().all():
                v.application_id = app.id
            await db.commit()
        except Exception as e:
            logger.warning(f"auto-create: link DocumentVersions failed: {e}")

    logger.info(f"auto-create: app_id={app.id}, app_name={app.app_name}")
    return AutoCreateResponse(
        app_id=app.id,
        app_name=app.app_name,
        app_code=app.app_code,
        is_new=True,
    )


@router.put("/{app_id}", response_model=ApplicationResponse)
async def update_application(
    app_id: int,
    data: ApplicationCreate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """更新应用配置（继续完善后重新生成前调用）"""
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    app.app_name = data.app_name
    app.description = data.description
    if hasattr(data, 'app_code') and data.app_code:
        app.app_code = data.app_code
    if hasattr(data, 'platform_env_id') and data.platform_env_id:
        app.platform_env_id = data.platform_env_id
    if data.config_preview:
        app.config_preview = json.dumps(data.config_preview, ensure_ascii=False)
    # 重置状态为 draft，允许重新生成
    if app.status in ("failed", "completed"):
        app.status = "draft"
    await db.commit()
    await db.refresh(app)
    return _enrich(app)


@router.patch("/{app_id}/code")
async def update_app_code(
    app_id: int,
    body: dict,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """更新应用编码（部署失败后修改）"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    new_code = body.get("app_code")
    if not new_code:
        raise HTTPException(status_code=400, detail="app_code 不能为空")
    app.app_code = new_code
    await db.commit()
    return {"ok": True, "app_code": new_code}


class PlatformConfigUpdate(BaseModel):
    """更新应用的平台环境配置"""
    platform_url: Optional[str] = None
    platform_tenant_id: Optional[str] = None
    platform_username: Optional[str] = None
    platform_password_enc: Optional[str] = None


@router.patch("/{app_id}/platform-config")
async def update_platform_config(
    app_id: int,
    data: PlatformConfigUpdate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """更新应用的平台环境配置"""
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

    if data.platform_url is not None:
        app.platform_url = data.platform_url
    if data.platform_tenant_id is not None:
        app.platform_tenant_id = data.platform_tenant_id
    if data.platform_username is not None:
        app.platform_username = data.platform_username
    if data.platform_password_enc is not None:
        app.platform_password_enc = data.platform_password_enc

    await db.commit()
    return {"success": True, "message": "平台配置已更新"}


@router.delete("/{app_id}")
async def delete_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """删除本地应用记录"""
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await check_resource_permission(ctx, db, app, "application", Action.DELETE)

    await db.delete(app)
    await db.commit()
    return {"ok": True}


@router.get("/{app_id}/generate")
async def generate_application(
    app_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Optional[str] = Query(None),
):
    from app.apaas_client import APaaSClient
    from app.generator_v2 import run_complete_generation

    # SSE不能设置Authorization header，通过query param传token
    if not token:
        raise HTTPException(status_code=401, detail="缺少认证token")
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = int(payload.get("sub", 0))
        tenant_id = payload.get("tid")
        if tenant_id is None:
            raise HTTPException(status_code=403, detail="平台管理员无法生成应用")
        tenant_id = int(tenant_id)
    except (JWTError, Exception):
        raise HTTPException(status_code=401, detail="无效的认证凭证")

    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    current_user = result.scalar_one_or_none()
    if not current_user:
        raise HTTPException(status_code=401, detail="用户不存在")

    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == tenant_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    if not app.config_preview:
        raise HTTPException(status_code=400, detail="应用配置为空")
    if not current_user.apaas_token:
        raise HTTPException(status_code=400, detail="未连接得帆云平台，请先在设置中连接APaaS平台")

    config = json.loads(app.config_preview) if isinstance(app.config_preview, str) else app.config_preview
    client = APaaSClient(base_url=current_user.apaas_base_url, tenant_id=current_user.apaas_tenant_id, token=current_user.apaas_token)
    # 记住已有的 apaas_app_id（SSE generator 需要自己的 session）
    existing_apaas_app_id = app.apaas_app_id

    async def event_generator():
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            # 在新 session 中重新加载 app 对象
            result = await session.execute(
                select(Application).where(Application.id == app_id)
            )
            app_obj = result.scalar_one()

            try:
                if not existing_apaas_app_id:
                    apaas_result = await client.create_app(app_obj.app_name, app_obj.app_code, app_obj.description or "")
                    apaas_app_id = str(apaas_result) if isinstance(apaas_result, str) else str(apaas_result.get("id", apaas_result.get("appId", "")))
                    app_obj.apaas_app_id = apaas_app_id
                    app_obj.status = "generating"
                    await session.commit()
                    logger.info(f"应用 {app_id} 平台创建成功, apaas_app_id={apaas_app_id}")
                    yield {"event": "progress", "data": json.dumps({"stage": -1, "status": "running", "step": f"应用已创建: {app_obj.app_name}"}, ensure_ascii=False)}
                else:
                    apaas_app_id = existing_apaas_app_id
                    app_obj.status = "generating"
                    await session.commit()
                    yield {"event": "progress", "data": json.dumps({"stage": -1, "status": "running", "step": f"复用已有平台应用: {apaas_app_id}"}, ensure_ascii=False)}

                async for event in run_complete_generation(client, apaas_app_id, config):
                    yield {"event": "progress", "data": json.dumps(event, ensure_ascii=False)}
                    if event.get("type") == "complete":
                        app_obj.status = "completed"
                        await session.commit()
                    elif event.get("status") == "error":
                        app_obj.status = "failed"
                        await session.commit()

                yield {"event": "done", "data": json.dumps({"type": "done"})}
            except Exception as e:
                logger.error(f"应用 {app_id} 生成失败: {e}")
                app_obj.status = "failed"
                await session.commit()

                # 特殊处理401错误
                error_msg = str(e)
                if "401" in error_msg or "Token已过期" in error_msg or "Unauthorized" in error_msg:
                    error_msg = "APaaS平台Token已过期，请重新连接平台后再试"

                yield {"event": "error", "data": json.dumps({"type": "error", "message": error_msg}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.post("/upload-doc")
async def upload_design_doc(
    file: UploadFile = File(...),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
):
    """上传功能设计文档(.md)，用 AI 解析为 preview JSON"""
    if not file.filename or not file.filename.endswith('.md'):
        raise HTTPException(status_code=400, detail="仅支持 .md 格式文件")

    content = await file.read()
    text = content.decode('utf-8')

    from app.ai_doc_parser import parse_doc_with_ai
    try:
        data = await parse_doc_with_ai(text, filename=file.filename or "")
    except Exception as e:
        logger.error(f"AI 文档解析失败: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"文档解析失败: {e}")

    # 如果解析出的 appName 是默认值，用文件名推断
    if data.get("appName") in ("业务应用", "应用", None, "") and file.filename:
        name = file.filename.replace('.md', '').replace('-', ' ').replace('_', ' ')
        for suffix in ('功能设计', '设计文档', '需求文档', '设计'):
            name = name.replace(suffix, '')
        data["appName"] = name.strip() or data["appName"]

    # 生成AI理解摘要
    models_count = len(data.get("models", []))
    roles_count = len(data.get("roles", []))
    dicts_count = len(data.get("dicts", []))
    workflows_count = len(data.get("workflows", []))

    # 列出所有字典
    dicts_list = []
    for d in data.get("dicts", []):
        dict_name = d.get("name", "")
        dict_code = d.get("code", "")
        options_count = len(d.get("options", []))
        if options_count > 0:
            dicts_list.append(f"  - {dict_name}（{dict_code}）：{options_count}个选项")
        else:
            dicts_list.append(f"  - {dict_name}（{dict_code}）：⚠️ 空字典，需要补充选项")

    summary = f"我已经理解了你的设计文档《{file.filename}》，识别出：\n\n"
    summary += f"- **{models_count} 个业务表单**\n"
    summary += f"- **{roles_count} 个角色**\n"
    summary += f"- **{dicts_count} 个数据字典**\n"
    if dicts_list:
        summary += "\n数据字典详情：\n" + "\n".join(dicts_list) + "\n"
    if workflows_count > 0:
        summary += f"- **{workflows_count} 个流程**\n"
    summary += f"\n全部设计里面是不是有缺少了？好像不太完整少了一些数据字典？你可以告诉我需要调整的地方，或者直接点击\"开始生成\"。"

    return {
        "type": "preview",
        "data": data,
        "summary": summary,
        "document_content": text
    }


@router.post("/upload-doc-with-conversation")
async def upload_doc_with_conversation(
    file: UploadFile = File(...),
    conversation_id: Optional[int] = Form(None),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
):
    """上传功能设计文档并创建对话会话（SSE 流式返回解析进度）

    支持两种模式：
    - V1（首次上传）：不传 conversation_id，完整解析，创建新对话
    - V2+（增量上传）：传 conversation_id，对比文档文本，只解析变化部分

    事件格式：
    - event: progress / data: {"message": "..."} — 解析进度
    - event: done / data: {"conversation_id":N, "summary":"...", "preview":{...}} — 完成
    - event: error / data: {"message": "..."} — 失败
    """
    if not file.filename or not file.filename.endswith('.md'):
        raise HTTPException(status_code=400, detail="仅支持 .md 格式文件")

    content = await file.read()
    text = content.decode('utf-8')
    fname = file.filename or ""

    # 把 db session 相关的值先存好
    user_id = current_user.id
    tenant_id = ctx.tenant_id
    existing_conversation_id = conversation_id

    # 如果传了 conversation_id，预先查找 V1 文档版本
    v1_doc_info: Optional[dict] = None
    if existing_conversation_id:
        v1_result = await db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.conversation_id == existing_conversation_id)
            .order_by(desc(DocumentVersion.version))
            .limit(1)
        )
        v1_doc_obj = v1_result.scalar_one_or_none()
        if v1_doc_obj:
            v1_doc_info = {
                "raw_content": v1_doc_obj.raw_content,
                "parsed_config": v1_doc_obj.parsed_config,
                "version": v1_doc_obj.version,
            }

    async def event_generator():
        from app.config_assembler import assemble_config_streaming
        from app.database import AsyncSessionLocal
        from app.doc_text_differ import diff_sections, build_changed_text, get_diff_stats
        from app.ai_doc_parser import parse_doc_with_ai, extract_existing_codes
        from app.config_diff import compute_config_diff

        data = None
        is_incremental = False
        v1_parsed_config = None
        diff_result = None

        try:
            # ── 判断是否走增量模式 ──
            if v1_doc_info and v1_doc_info.get("raw_content"):
                is_incremental = True

                # Step 1: 文本级章节对比
                yield {"event": "progress", "data": json.dumps({"message": "正在对比文档..."}, ensure_ascii=False)}
                diff_result = diff_sections(v1_doc_info["raw_content"], text)
                diff_stats = get_diff_stats(diff_result)

                total_changes = diff_stats["added"] + diff_stats["modified"] + diff_stats["removed"]
                yield {"event": "progress", "data": json.dumps({
                    "message": f"发现 {total_changes} 个章节变化（新增 {diff_stats['added']} 个，修改 {diff_stats['modified']} 个，删除 {diff_stats['removed']} 个）",
                    "diff_stats": diff_stats,
                }, ensure_ascii=False)}

                # 加载 V1 parsed_config
                if v1_doc_info.get("parsed_config"):
                    try:
                        v1_parsed_config = json.loads(v1_doc_info["parsed_config"]) if isinstance(v1_doc_info["parsed_config"], str) else v1_doc_info["parsed_config"]
                    except Exception:
                        v1_parsed_config = None

                changed_count = diff_stats["added"] + diff_stats["modified"]

                if changed_count == 0 and diff_stats["removed"] == 0:
                    # 文档完全无变化
                    yield {"event": "error", "data": json.dumps({"message": "文档内容无变化，无需重新上传"}, ensure_ascii=False)}
                    return

                if changed_count > 0 and v1_parsed_config:
                    # Step 2: 只解析变化部分
                    changed_text = build_changed_text(diff_result)
                    yield {"event": "progress", "data": json.dumps({
                        "message": f"正在解析变化部分（{changed_count} 个章节）...",
                    }, ensure_ascii=False)}

                    # 提取 V1 已有编码作为上下文
                    existing_codes = extract_existing_codes(v1_parsed_config)

                    # 只对变化部分调 AI 解析
                    partial_config = await parse_doc_with_ai(
                        changed_text, filename=fname, existing_codes=existing_codes
                    )

                    # Step 3: 合并配置
                    yield {"event": "progress", "data": json.dumps({"message": "合并配置..."}, ensure_ascii=False)}
                    data = _merge_configs(v1_parsed_config, partial_config, diff_result)

                elif v1_parsed_config:
                    # 只有删除，无新增/修改
                    yield {"event": "progress", "data": json.dumps({
                        "message": "无新增或修改章节，复用已有解析结果",
                    }, ensure_ascii=False)}
                    data = _remove_deleted_from_config(v1_parsed_config, diff_result)
                else:
                    # V1 没有 parsed_config，回退全量解析
                    is_incremental = False

            # ── V1 首次上传：全量解析 ──
            if not is_incremental:
                async for event in assemble_config_streaming(
                    user_prompt=f"请根据以下设计文档生成完整的应用配置。文档名：{fname}",
                    context=text,
                ):
                    phase = event.get("phase", "")
                    message = event.get("message", "")

                    progress_data: dict = {"message": f"[{phase}] {message}"}
                    if event.get("batch"):
                        progress_data["batch"] = event["batch"]
                    if event.get("data"):
                        progress_data["data"] = event["data"]
                    yield {"event": "progress", "data": json.dumps(progress_data, ensure_ascii=False)}

                    if phase == "complete" and event.get("data"):
                        data = event["data"]

        except Exception as e:
            err_msg = str(e) or repr(e) or type(e).__name__
            logger.error(f"AI 文档解析失败: {err_msg}", exc_info=True)
            yield {"event": "error", "data": json.dumps({"message": f"文档解析失败: {err_msg}"}, ensure_ascii=False)}
            return

        if not data:
            yield {"event": "error", "data": json.dumps({"message": "配置生成失败：无数据"}, ensure_ascii=False)}
            return

        # 推断应用名
        if data.get("appName") in ("业务应用", "应用", None, "") and fname:
            name = fname.replace('.md', '').replace('-', ' ').replace('_', ' ')
            for suffix in ('功能设计', '设计文档', '需求文档', '设计'):
                name = name.replace(suffix, '')
            data["appName"] = name.strip() or "业务应用"

        # 创建对话 + 消息（用独立 session）
        async with AsyncSessionLocal() as session:
            from app.models import Conversation, Message

            # 增量模式复用已有对话，首次上传创建新对话
            if existing_conversation_id:
                conv_id = existing_conversation_id
            else:
                conversation = Conversation(
                    user_id=user_id, tenant_id=tenant_id,
                    title=f"文档：{fname}", agent_type="builder", status="active"
                )
                session.add(conversation)
                await session.flush()
                conv_id = conversation.id

            # 系统上下文
            models_summary = []
            for m in data.get("models", []):
                field_names = [f.get("name", "") for f in m.get("fields", [])]
                models_summary.append(f"- {m.get('name')}：{', '.join(field_names)}")
            dicts_summary = [f"- {d.get('name')}（{d.get('code')}）：{', '.join(o.get('name','') for o in d.get('options',[]))}" for d in data.get("dicts", [])]
            roles_summary = [r.get('name', '') for r in data.get("roles", [])]

            context_content = f"用户上传了设计文档《{fname}》，已解析为以下配置摘要：\n\n"
            context_content += f"应用名：{data.get('appName', '业务应用')}\n"
            context_content += f"角色：{', '.join(roles_summary)}\n\n"
            context_content += f"数据字典：\n" + "\n".join(dicts_summary) + "\n\n"
            context_content += f"业务表单：\n" + "\n".join(models_summary) + "\n\n"
            context_content += "用户可能会要求修改配置。当用户确认后，生成完整的配置JSON。"

            session.add(Message(conversation_id=conv_id, role="system", content=context_content))

            # 保存原始文档内容（供后续创建 DocumentVersion 使用）
            doc_raw_msg = json.dumps({"type": "doc_raw", "filename": fname, "content": text}, ensure_ascii=False)
            session.add(Message(conversation_id=conv_id, role="system", content=doc_raw_msg))

            # 生成摘要
            models_count = len(data.get("models", []))
            roles_count = len(data.get("roles", []))
            dicts_count = len(data.get("dicts", []))

            dicts_list = []
            for d in data.get("dicts", []):
                opts_count = len(d.get("options", []))
                tag = f"{opts_count}个选项" if opts_count > 0 else "⚠️ 空字典"
                dicts_list.append(f"  - {d.get('name', '')}（{d.get('code', '')}）：{tag}")

            if is_incremental and v1_parsed_config:
                # 增量模式：用 config_diff 展示差异
                v1_for_diff = v1_parsed_config
                resource_diff = compute_config_diff(v1_for_diff, data)
                diff_summary_text = resource_diff.summary or "文档更新解析完成"

                summary = f"文档《{fname}》已更新（V{v1_doc_info['version'] + 1}），增量解析完成：\n\n"
                summary += diff_summary_text + "\n\n"
                summary += f"当前配置：**{models_count} 个表单**、**{roles_count} 个角色**、**{dicts_count} 个字典**\n"
                summary += "\n你可以告诉我需要调整的地方，或者直接说\"开始生成\"。"
            else:
                summary = f"我已经理解了设计文档《{fname}》，识别出：\n\n"
                summary += f"- **{models_count} 个业务表单**\n"
                summary += f"- **{roles_count} 个角色**\n"
                summary += f"- **{dicts_count} 个数据字典**\n"
                if dicts_list:
                    summary += "\n数据字典详情：\n" + "\n".join(dicts_list) + "\n"
                summary += "\n你可以告诉我需要调整的地方，或者直接说\"开始生成\"。"

            session.add(Message(conversation_id=conv_id, role="assistant", content=summary))

            # 保存完整配置 JSON 作为 system 消息（刷新页面时可恢复）
            config_msg = '```json\n' + json.dumps({"type": "preview", "data": data}, ensure_ascii=False) + '\n```'
            session.add(Message(conversation_id=conv_id, role="system", content=config_msg))

            # 保存原始文档内容（用于后续创建 DocumentVersion）
            doc_msg = '```doc_raw\n' + json.dumps({"filename": fname, "raw_content": text}, ensure_ascii=False) + '\n```'
            session.add(Message(conversation_id=conv_id, role="system", content=doc_msg))

            # 自动保存 DocumentVersion（conversation_id 关联，application_id 待后续绑定）
            import hashlib
            # 检查同一 conversation 下已有版本号
            existing_ver_result = await session.execute(
                select(sa_func.max(DocumentVersion.version))
                .where(DocumentVersion.conversation_id == conv_id)
            )
            max_ver = existing_ver_result.scalar() or 0
            new_version = max_ver + 1

            config_json_str = json.dumps(data, ensure_ascii=False)
            doc_ver = DocumentVersion(
                application_id=None,
                conversation_id=conv_id,
                version=new_version,
                filename=fname,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                raw_content=text,
                parsed_config=config_json_str,
                parent_version=max_ver if max_ver > 0 else None,
                summary=f"{models_count} 模型, {dicts_count} 字典, {roles_count} 角色",
            )
            session.add(doc_ver)

            await session.commit()

            done_data = {
                "conversation_id": conv_id,
                "summary": summary,
                "preview": data,
                "version": new_version,
                "is_incremental": is_incremental,
            }
            # 增量模式下额外返回 diff 信息
            if is_incremental and v1_parsed_config:
                resource_diff_dict = resource_diff.to_dict()
                done_data["diff"] = resource_diff_dict

            yield {
                "event": "done",
                "data": json.dumps(done_data, ensure_ascii=False)
            }

    from sse_starlette.sse import EventSourceResponse
    return EventSourceResponse(event_generator())


# ── 文档驱动增量开发 ──────────────────────────────────


class SelectionsUpdate(BaseModel):
    """更新 change plan 中 actions 的选择状态"""
    selections: dict  # {action_id: bool}


def _merge_configs(v1_config: dict, partial_v2_config: dict, text_diff: dict) -> dict:
    """合并 V1 未变更部分 + V2 变更部分（AI 只解析了变更章节）。

    策略：以 V1 config 为基础，用 partial_v2_config（变更章节的解析结果）覆盖/补充。
    - partial_v2_config 中的 models/dicts/roles：如果 code 匹配 V1 则替换，否则新增
    - V1 中不在 partial_v2_config 中出现的（未变更章节的数据）：保留
    - removed 章节对应的数据：不包含在 partial_v2_config 中，需要从 V1 移除
    """
    from copy import deepcopy

    merged = deepcopy(v1_config)

    # 收集变更解析出的 codes
    v2_model_codes = {m.get("code", ""): m for m in partial_v2_config.get("models", []) if m.get("code")}
    v2_dict_codes = {d.get("code", ""): d for d in partial_v2_config.get("dicts", []) if d.get("code")}
    v2_role_codes = {r.get("code", ""): r for r in partial_v2_config.get("roles", []) if r.get("code")}

    # 更新 models：替换已存在的，追加新增的
    existing_model_codes = {m.get("code", "") for m in merged.get("models", [])}
    new_models = []
    for m in merged.get("models", []):
        code = m.get("code", "")
        if code in v2_model_codes:
            new_models.append(v2_model_codes[code])  # 替换为新版本
        else:
            new_models.append(m)  # 保留未变更的
    # 追加全新的模型
    for code, m in v2_model_codes.items():
        if code not in existing_model_codes:
            new_models.append(m)
    merged["models"] = new_models

    # 更新 dicts
    existing_dict_codes = {d.get("code", "") for d in merged.get("dicts", [])}
    new_dicts = []
    for d in merged.get("dicts", []):
        code = d.get("code", "")
        if code in v2_dict_codes:
            new_dicts.append(v2_dict_codes[code])
        else:
            new_dicts.append(d)
    for code, d in v2_dict_codes.items():
        if code not in existing_dict_codes:
            new_dicts.append(d)
    merged["dicts"] = new_dicts

    # 更新 roles
    existing_role_codes = {r.get("code", "") for r in merged.get("roles", [])}
    new_roles = []
    for r in merged.get("roles", []):
        code = r.get("code", "")
        if code in v2_role_codes:
            new_roles.append(v2_role_codes[code])
        else:
            new_roles.append(r)
    for code, r in v2_role_codes.items():
        if code not in existing_role_codes:
            new_roles.append(r)
    merged["roles"] = new_roles

    # 更新 appName（如果变更解析结果中有）
    if partial_v2_config.get("appName"):
        merged["appName"] = partial_v2_config["appName"]

    return merged


def _remove_deleted_from_config(v1_config: dict, text_diff: dict) -> dict:
    """当只有删除章节（无新增/修改）时，从 V1 config 中移除被删除章节对应的内容。

    注意：由于章节标题和 config 中的 model/dict 名称不一定完全对应，
    这里采取保守策略 — 只返回 V1 config 的副本。
    真正的删除判断由后续的 semantic_diff 来处理。
    """
    from copy import deepcopy
    return deepcopy(v1_config)


@router.post("/{app_id}/upload-doc-version")
async def upload_doc_version(
    app_id: int,
    file: UploadFile = File(...),
    conversation_id: int = Form(...),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """上传新版本设计文档，AI 解析后与当前配置做语义对比（SSE 流式返回进度）"""
    if not file.filename or not file.filename.endswith('.md'):
        raise HTTPException(status_code=400, detail="仅支持 .md 格式文件")

    # 加载应用
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    content_bytes = await file.read()
    text = content_bytes.decode('utf-8')
    fname = file.filename or ""

    # 提前获取需要的值（SSE generator 不能用原始 db session）
    app_id_val = app.id
    tenant_id_val = ctx.tenant_id
    current_config_str = app.config_preview

    async def event_generator():
        from app.database import AsyncSessionLocal
        from app.doc_differ import build_structure_index, semantic_diff, diff_to_actions, compute_hash
        from app.config_diff import compute_config_diff
        from app.doc_text_differ import diff_sections, build_changed_text, get_diff_stats

        try:
            yield {"event": "progress", "data": json.dumps({"step": "读取文档内容..."}, ensure_ascii=False)}

            # 1. 计算 hash
            content_hash = compute_hash(text)

            # 2. 检查是否重复 & 获取 V1 文档版本
            v1_doc: Optional[dict] = None
            async with AsyncSessionLocal() as session:
                dup_result = await session.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.application_id == app_id_val,
                        DocumentVersion.content_hash == content_hash,
                    )
                )
                if dup_result.scalar_one_or_none():
                    yield {"event": "error", "data": json.dumps({"message": "文档内容未变化，无需上传"}, ensure_ascii=False)}
                    return

                # 3. 获取当前最大 version 及其 DocumentVersion 记录
                max_ver_result = await session.execute(
                    select(sa_func.max(DocumentVersion.version)).where(
                        DocumentVersion.application_id == app_id_val
                    )
                )
                max_ver = max_ver_result.scalar() or 0
                new_version = max_ver + 1

                # 获取 V1 文档记录（用于文本对比）
                if max_ver > 0:
                    v1_result = await session.execute(
                        select(DocumentVersion).where(
                            DocumentVersion.application_id == app_id_val,
                            DocumentVersion.version == max_ver,
                        )
                    )
                    v1_doc_obj = v1_result.scalar_one_or_none()
                    if v1_doc_obj:
                        # 提取需要的字段，避免 session 外访问
                        v1_doc = {
                            "raw_content": v1_doc_obj.raw_content,
                            "parsed_config": v1_doc_obj.parsed_config,
                            "version": v1_doc_obj.version,
                        }

            yield {"event": "progress", "data": json.dumps({"step": "解析文档结构..."}, ensure_ascii=False)}

            # 4. 构建章节索引
            structure_index = build_structure_index(text)

            # ── 分支：有 V1 文档时走「文档对比优先」，否则走全量解析 ──
            from app.ai_doc_parser import parse_doc_with_ai, extract_existing_codes

            if v1_doc and v1_doc.get("raw_content"):
                # ===== 增量模式：文档对比优先 =====
                yield {"event": "progress", "data": json.dumps({"step": "text_diff", "message": "正在对比文档章节..."}, ensure_ascii=False)}

                # Step A: 纯文本章节对比
                text_diff = diff_sections(v1_doc["raw_content"], text)
                diff_stats = get_diff_stats(text_diff)

                yield {"event": "progress", "data": json.dumps({
                    "step": "text_diff",
                    "data": diff_stats,
                    "message": f"章节对比完成：新增 {diff_stats['added']}、修改 {diff_stats['modified']}、删除 {diff_stats['removed']}、未变更 {diff_stats['unchanged']}",
                }, ensure_ascii=False)}

                # Step B: 加载 V1 的 parsed_config
                v1_parsed_config: dict = {}
                if v1_doc.get("parsed_config"):
                    try:
                        v1_parsed_config = json.loads(v1_doc["parsed_config"]) if isinstance(v1_doc["parsed_config"], str) else v1_doc["parsed_config"]
                    except Exception:
                        pass

                changed_count = diff_stats["added"] + diff_stats["modified"]

                if changed_count > 0:
                    # Step C: 只对变更章节调 AI 解析（传入 V1 已有编码让 AI 复用）
                    changed_text = build_changed_text(text_diff)
                    yield {"event": "progress", "data": json.dumps({
                        "step": "parse_changes",
                        "message": f"正在解析 {changed_count} 个变更章节...",
                    }, ensure_ascii=False)}

                    existing_codes = extract_existing_codes(v1_parsed_config) if v1_parsed_config else None
                    partial_config = await parse_doc_with_ai(changed_text, filename=fname, existing_codes=existing_codes)

                    # Step D: 合并 — V1 未变更部分 + V2 变更部分
                    yield {"event": "progress", "data": json.dumps({"step": "merge", "message": "合并未变更部分与变更结果..."}, ensure_ascii=False)}
                    v2_config = _merge_configs(v1_parsed_config, partial_config, text_diff)
                else:
                    # 所有章节未变更（只有删除），直接用 V1 config 减去删除的部分
                    yield {"event": "progress", "data": json.dumps({
                        "step": "parse_changes",
                        "message": "无新增或修改章节，复用已有解析结果",
                    }, ensure_ascii=False)}
                    v2_config = _remove_deleted_from_config(v1_parsed_config, text_diff)
            else:
                # ===== 首次上传：全量解析 =====
                yield {"event": "progress", "data": json.dumps({"step": "AI 解析文档配置..."}, ensure_ascii=False)}
                v2_config = await parse_doc_with_ai(text, filename=fname)

            yield {"event": "progress", "data": json.dumps({"step": "对比资源差异..."}, ensure_ascii=False)}

            # 6. 加载 V1 配置（从应用当前 config_preview）
            v1_config: dict = {}
            if current_config_str:
                try:
                    loaded = json.loads(current_config_str) if isinstance(current_config_str, str) else current_config_str
                    v1_config = loaded.get("data", loaded)
                except Exception:
                    pass

            # 7. 资源级差异对比（用于前端展示）
            resource_diff = compute_config_diff(v1_config, v2_config)
            resource_diff_dict = resource_diff.to_dict()

            # 8. 语义对比（用于生成可勾选 actions）
            diff = semantic_diff(v1_config, v2_config)

            # 9. 生成 patch actions
            actions = diff_to_actions(diff, v2_config)

            # 10. 生成摘要
            summary = resource_diff.summary or f"文档 V{new_version} 资源变更分析完成"

            yield {"event": "progress", "data": json.dumps({"step": "保存版本记录..."}, ensure_ascii=False)}

            # 11. 创建 DocumentVersion + ChangePlan
            async with AsyncSessionLocal() as session:
                doc_ver = DocumentVersion(
                    application_id=app_id_val,
                    version=new_version,
                    filename=fname,
                    content_hash=content_hash,
                    raw_content=text,
                    structure_index=json.dumps(structure_index, ensure_ascii=False),
                    parsed_config=json.dumps(v2_config, ensure_ascii=False),
                    parent_version=max_ver if max_ver > 0 else None,
                    summary=summary,
                )
                session.add(doc_ver)
                await session.flush()

                change_plan = ChangePlan(
                    application_id=app_id_val,
                    conversation_id=conversation_id,
                    from_version=max_ver,
                    to_version=new_version,
                    diff_summary=json.dumps(resource_diff_dict, ensure_ascii=False),
                    actions=json.dumps(actions, ensure_ascii=False),
                    status="pending",
                )
                session.add(change_plan)

                # 更新应用的当前文档版本
                app_result = await session.execute(
                    select(Application).where(Application.id == app_id_val)
                )
                app_obj = app_result.scalar_one()
                app_obj.current_doc_version = new_version

                await session.commit()
                await session.refresh(change_plan)

                yield {
                    "event": "done",
                    "data": json.dumps({
                        "version": new_version,
                        "summary": summary,
                        "diff": resource_diff_dict,
                        "semantic_diff": diff,
                        "actions": actions,
                        "change_plan_id": change_plan.id,
                        "is_first_version": max_ver == 0,
                        "parsed_config": v2_config,
                    }, ensure_ascii=False),
                }

        except Exception as e:
            logger.error(f"文档版本上传失败: {e}", exc_info=True)
            yield {"event": "error", "data": json.dumps({"message": f"处理失败: {str(e)}"}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


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
        "diff_summary": json.loads(plan.diff_summary) if isinstance(plan.diff_summary, str) else plan.diff_summary,
        "actions": json.loads(plan.actions) if isinstance(plan.actions, str) else plan.actions,
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

    actions = json.loads(plan.actions) if isinstance(plan.actions, str) else plan.actions
    for action in actions:
        aid = action.get("id")
        if aid and aid in body.selections:
            action["selected"] = body.selections[aid]

    plan.actions = json.dumps(actions, ensure_ascii=False)
    await db.commit()
    return {"ok": True, "actions": actions}


@router.post("/{app_id}/change-plans/{plan_id}/execute")
async def execute_change_plan(
    app_id: int,
    plan_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """执行变更计划，将选中的 actions 应用到 config_preview 并同步到得帆云平台（SSE 流式返回进度）"""
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

    # 保存用户 APaaS 凭证（在 event_generator 前）
    apaas_token = ctx.user.apaas_token
    apaas_base_url = ctx.user.apaas_base_url
    apaas_tenant_id = ctx.user.apaas_tenant_id
    apaas_app_id = app.apaas_app_id
    app_name = app.app_name

    app_id_val = app.id
    current_config_str = app.config_preview
    plan_id_val = plan.id
    actions_str = plan.actions

    async def event_generator():
        from app.database import AsyncSessionLocal
        from app.doc_differ import apply_actions_to_config
        from app.apaas_client import APaaSClient
        from app.config_diff import compute_config_diff
        from app.incremental_executor import IncrementalExecutor, fetch_remote_data

        try:
            yield {"event": "progress", "data": json.dumps({"step": "加载当前配置..."}, ensure_ascii=False)}

            # 加载当前配置
            current_config: dict = {}
            if current_config_str:
                try:
                    loaded = json.loads(current_config_str) if isinstance(current_config_str, str) else current_config_str
                    current_config = loaded.get("data", loaded)
                except Exception:
                    pass

            actions = json.loads(actions_str) if isinstance(actions_str, str) else actions_str
            selected = [a for a in actions if a.get("selected", True)]

            yield {"event": "progress", "data": json.dumps({"step": f"应用 {len(selected)} 项变更..."}, ensure_ascii=False)}

            # 应用 patch 得到 new_config
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

                    # 计算差异
                    yield {"event": "progress", "data": json.dumps({"step": "计算资源变更差异..."}, ensure_ascii=False)}
                    diff = compute_config_diff(current_config, new_config, remote_data)

                    if diff.has_changes:
                        # 创建执行器并执行
                        executor = IncrementalExecutor(client, apaas_app_id, app_name)

                        # 流式执行差异
                        async for progress in executor.execute_diff_stream(diff):
                            if progress.get("type") == "complete":
                                sync_result = progress.get("result", {})
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
                    logger.warning(f"平台同步失败（将继续保存本地配置）: {e}", exc_info=True)
                    sync_errors.append(str(e))
            else:
                if not apaas_token:
                    logger.info("用户未连接平台，跳过同步")
                elif not apaas_app_id:
                    logger.info("应用未创建到平台，跳过同步")

            yield {"event": "progress", "data": json.dumps({"step": "保存本地配置..."}, ensure_ascii=False)}

            # 保存本地配置
            async with AsyncSessionLocal() as session:
                app_result = await session.execute(
                    select(Application).where(Application.id == app_id_val)
                )
                app_obj = app_result.scalar_one()
                app_obj.config_preview = json.dumps(new_config, ensure_ascii=False)

                plan_result = await session.execute(
                    select(ChangePlan).where(ChangePlan.id == plan_id_val)
                )
                plan_obj = plan_result.scalar_one()
                plan_obj.status = "completed"
                plan_obj.executed_at = datetime.utcnow()

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


@router.get("/{app_id}/doc-versions")
async def list_doc_versions(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取应用的文档版本历史"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.application_id == app_id)
        .order_by(desc(DocumentVersion.version))
    )
    versions = result.scalars().all()

    # 同时加载关联的 change plans
    result = await db.execute(
        select(ChangePlan)
        .where(ChangePlan.application_id == app_id)
        .order_by(desc(ChangePlan.created_at))
    )
    plans = result.scalars().all()
    plans_by_to_version = {}
    for p in plans:
        plans_by_to_version.setdefault(p.to_version, []).append(p)

    items = []
    for v in versions:
        related_plans = plans_by_to_version.get(v.version, [])
        items.append({
            "id": v.id,
            "version": v.version,
            "filename": v.filename,
            "content_hash": v.content_hash,
            "raw_content": v.raw_content,
            "summary": v.summary,
            "structure_index": json.loads(v.structure_index) if v.structure_index else None,
            "created_at": str(v.created_at) if v.created_at else None,
            "change_plans": [
                {
                    "id": p.id,
                    "from_version": p.from_version,
                    "to_version": p.to_version,
                    "status": p.status,
                    "created_at": str(p.created_at) if p.created_at else None,
                }
                for p in related_plans
            ],
        })

    return {
        "current_version": app.current_doc_version,
        "versions": items,
    }


@router.get("/doc-versions-by-conversation/{conversation_id}")
async def list_doc_versions_by_conversation(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """通过 conversation_id 获取文档版本（在 Application 创建之前使用）"""
    from app.models import Conversation
    # 验证对话属于当前用户/租户
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == ctx.tenant_id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.conversation_id == conversation_id)
        .order_by(desc(DocumentVersion.version))
    )
    versions = result.scalars().all()

    items = []
    for v in versions:
        items.append({
            "id": v.id,
            "version": v.version,
            "filename": v.filename,
            "content_hash": v.content_hash,
            "raw_content": v.raw_content,
            "summary": v.summary,
            "structure_index": json.loads(v.structure_index) if v.structure_index else None,
            "created_at": str(v.created_at) if v.created_at else None,
        })

    return {
        "versions": items,
    }
