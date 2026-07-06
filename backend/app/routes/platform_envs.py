"""
Platform Environment API 路由 — 低代码平台环境管理
"""
from __future__ import annotations

import logging
from app.crypto import encrypt_password, decrypt_password
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Application, PlatformEnv
from app.deps import AuthContext, require_tenant_admin, resolve_effective_tenant_id
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
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出当前租户的所有平台环境.

    Response also carries computed fields used by /runtime envs tab v2:
      - `health`         — 'ok' | 'warn' | 'error' (derived from `status`)
      - `heartbeat`      — relative time placeholder (default '—')
      - `deployed_apps`  — count of Application rows bound to this env
      - `key_expiry`     — API-key expiry placeholder (default '—')
      - `key_warn`       — whether key is near expiry (default False)
      - `tenant_name`    — display name placeholder (default '')
      - `endpoint`       — alias of `base_url` for consumers that want it
      - `alias`          — placeholder alias (currently same as env id)
    Defaults are returned when the underlying source isn't yet wired —
    the shape matches `frontend/src/api/runtimeEnv.ts`.
    """
    tenant_id = await resolve_effective_tenant_id(db, ctx)
    result = await db.execute(
        select(PlatformEnv)
        .where(PlatformEnv.tenant_id == tenant_id)
        .order_by(PlatformEnv.created_at.desc())
    )
    envs = result.scalars().all()

    # Compute deployed_apps counts in one round-trip.
    env_ids = [e.id for e in envs]
    deployed_counts: dict[int, int] = {}
    if env_ids:
        count_rows = await db.execute(
            select(Application.platform_env_id, func.count(Application.id))
            .where(
                Application.tenant_id == tenant_id,
                Application.platform_env_id.in_(env_ids),
            )
            .group_by(Application.platform_env_id)
        )
        for env_id, cnt in count_rows.all():
            if env_id is not None:
                deployed_counts[int(env_id)] = int(cnt or 0)

    def _health_from_status(status: str) -> str:
        if status == "connected":
            return "ok"
        if status == "disconnected":
            return "warn"
        return "error"

    return [
        {
            "id": e.id,
            "env_name": e.env_name,
            "name": e.env_name,  # alias for v2 page
            "base_url": e.base_url,
            "endpoint": e.base_url,  # alias for v2 page
            "platform_tenant_id": e.platform_tenant_id,
            "tenant_name": "",  # not yet tracked — placeholder
            "username": e.username,
            "is_default": e.is_default,
            "status": e.status,
            "health": _health_from_status(e.status),
            "heartbeat": "—",  # last_test_at not yet tracked
            "deployed_apps": deployed_counts.get(e.id, 0),
            "key_expiry": "—",  # api-key expiry not yet tracked
            "key_warn": False,
            "alias": str(e.id),  # placeholder until env aliases land
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in envs
    ]


@router.post("")
async def create_env(
    data: EnvCreate,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """创建平台环境"""
    tenant_id = await resolve_effective_tenant_id(db, ctx)
    env = PlatformEnv(
        tenant_id=tenant_id,
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
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """更新平台环境"""
    tenant_id = await resolve_effective_tenant_id(db, ctx)
    result = await db.execute(
        select(PlatformEnv).where(
            PlatformEnv.id == env_id,
            PlatformEnv.tenant_id == tenant_id,
        )
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="环境不存在")

    # 跟踪关键字段是否变更（需要重新登录）
    need_relogin = False

    if data.env_name is not None:
        env.env_name = data.env_name
    if data.base_url is not None and data.base_url.rstrip("/") != env.base_url:
        env.base_url = data.base_url.rstrip("/")
        need_relogin = True
    if data.platform_tenant_id is not None and data.platform_tenant_id != env.platform_tenant_id:
        env.platform_tenant_id = data.platform_tenant_id
        need_relogin = True
    if data.username is not None:
        if data.username != env.username:
            need_relogin = True
        env.username = data.username
    if data.password is not None:
        env.password_enc = encrypt_password(data.password)
        need_relogin = True
    if data.token is not None:
        env.token = data.token
        need_relogin = False  # 直接提供了新 token

    # 关键字段变更后，旧 token 无效，必须清空并重新登录
    if need_relogin:
        env.token = None
        env.status = "disconnected"

    await db.commit()

    # 如果需要重新登录且有账号密码，自动尝试登录
    if need_relogin and env.username and env.password_enc:
        try:
            password = decrypt_password(env.password_enc)
            client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
            login_result = await client.login(env.username, password)
            token = login_result.get("token", "")
            if token:
                env.token = token
                env.status = "connected"
                await db.commit()
        except Exception:
            pass  # 自动登录失败，用户需要手动点登录

    return {"ok": True, "need_relogin": need_relogin, "status": env.status}


@router.delete("/{env_id}")
async def delete_env(
    env_id: int,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除平台环境"""
    tenant_id = await resolve_effective_tenant_id(db, ctx)
    result = await db.execute(
        select(PlatformEnv).where(
            PlatformEnv.id == env_id,
            PlatformEnv.tenant_id == tenant_id,
        )
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="环境不存在")

    linked_count_result = await db.execute(
        select(func.count(Application.id)).where(
            Application.tenant_id == tenant_id,
            Application.platform_env_id == env_id,
        )
    )
    linked_count = int(linked_count_result.scalar_one() or 0)
    if linked_count:
        await db.execute(
            update(Application)
            .where(
                Application.tenant_id == tenant_id,
                Application.platform_env_id == env_id,
            )
            .values(platform_env_id=None)
        )

    await db.delete(env)
    await db.commit()
    return {"ok": True, "unlinked_applications": linked_count}


