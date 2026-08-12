"""TASK-009 recovery ownership, restart and safety barriers."""
from __future__ import annotations

import asyncio

import pytest

from app.system_assistant.recovery_coordinator import (
    RecoveryCoordinator,
    run_configured_startup_recovery_scan,
    run_startup_recovery_scan,
)
from tests.helpers.system_assistant_durable_store import (
    DurableChangePort,
    DurableRecoveryStore,
)


@pytest.mark.asyncio
async def test_two_scanners_cross_the_same_candidate_barrier_but_only_one_owns_terminal(
    tmp_path,
):
    store = await DurableRecoveryStore(tmp_path / "two-scanners.sqlite3").open()
    try:
        await store.seed_run("run-double", effect_state="present")
        candidate_barrier = asyncio.Barrier(2)
        coordinator_a = RecoveryCoordinator(
            store.session_factory,
            DurableChangePort(store.path),
            candidate_barrier=candidate_barrier,
        )
        coordinator_b = RecoveryCoordinator(
            store.session_factory,
            DurableChangePort(store.path),
            candidate_barrier=candidate_barrier,
        )
        reports = await asyncio.gather(
            coordinator_a.scan(owner="scanner-a"),
            coordinator_b.scan(owner="scanner-b"),
        )

        run = await store.read_run("run-double")
        counts = await store.counts("run-double")
        terminals = [
            item for report in reports for item in report.outcomes if item.terminal
        ]
        assert len(terminals) == 1
        assert (terminals[0].owner, terminals[0].terminal) in {
            ("scanner-a", "succeeded"),
            ("scanner-b", "succeeded"),
        }
        assert (run.recovery_owner, run.status, counts.effect_count) == (
            terminals[0].owner,
            "succeeded",
            1,
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_restart_uses_only_database_and_durable_effect_ledger(tmp_path):
    path = tmp_path / "restart.sqlite3"
    store = await DurableRecoveryStore(path).open()
    await store.seed_run("run-restart", effect_state="present")
    await store.close()

    restarted = await DurableRecoveryStore(path).open()
    try:
        coordinator = RecoveryCoordinator(
            restarted.session_factory, DurableChangePort(path)
        )
        await coordinator.scan(owner="scanner-after-restart")
        run = await restarted.read_run("run-restart")
        counts = await restarted.counts("run-restart")
        assert (run.status, run.recovery_owner, counts.effect_count) == (
            "succeeded",
            "scanner-after-restart",
            1,
        )
    finally:
        await restarted.close()


@pytest.mark.asyncio
async def test_outcome_unknown_requires_new_verifier_evidence_before_followup_terminal(
    tmp_path,
):
    store = await DurableRecoveryStore(tmp_path / "unknown-followup.sqlite3").open()
    try:
        await store.seed_run("run-unknown", effect_state="unknown")
        coordinator = RecoveryCoordinator(
            store.session_factory, DurableChangePort(store.path)
        )
        await coordinator.scan(owner="scanner-a")
        unknown = await store.read_run("run-unknown")
        first_version = unknown.state_version
        first_evidence = unknown.result_summary["recovery_observation"][
            "evidence_digest"
        ]

        repeated = await coordinator.scan(owner="scanner-a")
        same = await store.read_run("run-unknown")
        assert repeated.outcomes[0].terminal is None
        assert (same.status, same.state_version) == ("outcome_unknown", first_version + 1)
        assert same.result_summary["recovery_observation"]["evidence_digest"] == first_evidence

        await store.set_effect_state("run-unknown", "present")
        resolved = await coordinator.scan(owner="scanner-a")
        recovered = await store.read_run("run-unknown")
        assert resolved.outcomes[0].terminal == "recovered"
        assert recovered.status == "recovered"
        assert recovered.result_summary["recovery_observation"]["evidence_digest"] != (
            first_evidence
        )
    finally:
        await store.close()

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "next_effect,expected_terminal",
    [("none", "failed"), ("partial", "recovery_blocked"), ("present", "recovered")],
)
async def test_outcome_unknown_new_observation_has_only_frozen_followup_terminals(
    tmp_path, next_effect, expected_terminal
):
    store = await DurableRecoveryStore(
        tmp_path / f"unknown-{next_effect}.sqlite3"
    ).open()
    try:
        await store.seed_run("run-followup", effect_state="unknown")
        coordinator = RecoveryCoordinator(
            store.session_factory, DurableChangePort(store.path)
        )
        await coordinator.scan(owner="scanner-a")
        await store.set_effect_state("run-followup", next_effect)
        report = await coordinator.scan(owner="scanner-a")
        run = await store.read_run("run-followup")
        assert report.outcomes[0].terminal == expected_terminal
        assert run.status == expected_terminal
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_repeated_verifier_error_is_not_new_outcome_unknown_evidence(tmp_path):
    store = await DurableRecoveryStore(tmp_path / "verifier-error.sqlite3").open()
    try:
        await store.seed_run("run-error", effect_state="unknown")

        class BrokenPort(DurableChangePort):
            async def verify_change(self, run_id: str):
                raise RuntimeError("verifier remains unavailable")

        coordinator = RecoveryCoordinator(
            store.session_factory, BrokenPort(store.path)
        )
        await coordinator.scan(owner="scanner-a")
        first = await store.read_run("run-error")
        first_evidence = first.result_summary["recovery_observation"][
            "evidence_digest"
        ]

        repeated = await coordinator.scan(owner="scanner-a")
        second = await store.read_run("run-error")
        assert repeated.outcomes[0].terminal is None
        assert second.status == "outcome_unknown"
        assert second.result_summary["recovery_observation"]["evidence_digest"] == (
            first_evidence
        )
    finally:
        await store.close()

