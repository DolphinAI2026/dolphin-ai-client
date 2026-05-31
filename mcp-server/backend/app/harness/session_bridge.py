"""Harness Core — 会话桥接（新 harness 表 ↔ 旧 Conversation/Message 表）"""
import json
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message
from app.harness.models import HarnessThread

logger = logging.getLogger(__name__)


async def link_thread_to_conversation(
    db: AsyncSession,
    thread_id: int,
    conversation_id: int,
):
    """将 harness thread 关联到旧的 Conversation。"""
    thread = await db.get(HarnessThread, thread_id)
    if thread:
        thread.conversation_id = conversation_id
        await db.flush()


async def create_conversation_for_thread(
    db: AsyncSession,
    thread_id: int,
    *,
    title: str = "",
    user_id: int,
    tenant_id: int,
    agent_type: str = "developer",
    workspace_id: Optional[str] = None,
) -> int:
    """为 harness thread 创建对应的旧 Conversation 记录，返回 conversation_id。"""
    conv = Conversation(
        title=title or f"Harness Thread #{thread_id}",
        user_id=user_id,
        tenant_id=tenant_id,
        agent_type=agent_type,
        workspace_id=workspace_id,
    )
    db.add(conv)
    await db.flush()

    # 关联
    thread = await db.get(HarnessThread, thread_id)
    if thread:
        thread.conversation_id = conv.id

    return conv.id


async def save_turn_to_messages(
    db: AsyncSession,
    conversation_id: int,
    user_input: str,
    assistant_output: str,
):
    """将一轮对话保存到旧 Message 表（兼容旧前端查看历史）。"""
    db.add(Message(conversation_id=conversation_id, role="user", content=user_input))
    if assistant_output:
        db.add(Message(conversation_id=conversation_id, role="assistant", content=assistant_output))
    await db.flush()


async def get_thread_by_conversation(
    db: AsyncSession,
    conversation_id: int,
) -> Optional[int]:
    """通过旧 conversation_id 查找对应的 harness thread_id。"""
    result = await db.execute(
        select(HarnessThread.id).where(HarnessThread.conversation_id == conversation_id)
    )
    return result.scalar_one_or_none()
