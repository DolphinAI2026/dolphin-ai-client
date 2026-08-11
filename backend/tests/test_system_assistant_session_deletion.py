"""TASK-007 delete/execute barriers for governed system-assistant sessions."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    AIChatArtifact,
    AIChatAttachment,
    AIChatMessage,
    AIChatSession,
    AIChatToolCall,
)
from app.models.system_assistant_governance import ActionRun, ActionTicket
from app.system_assistant.action_execution import execute_with_governance
from app.system_assistant.action_store import ActionCASConflict, reserve_ticket_and_run
from app.system_assistant.session_lifecycle import (
    ACTIVE_ACTION_ERROR_CODE,
    SessionHasActiveAction,
    delete_session_with_guard,
)
from app.routes import ai_chat


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _make_store(path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        from app.database import Base

        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _seed(session_factory, *, ticket_status: str = "authorized") -> tuple[int, str]:
    async with session_factory() as session:
        chat = AIChatSession(
            public_id="session-007",
            tenant_id=7,
            user_id=5,
            title="lifecycle",
            status="active",
        )
        session.add(chat)
        await session.flush()
        ticket = ActionTicket(
            ticket_id="ticket-007",
            tenant_id=7,
            control_plane_tenant_id="cp-7",
            user_id=5,
            session_id=chat.id,
            session_public_id=chat.public_id,
            object_ref="application:projected-result",
            action_kind="project_result",
            args_digest="a" * 64,
            object_revision="revision-1",
            policy_revision=1,
            status=ticket_status,
            expires_at=_now() + timedelta(minutes=5),
            correlation_id="corr-007",
            state_version=1,
        )
        run = ActionRun(
            run_id="run-007",
            ticket_id=ticket.ticket_id,
            capability_id="system_assistant.project_result",
            action_kind=ticket.action_kind,
            object_ref=ticket.object_ref,
            status="authorized",
            args_digest=ticket.args_digest,
            object_revision=ticket.object_revision,
            policy_revision=ticket.policy_revision,
            correlation_id=ticket.correlation_id,
            audit_delivery_status="not_required",
        )
        session.add_all(
            [
                ticket,
                run,
                AIChatMessage(session_id=chat.id, role="user", content="old"),
                AIChatToolCall(session_id=chat.id, tool_name="project_result"),
                AIChatAttachment(session_id=chat.id, filename="old.txt", kind="txt"),
                AIChatArtifact(session_id=chat.id, filename="old.md", format="md"),
            ]
        )
        await session.commit()
        return chat.id, chat.public_id


@pytest.mark.asyncio
async def test_delete_first_revokes_authorized_ticket_and_stale_execute_cas_does_not_call_handler(tmp_path):
    engine, factory = await _make_store(tmp_path / "delete-first.sqlite3")
    try:
        session_id, _ = await _seed(factory)
        stale_execute_ready = asyncio.Event()
        release_stale_execute = asyncio.Event()
        calls: list[str] = []

        async def stale_execute() -> str:
            stale_execute_ready.set()
            await release_stale_execute.wait()
            async with factory() as db:
                try:
                    await reserve_ticket_and_run(
                        db,
                        ticket_id="ticket-007",
                        run_id="run-007",
                        expected_ticket_state_version=1,
                        expected_run_state_version=0,
                        lease_owner="late-executor",
                        args_digest="a" * 64,
                        object_revision="revision-1",
                        correlation_id="corr-007",
                    )
                except ActionCASConflict:
                    await db.rollback()
                    return "cas_failed"
            calls.append("handler")
            return "handler_called"

        execute_task = asyncio.create_task(stale_execute())
        await stale_execute_ready.wait()
        async with factory() as delete_db:
            assert await delete_session_with_guard(delete_db, session_id) == {"ok": True}
        release_stale_execute.set()
        assert await execute_task == "cas_failed"
        assert calls == []

        async with factory() as db:
            assert await db.get(AIChatSession, session_id) is None
            ticket = await db.get(ActionTicket, "ticket-007")
            assert (ticket.status, ticket.session_id) == ("revoked", None)
            assert await db.get(ActionRun, "run-007") is not None
            assert not (
                await db.execute(
                    select(AIChatMessage).where(AIChatMessage.session_id == session_id)
                )
            ).scalars().all()
            assert not (
                await db.execute(
                    select(AIChatToolCall).where(AIChatToolCall.session_id == session_id)
                )
            ).scalars().all()
            assert not (
                await db.execute(
                    select(AIChatAttachment).where(AIChatAttachment.session_id == session_id)
                )
            ).scalars().all()
            assert not (
                await db.execute(
                    select(AIChatArtifact).where(AIChatArtifact.session_id == session_id)
                )
            ).scalars().all()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_execute_first_blocks_delete_after_commit_and_starts_only_governed_handler(tmp_path):
    engine, factory = await _make_store(tmp_path / "execute-first.sqlite3")
    try:
        session_id, _ = await _seed(factory)
        handler_entered = asyncio.Event()
        release_handler = asyncio.Event()
        calls: list[str] = []

        async def governed(_fence):
            calls.append("governed")
            handler_entered.set()
            await release_handler.wait()

        async def legacy():
            calls.append("legacy")

        async with factory() as execute_db:
            execute_task = asyncio.create_task(
                execute_with_governance(
                    execute_db,
                    ticket_id="ticket-007",
                    run_id="run-007",
                    governed_handler=governed,
                    legacy_handler=legacy,
                    expected_ticket_state_version=1,
                    expected_run_state_version=0,
                    lease_owner="executor",
                    args_digest="a" * 64,
                    object_revision="revision-1",
                    correlation_id="corr-007",
                )
            )
            await handler_entered.wait()
            async with factory() as delete_db:
                with pytest.raises(SessionHasActiveAction) as exc_info:
                    await delete_session_with_guard(delete_db, session_id)
            assert exc_info.value.code == ACTIVE_ACTION_ERROR_CODE
            release_handler.set()
            result = await execute_task
            assert result.governed_called is True
            assert result.legacy_called is False

        assert calls == ["governed"]
        async with factory() as db:
            assert await db.get(AIChatSession, session_id) is not None
            ticket = await db.get(ActionTicket, "ticket-007")
            run = await db.get(ActionRun, "run-007")
            assert (ticket.status, run.status) == ("reserved", "executing")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "run_status",
    ["executing", "partially_failed", "recovery_blocked", "outcome_unknown"],
)
async def test_delete_uses_distinct_ticket_and_run_blocking_predicates(
    tmp_path, run_status: str
):
    engine, factory = await _make_store(tmp_path / f"blocking-{run_status}.sqlite3")
    try:
        session_id, _ = await _seed(factory)
        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            run.status = run_status
            await db.commit()
        async with factory() as db:
            with pytest.raises(SessionHasActiveAction) as exc_info:
                await delete_session_with_guard(db, session_id)
        assert exc_info.value.code == ACTIVE_ACTION_ERROR_CODE
        async with factory() as db:
            assert await db.get(AIChatSession, session_id) is not None
            ticket = await db.get(ActionTicket, "ticket-007")
            assert (ticket.status, ticket.session_id) == ("authorized", session_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reserved_ticket_blocks_delete_even_when_run_is_not_executing(tmp_path):
    engine, factory = await _make_store(tmp_path / "reserved-ticket.sqlite3")
    try:
        session_id, _ = await _seed(factory, ticket_status="reserved")
        async with factory() as db:
            with pytest.raises(SessionHasActiveAction):
                await delete_session_with_guard(db, session_id)
        async with factory() as db:
            ticket = await db.get(ActionTicket, "ticket-007")
            assert ticket.status == "reserved"
            assert await db.get(AIChatSession, session_id) is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ai_chat_delete_route_returns_stable_409_error_code(tmp_path):
    engine, factory = await _make_store(tmp_path / "route-409.sqlite3")
    try:
        session_id, _ = await _seed(factory)
        async with factory() as db:
            run = await db.get(ActionRun, "run-007")
            run.status = "outcome_unknown"
            await db.commit()
        ctx = SimpleNamespace(user=SimpleNamespace(id=5), tenant_id=7)
        async with factory() as db:
            with pytest.raises(HTTPException) as exc_info:
                await ai_chat.delete_session(session_id, ctx=ctx, db=db)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == {"code": ACTIVE_ACTION_ERROR_CODE}
    finally:
        await engine.dispose()
