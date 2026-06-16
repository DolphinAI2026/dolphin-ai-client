"""桌面产品登录路由 — authority 模式集成测试。

用 StaticPool 内存库 + monkeypatch app.database.AsyncSessionLocal 保证
provision_desktop_account 写的行和路由 get_db 看到的是同一个库。
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

import app.database as database
from app.database import Base
from app import desktop_accounts as da


@pytest_asyncio.fixture
async def client(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # patch AsyncSessionLocal so any module that imports it (get_db, etc.) uses the in-memory DB
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)

    async with Session() as s:
        await da.provision_desktop_account(s, "dave", "pw123456")
        await s.commit()

    from app.main import app
    from app.database import get_db

    async def _get_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_desktop_login_success(client):
    r = await client.post("/api/desktop-auth/login", json={"username": "dave", "password": "pw123456"})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["token_type"] == "bearer"
    assert body["username"] == "dave"


@pytest.mark.asyncio
async def test_desktop_login_wrong_password(client):
    r = await client.post("/api/desktop-auth/login", json={"username": "dave", "password": "nope"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_desktop_login_unknown_user(client):
    r = await client.post("/api/desktop-auth/login", json={"username": "ghost", "password": "pw123456"})
    assert r.status_code == 401
