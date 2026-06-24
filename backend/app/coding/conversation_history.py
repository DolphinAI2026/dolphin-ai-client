"""对话历史 helper(中立模块)。

从 pipeline.py 迁出:read_query 等非流水线代码也要用,退役 coding 流水线时
这个 helper 必须留下。pipeline.py 现 re-export 本函数(零破坏)。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message


async def get_conversation_history(db: AsyncSession, conversation_id: int) -> list:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [
        {"role": m.role, "content": m.content}
        for m in messages
        if m.role in ("user", "assistant")
    ]
