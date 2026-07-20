"""Tenant public UUID authentication projections."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.database as database
from app.auth import create_access_token, get_password_hash
from app.database import Base, get_db
from app.deps import get_auth_context, get_auth_context_from_token
from app.models import User
from app.models.tenant import Tenant, UserTenant
from app.routes.auth import router as auth_router
from app.routes.auth.login import _issue_login_response_for_user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def credentials_for(token: str) -> SimpleNamespace:
    return SimpleNamespace(credentials=token)


@pytest_asyncio.fixture
async def auth_db_factory(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    monkeypatch.setattr(database, "AsyncSessionLocal", session_factory)
    yield session_factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client(auth_db_factory):
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")

    async def override_get_db():
        async with auth_db_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


async def seed_tenant_user(
    auth_db_factory,
    *,
    tenant_count: int = 1,
    is_platform_admin: bool = False,
):
    async with auth_db_factory() as session:
        user = User(
            username="tenant-user",
            hashed_password=get_password_hash("secret"),
            is_active=True,
            is_platform_admin=is_platform_admin,
        )
        tenants = [
            Tenant(tenant_name=f"Tenant {index}", tenant_code=f"tenant-{index}", status=1)
            for index in range(tenant_count)
        ]
        session.add_all([user, *tenants])
        await session.flush()
        session.add_all(
            UserTenant(
                user_id=user.id,
                tenant_id=tenant.id,
                status=1,
                is_default=False,
            )
            for tenant in tenants
        )
        await session.commit()
        return user, tenants


async def disable_tenant(session: AsyncSession, tenant_id: int) -> None:
    tenant = await session.get(Tenant, tenant_id)
    tenant.status = 0
    await session.commit()


@pytest.mark.asyncio
async def test_me_returns_current_tenant_public_id(client, auth_db_factory):
    user, tenants = await seed_tenant_user(auth_db_factory)
    tenant = tenants[0]
    tenant_user_token = create_access_token(user, tenant_id=tenant.id)

    response = await client.get("/api/auth/me", headers=bearer(tenant_user_token))

    assert response.status_code == 200
    assert response.json()["tenant_public_id"] == tenant.public_id


@pytest.mark.asyncio
async def test_me_tenants_returns_tenant_public_id(client, auth_db_factory):
    user, tenants = await seed_tenant_user(auth_db_factory)
    tenant_user_token = create_access_token(user, tenant_id=tenants[0].id)

    response = await client.get("/api/auth/me/tenants", headers=bearer(tenant_user_token))

    assert response.status_code == 200
    assert response.json() == [
        {
            "tenant_id": tenants[0].id,
            "tenant_name": tenants[0].tenant_name,
            "tenant_code": tenants[0].tenant_code,
            "tenant_public_id": tenants[0].public_id,
        }
    ]


@pytest.mark.asyncio
async def test_switch_tenant_response_remains_token_only(client, auth_db_factory):
    user, tenants = await seed_tenant_user(auth_db_factory, tenant_count=2)
    token = create_access_token(user, tenant_id=tenants[0].id)

    response = await client.post(
        "/api/auth/switch-tenant",
        headers=bearer(token),
        json={"tenant_id": tenants[1].id},
    )

    assert response.status_code == 200
    assert set(response.json()) == {"access_token", "token_type"}


@pytest.mark.asyncio
async def test_multi_tenant_login_projects_tenant_public_ids(auth_db_factory):
    user, tenants = await seed_tenant_user(auth_db_factory, tenant_count=2)

    async with auth_db_factory() as session:
        persisted_user = await session.get(User, user.id)
        response = await _issue_login_response_for_user(session, persisted_user)

    assert response.requires_tenant_selection is True
    assert [option.tenant_public_id for option in response.tenants] == [
        tenant.public_id for tenant in tenants
    ]


@pytest.mark.asyncio
async def test_header_auth_rejects_inactive_tenant_token(auth_db_factory):
    user, tenants = await seed_tenant_user(auth_db_factory, is_platform_admin=True)
    tenant = tenants[0]
    token = create_access_token(user, tenant_id=tenant.id)

    async with auth_db_factory() as session:
        await disable_tenant(session, tenant.id)
        with pytest.raises(HTTPException) as exc:
            await get_auth_context(credentials_for(token), session)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_query_token_auth_rejects_inactive_tenant_token(auth_db_factory):
    user, tenants = await seed_tenant_user(auth_db_factory)
    tenant = tenants[0]
    token = create_access_token(user, tenant_id=tenant.id)

    async with auth_db_factory() as session:
        await disable_tenant(session, tenant.id)

    with pytest.raises(ValueError, match="Tenant is inactive"):
        await get_auth_context_from_token(token)
