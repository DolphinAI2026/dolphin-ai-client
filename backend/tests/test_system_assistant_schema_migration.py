"""Strict, additive B0 schema migration checks."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

from app.system_assistant.schema_migration import (
    CompatibilityColumn,
    migrate_system_assistant_governance,
)


async def _legacy_schema(conn) -> None:
    await conn.execute(text("CREATE TABLE ai_chat_tool_calls (id INTEGER PRIMARY KEY)"))
    await conn.execute(text("CREATE TABLE agent_step (id INTEGER PRIMARY KEY)"))


@pytest.mark.asyncio
async def test_migration_adds_missing_compatibility_columns_and_new_tables(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.sqlite3'}")
    try:
        async with engine.begin() as conn:
            await _legacy_schema(conn)
            await migrate_system_assistant_governance(conn)

            def schema(sync_conn):
                inspector = inspect(sync_conn)
                return {
                    table: {column["name"] for column in inspector.get_columns(table)}
                    for table in (
                        "ai_chat_tool_calls",
                        "agent_step",
                        "system_assistant_action_tickets",
                        "system_assistant_action_runs",
                    )
                }

            tables = await conn.run_sync(schema)

        expected_compatibility = {
            "action_run_id",
            "correlation_id",
            "result_status",
            "error_code",
            "snapshot_digest",
        }
        assert expected_compatibility <= tables["ai_chat_tool_calls"]
        assert expected_compatibility <= tables["agent_step"]
        assert {"id", "tenant_id", "correlation_id", "status"} <= tables[
            "system_assistant_action_tickets"
        ]
        assert {"id", "ticket_id", "result_status", "error_code"} <= tables[
            "system_assistant_action_runs"
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_repairs_partial_indexes_and_is_idempotent(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'partial.sqlite3'}")
    try:
        async with engine.begin() as conn:
            await _legacy_schema(conn)
            await conn.execute(text("ALTER TABLE ai_chat_tool_calls ADD COLUMN action_run_id VARCHAR(36)"))
            await migrate_system_assistant_governance(conn)
            await migrate_system_assistant_governance(conn)

            def indexes(sync_conn):
                inspector = inspect(sync_conn)
                return {
                    table: {index["name"] for index in inspector.get_indexes(table)}
                    for table in ("ai_chat_tool_calls", "agent_step")
                }

            current_indexes = await conn.run_sync(indexes)

        assert "ix_ai_chat_tool_calls_action_run_id" in current_indexes["ai_chat_tool_calls"]
        assert "ix_ai_chat_tool_calls_correlation_id" in current_indexes["ai_chat_tool_calls"]
        assert "ix_agent_step_action_run_id" in current_indexes["agent_step"]
        assert "ix_agent_step_correlation_id" in current_indexes["agent_step"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_propagates_actual_ddl_error(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ddl-error.sqlite3'}")
    invalid_column = CompatibilityColumn(
        table_name="ai_chat_tool_calls",
        column_name="invalid_ddl",
        sql_type="VARCHAR(",
        index_name=None,
    )
    try:
        async with engine.begin() as conn:
            await _legacy_schema(conn)
            with pytest.raises(OperationalError):
                await migrate_system_assistant_governance(
                    conn,
                    compatibility_columns=(invalid_column,),
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_blocks_existing_governance_table_missing_status_constraint(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'missing-check.sqlite3'}")
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE system_assistant_action_tickets ("
                "id VARCHAR(36) PRIMARY KEY, tenant_id INTEGER NOT NULL, "
                "action_type VARCHAR(64) NOT NULL, correlation_id VARCHAR(64) NOT NULL, "
                "status VARCHAR(20) NOT NULL, summary TEXT, metadata_json JSON, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            ))
            with pytest.raises(Exception, match="check constraint"):
                await migrate_system_assistant_governance(conn)
    finally:
        await engine.dispose()
