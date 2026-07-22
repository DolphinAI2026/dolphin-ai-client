"""Tenant public UUID authentication projections."""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import app.database as database
from app.auth import (
    create_access_token,
    create_mcp_service_token,
    create_selection_token,
    decode_token,
    get_password_hash,
)
from app.database import Base, get_db
from app.deps import (
    get_auth_context,
    get_auth_context_from_token,
    get_platform_auth_context,
    require_platform_admin,
    require_tenant_admin,
)
from app.models import User
from app.models.tenant import Tenant, UserTenant
from app.routes.auth import router as auth_router
from app.routes.auth.login import _issue_login_response_for_user, _local_login_response
from app.routes.applications.section_content import _serve_custom_page_asset
from app.schemas import UserLogin
from app.tenant_public_id import historical_tenant_public_id

login_routes = importlib.import_module("app.routes.auth.login")


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
    account_source: str = "apaas",
    apaas_base_url: str | None = None,
):
    async with auth_db_factory() as session:
        user = User(
            username="tenant-user",
            hashed_password=get_password_hash("secret"),
            is_active=True,
            is_platform_admin=is_platform_admin,
            account_source=account_source,
            apaas_base_url=apaas_base_url,
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


async def disable_membership(session: AsyncSession, user_id: int, tenant_id: int) -> None:
    membership = (
        await session.execute(
            select(UserTenant).where(
                UserTenant.user_id == user_id,
                UserTenant.tenant_id == tenant_id,
            )
        )
    ).scalar_one()
    membership.status = 0
    await session.commit()


async def remove_membership(session: AsyncSession, user_id: int, tenant_id: int) -> None:
    membership = (
        await session.execute(
            select(UserTenant).where(
                UserTenant.user_id == user_id,
                UserTenant.tenant_id == tenant_id,
            )
        )
    ).scalar_one()
    await session.delete(membership)
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
async def test_me_durably_backfills_legacy_null_tenant_public_id(client, auth_db_factory):
    user, tenants = await seed_tenant_user(auth_db_factory)
    tenant = tenants[0]
    token = create_access_token(user, tenant_id=tenant.id)

    async with auth_db_factory() as session:
        persisted = await session.get(Tenant, tenant.id)
        persisted.public_id = None
        await session.commit()

    response = await client.get("/api/auth/me", headers=bearer(token))

    assert response.status_code == 200
    projected_public_id = response.json()["tenant_public_id"]
    async with auth_db_factory() as session:
        persisted = await session.get(Tenant, tenant.id)

    assert projected_public_id == historical_tenant_public_id(tenant.id)
    assert persisted.public_id == projected_public_id


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
async def test_me_tenants_durably_backfills_legacy_null_tenant_public_id(
    client,
    auth_db_factory,
):
    user, tenants = await seed_tenant_user(auth_db_factory)
    tenant = tenants[0]
    token = create_access_token(user, tenant_id=tenant.id)

    async with auth_db_factory() as session:
        persisted = await session.get(Tenant, tenant.id)
        persisted.public_id = None
        await session.commit()

    response = await client.get("/api/auth/me/tenants", headers=bearer(token))

    assert response.status_code == 200
    assert response.json()[0]["tenant_public_id"] == historical_tenant_public_id(
        tenant.id
    )
    async with auth_db_factory() as session:
        persisted = await session.get(Tenant, tenant.id)

    assert persisted.public_id == response.json()[0]["tenant_public_id"]


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
async def test_switch_tenant_rejects_disabled_tenant_without_signing(
    client,
    auth_db_factory,
    monkeypatch,
):
    user, tenants = await seed_tenant_user(auth_db_factory, tenant_count=2)
    token = create_access_token(user, tenant_id=tenants[0].id)
    async with auth_db_factory() as session:
        await disable_tenant(session, tenants[1].id)
    token_signer = Mock(wraps=login_routes.create_access_token)
    monkeypatch.setattr(login_routes, "create_access_token", token_signer)

    response = await client.post(
        "/api/auth/switch-tenant",
        headers=bearer(token),
        json={"tenant_id": tenants[1].id},
    )

    assert response.status_code == 403
    token_signer.assert_not_called()


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
async def test_multi_tenant_login_excludes_inactive_tenant(auth_db_factory):
    user, tenants = await seed_tenant_user(auth_db_factory, tenant_count=3)
    async with auth_db_factory() as session:
        await disable_tenant(session, tenants[2].id)
        persisted_user = await session.get(User, user.id)
        response = await _issue_login_response_for_user(session, persisted_user)

    assert response.requires_tenant_selection is True
    assert [option.tenant_id for option in response.tenants] == [
        tenants[0].id,
        tenants[1].id,
    ]


@pytest.mark.asyncio
async def test_single_active_tenant_login_never_signs_inactive_membership(
    auth_db_factory,
):
    user, tenants = await seed_tenant_user(auth_db_factory, tenant_count=2)
    async with auth_db_factory() as session:
        await disable_tenant(session, tenants[1].id)
        persisted_user = await session.get(User, user.id)
        response = await _issue_login_response_for_user(session, persisted_user)

    payload = decode_token(response.access_token)
    assert response.requires_tenant_selection is False
    assert payload["tid"] == tenants[0].id


@pytest.mark.asyncio
async def test_login_rejects_active_membership_for_only_inactive_tenant(
    auth_db_factory,
):
    user, tenants = await seed_tenant_user(auth_db_factory)
    async with auth_db_factory() as session:
        await disable_tenant(session, tenants[0].id)
        persisted_user = await session.get(User, user.id)
        with pytest.raises(HTTPException) as exc:
            await _issue_login_response_for_user(session, persisted_user)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_select_tenant_rejects_active_membership_for_inactive_tenant(
    client,
    auth_db_factory,
):
    user, tenants = await seed_tenant_user(auth_db_factory)
    async with auth_db_factory() as session:
        await disable_tenant(session, tenants[0].id)

    response = await client.post(
        "/api/auth/select-tenant",
        json={
            "selection_token": create_selection_token(user.id),
            "tenant_id": tenants[0].id,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "目标租户不可用"


@pytest.mark.asyncio
async def test_multi_tenant_login_durably_backfills_legacy_null_tenant_public_ids(
    auth_db_factory,
):
    user, tenants = await seed_tenant_user(auth_db_factory, tenant_count=2)

    async with auth_db_factory() as session:
        persisted_tenants = (
            await session.execute(
                select(Tenant).where(Tenant.id.in_([tenant.id for tenant in tenants]))
            )
        ).scalars().all()
        for tenant in persisted_tenants:
            tenant.public_id = None
        await session.commit()

    async with auth_db_factory() as session:
        response = await _local_login_response(
            UserLogin(username=user.username, password="secret"),
            session,
        )

    assert [option.tenant_public_id for option in response.tenants] == [
        historical_tenant_public_id(tenant.id) for tenant in tenants
    ]
    async with auth_db_factory() as session:
        persisted_tenants = (
            await session.execute(
                select(Tenant)
                .where(Tenant.id.in_([tenant.id for tenant in tenants]))
                .order_by(Tenant.id)
            )
        ).scalars().all()

    assert [tenant.public_id for tenant in persisted_tenants] == [
        historical_tenant_public_id(tenant.id) for tenant in tenants
    ]


@pytest.mark.asyncio
async def test_control_plane_legacy_projection_rolls_back_pending_sync_on_response_failure(
    auth_db_factory,
    monkeypatch,
):
    user, tenants = await seed_tenant_user(auth_db_factory, tenant_count=2)
    legacy_tenant = tenants[0]
    original_display_name = user.display_name

    async with auth_db_factory() as session:
        persisted = await session.get(Tenant, legacy_tenant.id)
        persisted.public_id = None
        await session.commit()

    async def fake_control_plane_login(*_args):
        return SimpleNamespace(username=user.username)

    async def fake_ensure_control_plane_user(db, _identity):
        persisted_user = await db.get(User, user.id)
        persisted_user.display_name = "pending control plane sync"
        persisted_user.coding_access_token = "pending-control-plane-token"
        return persisted_user

    def fail_response_encoding(*_args):
        raise RuntimeError("response encoding failed")

    monkeypatch.setattr(login_routes.settings, "control_plane_binding_enabled", False)
    monkeypatch.setattr(
        login_routes,
        "login_to_control_plane",
        fake_control_plane_login,
    )
    monkeypatch.setattr(
        login_routes,
        "_ensure_control_plane_user",
        fake_ensure_control_plane_user,
    )
    monkeypatch.setattr(
        login_routes,
        "create_selection_token",
        fail_response_encoding,
    )

    async with auth_db_factory() as session:
        with pytest.raises(RuntimeError, match="response encoding failed"):
            await login_routes._control_plane_login_response(
                UserLogin(
                    username=user.username,
                    password="secret",
                    captcha_id="captcha",
                    captcha_code="code",
                ),
                session,
            )
        await session.rollback()

    async with auth_db_factory() as session:
        persisted_user = await session.get(User, user.id)
        persisted_tenant = await session.get(Tenant, legacy_tenant.id)

    assert persisted_user.display_name == original_display_name
    assert persisted_user.coding_access_token is None
    assert persisted_tenant.public_id is None


@pytest.mark.asyncio
async def test_control_plane_legacy_projection_commits_once_at_outer_boundary(
    auth_db_factory,
    monkeypatch,
):
    user, tenants = await seed_tenant_user(auth_db_factory, tenant_count=2)
    legacy_tenant = tenants[0]

    async with auth_db_factory() as session:
        persisted = await session.get(Tenant, legacy_tenant.id)
        persisted.public_id = None
        await session.commit()

    async def fake_control_plane_login(*_args):
        return SimpleNamespace(username=user.username)

    async def fake_ensure_control_plane_user(db, _identity):
        persisted_user = await db.get(User, user.id)
        persisted_user.display_name = "committed control plane sync"
        persisted_user.coding_access_token = "committed-control-plane-token"
        return persisted_user

    monkeypatch.setattr(login_routes.settings, "control_plane_binding_enabled", False)
    monkeypatch.setattr(
        login_routes,
        "login_to_control_plane",
        fake_control_plane_login,
    )
    monkeypatch.setattr(
        login_routes,
        "_ensure_control_plane_user",
        fake_ensure_control_plane_user,
    )

    async with auth_db_factory() as session:
        commits = []

        def track_commit(*_args):
            commits.append(True)

        event.listen(session.sync_session, "after_commit", track_commit)
        try:
            response = await login_routes._control_plane_login_response(
                UserLogin(
                    username=user.username,
                    password="secret",
                    captcha_id="captcha",
                    captcha_code="code",
                ),
                session,
            )
        finally:
            event.remove(session.sync_session, "after_commit", track_commit)

    assert response.requires_tenant_selection is True
    assert commits == [True]
    async with auth_db_factory() as session:
        persisted_user = await session.get(User, user.id)
        persisted_tenant = await session.get(Tenant, legacy_tenant.id)

    assert persisted_user.display_name == "committed control plane sync"
    assert persisted_user.coding_access_token == "committed-control-plane-token"
    assert persisted_tenant.public_id == historical_tenant_public_id(legacy_tenant.id)


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


@pytest.mark.asyncio
async def test_query_token_rejects_disabled_membership(auth_db_factory):
    user, tenants = await seed_tenant_user(auth_db_factory)
    tenant = tenants[0]
    token = create_access_token(user, tenant_id=tenant.id)

    async with auth_db_factory() as session:
        await disable_membership(session, user.id, tenant.id)

    with pytest.raises(ValueError, match="Tenant membership is inactive"):
        await get_auth_context_from_token(token)


@pytest.mark.asyncio
async def test_query_token_rejects_disabled_user(auth_db_factory):
    user, tenants = await seed_tenant_user(auth_db_factory)
    token = create_access_token(user, tenant_id=tenants[0].id)

    async with auth_db_factory() as session:
        persisted_user = await session.get(User, user.id)
        persisted_user.is_active = False
        await session.commit()

    with pytest.raises(ValueError, match="User is disabled"):
        await get_auth_context_from_token(token)


@pytest.mark.asyncio
async def test_query_token_rejects_missing_user(auth_db_factory):
    token = create_access_token(999_999, tenant_id=1)

    with pytest.raises(ValueError, match="User not found"):
        await get_auth_context_from_token(token)


@pytest.mark.parametrize(
    ("account_source", "apaas_base_url"),
    [
        ("apaas", "https://apaas.example"),
        ("coding", None),
        ("control_plane", None),
    ],
)
@pytest.mark.asyncio
async def test_header_token_rejects_revoked_external_platform_admin_membership(
    auth_db_factory,
    account_source,
    apaas_base_url,
):
    user, tenants = await seed_tenant_user(
        auth_db_factory,
        is_platform_admin=True,
        account_source=account_source,
        apaas_base_url=apaas_base_url,
    )
    tenant = tenants[0]
    token = create_access_token(user, tenant_id=tenant.id)

    async with auth_db_factory() as session:
        await remove_membership(session, user.id, tenant.id)
        with pytest.raises(HTTPException) as exc:
            await get_auth_context(credentials_for(token), session)

    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    ("account_source", "apaas_base_url"),
    [
        ("apaas", "https://apaas.example"),
        ("coding", None),
        ("control_plane", None),
    ],
)
@pytest.mark.asyncio
async def test_query_token_rejects_revoked_external_platform_admin_membership(
    auth_db_factory,
    account_source,
    apaas_base_url,
):
    user, tenants = await seed_tenant_user(
        auth_db_factory,
        is_platform_admin=True,
        account_source=account_source,
        apaas_base_url=apaas_base_url,
    )
    tenant = tenants[0]
    token = create_access_token(user, tenant_id=tenant.id)

    async with auth_db_factory() as session:
        await remove_membership(session, user.id, tenant.id)

    with pytest.raises(ValueError, match="Tenant membership is inactive"):
        await get_auth_context_from_token(token)


@pytest.mark.parametrize(
    ("account_source", "apaas_base_url"),
    [
        ("apaas", "https://apaas.example"),
        ("coding", None),
        ("control_plane", None),
    ],
)
@pytest.mark.asyncio
async def test_external_platform_admin_active_membership_keeps_wildcard_permissions(
    auth_db_factory,
    account_source,
    apaas_base_url,
):
    user, tenants = await seed_tenant_user(
        auth_db_factory,
        is_platform_admin=True,
        account_source=account_source,
        apaas_base_url=apaas_base_url,
    )
    tenant = tenants[0]
    token = create_access_token(user, tenant_id=tenant.id)

    async with auth_db_factory() as session:
        header_ctx = await get_auth_context(credentials_for(token), session)
    query_ctx = await get_auth_context_from_token(token)

    for ctx in (header_ctx, query_ctx):
        assert ctx.tenant_id == tenant.id
        assert ctx.tenant_role == "platform_admin"
        assert ctx.org_permissions == {"*": True}


@pytest.mark.parametrize(
    ("account_source", "apaas_base_url"),
    [
        ("apaas", "https://apaas.example"),
        ("coding", None),
        ("control_plane", None),
    ],
)
@pytest.mark.asyncio
async def test_external_platform_admin_without_tid_is_platform_only_after_membership_removal(
    auth_db_factory,
    account_source,
    apaas_base_url,
):
    user, tenants = await seed_tenant_user(
        auth_db_factory,
        is_platform_admin=True,
        account_source=account_source,
        apaas_base_url=apaas_base_url,
    )
    token = create_access_token(user, tenant_id=None)

    async with auth_db_factory() as session:
        await remove_membership(session, user.id, tenants[0].id)
        with pytest.raises(HTTPException, match="需要租户上下文"):
            await get_auth_context(credentials_for(token), session)
        platform_ctx = await get_platform_auth_context(credentials_for(token), session)

    with pytest.raises(ValueError, match="Tenant context required"):
        await get_auth_context_from_token(token)

    assert platform_ctx.tenant_id == 0
    assert platform_ctx.tenant_role == "platform_admin"
    assert platform_ctx.org_permissions == {"*": True}
    assert platform_ctx.tenant_access_scope == "platform_only"
    assert await require_platform_admin(platform_ctx) is platform_ctx


@pytest.mark.parametrize(
    ("account_source", "apaas_base_url"),
    [
        ("apaas", "https://apaas.example"),
        ("coding", None),
        ("control_plane", None),
    ],
)
@pytest.mark.asyncio
async def test_external_platform_only_admin_route_matrix_is_fail_closed(
    auth_db_factory,
    client,
    account_source,
    apaas_base_url,
):
    user, tenants = await seed_tenant_user(
        auth_db_factory,
        is_platform_admin=True,
        account_source=account_source,
        apaas_base_url=apaas_base_url,
    )
    token = create_access_token(user, tenant_id=None)
    async with auth_db_factory() as session:
        await remove_membership(session, user.id, tenants[0].id)

    users_response = await client.get("/api/auth/users", headers=bearer(token))
    me_response = await client.get("/api/auth/me", headers=bearer(token))
    tenants_response = await client.get("/api/auth/me/tenants", headers=bearer(token))
    platform_tenants_response = await client.get("/api/auth/tenants", headers=bearer(token))
    tenant_members_response = await client.get(
        f"/api/auth/tenants/{tenants[0].id}/members",
        headers=bearer(token),
    )

    assert users_response.status_code == 403
    assert users_response.json()["detail"] == "需要租户上下文"
    assert me_response.status_code == 200
    assert me_response.json()["tenant_id"] is None
    assert tenants_response.status_code == 200
    assert tenants_response.json() == []
    assert platform_tenants_response.status_code == 200
    assert [item["id"] for item in platform_tenants_response.json()] == [tenants[0].id]
    assert tenant_members_response.status_code == 200
    assert tenant_members_response.json() == []


@pytest.mark.asyncio
async def test_custom_page_query_token_rejects_removed_membership(auth_db_factory):
    user, tenants = await seed_tenant_user(auth_db_factory)
    tenant = tenants[0]
    token = create_access_token(user, tenant_id=tenant.id)

    async with auth_db_factory() as session:
        await remove_membership(session, user.id, tenant.id)
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/applications/1/custom-page-assets-auth/token/bundle/app.js",
                "headers": [],
                "query_string": b"",
            }
        )
        with pytest.raises(HTTPException) as exc:
            await _serve_custom_page_asset(
                app_id=1,
                bundle_dir="bundle",
                asset_path="app.js",
                request=request,
                db=session,
                token=token,
            )

    assert exc.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("account_source", ["apaas", "desktop"])
