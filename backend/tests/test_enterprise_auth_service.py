from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.code_runtime.auth import CodingAuthResult
from app.models import EnterpriseAuthAccount, EnterpriseAuthBinding, User
from app.services.enterprise_auth import (
    DISABLED,
    ENTERPRISE_AUTH_ACCOUNT_INVALID,
    ENTERPRISE_AUTH_BINDING_AMBIGUOUS,
    ENTERPRISE_AUTH_BINDING_NOT_FOUND,
    ENTERPRISE_AUTH_BINDING_UNAVAILABLE,
    OK,
    STATUS_CONNECTED,
    STATUS_ERROR,
    EnterpriseAuthError,
    authenticate_enterprise_account,
    normalize_base_url,
    normalize_provider,
    read_access_token,
    read_refresh_token,
    refresh_bound_account_after_login,
    resolve_bound_account,
    set_account_password,
    set_account_tokens,
)


def _account(**overrides):
    values = {
        "provider": "apaas",
        "base_url": "https://apaas.example.com",
        "tenant_ref": "tenant-1",
        "account": "builder",
        "created_by": 1,
    }
    values.update(overrides)
    return EnterpriseAuthAccount(**values)


@pytest_asyncio.fixture
async def auth_db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=[
                    User.__table__,
                    EnterpriseAuthAccount.__table__,
                    EnterpriseAuthBinding.__table__,
                ],
            )
        )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        owner = User(username="owner", hashed_password="hash")
        session.add(owner)
        await session.flush()
        yield session, owner.id
    await engine.dispose()


async def _persist_account(db, owner_id, **overrides):
    account = _account(created_by=owner_id, **overrides)
    db.add(account)
    await db.flush()
    return account


async def _persist_binding(db, owner_id, left, right, *, priority=100, enabled=True):
    assert left.id < right.id
    binding = EnterpriseAuthBinding(
        left_account_id=left.id,
        right_account_id=right.id,
        priority=priority,
        enabled=enabled,
        created_by=owner_id,
    )
    db.add(binding)
    await db.flush()
    return binding


def test_normalizes_enterprise_identity_and_rejects_invalid_provider():
    assert normalize_provider("apaas") == "apaas"
    assert normalize_provider("coding") == "control_plane"
    assert normalize_provider(" control_plane ") == "control_plane"
    assert normalize_base_url(" https://example.com/path/// ") == "https://example.com/path"

    with pytest.raises(EnterpriseAuthError) as exc_info:
        normalize_provider("unsupported")

    assert exc_info.value.code == ENTERPRISE_AUTH_ACCOUNT_INVALID


def test_account_credentials_are_encrypted_and_round_trip():
    account = _account()
    expires_at = datetime(2030, 1, 2, 3, 4, 5)

    set_account_password(account, "password-secret")
    original_password_enc = account.password_enc
    set_account_password(account, "")
    set_account_tokens(
        account,
        "access-secret",
        refresh_token="refresh-secret",
        expires_at=expires_at,
    )

    assert account.password_enc == original_password_enc
    assert account.password_enc != "password-secret"
    assert account.access_token_enc != "access-secret"
    assert account.refresh_token_enc != "refresh-secret"
    assert read_access_token(account) == "access-secret"
    assert read_refresh_token(account) == "refresh-secret"
    assert account.token_expires_at == expires_at
    assert account.status == STATUS_CONNECTED
    assert account.last_verified_at is not None
    assert account.last_error is None


@pytest.mark.asyncio
async def test_resolve_bound_account_returns_unique_lowest_priority(auth_db):
    db, owner_id = auth_db
    source = await _persist_account(
        db,
        owner_id,
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="source-user",
    )
    preferred = await _persist_account(
        db,
        owner_id,
        provider="apaas",
        base_url="https://apaas.example.com",
        tenant_ref="tenant-1",
        account="preferred",
        status="connected",
    )
    fallback = await _persist_account(
        db,
        owner_id,
        provider="apaas",
        base_url="https://apaas.example.com",
        tenant_ref="tenant-2",
        account="fallback",
    )
    await _persist_binding(db, owner_id, source, preferred, priority=10)
    await _persist_binding(db, owner_id, source, fallback, priority=20)
    await db.commit()

    result = await resolve_bound_account(
        db,
        "coding",
        " https://coding.example.com/ ",
        "control",
        "source-user",
        "apaas",
    )

    assert result.code == OK
    assert result.account.id == preferred.id


@pytest.mark.asyncio
async def test_resolve_bound_account_works_in_reverse_direction(auth_db):
    db, owner_id = auth_db
    target = await _persist_account(
        db,
        owner_id,
        provider="apaas",
        base_url="https://apaas.example.com",
        tenant_ref="tenant-1",
        account="target-user",
    )
    source = await _persist_account(
        db,
        owner_id,
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="source-user",
    )
    await _persist_binding(db, owner_id, target, source, priority=5)
    await db.commit()

    result = await resolve_bound_account(
        db,
        "control_plane",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
    )

    assert result.code == OK
    assert result.account.id == target.id


@pytest.mark.asyncio
async def test_resolve_bound_account_rejects_tied_lowest_priority(auth_db):
    db, owner_id = auth_db
    source = await _persist_account(
        db,
        owner_id,
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="source-user",
    )
    first = await _persist_account(
        db,
        owner_id,
        provider="apaas",
        base_url="https://apaas.example.com",
        tenant_ref="tenant-1",
        account="first",
    )
    second = await _persist_account(
        db,
        owner_id,
        provider="apaas",
        base_url="https://apaas.example.com",
        tenant_ref="tenant-2",
        account="second",
    )
    await _persist_binding(db, owner_id, source, first, priority=10)
    await _persist_binding(db, owner_id, source, second, priority=10)
    await db.commit()

    result = await resolve_bound_account(
        db,
        "coding",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
    )

    assert result.account is None
    assert result.code == ENTERPRISE_AUTH_BINDING_AMBIGUOUS


