"""Harness Core — API 路由

提供统一的 thread/turn/event 接口，供所有四种 mode 使用。
"""
import json
import logging
from typing import Annotated, Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.database import get_db
from app.routes.auth import get_auth_context, AuthContext
from app.harness import HarnessManager, list_profiles
from app.project_access import require_project_access
from app.routes.coding import _ensure_workspace_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/harness", tags=["harness"])


# ── Request/Response Models ──────────────────────

class CreateThreadRequest(BaseModel):
    profile_name: str
    conversation_id: int | None = None
    metadata: dict = {}


class StartTurnRequest(BaseModel):
    user_input: str


# ── Endpoints ──────────────────────────────────────

@router.post("/threads")
async def create_thread(
    req: CreateThreadRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """创建新的 harness thread。"""
    mgr = HarnessManager(db)

    metadata = dict(req.metadata)

    try:
        thread_ctx = await mgr.create_thread(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user.id,
            profile_name=req.profile_name,
            conversation_id=req.conversation_id,
            metadata=metadata,
        )
        await db.commit()
        return {
            "id": thread_ctx.thread_id,
            "profile_name": thread_ctx.profile_name,
            "status": "active",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取 thread 状态和详情。"""
    mgr = HarnessManager(db)
    try:
        info = await mgr.get_thread_info(thread_id, tenant_id=ctx.tenant_id)
        return info.model_dump(mode="json")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/threads/{thread_id}/turns")
async def start_turn(
    thread_id: int,
    req: StartTurnRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """发起新一轮（SSE 流式返回事件）。"""
    mgr = HarnessManager(db)
    try:
        thread_ctx = await mgr.load_thread(thread_id, tenant_id=ctx.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    event_stream = await mgr.start_turn(thread_ctx, req.user_input)

    async def sse_generator():
        async for event in event_stream:
            if event.get("type") == "heartbeat":
                yield {"event": "ping", "data": ""}
            else:
                yield {"event": "message", "data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(sse_generator())


@router.get("/threads/{thread_id}/events")
async def replay_events(
    thread_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    after_seq: int = Query(default=0, description="从该 seq 之后开始回放"),
):
    """回放 thread 的历史事件。"""
    mgr = HarnessManager(db)
    try:
        events = await mgr.replay_events(
            thread_id, after_seq=after_seq, tenant_id=ctx.tenant_id
        )
        return {"events": events, "count": len(events)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/threads/{thread_id}/artifacts")
async def get_thread_artifacts(
    thread_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    turn_id: Optional[int] = Query(default=None),
    artifact_type: Optional[str] = Query(default=None),
):
    """查询 thread 的 artifacts。"""
    from app.harness.artifacts import get_artifacts
    mgr = HarnessManager(db)
    try:
        await mgr.load_thread(thread_id, tenant_id=ctx.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    artifacts = await get_artifacts(db, thread_id, turn_id=turn_id, artifact_type=artifact_type)
    return {"artifacts": artifacts, "count": len(artifacts)}


@router.get("/profiles")
async def get_profiles():
    """列出所有已注册的 profile。"""
    return {"profiles": list_profiles()}


# ── Coding 快捷端点 ──────────────────────────────
# 前端可以一步完成 create_thread + start_turn（对应旧 auto-pipeline 的一个 POST 调用）

class CodingPipelineRequest(BaseModel):
    """Coding Pipeline 一步到位请求 — 替代旧的 /coding/auto-pipeline"""
    message: str
    workspace_id: str | None = None
    conversation_id: int | None = None
    selected_model: str | None = None
    project_id: int | None = None
    app_id: str | None = None  # 分场景「在应用上定制」选中的本地 Application.id
    attachments: list[dict[str, Any]] | None = None


@router.get("/coding/run-status")
async def coding_run_status(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """该会话是否有在跑的 coding run + 最新 seq —— 前端切回会话据此决定是否重连。"""
    from app.harness.run_registry import run_registry

    h = run_registry.get(conversation_id)
    if h and not h.task.done():
        return {
            "running": True,
            "last_seq": getattr(h.event_bus, "current_seq", 0),
            "run_id": h.run_id,
        }
    return {"running": False, "last_seq": 0, "run_id": None}


@router.post("/coding/stop")
async def coding_stop(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """显式停止该会话在跑的 coding run(停止键)。

    现在 run 是 RunRegistry 强引用的后台 task,断 SSE 不再停它 → 停止键必须显式取消 task。
    取消后 task 的 finally 会 send_sentinel + 摘除注册表。
    """
    from app.harness.run_registry import run_registry

    h = run_registry.get(conversation_id)
    if h and not h.task.done():
        h.task.cancel()
        return {"ok": True, "stopped": True}
    return {"ok": True, "stopped": False}


@router.get("/coding/attach")
async def coding_attach(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    after_seq: int = Query(0, ge=0),
):
    """重连一个在跑的 coding run(切会话/刷新后续看):补 seq>after_seq + 跟实时,SSE。

    与 /coding/pipeline 同构事件;不在跑则空流(历史由 /coding/conversations/{id}/replay 覆盖)。
    """
    mgr = HarnessManager(db)
    stream = mgr.attach_stream(conversation_id, after_seq=after_seq, tenant_id=ctx.tenant_id)

    async def sse_generator():
        async for event in stream:
            if event.get("type") == "heartbeat":
                yield {"event": "ping", "data": ""}
            else:
                yield {"event": "message", "data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(
        sse_generator(),
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache, no-store"},
        ping=15,
    )


@router.post("/coding/pipeline")
async def coding_pipeline(
    req: CodingPipelineRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Coding Pipeline 一步到位端点。

    等效于 create_thread(coding) + start_turn(message)，但合并为一个 SSE 请求，
    前端无需做两步调用，与旧 auto-pipeline 的调用方式一致。
    """
    metadata = {
        "workspace_id": req.workspace_id,
        "conversation_id": req.conversation_id,
        "selected_model": req.selected_model,
        "project_id": req.project_id,
        "app_id": req.app_id,
        "attachments": req.attachments or [],
    }
    if req.workspace_id:
        await _ensure_workspace_access(req.workspace_id, ctx, db, minimum_project_role="member")
    if req.project_id:
        await require_project_access(
            db,
            project_id=req.project_id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            minimum_role="member",
        )
    return await _start_coding_turn_sse(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user.id,
        conversation_id=req.conversation_id,
        message=req.message,
        metadata=metadata,
    )


async def _start_coding_turn_sse(
    db: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    conversation_id: int | None,
    message: str,
    metadata: dict[str, Any],
):
    # 守卫:同会话已有在跑 run → 挡住(单会话单 run,避免并发竞态/误丢)
    from app.harness.run_registry import run_registry
    if conversation_id is not None and run_registry.is_running(conversation_id):
        raise HTTPException(status_code=409, detail="该会话有任务在跑,请等它完成或先停止")

    mgr = HarnessManager(db)

    try:
        thread_ctx = await mgr.create_thread(
            tenant_id=tenant_id,
            user_id=user_id,
            profile_name="coding",
            conversation_id=conversation_id,
            metadata=metadata,
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    event_stream = await mgr.start_turn(thread_ctx, message)

    async def sse_generator():
        async for event in event_stream:
            if event.get("type") == "heartbeat":
                yield {"event": "ping", "data": ""}
            else:
                yield {"event": "message", "data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(
        sse_generator(),
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store",
        },
        ping=15,
    )
