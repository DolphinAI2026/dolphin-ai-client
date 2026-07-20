import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import yaml
from sqlalchemy.exc import DBAPIError

from app.models.tenant import Tenant
from app import tenant_public_id
from app.tenant_public_id import historical_tenant_public_id, new_tenant_public_id

try:
    from pymysql.err import OperationalError as MySqlOperationalError
except ImportError:
    class MySqlOperationalError(Exception):
        pass


def test_new_tenant_public_id_is_uuid4():
    value = new_tenant_public_id()

    parsed = UUID(value)

    assert parsed.version == 4
    assert value == str(parsed)


def test_historical_tenant_public_id_is_stable_uuid5():
    assert historical_tenant_public_id(42) == historical_tenant_public_id(42)
    assert UUID(historical_tenant_public_id(42)).version == 5


def test_tenant_public_id_column_is_nullable_unique_indexed_uuid_default():
    column = Tenant.__table__.c.public_id

    assert column.type.length == 36
    assert column.nullable is True
    assert column.unique is True
    assert column.index is True
    assert UUID(column.default.arg(None)).version == 4


def test_cli_formats_all_strict_reconciliation_ids_stably():
    result = tenant_public_id.TenantPublicIdReconciliation(
        scanned_count=5,
        filled_count=1,
        null_count=1,
        null_tenant_ids=(2,),
        conflict_tenant_ids=(7, 11),
        invalid_tenant_ids=(4, 9),
    )

    assert tenant_public_id._format_result(result) == (
        "scanned_count=5 filled_count=1 null_count=1 "
        "null_tenant_ids=2 conflict_tenant_ids=7,11 invalid_tenant_ids=4,9"
    )


def test_cli_prints_strict_reconciliation_ids_without_traceback(monkeypatch, capsys):
    result = tenant_public_id.TenantPublicIdReconciliation(
        scanned_count=2,
        filled_count=0,
        null_count=0,
        null_tenant_ids=(),
        conflict_tenant_ids=(7, 11),
        invalid_tenant_ids=(4, 9),
    )

    async def run_reconciliation(_verify_only_after_write):
        return result

    monkeypatch.setattr(tenant_public_id, "_run_cli_reconciliation", run_reconciliation)
    monkeypatch.setattr(sys, "argv", ["tenant_public_id.py", "reconcile"])

    with pytest.raises(SystemExit) as exc_info:
        tenant_public_id.main()

    assert exc_info.value.code == 1
    assert capsys.readouterr().out == (
        "scanned_count=2 filled_count=0 null_count=0 "
        "null_tenant_ids= conflict_tenant_ids=7,11 invalid_tenant_ids=4,9\n"
    )


def test_dialect_runner_selects_reachable_host_for_local_docker_and_dind():
    runner = Path(__file__).parent / "integration" / "run_tenant_public_id_dialects.sh"
    command = (
        'source "$1"; '
        'DOCKER_HOST=""; '
        'printf "local=%s|%s\\n" "$(database_host)" "$(port_bind_host)"; '
        'DOCKER_HOST="tcp://docker:2375"; '
        'printf "dind=%s|%s\\n" "$(database_host)" "$(port_bind_host)"'
    )

    result = subprocess.run(
        ["bash", "-c", command, "bash", str(runner)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "local=127.0.0.1|127.0.0.1\ndind=docker|0.0.0.0\n"


@pytest.mark.parametrize(
    ("dialect_name", "error", "column_duplicate", "index_duplicate"),
    [
        (
            "postgresql",
            SimpleNamespace(orig=SimpleNamespace(sqlstate="42701")),
            True,
            False,
        ),
        (
            "postgresql",
            SimpleNamespace(orig=SimpleNamespace(pgcode="42P07")),
            False,
            True,
        ),
        (
            "sqlite",
            RuntimeError("duplicate column name: public_id"),
            True,
            False,
        ),
        (
            "sqlite",
            RuntimeError("index ix_tenants_public_id already exists"),
            False,
            True,
        ),
    ],
)
def test_duplicate_ddl_errors_use_dialect_driver_codes_before_sqlite_fallback(
    dialect_name,
    error,
    column_duplicate,
    index_duplicate,
):
    assert (
        tenant_public_id._is_duplicate_column_error(dialect_name, error)
        is column_duplicate
    )
    assert (
        tenant_public_id._is_duplicate_index_error(dialect_name, error)
        is index_duplicate
    )


@pytest.mark.parametrize(
    ("code", "column_duplicate", "index_duplicate"),
    [
        (1060, True, False),
        ("1060", True, False),
        (1061, False, True),
        ("1061", False, True),
    ],
)
def test_mysql_duplicate_ddl_errors_read_dbapi_args_through_sqlalchemy_orig(
    code,
    column_duplicate,
    index_duplicate,
):
    error = DBAPIError.instance(
        "ALTER TABLE tenants ADD COLUMN public_id VARCHAR(36)",
        {},
        MySqlOperationalError(code, "driver message"),
        Exception,
    )

    assert (
        tenant_public_id._is_duplicate_column_error("mysql", error)
        is column_duplicate
    )
    assert (
        tenant_public_id._is_duplicate_index_error("mysql", error)
        is index_duplicate
    )


@pytest.mark.parametrize(
    "code",
    [
        1060.0,
        " 1060",
        "1060 ",
        "1060x",
        b"1060",
        None,
    ],
)
def test_mysql_duplicate_ddl_errors_reject_non_integer_or_non_numeric_args(code):
    error = DBAPIError.instance(
        "ALTER TABLE tenants ADD COLUMN public_id VARCHAR(36)",
        {},
        MySqlOperationalError(code, "driver message"),
        Exception,
    )

    assert not tenant_public_id._is_duplicate_column_error("mysql", error)
    assert not tenant_public_id._is_duplicate_index_error("mysql", error)


def test_mysql_duplicate_ddl_errors_keep_errno_compatibility():
    error = SimpleNamespace(orig=SimpleNamespace(errno=1060))

    assert tenant_public_id._is_duplicate_column_error("mysql", error)
    assert not tenant_public_id._is_duplicate_index_error("mysql", error)


def test_duplicate_ddl_message_fallback_is_limited_to_sqlite():
    error = RuntimeError("duplicate column name: public_id")

    assert tenant_public_id._is_duplicate_column_error("sqlite", error)
    assert not tenant_public_id._is_duplicate_column_error("postgresql", error)
    assert not tenant_public_id._is_duplicate_column_error("mysql", error)


def test_dialect_runner_job_uses_standard_gitlab_yaml_and_preserves_dind_networking():
    config_path = Path(__file__).parents[2] / ".gitlab-ci.yml"
    config = yaml.safe_load(config_path.read_text())
    job = config["verify_tenant_public_id_dialects"]

    assert "privileged" not in job
    assert job["services"] == [
        {
            "name": "$BUILDER_DOCKER_DIND_IMAGE",
            "alias": "docker",
        },
    ]
    assert job["variables"]["DOCKER_HOST"] == "tcp://docker:2375"
    assert job["variables"]["DOCKER_TLS_CERTDIR"] == ""
