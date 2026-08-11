from __future__ import annotations


def test_governance_telemetry_uses_bounded_labels_and_terminal_cas_winner_only():
    from app.system_assistant.telemetry import GovernanceTelemetryRegistry

    telemetry = GovernanceTelemetryRegistry()
    telemetry.record_projection("304")
    telemetry.record_projection("failure")
    telemetry.record_snapshot("stale", policy_revision=999999999)
    telemetry.record_access_compare("allow", "deny", "mismatch")
    telemetry.record_ticket_transition("issued_to_authorized", "success")
    telemetry.record_run_transition(
        "succeeded", "capability-user-raw-123", run_id="run-1", cas_won=True
    )
    telemetry.record_run_transition(
        "succeeded", "capability-user-raw-123", run_id="run-1", cas_won=False
    )
    telemetry.record_recovery("recovered")
    telemetry.record_late_completion("ignored")
    telemetry.record_observability_projection("failed")

    snapshot = telemetry.snapshot()
    assert snapshot['system_assistant_projection_load_total{result="not_modified"}'] == 1
    assert snapshot['system_assistant_projection_load_total{result="failure"}'] == 1
    assert snapshot['system_assistant_snapshot_total{policy_revision="other",result="stale"}'] == 1
    assert snapshot['system_assistant_run_transition_total{capability_id="other",status="succeeded"}'] == 1
    assert snapshot['system_assistant_recovery_total{result="recovered"}'] == 1
    assert snapshot['system_assistant_late_completion_total{result="ignored"}'] == 1
    assert snapshot['system_assistant_observability_projection_total{result="failed"}'] == 1
    assert "capability-user-raw-123" not in telemetry.render()


def test_terminal_transition_is_idempotent_for_same_run_when_cas_wins_repeatedly():
    from app.system_assistant.telemetry import GovernanceTelemetryRegistry

    telemetry = GovernanceTelemetryRegistry()
    telemetry.record_run_transition("failed", "code.workspace.edit", run_id="run-1")
    telemetry.record_run_transition("failed", "code.workspace.edit", run_id="run-1")
    telemetry.record_run_transition("failed", "code.workspace.edit", run_id="run-2")

    assert telemetry.snapshot()[
        'system_assistant_run_transition_total{capability_id="code.workspace.edit",status="failed"}'
    ] == 2


def test_governance_metrics_can_be_registered_into_existing_sandbox_registry():
    from app.code_runtime.sandbox_metrics import SandboxAuthMetricsRegistry
    from app.system_assistant.telemetry import GovernanceTelemetryRegistry

    sandbox = SandboxAuthMetricsRegistry()
    governance = GovernanceTelemetryRegistry()
    governance.record_projection("success")
    sandbox.register_collector(governance)

    rendered = sandbox.render()
    assert "sandbox_auth_renew_total" in rendered
    assert 'system_assistant_projection_load_total{result="success"} 1' in rendered
