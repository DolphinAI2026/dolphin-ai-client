from datetime import datetime, timedelta
from typing import Annotated, Optional
import hashlib
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database import get_db
from app.models import User

security = HTTPBearer()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    password_hash = hashlib.sha256(plain_password.encode()).hexdigest()
    return password_hash == hashed_password


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return hashlib.sha256(password.encode()).hexdigest()


def create_access_token(data: dict, tenant_id: Optional[int] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode.update({"exp": expire, "type": "access"})
    # 确保sub是字符串
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    # 添加租户ID
    if tenant_id is not None:
        to_encode["tid"] = tenant_id
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_selection_token(user_id: int) -> str:
    """创建租户选择令牌（多租户用户登录第一步）"""
    to_encode = {
        "sub": str(user_id),
        "type": "selection",
        "exp": datetime.utcnow() + timedelta(minutes=15)  # 15分钟有效期
    }
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        print(f"DEBUG: Decoded user_id from token: {user_id}, type: {type(user_id)}")
        if user_id is None:
            print("DEBUG: user_id is None")
            raise credentials_exception
        user_id = int(user_id)  # 确保是整数
    except JWTError as e:
        print(f"DEBUG: JWT decode error: {e}")
        raise credentials_exception
    except Exception as e:
        print(f"DEBUG: Unexpected error: {e}")
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    print(f"DEBUG: Found user: {user}")

    if user is None or not user.is_active:
        print(f"DEBUG: User not found or inactive")
        raise credentials_exception

    return user
