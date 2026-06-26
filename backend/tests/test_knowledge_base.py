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
        KnowledgeDoc(slug="d", title="无关标题", summary="规范描述",
                     category="搭建", body_md="这里讲字段命名细则", status="published"),
        KnowledgeDoc(slug="e", title="字段草稿", summary="字段",
                     category="搭建", body_md="字段相关内容", status="draft"),
    ])
    await db.commit()


@pytest.mark.asyncio
async def test_list_published_excludes_draft(db):
    from app.knowledge_base import list_published_docs
    await _seed(db)
    slugs = [d.slug for d in await list_published_docs(db)]
    # 按 category 排序:二次开发 < 搭建(unicode),再按 title
    # 搭建内:无关标题(d) < 表单字段规范(a)
    assert slugs == ["b", "d", "a"]
    # 验证 draft 被排除(c 和 e 不在结果中)
    assert "c" not in slugs and "e" not in slugs


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
    # 验证排序:标题命中(a)应排在仅body命中(d)前
    assert len(hits) >= 2, f"Expected at least 2 hits, got {len(hits)}"
    hit_slugs = [h.slug for h in hits]
    assert "a" in hit_slugs, "Doc 'a' (title hit) should be in results"
    assert "d" in hit_slugs, "Doc 'd' (body-only hit) should be in results"
    assert hit_slugs.index("a") < hit_slugs.index("d"), "Title hit 'a' should rank before body-only hit 'd'"
    # 验证草稿被排除
    assert "e" not in hit_slugs, "Draft doc 'e' should be excluded even though it contains '字段'"
    assert all(h.status == "published" for h in hits), "All hits must be published"


@pytest.mark.asyncio
async def test_search_escapes_like_wildcards(db):
    """LIKE pattern % and _ should be escaped, not treated as wildcards."""
    from app.knowledge_base import search_published_docs
    from app.models.knowledge_doc import KnowledgeDoc

    # Positive cases: docs with literal wildcards
    db.add_all([
        KnowledgeDoc(slug="f", title="50% 优惠规则", summary="折扣", category="搭建",
                     body_md="字段规则", status="published"),
        KnowledgeDoc(slug="g", title="字段映射", summary="a_b映射",
                     category="搭建", body_md="下划线分隔符", status="published"),
        # Negative cases: docs that unescaped wildcard would match but literal won't
        KnowledgeDoc(slug="neg1", title="命中50个名额", summary="容量", category="搭建",
                     body_md="限制信息", status="published"),
        KnowledgeDoc(slug="neg2", title="aXb映射示例", summary="转换器", category="搭建",
                     body_md="字符转换", status="published"),
    ])
    await db.commit()

    # 查询包含 % 的文字 — 转义后只匹配字面 %，不作为通配符
    hits = await search_published_docs(db, "50%")
    hit_slugs = [h.slug for h in hits]
    # Positive: literal "50%" should be found
    assert "f" in hit_slugs, "Should find literal '50%' in doc 'f' title"
    # Negative: unescaped "50%" pattern %50%% would match "50个" but escaped %50\%% won't
    assert "neg1" not in hit_slugs, (
        "Doc 'neg1' with '50个' should NOT match query '50%' when % is escaped as \\%; "
        "unescaped would match because %50%% matches any 'X50<any1char>X'"
    )

    # 查询包含 _ 的文字 — 转义后只匹配字面 _，不作为通配符
    hits = await search_published_docs(db, "a_b")
    hit_slugs = [h.slug for h in hits]
    # Positive: literal "a_b" should be found
    assert "g" in hit_slugs, "Should find literal 'a_b' in doc 'g' summary"
    # Negative: unescaped "a_b" pattern %a_b% would match "aXb" but escaped %a\_b% won't
    assert "neg2" not in hit_slugs, (
        "Doc 'neg2' with 'aXb' should NOT match query 'a_b' when _ is escaped as \\_; "
        "unescaped would match because %a_b% matches any 'X<any1char>bX'"
    )


def test_build_manifest_groups_and_empty():
    from app.knowledge_base import build_knowledge_manifest
    from app.models.knowledge_doc import KnowledgeDoc
    assert build_knowledge_manifest([]) == ""   # 空集 no-op
    m = build_knowledge_manifest([
        KnowledgeDoc(slug="b", title="T2", summary="S2", category="二次开发", body_md="x", status="published"),
    ])
    assert "## 平台知识库" in m and "[二次开发]" in m and "b: T2 — S2" in m
