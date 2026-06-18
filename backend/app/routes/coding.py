"""
Coding API 路由 - aPaaS Vibe Coding 接口
"""

import asyncio
import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Annotated, AsyncIterator, Any
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from app.crypto import decrypt_password
from app.database import get_db, AsyncSessionLocal
from app.models import User, Conversation, Message, Project, ProjectMember, Application, RegisteredWorkspace
from app.deps import get_auth_context, AuthContext, auth_from_header_or_query
from app.coding.scenes import SceneType, get_scene, get_all_scenes, get_scenes_by_category
from app.coding.workspace import WorkspaceManager, ProjectType
from app.llm_client import LLMClient
from app.apaas_client import APaaSClient
from app.config import settings
from app.project_access import require_project_access
from app.routes.applications.extension import _ensure_env_token
from app.coding.workspace_access import (
    _decorate_workspace_access,
    _ensure_workspace_access,
    _workspace_permissions,
    workspace_mgr,
)
from app.coding.deploy_service import (
    _PAGE_TYPES,
    _PROJECT_TYPE_TO_FILE_TYPE,
    _attach_dev_kits_tolerant,
    _build_and_upload_kits,
    _build_upload_form_data,
    _deploy_to_app_impl,
    _find_kit_by_filename,
    _find_self_dev_menu,
    _is_duplicate_attach_error,
    _normalize_backend_jdk,
    _query_existing_development_kits,
    _resolve_backend_runtime_jar,
    _resolve_backend_runtime_version,
    _resolve_page_register_name,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coding", tags=["coding"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# 祖先判断: 这些系统根本身或其任意子目录都拒绝(无合法用户项目落在下面)。
# /etc /var 等 resolve 后是 /private/etc /private/var, 由 /private 这条祖先兜住。
_SENSITIVE_ANCESTRY_ROOTS = {
    Path("/System"), Path("/Library"), Path("/Applications"),
    Path("/private"), Path("/usr"), Path("/bin"), Path("/sbin"),
    Path("/etc"), Path("/var"), Path("/dev"), Path("/opt"),
}


def _is_sensitive_path(rp: Path) -> bool:
    """纯路径策略判断(传入已 resolve 的路径), 不查 fs。便于单测。"""
    if rp == Path(rp.anchor):           # 文件系统根 /
        return True
    if rp == Path.home().resolve():     # 家目录根
        return True
    if rp == Path("/Users"):            # 家目录们的父 — 仅精确拦; 祖先拦会误杀 /Users/<x>/proj
        return True
    if rp.parent == Path("/Volumes"):   # 卷根 /Volumes/<x>
        return True
    for root in _SENSITIVE_ANCESTRY_ROOTS:
        if rp == root or root in rp.parents:
            return True
    return False


def _is_sensitive_dir(p: Path) -> bool:
    """拒绝把系统/家目录根当工作区交给 agent。"""
    try:
        rp = p.resolve()
    except Exception:
        return True
    if not rp.exists() or not rp.is_dir():
        return True
    return _is_sensitive_path(rp)


def _event_stream_response(
    generator: AsyncIterator[str] | AsyncIterator[dict[str, Any]],
    *,
    ping: int | None = None,
) -> EventSourceResponse:
    """统一 SSE 响应头，尽量避免云上反向代理缓冲流式输出。"""
    kwargs: dict[str, Any] = {"headers": SSE_HEADERS}
    if ping is not None:
        kwargs["ping"] = ping
    return EventSourceResponse(generator, **kwargs)


def _normalize_stream_payload(stream_messages: list) -> list[dict[str, Any]]:
    """回放流类型白名单 + 字段裁剪(文件与 DB 两个来源共用)。

    "message" = 普通 Markdown 回复(READ 只读问答的答案就是这个类型), 漏掉会让
    回放只剩 user+工具 chip、答案消失。
    """
    normalized_stream_messages: list[dict[str, Any]] = []
    for message in stream_messages or []:
        if not isinstance(message, dict):
            continue
        msg_type = str(message.get("type") or "").strip()
        content = message.get("content")
        if msg_type not in {"user", "thinking", "tool", "file_write", "file_edit", "command", "status", "error", "message"}:
            continue
        if not isinstance(content, str):
            content = ""
        normalized_item: dict[str, Any] = {
            "type": msg_type,
            "content": content,
        }
        for field in ("fileName", "filePath", "fileContent", "oldContent", "collapsed", "timestamp"):
            if field in message:
                normalized_item[field] = message[field]
        if "attachments" in message:
            from app.coding.attachments import normalize_coding_attachments

            attachments = normalize_coding_attachments(message.get("attachments"))
            if attachments:
                normalized_item["attachments"] = attachments
        normalized_stream_messages.append(normalized_item)
    return normalized_stream_messages


def _normalize_workspace_conversation_key(value: Any) -> str:
    return re.sub(r"[\s_\-:/（）()【】\[\]·.]+", "", str(value or "").strip().lower())


def _workspace_conversation_keys(workspace_meta: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for raw_value in (workspace_meta.get("display_name"), workspace_meta.get("project_name")):
        raw = str(raw_value or "").strip()
        normalized = _normalize_workspace_conversation_key(raw)
        if len(normalized) >= 3:
            keys.add(normalized)
        for prefix in ("form-page-", "apaas-custom-", "form-component-", "backend-api-", "frontend-plugin-"):
            if raw.startswith(prefix):
                stripped = _normalize_workspace_conversation_key(raw[len(prefix):])
                if len(stripped) >= 3:
                    keys.add(stripped)
    return keys


def _conversation_title_matches_workspace(conv: Conversation, workspace_meta: dict[str, Any]) -> bool:
    title = _normalize_workspace_conversation_key(getattr(conv, "title", ""))
    if not title:
        return False
    return any(key in title or title in key for key in _workspace_conversation_keys(workspace_meta))


def _pick_workspace_conversation(
    conversations: list[Conversation],
    messages_by_id: dict[int, list[Message]],
    workspace_meta: dict[str, Any],
) -> tuple[Conversation, list[Message]]:
    """Choose the active conversation for a workspace.

    Migrated/generated workspaces can be repurposed under the same workspace_id.
    Prefer a conversation whose title matches the current asset identity even if
    it has no messages yet, then fall back to the legacy "first useful history"
    behavior for normal workspaces.
    """
    for conv in conversations:
        if _conversation_title_matches_workspace(conv, workspace_meta):
            return conv, messages_by_id.get(conv.id, [])

    selected_conv = conversations[0]
    selected_messages = messages_by_id.get(selected_conv.id, [])
    for conv in conversations:
        messages = messages_by_id.get(conv.id, [])
        if not selected_messages:
            selected_conv = conv
            selected_messages = messages

        has_assistant_reply = any(
            m.role == "assistant" and isinstance(m.content, str) and m.content.strip()
            for m in messages
        )
        has_multi_message_history = len(messages) >= 2
        if has_assistant_reply or has_multi_message_history:
            return conv, messages

    return selected_conv, selected_messages


def _build_openai_chat_completions_url() -> str:
    base = settings.llm_api_base.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}/chat/completions"


# Coding 模型路由表
_CODING_MODEL_ROUTES: dict = {}


def _init_coding_model_routes():
    """从 settings 构建模型路由表（启动时调用一次）"""
    global _CODING_MODEL_ROUTES
    routes = {}

    # 默认模型（MiniMax）
    routes["default"] = {
        "url": _build_openai_chat_completions_url(),
        "api_key": settings.llm_api_key,
    }

    # DeepSeek
    if settings.coding_model_deepseek_base_url and settings.coding_model_deepseek_api_key:
        base = settings.coding_model_deepseek_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        routes["deepseek"] = {
            "url": f"{base}/chat/completions",
            "api_key": settings.coding_model_deepseek_api_key,
            "model": settings.coding_model_deepseek_model,
        }

    # Qwen
    if settings.coding_model_qwen_base_url and settings.coding_model_qwen_api_key:
        base = settings.coding_model_qwen_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        routes["qwen"] = {
            "url": f"{base}/chat/completions",
            "api_key": settings.coding_model_qwen_api_key,
            "model": settings.coding_model_qwen_model,
        }

    # GPT-5.3-Codex (via jiekou.ai, /responses endpoint)
    if settings.coding_model_codex_base_url and settings.coding_model_codex_api_key:
        base = settings.coding_model_codex_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        routes["codex"] = {
            "url": f"{base}/chat/completions",  # 会在代理中被转换为 /responses
            "api_key": settings.coding_model_codex_api_key,
            "model": settings.coding_model_codex_model,
        }

    # GPT-5.4 (via jiekou.ai)
    if settings.coding_model_gpt54_base_url and settings.coding_model_gpt54_api_key:
        base = settings.coding_model_gpt54_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        routes["gpt"] = {
            "url": f"{base}/chat/completions",
            "api_key": settings.coding_model_gpt54_api_key,
            "model": settings.coding_model_gpt54_model,
        }

    # Claude Sonnet 4.6 (via jiekou.ai)
    if settings.coding_model_sonnet_base_url and settings.coding_model_sonnet_api_key:
        base = settings.coding_model_sonnet_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        routes["sonnet"] = {
            "url": f"{base}/chat/completions",
            "api_key": settings.coding_model_sonnet_api_key,
            "model": settings.coding_model_sonnet_model,
        }

    # Claude Opus 4.6 (via jiekou.ai)
    if settings.coding_model_opus_base_url and settings.coding_model_opus_api_key:
        base = settings.coding_model_opus_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        routes["opus"] = {
            "url": f"{base}/chat/completions",
            "api_key": settings.coding_model_opus_api_key,
            "model": settings.coding_model_opus_model,
        }

    _CODING_MODEL_ROUTES = routes


# ============================================================
# 请求/响应模型
# ============================================================

class CreateWorkspaceRequest(BaseModel):
    """创建工作区请求"""
    project_type: str   # form-component, form-page, form-list, backend-api
    project_name: str   # 项目名称
    display_name: Optional[str] = None  # 展示名称
    project_id: Optional[int] = None  # 关联项目ID；应用上下文中复用为 Application.id


class WriteFileRequest(BaseModel):
    """写入文件请求"""
    file_path: str
    content: str


class AcceptWorkspaceChangesRequest(BaseModel):
    """接受工作区改动请求。file_path 为空表示接受全部。"""
    file_path: Optional[str] = None


# ============================================================
# 场景相关接口
# ============================================================

@router.get("/scenes")
async def list_scenes(category: Optional[str] = None):
    """获取所有支持的开发场景"""
    if category:
        scenes = get_scenes_by_category(category)
    else:
        scenes = get_all_scenes()
    return [
        {
            "type": s.type.value,
            "name": s.name,
            "description": s.description,
            "category": s.category,
            "platform": s.platform,
        }
        for s in scenes
    ]


# ============================================================
# 对话相关接口
# ============================================================

@router.get("/conversations")
async def list_coding_conversations(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取Coding类型的对话列表"""
    stmt = (
        select(Conversation)
        .where(
            Conversation.user_id == ctx.user.id,
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.agent_type == "coding",
        )
        .order_by(Conversation.updated_at.desc())
    )
    result = await db.execute(stmt)
    conversations = result.scalars().all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "workspace_id": c.workspace_id,
            "selected_llm_config_id": c.selected_llm_config_id,
            "coding_app_id": c.coding_app_id,  # 绑定应用,前端据此恢复「在应用上定制」绑定
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in conversations
    ]


@router.delete("/conversations/{conversation_id}")
async def delete_coding_conversation(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除一个 coding 会话(含消息)。若有关联工作区,best-effort 一并清理。

    架构语义: 会话是主单位,workspace 随会话删。Conversation.workspace_id 单值 1:1,
    不存在多会话共享同一 workspace 的情况。工作区目录已不存在(孤儿会话)等情况
    **不报错** —— 保证孤儿会话也能删掉,修掉「点 × 没反应、删不掉」的逻辑缺口。
    """
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == ctx.user.id,
                Conversation.tenant_id == ctx.tenant_id,
                Conversation.agent_type == "coding",
            )
        )
    ).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    ws_id = conv.workspace_id
    should_delete_workspace = False
    if ws_id:
        sibling_count = (
            await db.execute(
                select(Conversation.id).where(
                    Conversation.workspace_id == ws_id,
                    Conversation.id != conversation_id,
                    Conversation.tenant_id == ctx.tenant_id,
                    Conversation.agent_type == "coding",
                ).limit(1)
            )
        ).first()
        should_delete_workspace = sibling_count is None

    if ws_id and should_delete_workspace:
        try:
            await workspace_mgr.delete_workspace(ws_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[delete_conversation] 清理工作区 %s 失败(忽略,继续删会话): %s", ws_id, exc)

    await db.execute(delete(Message).where(Message.conversation_id == conversation_id))
    await db.delete(conv)
    await db.commit()
    return {"status": "ok"}


@router.get("/conversations/{conversation_id}/messages")
async def get_coding_messages(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取Coding对话的消息列表"""
    # 验证对话属于当前用户
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == ctx.user.id,
        Conversation.tenant_id == ctx.tenant_id,
        Conversation.agent_type == "coding",
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


@router.get("/conversations/{conversation_id}/replay")
async def get_coding_conversation_replay(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """会话富回放(消息 + 回放流) — 头部切会话/侧栏选择恢复结构化工具卡用。

    回放流来自 conversation_replays(按会话存, 多会话不互踩); 没有则 stream 为空,
    前端回退纯消息重建。
    """
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == ctx.user.id,
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    msg_stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    msg_result = await db.execute(msg_stmt)
    messages = msg_result.scalars().all()

    from app.coding.replay_store import load_conversation_replay

    stream = _normalize_stream_payload(await load_conversation_replay(db, conversation_id))
    return {
        "conversation_id": conversation_id,
        "selected_llm_config_id": conv.selected_llm_config_id,
        "coding_app_id": conv.coding_app_id,
        "workspace_id": conv.workspace_id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "stream_messages": stream,
    }


@router.get("/v2/conversations/{conversation_id}/workspace")
async def get_coding_conversation_workspace(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """返回 coding 会话关联的工作区 ID，供前端直接恢复原生代码工作区。"""
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == ctx.user.id,
                Conversation.tenant_id == ctx.tenant_id,
                Conversation.agent_type == "coding",
            )
        )
    ).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"conversation_id": conversation_id, "workspace_id": conv.workspace_id}


# ============================================================
# 工作区相关接口
# ============================================================

@router.post("/workspace/create")
async def create_workspace(
    req: CreateWorkspaceRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """创建新工作区（脚手架初始化）"""
    try:
        project_type = ProjectType(req.project_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的项目类型: {req.project_type}，可选: {[t.value for t in ProjectType]}"
        )

    access_role = "owner"
    if req.project_id:
        app_result = await db.execute(
            select(Application.id).where(
                Application.id == req.project_id,
                Application.tenant_id == ctx.tenant_id,
            )
        )
        is_application_binding = app_result.scalar_one_or_none() is not None
        if not is_application_binding:
            project_access = await require_project_access(
                db,
                project_id=req.project_id,
                user_id=ctx.user.id,
                tenant_id=ctx.tenant_id,
                minimum_role="member",
            )
            access_role = project_access.role

    meta = workspace_mgr.create_workspace(
        project_type=project_type,
        project_name=req.project_name,
        display_name=req.display_name,
        user_id=ctx.user.id,
        project_id=req.project_id,
        tenant_id=ctx.tenant_id,
    )
    meta["files"] = workspace_mgr.list_files(meta["id"])
    return _decorate_workspace_access(meta, access_role)


class OpenLocalWorkspaceRequest(BaseModel):
    abs_path: str
    apaas_app_id: Optional[str] = None


@router.post("/workspace/open-local")
async def open_local_workspace(
    req: OpenLocalWorkspaceRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """桌面: 打开用户本地文件夹当 external 工作区。指针进 DB, 不写用户文件夹。"""
    abs_path = (req.abs_path or "").strip()
    apaas_app_id = req.apaas_app_id
    if not abs_path:
        raise HTTPException(status_code=400, detail="abs_path 必填")
    p = Path(abs_path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail="文件夹不存在或不是目录")
    if _is_sensitive_dir(p):
        raise HTTPException(status_code=400, detail="该目录是系统/家目录根，过于宽泛，请选具体项目文件夹")
    resolved_abs = str(p.resolve())
    existing = (await db.execute(
        select(RegisteredWorkspace).where(
            RegisteredWorkspace.tenant_id == ctx.tenant_id,
            RegisteredWorkspace.abs_path == resolved_abs,
        )
    )).scalar_one_or_none()
    if existing:
        existing.last_opened_at = datetime.utcnow()
        if apaas_app_id is not None:
            existing.apaas_app_id = apaas_app_id
        await db.commit()
        ws_id = existing.ws_id
        display_name = existing.display_name
        apaas_app_id = existing.apaas_app_id
    else:
        ws_id = f"{ctx.user.id}_{uuid.uuid4().hex[:8]}"
        display_name = p.name
        db.add(RegisteredWorkspace(
            ws_id=ws_id, abs_path=resolved_abs, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
            workspace_type="external", apaas_app_id=apaas_app_id,
            display_name=display_name,
        ))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = (await db.execute(
                select(RegisteredWorkspace).where(
                    RegisteredWorkspace.tenant_id == ctx.tenant_id,
                    RegisteredWorkspace.abs_path == resolved_abs,
                )
            )).scalar_one()
            ws_id = existing.ws_id
            display_name = existing.display_name
            apaas_app_id = existing.apaas_app_id
    workspace_mgr.register_external(
        ws_id, resolved_abs,
        user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        apaas_app_id=apaas_app_id, display_name=display_name,
    )
    return {
        "ws_id": ws_id, "disk_path": resolved_abs, "display_name": display_name,
        "workspace_type": "external", "apaas_app_id": apaas_app_id,
    }


# 2026-05-19 image #25: 允许上传已有的自开发包 zip 进行二次调整。
# 流程：先用 workspace_mgr 创建一个空 ws（拿到 id + dir + meta），
# 然后清空脚手架内容，把 zip 解压到 ws 根目录，重写 .workspace.json
# 保留 meta 字段（id/user_id/tenant_id/project_id 等）。
@router.post("/workspace/import-zip")
async def import_zip_to_workspace_endpoint(
    file: UploadFile = File(...),
    project_type: Optional[str] = Query(None, description="可选：手动指定 form-component-dual / form-page / form-list 等；不传则从 package.json 自动检测"),
    project_id: Optional[int] = Query(None),
    display_name: Optional[str] = Query(None, description="工作区展示名，默认取 zip 内 package.json.name"),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """上传已有的自开发包 zip，解压成新的 coding workspace 供 AI 二次调整。

    入参：
      file          multipart 文件（必须是 .zip）
      project_type  可选，未传时从 zip 内 package.json + 目录结构自动检测
      project_id    可选，关联到某个 project
      display_name  可选，工作区展示名

    返回：workspace meta + files
    """
    import io
    import json as _json
    import shutil
    import zipfile

    # 1. 读取 + 校验 zip
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "只接受 .zip 文件")
    raw = await file.read()
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(400, f"zip 太大 ({len(raw)} bytes > 30MB)")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw), "r")
        names = zf.namelist()
    except zipfile.BadZipFile:
        raise HTTPException(400, "不是合法的 zip 文件")
    if not names:
        raise HTTPException(400, "zip 内为空")

    # 2. 检测 zip 内 single-root prefix（如 form-component-upload-src/）+ 检测 project_type
    def _strip_common_prefix(paths: list[str]) -> str:
        roots = {p.split("/", 1)[0] for p in paths if "/" in p}
        single_root = next(iter(roots)) if len(roots) == 1 and all(p.startswith(next(iter(roots)) + "/") or p == next(iter(roots)) for p in paths) else ""
        return single_root + "/" if single_root else ""

    strip_prefix = _strip_common_prefix(names)

    # 找 package.json 用于自动检测 project_type + name
    pkg_json: dict = {}
    for n in names:
        rel = n[len(strip_prefix):] if strip_prefix and n.startswith(strip_prefix) else n
        if rel == "package.json":
            try:
                pkg_json = _json.loads(zf.read(n).decode("utf-8"))
            except Exception:
                pkg_json = {}
            break

    detected_type = project_type or ""
    if not detected_type:
        # 用 package.json 的 apaas.scene 或 name prefix 判断
        apaas_meta = pkg_json.get("apaas") or {}
        if isinstance(apaas_meta, dict):
            scene = (apaas_meta.get("scene") or apaas_meta.get("type") or "").lower()
            if scene:
                detected_type = scene
        # fallback：根据目录命名/文件存在判断
        if not detected_type:
            joined = " ".join(names).lower()
            if "form-component" in joined or "widget.config.json" in joined:
                detected_type = "form-component-dual"
            elif "form-page-local" in joined or "form-page" in joined:
                detected_type = "form-page"
            elif "form-list" in joined or "form-view" in joined:
                detected_type = "form-list"
            else:
                detected_type = "form-component-dual"  # 兜底

    try:
        pt = ProjectType(detected_type)
    except ValueError:
        raise HTTPException(400, f"无法识别 project_type={detected_type!r}，请显式指定")

    pkg_name = (pkg_json.get("name") or "").strip()
    inferred_name = pkg_name or strip_prefix.rstrip("/") or f"imported-{pt.value}"
    final_display = display_name or pkg_name or inferred_name

    # 3. 复用 workspace_mgr 创建空壳（拿到 id + dir + meta；不要 access check 是空 zip 时不会 leak）
    if project_id:
        await require_project_access(
            db, project_id=project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id, minimum_role="member",
        )

    meta = workspace_mgr.create_workspace(
        project_type=pt, project_name=inferred_name, display_name=final_display,
        user_id=ctx.user.id, project_id=project_id, tenant_id=ctx.tenant_id,
    )
    ws_id = meta["id"]
    ws_path = workspace_mgr.get_workspace_path(ws_id)

    # 4. 删脚手架内容（保留 .workspace.json），解压 zip
    ws_meta_path = ws_path / ".workspace.json"
    saved_meta = ws_meta_path.read_text(encoding="utf-8") if ws_meta_path.exists() else None
    for child in ws_path.iterdir():
        if child.name == ".workspace.json":
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except FileNotFoundError:
                pass

    extracted_count = 0
    for member in zf.infolist():
        if member.is_dir():
            continue
        rel = member.filename[len(strip_prefix):] if strip_prefix and member.filename.startswith(strip_prefix) else member.filename
        if not rel or rel.startswith(("..", "/")) or ".." in rel.split("/"):
            continue
        target = ws_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        extracted_count += 1

    # 重写 meta（status: ready, imported=True）
    if saved_meta:
        try:
            meta_dict = _json.loads(saved_meta)
            meta_dict["status"] = "ready"
            meta_dict["imported_from_zip"] = file.filename
            ws_meta_path.write_text(_json.dumps(meta_dict, ensure_ascii=False, indent=2))
        except Exception:
            pass

    meta = workspace_mgr.get_workspace_info(ws_id)
    meta["imported_file_count"] = extracted_count
    return _decorate_workspace_access(meta, "owner")


@router.post("/workspace/{ws_id}/install")
async def install_workspace_deps(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """安装工作区依赖（npm install）"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    try:
        result = await workspace_mgr.install_deps(ws_id)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


@router.post("/workspace/{ws_id}/build")
async def build_workspace(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """构建工作区项目"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    try:
        result = await workspace_mgr.build_project(ws_id)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


@router.get("/workspace/{ws_id}/download")
async def download_workspace_zip(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    type: str = Query(default="dist", description="下载类型: dist=构建产物, src=源代码"),
):
    """下载工作区打包文件（zip）"""
    import zipfile
    import io
    from fastapi.responses import StreamingResponse

    info = await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")

    ws_path = workspace_mgr.get_workspace_path(ws_id)
    project_name = info.get("project_name", ws_id)

    if type == "dist":
        # 下载构建产物
        output_path = workspace_mgr.get_build_output_dir(ws_id)
        if not workspace_mgr._has_build_artifacts(output_path):
            raise HTTPException(status_code=400, detail="请先构建项目")
        target_path = output_path
        zip_name = f"{project_name}.zip"
    else:
        # 下载源代码（排除 node_modules 和 dist）
        target_path = ws_path
        zip_name = f"{project_name}-src.zip"

    # 创建 zip
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in target_path.rglob("*"):
            if file_path.is_file():
                rel = file_path.relative_to(target_path)
                rel_str = str(rel)
                # 排除 node_modules、dist（源码模式）、.DS_Store 等
                if any(part in rel_str for part in ['node_modules', '.DS_Store']):
                    continue
                if type == "src" and rel_str.startswith("dist"):
                    continue
                zf.write(file_path, rel)

        # dist 模式下，额外加入 apaas.json 和 static 目录（平台需要它们来识别组件）
        if type == "dist":
            apaas_json = ws_path / "src" / "apaas.json"
            if apaas_json.exists() and not (target_path / "apaas.json").exists():
                zf.write(apaas_json, "apaas.json")

            # 加入 static/custom/组件名/ 目录（平台需要此目录结构）
            # 从 apaas.json 的 copyAssets 读取，或用 project_name 兜底
            import json as _json
            try:
                apaas_cfg = _json.loads(apaas_json.read_text())
                copy_assets = apaas_cfg.get("copyAssets", [])
            except Exception:
                copy_assets = []

            # 创建 static 目录占位（空目录需要加一个 entry）
            if copy_assets:
                for asset_path in copy_assets:
                    # public/form-component/xxx -> static/form-component/xxx/
                    static_dir = asset_path.replace("public/", "static/", 1)
                    zf.writestr(f"{static_dir}/", "")
            else:
                zf.writestr(f"static/custom/{project_name}/", "")

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'}
    )


@router.get("/workspace/{ws_id}")
async def get_workspace_info(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取工作区信息"""
    return await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")


@router.get("/models")
async def ide_available_models_simple():
    """返回可用的 Coding 模型列表（无需 workspace 认证，供 Chat 面板模型选择器使用）"""
    if not _CODING_MODEL_ROUTES:
        _init_coding_model_routes()
    models = []
    for key, route in _CODING_MODEL_ROUTES.items():
        if key == "default":
            models.append({"id": settings.llm_model, "name": f"MiniMax ({settings.llm_model})", "provider": "minimax"})
        else:
            models.append({"id": route.get("model", key), "name": f"{key.title()} ({route.get('model', key)})", "provider": key})
    return {"models": models}


@router.get("/workspace/{ws_id}/files")
async def list_workspace_files(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出工作区文件"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    try:
        return workspace_mgr.list_files(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


async def _read_class_file_decompiled(ws_id: str, file_path: str) -> dict:
    """.class 文件按字节没法预览,反编译成文本返回(CFR 优先, javap 兜底)。"""
    from app.coding.class_decompiler import DecompileError, decompile_class_file

    ws_path = workspace_mgr.get_workspace_path(ws_id)
    target = (ws_path / file_path).resolve()
    if not str(target).startswith(str(ws_path.resolve())):
        raise HTTPException(status_code=400, detail="文件路径越界")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
    try:
        result = await asyncio.to_thread(decompile_class_file, target)
    except DecompileError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {
        "path": file_path,
        "content": result.text,
        "decompiled": True,
        "decompiler": result.tool,
    }


@router.get("/workspace/{ws_id}/file")
async def read_workspace_file(
    ws_id: str,
    file_path: str = Query(..., description="文件相对路径"),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """读取工作区文件内容;.class 返回反编译文本(decompiled: true)"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    if file_path.lower().endswith(".class"):
        return await _read_class_file_decompiled(ws_id, file_path)
    try:
        content = workspace_mgr.read_file(ws_id, file_path)
        return {"path": file_path, "content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/workspace/{ws_id}/raw")
async def download_workspace_file_raw(
    ws_id: str,
    file_path: str = Query(..., description="文件相对路径"),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """以原始字节返回工作区单文件，供二进制文件（zip/图片/字体等）下载。"""
    from fastapi.responses import FileResponse

    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    target = (ws_path / file_path).resolve()
    if not str(target).startswith(str(ws_path.resolve())):
        raise HTTPException(status_code=400, detail="文件路径越界")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
    return FileResponse(str(target), filename=target.name)


@router.post("/workspace/{ws_id}/file")
async def write_workspace_file(
    ws_id: str,
    req: WriteFileRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """写入文件到工作区"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    try:
        workspace_mgr.write_file(ws_id, req.file_path, req.content)
        return {"status": "ok", "path": req.file_path}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/workspace/{ws_id}/changes")
async def get_workspace_changes(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """工作区相对 git 基线的改动清单（文件树徽标 / 改动分组用）。git 不可用时 enabled=False。"""
    from app.coding.git_changes import collect_changes

    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    if not ws_path.exists():
        raise HTTPException(status_code=404, detail="工作区不存在")
    return await asyncio.to_thread(collect_changes, ws_path)


@router.post("/workspace/{ws_id}/changes/accept")
async def accept_workspace_changes(
    ws_id: str,
    req: AcceptWorkspaceChangesRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """把当前工作区改动收进内部 git 基线。file_path 为空表示接受全部。"""
    from app.coding.git_changes import accept_changes

    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    if not ws_path.exists():
        raise HTTPException(status_code=404, detail="工作区不存在")

    file_path = (req.file_path or "").strip()
    if file_path:
        ws_root = ws_path.resolve()
        target = (ws_root / file_path).resolve()
        try:
            file_path = target.relative_to(ws_root).as_posix()
        except ValueError:
            raise HTTPException(status_code=400, detail="文件路径越界")

    return await asyncio.to_thread(accept_changes, ws_path, file_path or None)


@router.get("/workspace/{ws_id}/file-diff")
async def get_workspace_file_diff(
    ws_id: str,
    file_path: str = Query(..., description="文件相对路径"),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """单文件相对 git 基线的 unified diff（查看器红绿对比用）。"""
    from app.coding.git_changes import file_diff

    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    if not ws_path.exists():
        raise HTTPException(status_code=404, detail="工作区不存在")
    target = (ws_path / file_path).resolve()
    if not str(target).startswith(str(ws_path.resolve())):
        raise HTTPException(status_code=400, detail="文件路径越界")
    return await asyncio.to_thread(file_diff, ws_path, file_path)


class BindWorkspaceAppRequest(BaseModel):
    app_id: Optional[int] = None  # None = 解绑


@router.post("/workspace/{ws_id}/bind-app")
async def bind_workspace_app(
    ws_id: str,
    req: BindWorkspaceAppRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """绑定/解绑工作区所属应用(写 meta.project_id)。存量迁移工作区无会话绑定, 靠这里手动归属。"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    if req.app_id is not None:
        app_row = await db.execute(
            select(Application).where(
                Application.id == req.app_id, Application.tenant_id == ctx.tenant_id,
            )
        )
        if not app_row.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="应用不存在或不属于当前租户")
    if not workspace_mgr.bind_project_id(ws_id, req.app_id):
        raise HTTPException(status_code=404, detail="工作区不存在")
    return {"status": "ok", "project_id": req.app_id}


@router.get("/workspace/{ws_id}/search")
async def search_workspace_content(
    ws_id: str,
    q: str = Query(..., min_length=1, max_length=200, description="搜索文本(字面量, 大小写不敏感)"),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """工作区全文内容搜索(文件树搜索框用)。逐行返回 path/line/text。"""
    import re as _re

    from app.coding.workspace_read_tools import search_workspace_hits

    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    if not ws_path.exists():
        raise HTTPException(status_code=404, detail="工作区不存在")
    regex = _re.compile(_re.escape(q), _re.IGNORECASE)
    hits, truncated = await asyncio.to_thread(search_workspace_hits, ws_path, regex)
    # 人用的搜索跳过构建产物(umd/zip 等) —— bundle 里的命中是噪音, 会把源码命中淹掉
    from app.coding.git_changes import _is_build_artifact
    hits = [h for h in hits if not _is_build_artifact(h["path"])]
    return {"hits": hits, "truncated": truncated}


@router.get("/workspaces")
async def list_workspaces(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出当前用户的所有工作区"""
    owned_result = await db.execute(
        select(Project.id).where(
            Project.tenant_id == ctx.tenant_id,
            Project.user_id == ctx.user.id,
        )
    )
    member_result = await db.execute(
        select(ProjectMember.project_id).where(ProjectMember.user_id == ctx.user.id)
    )
    project_ids = {row[0] for row in owned_result.all()}
    project_ids.update(row[0] for row in member_result.all())

    # ws meta 的 project_id 字段被复用为「所属应用」(Application.id, 应用锁定建工作区时注入)。
    # 可见性允许集合必须把本租户应用也算进去, 否则应用绑定的工作区在资产库直接消失。
    app_result = await db.execute(
        select(Application.id).where(Application.tenant_id == ctx.tenant_id)
    )
    application_ids = {row[0] for row in app_result.all()}
    project_ids.update(application_ids)

    workspaces = workspace_mgr.list_accessible_workspaces(
        ctx.user.id, list(project_ids), tenant_id=ctx.tenant_id
    )

    # 租户隔离收紧:list_accessible_workspaces 对「缺 tenant_id 的老 workspace」按 user_id 兜底放行,
    # 导致同一用户(如 admin)切租户后仍看到别租户的老自开发资产(「切了租户数据没变」)。
    # 这里用 workspace 关联会话的 tenant_id 推断真实归属:别租户的剔除,本租户的回填 .workspace.json
    # (回填后下次走严格过滤,自愈)。无会话的孤儿 workspace 维持 user_id 归属(仅本人可见,非跨用户泄漏)。
    legacy_ids = [str(ws.get("id")) for ws in workspaces if ws.get("tenant_id") in (None, "")]
    if legacy_ids:
        owner_rows = await db.execute(
            select(Conversation.workspace_id, Conversation.tenant_id).where(
                Conversation.workspace_id.in_(legacy_ids),
                Conversation.tenant_id.isnot(None),
            )
        )
        ws_owner_tenant: dict[str, int] = {}
        for ws_id_val, tenant_val in owner_rows.all():
            if ws_id_val and tenant_val is not None:
                ws_owner_tenant.setdefault(str(ws_id_val), int(tenant_val))
        kept: list[dict[str, Any]] = []
        for ws in workspaces:
            if ws.get("tenant_id") in (None, ""):
                owner_tenant = ws_owner_tenant.get(str(ws.get("id")))
                if owner_tenant is not None and owner_tenant != ctx.tenant_id:
                    continue  # 属于别的租户 → 隐藏
                if owner_tenant == ctx.tenant_id:
                    if workspace_mgr.stamp_tenant_id(str(ws.get("id")), ctx.tenant_id):
                        ws["tenant_id"] = ctx.tenant_id  # 回填,UI 也立即一致
            kept.append(ws)
        workspaces = kept

    # 所属应用自愈回填: project_id 缺失的 workspace 从其会话的 coding_app_id(在应用上定制)推断,
    # 写回 .workspace.json → 资产库「所属应用」列/筛选与应用详情自开发分组有数据。
    unbound_ids = [str(ws.get("id")) for ws in workspaces if not ws.get("project_id")]
    if unbound_ids:
        bind_rows = await db.execute(
            select(Conversation.workspace_id, Conversation.coding_app_id).where(
                Conversation.workspace_id.in_(unbound_ids),
                Conversation.coding_app_id.isnot(None),
            )
        )
        ws_bound_app: dict[str, int] = {}
        for ws_id_val, app_val in bind_rows.all():
            if ws_id_val and app_val is not None:
                ws_bound_app.setdefault(str(ws_id_val), int(app_val))
        for ws in workspaces:
            if not ws.get("project_id"):
                bound = ws_bound_app.get(str(ws.get("id")))
                if bound and bound in application_ids:
                    if workspace_mgr.stamp_project_id(str(ws.get("id")), bound):
                        ws["project_id"] = bound

    # external (打开本地文件夹) 工作区: 从 DB 注册表按租户合并进列表
    ext_rows = (await db.execute(
        select(RegisteredWorkspace).where(RegisteredWorkspace.tenant_id == ctx.tenant_id)
    )).scalars().all()
    for rw in ext_rows:
        workspaces.append({
            "id": rw.ws_id,
            "display_name": rw.display_name or Path(rw.abs_path).name,
            "folder_name": Path(rw.abs_path).name,
            "disk_path": rw.abs_path,
            "project_type": "external",
            "workspace_type": "external",
            "project_id": None,
            "apaas_app_id": rw.apaas_app_id,
            "tenant_id": rw.tenant_id,
            "user_id": rw.user_id,
            "updated_at": rw.last_opened_at.isoformat() if rw.last_opened_at else None,
            "status": "local",
            "project_name": rw.display_name or Path(rw.abs_path).name,
        })

    decorated: list[dict[str, Any]] = []
    for ws in workspaces:
        project_id = ws.get("project_id")
        if project_id and int(project_id) in application_ids:
            # 应用绑定(Application.id 复用 project_id 字段) → 不是协作项目, 可见性已由
            # allowed 集合控制, 不走 require_project_access(那是查 Project 表, 会 404)
            decorated.append(_decorate_workspace_access(ws, "owner"))
        elif project_id:
            access = await require_project_access(
                db,
                project_id=int(project_id),
                user_id=ctx.user.id,
                tenant_id=ctx.tenant_id,
            )
            decorated.append(_decorate_workspace_access(ws, access.role))
        else:
            decorated.append(_decorate_workspace_access(ws, "owner"))
    return decorated


@router.get("/workspace/{ws_id}/conversation")
async def get_workspace_conversation(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取工作区关联的对话及消息"""
    workspace_meta = await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    conditions = [
        Conversation.tenant_id == ctx.tenant_id,
        Conversation.workspace_id == ws_id,
        Conversation.agent_type == "coding",
    ]
    if not workspace_meta.get("project_id"):
        conditions.append(Conversation.user_id == ctx.user.id)
    stmt = select(Conversation).where(*conditions).order_by(Conversation.updated_at.desc()).limit(10)
    result = await db.execute(stmt)
    conversations = result.scalars().all()

    if not conversations:
        return {"conversation_id": None, "selected_llm_config_id": None, "messages": []}

    messages_by_id: dict[int, list[Message]] = {}
    for conv in conversations:
        msg_stmt = (
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.asc())
        )
        msg_result = await db.execute(msg_stmt)
        messages_by_id[conv.id] = msg_result.scalars().all()
    selected_conv, selected_messages = _pick_workspace_conversation(
        conversations,
        messages_by_id,
        workspace_meta,
    )

    # 富回放只读 DB(按会话, 多会话不互踩); 没有则回退 messages 表。
    from app.coding.replay_store import load_conversation_replay

    _db_stream = _normalize_stream_payload(await load_conversation_replay(db, selected_conv.id))
    replay_payload = {"messages": [], "stream_messages": _db_stream}

    response_messages = replay_payload["messages"] or [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in selected_messages
    ]

    return {
        "conversation_id": selected_conv.id,
        "selected_llm_config_id": selected_conv.selected_llm_config_id,
        "coding_app_id": selected_conv.coding_app_id,
        "messages": response_messages,
        "stream_messages": replay_payload["stream_messages"],
    }


@router.delete("/workspace/{ws_id}")
async def delete_workspace(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除工作区：先停掉所有 npm run serve 进程，再删除工作区文件夹。"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="admin")
    await workspace_mgr.delete_workspace(ws_id)
    return {"status": "ok"}


# ============================================================
# 文件上传接口
# ============================================================

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    workspace_id: Optional[str] = Query(None),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """
    上传文件（图片/文档）用于对话附件。
    - 图片: 保存到工作区或临时目录，返回文件路径
    - 文本文档(.md, .txt): 读取并返回文本内容
    - 其他文档(.pdf, .docx): 尝试提取文本，否则返回文件路径
    """
    import os
    import tempfile

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    content_bytes = await file.read()
    filename = file.filename
    content_type = file.content_type or "application/octet-stream"
    ext = os.path.splitext(filename)[1].lower()

    # Determine save directory
    if workspace_id:
        workspace_meta = await _ensure_workspace_access(workspace_id, ctx, db, minimum_project_role="member")
        save_dir = os.path.join(workspace_meta["disk_path"], "uploads")
    else:
        save_dir = os.path.join(tempfile.gettempdir(), "coding_uploads")

    os.makedirs(save_dir, exist_ok=True)

    # Generate unique filename to avoid conflicts
    import uuid
    unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    file_path = os.path.join(save_dir, unique_name)

    with open(file_path, "wb") as f:
        f.write(content_bytes)

    result = {
        "filename": filename,
        "content_type": content_type,
        "file_path": file_path,
    }
    if workspace_id:
        from urllib.parse import quote

        try:
            rel_path = Path(file_path).resolve().relative_to(Path(workspace_meta["disk_path"]).resolve())
            rel_posix = rel_path.as_posix()
            result["relative_path"] = rel_posix
            if content_type.startswith("image/"):
                result["preview_url"] = (
                    f"/api/coding/workspace/{workspace_id}/raw?file_path={quote(rel_posix, safe='')}"
                )
        except Exception:
            logger.debug("Failed to derive workspace-relative upload path: %s", file_path, exc_info=True)

    # For text-based documents, extract content
    if ext in (".md", ".txt"):
        try:
            text_content = content_bytes.decode("utf-8")
            result["content"] = text_content
        except UnicodeDecodeError:
            pass  # Binary file, just return path
    elif ext == ".docx":
        try:
            from docx import Document as DocxDocument
            import io
            doc = DocxDocument(io.BytesIO(content_bytes))
            text_content = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            result["content"] = text_content
        except ImportError:
            logger.info("python-docx not installed, returning file path only for .docx")
        except Exception as e:
            logger.warning(f"Failed to extract .docx content: {e}")
    elif ext == ".pdf":
        try:
            from markitdown import MarkItDown
            mid = MarkItDown()
            md_result = mid.convert(file_path)
            result["content"] = md_result.text_content
        except ImportError:
            logger.info("markitdown not installed, returning file path only for .pdf")
        except Exception as e:
            logger.warning(f"Failed to extract PDF content: {e}")

    return result


# ============================================================
# 自动化 Pipeline（对话式开发）
# ============================================================

@router.post("/workspace/{ws_id}/serve")
async def manage_serve(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    action: str = Query(default="start", description="start 或 stop"),
    kind: str = Query(default="web", description="serve 类型：web/mobile/h5"),
):
    """启动或停止工作区的 serve 进程"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    ws_mgr = WorkspaceManager()
    if action == "start":
        result = await ws_mgr.start_serve(ws_id, kind=kind)
    elif action == "stop":
        result = await ws_mgr.stop_serve(ws_id)
    else:
        raise HTTPException(status_code=400, detail="action 必须是 start 或 stop")
    return result


@router.get("/workspace/{ws_id}/serve-status")
async def get_serve_status(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """查询 serve 运行状态"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    ws_mgr = WorkspaceManager()
    return ws_mgr.is_serve_running(ws_id)


@router.get("/workspace/{ws_id}/serve-logs")
async def serve_logs_stream(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(auth_from_header_or_query)],
    last_seen_seq: int = Query(0, ge=0, description="上次收到的 seq；断线重连补发 > N 的历史"),
    heartbeat_seconds: int = Query(15, ge=5, le=120, description="心跳间隔（秒）"),
):
    """订阅 serve 进程的实时日志（SSE）。

    event 名 "log"，data = {seq, stream, line}；先补发 seq > last_seen_seq 的历史再实时跟随。
    EventSource 无法带 header → 走 ?token= 鉴权（auth_from_header_or_query）。
    """
    async with AsyncSessionLocal() as check_db:
        await _ensure_workspace_access(ws_id, ctx, check_db, minimum_project_role="member")

    ws_mgr = WorkspaceManager()

    async def event_stream() -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=512)

        async def _pump_logs():
            try:
                async for ev in ws_mgr.iter_serve_logs(ws_id, last_seen_seq):
                    await queue.put(("log", ev))
            except Exception as e:
                logger.warning("serve-logs pump err: %s", e)
            finally:
                await queue.put(None)

        async def _pump_heartbeat():
            while True:
                await asyncio.sleep(heartbeat_seconds)
                await queue.put(("heartbeat", {"seq": 0}))

        pump_task = asyncio.create_task(_pump_logs())
        hb_task = asyncio.create_task(_pump_heartbeat())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event_name, payload = item
                yield {
                    "event": event_name,
                    "id": str(payload.get("seq", 0)),
                    "data": json.dumps(payload, ensure_ascii=False),
                }
        finally:
            pump_task.cancel()
            hb_task.cancel()
            for t in (pump_task, hb_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    return _event_stream_response(event_stream(), ping=heartbeat_seconds)


@router.post("/workspace/{ws_id}/publish")
async def publish_workspace(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """构建 + 打包 zip（一键发布）"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="admin")
    ws_mgr = WorkspaceManager()
    try:
        zip_path = await ws_mgr.build_and_package(ws_id)
        # 返回下载链接
        from fastapi.responses import FileResponse
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=zip_path.split("/")[-1] if isinstance(zip_path, str) else zip_path.name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class UploadToPlatformRequest(BaseModel):
    env_id: int


@router.post("/workspace/{ws_id}/upload-to-platform")
async def upload_workspace_to_platform(
    ws_id: str,
    body: UploadToPlatformRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """构建 + 打包 zip，然后上传到指定的平台环境"""
    import time
    import uuid
    from app.models import PlatformEnv

    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="admin")

    # 1. 查询平台环境（验证属于当前 tenant）
    result = await db.execute(
        select(PlatformEnv).where(PlatformEnv.id == body.env_id)
    )
    env = result.scalar_one_or_none()
    if not env:
        raise HTTPException(status_code=404, detail="平台环境不存在")
    if ctx.tenant_id and env.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=403, detail="无权访问该平台环境")
    if not env.token:
        raise HTTPException(status_code=400, detail="平台环境未登录，请先在环境管理中连接")

    # 1b. 确保 token 有效，过期则用保存的账号密码自动重新登录
    async def _refresh_env_token(env, db) -> str:
        if not env.username or not env.password_enc:
            raise HTTPException(status_code=400, detail="平台 token 已过期且未保存登录凭证，请在环境管理中重新连接")
        try:
            password = decrypt_password(env.password_enc)
            apaas = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id)
            login_result = await apaas.login(env.username, password)
            new_token = login_result.get("token") if isinstance(login_result, dict) else None
            if not new_token:
                raise Exception("登录返回中未包含 token")
            env.token = new_token
            env.status = "connected"
            await db.commit()
            return new_token
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"平台 token 已过期，自动重新登录失败: {e}")

    # 2. 构建 + 打包
    ws_mgr = WorkspaceManager()
    ws_path = ws_mgr.get_workspace_path(ws_id)
    meta = ws_mgr._read_meta(ws_path)
    project_type = meta.get("project_type", "")
    display_name = meta.get("display_name") or meta.get("project_name", ws_id)

    # 双端模板：构建两个包，各自上传
    if project_type == ProjectType.FORM_COMPONENT_DUAL.value:
        try:
            dual_packages = await ws_mgr.build_and_package_dual(ws_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"双端构建失败: {e}")

        add_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/add/developmentKit"
        update_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/update/developmentKit"

        async def _do_upload_file(token: str, file_path: Path, ft: str, existing_kit: Optional[dict]):
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            form_data = _build_upload_form_data(
                file_type=ft,
                description=f"{display_name} - 由 apaas-builder 上传",
                version_code=uuid.uuid4().hex,
                upload_id=str(int(time.time() * 1000)),
                existing_kit=existing_kit,
            )
            target_url = update_url if existing_kit else add_url
            async with httpx.AsyncClient(verify=False, timeout=120.0) as http:
                return await http.post(
                    target_url,
                    headers={
                        "xdaptenantid": env.platform_tenant_id,
                        "xdaptoken": token,
                        "xdaptimestamp": str(int(time.time() * 1000)),
                    },
                    files={"file": (file_path.name, file_bytes, "application/zip")},
                    data=form_data,
                )

        # 双端：用 PC outputName（无 .zip / 无 -m 后缀）作为 keyWord 一次查询，
        # PC 包 form-xxx.zip 和 mobile 包 form-xxx-m.zip 都能被模糊命中
        web_file_name = next(
            (Path(p).name for p, ft in dual_packages if ft == "FRONTCOMPONENT"),
            None,
        )
        default_name = web_file_name or (Path(dual_packages[0][0]).name if dual_packages else "")
        # 去掉 .zip 后缀做 keyWord（平台模糊匹配，不能带后缀）
        query_keyword = default_name[:-4] if default_name.endswith(".zip") else default_name
        existing_kits = await _query_existing_development_kits(
            env.base_url, env.platform_tenant_id, env.token, query_keyword,
        )

        upload_results = []
        for zip_path_str, ft in dual_packages:
            file_path = Path(zip_path_str)
            existing_kit = _find_kit_by_filename(existing_kits, file_path.name)
            action = "update" if existing_kit else "create"
            logger.info(
                f"[upload-to-platform] {file_path.name} → {action}"
                + (f" (id={existing_kit.get('id')})" if existing_kit else "")
            )

            try:
                response = await _do_upload_file(env.token, file_path, ft, existing_kit)
            except httpx.RequestError as e:
                logger.exception(f"[upload-to-platform] 上传 {file_path.name} 失败: {target_url}")
                err_detail = str(e) or repr(e)
                raise HTTPException(
                    status_code=502,
                    detail=f"上传 {file_path.name} 请求失败: {type(e).__name__}: {err_detail}（目标 URL: {target_url}）",
                )
            try:
                resp_data = response.json()
            except Exception:
                raise HTTPException(status_code=502, detail=f"平台响应非JSON，状态码: {response.status_code}")

            def _is_unauthorized(data: dict) -> bool:
                msg = (data.get("message") or data.get("msg") or "").lower()
                code = data.get("code")
                return response.status_code == 401 or code == 401 or "unauthorized" in msg

            if _is_unauthorized(resp_data):
                new_token = await _refresh_env_token(env, db)
                # token 刷新后整个列表重新查一次，避免 mobile 包那条还在用过期 token 的结果
                existing_kits = await _query_existing_development_kits(
                    env.base_url, env.platform_tenant_id, new_token, query_keyword,
                )
                existing_kit = _find_kit_by_filename(existing_kits, file_path.name)
                try:
                    response = await _do_upload_file(new_token, file_path, ft, existing_kit)
                    resp_data = response.json()
                except Exception as e:
                    raise HTTPException(status_code=502, detail=f"刷新 token 后重试失败: {e}")

            upload_results.append({
                "file": file_path.name,
                "fileType": ft,
                "action": action,
                "response": resp_data,
            })

        action_summary = ", ".join(
            f"{r['file']}({'更新' if r['action'] == 'update' else '新增'})" for r in upload_results
        )
        return {
            "status": "ok",
            "message": f"双端上传完成：{action_summary}",
            "results": upload_results,
        }

    # 单端项目：原有逻辑
    try:
        zip_path = await ws_mgr.build_and_package(ws_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"构建失败: {e}")

    file_type = _PROJECT_TYPE_TO_FILE_TYPE.get(project_type)
    if not file_type:
        raise HTTPException(status_code=400, detail=f"不支持上传的项目类型: {project_type}")

    # 4. 上传到平台（token 过期时自动刷新后重试一次）
    add_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/add/developmentKit"
    update_url = f"{env.base_url.rstrip('/')}/xdap-app/selfdevelopment/update/developmentKit"

    # 后端项目：直接上传业务 JAR，并确保 runtime JAR 在资源池里可用。
    _backend_project_types = {"backend-api", "backend-feign", "backend-scheduled"}
    if project_type in _backend_project_types:
        output_dir = ws_mgr._get_build_output_dir(ws_path)
        jar_files = [j for j in output_dir.glob("*.jar") if not j.name.endswith(".original")]
        if not jar_files:
            raise HTTPException(status_code=500, detail="未找到编译产物 JAR，请先在 IDE 中构建项目")
        runtime_jar = _resolve_backend_runtime_jar(ws_path)
        upload_packages = [
            {
                "path": jar_files[0],
                "content_type": "application/java-archive",
                "description": f"{display_name} - 由 apaas-builder 上传",
                "upload_policy": "update_if_exists",
            },
            {
                "path": runtime_jar,
                "content_type": "application/java-archive",
                "description": f"{runtime_jar.stem} - aPaaS 后端运行时依赖",
                "upload_policy": "missing_only",
            },
        ]
    else:
        upload_packages = [{
            "path": Path(zip_path),
            "content_type": "application/zip",
            "description": f"{display_name} - 由 apaas-builder 上传",
            "upload_policy": "update_if_exists",
        }]

    async def _do_upload(token: str, package: dict, existing_kit: Optional[dict]):
        file_path = Path(package["path"])
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        form_data = _build_upload_form_data(
            file_type=file_type,
            description=str(package["description"]),
            version_code=uuid.uuid4().hex,
            upload_id=str(int(time.time() * 1000)),
            existing_kit=existing_kit,
        )
        target_url = update_url if existing_kit else add_url
        async with httpx.AsyncClient(verify=False, timeout=120.0) as http:
            return await http.post(
                target_url,
                headers={
                    "xdaptenantid": env.platform_tenant_id,
                    "xdaptoken": token,
                        "xdaptimestamp": str(int(time.time() * 1000)),
                    },
                    files={"file": (file_path.name, file_bytes, str(package["content_type"]))},
                    data=form_data,
                )

    def _is_unauthorized(data: dict, response_status: int) -> bool:
        msg = (data.get("message") or data.get("msg") or "").lower()
        code = data.get("code")
        return response_status == 401 or code == 401 or "unauthorized" in msg

    upload_results = []
    for package in upload_packages:
        upload_file_path = Path(package["path"])
        # 按完整文件名查，runtime-*.jar 已存在时复用，不重复上传。
        existing_kits = await _query_existing_development_kits(
            env.base_url, env.platform_tenant_id, env.token, upload_file_path.name,
        )
        existing_kit = _find_kit_by_filename(existing_kits, upload_file_path.name)
        action = "update" if existing_kit else "create"
        if existing_kit and package.get("upload_policy") == "missing_only":
            upload_results.append({
                "file": upload_file_path.name,
                "fileType": file_type,
                "action": "reuse",
                "kitId": str(existing_kit.get("id") or ""),
                "response": {"code": "ok", "message": "already exists"},
            })
            continue

        try:
            response = await _do_upload(env.token, package, existing_kit)
        except httpx.RequestError as e:
            logger.exception(f"[upload-to-platform] 单端上传失败 base_url={env.base_url}")
            err_detail = str(e) or repr(e)
            raise HTTPException(
                status_code=502,
                detail=f"上传请求失败: {type(e).__name__}: {err_detail}（目标平台 base_url: {env.base_url}）",
            )

        # 5. 解析响应；若 token 过期则刷新后重试一次
        try:
            resp_data = response.json()
        except Exception:
            raise HTTPException(status_code=502, detail=f"平台响应非JSON，状态码: {response.status_code}")

        if _is_unauthorized(resp_data, response.status_code):
            new_token = await _refresh_env_token(env, db)
            existing_kits = await _query_existing_development_kits(
                env.base_url, env.platform_tenant_id, new_token, upload_file_path.name,
            )
            existing_kit = _find_kit_by_filename(existing_kits, upload_file_path.name)
            action = "update" if existing_kit else "create"
            try:
                response = await _do_upload(new_token, package, existing_kit)
                resp_data = response.json()
            except httpx.RequestError as e:
                logger.exception(f"[upload-to-platform] 单端 token 刷新后重试上传失败 base_url={env.base_url}")
                err_detail = str(e) or repr(e)
                raise HTTPException(
                    status_code=502,
                    detail=f"上传请求失败: {type(e).__name__}: {err_detail}（目标平台 base_url: {env.base_url}）",
                )
            except Exception:
                raise HTTPException(status_code=502, detail=f"平台响应非JSON，状态码: {response.status_code}")

        code = resp_data.get("code")
        if code not in ("ok", 200):
            msg = resp_data.get("message") or resp_data.get("msg") or "上传失败"
            raise HTTPException(status_code=500, detail=msg)

        upload_results.append({
            "file": upload_file_path.name,
            "fileType": file_type,
            "action": action,
            "response": resp_data,
        })

    client = APaaSClient(base_url=env.base_url, tenant_id=env.platform_tenant_id, token=env.token)
    uploaded_kits = []
    for package in upload_packages:
        file_name = Path(package["path"]).name
        kits = await client.query_app_dev_kits("", file_name=file_name)
        for kit in kits:
            if kit.get("fileName") == file_name and kit.get("id"):
                uploaded_kits.append({
                    "id": str(kit["id"]),
                    "fileName": file_name,
                    "fileType": str(kit.get("fileType") or file_type),
                })
                break

    action_summary = ", ".join(
        f"{r['file']}({'复用' if r['action'] == 'reuse' else '更新' if r['action'] == 'update' else '新增'})"
        for r in upload_results
    )
    return {
        "status": "ok",
        "message": f"上传完成：{action_summary}",
        "action": upload_results[0]["action"] if len(upload_results) == 1 else "multi",
        "results": upload_results,
        "uploaded_kits": uploaded_kits,
        "kit_ids": [kit["id"] for kit in uploaded_kits],
    }


class DeployToAppRequest(BaseModel):
    local_app_id: Optional[int] = None   # bound 模式传本地 app_id;lib 模式不传


@router.post("/workspace/{ws_id}/deploy-to-app")
async def deploy_to_app(
    ws_id: str,
    body: DeployToAppRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """装回应用 / 发布到资产库:见 _deploy_to_app_impl。"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="admin")
    return await _deploy_to_app_impl(ws_id, body.local_app_id, ctx, db)


@router.get("/workspace/{ws_id}/debug/screenshot/{filename}")
async def get_debug_screenshot(
    ws_id: str,
    filename: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Serve debug screenshot image"""
    import re
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    # Sanitize filename to prevent directory traversal
    if not re.match(r'^[\w\-\.]+\.(png|jpg|jpeg)$', filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    screenshot_path = workspace_mgr.get_workspace_path(ws_id) / "debug" / "screenshots" / filename
    if not screenshot_path.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    from fastapi.responses import FileResponse
    return FileResponse(str(screenshot_path), media_type="image/png")


class DebugRequest(BaseModel):
    """Debug 请求（参数可选，优先从项目配置读取，回退到用户平台连接信息）"""
    platform_url: Optional[str] = None
    tenant_id: Optional[str] = None
    app_id: Optional[str] = None
    project_id: Optional[int] = None
    debug_mode: str = "app"  # "platform"（设计态） or "app"（运行态）
    form_id: Optional[str] = None   # 用户指定的表单ID（为空则自动创建）
    menu_id: Optional[str] = None   # 用户指定的菜单ID


@router.post("/workspace/{ws_id}/debug")
async def debug_workspace(
    ws_id: str,
    req: DebugRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """启动 Debug 模式：确保 serve 运行 + 启动 Puppeteer 注入组件到平台"""
    ws_mgr = WorkspaceManager()
    workspace_meta = await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")

    # 1. 确保 serve 在运行
    serve_info = ws_mgr.is_serve_running(ws_id)
    if not serve_info["running"]:
        serve_result = await ws_mgr.start_serve(ws_id)
        if serve_result["status"] != "ok":
            raise HTTPException(status_code=500, detail=f"启动 serve 失败: {serve_result.get('message', '')}")
        serve_port = serve_result["port"]
    else:
        serve_port = serve_info["port"]

    # 2. 读取 apaas.json 获取组件信息
    ws_path = ws_mgr.get_workspace_path(ws_id)
    apaas_json_path = ws_path / "src" / "apaas.json"
    if not apaas_json_path.exists():
        raise HTTPException(status_code=400, detail="apaas.json 不存在")

    import json as _json
    apaas_config = _json.loads(apaas_json_path.read_text())
    output_name = apaas_config.get("outputName", "")
    custom_widget_list = apaas_config.get("customWidgetList", [])

    # 3. 从项目配置 / 请求参数 / 用户平台连接信息获取 debug 参数
    user = ctx.user
    project = None
    _project_id = req.project_id
    if not _project_id:
        # Try to get project_id from workspace metadata
        _project_id = workspace_meta.get("project_id")
    if _project_id:
        access = await require_project_access(
            db,
            project_id=int(_project_id),
            user_id=user.id,
            tenant_id=ctx.tenant_id,
            minimum_role="member",
        )
        project = access.project

    if project and project.platform_url:
        _platform_url = req.platform_url or _get_platform_frontend_url(project.platform_url)
        _tenant_id = req.tenant_id or user.apaas_tenant_id or project.platform_tenant_id or ""
        _app_id = req.app_id or project.platform_app_id or "806997227284201472"
    else:
        _platform_url = req.platform_url or _get_user_platform_url(user)
        _tenant_id = req.tenant_id or user.apaas_tenant_id or ""
        _app_id = req.app_id or "806997227284201472"

    # 4. 获取 app_code（用于应用 debug 模式）
    _app_code = ""
    if project:
        _app_code = getattr(project, 'platform_app_code', '') or ''

    # 获取 platform_token 和 platform_backend_url（自动创建表单需要）
    _apaas_token = ""
    _platform_backend_url = ""
    if project:
        _apaas_token = getattr(project, 'platform_token', '') or ''
        _platform_backend_url = getattr(project, 'platform_url', '') or ''

    # 从组件配置中提取组件名称
    _component_name = ""
    if custom_widget_list:
        _component_name = custom_widget_list[0].get("name", "") or custom_widget_list[0].get("code", "")

    # 5. 启动 Puppeteer debug（后台进程）
    debug_result = await ws_mgr.start_debug(
        ws_id=ws_id,
        serve_port=serve_port,
        platform_url=_platform_url,
        tenant_id=_tenant_id,
        app_id=_app_id,
        output_name=output_name,
        custom_widget_list=custom_widget_list,
        debug_mode=req.debug_mode,
        app_code=_app_code,
        form_id=req.form_id or "",
        menu_id=req.menu_id or "",
        component_name=_component_name,
        apaas_token=_apaas_token,
        platform_backend_url=_platform_backend_url,
    )

    return debug_result


def _get_platform_frontend_url(backend_url: str) -> str:
    """从平台后端 URL 推导出平台前端 URL"""
    base = backend_url or ""
    if "/backend" in base:
        return base.replace("/backend", "/platform/")
    if base and not base.endswith("/"):
        return base + "/platform/"
    return base + "platform/" if base else ""


def _get_user_platform_url(user) -> str:
    """从用户的平台连接信息推导出平台前端 URL"""
    base = user.apaas_base_url or settings.apaas_base_url or ""
    # apaas_base_url 通常是后端地址，平台前端地址由它推导。
    if "/backend" in base:
        return base.replace("/backend", "/platform/")
    if base and not base.endswith("/"):
        return base + "/platform/"
    return base + "platform/" if base else ""


def _sse(data: dict) -> str:
    """SSE 事件格式化"""
    return json.dumps(data, ensure_ascii=False)
