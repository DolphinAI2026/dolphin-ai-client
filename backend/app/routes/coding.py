"""
Coding API 路由 - aPaaS Vibe Coding 接口
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Annotated, AsyncIterator, Any
from urllib.parse import urlencode, urlparse
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request, Header
from fastapi.responses import StreamingResponse, JSONResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, Conversation, Message, Project
from app.deps import get_auth_context, AuthContext
from app.coding.scenes import SceneType, get_scene, get_all_scenes, get_scenes_by_category
from app.coding.generator import CodingGenerator, parse_files_from_response, CodeGenerationResult
from app.coding.templates import get_project_template
from app.coding.prompts import get_scene_prompt, AGENT_SYSTEM_PROMPT
from app.coding.workspace import WorkspaceManager, ProjectType, WORKSPACE_ROOT
from app.llm_client import LLMClient
from app.apaas_client import APaaSClient
from app.config import settings
from app.coding.verifier import ComponentVerifier

try:
    from app.coding.vibe_agent import VibeCodingAgent
    _VIBE_AGENT_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    if exc.name == "claude_agent_sdk":
        VibeCodingAgent = None
        _VIBE_AGENT_IMPORT_ERROR = exc
    else:
        raise

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coding", tags=["coding"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

IDE_EXCLUDED_GLOBS = (
    "**/node_modules",
    "**/dist",
    "**/coverage",
    "**/.git",
    "**/.idea",
    "**/.DS_Store",
    "**/*.zip",
)


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


def _ensure_vibe_workspace_file(ws_path: Path) -> Path:
    """为 Web IDE 生成轻量 workspace，避免直接打开庞大目录造成白屏或卡顿。"""
    workspace_file = ws_path / ".vibe-ide.code-workspace"
    workspace_payload = {
        "folders": [{"path": str(ws_path.resolve())}],
        "settings": {
            "files.exclude": {pattern: True for pattern in IDE_EXCLUDED_GLOBS},
            "search.exclude": {pattern: True for pattern in IDE_EXCLUDED_GLOBS},
            "files.watcherExclude": {pattern: True for pattern in IDE_EXCLUDED_GLOBS},
            "explorer.autoReveal": False,
            "git.autoRepositoryDetection": "openEditors",
        },
    }
    serialized = json.dumps(workspace_payload, ensure_ascii=False, indent=2)
    if not workspace_file.exists() or workspace_file.read_text(encoding="utf-8") != serialized:
        workspace_file.write_text(serialized, encoding="utf-8")
    return workspace_file


def _build_public_api_base(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def _build_ide_proxy_api_base(request: Request, ws_id: str) -> str:
    """为 code-server 场景优先生成同源代理地址，避免浏览器被 CSP 拦截直连后端。"""
    public_base = _build_public_api_base(request)
    code_server_base = (settings.code_server_base_url or "").rstrip("/")
    if not code_server_base:
        return f"{public_base}/api/coding/workspace/{ws_id}/ide"

    request_host = (request.url.hostname or "").strip().lower()
    code_server_host = (urlparse(code_server_base).hostname or "").strip().lower()
    local_hosts = {"127.0.0.1", "localhost"}
    backend_port = request.url.port

    if request_host in local_hosts and code_server_host in local_hosts and backend_port:
        return f"{code_server_base}/proxy/{backend_port}/api/coding/workspace/{ws_id}/ide"

    return f"{public_base}/api/coding/workspace/{ws_id}/ide"


def _create_ide_access_token(ctx: AuthContext, ws_id: str) -> str:
    payload = {
        "sub": str(ctx.user.id),
        "tid": ctx.tenant_id,
        "type": "ide_access",
        "ws": ws_id,
        "exp": datetime.utcnow() + timedelta(hours=8),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _verify_ide_access_token(token: str, ws_id: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=401, detail="无效或已过期的 IDE 访问令牌")

    if payload.get("type") != "ide_access" or payload.get("ws") != ws_id:
        raise HTTPException(status_code=403, detail="IDE 访问令牌与当前工作区不匹配")

    return payload


def _build_openai_chat_completions_url() -> str:
    base = settings.llm_api_base.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}/chat/completions"


# ============================================================
# 请求/响应模型
# ============================================================

class GenerateRequest(BaseModel):
    """代码生成请求"""
    scene_type: Optional[str] = None  # 场景类型，为空则自动识别
    requirement: str                   # 用户需求描述
    conversation_id: Optional[int] = None  # 关联的对话ID
    app_id: Optional[str] = None      # 关联的aPaaS应用ID（来自builder）
    module_name: Optional[str] = None  # 模块名称


class DetectSceneRequest(BaseModel):
    """场景识别请求"""
    requirement: str


class TemplateRequest(BaseModel):
    """模板生成请求"""
    scene_type: str
    module_name: str


class CodingChatRequest(BaseModel):
    """Coding对话请求（流式）"""
    scene_type: Optional[str] = None
    message: str
    conversation_id: Optional[int] = None
    app_id: Optional[str] = None
    workspace_id: Optional[str] = None  # 关联的工作区ID


class CreateWorkspaceRequest(BaseModel):
    """创建工作区请求"""
    project_type: str   # form-component, form-page, form-list, backend-api
    project_name: str   # 项目名称
    display_name: Optional[str] = None  # 展示名称
    project_id: Optional[int] = None  # 关联项目ID


class WriteFileRequest(BaseModel):
    """写入文件请求"""
    file_path: str
    content: str


class AutoPipelineRequest(BaseModel):
    """自动化 Pipeline 请求（对话式开发）"""
    message: str                           # 用户需求描述
    workspace_id: Optional[str] = None     # 已有工作区（迭代修改）
    conversation_id: Optional[int] = None  # 已有对话
    app_id: Optional[str] = None           # aPaaS 应用ID (deprecated, use project_id)
    project_id: Optional[int] = None       # 关联项目ID（优先使用项目的平台配置）
    project_type: Optional[str] = None     # 前端指定的项目类型（menu-page 等）


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


@router.post("/detect-scene")
async def detect_scene(
    req: DetectSceneRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """根据用户需求自动识别开发场景"""
    generator = CodingGenerator()
    scene_type = await generator.detect_scene(req.requirement)
    scene_info = get_scene(scene_type)
    return {
        "scene_type": scene_type.value,
        "scene_name": scene_info.name,
        "scene_description": scene_info.description,
        "conventions": scene_info.required_conventions,
    }


# ============================================================
# 模板相关接口
# ============================================================

@router.post("/template")
async def generate_template(
    req: TemplateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """生成项目模板骨架"""
    try:
        scene_type = SceneType(req.scene_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"不支持的场景类型: {req.scene_type}")

    files = get_project_template(scene_type, req.module_name)
    return {
        "scene_type": req.scene_type,
        "module_name": req.module_name,
        "files": [
            {"path": path, "content": content}
            for path, content in files.items()
        ],
    }


# ============================================================
# 代码生成接口
# ============================================================

@router.post("/generate")
async def generate_code(
    req: GenerateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """非流式代码生成"""
    user = ctx.user
    generator = CodingGenerator()

    # 确定场景类型
    if req.scene_type:
        try:
            scene_type = SceneType(req.scene_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"不支持的场景类型: {req.scene_type}")
    else:
        scene_type = await generator.detect_scene(req.requirement)

    # 获取对话历史
    history = []
    if req.conversation_id:
        history = await _get_conversation_history(db, req.conversation_id)

    # 获取应用上下文（如果关联了builder应用）
    app_context = None
    if req.app_id and user.apaas_token:
        app_context = await _get_app_context(user, req.app_id)

    # 生成代码
    result = await generator.generate(
        scene_type=scene_type,
        user_requirement=req.requirement,
        conversation_history=history,
        app_context=app_context,
    )

    # 保存到对话
    if req.conversation_id:
        await _save_coding_message(db, req.conversation_id, "user", req.requirement)
        assistant_content = json.dumps(result.to_dict(), ensure_ascii=False)
        await _save_coding_message(db, req.conversation_id, "assistant", assistant_content)

    return result.to_dict()


@router.post("/generate-stream")
async def generate_code_stream(
    req: CodingChatRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """流式代码生成（SSE）"""
    user = ctx.user
    generator = CodingGenerator()

    # 确定场景类型
    if req.scene_type:
        try:
            scene_type = SceneType(req.scene_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"不支持的场景类型: {req.scene_type}")
    else:
        scene_type = await generator.detect_scene(req.message)

    # 获取对话历史
    history = []
    if req.conversation_id:
        history = await _get_conversation_history(db, req.conversation_id)

    # 获取应用上下文
    app_context = None
    if req.app_id and user.apaas_token:
        app_context = await _get_app_context(user, req.app_id)

    # 获取工作区上下文
    workspace_context = None
    if req.workspace_id:
        workspace_context = _build_workspace_context(req.workspace_id)

    # 创建或获取对话
    conversation_id = req.conversation_id
    if not conversation_id:
        conv = Conversation(
            title=req.message[:50],
            user_id=user.id,
            tenant_id=ctx.tenant_id,
            agent_type="coding",
            workspace_id=req.workspace_id,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        conversation_id = conv.id

    # 保存用户消息
    await _save_coding_message(db, conversation_id, "user", req.message)

    async def event_generator():
        full_response = ""
        # 先发送场景信息
        yield json.dumps({
            "type": "scene_detected",
            "scene_type": scene_type.value,
            "scene_name": get_scene(scene_type).name,
            "conversation_id": conversation_id,
        }, ensure_ascii=False)

        # 流式输出代码
        async for chunk in generator.generate_stream(
            scene_type=scene_type,
            user_requirement=req.message,
            conversation_history=history,
            app_context=app_context,
            workspace_context=workspace_context,
        ):
            full_response += chunk
            yield json.dumps({
                "type": "content",
                "content": chunk,
            }, ensure_ascii=False)

        # 保存助手回复
        await _save_coding_message(db, conversation_id, "assistant", full_response)

        yield json.dumps({
            "type": "done",
            "conversation_id": conversation_id,
        }, ensure_ascii=False)

    return _event_stream_response(event_generator())


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
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in conversations
    ]


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


# ============================================================
# 工作区相关接口
# ============================================================

workspace_mgr = WorkspaceManager()


@router.post("/workspace/create")
async def create_workspace(
    req: CreateWorkspaceRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """创建新工作区（脚手架初始化）"""
    try:
        project_type = ProjectType(req.project_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的项目类型: {req.project_type}，可选: {[t.value for t in ProjectType]}"
        )

    meta = workspace_mgr.create_workspace(
        project_type=project_type,
        project_name=req.project_name,
        display_name=req.display_name,
        user_id=ctx.user.id,
        project_id=req.project_id,
    )
    meta["files"] = workspace_mgr.list_files(meta["id"])
    return meta


@router.post("/workspace/{ws_id}/install")
async def install_workspace_deps(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """安装工作区依赖（npm install）"""
    try:
        result = await workspace_mgr.install_deps(ws_id)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


@router.post("/workspace/{ws_id}/build")
async def build_workspace(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """构建工作区项目"""
    try:
        result = await workspace_mgr.build_project(ws_id)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


@router.get("/workspace/{ws_id}/download")
async def download_workspace_zip(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    type: str = Query(default="dist", description="下载类型: dist=构建产物, src=源代码"),
):
    """下载工作区打包文件（zip）"""
    import zipfile
    import io
    from fastapi.responses import StreamingResponse

    try:
        info = workspace_mgr.get_workspace_info(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")

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
):
    """获取工作区信息"""
    try:
        return workspace_mgr.get_workspace_info(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


@router.get("/workspace/{ws_id}/ide-url")
async def get_workspace_ide_url(
    ws_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    conversation_id: Optional[int] = Query(default=None, description="可选，会话ID，用于把上下文带入 Vibe IDE"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    """获取工作区的 Web IDE (code-server) URL"""
    base_url = settings.code_server_base_url
    if not base_url:
        raise HTTPException(status_code=501, detail="Web IDE 未配置，请在 .env 中设置 CODE_SERVER_BASE_URL")
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    if not ws_path.exists():
        raise HTTPException(status_code=404, detail="工作区不存在")

    effective_conversation_id = conversation_id
    if effective_conversation_id is None and db is not None:
        stmt = (
            select(Conversation)
            .where(
                Conversation.user_id == ctx.user.id,
                Conversation.tenant_id == ctx.tenant_id,
                Conversation.workspace_id == ws_id,
                Conversation.agent_type == "coding",
            )
            .order_by(Conversation.updated_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        conv = result.scalar_one_or_none()
        if conv:
            effective_conversation_id = conv.id

    ide_workspace_file = _ensure_vibe_workspace_file(ws_path)
    ide_token = _create_ide_access_token(ctx, ws_id)
    api_base = _build_ide_proxy_api_base(request, ws_id)
    query_params = {
        "workspace": str(ide_workspace_file.resolve()),
        "vibe_workspace_id": ws_id,
        "vibe_api_base": api_base,
        "vibe_ide_token": ide_token,
        "vibe_model": settings.llm_model,
    }
    if effective_conversation_id and db is not None:
        history = await _get_conversation_history(db, effective_conversation_id)
        ide_context = _build_ide_conversation_context(history)
        query_params["vibe_conversation_id"] = str(effective_conversation_id)
        if ide_context:
            query_params["vibe_context"] = ide_context

    base_url = base_url.rstrip("/")
    ide_url = f"{base_url}/?{urlencode(query_params)}"
    return {"ide_url": ide_url}


@router.post("/workspace/{ws_id}/ide/chat/completions")
async def ide_chat_completions_proxy(
    ws_id: str,
    request: Request,
    x_vibe_ide_token: Annotated[Optional[str], Header(alias="X-Vibe-IDE-Token")] = None,
    token: Optional[str] = Query(default=None),
):
    """Web IDE Chat 代理：由后端持有真实 LLM API key，浏览器只持有短时 IDE token。"""
    ide_token = x_vibe_ide_token or token
    if not ide_token:
        raise HTTPException(status_code=401, detail="缺少 IDE 访问令牌，请重新从 Builder 打开 Web IDE")

    _verify_ide_access_token(ide_token, ws_id)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效的请求体")

    upstream_url = _build_openai_chat_completions_url()
    upstream_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.llm_api_key}",
    }
    stream = bool(payload.get("stream"))

    if stream:
        async def _stream() -> AsyncIterator[bytes]:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    upstream_url,
                    headers=upstream_headers,
                    json=payload,
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        detail = body.decode("utf-8", errors="ignore") or f"LLM API {resp.status_code}"
                        raise HTTPException(status_code=resp.status_code, detail=detail)
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            yield chunk

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform"},
        )

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(
                upstream_url,
                headers=upstream_headers,
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"调用 LLM 失败: {exc}")

    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type.lower():
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    return JSONResponse(status_code=resp.status_code, content={"detail": resp.text})


@router.get("/workspace/{ws_id}/files")
async def list_workspace_files(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """列出工作区文件"""
    try:
        return workspace_mgr.list_files(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")


@router.get("/workspace/{ws_id}/file")
async def read_workspace_file(
    ws_id: str,
    file_path: str = Query(..., description="文件相对路径"),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
):
    """读取工作区文件内容"""
    try:
        content = workspace_mgr.read_file(ws_id, file_path)
        return {"path": file_path, "content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/workspace/{ws_id}/file")
async def write_workspace_file(
    ws_id: str,
    req: WriteFileRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """写入文件到工作区"""
    try:
        workspace_mgr.write_file(ws_id, req.file_path, req.content)
        return {"status": "ok", "path": req.file_path}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/workspaces")
async def list_workspaces(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """列出当前用户的所有工作区"""
    return workspace_mgr.list_user_workspaces(ctx.user.id)


@router.get("/workspace/{ws_id}/conversation")
async def get_workspace_conversation(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """获取工作区关联的对话及消息"""
    stmt = (
        select(Conversation)
        .where(
            Conversation.user_id == ctx.user.id,
            Conversation.workspace_id == ws_id,
        )
        .order_by(Conversation.updated_at.desc())
        .limit(10)
    )
    result = await db.execute(stmt)
    conversations = result.scalars().all()

    if not conversations:
        return {"conversation_id": None, "messages": []}

    selected_conv = conversations[0]
    selected_messages: list[Message] = []

    for conv in conversations:
        msg_stmt = (
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.asc())
        )
        msg_result = await db.execute(msg_stmt)
        messages = msg_result.scalars().all()
        if not selected_messages:
            selected_conv = conv
            selected_messages = messages

        has_assistant_reply = any(
            m.role == "assistant" and isinstance(m.content, str) and m.content.strip()
            for m in messages
        )
        has_multi_message_history = len(messages) >= 2
        if has_assistant_reply or has_multi_message_history:
            selected_conv = conv
            selected_messages = messages
            break

    return {
        "conversation_id": selected_conv.id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in selected_messages
        ],
    }


@router.delete("/workspace/{ws_id}")
async def delete_workspace(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """删除工作区"""
    workspace_mgr.delete_workspace(ws_id)
    return {"status": "ok"}


# ============================================================
# 辅助函数
# ============================================================

async def _get_conversation_history(
    db: AsyncSession, conversation_id: int
) -> list:
    """获取对话历史"""
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


async def _save_coding_message(
    db: AsyncSession, conversation_id: int, role: str, content: str
):
    """保存对话消息"""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
    )
    db.add(msg)
    await db.commit()


def _summarize_history_content(content: str, max_chars: int = 220) -> str:
    if not content:
        return ""

    text = str(content)
    text = text.replace("\r\n", "\n")
    text = text.replace("</think>", "").replace("<think>", "")
    text = text.replace("[TOOL_CALL]", "").replace("[/TOOL_CALL]", "")
    text = re.sub(r"```[\s\S]*?```", "[代码片段已省略]", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if len(text) > max_chars:
        text = text[:max_chars] + "...[截断]"
    return text


def _build_ide_conversation_context(history: list[dict[str, str]], max_messages: int = 6) -> str:
    if not history:
        return ""

    recent_messages = history[-max_messages:]
    lines: list[str] = []
    for item in recent_messages:
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        label = "用户" if role == "user" else "AI"
        summary = _summarize_history_content(item.get("content", ""))
        if not summary:
            continue
        lines.append(f"{label}: {summary}")

    return "\n".join(lines)[:1800]


def _build_workspace_context(ws_id: str) -> dict:
    """构建工作区上下文，用于告知 AI 现有文件结构和关键文件内容"""
    try:
        info = workspace_mgr.get_workspace_info(ws_id)
        files = info.get("files", [])
        project_type = (info.get("project_type", "") or "").lower()
        rule_files = [
            fp for fp in files
            if fp.startswith(".cursor/rules/") and fp.endswith(".mdc")
        ]

        # 按项目类型挑选关键文件，避免把表单组件规则错误带到布局/后端项目
        if project_type in {"form-component", "mobile-component"}:
            key_extensions = ('.vue', '.widget.config.js', '.editor.config.js')
            key_names = ('apaas.json', 'form-widget.mixin.js')
        elif project_type == "form-list":
            key_extensions = ('.vue', '.js')
            key_names = ('apaas.json', 'index.js')
        elif project_type == "plugin":
            key_extensions = ('.vue', '.js')
            key_names = ('apaas.json', 'admin.js', 'app.js', 'mobile.js', 'extension.js', 'tab-config.js')
        elif project_type == "layout":
            key_extensions = ('.vue',)
            key_names = ('apaas.json', 'index.js')
        elif project_type in {"menu-page", "form-page", "mobile-page"}:
            key_extensions = ('.vue', '.js')
            key_names = ('apaas.json', 'index.js')
        elif project_type == "backend-api":
            key_extensions = ('.java', '.xml', '.yml', '.yaml', '.properties', '.md')
            key_names = ('pom.xml', 'application.yml', 'application.yaml', 'application.properties')
        else:
            key_extensions = ('.vue', '.js')
            key_names = ('apaas.json', 'index.js')

        key_file_paths = list(rule_files)
        for fp in files:
            basename = fp.split('/')[-1] if '/' in fp else fp
            if fp in key_file_paths:
                continue
            if any(fp.endswith(ext) for ext in key_extensions):
                key_file_paths.append(fp)
            elif basename in key_names:
                key_file_paths.append(fp)

        key_files = {}
        for fp in key_file_paths:
            try:
                content = workspace_mgr.read_file(ws_id, fp)
                # 跳过过大的文件（如 mixin > 800行），只传摘要
                lines = content.split('\n')
                if len(lines) > 300:
                    # 对于大文件只传前50行 + 最后20行
                    content = '\n'.join(lines[:50]) + '\n// ... (省略中间部分) ...\n' + '\n'.join(lines[-20:])
                key_files[fp] = content
            except Exception:
                pass

        return {
            "workspace_id": ws_id,
            "project_name": info.get("project_name", ""),
            "project_type": info.get("project_type", ""),
            "files": files,
            "key_files": key_files,
        }
    except Exception as e:
        logger.warning(f"构建工作区上下文失败: {e}")
        return None


async def _get_app_context(user: User, app_id: str) -> dict:
    """从aPaaS平台获取应用上下文（模型、字典等）"""
    try:
        client = APaaSClient(
            tenant_id=user.apaas_tenant_id,
            token=user.apaas_token,
        )
        models = await client.query_models(app_id)
        dicts = await client.query_dicts(app_id)
        menus = await client.query_menus(app_id)

        return {
            "app_id": app_id,
            "models": [
                {
                    "name": m.get("modelName"),
                    "code": m.get("modelCode"),
                    "fields": [
                        {"name": f.get("fieldName"), "code": f.get("fieldCode"), "type": f.get("fieldType")}
                        for f in m.get("fields", m.get("dataModelFields", []))
                    ],
                }
                for m in models
            ],
            "dicts": [
                {"name": d.get("dictionaryName"), "code": d.get("dictionaryCode")}
                for d in dicts
            ],
            "menus": [
                {"name": m.get("menuName"), "id": m.get("id")}
                for m in menus
            ],
        }
    except Exception as e:
        logger.warning(f"获取应用上下文失败: {e}")
        return None


# ============================================================
# 文件上传接口
# ============================================================

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    workspace_id: Optional[str] = Query(None),
    ctx: Annotated[AuthContext, Depends(get_auth_context)] = None,
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
        ws_mgr_temp = WorkspaceManager()
        try:
            ws_info = ws_mgr_temp.get_workspace_info(workspace_id)
            save_dir = os.path.join(ws_info["path"], "uploads")
        except Exception:
            save_dir = os.path.join(tempfile.gettempdir(), "coding_uploads")
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

workspace_mgr = WorkspaceManager()


@router.post("/auto-pipeline")
async def auto_pipeline(
    req: AutoPipelineRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    自动化 Pipeline（对话式组件开发）
    串联：检测场景 → 创建工作区 → 生成代码 → 安装依赖 → 启动serve
    迭代模式（有workspace_id）：生成代码 → 写入文件（热更新自动生效）
    """
    user = ctx.user
    generator = CodingGenerator()
    ws_mgr = WorkspaceManager()

    async def pipeline_events():
        ws_id = req.workspace_id
        conversation_id = req.conversation_id
        is_iteration = ws_id is not None

        # Load project config if project_id is provided
        project = None
        project_id = req.project_id
        if project_id:
            result = await db.execute(
                select(Project).where(Project.id == project_id, Project.user_id == user.id)
            )
            project = result.scalar_one_or_none()
        elif ws_id:
            # Try to get project_id from workspace metadata
            try:
                ws_info = ws_mgr.get_workspace_info(ws_id)
                _ws_project_id = ws_info.get("project_id")
                if _ws_project_id:
                    project_id = _ws_project_id
                    result = await db.execute(
                        select(Project).where(Project.id == project_id, Project.user_id == user.id)
                    )
                    project = result.scalar_one_or_none()
            except Exception:
                pass

        try:
            # ---- 意图检测：debug/调试/预览/发布 ----
            msg_lower = req.message.strip().lower()
            is_debug_intent = any(kw in msg_lower for kw in ['debug', '调试', '预览', '帮我debug', '启动debug', '启动调试'])
            is_publish_intent = any(kw in msg_lower for kw in ['发布', '打包', '上传', 'publish', 'build'])

            # 检测 debug 模式：用户明确指定了类型就直接执行，否则先问
            _is_platform_debug = any(kw in msg_lower for kw in ['平台调试', '设计器调试', '配置调试', '平台debug', 'platform debug', '设计器'])
            _is_app_debug = any(kw in msg_lower for kw in ['应用调试', '前台调试', '看效果', '应用debug', 'app debug', '前台'])
            _debug_mode = "platform" if _is_platform_debug else ("app" if _is_app_debug else None)

            if is_debug_intent and ws_id and _debug_mode is None:
                # 用户只说了"debug"，没指定类型 → 先问
                yield _sse({"type": "content", "content": "请选择调试模式：\n\n**1. 平台调试（设计态）** — 在平台后台的表单设计器中拖入组件、配置属性\n\n**2. 应用调试（运行态）** — 在应用前台查看组件/页面的实际效果\n\n请回复 **平台调试** 或 **应用调试**"})
                yield _sse({"type": "done", "workspace_id": ws_id, "conversation_id": conversation_id})
                return

            if is_debug_intent and ws_id:
                _mode_label = "平台" if _debug_mode == "platform" else "应用"
                yield _sse({"type": "step", "step": "debug", "status": "running", "data": {"message": f"正在启动{_mode_label}调试..."}})

                ws_path = ws_mgr.get_workspace_path(ws_id)
                apaas_json_path = ws_path / "src" / "apaas.json"
                import json as _json
                apaas_config = _json.loads(apaas_json_path.read_text()) if apaas_json_path.exists() else {}
                output_name = apaas_config.get("outputName", "")
                custom_widget_list = apaas_config.get("customWidgetList", [])

                # 确保 serve 在运行
                serve_info = ws_mgr.is_serve_running(ws_id)
                if not serve_info["running"]:
                    yield _sse({"type": "step", "step": "serve", "status": "running"})
                    serve_result = await ws_mgr.start_serve(ws_id)
                    serve_port = serve_result.get("port", 8080)
                    yield _sse({"type": "step", "step": "serve", "status": "done"})
                else:
                    serve_port = serve_info["port"]

                # 从项目配置获取平台参数
                if project and project.platform_url:
                    _platform_url = _get_platform_frontend_url(project.platform_url)
                    _tenant_id = project.platform_tenant_id or settings.apaas_tenant_id
                    _app_id = project.platform_app_id or ""
                else:
                    _platform_url = _get_user_platform_url(user)
                    _tenant_id = user.apaas_tenant_id or settings.apaas_tenant_id
                    _app_id = ""

                _app_code = getattr(project, 'platform_app_code', '') if project else ''

                # 简单 debug：打开浏览器 + 注入组件，用户手动导航
                debug_result = await ws_mgr.start_debug(
                    ws_id=ws_id, serve_port=serve_port,
                    platform_url=_platform_url,
                    tenant_id=_tenant_id, app_id=_app_id,
                    output_name=output_name, custom_widget_list=custom_widget_list,
                    debug_mode=_debug_mode, app_code=_app_code,
                )

                if debug_result.get("status") == "ok":
                    yield _sse({"type": "step", "step": "debug", "status": "done"})
                    yield _sse({"type": "content", "content": f"✅ Debug 浏览器已打开！\n\n请在 Chromium 中：\n1. **登录平台**\n2. **导航到目标表单/页面**\n3. **F5 刷新**页面，组件会自动注入\n\n修改代码后刷新浏览器即可看到更新。"})
                else:
                    yield _sse({"type": "step", "step": "debug", "status": "error"})
                    yield _sse({"type": "content", "content": f"Debug 启动失败: {debug_result.get('message', '')}"})

                yield _sse({"type": "done", "workspace_id": ws_id, "conversation_id": conversation_id})
                return

            if is_publish_intent and ws_id:
                yield _sse({"type": "step", "step": "build", "status": "running", "data": {"message": "正在构建打包..."}})
                try:
                    zip_path = await ws_mgr.build_and_package(ws_id)
                    yield _sse({"type": "step", "step": "build", "status": "done"})
                    yield _sse({"type": "content", "content": f"✅ 构建完成！\n\n请点击顶部的「打包发布」按钮下载 zip 文件，然后上传到 aPaaS 平台。"})
                except Exception as e:
                    yield _sse({"type": "step", "step": "build", "status": "error"})
                    yield _sse({"type": "content", "content": f"❌ 构建失败: {str(e)}"})
                yield _sse({"type": "done", "workspace_id": ws_id, "conversation_id": conversation_id})
                return

            # ---- 意图判断：修改当前组件 vs 做新组件 ----
            if is_iteration:
                # 有工作区时，判断用户是想修改当前组件还是做一个全新的组件
                is_new_component = await _is_new_component_intent(generator, req.message, ws_id, ws_mgr)
                if is_new_component:
                    # 用户想做新组件 → 自动创建新工作区
                    is_iteration = False
                    ws_id = None
                    yield _sse({"type": "content", "content": "💡 检测到你想做一个新组件，正在为你创建新的工作区...\n\n"})

            # ---- Step 1: 检测场景 ----
            if not is_iteration:
                yield _sse({"type": "step", "step": "detect_scene", "status": "running"})
                # 前端指定了 project_type 时直接使用，不调 LLM 检测
                if req.project_type:
                    type_to_scene = {
                        "form-component": SceneType.WEB_COMPONENT,
                        "menu-page": SceneType.WEB_PAGE,
                        "form-page": SceneType.WEB_PAGE,
                        "form-list": SceneType.WEB_LIST_VIEW,
                        "backend-api": SceneType.BACKEND_API,
                        "layout": SceneType.WEB_LAYOUT,
                        "plugin": SceneType.WEB_PLUGIN,
                        "mobile-component": SceneType.MOBILE_COMPONENT,
                        "mobile-page": SceneType.MOBILE_PAGE,
                        "script-js": SceneType.SCRIPT_JS,
                        "script-python": SceneType.SCRIPT_PYTHON,
                        "script-groovy": SceneType.SCRIPT_GROOVY,
                        "business-dialog": SceneType.BUSINESS_DIALOG,
                        "ui-style": SceneType.UI_STYLE,
                        "list-custom-module": SceneType.LIST_CUSTOM_MODULE,
                        "web-login": SceneType.WEB_LOGIN,
                    }
                    # "script" 类型需要 LLM 自动识别子类型
                    if req.project_type in ("script",):
                        try:
                            scene_type = await generator.detect_scene(req.message)
                        except Exception as e:
                            logger.warning(f"脚本场景检测失败，默认 SCRIPT_JS: {e}")
                            scene_type = SceneType.SCRIPT_JS
                    else:
                        scene_type = type_to_scene.get(req.project_type, SceneType.WEB_COMPONENT)
                else:
                    try:
                        scene_type = await generator.detect_scene(req.message)
                    except Exception as e:
                        logger.warning(f"场景检测失败，默认使用 WEB_COMPONENT: {e}")
                        scene_type = SceneType.WEB_COMPONENT
                yield _sse({"type": "step", "step": "detect_scene", "status": "done",
                            "data": {"scene_type": scene_type.value}})
            else:
                # 迭代模式：从工作区元数据推断场景类型
                info = ws_mgr.get_workspace_info(ws_id)
                pt = info.get("project_type", "form-component")
                scene_map = {
                    "form-component": SceneType.WEB_COMPONENT,
                    "form-page": SceneType.WEB_PAGE,
                    "menu-page": SceneType.WEB_PAGE,
                    "form-list": SceneType.WEB_LIST_VIEW,
                    "backend-api": SceneType.BACKEND_API,
                    "layout": SceneType.WEB_LAYOUT,
                    "plugin": SceneType.WEB_PLUGIN,
                    "mobile-component": SceneType.MOBILE_COMPONENT,
                    "mobile-page": SceneType.MOBILE_PAGE,
                    "script-js": SceneType.SCRIPT_JS,
                    "script-python": SceneType.SCRIPT_PYTHON,
                    "script-groovy": SceneType.SCRIPT_GROOVY,
                    "business-dialog": SceneType.BUSINESS_DIALOG,
                    "ui-style": SceneType.UI_STYLE,
                    "list-custom-module": SceneType.LIST_CUSTOM_MODULE,
                    "web-login": SceneType.WEB_LOGIN,
                }
                scene_type = scene_map.get(pt, SceneType.WEB_COMPONENT)

            # ---- Step 2: 创建工作区 ----
            if not is_iteration:
                yield _sse({"type": "step", "step": "create_workspace", "status": "running"})
                # 从需求中提取项目名（LLM 失败时用关键词提取）
                try:
                    project_name = await _extract_project_name(generator, req.message)
                except Exception as e:
                    logger.warning(f"项目名提取失败，使用 fallback: {e}")
                    project_name = "custom-dev"
                # 前端指定的 project_type 优先（如从"页面开发"入口进来）
                project_type_str = req.project_type or _scene_to_project_type(scene_type)
                project_type_enum = ProjectType(project_type_str)
                display_name = _extract_display_name(req.message, project_type_str, project_name)
                meta = ws_mgr.create_workspace(
                    project_type_enum,
                    project_name,
                    user.id,
                    project_id=project_id,
                    display_name=display_name,
                )
                ws_id = meta["id"]
                yield _sse({"type": "step", "step": "create_workspace", "status": "done",
                            "data": {
                                "workspace_id": ws_id,
                                "project_name": meta["project_name"],
                                "display_name": meta.get("display_name", meta["project_name"]),
                            }})

            # ---- Step 3: 生成代码（Agent 模式）----
            yield _sse({"type": "step", "step": "generate", "status": "running"})

            # 创建或获取对话
            if not conversation_id:
                conv = Conversation(
                    title=req.message[:50],
                    user_id=user.id,
                    tenant_id=ctx.tenant_id,
                    agent_type="coding",
                    workspace_id=ws_id,
                )
                db.add(conv)
                await db.commit()
                await db.refresh(conv)
                conversation_id = conv.id

            await _save_coding_message(db, conversation_id, "user", req.message)

            # 获取对话历史摘要
            conversation_summary = ""
            if conversation_id:
                history = await _get_conversation_history(db, conversation_id)
                if history:
                    conversation_summary = "\n".join(
                        f"{'User' if m.get('role') == 'user' else 'Assistant'}: {m.get('content', '')[:200]}"
                        for m in history[-6:]  # Last 3 rounds
                    )

            # Use VibeCodingAgent for autonomous coding
            if VibeCodingAgent is None:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Vibe Coding Agent 依赖未安装：缺少 claude_agent_sdk。"
                        "请在 backend 虚拟环境中执行 `pip install -r requirements.txt`。"
                    ),
                ) from _VIBE_AGENT_IMPORT_ERROR
            agent = VibeCodingAgent(ws_id, system_prompt=AGENT_SYSTEM_PROMPT)
            agent_result_text = ""
            persisted_agent_output: list[str] = []
            assistant_history_saved = False

            async def _persist_agent_output_if_needed():
                nonlocal assistant_history_saved
                if assistant_history_saved:
                    return

                saved_assistant_output = "".join(persisted_agent_output).strip()
                if not saved_assistant_output:
                    saved_assistant_output = agent_result_text.strip()
                if not saved_assistant_output:
                    return

                try:
                    await _save_coding_message(db, conversation_id, "assistant", saved_assistant_output)
                    assistant_history_saved = True
                except Exception:
                    logger.exception("保存 Agent 历史失败")

            try:
                async for event in agent.run(
                    requirement=req.message,
                    conversation_summary=conversation_summary,
                    max_turns=30,
                ):
                    # Forward all agent events to frontend via SSE
                    yield _sse(event)

                    _append_agent_event_to_history(persisted_agent_output, event)

                    # Collect agent thinking for conversation history
                    if event.get("type") == "agent_thinking":
                        agent_result_text += event.get("content", "") + "\n"
                    elif event.get("type") == "agent_done":
                        if event.get("result"):
                            agent_result_text += "\n" + event["result"]
            except asyncio.CancelledError:
                await _persist_agent_output_if_needed()
                raise
            except Exception:
                await _persist_agent_output_if_needed()
                raise

            await _persist_agent_output_if_needed()

            # Agent handles file writes, npm install, and serve internally
            # Just report generation step as done
            yield _sse({"type": "step", "step": "generate", "status": "done",
                        "data": {"files": [], "file_count": 0, "agent_mode": True}})

            # For iteration mode, agent already handles everything
            if is_iteration:
                serve_status = ws_mgr.is_serve_running(ws_id)
                yield _sse({"type": "step", "step": "hot_reload", "status": "done",
                            "data": {"serve_running": serve_status["running"],
                                     "port": serve_status.get("port")}})
                yield _sse({"type": "done", "workspace_id": ws_id,
                            "conversation_id": conversation_id})
                return

            # For first-time creation, agent should have run npm install + serve
            # But check and do it as fallback if agent didn't
            serve_status = ws_mgr.is_serve_running(ws_id)
            if not serve_status["running"]:
                # ---- Step 4: 安装依赖（首次创建 fallback）----
                yield _sse({"type": "step", "step": "install", "status": "running"})
                install_result = await ws_mgr.install_deps(ws_id)
                if install_result["status"] == "error":
                    yield _sse({"type": "step", "step": "install", "status": "error",
                                "data": {"message": install_result["message"]}})
                else:
                    yield _sse({"type": "step", "step": "install", "status": "done"})

                # ---- Step 5: 启动 serve ----
                yield _sse({"type": "step", "step": "serve", "status": "running"})
                serve_result = await ws_mgr.start_serve(ws_id)
                yield _sse({"type": "step", "step": "serve", "status": "done" if serve_result["status"] == "ok" else "error",
                            "data": {"port": serve_result.get("port"),
                                     "url": f"https://localhost:{serve_result.get('port', 8080)}/"}})
            else:
                yield _sse({"type": "step", "step": "install", "status": "done"})
                yield _sse({"type": "step", "step": "serve", "status": "done",
                            "data": {"port": serve_status.get("port"),
                                     "url": f"https://localhost:{serve_status.get('port', 8080)}/"}})

            yield _sse({"type": "done", "workspace_id": ws_id,
                        "conversation_id": conversation_id})

        except Exception as e:
            logger.exception("auto-pipeline 错误")
            yield _sse({"type": "error", "message": str(e)})

    return _event_stream_response(pipeline_events(), ping=15)


