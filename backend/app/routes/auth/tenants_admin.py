import logging
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app import runtime
from app.code_runtime.auth import control_plane_access_token, fetch_control_plane_identity
from app.database import get_db
from app.crypto import decrypt_password
from app.models import User
from app.models.tenant import Tenant, UserTenant, Role
from app.schemas import UserInfo, TenantOption
from app.auth import get_password_hash
from app.tenant_public_id import ensure_tenant_public_id
from app.deps import (
    AuthContext,
    get_auth_context,
    get_platform_auth_context,
    is_control_plane_context,
    platform_admin_has_unscoped_tenant_access,
    require_tenant_admin,
    resolve_default_tenant_id_for_user,
)
from app.routes.auth.login import (
    _tenant_options_with_durable_public_ids,
    _apaas_backend_login,
    _apaas_membership_role_preference,
    _apaas_switchable_tenants,
    _ensure_apaas_tenant,
    _extract_apaas_user,
    _extract_default_tenant_item,
    _extract_login_error_message,
    _extract_user_display_name,
    _merge_tenant_items,
    _normalize_apaas_origin,
    _sync_user_membership,
    _tenant_enabled,
    _tenant_item_id,
    _upsert_user_credential,
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


def _reject_control_plane_local_admin(ctx: AuthContext) -> None:
    if is_control_plane_context(ctx):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONTROL_PLANE_REMOTE_MANAGEMENT_REQUIRED",
                "message": "组织、成员、角色和 aPaaS 绑定由 Control Plane 管理，请打开远程控制台",
            },
        )


# ─── Shared helpers ────────────────────────────────────────────────────────────

def _resolve_tenant_role(role: Optional[Role]) -> tuple[str, Optional[str], dict]:
    if not role:
        return "member", None, {}
    role_code = role.role_code or ""
    if role_code in ("R_tenant_admin", "admin"):
        return "tenant_admin", role.role_name, role.permissions or {}
    if role_code == "R_developer":
        return "developer", role.role_name, role.permissions or {}
    if role_code == "R_viewer":
        return "viewer", role.role_name, role.permissions or {}
    return "member", role.role_name, role.permissions or {}


def _serialize_account_binding(user: User) -> dict:
    return {
        "account_source": user.account_source,
        "apaas_user_id": user.apaas_user_id,
        "apaas_tenant_id": user.apaas_tenant_id,
        "coding_user_id": user.coding_user_id,
        "apaas_bound": bool(user.apaas_user_id and user.apaas_tenant_id),
    }


def _serialize_tenant_user(user: User, membership: UserTenant, role: Optional[Role], tenant: Optional[Tenant] = None) -> dict:
    tenant_role, role_name, permissions = _resolve_tenant_role(role)
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "is_active": user.is_active,
        "is_platform_admin": user.is_platform_admin,
        "tenant_id": membership.tenant_id,
        "tenant_name": tenant.tenant_name if tenant else None,
        "tenant_summary": tenant.tenant_name if tenant else None,
        "tenant_status": membership.status,
        "tenant_role": tenant_role,
        "role_code": role.role_code if role else None,
        "role_name": role_name,
        "org_permissions": permissions,
        "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        **_serialize_account_binding(user),
    }


def _serialize_platform_user(user: User, memberships: list[tuple[UserTenant, Tenant, Optional[Role]]]) -> dict:
    active_memberships = [m for m, _tenant, _role in memberships if m.status == 1]
    tenant_names = [tenant.tenant_name for _m, tenant, _role in memberships]
    tenant_summary = "、".join(tenant_names[:3])
    if len(tenant_names) > 3:
        tenant_summary += f" 等 {len(tenant_names)} 个组织"
    if not tenant_summary:
        tenant_summary = "未加入组织"

    tenant_role = "member"
    role_code = "normal_user"
    role_name = "普通账号"
    permissions: dict = {}
    if user.is_platform_admin:
        tenant_role = "platform_admin"
        role_code = "platform_admin"
        role_name = "平台超级管理员"
        tenant_summary = "平台级权限"
    else:
        for _membership, _tenant, role in memberships:
            resolved_role, resolved_name, resolved_permissions = _resolve_tenant_role(role)
            if resolved_role == "tenant_admin":
                tenant_role = resolved_role
                role_code = role.role_code if role else "normal_user"
                role_name = resolved_name or role_name
                permissions = resolved_permissions
                break
            if resolved_role != "member" and tenant_role == "member":
                tenant_role = resolved_role
                role_code = role.role_code if role else "normal_user"
                role_name = resolved_name or role_name
                permissions = resolved_permissions

    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "is_active": user.is_active,
        "is_platform_admin": user.is_platform_admin,
        "tenant_id": None,
        "tenant_name": None,
        "tenant_summary": tenant_summary,
        "tenant_status": 1 if user.is_active else 0,
        "tenant_role": tenant_role,
        "role_code": role_code,
        "role_name": role_name,
        "org_permissions": permissions,
        "joined_at": active_memberships[0].joined_at.isoformat() if active_memberships else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        **_serialize_account_binding(user),
    }


async def _load_user_memberships(
    db: AsyncSession, user_ids: list[int]
) -> dict[int, list[tuple[UserTenant, Tenant, Optional[Role]]]]:
    if not user_ids:
        return {}
    result = await db.execute(
        select(UserTenant, Tenant, Role)
        .join(Tenant, Tenant.id == UserTenant.tenant_id)
        .outerjoin(Role, Role.id == UserTenant.role_id)
        .where(UserTenant.user_id.in_(user_ids))
        .order_by(Tenant.tenant_name.asc(), UserTenant.joined_at.asc())
    )
    grouped: dict[int, list[tuple[UserTenant, Tenant, Optional[Role]]]] = {}
    for membership, tenant, role in result.all():
        grouped.setdefault(membership.user_id, []).append((membership, tenant, role))
    return grouped


def _require_platform_admin(ctx: AuthContext) -> None:
    if ctx.user.is_platform_admin or ctx.tenant_role == "platform_admin":
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台管理员可执行此操作")


# ─── Pydantic models ───────────────────────────────────────────────────────────

class UpdateTenantUserStatusRequest(BaseModel):
    status: int


class UpdateTenantUserRoleRequest(BaseModel):
    role_code: str


