"""Post-commit governed execution and ActionRun fencing."""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_assistant_governance import ActionRun
from app.system_assistant.action_store import (
    ActionCASConflict,
    DurableReservation,
    read_reservation,
    record_reserve_conflict,
    reserve_ticket_and_run,
)
from app.system_assistant.telemetry import GovernanceTelemetryRegistry, governance_telemetry


CAS_CONFLICT_ERROR = "错误：该动作已被其他请求占用，请稍后重试"
EXECUTION_FENCE_ERROR = "错误：执行租约已失效，请重新发起动作"


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class ExecutionFence:
    run_id: str
    execution_generation: int


class ExecutionFenceRejected(RuntimeError):
    """A handler tried to act without the current durable execution fence."""


@dataclass(frozen=True)
class ExecutionResult:
    fence: ExecutionFence | None = None
    value: Any = None
    error: str | None = None
    governed_called: bool = False
    legacy_called: bool = False
    outcome: str = "not_started"


async def _call_hook(hook: Any, *args: Any) -> Any:
    if hook is None:
        return None
    if callable(hook):
        try:
            parameters = inspect.signature(hook).parameters.values()
            accepts_args = any(
                parameter.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.VAR_POSITIONAL,
                )
                for parameter in parameters
            )
        except (TypeError, ValueError):
            accepts_args = bool(args)
        value = hook(*args) if accepts_args else hook()
    else:
        value = hook
    if inspect.isawaitable(value):
        return await value
    return value


async def _read_independently(
    session_factory: Any,
    *,
    ticket_id: str,
    run_id: str,
) -> DurableReservation | None:
    if session_factory is None:
        return None
    try:
        async with session_factory() as independent:
            state = await read_reservation(
                independent, ticket_id=ticket_id, run_id=run_id
            )
            await independent.rollback()
            return state
    except Exception:
        return None


def _matches_attempt(
    state: DurableReservation | None,
    *,
    expected_generation: int = 1,
) -> bool:
    return bool(
        state
        and state.ticket_status == "reserved"
        and state.run_status == "executing"
        and state.execution_generation == expected_generation
        and state.lease_owner
    )


async def assert_execution_fence(
    session_or_factory: AsyncSession | Any,
    fence: ExecutionFence | str,
    execution_generation: int | None = None,
    *,
    now: datetime | None = None,
) -> None:
    """Assert status, generation, lease and recovery ownership before effects."""
    now = now or utc_now()
    if isinstance(fence, str):
        if execution_generation is None:
            raise TypeError("execution_generation is required with run_id")
        fence = ExecutionFence(fence, execution_generation)
    owns_session = not isinstance(session_or_factory, AsyncSession)
    if owns_session:
        async with session_or_factory() as session:
            await _assert_in_session(session, fence, now)
        return
    await _assert_in_session(session_or_factory, fence, now)


async def _assert_in_session(
    session: AsyncSession, fence: ExecutionFence, now: datetime
) -> None:
    run = await session.get(ActionRun, fence.run_id)
    if (
        run is None
        or run.status != "executing"
        or int(run.execution_generation) != int(fence.execution_generation)
        or run.lease_owner is None
        or run.lease_expires_at is None
        or run.lease_expires_at <= now
        or run.recovery_owner is not None
    ):
        raise ExecutionFenceRejected(EXECUTION_FENCE_ERROR)


