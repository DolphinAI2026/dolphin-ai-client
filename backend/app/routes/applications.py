from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select, desc, func as sa_func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from app.database import get_db
from app.models import User, Application, DocumentVersion, ChangePlan, ApiCallLog, PlatformEnv, Conversation, ConfigSnapshot
from app.auth import get_current_user
from app.schemas import ApplicationCreate, ApplicationResponse, MergedAppResponse
from app.deps import get_auth_context, AuthContext
from app.permissions import has_org_permission, check_resource_permission, batch_get_permissions, Action
from jose import JWTError, jwt
from app.config import settings
from app.apaas_client import APaaSClient
from app.crypto import decrypt_password

from app.services.config_converter import convert_analysis_to_app_config

router = APIRouter(prefix="/applications", tags=["应用"])
logger = logging.getLogger(__name__)


def _compact_preview_payload(config: dict | None) -> dict:
    if not isinstance(config, dict):
        return {}

    data = config.get("data", config)
    if not isinstance(data, dict):
        return {}

    compact_models = []
    for model in data.get("models", []) or []:
        if not isinstance(model, dict):
            continue
        compact_fields = []
        for field in model.get("fields", []) or []:
            if not isinstance(field, dict):
                continue
            compact_field = {
                "code": field.get("code"),
                "name": field.get("name"),
                "type": field.get("type"),
            }
            if field.get("database_field_type") or field.get("databaseFieldType"):
                compact_field["database_field_type"] = field.get("database_field_type") or field.get("databaseFieldType")
            if field.get("max_length") or field.get("maxLength") or field.get("length"):
                compact_field["max_length"] = field.get("max_length") or field.get("maxLength") or field.get("length")
                compact_field["length"] = field.get("length") or field.get("max_length") or field.get("maxLength")
            if field.get("dict"):
                compact_field["dict"] = field.get("dict")
            if field.get("ref"):
                compact_field["ref"] = field.get("ref")
            if field.get("required") is True:
                compact_field["required"] = True
            if field.get("comment"):
                compact_field["comment"] = field.get("comment")
            compact_fields.append(compact_field)

        compact_model = {
            "code": model.get("code"),
            "name": model.get("name"),
            "fields": compact_fields,
        }
        if model.get("table_type"):
            compact_model["table_type"] = model.get("table_type")
        if model.get("parent_model_code"):
            compact_model["parent_model_code"] = model.get("parent_model_code")
        compact_models.append(compact_model)

    compact_forms = []
    for form in data.get("forms", []) or []:
        if not isinstance(form, dict):
            continue
        compact_components = []
        for comp in form.get("components", []) or []:
            if not isinstance(comp, dict):
                continue
            compact_comp = {
                "code": comp.get("code"),
                "label": comp.get("label"),
                "componentType": comp.get("componentType"),
            }
            for key in ("modelCode", "tableModelCode", "sectionType", "modelField"):
                if comp.get(key):
                    compact_comp[key] = comp.get(key)
            for key in ("hidden", "readonly", "required", "showInList", "searchable"):
                if key in comp and comp.get(key) is not None:
                    compact_comp[key] = bool(comp.get(key))
            compact_components.append(compact_comp)

        compact_form = {
            "name": form.get("name") or form.get("formName"),
            "modelCode": form.get("modelCode"),
            "components": compact_components,
        }
        if form.get("allModelCodes"):
            compact_form["allModelCodes"] = form.get("allModelCodes")
        compact_forms.append(compact_form)

    compact_permissions = []
    for perm in data.get("permissions", []) or []:
        if not isinstance(perm, dict):
            continue
        compact_perm = {
            "formName": perm.get("formName"),
            "formCode": perm.get("formCode"),
        }
        rules = []
        for rule in perm.get("rules", []) or []:
            if not isinstance(rule, dict):
                continue
            rules.append({
                "roleCode": rule.get("roleCode"),
                "roleName": rule.get("roleName"),
                "actions": rule.get("actions", []),
                "dataScope": rule.get("dataScope"),
            })
        if rules:
            compact_perm["rules"] = rules
        compact_permissions.append(compact_perm)

    return {
        "appName": data.get("appName"),
        "appCode": data.get("appCode"),
        "roles": data.get("roles", []),
        "dicts": data.get("dicts", []),
        "models": compact_models,
        "forms": compact_forms,
        "workflows": data.get("workflows", []),
        "permissions": compact_permissions or data.get("permissions", []),
    }


