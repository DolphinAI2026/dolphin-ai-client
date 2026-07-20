import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import inspect, text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.tenant import Tenant


TENANT_PUBLIC_ID_NAMESPACE = UUID("13ad9ef8-0005-5fc9-a95d-ac66f5c431ed")


@dataclass(frozen=True)
class TenantPublicIdReconciliation:
    scanned_count: int
    filled_count: int
    null_count: int
    null_tenant_ids: tuple[int, ...]
    conflict_tenant_ids: tuple[int, ...]
    invalid_tenant_ids: tuple[int, ...]


class TenantPublicIdStrictError(RuntimeError):
    def __init__(self, result: TenantPublicIdReconciliation):
        self.result = result
        self.tenant_ids = tuple(sorted(set(
            result.null_tenant_ids
            + result.conflict_tenant_ids
            + result.invalid_tenant_ids
        )))
        tenant_ids = ",".join(str(value) for value in self.tenant_ids)
        super().__init__(
            "tenant public ID reconciliation failed for tenant IDs: "
            f"{tenant_ids}"
        )


@dataclass(frozen=True)
class _TenantPublicIdAnalysis:
    null_tenant_ids: tuple[int, ...]
    conflict_tenant_ids: tuple[int, ...]
    invalid_tenant_ids: tuple[int, ...]
    backfill_tenant_ids: tuple[int, ...]


def new_tenant_public_id() -> str:
    return str(uuid4())


def historical_tenant_public_id(tenant_id: int) -> str:
    return str(uuid5(TENANT_PUBLIC_ID_NAMESPACE, f"tenant:{int(tenant_id)}"))


async def _tenant_columns(conn: Any) -> dict[str, dict[str, Any]]:
    return await conn.run_sync(
        lambda sync_conn: {
            str(column["name"]): column
            for column in inspect(sync_conn).get_columns("tenants")
        }
    )


def _is_expected_public_id_column(column: dict[str, Any] | None) -> bool:
    if column is None or not column.get("nullable", False):
        return False
    return getattr(column.get("type"), "length", None) == 36


def _is_duplicate_column_error(error: Exception) -> bool:
    message = str(error).lower()
    return "public_id" in message and (
        "duplicate column" in message
        or ("column" in message and "already exists" in message)
    )


def _is_duplicate_index_error(error: Exception) -> bool:
    message = str(error).lower()
    return "ix_tenants_public_id" in message and (
        "duplicate key name" in message
        or ("index" in message and "already exists" in message)
        or ("relation" in message and "already exists" in message)
    )


async def _ensure_nullable_column(conn: Any) -> None:
    columns = await _tenant_columns(conn)
    public_id_column = columns.get("public_id")
    if public_id_column is None:
        try:
            await conn.execute(text(
                "ALTER TABLE tenants ADD COLUMN public_id VARCHAR(36)"
            ))
        except Exception as exc:
            if not _is_duplicate_column_error(exc):
                raise
            if _is_expected_public_id_column(
                (await _tenant_columns(conn)).get("public_id")
            ):
                return
            raise
        return
    if _is_expected_public_id_column(public_id_column):
        return
    if public_id_column.get("nullable", True):
        raise RuntimeError(
            "tenants.public_id must be nullable VARCHAR(36)"
        )

    if conn.dialect.name == "postgresql":
        statement = "ALTER TABLE tenants ALTER COLUMN public_id DROP NOT NULL"
    elif conn.dialect.name == "mysql":
        statement = "ALTER TABLE tenants MODIFY COLUMN public_id VARCHAR(36) NULL"
    else:
        raise RuntimeError(
            "tenants.public_id must be nullable; SQLite requires a manual table rebuild"
        )
    await conn.execute(text(statement))
    if not _is_expected_public_id_column(
        (await _tenant_columns(conn)).get("public_id")
    ):
        raise RuntimeError("tenants.public_id must be nullable VARCHAR(36)")


async def _has_unique_public_id_index(conn: Any) -> bool:
    def has_unique_public_id_index(sync_conn: Any) -> bool:
        inspector = inspect(sync_conn)
        for index in inspector.get_indexes("tenants"):
            if index.get("unique") and index.get("column_names") == ["public_id"]:
                return True
        for constraint in inspector.get_unique_constraints("tenants"):
            if constraint.get("column_names") == ["public_id"]:
                return True
        return False

    return await conn.run_sync(has_unique_public_id_index)


async def _ensure_unique_index(conn: Any) -> None:
    if await _has_unique_public_id_index(conn):
        return
    try:
        await conn.execute(text(
            "CREATE UNIQUE INDEX ix_tenants_public_id ON tenants(public_id)"
        ))
    except Exception as exc:
        if not _is_duplicate_index_error(exc):
            raise
        if await _has_unique_public_id_index(conn):
            return
        raise


async def _tenant_public_id_rows(conn: Any) -> list[dict[str, Any]]:
    return list((await conn.execute(text(
        "SELECT id, public_id FROM tenants ORDER BY id"
    ))).mappings().all())


