"""Atomic persistence primitives for governed action tickets and runs.

The functions in this module deliberately do not commit.  The caller owns the
transaction boundary so no handler can be reached before a durable commit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_assistant_governance import ActionRun, ActionTicket
from app.system_assistant.telemetry import governance_telemetry, log_governance_event


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ActionCASConflict(RuntimeError):
    """The expected owner/state no longer exists; callers must not retry."""


@dataclass(frozen=True)
class RunReservation:
    ticket_id: str
    run_id: str
    execution_generation: int
    lease_owner: str
    lease_expires_at: datetime


@dataclass(frozen=True)
class DurableReservation:
    ticket_status: str | None
    ticket_state_version: int | None
    run_status: str | None
    run_state_version: int | None
    execution_generation: int | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    recovery_owner: str | None
    capability_id: str | None = None

    @property
    def matches_reserved_owner(self) -> bool:
        return (
            self.ticket_status == "reserved"
            and self.run_status == "executing"
            and self.execution_generation is not None
            and self.lease_owner is not None
        )


async def _state_version(session: AsyncSession, model: Any, identity: Any) -> int:
    row = await session.get(model, identity)
    if row is None:
        raise ActionCASConflict(f"{model.__name__} not found")
    return int(row.state_version)


async def confirm_ticket(
    session: AsyncSession,
    ticket_id: str,
    *,
    expected_state_version: int | None = None,
    now: datetime | None = None,
) -> bool:
    """Issue ``issued -> authorized`` with an allowed-state/version CAS."""
    now = now or utc_now()
    if expected_state_version is None:
        expected_state_version = await _state_version(session, ActionTicket, ticket_id)
    result = await session.execute(
        update(ActionTicket)
        .where(
            ActionTicket.ticket_id == ticket_id,
            ActionTicket.status == "issued",
            ActionTicket.state_version == expected_state_version,
            ActionTicket.expires_at > now,
        )
        .values(
            status="authorized",
            state_version=ActionTicket.state_version + 1,
            updated_at=now,
        )
    )
    won = result.rowcount == 1
    governance_telemetry.record_ticket_transition(
        "issued_to_authorized", "success" if won else "conflict"
    )
    return won


async def reserve_ticket(
    session: AsyncSession,
    ticket_id: str,
    *,
    expected_state_version: int | None = None,
    now: datetime | None = None,
) -> bool:
    """Reserve an authorized, unexpired ticket using a single SQL CAS."""
    now = now or utc_now()
    if expected_state_version is None:
        expected_state_version = await _state_version(session, ActionTicket, ticket_id)
    result = await session.execute(
        update(ActionTicket)
        .where(
            ActionTicket.ticket_id == ticket_id,
            ActionTicket.status == "authorized",
            ActionTicket.state_version == expected_state_version,
            ActionTicket.expires_at > now,
        )
        .values(
            status="reserved",
            state_version=ActionTicket.state_version + 1,
            updated_at=now,
        )
    )
    won = result.rowcount == 1
    governance_telemetry.record_ticket_transition(
        "authorized_to_reserved", "success" if won else "conflict"
    )
    return won


async def reserve_ticket_and_run(
    session: AsyncSession,
    *,
    ticket_id: str,
    run_id: str,
    expected_ticket_state_version: int | None = None,
    expected_run_state_version: int | None = None,
    lease_owner: str | None = None,
    lease_expires_at: datetime | None = None,
    lease_seconds: int = 60,
    now: datetime | None = None,
    args_digest: str | None = None,
    object_revision: str | None = None,
    correlation_id: str | None = None,
) -> RunReservation:
    """Atomically reserve a ticket and move its authorized run to executing.

    Both updates are CAS predicates in the same caller-owned transaction.  A
    run mismatch raises ``ActionCASConflict`` so the caller rolls back the
    ticket update rather than opening a second execution path.
    """
    now = now or utc_now()
    lease_owner = lease_owner or str(uuid4())
    lease_expires_at = lease_expires_at or now + timedelta(seconds=lease_seconds)
    if expected_ticket_state_version is None:
        expected_ticket_state_version = await _state_version(
            session, ActionTicket, ticket_id
        )
    if expected_run_state_version is None:
        expected_run_state_version = await _state_version(session, ActionRun, run_id)

    ticket_result = await session.execute(
        update(ActionTicket)
        .where(
            ActionTicket.ticket_id == ticket_id,
            ActionTicket.status == "authorized",
            ActionTicket.state_version == expected_ticket_state_version,
            ActionTicket.expires_at > now,
        )
        .values(
            status="reserved",
            state_version=ActionTicket.state_version + 1,
            updated_at=now,
        )
    )
    if ticket_result.rowcount != 1:
        governance_telemetry.record_ticket_transition(
            "authorized_to_reserved", "conflict"
        )
        raise ActionCASConflict("ticket reserve conflict")
    governance_telemetry.record_ticket_transition(
        "authorized_to_reserved", "success"
    )

    predicates = [
        ActionRun.run_id == run_id,
        ActionRun.ticket_id == ticket_id,
        ActionRun.status == "authorized",
        ActionRun.state_version == expected_run_state_version,
    ]
    if args_digest is not None:
        predicates.append(ActionRun.args_digest == args_digest)
    if object_revision is not None:
        predicates.append(ActionRun.object_revision == object_revision)
    if correlation_id is not None:
        predicates.append(ActionRun.correlation_id == correlation_id)
    run_result = await session.execute(
        update(ActionRun)
        .where(and_(*predicates))
        .values(
            status="executing",
            execution_generation=ActionRun.execution_generation + 1,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
            started_at=now,
            state_version=ActionRun.state_version + 1,
            updated_at=now,
        )
    )
    if run_result.rowcount != 1:
        raise ActionCASConflict("run reserve conflict")

    generation = await session.scalar(
        select(ActionRun.execution_generation).where(ActionRun.run_id == run_id)
    )
    if generation is None:
        raise ActionCASConflict("run disappeared after reserve")
    await session.flush()
    return RunReservation(
        ticket_id=ticket_id,
        run_id=run_id,
        execution_generation=int(generation),
        lease_owner=lease_owner,
        lease_expires_at=lease_expires_at,
    )


async def read_reservation(
    session: AsyncSession,
    *,
    ticket_id: str,
    run_id: str,
) -> DurableReservation:
    """Read both rows through the caller's independent connection."""
    ticket = await session.get(ActionTicket, ticket_id)
    run = await session.get(ActionRun, run_id)
    return DurableReservation(
        ticket_status=getattr(ticket, "status", None),
        ticket_state_version=getattr(ticket, "state_version", None),
        run_status=getattr(run, "status", None),
        run_state_version=getattr(run, "state_version", None),
        execution_generation=getattr(run, "execution_generation", None),
        lease_owner=getattr(run, "lease_owner", None),
        lease_expires_at=getattr(run, "lease_expires_at", None),
        recovery_owner=getattr(run, "recovery_owner", None),
        capability_id=getattr(run, "capability_id", None),
    )


