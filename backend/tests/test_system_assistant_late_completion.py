"""TASK-007 late completion CAS and bounded diagnostic contract."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.models.system_assistant_governance import ActionRun
from app.system_assistant.action_execution import (
    ExecutionFence,
    complete_action_run as action_execution_complete_action_run,
)
from app.system_assistant.session_lifecycle import cancel_action_run, complete_action_run
from app.system_assistant.telemetry import GovernanceTelemetryRegistry
from tests.test_system_assistant_session_deletion import _make_store, _seed


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _seed_executing(factory, *, generation: int = 1) -> None:
    await _seed(factory)
    async with factory() as db:
        run = await db.get(ActionRun, "run-007")
        run.status = "executing"
        run.execution_generation = generation
        run.state_version = generation
        run.lease_owner = "governed-handler"
        run.lease_expires_at = _now() + timedelta(minutes=5)
        await db.commit()


@pytest.mark.asyncio
async def test_cancel_late_complete_barrier_keeps_unknown_generation_without_mutating_terminal_row(tmp_path):
    engine, factory = await _make_store(tmp_path / "late-completion.sqlite3")
    telemetry = GovernanceTelemetryRegistry()
    try:
        await _seed_executing(factory)
        async with factory() as cancel_db:
            await cancel_action_run(cancel_db, "run-007", expected_generation=1, now=_now())

        async with factory() as complete_db:
            first = await complete_action_run(
                complete_db,
                ExecutionFence("run-007", 1),
                status="succeeded",
                telemetry=telemetry,
                now=_now(),
            )
            second = await complete_action_run(
                complete_db,
                ExecutionFence("run-007", 1),
                status="failed",
                telemetry=telemetry,
                now=_now(),
            )
            assert first is False
            assert second is False

        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            assert (run.status, run.execution_generation) == ("outcome_unknown", 2)
            assert run.error_code is None
            assert run.state_version == 2
        ignored = 'system_assistant_late_completion_total{result="ignored"}'
        assert telemetry.snapshot().get(ignored, 0) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_late_completion_cannot_overwrite_an_existing_terminal_state(tmp_path):
    engine, factory = await _make_store(tmp_path / "late-terminal.sqlite3")
    try:
        await _seed_executing(factory)
        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            run.status = "succeeded"
            run.execution_generation = 2
            run.result_status = "success"
            run.finished_at = _now()
            await db.commit()

        async with factory() as db:
            assert not await complete_action_run(
                db,
                ExecutionFence("run-007", 1),
                status="failed",
                now=_now(),
            )
            run = await db.get(ActionRun, "run-007")
            assert run.status == "succeeded"
            assert run.result_status == "success"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal_status",
    [
        "succeeded",
        "failed",
        "partially_failed",
        "recovered",
        "recovery_blocked",
        "outcome_unknown",
        "aborted",
    ],
)
async def test_late_completion_preserves_terminal_error_and_state_version(
    tmp_path, terminal_status: str
):
    engine, factory = await _make_store(tmp_path / f"late-{terminal_status}.sqlite3")
    telemetry = GovernanceTelemetryRegistry()
    try:
        await _seed_executing(factory)
        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            run.status = terminal_status
            run.execution_generation = 2
            run.state_version = 9
            run.error_code = "ORIGINAL_TERMINAL_ERROR"
            run.result_status = "original"
            run.finished_at = _now()
            await db.commit()

        async with factory() as db:
            assert not await complete_action_run(
                db,
                ExecutionFence("run-007", 1),
                status="failed",
                error_code="STALE_ERROR",
                telemetry=telemetry,
                now=_now(),
            )

        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            assert (run.status, run.error_code, run.state_version) == (
                terminal_status,
                "ORIGINAL_TERMINAL_ERROR",
                9,
            )
        ignored = 'system_assistant_late_completion_total{result="ignored"}'
        assert telemetry.snapshot().get(ignored, 0) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_two_independent_stale_completions_atomically_mark_and_count_once(tmp_path):
    engine, factory = await _make_store(tmp_path / "late-two-connections.sqlite3")
    telemetry = GovernanceTelemetryRegistry()
    ready = asyncio.Barrier(2)
    try:
        await _seed_executing(factory, generation=2)

        async def stale_completion():
            async with factory() as db:
                await ready.wait()
                return await complete_action_run(
                    db,
                    ExecutionFence("run-007", 1),
                    status="succeeded",
                    telemetry=telemetry,
                    now=_now(),
                )

        first, second = await asyncio.gather(stale_completion(), stale_completion())
        assert (first, second) == (False, False)

        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            assert (run.status, run.error_code, run.state_version) == (
                "executing",
                "LATE_COMPLETION_IGNORED",
                3,
            )
        ignored = 'system_assistant_late_completion_total{result="ignored"}'
        assert telemetry.snapshot()[ignored] == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_action_execution_completion_entry_uses_lifecycle_single_count(tmp_path):
    engine, factory = await _make_store(tmp_path / "late-canonical-entry.sqlite3")
    telemetry = GovernanceTelemetryRegistry()
    try:
        await _seed_executing(factory, generation=2)
        async with factory() as db:
            first = await action_execution_complete_action_run(
                db,
                ExecutionFence("run-007", 1),
                status="failed",
                telemetry=telemetry,
                now=_now(),
            )
        async with factory() as db:
            second = await action_execution_complete_action_run(
                db,
                ExecutionFence("run-007", 1),
                status="failed",
                telemetry=telemetry,
                now=_now(),
            )
        assert (first, second) == (False, False)

        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            assert (run.status, run.error_code, run.state_version) == (
                "executing",
                "LATE_COMPLETION_IGNORED",
                3,
            )
        ignored = 'system_assistant_late_completion_total{result="ignored"}'
        assert telemetry.snapshot()[ignored] == 1
    finally:
        await engine.dispose()
