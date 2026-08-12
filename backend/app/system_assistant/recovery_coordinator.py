"""Bounded deterministic recovery for interrupted governed actions."""
from __future__ import annotations
import asyncio
import hashlib
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4
from sqlalchemy import JSON, bindparam, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.models.system_assistant_governance import ActionRun, ActionTicket
from app.system_assistant.telemetry import governance_telemetry, log_governance_event
SCANNABLE_STATUSES = ("executing", "partially_failed", "outcome_unknown")
RECOVERY_SCHEMA = "RecoveryObservation/v1"
RECOVERY_SCAN_TIMEOUT = "SYSTEM_ASSISTANT_RECOVERY_SCAN_TIMEOUT"
RECOVERY_VERIFIER_UNAVAILABLE = "SYSTEM_ASSISTANT_RECOVERY_VERIFIER_UNAVAILABLE"
_VERIFICATIONS = frozenset({"no_effect", "effect_matches", "effect_partial", "effect_unknown", "external_modified", "error"})
_EFFECT_STATES = frozenset({"none", "present", "partial", "unknown"})
def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
class ChangeRecoveryPort(Protocol):
    async def verify_change(self, run_id: str) -> Mapping[str, Any]: ...
    async def recover_change(
        self, run_id: str, fence: "RecoveryFence"
    ) -> Mapping[str, Any]: ...
@dataclass(frozen=True)
class RecoveryFence:
    run_id: str
    execution_generation: int
    object_revision_observed: str
    object_digest_observed: str
@dataclass(frozen=True)
class RecoveryOutcome:
    run_id: str
    owner: str
    terminal: str | None
    error_code: str | None = None
@dataclass(frozen=True)
class RecoveryScanReport:
    outcomes: tuple[RecoveryOutcome, ...]
@dataclass(frozen=True)
class RecoveryHealth:
    status: str
    error_code: str | None = None
    scanned_count: int = 0
@dataclass(frozen=True)
class _Candidate:
    run_id: str
    ticket_id: str | None
    status: str
    state_version: int
    execution_generation: int
    capability_id: str
    object_revision: str
    result_summary: dict[str, Any]