async def claim_recovery(
    session: AsyncSession,
    *,
    run_id: str,
    owner: str,
    now: datetime | None = None,
    lease_seconds: int = 30,
    expected_state_version: int | None = None,
) -> bool:
    """Claim an interrupted run; an unexpired recovery owner wins the CAS."""
    now = now or utc_now()
    lease_expires_at = now + timedelta(seconds=lease_seconds)
    predicates = [
        ActionRun.run_id == run_id,
        ActionRun.status.in_(("executing", "partially_failed", "outcome_unknown")),
        or_(
            ActionRun.recovery_owner.is_(None),
            ActionRun.recovery_lease_expires_at <= now,
        ),
    ]
    if expected_state_version is None:
        expected_state_version = await _state_version(session, ActionRun, run_id)
    predicates.append(ActionRun.state_version == expected_state_version)
    result = await session.execute(
        update(ActionRun)
        .where(and_(*predicates))
        .values(
            recovery_owner=owner,
            recovery_lease_expires_at=lease_expires_at,
            state_version=ActionRun.state_version + 1,
            updated_at=now,
        )
    )
    won = result.rowcount == 1
    governance_telemetry.record_recovery("recovered" if won else "skipped")
    await session.flush()
    return won


async def record_reserve_conflict(
    state: DurableReservation | None,
    *,
    ticket_id: str,
    run_id: str,
) -> None:
    """Emit only bounded diagnostics; never invokes either handler path."""
    log_governance_event(
        "shadow_reserve_conflict",
        error_code="SHADOW_RESERVE_CONFLICT",
        object_digest=ticket_id,
        correlation_id=run_id,
        execution_generation=getattr(state, "execution_generation", None),
    )


# Explicit aliases keep the operation names discoverable to callers and tests.
reserve_and_start = reserve_ticket_and_run
read_durable_reservation = read_reservation
recover_interrupted_run = claim_recovery
confirm_ticket_cas = confirm_ticket
reserve_ticket_cas = reserve_ticket
reserve_action_run = reserve_ticket_and_run
claim_recovery_lease = claim_recovery
