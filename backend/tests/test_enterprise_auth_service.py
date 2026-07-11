from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.dml import Update

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
    resolve_provider_token_for_context,
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


def test_enterprise_base_url_uses_idna2008_uts46_hostname_normalization():
    assert (
        validate_enterprise_base_url("https://faß.de/backend")
        == "https://xn--fa-hia.de/backend"
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://bad_label.example.com",
        "https://-leading-hyphen.example.com",
        "https://trailing-hyphen-.example.com",
    ],
)
def test_enterprise_base_url_rejects_invalid_idna_labels(base_url):
    with pytest.raises(EnterpriseAuthError) as exc_info:
        validate_enterprise_base_url(base_url)

    assert exc_info.value.code == ENTERPRISE_AUTH_ACCOUNT_INVALID


def test_enterprise_base_url_normalizes_rfc_dot_segments():
    assert (
        validate_enterprise_base_url("https://apaas.example.com/a/../b")
        == validate_enterprise_base_url("https://apaas.example.com/b")
        == "https://apaas.example.com/b"
    )
    assert (
        validate_enterprise_base_url("https://apaas.example.com/a/./b/")
        == "https://apaas.example.com/a/b"
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://apaas.example.com:0/backend",
        "https://apaas.example.com:65536/backend",
    ],
)
def test_enterprise_base_url_rejects_ports_outside_valid_range(base_url):
    with pytest.raises(EnterpriseAuthError) as exc_info:
        validate_enterprise_base_url(base_url)

    assert exc_info.value.code == ENTERPRISE_AUTH_ACCOUNT_INVALID


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
    assert not base_url_origin_changed(
        "https://apaas.example.com:443/backend",
        "https://apaas.example.com/other-path",
    )
    assert base_url_origin_changed(
        "http://apaas.example.com/backend",
        "https://apaas.example.com/backend",
    )
    assert base_url_origin_changed(
        "https://apaas.example.com/backend",
        "https://apaas.example.com:8443/backend",
    )


def test_base_url_origin_change_rejects_explicit_port_zero():
    with pytest.raises(EnterpriseAuthError) as exc_info:
        base_url_origin_changed(
            "https://apaas.example.com:0/backend",
            "https://apaas.example.com/backend",
        )

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
async def test_resolve_provider_token_uses_current_coding_login_token_when_binding_disabled(
    monkeypatch,
):
    from app.config import settings

    class NoQuerySession:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("direct Control Plane login must not query bindings")

    monkeypatch.setattr(settings, "auth_account_binding_enabled", False)
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            account_source="coding",
            coding_access_token=" direct-control-plane-token ",
        )
    )

    token = await resolve_provider_token_for_context(
        NoQuerySession(),
        ctx,
        "control_plane",
    )

    assert token == "direct-control-plane-token"


@pytest.mark.asyncio
async def test_resolve_provider_token_uses_apaas_binding_identity_and_target_token(
    monkeypatch,
):
    from app.config import settings
    from app.services import enterprise_auth

    target = _account(
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="coding-user",
    )
    set_account_tokens(target, "bound-control-plane-token")
    calls = []

    async def fake_resolve_bound_account(*args, **kwargs):
        calls.append((args, kwargs))
        return enterprise_auth.BindingResolution(
            account=target,
            code=OK,
            message="resolved",
        )

    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)
    monkeypatch.setattr(settings, "apaas_base_url", "https://settings.example.com")
    monkeypatch.setattr(
        enterprise_auth,
        "resolve_bound_account",
        fake_resolve_bound_account,
    )
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            account_source="apaas",
            username="apaas-user",
            apaas_base_url="https://user.example.com/backend/",
            apaas_tenant_id="user-tenant",
        ),
        tenant_id=7,
        apaas_tenant_id="ctx-tenant",
    )

    token = await resolve_provider_token_for_context(
        SimpleNamespace(),
        ctx,
        "control_plane",
    )

    assert token == "bound-control-plane-token"
    assert calls == [(
        (
            SimpleNamespace(),
            "apaas",
            "https://user.example.com/backend/",
            "ctx-tenant",
            "apaas-user",
            "control_plane",
        ),
        {},
    )]


