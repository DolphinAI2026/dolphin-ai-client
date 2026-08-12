"""TASK-009 deterministic recovery crash-window table."""
from __future__ import annotations

import pytest

from app.system_assistant.recovery_coordinator import RecoveryCoordinator
from tests.helpers.system_assistant_durable_store import (
    DurableChangePort,
    DurableRecoveryStore,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "window,effect_state,manifest_state,expected_terminal,expected_effects",
    [
        ("window-1-before-effect", "none", "uncommitted", "failed", 0),
        ("window-2-effect-present", "present", "uncommitted", "succeeded", 1),
        ("window-2-effect-partial", "partial", "uncommitted", "partially_failed", 1),
        ("window-2-effect-unknown", "unknown", "uncommitted", "outcome_unknown", 1),
        ("window-3-manifest-committed", "present", "committed", "succeeded", 1),
    ],
)
async def test_crash_window_readback_has_one_terminal_and_never_replays_effect(
    tmp_path, window, effect_state, manifest_state, expected_terminal, expected_effects
):
    store = await DurableRecoveryStore(tmp_path / f"{window}.sqlite3").open()
    try:
        await store.seed_run(
            window, effect_state=effect_state, manifest_state=manifest_state
        )
        coordinator = RecoveryCoordinator(
            store.session_factory, DurableChangePort(store.path), lease_seconds=30
        )
        report = await coordinator.scan(owner="scanner-a")

        run = await store.read_run(window)
        counts = await store.counts(window)
        assert [(item.run_id, item.owner, item.terminal) for item in report.outcomes] == [
            (window, "scanner-a", expected_terminal)
        ]
        assert (run.status, run.recovery_owner) == (expected_terminal, "scanner-a")
        assert counts.effect_count == expected_effects
        assert run.result_summary["recovery_observation"]["schema_version"] == (
            "RecoveryObservation/v1"
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_window_4_terminal_commit_failure_retries_same_cas_after_restart_without_effect(
    tmp_path,
):
    path = tmp_path / "window-4.sqlite3"
    store = await DurableRecoveryStore(path).open()
    await store.seed_run(
        "window-4", effect_state="present", manifest_state="committed"
    )
    store.arm_commit_failure()
    first = RecoveryCoordinator(
        store.session_factory,
        DurableChangePort(path),
        lease_seconds=30,
        terminal_commit=store.commit_with_durable_fault,
    )
    first_report = await first.scan(owner="scanner-a")
    first_run = await store.read_run("window-4")
    first_counts = await store.counts("window-4")
    assert first_report.outcomes[0].terminal is None
    assert first_run.status == "executing"
    assert first_counts.effect_count == 1
    await store.close()

    restarted = await DurableRecoveryStore(path).open()
    try:
        # A later verifier read must not change the already derived terminal.
        await restarted.set_effect_state("window-4", "partial")
        await restarted.expire_recovery_lease("window-4")
        second = RecoveryCoordinator(
            restarted.session_factory, DurableChangePort(path), lease_seconds=30
        )
        second_report = await second.scan(owner="scanner-after-restart")
        run = await restarted.read_run("window-4")
        counts = await restarted.counts("window-4")
        assert [(item.owner, item.terminal) for item in second_report.outcomes] == [
            ("scanner-after-restart", "succeeded")
        ]
        assert (run.status, run.recovery_owner, counts.effect_count) == (
            "succeeded",
            "scanner-after-restart",
            1,
        )
    finally:
        await restarted.close()