async def test_local_platform_admin_keeps_unscoped_header_and_query_access(
    auth_db_factory,
    account_source,
):
    user, tenants = await seed_tenant_user(
        auth_db_factory,
        is_platform_admin=True,
        account_source=account_source,
    )
    tenant = tenants[0]
    token = create_access_token(user, tenant_id=tenant.id)

    async with auth_db_factory() as session:
        await remove_membership(session, user.id, tenant.id)
        header_ctx = await get_auth_context(credentials_for(token), session)

    query_ctx = await get_auth_context_from_token(token)

    for ctx in (header_ctx, query_ctx):
        assert ctx.tenant_id == tenant.id
        assert ctx.tenant_role == "platform_admin"
        assert ctx.org_permissions == {"*": True}


@pytest.mark.asyncio
async def test_query_token_keeps_mcp_service_special_branch(auth_db_factory):
    user, tenants = await seed_tenant_user(auth_db_factory)
    tenant = tenants[0]
    token = create_mcp_service_token(user.id, tenant.id)

    async with auth_db_factory() as session:
        await remove_membership(session, user.id, tenant.id)
        header_ctx = await get_auth_context(credentials_for(token), session)

    query_ctx = await get_auth_context_from_token(token)

    for ctx in (header_ctx, query_ctx):
        assert ctx.tenant_id == tenant.id
        assert ctx.tenant_role == "platform_admin"
        assert ctx.org_permissions == {"*": True}
