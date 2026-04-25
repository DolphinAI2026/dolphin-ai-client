"""Webhook 事件 → Builder 状态变更（Task 1: stub；Task 2 实现完整 handlers）"""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collaboration import GitConnection
from app.git.webhook import WebhookEvent


async def dispatch_webhook_event(
    db: AsyncSession, *, conn: GitConnection, event: WebhookEvent,
) -> None:
    """Stub — Task 2 替换为完整 dispatcher"""
    pass
