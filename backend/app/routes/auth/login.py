import logging
import re
import secrets
from dataclasses import replace
from datetime import datetime
from typing import Annotated, Optional, Union
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError
from app.database import get_db
from app.models import APaaSPlatformCredential, APaaSUserCredential, PlatformEnv, User
from app.models.tenant import Tenant, UserTenant, Role
from app.schemas import (
    UserLogin, Token,
    LoginResponse, TenantOption, TenantSelectRequest
)
from app.auth import _DESKTOP_ISSUER, verify_password, get_password_hash, create_access_token, create_selection_token
from app.code_runtime.auth import (
    ControlPlaneAuthResult,
    control_plane_access_token,
    exchange_apaas_token,
    fetch_control_plane_identity,
    fetch_dolphin_captcha,
    login_to_control_plane,
    store_control_plane_credentials,
)
from app.crypto import decrypt_password, encrypt_password
from app.deps import (
    AuthContext,
    get_auth_context,
    platform_admin_has_unscoped_tenant_access,
    resolve_default_tenant_id_for_user,
)
from app.config import settings
from app import runtime
from app.error_messages import SELECT_TOKEN_INVALID, SELECT_TOKEN_EXPIRED
from app.tenant_public_id import ensure_tenant_public_id
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()
control_plane_bearer = HTTPBearer()


async def _tenant_option(db: AsyncSession, tenant: Tenant) -> TenantOption:
    return TenantOption(
        tenant_id=tenant.id,
        tenant_name=tenant.tenant_name,
        tenant_code=tenant.tenant_code,
        tenant_public_id=await ensure_tenant_public_id(db, tenant),
    )


async def _tenant_options_with_durable_public_ids(
    db: AsyncSession,
    tenants: list[Tenant],
) -> list[TenantOption]:
    return [await _tenant_option(db, tenant) for tenant in tenants]


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


def _extract_user_display_name(user_info: dict, fallback: str = "") -> str:
    if not isinstance(user_info, dict):
        return ""
    for key in (
        "displayName",
        "display_name",
        "realName",
        "real_name",
        "nickName",
        "nickname",
        "name",
        "userName",
        "username",
    ):
        value = str(user_info.get(key) or "").strip()
        if value and value != fallback:
            return value
    return ""


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
    code_values = {
        str(value or "").strip()
        for value in (
            item.get("tenantCode"),
            item.get("tenant_code"),
            item.get("code"),
            item.get("tenantId"),
            item.get("tenant_id"),
            item.get("id"),
            fallback,
        )
        if str(value or "").strip()
    }
    for key in (
        "displayName",
        "display_name",
        "tenantDisplayName",
        "tenant_display_name",
        "label",
        "orgName",
        "org_name",
        "companyName",
        "company_name",
    ):
        value = str(item.get(key) or "").strip()
        if value and value not in code_values:
            return value
    for key in ("tenantName", "tenant_name", "name"):
        value = str(item.get(key) or "").strip()
        if value and value not in code_values:
            return value
    return str(item.get("tenantName") or item.get("tenant_name") or item.get("name") or fallback).strip()


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


def _is_placeholder_apaas_base_url() -> bool:
    base_url = (settings.apaas_base_url or "").strip().lower()
    return not base_url or "your-apaas.example.com" in base_url


APAAS_LOGIN_TIMEOUT_SECONDS = 30


