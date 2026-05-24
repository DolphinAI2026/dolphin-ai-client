"""ConfigChat 会话 CRUD — `/chat?app_id=X` 右侧 ConfigAssistantPanel 的会话持久化端点。

2026-05-24 配套 ConfigAssistantPanel 加 "新对话" / "历史" 抽屉。学 super-agents-dev 的
ChatSession + ChatSessionContent 双表 + sidebar 内 SessionDrawer 模式。

主 endpoint `POST /applications/{app_id}/config-chat-stream` 自己已经在
`backend/app/routes/applications/__init__.py` 内 `_config_chat_event_stream` 函数里负责
落 message。这里只提供 sessions 的 list/create/get_messages/delete/rename CRUD。

权限：sessions 按 (tenant_id, user_id, app_id) 隔离，访问别人的 session 返 404 而不
是 403（不暴露 session 存在）。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models import Application
from app.models.config_chat import ConfigChatMessage, ConfigChatSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["配置助手会话"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SessionSummary(BaseModel):
    """列表项 — 用于左侧 drawer 渲染。包含轻量统计字段方便用户挑选。"""
    id: int
    title: str
    message_count: int = 0
    last_message_preview: Optional[str] = None  # 末条消息前 60 字（user 或 assistant 都可能）
    updated_at: datetime
    created_at: datetime


class SessionCreateReq(BaseModel):
    title: Optional[str] = None  # 不填走默认 "新对话"


class SessionCreateResp(BaseModel):
    id: int
    title: str
    created_at: datetime


class SessionRenameReq(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MessageItem(BaseModel):
    id: int
    role: str  # 'user' | 'assistant'
    content: str
    tool_trace: Optional[list] = None
    change_plan: Optional[dict] = None
    actions_summary: Optional[list] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _require_app_access(
    db: AsyncSession, ctx: AuthContext, app_id: int
) -> Application:
    """简化版应用归属检查：必须是同租户。复杂的协作权限走主 chat endpoint 已经检查过。

    这里之所以独立检查而不复用 `_require_application_permission`，是因为
    session list/CRUD 是配置助手 UI 侧的元数据操作，权限粒度跟 chat 主流程一致即可
    （能看到应用就能管理自己的 sessions）。
    """
    result = await db.execute(
        select(Application).where(
            Application.id == app_id,
            Application.tenant_id == ctx.tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    return app


async def _require_session(
    db: AsyncSession, ctx: AuthContext, session_id: int
) -> ConfigChatSession:
    """拉 session 并校验属于当前 user + tenant。否则 404（不暴露存在性）。"""
    result = await db.execute(
        select(ConfigChatSession).where(
            ConfigChatSession.id == session_id,
            ConfigChatSession.tenant_id == ctx.tenant_id,
            ConfigChatSession.user_id == ctx.user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/applications/{app_id}/config-chat-sessions",
    response_model=List[SessionSummary],
)
async def list_sessions(
    app_id: Annotated[int, Path()],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列当前用户在该 app 下的所有 sessions，按 updated_at DESC 排序。

    带轻量统计：message_count（消息总条数）+ last_message_preview（末条消息 60 字截断）。
    用一个聚合查询 + 一个 LATERAL-like correlated subquery 不如直接两次查询简单，
    sessions 一般不多（< 100/user），实际性能没问题。
    """
    await _require_app_access(db, ctx, app_id)

    # 一次性拉所有 sessions
    sessions_result = await db.execute(
        select(ConfigChatSession)
        .where(
            ConfigChatSession.app_id == app_id,
            ConfigChatSession.tenant_id == ctx.tenant_id,
            ConfigChatSession.user_id == ctx.user.id,
        )
        .order_by(desc(ConfigChatSession.updated_at))
    )
    sessions = list(sessions_result.scalars().all())
    if not sessions:
        return []

    session_ids = [s.id for s in sessions]

    # 一次性拉 message_count
    count_rows = (await db.execute(
        select(ConfigChatMessage.session_id, func.count(ConfigChatMessage.id))
        .where(ConfigChatMessage.session_id.in_(session_ids))
        .group_by(ConfigChatMessage.session_id)
    )).all()
    count_map = {sid: cnt for (sid, cnt) in count_rows}

    # 一次性拉每个 session 末条消息（用 session_id IN ... ORDER BY created_at DESC，
    # Python 侧分组取首条 — 简单可靠，不用做 window function）
    last_rows = (await db.execute(
        select(ConfigChatMessage.session_id, ConfigChatMessage.content, ConfigChatMessage.created_at)
        .where(ConfigChatMessage.session_id.in_(session_ids))
        .order_by(desc(ConfigChatMessage.created_at))
    )).all()
    last_map: dict[int, str] = {}
    for sid, content, _ in last_rows:
        if sid not in last_map and content:
            preview = content.strip()
            if len(preview) > 60:
                preview = preview[:60] + "…"
            last_map[sid] = preview

    return [
        SessionSummary(
            id=s.id,
            title=s.title,
            message_count=int(count_map.get(s.id, 0)),
            last_message_preview=last_map.get(s.id),
            updated_at=s.updated_at,
            created_at=s.created_at,
        )
        for s in sessions
    ]


