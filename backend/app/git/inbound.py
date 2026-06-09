"""Webhook 事件入口。

旧变更流已下线，Git webhook 目前只保留接收和日志能力，避免旧的
spec 分支、外部 PR 或直连 merge 逻辑继续修改 Builder 状态。
"""
from __future__ import annotations
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collaboration import GitConnection
from app.git.webhook import WebhookEvent

logger = logging.getLogger(__name__)


async def dispatch_webhook_event(
    db: AsyncSession, *, conn: GitConnection, event: WebhookEvent,
) -> None:
    """记录 webhook 事件，不再触发状态流转。"""
    logger.info(
        "git webhook ignored after proposal flow removal: event=%s repo=%s branch=%s",
        event.event_type,
        event.repo_full_path,
        event.branch,
    )
