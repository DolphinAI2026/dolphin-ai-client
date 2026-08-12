"""Durable SQLite oracle for TASK-009 recovery tests."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import JSON, bindparam, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.system_assistant_governance import ActionRun, ActionTicket


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _digest(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class DurableCounts:
    effect_count: int
    recovery_count: int


class DurableRecoveryStore:
    """File-backed action, object, effect-ledger and fault-barrier store."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fault_path = path.with_suffix(".faults.sqlite3")
        self.engine = None
        self.session_factory = None

    async def open(self) -> "DurableRecoveryStore":
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.path}", connect_args={"timeout": 30}
        )
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(ActionTicket.__table__.create, checkfirst=True)
            await connection.run_sync(ActionRun.__table__.create, checkfirst=True)
            await connection.execute(text("""
                CREATE TABLE IF NOT EXISTS recovery_test_objects (
                    object_ref TEXT PRIMARY KEY,
                    revision TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    base_revision TEXT NOT NULL,
                    base_digest TEXT NOT NULL
                )
            """))
            await connection.execute(text("""
                CREATE TABLE IF NOT EXISTS recovery_test_effect_ledger (
                    run_id TEXT PRIMARY KEY,
                    effect_state TEXT NOT NULL,
                    effect_count INTEGER NOT NULL,
                    recovery_count INTEGER NOT NULL,
                    effect_digest TEXT NOT NULL
                )
            """))
        with sqlite3.connect(self.fault_path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS commit_faults "
                "(fault_name TEXT PRIMARY KEY, remaining INTEGER NOT NULL)"
            )
        return self

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
        self.engine = None
        self.session_factory = None

    async def seed_run(
        self,
        run_id: str,
        *,
        effect_state: str,
        manifest_state: str = "uncommitted",
        status: str = "executing",
    ) -> None:
        assert self.session_factory is not None
        object_ref = f"application:{run_id}"
        effect_count = 0 if effect_state == "none" else 1
        revision = "revision-1" if effect_state == "none" else f"revision-{effect_state}"
        object_digest = _digest(run_id, revision, effect_state)
        effect_digest = _digest(run_id, effect_state, "effect")
        async with self.session_factory() as session:
            ticket = ActionTicket(
                ticket_id=f"ticket-{run_id}",
                tenant_id=7,
                control_plane_tenant_id="cp-7",
                user_id=5,
                session_public_id="s" * 36,
                object_ref=object_ref,
                action_kind="project_result",
                args_digest="a" * 64,
                object_revision="revision-1",
                policy_revision=1,
                status="reserved",
                expires_at=_now() + timedelta(minutes=5),
                correlation_id=f"corr-{run_id}"[:36],
                state_version=1,
            )
            run = ActionRun(
                run_id=run_id,
                ticket_id=ticket.ticket_id,
                capability_id="system_assistant.project_result",
                action_kind=ticket.action_kind,
                object_ref=object_ref,
                status=status,
                args_digest=ticket.args_digest,
                object_revision="revision-1",
                policy_revision=1,
                execution_generation=1,
                lease_owner="execution-owner",
                lease_expires_at=_now() - timedelta(seconds=1),
                base_state={"schema_version": "v1", "object_revision": "revision-1"},
                change_manifest={},
                result_summary={},
                correlation_id=ticket.correlation_id,
                audit_delivery_status="not_required",
                state_version=0,
            )
            session.add_all([ticket, run])
            await session.flush()
            manifest = {
                "schema_version": "RecoveryObservation/v1",
                "commit_state": manifest_state,
                "operations_digest": _digest(run_id, "operations"),
                "effect_digest": effect_digest,
                "manifest_revision": "manifest-1",
            }
            statement = (
                update(ActionRun)
                .where(ActionRun.run_id == run_id)
                .values(change_manifest=bindparam("manifest", type_=JSON))
            )
            await session.execute(statement, {"manifest": manifest})
            await session.execute(
                text("""
                    INSERT INTO recovery_test_objects
                        (object_ref, revision, digest, base_revision, base_digest)
                    VALUES (:object_ref, :revision, :digest, 'revision-1', :base_digest)
                """),
                {
                    "object_ref": object_ref,
                    "revision": revision,
                    "digest": object_digest,
                    "base_digest": _digest(run_id, "revision-1", "none"),
                },
            )
            await session.execute(
                text("""
                    INSERT INTO recovery_test_effect_ledger
                        (run_id, effect_state, effect_count, recovery_count, effect_digest)
                    VALUES (:run_id, :effect_state, :effect_count, 0, :effect_digest)
                """),
                {
                    "run_id": run_id,
                    "effect_state": effect_state,
                    "effect_count": effect_count,
                    "effect_digest": effect_digest,
                },
            )
            await session.commit()

    async def read_run(self, run_id: str) -> ActionRun:
        assert self.session_factory is not None
        async with self.session_factory() as session:
            run = await session.get(ActionRun, run_id)
            assert run is not None
            session.expunge(run)
            return run

    async def counts(self, run_id: str) -> DurableCounts:
        assert self.session_factory is not None
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    text("""
                        SELECT effect_count, recovery_count
                        FROM recovery_test_effect_ledger WHERE run_id = :run_id
                    """),
                    {"run_id": run_id},
                )
            ).one()
            return DurableCounts(int(row.effect_count), int(row.recovery_count))

    async def set_effect_state(self, run_id: str, effect_state: str) -> None:
        assert self.session_factory is not None
        revision = "revision-1" if effect_state == "none" else f"revision-{effect_state}"
        async with self.session_factory() as session:
            object_ref = await session.scalar(
                text("SELECT object_ref FROM system_assistant_action_runs WHERE run_id=:run_id"),
                {"run_id": run_id},
            )
            await session.execute(
                text("""
                    UPDATE recovery_test_effect_ledger
                    SET effect_state=:effect_state, effect_digest=:effect_digest
                    WHERE run_id=:run_id
                """),
                {
                    "run_id": run_id,
                    "effect_state": effect_state,
                    "effect_digest": _digest(run_id, effect_state, "effect"),
                },
            )
            await session.execute(
                text("""
                    UPDATE recovery_test_objects SET revision=:revision, digest=:digest
                    WHERE object_ref=:object_ref
                """),
                {
                    "object_ref": object_ref,
                    "revision": revision,
                    "digest": _digest(run_id, revision, effect_state),
                },
            )
            await session.commit()

    async def external_modify(self, run_id: str) -> None:
        assert self.session_factory is not None
        async with self.session_factory() as session:
            object_ref = await session.scalar(
                text("SELECT object_ref FROM system_assistant_action_runs WHERE run_id=:run_id"),
                {"run_id": run_id},
            )
            await session.execute(
                text("""
                    UPDATE recovery_test_objects
                    SET revision='external-revision', digest=:digest
                    WHERE object_ref=:object_ref
                """),
                {"object_ref": object_ref, "digest": _digest(run_id, "external")},
            )
            await session.commit()

    async def expire_recovery_lease(self, run_id: str) -> None:
        assert self.session_factory is not None
        async with self.session_factory() as session:
            await session.execute(
                text("""
                    UPDATE system_assistant_action_runs
                    SET recovery_lease_expires_at=:expired
                    WHERE run_id=:run_id
                """),
                {"run_id": run_id, "expired": _now() - timedelta(seconds=1)},
            )
            await session.commit()

    def arm_commit_failure(self, fault_name: str = "terminal") -> None:
        with sqlite3.connect(self.fault_path) as connection:
            connection.execute(
                "INSERT INTO commit_faults(fault_name, remaining) VALUES (?, 1) "
                "ON CONFLICT(fault_name) DO UPDATE SET remaining=1",
                (fault_name,),
            )

    async def commit_with_durable_fault(
        self, session: AsyncSession, fault_name: str = "terminal"
    ) -> None:
        with sqlite3.connect(self.fault_path) as connection:
            row = connection.execute(
                "SELECT remaining FROM commit_faults WHERE fault_name=?", (fault_name,)
            ).fetchone()
            if row and int(row[0]) > 0:
                connection.execute(
                    "UPDATE commit_faults SET remaining=remaining-1 WHERE fault_name=?",
                    (fault_name,),
                )
                raise RuntimeError("durable terminal commit fault")
        await session.commit()


