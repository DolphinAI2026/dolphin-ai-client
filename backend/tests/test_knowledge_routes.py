# backend/tests/test_knowledge_routes.py
import pytest, pytest_asyncio
from types import SimpleNamespace
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.deps import require_platform_admin
import app.models  # noqa: F401


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_db():
        async with Session() as s:
            yield s

    from app.routes import knowledge
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api")
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_platform_admin] = lambda: SimpleNamespace(user=SimpleNamespace(id=1))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_crud_flow(client):
    r = await client.post("/api/knowledge/docs", json={
        "slug": "sdk", "title": "事件 SDK", "summary": "写侧", "category": "二次开发",
        "body_md": "afterFormData", "status": "published"})
    assert r.status_code == 200, r.text
    assert (await client.get("/api/knowledge/docs")).json()["docs"][0]["slug"] == "sdk"
    assert (await client.get("/api/knowledge/docs/sdk")).json()["body_md"] == "afterFormData"
    r = await client.put("/api/knowledge/docs/sdk", json={
        "slug": "sdk", "title": "事件 SDK v2", "summary": "写侧", "category": "二次开发",
        "body_md": "updated", "status": "published"})
    assert r.json()["title"] == "事件 SDK v2"
    assert (await client.delete("/api/knowledge/docs/sdk")).json()["ok"] is True
    assert (await client.get("/api/knowledge/docs/sdk")).status_code == 404


@pytest.mark.asyncio
async def test_duplicate_slug_409(client):
    body = {"slug": "x", "title": "T", "summary": "", "category": "搭建", "body_md": "b", "status": "draft"}
    assert (await client.post("/api/knowledge/docs", json=body)).status_code == 200
    assert (await client.post("/api/knowledge/docs", json=body)).status_code == 409


@pytest.mark.asyncio
async def test_non_admin_403():
    # 不覆盖 require_platform_admin → 真实依赖,无 token → 401/403
    from app.routes import knowledge
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/knowledge/docs")).status_code in (401, 403)
