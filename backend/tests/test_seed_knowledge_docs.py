"""TDD tests for knowledge_seed.py — idempotency + status checks."""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401 — register all ORM mappings (including KnowledgeDoc)


@pytest_asyncio.fixture
async def session_maker():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_seed_is_idempotent(session_maker):
    """Running upsert_seed_docs twice must not create duplicate slugs."""
    from app.knowledge_seed import upsert_seed_docs
    from app.models.knowledge_doc import KnowledgeDoc

    async with session_maker() as db:
        count_first = await upsert_seed_docs(db)

    async with session_maker() as db:
        count_second = await upsert_seed_docs(db)

    async with session_maker() as db:
        rows = (await db.execute(select(KnowledgeDoc))).scalars().all()
        slugs = [r.slug for r in rows]

    assert len(slugs) == len(set(slugs)), "Duplicate slugs found after double upsert"
    assert len(slugs) >= 1, "No docs seeded"
    assert count_first == count_second, "Count should be same on both runs"


@pytest.mark.asyncio
async def test_published_items_have_correct_status(session_maker):
    """Canonical published items must be status='published'."""
    from app.knowledge_seed import upsert_seed_docs, SEED
    from app.models.knowledge_doc import KnowledgeDoc

    async with session_maker() as db:
        await upsert_seed_docs(db)

    async with session_maker() as db:
        rows = (await db.execute(select(KnowledgeDoc))).scalars().all()
        by_slug = {r.slug: r for r in rows}

    published_slugs = [item["slug"] for item in SEED if item["status"] == "published"]
    assert len(published_slugs) >= 5, "Expected at least 5 published seed docs"

    for slug in published_slugs:
        assert slug in by_slug, f"Slug {slug!r} not found in DB"
        assert by_slug[slug].status == "published", (
            f"{slug!r} should be status='published', got {by_slug[slug].status!r}"
        )


@pytest.mark.asyncio
async def test_definesys_write_sdk_is_draft(session_maker):
    """The definesys write-SDK placeholder must be status='draft'."""
    from app.knowledge_seed import upsert_seed_docs
    from app.models.knowledge_doc import KnowledgeDoc

    async with session_maker() as db:
        await upsert_seed_docs(db)

    async with session_maker() as db:
        row = (
            await db.execute(
                select(KnowledgeDoc).where(
                    KnowledgeDoc.slug == "apaas-event-python-write-sdk"
                )
            )
        ).scalar_one_or_none()

    assert row is not None, "Draft placeholder doc not found"
    assert row.status == "draft", f"Expected 'draft', got {row.status!r}"


@pytest.mark.asyncio
async def test_seed_count_matches_seed_list(session_maker):
    """Total docs in DB after seeding equals len(SEED)."""
    from app.knowledge_seed import upsert_seed_docs, SEED
    from app.models.knowledge_doc import KnowledgeDoc

    async with session_maker() as db:
        await upsert_seed_docs(db)

    async with session_maker() as db:
        rows = (await db.execute(select(KnowledgeDoc))).scalars().all()

    assert len(rows) == len(SEED), (
        f"Expected {len(SEED)} docs, found {len(rows)}"
    )


def test_seed_slugs_are_route_safe():
    """seed slug 不能含 '/' — CRUD 路由用 /docs/{slug} 普通转换器, 斜杠会 404,
    管理页就改/删/看不了默认文档(上线后唯一内容)。"""
    from app.knowledge_seed import SEED

    bad = [d["slug"] for d in SEED if "/" in d["slug"]]
    assert not bad, f"含斜杠的 slug 会让管理页 /docs/{{slug}} 路由 404: {bad}"