def _extract_login_error_message(*payloads: object) -> str:
    keys = (
        "message",
        "msg",
        "error",
        "errorMessage",
        "error_message",
        "detail",
        "description",
    )
    for payload in payloads:
        if isinstance(payload, dict):
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            for key in keys:
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            code = data.get("code")
            if code not in (None, "", "ok", 200, "200"):
                return f"平台返回 code={code}"
    return ""


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
    headers.pop("xdaptenantid", None)
    body = {
        "type": "account",
        "account": username,
        "password": mcp_platform._encrypt_apaas_password(password, rsa_public_key),
        "securityCode": "",
    }
    async with httpx.AsyncClient(timeout=APAAS_LOGIN_TIMEOUT_SECONDS, verify=False, trust_env=False) as client:
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
    clean_tenant_id = (tenant_id or "").strip()
    headers = mcp_platform._headers(
        base_url,
        tenant_id=clean_tenant_id or None,
        rsa_public_key=rsa_public_key,
    )
    headers["referer"] = f"{base_url}/platform/account/login"
    if not clean_tenant_id:
        headers.pop("xdaptenantid", None)
    body = {
        "type": "account",
        "account": username,
        "password": mcp_platform._encrypt_apaas_password(password, rsa_public_key),
        "loginType": "MANAGE",
        "securityCode": "",
    }
    if clean_tenant_id:
        body["tenantId"] = clean_tenant_id
    async with httpx.AsyncClient(timeout=APAAS_LOGIN_TIMEOUT_SECONDS, verify=False, trust_env=False) as client:
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
    async with httpx.AsyncClient(timeout=APAAS_LOGIN_TIMEOUT_SECONDS, verify=False, trust_env=False) as client:
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
    async with httpx.AsyncClient(timeout=APAAS_LOGIN_TIMEOUT_SECONDS, verify=False, trust_env=False) as client:
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


def _apaas_membership_role_preference(
    item: dict,
    username: str,
    user_info: dict,
    admin_tenant_ids: set[str],
    is_platform_admin: bool,
) -> tuple[str, ...]:
    if (
        is_platform_admin
        or _tenant_item_id(item) in admin_tenant_ids
        or _tenant_admin_matches(item, username, user_info)
    ):
        return ("R_tenant_admin", "admin", "R_developer")
    return ("R_developer", "R_tenant_admin", "admin")


