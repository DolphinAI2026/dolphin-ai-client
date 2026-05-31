"""apaas 环境别名注册表 v2 —— MCP server 自管 + ai-builder DB 兜底.

设计目标（用户决策 2026-05-10）：MCP server 自管 env 凭证，真正脱离 ai-builder 用户体系：
- 主存储：backend/config/apaas_envs.yaml（gitignore，含 service_token）
- 兼容存储：platform_envs 表（老配置兜底，admin UI 仍可写）
- dolphin agent 全局记忆只存 alias 字符串（zero secrets，dolphin admin 看不到 token）

加载策略：
- 进程启动时读 yaml 一次（cache 到内存 dict）
- 调 reload_yaml_config() 触发刷新（admin endpoint 暴露 / SIGHUP / 手动）
- 每次 resolve_env_by_alias：先查 cache → 不命中 fallback platform_envs 表

为什么 MCP server 自管而非 ai-builder DB：
- ai-builder 是"应用管理 UI"产品，dolphin agent 是独立 agent 平台，两者解耦
- agent 凭证存在 MCP server 后端，dolphin admin / ai-builder admin 都看不到 secrets
- "假设 ai-builder 不存在 agent 也能用"成立——只要 MCP server 配 yaml 即可

调用方式：
    alias 来自 dolphin agent 全局记忆（如 "dev8" / "baogong"），agent 调 MCP
    工具时把 alias 当作 env 参数传过来。本模块负责把 alias 翻译成实际凭证。

错误处理：
    alias 不存在 / 未连接（无 token）时返回 None。调用方负责给 agent 返
    _business_error，不在本模块抛异常。
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml as _yaml
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import PlatformEnv

logger = logging.getLogger(__name__)


# yaml 配置文件位置（可被 APAAS_ENVS_CONFIG_PATH 环境变量覆盖）
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "apaas_envs.yaml"
CONFIG_PATH = Path(os.getenv("APAAS_ENVS_CONFIG_PATH", str(_DEFAULT_CONFIG_PATH)))

# 进程内 cache：
#   {alias: {env_name, base_url, platform_tenant_id, username, password, status}}
# token 不进 yaml cache（每次按账密 login 拿 + 进程内 token cache）
_YAML_CACHE: dict[str, dict[str, Any]] = {}

# 进程内 token cache（按账密 login 后缓存，避免每次调用都重 login）
# {alias: {token: str, expires_at: int (unix ts)}}
_TOKEN_CACHE: dict[str, dict[str, Any]] = {}
_TOKEN_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class ApaasEnvCredentials:
    """调 apaas API 所需的全部凭证 + 元信息。"""

    env_id: int                  # platform_envs.id（yaml 来源时 = -1）
    alias: str
    env_name: str
    base_url: str
    platform_tenant_id: str
    token: Optional[str]
    status: str
    source: str = "db"           # 'yaml' or 'db'


def _load_yaml_to_cache() -> int:
    """从 yaml 加载 alias 凭证到进程内 cache。返回加载条数。"""
    global _YAML_CACHE
    new_cache: dict[str, dict[str, Any]] = {}

    if not CONFIG_PATH.exists():
        logger.info("apaas_envs.yaml 不存在 (%s)，仅用 platform_envs 表 fallback", CONFIG_PATH)
        _YAML_CACHE = new_cache
        return 0

    try:
        raw = CONFIG_PATH.read_text(encoding="utf-8")
        data = _yaml.safe_load(raw)
    except Exception as exc:
        logger.error("读取 apaas_envs.yaml 失败 %s: %s", CONFIG_PATH, exc)
        return len(_YAML_CACHE)  # 保留旧 cache

    if not isinstance(data, list):
        logger.warning("apaas_envs.yaml 顶层应是 list，实际 %s——忽略", type(data).__name__)
        _YAML_CACHE = new_cache
        return 0

    for entry in data:
        if not isinstance(entry, dict):
            continue
        alias = (entry.get("alias") or "").strip()
        if not alias:
            continue
        new_cache[alias] = {
            "alias": alias,
            "env_name": entry.get("env_name") or alias,
            "base_url": (entry.get("base_url") or "").rstrip("/"),
            "platform_tenant_id": str(entry.get("apaas_tenant_id") or ""),
            # 凭证：service_token（long-lived 优先）或 username+password（自动 login）
            "service_token": entry.get("service_token") or "",
            "username": entry.get("username") or "",
            "password": entry.get("password") or "",
            "status": entry.get("status") or "connected",
        }

    _YAML_CACHE = new_cache
    # yaml 重新加载时清掉 token cache（账密可能改了）
    _TOKEN_CACHE.clear()
    logger.info("apaas_envs.yaml 加载完成: %d 个 alias (%s)", len(new_cache), list(new_cache.keys()))
    return len(new_cache)


def reload_yaml_config() -> int:
    """admin / SIGHUP 触发热重载 yaml。返回最新加载条数。"""
    return _load_yaml_to_cache()


# 进程启动时加载一次
_load_yaml_to_cache()


async def resolve_env_by_alias(alias: str) -> Optional[ApaasEnvCredentials]:
    """按 alias 查环境凭证。**优先 yaml**，未命中 fallback platform_envs 表。

    多租户隔离靠"每 dolphin agent 全局记忆里固定写一个 alias"实现，跨 agent
    不共享。**不做** ai-builder tenant 归属校验。
    """
    if not alias or not isinstance(alias, str):
        return None
    alias_clean = alias.strip()
    if not alias_clean:
        return None

    # ① yaml 优先（MCP server 自管）
    cached = _YAML_CACHE.get(alias_clean)
    if cached:
        # token 来源优先级：
        # 1. yaml service_token（long-lived，直接用）
        # 2. _TOKEN_CACHE（之前用账密 login 过的，未过期）
        # 3. 用 yaml username/password 现 login，结果存 _TOKEN_CACHE
        token = cached.get("service_token") or ""
        if not token:
            token = await _get_or_login_yaml_token(alias_clean, cached)
        # 2026-05-10 BUG fix：yaml 命中时也回查 platform_envs DB 拿真 env_id。
        # 否则 generate_app_from_doc / publish_application 等内部路径
        # `if env_id > 0: create_body["platform_env_id"]=...` 判断 fail
        # → backend 用 user 默认 env → 应用打到错的 apaas tenant。
        # 实测 pg 用户用 env=baogong 创建应用，结果建到 default tenant 的
        # 新豪轩 env (834031758956560385) 而不是宝洁 (833850449709760513)。
        env_id_db = -1
        try:
            async with AsyncSessionLocal() as db:
                row = (await db.execute(
                    select(PlatformEnv).where(PlatformEnv.alias == alias_clean)
                )).scalar_one_or_none()
                if row:
                    env_id_db = row.id
        except Exception as exc:
            logger.warning("yaml alias=%s 回查 platform_envs.id 失败: %s", alias_clean, exc)
        return ApaasEnvCredentials(
            env_id=env_id_db,
            alias=alias_clean,
            env_name=cached["env_name"],
            base_url=cached["base_url"],
            platform_tenant_id=cached["platform_tenant_id"],
            token=token,
            status=cached["status"],
            source="yaml",
        )

    # ② platform_envs 表 fallback（兼容老配置 / admin UI 仍可写）
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(PlatformEnv).where(PlatformEnv.alias == alias_clean)
            )
        ).scalar_one_or_none()
        if not row:
            return None
        return ApaasEnvCredentials(
            env_id=row.id,
            alias=row.alias or alias_clean,
            env_name=row.env_name,
            base_url=row.base_url,
            platform_tenant_id=row.platform_tenant_id,
            token=row.token,
            status=row.status,
            source="db",
        )


async def _get_or_login_yaml_token(alias: str, cached: dict[str, Any]) -> str:
    """yaml 来源 alias 的 token 管理：cache 命中返 cache，否则用 yaml 账密 login.

    cache miss：调 APaaSClient.login(username, password) 拿 token，
    cache hit （未过期 60s 内）：直接返 cache。
    """
    # 看 token cache
    async with _TOKEN_LOCK:
        tc = _TOKEN_CACHE.get(alias)
        if tc and tc.get("expires_at", 0) > time.time() + 60:
            return tc["token"]

    username = cached.get("username") or ""
    password = cached.get("password") or ""
    if not username or not password:
        logger.warning("yaml alias=%s 没 username/password，token 拿不到", alias)
        return ""

    from app.apaas_client import APaaSClient

    try:
        client = APaaSClient(
            base_url=cached["base_url"],
            tenant_id=cached["platform_tenant_id"],
        )
        login_result = await client.login(username, password)
        token = login_result.get("token", "")
        if not token:
            logger.warning("yaml alias=%s login 返回空 token", alias)
            return ""
        # JWT 解 exp（apaas trial 一般 2h 有效，我们提前 5min 重 login）
        expires_at = _parse_jwt_exp(token) or (int(time.time()) + 7200 - 300)
        async with _TOKEN_LOCK:
            _TOKEN_CACHE[alias] = {"token": token, "expires_at": expires_at}
        logger.info("yaml alias=%s 用 %s 账号 login 成功，expires_at=%d", alias, username, expires_at)
        return token
    except Exception as exc:
        logger.error("yaml alias=%s login 失败: %s", alias, exc)
        return ""


def _parse_jwt_exp(token: str) -> Optional[int]:
    """从 JWT payload 解 exp 字段（unix ts）。失败返 None."""
    try:
        import base64
        import json
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return int(data.get("exp", 0)) or None
    except Exception:
        return None


async def refresh_env_token_by_alias(alias: str) -> bool:
    """alias 的 token 自愈：yaml 来源重 login + 写 cache；DB 来源走老逻辑."""
    creds = await resolve_env_by_alias(alias)
    if not creds:
        return False

    if creds.source == "yaml":
        # 清掉 _TOKEN_CACHE 强制重 login
        async with _TOKEN_LOCK:
            _TOKEN_CACHE.pop(alias, None)
        # 重新调 resolve 触发 _get_or_login_yaml_token
        new_creds = await resolve_env_by_alias(alias)
        success = bool(new_creds and new_creds.token)
        if not success:
            logger.warning("yaml alias=%s 重 login 失败（可能账密错 / apaas 拒登）", alias)
        return success

    # DB 来源：用账号密码自动 login
    from app.apaas_client import APaaSClient
    from app.crypto import decrypt_password

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(select(PlatformEnv).where(PlatformEnv.alias == alias))
        ).scalar_one_or_none()
        if not row:
            return False
        if not row.username or not row.password_enc:
            return False
        try:
            password = decrypt_password(row.password_enc)
            client = APaaSClient(
                base_url=row.base_url,
                tenant_id=row.platform_tenant_id,
            )
            login_result = await client.login(row.username, password)
            token = login_result.get("token", "")
            if not token:
                return False
            row.token = token
            row.status = "connected"
            await db.commit()
            return True
        except Exception:
            try:
                row.status = "disconnected"
                await db.commit()
            except Exception:
                await db.rollback()
            return False


async def list_all_aliases() -> list[dict]:
    """合并 yaml + DB 的 alias 列表（admin 看 / 工具列表用）。yaml 同名优先。"""
    items: list[dict] = []
    yaml_aliases = set(_YAML_CACHE.keys())

    # yaml 来源
    for alias, e in _YAML_CACHE.items():
        items.append({
            "alias": alias,
            "env_name": e["env_name"],
            "base_url": e["base_url"],
            "platform_tenant_id": e["platform_tenant_id"],
            "status": e["status"],
            "source": "yaml",
        })

    # DB 补充（不重复）
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(PlatformEnv).where(PlatformEnv.alias.isnot(None)))
        ).scalars().all()
        for r in rows:
            if r.alias and r.alias not in yaml_aliases:
                items.append({
                    "alias": r.alias,
                    "env_name": r.env_name,
                    "base_url": r.base_url,
                    "platform_tenant_id": r.platform_tenant_id,
                    "status": r.status,
                    "source": "db",
                })
    return items
