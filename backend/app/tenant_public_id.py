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
    conflict_tenant_ids: tuple[int, ...]


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


async def _ensure_nullable_column(conn: Any) -> None:
    columns = await _tenant_columns(conn)
    public_id_column = columns.get("public_id")
    if public_id_column is None:
        await conn.execute(text(
            "ALTER TABLE tenants ADD COLUMN public_id VARCHAR(36)"
        ))
        return
    if public_id_column.get("nullable", True):
        return

    if conn.dialect.name == "postgresql":
        statement = "ALTER TABLE tenants ALTER COLUMN public_id DROP NOT NULL"
    elif conn.dialect.name == "mysql":
        statement = "ALTER TABLE tenants MODIFY COLUMN public_id VARCHAR(36) NULL"
    else:
        raise RuntimeError(
            "tenants.public_id must be nullable; SQLite requires a manual table rebuild"
        )
    await conn.execute(text(statement))


async def _validate_uuid_values_and_conflicts(conn: Any) -> tuple[int, ...]:
    rows = (await conn.execute(text(
        "SELECT id, public_id FROM tenants ORDER BY id"
    ))).mappings().all()
    public_id_tenant_ids: dict[str, list[int]] = defaultdict(list)

    for row in rows:
        tenant_id = int(row["id"])
        value = row["public_id"]
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"invalid tenant public_id for tenant {tenant_id}")
        try:
            parsed = UUID(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid tenant public_id for tenant {tenant_id}"
            ) from exc
        if value != str(parsed):
            raise ValueError(f"invalid tenant public_id for tenant {tenant_id}")
        public_id_tenant_ids[value].append(tenant_id)

    return tuple(sorted(
        tenant_id
        for tenant_ids in public_id_tenant_ids.values()
        if len(tenant_ids) > 1
        for tenant_id in tenant_ids
    ))


async def _ensure_unique_index(conn: Any) -> None:
    def has_unique_public_id_index(sync_conn: Any) -> bool:
        inspector = inspect(sync_conn)
        for index in inspector.get_indexes("tenants"):
            if index.get("unique") and index.get("column_names") == ["public_id"]:
                return True
        for constraint in inspector.get_unique_constraints("tenants"):
            if constraint.get("column_names") == ["public_id"]:
                return True
        return False

    if await conn.run_sync(has_unique_public_id_index):
        return
    await conn.execute(text(
        "CREATE UNIQUE INDEX ix_tenants_public_id ON tenants(public_id)"
    ))


async def _reconciliation_result(
    conn: Any,
    *,
    scanned_count: int,
    filled_count: int,
) -> TenantPublicIdReconciliation:
    null_count = int((await conn.execute(text(
        "SELECT COUNT(*) FROM tenants WHERE public_id IS NULL"
    ))).scalar_one())
    conflict_tenant_ids = await _validate_uuid_values_and_conflicts(conn)
    if not conflict_tenant_ids:
        await _ensure_unique_index(conn)
    return TenantPublicIdReconciliation(
        scanned_count=scanned_count,
        filled_count=filled_count,
        null_count=null_count,
        conflict_tenant_ids=conflict_tenant_ids,
    )


async def reconcile_tenant_public_ids(conn: Any) -> TenantPublicIdReconciliation:
    await _ensure_nullable_column(conn)
    rows = (await conn.execute(text(
        "SELECT id, public_id FROM tenants ORDER BY id"
    ))).mappings().all()
    filled_count = 0

    for row in rows:
        if row["public_id"] is None:
            update_result = await conn.execute(
                text(
                    "UPDATE tenants SET public_id = :public_id "
                    "WHERE id = :id AND public_id IS NULL"
                ),
                {
                    "id": row["id"],
                    "public_id": historical_tenant_public_id(int(row["id"])),
                },
            )
            filled_count += int(update_result.rowcount or 0)

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
    conflict_tenant_ids = ",".join(str(value) for value in result.conflict_tenant_ids)
    return (
        f"scanned_count={result.scanned_count} "
        f"filled_count={result.filled_count} "
        f"null_count={result.null_count} "
        f"conflict_tenant_ids={conflict_tenant_ids}"
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
    if result.null_count or result.conflict_tenant_ids:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
