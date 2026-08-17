"""B0 durable persistence contracts for governed system-assistant actions."""
from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.database import Base


def _utc_naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _normalise_governance_json_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


class GovernanceJSONMap(TypeDecorator):
    """A versioned audit map that excludes raw tool input and credentials."""

    impl = JSON
    cache_ok = True

    _sensitive_key_names = frozenset({
        "apikey", "args", "argument", "authorization", "connectionstring", "credential",
        "databaseurl", "environment", "filebody", "headers", "mcpheaders", "password",
        "payload", "rawcontent", "secret", "token", "toolargs",
    })
    _sensitive_key_parts = frozenset(
        _normalise_governance_json_key(key) for key in _sensitive_key_names
    )
    _allowed_key_names = frozenset({
        "at", "change", "changes", "code", "counts", "delivery_status", "digest", "error_code",
        "generation", "id", "items", "kind", "label", "metadata", "object_ref",
        "object_revision", "phase", "policy_revision", "reference", "references", "result",
        "result_status", "results", "retry_count", "schema_version", "state", "status", "summary",
        "timestamp", "type", "version", "warning", "warnings",
    })
    _allowed_keys = frozenset(
        _normalise_governance_json_key(key) for key in _allowed_key_names
    )
    _connection_string = re.compile(
        r"(?:postgres(?:ql)?|mysql|sqlite|mariadb|mongodb|redis|amqp)://", re.IGNORECASE
    )

    def __init__(self, field_name: str) -> None:
        self.field_name = field_name
        super().__init__()

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError(f"{self.field_name} must be a JSON map")
        self._validate(value)
        return value

    @classmethod
    def _normalise_key(cls, key: Any) -> str:
        return _normalise_governance_json_key(key)

    @classmethod
    def _validate(cls, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalised = cls._normalise_key(key)
                if (
                    normalised in cls._sensitive_key_parts
                    or normalised not in cls._allowed_keys
                ):
                    raise ValueError("sensitive or unsupported key in governance JSON map")
                cls._validate(item)
        elif isinstance(value, list):
            for item in value:
                cls._validate(item)
        elif isinstance(value, str) and cls._connection_string.search(value):
            raise ValueError("sensitive connection string in governance JSON map")


class ActionTicket(Base):
    """An expiring authorization ticket; reserve/consume behavior is downstream work."""

    __tablename__ = "system_assistant_action_tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('issued', 'authorized', 'reserved', 'consumed', 'expired', 'revoked')",
            name="ck_system_assistant_action_tickets_status",
        ),
        UniqueConstraint("ticket_id", "tenant_id", name="uq_system_assistant_action_tickets_ticket_tenant"),
        Index(
            "ix_system_assistant_action_tickets_tenant_user_status_expires",
            "tenant_id",
            "user_id",
            "status",
            "expires_at",
        ),
        Index(
            "ix_system_assistant_action_tickets_session_object_status",
            "session_public_id",
            "object_ref",
            "status",
        ),
    )

    ticket_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    control_plane_tenant_id: Mapped[str] = mapped_column(String(80), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    session_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("ai_chat_sessions.id", ondelete="SET NULL", name="fk_system_assistant_action_tickets_session_id"),
        nullable=True,
    )
    session_public_id: Mapped[str] = mapped_column(String(36), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    action_kind: Mapped[str] = mapped_column(String(120), nullable=False)
    args_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    object_revision: Mapped[str] = mapped_column(String(160), nullable=False)
    policy_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_naive_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_naive_now,
        onupdate=_utc_naive_now,
    )


class ActionRun(Base):
    """A durable action attempt. CAS, leases and fences are not implemented here."""

    __tablename__ = "system_assistant_action_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('prepared', 'authorized', 'executing', 'succeeded', 'failed', "
            "'partially_failed', 'recovered', 'recovery_blocked', 'outcome_unknown', 'aborted')",
            name="ck_system_assistant_action_runs_status",
        ),
        CheckConstraint(
            "audit_delivery_status IN ('not_required', 'pending', 'delivered', 'failed')",
            name="ck_system_assistant_action_runs_audit_delivery_status",
        ),
        Index("ix_system_assistant_action_runs_status_updated", "status", "updated_at"),
        Index("ix_system_assistant_action_runs_ticket_id", "ticket_id"),
        Index("ix_system_assistant_action_runs_correlation_id", "correlation_id"),
        Index("ix_system_assistant_action_runs_object_created", "object_ref", "created_at"),
        Index(
            "ix_system_assistant_action_runs_recovery_lease_status",
            "recovery_lease_expires_at",
            "status",
        ),
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    ticket_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey(
            "system_assistant_action_tickets.ticket_id",
            ondelete="SET NULL",
            name="fk_system_assistant_action_runs_ticket_id",
        ),
        nullable=True,
    )
    tool_call_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey(
            "ai_chat_tool_calls.id",
            ondelete="SET NULL",
            name="fk_system_assistant_action_runs_tool_call_id",
        ),
        nullable=True,
    )
    capability_id: Mapped[str] = mapped_column(String(120), nullable=False)
    action_kind: Mapped[str] = mapped_column(String(120), nullable=False)
    object_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    args_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    object_revision: Mapped[str] = mapped_column(String(160), nullable=False)
    policy_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    execution_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_owner: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancel_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancel_acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    recovery_owner: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    recovery_lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    base_state: Mapped[dict[str, Any]] = mapped_column(GovernanceJSONMap("base_state"), nullable=False, default=dict)
    change_manifest: Mapped[dict[str, Any]] = mapped_column(
        GovernanceJSONMap("change_manifest"), nullable=False, default=dict
    )
    result_summary: Mapped[dict[str, Any]] = mapped_column(
        GovernanceJSONMap("result_summary"), nullable=False, default=dict
    )
    result_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    audit_delivery_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_required"
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_naive_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_naive_now,
        onupdate=_utc_naive_now,
    )
