import os
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.tenant import Tenant
from app.tenant_public_id import (
    ensure_tenant_public_id,
    historical_tenant_public_id,
    reconcile_tenant_public_ids,
)


@pytest_asyncio.fixture
async def sqlite_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield engine
    await engine.dispose()


async def _create_legacy_tenants(sqlite_engine, *, with_public_id: bool = False) -> None:
    public_id_column = ", public_id VARCHAR(36)" if with_public_id else ""
    async with sqlite_engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE tenants ("
            "id INTEGER PRIMARY KEY, "
            "tenant_name VARCHAR(128) NOT NULL, "
            "tenant_code VARCHAR(64) NOT NULL UNIQUE"
            f"{public_id_column}"
            ")"
        ))


async def run_reconciliation(sqlite_engine, legacy_rows):
    await _create_legacy_tenants(sqlite_engine)
    async with sqlite_engine.begin() as conn:
        for tenant_id, tenant_code in legacy_rows:
            await conn.execute(
                text(
                    "INSERT INTO tenants (id, tenant_name, tenant_code) "
                    "VALUES (:id, :tenant_name, :tenant_code)"
                ),
                {
                    "id": tenant_id,
                    "tenant_name": f"tenant-{tenant_id}",
                    "tenant_code": tenant_code,
                },
            )
        return await reconcile_tenant_public_ids(conn)


async def public_ids(sqlite_engine) -> list[str]:
    async with sqlite_engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT public_id FROM tenants ORDER BY id"
        ))).scalars().all()
    return [str(value) for value in rows]


async def public_id(sqlite_engine, tenant_id: int) -> str | None:
    async with sqlite_engine.connect() as conn:
        return (await conn.execute(
            text("SELECT public_id FROM tenants WHERE id = :id"),
            {"id": tenant_id},
        )).scalar_one()


async def seed_public_id(sqlite_engine, *, tenant_id: int, public_id: str | None) -> None:
    await _create_legacy_tenants(sqlite_engine, with_public_id=True)
    async with sqlite_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO tenants (id, tenant_name, tenant_code, public_id) "
                "VALUES (:id, :tenant_name, :tenant_code, :public_id)"
            ),
            {
                "id": tenant_id,
                "tenant_name": f"tenant-{tenant_id}",
                "tenant_code": f"tenant-{tenant_id}",
                "public_id": public_id,
            },
        )


async def old_writer_insert(sqlite_engine, *, tenant_id: int, public_id: str | None) -> None:
    async with sqlite_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO tenants (id, tenant_name, tenant_code, public_id) "
                "VALUES (:id, :tenant_name, :tenant_code, :public_id)"
            ),
            {
                "id": tenant_id,
                "tenant_name": f"tenant-{tenant_id}",
                "tenant_code": f"tenant-{tenant_id}",
                "public_id": public_id,
            },
        )


@pytest.mark.asyncio
async def test_reconcile_adds_nullable_column_and_backfills_stable_uuid5(sqlite_engine):
    result = await run_reconciliation(sqlite_engine, legacy_rows=[(1, "a"), (2, "b")])

    assert result.null_count == 0
    assert result.filled_count == 2
    assert await public_ids(sqlite_engine) == [
        historical_tenant_public_id(1),
        historical_tenant_public_id(2),
    ]


@pytest.mark.asyncio
async def test_reconcile_fills_null_inserted_by_old_writer_without_changing_existing_value(sqlite_engine):
    original = str(uuid4())
    await seed_public_id(sqlite_engine, tenant_id=1, public_id=original)
    await old_writer_insert(sqlite_engine, tenant_id=2, public_id=None)

    async with sqlite_engine.begin() as conn:
        await reconcile_tenant_public_ids(conn)

    assert await public_id(sqlite_engine, 1) == original
    assert await public_id(sqlite_engine, 2) == historical_tenant_public_id(2)


@pytest.mark.asyncio
async def test_reconcile_reports_duplicate_existing_public_ids_without_replacing_them(sqlite_engine):
    original = str(uuid4())
    await seed_public_id(sqlite_engine, tenant_id=1, public_id=original)
    await old_writer_insert(sqlite_engine, tenant_id=2, public_id=original)

    async with sqlite_engine.begin() as conn:
        result = await reconcile_tenant_public_ids(conn)

    assert result.conflict_tenant_ids == (1, 2)
    assert await public_ids(sqlite_engine) == [original, original]


@pytest.mark.asyncio
async def test_reconcile_rejects_noncanonical_existing_public_id(sqlite_engine):
    await seed_public_id(sqlite_engine, tenant_id=1, public_id=str(uuid4()).upper())

    async with sqlite_engine.begin() as conn:
        with pytest.raises(ValueError, match="invalid tenant public_id"):
            await reconcile_tenant_public_ids(conn)


@pytest.mark.asyncio
async def test_ensure_tenant_public_id_assigns_uuid4_and_flushes():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            tenant = Tenant(tenant_name="tenant", tenant_code="tenant")
            session.add(tenant)

            public_id_value = await ensure_tenant_public_id(session, tenant)

            assert tenant.id is not None
            assert public_id_value == tenant.public_id
            assert UUID(public_id_value).version == 4
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reconcile_runs_against_configured_sql_dialect():
    database_url = os.environ.get("TENANT_PUBLIC_ID_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TENANT_PUBLIC_ID_TEST_DATABASE_URL is not configured")

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS tenants"))
            await conn.execute(text(
                "CREATE TABLE tenants ("
                "id INTEGER PRIMARY KEY, "
                "tenant_name VARCHAR(128) NOT NULL, "
                "tenant_code VARCHAR(64) NOT NULL UNIQUE"
                ")"
            ))
            await conn.execute(text(
                "INSERT INTO tenants (id, tenant_name, tenant_code) "
                "VALUES (1, 'tenant-1', 'tenant-1')"
            ))

            result = await reconcile_tenant_public_ids(conn)

            assert result.filled_count == 1
            assert result.null_count == 0
            assert result.conflict_tenant_ids == ()
            assert (await conn.execute(text(
                "SELECT public_id FROM tenants WHERE id = 1"
            ))).scalar_one() == historical_tenant_public_id(1)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS tenants"))
        await engine.dispose()