async def execute_with_governance(
    session: AsyncSession,
    *,
    ticket_id: str,
    run_id: str,
    governed_handler: Callable[..., Any],
    legacy_handler: Callable[..., Any] | None,
    expected_ticket_state_version: int | None = None,
    expected_run_state_version: int | None = None,
    lease_owner: str | None = None,
    lease_expires_at: datetime | None = None,
    lease_seconds: int = 60,
    now: datetime | None = None,
    reserve_barrier: Any = None,
    commit_fault: Callable[..., Any] | None = None,
    independent_session_factory: Any = None,
) -> ExecutionResult:
    """Reserve, commit, fence-check, then call exactly one execution path.

    A CAS conflict never falls back to legacy.  A commit exception is resolved
    only with an independent connection: durable matching rows permit the
    governed path, confirmed absence permits one legacy call, and an unreadable
    outcome invokes neither.
    """
    now = now or utc_now()
    if reserve_barrier is not None:
        await _call_hook(reserve_barrier.wait if hasattr(reserve_barrier, "wait") else reserve_barrier)
    if session.in_transaction():
        await session.rollback()

    reservation = None
    try:
        reservation = await reserve_ticket_and_run(
            session,
            ticket_id=ticket_id,
            run_id=run_id,
            expected_ticket_state_version=expected_ticket_state_version,
            expected_run_state_version=expected_run_state_version,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
            lease_seconds=lease_seconds,
            now=now,
        )
        if commit_fault is None:
            await session.commit()
        else:
            await _call_hook(commit_fault, session)
            # A fault hook may be observational and return normally.
            if session.in_transaction():
                await session.commit()
    except ActionCASConflict:
        await _rollback_quietly(session)
        state = await _read_independently(
            independent_session_factory,
            ticket_id=ticket_id,
            run_id=run_id,
        )
        await record_reserve_conflict(state, ticket_id=ticket_id, run_id=run_id)
        if state is not None and state.ticket_status is None and state.run_status is None:
            return await _call_legacy(legacy_handler, outcome="rollback_confirmed")
        return ExecutionResult(error=CAS_CONFLICT_ERROR, outcome="cas_conflict")
    except Exception:
        await _rollback_quietly(session)
        state = await _read_independently(
            independent_session_factory,
            ticket_id=ticket_id,
            run_id=run_id,
        )
        if _matches_attempt(
            state,
            expected_generation=(reservation.execution_generation if reservation else 1),
        ):
            fence = ExecutionFence(run_id, int(state.execution_generation))
            try:
                await assert_execution_fence(
                    independent_session_factory or session,
                    fence,
                    now=utc_now(),
                )
            except ExecutionFenceRejected:
                return ExecutionResult(
                    fence=fence,
                    error=EXECUTION_FENCE_ERROR,
                    outcome="fence_rejected",
                )
            governance_telemetry.record_run_transition(
                "executing",
                state.capability_id or "other",
                run_id=fence.run_id,
                cas_won=True,
            )
            return await _call_governed(
                session,
                fence,
                governed_handler,
                outcome="commit_unknown_durable",
            )
        if state is not None and (
            (state.ticket_status is None and state.run_status is None)
            or (
                state.ticket_status == "authorized"
                and state.run_status == "authorized"
            )
        ):
            return await _call_legacy(legacy_handler, outcome="rollback_confirmed")
        return ExecutionResult(outcome="commit_outcome_unknown")

    fence = ExecutionFence(run_id, reservation.execution_generation)
    try:
        await assert_execution_fence(session, fence, now=utc_now())
    except ExecutionFenceRejected:
        return ExecutionResult(
            fence=fence,
            error=EXECUTION_FENCE_ERROR,
            outcome="fence_rejected",
        )
    run = await session.get(ActionRun, run_id)
    governance_telemetry.record_run_transition(
        "executing",
        getattr(run, "capability_id", "other"),
        run_id=run_id,
        cas_won=True,
    )
    await _rollback_quietly(session)
    return await _call_governed(session, fence, governed_handler, outcome="committed")


async def _call_governed(
    session: AsyncSession,
    fence: ExecutionFence,
    handler: Callable[..., Any],
    *,
    outcome: str,
) -> ExecutionResult:
    try:
        value = await _call_hook(handler, fence)
    except Exception as error:
        return ExecutionResult(
            fence=fence,
            error=str(error),
            governed_called=True,
            outcome=outcome,
        )
    return ExecutionResult(
        fence=fence,
        value=value,
        governed_called=True,
        outcome=outcome,
    )


async def _call_legacy(
    handler: Callable[..., Any] | None,
    *,
    outcome: str,
) -> ExecutionResult:
    if handler is None:
        return ExecutionResult(outcome=outcome)
    try:
        value = await _call_hook(handler)
    except Exception as error:
        return ExecutionResult(
            value=None,
            error=str(error),
            legacy_called=True,
            outcome=outcome,
        )
    return ExecutionResult(value=value, legacy_called=True, outcome=outcome)


async def complete_action_run(
    session: AsyncSession,
    fence: ExecutionFence,
    *,
    status: str,
    result_status: str | None = None,
    result_summary: dict[str, Any] | None = None,
    error_code: str | None = None,
    telemetry: GovernanceTelemetryRegistry = governance_telemetry,
    now: datetime | None = None,
) -> bool:
    """Write one terminal state using status+generation CAS; late writes lose."""
    now = now or utc_now()
    terminal = {
        "succeeded", "failed", "partially_failed", "recovered",
        "recovery_blocked", "outcome_unknown", "aborted",
    }
    if status not in terminal:
        raise ValueError(f"unsupported terminal status: {status}")
    result = await session.execute(
        update(ActionRun)
        .where(
            ActionRun.run_id == fence.run_id,
            ActionRun.status == "executing",
            ActionRun.execution_generation == fence.execution_generation,
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
    won = result.rowcount == 1
    await session.commit()
    run = await session.get(ActionRun, fence.run_id)
    telemetry.record_run_transition(
        status,
        getattr(run, "capability_id", "other"),
        run_id=fence.run_id,
        cas_won=won,
    )
    if not won:
        telemetry.record_late_completion("ignored")
    return won


async def _rollback_quietly(session: AsyncSession) -> None:
    try:
        if session.in_transaction():
            await session.rollback()
    except Exception:
        pass


# Operation aliases used by adapters and focused tests.
reserve_and_fence = execute_with_governance
start_governed_action = execute_with_governance
run_governed_action = execute_with_governance
assert_fence = assert_execution_fence
