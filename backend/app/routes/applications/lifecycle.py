from __future__ import annotations
import logging
import time
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import Application, ApiCallLog, PlatformEnv, Project, ProjectMember
from app.deps import get_auth_context, AuthContext
from app.permissions import check_resource_permission, Action
from app.config import APP_DEPLOY_ABSTRACT
from app.apaas_client import APaaSClient
from app.crypto import decrypt_password
from app.json_utils import loads_if_str
from app.error_messages import (
    APAAS_LOGIN_FAILED,
    is_apaas_token_error,
)
from app.project_access import require_project_access

from ._helpers import (
    _dump_preview_config,
    _normalize_app_code,
    _coerce_app_code,
)
from .crud import (
    _extract_apaas_app_version,
    _bump_patch_version,
    _deploy_apaas_app_with_version_retry,
    _require_application_permission,
    _resolve_apaas_call_context,
    _extract_preview_data,
    _merge_preview_data,
)

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/{app_id}/publish")
async def publish_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """上线应用（发布到平台）。"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    if not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用尚未部署，不能上线")
    # 生成未完成不能上线 —— deploy 起的后台生成(模型/表单/权限)可能还在跑(apaas_app_id
    # 在生成早期就写入, 不能当"已就绪"的依据)。此时 publish 会发出半成品版本(表单缺失)。
    # 硬门要求 status=completed 再发, 同时挡住 agent 提前宣布"已上线"和 UI 提前发布。
    if app.status in ("generating", "in_progress"):
        raise HTTPException(
            status_code=409,
            detail="应用还在生成中（模型/表单/权限尚未全部就绪），请等生成完成（status=completed）后再上线。可轮询 get_application / 步骤状态查进度。",
        )

    permissions = await _require_application_permission(ctx, db, app, Action.EDIT)
    if not permissions.get("publish", False):
        raise HTTPException(status_code=403, detail="当前角色无权上线该应用")

    env = None
    if app.platform_env_id:
        env_result = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
        env = env_result.scalar_one_or_none()
    if not env:
        env_result = await db.execute(
            select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id, PlatformEnv.is_default == True)
        )
        env = env_result.scalar_one_or_none()
    if not env:
        env_result = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == ctx.tenant_id,
                PlatformEnv.status == "connected",
            ).limit(1)
        )
        env = env_result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=400, detail="未找到可用的平台环境")

    token = env.token
    if not token and env.username and env.password_enc:
        try:
            password = decrypt_password(env.password_enc)
            login_client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
            login_result = await login_client.login(env.username, password)
            token = login_result.get("token", "")
            if token:
                env.token = token
                env.status = "connected"
                await db.commit()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"平台登录失败: {e}")
    if not token:
        raise HTTPException(status_code=400, detail="平台 token 不可用，请先在环境管理中登录")

    # 写一条 in_progress 部署记录（用于历史 + 回滚）
    from .deploy_history import create_deploy_record_pre, complete_deploy_record
    record = await create_deploy_record_pre(
        db, app, ctx.user, deploy_type="publish", version_label=None
    )

    try:
        client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)
        app_detail = await client.query_app_detail(str(app.apaas_app_id))
        current_version = _extract_apaas_app_version(app_detail)
        next_version = _bump_patch_version(current_version) if current_version else "1.0.0"
        access_event = {"type": "app_access", "object_type": "ALL", "status": "skipped"}
        try:
            await client.save_app_access(str(app.apaas_app_id), object_type="ALL", object_ids=[])
            access_event["status"] = "success"
        except Exception as access_error:
            logger.warning("publish_application: app access save failed app_id=%s apaas_app_id=%s: %s", app_id, app.apaas_app_id, access_error)
            access_event = {"type": "app_access", "object_type": "ALL", "status": "failed", "error": str(access_error)}
        published_version, retry_events = await _deploy_apaas_app_with_version_retry(
            client, str(app.apaas_app_id), next_version, APP_DEPLOY_ABSTRACT
        )
        app.status = "completed"
        await db.commit()
        await complete_deploy_record(
            db, record, app, success=True, version_label=published_version,
            event_log=[
                access_event,
                *retry_events,
                {"type": "publish", "version": published_version, "status": "success"},
            ],
        )
        return {"ok": True, "version": published_version, "remote_status": "ENABLE", "deploy_record_id": record.id}
    except Exception as e:
        detail = str(e)
        if (is_apaas_token_error(detail) or "401" in detail) and env.username and env.password_enc:
            try:
                password = decrypt_password(env.password_enc)
                refresh_client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
                login_result = await refresh_client.login(env.username, password)
                token = login_result.get("token", "")
                if token:
                    env.token = token
                    env.status = "connected"
                    await db.commit()
                    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)
                    app_detail = await client.query_app_detail(str(app.apaas_app_id))
                    current_version = _extract_apaas_app_version(app_detail)
                    next_version = _bump_patch_version(current_version) if current_version else "1.0.0"
                    access_event = {"type": "app_access", "object_type": "ALL", "status": "skipped"}
                    try:
                        await client.save_app_access(str(app.apaas_app_id), object_type="ALL", object_ids=[])
                        access_event["status"] = "success"
                    except Exception as access_error:
                        logger.warning("publish_application retry: app access save failed app_id=%s apaas_app_id=%s: %s", app_id, app.apaas_app_id, access_error)
                        access_event = {"type": "app_access", "object_type": "ALL", "status": "failed", "error": str(access_error)}
                    published_version, retry_events = await _deploy_apaas_app_with_version_retry(
                        client, str(app.apaas_app_id), next_version, APP_DEPLOY_ABSTRACT
                    )
                    app.status = "completed"
                    await db.commit()
                    await complete_deploy_record(
                        db, record, app, success=True, version_label=published_version,
                        event_log=[
                            {"type": "publish", "status": "token_refresh"},
                            access_event,
                            *retry_events,
                            {"type": "publish", "version": published_version, "status": "success"},
                        ],
                    )
                    return {"ok": True, "version": published_version, "remote_status": "ENABLE", "deploy_record_id": record.id}
            except Exception as retry_error:
                await complete_deploy_record(
                    db, record, app, success=False,
                    error_message=f"{APAAS_LOGIN_FAILED}：{retry_error}",
                    event_log=[{"type": "publish", "status": "token_refresh_failed", "error": str(retry_error)}],
                )
                raise HTTPException(status_code=401, detail=f"{APAAS_LOGIN_FAILED}：{retry_error}")
        await complete_deploy_record(
            db, record, app, success=False,
            error_message=f"上线失败: {detail}",
            event_log=[{"type": "publish", "status": "failed", "error": detail}],
        )
        raise HTTPException(status_code=400, detail=f"上线失败: {detail}")


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

    await _require_application_permission(ctx, db, app, Action.EDIT)

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
    """删除本地应用记录及其关联数据"""
    try:
        result = await db.execute(
            select(Application).where(
                Application.id == app_id,
                Application.tenant_id == ctx.tenant_id
            )
        )
        app = result.scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=404, detail="应用不存在")

        await _require_application_permission(ctx, db, app, Action.DELETE)

        if app.status in {"completed", "generating"} or app.apaas_app_id:
            raise HTTPException(status_code=400, detail="已构建或已同步到平台的应用不允许删除")

        # 先清理依赖当前 application_id 的关联数据，避免外键约束导致主记录删除失败。
        await db.execute(
            delete(DocumentVersion).where(DocumentVersion.application_id == app.id)
        )
        await db.execute(
            delete(ChangePlan).where(ChangePlan.application_id == app.id)
        )
        await db.execute(
            delete(ConfigSnapshot).where(ConfigSnapshot.application_id == app.id)
        )
        await db.execute(
            delete(ApiCallLog).where(ApiCallLog.application_id == app.id)
        )
        await db.execute(
            delete(Application).where(
                Application.id == app.id,
                Application.tenant_id == ctx.tenant_id,
            )
        )

        await db.commit()
        return {"ok": True}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("delete application failed: app_id=%s tenant_id=%s", app_id, ctx.tenant_id)
        raise HTTPException(status_code=500, detail=f"删除失败: {exc}")


# ── 2026-05-26 design-v4 I3: 应用 env 切换 ──
#
# 应用栏 "开发 / 生产" toggle 需要知道当前 tenant 有哪些 env, 哪个是
# 当前 (= application.platform_env_id 对应) 的 env. 这个 endpoint 列出来,
# 让前端 toggle 切换时拿到目标 env 的 url + id, 调 platform-proxy/entry
# 时透传 env_id 真切 iframe.
#
# env type 推断 (env_name 启发式 — current schema 没 type 字段):
#   含 prod / production / 生产           → 'prod'
#   含 trial / preview / sandbox / 预览    → 'preview'
#   其他                                   → 'dev'
def _infer_env_type(env_name: str) -> str:
    name_lower = (env_name or "").lower()
    if any(k in name_lower for k in ("prod", "production")) or "生产" in (env_name or ""):
        return "prod"
    if any(k in name_lower for k in ("trial", "preview", "sandbox")) or "预览" in (env_name or ""):
        return "preview"
    return "dev"


@router.get("/{app_id}/envs")
async def list_app_envs(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出当前应用可切换的平台环境.

    返回当前 tenant 全部 envs (PlatformEnv), 推断每个 env 的 type
    (dev / preview / prod), 标记 current=true 的是 application.platform_env_id
    对应的那个.

    前端应用栏 "开发 / 生产" toggle 用这个 endpoint:
      - 默认显示 type=dev 那个 (current env 一般是 dev)
      - 点 "生产" → 找 type=prod 的 env, 切 iframe URL 走那个 env_id
      - 没 type=prod env → toast "未配置生产环境"

    返:
      ok: True
      envs: [
        { id, env_name, alias?, base_url, type, current, status,
          has_token, can_iframe }
      ]
      current_env_id: int | None
      has_prod_env: bool
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
    await _require_application_permission(ctx, db, app, Action.VIEW)

    # 拉当前 tenant 所有 env
    env_rows = await db.execute(
        select(PlatformEnv)
        .where(PlatformEnv.tenant_id == ctx.tenant_id)
        .order_by(PlatformEnv.is_default.desc(), PlatformEnv.id.asc())
    )
    envs = env_rows.scalars().all()

    out_envs = []
    has_prod = False
    for env in envs:
        env_type = _infer_env_type(env.env_name)
        if env_type == "prod":
            has_prod = True
        is_current = bool(app.platform_env_id and env.id == app.platform_env_id)
        has_token = bool(env.token)
        out_envs.append({
            "id": env.id,
            "env_name": env.env_name,
            "alias": env.alias,
            "base_url": env.base_url,
            "type": env_type,
            "current": is_current,
            "status": env.status,
            "is_default": env.is_default,
            "has_token": has_token,
            "can_iframe": has_token and env.status == "connected",
        })

    return {
        "ok": True,
        "envs": out_envs,
        "current_env_id": app.platform_env_id,
        "has_prod_env": has_prod,
        "apaas_app_id": app.apaas_app_id,  # 前端判断是否能切 (没 apaas_app_id = 没部署)
    }


# ── API 调用日志 ──

@router.get("/{app_id}/api-logs")
async def list_api_logs(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    step_key: Optional[str] = Query(None),
    success: Optional[bool] = Query(None),
):
    """查询应用的平台 API 调用日志（分页）"""
    # 验证应用归属
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    await _require_application_permission(ctx, db, app, Action.VIEW)

    # 构建查询
    query = select(ApiCallLog).where(ApiCallLog.application_id == app_id)
    count_query = select(sa_func.count()).select_from(ApiCallLog).where(ApiCallLog.application_id == app_id)

    if step_key:
        query = query.where(ApiCallLog.step_key == step_key)
        count_query = count_query.where(ApiCallLog.step_key == step_key)
    if success is not None:
        query = query.where(ApiCallLog.success == success)
        count_query = count_query.where(ApiCallLog.success == success)

    # 总数
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # 分页查询
    query = query.order_by(desc(ApiCallLog.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": log.id,
                "step_key": log.step_key,
                "method": log.method,
                "url": log.url,
                "request_body": log.request_body,
                "response_status": log.response_status,
                "response_body": log.response_body,
                "success": log.success,
                "error_message": log.error_message,
                "elapsed_ms": log.elapsed_ms,
                "created_at": str(log.created_at) if log.created_at else None,
            }
            for log in logs
        ],
    }



# ---------------------------------------------------------------------------
# Phase F：Application 默认模式 (simple|pro|None) 端点
# ---------------------------------------------------------------------------
class UpdateAppDefaultModeRequest(BaseModel):
    default_mode: Optional[str] = None  # None or 'simple' or 'pro'


@router.get("/{application_id}/default-mode")
async def get_application_default_mode(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = (await db.execute(
        select(Application).where(
            Application.id == application_id, Application.tenant_id == ctx.tenant_id
        )
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")
    return {"application_id": app.id, "default_mode": app.default_mode}


@router.patch("/{application_id}/default-mode")
async def patch_application_default_mode(
    application_id: int,
    req: UpdateAppDefaultModeRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = (await db.execute(
        select(Application).where(
            Application.id == application_id, Application.tenant_id == ctx.tenant_id
        )
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")
    if not app.project_id:
        raise HTTPException(400, "应用未关联 project，无法设置默认模式")
    await require_project_access(
        db, project_id=app.project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )
    if req.default_mode not in (None, "simple", "pro"):
        raise HTTPException(400, "default_mode 仅支持 None / 'simple' / 'pro'")
    app.default_mode = req.default_mode
    await db.commit()
    return {"application_id": app.id, "default_mode": app.default_mode}


@router.post("/{application_id}/git-project/ensure")
async def ensure_application_git_project(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """确保老应用也有 Project，供 Project 级 Git/GitHub 连接复用。"""
    app = (await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")

    if app.project_id:
        await require_project_access(
            db,
            project_id=app.project_id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            minimum_role="member",
        )
        return {"application_id": app.id, "project_id": app.project_id, "created": False}

    if app.user_id != ctx.user.id and app.created_by != ctx.user.id:
        raise HTTPException(403, "无权为该应用创建 Git 项目")

    project = Project(
        name=app.app_name or app.app_code or f"应用 {app.id}",
        description=f"应用「{app.app_name or app.app_code or app.id}」的 Git/GitHub 集成项目",
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=ctx.user.id, role="owner"))
    app.project_id = project.id
    await db.commit()
    await db.refresh(app)
    return {"application_id": app.id, "project_id": app.project_id, "created": True}


# ─────────────────────── App ↔ AI Chat session 绑定 ───────────────────────


@router.post("/{app_id}/chat-session/ensure")
async def ensure_app_chat_session(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取或创建 application 绑定的 ai_chat_session。

    首次调用：建一个 ai_chat_session（mode=chat），把应用最新 md 作为 artifact
    注入（filename=`{app_name}-设计文档.md`），让 AI 在对话里能直接 read/write 这份文档。
    回写 application.ai_chat_session_id；后续调用直接复用同一 session。
    """
    from app.models import DocumentVersion
    from app.models.ai_chat import AIChatArtifact, AIChatSession

    res = await db.execute(
        select(Application).where(
            Application.id == app_id, Application.tenant_id == ctx.tenant_id
        )
    )
    app = res.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    # 已绑就直接返回
    if app.ai_chat_session_id:
        existing = (
            await db.execute(
                select(AIChatSession).where(AIChatSession.id == app.ai_chat_session_id)
            )
        ).scalar_one_or_none()
        if existing and existing.tenant_id == ctx.tenant_id:
            return {
                "session_id": existing.id,
                "title": existing.title,
                "is_new": False,
            }
        # session 被删了或属其他租户：清掉重新建
        app.ai_chat_session_id = None

    session = AIChatSession(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user.id,
        title=f"调整应用：{app.app_name or app.app_code or app_id}",
        mode="chat",
        status="active",
    )
    db.add(session)
    await db.flush()

    # 注入应用最新 md 作为初始 artifact
    latest_doc = (
        await db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.application_id == app.id)
            .order_by(DocumentVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    initial_md = ""
    if latest_doc:
        try:
            from app.routes.applications._doc_helpers import _ensure_doc_version_rendered_content as _render_md
            initial_md = await _render_md(db, app, latest_doc)
        except Exception:
            initial_md = ""
    if not initial_md and app.config_preview:
        # fallback：从 config_preview 渲染 md
        try:
            from app.routes.applications._doc_helpers import _render_doc_content_from_config as _render_from_cfg
            initial_md = _render_from_cfg(loads_if_str(app.config_preview)) or ""
        except Exception:
            initial_md = ""

    artifact_filename = f"{app.app_name or app.app_code or 'app'}-设计文档.md"
    if initial_md.strip():
        db.add(
            AIChatArtifact(
                session_id=session.id,
                filename=artifact_filename,
                format="md",
                content=initial_md,
                version=1,
            )
        )

    app.ai_chat_session_id = session.id
    await db.commit()
    await db.refresh(session)

    return {
        "session_id": session.id,
        "title": session.title,
        "is_new": True,
        "artifact_filename": artifact_filename if initial_md.strip() else None,
    }


@router.post("/{app_id}/sync-from-chat-md")
async def sync_app_from_chat_md(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """从绑定的 ai_chat session 拉最新 md artifact，走 upload-doc-version 流程更新应用。

    返回 doc-version 创建结果（version_id / change_plan_id 等），前端拿到后跟原"上传新版 md"
    一样进入变更预览/审查界面。
    """
    from app.models.ai_chat import AIChatArtifact

    res = await db.execute(
        select(Application).where(
            Application.id == app_id, Application.tenant_id == ctx.tenant_id
        )
    )
    app = res.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    if not app.ai_chat_session_id:
        raise HTTPException(status_code=400, detail="应用还未绑定 AI Chat 会话，请先在对话中产生设计文档")

    # 拉最新 md artifact（按 updated_at desc，filter md）
    art = (
        await db.execute(
            select(AIChatArtifact)
            .where(AIChatArtifact.session_id == app.ai_chat_session_id)
            .where(AIChatArtifact.format == "md")
            .order_by(AIChatArtifact.updated_at.desc(), AIChatArtifact.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not art or not art.content.strip():
        raise HTTPException(
            status_code=400,
            detail="对话里还没有可应用的 md 设计文档；请先让 AI 用 write_artifact 产出 / 修改设计文档",
        )

    return {
        "ok": True,
        "artifact_filename": art.filename,
        "artifact_version": art.version,
        "content": art.content,
        # 前端拿到 content 后调既有的 upload-doc-version 接口（FormData 上传 md）走完整变更流
        "next_step": "POST /applications/{app_id}/upload-doc-version with file=this content",
    }


# ============================================================================
# Plan C (2026-05-19): Deploy from ai_chat artifact
#
# 流：AIChatPage 用户点 🚀 → DeployConfirmModal 弹起 → 用户确认 → 调本 endpoint
#  1. 校验 artifact 属于当前 tenant
#  2. parse_design_doc(artifact.content) → config_preview JSON
#  3. 创建 / 复用 Application 记录 (status='generating', requirement_doc=md)
#  4. 返回 task_id + app_id 供前端轮询
#
# 真 build pipeline (run_complete_generation) 复用既有 generate.py 的
# /api/applications/{app_id}/generate SSE 端点 — 前端拿到 app_id 后接 SSE 即可。
# 这里 deploy-from-artifact 只做"建库+预解析" + 返回 task_id 做轻量轮询。
# ============================================================================


class DeployFromArtifactReq(BaseModel):
    """触发部署 — 从 ai_chat_artifacts 拉 md 内容生成应用。"""
    artifact_id: int
    env: str = "test"  # dev / test / prod
    app_code: Optional[str] = None  # 可选覆盖（默认从 md 里解析）
    platform_env_id: Optional[int] = None  # 可选覆盖（默认走租户 default env）


class DeployTaskResp(BaseModel):
    task_id: str
    app_id: int
    sse_url: str  # SSE 进度流 (复用 /api/applications/{app_id}/generate)


class DeployStatusResp(BaseModel):
    done: bool
    phase: str  # draft / generating / completed / failed
    progress: int  # 0-100 (粗略估算)
    error: Optional[str] = None
    app_id: Optional[int] = None


def _parse_task_id(task_id: str) -> Optional[int]:
    """task_id 格式: deploy-art-{app_id}-{epoch}, 抽出 app_id"""
    try:
        parts = task_id.split("-")
        # ["deploy", "art", "{app_id}", "{epoch}"]
        if len(parts) >= 4 and parts[0] == "deploy" and parts[1] == "art":
            return int(parts[2])
    except Exception:
        pass
    return None


@router.post("/deploy-from-artifact", response_model=DeployTaskResp)
async def deploy_from_artifact(
    payload: DeployFromArtifactReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """从 ai_chat artifact (md 设计文档) 触发应用部署。

    返回 task_id 让前端轮询；app_id 让前端可立即跳转应用详情页 / 接 SSE。
    """
    from app.models.ai_chat import AIChatArtifact, AIChatSession
    from app.doc_parser import parse_design_doc

    # 1. 拉 artifact + 校验属于当前 tenant
    row = (await db.execute(
        select(AIChatArtifact, AIChatSession)
        .join(AIChatSession, AIChatArtifact.session_id == AIChatSession.id)
        .where(
            AIChatArtifact.id == payload.artifact_id,
            AIChatSession.tenant_id == ctx.tenant_id,
        )
    )).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="artifact 不存在或不属于当前租户")
    art, sess = row
    if not art.content.strip():
        raise HTTPException(status_code=400, detail="artifact 内容为空")
    if art.format != "md":
        raise HTTPException(
            status_code=400,
            detail=f"artifact 格式必须是 md (当前: {art.format})",
        )

    # 2. parse md → config_preview
    try:
        parsed = parse_design_doc(art.content)
    except Exception as e:
        logger.error(f"parse_design_doc failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"md 解析失败: {e}")

    if not isinstance(parsed, dict) or "data" not in parsed:
        raise HTTPException(
            status_code=400,
            detail="md 解析未产出 preview data — 请检查文档是否符合标准 6 章节格式",
        )

    preview_data = parsed.get("data", {})
    if not isinstance(preview_data, dict):
        raise HTTPException(status_code=400, detail="md 解析结果格式异常")

    # 3. 推导 app_name / app_code
    app_name = (
        preview_data.get("appName")
        or preview_data.get("app_name")
        or art.filename.rsplit(".", 1)[0]  # 去 .md 后缀作为 fallback
        or "未命名应用"
    )
    ascii_code = (
        _normalize_app_code(payload.app_code)
        or _normalize_app_code(preview_data.get("appCode") or preview_data.get("app_code"))
        or _coerce_app_code(app_name)
    )
    if not ascii_code:
        import hashlib
        ascii_code = f"app-{hashlib.md5(app_name.encode()).hexdigest()[:6]}"
    preview_data["appCode"] = ascii_code
    preview_data["app_code"] = ascii_code

    # 4. 决定 platform_env_id（优先级：req > tenant default > any connected）
    resolved_env_id: Optional[int] = None
    if payload.platform_env_id:
        env_check = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.id == payload.platform_env_id,
                PlatformEnv.tenant_id == ctx.tenant_id,
            )
        )
        if env_check.scalar_one_or_none():
            resolved_env_id = payload.platform_env_id
    if not resolved_env_id:
        env_default = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == ctx.tenant_id,
                PlatformEnv.is_default == True,
            )
        )
        env_obj = env_default.scalar_one_or_none()
        if env_obj:
            resolved_env_id = env_obj.id
    if not resolved_env_id:
        env_conn = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == ctx.tenant_id,
                PlatformEnv.status == "connected",
            ).limit(1)
        )
        env_obj = env_conn.scalar_one_or_none()
        if env_obj:
            resolved_env_id = env_obj.id

    # 5. 🔑 2026-05-28 appCode = 应用身份: 同租户同 app_code 已存在 → 复用同一应用 + 增量合并 config,
    #    绝不建重复应用。修"大文档拆批 → 第二批同 appCode 撞'编码重复' → agent 加 -v1 →
    #    inn-idm / inn-idm-v1 多个残缺应用乱套"(用户实测)。apaas appCode 本就唯一, 同 code =
    #    同一个应用 —— 不论状态/时间/有无 apaas_app_id 都复用 (保留 apaas_app_id 让 generate
    #    pipeline 增量补缺失模型/表单, 而非新建)。顺带覆盖了原 retry-storm 去重 (5min 窗口)。
    config_str = _dump_preview_config(parsed)
    reused = (
        await db.execute(
            select(Application).where(
                Application.tenant_id == ctx.tenant_id,
                Application.app_code == ascii_code,
            ).order_by(Application.id.desc()).limit(1)
        )
    ).scalar_one_or_none()

    if reused:
        # 增量合并 config (按 code 并集模型/表单/角色/字典/权限), 保留 apaas_app_id
        try:
            merged_data = _merge_preview_data(
                _extract_preview_data(reused.config_preview), preview_data
            )
            reused.config_preview = _dump_preview_config({"type": "preview", "data": merged_data})
        except Exception as merge_exc:  # noqa: BLE001
            logger.warning(
                "deploy-from-artifact appCode 复用: 合并 config 失败, 退回新 config: %s", merge_exc
            )
            reused.config_preview = config_str
        reused.app_name = app_name or reused.app_name
        reused.requirement_doc = art.content
        if resolved_env_id:
            reused.platform_env_id = resolved_env_id
        reused.status = "generating"
        reused.ai_chat_session_id = sess.id
        await db.commit()
        await db.refresh(reused)
        app = reused
        logger.info(
            "deploy-from-artifact appCode 复用: app_id=%s app_code=%s (复用同一应用 + 增量合并, 不新建)",
            app.id, ascii_code,
        )
    else:
        app = Application(
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            created_by=ctx.user.id,
            app_name=app_name,
            app_code=ascii_code,
            config_preview=config_str,
            requirement_doc=art.content,
            platform_env_id=resolved_env_id,
            ai_chat_session_id=sess.id,
            status="generating",
        )
        db.add(app)
        await db.commit()
        await db.refresh(app)

    import time
    task_id = f"deploy-art-{app.id}-{int(time.time())}"

    logger.info(
        "deploy-from-artifact: artifact_id=%s tenant=%s → app_id=%s code=%s env=%s task=%s",
        art.id, ctx.tenant_id, app.id, ascii_code, payload.env, task_id,
    )

    # SSE URL 走既有 /applications/{app_id}/generate（real build pipeline）
    # 前端拿到这个 URL 后接 EventSource (要带 ?token=<jwt> query param)
    sse_url = f"/api/applications/{app.id}/generate"

    return DeployTaskResp(
        task_id=task_id,
        app_id=app.id,
        sse_url=sse_url,
    )


