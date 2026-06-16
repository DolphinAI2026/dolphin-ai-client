"""ai-builder JWT + 密码工具。

JWT 载荷规范（Phase 2 / 2026-05-10）
=====================================
统一所有内部签发的 JWT 用一套 helper 出。载荷字段：

    {
      "sub": "<local users.id>",          # str（jose 要求 sub 是 str）
      "tid": <local tenants.id int>,      # 可空（多租户首步登录前）
      "type": "access" | "selection" | "ide_access" | "mcp_service",
      "iat": <epoch>,
      "exp": <epoch>,
      # 双 ID 增强（access type 才填，其他 type 不填避免膨胀短期 token）：
      "apaas_sub": "<aPaaS user_id 21 位 string>",   # 可空
      "apaas_tid": "<aPaaS tenant_id 21 位 string>", # 可空
      "username": "<local users.username>",
      "iss": "ai-builder",
      "aud": "ai-builder-web",
      # ide_access 还带 ws (workspace id)
    }

后端 get_auth_context 解 JWT 时优先用 access type 的 apaas_sub/apaas_tid 给
AuthContext 赋值；老 JWT（无这俩 claim）回落到从 User 行读 apaas_user_id 字段。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import bcrypt as _bcrypt
from typing import Annotated, Any, Mapping, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User

security = HTTPBearer()

# 常量
_ISSUER = "ai-builder"
_AUDIENCE = "ai-builder-web"


# ─── 密码（bcrypt 为主，旧 sha256 hexdigest 回落兼容） ─────────────────────
# 新账号用 bcrypt；旧账号是裸 sha256 hexdigest（非 bcrypt 格式），verify 时手动回落。


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if hashed_password.startswith("$2"):
        return _bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
    # 旧裸 sha256 回落（迁移期）
    return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password


def get_password_hash(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


# ─── JWT 工厂 ────────────────────────────────────────────────────────────
def _now_utc() -> datetime:
    return datetime.utcnow()


def _encode(payload: dict) -> str:
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_token(token: str) -> dict:
    """解 ai-builder JWT。验签 + exp，但不验 aud（旧 JWT 没 aud）。

    抛 JWTError 由调用方接住转 401。
    """
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"verify_aud": False},
    )


def create_access_token(
    user: "User | int | Mapping[str, Any]",
    tenant_id: Optional[int] = None,
    *,
    expire_minutes: Optional[int] = None,
    apaas_user_id: Optional[str] = None,
    apaas_tenant_id: Optional[str] = None,
    username: Optional[str] = None,
) -> str:
    """主登录 JWT。优先从 user 对象取 apaas claims；调用方覆盖参数优先级最高。

    兼容签法：传 int user_id 或 {"sub": user_id}（旧测试/老路径）也接受，仅不嵌入
    apaas claims（双 ID 字段需要 user 对象才能拿）。
    """
    if isinstance(user, int):
        sub = user
        u_apaas_uid = apaas_user_id
        u_apaas_tid = apaas_tenant_id
        u_username = username
    elif isinstance(user, Mapping):
        sub = int(user.get("sub") or user.get("user_id") or user.get("id"))
        u_apaas_uid = apaas_user_id or user.get("apaas_sub") or user.get("apaas_user_id")
        u_apaas_tid = apaas_tenant_id or user.get("apaas_tid") or user.get("apaas_tenant_id")
        u_username = username or user.get("username")
    else:
        sub = int(user.id)
        u_apaas_uid = apaas_user_id or (user.apaas_user_id or None)
        u_apaas_tid = apaas_tenant_id or (user.apaas_tenant_id or None)
        u_username = username or user.username

    minutes = expire_minutes if expire_minutes is not None else settings.jwt_expire_minutes
    now = _now_utc()
    payload: dict[str, Any] = {
        "sub": str(sub),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
        "iss": _ISSUER,
        "aud": _AUDIENCE,
    }
    if tenant_id is not None:
        payload["tid"] = int(tenant_id)
    if u_apaas_uid:
        payload["apaas_sub"] = str(u_apaas_uid)
    if u_apaas_tid:
        payload["apaas_tid"] = str(u_apaas_tid)
    if u_username:
        payload["username"] = u_username
    return _encode(payload)


def create_selection_token(user_id: int) -> str:
    """多租户选择令牌（15min）。"""
    now = _now_utc()
    return _encode({
        "sub": str(user_id),
        "type": "selection",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "iss": _ISSUER,
    })


def create_ide_access_token(user_id: int, tenant_id: int, ws_id: str) -> str:
    """IDE workspace 访问令牌（8h），不带 apaas claims（内部短票）。"""
    now = _now_utc()
    return _encode({
        "sub": str(user_id),
        "tid": int(tenant_id),
        "type": "ide_access",
        "ws": ws_id,
        "iat": now,
        "exp": now + timedelta(hours=8),
        "iss": _ISSUER,
    })


def create_mcp_service_token(user_id: int, tenant_id: int, ttl_minutes: int = 15) -> str:
    """MCP backend 内部互调短票，不带 apaas claims。"""
    now = _now_utc()
    return _encode({
        "sub": str(user_id),
        "tid": int(tenant_id),
        "type": "mcp_service",
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
        "iss": _ISSUER,
    })


# ─── FastAPI 依赖 ────────────────────────────────────────────────────────
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """从 Bearer JWT 解出 ai-builder User。401 抛标准异常。"""
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        sub = payload.get("sub")
        if sub is None:
            raise credentials_exception
        user_id = int(sub)
    except (JWTError, ValueError):
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    return user
