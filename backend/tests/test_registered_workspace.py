import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select, text

from app.database import Base
from app.models import RegisteredWorkspace


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s


@pytest.mark.asyncio
async def test_insert_and_query(session):
    session.add(RegisteredWorkspace(
        ws_id="1_abc12345", abs_path="/Users/x/proj", user_id=1, tenant_id=1,
        workspace_type="external", display_name="proj",
    ))
    await session.commit()
    row = (await session.execute(select(RegisteredWorkspace).where(RegisteredWorkspace.ws_id == "1_abc12345"))).scalar_one()
    assert row.abs_path == "/Users/x/proj" and row.workspace_type == "external" and row.apaas_app_id is None


@pytest.mark.asyncio
async def test_unique_device_path_digest(session):
    from sqlalchemy.exc import IntegrityError
    from app.code_runtime.application_locations import local_workspace_path_digest

    digest = local_workspace_path_digest("/p")
    session.add(RegisteredWorkspace(
        ws_id="1_a",
        abs_path="/p",
        path_identity_digest=digest,
        user_id=1,
        tenant_id=1,
        display_name="p",
    ))
    await session.commit()
    session.add(RegisteredWorkspace(
        ws_id="1_b",
        abs_path="/p",
        path_identity_digest=digest,
        user_id=1,
        tenant_id=2,
        display_name="p",
    ))
    with pytest.raises(IntegrityError):
        await session.commit()


def test_registered_workspace_uses_full_path_digest_unique_index():
    column = RegisteredWorkspace.__table__.columns["path_identity_digest"]
    index = next(
        item for item in RegisteredWorkspace.__table__.indexes
        if item.name == "uq_regws_path_identity_digest"
    )

    assert column.type.length == 64
    assert column.nullable is True
    assert index.unique is True
    assert [expression.name for expression in index.expressions] == ["path_identity_digest"]
    assert "uq_regws_abs_path" not in {item.name for item in RegisteredWorkspace.__table__.indexes}
    assert "uq_regws_tenant_path" not in {item.name for item in RegisteredWorkspace.__table__.indexes}


@pytest.mark.asyncio
async def test_path_identity_migration_backfills_unique_rows_and_leaves_duplicate_group_unclaimed():
    from app.database import migrate_registered_workspace_path_identity
    from app.code_runtime.application_locations import local_workspace_path_digest

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE registered_workspaces (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                abs_path VARCHAR(1000) NOT NULL
            )
        """))
        await conn.execute(text(
            "CREATE UNIQUE INDEX uq_regws_tenant_path "
            "ON registered_workspaces(tenant_id, abs_path)"
        ))
        await conn.execute(text("""
            INSERT INTO registered_workspaces (id, tenant_id, abs_path) VALUES
            (1, 1, '/workspace/unique'),
            (2, 1, '/workspace/duplicate'),
            (3, 2, '/workspace/duplicate')
        """))
        await migrate_registered_workspace_path_identity(conn)
        rows = (
            await conn.execute(text(
                "SELECT id, path_identity_digest FROM registered_workspaces ORDER BY id"
            ))
        ).all()
        legacy_indexes = {
            row[1]
            for row in (await conn.execute(text("PRAGMA index_list('registered_workspaces')"))).all()
        }

    await engine.dispose()
    assert rows == [
        (1, local_workspace_path_digest('/workspace/unique')),
        (2, None),
        (3, None),
    ]
    assert "uq_regws_tenant_path" not in legacy_indexes


def test_workspace_manager_external(tmp_path):
    from app.coding.workspace import WorkspaceManager
    WorkspaceManager._external_paths.clear()
    wm = WorkspaceManager()
    wm.register_external("ext_1", str(tmp_path))
    assert wm.get_workspace_path("ext_1") == tmp_path.resolve() or wm.get_workspace_path("ext_1") == tmp_path
    WorkspaceManager._external_paths.clear()


def test_workspace_manager_external_missing_folder(tmp_path):
    import pytest
    from app.coding.workspace import WorkspaceManager
    WorkspaceManager._external_paths.clear()
    missing = tmp_path / "gone"
    WorkspaceManager.load_external([("ext_2", str(missing))])
    wm = WorkspaceManager()
    with pytest.raises(FileNotFoundError):
        wm.get_workspace_path("ext_2")
    WorkspaceManager._external_paths.clear()


@pytest.mark.asyncio
async def test_restore_external_from_db(session):
    from app.coding.workspace import WorkspaceManager, restore_external_workspaces
    from app.models import RegisteredWorkspace
    WorkspaceManager._external_paths.clear()
    session.add(RegisteredWorkspace(ws_id="r_1", abs_path="/some/p", user_id=1, tenant_id=1, display_name="p"))
    await session.commit()
    await restore_external_workspaces(session)
    assert WorkspaceManager._external_paths.get("r_1") == "/some/p"
    WorkspaceManager._external_paths.clear()
