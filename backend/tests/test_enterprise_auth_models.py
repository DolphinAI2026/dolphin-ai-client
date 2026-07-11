from importlib import import_module
from types import SimpleNamespace

import pytest
from sqlalchemy import (
    CheckConstraint,
    Integer,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database import Base


def _enterprise_auth_models():
    module = import_module("app.models.enterprise_auth")
    return module.EnterpriseAuthAccount, module.EnterpriseAuthBinding


@pytest.fixture
def sqlite_auth_db():
    models = import_module("app.models")
    account_model, binding_model = _enterprise_auth_models()
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            models.User.__table__,
            account_model.__table__,
            binding_model.__table__,
        ],
    )

    with Session(engine) as session:
        user = models.User(username="owner", hashed_password="hash")
        session.add(user)
        session.commit()
        yield session, user.id, account_model, binding_model

    engine.dispose()


def _create_account(
    session,
    account_model,
    user_id,
    *,
    account,
    provider="apaas",
    status="unverified",
):
    row = account_model(
        provider=provider,
        base_url="https://example.test",
        tenant_ref="tenant-1",
        account=account,
        status=status,
        created_by=user_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_auth_account_binding_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AUTH_ACCOUNT_BINDING_ENABLED", raising=False)

    settings = Settings(_env_file=None, jwt_secret_key="test-secret")

    assert settings.auth_account_binding_enabled is False


def test_enterprise_auth_models_are_exported_and_registered():
    models = import_module("app.models")
    account_model, binding_model = _enterprise_auth_models()

    assert models.EnterpriseAuthAccount is account_model
    assert models.EnterpriseAuthBinding is binding_model
    assert Base.metadata.tables["enterprise_auth_accounts"] is account_model.__table__
    assert Base.metadata.tables["enterprise_auth_bindings"] is binding_model.__table__


def test_enterprise_auth_account_fields_and_defaults():
    account_model, _ = _enterprise_auth_models()
    table = account_model.__table__

    assert set(table.columns.keys()) == {
        "id",
        "provider",
        "base_url",
        "tenant_ref",
        "tenant_name",
        "account",
        "password_enc",
        "access_token_enc",
        "refresh_token_enc",
        "token_expires_at",
        "status",
        "auth_generation",
        "last_verified_at",
        "last_error",
        "created_by",
        "created_at",
        "updated_at",
    }
    for column_name in ("provider", "base_url", "tenant_ref", "account"):
        assert table.c[column_name].nullable is False
    assert table.c.status.default.arg == "unverified"
    generation = table.c.auth_generation
    assert isinstance(generation.type, Integer)
    assert generation.nullable is False
    assert generation.default.arg == 0
    assert str(generation.server_default.arg) == "0"


@pytest.mark.asyncio
async def test_enterprise_auth_generation_migration_upgrades_legacy_sqlite():
    database = import_module("app.database")
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE enterprise_auth_accounts "
                "(id INTEGER PRIMARY KEY, account VARCHAR(128) NOT NULL)"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO enterprise_auth_accounts (id, account) "
                "VALUES (1, 'legacy-account')"
            )
        )

        await database._ensure_enterprise_auth_account_auth_generation(
            connection,
            database.inspect,
        )
        await database._ensure_enterprise_auth_account_auth_generation(
            connection,
            database.inspect,
        )

        columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]: column
                for column in database.inspect(sync_connection).get_columns(
                    "enterprise_auth_accounts"
                )
            }
        )
        generation = (
            await connection.execute(
                text(
                    "SELECT auth_generation "
                    "FROM enterprise_auth_accounts WHERE id = 1"
                )
            )
        ).scalar_one()

    await engine.dispose()

    assert columns["auth_generation"]["nullable"] is False
    assert generation == 0


@pytest.mark.asyncio
async def test_enterprise_auth_generation_migration_uses_mysql_compatible_ddl():
    database = import_module("app.database")

    class MySQLConnection:
        dialect = SimpleNamespace(name="mysql")

        def __init__(self):
            self.statements = []

        async def run_sync(self, _callable):
            return {"id", "provider"}

        async def execute(self, statement):
            self.statements.append(str(statement))

    connection = MySQLConnection()

    await database._ensure_enterprise_auth_account_auth_generation(
        connection,
        database.inspect,
    )

    assert connection.statements == [
        "ALTER TABLE enterprise_auth_accounts "
        "ADD COLUMN auth_generation INTEGER NOT NULL DEFAULT 0"
    ]


def test_enterprise_auth_account_unique_constraint():
    account_model, _ = _enterprise_auth_models()
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in account_model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("provider", "base_url", "tenant_ref", "account") in unique_columns


def test_enterprise_auth_account_identity_index_is_mysql_safe():
    account_model, _ = _enterprise_auth_models()
    identity_columns = ("provider", "base_url", "tenant_ref", "account")
    total_chars = sum(
        account_model.__table__.c[column_name].type.length
        for column_name in identity_columns
    )

    assert total_chars * 4 <= 3072


def test_enterprise_auth_binding_fields_defaults_and_constraints():
    _, binding_model = _enterprise_auth_models()
    table = binding_model.__table__

    assert set(table.columns.keys()) == {
        "id",
        "left_account_id",
        "right_account_id",
        "priority",
        "enabled",
        "created_by",
        "created_at",
        "updated_at",
    }
    assert table.c.priority.default.arg == 100
    assert table.c.enabled.default.arg is True

    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("left_account_id", "right_account_id") in unique_columns

    checks = {
        str(constraint.sqltext).replace(" ", "")
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "left_account_id<right_account_id" in checks

    for column_name in ("left_account_id", "right_account_id"):
        foreign_key = next(iter(table.c[column_name].foreign_keys))
        assert foreign_key.target_fullname == "enterprise_auth_accounts.id"
        assert foreign_key.ondelete == "CASCADE"


def test_sqlite_rejects_noncanonical_reverse_binding(sqlite_auth_db):
    session, user_id, account_model, binding_model = sqlite_auth_db
    left = _create_account(session, account_model, user_id, account="left")
    right = _create_account(session, account_model, user_id, account="right")
    session.add(
        binding_model(
            left_account_id=left.id,
            right_account_id=right.id,
            created_by=user_id,
        )
    )
    session.commit()

    with pytest.raises(IntegrityError):
        session.add(
            binding_model(
                left_account_id=right.id,
                right_account_id=left.id,
                created_by=user_id,
            )
        )
        session.commit()
    session.rollback()


def test_sqlite_rejects_invalid_enterprise_auth_provider(sqlite_auth_db):
    session, user_id, account_model, _ = sqlite_auth_db

    with pytest.raises(IntegrityError):
        _create_account(
            session,
            account_model,
            user_id,
            account="invalid-provider",
            provider="unsupported",
        )
    session.rollback()


def test_sqlite_rejects_invalid_enterprise_auth_status(sqlite_auth_db):
    session, user_id, account_model, _ = sqlite_auth_db

    with pytest.raises(IntegrityError):
        _create_account(
            session,
            account_model,
            user_id,
            account="invalid-status",
            status="pending",
        )
    session.rollback()
