# backend/tests/test_knowledge_manifest_inject.py
import pytest, pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
import app.models  # noqa: F401


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_manifest_appended_to_system(db):
    from app.ai_chat.agent import _append_knowledge_manifest
    from app.models.knowledge_doc import KnowledgeDoc
    db.add(KnowledgeDoc(slug="sdk", title="事件 SDK", summary="写侧", category="二次开发",
                        body_md="x", status="published"))
    await db.commit()
    msgs = [{"role": "system", "content": "BASE"}]
    await _append_knowledge_manifest(msgs, db)
    assert msgs[0]["content"].startswith("BASE")
    assert "平台知识库" in msgs[0]["content"] and "sdk: 事件 SDK" in msgs[0]["content"]


@pytest.mark.asyncio
async def test_manifest_empty_is_noop(db):
    from app.ai_chat.agent import _append_knowledge_manifest
    msgs = [{"role": "system", "content": "BASE"}]
    await _append_knowledge_manifest(msgs, db)   # 空库
    assert msgs[0]["content"] == "BASE"


@pytest.mark.asyncio
async def test_manifest_skips_non_system_head(db):
    from app.ai_chat.agent import _append_knowledge_manifest
    from app.models.knowledge_doc import KnowledgeDoc
    db.add(KnowledgeDoc(slug="s", title="T", summary="S", category="搭建", body_md="x", status="published"))
    await db.commit()
    msgs = [{"role": "user", "content": "hi"}]
    await _append_knowledge_manifest(msgs, db)   # 头不是 system → 不动
    assert msgs[0]["content"] == "hi"
