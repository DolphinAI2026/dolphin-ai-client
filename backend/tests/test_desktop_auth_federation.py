import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

import app.database as database
from app.database import Base


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setattr("app.config.settings.public_account_base_url", "https://public.test")
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
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
async def test_federation_login_mirrors_user_and_signs_local_jwt(client, monkeypatch):
    async def fake_remote(base_url, username, password):
        return {"username": username} if password == "pw123456" else None
    monkeypatch.setattr("app.routes.desktop_auth._remote_authenticate", fake_remote)

    ok = await client.post("/api/desktop-auth/login", json={"username": "frank", "password": "pw123456"})
    assert ok.status_code == 200 and ok.json()["access_token"]

    bad = await client.post("/api/desktop-auth/login", json={"username": "frank", "password": "wrong"})
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_federation_second_login_reuses_mirror(client, monkeypatch):
    """同一联邦用户二次登录复用本地镜像, 不重复建号。"""
    from sqlalchemy import select, func
    from app.models import User
    import app.database as database

    async def fake_remote(base_url, username, password):
        return {"username": username}
    monkeypatch.setattr("app.routes.desktop_auth._remote_authenticate", fake_remote)

    r1 = await client.post("/api/desktop-auth/login", json={"username": "grace", "password": "x"})
    assert r1.status_code == 200
    r2 = await client.post("/api/desktop-auth/login", json={"username": "grace", "password": "x"})
    assert r2.status_code == 200 and r2.json()["username"] == "grace"

    async with database.AsyncSessionLocal() as s:
        n = (await s.execute(select(func.count()).select_from(User).where(User.username == "grace"))).scalar()
    assert n == 1  # 只镜像一份


@pytest.mark.asyncio
async def test_federation_token_has_desktop_issuer(client, monkeypatch):
    """联邦本地签的票 issuer=desktop-sidecar, 不与 authority 共用 ai-builder。"""
    from app.auth import decode_token

    async def fake_remote(base_url, username, password):
        return {"username": username}
    monkeypatch.setattr("app.routes.desktop_auth._remote_authenticate", fake_remote)
    monkeypatch.setattr("app.config.settings.accepted_token_issuers", "ai-builder,desktop-sidecar")

    r = await client.post("/api/desktop-auth/login", json={"username": "iris", "password": "x"})
    assert r.status_code == 200
    payload = decode_token(r.json()["access_token"])
    assert payload["iss"] == "desktop-sidecar"