@pytest.mark.asyncio
async def test_recovery_observation_persists_only_frozen_v1_fields(tmp_path):
    store = await DurableRecoveryStore(tmp_path / "observation-fields.sqlite3").open()
    try:
        await store.seed_run("run-fields", effect_state="present")
        class ExtraFieldPort(DurableChangePort):
            async def verify_change(self, run_id: str):
                observation = await super().verify_change(run_id)
                observation["secret"] = "must-not-persist"
                observation["future_extension"] = {"token": "must-not-persist"}
                return observation
        coordinator = RecoveryCoordinator(
            store.session_factory, ExtraFieldPort(store.path)
        )
        await coordinator.scan(owner="scanner-a")
        observation = (await store.read_run("run-fields")).result_summary[
            "recovery_observation"
        ]
        assert set(observation) == {
            "schema_version",
            "observed_at",
            "object_revision_before",
            "object_revision_observed",
            "object_digest_observed",
            "manifest_state",
            "effect_state",
            "verification_status",
            "verifier_error_code",
            "evidence_digest",
            "terminal_candidate",
        }
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_external_modification_between_verify_and_recover_blocks_without_write(
    tmp_path,
):
    store = await DurableRecoveryStore(tmp_path / "external.sqlite3").open()
    try:
        await store.seed_run("run-external", effect_state="partial")
        coordinator = RecoveryCoordinator(
            store.session_factory, DurableChangePort(store.path)
        )
        await coordinator.scan(owner="scanner-a")
        assert (await store.read_run("run-external")).status == "partially_failed"

        async def external_modification(_run_id: str) -> None:
            await store.external_modify("run-external")

        recovery = RecoveryCoordinator(
            store.session_factory,
            DurableChangePort(store.path),
            before_recover=external_modification,
        )
        report = await recovery.scan(owner="scanner-a")
        run = await store.read_run("run-external")
        counts = await store.counts("run-external")
        assert report.outcomes[0].terminal == "recovery_blocked"
        assert (run.status, counts.effect_count, counts.recovery_count) == (
            "recovery_blocked",
            1,
            0,
        )
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_shadow_startup_scan_timeout_is_degraded_and_does_not_raise(tmp_path):
    store = await DurableRecoveryStore(tmp_path / "timeout.sqlite3").open()
    try:
        await store.seed_run("run-timeout", effect_state="present")

        class SlowPort(DurableChangePort):
            async def verify_change(self, run_id: str):
                await asyncio.Event().wait()

        health = await run_startup_recovery_scan(
            store.session_factory,
            SlowPort(store.path),
            policy="shadow",
            timeout_seconds=0.01,
        )
        run = await store.read_run("run-timeout")
        assert (health.status, health.error_code) == (
            "degraded",
            "SYSTEM_ASSISTANT_RECOVERY_SCAN_TIMEOUT",
        )
        assert run.status == "executing"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_configured_shadow_startup_scan_publishes_degraded_health_without_verifier():
    app = type("App", (), {"state": type("State", (), {})()})()

    health = await run_configured_startup_recovery_scan(
        app,
        policy="shadow",
        session_factory=None,
        change_port=None,
        timeout_seconds=0.01,
    )

    assert health.status == "degraded"
    assert health.error_code == "SYSTEM_ASSISTANT_RECOVERY_VERIFIER_UNAVAILABLE"
    assert app.state.system_assistant_recovery_health is health
