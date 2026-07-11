from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field
from sqlalchemy import event, select
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.deps import get_auth_context
from app.models import EnterpriseAuthAccount, EnterpriseAuthBinding, User
from app.crypto import decrypt_password
from app.services.enterprise_auth import (
    ENTERPRISE_AUTH_ACCOUNT_INVALID,
    STATUS_CONNECTED,
    STATUS_DISABLED,
    STATUS_ERROR,
    STATUS_UNVERIFIED,
    EnterpriseAuthError,
    set_account_tokens,
)


ACCOUNT_PATH = "/enterprise-auth/accounts"
BINDING_PATH = "/enterprise-auth/bindings"


class OtherValidationInput(BaseModel):
    name: str = Field(min_length=3)


def _account_payload(**overrides):
    values = {
        "provider": "apaas",
        "base_url": "https://apaas.example.com/backend",
        "tenant_ref": "tenant-1",
        "tenant_name": "Tenant One",
        "account": "builder-admin",
        "password": "secret-password",
        "enabled": True,
    }
    values.update(overrides)
    return values


def _assert_no_secrets(payload):
    forbidden_keys = {
        "password",
        "password_enc",
        "access_token_enc",
        "refresh_token_enc",
    }
    forbidden_values = {
        "secret-password",
        "access-secret",
        "refresh-secret",
    }

    def _visit(value):
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            for nested in value.values():
                _visit(nested)
        elif isinstance(value, list):
            for nested in value:
                _visit(nested)
        elif isinstance(value, str):
            assert value not in forbidden_values

    _visit(payload)


@pytest_asyncio.fixture
async def api():
    from app.routes import enterprise_auth

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _disable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

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
        owner = User(
            username="platform-admin",
            hashed_password="hash",
            is_platform_admin=True,
        )
        session.add(owner)
        await session.commit()
        owner_id = owner.id

    async def _override_db():
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.add_exception_handler(
        RequestValidationError,
        enterprise_auth.enterprise_auth_validation_exception_handler,
    )
    app.include_router(enterprise_auth.router)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[
        enterprise_auth.require_enterprise_auth_admin
    ] = lambda: SimpleNamespace(
        user=SimpleNamespace(id=owner_id, is_platform_admin=True),
        tenant_role="platform_admin",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield SimpleNamespace(
            client=client,
            app=app,
            engine=engine,
            session_factory=session_factory,
            owner_id=owner_id,
            routes=enterprise_auth,
        )

    await engine.dispose()


async def _create_account(api, **overrides):
    response = await api.client.post(
        ACCOUNT_PATH,
        json=_account_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", ACCOUNT_PATH, None),
        ("POST", ACCOUNT_PATH, _account_payload()),
        ("PUT", f"{ACCOUNT_PATH}/1", {"tenant_name": "Updated"}),
        ("DELETE", f"{ACCOUNT_PATH}/1", None),
        ("POST", f"{ACCOUNT_PATH}/1/test", None),
        ("GET", BINDING_PATH, None),
        (
            "POST",
            BINDING_PATH,
            {
                "left_account_id": 1,
                "right_account_id": 2,
                "priority": 0,
                "enabled": True,
            },
        ),
        ("PUT", f"{BINDING_PATH}/1", {"priority": 1}),
        ("DELETE", f"{BINDING_PATH}/1", None),
        ("GET", "/enterprise-auth/status", None),
    ],
)
async def test_all_endpoints_require_real_platform_admin(method, path, json_body):
    from app.routes import enterprise_auth

    app = FastAPI()
    app.include_router(enterprise_auth.router)
    app.dependency_overrides[get_auth_context] = lambda: SimpleNamespace(
        user=SimpleNamespace(id=2, is_platform_admin=False),
        tenant_role="member",
        tenant_id=1,
        org_permissions={},
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.request(method, path, json=json_body)

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "ENTERPRISE_AUTH_ADMIN_REQUIRED",
        "message": "需要平台管理员权限",
    }


