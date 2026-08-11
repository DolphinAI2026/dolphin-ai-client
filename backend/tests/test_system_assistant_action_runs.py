"""TASK-006 ActionRun authority and recovery lease tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.system_assistant_governance import ActionRun
from app.system_assistant.action_store import claim_recovery, reserve_ticket_and_run
from tests.test_system_assistant_execution_fence import _make_store, _seed


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_atomic_start_preserves_immutable_run_digest_and_revision(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "run-start.sqlite3")
    try:
        await _seed(session_factory)
        async with session_factory() as session:
            reservation = await reserve_ticket_and_run(
                session,
                ticket_id="ticket-006",
                run_id="run-006",
                expected_ticket_state_version=1,
                expected_run_state_version=0,
                lease_owner="runner-a",
                now=_now(),
                args_digest="a" * 64,
                object_revision="revision-1",
                correlation_id="corr-006",
            )
            await session.commit()
            assert reservation.execution_generation == 1
            run = await session.get(ActionRun, "run-006")
            assert (run.args_digest, run.object_revision, run.correlation_id) == (
                "a" * 64,
                "revision-1",
                "corr-006",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_recovery_takeover_requires_expired_lease_and_bumps_state_version(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "run-recovery.sqlite3")
    try:
        await _seed(session_factory)
        async with session_factory() as session:
            run = await session.get(ActionRun, "run-006")
            run.status = "executing"
            run.lease_owner = "runner-a"
            run.lease_expires_at = _now() - timedelta(seconds=1)
            await session.commit()
            assert await claim_recovery(
                session,
                run_id="run-006",
                owner="recovery-a",
                now=_now(),
                expected_state_version=0,
            )
            await session.commit()
            run = await session.get(ActionRun, "run-006")
            assert (run.recovery_owner, run.state_version) == ("recovery-a", 1)
            assert not await claim_recovery(
                session,
                run_id="run-006",
                owner="recovery-b",
                now=_now(),
                expected_state_version=1,
            )
            await session.rollback()
    finally:
        await engine.dispose()
