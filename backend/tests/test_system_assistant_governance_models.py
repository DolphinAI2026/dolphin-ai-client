"""B0 governance persistence models."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import BigInteger, DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.system_assistant_governance import ActionRun, ActionTicket


def _column_contract(table, expected):
    assert set(table.columns.keys()) == {name for name, *_ in expected}
    for name, column_type, length, nullable in expected:
        column = table.c[name]
        actual_type = getattr(column.type, "impl", column.type)
        assert isinstance(actual_type, column_type), name
        if length is not None:
            assert column.type.length == length, name
        assert column.nullable is nullable, name


def _index_contract(table):
    return {
        (tuple(column.name for column in index.columns), index.unique)
        for index in table.indexes
    }


def test_ticket_model_matches_frozen_persistence_contract():
    table = ActionTicket.__table__
    _column_contract(table, (
        ("ticket_id", String, 36, False),
        ("tenant_id", BigInteger, None, False),
        ("control_plane_tenant_id", String, 80, False),
        ("user_id", BigInteger, None, False),
        ("session_id", Integer, None, True),
        ("session_public_id", String, 36, False),
        ("object_ref", String, 500, False),
        ("action_kind", String, 120, False),
        ("args_digest", String, 64, False),
        ("object_revision", String, 160, False),
        ("policy_revision", BigInteger, None, False),
        ("status", String, 20, False),
        ("expires_at", DateTime, None, False),
        ("correlation_id", String, 36, False),
        ("state_version", BigInteger, None, False),
        ("created_at", DateTime, None, False),
        ("updated_at", DateTime, None, False),
    ))
    assert tuple(table.primary_key.columns.keys()) == ("ticket_id",)
    assert table.c.state_version.default.arg == 0
    assert _index_contract(table) == {
        (("tenant_id", "user_id", "status", "expires_at"), False),
        (("session_public_id", "object_ref", "status"), False),
    }
    unique_constraints = [
        constraint for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
    ]
    assert [tuple(constraint.columns.keys()) for constraint in unique_constraints] == [
        ("ticket_id", "tenant_id")
    ]
    session_fk = next(iter(table.c.session_id.foreign_keys))
    assert session_fk.target_fullname == "ai_chat_sessions.id"
    assert session_fk.ondelete == "SET NULL"
    ticket_check = next(
        constraint for constraint in table.constraints if constraint.name == "ck_system_assistant_action_tickets_status"
    )
    assert "issued" in str(ticket_check.sqltext)
    assert "revoked" in str(ticket_check.sqltext)


def test_run_model_matches_frozen_persistence_contract():
    table = ActionRun.__table__
    _column_contract(table, (
        ("run_id", String, 36, False),
        ("ticket_id", String, 36, True),
        ("tool_call_id", Integer, None, True),
        ("capability_id", String, 120, False),
        ("action_kind", String, 120, False),
        ("object_ref", String, 500, False),
        ("status", String, 32, False),
        ("args_digest", String, 64, False),
        ("object_revision", String, 160, False),
        ("policy_revision", BigInteger, None, False),
        ("execution_generation", BigInteger, None, False),
        ("lease_owner", String, 120, True),
        ("lease_expires_at", DateTime, None, True),
        ("cancel_requested_at", DateTime, None, True),
        ("cancel_acknowledged_at", DateTime, None, True),
        ("recovery_owner", String, 120, True),
        ("recovery_lease_expires_at", DateTime, None, True),
        ("base_state", JSON, None, False),
        ("change_manifest", JSON, None, False),
        ("result_summary", JSON, None, False),
        ("result_status", String, 32, True),
        ("error_code", String, 120, True),
        ("correlation_id", String, 36, False),
        ("audit_delivery_status", String, 20, False),
        ("started_at", DateTime, None, True),
        ("finished_at", DateTime, None, True),
        ("state_version", BigInteger, None, False),
        ("created_at", DateTime, None, False),
        ("updated_at", DateTime, None, False),
    ))
    assert tuple(table.primary_key.columns.keys()) == ("run_id",)
    assert table.c.execution_generation.default.arg == 0
    assert table.c.state_version.default.arg == 0
    assert table.c.base_state.default.arg(None) == {}
    assert table.c.change_manifest.default.arg(None) == {}
    assert table.c.result_summary.default.arg(None) == {}
    assert _index_contract(table) == {
        (("status", "updated_at"), False),
        (("ticket_id",), False),
        (("correlation_id",), False),
        (("object_ref", "created_at"), False),
        (("recovery_lease_expires_at", "status"), False),
    }
    foreign_keys = {foreign_key.target_fullname: foreign_key for foreign_key in table.foreign_keys}
    assert foreign_keys["system_assistant_action_tickets.ticket_id"].ondelete == "SET NULL"
    assert foreign_keys["ai_chat_tool_calls.id"].ondelete == "SET NULL"
    run_check = next(
        constraint for constraint in table.constraints if constraint.name == "ck_system_assistant_action_runs_status"
    )
    assert "partially_failed" in str(run_check.sqltext)
    assert "outcome_unknown" in str(run_check.sqltext)
    audit_check = next(
        constraint for constraint in table.constraints if constraint.name == "ck_system_assistant_action_runs_audit_delivery_status"
    )
    assert "not_required" in str(audit_check.sqltext)
    assert "delivered" in str(audit_check.sqltext)


@pytest.mark.asyncio
async def test_action_ticket_and_run_persist_audit_references_only(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'governance.sqlite3'}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(ActionTicket.__table__.create)
            await conn.run_sync(ActionRun.__table__.create)

        async with session_factory() as session:
            ticket = ActionTicket(
                tenant_id=7,
                control_plane_tenant_id="control-tenant-7",
                user_id=5,
                session_public_id="a" * 36,
                object_ref="application:projected-result",
                action_kind="project_result",
                args_digest="b" * 64,
                object_revision="revision-1",
                policy_revision=1,
                status="issued",
                expires_at=datetime.now(UTC).replace(tzinfo=None),
                correlation_id="corr-001",
            )
            session.add(ticket)
            await session.flush()
            run = ActionRun(
                ticket_id=ticket.ticket_id,
                capability_id="project.result",
                action_kind="project_result",
                object_ref="application:projected-result",
                status="prepared",
                args_digest="b" * 64,
                object_revision="revision-1",
                policy_revision=1,
                correlation_id="corr-001",
                audit_delivery_status="not_required",
            )
            session.add(run)
            await session.commit()

            assert ticket.ticket_id
            assert run.run_id
            assert run.ticket_id == ticket.ticket_id
            now = datetime.now(UTC).replace(tzinfo=None)
            assert ticket.created_at <= now
            assert run.created_at <= now
            assert run.base_state == {}
            assert run.change_manifest == {}
            assert run.result_summary == {}
    finally:
        await engine.dispose()


@pytest.mark.parametrize("field_name, value", (
    ("base_state", {"secret": "secret"}),
    ("change_manifest", {"access_token": "secret"}),
    ("result_summary", {"api-key": "secret"}),
    ("base_state", {"references": [{"authorization": "Bearer secret"}]}),
    ("change_manifest", {"changes": [{"environment": {"prod": "secret"}}]}),
    ("result_summary", {"summary": "postgresql://user:password@host/db"}),
    ("base_state", {"references": [{"tool_args": {"x": "complete args"}}]}),
))
def test_versioned_json_maps_reject_sensitive_key_variants_and_nested_values(field_name, value):
    json_type = ActionRun.__table__.c[field_name].type
    with pytest.raises(ValueError, match="sensitive"):
        json_type.process_bind_param(value, None)


@pytest.mark.parametrize("field_name, value", (
    ("base_state", {"schema_version": "v1", "object_ref": "application:result"}),
    ("change_manifest", {"delivery_status": "pending", "retry_count": 1}),
    ("result_summary", {"result_status": "succeeded", "error_code": "none"}),
))
def test_versioned_json_maps_accept_allowed_snake_case_keys(field_name, value):
    json_type = ActionRun.__table__.c[field_name].type
    assert json_type.process_bind_param(value, None) == value


def test_governance_tables_define_ticket_fk_set_null_and_lookup_indexes():
    ticket_fk = next(
        foreign_key
        for foreign_key in ActionRun.__table__.foreign_keys
        if foreign_key.target_fullname == "system_assistant_action_tickets.ticket_id"
    )
    assert ticket_fk.ondelete == "SET NULL"

    indexes = {index.name for index in ActionRun.__table__.indexes}
    assert "ix_system_assistant_action_runs_ticket_id" in indexes
    assert "ix_system_assistant_action_runs_correlation_id" in indexes
