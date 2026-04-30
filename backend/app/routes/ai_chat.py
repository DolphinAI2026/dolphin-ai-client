"""AIChat 路由 — 独立于现有 ChatPage 链路，提供 agentic chat 能力。

端点：
- GET    /api/ai-chat/sessions              列会话
- POST   /api/ai-chat/sessions              创建会话
- GET    /api/ai-chat/sessions/:id          会话详情（含 messages + tool_calls）
- PATCH  /api/ai-chat/sessions/:id          更新会话（title / llm 选择）
- POST   /api/ai-chat/sessions/:id/upload   上传附件（multipart, multi-file，自动解析）
- POST   /api/ai-chat/sessions/:id/send     发消息（SSE 流式 agent loop）
- POST   /api/ai-chat/sessions/:id/abort    中断当前 agent loop
- GET    /api/ai-chat/sessions/:id/artifacts            列产出物
- GET    /api/ai-chat/sessions/:id/artifacts/:filename  获取产出物内容
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.database import get_db, AsyncSessionLocal
from app.deps import get_auth_context, AuthContext
from app.models import (
    AIChatSession,
    AIChatMessage,
    AIChatToolCall,
    AIChatAttachment,
    AIChatArtifact,
)
from app.routes.chat import _parse_uploaded_document  # 复用现有文档解析
from app.ai_chat.agent import run_agent, generate_title

router = APIRouter(prefix="/ai-chat", tags=["ai-chat"])


# ─────────────────────────── 请求 / 响应 schemas ───────────────────────────

class CreateSessionRequest(BaseModel):
    title: Optional[str] = None
    selected_llm_config_id: Optional[int] = None
    # 工作模式：'chat'（从零理需求）/ 'cowork'（批量材料整合）
    mode: Optional[str] = None


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None
    selected_llm_config_id: Optional[int] = None
    status: Optional[str] = None


class SendMessageRequest(BaseModel):
    message: str
    attachment_ids: Optional[List[int]] = None  # 引用本会话已上传的附件


# ─────────────────────────── 会话存活的 abort 标志 ───────────────────────────
# 内存表：session_id -> asyncio.Event；用户点中断 → set，agent loop 检测到就停
_session_aborts: dict[int, asyncio.Event] = {}


def get_or_create_abort_event(session_id: int) -> asyncio.Event:
    ev = _session_aborts.get(session_id)
    if ev is None:
        ev = asyncio.Event()
        _session_aborts[session_id] = ev
    return ev


def reset_abort_event(session_id: int) -> None:
    """每次开始新一轮 send 时清 abort 标志。"""
    ev = _session_aborts.get(session_id)
    if ev:
        ev.clear()


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


# ─────────────────────────── 工具函数 ───────────────────────────

def _session_to_dict(s: AIChatSession) -> dict:
    return {
        "id": s.id,
        "title": s.title,
        "status": s.status,
        "mode": getattr(s, "mode", None) or "chat",
        "selected_llm_config_id": s.selected_llm_config_id,
        "workspace_dir": s.workspace_dir,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _message_to_dict(m: AIChatMessage) -> dict:
    return {
        "id": m.id,
        "session_id": m.session_id,
        "role": m.role,
        "content": m.content,
        "extra_meta": m.extra_meta or {},
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _tool_call_to_dict(t: AIChatToolCall) -> dict:
    return {
        "id": t.id,
        "session_id": t.session_id,
        "message_id": t.message_id,
        "tool_name": t.tool_name,
        "args_json": t.args_json or {},
        "result_text": t.result_text,
        "status": t.status,
        "error_message": t.error_message,
        "duration_ms": t.duration_ms,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
    }


def _attachment_to_dict(a: AIChatAttachment) -> dict:
    return {
        "id": a.id,
        "session_id": a.session_id,
        "filename": a.filename,
        "kind": a.kind,
        "mime": a.mime,
        "size_bytes": a.size_bytes,
        "has_content_text": bool(a.content_text),
        "has_image": bool(a.image_data_url),
        "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None,
    }


def _artifact_to_dict(a: AIChatArtifact) -> dict:
    return {
        "id": a.id,
        "session_id": a.session_id,
        "filename": a.filename,
        "format": a.format,
        "version": a.version,
        "preview": (a.content[:200] + "...") if len(a.content) > 200 else a.content,
        "size_bytes": len(a.content.encode("utf-8")) if a.content else 0,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


def _ensure_session_workspace(session: AIChatSession) -> str:
    """每个会话有独立的工作区目录（存附件 + run_python 的 cwd）。"""
    if session.workspace_dir and Path(session.workspace_dir).exists():
        return session.workspace_dir
    base = Path(tempfile.gettempdir()) / "ai-chat-workspaces" / f"session-{session.id}"
    base.mkdir(parents=True, exist_ok=True)
    session.workspace_dir = str(base)
    return session.workspace_dir


def _classify_kind(filename: str, mime: Optional[str]) -> str:
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext in {"png", "jpg", "jpeg", "gif", "webp"}:
        return "image"
    if ext in {"docx", "pdf", "xlsx", "pptx", "md", "markdown", "txt", "csv", "json", "yaml", "yml"}:
        return ext if ext != "markdown" else "md"
    return "other"


# ─────────────────────────── 鉴权辅助 ───────────────────────────

async def _load_session_or_404(
    db: AsyncSession, session_id: int, ctx: AuthContext
) -> AIChatSession:
    res = await db.execute(
        select(AIChatSession).where(
            AIChatSession.id == session_id,
            AIChatSession.user_id == ctx.user.id,
            AIChatSession.tenant_id == ctx.tenant_id,
        )
    )
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在或无权限")
    return s


# ═══════════════════════════ Sessions CRUD ═══════════════════════════

@router.get("/sessions")
async def list_sessions(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 50,
):
    res = await db.execute(
        select(AIChatSession)
        .where(
            AIChatSession.user_id == ctx.user.id,
            AIChatSession.tenant_id == ctx.tenant_id,
        )
        .order_by(desc(AIChatSession.updated_at))
        .limit(limit)
    )
    sessions = res.scalars().all()
    return {"sessions": [_session_to_dict(s) for s in sessions]}


@router.post("/sessions")
async def create_session(
    body: CreateSessionRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    s = AIChatSession(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user.id,
        title=body.title or "新会话",
        selected_llm_config_id=body.selected_llm_config_id,
        mode="cowork" if body.mode == "cowork" else "chat",
        status="active",
    )
    db.add(s)
    await db.flush()  # 拿到 id
    _ensure_session_workspace(s)
    await db.commit()
    await db.refresh(s)
    return _session_to_dict(s)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    s = await _load_session_or_404(db, session_id, ctx)

    # 加载消息 + 工具调用 + 附件
    msgs_res = await db.execute(
        select(AIChatMessage)
        .where(AIChatMessage.session_id == session_id)
        .order_by(AIChatMessage.id.asc())
    )
    all_messages = msgs_res.scalars().all()
    # 过滤掉 tool_use turn 的 assistant 消息（content 空 + extra_meta.tool_calls 非空）：
    # 这些是 LLM history 重建用的占位记录，不是给用户看的。前端的工具调用渲染基于
    # tool_calls 数组单独完成，不需要这条 assistant 占位。
    def _is_tool_use_placeholder(m: AIChatMessage) -> bool:
        if m.role != "assistant":
            return False
        if (m.content or "").strip():
            return False
        meta = m.extra_meta if isinstance(m.extra_meta, dict) else None
        return bool(meta and meta.get("tool_calls"))
    messages = [m for m in all_messages if not _is_tool_use_placeholder(m)]

    tool_res = await db.execute(
        select(AIChatToolCall)
        .where(AIChatToolCall.session_id == session_id)
        .order_by(AIChatToolCall.id.asc())
    )
    tool_calls = tool_res.scalars().all()

    att_res = await db.execute(
        select(AIChatAttachment)
        .where(AIChatAttachment.session_id == session_id)
        .order_by(AIChatAttachment.id.asc())
    )
    attachments = att_res.scalars().all()

    art_res = await db.execute(
        select(AIChatArtifact)
        .where(AIChatArtifact.session_id == session_id)
        .order_by(AIChatArtifact.id.asc())
    )
    artifacts = art_res.scalars().all()

    return {
        "session": _session_to_dict(s),
        "messages": [_message_to_dict(m) for m in messages],
        "tool_calls": [_tool_call_to_dict(t) for t in tool_calls],
        "attachments": [_attachment_to_dict(a) for a in attachments],
        "artifacts": [_artifact_to_dict(a) for a in artifacts],
    }


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    s = await _load_session_or_404(db, session_id, ctx)
    # 防御性显式清理子表（即使 FK CASCADE 没生效也能干净删掉）
    from sqlalchemy import delete as sql_delete
    await db.execute(sql_delete(AIChatToolCall).where(AIChatToolCall.session_id == session_id))
    await db.execute(sql_delete(AIChatMessage).where(AIChatMessage.session_id == session_id))
    await db.execute(sql_delete(AIChatAttachment).where(AIChatAttachment.session_id == session_id))
    await db.execute(sql_delete(AIChatArtifact).where(AIChatArtifact.session_id == session_id))
    await db.delete(s)
    await db.commit()
    # 清理 in-memory abort event
    _session_aborts.pop(session_id, None)
    return {"ok": True}


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: int,
    body: UpdateSessionRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    s = await _load_session_or_404(db, session_id, ctx)
    if body.title is not None:
        s.title = body.title
    if body.selected_llm_config_id is not None:
        s.selected_llm_config_id = body.selected_llm_config_id
    if body.status is not None:
        s.status = body.status
    await db.commit()
    await db.refresh(s)
    return _session_to_dict(s)


# ═══════════════════════════ Upload ═══════════════════════════

@router.post("/sessions/{session_id}/upload")
async def upload_attachments(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    files: List[UploadFile] = File(default=[]),
):
    """支持多文件批量上传：解析文本（docx/pdf/xlsx/pptx/md/txt）+ 图片留 base64。"""
    s = await _load_session_or_404(db, session_id, ctx)
    workspace = _ensure_session_workspace(s)

    saved: list[AIChatAttachment] = []
    for f in files:
        if not f.filename:
            continue
        kind = _classify_kind(f.filename, f.content_type)
        # 落盘到 session workspace（让 run_python 能读到）
        save_path = Path(workspace) / f.filename
        save_path.parent.mkdir(parents=True, exist_ok=True)
        raw = await f.read()
        save_path.write_bytes(raw)

        content_text: Optional[str] = None
        image_data_url: Optional[str] = None

        if kind == "image":
            import base64
            mime_map = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "gif": "image/gif",
                "webp": "image/webp",
            }
            ext = os.path.splitext(f.filename)[1].lower().lstrip(".")
            mime = mime_map.get(ext, "image/png")
            image_data_url = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        else:
            # 重新构造 UploadFile 给 _parse_uploaded_document（它内部 await file.read()）
            from io import BytesIO
            from starlette.datastructures import UploadFile as StarletteUpload
            stub = StarletteUpload(filename=f.filename, file=BytesIO(raw))
            try:
                content_text = await _parse_uploaded_document(stub)
            except Exception:
                content_text = ""

        att = AIChatAttachment(
            session_id=session_id,
            filename=f.filename,
            kind=kind,
            mime=f.content_type,
            size_bytes=len(raw),
            file_path=str(save_path),
            content_text=content_text,
            image_data_url=image_data_url,
        )
        db.add(att)
        saved.append(att)

    await db.commit()
    for att in saved:
        await db.refresh(att)
    return {"attachments": [_attachment_to_dict(a) for a in saved]}


# ═══════════════════════════ Send (SSE 流式) ═══════════════════════════

@router.post("/sessions/{session_id}/send")
async def send_message(
    session_id: int,
    body: SendMessageRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """发消息 → 触发 agent loop → SSE 流式回 thinking / tool_call / message / artifact 等事件。"""
    # 用请求级 session 校验权限并写入 user_msg（这一步必须同步落库才能让前端立即看到）
    s = await _load_session_or_404(db, session_id, ctx)
    reset_abort_event(session_id)
    abort_event = get_or_create_abort_event(session_id)

    user_msg = AIChatMessage(
        session_id=session_id,
        role="user",
        content=body.message,
        extra_meta={"attachment_ids": body.attachment_ids or []},
    )
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)

    user_msg_dict = _message_to_dict(user_msg)
    initial_title = s.title
    is_first_user_message = body.message.strip() and initial_title in ("新会话", "")

    async def event_stream():
        # 流式必须用一个全新的 AsyncSession：FastAPI 的依赖注入 session 在响应函数返回后
        # 可能已经被 finally 清理，导致 SSE 内部 `db.commit() / db.refresh()` 抛
        # "Instance ... is not persistent within this Session"
        async with AsyncSessionLocal() as stream_db:
            try:
                # 重新加载会话到当前 session（避免持有跨 session 的 ORM 实例）
                stream_s = await stream_db.get(AIChatSession, session_id)
                if stream_s is None:
                    yield _sse("error", {"error": "会话已被删除"})
                    return

                yield {"event": "user_message", "data": json.dumps(user_msg_dict, ensure_ascii=False)}

                # 第一条消息自动生成标题
                if is_first_user_message:
                    msg_count_res = await stream_db.execute(
                        select(AIChatMessage).where(
                            AIChatMessage.session_id == stream_s.id,
                            AIChatMessage.role == "user",
                        )
                    )
                    if len(msg_count_res.scalars().all()) <= 1:
                        new_title = await generate_title(stream_db, stream_s, body.message)
                        if new_title:
                            stream_s.title = new_title
                            await stream_db.commit()
                            await stream_db.refresh(stream_s)
                            yield {
                                "event": "session_updated",
                                "data": json.dumps(_session_to_dict(stream_s), ensure_ascii=False),
                            }

                async for event in run_agent(stream_db, stream_s, body.message, abort_event):
                    yield event
            except Exception as e:
                import traceback
                traceback.print_exc()
                yield {"event": "error", "data": json.dumps({"error": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(event_stream())


@router.post("/sessions/{session_id}/abort")
async def abort_session(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _load_session_or_404(db, session_id, ctx)
    ev = get_or_create_abort_event(session_id)
    ev.set()
    return {"ok": True}


# ═══════════════════════════ Artifacts ═══════════════════════════

@router.get("/sessions/{session_id}/artifacts")
async def list_artifacts(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _load_session_or_404(db, session_id, ctx)
    res = await db.execute(
        select(AIChatArtifact)
        .where(AIChatArtifact.session_id == session_id)
        .order_by(desc(AIChatArtifact.updated_at))
    )
    arts = res.scalars().all()
    return {"artifacts": [_artifact_to_dict(a) for a in arts]}


@router.get("/sessions/{session_id}/artifacts/{filename}")
async def get_artifact(
    session_id: int,
    filename: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    version: Optional[int] = None,
):
    """获取产出物内容。version 不传 → 返回最新版；传具体值 → 返回该版本。"""
    await _load_session_or_404(db, session_id, ctx)
    query = (
        select(AIChatArtifact)
        .where(
            AIChatArtifact.session_id == session_id,
            AIChatArtifact.filename == filename,
        )
    )
    if version is not None:
        query = query.where(AIChatArtifact.version == version)
    else:
        query = query.order_by(desc(AIChatArtifact.version))
    res = await db.execute(query.limit(1))
    a = res.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="产出物不存在")
    return {
        **_artifact_to_dict(a),
        "content": a.content,
    }


@router.get("/sessions/{session_id}/artifacts/{filename}/versions")
async def list_artifact_versions(
    session_id: int,
    filename: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出某个 filename 的所有历史版本（按 version 降序）。"""
    await _load_session_or_404(db, session_id, ctx)
    res = await db.execute(
        select(AIChatArtifact)
        .where(
            AIChatArtifact.session_id == session_id,
            AIChatArtifact.filename == filename,
        )
        .order_by(desc(AIChatArtifact.version))
    )
    items = res.scalars().all()
    return {"versions": [_artifact_to_dict(a) for a in items]}