@pytest.mark.asyncio
async def test_create_and_list_accounts_normalize_and_hide_secrets(api):
    response = await api.client.post(
        ACCOUNT_PATH,
        json=_account_payload(
            provider=" apaas ",
            base_url=" HTTPS://APAAS.EXAMPLE.COM/backend/// ",
            tenant_ref=" tenant-1 ",
            tenant_name=" Tenant One ",
            account=" builder-admin ",
            password=" secret-password ",
        ),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["provider"] == "apaas"
    assert body["base_url"] == "https://apaas.example.com/backend"
    assert body["tenant_ref"] == "tenant-1"
    assert body["tenant_name"] == "Tenant One"
    assert body["account"] == "builder-admin"
    assert body["has_password"] is True
    assert body["has_access_token"] is False
    assert body["status"] == STATUS_UNVERIFIED
    _assert_no_secrets(body)

    list_response = await api.client.get(ACCOUNT_PATH)
    assert list_response.status_code == 200
    assert list_response.json() == [body]
    _assert_no_secrets(list_response.json())

    async with api.session_factory() as session:
        stored = (
            await session.execute(select(EnterpriseAuthAccount))
        ).scalar_one()
        assert stored.password_enc
        assert stored.password_enc != "secret-password"
        assert stored.created_by == api.owner_id
        assert stored.status == STATUS_UNVERIFIED


@pytest.mark.asyncio
async def test_create_and_update_preserve_password_whitespace_exactly(api):
    created = await _create_account(api, password="  secret  ")
    async with api.session_factory() as session:
        stored = await session.get(EnterpriseAuthAccount, created["id"])
        assert decrypt_password(stored.password_enc) == "  secret  "

    response = await api.client.put(
        f"{ACCOUNT_PATH}/{created['id']}",
        json={"password": "  rotated secret  "},
    )

    assert response.status_code == 200, response.text
    async with api.session_factory() as session:
        stored = await session.get(EnterpriseAuthAccount, created["id"])
        assert decrypt_password(stored.password_enc) == "  rotated secret  "


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "secret_value"),
    [
        (_account_payload(password="   "), None),
        (
            _account_payload(password="overlong-secret-" + ("x" * 4090)),
            "overlong-secret-",
        ),
        (
            _account_payload(
                password_enc="password-enc-secret",
                access_token_enc="access-token-enc-secret",
            ),
            "password-enc-secret",
        ),
    ],
)
async def test_enterprise_auth_validation_errors_are_redacted(
    api,
    payload,
    secret_value,
):
    response = await api.client.post(ACCOUNT_PATH, json=payload)

    assert response.status_code == 422
    assert '"input"' not in response.text
    assert '"ctx"' not in response.text
    if secret_value is not None:
        assert secret_value not in response.text
    for error in response.json()["detail"]:
        assert set(error) <= {"loc", "msg", "type"}


@pytest.mark.asyncio
async def test_validation_handler_delegates_non_enterprise_paths_to_fastapi_default():
    from app.routes.enterprise_auth import (
        enterprise_auth_validation_exception_handler,
    )

    app = FastAPI()
    app.add_exception_handler(
        RequestValidationError,
        enterprise_auth_validation_exception_handler,
    )

    @app.post("/other")
    async def other_route(data: OtherValidationInput):
        return data

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/other", json={"name": "x"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == "x"


def test_production_main_registers_enterprise_auth_validation_handler():
    from app.main import app
    from app.routes.enterprise_auth import (
        enterprise_auth_validation_exception_handler,
    )

    assert (
        app.exception_handlers[RequestValidationError]
        is enterprise_auth_validation_exception_handler
    )


@pytest.mark.asyncio
async def test_status_is_platform_admin_read_only_configuration(api, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "auth_provider", "control_plane")
    monkeypatch.setattr(settings, "auth_account_binding_enabled", True)

    response = await api.client.get("/enterprise-auth/status")

    assert response.status_code == 200
    assert response.json() == {
        "auth_provider": "control_plane",
        "binding_enabled": True,
    }


