"""Harness Core — API 路由

提供统一的 thread/turn/event 接口，供所有四种 mode 使用。
"""
import json
import logging
from typing import Annotated, Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.database import get_db
from app.routes.auth import get_auth_context, AuthContext
from app.harness import HarnessManager, list_profiles

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
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """创建新的 harness thread。"""
    mgr = HarnessManager(db)

    # 为 coding profile 预计算 request-scoped 值注入 metadata
    metadata = dict(req.metadata)
    if req.profile_name == "coding":
        _inject_coding_metadata(metadata, ctx, request)

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


class IDECodingPipelineRequest(BaseModel):
    message: str
    conversation_id: int | None = None
    selected_model: str | None = None
    project_id: int | None = None


@router.post("/coding/pipeline")
async def coding_pipeline(
    req: CodingPipelineRequest,
    request: Request,
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
    }
    _inject_coding_metadata(metadata, ctx, request)

    return await _start_coding_turn_sse(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user.id,
        conversation_id=req.conversation_id,
        message=req.message,
        metadata=metadata,
    )


@router.post("/coding/workspace/{ws_id}/ide/pipeline")
async def ide_coding_pipeline(
    ws_id: str,
    req: IDECodingPipelineRequest,
    request: Request,
    x_vibe_ide_token: Annotated[Optional[str], Header(alias="X-Vibe-IDE-Token")] = None,
    token: Optional[str] = Query(default=None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """IDE 使用短期 token 直接接入统一 harness coding runtime。"""
    from app.routes.coding import _verify_ide_access_token

    ide_token = x_vibe_ide_token or token
    if not ide_token:
        raise HTTPException(status_code=401, detail="缺少 IDE 访问令牌，请重新从 Builder 打开 Web IDE")

    token_payload = _verify_ide_access_token(ide_token, ws_id)
    try:
        user_id = int(token_payload.get("sub"))
        tenant_id = int(token_payload.get("tid"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="无效的 IDE 访问令牌")

    metadata = {
        "workspace_id": ws_id,
        "conversation_id": req.conversation_id,
        "selected_model": req.selected_model,
        "project_id": req.project_id,
        "ide_token": ide_token,
    }
    _inject_coding_metadata(metadata, None, request)

    return await _start_coding_turn_sse(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=req.conversation_id,
        message=req.message,
        metadata=metadata,
    )


# ── Coding 辅助函数 ──────────────────────────────

def _inject_coding_metadata(metadata: dict, ctx: AuthContext | None, request: Request):
    """为 coding profile 预计算 request-scoped 值，注入到 thread metadata。"""
    from app.config import settings

    # code-server base URL
    if "code_server_base_url" not in metadata:
        metadata["code_server_base_url"] = settings.code_server_base_url or ""

    # API base — 用于 code-server 内的 IDE proxy
    if "api_base_builder" not in metadata:
        try:
            from app.routes.coding import _build_ide_proxy_api_base, _derive_harness_api_base
            # 需要一个 ws_id，但创建 thread 时可能还没有
            # 使用占位符，pipeline 内部会在有 ws_id 后重新计算
            ws_id = metadata.get("workspace_id") or "__placeholder__"
            api_base = _build_ide_proxy_api_base(request, ws_id)
            # 存储 base pattern（去掉 ws_id 部分），pipeline 内部替换
            metadata["api_base_builder"] = api_base.replace(ws_id, "{ws_id}")
            metadata["harness_api_base_builder"] = _derive_harness_api_base(api_base).replace(ws_id, "{ws_id}")
        except Exception:
            pass


async def _start_coding_turn_sse(
    db: AsyncSession,
    *,
    tenant_id: int,
    user_id: int,
    conversation_id: int | None,
    message: str,
    metadata: dict[str, Any],
):
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