def _dump_preview_config(config: dict | None) -> str:
    compact = _compact_preview_payload(config)
    return json.dumps({"type": "preview", "data": compact}, ensure_ascii=False, separators=(",", ":"))


def _dump_parsed_config(config: dict | None) -> str:
    compact = _compact_preview_payload(config)
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def _parsed_config_is_stale(parsed_config: dict | None) -> bool:
    if not isinstance(parsed_config, dict):
        return True
    data = parsed_config.get("data", parsed_config)
    models = data.get("models", []) if isinstance(data, dict) else []
    if not isinstance(models, list) or not models:
        return True
    has_table_meta = any(m.get("table_type") or m.get("parent_model_code") for m in models if isinstance(m, dict))
    has_field_meta = False
    for model in models:
        if not isinstance(model, dict):
            continue
        for field in model.get("fields", []) or []:
            if not isinstance(field, dict):
                continue
            if (
                field.get("database_field_type") or field.get("databaseFieldType")
                or field.get("max_length") or field.get("maxLength") or field.get("length")
            ):
                has_field_meta = True
                break
        if has_field_meta:
            break
    return not (has_table_meta and has_field_meta)


async def _ensure_doc_version_parsed_config(
    db: AsyncSession,
    version: DocumentVersion,
) -> dict | None:
    parsed = None
    if version.parsed_config:
        try:
            parsed = json.loads(version.parsed_config) if isinstance(version.parsed_config, str) else version.parsed_config
        except Exception:
            parsed = None

    if not _parsed_config_is_stale(parsed):
        return parsed

    if not version.raw_content:
        return parsed

    try:
        from app.doc_pipeline import parse_document

        reparsed = await parse_document(version.raw_content)
        if reparsed:
            version.parsed_config = _dump_parsed_config(reparsed)
            await db.flush()
            return _compact_preview_payload(reparsed)
    except Exception:
        logger.warning("文档版本重解析失败 id=%s", version.id, exc_info=True)

    return parsed


async def _resolve_builder_llm_cfg(
    db: AsyncSession,
    tenant_id: int,
    *,
    conversation_id: Optional[int] = None,
) -> dict | None:
    from app.harness.llm_resolver import resolve_llm_config

    selected_config_id: Optional[int] = None
    if conversation_id is not None:
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )
        conversation = conv_result.scalar_one_or_none()
        if conversation:
            selected_config_id = conversation.selected_llm_config_id

    resolved = await resolve_llm_config(
        db,
        tenant_id,
        purpose="builder",
        selected_config_id=selected_config_id,
    )
    if not resolved:
        return None
    return {
        "api_key": resolved.api_key,
        "base_url": resolved.base_url,
        "model": resolved.model,
        "max_tokens": resolved.max_tokens,
        "provider": resolved.provider,
    }


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
        conversation_id=app.conversation_id,
        platform_env_id=app.platform_env_id,
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


def _build_apaas_url(apaas_app_id: str, base_url: str | None = None, tenant_id: str | None = None) -> str:
    """得帆云平台应用直达链接（从环境配置取地址）"""
    host = base_url.rstrip("/").replace("/backend", "") if base_url else "https://apaas-poc.definesys.cn"
    tid = tenant_id or settings.apaas_tenant_id
    return f"{host}/platform/{tid}/admin/app-store/edit-app?appId={apaas_app_id}&currentStepIndex=0"


def _build_local(app: Application, perms: dict | None = None, env_name: str | None = None, env_status: str | None = None) -> MergedAppResponse:
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
        env_name=env_name,
        env_status=env_status,
        created_at=str(enriched.created_at) if enriched.created_at else None,
        updated_at=str(enriched.updated_at) if enriched.updated_at else None,
    )


