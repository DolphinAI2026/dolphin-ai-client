from __future__ import annotations
from typing import Annotated, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import APaaSUserCredential, User
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