class InviteTenantUserRequest(BaseModel):
    username: str
    password: Optional[str] = None
    role_code: Optional[str] = None
    # platform_admin 调用时可选：把账号同步加入指定租户（避免建出"孤儿账号"）
    tenant_id: Optional[int] = None


class TenantCreateRequest(BaseModel):
    tenant_name: str
    tenant_code: str
    max_applications: int = 0
    max_workspaces: int = 0
    max_components: int = 0
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None


class TenantStatusRequest(BaseModel):
    status: int  # 1=active, 0=disabled


class TenantUpdateRequest(BaseModel):
    tenant_name: Optional[str] = None
    max_applications: Optional[int] = None
    max_workspaces: Optional[int] = None
    max_components: Optional[int] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    # apaas 平台绑定字段：UI 直接输 apaas_base_url + apaas_platform_tenant_id
    # （不暴露 PlatformEnv 概念，后端自动 maintain 一条对应 env 记录）
    apaas_base_url: Optional[str] = None
    apaas_platform_tenant_id: Optional[str] = None
    # 高级字段（UI 默认不显示，特殊场景下走 API 直传）
    apaas_env_id: Optional[int] = None


class TenantAdminItem(BaseModel):
    """租户管理列表项。

    plan_type 字段已废弃（ToB 私有化部署不需要 SaaS 风格的订阅档），DB 列保留默认 free
    向后兼容。
    """
    id: int
    tenant_name: str
    tenant_code: str
    max_applications: int
    max_workspaces: int
    max_components: int
    status: int
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    member_count: int = 0
    created_at: Optional[str] = None
    # apaas 平台绑定（前端编辑用）：从 PlatformEnv 反查回来（前端 prefill）
    apaas_base_url: Optional[str] = None
    apaas_platform_tenant_id: Optional[str] = None
    apaas_env_id: Optional[int] = None
    # 绑定完整性（admin 视图标红用）
    binding_complete: bool = False
    missing_fields: list[str] = []


class TenantSwitchRequest(BaseModel):
    tenant_id: int


class ResetPasswordRequest(BaseModel):
    new_password: str


class BindApaasAccountRequest(BaseModel):
    username: str
    password: str
    apaas_tenant_id: Optional[str] = None


# ─── Helper functions ──────────────────────────────────────────────────────────

def _tenant_admin_item(t: Tenant, member_count: int) -> TenantAdminItem:
    missing: list[str] = []
    if not t.apaas_env_id:
        missing.append("apaas_env_id")
    return TenantAdminItem(
        id=t.id,
        tenant_name=t.tenant_name,
        tenant_code=t.tenant_code,
        max_applications=t.max_applications,
        max_workspaces=t.max_workspaces,
        max_components=t.max_components,
        status=t.status,
        contact_name=t.contact_name,
        contact_email=t.contact_email,
        member_count=member_count,
        created_at=t.created_at.isoformat() if t.created_at else None,
        apaas_env_id=t.apaas_env_id,
        binding_complete=not missing,
        missing_fields=missing,
    )


async def _attach_apaas_env_info(item: TenantAdminItem, db: AsyncSession) -> TenantAdminItem:
    """从 apaas_env_id 反查 PlatformEnv 拿 base_url + platform_tenant_id 塞到 item。
    给前端 prefill 用 — admin 编辑租户时不暴露 env_id 概念，只暴露这两个字段。"""
    if item.apaas_env_id:
        from app.models import PlatformEnv
        env = (
            await db.execute(select(PlatformEnv).where(PlatformEnv.id == item.apaas_env_id))
        ).scalar_one_or_none()
        if env:
            item.apaas_base_url = env.base_url
            item.apaas_platform_tenant_id = env.platform_tenant_id
    return item


async def _attach_apaas_env_info_batch(items: list[TenantAdminItem], db: AsyncSession) -> list[TenantAdminItem]:
    """批量版（list_all_tenants 用，避免 N+1）。"""
    env_ids = [i.apaas_env_id for i in items if i.apaas_env_id]
    if not env_ids:
        return items
    from app.models import PlatformEnv
    rows = (await db.execute(select(PlatformEnv).where(PlatformEnv.id.in_(env_ids)))).scalars().all()
    env_map = {e.id: e for e in rows}
    for i in items:
        if i.apaas_env_id and i.apaas_env_id in env_map:
            e = env_map[i.apaas_env_id]
            i.apaas_base_url = e.base_url
            i.apaas_platform_tenant_id = e.platform_tenant_id
    return items


# ─── Routes ────────────────────────────────────────────────────────────────────

@router.get("/tenants", response_model=list[TenantAdminItem])
async def list_all_tenants(
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Optional[str] = None,
    status: Optional[int] = None,
):
    """列出所有租户（仅平台管理员），含 member_count。

    - q：模糊匹配 tenant_name / tenant_code（不区分大小写）
    - status：1=只看启用 / 0=只看禁用 / 不传=全部
    """
    _reject_control_plane_local_admin(ctx)
    _require_platform_admin(ctx)

    from sqlalchemy import func as sql_func, or_

    stmt = select(Tenant).order_by(Tenant.created_at.desc(), Tenant.id.desc())
    if q:
        keyword = q.strip().lower()
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    sql_func.lower(Tenant.tenant_name).like(pattern),
                    sql_func.lower(Tenant.tenant_code).like(pattern),
                )
            )
    if status in (0, 1):
        stmt = stmt.where(Tenant.status == status)

    rows = (await db.execute(stmt)).scalars().all()

    counts_rows = (
        await db.execute(
            select(UserTenant.tenant_id, sql_func.count(UserTenant.id))
            .where(UserTenant.status == 1)
            .group_by(UserTenant.tenant_id)
        )
    ).all()
    count_map = {tid: cnt for tid, cnt in counts_rows}

    items = [_tenant_admin_item(t, count_map.get(t.id, 0)) for t in rows]
    return await _attach_apaas_env_info_batch(items, db)


