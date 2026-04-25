import os
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Force in-memory sqlite before any app import touches database.py
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from app.database import Base  # noqa: E402
from app import models  # noqa: F401, E402  — register all ORM mappings


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()
