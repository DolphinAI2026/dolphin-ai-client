import logging
import re
from datetime import datetime
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError
from app.database import get_db
from app.models import APaaSPlatformCredential, APaaSUserCredential, PlatformEnv, User
from app.models.tenant import Tenant, UserTenant, Role
from app.schemas import (
    UserLogin, Token, UserInfo,
    LoginResponse, TenantOption, TenantSelectRequest
)
from app.auth import verify_password, get_password_hash, create_access_token, create_selection_token
from app.crypto import encrypt_password
from app.deps import (
    AuthContext,
    get_auth_context,
    require_tenant_admin,
    resolve_default_tenant_id_for_user,
)
from app.config import settings
from app.error_messages import SELECT_TOKEN_INVALID, SELECT_TOKEN_EXPIRED
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


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


def _serialize_tenant_user(user: User, membership: UserTenant, role: Optional[Role], tenant: Optional[Tenant] = None) -> dict:
    tenant_role, role_name, permissions = _resolve_tenant_role(role)
    return {
        "id": user.id,
        "username": user.username,
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


def _normalize_apaas_origin(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/backend"):
        base = base[:-len("/backend")]
    return base


def _is_allowed_apaas_base_url(base_url: Optional[str], allowlist: list[str]) -> bool:
    """SSRF 防护: 校验用户传入的 apaas_base_url 是否在白名单内。

    背景: /auth/exchange-apaas-token 无鉴权(SSO 换 token 设计上须允许未登录调), 却接受
    用户任意 apaas_base_url 去发请求 → 未授权 SSRF。端点不能加登录, 故用 origin 白名单兜底:
    传入 URL 归一化后的 origin(scheme://host:port) 必须匹配某条已配置 base_url 的 origin。
    按 origin 比对(非整串前缀)防 host 子串/前缀绕过(如 apaas.x.cn.evil.com / evil.com/apaas.x.cn)。
    白名单为空 → 拒绝一切, 不留口子。
    """
    if not base_url:
        return False
    from urllib.parse import urlparse

    def _origin(u: str) -> Optional[tuple]:
        try:
            p = urlparse((u or "").strip())
        except Exception:
            return None
        if not p.scheme or not p.netloc:
            return None
        return (p.scheme.lower(), p.hostname.lower() if p.hostname else "", p.port)

    target = _origin(base_url)
    if target is None:
        return False
    for allowed in allowlist or []:
        if _origin(allowed) == target:
            return True
    return False


def _normalize_tenant_code(value: str, fallback: str) -> str:
    code = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip().lower()).strip("-_")
    if not code:
        code = f"apaas-{fallback[-8:]}" if fallback else "apaas"
    return code[:60]


def _extract_apaas_token(payload: object) -> Optional[str]:
    if isinstance(payload, dict):
        for key in ("xdaptoken", "xdapToken", "token", "accessToken", "access_token"):
            value = payload.get(key)
            if isinstance(value, str) and value.count(".") >= 1:
                return value
        for value in payload.values():
            found = _extract_apaas_token(value)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _extract_apaas_token(item)
            if found:
                return found
    return None


def _decode_jwt_exp(token: Optional[str]) -> Optional[datetime]:
    if not token:
        return None
    try:
        from app.auth import decode_token
        payload = decode_token(token)
        exp = payload.get("exp")
        return datetime.utcfromtimestamp(int(exp)) if exp else None
    except Exception:
        return None


def _extract_apaas_user(payload: object, username: str) -> dict:
    if isinstance(payload, dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        user = data.get("user") if isinstance(data.get("user"), dict) else data.get("userInfo")
        if isinstance(user, dict):
            return user
        for value in data.values():
            found = _extract_apaas_user(value, username)
            if found:
                return found
    return {"account": username, "username": username}


def _tenant_item_id(item: object) -> str:
    if not isinstance(item, dict):
        return ""
    value = (
        item.get("tenantId")
        or item.get("tenant_id")
        or item.get("id")
        or item.get("tenantID")
    )
    return str(value or "").strip()


def _tenant_item_name(item: object, fallback: str) -> str:
    if not isinstance(item, dict):
        return fallback
    return str(
        item.get("tenantName")
        or item.get("tenant_name")
        or item.get("name")
        or item.get("displayName")
        or fallback
    ).strip()


def _tenant_item_code(item: object, fallback: str) -> str:
    if not isinstance(item, dict):
        return _normalize_tenant_code(fallback, fallback)
    raw = item.get("tenantCode") or item.get("tenant_code") or item.get("code") or ""
    return _normalize_tenant_code(str(raw or ""), fallback)


def _tenant_enabled(item: object) -> bool:
    if not isinstance(item, dict):
        return True
    value = item.get("status", item.get("state", item.get("enabled", item.get("enable"))))
    if value in (None, ""):
        return True
    if value in (1, "1", True):
        return True
    text = str(value).strip().lower()
    return text in {"enable", "enabled", "active", "normal", "启用"}


def _tenant_admin_matches(item: object, username: str, user_info: dict) -> bool:
    if not isinstance(item, dict):
        return False
    admin_list = item.get("adminList") or item.get("admins") or item.get("tenantAdmins") or []
    if not isinstance(admin_list, list):
        return False
    username_text = str(username or "").strip().lower()
    apaas_uid = str(user_info.get("id") or user_info.get("userId") or user_info.get("user_id") or "").strip()
    for admin in admin_list:
        if not isinstance(admin, dict):
            continue
        candidates = [
            admin.get("account"),
            admin.get("username"),
            admin.get("name"),
            admin.get("mobile"),
            admin.get("phone"),
        ]
        ids = [admin.get("id"), admin.get("userId"), admin.get("user_id")]
        if username_text and any(str(value or "").strip().lower() == username_text for value in candidates):
            return True
        if apaas_uid and any(str(value or "").strip() == apaas_uid for value in ids):
            return True
    return False


def _extract_tenant_items(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict) and _tenant_item_id(item)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    candidates = [data, payload]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict) and _tenant_item_id(item)]
        if isinstance(candidate, dict):
            for key in ("tenantInfos", "tenants", "tenantList", "table", "list", "records", "rows", "items", "data"):
                value = candidate.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict) and _tenant_item_id(item)]
                if isinstance(value, dict):
                    nested = _extract_tenant_items(value)
                    if nested:
                        return nested
    return []


def _find_tenant_item_by_id(payload: object, tenant_id: str) -> Optional[dict]:
    if not tenant_id:
        return None
    for item in _extract_tenant_items(payload):
        if _tenant_item_id(item) == tenant_id:
            return item
    return None


