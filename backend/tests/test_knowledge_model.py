import pytest, pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select
from app.database import Base
import app.models  # noqa: F401 — 注册全部 ORM 映射


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_knowledge_doc_roundtrip(db):
    from app.models.knowledge_doc import KnowledgeDoc
    d = KnowledgeDoc(slug="definesys-event-sdk", title="definesys 事件 SDK",
                     summary="写侧 SDK 规范", category="二次开发", body_md="# 正文", status="published")
    db.add(d); await db.commit()
    got = (await db.execute(select(KnowledgeDoc).where(KnowledgeDoc.slug == "definesys-event-sdk"))).scalar_one()
    assert got.title == "definesys 事件 SDK"
    assert got.tenant_id is None
    assert got.status == "published"