@pytest.mark.asyncio
async def test_duplicate_account_returns_structured_conflict(api):
    assert (
        await api.client.post(ACCOUNT_PATH, json=_account_payload())
    ).status_code == 201

    duplicate = await api.client.post(ACCOUNT_PATH, json=_account_payload())

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "ENTERPRISE_AUTH_ACCOUNT_DUPLICATE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"provider": "control_plane"},
        {"account": "other-admin"},
        {"base_url": "https://other.example.com/backend"},
    ],
)
async def test_identity_or_origin_change_requires_new_password(api, change):
    account = await _create_account(api)

    response = await api.client.put(
        f"{ACCOUNT_PATH}/{account['id']}",
        json=change,
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == ENTERPRISE_AUTH_ACCOUNT_INVALID


@pytest.mark.asyncio
async def test_provider_update_rejects_same_provider_existing_binding(api):
    apaas = await _create_account(api)
    control = await _create_account(
        api,
        provider="control_plane",
        base_url="https://control.example.com",
        tenant_ref="enterprise-1",
        account="control-one",
    )
    binding = await api.client.post(
        BINDING_PATH,
        json={
            "left_account_id": apaas["id"],
            "right_account_id": control["id"],
            "priority": 0,
            "enabled": True,
        },
    )
    assert binding.status_code == 201

    response = await api.client.put(
        f"{ACCOUNT_PATH}/{apaas['id']}",
        json={
            "provider": "control_plane",
            "password": "new-secret",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == ENTERPRISE_AUTH_ACCOUNT_INVALID
    async with api.session_factory() as session:
        stored = await session.get(EnterpriseAuthAccount, apaas["id"])
        stored_binding = await session.get(
            EnterpriseAuthBinding,
            binding.json()["id"],
        )
        assert stored.provider == "apaas"
        assert stored_binding is not None


@pytest.mark.asyncio
async def test_account_graph_lock_retries_endpoint_drift_in_canonical_order():
    from app.services.enterprise_auth import lock_enterprise_auth_account_graph

    target = EnterpriseAuthAccount(
        id=1,
        provider="apaas",
        base_url="https://apaas.example.com",
        tenant_ref="tenant-1",
        account="target",
        created_by=1,
    )
    first_endpoint = EnterpriseAuthAccount(
        id=2,
        provider="control_plane",
        base_url="https://control.example.com",
        tenant_ref="control-1",
        account="first",
        created_by=1,
    )
    drift_endpoint = EnterpriseAuthAccount(
        id=3,
        provider="control_plane",
        base_url="https://control.example.com",
        tenant_ref="control-2",
        account="drift",
        created_by=1,
    )
    first_binding = EnterpriseAuthBinding(
        id=10,
        left_account_id=1,
        right_account_id=2,
        priority=0,
        enabled=True,
        created_by=1,
    )
    drift_binding = EnterpriseAuthBinding(
        id=11,
        left_account_id=1,
        right_account_id=3,
        priority=1,
        enabled=True,
        created_by=1,
    )

    class FakeResult:
        def __init__(self, value):
            self.value = value

        def all(self):
            return self.value

        def scalars(self):
            return self

    class DriftSession:
        def __init__(self):
            self.statements = []
            self.rollback_count = 0

        async def execute(self, statement):
            self.statements.append(statement)
            attempt = (len(self.statements) - 1) // 3
            phase = (len(self.statements) - 1) % 3
            if phase == 0:
                pairs = [(1, 2)]
                if attempt == 1:
                    pairs.append((1, 3))
                return FakeResult(pairs)
            if phase == 1:
                accounts = [target, first_endpoint]
                if attempt == 1:
                    accounts.append(drift_endpoint)
                return FakeResult(accounts)
            return FakeResult([first_binding, drift_binding])

        async def rollback(self):
            self.rollback_count += 1

    session = DriftSession()

    graph = await lock_enterprise_auth_account_graph(session, target.id)

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
        for statement in session.statements
    ]
    assert session.rollback_count == 1
    assert graph.account is target
    assert set(graph.accounts_by_id) == {1, 2, 3}
    assert [binding.id for binding in graph.bindings] == [10, 11]
    assert all("FOR UPDATE" not in compiled[index] for index in (0, 3))
    assert "IN (1, 2)" in compiled[1]
    assert "IN (1, 2, 3)" in compiled[4]
    assert "ORDER BY ENTERPRISE_AUTH_ACCOUNTS.ID ASC FOR UPDATE" in compiled[4]
    assert (
        "ORDER BY ENTERPRISE_AUTH_BINDINGS.LEFT_ACCOUNT_ID ASC, "
        "ENTERPRISE_AUTH_BINDINGS.RIGHT_ACCOUNT_ID ASC FOR UPDATE"
        in compiled[5]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"password": "new-password"},
        {"tenant_ref": "tenant-2"},
        {"base_url": "https://apaas.example.com/other-path"},
    ],
)
async def test_credential_changes_clear_tokens_and_verification(api, monkeypatch, change):
    account = await _create_account(api)

    async def _authenticate(stored):
        set_account_tokens(
            stored,
            "access-secret",
            refresh_token="refresh-secret",
        )
        return stored

    monkeypatch.setattr(api.routes, "authenticate_enterprise_account", _authenticate)
    tested = await api.client.post(f"{ACCOUNT_PATH}/{account['id']}/test")
    assert tested.status_code == 200
    assert tested.json()["status"] == STATUS_CONNECTED

    response = await api.client.put(
        f"{ACCOUNT_PATH}/{account['id']}",
        json=change,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == STATUS_UNVERIFIED
    assert body["has_access_token"] is False
    assert body["last_verified_at"] is None
    assert body["last_error"] is None
    _assert_no_secrets(body)

    async with api.session_factory() as session:
        stored = await session.get(EnterpriseAuthAccount, account["id"])
        assert stored.access_token_enc is None
        assert stored.refresh_token_enc is None
        assert stored.token_expires_at is None


@pytest.mark.asyncio
async def test_disable_and_reenable_account_use_status_contract(api):
    account = await _create_account(api)

    disabled = await api.client.put(
        f"{ACCOUNT_PATH}/{account['id']}",
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == STATUS_DISABLED

    enabled = await api.client.put(
        f"{ACCOUNT_PATH}/{account['id']}",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["status"] == STATUS_UNVERIFIED


@pytest.mark.asyncio
async def test_credential_update_does_not_implicitly_enable_disabled_account(api):
    account = await _create_account(api)
    assert (
        await api.client.put(
            f"{ACCOUNT_PATH}/{account['id']}",
            json={"enabled": False},
        )
    ).json()["status"] == STATUS_DISABLED

    updated = await api.client.put(
        f"{ACCOUNT_PATH}/{account['id']}",
        json={"tenant_ref": "tenant-2"},
    )

    assert updated.status_code == 200
    assert updated.json()["status"] == STATUS_DISABLED


@pytest.mark.asyncio
async def test_account_update_rejects_direct_status(api):
    account = await _create_account(api)

    response = await api.client.put(
        f"{ACCOUNT_PATH}/{account['id']}",
        json={"status": STATUS_CONNECTED},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_account_connection_test_success_commits_masked_tokens(api, monkeypatch):
    account = await _create_account(api)

    async def _authenticate(stored):
        set_account_tokens(
            stored,
            "access-secret",
            refresh_token="refresh-secret",
        )
        return stored

    monkeypatch.setattr(api.routes, "authenticate_enterprise_account", _authenticate)

    response = await api.client.post(f"{ACCOUNT_PATH}/{account['id']}/test")

    assert response.status_code == 200
    assert response.json()["status"] == STATUS_CONNECTED
    assert response.json()["has_access_token"] is True
    _assert_no_secrets(response.json())

    async with api.session_factory() as session:
        stored = await session.get(EnterpriseAuthAccount, account["id"])
        assert stored.access_token_enc
        assert stored.access_token_enc != "access-secret"


@pytest.mark.asyncio
async def test_account_connection_test_holds_full_account_graph_lock(
    api,
    monkeypatch,
):
    apaas = await _create_account(api)
    control = await _create_account(
        api,
        provider="control_plane",
        base_url="https://control.example.com",
        tenant_ref="enterprise-1",
        account="control-one",
    )
    assert (
        await api.client.post(
            BINDING_PATH,
            json={
                "left_account_id": apaas["id"],
                "right_account_id": control["id"],
                "priority": 0,
                "enabled": True,
            },
        )
    ).status_code == 201
    original_lock = api.routes.lock_enterprise_auth_account_graph
    locked_account_sets = []

    async def _recording_lock(db, account_id):
        graph = await original_lock(db, account_id)
        locked_account_sets.append(set(graph.accounts_by_id))
        return graph

    async def _authenticate(stored):
        set_account_tokens(stored, "access-secret")
        return stored

    monkeypatch.setattr(
        api.routes,
        "lock_enterprise_auth_account_graph",
        _recording_lock,
    )
    monkeypatch.setattr(api.routes, "authenticate_enterprise_account", _authenticate)

    response = await api.client.post(f"{ACCOUNT_PATH}/{apaas['id']}/test")

    assert response.status_code == 200
    assert locked_account_sets == [{apaas["id"], control["id"]}]


@pytest.mark.asyncio
async def test_failed_connection_test_relocks_full_graph_before_recording_error(
    api,
    monkeypatch,
):
    apaas = await _create_account(api)
    control = await _create_account(
        api,
        provider="control_plane",
        base_url="https://control.example.com",
        tenant_ref="enterprise-1",
        account="control-one",
    )
    assert (
        await api.client.post(
            BINDING_PATH,
            json={
                "left_account_id": apaas["id"],
                "right_account_id": control["id"],
                "priority": 0,
                "enabled": True,
            },
        )
    ).status_code == 201
    original_lock = api.routes.lock_enterprise_auth_account_graph
    locked_account_sets = []

    async def _recording_lock(db, account_id):
        graph = await original_lock(db, account_id)
        locked_account_sets.append(set(graph.accounts_by_id))
        return graph

    async def _authenticate(_stored):
        raise EnterpriseAuthError(
            ENTERPRISE_AUTH_ACCOUNT_INVALID,
            "upstream failure",
        )

    monkeypatch.setattr(
        api.routes,
        "lock_enterprise_auth_account_graph",
        _recording_lock,
    )
    monkeypatch.setattr(api.routes, "authenticate_enterprise_account", _authenticate)

    response = await api.client.post(f"{ACCOUNT_PATH}/{apaas['id']}/test")

    assert response.status_code == 400
    assert locked_account_sets == [
        {apaas["id"], control["id"]},
        {apaas["id"], control["id"]},
    ]
    async with api.session_factory() as session:
        stored = await session.get(EnterpriseAuthAccount, apaas["id"])
        assert stored.status == STATUS_ERROR
        assert stored.last_error == "企业认证账号验证失败"


@pytest.mark.asyncio
async def test_account_connection_test_failure_rolls_back_and_records_safe_error(
    api,
    monkeypatch,
):
    account = await _create_account(api)

    async def _authenticate(stored):
        set_account_tokens(stored, "access-secret")
        raise EnterpriseAuthError(
            ENTERPRISE_AUTH_ACCOUNT_INVALID,
            "upstream included secret-password",
        )

    monkeypatch.setattr(api.routes, "authenticate_enterprise_account", _authenticate)

    response = await api.client.post(f"{ACCOUNT_PATH}/{account['id']}/test")

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": ENTERPRISE_AUTH_ACCOUNT_INVALID,
        "message": "企业认证账号验证失败",
    }
    _assert_no_secrets(response.json())

    async with api.session_factory() as session:
        stored = await session.get(EnterpriseAuthAccount, account["id"])
        assert stored.status == STATUS_ERROR
        assert stored.access_token_enc is None
        assert stored.last_error == "企业认证账号验证失败"


@pytest.mark.asyncio
async def test_failed_connection_test_does_not_overwrite_disabled_status(api, monkeypatch):
    account = await _create_account(api)
    assert (
        await api.client.put(
            f"{ACCOUNT_PATH}/{account['id']}",
            json={"enabled": False},
        )
    ).status_code == 200

    async def _authenticate(_stored):
        raise EnterpriseAuthError(
            ENTERPRISE_AUTH_ACCOUNT_INVALID,
            "failure",
        )

    monkeypatch.setattr(api.routes, "authenticate_enterprise_account", _authenticate)

    response = await api.client.post(f"{ACCOUNT_PATH}/{account['id']}/test")

    assert response.status_code == 400
    async with api.session_factory() as session:
        stored = await session.get(EnterpriseAuthAccount, account["id"])
        assert stored.status == STATUS_DISABLED


@pytest.mark.asyncio
async def test_binding_crud_is_canonical_cross_provider_and_has_account_summaries(api):
    apaas_one = await _create_account(api, account="apaas-one")
    apaas_two = await _create_account(
        api,
        tenant_ref="tenant-2",
        account="apaas-two",
    )
    control_one = await _create_account(
        api,
        provider="control_plane",
        base_url="https://control.example.com",
        tenant_ref="enterprise-1",
        account="control-one",
    )

    first = await api.client.post(
        BINDING_PATH,
        json={
            "left_account_id": control_one["id"],
            "right_account_id": apaas_one["id"],
            "priority": 20,
            "enabled": True,
        },
    )
    assert first.status_code == 201, first.text
    first_body = first.json()
    assert first_body["left_account_id"] == min(
        control_one["id"],
        apaas_one["id"],
    )
    assert first_body["right_account_id"] == max(
        control_one["id"],
        apaas_one["id"],
    )
    assert first_body["left_account"]["id"] == first_body["left_account_id"]
    assert first_body["right_account"]["id"] == first_body["right_account_id"]
    _assert_no_secrets(first_body)

    second = await api.client.post(
        BINDING_PATH,
        json={
            "left_account_id": apaas_two["id"],
            "right_account_id": control_one["id"],
            "priority": 5,
            "enabled": True,
        },
    )
    assert second.status_code == 201

    listed = await api.client.get(BINDING_PATH)
    assert listed.status_code == 200
    assert len(listed.json()) == 2
    _assert_no_secrets(listed.json())

    updated = await api.client.put(
        f"{BINDING_PATH}/{first_body['id']}",
        json={"priority": 1, "enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["priority"] == 1
    assert updated.json()["enabled"] is False

    deleted = await api.client.delete(f"{BINDING_PATH}/{first_body['id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True, "deleted_id": first_body["id"]}


@pytest.mark.asyncio
async def test_binding_rejects_same_provider_self_missing_and_reverse_duplicate(api):
    apaas_one = await _create_account(api, account="apaas-one")
    apaas_two = await _create_account(
        api,
        tenant_ref="tenant-2",
        account="apaas-two",
    )
    control = await _create_account(
        api,
        provider="control_plane",
        base_url="https://control.example.com",
        tenant_ref="enterprise-1",
        account="control-one",
    )

    same_provider = await api.client.post(
        BINDING_PATH,
        json={
            "left_account_id": apaas_one["id"],
            "right_account_id": apaas_two["id"],
            "priority": 0,
            "enabled": True,
        },
    )
    assert same_provider.status_code == 400
    assert (
        same_provider.json()["detail"]["code"]
        == ENTERPRISE_AUTH_ACCOUNT_INVALID
    )

    self_binding = await api.client.post(
        BINDING_PATH,
        json={
            "left_account_id": apaas_one["id"],
            "right_account_id": apaas_one["id"],
            "priority": 0,
            "enabled": True,
        },
    )
    assert self_binding.status_code == 400
    assert self_binding.json()["detail"]["code"] == ENTERPRISE_AUTH_ACCOUNT_INVALID

    missing = await api.client.post(
        BINDING_PATH,
        json={
            "left_account_id": apaas_one["id"],
            "right_account_id": 99999,
            "priority": 0,
            "enabled": True,
        },
    )
    assert missing.status_code == 404
    assert (
        missing.json()["detail"]["code"]
        == "ENTERPRISE_AUTH_ACCOUNT_NOT_FOUND"
    )

    created = await api.client.post(
        BINDING_PATH,
        json={
            "left_account_id": apaas_one["id"],
            "right_account_id": control["id"],
            "priority": 0,
            "enabled": True,
        },
    )
    assert created.status_code == 201

    reverse_duplicate = await api.client.post(
        BINDING_PATH,
        json={
            "left_account_id": control["id"],
            "right_account_id": apaas_one["id"],
            "priority": 10,
            "enabled": False,
        },
    )
    assert reverse_duplicate.status_code == 409
    assert (
        reverse_duplicate.json()["detail"]["code"]
        == "ENTERPRISE_AUTH_BINDING_DUPLICATE"
    )


@pytest.mark.asyncio
async def test_binding_update_can_change_pair_and_detect_duplicate(api):
    apaas_one = await _create_account(api, account="apaas-one")
    apaas_two = await _create_account(
        api,
        tenant_ref="tenant-2",
        account="apaas-two",
    )
    control = await _create_account(
        api,
        provider="control_plane",
        base_url="https://control.example.com",
        tenant_ref="enterprise-1",
        account="control-one",
    )
    first = (
        await api.client.post(
            BINDING_PATH,
            json={
                "left_account_id": apaas_one["id"],
                "right_account_id": control["id"],
                "priority": 10,
                "enabled": True,
            },
        )
    ).json()
    second = (
        await api.client.post(
            BINDING_PATH,
            json={
                "left_account_id": apaas_two["id"],
                "right_account_id": control["id"],
                "priority": 20,
                "enabled": True,
            },
        )
    ).json()

    duplicate = await api.client.put(
        f"{BINDING_PATH}/{first['id']}",
        json={
            "left_account_id": control["id"],
            "right_account_id": apaas_two["id"],
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "ENTERPRISE_AUTH_BINDING_DUPLICATE"

    moved = await api.client.put(
        f"{BINDING_PATH}/{second['id']}",
        json={
            "left_account_id": apaas_one["id"],
            "right_account_id": control["id"],
        },
    )
    assert moved.status_code == 409


@pytest.mark.asyncio
async def test_delete_account_explicitly_removes_bindings_with_sqlite_fk_off(api):
    apaas = await _create_account(api)
    control = await _create_account(
        api,
        provider="control_plane",
        base_url="https://control.example.com",
        tenant_ref="enterprise-1",
        account="control-one",
    )
    binding = await api.client.post(
        BINDING_PATH,
        json={
            "left_account_id": apaas["id"],
            "right_account_id": control["id"],
            "priority": 0,
            "enabled": True,
        },
    )
    assert binding.status_code == 201

    response = await api.client.delete(f"{ACCOUNT_PATH}/{apaas['id']}")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "deleted_id": apaas["id"]}
    async with api.session_factory() as session:
        assert await session.get(EnterpriseAuthAccount, apaas["id"]) is None
        assert (
            await session.execute(select(EnterpriseAuthBinding))
        ).scalars().all() == []


@pytest.mark.asyncio
async def test_missing_account_and_binding_return_structured_not_found(api):
    account_response = await api.client.delete(f"{ACCOUNT_PATH}/99999")
    binding_response = await api.client.delete(f"{BINDING_PATH}/99999")

    assert account_response.status_code == 404
    assert (
        account_response.json()["detail"]["code"]
        == "ENTERPRISE_AUTH_ACCOUNT_NOT_FOUND"
    )
    assert binding_response.status_code == 404
    assert (
        binding_response.json()["detail"]["code"]
        == "ENTERPRISE_AUTH_BINDING_NOT_FOUND"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("PUT", f"{ACCOUNT_PATH}/99999", {"tenant_name": "missing"}),
        ("POST", f"{ACCOUNT_PATH}/99999/test", None),
    ],
)
async def test_account_graph_writes_keep_account_not_found_contract(
    api,
    method,
    path,
    payload,
):
    response = await api.client.request(method, path, json=payload)

    assert response.status_code == 404
    assert (
        response.json()["detail"]["code"]
        == "ENTERPRISE_AUTH_ACCOUNT_NOT_FOUND"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_url", f"https://example.com/{'x' * 240}"),
        ("tenant_ref", "x" * 129),
        ("tenant_name", "x" * 256),
        ("account", "x" * 129),
    ],
)
async def test_account_input_length_limits_return_422(api, field, value):
    payload = _account_payload(**{field: value})

    response = await api.client.post(ACCOUNT_PATH, json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url",
    [
        "https://exa mple.com/backend",
        "https://example.com/bad path",
        "https://example.com/bad\tpath",
        "https://example.com/bad\u0001path",
        f"https://{'a' * 64}.example.com/backend",
    ],
)
async def test_account_base_url_rejects_whitespace_control_and_invalid_idna(
    api,
    base_url,
):
    response = await api.client.post(
        ACCOUNT_PATH,
        json=_account_payload(base_url=base_url),
    )

    assert response.status_code == 422
    assert '"input"' not in response.text


@pytest.mark.asyncio
async def test_password_is_required_non_empty_and_priority_is_non_negative(api):
    missing_password = _account_payload()
    missing_password.pop("password")
    empty_password = _account_payload(password="   ")

    assert (
        await api.client.post(ACCOUNT_PATH, json=missing_password)
    ).status_code == 422
    assert (
        await api.client.post(ACCOUNT_PATH, json=empty_password)
    ).status_code == 422

    apaas = await _create_account(api)
    control = await _create_account(
        api,
        provider="control_plane",
        base_url="https://control.example.com",
        tenant_ref="enterprise-1",
        account="control-one",
    )
    negative_priority = await api.client.post(
        BINDING_PATH,
        json={
            "left_account_id": apaas["id"],
            "right_account_id": control["id"],
            "priority": -1,
            "enabled": True,
        },
    )
    assert negative_priority.status_code == 422


@pytest.mark.asyncio
async def test_reusable_lock_helpers_compile_in_account_then_canonical_binding_order():
    from app.services.enterprise_auth import (
        lock_enterprise_auth_accounts,
        lock_enterprise_auth_bindings,
    )

    statements = []

    class FakeScalars:
        def all(self):
            return []

    class FakeResult:
        def scalars(self):
            return FakeScalars()

    class CapturingSession:
        async def execute(self, statement):
            statements.append(statement)
            return FakeResult()

    session = CapturingSession()
    await lock_enterprise_auth_accounts(session, [3, 1, 2, 2])
    await lock_enterprise_auth_bindings(
        session,
        account_id=2,
        pairs=[(3, 1), (2, 1)],
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
    assert len(compiled) == 2
    assert "IN (1, 2, 3)" in compiled[0]
    assert "ORDER BY ENTERPRISE_AUTH_ACCOUNTS.ID ASC FOR UPDATE" in compiled[0]
    assert (
        "ORDER BY ENTERPRISE_AUTH_BINDINGS.LEFT_ACCOUNT_ID ASC, "
        "ENTERPRISE_AUTH_BINDINGS.RIGHT_ACCOUNT_ID ASC FOR UPDATE"
        in compiled[1]
    )
