from importlib import import_module

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.config import Settings
from app.database import Base


def _enterprise_auth_models():
    module = import_module("app.models.enterprise_auth")
    return module.EnterpriseAuthAccount, module.EnterpriseAuthBinding


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
        "last_verified_at",
        "last_error",
        "created_by",
        "created_at",
        "updated_at",
    }
    for column_name in ("provider", "base_url", "tenant_ref", "account"):
        assert table.c[column_name].nullable is False
    assert table.c.status.default.arg == "unverified"


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
    assert "left_account_id!=right_account_id" in checks

    for column_name in ("left_account_id", "right_account_id"):
        foreign_key = next(iter(table.c[column_name].foreign_keys))
        assert foreign_key.target_fullname == "enterprise_auth_accounts.id"
        assert foreign_key.ondelete == "CASCADE"
