import pytest
import pytest_asyncio
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

import app.database as database
from app.database import Base


@pytest_asyncio.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    from app.main import app
    from app.database import get_db
    from app.deps import get_auth_context, AuthContext
    async def _get_db():
        async with Session() as s:
            yield s
    async def _ctx():
        from app.models import User
        # AuthContext fields: user, tenant_id, tenant_role, org_permissions, apaas_user_id (opt), apaas_tenant_id (opt)
        # User model has no tenant_id column — tenant_id lives on AuthContext, not User
        return AuthContext(
            user=User(id=1, username="t"),
            tenant_id=1,
            tenant_role="tenant_admin",
            org_permissions={"*": True},
        )
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_auth_context] = _ctx
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_open_local_creates_and_dedups(client, tmp_path, monkeypatch):
    # tmp_path on macOS resolves under /private/var (blocked by sensitive-root check);
    # patch _is_sensitive_dir so this test focuses on the DB create+dedup logic.
    import app.routes.coding as coding_mod
    monkeypatch.setattr(coding_mod, "_is_sensitive_dir", lambda p: False)
    r1 = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(tmp_path)})
    assert r1.status_code == 200
    ws_id = r1.json()["ws_id"]
    r2 = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(tmp_path)})
    assert r2.status_code == 200 and r2.json()["ws_id"] == ws_id


@pytest.mark.asyncio
async def test_open_local_rejects_sensitive(client):
    r = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(Path.home())})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_open_local_rejects_missing(client, tmp_path):
    r = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(tmp_path / "nope")})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_open_local_rejects_symlinked_system_dir(client):
    # /etc resolves to /private/etc on macOS — must still be blocked via ancestry check
    r = await client.post("/api/coding/workspace/open-local", json={"abs_path": "/etc"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_open_local_rejects_users_root(client):
    r = await client.post("/api/coding/workspace/open-local", json={"abs_path": "/Users"})
    assert r.status_code == 400
