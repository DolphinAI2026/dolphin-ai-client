from __future__ import annotations
from typing import Annotated, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import User
from app.models.tenant import Tenant
from app.auth import get_current_user
from app.deps import AuthContext, get_auth_context
from app.apaas_client import APaaSClient

router = APIRouter(prefix="/apaas", tags=["得帆云平台"])


class APaaSLoginRequest(BaseModel):
    username: str
    password: str
    base_url: Optional[str] = None
    tenant_id: Optional[str] = None


class APaaSTokenConnect(BaseModel):
    token: str
    base_url: Optional[str] = None
    tenant_id: Optional[str] = None


class APaaSEmbedCredentials(BaseModel):
    connected: bool
    apaas_token: Optional[str] = None
    apaas_tenant_id: Optional[str] = None


@router.post("/login")
async def apaas_login(
    data: APaaSLoginRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """用户名密码登录得帆云平台，获取token"""
    client = APaaSClient(base_url=data.base_url, tenant_id=data.tenant_id)
    try:
        result = await client.login(data.username, data.password)
        token = result.get("token", "")
        # 保存token到用户记录
        current_user.apaas_token = token
        current_user.apaas_base_url = data.base_url or client.base_url
        current_user.apaas_tenant_id = data.tenant_id or client.tenant_id
        user_info = result.get("user", {})
        current_user.apaas_user_id = str(user_info.get("id", ""))
        await db.commit()
        return {"status": "ok", "token": token, "user_id": user_info.get("id")}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/connect")
async def apaas_connect(
    data: APaaSTokenConnect,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """用已有token连接得帆云平台，验证token有效性"""
    client = APaaSClient(base_url=data.base_url, tenant_id=data.tenant_id, token=data.token)
    try:
        await client.test_connection()
        # 保存token和环境信息
        current_user.apaas_token = data.token
        current_user.apaas_base_url = data.base_url or client.base_url
        current_user.apaas_tenant_id = data.tenant_id or client.tenant_id
        await db.commit()
        return {"status": "ok", "message": "连接成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接失败: {e}")


@router.get("/status")
async def apaas_status(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """检查当前用户是否已连接得帆云平台"""
    connected = bool(current_user.apaas_token)
    return {"connected": connected}


@router.get("/embed-credentials", response_model=APaaSEmbedCredentials)
async def apaas_embed_credentials(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """返回当前登录用户用于嵌入式助手的 aPaaS 凭证。"""
    token = (ctx.user.apaas_token or "").strip()
    tenant_id = (ctx.apaas_tenant_id or ctx.user.apaas_tenant_id or "").strip()

    if not tenant_id and ctx.tenant_id:
        result = await db.execute(select(Tenant.apaas_tenant_id_str).where(Tenant.id == ctx.tenant_id))
        tenant_id = (result.scalar_one_or_none() or "").strip()

    if not token or not tenant_id:
        return APaaSEmbedCredentials(connected=False)

    return APaaSEmbedCredentials(
        connected=True,
        apaas_token=token,
        apaas_tenant_id=tenant_id,
    )