def _extract_default_tenant_id(payload: object) -> str:
    if isinstance(payload, dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        for key in (
            "defaultTenantId",
            "default_tenant_id",
            "currentTenantId",
            "current_tenant_id",
            "tenantId",
            "tenant_id",
            "xdaptenantid",
        ):
            value = data.get(key)
            if value not in (None, ""):
                return str(value).strip()
        for key in ("defaultTenant", "currentTenant", "tenant", "tenantInfo"):
            value = data.get(key)
            tid = _tenant_item_id(value)
            if tid:
                return tid
        for value in data.values():
            tid = _extract_default_tenant_id(value)
            if tid:
                return tid
    if isinstance(payload, list):
        for item in payload:
            tid = _extract_default_tenant_id(item)
            if tid:
                return tid
    return ""


def _extract_default_tenant_item(payload: object) -> Optional[dict]:
    tenant_id = _extract_default_tenant_id(payload)
    if not tenant_id:
        items = _extract_tenant_items(payload)
        return items[0] if len(items) == 1 else None
    found = _find_tenant_item_by_id(payload, tenant_id)
    return found or {"tenantId": tenant_id, "tenantName": tenant_id, "tenantCode": tenant_id}


async def _apaas_platform_login(username: str, password: str) -> tuple[Optional[str], dict]:
    """Try aPaaS platform-admin login. Success means platform admin."""
    from app.routes import mcp_platform
    import httpx
    import time

    base_url = _normalize_apaas_origin(settings.apaas_base_url)
    rsa_public_key = await mcp_platform._get_apaas_rsa_public_key(base_url)
    ts = str(int(time.time() * 1000))
    url = f"{mcp_platform._api_base(base_url)}/xdap-admin/platform/apaasSystemAdmin/login?timestamp={ts}"
    headers = mcp_platform._headers(base_url, tenant_id="", rsa_public_key=rsa_public_key)
    headers["referer"] = f"{base_url}/platform/account/login"
    body = {
        "type": "account",
        "account": username,
        "password": mcp_platform._encrypt_apaas_password(password, rsa_public_key),
        "securityCode": "",
    }
    async with httpx.AsyncClient(timeout=20, verify=False) as client:
        resp = await client.post(url, headers=headers, json=body)
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}
    if not resp.is_success:
        return None, payload if isinstance(payload, dict) else {}
    return _extract_apaas_token(payload), payload if isinstance(payload, dict) else {}


async def _apaas_backend_login(username: str, password: str, tenant_id: str = "") -> tuple[Optional[str], dict]:
    """Try aPaaS manage-login. With empty tenant_id, some aPaaS versions return selectable tenants."""
    from app.routes import mcp_platform
    import httpx
    import time

    base_url = _normalize_apaas_origin(settings.apaas_base_url)
    rsa_public_key = await mcp_platform._get_apaas_rsa_public_key(base_url)
    ts = str(int(time.time() * 1000))
    url = f"{mcp_platform._api_base(base_url)}/xdap-admin/user/login?timestamp={ts}"
    headers = mcp_platform._headers(base_url, tenant_id=tenant_id, rsa_public_key=rsa_public_key)
    headers["referer"] = f"{base_url}/platform/account/login"
    body = {
        "type": "account",
        "account": username,
        "password": mcp_platform._encrypt_apaas_password(password, rsa_public_key),
        "tenantId": tenant_id,
        "loginType": "MANAGE",
        "securityCode": "",
    }
    async with httpx.AsyncClient(timeout=20, verify=False) as client:
        resp = await client.post(url, headers=headers, json=body)
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}
    if not resp.is_success:
        return None, payload if isinstance(payload, dict) else {}
    return _extract_apaas_token(payload), payload if isinstance(payload, dict) else {}


async def _apaas_all_tenants(platform_token: str) -> list[dict]:
    from app.routes import mcp_platform
    import httpx
    import time

    base_url = _normalize_apaas_origin(settings.apaas_base_url)
    rsa_public_key = await mcp_platform._get_apaas_rsa_public_key(base_url)
    ts = str(int(time.time() * 1000))
    url = f"{mcp_platform._api_base(base_url)}/xdap-admin/platform/query/tenantList?timestamp={ts}"
    headers = mcp_platform._headers(base_url, token=platform_token, rsa_public_key=rsa_public_key)
    async with httpx.AsyncClient(timeout=20, verify=False) as client:
        resp = await client.post(url, headers=headers, json={"page": 1, "pageSize": 500, "keyword": ""})
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}
    if not resp.is_success:
        return []
    return _extract_tenant_items(payload)


async def _apaas_switchable_tenants(backend_token: str, default_tenant_id: str) -> list[dict]:
    from app.routes import mcp_platform
    import httpx
    import time

    if not backend_token or not default_tenant_id:
        return []
    base_url = _normalize_apaas_origin(settings.apaas_base_url)
    rsa_public_key = await mcp_platform._get_apaas_rsa_public_key(base_url)
    ts = str(int(time.time() * 1000))
    url = f"{mcp_platform._api_base(base_url)}/xdap-app/tenant/query/adminTenantListByUser?timestamp={ts}"
    headers = mcp_platform._headers(
        base_url,
        token=backend_token,
        tenant_id=default_tenant_id,
        rsa_public_key=rsa_public_key,
    )
    headers["referer"] = f"{base_url}/platform/{default_tenant_id}/admin/data-dictionary"
    async with httpx.AsyncClient(timeout=20, verify=False) as client:
        resp = await client.get(url, headers=headers)
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}
    if not resp.is_success:
        return []
    return _extract_tenant_items(payload)


