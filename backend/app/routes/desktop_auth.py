"""桌面产品登录路由。与 /api/auth/login 的 aPaaS 链路完全分开。

- authority 模式(公网, 未配 public_account_base_url): 校验本地桌面账号密码, 签本地 JWT。
- federation 模式(桌面 sidecar): 见后续任务。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.database import get_db
from app.deps import get_auth_context, AuthContext, resolve_default_tenant_id_for_user
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