# ============================================================
# 连接管理
# ============================================================

@router.post("/{env_id}/test")
async def test_env(
    env_id: int,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """测试平台环境连接"""
    tenant_id = await resolve_effective_tenant_id(db, ctx)
    result = await db.execute(
        select(PlatformEnv).where(
            PlatformEnv.id == env_id,
            PlatformEnv.tenant_id == tenant_id,
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
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """用账号密码登录获取 token"""
    tenant_id = await resolve_effective_tenant_id(db, ctx)
    result = await db.execute(
        select(PlatformEnv).where(
            PlatformEnv.id == env_id,
            PlatformEnv.tenant_id == tenant_id,
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
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """设为默认环境"""
    tenant_id = await resolve_effective_tenant_id(db, ctx)
    # 先取消所有默认
    all_envs_result = await db.execute(
        select(PlatformEnv).where(PlatformEnv.tenant_id == tenant_id)
    )
    for e in all_envs_result.scalars().all():
        e.is_default = (e.id == env_id)
    await db.commit()
    return {"ok": True}


# ============================================================
# 平台应用列表（供导入使用）
# ============================================================

@router.get("/{env_id}/remote-apps")
async def list_remote_apps(
    env_id: int,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出平台上可导入的应用列表（排除已导入的）"""
    from app.models import Application

    tenant_id = await resolve_effective_tenant_id(db, ctx)
    result = await db.execute(
        select(PlatformEnv).where(
            PlatformEnv.id == env_id,
            PlatformEnv.tenant_id == tenant_id,
        )
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="环境不存在")

    token = env.token or getattr(ctx.user, "apaas_token", None)
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
            raise HTTPException(status_code=400, detail=f"登录平台失败: {e}")
    if not token:
        raise HTTPException(status_code=400, detail="当前用户平台 token 不可用，请重新登录")

    # 自动刷新 token
    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=token)
    try:
        remote_apps = await client.query_app_list()
    except Exception:
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
                remote_apps = await client.query_app_list()
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"查询平台应用失败: {e}")
        else:
            raise HTTPException(status_code=400, detail="token 过期且无登录凭据")

    # 查询已导入的 apaas_app_id
    imported_result = await db.execute(
        select(Application.apaas_app_id).where(
            Application.tenant_id == tenant_id,
            Application.apaas_app_id.isnot(None),
        )
    )
    imported_ids = {row[0] for row in imported_result.all() if row[0]}

    # 过滤并格式化
    apps = []
    for a in remote_apps:
        app_id = str(a.get("id", a.get("appId", "")))
        apps.append({
            "apaas_app_id": app_id,
            "app_name": a.get("appName", a.get("name", "")),
            "app_code": a.get("appCode", a.get("code", "")),
            "description": a.get("description", a.get("appDescription", "")),
            "status": a.get("status", ""),
            "already_imported": app_id in imported_ids,
        })

    return apps


# ============================================================
# iframe 嵌入 URL
# ============================================================

@router.get("/embed-url")
async def get_embed_url(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取嵌入低代码平台的 iframe URL（含 token）"""
    from app.models import Application

    tenant_id = await resolve_effective_tenant_id(db, ctx)
    # 查应用
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.tenant_id == tenant_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    if not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="应用尚未部署到平台")

    # 查环境（优先应用关联 → 默认环境 → 任意已连接环境）
    env = None
    if app.platform_env_id:
        env_result = await db.execute(select(PlatformEnv).where(PlatformEnv.id == app.platform_env_id))
        env = env_result.scalar_one_or_none()
    if not env:
        env_result = await db.execute(
            select(PlatformEnv).where(PlatformEnv.tenant_id == tenant_id, PlatformEnv.is_default == True)
        )
        env = env_result.scalar_one_or_none()
    if not env:
        # 兜底：取第一个已连接的环境
        env_result = await db.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == tenant_id,
                PlatformEnv.status == "connected",
            ).limit(1)
        )
        env = env_result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=400, detail="未配置平台环境，请在环境管理中添加并连接")

    # 确保 token 有效：先测试，失败则尝试重新登录
    token = env.token
    if not token and env.username and env.password_enc:
        try:
            password = decrypt_password(env.password_enc)
            client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
            login_result = await client.login(env.username, password)
            token = login_result.get("token", "")
            if token:
                env.token = token
                env.status = "connected"
                await db.commit()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"平台登录失败: {e}")

    if not token:
        raise HTTPException(status_code=400, detail="平台 token 不可用，请先在环境管理中登录")

    # 构建 URL（不传 token — 平台不支持 URL token 免登）
    host = env.base_url.rstrip("/").replace("/backend", "")
    tid = env.platform_tenant_id
    embed_url = f"{host}/platform/{tid}/admin/app-store/edit-app?appId={app.apaas_app_id}&currentStepIndex=0"

    return {
        "url": embed_url,
        "env_name": env.env_name,
        "username": env.username or "",
        "token": token,
        "tenant_id": tid,
        "host": host,
    }