@pytest.mark.asyncio
async def test_resolve_provider_token_uses_local_tenant_apaas_id_as_last_fallback(
    monkeypatch,
):
    from app.config import settings
    from app.services import enterprise_auth

    target = _account(provider="control_plane")
    set_account_tokens(target, "bound-token")
    captured = {}

    class TenantResult:
        def scalar_one_or_none(self):
            return "local-apaas-tenant"

    class TenantSession:
        async def execute(self, _statement):
            return TenantResult()

    async def fake_resolve_bound_account(
        db,
        source_provider,
        source_base_url,
        source_tenant_ref,
        source_account,
        target_provider,
    ):
        captured.update(
            db=db,
            source_provider=source_provider,
            source_base_url=source_base_url,
            source_tenant_ref=source_tenant_ref,
            source_account=source_account,
            target_provider=target_provider,
        )
        return enterprise_auth.BindingResolution(target, OK, "resolved")

    db = TenantSession()
    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)
    monkeypatch.setattr(settings, "apaas_base_url", "https://settings.example.com")
    monkeypatch.setattr(
        enterprise_auth,
        "resolve_bound_account",
        fake_resolve_bound_account,
    )
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            account_source="apaas",
            username="apaas-user",
            apaas_base_url=None,
            apaas_tenant_id=None,
        ),
        tenant_id=7,
        apaas_tenant_id=None,
    )

    token = await resolve_provider_token_for_context(db, ctx, "control_plane")

    assert token == "bound-token"
    assert captured == {
        "db": db,
        "source_provider": "apaas",
        "source_base_url": "https://settings.example.com",
        "source_tenant_ref": "local-apaas-tenant",
        "source_account": "apaas-user",
        "target_provider": "control_plane",
    }


@pytest.mark.asyncio
async def test_resolve_provider_token_does_not_query_apaas_binding_when_disabled(
    monkeypatch,
):
    from app.config import settings

    class NoQuerySession:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("disabled binding must not query database")

    monkeypatch.setattr(settings, "auth_account_binding_enabled", False)
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            account_source="apaas",
            username="apaas-user",
        )
    )

    token = await resolve_provider_token_for_context(
        NoQuerySession(),
        ctx,
        "control_plane",
    )

    assert token is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resolution_code",
    [
        ENTERPRISE_AUTH_BINDING_NOT_FOUND,
        ENTERPRISE_AUTH_BINDING_AMBIGUOUS,
        ENTERPRISE_AUTH_BINDING_UNAVAILABLE,
    ],
)
async def test_resolve_provider_token_fails_closed_for_unusable_binding_resolution(
    monkeypatch,
    resolution_code,
):
    from app.config import settings
    from app.services import enterprise_auth

    async def fake_resolve_bound_account(*_args, **_kwargs):
        return enterprise_auth.BindingResolution(
            account=None,
            code=resolution_code,
            message="not usable",
        )

    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)
    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas.example.com")
    monkeypatch.setattr(
        enterprise_auth,
        "resolve_bound_account",
        fake_resolve_bound_account,
    )
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            account_source="apaas",
            username="apaas-user",
            apaas_base_url=None,
            apaas_tenant_id="tenant-1",
        ),
        tenant_id=7,
        apaas_tenant_id=None,
    )

    token = await resolve_provider_token_for_context(
        SimpleNamespace(),
        ctx,
        "control_plane",
    )

    assert token is None


@pytest.mark.asyncio
async def test_resolve_provider_token_rejects_expired_bound_token(monkeypatch):
    from app.config import settings
    from app.services import enterprise_auth

    target = _account(provider="control_plane")
    set_account_tokens(
        target,
        "expired-token",
        expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
    )

    async def fake_resolve_bound_account(*_args, **_kwargs):
        return enterprise_auth.BindingResolution(target, OK, "resolved")

    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)
    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas.example.com")
    monkeypatch.setattr(
        enterprise_auth,
        "resolve_bound_account",
        fake_resolve_bound_account,
    )
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            account_source="apaas",
            username="apaas-user",
            apaas_tenant_id="tenant-1",
        ),
        tenant_id=7,
        apaas_tenant_id=None,
    )

    token = await resolve_provider_token_for_context(
        SimpleNamespace(),
        ctx,
        "control_plane",
    )

    assert token is None


