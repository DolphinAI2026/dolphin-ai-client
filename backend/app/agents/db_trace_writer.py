"""DbTraceWriter — 把 agent 内部 trace 写入 agent_traces 表。"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_models import AgentTrace

logger = logging.getLogger(__name__)


class DbTraceWriter:
    """基于数据库的 TraceWriter 实现。

    (session_type, session_id) 共享一个 seq counter，首次写入前从 DB 查最大值。
    """

    def __init__(self) -> None:
        self._counters: dict[tuple[str, str], int] = {}
        self._loaded: set[tuple[str, str]] = set()

    async def _ensure_seq_loaded(
        self, session_type: str, session_id: str, db: AsyncSession,
    ) -> None:
        key = (session_type, session_id)
        if key in self._loaded:
            return
        result = await db.execute(
            select(func.max(AgentTrace.seq)).where(
                AgentTrace.session_type == session_type,
                AgentTrace.session_id == session_id,
            )
        )
        max_seq = result.scalar() or 0
        self._counters[key] = max_seq
        self._loaded.add(key)

    async def write(
        self,
        *,
        session_type: str,
        session_id: str,
        turn: int,
        event_type: str,
        payload: dict[str, Any],
        tokens_input: Optional[int] = None,
        tokens_output: Optional[int] = None,
        duration_ms: Optional[int] = None,
        model: Optional[str] = None,
        db: AsyncSession,
    ) -> str:
        """写入一条 trace。返回 trace id。

        db 参数是扩展（Protocol 里没有，agent 代码通过 ctx.db 传入）。
        """
        await self._ensure_seq_loaded(session_type, session_id, db)
        key = (session_type, session_id)
        self._counters[key] += 1
        seq = self._counters[key]

        trace_id = uuid.uuid4().hex
        row = AgentTrace(
            id=trace_id,
            session_type=session_type,
            session_id=session_id,
            seq=seq,
            turn=turn,
            event_type=event_type,
            payload=payload or {},
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            duration_ms=duration_ms,
            model=model,
        )
        db.add(row)
        try:
            await db.commit()
        except Exception as e:
            logger.error("Failed to persist agent_trace: %s", e)
            await db.rollback()
            self._counters[key] -= 1
            raise
        return trace_id


class ScopedDbTraceWriter:
    """满足 TraceWriter Protocol 的 adapter — 绑定一个 DB session。"""

    def __init__(self, writer: "DbTraceWriter", db: AsyncSession) -> None:
        self._writer = writer
        self._db = db

    async def write(
        self,
        *,
        session_type: str,
        session_id: str,
        turn: int,
        event_type: str,
        payload: dict[str, Any],
        tokens_input: Optional[int] = None,
        tokens_output: Optional[int] = None,
        duration_ms: Optional[int] = None,
        model: Optional[str] = None,
    ) -> str:
        return await self._writer.write(
            session_type=session_type,
            session_id=session_id,
            turn=turn,
            event_type=event_type,
            payload=payload,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            duration_ms=duration_ms,
            model=model,
            db=self._db,
        )


def _make_scoped_writer(writer: "DbTraceWriter", db: AsyncSession) -> ScopedDbTraceWriter:
    return ScopedDbTraceWriter(writer, db)


DbTraceWriter.scoped = _make_scoped_writer  # type: ignore[attr-defined]


# 进程级单例
_writer_instance: DbTraceWriter | None = None


def get_db_trace_writer() -> DbTraceWriter:
    global _writer_instance
    if _writer_instance is None:
        _writer_instance = DbTraceWriter()
    return _writer_instance