def _build_linked(app: Application, remote: dict, perms: dict | None = None, env_base_url: str | None = None, env_tenant_id: str | None = None, env_name: str | None = None, env_status: str | None = None) -> MergedAppResponse:
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
        apaas_url=_build_apaas_url(apaas_id, env_base_url, env_tenant_id),
        conversation_id=app.conversation_id,
        models=enriched.models, forms=enriched.forms,
        roles=enriched.roles, dicts=enriched.dicts,
        config_preview=enriched.config_preview,
        permissions=perms,
        env_name=env_name,
        env_status=env_status,
        created_at=str(enriched.created_at) if enriched.created_at else None,
        updated_at=str(enriched.updated_at) if enriched.updated_at else None,
    )


def _build_remote(remote: dict, env_base_url: str | None = None, env_tenant_id: str | None = None) -> MergedAppResponse:
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
        apaas_url=_build_apaas_url(apaas_id, env_base_url, env_tenant_id),
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

    # 1.5 获取所有环境信息（用于构建 URL 和显示环境名称）
    env_base_url = None
    env_tenant_id = None
    env_map: dict[int, dict] = {}  # env_id → {env_name, status}
    try:
        from app.models import PlatformEnv
        env_result = await db.execute(
            select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id)
        )
        all_envs = env_result.scalars().all()
        for env in all_envs:
            env_map[env.id] = {"env_name": env.env_name, "status": env.status}
            if env.is_default:
                env_base_url = env.base_url
                env_tenant_id = env.platform_tenant_id
    except Exception:
        pass

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
        # 查找应用关联的环境信息
        app_env = env_map.get(app.platform_env_id) if app.platform_env_id else None
        app_env_name = app_env["env_name"] if app_env else None
        app_env_status = app_env["status"] if app_env else None

        if app.apaas_app_id and app.apaas_app_id in remote_map:
            matched_remote_ids.add(app.apaas_app_id)
            if source_filter and source_filter != "linked":
                continue
            merged.append(_build_linked(app, remote_map[app.apaas_app_id], perms, env_base_url, env_tenant_id, app_env_name, app_env_status))
        else:
            if source_filter and source_filter != "local":
                continue
            merged.append(_build_local(app, perms, app_env_name, app_env_status))

    # 未匹配的远程应用
    if source_filter != "local":
        for rid, remote in remote_map.items():
            if rid not in matched_remote_ids:
                if source_filter and source_filter != "remote":
                    continue
                merged.append(_build_remote(remote, env_base_url, env_tenant_id))

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

    # 构建平台直达链接
    if app.apaas_app_id:
        env_base_url = env_tenant_id = None
        if app.platform_env_id:
            env_result = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
            env = env_result.scalar_one_or_none()
            if env:
                env_base_url, env_tenant_id = env.base_url, env.platform_tenant_id
        if not env_base_url:
            # 回退到默认环境
            default_env_result = await db.execute(
                select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id, PlatformEnv.is_default == True)
            )
            default_env = default_env_result.scalar_one_or_none()
            if default_env:
                env_base_url, env_tenant_id = default_env.base_url, default_env.platform_tenant_id
        resp.apaas_url = _build_apaas_url(str(app.apaas_app_id), env_base_url, env_tenant_id)

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

    config_str = _dump_preview_config(data.config_preview) if data.config_preview else None
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
                        parsed_config=_dump_parsed_config(data.config_preview),
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
            existing.config_preview = _dump_preview_config(data.config_preview)
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

    config_str = _dump_preview_config(data.config_preview)
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


# ============================================================
# 从平台导入已有应用
# ============================================================

class ImportFromPlatformRequest(BaseModel):
    env_id: int
    apaas_app_id: str


