import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AIChatArtifact


@pytest.mark.asyncio
async def test_artifact_has_binary_fields():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        art = AIChatArtifact(session_id=1, filename="a.pptx", format="pptx",
                             storage="file", file_path="/ws/a.pptx", size_bytes=123)
        db.add(art)
        await db.commit()
        row = (await db.execute(select(AIChatArtifact).where(AIChatArtifact.filename == "a.pptx"))).scalar_one()
        assert row.storage == "file"
        assert row.file_path == "/ws/a.pptx"
        assert row.size_bytes == 123


@pytest.mark.asyncio
async def test_artifact_storage_defaults_text():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        art = AIChatArtifact(session_id=1, filename="d.md", content="x")
        db.add(art)
        await db.commit()
        row = (await db.execute(select(AIChatArtifact).where(AIChatArtifact.filename == "d.md"))).scalar_one()
        assert row.storage == "text"
        assert row.file_path is None
