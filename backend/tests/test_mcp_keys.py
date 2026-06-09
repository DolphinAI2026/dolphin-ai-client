from __future__ import annotations

import pytest

from app.mcp_keys import get_mcp_key_config, parse_mcp_keys, save_mcp_api_keys


def test_parse_mcp_keys_accepts_commas_and_lines():
    assert parse_mcp_keys(" a,\nb ,, c ") == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_mcp_keys_fallback_to_env_before_page_save(db_session, monkeypatch):
    monkeypatch.setenv("MCP_API_KEYS", "env-key")

    config = await get_mcp_key_config(db_session, use_cache=False)

    assert config.source == "env"
    assert config.keys == ["env-key"]


@pytest.mark.asyncio
async def test_empty_page_config_does_not_fallback_to_env(db_session, monkeypatch):
    monkeypatch.setenv("MCP_API_KEYS", "env-key")

    await save_mcp_api_keys(db_session, [], user_id=1)
    config = await get_mcp_key_config(db_session, use_cache=False)

    assert config.source == "database"
    assert config.keys == []


@pytest.mark.asyncio
async def test_page_config_is_database_source(db_session, monkeypatch):
    monkeypatch.setenv("MCP_API_KEYS", "env-key")

    await save_mcp_api_keys(db_session, ["db-key", "db-key", "other-key"], user_id=1)
    config = await get_mcp_key_config(db_session, use_cache=False)

    assert config.source == "database"
    assert config.keys == ["db-key", "other-key"]
