import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

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
async def test_unique_tenant_path(session):
    from sqlalchemy.exc import IntegrityError
    session.add(RegisteredWorkspace(ws_id="1_a", abs_path="/p", user_id=1, tenant_id=1, display_name="p"))
    await session.commit()
    session.add(RegisteredWorkspace(ws_id="1_b", abs_path="/p", user_id=1, tenant_id=1, display_name="p"))
    with pytest.raises(IntegrityError):
        await session.commit()
