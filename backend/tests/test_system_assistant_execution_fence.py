"""TASK-006 RED/GREEN tests for reserve, ActionRun authority and fencing."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.system_assistant_governance import ActionRun, ActionTicket
from app.system_assistant.action_execution import (
    CAS_CONFLICT_ERROR,
    ExecutionFence,
    ExecutionFenceRejected,
    execute_with_governance,
    assert_execution_fence,
    complete_action_run,
)
from app.system_assistant.action_store import confirm_ticket
from app.system_assistant.telemetry import GovernanceTelemetryRegistry


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _make_store(path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as conn:
        await conn.run_sync(ActionTicket.__table__.create)
        await conn.run_sync(ActionRun.__table__.create)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _seed(session_factory, *, ticket_status: str = "authorized", ticket_state_version: int = 1):
    async with session_factory() as session:
        ticket = ActionTicket(
            ticket_id="ticket-006",
            tenant_id=7,
            control_plane_tenant_id="cp-7",
            user_id=5,
            session_public_id="s" * 36,
            object_ref="application:projected-result",
            action_kind="project_result",
            args_digest="a" * 64,
            object_revision="revision-1",
            policy_revision=1,
            status=ticket_status,
            expires_at=_now() + timedelta(minutes=5),
            correlation_id="corr-006",
            state_version=ticket_state_version,
        )
        run = ActionRun(
            run_id="run-006",
            ticket_id=ticket.ticket_id,
            capability_id="system_assistant.project_result",
            action_kind=ticket.action_kind,
            object_ref=ticket.object_ref,
            status="authorized",
            args_digest=ticket.args_digest,
            object_revision=ticket.object_revision,
            policy_revision=ticket.policy_revision,
            correlation_id=ticket.correlation_id,
            audit_delivery_status="not_required",
        )
        session.add_all([ticket, run])
        await session.commit()


@pytest.mark.asyncio
async def test_confirm_ticket_uses_allowed_state_and_state_version_cas(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "confirm.sqlite3")
    try:
        await _seed(session_factory, ticket_status="issued", ticket_state_version=0)
        async with session_factory() as session:
            assert await confirm_ticket(session, "ticket-006", expected_state_version=0)
            await session.commit()
            assert not await confirm_ticket(session, "ticket-006", expected_state_version=0)
            await session.rollback()
            ticket = await session.get(ActionTicket, "ticket-006")
            assert ticket.status == "authorized"
            assert ticket.state_version == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_two_independent_sessions_start_one_owner_and_one_governed_handler(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "concurrent.sqlite3")
    try:
        await _seed(session_factory)
        barrier = asyncio.Barrier(2)
        calls: list[tuple[str, object]] = []

        async def governed(fence: ExecutionFence):
            calls.append(("governed", fence))
            return "new-result"

        async def legacy():
            calls.append(("legacy", None))
            return "old-result"

        async def worker():
            async with session_factory() as session:
                return await execute_with_governance(
                    session,
                    ticket_id="ticket-006",
                    run_id="run-006",
                    governed_handler=governed,
                    legacy_handler=legacy,
                    expected_ticket_state_version=1,
                    expected_run_state_version=0,
                    reserve_barrier=barrier,
                    lease_owner="worker",
                )

        results = await asyncio.gather(worker(), worker())
        assert sum(result.fence is not None for result in results) == 1
        assert sum(result.error == CAS_CONFLICT_ERROR for result in results) == 1
        assert [kind for kind, _ in calls] == ["governed"]

        async with session_factory() as session:
            ticket = await session.get(ActionTicket, "ticket-006")
            run = await session.get(ActionRun, "run-006")
            assert ticket.status == "reserved"
            assert ticket.state_version == 2
            assert run.status == "executing"
            assert run.execution_generation == 1
            assert run.state_version == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_confirmed_rollback_without_durable_row_calls_legacy_once(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "rollback.sqlite3")
    try:
        await _seed(session_factory)
        calls: list[str] = []

        async def governed(_fence):
            calls.append("governed")

        async def legacy():
            calls.append("legacy")
            return "legacy-result"

        async with session_factory() as session:
            async def fail_before_commit():
                raise RuntimeError("flush/commit fault")

            result = await execute_with_governance(
                session,
                ticket_id="ticket-006",
                run_id="run-006",
                governed_handler=governed,
                legacy_handler=legacy,
                expected_ticket_state_version=1,
                expected_run_state_version=0,
                commit_fault=fail_before_commit,
                independent_session_factory=session_factory,
            )

        assert result.legacy_called is True
        assert result.fence is None
        assert calls == ["legacy"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_commit_outcome_re_read_uses_governed_once_when_rows_are_durable(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "commit-unknown.sqlite3")
    try:
        await _seed(session_factory)
        calls: list[str] = []

        async def governed(fence):
            calls.append(f"governed:{fence.execution_generation}")
            return "new-result"

        async def legacy():
            calls.append("legacy")

        async with session_factory() as session:
            async def commit_after_durable_flush(current: AsyncSession):
                await current.commit()
                raise RuntimeError("commit acknowledgement lost")

            result = await execute_with_governance(
                session,
                ticket_id="ticket-006",
                run_id="run-006",
                governed_handler=governed,
                legacy_handler=legacy,
                expected_ticket_state_version=1,
                expected_run_state_version=0,
                commit_fault=commit_after_durable_flush,
                independent_session_factory=session_factory,
            )

        assert result.fence == ExecutionFence("run-006", 1)
        assert result.legacy_called is False
        assert calls == ["governed:1"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_commit_outcome_re_read_rejects_foreign_owner_same_generation(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "foreign-owner.sqlite3")
    try:
        await _seed(session_factory)
        calls: list[str] = []

        async def governed(_fence):
            calls.append("governed")

        async def legacy():
            calls.append("legacy")

        async with session_factory() as session:
            async def commit_then_foreign_owner(current: AsyncSession):
                await current.commit()
                async with session_factory() as foreign:
                    run = await foreign.get(ActionRun, "run-006")
                    run.lease_owner = "owner-B"
                    await foreign.commit()
                raise RuntimeError("commit acknowledgement lost")

            result = await execute_with_governance(
                session,
                ticket_id="ticket-006",
                run_id="run-006",
                governed_handler=governed,
                legacy_handler=legacy,
                expected_ticket_state_version=1,
                expected_run_state_version=0,
                lease_owner="owner-A",
                commit_fault=commit_then_foreign_owner,
                independent_session_factory=session_factory,
            )

        assert result.outcome == "commit_outcome_unknown"
        assert result.governed_called is False
        assert result.legacy_called is False
        assert calls == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_execution_fence_rejects_old_generation_expired_lease_and_takeover(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "fence.sqlite3")
    try:
        await _seed(session_factory)
        async with session_factory() as session:
            async with session.begin():
                ticket = await session.get(ActionTicket, "ticket-006")
                ticket.status = "reserved"
                ticket.state_version = 1
                run = await session.get(ActionRun, "run-006")
                run.status = "executing"
                run.execution_generation = 2
                run.lease_owner = "owner"
                run.lease_expires_at = _now() + timedelta(minutes=5)
                run.state_version = 1
        with pytest.raises(ExecutionFenceRejected):
            await assert_execution_fence(
                session_factory, ExecutionFence("run-006", 1), now=_now()
            )

        async with session_factory() as session:
            run = await session.get(ActionRun, "run-006")
            run.execution_generation = 1
            run.lease_expires_at = _now() - timedelta(seconds=1)
            await session.commit()
        with pytest.raises(ExecutionFenceRejected):
            await assert_execution_fence(
                session_factory, ExecutionFence("run-006", 1), now=_now()
            )

        async with session_factory() as session:
            run = await session.get(ActionRun, "run-006")
            run.lease_expires_at = _now() + timedelta(minutes=5)
            run.recovery_owner = "recovery-worker"
            await session.commit()
        with pytest.raises(ExecutionFenceRejected):
            await assert_execution_fence(
                session_factory, ExecutionFence("run-006", 1), now=_now()
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_missing_rows_cas_conflict_never_falls_back_to_legacy(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "missing-cas.sqlite3")
    try:
        calls: list[str] = []

        async def governed(_fence):
            calls.append("governed")

        async def legacy():
            calls.append("legacy")

        async with session_factory() as session:
            result = await execute_with_governance(
                session,
                ticket_id="missing-ticket",
                run_id="missing-run",
                governed_handler=governed,
                legacy_handler=legacy,
                expected_ticket_state_version=0,
                expected_run_state_version=0,
                independent_session_factory=session_factory,
            )

        assert result.outcome == "cas_conflict"
        assert result.governed_called is False
        assert result.legacy_called is False
        assert calls == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_immutable_ticket_and_run_contract_mismatch_rejects_without_handler(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "immutable-mismatch.sqlite3")
    try:
        await _seed(session_factory)
        async with session_factory() as session:
            run = await session.get(ActionRun, "run-006")
            run.args_digest = "b" * 64
            await session.commit()

        calls: list[str] = []

        async def governed(_fence):
            calls.append("governed")

        async def legacy():
            calls.append("legacy")

        async with session_factory() as session:
            result = await execute_with_governance(
                session,
                ticket_id="ticket-006",
                run_id="run-006",
                governed_handler=governed,
                legacy_handler=legacy,
                expected_ticket_state_version=1,
                expected_run_state_version=0,
                independent_session_factory=session_factory,
            )

        assert result.outcome == "cas_conflict"
        assert result.governed_called is False
        assert result.legacy_called is False
        assert calls == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_terminal_transition_is_generation_cas_and_counted_once(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "terminal.sqlite3")
    try:
        await _seed(session_factory)
        telemetry = GovernanceTelemetryRegistry()
        async with session_factory() as session:
            async with session.begin():
                ticket = await session.get(ActionTicket, "ticket-006")
                ticket.status = "reserved"
                ticket.state_version = 2
                run = await session.get(ActionRun, "run-006")
                run.status = "executing"
                run.execution_generation = 1
                run.lease_owner = "owner"
                run.lease_expires_at = _now() + timedelta(minutes=5)
                run.state_version = 1
            await complete_action_run(
                session,
                ExecutionFence("run-006", 1),
                status="succeeded",
                result_status="success",
                result_summary={"result_status": "success"},
                telemetry=telemetry,
            )
            await complete_action_run(
                session,
                ExecutionFence("run-006", 1),
                status="failed",
                error_code="late",
                telemetry=telemetry,
            )
        async with session_factory() as session:
            ticket = await session.get(ActionTicket, "ticket-006")
            run = await session.get(ActionRun, "run-006")
            assert (ticket.status, ticket.state_version) == ("consumed", 3)
            assert run.status == "succeeded"
        series = "system_assistant_run_transition_total[status=succeeded]"
        assert sum(
            value
            for name, value in telemetry.snapshot().items()
            if name.startswith("system_assistant_run_transition_total{")
            and 'capability_id="system_assistant.project_result"' in name
            and 'status="succeeded"' in name
        ) == 1
    finally:
        await engine.dispose()
