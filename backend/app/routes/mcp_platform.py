"""MCP Platform admin APIs.

MCP 平台：
- 管理多个 aPaaS 平台管理员账号；
- 后端用账号密码登录 aPaaS 换 xdaptoken；
- 前端刷新租户/用户时只调用本后端，不直接接触 xdaptoken。
"""
from __future__ import annotations

import base64
import asyncio
import os
import re
import time
import uuid
from datetime import datetime
from typing import Annotated, Any, Optional

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_password_hash
from app.config import settings
from app.crypto import decrypt_password, encrypt_password
from app.database import AsyncSessionLocal, get_db
from app.deps import AuthContext, get_auth_context
from app.models import APaaSPlatformCredential, MCPCallLog, PlatformEnv, Tenant, User
from app.schemas import LoginResponse, UserLogin


router = APIRouter(prefix="/mcp-platform", tags=["mcp-platform"])

DEFAULT_APAAS_RSA_PUBLIC_KEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAww3u+ffWA67sQ4UmSQruRQ3/"
    "N4vhI4M05+iKUfBk5+kBW8cWskgQPfiZk3PICJb6R1y9a5qomiO/KSKfIsxHDogVKAn+"
    "q2XJZQ5AH0GzDsNYPSYAQ6SOVfJ//g4UlrFZDEKymmEvCVcOEN5XDNTEM3rLMv2xI5204"
    "XOP2iOzODIWjqyPb8tcnZHVMDjAqDnaHPMScn4lVLwbEqs5IP8yHEMtLxGfNS9DVDY5Ep"
    "ZukvMV6bad6z/nikScN9KjskkzDKHfWQmZYqCna/EC3EIrkfA+6BuF38Y+VmVJ19eEdMS"
    "nzoEbYhk3dByM5gR7MwL+NjCbUJdUTNFf2A2Vjujl8QIDAQAB"
)
_RSA_PUBLIC_KEY_CACHE: dict[str, str] = {}

APAAS_BASE_URL = (settings.apaas_base_url or os.getenv("APAAS_BASE_URL") or "").rstrip("/")


class APaaSAdminCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    account: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    is_default: bool = False


class APaaSAdminUpdate(BaseModel):
    name: Optional[str] = None
    account: Optional[str] = None
    password: Optional[str] = None
    is_default: Optional[bool] = None


class APaaSUserTokenRequest(BaseModel):
    account: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    admin_id: Optional[str] = None


