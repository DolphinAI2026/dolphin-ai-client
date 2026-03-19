from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import User, Conversation, Message
from app.schemas import ConversationCreate, ConversationResponse, MessageResponse
from app.deps import get_auth_context, AuthContext

router = APIRouter(prefix="/conversations", tags=["对话"])


@router.post("", response_model=ConversationResponse)
async def create_conversation(
    data: ConversationCreate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    # 创建新对话（租户隔离）
    conversation = Conversation(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        title=f"新对话 - {data.agent_type}",
        agent_type=data.agent_type,
        status="active"
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)

    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        agent_type=conversation.agent_type,
        status=conversation.status,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at
    )


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id
        )
        .order_by(desc(Conversation.updated_at))
    )
    conversations = result.scalars().all()

    return [
        ConversationResponse(
            id=conv.id,
            title=conv.title,
            agent_type=conv.agent_type,
            status=conv.status,
            created_at=conv.created_at,
            updated_at=conv.updated_at
        )
        for conv in conversations
    ]


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id
        )
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        agent_type=conversation.agent_type,
        status=conversation.status,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at
    )


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    # 先验证对话归属（租户隔离）
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id
        )
    )
    if not conv_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="对话不存在")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(asc(Message.created_at))
    )
    return [
        MessageResponse(
            id=msg.id,
            role=msg.role,
            content=msg.content,
            created_at=msg.created_at
        )
        for msg in result.scalars().all()
    ]