@router.post("/workspace/{ws_id}/serve")
async def manage_serve(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    action: str = Query(default="start", description="start 或 stop"),
):
    """启动或停止工作区的 serve 进程"""
    ws_mgr = WorkspaceManager()
    if action == "start":
        result = await ws_mgr.start_serve(ws_id)
    elif action == "stop":
        result = await ws_mgr.stop_serve(ws_id)
    else:
        raise HTTPException(status_code=400, detail="action 必须是 start 或 stop")
    return result


@router.get("/workspace/{ws_id}/serve-status")
async def get_serve_status(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """查询 serve 运行状态"""
    ws_mgr = WorkspaceManager()
    return ws_mgr.is_serve_running(ws_id)


@router.post("/workspace/{ws_id}/publish")
async def publish_workspace(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """构建 + 打包 zip（一键发布）"""
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


@router.get("/workspace/{ws_id}/debug/screenshot/{filename}")
async def get_debug_screenshot(ws_id: str, filename: str):
    """Serve debug screenshot image"""
    import re
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
        ws_info_meta = ws_mgr.get_workspace_info(ws_id)
        _project_id = ws_info_meta.get("project_id")
    if _project_id:
        result = await db.execute(
            select(Project).where(Project.id == _project_id, Project.user_id == user.id)
        )
        project = result.scalar_one_or_none()

    if project and project.platform_url:
        _platform_url = req.platform_url or _get_platform_frontend_url(project.platform_url)
        _tenant_id = req.tenant_id or project.platform_tenant_id or settings.apaas_tenant_id
        _app_id = req.app_id or project.platform_app_id or "806997227284201472"
    else:
        _platform_url = req.platform_url or _get_user_platform_url(user)
        _tenant_id = req.tenant_id or user.apaas_tenant_id or settings.apaas_tenant_id
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
    return base + "platform/" if base else "https://apaas-dev8.dfy.definesys.cn/platform/"


def _get_user_platform_url(user) -> str:
    """从用户的平台连接信息推导出平台前端 URL"""
    base = user.apaas_base_url or settings.apaas_base_url or ""
    # apaas_base_url 通常是后端地址如 https://apaas-dev8.dfy.definesys.cn/backend
    # 平台前端地址是 https://apaas-dev8.dfy.definesys.cn/platform/
    if "/backend" in base:
        return base.replace("/backend", "/platform/")
    if base and not base.endswith("/"):
        return base + "/platform/"
    return base + "platform/" if base else "https://apaas-dev8.dfy.definesys.cn/platform/"


def _sse(data: dict) -> str:
    """SSE 事件格式化"""
    return json.dumps(data, ensure_ascii=False)


def _append_agent_event_to_history(history_parts: list[str], event: dict[str, Any]):
    """将 Agent 的关键执行输出整理成可持久化的文本记录。"""
    event_type = event.get("type")

    if event_type == "content":
        content = event.get("content")
        if isinstance(content, str) and content:
            history_parts.append(content)
        return

    if event_type == "agent_tool":
        tool_name = event.get("tool_display") or event.get("tool") or "工具"
        preview = event.get("input_preview") or ""
        if preview:
            history_parts.append(f"\n🔧 **{tool_name}** `{preview}`\n")
        else:
            history_parts.append(f"\n🔧 **{tool_name}**\n")
        return

    if event_type == "agent_result":
        preview = event.get("output_preview")
        if event.get("is_error"):
            history_parts.append(f"> ❌ {preview or '执行失败'}\n\n")
        elif isinstance(preview, str) and preview and preview != "(empty)":
            clipped = preview[:300] + "..." if len(preview) > 300 else preview
            history_parts.append(f"> ✅ {clipped}\n\n")
        else:
            history_parts.append("> ✅ 完成\n\n")
        return

    if event_type == "agent_command_output":
        chunk = event.get("chunk")
        if isinstance(chunk, str) and chunk:
            history_parts.append(chunk)
        return

    if event_type == "agent_done":
        turns = event.get("num_turns") or "?"
        history_parts.append(f"\n---\n✨ **Agent 完成** ({turns} 轮对话)\n")
        return

    if event_type == "agent_error":
        message = event.get("message") or "发生未知错误"
        history_parts.append(f"\n❌ **Agent 错误**: {message}\n")


def _scene_to_project_type(scene_type: SceneType) -> str:
    """场景类型转项目类型"""
    mapping = {
        SceneType.WEB_COMPONENT: "form-component",
        SceneType.WEB_PAGE: "form-page",
        SceneType.WEB_LIST_VIEW: "form-list",
        SceneType.WEB_LAYOUT: "layout",
        SceneType.WEB_PLUGIN: "plugin",
        SceneType.BACKEND_API: "backend-api",
        SceneType.MOBILE_COMPONENT: "mobile-component",
        SceneType.MOBILE_PAGE: "mobile-page",
        SceneType.SCRIPT_JS: "script",
        SceneType.SCRIPT_PYTHON: "script",
        SceneType.SCRIPT_GROOVY: "script",
        SceneType.BUSINESS_DIALOG: "script",
        SceneType.WEB_LOGIN: "web-login",
        SceneType.UI_STYLE: "ui-style",
        SceneType.LIST_CUSTOM_MODULE: "list-custom-module",
    }
    return mapping.get(scene_type, "form-component")


async def _extract_project_name(generator: CodingGenerator, message: str) -> str:
    """从用户需求中提取项目名称"""
    import re

    keyword_map = {
        # 组件类
        "甘特图": "gantt-chart", "审批流程": "approval-flow", "审批": "approval",
        "进度条": "progress-bar", "评分": "star-rating", "颜色选择": "color-picker",
        "颜色选择器": "color-picker", "标签": "tag-input", "图表分析": "chart-analysis",
        "图表": "chart", "日期选择": "date-picker", "日期范围": "date-range",
        "文件上传": "file-upload", "上传": "upload", "头像": "avatar",
        "签名": "signature", "二维码": "qrcode", "地图": "map-view",
        "富文本": "rich-text", "树形": "tree-select", "组织树": "org-tree",
        "组织架构树": "org-tree", "组织架构": "org-tree", "部门树": "dept-tree",
        "级联": "cascader", "数据表格": "data-table", "表格": "data-table",
        "看板": "kanban", "数据查询": "data-query", "弹窗选择": "popup-select",
        "人员选择": "person-select", "图片识别": "image-recognition",
        "截图": "screenshot", "AI分析": "ai-analysis", "拍照": "camera",
        "水印": "watermark", "倒计时": "countdown", "步骤条": "steps",
        "时间轴": "timeline", "轮播": "carousel", "抽屉": "drawer",
        "物料选择": "material-select", "地图选点": "map-picker",
        # 页面类
        "供应商管理": "supplier-mgmt", "供应商": "supplier",
        "采购管理": "purchase-mgmt", "采购": "purchase",
        "客户管理": "customer-mgmt", "客户": "customer",
        "工单管理": "work-order-mgmt", "工单": "work-order",
        "派工管理": "dispatch-mgmt", "派工": "dispatch", "智能派工": "smart-dispatch",
        "订单管理": "order-mgmt", "订单": "order",
        "库存管理": "inventory-mgmt", "库存": "inventory",
        "考勤管理": "attendance-mgmt", "考勤": "attendance",
        "报表": "report", "仪表盘": "dashboard", "数据分析": "data-analysis",
        "设备管理": "device-mgmt", "设备": "device",
        "项目管理": "project-mgmt", "任务管理": "task-mgmt",
        "合同管理": "contract-mgmt", "合同": "contract",
        "费用管理": "expense-mgmt", "费用": "expense",
        "预算管理": "budget-mgmt", "预算": "budget",
        # 其他前端类型
        "布局": "app-layout", "插件": "frontend-plugin", "登录页": "login-page",
    }

    def _slugify(candidate: str) -> str:
        text = (candidate or "").strip().lower()
        if not text:
            return ""
        text = text.replace("&", " and ")
        text = re.sub(r"[^a-z0-9\\s-]", "-", text)
        text = text.replace("_", "-")
        text = re.sub(r"\s+", "-", text)
        text = re.sub(r"-+", "-", text).strip("-")
        text = re.sub(r"^[^a-z]+", "", text)
        return text[:48].strip("-")

    async def _translate_to_slug(text: str) -> str:
        candidate = (text or "").strip()
        if not candidate:
            return ""
        try:
            llm = LLMClient()
            resp = await llm.chat_completion([
                {
                    "role": "system",
                    "content": (
                        "把用户给出的功能或模块名称转换成简短、可读的英文 kebab-case 项目名。"
                        "优先输出语义明确、2-4 段的名字，例如 `date-range`、`org-tree`、`smart-dispatch`。"
                        "只返回名称本身，不要解释。"
                    ),
                },
                {"role": "user", "content": candidate},
            ], max_tokens=80)
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            match = re.search(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\b", content.lower())
            return _slugify(match.group(1)) if match else ""
        except Exception as e:
            logger.warning(f"LLM 提取项目名失败: {e}")
            return ""

    msg_lower = (message or "").lower()

    explicit_slug = re.search(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b", msg_lower)
    if explicit_slug:
        return explicit_slug.group(1)

    for cn, en in sorted(keyword_map.items(), key=lambda item: len(item[0]), reverse=True):
        if cn in message:
            return en

    patterns = [
        r"(?:叫做|命名为|名称为|项目名为|工作区名为)\s*[`\"']?([A-Za-z][A-Za-z0-9 _-]{2,40})[`\"']?",
        r"(?:做|开发|创建|实现|搭建|写|生成|补一个|新增|增加|搞一个|做个)\s*(?:一|1)?个?\s*(.{2,24}?)(?:的?\s*(?:组件|页面|模块|系统|功能|弹窗|选择器|面板|布局|插件|登录页))",
        r"(.{2,24}?)(?:组件|页面|模块|系统|弹窗|选择器|面板|布局|插件|登录页)(?:的?\s*(?:开发|设计|需求))",
        r"(?:做|开发|创建|实现)\s*(.{2,24}?)$",
    ]

    candidates: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip("，。,.!！?？：: `\"'")
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        for cn, en in sorted(keyword_map.items(), key=lambda item: len(item[0]), reverse=True):
            if cn in candidate:
                return en
        ascii_slug = _slugify(candidate)
        if ascii_slug and ascii_slug not in {"custom", "custom-dev", "component", "page"}:
            return ascii_slug

    for candidate in candidates:
        translated = await _translate_to_slug(candidate)
        if translated and translated not in {"custom", "custom-dev", "component", "page"}:
            return translated

    translated = await _translate_to_slug(message)
    if translated and translated not in {"custom", "custom-dev", "component", "page"}:
        return translated

    return "custom-dev"


def _extract_display_name(message: str, project_type: str, fallback_name: str) -> str:
    """提取适合在工作区列表中展示的名称"""
    import re

    cleaned = re.sub(r"\s+", " ", (message or "").strip())
    if not cleaned:
        return fallback_name

    patterns = [
        r'(?:做|开发|创建|实现|搭建|写|生成|补一个|新增|增加|搞一个|搞个)\s*(?:一|1)?个?\s*(.+?)(?:组件|页面|模块|系统|功能|弹窗|选择器|面板)',
        r'(.+?)(?:组件|页面|模块|系统|功能|弹窗|选择器|面板)',
    ]
    display_name = ""
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            display_name = match.group(1).strip("，。,.!！?？：: ")
            break

    if not display_name:
        display_name = cleaned.split("，", 1)[0].split("。", 1)[0].strip()

    display_name = re.sub(
        r'^(请|帮我|帮忙|我想|我要|想要|需要|帮我做|帮我开发|做一个|做个|开发一个|开发个|实现一个|实现个|创建一个|创建个|生成一个|生成个)\s*',
        '',
        display_name,
    ).strip("，。,.!！?？：: ")

    suffix_map = {
        "form-component": "组件",
        "mobile-component": "组件",
        "form-page": "页面",
        "menu-page": "页面",
        "mobile-page": "页面",
        "form-list": "列表",
        "layout": "布局",
        "plugin": "插件",
        "backend-api": "接口",
    }
    suffix = suffix_map.get(project_type, "")
    if suffix and not any(token in display_name for token in ("组件", "页面", "选择器", "弹窗", "布局", "插件", "接口", "模块", "登录页")):
        display_name = f"{display_name}{suffix}"

    return (display_name or fallback_name)[:48]


async def _is_new_component_intent(generator: CodingGenerator, message: str, ws_id: str, ws_mgr: WorkspaceManager) -> bool:
    """判断用户消息是要修改当前组件还是做一个全新的组件"""
    import re

    # 快速关键词判断（不调 LLM）
    msg_lower = message.lower()
    new_keywords = ["做一个新", "创建一个新", "新建一个", "开发一个新", "新组件", "新工作区", "另一个组件"]
    modify_keywords = ["修改", "改一下", "调整", "优化", "加个", "删掉", "改成", "换个", "bug", "fix",
                       "空白", "渲染", "不对", "报错", "完善", "补充", "实现", "请用", "改为", "更新"]

    has_new = any(kw in msg_lower for kw in new_keywords)
    has_modify = any(kw in msg_lower for kw in modify_keywords)

    if has_new and not has_modify:
        return True
    if has_modify and not has_new:
        return False

    # 都有或都没有，用 LLM 判断
    try:
        info = ws_mgr.get_workspace_info(ws_id)
        project_name = info.get("project_name", "")

        llm = LLMClient()
        resp = await llm.chat_completion([
            {"role": "system", "content": f"当前工作区的组件是 '{project_name}'。判断用户的消息是想【修改当前组件】还是想【做一个全新的、不同的组件】。回答中必须包含 MODIFY 或 NEW 这个词。"},
            {"role": "user", "content": message}
        ], max_tokens=50)
        answer = resp.get("choices", [{}])[0].get("message", {}).get("content", "").upper()
        return "NEW" in answer
    except Exception as e:
        logger.warning(f"意图判断失败: {e}")
        return False


# ========== 组件预览 ==========

from fastapi.responses import HTMLResponse, FileResponse as StaticFileResponse
from app.coding.preview import generate_preview_html


@router.post("/workspace/{ws_id}/preview")
async def preview_workspace(ws_id: str):
    """触发构建（如需）并返回预览 URL"""
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    if not ws_path.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    # 按需构建
    ws_mgr = WorkspaceManager()
    build_result = await ws_mgr.build_if_needed(ws_id)
    if build_result.get("status") == "error":
        raise HTTPException(status_code=500, detail=f"构建失败: {build_result.get('message', '')}")

    # 读取 apaas.json
    apaas_json_path = ws_path / "src" / "apaas.json"
    apaas_config = {}
    if apaas_json_path.exists():
        with open(apaas_json_path, "r", encoding="utf-8") as f:
            apaas_config = json.load(f)

    workspace_meta = {}
    workspace_meta_path = ws_path / ".workspace.json"
    if workspace_meta_path.exists():
        with open(workspace_meta_path, "r", encoding="utf-8") as f:
            workspace_meta = json.load(f)
    output_name = apaas_config.get("outputName") or workspace_meta.get("project_name") or ws_id
    template_type = apaas_config.get("templateType", "FORM_COMPONENT")
    project_type = workspace_meta.get("project_type", "")

    return {
        "status": "ok",
        "preview_url": f"/api/coding/workspace/{ws_id}/preview/sandbox",
        "output_name": output_name,
        "template_type": template_type,
        "project_type": project_type,
        "build_message": build_result.get("message", ""),
    }


@router.get("/workspace/{ws_id}/preview/sandbox")
async def preview_sandbox(ws_id: str):
    """返回预览沙箱 HTML 页面"""
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    if not ws_path.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    # 读取 apaas.json
    apaas_json_path = ws_path / "src" / "apaas.json"
    apaas_config = {}
    if apaas_json_path.exists():
        with open(apaas_json_path, "r", encoding="utf-8") as f:
            apaas_config = json.load(f)

    workspace_meta = {}
    workspace_meta_path = ws_path / ".workspace.json"
    if workspace_meta_path.exists():
        with open(workspace_meta_path, "r", encoding="utf-8") as f:
            workspace_meta = json.load(f)
    output_name = apaas_config.get("outputName") or workspace_meta.get("project_name") or ws_id
    template_type = apaas_config.get("templateType", "FORM_COMPONENT")
    project_type = workspace_meta.get("project_type", "")
    dist_base_url = f"/api/coding/workspace/{ws_id}/preview/dist"

    html = generate_preview_html(
        template_type,
        apaas_config,
        dist_base_url,
        output_name,
        project_type=project_type,
    )
    return HTMLResponse(content=html)


@router.get("/workspace/{ws_id}/preview/dist/{filename:path}")
async def preview_dist_file(ws_id: str, filename: str):
    """静态服务预览构建产物目录下的文件"""
    output_dir = workspace_mgr.get_build_output_dir(ws_id)
    file_path = output_dir / filename

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    # 安全检查：确保文件在构建产物目录下
    try:
        file_path.resolve().relative_to(output_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    # 确定 MIME 类型
    suffix = file_path.suffix.lower()
    media_types = {
        ".js": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".map": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return StaticFileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={"Cache-Control": "no-cache"},
    )
