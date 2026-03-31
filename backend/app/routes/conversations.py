from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import User, Conversation, Message, Application
from app.schemas import ConversationCreate, ConversationResponse, MessageResponse
from app.deps import get_auth_context, AuthContext

router = APIRouter(prefix="/conversations", tags=["对话"])


class ConversationModelUpdateRequest(BaseModel):
    selected_llm_config_id: Optional[int] = None


@router.post("", response_model=ConversationResponse)
async def create_conversation(
    data: ConversationCreate,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    selected_llm_config_id: Optional[int] = None
    model_purpose = "coding" if data.agent_type == "coding" else ("builder" if data.agent_type in {"builder", "requirements"} else None)
    if model_purpose:
        from app.routes.llm_configs import (
            get_active_llm_config_by_id_for_purpose,
            get_default_llm_config_id_for_purpose,
        )

        if data.selected_llm_config_id is not None:
            config = await get_active_llm_config_by_id_for_purpose(
                db,
                ctx.tenant_id,
                data.selected_llm_config_id,
                model_purpose,
            )
            if not config:
                raise HTTPException(status_code=400, detail="所选模型不可用")
            selected_llm_config_id = config.id
        else:
            selected_llm_config_id = await get_default_llm_config_id_for_purpose(
                db,
                ctx.tenant_id,
                model_purpose,
            )

    # 创建新对话（租户隔离）
    conversation = Conversation(
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        title=f"新对话 - {data.agent_type}",
        agent_type=data.agent_type,
        selected_llm_config_id=selected_llm_config_id,
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
        selected_llm_config_id=conversation.selected_llm_config_id,
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
            selected_llm_config_id=conv.selected_llm_config_id,
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
        selected_llm_config_id=conversation.selected_llm_config_id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at
    )


@router.patch("/{conversation_id}/model", response_model=ConversationResponse)
async def update_conversation_model(
    conversation_id: int,
    data: ConversationModelUpdateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    if conversation.agent_type not in {"builder", "requirements", "coding"}:
        raise HTTPException(status_code=400, detail="当前对话不支持切换模型")

    model_purpose = "coding" if conversation.agent_type == "coding" else "builder"

    if data.selected_llm_config_id is None:
        conversation.selected_llm_config_id = None
    else:
        from app.routes.llm_configs import get_active_llm_config_by_id_for_purpose

        config = await get_active_llm_config_by_id_for_purpose(
            db,
            ctx.tenant_id,
            data.selected_llm_config_id,
            model_purpose,
        )
        if not config:
            raise HTTPException(status_code=400, detail="所选模型不可用")
        conversation.selected_llm_config_id = config.id

    await db.commit()
    await db.refresh(conversation)

    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        agent_type=conversation.agent_type,
        status=conversation.status,
        selected_llm_config_id=conversation.selected_llm_config_id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
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


# ── 带应用信息的对话列表（用于对话历史面板）──

class ConversationWithAppResponse(BaseModel):
    id: int
    title: str
    agent_type: str
    status: str
    selected_llm_config_id: Optional[int] = None
    created_at: str
    updated_at: str
    app_id: Optional[int] = None
    app_name: Optional[str] = None


@router.get("/with-apps/list", response_model=list[ConversationWithAppResponse])
async def list_conversations_with_apps(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    agent_type: Optional[str] = Query(None),
):
    """获取当前用户的所有对话，并附带关联的应用信息"""
    query = (
        select(Conversation)
        .where(
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id,
        )
        .order_by(desc(Conversation.updated_at))
    )
    if agent_type:
        query = query.where(Conversation.agent_type == agent_type)

    result = await db.execute(query)
    conversations = result.scalars().all()

    if not conversations:
        return []

    # 批量查询关联的应用
    conv_ids = [c.id for c in conversations]
    app_result = await db.execute(
        select(Application).where(Application.conversation_id.in_(conv_ids))
    )
    apps_by_conv: dict[int, Application] = {}
    for app in app_result.scalars().all():
        apps_by_conv[app.conversation_id] = app

    items = []
    for conv in conversations:
        app = apps_by_conv.get(conv.id)
        items.append(ConversationWithAppResponse(
            id=conv.id,
            title=conv.title,
            agent_type=conv.agent_type,
            status=conv.status,
            selected_llm_config_id=conv.selected_llm_config_id,
            created_at=str(conv.created_at),
            updated_at=str(conv.updated_at),
            app_id=app.id if app else None,
            app_name=app.app_name if app else None,
        ))

    return items
