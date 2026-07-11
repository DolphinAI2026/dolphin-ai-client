from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
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
    STATUS_DISABLED,
    STATUS_ERROR,
    STATUS_UNVERIFIED,
    EnterpriseAuthError,
    authenticate_enterprise_account,
    base_url_origin_changed,
    normalize_base_url,
    normalize_provider,
    read_access_token,
    read_refresh_token,
    refresh_bound_account_after_login,
    resolve_bound_account,
    set_account_password,
    set_account_tokens,
    validate_enterprise_base_url,
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


def test_validates_enterprise_base_url_without_blocking_local_deployments():
    assert (
        validate_enterprise_base_url(" http://127.0.0.1:8080/backend/// ")
        == "http://127.0.0.1:8080/backend"
    )
    assert (
        validate_enterprise_base_url("https://apaas.example.com/platform/")
        == "https://apaas.example.com/platform"
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "apaas.example.com",
        "/backend",
        "ftp://apaas.example.com",
        "https:///backend",
        "https://user@apaas.example.com",
        "https://user:password@apaas.example.com",
        "https://apaas.example.com/backend?tenant=1",
        "https://apaas.example.com/backend#token",
    ],
)
def test_rejects_unsafe_enterprise_base_url(base_url):
    with pytest.raises(EnterpriseAuthError) as exc_info:
        validate_enterprise_base_url(base_url)

    assert exc_info.value.code == ENTERPRISE_AUTH_ACCOUNT_INVALID


def test_base_url_origin_change_requires_new_credentials_contract():
    assert not base_url_origin_changed(
        "https://apaas.example.com/backend",
        "https://APAAS.EXAMPLE.COM/other-path",
    )
    assert base_url_origin_changed(
        "http://apaas.example.com/backend",
        "https://apaas.example.com/backend",
    )
    assert base_url_origin_changed(
        "https://apaas.example.com/backend",
        "https://apaas.example.com:8443/backend",
    )


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


@pytest.mark.parametrize("status", ["unverified", "error", "disabled"])
def test_token_reads_reject_accounts_that_are_not_connected(status):
    account = _account()
    set_account_tokens(
        account,
        "access-secret",
        refresh_token="refresh-secret",
    )
    account.status = status

    assert read_access_token(account) is None
    assert read_refresh_token(account) is None


