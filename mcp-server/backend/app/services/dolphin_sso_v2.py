"""dolphin 真身 login + token cache（P3 多租户身份对齐）。

设计目的
========
v1（dolphin_user.py）走镜像账号机制：每个 ai-builder 用户在 dolphin **default 租户**
镜像出 `aib_<id>_<name>` 账号，密码后端托管。问题：

- dolphin 租户严格隔离 — 镜像账号在 default 租户，**不能调宝洁租户的 agent**
- 客户租户审计 / 合规视角下"假账号"很别扭
- 跨租户上线时碰壁

v2（本模块）走"用户真身 dolphin 账号"路径：

- ai-builder login 时拿到用户输入的**明文密码**
- 同步用 (username, password) 调 dolphin `/api/auth/login` 拿 token
- 这个 token 是用户在 dolphin 真身（如 li.l.77@pg.com 在宝洁租户 sub=94）
- 缓存进程内 25 分钟（dolphin token 30 天有效，缓存短一点保活）
- `/api/dolphin/config` 优先返这个 cached token

降级策略
========
- ai-builder login 失败：直接返 None，不阻断 ai-builder 登录
- get_cached_dolphin_token 返 None 时调用方决定 fallback（镜像账号 / 报错）
- 这样支持平滑过渡：现有用户 dolphin 没同名账号也能用 ai-builder UI（dolphin chat 入口降级）

约束
====
- 必须 ai-builder username == dolphin username（强一致）
- 必须 ai-builder password == dolphin password（同步好）
- 不一致时 dolphin login 失败 → cache miss → 用户进 /ai-copilot 报错
"""
from __future__ import annotations

import base64
import json
import logging
import time
from threading import RLock
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# user_id → (token, dolphin_user_id, exp_ts)
# dolphin token 实际 30 天有效，我们 25 分钟过期触发重新 login 保活（实际上需要前端
# 触发：用户每次 ai-builder login 时同步登；25 分钟内不重 login，cache 自然过期）
_TOKEN_CACHE: dict[int, tuple[str, int, float]] = {}
_LOCK = RLock()
_CACHE_TTL = 25 * 60  # seconds


def _decode_dolphin_jwt_sub(token: str) -> Optional[int]:
    """从 dolphin JWT payload 提取 sub（dolphin user_id）。仅做 base64 decode 不验签。"""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        # JWT base64url，可能缺 padding
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload).decode())
        sub = data.get("sub")
        return int(sub) if sub is not None else None
    except Exception:
        return None


async def login_dolphin_for_user(user_id: int, username: str, plain_password: str) -> Optional[dict]:
    """ai-builder login 成功后立刻调一次。同步用 (username, password) 调 dolphin login，
    成功就 cache 真身 token。

    返回：
      - {"token": str, "sub": int} 成功
      - None 失败（用户 dolphin 没账号 / 密码不一致 / 网络错误）
    """
    if not username or not plain_password:
        return None
    if not settings.dolphin_server_url:
        return None

    server = settings.dolphin_server_url.rstrip("/")
    url = f"{server}/api/auth/login"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                json={"username": username, "password": plain_password},
                headers={"Content-Type": "application/json"},
            )
    except Exception as exc:
        logger.warning("dolphin login (real identity) network error for user_id=%s: %s", user_id, exc)
        return None

    if resp.status_code != 200:
        # 401 通常是密码不一致；404 通常是用户在 dolphin 没账号
        logger.info(
            "dolphin login (real identity) failed user_id=%s username=%s HTTP=%d body=%s",
            user_id, username, resp.status_code, (resp.text or "")[:200],
        )
        return None

    try:
        data = resp.json()
    except Exception:
        return None

    token = data.get("access_token")
    if not token:
        return None

    sub = _decode_dolphin_jwt_sub(token)
    if not sub:
        logger.warning("dolphin login 拿到 token 但解析 sub 失败 user_id=%s", user_id)
        return None

    with _LOCK:
        _TOKEN_CACHE[int(user_id)] = (token, int(sub), time.time() + _CACHE_TTL)

    logger.info(
        "dolphin real-identity login OK user_id=%s username=%s → dolphin_sub=%s",
        user_id, username, sub,
    )
    return {"token": token, "sub": int(sub)}


def get_cached_dolphin_token(user_id: int) -> Optional[dict]:
    """供 /api/dolphin/config / init-app-context 等调，取当前用户已缓存的真身 dolphin token。

    返回 None 时调用方应 fallback（v1 镜像账号 / 报错）。
    """
    if not user_id or int(user_id) <= 0:
        return None
    with _LOCK:
        rec = _TOKEN_CACHE.get(int(user_id))
        if not rec:
            return None
        token, sub, exp = rec
        if time.time() > exp:
            _TOKEN_CACHE.pop(int(user_id), None)
            return None
        return {"token": token, "sub": sub}


