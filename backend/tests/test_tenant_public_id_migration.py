import asyncio
import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import String, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app import database, tenant_public_id
from app.database import Base
from app.models.tenant import Tenant
from app.tenant_public_id import (
    TenantPublicIdStrictError,
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


class _DdlRaceConnection:
    def __init__(self, error: Exception):
        self.dialect = SimpleNamespace(name="sqlite")
        self.error = error
        self.executed_statements: list[str] = []

    async def execute(self, statement, *_args, **_kwargs):
        self.executed_statements.append(str(statement))
        raise self.error


class _PostgresqlDdlRaceConnection(_DdlRaceConnection):
    def __init__(self, error: Exception):
        super().__init__(error)
        self.dialect = SimpleNamespace(name="postgresql")
        self.savepoint_rolled_back = False

    def begin_nested(self):
        return _PostgresqlSavepoint(self)


class _PostgresqlSavepoint:
    def __init__(self, conn: _PostgresqlDdlRaceConnection):
        self.conn = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, *_args):
        self.conn.savepoint_rolled_back = exc_type is not None
        return False


class _NoopBegin:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def run_sync(self, _fn):
        return None


class _NoopEngine:
    def begin(self):
        return _NoopBegin()


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
async def test_reconcile_reports_noncanonical_existing_public_id(sqlite_engine):
    await seed_public_id(sqlite_engine, tenant_id=1, public_id=str(uuid4()).upper())

    async with sqlite_engine.begin() as conn:
        result = await reconcile_tenant_public_ids(conn)

    assert result.invalid_tenant_ids == (1,)


@pytest.mark.asyncio
async def test_reconcile_reports_every_invalid_tenant_id_without_traceback(sqlite_engine):
    await seed_public_id(sqlite_engine, tenant_id=4, public_id=str(uuid4()).upper())
    await old_writer_insert(sqlite_engine, tenant_id=9, public_id="not-a-uuid")

    async with sqlite_engine.begin() as conn:
        result = await reconcile_tenant_public_ids(conn)

    assert result.invalid_tenant_ids == (4, 9)
    assert result.conflict_tenant_ids == ()


@pytest.mark.asyncio
async def test_reconcile_does_not_partially_backfill_when_invalid_values_block_strict_state(
    sqlite_engine,
):
    await seed_public_id(sqlite_engine, tenant_id=2, public_id=None)
    await old_writer_insert(sqlite_engine, tenant_id=9, public_id="not-a-uuid")

    async with sqlite_engine.begin() as conn:
        result = await reconcile_tenant_public_ids(conn)

    assert result.filled_count == 0
    assert result.null_tenant_ids == (2,)
    assert result.invalid_tenant_ids == (9,)
    assert await public_id(sqlite_engine, 2) is None


@pytest.mark.asyncio
async def test_reconcile_reports_historical_uuid_collision_before_writing_null_row(sqlite_engine):
    await seed_public_id(
        sqlite_engine,
        tenant_id=1,
        public_id=historical_tenant_public_id(2),
    )
    await old_writer_insert(sqlite_engine, tenant_id=2, public_id=None)
    async with sqlite_engine.begin() as conn:
        await conn.execute(text(
            "CREATE UNIQUE INDEX ix_tenants_public_id ON tenants(public_id)"
        ))
        result = await reconcile_tenant_public_ids(conn)

    assert result.conflict_tenant_ids == (1, 2)
    assert result.null_tenant_ids == (2,)
    assert await public_id(sqlite_engine, 2) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "tenant_ids"),
    [
        (
            SimpleNamespace(
                null_count=0,
                null_tenant_ids=(),
                conflict_tenant_ids=(7, 11),
                invalid_tenant_ids=(),
            ),
            (7, 11),
        ),
        (
            SimpleNamespace(
                null_count=2,
                null_tenant_ids=(4, 9),
                conflict_tenant_ids=(),
                invalid_tenant_ids=(),
            ),
            (4, 9),
        ),
    ],
)
async def test_init_db_blocks_strict_reconciliation_with_all_tenant_ids(
    monkeypatch,
    result,
    tenant_ids,
):
    async def reconcile(_conn):
        return result

    monkeypatch.setattr(database, "engine", _NoopEngine())
    monkeypatch.setattr(database, "reconcile_tenant_public_ids", reconcile)

    with pytest.raises(RuntimeError) as exc_info:
        await database.init_db()

    assert all(str(tenant_id) in str(exc_info.value) for tenant_id in tenant_ids)


