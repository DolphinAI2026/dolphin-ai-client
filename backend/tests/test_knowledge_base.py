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
        KnowledgeDoc(slug="a", title="表单字段规范", summary="字段口径", category="搭建",
                     body_md="字段命名用蛇形", status="published"),
        KnowledgeDoc(slug="b", title="definesys 事件 SDK", summary="写侧 API",
                     category="二次开发", body_md="afterFormData 用法", status="published"),
        KnowledgeDoc(slug="c", title="草稿", summary="未发布", category="搭建",
                     body_md="draft body", status="draft"),
    ])
    await db.commit()


@pytest.mark.asyncio
async def test_list_published_excludes_draft(db):
    from app.knowledge_base import list_published_docs
    await _seed(db)
    slugs = [d.slug for d in await list_published_docs(db)]
    assert slugs == ["b", "a"]  # 按 category 排序:二次开发 < 搭建(unicode),再按 title


@pytest.mark.asyncio
async def test_get_published_doc(db):
    from app.knowledge_base import get_published_doc
    await _seed(db)
    assert (await get_published_doc(db, "b")).title == "definesys 事件 SDK"
    assert await get_published_doc(db, "c") is None      # draft 不可读
    assert await get_published_doc(db, "zzz") is None     # 不存在


@pytest.mark.asyncio
async def test_search_ranks_title_over_body(db):
    from app.knowledge_base import search_published_docs
    await _seed(db)
    hits = await search_published_docs(db, "字段")
    assert hits[0].slug == "a"        # 标题命中权重最高
    assert all(h.status == "published" for h in hits)


def test_build_manifest_groups_and_empty():
    from app.knowledge_base import build_knowledge_manifest
    from app.models.knowledge_doc import KnowledgeDoc
    assert build_knowledge_manifest([]) == ""   # 空集 no-op
    m = build_knowledge_manifest([
        KnowledgeDoc(slug="b", title="T2", summary="S2", category="二次开发", body_md="x", status="published"),
    ])
    assert "## 平台知识库" in m and "[二次开发]" in m and "b: T2 — S2" in m