async def _ensure_apaas_tenant(
    db: AsyncSession,
    item: dict,
    login_username: str | None = None,
    login_password: str | None = None,
) -> Tenant:
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
        from app.seed_data import seed_default_roles
        await seed_default_roles(db, tenant.id, commit=False)
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
        env = (
            await db.execute(
                select(PlatformEnv)
                .where(PlatformEnv.tenant_id == tenant.id)
                .order_by(PlatformEnv.is_default.desc(), PlatformEnv.id.asc())
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
        # 2026-06-01 登录即把账号密码灌进 env → 让查模型等读接口的 token 自愈有凭据可用,
        # 免去用户先手动「平台管理 → 刷新租户」。token 留空, 首次访问由 call_apaas_with_relogin 自愈拿。
        if login_username and login_password:
            env.username = login_username
            env.password_enc = encrypt_password(login_password)
        db.add(env)
        await db.flush()
        tenant.apaas_env_id = env.id
    else:
        env.env_name = name
        env.base_url = (settings.apaas_base_url or "").rstrip("/")
        env.platform_tenant_id = platform_tid
        env.is_default = True
        # 旧 env(早期登录建的, 无凭据) → 补上让自愈可用; 已有凭据不覆盖(可能是更高权限账号)
        if login_username and login_password and (not env.username or not env.password_enc):
            env.username = login_username
            env.password_enc = encrypt_password(login_password)
    return tenant


async def _ensure_apaas_user(db: AsyncSession, username: str, password: str, user_info: dict, is_platform_admin: bool) -> User:
    apaas_uid = str(user_info.get("id") or user_info.get("userId") or user_info.get("user_id") or "").strip() or None
    display_name = _extract_user_display_name(user_info, fallback=username)
    user = None
    if apaas_uid:
        user = (await db.execute(select(User).where(User.apaas_user_id == apaas_uid))).scalar_one_or_none()
    if not user:
        user = (await db.execute(
            select(User).where(User.username == username, User.account_source == "apaas")
        )).scalar_one_or_none()
    if not user:
        user = User(
            username=username,
            display_name=display_name or None,
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            apaas_user_id=apaas_uid,
            account_source="apaas",
            is_platform_admin=is_platform_admin,
            is_active=True,
        )
        db.add(user)
        await db.flush()
    else:
        user.username = username
        if display_name:
            user.display_name = display_name
        user.hashed_password = get_password_hash(secrets.token_urlsafe(32))
        if apaas_uid:
            user.apaas_user_id = apaas_uid
        user.is_platform_admin = is_platform_admin
        user.is_active = True
    user.apaas_base_url = _normalize_apaas_origin(settings.apaas_base_url)
    return user


async def _has_cached_platform_admin_identity(db: AsyncSession, username: str, user_info: dict) -> bool:
    """Return True when this aPaaS account was previously verified as platform admin.

    The live platform-admin probe is authoritative when it responds. If it times
    out, keep a previously verified platform identity instead of demoting the
    user during an otherwise successful tenant login.
    """
    apaas_uid = str(user_info.get("id") or user_info.get("userId") or user_info.get("user_id") or "").strip()
    stmt = select(User).where(User.account_source == "apaas")
    if apaas_uid:
        stmt = stmt.where(User.apaas_user_id == apaas_uid)
    else:
        stmt = stmt.where(User.username == username)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        return False
    if user.is_platform_admin:
        return True

    base_url = _normalize_apaas_origin(settings.apaas_base_url)
    credential = (
        await db.execute(
            select(APaaSPlatformCredential.id)
            .where(
                APaaSPlatformCredential.user_id == user.id,
                APaaSPlatformCredential.base_url == base_url,
                APaaSPlatformCredential.account == username,
                APaaSPlatformCredential.status == "connected",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return credential is not None


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


async def _sync_user_membership(
    db: AsyncSession,
    user: User,
    tenant: Tenant,
    is_default: bool,
    preferred_role_codes: tuple[str, ...] = ("R_developer", "R_tenant_admin", "admin"),
) -> UserTenant:
    roles = (
        await db.execute(
            select(Role)
            .where(Role.tenant_id == tenant.id)
            .where(Role.role_code.in_(list(preferred_role_codes)))
        )
    ).scalars().all()
    roles_by_code = {role.role_code: role for role in roles}
    role = next((roles_by_code.get(code) for code in preferred_role_codes if roles_by_code.get(code)), None)
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

    platform_probe_failed = False
    try:
        platform_token, platform_payload = await _apaas_platform_login(username, password)
    except Exception as exc:
        platform_probe_failed = True
        logger.warning(
            "aPaaS platform-admin login probe failed; continue backend login (%s): %s",
            type(exc).__name__,
            exc,
        )
        platform_token, platform_payload = None, {}
    is_platform_admin = bool(platform_token)

    backend_token, backend_payload = await _apaas_backend_login(username, password, "")
    default_tenant_item = _extract_default_tenant_item(backend_payload) if backend_token else None
    default_tenant_id = _tenant_item_id(default_tenant_item) if default_tenant_item else ""
    has_backend_identity = bool(backend_token and default_tenant_id)

    if not has_backend_identity and not is_platform_admin:
        if not _is_placeholder_apaas_base_url():
            message = _extract_login_error_message(platform_payload, backend_payload)
            if not message:
                message = "平台未返回有效 token 或租户信息，请确认 aPaaS 地址、账号、密码和租户权限"
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"aPaaS 登录失败：{message}",
            )
        return None

    user_info = _extract_apaas_user(backend_payload or platform_payload, username)
    if platform_probe_failed and not is_platform_admin:
        is_platform_admin = await _has_cached_platform_admin_identity(db, username, user_info)

    switchable_items: list[dict] = []
    if has_backend_identity:
        switchable_items = await _apaas_switchable_tenants(backend_token, default_tenant_id)
    platform_items: list[dict] = []
    if is_platform_admin and platform_token:
        try:
            platform_items = await _apaas_all_tenants(platform_token)
        except Exception as exc:
            logger.warning("aPaaS platform tenant sync failed during login: %s", exc)
    admin_tenant_ids = {_tenant_item_id(item) for item in switchable_items if _tenant_item_id(item)}

    if has_backend_identity:
        available_items = _merge_tenant_items(
            [default_tenant_item] if default_tenant_item else [],
            switchable_items,
        )
        if is_platform_admin and platform_items:
            available_ids = {_tenant_item_id(item) for item in available_items if _tenant_item_id(item)}
            enriched_items = [item for item in platform_items if _tenant_item_id(item) in available_ids]
            available_items = _merge_tenant_items(available_items, enriched_items)
        available_items = [item for item in available_items if _tenant_enabled(item)]
    else:
        available_items = []

    user = await _ensure_apaas_user(db, username, password, user_info, is_platform_admin)
    if platform_token:
        await _upsert_platform_credential(db, user, username, password, platform_token)
    if is_platform_admin:
        for item in platform_items:
            if _tenant_enabled(item):
                await _ensure_apaas_tenant(db, item)

    local_tenants: list[Tenant] = []
    for idx, item in enumerate(available_items):
        tenant = await _ensure_apaas_tenant(db, item, username, password)
        local_tenants.append(tenant)
        should_bind_backend_token = (
            bool(backend_token)
            and (
                not is_platform_admin
                or (tenant.apaas_tenant_id_str and tenant.apaas_tenant_id_str == default_tenant_id)
            )
        )
        if should_bind_backend_token:
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
        await _sync_user_membership(
            db,
            user,
            tenant,
            is_default=idx == 0,
            preferred_role_codes=_apaas_membership_role_preference(
                item,
                username,
                user_info,
                admin_tenant_ids,
                is_platform_admin,
            ),
        )

    if settings.control_plane_binding_enabled:
        if not local_tenants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="aPaaS 账号未返回可绑定的租户",
            )
        selected_tenant = local_tenants[0]
        selected_apaas_tenant_id = str(selected_tenant.apaas_tenant_id_str or "").strip()
        subject_token = str(backend_token or platform_token or "").strip()
        if not selected_apaas_tenant_id or not subject_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="aPaaS 账号未返回可用于 Control Plane 绑定的租户或 Token",
            )
        dolphin_token = await exchange_apaas_token(subject_token, selected_apaas_tenant_id)
        user.coding_tenant_id = dolphin_token.tenant_id
        store_control_plane_credentials(
            user,
            dolphin_token.access_token,
            dolphin_token.refresh_token,
        )

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
        tenant_options = await _tenant_options_with_durable_public_ids(
            db,
            local_tenants,
        )
        await db.commit()
        return LoginResponse(
            access_token=access_token,
            tenants=tenant_options,
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


def _auth_provider() -> str:
    provider = (getattr(settings, "auth_provider", "") or "").strip().lower()
    provider = {
        "self": "local",
        "own": "local",
        "native": "local",
        "builtin": "local",
        "coding": "control_plane",
    }.get(provider, provider)
    if provider not in ("", "local", "apaas", "control_plane"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_PROVIDER must be one of control_plane, apaas",
        )
    return provider


def _prime_login_slot(user: User, tenant_id: int) -> None:
    try:
        from app.routes.current_app import set_current_app, set_apaas_user_alias

        set_current_app(user.id, tenant_id, 0, "")
        if user.apaas_user_id:
            set_apaas_user_alias(user.apaas_user_id, user.id, tenant_id)
    except Exception as exc:
        logger.warning("登录后写 current_app slot 失败: %s", exc)


async def _try_apaas_real_login(
    db: AsyncSession,
    target_user: User,
    plain_pw: str,
    target_tid: int,
) -> None:
    if target_user.account_source != "apaas" or not target_user.username or not plain_pw:
        return
    try:
        t_res = await db.execute(select(Tenant).where(Tenant.id == target_tid))
        target_tenant = t_res.scalar_one_or_none()
        if not target_tenant or not target_tenant.apaas_env_id:
            return
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
            target_user.id,
            target_user.username,
            env.platform_tenant_id,
        )
    except Exception as exc:
        logger.info(
            "apaas chain login skipped user_id=%s username=%s: %s",
            target_user.id,
            target_user.username,
            exc,
        )


async def _issue_login_response_for_user(
    db: AsyncSession,
    user: User,
    *,
    plain_password: str = "",
    allow_apaas_chain: bool = False,
) -> LoginResponse:
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用",
        )

    if user.is_platform_admin:
        tenant_id = await resolve_default_tenant_id_for_user(db, user.id)
        _prime_login_slot(user, tenant_id or 0)
        if tenant_id and allow_apaas_chain:
            await _try_apaas_real_login(db, user, plain_password, tenant_id)
        access_token = create_access_token(user, tenant_id=tenant_id)
        return LoginResponse(access_token=access_token)

    result = await db.execute(
        select(UserTenant)
        .join(Tenant, Tenant.id == UserTenant.tenant_id)
        .where(
            UserTenant.user_id == user.id,
            UserTenant.status == 1,
            Tenant.status == 1,
        )
    )
    memberships = result.scalars().all()

    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号未关联任何租户",
        )

    if len(memberships) == 1:
        tenant_id = memberships[0].tenant_id
        _prime_login_slot(user, tenant_id)
        if allow_apaas_chain:
            await _try_apaas_real_login(db, user, plain_password, tenant_id)
        access_token = create_access_token(user, tenant_id=tenant_id)
        return LoginResponse(access_token=access_token)

    tenant_ids = [m.tenant_id for m in memberships]
    result = await db.execute(
        select(Tenant).where(Tenant.id.in_(tenant_ids), Tenant.status == 1)
    )
    tenant_map = {t.id: t for t in result.scalars().all()}

    option_tenants = []
    default_tid = None
    for m in memberships:
        t = tenant_map.get(m.tenant_id)
        if t:
            option_tenants.append(t)
            if m.is_default:
                default_tid = t.id

    tenants = await _tenant_options_with_durable_public_ids(db, option_tenants)

    if default_tid:
        _prime_login_slot(user, default_tid)
        if allow_apaas_chain:
            await _try_apaas_real_login(db, user, plain_password, default_tid)
        access_token = create_access_token(user, tenant_id=default_tid)
        return LoginResponse(access_token=access_token, tenants=tenants)

    selection_token = create_selection_token(user.id)
    return LoginResponse(
        requires_tenant_selection=True,
        selection_token=selection_token,
        tenants=tenants,
    )


