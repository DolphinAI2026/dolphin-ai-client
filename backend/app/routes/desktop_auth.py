"""桌面产品登录路由。与 /api/auth/login 的 aPaaS 链路完全分开。

- authority 模式(公网, 未配 public_account_base_url): 校验本地桌面账号密码, 签本地 JWT。
- federation 模式(桌面 sidecar, 配了 public_account_base_url): 转发公网认证 + 本地镜像 user/tenant + 签本地 JWT。
"""
import logging
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, get_password_hash, _DESKTOP_ISSUER
from app.config import settings
from app.database import get_db
from app.deps import get_auth_context, AuthContext, resolve_default_tenant_id_for_user
from app.models import User
from app import desktop_accounts as da

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/desktop-auth", tags=["desktop-auth"])


class DesktopLoginIn(BaseModel):
    username: str
    password: str


class DesktopLoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


async def _remote_authenticate(base_url: str, username: str, password: str):
    """转发到公网 authority 校验; 通过返回 {username,...}, 失败 None, 不可达抛 503。"""
    url = base_url.rstrip("/") + "/api/desktop-auth/login"
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            resp = await c.post(url, json={"username": username, "password": password})
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="公网账号服务不可达")
    if resp.status_code == 401:
        return None
    try:
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPStatusError, ValueError):
        # 公网返回非 401 的错误状态 / 非 JSON 体 → 转 502, 别把裸 500 甩给客户端。
        raise HTTPException(status_code=502, detail="公网账号服务响应异常")
    return {"username": body.get("username", username)}


async def _federation_login(db: AsyncSession, data: DesktopLoginIn, base_url: str) -> DesktopLoginOut:
    remote = await _remote_authenticate(base_url, data.username, data.password)
    if not remote:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    # 本地镜像该用户(+独立租户); 已存在则复用。本地密码随机(从不本地校验, 认证由公网做)。
    # 必须加 account_source 过滤: aPaaS 登录可能同步同名 apaas 行, 不过滤会 MultipleResultsFound。
    user = (await db.execute(
        select(User).where(User.username == remote["username"], User.account_source == "desktop")
    )).scalar_one_or_none()
    if user is None:
        user = await da.provision_desktop_account(db, remote["username"], secrets.token_urlsafe(32))
        await db.commit()
    tenant_id = await resolve_default_tenant_id_for_user(db, user.id)
    if tenant_id is None:
        raise HTTPException(status_code=500, detail="账号租户配置异常")
    token = create_access_token(user, tenant_id=tenant_id, issuer=_DESKTOP_ISSUER)
    return DesktopLoginOut(access_token=token, username=user.username)


async def _authority_login(db: AsyncSession, data: DesktopLoginIn) -> DesktopLoginOut:
    user = await da.verify_desktop_account(db, data.username, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    tenant_id = await resolve_default_tenant_id_for_user(db, user.id)
    if tenant_id is None:
        # 认证成功但无默认租户=数据异常; 让它在登录时就响, 别发个无 tenant 的残废 token。
        raise HTTPException(status_code=500, detail="账号租户配置异常，请联系管理员")
    token = create_access_token(user, tenant_id=tenant_id)
    return DesktopLoginOut(access_token=token, username=user.username)


@router.post("/login", response_model=DesktopLoginOut)
async def desktop_login(data: DesktopLoginIn, db: AsyncSession = Depends(get_db)):
    base_url = settings.public_account_base_url
    if base_url:
        return await _federation_login(db, data, base_url)
    return await _authority_login(db, data)


class CreateAccountIn(BaseModel):
    username: str
    password: str


class CreateAccountOut(BaseModel):
    username: str
    tenant_id: int


@router.post("/admin/accounts", response_model=CreateAccountOut)
async def admin_create_account(
    data: CreateAccountIn,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    """平台管理员开桌面账号。仅 is_platform_admin=True 的用户可调用。"""
    if not ctx.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="仅平台管理员可开桌面账号")
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    try:
        user = await da.provision_desktop_account(db, data.username, data.password)
    except da.AccountExistsError:
        raise HTTPException(status_code=409, detail="账号已存在")
    await db.commit()
    tid = await resolve_default_tenant_id_for_user(db, user.id)
    if tid is None:
        # provision 总会建租户+membership; 走到 None 即数据异常, 别用 0 掩盖。
        raise HTTPException(status_code=500, detail="新账号租户创建异常")
    return CreateAccountOut(username=user.username, tenant_id=tid)


class AccountItem(BaseModel):
    id: int
    username: str
    is_active: bool
    is_platform_admin: bool
    tenant_id: int | None


@router.get("/admin/accounts", response_model=list[AccountItem])
async def admin_list_accounts(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    """平台管理员列出所有桌面账号。仅 is_platform_admin=True 可调用。"""
    if not ctx.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="仅平台管理员可管理桌面账号")
    users = (await db.execute(
        select(User).where(User.account_source == "desktop").order_by(User.id.asc())
    )).scalars().all()
    items = []
    for u in users:
        tid = await resolve_default_tenant_id_for_user(db, u.id)
        items.append(AccountItem(
            id=u.id,
            username=u.username,
            is_active=u.is_active,
            is_platform_admin=u.is_platform_admin,
            tenant_id=tid,
        ))
    return items


class AccountPatchIn(BaseModel):
    action: str  # "disable" | "enable" | "reset_password"
    password: str | None = None  # action=reset_password 时必填, 至少 8 位


class AccountPatchOut(BaseModel):
    username: str
    is_active: bool


@router.patch("/admin/accounts/{username}", response_model=AccountPatchOut)
async def admin_patch_account(
    username: str,
    data: AccountPatchIn,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    """平台管理员改密 / 停用 / 启用桌面账号。仅 is_platform_admin=True 可调用。"""
    if not ctx.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="仅平台管理员可管理桌面账号")
    user = (await db.execute(
        select(User).where(User.username == username, User.account_source == "desktop")
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if data.action == "disable":
        user.is_active = False
    elif data.action == "enable":
        user.is_active = True
    elif data.action == "reset_password":
        if not data.password or len(data.password) < 8:
            raise HTTPException(status_code=400, detail="密码至少 8 位")
        user.hashed_password = get_password_hash(data.password)
    else:
        raise HTTPException(status_code=400, detail="不支持的操作")
    await db.commit()
    return AccountPatchOut(username=user.username, is_active=user.is_active)
