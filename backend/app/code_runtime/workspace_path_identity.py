"""Startup migration for device-wide local workspace path identity."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import inspect, text

from app.code_runtime.application_locations import local_workspace_path_digest


async def _execute_best_effort(conn, statement: str) -> None:
    if conn.dialect.name == "postgresql":
        try:
            async with conn.begin_nested():
                await conn.execute(text(statement))
        except Exception:
            return
    else:
        try:
            await conn.execute(text(statement))
        except Exception:
            return


async def _index_exists(conn, table_name: str, index_name: str) -> bool:
    return await conn.run_sync(
        lambda sync_conn: any(
            item.get("name") == index_name
            for item in inspect(sync_conn).get_indexes(table_name)
        )
    )


async def _create_required_unique_index(
    conn,
    statement: str,
    *,
    table_name: str,
    index_name: str,
) -> None:
    if await _index_exists(conn, table_name, index_name):
        return
    try:
        if conn.dialect.name == "postgresql":
            async with conn.begin_nested():
                await conn.execute(text(statement))
        else:
            await conn.execute(text(statement))
    except Exception as exc:
        if not await _index_exists(conn, table_name, index_name):
            raise RuntimeError(f"cannot create required unique index {index_name}") from exc


async def migrate_registered_workspace_path_identity(conn) -> None:
    """Backfill unambiguous path digests and enforce future uniqueness."""

    await _execute_best_effort(
        conn,
        "ALTER TABLE registered_workspaces ADD COLUMN path_identity_digest VARCHAR(64) NULL",
    )
    rows = (
        await conn.execute(text(
            "SELECT id, abs_path FROM registered_workspaces ORDER BY id"
        ))
    ).all()
    ids_by_digest: dict[str, list[int]] = defaultdict(list)
    for row_id, abs_path in rows:
        try:
            ids_by_digest[local_workspace_path_digest(abs_path)].append(int(row_id))
        except (OSError, ValueError):
            continue

    await conn.execute(text("UPDATE registered_workspaces SET path_identity_digest = NULL"))
    for digest, row_ids in ids_by_digest.items():
        if len(row_ids) != 1:
            continue
        await conn.execute(
            text(
                "UPDATE registered_workspaces SET path_identity_digest = :digest "
                "WHERE id = :row_id"
            ),
            {"digest": digest, "row_id": row_ids[0]},
        )

    legacy_index_names = ("uq_regws_tenant_path", "uq_regws_abs_path")
    for legacy_index_name in legacy_index_names:
        if conn.dialect.name == "mysql":
            statement = (
                f"DROP INDEX {legacy_index_name} ON registered_workspaces"
            )
        else:
            statement = f"DROP INDEX IF EXISTS {legacy_index_name}"
        await _execute_best_effort(conn, statement)
    await _create_required_unique_index(
        conn,
        "CREATE UNIQUE INDEX uq_regws_path_identity_digest "
        "ON registered_workspaces(path_identity_digest)",
        table_name="registered_workspaces",
        index_name="uq_regws_path_identity_digest",
    )
