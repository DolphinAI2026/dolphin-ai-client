"""会话富回放的 DB 存取(按会话 merge, 不再互踩)。

写入是旁路: 任何失败只 warning, 不影响 pipeline 主流程。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation_replay import ConversationReplay

logger = logging.getLogger(__name__)

# 单会话回放上限(条): 防止长会话无限膨胀, 超出截尾保留最新
_MAX_REPLAY_MESSAGES = 2000


async def load_conversation_replay(db: AsyncSession, conversation_id: int) -> list[dict]:
    """读会话回放流。没有/解析失败 → []。"""
    if not conversation_id:
        return []
    try:
        res = await db.execute(
            select(ConversationReplay).where(ConversationReplay.conversation_id == conversation_id)
        )
        row = res.scalar_one_or_none()
        if not row:
            return []
        data = json.loads(row.stream_messages or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        logger.warning("读会话回放失败(忽略): conversation_id=%s", conversation_id, exc_info=True)
        return []


async def append_conversation_replay(
    db: AsyncSession,
    conversation_id: int,
    new_stream_messages: list[dict[str, Any]],
) -> None:
    """把本轮回放追加到会话回放(已有内容 + ─── 分隔 + 本轮), upsert。"""
    if not conversation_id or not new_stream_messages:
        return
    try:
        res = await db.execute(
            select(ConversationReplay).where(ConversationReplay.conversation_id == conversation_id)
        )
        row = res.scalar_one_or_none()
        merged: list[dict[str, Any]] = []
        if row:
            try:
                existing = json.loads(row.stream_messages or "[]")
                if isinstance(existing, list):
                    merged = [m for m in existing if isinstance(m, dict)]
            except Exception:
                merged = []
        if merged:
            merged.append({
                "type": "status",
                "content": "───",
                "timestamp": int(datetime.now().timestamp() * 1000),
            })
        merged.extend(m for m in new_stream_messages if isinstance(m, dict))
        merged = merged[-_MAX_REPLAY_MESSAGES:]
        payload = json.dumps(merged, ensure_ascii=False)
        if row:
            row.stream_messages = payload
        else:
            db.add(ConversationReplay(conversation_id=conversation_id, stream_messages=payload))
        await db.commit()
    except Exception:
        logger.warning("写会话回放失败(忽略): conversation_id=%s", conversation_id, exc_info=True)
