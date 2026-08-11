"""Strict, additive schema validation for B0 governance persistence."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, inspect, text
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
        ("correlation_id", "VARCHAR(36)", f"ix_{table}_correlation_id"),
        ("result_status", "VARCHAR(32)", None),
        ("error_code", "VARCHAR(120)", None),
        ("snapshot_digest", "VARCHAR(64)", None),
    )
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GovernanceSchemaMigrationError(RuntimeError):
    """Existing schema is incompatible and cannot be repaired additively."""


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid schema identifier: {value!r}")
    return value


def _normalise_sql(value: Any) -> str:
    return re.sub(r"\s+", "", str(value)).lower()


def _type_signature(value: Any, dialect: Any) -> str:
    return _normalise_sql(value.compile(dialect=dialect))


async def _table_snapshot(conn: AsyncConnection, table_name: str) -> dict[str, Any]:
    def inspect_table(sync_conn):
        inspector = inspect(sync_conn)
        if not inspector.has_table(table_name):
            return {"exists": False}
        return {
            "exists": True,
            "columns": {column["name"]: column for column in inspector.get_columns(table_name)},
            "indexes": {index["name"]: index for index in inspector.get_indexes(table_name)},
            "unique_constraints": inspector.get_unique_constraints(table_name),
            "check_constraints": inspector.get_check_constraints(table_name),
            "foreign_keys": inspector.get_foreign_keys(table_name),
            "primary_key": inspector.get_pk_constraint(table_name),
        }

    return await conn.run_sync(inspect_table)


def _expected_check_constraints(table) -> dict[str, str]:
    return {
        constraint.name: _normalise_sql(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }


def _expected_foreign_keys(table) -> list[dict[str, Any]]:
    return [
        {
            "name": constraint.name,
            "columns": [element.parent.name for element in constraint.elements],
            "referred_table": constraint.elements[0].column.table.name,
            "referred_columns": [element.column.name for element in constraint.elements],
            "ondelete": (constraint.ondelete or "").upper(),
        }
        for constraint in table.foreign_key_constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]


def _foreign_key_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return (
        actual.get("constrained_columns") == expected["columns"]
        and actual.get("referred_table") == expected["referred_table"]
        and actual.get("referred_columns") == expected["referred_columns"]
        and (actual.get("options") or {}).get("ondelete", "").upper() == expected["ondelete"]
    )


async def _ensure_index(
    conn: AsyncConnection,
    *,
    table_name: str,
    index_name: str,
    columns: Iterable[str],
    unique: bool = False,
) -> None:
    expected_columns = list(columns)
    state = await _table_snapshot(conn, table_name)
    actual = state["indexes"].get(index_name)
    if actual:
        if actual.get("column_names") != expected_columns or bool(actual.get("unique")) != unique:
            raise GovernanceSchemaMigrationError(
                f"{table_name} index definition mismatch: {index_name}"
            )
        return
    if any(
        index.get("column_names") == expected_columns and bool(index.get("unique")) == unique
        for index in state["indexes"].values()
    ):
        return
    qualifier = "UNIQUE " if unique else ""
    columns_sql = ", ".join(_identifier(column) for column in expected_columns)
    await conn.execute(text(
        f"CREATE {qualifier}INDEX {_identifier(index_name)} "
        f"ON {_identifier(table_name)} ({columns_sql})"
    ))


async def _ensure_unique_constraint(conn: AsyncConnection, table, constraint: UniqueConstraint) -> None:
    expected_columns = list(constraint.columns.keys())
    state = await _table_snapshot(conn, table.name)
    named = next(
        (item for item in state["unique_constraints"] if item.get("name") == constraint.name),
        None,
    )
    if named:
        if named.get("column_names") != expected_columns:
            raise GovernanceSchemaMigrationError(
                f"{table.name} unique constraint definition mismatch: {constraint.name}"
            )
        return
    if any(item.get("column_names") == expected_columns for item in state["unique_constraints"]):
        return
    await _ensure_index(
        conn,
        table_name=table.name,
        index_name=constraint.name or f"uq_{table.name}_{'_'.join(expected_columns)}",
        columns=expected_columns,
        unique=True,
    )


async def _ensure_check_constraints(conn: AsyncConnection, table) -> None:
    state = await _table_snapshot(conn, table.name)
    actual_by_name = {
        constraint.get("name"): _normalise_sql(constraint.get("sqltext", ""))
        for constraint in state["check_constraints"]
        if constraint.get("name")
    }
    for name, expected_sql in _expected_check_constraints(table).items():
        actual_sql = actual_by_name.get(name)
        if actual_sql is not None:
            if actual_sql != expected_sql:
                raise GovernanceSchemaMigrationError(
                    f"{table.name} check constraint definition mismatch: {name}"
                )
            continue
        if conn.dialect.name == "sqlite":
            raise GovernanceSchemaMigrationError(
                f"{table.name} is missing check constraint {name}; SQLite requires a destructive rebuild"
            )
        await conn.execute(text(
            f"ALTER TABLE {_identifier(table.name)} ADD CONSTRAINT {_identifier(name)} "
            f"CHECK ({expected_sql})"
        ))


async def _ensure_foreign_keys(conn: AsyncConnection, table) -> None:
    state = await _table_snapshot(conn, table.name)
    for expected in _expected_foreign_keys(table):
        named = next(
            (item for item in state["foreign_keys"] if item.get("name") == expected["name"]),
            None,
        )
        if named:
            if not _foreign_key_matches(named, expected):
                raise GovernanceSchemaMigrationError(
                    f"{table.name} foreign key definition mismatch: {expected['name']}"
                )
            continue
        if any(_foreign_key_matches(item, expected) for item in state["foreign_keys"]):
            continue
        if conn.dialect.name == "sqlite":
            raise GovernanceSchemaMigrationError(
                f"{table.name} is missing foreign key {expected['name']}; SQLite requires a destructive rebuild"
            )
        columns_sql = ", ".join(_identifier(column) for column in expected["columns"])
        referred_columns = ", ".join(_identifier(column) for column in expected["referred_columns"])
        await conn.execute(text(
            f"ALTER TABLE {_identifier(table.name)} ADD CONSTRAINT {_identifier(expected['name'])} "
            f"FOREIGN KEY ({columns_sql}) REFERENCES {_identifier(expected['referred_table'])} "
            f"({referred_columns}) ON DELETE {expected['ondelete']}"
        ))


async def _ensure_governance_table(conn: AsyncConnection, table) -> None:
    state = await _table_snapshot(conn, table.name)
    if not state["exists"]:
        await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))
        return

    expected_pk = list(table.primary_key.columns.keys())
    if state["primary_key"].get("constrained_columns") != expected_pk:
        raise GovernanceSchemaMigrationError(f"{table.name} primary key definition mismatch")

    missing_required = [
        column.name for column in table.columns
        if not column.nullable and column.name not in state["columns"]
    ]
    if missing_required:
        raise GovernanceSchemaMigrationError(
            f"{table.name} is missing non-nullable columns: {', '.join(missing_required)}"
        )

    for column in table.columns:
        actual = state["columns"].get(column.name)
        if actual is None:
            await conn.execute(text(
                f"ALTER TABLE {_identifier(table.name)} ADD COLUMN {_identifier(column.name)} "
                f"{column.type.compile(dialect=conn.dialect)}"
            ))
            continue
        expected_type = _type_signature(column.type, conn.dialect)
        actual_type = _type_signature(actual["type"], conn.dialect)
        if (
            expected_type != actual_type
            or bool(actual.get("nullable")) != column.nullable
            or bool(column.primary_key) != (column.name in expected_pk)
        ):
            raise GovernanceSchemaMigrationError(
                f"{table.name} column definition mismatch: {column.name}"
            )

    await _ensure_check_constraints(conn, table)
    await _ensure_foreign_keys(conn, table)
    for index in table.indexes:
        await _ensure_index(
            conn,
            table_name=table.name,
            index_name=index.name,
            columns=[column.name for column in index.columns],
            unique=index.unique,
        )
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            await _ensure_unique_constraint(conn, table, constraint)


async def _ensure_compatibility_column(conn: AsyncConnection, column: CompatibilityColumn) -> None:
    state = await _table_snapshot(conn, column.table_name)
    if not state["exists"]:
        return
    actual = state["columns"].get(column.column_name)
    if actual is None:
        await conn.execute(text(
            f"ALTER TABLE {_identifier(column.table_name)} ADD COLUMN "
            f"{_identifier(column.column_name)} {column.sql_type}"
        ))
    elif _normalise_sql(actual["type"].compile(dialect=conn.dialect)) != _normalise_sql(column.sql_type):
        raise GovernanceSchemaMigrationError(
            f"{column.table_name} column definition mismatch: {column.column_name}"
        )
    elif not actual.get("nullable"):
        raise GovernanceSchemaMigrationError(
            f"{column.table_name} compatibility column must be nullable: {column.column_name}"
        )
    if column.index_name:
        await _ensure_index(
            conn,
            table_name=column.table_name,
            index_name=column.index_name,
            columns=(column.column_name,),
        )


async def migrate_system_assistant_governance(
    conn: AsyncConnection,
    *,
    compatibility_columns: tuple[CompatibilityColumn, ...] = COMPATIBILITY_COLUMNS,
) -> None:
    """Validate or add only B0 additive schema; real DDL errors always propagate."""

    await _ensure_governance_table(conn, ActionTicket.__table__)
    await _ensure_governance_table(conn, ActionRun.__table__)
    for column in compatibility_columns:
        await _ensure_compatibility_column(conn, column)
