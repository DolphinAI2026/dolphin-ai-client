"""应用级并发锁

防止同一应用的并发操作互相踩踏。

使用方式：
    async with acquire_app_lock(app_id):
        # 执行对该应用的修改操作
        ...

锁被占用时抛出 AppLockError（HTTP 409）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Dict

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# 锁超时：30 秒后自动释放（防止进程崩溃后死锁）
LOCK_TIMEOUT_SECONDS = 30


class AppLockError(HTTPException):
    """应用正在被其他操作修改"""

    def __init__(self, app_id: int):
        super().__init__(
            status_code=409,
            detail=f"应用 {app_id} 正在被其他操作修改中，请稍后重试"
        )


class _AppLockEntry:
    """单个应用的锁条目"""
    __slots__ = ("lock", "acquired_at", "holder")

    def __init__(self):
        self.lock = asyncio.Lock()
        self.acquired_at: float = 0
        self.holder: str = ""


# 全局锁注册表
_registry: Dict[int, _AppLockEntry] = {}
_registry_lock = asyncio.Lock()


async def _get_entry(app_id: int) -> _AppLockEntry:
    """获取或创建应用锁条目"""
    async with _registry_lock:
        if app_id not in _registry:
            _registry[app_id] = _AppLockEntry()
        return _registry[app_id]


def _is_stale(entry: _AppLockEntry) -> bool:
    """检查锁是否已超时（stale）"""
    if entry.acquired_at == 0:
        return False
    return (time.monotonic() - entry.acquired_at) > LOCK_TIMEOUT_SECONDS


@asynccontextmanager
async def acquire_app_lock(app_id: int, operation: str = ""):
    """尝试获取应用级锁。

    如果锁被占用且未超时，立即抛出 AppLockError（HTTP 409）。
    如果锁已超时（stale），强制释放并重新获取。

    用法：
        async with acquire_app_lock(app_id, "步骤执行"):
            ...
    """
    entry = await _get_entry(app_id)

    # 尝试非阻塞获取
    if entry.lock.locked():
        # 检查是否超时
        if _is_stale(entry):
            logger.warning(
                f"应用 {app_id} 的锁已超时（持有者: {entry.holder}，"
                f"已持有 {time.monotonic() - entry.acquired_at:.1f}s），强制释放"
            )
            # 强制释放 stale lock
            try:
                entry.lock.release()
            except RuntimeError:
                # 可能已经被释放了
                pass
        else:
            raise AppLockError(app_id)

    # 获取锁
    acquired = False
    try:
        # 用很短的等待时间尝试获取，避免竞态
        try:
            await asyncio.wait_for(entry.lock.acquire(), timeout=0.5)
            acquired = True
        except asyncio.TimeoutError:
            raise AppLockError(app_id)

        entry.acquired_at = time.monotonic()
        entry.holder = operation or "unknown"
        logger.debug(f"应用 {app_id} 锁已获取: {entry.holder}")

        yield

    finally:
        if acquired:
            entry.acquired_at = 0
            entry.holder = ""
            try:
                entry.lock.release()
            except RuntimeError:
                pass
            logger.debug(f"应用 {app_id} 锁已释放")


async def cleanup_stale_locks():
    """清理超时的锁条目（可定期调用）"""
    async with _registry_lock:
        stale_ids = [
            app_id for app_id, entry in _registry.items()
            if _is_stale(entry)
        ]
        for app_id in stale_ids:
            entry = _registry[app_id]
            logger.warning(f"清理超时锁: app_id={app_id}, holder={entry.holder}")
            try:
                entry.lock.release()
            except RuntimeError:
                pass
            entry.acquired_at = 0
            entry.holder = ""