@router.post("/tenants", response_model=TenantAdminItem)
async def create_new_tenant(
    data: TenantCreateRequest,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """新建租户（仅平台管理员）。"""
    _reject_control_plane_local_admin(ctx)
    _require_platform_admin(ctx)

    name = (data.tenant_name or "").strip()
    code = (data.tenant_code or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="租户名称不能为空")
    if not code or not all(ch.isalnum() or ch in "_-" for ch in code):
        raise HTTPException(status_code=400, detail="租户编码仅支持小写字母、数字、_、-")
    existing = (
        await db.execute(select(Tenant).where(Tenant.tenant_code == code))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"租户编码 '{code}' 已存在")

    t = Tenant(
        tenant_name=name,
        tenant_code=code,
        max_applications=data.max_applications,
        max_workspaces=data.max_workspaces,
        max_components=data.max_components,
        status=1,
        contact_name=(data.contact_name or "").strip() or None,
        contact_email=(data.contact_email or "").strip() or None,
    )
    db.add(t)
    await db.flush()  # 拿到 t.id 后顺手种默认角色 + 内置 LLM 配置
    from app.seed_data import seed_default_roles, sync_builtin_llm_configs
    await seed_default_roles(db, t.id, commit=False)
    # 给新租户种内置 LLM（否则租户成员一进 AI 搭建/聊天就提示"未配置可用模型"）
    try:
        await sync_builtin_llm_configs(db, tenant_ids=[t.id], commit=False)
    except Exception as exc:
        # 内置模型种子失败不阻断租户创建（环境变量可能没配）
        logger.warning("sync_builtin_llm_configs failed for new tenant %s: %s", t.id, exc)
    await db.commit()
    await db.refresh(t)
    return _tenant_admin_item(t, 0)


# ── 注意：/tenants/dashboard 必须在 /tenants/{tenant_id} 前定义，防止 {tenant_id} 通配先匹配 ──

@router.get("/tenants/dashboard")
async def tenant_dashboard(
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _reject_control_plane_local_admin(ctx)
    """平台总览（仅平台管理员）：所有租户的资源使用量聚合。"""
    _require_platform_admin(ctx)
    from app.tenant_quota import get_tenant_usage as _usage

    rows = (
        await db.execute(
            select(Tenant)
            .where(Tenant.status == 1)
            .order_by(Tenant.created_at.asc(), Tenant.id.asc())
        )
    ).scalars().all()

    total_apps = total_workspaces = total_components = total_members = 0

    for t in rows:
        u = await _usage(db, t.id)
        apps_used = u["applications"]["used"]
        ws_used = u["workspaces"]["used"]
        comps_used = u["components"]["used"]

        total_apps += apps_used
        total_workspaces += ws_used
        total_components += comps_used
        total_members += u["members"]

    return {
        "tenants_active": len(rows),
        "totals": {
            "applications": {"used": total_apps, "max": 0},
            "workspaces": {"used": total_workspaces, "max": 0},
            "components": {"used": total_components, "max": 0},
            "members": total_members,
        },
        "near_limit": [],
    }


@router.put("/tenants/{tenant_id}", response_model=TenantAdminItem)
async def update_tenant(
    tenant_id: int,
    data: TenantUpdateRequest,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _reject_control_plane_local_admin(ctx)
    """编辑租户基本信息（仅平台管理员）。tenant_code 一旦创建不可改。"""
    _require_platform_admin(ctx)

    t = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="租户不存在")

    if data.tenant_name is not None:
        name = data.tenant_name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="租户名称不能为空")
        t.tenant_name = name

    for field in ("max_applications", "max_workspaces", "max_components"):
        val = getattr(data, field)
        if val is not None:
            setattr(t, field, val)

    if data.contact_name is not None:
        t.contact_name = data.contact_name.strip() or None
    if data.contact_email is not None:
        t.contact_email = data.contact_email.strip() or None

    # apaas 平台绑定字段
    # admin 直接输 base_url + platform_tenant_id（不暴露 env_id）。
    # 后端帮他 maintain 一条 PlatformEnv 记录：第一次绑定时创建，后续编辑就 update。
    base_url_in = (data.apaas_base_url or "").strip() if data.apaas_base_url is not None else None
    platform_tid_in = (data.apaas_platform_tenant_id or "").strip() if data.apaas_platform_tenant_id is not None else None
    binding_env = None
    binding_changed = False
    if base_url_in is not None or platform_tid_in is not None:
        from app.models import PlatformEnv
        # 拿现有 env（如果绑定了）或新建
        env = None
        if t.apaas_env_id:
            env = (
                await db.execute(select(PlatformEnv).where(PlatformEnv.id == t.apaas_env_id))
            ).scalar_one_or_none()
        if env is None:
            env = PlatformEnv(
                tenant_id=t.id,
                env_name=f"{t.tenant_name}-默认环境",
                base_url=base_url_in or "",
                platform_tenant_id=platform_tid_in or "",
                status="disconnected",
                is_default=True,
            )
            db.add(env)
            await db.flush()
            t.apaas_env_id = env.id
            binding_changed = True
        binding_env = env
        # 已存在 env：更新 base_url + tid
        if base_url_in is not None:
            next_base_url = base_url_in.rstrip("/") if base_url_in else ""
            binding_changed = binding_changed or env.base_url != next_base_url
            env.base_url = next_base_url
        if platform_tid_in is not None:
            binding_changed = binding_changed or env.platform_tenant_id != platform_tid_in
            env.platform_tenant_id = platform_tid_in
        if binding_changed:
            # A token is tenant-bound. Never carry the previous tenant's token
            # across a rebinding, otherwise the next app query returns the old
            # tenant's applications while the env row shows the new ID.
            env.token = None
            env.status = "disconnected"

    # 高级路径：直接传 apaas_env_id（手动指定已存在的 env），UI 默认不暴露
    if data.apaas_env_id is not None and base_url_in is None and platform_tid_in is None:
        if data.apaas_env_id <= 0:
            t.apaas_env_id = None
        else:
            from app.models import PlatformEnv
            env = (
                await db.execute(select(PlatformEnv).where(PlatformEnv.id == data.apaas_env_id))
            ).scalar_one_or_none()
            if not env:
                raise HTTPException(status_code=400, detail=f"apaas_env_id={data.apaas_env_id} 不存在")
            if env.tenant_id != t.id:
                raise HTTPException(
                    status_code=400,
                    detail=f"apaas_env_id={data.apaas_env_id} 属于租户 {env.tenant_id}，不能绑定到租户 {t.id}",
                )
            t.apaas_env_id = data.apaas_env_id

    await db.commit()

    # Reuse stored credentials when a binding changed so the first /apps load
    # can reconnect without requiring a second manual login.
    if binding_changed and binding_env and binding_env.username and binding_env.password_enc:
        try:
            from app.apaas_client import APaaSClient

            password = decrypt_password(binding_env.password_enc)
            client = APaaSClient(
                base_url=binding_env.base_url,
                tenant_id=binding_env.platform_tenant_id,
            )
            login_result = await client.login(binding_env.username, password)
            token = (login_result.get("token") or "").strip()
            if token:
                binding_env.token = token
                binding_env.status = "connected"
                await db.commit()
        except Exception:
            logger.info("tenant binding reconnect failed tenant_id=%s", t.id, exc_info=True)

    await db.refresh(t)

    from sqlalchemy import func as sql_func
    cnt = (
        await db.execute(
            select(sql_func.count(UserTenant.id))
            .where(UserTenant.tenant_id == t.id, UserTenant.status == 1)
        )
    ).scalar() or 0
    return await _attach_apaas_env_info(_tenant_admin_item(t, int(cnt)), db)


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: int,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    force: bool = False,
):
    """删除租户（仅平台管理员）。

    安全规则：
    - 默认 force=false：租户内有应用/工作区/组件/成员任一时，返 409 列出残留资源数，
      要求平台管理员先清理或显式 force。
    - force=true：级联删除应用 + 组件 + 成员关系（DB 层 ON DELETE CASCADE）；
      Vibe Coding workspace 的文件系统目录不会自动删，需平台管理员后续手动清理。
    """
    _reject_control_plane_local_admin(ctx)
    _require_platform_admin(ctx)

    t = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="租户不存在")

    # 不能删除自己当前激活的租户（避免删完自己也踢出来）
    if ctx.tenant_id == tenant_id:
        raise HTTPException(
            status_code=400, detail="不能删除当前激活的租户，请先切到其他租户后再删除"
        )

    # 收集残留资源数
    from app.tenant_quota import get_tenant_usage
    usage = await get_tenant_usage(db, tenant_id)
    residual = {
        "applications": usage["applications"]["used"],
        "workspaces": usage["workspaces"]["used"],
        "components": usage["components"]["used"],
        "members": usage["members"],
    }
    has_data = any(v > 0 for v in residual.values())

    if has_data and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"租户「{t.tenant_name}」尚有数据未清理，无法直接删除",
                "residual": residual,
                "hint": "确认要级联删除请加 ?force=true 重试；workspace 文件需手动清理 _online_coding/<tenant_id>/",
            },
        )

    # 🆕 force=true 路径：手动级联删 7 张直挂 tenants 的表 + 关 FK 检查兜底子层级
    # 历史问题：原代码注释说"DB 层 ON DELETE CASCADE"但实际 7 张表 FK 全是 NO ACTION
    # （applications/platform_envs/projects/conversations/marketplace_components/
    # llm_configs/api_call_logs），直接 db.delete(t) 会被 FK 阻止抛 IntegrityError 500。
    if force:
        from sqlalchemy import text as _sql_text

        # 临时关 FK 检查（mysql 会话级）—— 兜底处理子层级 FK
        # （applications.id → application_doc_versions.app_id 等深度依赖）
        # 删完后 commit 自动结束会话，FK 检查在新会话里恢复。
        await db.execute(_sql_text("SET FOREIGN_KEY_CHECKS = 0"))
        try:
            # 直接挂 tenants 的 8 张表（model 定义里 ForeignKey("tenants.id") 但实测 mysql
            # FK 没 ondelete CASCADE，所以手动 delete）
            # 注意：user_tenants 必须含 —— 之前漏列导致 li.l.77 删 tenant 5 后留孤儿
            # 记录指向不存在的 tenant，登录时 default tenant fallback 失败陷"选择组织"页
            for table in (
                "applications",
                "platform_envs",
                "projects",
                "conversations",
                "marketplace_components",
                "llm_configs",
                "api_call_logs",
                "user_tenants",  # ← 用户与租户关联表，删租户时该用户的对应行也要清
            ):
                await db.execute(
                    _sql_text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                )

            # 删 tenant 本身（user_tenant_memberships / 其他已配 ondelete=CASCADE 的表
            # 自动跟着删；剩下的孤儿数据不影响业务因为 tenant 不存在了，但 mysql FK
            # 检查关了所以不会阻止 tenant 删除）
            await db.delete(t)
            await db.commit()
        finally:
            # 恢复 FK 检查（即使前面失败 commit/rollback 后也尽量恢复）
            # 恢复失败必须记日志：否则该 DB 会话残留 FOREIGN_KEY_CHECKS=0，
            # 后续复用会绕过外键校验造成静默数据损坏，绝不能静默吞掉。
            try:
                await db.execute(_sql_text("SET FOREIGN_KEY_CHECKS = 1"))
                await db.commit()
            except Exception as exc:
                logger.error(
                    "delete_tenant: 恢复 FOREIGN_KEY_CHECKS=1 失败 tenant_id=%s: %s",
                    tenant_id, exc,
                )
    else:
        # has_data=False 路径（租户没残留）：直接删
        await db.delete(t)
        await db.commit()

    return {"ok": True, "deleted_tenant_id": tenant_id, "residual": residual}


