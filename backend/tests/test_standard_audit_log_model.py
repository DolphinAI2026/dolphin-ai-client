from app import models
from app.database import Base
from app.models.collaboration import ApplicationMember


def test_audit_log_model_is_registered_with_stable_cursor_columns():
    assert hasattr(models, "AuditLog")

    table = Base.metadata.tables["audit_logs"]
    assert {
        "id",
        "occurred_at",
        "tenant_id",
        "application_id",
        "actor_id",
        "actor_name",
        "event_type",
        "target_type",
        "target_id",
        "result",
        "failure_reason",
        "ip_address",
        "request_id",
        "correlation_id",
        "before_value",
        "after_value",
    } <= set(table.columns.keys())
    assert "idx_audit_logs_tenant_cursor" in {index.name for index in table.indexes}


def test_application_member_role_defaults_to_collaborator():
    role_column = ApplicationMember.__table__.columns["role"]

    assert role_column.default.arg == "collaborator"
    assert str(role_column.server_default.arg) == "collaborator"