async def _local_login_response(user_data: UserLogin, db: AsyncSession) -> LoginResponse:
    result = await db.execute(
        select(User).where(User.username == user_data.username, User.account_source == "apaas")
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    response = await _issue_login_response_for_user(
        db,
        user,
        plain_password=user_data.password,
        allow_apaas_chain=True,
    )
    await db.commit()
    return response


def _control_plane_roles_include_admin(roles: list[str]) -> bool:
    normalized = {str(role or "").strip().upper() for role in roles}
    return bool(normalized.intersection({
        "ADMIN",
        "PLATFORM_ADMIN",
        "CONTROL_PLANE_ADMIN",
        "SYSTEM_ADMIN",
    }))


def _control_plane_identity_is_platform_admin(identity: ControlPlaneAuthResult) -> bool:
    permissions = getattr(identity, "org_permissions", {}) or {}
    return (
        _control_plane_roles_include_admin(identity.roles)
        or permissions.get("*") is True
        or permissions.get("system.*") is True
    )


def _control_plane_identity_is_tenant_admin(identity: ControlPlaneAuthResult) -> bool:
    normalized = {str(role or "").strip().upper() for role in identity.roles}
    return (
        _control_plane_identity_is_platform_admin(identity)
        or bool(normalized.intersection({"TENANT_ADMIN", "ORG_ADMIN"}))
    )


async def _require_control_plane_platform_binding(
    db: AsyncSession,
    user: User,
    identity: ControlPlaneAuthResult,
) -> None:
    tenant_id = await resolve_default_tenant_id_for_user(db, user.id)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前 Control Plane 账号未在 Builder 平台管理中绑定租户",
        )
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    env = None
    if tenant.apaas_env_id:
        env = (
            await db.execute(select(PlatformEnv).where(PlatformEnv.id == tenant.apaas_env_id))
        ).scalar_one_or_none()
    if not env:
        env = (
            await db.execute(
                select(PlatformEnv)
                .where(PlatformEnv.tenant_id == tenant_id)
                .order_by(PlatformEnv.is_default.desc(), PlatformEnv.id.asc())
            )
        ).scalars().first()
    if not env or not env.platform_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前租户未在 Builder 平台管理中配置 aPaaS 环境",
        )
    if not env.username or env.username.strip().lower() != identity.username.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="平台管理中配置的 aPaaS 账号与当前 Control Plane 账号不一致",
        )

