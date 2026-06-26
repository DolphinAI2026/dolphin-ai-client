# backend/tests/test_knowledge_tools.py
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


async def _seed(db):
    from app.models.knowledge_doc import KnowledgeDoc
    db.add_all([
        KnowledgeDoc(slug="sdk", title="事件 SDK", summary="写侧", category="二次开发",
                     body_md="afterFormData", status="published"),
        KnowledgeDoc(slug="draft1", title="草稿", summary="x", category="搭建",
                     body_md="y", status="draft"),
    ])
    await db.commit()


@pytest.mark.asyncio
async def test_read_knowledge_states(db):
    from app.ai_chat.tools import execute_read_knowledge
    await _seed(db)
    ok = await execute_read_knowledge({"slug": "sdk"}, None, db)
    assert "afterFormData" in ok and "事件 SDK" in ok
    assert "不存在" in await execute_read_knowledge({"slug": "draft1"}, None, db)  # draft 不可读
    assert "不存在" in await execute_read_knowledge({"slug": "zzz"}, None, db)
    assert "缺少" in await execute_read_knowledge({}, None, db)


@pytest.mark.asyncio
async def test_search_knowledge_hit_and_miss(db):
    from app.ai_chat.tools import execute_search_knowledge
    await _seed(db)
    hit = await execute_search_knowledge({"query": "写侧"}, None, db)
    assert "sdk" in hit
    assert "未检索到" in await execute_search_knowledge({"query": "完全不相关XYZ"}, None, db)


def test_knowledge_tools_registered_as_core():
    from app.ai_chat.tools import TOOL_HANDLERS, _BASE_LOCAL_NAMES, CORE_TOOL_NAMES
    for name in ("read_knowledge", "search_knowledge"):
        assert name in TOOL_HANDLERS
        assert name in _BASE_LOCAL_NAMES   # 自动随 TOOL_SCHEMAS
        assert name in CORE_TOOL_NAMES     # 恒在,不被延迟