@router.post("/import-from-platform", response_model=ApplicationResponse)
async def import_from_platform(
    body: ImportFromPlatformRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """从平台导入已有应用：拉取结构 → 生成 config_preview + markdown 需求文档"""
    from app.platform_sync import sync_from_platform_full
    from app.services.config_to_spec import config_to_markdown

    # 1. 获取环境
    env_result = await db.execute(
        select(PlatformEnv).where(
            PlatformEnv.id == body.env_id,
            PlatformEnv.tenant_id == ctx.tenant_id,
        )
    )
    env = env_result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="环境不存在")
    if not env.token:
        raise HTTPException(status_code=400, detail="环境未连接，请先登录")

    # 2. 检查是否已导入
    existing = await db.execute(
        select(Application).where(
            Application.tenant_id == ctx.tenant_id,
            Application.apaas_app_id == body.apaas_app_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="该应用已导入")

    # 3. 创建 client，获取应用信息
    client = APaaSClient(
        base_url=env.base_url,
        tenant_id=env.platform_tenant_id,
        token=env.token,
    )

    try:
        app_detail = await client.query_app_detail(body.apaas_app_id)
    except Exception:
        # token 可能过期，尝试刷新
        if env.username and env.password_enc:
            try:
                password = decrypt_password(env.password_enc)
                login_result = await client.login(env.username, password)
                env.token = login_result.get("token", "")
                env.status = "connected"
                await db.commit()
                client = APaaSClient(
                    base_url=env.base_url,
                    tenant_id=env.platform_tenant_id,
                    token=env.token,
                )
                app_detail = await client.query_app_detail(body.apaas_app_id)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"获取应用信息失败: {e}")
        else:
            raise HTTPException(status_code=400, detail="token 过期且无登录凭据")

    if not app_detail:
        raise HTTPException(status_code=404, detail="平台上未找到该应用")

    app_name = app_detail.get("appName", app_detail.get("name", "未命名"))
    app_code = app_detail.get("appCode", app_detail.get("code", ""))
    app_desc = app_detail.get("description", app_detail.get("appDescription", ""))

    # 4. 完整反向解析
    try:
        config = await sync_from_platform_full(client, body.apaas_app_id, app_name)
    except Exception as e:
        logger.error(f"反向解析失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"反向解析应用结构失败: {e}")

    # 5. 生成 markdown 需求文档
    try:
        markdown_spec = config_to_markdown(config, app_description=app_desc)
    except Exception as e:
        logger.warning(f"生成 markdown 失败: {e}")
        markdown_spec = ""

    # 6. 创建本地 Application 记录
    config_str = json.dumps(config, ensure_ascii=False)
    new_app = Application(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        created_by=ctx.user.id,
        app_name=app_name,
        app_code=app_code or app_name.lower().replace(" ", "_"),
        description=app_desc,
        config_preview=config_str,
        requirement_doc=markdown_spec,
        apaas_app_id=body.apaas_app_id,
        platform_env_id=body.env_id,
        status="completed",
    )
    db.add(new_app)
    await db.commit()
    await db.refresh(new_app)

    logger.info(f"应用导入成功: {app_name} (apaas_id={body.apaas_app_id})")
    return _enrich(new_app)


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
        app.config_preview = _dump_preview_config(data.config_preview)
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
    if app.config_preview:
        try:
            config = json.loads(app.config_preview) if isinstance(app.config_preview, str) else app.config_preview
            data = config.get("data", config)
            data["app_code"] = new_code
            app.config_preview = _dump_preview_config(config)

            if app.current_doc_version:
                import hashlib
                from app.routes.generation_steps import _render_design_doc_markdown

                new_version = app.current_doc_version + 1
                config_json = _dump_parsed_config(config)
                doc_ver = DocumentVersion(
                    application_id=app.id,
                    version=new_version,
                    filename=f"app-code-fix-v{new_version}",
                    content_hash=hashlib.sha256(config_json.encode()).hexdigest(),
                    raw_content=_render_design_doc_markdown(app.app_name, new_code, data),
                    parsed_config=config_json,
                    summary=f"应用编码修复: {new_code}",
                )
                db.add(doc_ver)
                app.current_doc_version = new_version
        except Exception as e:
            logger.warning(f"同步应用编码到文档版本失败: {e}")
    await db.commit()
    return {"ok": True, "app_code": new_code}


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

    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

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

    try:
        client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)
        app_detail = await client.query_app_detail(str(app.apaas_app_id))
        current_version = app_detail.get("appVersion", app_detail.get("version", ""))
        if current_version:
          parts = current_version.split(".")
          try:
              nums = [int(p) for p in parts]
              nums[-1] += 1
              next_version = ".".join(str(p) for p in nums)
          except Exception:
              next_version = "1.0.1"
        else:
          next_version = "1.0.0"
        await client.deploy_app(str(app.apaas_app_id), next_version, abstract="aPaaS Builder 应用上线")
        app.status = "completed"
        await db.commit()
        return {"ok": True, "version": next_version, "remote_status": "ENABLE"}
    except Exception as e:
        detail = str(e)
        if ("Token已过期或无效" in detail or "401" in detail) and env.username and env.password_enc:
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
                    current_version = app_detail.get("appVersion", app_detail.get("version", ""))
                    if current_version:
                        parts = current_version.split(".")
                        try:
                            nums = [int(p) for p in parts]
                            nums[-1] += 1
                            next_version = ".".join(str(p) for p in nums)
                        except Exception:
                            next_version = "1.0.1"
                    else:
                        next_version = "1.0.0"
                    await client.deploy_app(str(app.apaas_app_id), next_version, abstract="aPaaS Builder 应用上线")
                    app.status = "completed"
                    await db.commit()
                    return {"ok": True, "version": next_version, "remote_status": "ENABLE"}
            except Exception as retry_error:
                raise HTTPException(status_code=401, detail=f"平台登录失效，请重新连接APaaS平台：{retry_error}")
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

        await check_resource_permission(ctx, db, app, "application", Action.DELETE)

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

    from app.doc_pipeline import parse_document
    try:
        result = await parse_document(text)
        data = result.get("data", result)
    except Exception as e:
        logger.error(f"文档解析失败: {e}", exc_info=True)
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

    # 获取当前对话/租户绑定的 Builder 模型，避免文档解析回退到 .env 默认模型
    _tenant_llm_cfg = await _resolve_builder_llm_cfg(
        db,
        tenant_id,
        conversation_id=existing_conversation_id,
    )

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
        import asyncio
        from app.database import AsyncSessionLocal
        from app.doc_text_differ import diff_sections, get_diff_stats
        from app.doc_pipeline import parse_document
        from app.config_diff import compute_config_diff

        data = None
        diff_result = None
        is_incremental = bool(v1_doc_info)
        v1_parsed_config = None

        try:
            # ── 增量模式：有 V1 文档时先检查是否有变化 ──
            if v1_doc_info and v1_doc_info.get("raw_content"):
                yield {"event": "progress", "data": json.dumps({"message": "正在对比文档..."}, ensure_ascii=False)}
                diff_result = diff_sections(v1_doc_info["raw_content"], text)
                diff_stats = get_diff_stats(diff_result)
                total_changes = diff_stats["added"] + diff_stats["modified"] + diff_stats["removed"]

                if total_changes == 0:
                    yield {"event": "error", "data": json.dumps({"message": "文档内容无变化，无需重新上传"}, ensure_ascii=False)}
                    return

                yield {"event": "progress", "data": json.dumps({
                    "message": f"发现 {total_changes} 个章节变化（新增 {diff_stats['added']} 个，修改 {diff_stats['modified']} 个，删除 {diff_stats['removed']} 个）",
                    "diff_stats": diff_stats,
                }, ensure_ascii=False)}

            # ── 全量解析：用 asyncio.Queue 实时把进度推给前端 ──
            progress_queue: asyncio.Queue = asyncio.Queue()

            async def _on_progress(msg: str):
                await progress_queue.put(msg)

            # 启动解析任务（与 SSE 流并发）
            parse_task = asyncio.create_task(
                parse_document(text, llm_cfg=_tenant_llm_cfg, on_progress=_on_progress)
            )

            # 实时转发进度消息，直到解析完成
            while not parse_task.done():
                try:
                    msg = await asyncio.wait_for(progress_queue.get(), timeout=0.2)
                    yield {"event": "progress", "data": json.dumps({"message": msg}, ensure_ascii=False)}
                except asyncio.TimeoutError:
                    pass

            # 排干队列中剩余消息
            while not progress_queue.empty():
                msg = progress_queue.get_nowait()
                yield {"event": "progress", "data": json.dumps({"message": msg}, ensure_ascii=False)}

            # 取解析结果（若抛异常会在此处重新抛出）
            parse_result = parse_task.result()
            data = parse_result.get("data", parse_result)

            # ── 增量模式：用纯代码 diff 与 V1 config 对比，继承编码 ──
            if v1_doc_info and v1_doc_info.get("parsed_config"):
                try:
                    v1_parsed_config = json.loads(v1_doc_info["parsed_config"]) if isinstance(v1_doc_info["parsed_config"], str) else v1_doc_info["parsed_config"]
                    yield {"event": "progress", "data": json.dumps({"message": "对比配置差异..."}, ensure_ascii=False)}
                    resource_diff = compute_config_diff(v1_parsed_config, data)
                    if resource_diff.normalized_new_config:
                        data = resource_diff.normalized_new_config
                except Exception as e:
                    logger.warning(f"增量 diff 失败，使用全量解析结果: {e}")

        except Exception as e:
            err_msg = str(e) or repr(e) or type(e).__name__
            logger.error(f"文档解析失败: {err_msg}", exc_info=True)
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
                # 增量模式：用 config_diff 展示差异（会自动完成编码继承）
                v1_for_diff = v1_parsed_config
                resource_diff = compute_config_diff(v1_for_diff, data)
                # 使用编码继承后的配置，确保 V1 的 code 被保留
                if resource_diff.normalized_new_config:
                    data = resource_diff.normalized_new_config
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
            config_msg = '```json\n' + _dump_preview_config(data) + '\n```'
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

            config_json_str = _dump_parsed_config(data)
            from app.routes.generation_steps import _render_design_doc_markdown

            rendered_markdown = _render_design_doc_markdown(
                data.get("appName", ""),
                data.get("appCode", ""),
                data,
            )

            doc_ver = DocumentVersion(
                application_id=None,
                conversation_id=conv_id,
                version=new_version,
                filename=fname,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                raw_content=rendered_markdown,
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
    doc_llm_cfg = await _resolve_builder_llm_cfg(
        db,
        tenant_id_val,
        conversation_id=conversation_id,
    )

    async def event_generator():
        from app.database import AsyncSessionLocal
        from app.doc_differ import build_structure_index, semantic_diff, diff_to_actions, compute_hash
        from app.config_diff import compute_config_diff
        from app.doc_text_differ import diff_sections, get_diff_stats

        current_step = "初始化"

        try:
            current_step = "读取文档内容"
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

            current_step = "解析文档结构"
            yield {"event": "progress", "data": json.dumps({"step": "解析文档结构..."}, ensure_ascii=False)}

            # 4. 构建章节索引
            structure_index = build_structure_index(text)

            # ── 全量解析新文档（纯代码优先，失败模块 LLM 修复）──
            from app.doc_pipeline import parse_document

            if v1_doc and v1_doc.get("raw_content"):
                # 有旧文档时先做文本对比，告知变化情况
                current_step = "对比文档章节"
                yield {"event": "progress", "data": json.dumps({"step": "text_diff", "message": "正在对比文档章节..."}, ensure_ascii=False)}
                text_diff = diff_sections(v1_doc["raw_content"], text)
                diff_stats = get_diff_stats(text_diff)
                yield {"event": "progress", "data": json.dumps({
                    "step": "text_diff",
                    "data": diff_stats,
                    "message": f"章节对比完成：新增 {diff_stats['added']}、修改 {diff_stats['modified']}、删除 {diff_stats['removed']}、未变更 {diff_stats['unchanged']}",
                }, ensure_ascii=False)}

            current_step = "解析文档"
            progress_messages = []

            async def _on_progress(msg: str):
                progress_messages.append(msg)

            yield {"event": "progress", "data": json.dumps({"step": "parse", "message": "检查文档标准度..."}, ensure_ascii=False)}
            parse_result = await parse_document(text, llm_cfg=doc_llm_cfg, on_progress=_on_progress)

            for msg in progress_messages:
                yield {"event": "progress", "data": json.dumps({"step": "parse", "message": msg}, ensure_ascii=False)}

            v2_config = parse_result.get("data", parse_result)

            current_step = "对比资源差异"
            yield {"event": "progress", "data": json.dumps({"step": "对比资源差异..."}, ensure_ascii=False)}

            # 6. 加载 V1 配置（从应用当前 config_preview）
            v1_config: dict = {}
            if current_config_str:
                try:
                    loaded = json.loads(current_config_str) if isinstance(current_config_str, str) else current_config_str
                    v1_config = loaded.get("data", loaded)
                except Exception:
                    pass

            # 7. 资源级差异对比（用于前端展示，会自动完成编码继承）
            resource_diff = compute_config_diff(v1_config, v2_config)
            # 使用编码继承后的配置，确保 V1 的 code 被保留
            if resource_diff.normalized_new_config:
                v2_config = resource_diff.normalized_new_config
            resource_diff_dict = resource_diff.to_dict()

            # 8. 语义对比（用于生成可勾选 actions）
            diff = semantic_diff(v1_config, v2_config)

            # 9. 生成 patch actions
            actions = diff_to_actions(diff, v2_config)

            # 10. 生成摘要
            summary = resource_diff.summary or f"文档 V{new_version} 资源变更分析完成"

            current_step = "保存版本记录"
            yield {"event": "progress", "data": json.dumps({"step": "保存版本记录..."}, ensure_ascii=False)}

            # 11. 创建 DocumentVersion + ChangePlan
            async with AsyncSessionLocal() as session:
                app_result = await session.execute(
                    select(Application).where(Application.id == app_id_val)
                )
                app_obj = app_result.scalar_one()
                from app.routes.generation_steps import _render_design_doc_markdown

                rendered_markdown = _render_design_doc_markdown(
                    app_obj.app_name or v2_config.get("appName", ""),
                    app_obj.app_code or v2_config.get("appCode", ""),
                    v2_config,
                )

                doc_ver = DocumentVersion(
                    application_id=app_id_val,
                    version=new_version,
                    filename=fname,
                    content_hash=content_hash,
                    raw_content=rendered_markdown,
                    structure_index=json.dumps(structure_index, ensure_ascii=False),
                    parsed_config=_dump_parsed_config(v2_config),
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

                # 更新应用：文档版本 + 配置 + 状态
                app_obj.current_doc_version = new_version
                # 关键：用 V2 配置更新 config_preview（保留原始 appName）
                if app_obj.app_name:
                    v2_config["appName"] = app_obj.app_name
                app_obj.config_preview = _dump_preview_config(v2_config)
                # 标记需要重新部署
                if app_obj.status == "completed":
                    app_obj.status = "draft"
                # 在 generation_state 中记录配置版本变更
                if app_obj.generation_state:
                    try:
                        from datetime import datetime as dt
                        gs = json.loads(app_obj.generation_state)
                        gs["config_version"] = new_version
                        gs["config_updated_at"] = dt.utcnow().isoformat()
                        app_obj.generation_state = json.dumps(gs, ensure_ascii=False)
                    except Exception:
                        pass

                await session.commit()
                await session.refresh(change_plan)

                yield {
                    "event": "done",
                    "data": json.dumps({
                        "version": new_version,
                        "from_version": max_ver,
                        "to_version": new_version,
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
            detail = str(e).strip() or repr(e).strip() or e.__class__.__name__
            yield {
                "event": "error",
                "data": json.dumps({
                    "message": f"处理失败（步骤：{current_step}）：{detail}",
                    "step": current_step,
                    "error_type": e.__class__.__name__,
                }, ensure_ascii=False)
            }

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
                        current_config = json.loads(from_doc_obj.parsed_config) if isinstance(from_doc_obj.parsed_config, str) else from_doc_obj.parsed_config
                    except Exception:
                        pass

            # 回退：如果没有找到 from_version 的配置，使用 config_preview
            if not current_config and current_config_str:
                try:
                    loaded = json.loads(current_config_str) if isinstance(current_config_str, str) else current_config_str
                    current_config = loaded.get("data", loaded)
                except Exception:
                    pass

            actions = json.loads(actions_str) if isinstance(actions_str, str) else actions_str
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
        parsed_config = await _ensure_doc_version_parsed_config(db, v)
        related_plans = plans_by_to_version.get(v.version, [])
        items.append({
            "id": v.id,
            "version": v.version,
            "filename": v.filename,
            "content_hash": v.content_hash,
            "raw_content": v.raw_content,
            "parsed_config": parsed_config,
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

    await db.commit()

    return {
        "current_version": app.current_doc_version,
        "versions": items,
    }


@router.delete("/{app_id}/doc-versions/{version_id}")
async def delete_doc_version(
    app_id: int,
    version_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除指定文档版本，并同步应用当前版本指针。"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    await check_resource_permission(ctx, db, app, "application", Action.EDIT)

    result = await db.execute(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.application_id == app_id,
        )
    )
    doc_version = result.scalar_one_or_none()
    if not doc_version:
        raise HTTPException(status_code=404, detail="文档版本不存在")

    deleted_version_no = doc_version.version

    await db.execute(
        delete(ChangePlan).where(
            ChangePlan.application_id == app_id,
            (ChangePlan.to_version == deleted_version_no) | (ChangePlan.from_version == deleted_version_no),
        )
    )
    await db.delete(doc_version)
    await db.flush()

    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.application_id == app_id)
        .order_by(desc(DocumentVersion.version))
    )
    remaining_versions = result.scalars().all()

    latest = remaining_versions[0] if remaining_versions else None
    app.current_doc_version = latest.version if latest else None
    if latest and latest.parsed_config:
        try:
            parsed = json.loads(latest.parsed_config) if isinstance(latest.parsed_config, str) else latest.parsed_config
            app.config_preview = _dump_preview_config(parsed)
        except Exception:
            logger.warning("删除文档版本后同步 config_preview 失败", exc_info=True)
            app.config_preview = None
    else:
        app.config_preview = None

    await db.commit()
    return {
        "ok": True,
        "deleted_version": deleted_version_no,
        "current_version": app.current_doc_version,
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
        parsed_config = await _ensure_doc_version_parsed_config(db, v)
        items.append({
            "id": v.id,
            "version": v.version,
            "filename": v.filename,
            "content_hash": v.content_hash,
            "raw_content": v.raw_content,
            "parsed_config": parsed_config,
            "summary": v.summary,
            "structure_index": json.loads(v.structure_index) if v.structure_index else None,
            "created_at": str(v.created_at) if v.created_at else None,
        })

    await db.commit()

    return {
        "versions": items,
    }


# ── 获取单个应用信息 ──

@router.get("/{app_id}")
async def get_application(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取单个应用详情（包含平台链接）"""
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == ctx.tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    # 获取关联的平台环境
    env_base_url = None
    env_tenant_id = None
    if app.platform_env_id:
        env_result = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
        env = env_result.scalar_one_or_none()
        if env:
            env_base_url = env.base_url
            env_tenant_id = env.platform_tenant_id

    apaas_url = None
    if app.apaas_app_id:
        apaas_url = _build_apaas_url(str(app.apaas_app_id), env_base_url, env_tenant_id)

    return {
        "id": app.id,
        "app_name": app.app_name,
        "app_code": app.app_code,
        "status": app.status,
        "apaas_app_id": app.apaas_app_id,
        "apaas_url": apaas_url,
        "platform_env_id": app.platform_env_id,
        "created_at": str(app.created_at) if app.created_at else None,
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

    await check_resource_permission(ctx, db, app, "application", Action.VIEW)

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


# ── AnalysisResult → AppConfig 直接转换（无 LLM） ──────────────────────────


class ConvertConfigRequest(BaseModel):
    doc_result: dict


@router.post("/convert-config")
async def convert_config(
    body: ConvertConfigRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Convert a requirements AnalysisResult JSON directly to AppConfig format.
    Pure Python transformation — no LLM calls, no markdown roundtrip.
    """
    try:
        config = convert_analysis_to_app_config(body.doc_result)
        return {"config": config}
    except Exception as e:
        logger.error(f"Config conversion failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"配置转换失败: {str(e)}")
