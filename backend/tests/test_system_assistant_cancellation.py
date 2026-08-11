"""TASK-007 cancellation generation and repeat-cancel contracts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.system_assistant_governance import ActionRun
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
