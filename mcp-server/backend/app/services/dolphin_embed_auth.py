"""Dolphin Embed Auth (POST /api/embed/auth) —— 替代 v3.0 砍掉的 SSO 镜像账号机制.

dolphin 团队 2026-05 开放的官方接入方式（参考 dolphin SDK
https://dolphin-trial.definesys.cn/embed/sdk.js v1.2）。

关键点：
- 每个 ai-builder 用户用真实 user.id + username 调 dolphin /api/embed/auth
- dolphin 自动按 source_user_id 建/复用 dolphin 账号 + 签 JWT
- 比镜像账号干净（不用密码同步），比 service_token 多用户隔离干净
  （每个 user 独立 dolphin sub，会话历史 sidebar 自然隔离）

接口契约（从 SDK 反推）：
  POST {server}/api/embed/auth
  Body: {
    instance_id: "ai-builder",      # 必填，ai-builder 命名空间
    product: "aPaaS Builder AI",    # 可选
    customer_name: "得帆",            # 可选
    agent_code: "23c93f30d8",       # 必填，每个 agent 一个 token
    source_user_id: "23",           # 必填，ai-builder user.id 字符串
    source_user_name: "li.l.77",    # 必填
    source_user_phone: null,
    source_user_email: null,
  }
  Response: { token, tenant_id, agent_code, expires_at }

⚠️ 安全说明（dolphin admin 文档原话）：
  当前实现不做签名校验，任何知道 instance_id + agent_code 的人都能以任意
  source_user_id 登录。本服务在 ai-builder 后端做 user 身份校验（user 来自
  ctx.user，FastAPI 已经验过 JWT），不让外部直传 source_user_id。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from app.config import settings
from app.models import User

logger = logging.getLogger(__name__)

# 进程内缓存：{(user_id, agent_code) → {token, tenant_id, expires_at, agent_code}}
# JWT 默认 1 小时有效，缓存命中提前 60s 重签
_CACHE: dict[tuple[int, str], dict[str, Any]] = {}
_LOCK = asyncio.Lock()

# ai-builder 在 dolphin 端的命名空间标识
EMBED_INSTANCE_ID = "ai-builder"
EMBED_PRODUCT = "aPaaS Builder AI"
EMBED_CUSTOMER_NAME = "得帆"


def _is_token_valid(cached: dict[str, Any]) -> bool:
    """检查缓存的 JWT 是否还有 60s 以上有效期."""
    exp = cached.get("expires_at")
    if not exp:
        return False
    try:
        # expires_at 可能是 unix timestamp（秒）/ ms / ISO string
        if isinstance(exp, (int, float)):
            exp_ts = float(exp)
            # 如果是 ms（13 位）转秒
            if exp_ts > 10_000_000_000:
                exp_ts = exp_ts / 1000
        else:
            from datetime import datetime
            exp_ts = datetime.fromisoformat(str(exp).replace("Z", "+00:00")).timestamp()
    except Exception:
        return False
    return exp_ts > time.time() + 60


async def embed_auth_for_user(
    agent_code: str, user: User
) -> Optional[dict[str, Any]]:
    """按 (ai-builder user, dolphin agent_code) 拿 dolphin embed JWT.

    返回 {token, tenant_id, agent_code, expires_at}；失败返回 None.

    缓存策略：进程内 dict 按 (user.id, agent_code) 缓存到 expires_at - 60s.
    多实例部署时换 redis；trial 单实例够用.
    """
    if not agent_code or not user:
        return None
    cache_key = (user.id, agent_code)

    # ① 缓存命中
    async with _LOCK:
        cached = _CACHE.get(cache_key)
        if cached and _is_token_valid(cached):
            return cached

    # ② 调 dolphin embed/auth
    body = {
        "instance_id": EMBED_INSTANCE_ID,
        "product": EMBED_PRODUCT,
        "customer_name": EMBED_CUSTOMER_NAME,
        "agent_code": agent_code,
        "source_user_id": str(user.id),
        "source_user_name": user.username or f"user_{user.id}",
        "source_user_phone": None,
        "source_user_email": None,
    }
    url = settings.dolphin_server_url.rstrip("/") + "/api/embed/auth"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=body)
            if resp.status_code != 200:
                logger.error(
                    "dolphin embed/auth HTTP %d agent=%s user_id=%s: %s",
                    resp.status_code, agent_code, user.id, resp.text[:300],
                )
                return None
            data = resp.json()
            result = {
                "token": data.get("token", ""),
                "tenant_id": data.get("tenant_id", ""),
                "agent_code": data.get("agent_code", agent_code),
                "expires_at": data.get("expires_at"),
            }
            if not result["token"]:
                logger.error("dolphin embed/auth 返回空 token: %s", data)
                return None
            async with _LOCK:
                _CACHE[cache_key] = result
            logger.info(
                "dolphin embed/auth 成功 user_id=%s agent=%s tenant=%s",
                user.id, agent_code, result["tenant_id"],
            )
            return result
    except Exception as exc:
        logger.error(
            "dolphin embed/auth 调用失败 user_id=%s agent=%s: %s",
            user.id, agent_code, exc,
        )
        return None


def invalidate_user_cache(user_id: int) -> None:
    """清掉某个 user 的所有 agent token 缓存（用户登出 / 切租户时调）."""
    async def _do():
        async with _LOCK:
            keys_to_del = [k for k in _CACHE if k[0] == user_id]
            for k in keys_to_del:
                _CACHE.pop(k, None)
    asyncio.create_task(_do())
