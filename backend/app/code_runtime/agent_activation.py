"""Per-binding transaction boundary for Runtime agent activation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from weakref import WeakValueDictionary

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.models.ai_chat import CodeRuntimeBinding


_sqlite_activation_locks: WeakValueDictionary[tuple[int, str], asyncio.Lock] = (
    WeakValueDictionary()
)
logger = logging.getLogger(__name__)


def runtime_activation_scope(binding: CodeRuntimeBinding) -> str:
    runtime_instance = str(
        binding.sandbox_instance_id or binding.runtime_base_url or binding.builder_url or ""
    ).strip().rstrip("/").casefold()
    return f"{int(binding.tenant_id)}:{int(binding.user_id)}:{runtime_instance}"


def _lock_name(scope: str) -> str:
    return f"code-runtime:{hashlib.sha256(scope.encode('utf-8')).hexdigest()[:48]}"


def _sqlite_activation_lock(scope: str) -> asyncio.Lock:
    key = (id(asyncio.get_running_loop()), scope)
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

    initial_binding = await _locked_binding(db, binding_id, lock_row=False)
    scope = runtime_activation_scope(initial_binding)
    dialect_name = db.bind.dialect.name if db.bind is not None else ""
    if dialect_name == "sqlite":
        if db.in_transaction():
            await _commit_or_rollback(db)
        lock = _sqlite_activation_lock(scope)
        async with lock:
            try:
                await db.execute(text("BEGIN IMMEDIATE"))
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

    mysql_lock_name = _lock_name(scope)
    mysql_connection: AsyncConnection | None = None
    mysql_lock_acquired = False
    primary_error: BaseException | None = None
    try:
        if dialect_name == "postgresql":
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
                {"scope": scope},
            )
        else:
            if db.bind is None or not hasattr(db.bind, "connect"):
                raise RuntimeError(
                    "MySQL Runtime activation lock requires an AsyncEngine-bound session"
                )
            mysql_connection = await db.bind.connect()
            acquired = (
                await mysql_connection.execute(
                    text("SELECT GET_LOCK(:lock_name, 120)"),
                    {"lock_name": mysql_lock_name},
                )
            ).scalar_one()
            if int(acquired or 0) != 1:
                raise RuntimeError("Timed out acquiring shared Runtime activation lock")
            mysql_lock_acquired = True
        binding = await _locked_binding(db, binding_id, lock_row=True)
        yield binding
        await _commit_or_rollback(db)
    except BaseException as exc:
        primary_error = exc
        await db.rollback()
        raise
    finally:
        if mysql_connection is not None:
            release_error: BaseException | None = None
            try:
                if mysql_lock_acquired:
                    await mysql_connection.execute(
                        text("SELECT RELEASE_LOCK(:lock_name)"),
                        {"lock_name": mysql_lock_name},
                    )
            except BaseException as exc:
                release_error = exc
                try:
                    await mysql_connection.invalidate()
                except BaseException:
                    logger.exception("Failed to invalidate MySQL Runtime activation lock connection")
            finally:
                try:
                    await mysql_connection.close()
                except BaseException:
                    logger.exception("Failed to close MySQL Runtime activation lock connection")
            if release_error is not None:
                if primary_error is None:
                    raise RuntimeError("Failed to release shared Runtime activation lock") from release_error
                logger.error(
                    "Failed to release shared Runtime activation lock while handling another error",
                    exc_info=release_error,
                )