@pytest.mark.asyncio
async def test_resolve_bound_account_returns_not_found_without_binding(auth_db):
    db, owner_id = auth_db
    await _persist_account(
        db,
        owner_id,
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="source-user",
    )
    await db.commit()

    result = await resolve_bound_account(
        db,
        "coding",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
    )

    assert result.account is None
    assert result.code == ENTERPRISE_AUTH_BINDING_NOT_FOUND


@pytest.mark.asyncio
async def test_resolve_bound_account_ignores_disabled_source_account(auth_db):
    db, owner_id = auth_db
    source = await _persist_account(
        db,
        owner_id,
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="source-user",
        status="disabled",
    )
    target = await _persist_account(
        db,
        owner_id,
        provider="apaas",
        base_url="https://apaas.example.com",
        tenant_ref="tenant-1",
        account="target-user",
    )
    await _persist_binding(db, owner_id, source, target, priority=10)
    await db.commit()

    result = await resolve_bound_account(
        db,
        "coding",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
    )

    assert result.account is None
    assert result.code == ENTERPRISE_AUTH_BINDING_NOT_FOUND


@pytest.mark.asyncio
async def test_authenticate_apaas_account_saves_encrypted_token(monkeypatch):
    from app.services import enterprise_auth

    account = _account(tenant_ref="tenant-apaas")
    set_account_password(account, "apaas-password")
    calls = []

    class FakeAPaaSClient:
        def __init__(self, base_url, tenant_id):
            calls.append(("init", base_url, tenant_id))

        async def login(self, username, password):
            calls.append(("login", username, password))
            return {"token": "apaas-access-token"}

    monkeypatch.setattr(enterprise_auth, "APaaSClient", FakeAPaaSClient)

    result = await authenticate_enterprise_account(account)

    assert result is account
    assert calls == [
        ("init", "https://apaas.example.com", "tenant-apaas"),
        ("login", "builder", "apaas-password"),
    ]
    assert account.access_token_enc != "apaas-access-token"
    assert read_access_token(account) == "apaas-access-token"
    assert read_refresh_token(account) is None
    assert account.status == STATUS_CONNECTED


@pytest.mark.asyncio
async def test_authenticate_control_plane_account_uses_own_base_url_and_saves_tokens(
    monkeypatch,
):
    from app.services import enterprise_auth

    account = _account(
        provider="control_plane",
        base_url=" https://coding.example.com/ ",
        tenant_ref="control",
    )
    set_account_password(account, "coding-password")
    calls = []

    async def fake_login(username, password, base_url=None):
        calls.append((username, password, base_url))
        return CodingAuthResult(
            username=username,
            access_token="coding-access-token",
            refresh_token="coding-refresh-token",
        )

    monkeypatch.setattr(
        enterprise_auth,
        "login_to_coding_control_plane",
        fake_login,
    )

    result = await authenticate_enterprise_account(account)

    assert result is account
    assert calls == [("builder", "coding-password", "https://coding.example.com")]
    assert account.access_token_enc != "coding-access-token"
    assert account.refresh_token_enc != "coding-refresh-token"
    assert read_access_token(account) == "coding-access-token"
    assert read_refresh_token(account) == "coding-refresh-token"
    assert account.status == STATUS_CONNECTED


@pytest.mark.asyncio
async def test_authenticate_account_without_password_uses_approved_invalid_code():
    account = _account(password_enc=None)

    with pytest.raises(EnterpriseAuthError) as exc_info:
        await authenticate_enterprise_account(account)

    assert exc_info.value.code == ENTERPRISE_AUTH_ACCOUNT_INVALID


@pytest.mark.asyncio
async def test_refresh_bound_account_disabled_does_not_query_database(monkeypatch):
    from app.config import settings

    class NoQuerySession:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("database must not be queried")

        async def commit(self):
            raise AssertionError("database must not be committed")

    monkeypatch.setattr(settings, "auth_account_binding_enabled", False)

    result = await refresh_bound_account_after_login(
        NoQuerySession(),
        "coding",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
    )

    assert result.account is None
    assert result.code == DISABLED


@pytest.mark.asyncio
async def test_refresh_bound_account_records_safe_failure_and_never_raises(
    monkeypatch,
):
    from app.config import settings
    from app.services import enterprise_auth

    account = _account()

    class FakeSession:
        def __init__(self):
            self.commit_count = 0

        async def commit(self):
            self.commit_count += 1

    async def fake_resolve(*_args, **_kwargs):
        return enterprise_auth.BindingResolution(account, OK, "resolved")

    async def fake_authenticate(_account):
        raise RuntimeError("password-secret token-secret")

    db = FakeSession()
    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)
    monkeypatch.setattr(enterprise_auth, "resolve_bound_account", fake_resolve)
    monkeypatch.setattr(
        enterprise_auth,
        "authenticate_enterprise_account",
        fake_authenticate,
    )

    result = await refresh_bound_account_after_login(
        db,
        "coding",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
    )

    assert result.account is account
    assert result.code == ENTERPRISE_AUTH_BINDING_UNAVAILABLE
    assert account.status == STATUS_ERROR
    assert account.last_error
    assert "password-secret" not in account.last_error
    assert "token-secret" not in account.last_error
    assert db.commit_count == 1