def _analyze_tenant_public_id_rows(
    rows: list[dict[str, Any]],
) -> _TenantPublicIdAnalysis:
    tenant_ids_by_value: dict[str, list[int]] = defaultdict(list)
    null_tenant_ids: list[int] = []
    invalid_tenant_ids: list[int] = []

    for row in rows:
        tenant_id = int(row["id"])
        value = row["public_id"]
        if value is None:
            null_tenant_ids.append(tenant_id)
            tenant_ids_by_value[historical_tenant_public_id(tenant_id)].append(tenant_id)
            continue
        if not isinstance(value, str):
            invalid_tenant_ids.append(tenant_id)
            continue
        try:
            parsed = UUID(value)
        except (TypeError, ValueError):
            invalid_tenant_ids.append(tenant_id)
            continue
        if value != str(parsed):
            invalid_tenant_ids.append(tenant_id)
            continue
        tenant_ids_by_value[value].append(tenant_id)

    conflict_tenant_ids = tuple(sorted(
        tenant_id
        for tenant_ids in tenant_ids_by_value.values()
        if len(tenant_ids) > 1
        for tenant_id in tenant_ids
    ))
    conflict_tenant_id_set = set(conflict_tenant_ids)
    return _TenantPublicIdAnalysis(
        null_tenant_ids=tuple(sorted(null_tenant_ids)),
        conflict_tenant_ids=conflict_tenant_ids,
        invalid_tenant_ids=tuple(sorted(invalid_tenant_ids)),
        backfill_tenant_ids=tuple(
            tenant_id
            for tenant_id in null_tenant_ids
            if tenant_id not in conflict_tenant_id_set
        ),
    )


async def _reconciliation_result(
    conn: Any,
    *,
    scanned_count: int,
    filled_count: int,
) -> TenantPublicIdReconciliation:
    analysis = _analyze_tenant_public_id_rows(await _tenant_public_id_rows(conn))
    result = TenantPublicIdReconciliation(
        scanned_count=scanned_count,
        filled_count=filled_count,
        null_count=len(analysis.null_tenant_ids),
        null_tenant_ids=analysis.null_tenant_ids,
        conflict_tenant_ids=analysis.conflict_tenant_ids,
        invalid_tenant_ids=analysis.invalid_tenant_ids,
    )
    if not (
        result.null_count
        or result.conflict_tenant_ids
        or result.invalid_tenant_ids
    ):
        await _ensure_unique_index(conn)
    return result


async def reconcile_tenant_public_ids(conn: Any) -> TenantPublicIdReconciliation:
    await _ensure_nullable_column(conn)
    rows = await _tenant_public_id_rows(conn)
    analysis = _analyze_tenant_public_id_rows(rows)
    filled_count = 0

    for tenant_id in analysis.backfill_tenant_ids:
        update_result = await conn.execute(
            text(
                "UPDATE tenants SET public_id = :public_id "
                "WHERE id = :id AND public_id IS NULL"
            ),
            {
                "id": tenant_id,
                "public_id": historical_tenant_public_id(tenant_id),
            },
        )
        if update_result.rowcount and update_result.rowcount > 0:
            filled_count += int(update_result.rowcount)

    return await _reconciliation_result(
        conn,
        scanned_count=len(rows),
        filled_count=filled_count,
    )


async def ensure_tenant_public_id(
    session: "AsyncSession",
    tenant: "Tenant",
) -> str:
    if tenant.public_id is None:
        tenant.public_id = new_tenant_public_id()
    await session.flush()
    return tenant.public_id


async def _verify_tenant_public_ids(conn: Any) -> TenantPublicIdReconciliation:
    scanned_count = int((await conn.execute(text(
        "SELECT COUNT(*) FROM tenants"
    ))).scalar_one())
    return await _reconciliation_result(
        conn,
        scanned_count=scanned_count,
        filled_count=0,
    )


def _format_result(result: TenantPublicIdReconciliation) -> str:
    null_tenant_ids = ",".join(str(value) for value in result.null_tenant_ids)
    conflict_tenant_ids = ",".join(str(value) for value in result.conflict_tenant_ids)
    invalid_tenant_ids = ",".join(str(value) for value in result.invalid_tenant_ids)
    return (
        f"scanned_count={result.scanned_count} "
        f"filled_count={result.filled_count} "
        f"null_count={result.null_count} "
        f"null_tenant_ids={null_tenant_ids} "
        f"conflict_tenant_ids={conflict_tenant_ids} "
        f"invalid_tenant_ids={invalid_tenant_ids}"
    )


async def _run_cli_reconciliation(verify_only_after_write: bool) -> TenantPublicIdReconciliation:
    from app.database import engine

    async with engine.begin() as conn:
        result = await reconcile_tenant_public_ids(conn)
    if not verify_only_after_write:
        return result
    async with engine.connect() as conn:
        return await _verify_tenant_public_ids(conn)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--verify-only-after-write", action="store_true")
    args = parser.parse_args()

    result = asyncio.run(_run_cli_reconciliation(args.verify_only_after_write))
    print(_format_result(result))
    if (
        result.null_count
        or result.conflict_tenant_ids
        or result.invalid_tenant_ids
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