@pytest.mark.asyncio
async def test_init_db_reports_durable_null_and_invalid_ids_without_partial_backfill(
    monkeypatch,
    tmp_path,
):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'strict-reconciliation.db'}"
    )
    try:
        await _create_legacy_tenants(engine, with_public_id=True)
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO tenants (id, tenant_name, tenant_code, public_id) "
                "VALUES (2, 'tenant-2', 'tenant-2', NULL), "
                "(9, 'tenant-9', 'tenant-9', 'not-a-uuid')"
            ))

        monkeypatch.setattr(database, "engine", engine)

        with pytest.raises(TenantPublicIdStrictError) as exc_info:
            await database.init_db()

        result = exc_info.value.result
        assert result.filled_count == 0
        assert result.null_tenant_ids == (2,)
        assert result.invalid_tenant_ids == (9,)
        assert exc_info.value.tenant_ids == (2, 9)
        async with engine.connect() as conn:
            durable_rows = (await conn.execute(text(
                "SELECT id, public_id FROM tenants WHERE id IN (2, 9) ORDER BY id"
            ))).all()
        assert durable_rows == [(2, None), (9, "not-a-uuid")]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_add_column_race_is_tolerated_only_after_expected_column_recheck(monkeypatch):
    column_states = iter([
        {},
        {
            "public_id": {
                "nullable": True,
                "type": String(36),
            },
        },
    ])

    async def tenant_columns(_conn):
        return next(column_states)

    monkeypatch.setattr(tenant_public_id, "_tenant_columns", tenant_columns)
    conn = _DdlRaceConnection(RuntimeError("duplicate column name: public_id"))

    await tenant_public_id._ensure_nullable_column(conn)

    assert conn.executed_statements == [
        "ALTER TABLE tenants ADD COLUMN public_id VARCHAR(36)"
    ]


@pytest.mark.asyncio
async def test_add_column_race_rethrows_when_recheck_is_not_expected(monkeypatch):
    column_states = iter([{}, {}])

    async def tenant_columns(_conn):
        return next(column_states)

    error = RuntimeError("duplicate column name: public_id")
    monkeypatch.setattr(tenant_public_id, "_tenant_columns", tenant_columns)

    with pytest.raises(RuntimeError, match="duplicate column name"):
        await tenant_public_id._ensure_nullable_column(_DdlRaceConnection(error))


@pytest.mark.asyncio
async def test_postgresql_add_column_race_rechecks_after_savepoint_rollback(monkeypatch):
    error = RuntimeError("driver error")
    error.orig = SimpleNamespace(sqlstate="42701")
    conn = _PostgresqlDdlRaceConnection(error)

    async def tenant_columns(_conn):
        if conn.savepoint_rolled_back:
            return {
                "public_id": {
                    "nullable": True,
                    "type": String(36),
                },
            }
        return {}

    monkeypatch.setattr(tenant_public_id, "_tenant_columns", tenant_columns)

    await tenant_public_id._ensure_nullable_column(conn)

    assert conn.savepoint_rolled_back is True
    assert conn.executed_statements == [
        "ALTER TABLE tenants ADD COLUMN public_id VARCHAR(36)"
    ]


@pytest.mark.asyncio
async def test_create_unique_index_race_is_tolerated_only_after_expected_index_recheck(monkeypatch):
    index_states = iter([False, True])

    async def has_unique_index(_conn):
        return next(index_states)

    monkeypatch.setattr(
        tenant_public_id,
        "_has_unique_public_id_index",
        has_unique_index,
        raising=False,
    )
    conn = _DdlRaceConnection(RuntimeError(
        "index ix_tenants_public_id already exists"
    ))

    await tenant_public_id._ensure_unique_index(conn)

    assert conn.executed_statements == [
        "CREATE UNIQUE INDEX ix_tenants_public_id ON tenants(public_id)"
    ]


@pytest.mark.asyncio
async def test_create_unique_index_propagates_non_race_errors(monkeypatch):
    async def has_unique_index(_conn):
        return False

    monkeypatch.setattr(
        tenant_public_id,
        "_has_unique_public_id_index",
        has_unique_index,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="connection lost"):
        await tenant_public_id._ensure_unique_index(
            _DdlRaceConnection(RuntimeError("connection lost"))
        )