@router.post("/login", response_model=LoginResponse)
async def login_admin_spa_compat(
    user_data: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Compatibility login endpoint for older admin SPA bundles.

    Newer admin SPA builds call /auth/login. Some browsers may still have a
    cached bundle that posts to /mcp-platform/login, so keep this alias wired to
    the same backend auth flow.
    """
    from app.routes.auth import login as auth_login

    return await auth_login(user_data, db)


def _require_platform_admin(ctx: AuthContext) -> None:
    if ctx.user.is_platform_admin or ctx.tenant_role == "platform_admin":
        return
    raise HTTPException(status_code=403, detail="平台管理员才能访问")


async def _load_db_admins(db: AsyncSession) -> list[dict[str, Any]]:
    """Load platform admins from persisted DB credentials only."""
    cred_rows = await db.execute(
        select(APaaSPlatformCredential, User)
        .join(User, User.id == APaaSPlatformCredential.user_id)
        .order_by(APaaSPlatformCredential.is_default.desc(), APaaSPlatformCredential.id.asc())
    )
    admins: list[dict[str, Any]] = []
    for cred, user in cred_rows.all():
        admins.append({
            "id": f"db_platform_credential_{cred.id}",
            "name": cred.account,
            "base_url": _normalize_origin(cred.base_url),
            "account": cred.account,
            "password_enc": cred.password_enc,
            "is_default": bool(cred.is_default),
            "status": cred.status or "connected",
            "token": cred.token,
            "source": "db_platform_credential",
            "credential_id": cred.id,
            "user_id": user.id,
            "last_login_at": cred.last_login_at.isoformat(timespec="seconds") + "Z" if cred.last_login_at else None,
        })
    if admins and not any(item.get("is_default") for item in admins):
        credential_id = admins[0].get("credential_id")
        if credential_id:
            cred = (
                await db.execute(
                    select(APaaSPlatformCredential).where(APaaSPlatformCredential.id == credential_id)
                )
            ).scalar_one_or_none()
            if cred:
                cred.is_default = True
                await db.commit()
                admins[0]["is_default"] = True
    return admins


def append_mcp_call_log(record: dict[str, Any]) -> None:
    """Append one MCP gateway call log. Best-effort and token-safe."""
    safe = {
        "id": uuid.uuid4().hex[:12],
        "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        **record,
    }
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_persist_mcp_call_log(safe))
    except Exception:
        pass


async def _persist_mcp_call_log(record: dict[str, Any]) -> None:
    try:
        async with AsyncSessionLocal() as db:
            db.add(MCPCallLog(
                log_id=str(record.get("id") or uuid.uuid4().hex[:12]),
                service=record.get("service"),
                path=record.get("path"),
                rpc_method=record.get("rpc_method"),
                tool=record.get("tool"),
                request_params=record.get("request_params"),
                request_arguments=record.get("request_arguments"),
                request_headers=record.get("request_headers"),
                status_code=record.get("status_code"),
                success=bool(record.get("success", True)),
                error=record.get("error"),
                auth_source=record.get("auth_source"),
                apaas_tenant_id=str(record.get("apaas_tenant_id") or "") or None,
                apaas_user_id=str(record.get("apaas_user_id") or "") or None,
                local_user_id=record.get("local_user_id") or None,
                local_tenant_id=record.get("local_tenant_id") or None,
                elapsed_ms=int(record.get("elapsed_ms") or 0),
            ))
            await db.commit()
    except Exception:
        pass


async def _read_mcp_call_logs(db: AsyncSession, limit: int = 100) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(MCPCallLog)
            .order_by(MCPCallLog.created_at.desc(), MCPCallLog.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": row.log_id,
            "time": row.created_at.isoformat(timespec="seconds") + "Z",
            "service": row.service,
            "path": row.path,
            "rpc_method": row.rpc_method,
            "tool": row.tool,
            "request_params": row.request_params,
            "request_arguments": row.request_arguments,
            "request_headers": row.request_headers,
            "status_code": row.status_code,
            "success": row.success,
            "error": row.error,
            "auth_source": row.auth_source,
            "apaas_tenant_id": row.apaas_tenant_id,
            "apaas_user_id": row.apaas_user_id,
            "local_user_id": row.local_user_id,
            "local_tenant_id": row.local_tenant_id,
            "elapsed_ms": row.elapsed_ms,
        }
        for row in rows
    ]


def _public_admin(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "account": row.get("account"),
        "is_default": bool(row.get("is_default")),
        "has_password": bool(row.get("password_enc")),
        "has_token": bool(row.get("token")),
        "status": row.get("status") or ("connected" if row.get("token") else "disconnected"),
        "last_login_at": row.get("last_login_at"),
        "token_fingerprint": _fingerprint(row.get("token")),
    }


def _fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    return f"{value[:8]}...{value[-6:]}"


def _current_mcp_key() -> str:
    raw = (os.getenv("MCP_API_KEYS") or os.getenv("MCP_API_KEY") or "").strip()
    if not raw:
        return ""
    return next((item.strip() for item in raw.split(",") if item.strip()), "")


def _normalize_origin(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith("/backend"):
        base = base[:-len("/backend")]
    return base


def _api_base(base_url: str) -> str:
    return f"{_normalize_origin(base_url)}/backend"


def _admin_base(row: dict[str, Any]) -> str:
    return _normalize_origin(row.get("base_url") or APAAS_BASE_URL)


async def _get_apaas_rsa_public_key(base_url: str) -> str:
    origin = _normalize_origin(base_url)
    if origin in _RSA_PUBLIC_KEY_CACHE:
        return _RSA_PUBLIC_KEY_CACHE[origin]
    url = f"{origin}/platform/apaasRsa.pub"
    try:
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            resp = await client.get(url)
        resp.raise_for_status()
        key = resp.text.strip()
    except Exception:
        key = ""
    if not key:
        key = DEFAULT_APAAS_RSA_PUBLIC_KEY
    _RSA_PUBLIC_KEY_CACHE[origin] = key
    return key


def _encrypt_apaas_password(plain: str, rsa_public_key: str) -> str:
    key_bytes = base64.b64decode(rsa_public_key)
    public_key = serialization.load_der_public_key(key_bytes)
    cipher = public_key.encrypt(plain.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(cipher).decode("ascii")


def _headers(
    base_url: str,
    token: str | None = None,
    tenant_id: str | None = None,
    rsa_public_key: str | None = None,
) -> dict[str, str]:
    ts = str(int(time.time() * 1000))
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "origin": _normalize_origin(base_url),
        "referer": f"{_normalize_origin(base_url)}/platform/platform-admin/tenant-admin",
        "rsa-public-key": rsa_public_key or DEFAULT_APAAS_RSA_PUBLIC_KEY,
        "xdaptimestamp": ts,
        "xdaptenantid": "null" if tenant_id is None else tenant_id,
    }
    if token:
        headers["xdaptoken"] = token
    return headers


def _find_token(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("xdaptoken", "xdapToken", "token", "accessToken", "access_token"):
            value = payload.get(key)
            if isinstance(value, str) and value.count(".") >= 1:
                return value
        for value in payload.values():
            found = _find_token(value)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _find_token(item)
            if found:
                return found
    return None


async def _login_admin(row: dict[str, Any]) -> str:
    if not row.get("account") or not row.get("password_enc"):
        raise HTTPException(status_code=400, detail="请先绑定 aPaaS 管理员账号和密码")
    password = decrypt_password(row["password_enc"])
    ts = str(int(time.time() * 1000))
    base_url = _admin_base(row)
    rsa_public_key = await _get_apaas_rsa_public_key(base_url)
    url = f"{_api_base(base_url)}/xdap-admin/platform/apaasSystemAdmin/login?timestamp={ts}"
    body = {
        "type": "account",
        "account": row["account"],
        "password": _encrypt_apaas_password(password, rsa_public_key),
        "securityCode": "",
    }
    headers = _headers(base_url, tenant_id="", rsa_public_key=rsa_public_key)
    headers["referer"] = f"{_normalize_origin(base_url)}/platform/account/login"
    async with httpx.AsyncClient(timeout=20, verify=False) as client:
        resp = await client.post(url, headers=headers, json=body)
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}
    token = _find_token(payload)
    if not resp.is_success or not token:
        msg = payload.get("message") if isinstance(payload, dict) else None
        code = payload.get("code") if isinstance(payload, dict) else None
        hint = "请确认账号密码是 aPaaS 平台管理员的明文账号密码，不要填抓包里的加密 password。"
        raw_hint = f"（aPaaS 返回 code={code}）" if code else ""
        raise HTTPException(status_code=400, detail=f"aPaaS 登录失败：{msg or resp.text[:300]}{raw_hint}。{hint}")
    row["token"] = token
    row["status"] = "connected"
    row["last_login_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return token


def _select_admin(admins: list[dict[str, Any]], admin_id: str | None = None) -> dict[str, Any]:
    if admin_id:
        row = next((a for a in admins if a.get("id") == admin_id), None)
    else:
        row = next((a for a in admins if a.get("is_default")), None) or (admins[0] if admins else None)
    if not row:
        raise HTTPException(status_code=400, detail="请先添加 aPaaS 平台管理员账号")
    return row


async def _set_default_credential(db: AsyncSession, credential_id: int) -> None:
    await db.execute(APaaSPlatformCredential.__table__.update().values(is_default=False))
    cred = (
        await db.execute(
            select(APaaSPlatformCredential).where(APaaSPlatformCredential.id == credential_id)
        )
    ).scalar_one_or_none()
    if cred:
        cred.is_default = True


async def _sync_platform_user(db: AsyncSession, row: dict[str, Any], plain_password: str | None = None) -> None:
    account = (row.get("account") or "").strip()
    if not account:
        return
    base_url = _normalize_origin(_admin_base(row))
    result = await db.execute(select(User).where(User.username == account))
    user = result.scalar_one_or_none()
    if not user:
        if not plain_password:
            return
        user = User(
            username=account,
            hashed_password=get_password_hash(plain_password),
            is_platform_admin=True,
            is_active=True,
        )
        db.add(user)
    else:
        if plain_password:
            user.hashed_password = get_password_hash(plain_password)
        user.is_platform_admin = True
        user.is_active = True
    user.apaas_base_url = base_url
    if row.get("token"):
        user.apaas_token = row["token"]
    await db.flush()

    password_enc = row.get("password_enc") or (encrypt_password(plain_password) if plain_password else None)
    if password_enc:
        cred = None
        credential_id = row.get("credential_id")
        if credential_id:
            cred = (
                await db.execute(
                    select(APaaSPlatformCredential).where(APaaSPlatformCredential.id == credential_id)
                )
            ).scalar_one_or_none()
        if not cred:
            cred = (
                await db.execute(
                    select(APaaSPlatformCredential).where(
                        APaaSPlatformCredential.user_id == user.id,
                        APaaSPlatformCredential.base_url == base_url,
                        APaaSPlatformCredential.account == account,
                    )
                )
            ).scalar_one_or_none()
        if not cred:
            cred = APaaSPlatformCredential(
                user_id=user.id,
                base_url=base_url,
                account=account,
                password_enc=password_enc,
            )
            db.add(cred)
        else:
            cred.base_url = base_url
            cred.account = account
            cred.password_enc = password_enc
        if row.get("is_default"):
            await db.execute(APaaSPlatformCredential.__table__.update().values(is_default=False))
            cred.is_default = True
        if row.get("token"):
            cred.token = row["token"]
        cred.status = row.get("status") or ("connected" if row.get("token") else "disconnected")
        cred.last_login_at = datetime.utcnow() if row.get("token") else cred.last_login_at
        cred.last_error = None
    await db.commit()


@router.get("/apaas-admins")
async def list_apaas_admins(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_platform_admin(ctx)
    admins = await _load_db_admins(db)
    return {"items": [_public_admin(x) for x in admins]}


@router.get("/mcp-access")
async def get_mcp_access(ctx: Annotated[AuthContext, Depends(get_auth_context)]):
    _require_platform_admin(ctx)
    key = _current_mcp_key()
    return {
        "key": key,
        "fingerprint": _fingerprint(key),
        "services": [
            {"name": "主工具服务", "code": "apaas-builder-mcp", "url": "/api/mcp/mcp", "tools": 33},
            {"name": "Builder 场景服务", "code": "apaas-builder-config", "url": "/api/mcp-builder/mcp", "tools": 14},
            {"name": "Coding 工作区服务", "code": "apaas-builder-coding", "url": "/api/mcp-coding/mcp", "tools": 23},
            {"name": "Vibe 开发服务", "code": "apaas-builder-vibe", "url": "/api/mcp-vibe/mcp", "tools": 9},
            {"name": "设计解析服务", "code": "apaas-builder-design", "url": "/api/mcp-design/mcp", "tools": 4},
        ],
    }


@router.get("/call-logs")
async def list_mcp_call_logs(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=500),
):
    _require_platform_admin(ctx)
    return {"items": await _read_mcp_call_logs(db, limit)}


@router.post("/apaas-admins")
async def create_apaas_admin(
    body: APaaSAdminCreate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_platform_admin(ctx)
    admins = await _load_db_admins(db)
    row = {
        "id": uuid.uuid4().hex[:12],
        "name": body.name.strip(),
        "base_url": _normalize_origin(APAAS_BASE_URL),
        "account": body.account.strip(),
        "password_enc": encrypt_password(body.password),
        "is_default": bool(body.is_default) or not admins,
        "status": "disconnected",
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    await _sync_platform_user(db, row, body.password)
    admins = await _load_db_admins(db)
    saved = next((item for item in admins if item.get("account") == row["account"]), row)
    return _public_admin(saved)


@router.put("/apaas-admins/{admin_id}")
async def update_apaas_admin(
    admin_id: str,
    body: APaaSAdminUpdate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_platform_admin(ctx)
    admins = await _load_db_admins(db)
    row = _select_admin(admins, admin_id)
    if body.name is not None:
        row["name"] = body.name.strip()
    if body.account is not None:
        row["account"] = body.account.strip()
        row.pop("token", None)
        row["status"] = "disconnected"
    if body.password is not None:
        row["password_enc"] = encrypt_password(body.password)
        row.pop("token", None)
        row["status"] = "disconnected"
    if body.is_default is not None:
        row["is_default"] = bool(body.is_default)
    await _sync_platform_user(db, row, body.password)
    admins = await _load_db_admins(db)
    saved = next((item for item in admins if item.get("credential_id") == row.get("credential_id")), row)
    return _public_admin(saved)


@router.delete("/apaas-admins/{admin_id}")
async def delete_apaas_admin(
    admin_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_platform_admin(ctx)
    admins = await _load_db_admins(db)
    target = next((a for a in admins if a.get("id") == admin_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    deleted_was_default = bool(target.get("is_default"))
    if target.get("credential_id"):
        cred = (
            await db.execute(
                select(APaaSPlatformCredential).where(APaaSPlatformCredential.id == target["credential_id"])
            )
        ).scalar_one_or_none()
        if cred:
            await db.delete(cred)
            await db.commit()
    if deleted_was_default:
        remaining = await _load_db_admins(db)
        if remaining and remaining[0].get("credential_id"):
            await _set_default_credential(db, remaining[0]["credential_id"])
            await db.commit()
    return {"ok": True}


@router.post("/apaas-admins/{admin_id}/login")
async def login_apaas_admin(
    admin_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_platform_admin(ctx)
    admins = await _load_db_admins(db)
    row = _select_admin(admins, admin_id)
    await _login_admin(row)
    await _sync_platform_user(db, row)
    admins = await _load_db_admins(db)
    saved = next((item for item in admins if item.get("credential_id") == row.get("credential_id")), row)
    return _public_admin(saved)


@router.post("/apaas-admins/{admin_id}/token")
async def get_apaas_admin_token(
    admin_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_platform_admin(ctx)
    admins = await _load_db_admins(db)
    row = _select_admin(admins, admin_id)
    token = row.get("token") or await _login_admin(row)
    await _sync_platform_user(db, row)
    return {
        "token": token,
        "fingerprint": _fingerprint(token),
        "admin": _public_admin(row),
    }


@router.post("/apaas-user-token")
async def get_apaas_user_token(
    body: APaaSUserTokenRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_platform_admin(ctx)
    admins = await _load_db_admins(db)
    admin = _select_admin(admins, body.admin_id)
    base_url = _admin_base(admin)
    rsa_public_key = await _get_apaas_rsa_public_key(base_url)
    ts = str(int(time.time() * 1000))
    url = f"{_api_base(base_url)}/xdap-admin/user/login?timestamp={ts}"
    headers = _headers(base_url, tenant_id=body.tenant_id, rsa_public_key=rsa_public_key)
    headers["referer"] = f"{_normalize_origin(base_url)}/platform/account/login"
    payload = {
        "type": "account",
        "account": body.account.strip(),
        "password": _encrypt_apaas_password(body.password, rsa_public_key),
        "tenantId": body.tenant_id.strip(),
        "loginType": "MANAGE",
        "securityCode": "",
    }
    async with httpx.AsyncClient(timeout=20, verify=False) as client:
        resp = await client.post(url, headers=headers, json=payload)
    try:
        result = resp.json()
    except Exception:
        result = {"raw": resp.text}
    token = _find_token(result)
    if not resp.is_success or not token:
        msg = result.get("message") if isinstance(result, dict) else None
        code = result.get("code") if isinstance(result, dict) else None
        raw_hint = f"（aPaaS 返回 code={code}）" if code else ""
        raise HTTPException(
            status_code=400,
            detail=f"租户用户登录失败：{msg or resp.text[:300]}{raw_hint}。请填写该租户管理员的明文密码。",
        )
    resolved_tenant_id = body.tenant_id.strip()
    token_info = None
    try:
        from app.services.apaas_token_validator import validate_apaas_token
        token_info = await validate_apaas_token(token, _api_base(base_url), resolved_tenant_id)
        tenants = (token_info or {}).get("tenants") or []
        tenant_ids = [str(t.get("tenantId") or t.get("id") or "") for t in tenants if isinstance(t, dict)]
        if resolved_tenant_id not in tenant_ids and tenant_ids:
            resolved_tenant_id = tenant_ids[0]
    except Exception:
        token_info = None

    # 立刻用同一 token + tenantId 探测 xdap-app，避免 MCP 调用时才暴露 401。
    app_api_ok = False
    app_api_error = ""
    try:
        async with httpx.AsyncClient(timeout=20, verify=False) as client:
            probe = await client.get(
                f"{_api_base(base_url)}/xdap-app/apaasApplications/queryAppList",
                headers={
                    "xdaptoken": token,
                    "xdaptenantid": resolved_tenant_id,
                    "xdaptimestamp": str(int(time.time() * 1000)),
                    "Content-Type": "application/json",
                },
                params={"page": 1, "pageSize": 1, "keyword": "", "status": ""},
            )
        app_api_ok = probe.status_code == 200
        if not app_api_ok:
            app_api_error = f"HTTP {probe.status_code}: {probe.text[:300]}"
    except Exception as exc:
        app_api_error = str(exc)
    return {
        "token": token,
        "fingerprint": _fingerprint(token),
        "tenant_id": resolved_tenant_id,
        "account": body.account.strip(),
        "app_api_ok": app_api_ok,
        "app_api_error": app_api_error,
        "tenant_candidates": (token_info or {}).get("tenants") or [],
    }


@router.get("/apaas-tenants")
async def list_apaas_tenants(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    admin_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
    keyword: str = "",
    local_only: bool = False,
):
    _require_platform_admin(ctx)
    if local_only:
        stmt = (
            select(Tenant, PlatformEnv)
            .outerjoin(
                PlatformEnv,
                (PlatformEnv.tenant_id == Tenant.id) & (PlatformEnv.is_default == True),  # noqa: E712
            )
            .order_by(Tenant.updated_at.desc())
            .limit(max(1, min(page_size, 500)))
        )
        if keyword:
            kw = f"%{keyword.strip()}%"
            stmt = stmt.where(
                (Tenant.tenant_name.like(kw))
                | (Tenant.tenant_code.like(kw))
                | (Tenant.apaas_tenant_id_str.like(kw))
            )
        rows = (await db.execute(stmt)).all()
        items = []
        for tenant, env in rows:
            items.append({
                "localTenantId": tenant.id,
                "tenantName": tenant.tenant_name,
                "tenantCode": tenant.tenant_code,
                "tenantId": tenant.apaas_tenant_id_str or "",
                "status": "ENABLE" if tenant.status == 1 else "DISABLE",
                "platformEnvId": env.id if env else None,
                "platformEnvName": env.env_name if env else "",
                "platformEnvStatus": env.status if env else "",
                "adminList": [],
                "source": "local",
            })
        return {"items": items, "source": "local", "synced": None}

    admins = await _load_db_admins(db)
    row = _select_admin(admins, admin_id)
    token = row.get("token") or await _login_admin(row)
    await _sync_platform_user(db, row)
    ts = str(int(time.time() * 1000))
    base_url = _admin_base(row)
    rsa_public_key = await _get_apaas_rsa_public_key(base_url)
    url = f"{_api_base(base_url)}/xdap-admin/platform/query/tenantList?timestamp={ts}"
    headers = _headers(base_url, token=token, rsa_public_key=rsa_public_key)
    body = {"page": page, "pageSize": page_size, "keyword": keyword}
    async with httpx.AsyncClient(timeout=20, verify=False) as client:
        resp = await client.post(url, headers=headers, json=body)
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}
    if not resp.is_success or (isinstance(payload, dict) and payload.get("code") == "error"):
        # token 过期时重登一次再试
        token = await _login_admin(row)
        headers = _headers(base_url, token=token, rsa_public_key=rsa_public_key)
        async with httpx.AsyncClient(timeout=20, verify=False) as client:
            resp = await client.post(url, headers=headers, json=body)
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw": resp.text}
    if not resp.is_success:
        raise HTTPException(status_code=400, detail=f"获取 aPaaS 租户失败：{resp.text[:300]}")
    items = _extract_items(payload)
    sync_result = await _sync_apaas_tenants_to_local(db, row, items)
    return {
        "admin": _public_admin(row),
        "raw": payload,
        "items": items,
        "synced": sync_result,
    }


def _extract_items(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "records", "rows", "items", "table", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    for key in ("list", "records", "rows", "items", "table"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _tenant_status_enabled(value: Any) -> bool:
    if value in (1, "1", True):
        return True
    text = str(value or "").strip().lower()
    return text in {"enable", "enabled", "active", "normal", "启用"}


def _normalize_tenant_code(value: str, fallback: str) -> str:
    code = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip().lower()).strip("-_")
    if not code:
        code = f"apaas-{fallback[-8:]}" if fallback else f"apaas-{uuid.uuid4().hex[:8]}"
    return code[:60]


async def _resolve_unique_tenant_code(db: AsyncSession, preferred: str, platform_tenant_id: str) -> str:
    base = _normalize_tenant_code(preferred, platform_tenant_id)
    candidate = base
    idx = 2
    while True:
        existing = (
            await db.execute(select(Tenant).where(Tenant.tenant_code == candidate))
        ).scalar_one_or_none()
        if not existing or existing.apaas_tenant_id_str in (None, "", platform_tenant_id):
            return candidate
        suffix = f"-{platform_tenant_id[-6:]}" if idx == 2 and platform_tenant_id else f"-{idx}"
        candidate = f"{base[:60-len(suffix)]}{suffix}"
        idx += 1


async def _sync_apaas_tenants_to_local(
    db: AsyncSession,
    admin: dict[str, Any],
    items: list[Any],
) -> dict[str, int]:
    """Persist aPaaS tenant list as local Tenant + default PlatformEnv rows.

    The admin tenant page is still a live aPaaS view, but refresh must create the
    local binding used later by workspaces/applications: local tenant_id for
    isolation and platform_env_id/platform_tenant_id for APaaS calls.
    """
    from app.seed_data import seed_default_roles

    synced_tenants = 0
    synced_envs = 0
    # PlatformEnv.base_url 必须是 API base（含 /backend）— APaaSClient 用法是 base_url + "/xdap-app/..."。
    # _normalize_origin 会 strip /backend，那是给 RSA pub key + login 等"前端 origin 请求"用的，不是给 PlatformEnv 存。
    # 之前 bug：trial 同步进来的 PlatformEnv.base_url 漏 /backend，import-from-platform 调 query_app_detail 报 404。
    raw_admin_base = (admin.get("base_url") or APAAS_BASE_URL).strip().rstrip("/")
    base_url = raw_admin_base if raw_admin_base.endswith("/backend") else f"{raw_admin_base}/backend"
    admin_account = (admin.get("account") or "").strip() or None
    password_enc = admin.get("password_enc")

    for raw in items:
        if not isinstance(raw, dict):
            continue
        platform_tid = str(_pick(raw, "tenantId", "tenant_id", "id") or "").strip()
        if not platform_tid:
            continue
        tenant_name = str(_pick(raw, "tenantName", "tenant_name", "name") or platform_tid).strip()
        preferred_code = str(_pick(raw, "tenantCode", "tenant_code", "code") or tenant_name or platform_tid)
        enabled = _tenant_status_enabled(_pick(raw, "status", "state"))

        tenant = (
            await db.execute(select(Tenant).where(Tenant.apaas_tenant_id_str == platform_tid))
        ).scalar_one_or_none()
        if not tenant:
            legacy_code = _normalize_tenant_code(preferred_code, platform_tid)
            legacy = (
                await db.execute(select(Tenant).where(Tenant.tenant_code == legacy_code))
            ).scalar_one_or_none()
            if legacy and not legacy.apaas_tenant_id_str:
                tenant = legacy
                tenant.apaas_tenant_id_str = platform_tid
        if not tenant:
            tenant_code = await _resolve_unique_tenant_code(db, preferred_code, platform_tid)
            tenant = Tenant(
                tenant_name=tenant_name,
                tenant_code=tenant_code,
                status=1 if enabled else 0,
                apaas_tenant_id_str=platform_tid,
            )
            db.add(tenant)
            await db.flush()
            await seed_default_roles(db, tenant.id, commit=False)
        else:
            tenant.tenant_name = tenant_name
            tenant.status = 1 if enabled else 0
        synced_tenants += 1

        env = (
            await db.execute(
                select(PlatformEnv).where(
                    PlatformEnv.tenant_id == tenant.id,
                    PlatformEnv.platform_tenant_id == platform_tid,
                )
            )
        ).scalar_one_or_none()
        if not env:
            alias = _normalize_tenant_code(preferred_code, platform_tid)
            alias_conflict = (
                await db.execute(select(PlatformEnv).where(PlatformEnv.alias == alias))
            ).scalar_one_or_none()
            env = PlatformEnv(
                tenant_id=tenant.id,
                env_name=tenant_name,
                alias=None if alias_conflict else alias,
                base_url=base_url,
                platform_tenant_id=platform_tid,
                username=admin_account,
                password_enc=password_enc,
                is_default=True,
                status="disconnected",
            )
            db.add(env)
        else:
            env.env_name = tenant_name
            env.base_url = base_url
            env.platform_tenant_id = platform_tid
            if admin_account:
                env.username = admin_account
            if password_enc:
                env.password_enc = password_enc
        synced_envs += 1

    await db.commit()
    return {"tenants": synced_tenants, "envs": synced_envs}
