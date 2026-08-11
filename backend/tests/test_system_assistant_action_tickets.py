"""TASK-006 ticket CAS contract tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.system_assistant_governance import ActionTicket
from app.system_assistant.action_store import reserve_ticket
from tests.test_system_assistant_execution_fence import _make_store, _seed


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_authorized_ticket_reserve_increments_version_once(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "ticket-reserve.sqlite3")
    try:
        await _seed(session_factory)
        async with session_factory() as session:
            assert await reserve_ticket(
                session,
                "ticket-006",
                expected_state_version=1,
                now=_now(),
            )
            await session.commit()
            assert not await reserve_ticket(
                session,
                "ticket-006",
                expected_state_version=1,
                now=_now(),
            )
            await session.rollback()
            ticket = await session.get(ActionTicket, "ticket-006")
            assert (ticket.status, ticket.state_version) == ("reserved", 2)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_expired_authorized_ticket_cannot_be_reserved(tmp_path):
    engine, session_factory = await _make_store(tmp_path / "ticket-expired.sqlite3")
    try:
        await _seed(session_factory)
        async with session_factory() as session:
            ticket = await session.get(ActionTicket, "ticket-006")
            ticket.expires_at = _now() - timedelta(seconds=1)
            await session.commit()
            assert not await reserve_ticket(
                session,
                "ticket-006",
                expected_state_version=1,
                now=_now(),
            )
            await session.rollback()
            ticket = await session.get(ActionTicket, "ticket-006")
            assert ticket.status == "authorized"
    finally:
        await engine.dispose()
