"""Durable cancellation and session-delete lifecycle guards for B0.

This module owns only the lifecycle boundary.  Action reservation remains in
``action_store`` and handlers are still invoked by ``action_execution`` after
its reserve transaction commits.  Every helper here commits or rolls back its
own transaction so route callers cannot accidentally expose a half-decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, delete as sql_delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AIChatArtifact,
    AIChatAttachment,
    AIChatMessage,
    AIChatSession,
    AIChatToolCall,
)
from app.models.system_assistant_governance import ActionRun, ActionTicket
from app.system_assistant.telemetry import GovernanceTelemetryRegistry, governance_telemetry


ACTIVE_ACTION_ERROR_CODE = "SYSTEM_ASSISTANT_SESSION_HAS_ACTIVE_ACTION"
TICKET_BLOCKING_STATUSES = frozenset({"reserved"})
RUN_BLOCKING_STATUSES = frozenset(
    {"executing", "partially_failed", "recovery_blocked", "outcome_unknown"}
)
CANCELLABLE_RUN_STATUSES = frozenset({"authorized", "executing"})
TERMINAL_RUN_STATUSES = frozenset(
    {
        "succeeded",
        "failed",
        "partially_failed",
        "recovered",
        "recovery_blocked",
        "outcome_unknown",
        "aborted",
    }
)
LATE_COMPLETION_ERROR_CODE = "LATE_COMPLETION_IGNORED"


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class SessionHasActiveAction(RuntimeError):
    """The delete predicate found a durable action that may still have effects."""

    code = ACTIVE_ACTION_ERROR_CODE
    status_code = 409

    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        super().__init__(self.code)


class SessionNotFound(RuntimeError):
    """The session disappeared before the delete transaction acquired its lock."""


@dataclass(frozen=True)
class CancelResult:
    changed: bool
    run_id: str
    status: str | None
    execution_generation: int | None


async def _rollback_if_needed(db: AsyncSession) -> None:
    if db.in_transaction():
        await db.rollback()


async def delete_session_with_guard(
    db: AsyncSession,
    session_id: int,
) -> dict[str, bool]:
    """Delete a chat session only after the durable active-action check.

    The transaction order is intentionally explicit and must stay stable:
    session lock -> ticket lock/revoke -> run lock/check -> delete children and
    session.  Governance rows are never deleted; their session FK is cleared.
    """
    await _rollback_if_needed(db)
    try:
        session = (
            await db.execute(
                select(AIChatSession)
                .where(AIChatSession.id == session_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if session is None:
            raise SessionNotFound(session_id)

        tickets = (
            await db.execute(
                select(ActionTicket)
                .where(ActionTicket.session_id == session_id)
                .order_by(ActionTicket.ticket_id)
                .with_for_update()
            )
        ).scalars().all()
        ticket_ids = [ticket.ticket_id for ticket in tickets]
        now = utc_now()

        # Revoke only replayable tickets before inspecting blocking rows.  A
        # later 409 rolls this update back together with the whole transaction.
        for ticket in tickets:
            if ticket.status in {"issued", "authorized"}:
                ticket.status = "revoked"
                ticket.state_version = int(ticket.state_version) + 1
                ticket.updated_at = now

        runs = []
        if ticket_ids:
            runs = (
                await db.execute(
                    select(ActionRun)
                    .where(ActionRun.ticket_id.in_(ticket_ids))
                    .order_by(ActionRun.run_id)
                    .with_for_update()
                )
            ).scalars().all()
        if any(
            ticket.status in TICKET_BLOCKING_STATUSES for ticket in tickets
        ) or any(run.status in RUN_BLOCKING_STATUSES for run in runs):
            raise SessionHasActiveAction(session_id)

        # Keep governance references after the session disappears.  The
        # ticket/run rows remain queryable by object/correlation identifiers.
        for ticket in tickets:
            ticket.session_id = None
            ticket.updated_at = now

        await db.execute(sql_delete(AIChatToolCall).where(AIChatToolCall.session_id == session_id))
        await db.execute(sql_delete(AIChatMessage).where(AIChatMessage.session_id == session_id))
        await db.execute(sql_delete(AIChatAttachment).where(AIChatAttachment.session_id == session_id))
        await db.execute(sql_delete(AIChatArtifact).where(AIChatArtifact.session_id == session_id))
        await db.delete(session)
        await db.commit()
        return {"ok": True}
    except Exception:
        await db.rollback()
        raise


async def cancel_action_run(
    db: AsyncSession,
    run_id: str,
    *,
    expected_generation: int | None = None,
    generation: int | None = None,
    now: datetime | None = None,
) -> CancelResult:
    """Invalidate a governed handler and make its unknown outcome durable.

    ``status=outcome_unknown`` is deliberate: cancellation cannot prove that
    an external effect did not happen.  Incrementing generation and clearing
    the lease makes every old fence fail immediately.
    """
    now = now or utc_now()
    if expected_generation is None:
        expected_generation = generation
    if expected_generation is None:
        raise TypeError("expected_generation is required")
    await _rollback_if_needed(db)
    try:
        result = await db.execute(
            update(ActionRun)
            .where(
                ActionRun.run_id == run_id,
                ActionRun.status.in_(CANCELLABLE_RUN_STATUSES),
                ActionRun.execution_generation == expected_generation,
            )
            .values(
                status=case(
                    (ActionRun.status == "executing", "outcome_unknown"),
                    else_="aborted",
                ),
                cancel_requested_at=now,
                execution_generation=ActionRun.execution_generation + 1,
                lease_owner=None,
                lease_expires_at=None,
                state_version=ActionRun.state_version + 1,
                updated_at=now,
            )
        )
        changed = result.rowcount == 1
        await db.commit()
        run = await db.get(ActionRun, run_id)
        return CancelResult(
            changed=changed,
            run_id=run_id,
            status=getattr(run, "status", None),
            execution_generation=(
                int(run.execution_generation) if run is not None else None
            ),
        )
    except Exception:
        await db.rollback()
        raise


async def cancel_session_action_runs(
    db: AsyncSession,
    session_id: int,
    *,
    now: datetime | None = None,
) -> list[CancelResult]:
    """Cancel every currently executing governed run owned by a chat session."""
    now = now or utc_now()
    await _rollback_if_needed(db)
    try:
        runs = (
            await db.execute(
                select(ActionRun)
                .join(ActionTicket, ActionTicket.ticket_id == ActionRun.ticket_id)
                .where(
                    ActionTicket.session_id == session_id,
                    ActionRun.status.in_(CANCELLABLE_RUN_STATUSES),
                )
                .with_for_update()
            )
        ).scalars().all()
        results: list[CancelResult] = []
        for run in runs:
            generation = int(run.execution_generation)
            run.status = (
                "outcome_unknown" if run.status == "executing" else "aborted"
            )
            run.cancel_requested_at = now
            run.execution_generation = generation + 1
            run.lease_owner = None
            run.lease_expires_at = None
            run.state_version = int(run.state_version) + 1
            run.updated_at = now
            results.append(CancelResult(True, run.run_id, run.status, generation + 1))
        await db.commit()
        return results
    except Exception:
        await db.rollback()
        raise


async def complete_action_run(
    db: AsyncSession,
    fence: Any,
    *,
    status: str,
    result_status: str | None = None,
    result_summary: dict[str, Any] | None = None,
    error_code: str | None = None,
    telemetry: GovernanceTelemetryRegistry = governance_telemetry,
    now: datetime | None = None,
) -> bool:
    """Complete exactly one current generation, recording stale writes once."""
    now = now or utc_now()
    run_id = str(fence.run_id)
    generation = int(fence.execution_generation)
    if status not in TERMINAL_RUN_STATUSES:
        raise ValueError(f"unsupported terminal status: {status}")
    await _rollback_if_needed(db)
    try:
        result = await db.execute(
            update(ActionRun)
            .where(
                ActionRun.run_id == run_id,
                ActionRun.status == "executing",
                ActionRun.execution_generation == generation,
                ActionRun.lease_expires_at > now,
                ActionRun.recovery_owner.is_(None),
            )
            .values(
                status=status,
                result_status=result_status,
                result_summary=result_summary or {},
                error_code=error_code,
                finished_at=now,
                state_version=ActionRun.state_version + 1,
                updated_at=now,
            )
        )
        if result.rowcount == 1:
            await db.commit()
            run = await db.get(ActionRun, run_id)
            telemetry.record_run_transition(
                status,
                getattr(run, "capability_id", "other"),
                run_id=run_id,
                cas_won=True,
            )
            return True

        # Only a non-terminal current run can receive the bounded stale-write
        # marker.  Terminal rows are immutable after their winning CAS.
        await db.rollback()
        marker = await db.execute(
            update(ActionRun)
            .where(
                ActionRun.run_id == run_id,
                ActionRun.status.not_in(TERMINAL_RUN_STATUSES),
                ActionRun.error_code.is_(None),
            )
            .values(
                error_code=LATE_COMPLETION_ERROR_CODE,
                updated_at=now,
                state_version=ActionRun.state_version + 1,
            )
        )
        if marker.rowcount == 1:
            await db.commit()
            telemetry.record_late_completion("ignored")
        else:
            await db.rollback()
        return False
    except Exception:
        await db.rollback()
        raise


# Explicit aliases keep lifecycle call sites and contract tests readable.
delete_session = delete_session_with_guard
cancel_generation = cancel_action_run
complete_action_run_with_fence = complete_action_run
