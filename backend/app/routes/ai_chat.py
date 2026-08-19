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
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import or_, select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.database import get_db, AsyncSessionLocal
from app import runtime
from app.code_runtime.auth import control_plane_access_token
from app.code_runtime.control_plane_models import list_control_plane_model_options
from app.deps import get_auth_context, auth_from_header_or_query, AuthContext
from app.models import (
    AIChatSession,
    AIChatMessage,
    AIChatToolCall,
    AIChatAttachment,
    AIChatArtifact,
    DeployRecord,
    Application,
)
from app.routes.chat import _parse_uploaded_document, DOC_PARSE_ERROR_PREFIX  # 复用现有文档解析
from app.ai_chat.agent import run_agent, generate_title
from app.coding.workspace_access import workspace_mgr  # 代码会话标题派生用工作区显示名
from app.system_assistant.contracts import (
    AssistantProfileRequest,
    DEFAULT_ASSISTANT_PROFILE,
    assistant_model_purpose,
    normalize_assistant_profile,
)
from app.system_assistant.session_lifecycle import (
    SessionHasActiveAction,
    delete_session_with_guard,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-chat", tags=["ai-chat"])

_DEFAULT_SESSION_TITLES = {"", "新会话"}


def _control_plane_code_tenant_id(
    ctx: AuthContext,
    mode: str | None,
    assistant_profile: str | None = None,
) -> str | None:
    if str(getattr(ctx.user, "account_source", "") or "").strip().lower() != "control_plane":
        return None
    # Desktop Builder is backed by the signed-in Control Plane account too.
    # Record that tenant on every desktop session so its default model can come
    # from the online catalog. Web keeps the previous code/system-assistant-only
    # behavior.
    if (
        not runtime.is_desktop()
        and str(mode or "").strip().lower() != "code"
        and assistant_profile != "system_assistant"
    ):
        return None
    value = str(getattr(ctx, "control_plane_tenant_id", "") or "").strip()
    return value or None


async def _validated_selected_llm_config_id(
    db: AsyncSession,
    ctx: AuthContext,
    selected_llm_config_id: int | None,
    purpose: str,
) -> int | None:
    """Validate local IDs and synthesized Control Plane catalogue IDs alike."""
    if selected_llm_config_id is None or selected_llm_config_id == 0:
        return None
    if selected_llm_config_id > 0:
        from app.routes.llm_configs import get_active_llm_config_by_id_for_purpose

        cfg = await get_active_llm_config_by_id_for_purpose(
            db, ctx.tenant_id, selected_llm_config_id, purpose
        )
        if not cfg:
            raise HTTPException(status_code=400, detail="所选模型不可用或不支持当前助手")
        return cfg.id

    if str(getattr(ctx.user, "account_source", "") or "").lower() != "control_plane":
        raise HTTPException(status_code=400, detail="所选模型不可用或不支持当前助手")
    access_token = control_plane_access_token(ctx.user)
    if not access_token:
        raise HTTPException(status_code=400, detail="线上模型登录凭据已失效，请重新登录")
    options = await list_control_plane_model_options(
        purpose=purpose,
        authorization_header=f"Bearer {access_token}",
        delegated_context=ctx,
    )
    if not any(option.get("id") == selected_llm_config_id for option in options):
        raise HTTPException(status_code=400, detail="所选模型不可用或不支持当前助手")
    return selected_llm_config_id


# ─────────────────────────── 请求 / 响应 schemas ───────────────────────────

class CreateSessionRequest(AssistantProfileRequest):
    title: Optional[str] = None
    selected_llm_config_id: Optional[int] = None
    # 工作模式：'chat'（从零理需求）/ 'cowork'（批量材料整合）/ 'code'（二次开发，绑工作区）
    mode: Optional[str] = None
    # 锁定应用上下文：右栏配置助手创建会话时传入，run_agent 据此注入 app 上下文
    app_id: Optional[int] = None
    # code 会话绑定的工作区 slug（WorkspaceManager）；run_agent 据此锁工作区 + 注入 dev-apaas
    workspace_id: Optional[str] = None


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None
    selected_llm_config_id: Optional[int] = None
    status: Optional[str] = None


class SendMessageRequest(BaseModel):
    message: str
    attachment_ids: Optional[List[int]] = None  # 引用本会话已上传的附件
    # 每条消息可携带当前设计器 section 软提示（run_agent 注入 app 上下文时用；按消息传，随用户切 tab 变）
    section: Optional[str] = None
    view_context: Optional[str] = None


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

def _session_to_dict(s: AIChatSession, generation: Optional[dict] = None) -> dict:
    data = {
        "id": s.id,
        "title": s.title,
        "status": s.status,
        "mode": getattr(s, "mode", None) or "chat",
        "assistant_profile": getattr(s, "assistant_profile", None) or DEFAULT_ASSISTANT_PROFILE,
        "selected_llm_config_id": s.selected_llm_config_id,
        "workspace_dir": s.workspace_dir,
        "workspace_id": getattr(s, "workspace_id", None),
        "app_id": getattr(s, "app_id", None),
        "external_application_id": getattr(s, "external_application_id", None),
        "external_app_name": getattr(s, "external_app_name", None),
        "external_app_code": getattr(s, "external_app_code", None),
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
    if generation:
        data["generation"] = generation
    return data


def _clean_session_title(value: str) -> str:
    title = re.sub(r"\s+", " ", str(value or "")).strip(' "\'`「」# ')
    title = re.sub(r"\.(md|markdown|txt|docx|pdf|xlsx|pptx)$", "", title, flags=re.IGNORECASE)
    title = title.replace("_", " ").replace("-", " ")
    title = re.sub(r"\s+", " ", title).strip()
    if re.search(r"[\u4e00-\u9fff]", title):
        title = title.replace(" ", "")
    return title[:30]


def _title_from_markdown(content: str) -> str:
    for line in str(content or "").splitlines()[:40]:
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if match:
            title = _clean_session_title(match.group(1))
            if title:
                return title
    return ""


def _derive_session_title(
    *,
    user_message: str = "",
    attachments: Optional[List[AIChatAttachment]] = None,
    artifacts: Optional[List[AIChatArtifact]] = None,
    messages: Optional[List[AIChatMessage]] = None,
) -> str:
    """Infer a readable title when the first turn is attachment-only."""
    if user_message.strip():
        return _clean_session_title(user_message)

    for artifact in artifacts or []:
        title = _title_from_markdown(getattr(artifact, "content", "") or "")
        if title:
            return title

    for item in [*(attachments or []), *(artifacts or [])]:
        title = _clean_session_title(getattr(item, "filename", "") or "")
        if title:
            return title

    for message in messages or []:
        content = (getattr(message, "content", "") or "").strip()
        if content:
            title = _clean_session_title(content)
            if title:
                return title
    return ""


async def _derive_first_turn_title(
    db: AsyncSession,
    session: AIChatSession,
    user_message: str,
) -> Optional[str]:
    """Choose a first-turn title without letting system-assistant intent drift."""
    if not user_message.strip():
        return None
    if (
        getattr(session, "assistant_profile", None) or DEFAULT_ASSISTANT_PROFILE
    ) == "system_assistant":
        return _derive_session_title(user_message=user_message) or None
    return await generate_title(db, session, user_message)


def _extract_generated_app_from_tool(t: AIChatToolCall) -> Optional[dict]:
    try:
        result = json.loads(t.result_text or "{}")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(result, dict) or result.get("ok") is False:
        return None
    app_id = result.get("app_id") or result.get("application_id")
    if not app_id:
        return None
    try:
        app_id_int = int(app_id)
    except Exception:  # noqa: BLE001
        return None
    return {
        "app_id": app_id_int,
        "app_name": result.get("app_name") or result.get("application_name"),
        "app_code": result.get("app_code"),
        "is_new": result.get("is_new"),
        "tool_status": result.get("status"),
    }


def _deploy_error_from_record(record: Optional[DeployRecord]) -> Optional[str]:
    if not record:
        return None
    if record.error_message and record.error_message != "未知错误":
        return record.error_message
    raw_events = record.event_log_json or []
    if isinstance(raw_events, str):
        try:
            events = json.loads(raw_events)
        except Exception:  # noqa: BLE001
            events = []
    else:
        events = raw_events
    if isinstance(events, list):
        for event in reversed(events):
            if not isinstance(event, dict):
                continue
            if event.get("status") == "error" or event.get("type") in ("error", "exception"):
                for key in ("error", "message", "step"):
                    value = event.get(key)
                    if value not in (None, "", "未知错误"):
                        return str(value)
    return record.error_message


def _generation_status_label(status: str) -> str:
    return {
        "success": "生成成功",
        "failed": "生成失败",
        "running": "生成中",
        "in_progress": "生成中",
        "draft": "草稿",
    }.get(status, status)


async def _generation_meta_from_generated_app(
    db: AsyncSession,
    generated: dict,
    *,
    tool_created_at: Optional[datetime] = None,
) -> dict:
    app = (await db.execute(
        select(Application).where(Application.id == generated["app_id"])
    )).scalar_one_or_none()
    record_query = (
        select(DeployRecord)
        .where(DeployRecord.app_id == generated["app_id"])
        .order_by(DeployRecord.created_at.asc(), DeployRecord.id.asc())
        .limit(1)
    )
    if tool_created_at is not None:
        record_query = (
            select(DeployRecord)
            .where(
                DeployRecord.app_id == generated["app_id"],
                DeployRecord.created_at >= tool_created_at,
            )
            .order_by(DeployRecord.created_at.asc(), DeployRecord.id.asc())
            .limit(1)
        )
    record = (await db.execute(record_query)).scalar_one_or_none()
    status_value = record.status if record else str((app.status if app else None) or generated.get("tool_status") or "draft")
    return {
        **generated,
        "status": status_value,
        "label": _generation_status_label(str(status_value)),
        "deploy_record_id": record.id if record else None,
        "error_message": _deploy_error_from_record(record),
    }


async def _session_generation_meta(
    db: AsyncSession,
    sessions: List[AIChatSession],
    *,
    target_app_id: Optional[int] = None,
) -> dict[int, dict]:
    if not sessions:
        return {}
    session_ids = [s.id for s in sessions]
    res = await db.execute(
        select(AIChatToolCall)
        .where(
            AIChatToolCall.session_id.in_(session_ids),
            AIChatToolCall.tool_name == "generate_app_from_doc",
            AIChatToolCall.status == "success",
        )
        .order_by(AIChatToolCall.id.desc())
    )
    latest_by_session: dict[int, AIChatToolCall] = {}
    for tool_call in res.scalars().all():
        generated = _extract_generated_app_from_tool(tool_call)
        if not generated:
            continue
        if target_app_id is not None and generated["app_id"] != int(target_app_id):
            continue
        latest_by_session.setdefault(tool_call.session_id, tool_call)

    out: dict[int, dict] = {}
    for session_id, tool_call in latest_by_session.items():
        generated = _extract_generated_app_from_tool(tool_call)
        if not generated:
            continue
        out[session_id] = await _generation_meta_from_generated_app(
            db,
            generated,
            tool_created_at=tool_call.created_at,
        )
    return out


async def _tool_call_generation_meta(
    db: AsyncSession,
    tool_calls: List[AIChatToolCall],
) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for tool_call in tool_calls:
        if tool_call.tool_name != "generate_app_from_doc" or tool_call.status != "success":
            continue
        generated = _extract_generated_app_from_tool(tool_call)
        if not generated:
            continue
        out[tool_call.id] = await _generation_meta_from_generated_app(
            db,
            generated,
            tool_created_at=tool_call.created_at,
        )
    return out


def _message_to_dict(m: AIChatMessage) -> dict:
    return {
        "id": m.id,
        "session_id": m.session_id,
        "role": m.role,
        "content": m.content,
        # 从 extra_meta 透出 run_id，让刷新后的历史 assistant 消息也能挂「查看本次 trace」
        "run_id": (m.extra_meta or {}).get("run_id"),
        "extra_meta": m.extra_meta or {},
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _tool_call_to_dict(t: AIChatToolCall, generation: Optional[dict] = None) -> dict:
    data = {
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
    if generation:
        data["generation"] = generation
    return data


def _attachment_to_dict(a: AIChatAttachment) -> dict:
    # 解析失败时 content_text 存的是 DOC_PARSE_ERROR_PREFIX 错误标记(非正文)。
    # 不能让 has_content_text 因此翻 True, 否则前端无法区分"解析成功"与"解析失败";
    # 同时单独透出 parse_failed + parse_error 让 UI/下游能展示失败原因。
    _ct = a.content_text or ""
    _parse_failed = _ct.startswith(DOC_PARSE_ERROR_PREFIX)
    return {
        "id": a.id,
        "session_id": a.session_id,
        "filename": a.filename,
        "kind": a.kind,
        "mime": a.mime,
        "size_bytes": a.size_bytes,
        "has_content_text": bool(_ct) and not _parse_failed,
        "parse_failed": _parse_failed,
        "parse_error": _ct[len(DOC_PARSE_ERROR_PREFIX):].strip() if _parse_failed else None,
        "has_image": bool(a.image_data_url),
        # 图片附件回带 base64 data URL, 让历史消息气泡能渲染缩略图(粘贴的截图刷新后仍可见)。
        # 非图片不带, 避免响应膨胀。
        "image_data_url": a.image_data_url if a.kind == "image" else None,
        "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None,
    }


def _artifact_to_dict(a: AIChatArtifact) -> dict:
    storage = getattr(a, "storage", None) or "text"
    is_file = storage == "file"
    # file 产物 content 为空，真实大小落在 size_bytes 列；text 产物按内容字节数算
    if is_file:
        size_bytes = a.size_bytes or 0
        preview = a.filename  # file 产物无文本内容，预览给文件名让前端渲染下载卡片
    else:
        size_bytes = len(a.content.encode("utf-8")) if a.content else 0
        preview = (a.content[:200] + "...") if len(a.content) > 200 else a.content
    return {
        "id": a.id,
        "session_id": a.session_id,
        "filename": a.filename,
        "format": a.format,
        "version": a.version,
        "storage": storage,
        "preview": preview,
        "size_bytes": size_bytes,
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
    if (getattr(s, "assistant_profile", None) or DEFAULT_ASSISTANT_PROFILE) == "system_assistant":
        current_cp_tenant = str(getattr(ctx, "control_plane_tenant_id", "") or "").strip() or None
        stored_cp_tenant = str(getattr(s, "control_plane_tenant_id", "") or "").strip() or None
        if current_cp_tenant != stored_cp_tenant:
            raise HTTPException(status_code=404, detail="会话不存在或无权限")
    return s


# ═══════════════════════════ Sessions CRUD ═══════════════════════════

@router.get("/sessions")
async def list_sessions(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 50,
    app_id: Optional[int] = None,
    mode: Optional[str] = None,
    assistant_profile: Optional[str] = None,
):
    query = (
        select(AIChatSession)
        .where(
            AIChatSession.user_id == ctx.user.id,
            AIChatSession.tenant_id == ctx.tenant_id,
        )
    )
    if app_id is not None:
        query = query.where(AIChatSession.app_id == app_id)
    if mode:
        query = query.where(AIChatSession.mode == mode)
    if assistant_profile is not None:
        try:
            profile_filter = normalize_assistant_profile(assistant_profile)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        query = query.where(AIChatSession.assistant_profile == profile_filter)
    current_cp_tenant = str(getattr(ctx, "control_plane_tenant_id", "") or "").strip() or None
    query = query.where(
        or_(
            AIChatSession.assistant_profile != "system_assistant",
            AIChatSession.control_plane_tenant_id == current_cp_tenant,
        )
    )
    query = query.order_by(desc(AIChatSession.updated_at)).limit(limit)
    res = await db.execute(query)
    sessions = res.scalars().all()
    generation_by_session = await _session_generation_meta(db, sessions, target_app_id=app_id)
    return {"sessions": [_session_to_dict(s, generation_by_session.get(s.id)) for s in sessions]}


@router.post("/sessions")
async def create_session(
    body: CreateSessionRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    purpose = assistant_model_purpose(body.assistant_profile)
    selected_llm_config_id = await _validated_selected_llm_config_id(
        db, ctx, body.selected_llm_config_id, purpose
    )
    title = body.title or "新会话"
    is_system_assistant = body.assistant_profile == "system_assistant"
    app_id = None if is_system_assistant else body.app_id
    if body.mode == "code" and body.workspace_id:
        # 代码会话从「我的开发」/clone/本地夹各入口进来,单点派生两件事:
        #  ① 标题用工作区显示名(比通用「代码会话」有意义);查不到则回退前端传的标题。
        #  ② 工作区若已绑应用(meta.project_id=Application.id)→ 会话继承该 app_id,
        #     让 code agent 拿到应用上下文(build_app_context_block),不当孤儿会话。
        try:
            info = workspace_mgr.get_workspace_info(body.workspace_id)
            ws_name = (info.get("display_name") or info.get("project_name") or "").strip()
            if ws_name:
                title = ws_name
            if app_id is None and not is_system_assistant:
                ws_proj = info.get("project_id")
                if ws_proj:
                    bound_app = (await db.execute(
                        select(Application.id).where(
                            Application.id == int(ws_proj),
                            Application.tenant_id == ctx.tenant_id,
                        )
                    )).scalar_one_or_none()
                    if bound_app is not None:
                        app_id = int(ws_proj)
        except Exception:
            pass
    s = AIChatSession(
        tenant_id=ctx.tenant_id,
        control_plane_tenant_id=_control_plane_code_tenant_id(
            ctx,
            body.mode,
            body.assistant_profile,
        ),
        user_id=ctx.user.id,
        title=title,
        selected_llm_config_id=selected_llm_config_id,
        mode="code" if body.mode == "code" else ("cowork" if body.mode == "cowork" else "chat"),
        assistant_profile=body.assistant_profile,
        status="active",
        app_id=app_id,
        workspace_id=body.workspace_id,
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
    app_id: Optional[int] = None,
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
    tool_generation_by_id = await _tool_call_generation_meta(db, tool_calls)

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

    if (s.title or "") in _DEFAULT_SESSION_TITLES:
        derived_title = _derive_session_title(
            attachments=attachments,
            artifacts=artifacts,
            messages=messages,
        )
        if derived_title:
            s.title = derived_title
            await db.commit()
            await db.refresh(s)

    generation_by_session = await _session_generation_meta(db, [s], target_app_id=app_id or getattr(s, "app_id", None))

    return {
        "session": _session_to_dict(s, generation_by_session.get(s.id)),
        "messages": [_message_to_dict(m) for m in messages],
        "tool_calls": [_tool_call_to_dict(t, tool_generation_by_id.get(t.id)) for t in tool_calls],
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
    try:
        await delete_session_with_guard(db, s.id)
    except SessionHasActiveAction as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code},
        ) from exc
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
        purpose = assistant_model_purpose(getattr(s, "assistant_profile", None))
        s.selected_llm_config_id = await _validated_selected_llm_config_id(
            db, ctx, body.selected_llm_config_id, purpose
        )
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
            except Exception as exc:
                # 不再静默吞错: 记真实异常 + 把可读原因落到 content_text,
                # 让 read_attachment 能返回"解析失败: <原因>"(桌面端缺解析库时尤为关键)。
                logger.exception("附件解析失败 filename=%s session=%s", f.filename, session_id)
                content_text = DOC_PARSE_ERROR_PREFIX + f"解析时发生异常: {exc}"

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
    """发消息 → 触发 agent loop → SSE 流式回 thinking / tool_call / message / artifact 等事件。

    切会话不丢 run(Phase2):run_agent 跑在 RunRegistry 强引用的**后台任务**里,事件发到进程内
    AiChatRunBus;本 SSE 只是订阅者,客户端断开(切会话/刷新)不杀 run。切回经 /attach 续看。
    """
    from app.ai_chat.run_bus import AiChatRunBus, ai_chat_run_registry, subscribe_run_events
    from app.harness.run_registry import RunHandle

    # 用请求级 session 校验权限并写入 user_msg（这一步必须同步落库才能让前端立即看到）
    s = await _load_session_or_404(db, session_id, ctx)
    # 守卫:同会话已有在跑 run → 挡住(单会话单 run,避免并发竞态/误丢)
    if ai_chat_run_registry.is_running(session_id):
        raise HTTPException(status_code=409, detail="该会话有任务在跑,请等它完成或先停止")
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
    is_default_title = (initial_title or "") in _DEFAULT_SESSION_TITLES

    bus = AiChatRunBus()

    async def _run_bg():
        # 后台任务:全新 AsyncSession(请求级 session 响应返回后会被清理)。事件发到 bus,不直接 yield。
        try:
            async with AsyncSessionLocal() as stream_db:
                stream_s = await stream_db.get(AIChatSession, session_id)
                if stream_s is None:
                    await bus.publish(_sse("error", {"error": "会话已被删除"}))
                    return

                await bus.publish({"event": "user_message", "data": json.dumps(user_msg_dict, ensure_ascii=False)})

                # 第一轮自动生成/推断标题。附件-only 会话也要命名。
                if is_default_title:
                    msg_count_res = await stream_db.execute(
                        select(AIChatMessage).where(
                            AIChatMessage.session_id == stream_s.id,
                            AIChatMessage.role == "user",
                        )
                    )
                    if len(msg_count_res.scalars().all()) <= 1:
                        new_title = None
                        if body.message.strip():
                            new_title = await _derive_first_turn_title(
                                stream_db, stream_s, body.message
                            )
                        if not new_title:
                            att_res = await stream_db.execute(
                                select(AIChatAttachment).where(
                                    AIChatAttachment.session_id == stream_s.id,
                                    AIChatAttachment.id.in_(body.attachment_ids or [-1]),
                                )
                            )
                            new_title = _derive_session_title(
                                user_message=body.message,
                                attachments=att_res.scalars().all(),
                            )
                        if new_title:
                            stream_s.title = new_title
                            await stream_db.commit()
                            await stream_db.refresh(stream_s)
                            await bus.publish({
                                "event": "session_updated",
                                "data": json.dumps(_session_to_dict(stream_s), ensure_ascii=False),
                            })

                async for event in run_agent(stream_db, stream_s, body.message, abort_event, section=body.section, view_context=body.view_context):
                    await bus.publish(event)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await bus.publish({"event": "error", "data": json.dumps({"error": str(e)}, ensure_ascii=False)})
        finally:
            await bus.send_sentinel()
            ai_chat_run_registry.unregister(session_id)

    task = asyncio.create_task(_run_bg())
    ai_chat_run_registry.register(
        session_id, RunHandle(task=task, event_bus=bus, run_id=None, thread_id=session_id)
    )

    async def event_stream():
        async for ev in subscribe_run_events(bus, 0):
            yield ev

    return EventSourceResponse(event_stream())


@router.post("/sessions/{session_id}/abort")
async def abort_session(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """停止键:停掉该会话在跑的 ai-chat run。

    send 解耦后 run 是 RunRegistry 强引用的 detached 后台 task —— 断 SSE 不影响它,
    只 set abort_event 在 LLM I/O 阻塞时也来不及检查 → 必须显式 task.cancel()
    (对齐 coding /coding/stop)。cancel 触发 CancelledError(BaseException,不被 _run_bg
    的 except Exception 吞)→ finally send_sentinel + unregister 收尾。
    """
    from app.ai_chat.run_bus import ai_chat_run_registry

    await _load_session_or_404(db, session_id, ctx)
    ev = get_or_create_abort_event(session_id)
    ev.set()
    # Cancel durable governed runs even when this process no longer owns the
    # detached task (for example after a restart).  The legacy response/event
    # protocol below remains unchanged.
    from app.system_assistant.session_lifecycle import cancel_session_action_runs

    if isinstance(db, AsyncSession):
        await cancel_session_action_runs(db, session_id)
    h = ai_chat_run_registry.get(session_id)
    if h and not h.task.done():
        h.task.cancel()
        # The durable run is cancelled before legacy ToolCall cleanup.  The
        # old SSE payload remains unchanged, while an in-flight governed
        # handler receives an immediately invalidated execution generation.
        now = datetime.utcnow()
        rows = (await db.execute(
            select(AIChatToolCall).where(
                AIChatToolCall.session_id == session_id,
                AIChatToolCall.status == "running",
            )
        )).scalars().all()
        for tool_call in rows:
            tool_call.status = "aborted"
            tool_call.result_text = json.dumps(
                {"ok": False, "error_code": "ABORTED", "message": "用户已停止本轮执行"},
                ensure_ascii=False,
            )
            tool_call.error_message = "用户已停止本轮执行"
            tool_call.ended_at = now
            if tool_call.started_at:
                tool_call.duration_ms = max(
                    0,
                    int((now - tool_call.started_at).total_seconds() * 1000),
                )
        await db.commit()
        return {"ok": True, "stopped": True}
    return {"ok": True, "stopped": False}


@router.get("/sessions/{session_id}/run-status")
async def ai_chat_run_status(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """该会话是否有在跑的 run + 最新 seq —— 切回会话据此决定是否 attach 续看。"""
    from app.ai_chat.run_bus import ai_chat_run_registry

    await _load_session_or_404(db, session_id, ctx)
    h = ai_chat_run_registry.get(session_id)
    if h and not h.task.done():
        return {"running": True, "last_seq": getattr(h.event_bus, "current_seq", 0), "run_id": h.run_id}
    return {"running": False, "last_seq": 0, "run_id": None}


@router.get("/sessions/{session_id}/attach")
async def ai_chat_attach(
    session_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    after_seq: int = Query(0, ge=0),
):
    """重连在跑 run 的 SSE(切会话/刷新后续看):补 seq>after_seq + 跟实时;不在跑则空流。"""
    from app.ai_chat.run_bus import ai_chat_run_registry, subscribe_run_events

    await _load_session_or_404(db, session_id, ctx)
    h = ai_chat_run_registry.get(session_id)

    async def event_stream():
        if not (h and not h.task.done()):
            return
        async for ev in subscribe_run_events(h.event_bus, after_seq):
            yield ev

    return EventSourceResponse(event_stream())


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


@router.get("/sessions/{session_id}/artifacts/{filename}/download")
async def download_artifact(
    session_id: int,
    filename: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    version: Optional[int] = None,
):
    """下载二进制产物（storage=='file'）。校验 file_path 落在会话工作区内后用 FileResponse 返回。

    浏览器用 <a href>/window.open 直接 GET 拿文件，原生不能带 Authorization header，
    所以这里 header 优先、`?token=` 兜底（与 SSE 入口同套路）。
    """
    ctx = await auth_from_header_or_query(request)
    session = await _load_session_or_404(db, session_id, ctx)
    query = select(AIChatArtifact).where(
        AIChatArtifact.session_id == session_id,
        AIChatArtifact.filename == filename,
    )
    if version is not None:
        query = query.where(AIChatArtifact.version == version)
    else:
        query = query.order_by(desc(AIChatArtifact.version))
    res = await db.execute(query.limit(1))
    a = res.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="产出物不存在")
    if (getattr(a, "storage", None) or "text") != "file" or not a.file_path:
        raise HTTPException(status_code=400, detail="该产出物不是可下载文件")
    if not session.workspace_dir:
        raise HTTPException(status_code=404, detail="会话工作区未初始化")
    # 防越界 + TOCTOU：必须落在 workspace 内且文件仍存在
    ws = Path(session.workspace_dir).resolve()
    target = Path(a.file_path).resolve()
    if ws != target and ws not in target.parents:
        raise HTTPException(status_code=400, detail="文件路径越界")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件已不存在")
    return FileResponse(
        path=str(target),
        filename=a.filename,
        media_type="application/octet-stream",
    )


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