@pytest.mark.asyncio
async def test_postgresql_create_index_race_rechecks_after_savepoint_rollback(monkeypatch):
    error = RuntimeError("driver error")
    error.orig = SimpleNamespace(pgcode="42P07")
    conn = _PostgresqlDdlRaceConnection(error)

    async def has_unique_index(_conn):
        return conn.savepoint_rolled_back

    monkeypatch.setattr(
        tenant_public_id,
        "_has_unique_public_id_index",
        has_unique_index,
    )

    await tenant_public_id._ensure_unique_index(conn)

    assert conn.savepoint_rolled_back is True
    assert conn.executed_statements == [
        "CREATE UNIQUE INDEX ix_tenants_public_id ON tenants(public_id)"
    ]


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
async def test_ensure_tenant_public_id_durably_backfills_legacy_null_across_sessions(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'tenant-public-id-durable.db'}"
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            tenant = Tenant(tenant_name="tenant", tenant_code="tenant")
            session.add(tenant)
            await session.commit()
            tenant_id = tenant.id

        async with session_factory() as session:
            tenant = await session.get(Tenant, tenant_id)
            tenant.public_id = None
            await session.commit()

        async with session_factory() as session:
            tenant = await session.get(Tenant, tenant_id)
            projected_public_id = await ensure_tenant_public_id(session, tenant)
            await session.commit()

        async with session_factory() as session:
            persisted = await session.get(Tenant, tenant_id)

        assert projected_public_id == historical_tenant_public_id(tenant_id)
        assert persisted.public_id == projected_public_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_tenant_public_id_concurrently_returns_the_durable_legacy_value(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'tenant-public-id-concurrent.db'}"
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            tenant = Tenant(tenant_name="tenant", tenant_code="tenant")
            session.add(tenant)
            await session.commit()
            tenant_id = tenant.id

        async with session_factory() as session:
            tenant = await session.get(Tenant, tenant_id)
            tenant.public_id = None
            await session.commit()

        barrier = asyncio.Barrier(2)

        async def project_public_id() -> str:
            async with session_factory() as session:
                tenant = await session.get(Tenant, tenant_id)
                await barrier.wait()
                public_id_value = await ensure_tenant_public_id(session, tenant)
                await session.commit()
                return public_id_value

        first, second = await asyncio.gather(
            project_public_id(),
            project_public_id(),
        )

        async with session_factory() as session:
            persisted = await session.get(Tenant, tenant_id)

        assert first == second == persisted.public_id
        assert persisted.public_id == historical_tenant_public_id(tenant_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_tenant_public_id_reuses_callers_pool_connection_and_commit_is_durable(
    tmp_path,
):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'tenant-public-id-one-connection.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
        poolclass=AsyncAdaptedQueuePool,
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            tenant = Tenant(tenant_name="tenant", tenant_code="tenant")
            session.add(tenant)
            await session.commit()
            tenant_id = tenant.id

        async with session_factory() as session:
            tenant = await session.get(Tenant, tenant_id)
            tenant.public_id = None
            await session.commit()

        async with session_factory() as session:
            tenant = (
                await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            ).scalar_one()

            public_id_value = await asyncio.wait_for(
                ensure_tenant_public_id(session, tenant),
                timeout=1,
            )
            await session.commit()

        async with session_factory() as session:
            persisted = await session.get(Tenant, tenant_id)

        assert public_id_value == historical_tenant_public_id(tenant_id)
        assert persisted.public_id == public_id_value
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_tenant_public_id_does_not_autoflush_or_commit_pending_state(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'tenant-public-id-pending-state.db'}",
        pool_size=2,
        max_overflow=0,
        poolclass=AsyncAdaptedQueuePool,
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as session:
            legacy_tenant = Tenant(tenant_name="legacy", tenant_code="legacy")
            unrelated_tenant = Tenant(tenant_name="other", tenant_code="other")
            session.add_all([legacy_tenant, unrelated_tenant])
            await session.commit()
            legacy_tenant_id = legacy_tenant.id
            unrelated_tenant_id = unrelated_tenant.id

        async with session_factory() as session:
            legacy_tenant = await session.get(Tenant, legacy_tenant_id)
            legacy_tenant.public_id = None
            await session.commit()

        async with session_factory() as session:
            legacy_tenant = await session.get(Tenant, legacy_tenant_id)
            unrelated_tenant = await session.get(Tenant, unrelated_tenant_id)
            unrelated_tenant.tenant_name = "not yet committed"
            flushes = []

            def track_flush(*_args):
                flushes.append(True)

            event.listen(session.sync_session, "before_flush", track_flush)
            try:
                public_id_value = await ensure_tenant_public_id(session, legacy_tenant)
            finally:
                event.remove(session.sync_session, "before_flush", track_flush)

            assert public_id_value == historical_tenant_public_id(legacy_tenant_id)
            assert flushes == []
            await session.rollback()

        async with session_factory() as session:
            persisted_legacy = await session.get(Tenant, legacy_tenant_id)
            persisted_unrelated = await session.get(Tenant, unrelated_tenant_id)

        assert persisted_legacy.public_id is None
        assert persisted_unrelated.tenant_name == "other"
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