TerminalCommit = Callable[[AsyncSession], Awaitable[None]]
class RecoveryCoordinator:
    """Claims unresolved runs and derives terminals without replaying effects."""
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        change_port: ChangeRecoveryPort,
        *,
        lease_seconds: int = 30,
        batch_size: int = 100,
        candidate_barrier: Any | None = None,
        before_recover: Callable[[str], Any] | None = None,
        terminal_commit: TerminalCommit | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.change_port = change_port
        self.lease_seconds = max(1, int(lease_seconds))
        self.batch_size = max(1, int(batch_size))
        self.candidate_barrier = candidate_barrier
        self.before_recover = before_recover
        self.terminal_commit = terminal_commit
    async def scan(self, *, owner: str) -> RecoveryScanReport:
        candidates = await self._load_candidates()
        if self.candidate_barrier is not None and candidates:
            await self.candidate_barrier.wait()
        outcomes = [await self._recover_candidate(candidate, owner) for candidate in candidates]
        return RecoveryScanReport(tuple(outcomes))
    async def _load_candidates(self) -> list[_Candidate]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        ActionRun.run_id,
                        ActionRun.ticket_id,
                        ActionRun.status,
                        ActionRun.state_version,
                        ActionRun.execution_generation,
                        ActionRun.capability_id,
                        ActionRun.object_revision,
                        ActionRun.result_summary,
                    )
                    .where(ActionRun.status.in_(SCANNABLE_STATUSES))
                    .order_by(ActionRun.updated_at, ActionRun.run_id)
                    .limit(self.batch_size)
                )
            ).all()
        return [
            _Candidate(
                run_id=str(row.run_id),
                ticket_id=row.ticket_id,
                status=str(row.status),
                state_version=int(row.state_version),
                execution_generation=int(row.execution_generation),
                capability_id=str(row.capability_id),
                object_revision=str(row.object_revision),
                result_summary=dict(row.result_summary or {}),
            )
            for row in rows
        ]
    async def _claim(self, candidate: _Candidate, owner: str) -> int | None:
        now = utc_now()
        predicates = [
            ActionRun.run_id == candidate.run_id,
            ActionRun.status == candidate.status,
            ActionRun.state_version == candidate.state_version,
            or_(
                ActionRun.recovery_owner.is_(None),
                ActionRun.recovery_owner == owner,
                ActionRun.recovery_lease_expires_at.is_(None),
                ActionRun.recovery_lease_expires_at <= now,
            ),
        ]
        if candidate.status == "executing":
            predicates.append(
                or_(ActionRun.lease_expires_at.is_(None), ActionRun.lease_expires_at <= now)
            )
        async with self.session_factory() as session:
            result = await session.execute(
                update(ActionRun)
                .where(*predicates)
                .values(
                    recovery_owner=owner,
                    recovery_lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    state_version=ActionRun.state_version + 1,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                await session.rollback()
                governance_telemetry.record_recovery("skipped")
                return None
            await session.commit()
        return candidate.state_version + 1
    async def _recover_candidate(
        self, candidate: _Candidate, owner: str
    ) -> RecoveryOutcome:
        claimed_version = await self._claim(candidate, owner)
        if claimed_version is None:
            return RecoveryOutcome(candidate.run_id, owner, None, "RECOVERY_CLAIM_CONFLICT")
        pending = candidate.result_summary.get("recovery_observation")
        if (
            isinstance(pending, Mapping)
            and pending.get("schema_version") == RECOVERY_SCHEMA
            and pending.get("terminal_candidate") != candidate.status
        ):
            return await self._write_terminal(
                candidate,
                owner,
                claimed_version,
                str(pending["terminal_candidate"]),
                pending,
            )
        try:
            observation = self._normalize_observation(
                candidate, await self.change_port.verify_change(candidate.run_id)
            )
        except Exception:
            observation = self._error_observation(candidate, "RECOVERY_VERIFIER_ERROR")
        terminal, terminal_observation = await self._classify(
            candidate, observation
        )
        if terminal is None:
            return RecoveryOutcome(
                candidate.run_id, owner, None, "RECOVERY_OBSERVATION_UNCHANGED"
            )
        persisted_version = await self._persist_terminal_candidate(
            candidate, owner, claimed_version, terminal_observation
        )
        if persisted_version is None:
            return RecoveryOutcome(
                candidate.run_id, owner, None, "RECOVERY_CANDIDATE_CAS_CONFLICT"
            )
        return await self._write_terminal(
            candidate,
            owner,
            persisted_version,
            terminal,
            terminal_observation,
        )
    async def _persist_terminal_candidate(
        self,
        candidate: _Candidate,
        owner: str,
        expected_version: int,
        observation: Mapping[str, Any],
    ) -> int | None:
        summary = dict(candidate.result_summary)
        summary["recovery_observation"] = dict(observation)
        async with self.session_factory() as session:
            result = await session.execute(
                update(ActionRun)
                .where(
                    ActionRun.run_id == candidate.run_id,
                    ActionRun.status == candidate.status,
                    ActionRun.state_version == expected_version,
                    ActionRun.recovery_owner == owner,
                )
                .values(
                    result_summary=bindparam(
                        "candidate_summary",
                        type_=JSON,
                    ),
                    state_version=ActionRun.state_version + 1,
                    updated_at=utc_now(),
                ),
                {"candidate_summary": summary},
            )
            if result.rowcount != 1:
                await session.rollback()
                return None
            await session.commit()
        return expected_version + 1
    async def _classify(
        self, candidate: _Candidate, observation: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any]]:
        verification = observation["verification_status"]
        if candidate.status == "executing":
            terminal = {
                "no_effect": "failed",
                "effect_matches": "succeeded",
                "effect_partial": "partially_failed",
                "effect_unknown": "outcome_unknown",
                "external_modified": "outcome_unknown",
                "error": "outcome_unknown",
            }[verification]
            return terminal, observation
        previous = candidate.result_summary.get("recovery_observation")
        previous_evidence = (
            previous.get("evidence_digest") if isinstance(previous, Mapping) else None
        )
        if candidate.status == "outcome_unknown":
            if previous_evidence == observation["evidence_digest"]:
                return None, observation
            terminal = {
                "no_effect": "failed",
                "effect_matches": "recovered",
                "effect_partial": "recovery_blocked",
                "effect_unknown": "recovery_blocked",
                "external_modified": "recovery_blocked",
                "error": "recovery_blocked",
            }[verification]
            observation["terminal_candidate"] = terminal
            return terminal, observation
        if verification == "no_effect":
            observation["terminal_candidate"] = "recovered"
            return "recovered", observation
        if verification in {"external_modified", "error", "effect_unknown"}:
            observation["terminal_candidate"] = "recovery_blocked"
            return "recovery_blocked", observation
        if self.before_recover is not None:
            result = self.before_recover(candidate.run_id)
            if inspect.isawaitable(result):
                await result
        fence = RecoveryFence(
            run_id=candidate.run_id,
            execution_generation=candidate.execution_generation,
            object_revision_observed=str(observation["object_revision_observed"]),
            object_digest_observed=str(observation["object_digest_observed"]),
        )
        try:
            recovered = self._normalize_observation(
                candidate,
                await self.change_port.recover_change(candidate.run_id, fence),
            )
        except Exception:
            recovered = self._error_observation(candidate, "RECOVERY_WRITE_ERROR")
        if (
            recovered["verification_status"] == "external_modified"
            or recovered.get("terminal_candidate") == "recovery_blocked"
        ):
            recovered["terminal_candidate"] = "recovery_blocked"
            return "recovery_blocked", recovered
        if (
            recovered["verification_status"] == "no_effect"
            or recovered.get("terminal_candidate") == "recovered"
        ):
            recovered["terminal_candidate"] = "recovered"
            return "recovered", recovered
        recovered["terminal_candidate"] = "recovery_blocked"
        return "recovery_blocked", recovered
    async def _write_terminal(
        self,
        candidate: _Candidate,
        owner: str,
        claimed_version: int,
        terminal: str,
        observation: Mapping[str, Any],
    ) -> RecoveryOutcome:
        now = utc_now()
        summary = dict(candidate.result_summary)
        summary["recovery_observation"] = dict(observation)
        error_code = _terminal_error_code(terminal, observation)
        async with self.session_factory() as session:
            if candidate.ticket_id is not None:
                await session.execute(
                    update(ActionTicket)
                    .where(
                        ActionTicket.ticket_id == candidate.ticket_id,
                        ActionTicket.status == "reserved",
                    )
                    .values(
                        status="consumed",
                        state_version=ActionTicket.state_version + 1,
                        updated_at=now,
                    )
                )
            result = await session.execute(
                update(ActionRun)
                .where(
                    ActionRun.run_id == candidate.run_id,
                    ActionRun.status == candidate.status,
                    ActionRun.state_version == claimed_version,
                    ActionRun.recovery_owner == owner,
                )
                .values(
                    status=terminal,
                    result_status=terminal,
                    result_summary=bindparam(
                        "recovery_summary_payload",
                        type_=JSON,
                    ),
                    error_code=error_code,
                    finished_at=now,
                    state_version=ActionRun.state_version + 1,
                    updated_at=now,
                ),
                {"recovery_summary_payload": summary},
            )
            if result.rowcount != 1:
                await session.rollback()
                governance_telemetry.record_recovery("skipped")
                return RecoveryOutcome(
                    candidate.run_id, owner, None, "RECOVERY_TERMINAL_CAS_CONFLICT"
                )
            try:
                if self.terminal_commit is None:
                    await session.commit()
                else:
                    await self.terminal_commit(session)
            except Exception:
                await session.rollback()
                governance_telemetry.record_recovery("failure")
                return RecoveryOutcome(
                    candidate.run_id, owner, None, "RECOVERY_TERMINAL_COMMIT_FAILED"
                )
        governance_telemetry.record_run_transition(
            terminal,
            candidate.capability_id,
            run_id=f"{candidate.run_id}:{terminal}",
            cas_won=True,
        )
        governance_telemetry.record_recovery(
            "blocked" if terminal == "recovery_blocked" else "recovered"
        )
        return RecoveryOutcome(candidate.run_id, owner, terminal, error_code)
    def _normalize_observation(
        self, candidate: _Candidate, raw: Mapping[str, Any]
    ) -> dict[str, Any]:
        observation = dict(raw)
        if observation.get("schema_version") != RECOVERY_SCHEMA:
            raise ValueError("unsupported recovery observation")
        if observation.get("effect_state") not in _EFFECT_STATES:
            raise ValueError("unsupported effect state")
        if observation.get("verification_status") not in _VERIFICATIONS:
            raise ValueError("unsupported verification status")
        required = (
            "observed_at",
            "object_revision_before",
            "object_revision_observed",
            "object_digest_observed",
            "manifest_state",
            "evidence_digest",
            "terminal_candidate",
        )
        if any(key not in observation for key in required):
            raise ValueError("incomplete recovery observation")
        observation.setdefault("verifier_error_code", None)
        return {
            key: observation[key]
            for key in (
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
            )
        }
    def _error_observation(
        self, candidate: _Candidate, error_code: str
    ) -> dict[str, Any]:
        evidence = hashlib.sha256(
            f"{candidate.run_id}|{error_code}".encode("utf-8")
        ).hexdigest()
        return {
            "schema_version": RECOVERY_SCHEMA,
            "observed_at": utc_now().isoformat(),
            "object_revision_before": candidate.object_revision,
            "object_revision_observed": candidate.object_revision,
            "object_digest_observed": evidence,
            "manifest_state": "unknown",
            "effect_state": "unknown",
            "verification_status": "error",
            "verifier_error_code": error_code,
            "evidence_digest": evidence,
            "terminal_candidate": "outcome_unknown",
        }
def _terminal_error_code(terminal: str, observation: Mapping[str, Any]) -> str | None:
    verifier_code = observation.get("verifier_error_code")
    if terminal in {"succeeded", "recovered"}:
        return None
    if terminal == "failed":
        return str(verifier_code or "RECOVERY_NO_EFFECT")
    if terminal == "partially_failed":
        return str(verifier_code or "RECOVERY_EFFECT_PARTIAL")
    if terminal == "recovery_blocked":
        return str(verifier_code or "RECOVERY_BLOCKED")
    return str(verifier_code or "RECOVERY_OUTCOME_UNKNOWN")
async def run_startup_recovery_scan(
    session_factory: async_sessionmaker[AsyncSession],
    change_port: ChangeRecoveryPort | None,
    *,
    policy: str,
    timeout_seconds: float,
    lease_seconds: int = 30,
) -> RecoveryHealth:
    """Run one non-blocking startup scan; shadow failures only degrade health."""
    if change_port is None:
        status = "degraded" if policy == "shadow" else "healthy"
        return RecoveryHealth(status, RECOVERY_VERIFIER_UNAVAILABLE)
    coordinator = RecoveryCoordinator(
        session_factory, change_port, lease_seconds=lease_seconds
    )
    try:
        report = await asyncio.wait_for(
            coordinator.scan(owner=f"startup-{uuid4()}"), timeout=timeout_seconds
        )
    except TimeoutError:
        governance_telemetry.record_recovery("failure")
        log_governance_event(
            "system_assistant_recovery_scan_timeout",
            error_code=RECOVERY_SCAN_TIMEOUT,
        )
        return RecoveryHealth("degraded", RECOVERY_SCAN_TIMEOUT)
    except Exception:
        governance_telemetry.record_recovery("failure")
        log_governance_event(
            "system_assistant_recovery_scan_failed",
            error_code="SYSTEM_ASSISTANT_RECOVERY_SCAN_FAILED",
        )
        return RecoveryHealth("degraded", "SYSTEM_ASSISTANT_RECOVERY_SCAN_FAILED")
    return RecoveryHealth("healthy", scanned_count=len(report.outcomes))
async def run_configured_startup_recovery_scan(
    app: Any,
    *,
    policy: str,
    session_factory: async_sessionmaker[AsyncSession] | None,
    change_port: ChangeRecoveryPort | None,
    timeout_seconds: float = 5.0,
    lease_seconds: int = 30,
) -> RecoveryHealth:
    """Publish startup recovery health without creating a readiness gate."""
    if policy != "shadow":
        health = RecoveryHealth("healthy")
    elif session_factory is None or change_port is None:
        health = RecoveryHealth("degraded", RECOVERY_VERIFIER_UNAVAILABLE)
    else:
        health = await run_startup_recovery_scan(
            session_factory,
            change_port,
            policy=policy,
            timeout_seconds=timeout_seconds,
            lease_seconds=lease_seconds,
        )
    app.state.system_assistant_recovery_health = health
    return health