def test_token_reads_reject_expired_connected_account():
    account = _account()
    set_account_tokens(
        account,
        "access-secret",
        refresh_token="refresh-secret",
        expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
    )

    assert read_access_token(account) is None
    assert read_refresh_token(account) is None


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
async def test_resolve_bound_account_ignores_disabled_target_account(auth_db):
    db, owner_id = auth_db
    source = await _persist_account(
        db,
        owner_id,
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="source-user",
    )
    target = await _persist_account(
        db,
        owner_id,
        provider="apaas",
        base_url="https://apaas.example.com",
        tenant_ref="tenant-1",
        account="target-user",
        status="disabled",
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
async def test_resolve_bound_account_ignores_disabled_binding(auth_db):
    db, owner_id = auth_db
    source = await _persist_account(
        db,
        owner_id,
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="source-user",
    )
    target = await _persist_account(
        db,
        owner_id,
        provider="apaas",
        base_url="https://apaas.example.com",
        tenant_ref="tenant-1",
        account="target-user",
    )
    await _persist_binding(
        db,
        owner_id,
        source,
        target,
        priority=10,
        enabled=False,
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
async def test_authenticate_apaas_account_saves_encrypted_token(monkeypatch):
    from app.services import enterprise_auth

    account = _account(tenant_ref="tenant-apaas")
    set_account_password(account, "apaas-password")
    calls = []

    class FakeAPaaSClient:
        def __init__(
            self,
            base_url,
            tenant_id,
            verify_tls,
            record_call_logs,
        ):
            calls.append(
                (
                    "init",
                    base_url,
                    tenant_id,
                    verify_tls,
                    record_call_logs,
                )
            )

        async def login(self, username, password):
            calls.append(("login", username, password))
            return {"token": "apaas-access-token"}

    monkeypatch.setattr(enterprise_auth, "APaaSClient", FakeAPaaSClient)

    result = await authenticate_enterprise_account(account)

    assert result is account
    assert calls == [
        (
            "init",
            "https://apaas.example.com",
            "tenant-apaas",
            True,
            False,
        ),
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
async def test_authenticate_rejects_unsafe_base_url_before_client_creation(
    monkeypatch,
):
    from app.services import enterprise_auth

    account = _account(base_url="https://user:password@apaas.example.com")
    set_account_password(account, "apaas-password")

    class UnexpectedClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("client must not be created")

    monkeypatch.setattr(enterprise_auth, "APaaSClient", UnexpectedClient)

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
async def test_refresh_revalidates_binding_before_persisting_tokens(
    auth_db,
    monkeypatch,
):
    from app.config import settings
    from app.services import enterprise_auth

    db, owner_id = auth_db
    source = await _persist_account(
        db,
        owner_id,
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="source-user",
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
    target_id = target.id

    original_resolve = enterprise_auth.resolve_bound_account
    resolve_count = 0

    async def fake_resolve(*args, **kwargs):
        nonlocal resolve_count
        resolve_count += 1
        if resolve_count == 1:
            return await original_resolve(*args, **kwargs)
        return enterprise_auth.BindingResolution(
            None,
            ENTERPRISE_AUTH_BINDING_AMBIGUOUS,
            "changed during authentication",
        )

    async def fake_authenticate(account):
        set_account_tokens(
            account,
            "transient-access-token",
            refresh_token="transient-refresh-token",
        )
        return account

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

    stored = await db.get(EnterpriseAuthAccount, target_id)
    await db.refresh(stored)
    assert resolve_count == 2
    assert result.code == ENTERPRISE_AUTH_BINDING_UNAVAILABLE
    assert stored.access_token_enc is None
    assert stored.refresh_token_enc is None
    assert stored.status == STATUS_UNVERIFIED


@pytest.mark.asyncio
async def test_refresh_auth_failure_rolls_back_token_and_records_safe_error(
    auth_db,
    monkeypatch,
):
    from app.config import settings
    from app.services import enterprise_auth

    db, owner_id = auth_db
    source = await _persist_account(
        db,
        owner_id,
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="source-user",
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
    target_id = target.id

    async def fake_authenticate(account):
        set_account_tokens(
            account,
            "transient-access-token",
            refresh_token="transient-refresh-token",
        )
        raise RuntimeError("password-secret token-secret")

    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)
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

    stored = await db.get(EnterpriseAuthAccount, target_id)
    await db.refresh(stored)
    assert result.code == ENTERPRISE_AUTH_BINDING_UNAVAILABLE
    assert stored.status == STATUS_ERROR
    assert stored.access_token_enc is None
    assert stored.refresh_token_enc is None
    assert stored.last_error
    assert "password-secret" not in stored.last_error
    assert "token-secret" not in stored.last_error
    rows = (await db.execute(select(EnterpriseAuthAccount))).scalars().all()
    assert rows


@pytest.mark.asyncio
async def test_refresh_query_failure_rolls_back_and_session_remains_usable(
    auth_db,
    monkeypatch,
):
    from app.config import settings

    db, _owner_id = auth_db

    class FailFirstQuerySession:
        def __init__(self, session):
            self.session = session
            self.execute_count = 0
            self.rollback_count = 0

        async def execute(self, *args, **kwargs):
            self.execute_count += 1
            if self.execute_count == 1:
                raise RuntimeError("query failed")
            return await self.session.execute(*args, **kwargs)

        async def rollback(self):
            self.rollback_count += 1
            await self.session.rollback()

    failing_db = FailFirstQuerySession(db)
    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)

    result = await refresh_bound_account_after_login(
        failing_db,
        "coding",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
    )

    assert result.code == ENTERPRISE_AUTH_BINDING_UNAVAILABLE
    assert failing_db.rollback_count == 1
    rows = (await failing_db.execute(select(User))).scalars().all()
    assert isinstance(rows, list)


@pytest.mark.asyncio
async def test_refresh_rolls_back_when_token_and_error_commits_both_fail(
    auth_db,
    monkeypatch,
):
    from app.config import settings
    from app.services import enterprise_auth

    db, owner_id = auth_db
    source = await _persist_account(
        db,
        owner_id,
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="source-user",
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
    target_id = target.id

    class FailingCommitSession:
        def __init__(self, session):
            self.session = session
            self.commit_count = 0
            self.rollback_count = 0

        async def execute(self, *args, **kwargs):
            return await self.session.execute(*args, **kwargs)

        async def get(self, *args, **kwargs):
            return await self.session.get(*args, **kwargs)

        async def refresh(self, *args, **kwargs):
            return await self.session.refresh(*args, **kwargs)

        async def commit(self):
            self.commit_count += 1
            raise RuntimeError("commit failed")

        async def rollback(self):
            self.rollback_count += 1
            await self.session.rollback()

    async def fake_authenticate(account):
        set_account_tokens(
            account,
            "transient-access-token",
            refresh_token="transient-refresh-token",
        )
        return account

    failing_db = FailingCommitSession(db)
    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)
    monkeypatch.setattr(
        enterprise_auth,
        "authenticate_enterprise_account",
        fake_authenticate,
    )

    result = await refresh_bound_account_after_login(
        failing_db,
        "coding",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
    )

    assert result.code == ENTERPRISE_AUTH_BINDING_UNAVAILABLE
    assert failing_db.commit_count == 2
    assert failing_db.rollback_count >= 3
    stored = await db.get(EnterpriseAuthAccount, target_id)
    await db.refresh(stored)
    assert stored.status == STATUS_UNVERIFIED
    assert stored.access_token_enc is None
    rows = (await db.execute(select(EnterpriseAuthAccount))).scalars().all()
    assert rows
