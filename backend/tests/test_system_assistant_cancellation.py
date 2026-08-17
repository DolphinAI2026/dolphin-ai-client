"""TASK-007 cancellation generation and repeat-cancel contracts."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.models.system_assistant_governance import ActionRun
from app.system_assistant.action_execution import execute_with_governance
from app.system_assistant.session_lifecycle import cancel_action_run
from tests.test_system_assistant_session_deletion import _make_store, _seed


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_cancel_commits_unknown_outcome_and_invalidates_old_generation(tmp_path):
    engine, factory = await _make_store(tmp_path / "cancel.sqlite3")
    try:
        await _seed(factory)
        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            run.status = "executing"
            run.execution_generation = 1
            run.state_version = 1
            run.lease_owner = "governed-handler"
            run.lease_expires_at = _now() + timedelta(minutes=5)
            await db.commit()

        async with factory() as db:
            result = await cancel_action_run(
                db,
                "run-007",
                expected_generation=1,
                now=_now(),
            )
            assert result.changed is True
            assert result.status == "outcome_unknown"
            assert result.execution_generation == 2

        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            assert run.status == "outcome_unknown"
            assert run.execution_generation == 2
            assert run.cancel_requested_at is not None
            assert run.lease_owner is None
            assert run.lease_expires_at is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_cancel_is_noop_and_does_not_advance_generation(tmp_path):
    engine, factory = await _make_store(tmp_path / "cancel-repeat.sqlite3")
    try:
        await _seed(factory)
        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            run.status = "executing"
            run.execution_generation = 3
            run.state_version = 7
            run.lease_owner = "governed-handler"
            run.lease_expires_at = _now() + timedelta(minutes=5)
            await db.commit()

        async with factory() as db:
            first = await cancel_action_run(db, "run-007", expected_generation=3, now=_now())
            second = await cancel_action_run(db, "run-007", expected_generation=3, now=_now())
            assert first.changed is True
            assert second.changed is False
            assert second.status == "outcome_unknown"

        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            assert (run.execution_generation, run.state_version) == (4, 8)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancel_first_fences_authorized_reserve_in_independent_transaction_barrier(
    tmp_path,
):
    engine, factory = await _make_store(tmp_path / "cancel-reserve-barrier.sqlite3")
    reserve_ready = asyncio.Event()
    release_reserve = asyncio.Event()
    calls: list[str] = []
    try:
        await _seed(factory)

        async def reserve_barrier():
            reserve_ready.set()
            await release_reserve.wait()

        async def governed(_fence):
            calls.append("governed")

        async def legacy():
            calls.append("legacy")

        async with factory() as execute_db:
            execute_task = asyncio.create_task(
                execute_with_governance(
                    execute_db,
                    ticket_id="ticket-007",
                    run_id="run-007",
                    governed_handler=governed,
                    legacy_handler=legacy,
                    expected_ticket_state_version=1,
                    expected_run_state_version=0,
                    lease_owner="late-executor",
                    args_digest="a" * 64,
                    object_revision="revision-1",
                    correlation_id="corr-007",
                    reserve_barrier=reserve_barrier,
                )
            )
            await reserve_ready.wait()
            async with factory() as cancel_db:
                result = await cancel_action_run(
                    cancel_db,
                    "run-007",
                    expected_generation=0,
                    now=_now(),
                )
                assert result.changed is True
                assert result.status == "aborted"
                assert result.execution_generation == 1
            release_reserve.set()
            execute_result = await execute_task

        assert execute_result.outcome == "cas_conflict"
        assert calls == []
        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            assert (run.status, run.execution_generation, run.state_version) == (
                "aborted",
                1,
                1,
            )
    finally:
        release_reserve.set()
        await engine.dispose()