async def _ensure_control_plane_user(
    db: AsyncSession,
    identity: ControlPlaneAuthResult,
) -> User:
    user = None
    if identity.external_user_id:
        user = (
            await db.execute(
                select(User)
                .where(User.coding_user_id == identity.external_user_id)
                .order_by(User.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if not user:
        user = (await db.execute(
            select(User)
            .where(
                User.username == identity.username,
                User.account_source.in_(("control_plane", "coding")),
            )
            .order_by(
                (User.account_source == "control_plane").desc(),
                User.id.asc(),
            )
            .limit(1)
        )).scalar_one_or_none()
    if not user:
        user = User(
            username=identity.username,
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            account_source="control_plane",
            is_active=True,
        )
        db.add(user)
        await db.flush()

    user.username = identity.username
    user.display_name = identity.display_name or identity.username
    user.coding_user_id = identity.external_user_id
    user.coding_tenant_id = identity.tenant_id
    store_control_plane_credentials(user, identity.access_token, identity.refresh_token)
    user.is_active = True
    user.is_platform_admin = _control_plane_identity_is_platform_admin(identity)
    await db.flush()
    if runtime.is_desktop():
        return user

    preferred_roles = (
        ("R_tenant_admin", "admin", "R_developer")
        if _control_plane_identity_is_tenant_admin(identity)
        else ("R_developer", "R_tenant_admin", "admin")
    )
    if settings.control_plane_binding_enabled:
        mapped_envs = (
            await db.execute(
                select(PlatformEnv)
                .where(func.lower(PlatformEnv.username) == identity.username.strip().lower())
                .order_by(PlatformEnv.is_default.desc(), PlatformEnv.id.asc())
            )
        ).scalars().all()
        for index, env in enumerate(mapped_envs):
            tenant = (
                await db.execute(
                    select(Tenant).where(Tenant.id == env.tenant_id, Tenant.status == 1)
                )
            ).scalar_one_or_none()
            if tenant:
                await _sync_user_membership(
                    db,
                    user,
                    tenant,
                    is_default=index == 0,
                    preferred_role_codes=preferred_roles,
                )
    elif identity.tenant_id:
        from app.seed_data import seed_default_roles, sync_builtin_llm_configs

        workspace_tenant_code = _normalize_tenant_code(
            f"workspace-{identity.tenant_id}",
            identity.tenant_id,
        )
        tenant_codes = [workspace_tenant_code]
        if identity.tenant_id.strip().lower() == "default":
            tenant_codes.append("default")
        tenant = None
        for tenant_code in tenant_codes:
            tenant = (
                await db.execute(select(Tenant).where(Tenant.tenant_code == tenant_code))
            ).scalar_one_or_none()
            if tenant:
                break
        if not tenant:
            tenant = Tenant(
                tenant_name=identity.tenant_name or identity.tenant_id,
                tenant_code=(
                    "default"
                    if identity.tenant_id.strip().lower() == "default"
                    else workspace_tenant_code
                ),
            )
            db.add(tenant)
            await db.flush()
        await seed_default_roles(db, tenant.id, commit=False)
        try:
            await sync_builtin_llm_configs(db, tenant_ids=[tenant.id], commit=False)
        except Exception as exc:
            logger.warning(
                "sync_builtin_llm_configs failed for Control Plane tenant %s: %s",
                tenant.id,
                exc,
            )
        existing_default = (
            await db.execute(
                select(UserTenant)
                .where(
                    UserTenant.user_id == user.id,
                    UserTenant.status == 1,
                    UserTenant.is_default == True,
                )
                .order_by(UserTenant.joined_at.asc(), UserTenant.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        await _sync_user_membership(
            db,
            user,
            tenant,
            is_default=existing_default is None or existing_default.tenant_id == tenant.id,
            preferred_role_codes=preferred_roles,
        )
        await db.flush()
    return user


async def _control_plane_login_response(user_data: UserLogin, db: AsyncSession) -> LoginResponse:
    captcha_id = str(user_data.captcha_id or "").strip()
    captcha_code = str(user_data.captcha_code or "").strip()
    if settings.control_plane_captcha_enabled and (not captcha_id or not captcha_code):
        raise HTTPException(status_code=400, detail="请输入 Control Plane 验证码")
    identity = await login_to_control_plane(
        user_data.username,
        user_data.password,
        captcha_id,
        captcha_code,
    )
    user = await _ensure_control_plane_user(db, identity)
    if settings.control_plane_binding_enabled:
        await _require_control_plane_platform_binding(db, user, identity)
    response = await _issue_login_response_for_user(db, user)
    await db.commit()
    return response


@router.post("/control-plane/session", response_model=LoginResponse)
async def exchange_control_plane_session(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(control_plane_bearer)],
    x_tenant_id: Annotated[Optional[str], Header(alias="X-Tenant-Id")],
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    identity = await fetch_control_plane_identity(credentials.credentials)
    tenant_id = str(x_tenant_id or identity.tenant_id or "").strip()
    tenants = {
        str(item.get("tenant_id") or "").strip(): str(item.get("tenant_name") or "").strip()
        for item in identity.available_tenants
        if str(item.get("tenant_id") or "").strip()
    }
    if identity.tenant_id:
        tenants.setdefault(str(identity.tenant_id), str(identity.tenant_name or ""))
    if tenant_id not in tenants:
        raise HTTPException(status_code=403, detail="该 Control Plane 组织不可访问")
    user = await _ensure_control_plane_user(
        db,
        replace(identity, tenant_id=tenant_id, tenant_name=tenants[tenant_id] or tenant_id),
    )
    response = await _issue_login_response_for_user(db, user)
    await db.commit()
    return response


async def _try_apaas_provider_login_response(
    user_data: UserLogin,
    db: AsyncSession,
) -> Optional[LoginResponse]:
    import httpx

    try:
        return await _try_apaas_login_flow(user_data, db)
    except httpx.RequestError as exc:
        logger.warning("aPaaS 登录链路网络异常 (%s): %s", type(exc).__name__, exc)
        if not _is_placeholder_apaas_base_url():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="aPaaS 登录链路暂不可用，请稍后重试",
            ) from exc
        return None
    except HTTPException:
        raise
    except IntegrityError as exc:
        await db.rollback()
        logger.exception("aPaaS 登录同步本地数据唯一约束冲突，已回滚")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="aPaaS 登录成功，但同步本地账号/租户数据时发生唯一约束冲突，请联系管理员检查租户或账号绑定",
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("aPaaS 登录同步本地数据库失败，已回滚")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="aPaaS 登录成功，但本地数据库同步失败，请稍后重试或联系管理员",
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("aPaaS 登录同步发生未预期异常，已回滚")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="aPaaS 登录链路返回异常数据或同步失败，请稍后重试",
        ) from exc


@router.get("/captcha")
async def captcha():
    if _auth_provider() != "control_plane" or not settings.control_plane_captcha_enabled:
        return {"required": False}
    return {"required": True, **(await fetch_dolphin_captcha())}


@router.post("/login", response_model=LoginResponse)
async def login(
    user_data: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    provider = _auth_provider()

    if provider == "local":
        return await _local_login_response(user_data, db)

    if provider == "control_plane":
        return await _control_plane_login_response(user_data, db)

    apaas_response = await _try_apaas_provider_login_response(user_data, db)
    if apaas_response:
        return apaas_response

    if provider == "apaas":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="aPaaS 登录失败",
        )

    return await _local_login_response(user_data, db)


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

    tenant = (
        await db.execute(
            select(Tenant).where(
                Tenant.id == data.tenant_id,
                Tenant.status == 1,
            )
        )
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=403, detail="目标租户不可用")

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

    本地兜底平台管理员可以切到任意 active 租户；aPaaS 登录用户仅限自己可登录的
    active membership。aPaaS 平台管理员的全量租户同步不等于拥有工作台登录权限。
    """
    if platform_admin_has_unscoped_tenant_access(ctx.user):
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
                select(UserTenant)
                .join(Tenant, Tenant.id == UserTenant.tenant_id)
                .where(
                    UserTenant.user_id == ctx.user.id,
                    UserTenant.tenant_id == data.tenant_id,
                    UserTenant.status == 1,
                    Tenant.status == 1,
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