@router.get("/deploy-status/{task_id}", response_model=DeployStatusResp)
async def deploy_status(
    task_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """轮询部署状态 — 根据 task_id 抽 app_id 查 Application.status。

    progress 是基于 status 的粗略估算（draft=10 / generating=50 / completed=100 / failed=0），
    真细节进度走 SSE /api/applications/{app_id}/generate。
    """
    app_id = _parse_task_id(task_id)
    if not app_id:
        raise HTTPException(status_code=400, detail=f"task_id 格式错误: {task_id}")

    res = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = res.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="task 对应的应用不存在或不属于当前租户")

    status = app.status or "draft"
    progress_map = {
        "draft": 10,
        "generating": 50,
        "updating": 60,
        "completed": 100,
        "failed": 0,
    }
    progress = progress_map.get(status, 0)
    done = status in ("completed", "failed")
    error = None
    if status == "failed":
        # 老 generation flow 没记结构化错；从 ApiCallLog 抓最近一条失败的 error_message
        try:
            log_res = await db.execute(
                select(ApiCallLog).where(
                    ApiCallLog.application_id == app.id,
                    ApiCallLog.success == False,  # noqa: E712
                ).order_by(ApiCallLog.created_at.desc()).limit(1)
            )
            log = log_res.scalar_one_or_none()
            if log and log.error_message:
                error = log.error_message[:500]  # 截断防过长
        except Exception:
            pass
        if not error:
            error = "部署失败（查看应用详情页错误日志）"

    return DeployStatusResp(
        done=done,
        phase=status,
        progress=progress,
        error=error,
        app_id=app.id,
    )