def invalidate_cache(user_id: int) -> None:
    """logout / 改密码时调，清掉 cache。"""
    with _LOCK:
        _TOKEN_CACHE.pop(int(user_id), None)


# ─────────────────────── 按租户选 dolphin agent code ───────────────────────


async def pick_agent_codes_for_tenant(tenant_id: int) -> dict[str, Optional[str]]:
    """按 ai-builder tenant_id 返回该租户应该用的 dolphin agent_code 集合。

    数据源：tenants 表 5 个 dolphin agent code 字段：
      - dolphin_copilot_agent_code     应用低代码生命周期
      - dolphin_coding_agent_code       代码态自开发
      - dolphin_app_adjust_agent_code   应用调整（历史遗留）
      - dolphin_requirements_agent_code 需求分析（历史遗留）
      - dolphin_agent_code              兜底默认

    Fallback 链（2026-05-11 收紧后，**禁止跨 tenant fallback**）：
      1. 字段在 tenants 表里有值 → 用之
      2. 该字段为 NULL 但 copilot 字段有值 → 用 copilot（同 tenant 合并版场景）
      3. 仍为 NULL → 返 None（**不再 fallback .env 全局**，调用方 fail-fast）

    设计依据：用户 2026-05-11 决策"强制 1:1:1：每个 ai-builder 租户绑死一个
    apaas env + 一个 dolphin instance，禁止跨绑/禁止 fallback"。.env 全局兜底
    会导致 baogong tenant 未配某 agent 时静默用到 admin 的 agent，串号根源。
    """
    if not tenant_id or int(tenant_id) <= 0:
        return _empty_agent_codes()

    try:
        from app.database import AsyncSessionLocal
        from app.models import Tenant
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).where(Tenant.id == int(tenant_id)))).scalar_one_or_none()
            if t:
                copilot = t.dolphin_copilot_agent_code or None

                # tenant 字段 → 同 tenant copilot fallback → None（不再 .env）
                def pick(field: Optional[str]) -> Optional[str]:
                    return field or copilot

                return {
                    "copilot_agent_code": copilot,
                    "coding_agent_code": pick(t.dolphin_coding_agent_code),
                    "app_adjust_agent_code": pick(t.dolphin_app_adjust_agent_code),
                    "requirements_agent_code": pick(t.dolphin_requirements_agent_code),
                    "agent_code": t.dolphin_agent_code or copilot,
                }
    except Exception as exc:
        logger.warning(
            "pick_agent_codes_for_tenant 查 DB 失败 tenant_id=%s: %s（返空，调用方应 fail-fast）",
            tenant_id, exc,
        )

    return _empty_agent_codes()


def _empty_agent_codes() -> dict[str, Optional[str]]:
    """全 None。调用方按需 fail-fast，不再用 .env 全局兜底（避免跨 tenant 串号）。"""
    return {
        "copilot_agent_code": None,
        "coding_agent_code": None,
        "app_adjust_agent_code": None,
        "requirements_agent_code": None,
        "agent_code": None,
    }


async def get_dolphin_tenant_for_ai_tenant(ai_tenant_id: int) -> Optional[dict]:
    """查 ai-builder tenant 绑定的 dolphin 租户信息。

    返回 { dolphin_tenant_code, dolphin_tenant_id_str } 或 None（未绑定时）。
    供 _inject_ctx_and_get_session_id 等需要带 dolphin tenant 上下文的调用方用。
    """
    if not ai_tenant_id or int(ai_tenant_id) <= 0:
        return None
    try:
        from app.database import AsyncSessionLocal
        from app.models import Tenant
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).where(Tenant.id == int(ai_tenant_id)))).scalar_one_or_none()
            if not t:
                return None
            return {
                "dolphin_tenant_code": t.dolphin_tenant_code,
                "dolphin_tenant_id_str": t.dolphin_tenant_id_str,
            }
    except Exception as exc:
        logger.warning("get_dolphin_tenant_for_ai_tenant 查 DB 失败: %s", exc)
        return None


async def get_apaas_env_id_for_tenant(ai_tenant_id: int) -> Optional[int]:
    """查 ai-builder tenant 唯一绑定的 apaas env id。"""
    if not ai_tenant_id or int(ai_tenant_id) <= 0:
        return None
    try:
        from app.database import AsyncSessionLocal
        from app.models import Tenant
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).where(Tenant.id == int(ai_tenant_id)))).scalar_one_or_none()
            return int(t.apaas_env_id) if t and t.apaas_env_id else None
    except Exception:
        return None
