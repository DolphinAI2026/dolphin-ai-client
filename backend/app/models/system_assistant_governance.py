"""Durable, payload-safe audit references for system-assistant actions."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.database import Base


def _utc_naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class GovernanceMetadataJSON(TypeDecorator):
    """JSON map limited to audit references, never raw action input or secrets."""

    impl = JSON
    cache_ok = True

    _sensitive_keys = frozenset({
        "args", "arguments", "body", "content", "connection_string", "database_url",
        "environment", "environment_variables", "file_body", "headers", "mcp_headers",
        "password", "payload", "raw_content", "token",
    })

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("governance metadata must be a JSON object")
        self._assert_safe(value)
        return value

    @classmethod
    def _assert_safe(cls, value: dict[str, Any]) -> None:
        for key, item in value.items():
            if str(key).lower() in cls._sensitive_keys:
                raise ValueError("sensitive values are not permitted in governance metadata")
            if isinstance(item, dict):
                cls._assert_safe(item)
            elif isinstance(item, list):
                for entry in item:
                    if isinstance(entry, dict):
                        cls._assert_safe(entry)


class ActionTicket(Base):
    """A tenant-scoped request to carry out one governed assistant action."""

    __tablename__ = "system_assistant_action_tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled', 'executing', 'completed', 'failed')",
            name="ck_system_assistant_action_tickets_status",
        ),
        Index("ix_system_assistant_action_tickets_tenant_status", "tenant_id", "status"),
        Index(
            "uq_system_assistant_action_tickets_tenant_correlation",
            "tenant_id",
            "correlation_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(GovernanceMetadataJSON(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_naive_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utc_naive_now,
        onupdate=_utc_naive_now,
    )


class ActionRun(Base):
    """A durable execution attempt. Later B0 work owns state CAS and fencing."""

    __tablename__ = "system_assistant_action_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'reserved', 'running', 'succeeded', 'failed', 'interrupted', 'cancelled')",
            name="ck_system_assistant_action_runs_status",
        ),
        Index("ix_system_assistant_action_runs_ticket_created", "ticket_id", "created_at"),
        Index("ix_system_assistant_action_runs_tenant_correlation", "tenant_id", "correlation_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    ticket_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey(
            "system_assistant_action_tickets.id",
            ondelete="SET NULL",
            name="fk_system_assistant_action_runs_ticket_id",
        ),
        nullable=True,
    )
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    result_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    snapshot_digest: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(GovernanceMetadataJSON(), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utc_naive_now)