@router.get("/tenants/{tenant_id}/usage")
async def get_tenant_usage_endpoint(
    tenant_id: int,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """返回某租户的资源使用情况（仅平台管理员）。"""
    _reject_control_plane_local_admin(ctx)
    _require_platform_admin(ctx)
    from app.tenant_quota import get_tenant_usage as _get_usage
    return await _get_usage(db, tenant_id)


@router.put("/tenants/{tenant_id}/status", response_model=TenantAdminItem)
async def update_tenant_status(
    tenant_id: int,
    data: TenantStatusRequest,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """启用 / 禁用租户（仅平台管理员）。被禁用的租户成员仍可见但无法切入。"""
    _reject_control_plane_local_admin(ctx)
    _require_platform_admin(ctx)

    if data.status not in (0, 1):
        raise HTTPException(status_code=400, detail="status 仅支持 0 或 1")

    t = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="租户不存在")
    t.status = data.status
    await db.commit()
    await db.refresh(t)

    from sqlalchemy import func as sql_func
    cnt = (
        await db.execute(
            select(sql_func.count(UserTenant.id))
            .where(UserTenant.tenant_id == t.id, UserTenant.status == 1)
        )
    ).scalar() or 0
    return _tenant_admin_item(t, int(cnt))


@router.put("/me/default-tenant")
async def set_my_default_tenant(
    data: TenantSwitchRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """把指定租户标记为当前用户的默认租户（登录时自动落到这里）。

    用户必须是该租户的 active 成员；调用会清掉其他 membership 的 is_default。
    平台管理员若没有 membership 也允许（fallback：什么都不做，因为 platform_admin
    登录走的是 resolve_default_tenant_id_for_user，没 membership 时本身就走 fallback）。
    """
    _reject_control_plane_local_admin(ctx)
    membership = (
        await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == ctx.user.id,
                UserTenant.tenant_id == data.tenant_id,
                UserTenant.status == 1,
            )
        )
    ).scalar_one_or_none()
    if not membership:
        if not ctx.user.is_platform_admin:
            raise HTTPException(status_code=403, detail="你不是该租户的成员")
        # 平台管理员无 membership 也允许，但实际上不存数据库（platform_admin 登录靠
        # resolve_default_tenant_id_for_user 自然 fallback），这里直接返回 ok
        return {"ok": True, "tenant_id": data.tenant_id, "stored": False}

    # 清其他 default 标记
    await db.execute(
        UserTenant.__table__.update()
        .where(UserTenant.user_id == ctx.user.id, UserTenant.id != membership.id)
        .values(is_default=False)
    )
    membership.is_default = True
    await db.commit()
    return {"ok": True, "tenant_id": data.tenant_id, "stored": True}