@pytest.mark.asyncio
async def test_resolve_provider_token_fails_closed_on_decryption_error(monkeypatch):
    from app.config import settings
    from app.services import enterprise_auth

    target = _account(
        provider="control_plane",
        status=STATUS_CONNECTED,
        access_token_enc="corrupt-token",
    )

    async def fake_resolve_bound_account(*_args, **_kwargs):
        return enterprise_auth.BindingResolution(target, OK, "resolved")

    def fail_decrypt(_value):
        raise ValueError("secret material must not escape")

    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)
    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas.example.com")
    monkeypatch.setattr(
        enterprise_auth,
        "resolve_bound_account",
        fake_resolve_bound_account,
    )
    monkeypatch.setattr(enterprise_auth.crypto, "decrypt_password", fail_decrypt)
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            account_source="apaas",
            username="apaas-user",
            apaas_tenant_id="tenant-1",
        ),
        tenant_id=7,
        apaas_tenant_id=None,
    )

    token = await resolve_provider_token_for_context(
        SimpleNamespace(),
        ctx,
        "control_plane",
    )

    assert token is None


@pytest.mark.asyncio
async def test_resolve_provider_token_fails_closed_on_database_error(monkeypatch):
    from app.config import settings

    class FailingSession:
        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

        async def rollback(self):
            return None

    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)
    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas.example.com")
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            account_source="apaas",
            username="apaas-user",
            apaas_tenant_id=None,
        ),
        tenant_id=7,
        apaas_tenant_id=None,
    )

    token = await resolve_provider_token_for_context(
        FailingSession(),
        ctx,
        "control_plane",
    )

    assert token is None


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
async def test_resolve_bound_account_retries_and_ignores_persistent_orphan(
):
    source = _account(
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="source-user",
    )
    source.id = 2
    target = _account(account="target-user")
    target.id = 1
    binding = EnterpriseAuthBinding(
        id=10,
        left_account_id=target.id,
        right_account_id=source.id,
        priority=10,
        enabled=True,
        created_by=1,
    )
    orphan_binding = EnterpriseAuthBinding(
        id=11,
        left_account_id=source.id,
        right_account_id=99,
        priority=1,
        enabled=True,
        created_by=1,
    )
    statements = []

    class FakeResult:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

        def all(self):
            return self.value

        def scalars(self):
            return self

    class CapturingSession:
        def __init__(self):
            self.rollback_count = 0

        async def execute(self, statement):
            statements.append(statement)
            attempt = (len(statements) - 1) // 4
            phase = (len(statements) - 1) % 4
            if phase == 0:
                return FakeResult(source)
            if phase == 1:
                pairs = [(target.id, source.id)]
                if attempt == 1:
                    pairs.append((source.id, 99))
                return FakeResult(pairs)
            if phase == 2:
                return FakeResult([target, source])
            return FakeResult([binding, orphan_binding])

        async def rollback(self):
            self.rollback_count += 1

    session = CapturingSession()
    result = await resolve_bound_account(
        session,
        "coding",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
        lock=True,
    )

    compiled = [
        " ".join(
            str(
                statement.compile(
                    dialect=mysql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
            .upper()
            .split()
        )
        for statement in statements
    ]
    assert result.account is target
    assert len(compiled) == 8
    assert session.rollback_count == 1
    assert all("FOR UPDATE" not in compiled[index] for index in (0, 1, 4, 5))
    assert "IN (1, 2)" in compiled[2]
    assert "IN (1, 2, 99)" in compiled[6]
    assert (
        "ORDER BY ENTERPRISE_AUTH_ACCOUNTS.ID ASC FOR UPDATE"
        in compiled[6]
    )
    assert (
        "ORDER BY ENTERPRISE_AUTH_BINDINGS.LEFT_ACCOUNT_ID ASC, "
        "ENTERPRISE_AUTH_BINDINGS.RIGHT_ACCOUNT_ID ASC FOR UPDATE"
        in compiled[7]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("new_priority", "expected_code"),
    [
        (5, OK),
        (10, ENTERPRISE_AUTH_BINDING_AMBIGUOUS),
    ],
)
async def test_resolve_bound_account_retries_when_locked_binding_adds_endpoint(
    new_priority,
    expected_code,
):
    old_target = _account(account="old-target")
    old_target.id = 1
    new_target = _account(account="new-target")
    new_target.id = 2
    source = _account(
        provider="control_plane",
        base_url="https://coding.example.com",
        tenant_ref="control",
        account="source-user",
    )
    source.id = 3
    old_binding = EnterpriseAuthBinding(
        id=10,
        left_account_id=old_target.id,
        right_account_id=source.id,
        priority=10,
        enabled=True,
        created_by=1,
    )
    new_binding = EnterpriseAuthBinding(
        id=11,
        left_account_id=new_target.id,
        right_account_id=source.id,
        priority=new_priority,
        enabled=True,
        created_by=1,
    )

    class FakeResult:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

        def all(self):
            return self.value

        def scalars(self):
            return self

    class EndpointDriftSession:
        def __init__(self):
            self.statements = []
            self.rollback_count = 0

        async def execute(self, statement):
            self.statements.append(statement)
            attempt = (len(self.statements) - 1) // 4
            phase = (len(self.statements) - 1) % 4
            if phase == 0:
                return FakeResult(source)
            if phase == 1:
                pairs = [(old_target.id, source.id)]
                if attempt == 1:
                    pairs.append((new_target.id, source.id))
                return FakeResult(pairs)
            if phase == 2:
                accounts = [old_target, source]
                if attempt == 1:
                    accounts.insert(1, new_target)
                return FakeResult(accounts)
            return FakeResult([old_binding, new_binding])

        async def rollback(self):
            self.rollback_count += 1

    session = EndpointDriftSession()
    result = await resolve_bound_account(
        session,
        "coding",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
        lock=True,
    )

    assert session.rollback_count == 1
    assert len(session.statements) == 8
    second_account_lock = " ".join(
        str(
            session.statements[6].compile(
                dialect=mysql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        .upper()
        .split()
    )
    assert "IN (1, 2, 3)" in second_account_lock
    assert (
        "ORDER BY ENTERPRISE_AUTH_ACCOUNTS.ID ASC FOR UPDATE"
        in second_account_lock
    )
    assert result.code == expected_code
    if expected_code == OK:
        assert result.account is new_target
    else:
        assert result.account is None


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
    locked_result = await resolve_bound_account(
        db,
        "control_plane",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
        lock=True,
    )

    assert result.code == OK
    assert result.account.id == target.id
    assert locked_result.code == result.code
    assert locked_result.account.id == result.account.id


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
    lock_values = []

    async def fake_resolve(*args, **kwargs):
        nonlocal resolve_count
        resolve_count += 1
        lock_values.append(kwargs.get("lock", False))
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
    assert lock_values == [False, True]
    assert result.code == ENTERPRISE_AUTH_BINDING_UNAVAILABLE
    assert stored.access_token_enc is None
    assert stored.refresh_token_enc is None
    assert stored.status == STATUS_UNVERIFIED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "new_value"),
    [
        ("base_url", "https://changed.example.com"),
        ("tenant_ref", "changed-tenant"),
        ("account", "changed-account"),
        ("password_enc", "changed-password-ciphertext"),
    ],
)
async def test_refresh_discards_authenticated_token_when_target_credentials_change_before_relock(
    auth_db,
    monkeypatch,
    field_name,
    new_value,
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
    set_account_password(target, "original-password")
    await _persist_binding(db, owner_id, source, target, priority=10)
    await db.commit()
    target_id = target.id

    original_resolve = enterprise_auth.resolve_bound_account
    resolve_count = 0

    async def fake_resolve(*args, **kwargs):
        nonlocal resolve_count
        resolve_count += 1
        result = await original_resolve(*args, **kwargs)
        if resolve_count == 2 and result.account is not None:
            setattr(result.account, field_name, new_value)
        return result

    async def fake_authenticate(account):
        set_account_tokens(
            account,
            "stale-access-token",
            refresh_token="stale-refresh-token",
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
    assert stored.last_error == "Enterprise account authentication failed"
    assert "password-secret" not in stored.last_error
    assert "token-secret" not in stored.last_error
    rows = (await db.execute(select(EnterpriseAuthAccount))).scalars().all()
    assert rows


@pytest.mark.asyncio
async def test_refresh_persists_tokens_with_atomic_conditional_update(
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

    class TrackingSession:
        def __init__(self, session):
            self.session = session
            self.update_count = 0
            self.refresh_count = 0

        async def execute(self, statement, *args, **kwargs):
            if isinstance(statement, Update):
                self.update_count += 1
            return await self.session.execute(statement, *args, **kwargs)

        async def get(self, *args, **kwargs):
            return await self.session.get(*args, **kwargs)

        async def refresh(self, *args, **kwargs):
            self.refresh_count += 1
            return await self.session.refresh(*args, **kwargs)

        async def commit(self):
            await self.session.commit()

        async def rollback(self):
            await self.session.rollback()

    async def fake_authenticate(account):
        set_account_tokens(
            account,
            "atomic-access-token",
            refresh_token="atomic-refresh-token",
        )
        return account

    tracking_db = TrackingSession(db)
    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)
    monkeypatch.setattr(
        enterprise_auth,
        "authenticate_enterprise_account",
        fake_authenticate,
    )

    result = await refresh_bound_account_after_login(
        tracking_db,
        "coding",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
    )

    assert result.code == OK
    assert result.account.id == target_id
    assert tracking_db.update_count == 1
    assert tracking_db.refresh_count >= 2
    assert read_access_token(result.account) == "atomic-access-token"
    assert read_refresh_token(result.account) == "atomic-refresh-token"


@pytest.mark.asyncio
async def test_refresh_atomic_update_rowcount_zero_returns_unavailable(
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

    class ZeroRowUpdateSession:
        def __init__(self, session):
            self.session = session
            self.update_count = 0

        async def execute(self, statement, *args, **kwargs):
            if isinstance(statement, Update):
                self.update_count += 1
                return SimpleNamespace(rowcount=0)
            return await self.session.execute(statement, *args, **kwargs)

        async def get(self, *args, **kwargs):
            return await self.session.get(*args, **kwargs)

        async def refresh(self, *args, **kwargs):
            return await self.session.refresh(*args, **kwargs)

        async def commit(self):
            await self.session.commit()

        async def rollback(self):
            await self.session.rollback()

    async def fake_authenticate(account):
        set_account_tokens(
            account,
            "transient-access-token",
            refresh_token="transient-refresh-token",
        )
        return account

    zero_row_db = ZeroRowUpdateSession(db)
    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)
    monkeypatch.setattr(
        enterprise_auth,
        "authenticate_enterprise_account",
        fake_authenticate,
    )

    result = await refresh_bound_account_after_login(
        zero_row_db,
        "coding",
        "https://coding.example.com",
        "control",
        "source-user",
        "apaas",
    )

    stored = await db.get(EnterpriseAuthAccount, target_id)
    await db.refresh(stored)
    assert zero_row_db.update_count == 1
    assert result.code == ENTERPRISE_AUTH_BINDING_UNAVAILABLE
    assert stored.status == STATUS_UNVERIFIED
    assert stored.access_token_enc is None


@pytest.mark.asyncio
async def test_failure_status_update_is_atomic_and_does_not_match_disabled():
    from app.services import enterprise_auth

    statements = []

    class DisabledAccountSession:
        async def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(rowcount=0)

        async def get(self, *_args, **_kwargs):
            return _account(id=7, status=STATUS_DISABLED)

        async def commit(self):
            raise AssertionError("disabled account must not be updated")

        async def rollback(self):
            return None

    result = await enterprise_auth._record_account_auth_failure(
        DisabledAccountSession(),
        7,
        "classified failure",
    )

    compiled = str(
        statements[0].compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert result.status == STATUS_DISABLED
    assert "update enterprise_auth_accounts" in compiled
    assert "status != 'disabled'" in compiled


@pytest.mark.asyncio
async def test_refresh_commit_failure_records_persistence_error(
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

    class FailFirstCommitSession:
        def __init__(self, session):
            self.session = session
            self.commit_count = 0

        async def execute(self, *args, **kwargs):
            return await self.session.execute(*args, **kwargs)

        async def get(self, *args, **kwargs):
            return await self.session.get(*args, **kwargs)

        async def refresh(self, *args, **kwargs):
            return await self.session.refresh(*args, **kwargs)

        async def commit(self):
            self.commit_count += 1
            if self.commit_count == 1:
                raise RuntimeError("credential commit failed")
            await self.session.commit()

        async def rollback(self):
            await self.session.rollback()

    async def fake_authenticate(account):
        set_account_tokens(
            account,
            "transient-access-token",
            refresh_token="transient-refresh-token",
        )
        return account

    failing_db = FailFirstCommitSession(db)
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

    stored = await db.get(EnterpriseAuthAccount, target_id)
    await db.refresh(stored)
    assert result.code == ENTERPRISE_AUTH_BINDING_UNAVAILABLE
    assert stored.status == STATUS_ERROR
    assert (
        stored.last_error
        == "Enterprise account credential persistence failed"
    )
    assert stored.access_token_enc is None


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