@router.post(
    "/applications/{app_id}/config-chat-sessions",
    response_model=SessionCreateResp,
)
async def create_session(
    app_id: Annotated[int, Path()],
    payload: SessionCreateReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """主动新建 session — 一般用户在抽屉点 '+ 新对话' 时调。

    更常见的路径是 chat-stream 时不传 session_id，后端自动新建。这个端点用于
    "用户先点新对话再输入" 的场景，或者想以特定 title 提前开会话。
    """
    await _require_app_access(db, ctx, app_id)

    title = (payload.title or "").strip() or "新对话"
    if len(title) > 200:
        title = title[:200]

    session = ConfigChatSession(
        app_id=app_id,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user.id,
        title=title,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return SessionCreateResp(id=session.id, title=session.title, created_at=session.created_at)


@router.get(
    "/config-chat-sessions/{session_id}/messages",
    response_model=List[MessageItem],
)
async def get_messages(
    session_id: Annotated[int, Path()],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """拉某 session 的全部 messages（按 created_at 升序）。

    前端 SessionDrawer 选择某 session 后 → useConfigChat.loadHistory(sid) → 这个端点。
    """
    await _require_session(db, ctx, session_id)

    rows = (await db.execute(
        select(ConfigChatMessage)
        .where(ConfigChatMessage.session_id == session_id)
        .order_by(ConfigChatMessage.created_at.asc(), ConfigChatMessage.id.asc())
    )).scalars().all()

    return [
        MessageItem(
            id=m.id,
            role=m.role,
            content=m.content or "",
            tool_trace=m.tool_trace_json if isinstance(m.tool_trace_json, list) else None,
            change_plan=m.change_plan_json if isinstance(m.change_plan_json, dict) else None,
            actions_summary=m.actions_summary_json if isinstance(m.actions_summary_json, list) else None,
            created_at=m.created_at,
        )
        for m in rows
    ]


@router.delete("/config-chat-sessions/{session_id}")
async def delete_session(
    session_id: Annotated[int, Path()],
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除 session — messages 走 ondelete=CASCADE 自动级联清。"""
    session = await _require_session(db, ctx, session_id)
    await db.delete(session)
    await db.commit()
    return {"ok": True}


@router.patch("/config-chat-sessions/{session_id}")
async def rename_session(
    session_id: Annotated[int, Path()],
    payload: SessionRenameReq,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """改 session title — 用户对历史会话改个有意义的标题方便后续找。"""
    session = await _require_session(db, ctx, session_id)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title 不能为空")
    if len(title) > 200:
        title = title[:200]
    session.title = title
    await db.commit()
    await db.refresh(session)
    return {"ok": True, "id": session.id, "title": session.title}
