"""Strict additive migration for B0 governance persistence."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from sqlalchemy import CheckConstraint, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.system_assistant_governance import ActionRun, ActionTicket


@dataclass(frozen=True)
class CompatibilityColumn:
    table_name: str
    column_name: str
    sql_type: str
    index_name: str | None


COMPATIBILITY_COLUMNS = tuple(
    CompatibilityColumn(table, column, sql_type, index_name)
    for table in ("ai_chat_tool_calls", "agent_step")
    for column, sql_type, index_name in (
        ("action_run_id", "VARCHAR(36)", f"ix_{table}_action_run_id"),
        ("correlation_id", "VARCHAR(64)", f"ix_{table}_correlation_id"),
        ("result_status", "VARCHAR(32)", None),
        ("error_code", "VARCHAR(64)", None),
        ("snapshot_digest", "VARCHAR(64)", None),
    )
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GovernanceSchemaMigrationError(RuntimeError):
    """An existing table cannot be made compliant with additive DDL."""


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid schema identifier: {value!r}")
    return value


async def _table_snapshot(conn: AsyncConnection, table_name: str) -> dict:
    def inspect_table(sync_conn):
        inspector = inspect(sync_conn)
        if not inspector.has_table(table_name):
            return {
                "exists": False,
                "columns": set(),
                "indexes": set(),
                "foreign_keys": [],
                "check_constraints": set(),
            }
        return {
            "exists": True,
            "columns": {column["name"] for column in inspector.get_columns(table_name)},
            "indexes": {index["name"] for index in inspector.get_indexes(table_name)},
            "foreign_keys": inspector.get_foreign_keys(table_name),
            "check_constraints": {
                constraint["name"]
                for constraint in inspector.get_check_constraints(table_name)
                if constraint.get("name")
            },
        }

    return await conn.run_sync(inspect_table)


async def _ensure_index(
    conn: AsyncConnection,
    *,
    table_name: str,
    index_name: str,
    columns: Iterable[str],
    unique: bool = False,
) -> None:
    state = await _table_snapshot(conn, table_name)
    if index_name in state["indexes"]:
        return
    qualifier = "UNIQUE " if unique else ""
    columns_sql = ", ".join(_identifier(column) for column in columns)
    await conn.execute(text(
        f"CREATE {qualifier}INDEX {_identifier(index_name)} "
        f"ON {_identifier(table_name)} ({columns_sql})"
    ))


async def _ensure_governance_table(conn: AsyncConnection, table) -> None:
    state = await _table_snapshot(conn, table.name)
    if not state["exists"]:
        await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))
        return

    missing_required = [
        column.name
        for column in table.columns
        if not column.nullable and column.name not in state["columns"]
    ]
    if missing_required:
        raise GovernanceSchemaMigrationError(
            f"{table.name} is missing non-nullable columns: {', '.join(missing_required)}"
        )

    for column in table.columns:
        if column.name in state["columns"] or not column.nullable:
            continue
        compiled_type = column.type.compile(dialect=conn.dialect)
        await conn.execute(text(
            f"ALTER TABLE {_identifier(table.name)} ADD COLUMN "
            f"{_identifier(column.name)} {compiled_type}"
        ))

    state = await _table_snapshot(conn, table.name)
    expected_checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }
    missing_checks = expected_checks - state["check_constraints"]
    if missing_checks:
        raise GovernanceSchemaMigrationError(
            f"{table.name} is missing check constraint(s): {', '.join(sorted(missing_checks))}"
        )


async def _ensure_ticket_foreign_key(conn: AsyncConnection) -> None:
    state = await _table_snapshot(conn, ActionRun.__tablename__)
    if any(
        foreign_key.get("referred_table") == ActionTicket.__tablename__
        and foreign_key.get("constrained_columns") == ["ticket_id"]
        and (foreign_key.get("options") or {}).get("ondelete", "").upper() == "SET NULL"
        for foreign_key in state["foreign_keys"]
    ):
        return
    if conn.dialect.name == "sqlite":
        raise GovernanceSchemaMigrationError(
            "SQLite cannot add the required ActionRun ticket_id SET NULL foreign key without a destructive rebuild"
        )
    await conn.execute(text(
        "ALTER TABLE system_assistant_action_runs "
        "ADD CONSTRAINT fk_system_assistant_action_runs_ticket_id "
        "FOREIGN KEY (ticket_id) REFERENCES system_assistant_action_tickets(id) ON DELETE SET NULL"
    ))


async def _ensure_governance_indexes(conn: AsyncConnection) -> None:
    await _ensure_index(
        conn,
        table_name=ActionTicket.__tablename__,
        index_name="ix_system_assistant_action_tickets_tenant_status",
        columns=("tenant_id", "status"),
    )
    await _ensure_index(
        conn,
        table_name=ActionTicket.__tablename__,
        index_name="uq_system_assistant_action_tickets_tenant_correlation",
        columns=("tenant_id", "correlation_id"),
        unique=True,
    )
    await _ensure_index(
        conn,
        table_name=ActionRun.__tablename__,
        index_name="ix_system_assistant_action_runs_ticket_created",
        columns=("ticket_id", "created_at"),
    )
    await _ensure_index(
        conn,
        table_name=ActionRun.__tablename__,
        index_name="ix_system_assistant_action_runs_tenant_correlation",
        columns=("tenant_id", "correlation_id"),
    )


async def migrate_system_assistant_governance(
    conn: AsyncConnection,
    *,
    compatibility_columns: tuple[CompatibilityColumn, ...] = COMPATIBILITY_COLUMNS,
) -> None:
    """Apply only inspected, additive B0 DDL and propagate every real failure."""

    await _ensure_governance_table(conn, ActionTicket.__table__)
    await _ensure_governance_table(conn, ActionRun.__table__)
    await _ensure_ticket_foreign_key(conn)
    await _ensure_governance_indexes(conn)

    for column in compatibility_columns:
        state = await _table_snapshot(conn, column.table_name)
        if not state["exists"]:
            continue
        if column.column_name not in state["columns"]:
            await conn.execute(text(
                f"ALTER TABLE {_identifier(column.table_name)} ADD COLUMN "
                f"{_identifier(column.column_name)} {column.sql_type}"
            ))
        if column.index_name:
            await _ensure_index(
                conn,
                table_name=column.table_name,
                index_name=column.index_name,
                columns=(column.column_name,),
            )