class DurableChangePort:
    """Object-neutral port rebuilt from only the durable SQLite path."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self, run_id: str):
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute("""
                SELECT r.object_revision AS before_revision, r.change_manifest,
                       o.revision, o.digest, l.effect_state, l.effect_digest
                FROM system_assistant_action_runs r
                JOIN recovery_test_objects o ON o.object_ref=r.object_ref
                JOIN recovery_test_effect_ledger l ON l.run_id=r.run_id
                WHERE r.run_id=?
            """, (run_id,)).fetchone()

    async def verify_change(self, run_id: str) -> dict[str, object]:
        row = self._read(run_id)
        assert row is not None
        manifest = json.loads(row["change_manifest"] or "{}")
        effect_state = str(row["effect_state"])
        verification = {
            "none": "no_effect",
            "present": "effect_matches",
            "partial": "effect_partial",
            "unknown": "effect_unknown",
        }[effect_state]
        terminal = {
            "no_effect": "failed",
            "effect_matches": "succeeded",
            "effect_partial": "partially_failed",
            "effect_unknown": "outcome_unknown",
        }[verification]
        evidence = _digest(
            run_id, row["revision"], row["digest"], effect_state,
            manifest.get("commit_state", "unknown"), row["effect_digest"],
        )
        return {
            "schema_version": "RecoveryObservation/v1",
            "observed_at": _now().isoformat(),
            "object_revision_before": row["before_revision"],
            "object_revision_observed": row["revision"],
            "object_digest_observed": row["digest"],
            "manifest_state": manifest.get("commit_state", "unknown"),
            "effect_state": effect_state,
            "verification_status": verification,
            "verifier_error_code": None,
            "evidence_digest": evidence,
            "terminal_candidate": terminal,
        }

    async def recover_change(self, run_id: str, fence) -> dict[str, object]:
        row = self._read(run_id)
        assert row is not None
        if (
            row["revision"] != fence.object_revision_observed
            or row["digest"] != fence.object_digest_observed
        ):
            observation = await self.verify_change(run_id)
            observation["verification_status"] = "external_modified"
            observation["verifier_error_code"] = "RECOVERY_EXTERNAL_MODIFICATION"
            observation["terminal_candidate"] = "recovery_blocked"
            return observation
        with sqlite3.connect(self.path) as connection:
            connection.execute("""
                UPDATE recovery_test_objects
                SET revision=base_revision, digest=base_digest
                WHERE object_ref=(SELECT object_ref FROM system_assistant_action_runs WHERE run_id=?)
            """, (run_id,))
            connection.execute("""
                UPDATE recovery_test_effect_ledger
                SET effect_state='none', recovery_count=recovery_count+1
                WHERE run_id=?
            """, (run_id,))
        observation = await self.verify_change(run_id)
        observation["terminal_candidate"] = "recovered"
        return observation
