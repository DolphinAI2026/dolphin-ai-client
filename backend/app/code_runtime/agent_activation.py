"""Per-binding transaction boundary for Runtime agent activation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from weakref import WeakValueDictionary

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_chat import CodeRuntimeBinding


_sqlite_activation_locks: WeakValueDictionary[tuple[int, int], asyncio.Lock] = (
    WeakValueDictionary()
)


def _sqlite_activation_lock(binding_id: int) -> asyncio.Lock:
    key = (id(asyncio.get_running_loop()), int(binding_id))
    lock = _sqlite_activation_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _sqlite_activation_locks[key] = lock
    return lock


async def _locked_binding(
    db: AsyncSession,
    binding_id: int,
    *,
    lock_row: bool,
) -> CodeRuntimeBinding:
    statement = select(CodeRuntimeBinding).where(CodeRuntimeBinding.id == int(binding_id))
    if lock_row:
        statement = statement.with_for_update()
    binding = (
        await db.execute(statement.execution_options(populate_existing=True))
    ).scalar_one_or_none()
    if binding is None:
        raise RuntimeError("Code runtime binding disappeared during agent activation")
    return binding


async def _commit_or_rollback(db: AsyncSession) -> None:
    try:
        await db.commit()
    except BaseException:
        await db.rollback()
        raise


@asynccontextmanager
async def code_runtime_agent_activation_transaction(
    db: AsyncSession,
    binding_id: int,
) -> AsyncIterator[CodeRuntimeBinding]:
    """Serialize Runtime activation through the binding update and snapshot commit."""

    dialect_name = db.bind.dialect.name if db.bind is not None else ""
    if dialect_name == "sqlite":
        if db.in_transaction():
            await _commit_or_rollback(db)
        lock = _sqlite_activation_lock(binding_id)
        async with lock:
            try:
                binding = await _locked_binding(db, binding_id, lock_row=False)
                yield binding
                await _commit_or_rollback(db)
            except BaseException:
                await db.rollback()
                raise
        return

    if dialect_name not in {"postgresql", "mysql"}:
        raise RuntimeError(
            "Code runtime agent activation locking is unsupported for database "
            f"dialect: {dialect_name or 'unknown'}"
        )

    try:
        binding = await _locked_binding(db, binding_id, lock_row=True)
        yield binding
        await _commit_or_rollback(db)
    except BaseException:
        await db.rollback()
        raise
