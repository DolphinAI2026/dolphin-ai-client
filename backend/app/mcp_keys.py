from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt_password, encrypt_password
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

MCP_KEYS_SETTING_KEY = "mcp_api_keys"
_CACHE_TTL_SEC = 5
_cached_keys: list[str] | None = None
_cached_source = "none"
_cache_expires_at = 0.0


@dataclass(frozen=True)
class McpKeyConfig:
    keys: list[str]
    source: str


def parse_mcp_keys(raw: str | None) -> list[str]:
    if not raw:
        return []
    normalized = raw.replace("\n", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _env_keys() -> list[str]:
    return parse_mcp_keys(os.getenv("MCP_API_KEYS") or os.getenv("MCP_API_KEY") or "")


async def get_mcp_key_config(db: AsyncSession | None = None, *, use_cache: bool = True) -> McpKeyConfig:
    global _cached_keys, _cached_source, _cache_expires_at

    now = time.monotonic()
    if use_cache and db is None and _cached_keys is not None and now < _cache_expires_at:
        return McpKeyConfig(keys=list(_cached_keys), source=_cached_source)

    keys: list[str] = []
    source = "none"

    async def _read_from(session: AsyncSession) -> tuple[bool, list[str]]:
        row = await session.scalar(select(SystemSetting).where(SystemSetting.key == MCP_KEYS_SETTING_KEY))
        if not row or not row.value_enc:
            return row is not None, []
        return True, parse_mcp_keys(decrypt_password(row.value_enc))

    try:
        if db is not None:
            found_db_setting, keys = await _read_from(db)
        else:
            from app.database import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                found_db_setting, keys = await _read_from(session)
        if found_db_setting:
            source = "database"
    except Exception as exc:
        found_db_setting = False
        logger.warning("读取数据库 MCP key 配置失败，降级使用环境变量: %s", exc)

    if source != "database":
        keys = _env_keys()
        source = "env" if keys else "none"

    if db is None:
        _cached_keys = list(keys)
        _cached_source = source
        _cache_expires_at = now + _CACHE_TTL_SEC

    return McpKeyConfig(keys=keys, source=source)


async def get_mcp_api_keys(db: AsyncSession | None = None, *, use_cache: bool = True) -> list[str]:
    return (await get_mcp_key_config(db, use_cache=use_cache)).keys


async def save_mcp_api_keys(db: AsyncSession, keys: list[str], *, user_id: int | None = None) -> McpKeyConfig:
    global _cached_keys, _cached_source, _cache_expires_at

    cleaned: list[str] = []
    seen: set[str] = set()
    for key in keys:
        value = (key or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)

    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == MCP_KEYS_SETTING_KEY))
    if row is None:
        row = SystemSetting(
            key=MCP_KEYS_SETTING_KEY,
            value_enc=encrypt_password(",".join(cleaned)),
            description="MCP API keys configured from platform admin page",
            updated_by_user_id=user_id,
        )
        db.add(row)
    else:
        row.value_enc = encrypt_password(",".join(cleaned))
        row.description = "MCP API keys configured from platform admin page"
        row.updated_by_user_id = user_id

    await db.commit()
    _cached_keys = list(cleaned)
    _cached_source = "database"
    _cache_expires_at = time.monotonic() + _CACHE_TTL_SEC
    return McpKeyConfig(keys=cleaned, source="database")
