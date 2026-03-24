"""
Platform Environment API 路由 — 低代码平台环境管理
"""
from __future__ import annotations

import logging
from app.crypto import encrypt_password, decrypt_password
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import PlatformEnv
from app.deps import get_auth_context, AuthContext
from app.apaas_client import APaaSClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform-envs", tags=["platform-envs"])


# ============================================================
# 请求/响应模型
# ============================================================

class EnvCreate(BaseModel):
    env_name: str
    base_url: str
    platform_tenant_id: str
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None


class EnvUpdate(BaseModel):
    env_name: Optional[str] = None
    base_url: Optional[str] = None
    platform_tenant_id: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None


# ============================================================
# CRUD 接口
# ============================================================

@router.get("")
async def list_envs(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出当前租户的所有平台环境"""
    result = await db.execute(
        select(PlatformEnv)
        .where(PlatformEnv.tenant_id == ctx.tenant_id)
        .order_by(PlatformEnv.created_at.desc())
    )
    envs = result.scalars().all()
    return [
        {
            "id": e.id,
            "env_name": e.env_name,
            "base_url": e.base_url,
            "platform_tenant_id": e.platform_tenant_id,
            "username": e.username,
            "is_default": e.is_default,
            "status": e.status,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in envs
    ]


@router.post("")
async def create_env(
    data: EnvCreate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """创建平台环境"""
    env = PlatformEnv(
        tenant_id=ctx.tenant_id,
        env_name=data.env_name,
        base_url=data.base_url.rstrip("/"),
        platform_tenant_id=data.platform_tenant_id,
        username=data.username,
        password_enc=encrypt_password(data.password) if data.password else None,
        token=data.token,
        status="disconnected",
    )
    db.add(env)
    await db.commit()
    await db.refresh(env)
    return {"id": env.id, "env_name": env.env_name, "status": env.status}


@router.put("/{env_id}")
async def update_env(
    env_id: int,
    data: EnvUpdate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """更新平台环境"""
    result = await db.execute(
        select(PlatformEnv).where(
            PlatformEnv.id == env_id,
            PlatformEnv.tenant_id == ctx.tenant_id,
        )
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="环境不存在")

    if data.env_name is not None:
        env.env_name = data.env_name
    if data.base_url is not None:
        env.base_url = data.base_url.rstrip("/")
    if data.platform_tenant_id is not None:
        env.platform_tenant_id = data.platform_tenant_id
    if data.username is not None:
        env.username = data.username
    if data.password is not None:
        env.password_enc = encrypt_password(data.password)
    if data.token is not None:
        env.token = data.token

    await db.commit()
    return {"ok": True}


@router.delete("/{env_id}")
async def delete_env(
    env_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除平台环境"""
    result = await db.execute(
        select(PlatformEnv).where(
            PlatformEnv.id == env_id,
            PlatformEnv.tenant_id == ctx.tenant_id,
        )
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="环境不存在")

    await db.delete(env)
    await db.commit()
    return {"ok": True}


# ============================================================
# 连接管理
# ============================================================

@router.post("/{env_id}/test")
async def test_env(
    env_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """测试平台环境连接"""
    result = await db.execute(
        select(PlatformEnv).where(
            PlatformEnv.id == env_id,
            PlatformEnv.tenant_id == ctx.tenant_id,
        )
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="环境不存在")

    try:
        client = APaaSClient(
            base_url=env.base_url,
            tenant_id=env.platform_tenant_id,
            token=env.token,
        )
        await client.test_connection()
        env.status = "connected"
        await db.commit()
        return {"ok": True, "status": "connected"}
    except Exception as e:
        # Token 过期：尝试用保存的账号密码自动刷新
        if ("401" in str(e) or "Token" in str(e)) and env.username and env.password_enc:
            try:
                password = decrypt_password(env.password_enc)
                refresh_client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
                login_result = await refresh_client.login(env.username, password)
                new_token = login_result.get("token") if isinstance(login_result, dict) else None
                if new_token:
                    env.token = new_token
                    env.status = "connected"
                    await db.commit()
                    return {"ok": True, "status": "connected", "refreshed": True}
            except Exception:
                pass  # 刷新失败，继续走断开逻辑
        env.status = "disconnected"
        await db.commit()
        return {"ok": False, "status": "disconnected", "error": str(e)}


@router.post("/{env_id}/login")
async def login_env(
    env_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """用账号密码登录获取 token"""
    result = await db.execute(
        select(PlatformEnv).where(
            PlatformEnv.id == env_id,
            PlatformEnv.tenant_id == ctx.tenant_id,
        )
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="环境不存在")

    if not env.username or not env.password_enc:
        raise HTTPException(status_code=400, detail="未配置登录信息")

    try:
        password = decrypt_password(env.password_enc)
        client = APaaSClient(
            base_url=env.base_url,
            tenant_id=env.platform_tenant_id,
        )
        login_result = await client.login(env.username, password)
        token = login_result.get("token", "")
        if not token:
            raise Exception("登录返回中未包含 token")
        env.token = token
        env.status = "connected"
        await db.commit()
        return {"ok": True, "status": "connected"}
    except HTTPException:
        raise
    except Exception as e:
        env.status = "disconnected"
        await db.commit()
        raise HTTPException(status_code=400, detail=f"登录失败: {str(e)}")


@router.post("/{env_id}/set-default")
async def set_default(
    env_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """设为默认环境"""
    # 先取消所有默认
    all_envs_result = await db.execute(
        select(PlatformEnv).where(PlatformEnv.tenant_id == ctx.tenant_id)
    )
    for e in all_envs_result.scalars().all():
        e.is_default = (e.id == env_id)
    await db.commit()
    return {"ok": True}