def _merge_tenant_items(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    order: list[str] = []
    for item in primary + secondary:
        tid = _tenant_item_id(item)
        if not tid:
            continue
        if tid not in merged:
            order.append(tid)
            merged[tid] = item
        else:
            merged[tid] = {**merged[tid], **item}
    return [merged[tid] for tid in order]


async def _ensure_apaas_tenant(db: AsyncSession, item: dict) -> Tenant:
    platform_tid = _tenant_item_id(item)
    if not platform_tid:
        raise HTTPException(status_code=400, detail="aPaaS 租户缺 tenantId")
    name = _tenant_item_name(item, platform_tid)
    code = _tenant_item_code(item, platform_tid)
    tenant = (
        await db.execute(select(Tenant).where(Tenant.apaas_tenant_id_str == platform_tid))
    ).scalar_one_or_none()
    if not tenant:
        tenant = (await db.execute(select(Tenant).where(Tenant.tenant_code == code))).scalar_one_or_none()
        if tenant and not tenant.apaas_tenant_id_str:
            tenant.apaas_tenant_id_str = platform_tid
    if not tenant:
        base_code = code
        suffix = 2
        while (await db.execute(select(Tenant).where(Tenant.tenant_code == code))).scalar_one_or_none():
            marker = f"-{suffix}"
            code = f"{base_code[:60-len(marker)]}{marker}"
            suffix += 1
        tenant = Tenant(
            tenant_name=name,
            tenant_code=code,
            status=1 if _tenant_enabled(item) else 0,
            apaas_tenant_id_str=platform_tid,
        )
        db.add(tenant)
        await db.flush()
        from app.seed_data import seed_default_roles, sync_builtin_llm_configs
        await seed_default_roles(db, tenant.id, commit=False)
        try:
            await sync_builtin_llm_configs(db, tenant_ids=[tenant.id], commit=False)
        except Exception as exc:
            logger.warning("sync builtin llm skipped for apaas tenant %s: %s", tenant.id, exc)
    else:
        tenant.tenant_name = name
        tenant.status = 1 if _tenant_enabled(item) else 0

    env = None
    if tenant.apaas_env_id:
        env = (await db.execute(select(PlatformEnv).where(PlatformEnv.id == tenant.apaas_env_id))).scalar_one_or_none()
    if not env:
        env = (
            await db.execute(
                select(PlatformEnv).where(
                    PlatformEnv.tenant_id == tenant.id,
                    PlatformEnv.platform_tenant_id == platform_tid,
                )
            )
        ).scalar_one_or_none()
    if not env:
        alias = _normalize_tenant_code(code, platform_tid)
        if (await db.execute(select(PlatformEnv).where(PlatformEnv.alias == alias))).scalar_one_or_none():
            alias = None
        env = PlatformEnv(
            tenant_id=tenant.id,
            env_name=name,
            alias=alias,
            # 存 API base（含 /backend）— APaaSClient 用法是 base_url + "/xdap-app/..."，
            # _normalize_apaas_origin 会 strip /backend 拿 origin，不适合 PlatformEnv.base_url
            base_url=(settings.apaas_base_url or "").rstrip("/"),
            platform_tenant_id=platform_tid,
            is_default=True,
            status="connected",
        )
        db.add(env)
        await db.flush()
        tenant.apaas_env_id = env.id
    else:
        env.env_name = name
        env.base_url = (settings.apaas_base_url or "").rstrip("/")
        env.platform_tenant_id = platform_tid
        env.is_default = True
    return tenant


async def _ensure_apaas_user(db: AsyncSession, username: str, password: str, user_info: dict, is_platform_admin: bool) -> User:
    apaas_uid = str(user_info.get("id") or user_info.get("userId") or user_info.get("user_id") or "").strip() or None
    user = None
    if apaas_uid:
        user = (await db.execute(select(User).where(User.apaas_user_id == apaas_uid))).scalar_one_or_none()
    if not user:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if not user:
        user = User(
            username=username,
            hashed_password=get_password_hash(password),
            apaas_user_id=apaas_uid,
            is_platform_admin=is_platform_admin,
            is_active=True,
        )
        db.add(user)
        await db.flush()
    else:
        user.username = username
        user.hashed_password = get_password_hash(password)
        if apaas_uid:
            user.apaas_user_id = apaas_uid
        user.is_platform_admin = is_platform_admin
        user.is_active = True
    user.apaas_base_url = _normalize_apaas_origin(settings.apaas_base_url)
    return user


async def _upsert_platform_credential(db: AsyncSession, user: User, username: str, password: str, token: str) -> None:
    base_url = _normalize_apaas_origin(settings.apaas_base_url)
    row = (
        await db.execute(
            select(APaaSPlatformCredential).where(
                APaaSPlatformCredential.user_id == user.id,
                APaaSPlatformCredential.base_url == base_url,
                APaaSPlatformCredential.account == username,
            )
        )
    ).scalar_one_or_none()
    if not row:
        row = APaaSPlatformCredential(user_id=user.id, base_url=base_url, account=username, password_enc=encrypt_password(password))
        db.add(row)
    else:
        row.password_enc = encrypt_password(password)
    row.token = token
    row.token_expire_at = _decode_jwt_exp(token)
    row.status = "connected"
    row.last_login_at = datetime.utcnow()
    row.last_error = None


async def _upsert_user_credential(
    db: AsyncSession,
    user: User,
    tenant: Tenant,
    username: str,
    password: str,
    token: str,
    apaas_user_id: Optional[str],
    apaas_tenant_id: str,
) -> None:
    row = (
        await db.execute(
            select(APaaSUserCredential).where(
                APaaSUserCredential.user_id == user.id,
                APaaSUserCredential.local_tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        row = APaaSUserCredential(
            user_id=user.id,
            local_tenant_id=tenant.id,
            apaas_tenant_id=apaas_tenant_id,
            base_url=_normalize_apaas_origin(settings.apaas_base_url),
            account=username,
            password_enc=encrypt_password(password),
        )
        db.add(row)
    else:
        row.password_enc = encrypt_password(password)
    row.apaas_user_id = apaas_user_id
    row.apaas_tenant_id = apaas_tenant_id
    row.base_url = _normalize_apaas_origin(settings.apaas_base_url)
    row.account = username
    row.token = token
    row.token_expire_at = _decode_jwt_exp(token)
    row.status = "connected"
    row.last_login_at = datetime.utcnow()
    row.last_error = None


async def _sync_user_membership(db: AsyncSession, user: User, tenant: Tenant, is_default: bool) -> UserTenant:
    role = (
        await db.execute(
            select(Role)
            .where(Role.tenant_id == tenant.id)
            .where(Role.role_code.in_(["R_developer", "R_tenant_admin", "admin"]))
            .order_by(Role.role_code.asc())
        )
    ).scalars().first()
    membership = (
        await db.execute(
            select(UserTenant).where(UserTenant.user_id == user.id, UserTenant.tenant_id == tenant.id)
        )
    ).scalar_one_or_none()
    if membership:
        membership.status = 1 if tenant.status == 1 else 0
        if role:
            membership.role_id = role.id
    else:
        membership = UserTenant(
            user_id=user.id,
            tenant_id=tenant.id,
            role_id=role.id if role else None,
            status=1 if tenant.status == 1 else 0,
            is_default=is_default,
        )
        db.add(membership)
    if is_default:
        await db.execute(
            UserTenant.__table__.update()
            .where(UserTenant.user_id == user.id)
            .values(is_default=False)
        )
        membership.is_default = True
    return membership


async def _try_apaas_login_flow(user_data: UserLogin, db: AsyncSession) -> Optional[LoginResponse]:
    """aPaaS authoritative login flow.

    Returns None when aPaaS cannot authenticate the user, letting the legacy
    local login path work as a development fallback.
    """
    username = user_data.username.strip()
    password = user_data.password
    if not username or not password or not settings.apaas_base_url:
        return None

    platform_token, platform_payload = await _apaas_platform_login(username, password)
    is_platform_admin = bool(platform_token)

    backend_token, backend_payload = await _apaas_backend_login(username, password, "")
    default_tenant_item = _extract_default_tenant_item(backend_payload) if backend_token else None
    default_tenant_id = _tenant_item_id(default_tenant_item) if default_tenant_item else ""
    has_backend_identity = bool(backend_token and default_tenant_id)

    if not has_backend_identity and not is_platform_admin:
        return None

    all_tenants = await _apaas_all_tenants(platform_token) if platform_token else []
    if all_tenants:
        for item in all_tenants:
            try:
                await _ensure_apaas_tenant(db, item)
            except Exception as exc:
                logger.warning("sync apaas tenant skipped: %s", exc)
    all_by_id = {_tenant_item_id(item): item for item in all_tenants if _tenant_item_id(item)}
    if default_tenant_item and default_tenant_id in all_by_id:
        default_tenant_item = {**default_tenant_item, **all_by_id[default_tenant_id]}
        if str(default_tenant_item.get("tenantName") or "") == default_tenant_id and default_tenant_item.get("name"):
            default_tenant_item["tenantName"] = default_tenant_item["name"]

    user_info = _extract_apaas_user(backend_payload or platform_payload, username)

    switchable_items: list[dict] = []
    if has_backend_identity and not is_platform_admin:
        switchable_items = await _apaas_switchable_tenants(backend_token, default_tenant_id)

    if has_backend_identity:
        if is_platform_admin:
            # 平台管理员能切到所有 aPaaS 同步进来的租户，跟 aPaaS 平台原生行为对齐
            # （aPaaS 那边 admin 在租户切换下拉里能看到所有租户）
            available_items = _merge_tenant_items(
                [default_tenant_item] if default_tenant_item else [],
                all_tenants,
            )
        else:
            available_items = _merge_tenant_items(
                [default_tenant_item] if default_tenant_item else [],
                switchable_items,
            )
        available_items = [item for item in available_items if _tenant_enabled(item)]
    else:
        available_items = []

    user = await _ensure_apaas_user(db, username, password, user_info, is_platform_admin)
    if platform_token:
        await _upsert_platform_credential(db, user, username, password, platform_token)

    local_tenants: list[Tenant] = []
    for idx, item in enumerate(available_items):
        tenant = await _ensure_apaas_tenant(db, item)
        local_tenants.append(tenant)
        if backend_token:
            user.apaas_token = backend_token
            user.apaas_tenant_id = tenant.apaas_tenant_id_str
            await _upsert_user_credential(
                db,
                user,
                tenant,
                username,
                password,
                backend_token,
                user.apaas_user_id,
                tenant.apaas_tenant_id_str or _tenant_item_id(item),
            )
        await _sync_user_membership(db, user, tenant, is_default=idx == 0)

    await db.commit()

    if local_tenants:
        selected = local_tenants[0]
        try:
            from app.routes.current_app import set_current_app, set_apaas_user_alias
            set_current_app(user.id, selected.id, 0, "")
            if user.apaas_user_id:
                set_apaas_user_alias(user.apaas_user_id, user.id, selected.id)
        except Exception as exc:
            logger.warning("apaas login slot prime failed: %s", exc)
        access_token = create_access_token(
            user,
            tenant_id=selected.id,
            apaas_user_id=user.apaas_user_id,
            apaas_tenant_id=selected.apaas_tenant_id_str or user.apaas_tenant_id,
        )
        return LoginResponse(
            access_token=access_token,
            tenants=[
                TenantOption(tenant_id=t.id, tenant_name=t.tenant_name, tenant_code=t.tenant_code)
                for t in local_tenants
            ],
            entry_path="/",
            is_platform_admin=is_platform_admin,
            has_tenant_context=True,
        )

    if is_platform_admin:
        access_token = create_access_token(user, tenant_id=None, apaas_user_id=user.apaas_user_id)
        return LoginResponse(
            access_token=access_token,
            entry_path="/platform-admin",
            is_platform_admin=True,
            has_tenant_context=False,
        )

    return None


@router.post("/login", response_model=LoginResponse)
async def login(
    user_data: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    import httpx
    try:
        apaas_response = await _try_apaas_login_flow(user_data, db)
    except httpx.RequestError as exc:
        # aPaaS 平台网络抖动（连接失败/超时等）不应让登录端点直接 500。
        # 降级到本地登录路径（与 _try_apaas_login_flow 返回 None 的语义一致），
        # 本地账号仍可登录；aPaaS 账号会收到凭证错误并可重试（连接通常瞬时恢复）。
        logger.warning("aPaaS 登录链路网络异常 (%s)，降级本地登录: %s", type(exc).__name__, exc)
        apaas_response = None
    if apaas_response:
        return apaas_response

    # 验证用户
    result = await db.execute(select(User).where(User.username == user_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用"
        )

    # 登录成功后立刻往 current_app slot 写入 user→tenant 映射。
    # 这是 stop bleed 关键：MCP 工具反查 slot 拿真实 tenant_id，避免 slot miss 后
    # fallback 到 admin（旧行为导致跨租户数据泄漏）。app_id=0 表示用户已登录但未打开
    # 具体应用 —— 用户进 /apps 打开应用后会再调 set_current_app 覆盖。
    # 同时写 apaas_uid → 本地 (uid, tid) alias，让外部 agent 透传 aPaaS 大整数 user_id
    # 调 MCP 工具时 _resolve_identity 能命中缓存零 DB。
    def _prime_slot(real_user_id: int, real_tenant_id: int) -> None:
        try:
            from app.routes.current_app import set_current_app, set_apaas_user_alias
            set_current_app(real_user_id, real_tenant_id, 0, "")
            if user.apaas_user_id:
                set_apaas_user_alias(user.apaas_user_id, real_user_id, real_tenant_id)
        except Exception as exc:
            logger.warning("登录后写 current_app slot 失败: %s", exc)

    # 2026-05-10 Phase 4：登 apaas 拿 token 同步存。前提：用户 ai-builder 密码 == apaas
    # 同名账号密码（生产很少同步，admin 团队偶尔统一）。失败 silent log，登录流程不阻断。
    # 成功 → user.apaas_token 更新；user.apaas_user_id 校对 backfill；JWT 自动嵌完整 claims。
    async def _try_apaas_real_login(target_user: User, plain_pw: str, target_tid: int) -> None:
        if not target_user.username or not plain_pw:
            return
        try:
            # 找 user 默认 tenant 绑定的 apaas env
            from app.models import PlatformEnv
            t_res = await db.execute(select(Tenant).where(Tenant.id == target_tid))
            target_tenant = t_res.scalar_one_or_none()
            if not target_tenant or not target_tenant.apaas_env_id:
                return  # 该租户没绑 apaas env
            e_res = await db.execute(
                select(PlatformEnv).where(PlatformEnv.id == target_tenant.apaas_env_id)
            )
            env = e_res.scalar_one_or_none()
            if not env or env.status != "connected":
                return
            from app.apaas_client import APaaSClient
            cli = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
            result = await cli.login(target_user.username, plain_pw)
            tok = result.get("token") or ""
            if not tok:
                return
            target_user.apaas_token = tok
            target_user.apaas_base_url = env.base_url
            target_user.apaas_tenant_id = env.platform_tenant_id
            uinfo = result.get("user") or {}
            if uinfo.get("id"):
                target_user.apaas_user_id = str(uinfo["id"])
            await db.commit()
            logger.info(
                "apaas chain login OK user_id=%s username=%s apaas_tid=%s",
                target_user.id, target_user.username, env.platform_tenant_id,
            )
        except Exception as exc:
            logger.info(
                "apaas chain login skipped user_id=%s username=%s: %s",
                target_user.id, target_user.username, exc,
            )

    # 平台管理员直接进入默认租户上下文。平台管理权限仍由
    # is_platform_admin 标识提供，tenant_id 用于租户级配置页查询。
    if user.is_platform_admin:
        tenant_id = await resolve_default_tenant_id_for_user(db, user.id)
        _prime_slot(user.id, tenant_id or 0)
        if tenant_id:
            await _try_apaas_real_login(user, user_data.password, tenant_id)
        access_token = create_access_token(user, tenant_id=tenant_id)
        return LoginResponse(access_token=access_token)

    # 获取用户的租户成员关系
    result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == user.id,
            UserTenant.status == 1
        )
    )
    memberships = result.scalars().all()

    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号未关联任何租户"
        )

    if len(memberships) == 1:
        # 单租户 — 直接登录
        tenant_id = memberships[0].tenant_id
        _prime_slot(user.id, tenant_id)
        await _try_apaas_real_login(user, user_data.password, tenant_id)
        access_token = create_access_token(user, tenant_id=tenant_id)
        return LoginResponse(access_token=access_token)

    # 多租户 — 返回租户列表
    tenant_ids = [m.tenant_id for m in memberships]
    result = await db.execute(
        select(Tenant).where(Tenant.id.in_(tenant_ids))
    )
    tenant_map = {t.id: t for t in result.scalars().all()}

    tenants = []
    default_tid = None
    for m in memberships:
        t = tenant_map.get(m.tenant_id)
        if t:
            tenants.append(TenantOption(
                tenant_id=t.id,
                tenant_name=t.tenant_name,
                tenant_code=t.tenant_code,
            ))
            if m.is_default:
                default_tid = t.id

    # 如果有默认租户，自动选择
    if default_tid:
        _prime_slot(user.id, default_tid)
        await _try_apaas_real_login(user, user_data.password, default_tid)
        access_token = create_access_token(user, tenant_id=default_tid)
        return LoginResponse(access_token=access_token, tenants=tenants)

    # 需要用户选择租户
    selection_token = create_selection_token(user.id)
    return LoginResponse(
        requires_tenant_selection=True,
        selection_token=selection_token,
        tenants=tenants
    )


@router.post("/select-tenant", response_model=Token)
async def select_tenant(
    data: TenantSelectRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """用户选择租户，换取完整 JWT"""
    from app.auth import decode_token
    try:
        payload = decode_token(data.selection_token)
        if payload.get("type") != "selection":
            raise HTTPException(status_code=401, detail=SELECT_TOKEN_INVALID)
        user_id = int(payload.get("sub"))
    except JWTError:
        raise HTTPException(status_code=401, detail=SELECT_TOKEN_EXPIRED)

    # 验证用户属于该租户
    result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == user_id,
            UserTenant.tenant_id == data.tenant_id,
            UserTenant.status == 1
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="你不是该租户的成员")

    # 选完租户写 slot（覆盖 prime_slot 的 0 占位）
    try:
        from app.routes.current_app import set_current_app
        set_current_app(user_id, data.tenant_id, 0, "")
    except Exception as exc:
        logger.warning("select-tenant 后写 current_app slot 失败: %s", exc)

    # 生成完整 JWT —— 拉 user 对象让 create_access_token 自动嵌 apaas claims
    u_res = await db.execute(select(User).where(User.id == user_id))
    user_obj = u_res.scalar_one_or_none()
    access_token = create_access_token(
        user_obj or user_id, tenant_id=data.tenant_id
    )
    return Token(access_token=access_token)


# ─── Phase 2 · 密钥换取端点 ────────────────────────────────────────────
class ExchangeApaasTokenRequest(BaseModel):
    apaas_token: str
    apaas_base_url: Optional[str] = None    # 可选，缺省取 settings.apaas_base_url
    apaas_tenant_id: Optional[str] = None   # 用户希望进入哪个 apaas 租户上下文，
                                            # 缺省取 user/info 返的 tenantInfos[0]


class ExchangeApaasTokenResponse(BaseModel):
    access_token: str
    user_id: int            # 本地 ai-builder users.id
    tenant_id: int          # 本地 ai-builder tenants.id
    apaas_user_id: str
    apaas_tenant_id: str
    username: str
    auth_mode: str = "apaas_token_exchange"


@router.post("/exchange-apaas-token", response_model=ExchangeApaasTokenResponse)
async def exchange_apaas_token(
    data: ExchangeApaasTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """密钥换取：拿 apaas token 换 ai-builder JWT（含双 ID claims）。

    流程：
      1. 调 apaas POST /xdap-admin/user/info 间接验签 + 拿 tenantInfos[]
      2. 选 apaas_tenant_id：入参优先 → tenantInfos 唯一一个 → 第一个
      3. 反查本地 User by apaas_user_id（UNIQUE 索引）
         - 命中：用本地 User.id 签 JWT
         - miss：报错（管理员需先 backfill / 手工建 ai-builder 账号绑定）
      4. 反查本地 Tenant by apaas_tenant_id_str
         - 命中：用本地 tenant.id
         - miss：尝试 user 的默认 ai-builder tenant；都没则报错
      5. 签 ai-builder JWT 返
    """
    from app.services.apaas_token_validator import validate_apaas_token

    apaas_base_url = (data.apaas_base_url or settings.apaas_base_url or "").rstrip("/")
    if not apaas_base_url:
        raise HTTPException(status_code=400, detail="缺 apaas_base_url（且 settings.apaas_base_url 为空）")

    # ── SSRF 防护 ──────────────────────────────────────────────────────────
    # 本端点无鉴权(SSO 换 token 须允许未登录调), 用户传入的 apaas_base_url 会被拿去发请求。
    # 用白名单兜底: 只允许 settings 配置的 apaas_base_url + 数据库已配置 env 的 base_url,
    # 拒绝任意 URL(防探测内网/云元数据)。白名单为空则拒绝一切。
    allowlist: list[str] = []
    if settings.apaas_base_url:
        allowlist.append(settings.apaas_base_url)
    try:
        from app.models import PlatformEnv as _PEnv
        envs = (await db.execute(select(_PEnv.base_url))).scalars().all()
        allowlist.extend([b for b in envs if b])
    except Exception as exc:
        logger.warning("exchange-apaas-token: 加载 env base_url 白名单失败: %s", exc)
    if not _is_allowed_apaas_base_url(apaas_base_url, allowlist):
        logger.warning("exchange-apaas-token: 拒绝非白名单 apaas_base_url=%s", apaas_base_url)
        raise HTTPException(status_code=400, detail="apaas_base_url 不在允许列表内")

    # tenant context for /user/info：入参优先，否则空字符串（apaas 自己 fallback）
    tenant_ctx = data.apaas_tenant_id or ""

    info = await validate_apaas_token(data.apaas_token, apaas_base_url, tenant_ctx)
    if not info:
        raise HTTPException(status_code=401, detail="apaas token 无效或已过期")

    apaas_uid = str(info["user_id"])
    tenants_info = info.get("tenants") or []

    # 选 apaas_tenant_id
    chosen_apaas_tid: Optional[str] = None
    if data.apaas_tenant_id:
        # 入参指定的 tenant 必须在用户所属列表里（防越权）
        if any(str(t.get("tenantId")) == str(data.apaas_tenant_id) for t in tenants_info):
            chosen_apaas_tid = str(data.apaas_tenant_id)
        else:
            raise HTTPException(
                status_code=403,
                detail=f"apaas user 不在租户 {data.apaas_tenant_id} 内（tenantInfos: "
                       f"{[t.get('tenantId') for t in tenants_info]}）",
            )
    elif len(tenants_info) == 1:
        chosen_apaas_tid = str(tenants_info[0].get("tenantId"))
    elif tenants_info:
        chosen_apaas_tid = str(tenants_info[0].get("tenantId"))  # 取第一个
    if not chosen_apaas_tid:
        raise HTTPException(status_code=403, detail="apaas user 不属于任何租户")

    # 本地 User 反查
    u_res = await db.execute(select(User).where(User.apaas_user_id == apaas_uid))
    local_user = u_res.scalar_one_or_none()
    if not local_user or not local_user.is_active:
        raise HTTPException(
            status_code=403,
            detail=f"apaas user {apaas_uid} 在 ai-builder 没有对应账号。"
                   "请管理员先在 ai-builder 建账号 + 设 users.apaas_user_id "
                   "字段，或跑 backfill 脚本。",
        )

    # 本地 Tenant 反查（按 apaas_tenant_id_str）
    t_res = await db.execute(
        select(Tenant).where(Tenant.apaas_tenant_id_str == chosen_apaas_tid)
    )
    local_tenant = t_res.scalar_one_or_none()
    local_tid: Optional[int] = None
    if local_tenant:
        # 用户必须是该 tenant 成员
        ut_res = await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == local_user.id,
                UserTenant.tenant_id == local_tenant.id,
                UserTenant.status == 1,
            )
        )
        if ut_res.scalar_one_or_none():
            local_tid = local_tenant.id
        else:
            logger.warning(
                "exchange-apaas-token: user %s 不是本地 tenant %s 成员，回退到 default",
                local_user.id, local_tenant.id,
            )

    if local_tid is None:
        # fallback：用户的默认 ai-builder tenant
        local_tid = await resolve_default_tenant_id_for_user(db, local_user.id)
    if not local_tid:
        raise HTTPException(
            status_code=403,
            detail=f"apaas user {apaas_uid} 在 ai-builder 没绑定任何租户",
        )

    # 缓存 apaas alias（让下次 MCP 调用零 DB 命中 + 把 apaas token 顺手存 user 行）
    try:
        from app.routes.current_app import set_apaas_user_alias, set_current_app
        set_apaas_user_alias(apaas_uid, local_user.id, local_tid)
        set_current_app(local_user.id, local_tid, 0, "")
    except Exception as exc:
        logger.warning("exchange-apaas-token slot prime 失败: %s", exc)
    # 顺便把 apaas_token 存 user 行（MCP 调 apaas 业务接口时可用）
    if not local_user.apaas_token or local_user.apaas_token != data.apaas_token:
        local_user.apaas_token = data.apaas_token
        local_user.apaas_tenant_id = chosen_apaas_tid
        if apaas_base_url:
            local_user.apaas_base_url = apaas_base_url
        await db.commit()

    # 签 ai-builder JWT（含 apaas 双 ID）
    new_token = create_access_token(
        local_user,
        tenant_id=local_tid,
        apaas_user_id=apaas_uid,
        apaas_tenant_id=chosen_apaas_tid,
    )

    return ExchangeApaasTokenResponse(
        access_token=new_token,
        user_id=local_user.id,
        tenant_id=local_tid,
        apaas_user_id=apaas_uid,
        apaas_tenant_id=chosen_apaas_tid,
        username=local_user.username,
    )


class TenantSwitchRequest(BaseModel):
    tenant_id: int


@router.post("/switch-tenant", response_model=Token)
async def switch_tenant(
    data: TenantSwitchRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """已登录用户切换 active tenant，签发携带新 tid 的 JWT。

    平台管理员可以切到任意 active 租户；普通用户仅限自己 active membership。
    """
    if ctx.user.is_platform_admin:
        tenant = (
            await db.execute(
                select(Tenant).where(Tenant.id == data.tenant_id, Tenant.status == 1)
            )
        ).scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="租户不存在或未启用")
    else:
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
            raise HTTPException(status_code=403, detail="你不是该租户的成员")

    # 切租户后重写 slot 到新 tenant_id
    try:
        from app.routes.current_app import set_current_app
        set_current_app(ctx.user.id, data.tenant_id, 0, "")
    except Exception as exc:
        logger.warning("switch-tenant 后写 current_app slot 失败: %s", exc)

    access_token = create_access_token(ctx.user, tenant_id=data.tenant_id)
    return Token(access_token=access_token)


def _require_platform_admin(ctx: AuthContext) -> None:
    if ctx.user.is_platform_admin or ctx.tenant_role == "platform_admin":
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅平台管理员可执行此操作")


class TenantCreateRequest(BaseModel):
    tenant_name: str
    tenant_code: str
    max_applications: int = 10
    max_workspaces: int = 20
    max_components: int = 50
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
    向后兼容，新接口不再返。资源限制全部走 max_applications/max_workspaces/max_components。
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


@router.get("/tenants", response_model=list[TenantAdminItem])
async def list_all_tenants(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Optional[str] = None,
    status: Optional[int] = None,
):
    """列出所有租户（仅平台管理员），含 member_count。

    - q：模糊匹配 tenant_name / tenant_code（不区分大小写）
    - status：1=只看启用 / 0=只看禁用 / 不传=全部
    """
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
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """新建租户（仅平台管理员）。"""
    _require_platform_admin(ctx)

    name = (data.tenant_name or "").strip()
    code = (data.tenant_code or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="租户名称不能为空")
    if not code or not all(ch.isalnum() or ch in "_-" for ch in code):
        raise HTTPException(status_code=400, detail="租户编码仅支持小写字母、数字、_、-")
    if data.max_applications < 1 or data.max_applications > 10000:
        raise HTTPException(status_code=400, detail="max_applications 范围 1-10000")
    if data.max_workspaces < 0 or data.max_workspaces > 10000:
        raise HTTPException(status_code=400, detail="max_workspaces 范围 0-10000")
    if data.max_components < 0 or data.max_components > 10000:
        raise HTTPException(status_code=400, detail="max_components 范围 0-10000")

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


@router.put("/tenants/{tenant_id}", response_model=TenantAdminItem)
async def update_tenant(
    tenant_id: int,
    data: TenantUpdateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
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

    for field, low, high in (
        ("max_applications", 1, 10000),
        ("max_workspaces", 0, 10000),
        ("max_components", 0, 10000),
    ):
        val = getattr(data, field)
        if val is not None:
            if val < low or val > high:
                raise HTTPException(status_code=400, detail=f"{field} 范围 {low}-{high}")
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
        # 已存在 env：更新 base_url + tid
        if base_url_in is not None:
            env.base_url = base_url_in.rstrip("/") if base_url_in else ""
        if platform_tid_in is not None:
            env.platform_tenant_id = platform_tid_in

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
    await db.refresh(t)

    from sqlalchemy import func as sql_func
    cnt = (
        await db.execute(
            select(sql_func.count(UserTenant.id))
            .where(UserTenant.tenant_id == t.id, UserTenant.status == 1)
        )
    ).scalar() or 0
    return await _attach_apaas_env_info(_tenant_admin_item(t, int(cnt)), db)


class TenantMemberAddRequest(BaseModel):
    username: str
    password: Optional[str] = None
    role_code: Optional[str] = None  # 默认 R_developer


class TenantMemberItem(BaseModel):
    user_id: int
    username: str
    is_active: bool
    is_platform_admin: bool
    tenant_role: str  # tenant_admin / developer / viewer / member
    role_code: Optional[str] = None
    role_name: Optional[str] = None
    joined_at: Optional[str] = None
    is_default: bool = False


def _serialize_tenant_member(
    user: User, membership: UserTenant, role: Optional[Role]
) -> TenantMemberItem:
    tenant_role, role_name, _perms = _resolve_tenant_role(role)
    return TenantMemberItem(
        user_id=user.id,
        username=user.username,
        is_active=user.is_active,
        is_platform_admin=user.is_platform_admin,
        tenant_role=tenant_role,
        role_code=role.role_code if role else None,
        role_name=role_name,
        joined_at=membership.joined_at.isoformat() if membership.joined_at else None,
        is_default=bool(membership.is_default),
    )


@router.get("/tenants/{tenant_id}/members", response_model=list[TenantMemberItem])
async def list_tenant_members(
    tenant_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出指定租户的成员（仅平台管理员）。"""
    _require_platform_admin(ctx)
    # tenant 存在性
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    rows = (
        await db.execute(
            select(UserTenant, User, Role)
            .join(User, User.id == UserTenant.user_id)
            .outerjoin(Role, Role.id == UserTenant.role_id)
            .where(UserTenant.tenant_id == tenant_id, UserTenant.status == 1)
            .order_by(UserTenant.joined_at.asc())
        )
    ).all()
    return [_serialize_tenant_member(user, m, role) for m, user, role in rows]


@router.get("/tenants/{tenant_id}/roles")
async def list_roles_for_tenant(
    tenant_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出指定租户角色（仅平台管理员）。

    平台管理页在任意租户下添加/调整成员时不能使用当前 token 的租户角色，
    必须读取目标租户自己的角色清单。
    """
    _require_platform_admin(ctx)
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    rows = (
        await db.execute(
            select(Role)
            .where(Role.tenant_id == tenant_id)
            .order_by(Role.is_system.desc(), Role.created_at.asc(), Role.id.asc())
        )
    ).scalars().all()
    return [
        {
            "id": role.id,
            "role_code": role.role_code,
            "role_name": role.role_name,
            "is_system": role.is_system,
            "permissions": role.permissions or {},
        }
        for role in rows
    ]


@router.post("/tenants/{tenant_id}/members", response_model=TenantMemberItem)
async def add_tenant_member(
    tenant_id: int,
    data: TenantMemberAddRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """跨租户给指定租户加成员（仅平台管理员）。

    若用户名不存在则用 password 新建账号；已存在则只建/激活 UserTenant 关系。
    role_code 默认 R_developer，可传 R_tenant_admin / R_developer / R_viewer / member。
    """
    _require_platform_admin(ctx)

    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    username = (data.username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")

    role_code = (data.role_code or "R_developer").strip() or "R_developer"
    role = (
        await db.execute(
            select(Role).where(Role.tenant_id == tenant_id, Role.role_code == role_code)
        )
    ).scalar_one_or_none()
    if not role:
        # 找不到该 tenant 的同 code 角色，按优先级回退（兼容 init_db 种的 admin / 新版 seed 种的 R_tenant_admin）
        for fallback in ("R_developer", "R_tenant_admin", "admin"):
            role = (
                await db.execute(
                    select(Role).where(Role.tenant_id == tenant_id, Role.role_code == fallback)
                )
            ).scalar_one_or_none()
            if role:
                break
    if not role:
        raise HTTPException(status_code=404, detail="该租户未配置角色，请先创建角色")

    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if not user:
        if not data.password:
            raise HTTPException(status_code=400, detail="用户不存在，请提供初始密码创建账号")
        user = User(username=username, hashed_password=get_password_hash(data.password), is_active=True)
        db.add(user)
        await db.flush()

    membership = (
        await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == user.id, UserTenant.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if membership:
        membership.status = 1
        membership.role_id = role.id
    else:
        # 用户没有任何 active membership 时把这条设为 default
        existing_default = (
            await db.execute(
                select(UserTenant).where(
                    UserTenant.user_id == user.id, UserTenant.status == 1
                )
            )
        ).scalars().all()
        membership = UserTenant(
            user_id=user.id,
            tenant_id=tenant_id,
            role_id=role.id,
            is_default=not existing_default,
            status=1,
        )
        db.add(membership)

    await db.commit()
    await db.refresh(membership)
    return _serialize_tenant_member(user, membership, role)


class TenantMemberRoleUpdateRequest(BaseModel):
    role_code: str


@router.put("/tenants/{tenant_id}/members/{user_id}/role", response_model=TenantMemberItem)
async def update_tenant_member_role(
    tenant_id: int,
    user_id: int,
    data: TenantMemberRoleUpdateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """改租户内某个成员的角色（仅平台管理员）。

    防呆：不能把自己（当前激活租户里）从管理员降级成普通成员，避免锁死。
    """
    _require_platform_admin(ctx)

    role_code = (data.role_code or "").strip()
    if not role_code:
        raise HTTPException(status_code=400, detail="role_code 不能为空")

    # 查 membership
    res = await db.execute(
        select(UserTenant, User)
        .join(User, User.id == UserTenant.user_id)
        .where(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id)
    )
    row = res.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="该用户不是该租户成员")
    membership, user = row

    # 查 role
    role = (
        await db.execute(
            select(Role).where(Role.tenant_id == tenant_id, Role.role_code == role_code)
        )
    ).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail=f"该租户下没有角色 '{role_code}'")

    # 防呆：不能把自己从当前激活的租户管理员降级（避免操作完发现自己没权限）
    if (
        ctx.user.id == user_id
        and ctx.tenant_id == tenant_id
        and role_code not in ("admin", "R_tenant_admin")
    ):
        # 看一下被改的当前角色是不是 admin
        old_role = (
            await db.execute(select(Role).where(Role.id == membership.role_id))
        ).scalar_one_or_none()
        if old_role and old_role.role_code in ("admin", "R_tenant_admin"):
            raise HTTPException(
                status_code=400,
                detail="不能把自己从当前激活租户的管理员降级，请先切换租户后再改",
            )

    membership.role_id = role.id
    await db.commit()
    await db.refresh(membership)
    return _serialize_tenant_member(user, membership, role)


@router.delete("/tenants/{tenant_id}/members/{user_id}")
async def remove_tenant_member(
    tenant_id: int,
    user_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """把成员从租户移除（仅平台管理员）。

    硬删 UserTenant 行（不是软删）；不动 User 账号本身。
    保护：不能把自己从当前激活租户移除。
    """
    _require_platform_admin(ctx)

    if ctx.user.id == user_id and ctx.tenant_id == tenant_id:
        raise HTTPException(status_code=400, detail="不能把自己从当前激活的租户中移除")

    membership = (
        await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=404, detail="该用户不是该租户成员")

    await db.delete(membership)
    await db.commit()
    return {"ok": True, "tenant_id": tenant_id, "user_id": user_id}


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
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
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """返回某租户的资源使用情况（仅平台管理员）。"""
    _require_platform_admin(ctx)
    from app.tenant_quota import get_tenant_usage as _get_usage
    return await _get_usage(db, tenant_id)


@router.put("/tenants/{tenant_id}/status", response_model=TenantAdminItem)
async def update_tenant_status(
    tenant_id: int,
    data: TenantStatusRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """启用 / 禁用租户（仅平台管理员）。被禁用的租户成员仍可见但无法切入。"""
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


@router.get("/tenants/dashboard")
async def tenant_dashboard(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """平台总览（仅平台管理员）：所有租户的资源/配额聚合 + Top N 接近上限的租户。"""
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
    cap_apps = cap_workspaces = cap_components = 0
    near_limit: list[dict] = []

    for t in rows:
        u = await _usage(db, t.id)
        apps_used = u["applications"]["used"]
        ws_used = u["workspaces"]["used"]
        comps_used = u["components"]["used"]

        total_apps += apps_used
        total_workspaces += ws_used
        total_components += comps_used
        total_members += u["members"]
        cap_apps += t.max_applications
        cap_workspaces += t.max_workspaces
        cap_components += t.max_components

        # 任一资源 >= 80% 视为预警
        for k, used, mx in (
            ("applications", apps_used, t.max_applications),
            ("workspaces", ws_used, t.max_workspaces),
            ("components", comps_used, t.max_components),
        ):
            if mx > 0 and used / mx >= 0.8:
                near_limit.append(
                    {
                        "tenant_id": t.id,
                        "tenant_name": t.tenant_name,
                        "resource": k,
                        "used": used,
                        "max": mx,
                        "ratio": round(used / mx, 3),
                    }
                )

    near_limit.sort(key=lambda x: -x["ratio"])
    return {
        "tenants_active": len(rows),
        "totals": {
            "applications": {"used": total_apps, "max": cap_apps},
            "workspaces": {"used": total_workspaces, "max": cap_workspaces},
            "components": {"used": total_components, "max": cap_components},
            "members": total_members,
        },
        "near_limit": near_limit[:10],
    }


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


class ResetPasswordRequest(BaseModel):
    new_password: str


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
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出全平台 active 账号（仅平台管理员），供「租户管理 → 加成员」从已有账号里选。

    返回精简：id / username / is_platform_admin。不返密码 hash。
    """
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
            "is_platform_admin": u.is_platform_admin,
        }
        for u in rows
    ]


@router.get("/me/tenants", response_model=list[TenantOption])
async def list_my_tenants(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """返回当前用户可切换的租户列表（用于顶栏 dropdown）。"""
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
    return [
        TenantOption(tenant_id=t.id, tenant_name=t.tenant_name, tenant_code=t.tenant_code)
        for t in rows
    ]


@router.get("/users")
async def list_users(ctx: Annotated[AuthContext, Depends(get_auth_context)], db: Annotated[AsyncSession, Depends(get_db)]):
    """获取同租户下的所有用户（用于团队成员选择）"""
    if ctx.tenant_id:
        result = await db.execute(
            select(User.id, User.username)
            .join(UserTenant, User.id == UserTenant.user_id)
            .where(
                UserTenant.tenant_id == ctx.tenant_id,
                UserTenant.status == 1,
                User.is_active == True,
            )
        )
    else:
        result = await db.execute(select(User.id, User.username).where(User.is_active == True))
    return [{"id": row[0], "username": row[1]} for row in result.fetchall()]


@router.get("/tenant-roles")
async def list_tenant_roles(
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
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
async def get_me(ctx: Annotated[AuthContext, Depends(get_auth_context)], db: Annotated[AsyncSession, Depends(get_db)]):
    # 获取租户信息
    tenant_name = None
    if ctx.tenant_id:
        result = await db.execute(select(Tenant).where(Tenant.id == ctx.tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant:
            tenant_name = tenant.tenant_name

    return UserInfo(
        id=ctx.user.id,
        username=ctx.user.username,
        is_active=ctx.user.is_active,
        created_at=ctx.user.created_at,
        tenant_id=ctx.tenant_id if ctx.tenant_id else None,
        tenant_name=tenant_name,
        tenant_role=ctx.tenant_role,
        org_permissions=ctx.org_permissions or {}
    )