@router.post("/users/{user_id}/apaas-binding")
async def bind_user_apaas_account(
    user_id: int,
    data: BindApaasAccountRequest,
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """给本地/Control Plane 账号绑定 aPaaS 用户与租户。

    绑定后账号仍按原 account_source 登录；aPaaS 凭据只用于租户、应用和长任务续 token。
    """
    _reject_control_plane_local_admin(ctx)
    _require_platform_admin(ctx)

    username = (data.username or "").strip()
    password = data.password or ""
    requested_tenant_id = (data.apaas_tenant_id or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="aPaaS 账号不能为空")
    if not password:
        raise HTTPException(status_code=400, detail="aPaaS 密码不能为空")
    if not (settings.apaas_base_url or "").strip():
        raise HTTPException(status_code=400, detail="未配置 aPaaS 地址")

    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    preserve_unscoped_admin = platform_admin_has_unscoped_tenant_access(target)

    backend_token, backend_payload = await _apaas_backend_login(username, password, "")
    if not backend_token:
        message = _extract_login_error_message(backend_payload) or "aPaaS 账号或密码验证失败"
        raise HTTPException(status_code=401, detail=message)

    user_info = _extract_apaas_user(backend_payload, username)
    default_item = _extract_default_tenant_item(backend_payload)
    default_tenant_id = _tenant_item_id(default_item) if default_item else ""
    switchable_items = await _apaas_switchable_tenants(backend_token, default_tenant_id)
    tenant_items = _merge_tenant_items([default_item] if default_item else [], switchable_items)

    selected_item = None
    selected_tenant_id = requested_tenant_id or default_tenant_id
    if selected_tenant_id:
        selected_item = next((item for item in tenant_items if _tenant_item_id(item) == selected_tenant_id), None)
    if not selected_item and not requested_tenant_id and tenant_items:
        selected_item = tenant_items[0]
        selected_tenant_id = _tenant_item_id(selected_item)

    selected_token = backend_token
    selected_payload = backend_payload
    if requested_tenant_id and (not selected_item or requested_tenant_id != default_tenant_id):
        selected_token, selected_payload = await _apaas_backend_login(username, password, requested_tenant_id)
        if not selected_token:
            message = _extract_login_error_message(selected_payload) or "aPaaS 账号无法登录指定租户"
            raise HTTPException(status_code=403, detail=message)
        scoped_item = _extract_default_tenant_item(selected_payload)
        if scoped_item and _tenant_item_id(scoped_item) == requested_tenant_id:
            selected_item = {**(selected_item or {}), **scoped_item}
        elif not selected_item:
            selected_item = {
                "tenantId": requested_tenant_id,
                "tenantName": requested_tenant_id,
                "tenantCode": requested_tenant_id,
                "status": 1,
            }
        selected_tenant_id = requested_tenant_id

    if not selected_item or not selected_tenant_id:
        raise HTTPException(status_code=400, detail="未获取到可绑定的 aPaaS 租户")
    if not _tenant_enabled(selected_item):
        raise HTTPException(status_code=400, detail="aPaaS 租户未启用")

    scoped_user_info = _extract_apaas_user(selected_payload, username)
    user_info = {**user_info, **scoped_user_info}
    apaas_user_id = str(
        user_info.get("id") or user_info.get("userId") or user_info.get("user_id") or ""
    ).strip() or None
    display_name = _extract_user_display_name(user_info, fallback=username)

    tenant = await _ensure_apaas_tenant(db, selected_item, username, password)
    if preserve_unscoped_admin and str(target.account_source or "").strip().lower() == "apaas":
        target.account_source = "desktop"
    target.apaas_user_id = apaas_user_id
    target.apaas_tenant_id = selected_tenant_id
    target.apaas_base_url = _normalize_apaas_origin(settings.apaas_base_url)
    target.apaas_token = selected_token
    if display_name:
        target.display_name = display_name

    await _upsert_user_credential(
        db,
        target,
        tenant,
        username,
        password,
        selected_token,
        apaas_user_id,
        selected_tenant_id,
    )
    await db.execute(
        UserTenant.__table__.update()
        .where(UserTenant.user_id == target.id)
        .values(is_default=False)
    )
    membership = await _sync_user_membership(
        db,
        target,
        tenant,
        is_default=True,
        preferred_role_codes=_apaas_membership_role_preference(
            selected_item,
            username,
            user_info,
            set(),
            False,
        ),
    )
    await db.flush()
    await db.execute(
        UserTenant.__table__.update()
        .where(
            UserTenant.user_id == target.id,
            UserTenant.tenant_id == tenant.id,
        )
        .values(is_default=True)
    )
    membership.is_default = True

    await db.commit()
    await db.refresh(target)
    memberships = await _load_user_memberships(db, [target.id])
    return _serialize_platform_user(target, memberships.get(target.id, []))


@router.post("/users/{user_id}/reset-password")
async def admin_reset_user_password(
    user_id: int,
    data: ResetPasswordRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """管理员代用户重置密码。

    权限：
    - 平台管理员：可重置任意账号（自己除外，自己改密码请走个人设置）
    - 租户管理员：只能重置当前租户的成员，且不能重置平台管理员账号（防越权）
    - 其他角色：403

    新密码限制：6-128 位。重置后旧密码立即失效，但已签发的 JWT 会在过期前继续可用。
    """
    _reject_control_plane_local_admin(ctx)
    new_pw = (data.new_password or "").strip()
    if len(new_pw) < 6 or len(new_pw) > 128:
        raise HTTPException(status_code=400, detail="密码长度需在 6-128 位之间")

    if user_id == ctx.user.id:
        raise HTTPException(status_code=400, detail="请使用个人设置修改自己的密码")

    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")

    is_platform_admin = ctx.user.is_platform_admin or ctx.tenant_role == "platform_admin"
    if is_platform_admin:
        pass  # 通过
    elif ctx.tenant_role == "tenant_admin":
        # 只能改本租户成员，且不能改平台管理员
        if target.is_platform_admin:
            raise HTTPException(status_code=403, detail="租户管理员不能重置平台管理员密码")
        membership = (
            await db.execute(
                select(UserTenant).where(
                    UserTenant.user_id == user_id,
                    UserTenant.tenant_id == ctx.tenant_id,
                    UserTenant.status == 1,
                )
            )
        ).scalar_one_or_none()
        if not membership:
            raise HTTPException(status_code=403, detail="该用户不是当前租户成员")
    else:
        raise HTTPException(status_code=403, detail="没有重置密码权限")

    target.hashed_password = get_password_hash(new_pw)
    await db.commit()
    logger.info(
        "admin_reset_password by user_id=%s tenant_id=%s on target_user_id=%s",
        ctx.user.id, ctx.tenant_id, user_id,
    )
    return {"ok": True, "user_id": user_id, "username": target.username}


@router.get("/platform-users")
async def list_platform_users(
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出全平台 active 账号（仅平台管理员），供「租户管理 → 加成员」从已有账号里选。

    返回精简：id / username / display_name / is_platform_admin。不返密码 hash。
    """
    _reject_control_plane_local_admin(ctx)
    _require_platform_admin(ctx)
    rows = (
        await db.execute(
            select(User).where(User.is_active == True).order_by(User.username.asc())
        )
    ).scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "is_platform_admin": u.is_platform_admin,
        }
        for u in rows
    ]


@router.get("/me/tenants", response_model=list[TenantOption])
async def list_my_tenants(
    ctx: Annotated[AuthContext, Depends(get_platform_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """返回当前用户可切换的租户列表（用于顶栏 dropdown）。

    普通 aPaaS 用户只返回自己的 active membership。aPaaS 平台管理员还可以切换到
    已明确绑定 PlatformEnv 的本地租户；未绑定的本地租户仍不在工作台切换范围内。
    """
    if (
        str(ctx.user.account_source or "").strip().lower() == "control_plane"
        and (
            runtime.is_desktop()
            or ctx.tenant_access_scope == "control_plane_code"
            or bool(getattr(ctx, "control_plane_tenant_id", None))
        )
    ):
        token = control_plane_access_token(ctx.user)
        if not token:
            return []
        identity = await fetch_control_plane_identity(token)
        return [
            TenantOption(
                tenant_id=str(item.get("tenant_id") or ""),
                tenant_name=str(item.get("tenant_name") or item.get("tenant_id") or ""),
                tenant_code=str(item.get("tenant_id") or ""),
            )
            for item in identity.available_tenants
            if str(item.get("tenant_id") or "").strip()
        ]
    if platform_admin_has_unscoped_tenant_access(ctx.user):
        stmt = select(Tenant).where(Tenant.status == 1)
        rows = (
            await db.execute(
                stmt.order_by(Tenant.tenant_name.asc())
            )
        ).scalars().all()
    elif ctx.user.is_platform_admin and str(ctx.user.account_source or "").strip().lower() == "apaas":
        # aPaaS platform admins can work in every local tenant that has an
        # explicit platform binding. Membership is not required for these
        # synchronized tenant records.
        from app.models import PlatformEnv
        membership_rows = (
            await db.execute(
                select(Tenant)
                .join(UserTenant, UserTenant.tenant_id == Tenant.id)
                .where(
                    UserTenant.user_id == ctx.user.id,
                    UserTenant.status == 1,
                    Tenant.status == 1,
                )
            )
        ).scalars().all()
        bound_rows = (
            await db.execute(
                select(Tenant)
                .join(PlatformEnv, PlatformEnv.tenant_id == Tenant.id)
                .where(
                    Tenant.status == 1,
                    PlatformEnv.platform_tenant_id.is_not(None),
                    PlatformEnv.platform_tenant_id != "",
                )
                .order_by(Tenant.tenant_name.asc())
            )
        ).scalars().unique().all()
        rows_by_id = {row.id: row for row in [*membership_rows, *bound_rows]}
        rows = sorted(rows_by_id.values(), key=lambda row: (row.tenant_name or "", row.id))
    else:
        rows = (
            await db.execute(
                select(Tenant)
                .join(UserTenant, UserTenant.tenant_id == Tenant.id)
                .where(
                    UserTenant.user_id == ctx.user.id,
                    UserTenant.status == 1,
                    Tenant.status == 1,
                )
                .order_by(UserTenant.is_default.desc(), Tenant.tenant_name.asc())
            )
        ).scalars().all()
    options = await _tenant_options_with_durable_public_ids(db, rows)
    await db.commit()
    return options


@router.get("/users")
async def list_users(ctx: Annotated[AuthContext, Depends(get_auth_context)], db: Annotated[AsyncSession, Depends(get_db)]):
    """获取同租户下的所有用户（用于团队成员选择）"""
    if is_control_plane_context(ctx):
        return []
    if ctx.tenant_id:
        result = await db.execute(
            select(User.id, User.username, User.display_name)
            .join(UserTenant, User.id == UserTenant.user_id)
            .where(
                UserTenant.tenant_id == ctx.tenant_id,
                UserTenant.status == 1,
                User.is_active == True,
            )
        )
    else:
        result = await db.execute(select(User.id, User.username, User.display_name).where(User.is_active == True))
    return [{"id": row[0], "username": row[1], "display_name": row[2]} for row in result.fetchall()]


@router.get("/tenant-roles")
async def list_tenant_roles(
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _reject_control_plane_local_admin(ctx)
    if ctx.tenant_role == "platform_admin":
        return [
            {
                "id": -1,
                "role_code": "normal_user",
                "role_name": "普通账号",
                "is_system": True,
                "permissions": {},
            },
            {
                "id": 0,
                "role_code": "platform_admin",
                "role_name": "平台超级管理员",
                "is_system": True,
                "permissions": {"*": True},
            },
        ]

    result = await db.execute(
        select(Role).where(Role.tenant_id == ctx.tenant_id).order_by(Role.is_system.desc(), Role.created_at.asc())
    )
    roles = result.scalars().all()
    return [
        {
            "id": role.id,
            "role_code": role.role_code,
            "role_name": role.role_name,
            "is_system": role.is_system,
            "permissions": role.permissions or {},
        }
        for role in roles
    ]


@router.get("/tenant-users")
async def list_tenant_users(
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _reject_control_plane_local_admin(ctx)
    if ctx.tenant_role == "platform_admin":
        result = await db.execute(select(User).order_by(User.created_at.asc(), User.id.asc()))
        users = result.scalars().all()
        memberships = await _load_user_memberships(db, [user.id for user in users])
        return [_serialize_platform_user(user, memberships.get(user.id, [])) for user in users]

    result = await db.execute(
        select(UserTenant, User, Tenant, Role)
        .join(User, User.id == UserTenant.user_id)
        .join(Tenant, Tenant.id == UserTenant.tenant_id)
        .outerjoin(Role, Role.id == UserTenant.role_id)
        .where(UserTenant.tenant_id == ctx.tenant_id)
        .order_by(UserTenant.joined_at.asc(), User.created_at.asc())
    )
    rows = result.all()
    return [_serialize_tenant_user(user, membership, role, tenant) for membership, user, tenant, role in rows]


@router.post("/tenant-users/invite")
async def invite_tenant_user(
    req: InviteTenantUserRequest,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _reject_control_plane_local_admin(ctx)
    from sqlalchemy.exc import IntegrityError
    username = (req.username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")

    role_code = (req.role_code or "R_developer").strip() or "R_developer"
    if ctx.tenant_role == "platform_admin":
        if role_code not in ("platform_admin", "normal_user"):
            raise HTTPException(status_code=400, detail="平台管理员只能创建平台超级管理员或普通账号")
        user_result = await db.execute(select(User).where(User.username == username))
        user = user_result.scalar_one_or_none()
        if not user:
            if not req.password:
                raise HTTPException(status_code=400, detail="用户不存在，请提供初始密码创建账号")
            user = User(
                username=username,
                hashed_password=get_password_hash(req.password),
                account_source="desktop",
                is_platform_admin=role_code == "platform_admin",
            )
            db.add(user)
            await db.flush()
        else:
            if role_code == "platform_admin":
                user.is_platform_admin = True
        user.is_active = True

        # 可选：把账号同时加到指定租户（避免"建出来但不属于任何组织"的孤儿账号）
        if req.tenant_id:
            target_tenant = (
                await db.execute(select(Tenant).where(Tenant.id == req.tenant_id))
            ).scalar_one_or_none()
            if not target_tenant:
                raise HTTPException(status_code=404, detail="指定的租户不存在")
            # 找该租户的默认开发者角色（兼容老 init_db 的 R_tenant_admin 和新 seed 的 R_developer）
            # 注意：tenant seed 会同时建 R_developer + R_tenant_admin + R_viewer 三个角色，
            # 老代码用 .scalar_one_or_none() 撞 MultipleResultsFound 500。
            # 改 .scalars().first() —— order_by R_developer < R_tenant_admin < admin 字母序优先开发者角色。
            tenant_role = (
                await db.execute(
                    select(Role)
                    .where(Role.tenant_id == req.tenant_id)
                    .where(Role.role_code.in_(["R_developer", "R_tenant_admin", "admin"]))
                    .order_by(Role.role_code.asc())
                )
            ).scalars().first()
            if tenant_role:
                existing = (
                    await db.execute(
                        select(UserTenant).where(
                            UserTenant.user_id == user.id,
                            UserTenant.tenant_id == req.tenant_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.status = 1
                    existing.role_id = tenant_role.id
                else:
                    has_default = (
                        await db.execute(
                            select(UserTenant).where(
                                UserTenant.user_id == user.id, UserTenant.status == 1
                            )
                        )
                    ).scalars().first() is not None
                    db.add(
                        UserTenant(
                            user_id=user.id,
                            tenant_id=req.tenant_id,
                            role_id=tenant_role.id,
                            is_default=not has_default,
                            status=1,
                        )
                    )

        await db.commit()
        await db.refresh(user)
        memberships = await _load_user_memberships(db, [user.id])
        return _serialize_platform_user(user, memberships.get(user.id, []))

    role_result = await db.execute(
        select(Role).where(
            Role.tenant_id == ctx.tenant_id,
            Role.role_code == role_code,
        )
    )
    role = role_result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    user_result = await db.execute(select(User).where(User.username == username))
    user = user_result.scalar_one_or_none()
    if not user:
        if not req.password:
            raise HTTPException(status_code=400, detail="用户不存在，请提供初始密码创建账号")
        user = User(
            username=username,
            hashed_password=get_password_hash(req.password),
        )
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            # 并发邀请：两请求都过了上面的 null check 都去建同名用户，
            # 第二个 flush 撞 username UNIQUE 约束。回滚后重查已被对方建好的用户，
            # 继续走下面正常的 membership 关联流程（幂等）。
            await db.rollback()
            user_result = await db.execute(select(User).where(User.username == username))
            user = user_result.scalar_one_or_none()
            if not user:
                # 撞约束却又查不到 —— 不是同名冲突，按冲突原样上报
                raise HTTPException(status_code=409, detail="创建用户冲突，请重试")
            # rollback 已让 role 实例过期，重查避免后续访问 role.id 触发异步 refresh 报错
            role_result = await db.execute(
                select(Role).where(
                    Role.tenant_id == ctx.tenant_id,
                    Role.role_code == role_code,
                )
            )
            role = role_result.scalar_one_or_none()
            if not role:
                raise HTTPException(status_code=404, detail="角色不存在")

    membership_result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == user.id,
            UserTenant.tenant_id == ctx.tenant_id,
        )
    )
    membership = membership_result.scalar_one_or_none()
    if membership:
        membership.status = 1
        membership.role_id = role.id
    else:
        default_result = await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == user.id,
                UserTenant.status == 1,
            )
        )
        existing_memberships = default_result.scalars().all()
        membership = UserTenant(
            user_id=user.id,
            tenant_id=ctx.tenant_id,
            role_id=role.id,
            is_default=not existing_memberships,
            status=1,
        )
        db.add(membership)

    await db.commit()
    await db.refresh(membership)
    return _serialize_tenant_user(user, membership, role)


@router.put("/tenant-users/{user_id}/status")
async def update_tenant_user_status(
    user_id: int,
    req: UpdateTenantUserStatusRequest,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _reject_control_plane_local_admin(ctx)
    if req.status not in (0, 1):
        raise HTTPException(status_code=400, detail="status 只能是 0 或 1")
    if user_id == ctx.user.id:
        raise HTTPException(status_code=400, detail="不能在当前会话里禁用自己")

    if ctx.tenant_role == "platform_admin":
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        user.is_active = req.status == 1
        await db.commit()
        await db.refresh(user)
        memberships = await _load_user_memberships(db, [user.id])
        return _serialize_platform_user(user, memberships.get(user.id, []))

    result = await db.execute(
        select(UserTenant, User, Role)
        .join(User, User.id == UserTenant.user_id)
        .outerjoin(Role, Role.id == UserTenant.role_id)
        .where(
            UserTenant.tenant_id == ctx.tenant_id,
            UserTenant.user_id == user_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="租户成员不存在")

    membership, user, role = row
    membership.status = req.status
    await db.commit()
    await db.refresh(membership)
    return _serialize_tenant_user(user, membership, role)


@router.put("/tenant-users/{user_id}/role")
async def update_tenant_user_role(
    user_id: int,
    req: UpdateTenantUserRoleRequest,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _reject_control_plane_local_admin(ctx)
    if ctx.tenant_role == "platform_admin":
        if req.role_code not in ("platform_admin", "normal_user"):
            raise HTTPException(status_code=400, detail="平台管理员只能切换平台超级管理员或普通账号")
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if user_id == ctx.user.id and req.role_code != "platform_admin":
            raise HTTPException(status_code=400, detail="不能取消自己的平台超级管理员权限")
        user.is_platform_admin = req.role_code == "platform_admin"
        await db.commit()
        await db.refresh(user)
        memberships = await _load_user_memberships(db, [user.id])
        return _serialize_platform_user(user, memberships.get(user.id, []))

    membership_result = await db.execute(
        select(UserTenant, User)
        .join(User, User.id == UserTenant.user_id)
        .where(
            UserTenant.tenant_id == ctx.tenant_id,
            UserTenant.user_id == user_id,
        )
    )
    membership_row = membership_result.one_or_none()
    if not membership_row:
        raise HTTPException(status_code=404, detail="租户成员不存在")

    membership, user = membership_row
    role_result = await db.execute(
        select(Role).where(
            Role.tenant_id == ctx.tenant_id,
            Role.role_code == req.role_code,
        )
    )
    role = role_result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    if user_id == ctx.user.id and role.role_code not in ("R_tenant_admin", "admin"):
        raise HTTPException(status_code=400, detail="不能把自己降级为非管理员")

    membership.role_id = role.id
    await db.commit()
    await db.refresh(membership)
    return _serialize_tenant_user(user, membership, role)


@router.get("/me", response_model=UserInfo)
async def get_me(ctx: Annotated[AuthContext, Depends(get_platform_auth_context)], db: Annotated[AsyncSession, Depends(get_db)]):
    # 获取租户信息
    tenant_name = None
    tenant_public_id = None
    if ctx.tenant_id:
        result = await db.execute(select(Tenant).where(Tenant.id == ctx.tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant:
            tenant_name = tenant.tenant_name
            needs_public_id_commit = tenant.public_id is None
            tenant_public_id = await ensure_tenant_public_id(db, tenant)
            if needs_public_id_commit:
                await db.commit()

    is_desktop_control_plane_account = (
        ctx.user.account_source == "control_plane"
        and runtime.is_desktop()
        and bool((getattr(ctx, "control_plane_tenant_id", None) or ctx.user.coding_tenant_id or "").strip())
    )
    is_control_plane_account = ctx.user.account_source == "control_plane"
    control_plane_tenant_id = (
        getattr(ctx, "control_plane_tenant_id", None)
        or (ctx.user.coding_tenant_id or "").strip()
        or None
    )
    control_plane_tenant_name = getattr(ctx, "control_plane_tenant_name", None)
    control_plane_permissions = ctx.org_permissions or {}
    if is_desktop_control_plane_account:
        token = control_plane_access_token(ctx.user)
        if token:
            try:
                identity = await fetch_control_plane_identity(token)
                control_plane_tenant_id = control_plane_tenant_id or identity.tenant_id
                control_plane_tenant_name = control_plane_tenant_name or identity.tenant_name
                control_plane_permissions = identity.org_permissions or control_plane_permissions
            except HTTPException:
                pass

    return UserInfo(
        id=ctx.user.id,
        username=ctx.user.username,
        display_name=ctx.user.display_name,
        is_active=ctx.user.is_active,
        is_platform_admin=ctx.user.is_platform_admin,
        created_at=ctx.user.created_at,
        tenant_id=(
            control_plane_tenant_id
            if is_desktop_control_plane_account
            else (ctx.tenant_id if ctx.tenant_id else None)
        ),
        tenant_name=(
            control_plane_tenant_name
            if is_desktop_control_plane_account
            else tenant_name
        ),
        tenant_public_id=tenant_public_id,
        control_plane_tenant_id=(
            control_plane_tenant_id if is_control_plane_account else None
        ),
        control_plane_tenant_name=(
            control_plane_tenant_name if is_control_plane_account else None
        ),
        tenant_role=ctx.tenant_role,
        org_permissions=control_plane_permissions,
        account_source=ctx.user.account_source,
        tenant_authority="control_plane" if is_control_plane_account else "builder",
    )
