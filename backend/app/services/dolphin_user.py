"""ai-builder 用户 ↔ dolphin trial 租户内对应账号的镜像与 token 颁发。

为什么要镜像账号：
  dolphin trial 平台不开放 instanceId/embed-auth（要 superadmin），但开放
  租户内创建用户 + 用户名密码 login。所以 ai-builder 给每个登录用户在 dolphin
  默认租户下镜像出一个独立账号，前端浮窗 + iframe 用该账号 token —— 会话
  历史 / 项目按用户隔离，不再都挂在 dolphin admin 名下。

工作流：
  ai_builder_user → 查 DolphinUserLink
    ├─ 没有：调 POST /api/tenant/users 创建（用 ai-builder 的 service_token），
    │       Fernet 加密随机 password 落库
    └─ 有：解出 password
  → 调 POST /api/auth/login 拿 access_token（缓存进程内 ~50min）
"""
from __future__ import annotations

import logging
import re
import secrets
import time
from threading import RLock
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import encrypt_password, decrypt_password
from app.models import DolphinUserLink, User

logger = logging.getLogger(__name__)


# 进程内 token 缓存：ai_builder_user_id → (access_token, dolphin_user_id, exp_ts)
# dolphin login 拿的 access_token 是 30 天有效；我们只在 50min 内重用避免雪崩 login
_TOKEN_CACHE: dict[int, tuple[str, int, float]] = {}
_CACHE_LOCK = RLock()
_CACHE_TTL = 50 * 60  # seconds


def _safe_username(prefix: str, ai_user_id: int, raw: str) -> str:
    """生成 dolphin 全局唯一的 username。dolphin 限制 ASCII / 长度，过滤中文。"""
    base = re.sub(r"[^a-zA-Z0-9_-]+", "", raw or "")[:24]
    if not base:
        base = "user"
    return f"{prefix}{ai_user_id}_{base}"[:60]


async def _dolphin_create_user(
    *,
    server_url: str,
    service_token: str,
    username: str,
    nickname: str,
    password: str,
    role_id: int = 2,  # 2 = 开发者
) -> int:
    """调 dolphin admin API 在当前租户下创建用户，返回 dolphin user id。"""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{server_url.rstrip('/')}/api/tenant/users",
            json={"username": username, "nickname": nickname[:20] or username, "password": password, "role_id": role_id},
            headers={"Authorization": f"Bearer {service_token}", "Content-Type": "application/json"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"dolphin create user HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if not data.get("id"):
        raise RuntimeError(f"dolphin create user 返回未带 id: {data}")
    return int(data["id"])


async def _dolphin_login(*, server_url: str, username: str, password: str) -> str:
    """用 dolphin 用户名密码登录，返回 access_token。"""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{server_url.rstrip('/')}/api/auth/login",
            json={"username": username, "password": password},
            headers={"Content-Type": "application/json"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"dolphin login HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"dolphin login 没返 access_token: {data}")
    return token


async def get_user_dolphin_credentials(
    db: AsyncSession,
    user: User,
) -> tuple[str, int]:
    """返回 (access_token, dolphin_user_id)。
    没镜像账号就建一个；有就直接 login。
    """
    if not settings.dolphin_service_token:
        raise RuntimeError("DOLPHIN_SERVICE_TOKEN 未配置，无法颁发 dolphin 用户 token")

    now = time.time()
    with _CACHE_LOCK:
        cached = _TOKEN_CACHE.get(user.id)
    if cached and cached[2] > now + 60:
        return cached[0], cached[1]

    # 查映射
    res = await db.execute(select(DolphinUserLink).where(DolphinUserLink.user_id == user.id))
    link = res.scalar_one_or_none()

    if link is None:
        # 创建：dolphin trial 全局 username 唯一，加 ai_user_id 前缀确保不冲突
        nickname = (user.username or f"user{user.id}")[:20]
        username = _safe_username("aib_", user.id, user.username or "")
        password = secrets.token_urlsafe(20)
        try:
            dolphin_uid = await _dolphin_create_user(
                server_url=settings.dolphin_server_url,
                service_token=settings.dolphin_service_token,
                username=username,
                nickname=nickname,
                password=password,
            )
        except Exception as exc:
            logger.error("dolphin create user failed for ai-builder user %s: %s", user.id, exc)
            raise

        link = DolphinUserLink(
            user_id=user.id,
            dolphin_user_id=dolphin_uid,
            dolphin_username=username,
            dolphin_password_enc=encrypt_password(password),
        )
        db.add(link)
        await db.commit()
        await db.refresh(link)
        logger.info("created dolphin mirror user: ai-builder user %s → dolphin %s (%s)", user.id, dolphin_uid, username)

    # login 拿 token
    plain_pw = decrypt_password(link.dolphin_password_enc)
    try:
        access_token = await _dolphin_login(
            server_url=settings.dolphin_server_url,
            username=link.dolphin_username,
            password=plain_pw,
        )
    except Exception as exc:
        logger.error("dolphin login failed for ai-builder user %s (dolphin %s): %s", user.id, link.dolphin_user_id, exc)
        raise

    with _CACHE_LOCK:
        _TOKEN_CACHE[user.id] = (access_token, link.dolphin_user_id, now + _CACHE_TTL)

    return access_token, link.dolphin_user_id


def invalidate_token_cache(user_id: int) -> None:
    with _CACHE_LOCK:
        _TOKEN_CACHE.pop(user_id, None)
