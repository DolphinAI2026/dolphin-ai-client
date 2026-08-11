"""B0 governance persistence models."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.system_assistant_governance import ActionRun, ActionTicket


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
                action_type="project_result",
                correlation_id="corr-001",
                summary="publish projected result",
                metadata_json={"source": "system-assistant"},
            )
            session.add(ticket)
            await session.flush()
            run = ActionRun(
                ticket_id=ticket.id,
                tenant_id=7,
                correlation_id="corr-001",
                status="queued",
                snapshot_digest="a" * 64,
                metadata_json={"attempt": 1},
            )
            session.add(run)
            await session.commit()

            assert ticket.id
            assert run.id
            assert run.ticket_id == ticket.id
            now = datetime.now(UTC).replace(tzinfo=None)
            assert ticket.created_at <= now
            assert run.created_at <= now
            assert run.result_status is None
            assert run.error_code is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_governance_json_rejects_sensitive_payloads(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sensitive.sqlite3'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(ActionTicket.__table__.create)

        async with session_factory() as session:
            session.add(ActionTicket(
                tenant_id=7,
                action_type="reserve_run",
                correlation_id="corr-sensitive",
                summary="do not retain credentials",
                metadata_json={"token": "secret"},
            ))
            with pytest.raises(StatementError, match="sensitive"):
                await session.flush()
    finally:
        await engine.dispose()


def test_governance_tables_define_ticket_fk_set_null_and_lookup_indexes():
    ticket_fk = next(
        foreign_key
        for foreign_key in ActionRun.__table__.foreign_key_constraints
        if foreign_key.name == "fk_system_assistant_action_runs_ticket_id"
    )
    assert ticket_fk.ondelete == "SET NULL"

    indexes = {index.name for index in ActionRun.__table__.indexes}
    assert "ix_system_assistant_action_runs_ticket_created" in indexes
    assert "ix_system_assistant_action_runs_tenant_correlation" in indexes
