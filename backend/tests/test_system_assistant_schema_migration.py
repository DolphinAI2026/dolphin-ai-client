"""Strict, additive B0 schema migration checks."""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateTable

from app.system_assistant.schema_migration import (
    CompatibilityColumn,
    GovernanceSchemaMigrationError,
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
        assert {"ticket_id", "tenant_id", "correlation_id", "status"} <= tables[
            "system_assistant_action_tickets"
        ]
        assert {"run_id", "ticket_id", "result_status", "error_code"} <= tables[
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
    from sqlalchemy.dialects.sqlite import dialect
    from app.models.system_assistant_governance import ActionTicket

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'missing-check.sqlite3'}")
    table_sql = str(CreateTable(ActionTicket.__table__).compile(dialect=dialect()))
    table_sql = re.sub(
        r",?\s*CONSTRAINT ck_system_assistant_action_tickets_status CHECK \(status IN \([^)]*\)\)",
        "",
        table_sql,
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(text(table_sql))
            with pytest.raises(Exception, match="check constraint"):
                await migrate_system_assistant_governance(conn)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_missing_named_checks_keep_raw_sql_expressions_for_additive_ddl(monkeypatch):
    from app.models.system_assistant_governance import ActionRun
    from app.system_assistant import schema_migration

    statements = []

    async def snapshot(_conn, _table_name):
        return {"check_constraints": []}

    class FakeConnection:
        dialect = SimpleNamespace(name="postgresql")

        async def execute(self, statement):
            statements.append(str(statement))

    monkeypatch.setattr(schema_migration, "_table_snapshot", snapshot)

    await schema_migration._ensure_check_constraints(FakeConnection(), ActionRun.__table__)

    assert any("CHECK (status IN (" in statement for statement in statements)
    assert any("CHECK (audit_delivery_status IN (" in statement for statement in statements)


@pytest.mark.asyncio
async def test_migration_blocks_same_name_index_with_wrong_definition(tmp_path):
    from app.models.system_assistant_governance import ActionTicket

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wrong-index.sqlite3'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(ActionTicket.__table__.create)
            await conn.execute(text("DROP INDEX ix_system_assistant_action_tickets_tenant_user_status_expires"))
            await conn.execute(text(
                "CREATE INDEX ix_system_assistant_action_tickets_tenant_user_status_expires "
                "ON system_assistant_action_tickets(status)"
            ))
            with pytest.raises(Exception, match="index definition mismatch"):
                await migrate_system_assistant_governance(conn)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_blocks_same_name_check_with_wrong_expression(tmp_path):
    from sqlalchemy.dialects.sqlite import dialect
    from app.models.system_assistant_governance import ActionTicket

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wrong-check.sqlite3'}")
    table_sql = str(CreateTable(ActionTicket.__table__).compile(dialect=dialect()))
    table_sql = re.sub(
        r"CHECK \(status IN \([^)]*\)\)",
        "CHECK (status IN ('wrong'))",
        table_sql,
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(text(table_sql))
            with pytest.raises(Exception, match="check constraint definition mismatch"):
                await migrate_system_assistant_governance(conn)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_blocks_existing_column_type_drift(tmp_path):
    from sqlalchemy.dialects.sqlite import dialect
    from app.models.system_assistant_governance import ActionTicket

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wrong-type.sqlite3'}")
    table_sql = str(CreateTable(ActionTicket.__table__).compile(dialect=dialect()))
    table_sql = table_sql.replace("tenant_id BIGINT", "tenant_id TEXT")
    try:
        async with engine.begin() as conn:
            await conn.execute(text(table_sql))
            with pytest.raises(Exception, match="column definition mismatch"):
                await migrate_system_assistant_governance(conn)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_blocks_same_name_foreign_key_with_wrong_ondelete(tmp_path):
    from sqlalchemy.dialects.sqlite import dialect
    from app.models.system_assistant_governance import ActionRun, ActionTicket

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wrong-foreign-key.sqlite3'}")
    table_sql = str(CreateTable(ActionRun.__table__).compile(dialect=dialect()))
    table_sql = table_sql.replace(
        "CONSTRAINT fk_system_assistant_action_runs_ticket_id "
        "FOREIGN KEY(ticket_id) REFERENCES system_assistant_action_tickets "
        "(ticket_id) ON DELETE SET NULL",
        "CONSTRAINT fk_system_assistant_action_runs_ticket_id "
        "FOREIGN KEY(ticket_id) REFERENCES system_assistant_action_tickets "
        "(ticket_id) ON DELETE CASCADE",
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE ai_chat_tool_calls (id INTEGER PRIMARY KEY)"))
            await conn.run_sync(ActionTicket.__table__.create)
            await conn.execute(text(table_sql))
            with pytest.raises(
                GovernanceSchemaMigrationError,
                match="foreign key definition mismatch",
            ):
                await migrate_system_assistant_governance(conn)
    finally:
        await engine.dispose()
