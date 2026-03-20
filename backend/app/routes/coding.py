"""
Coding API 路由 - aPaaS Vibe Coding 接口
"""

import json
import logging
from typing import Optional, Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, Conversation, Message
from app.deps import get_auth_context, AuthContext
from app.coding.scenes import SceneType, get_scene, get_all_scenes, get_scenes_by_category
from app.coding.generator import CodingGenerator, parse_files_from_response, CodeGenerationResult
from app.coding.templates import get_project_template
from app.coding.prompts import get_scene_prompt
from app.coding.workspace import WorkspaceManager, ProjectType
from app.llm_client import LLMClient
from app.apaas_client import APaaSClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coding", tags=["coding"])


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


class WriteFileRequest(BaseModel):
    """写入文件请求"""
    file_path: str
    content: str


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

    return EventSourceResponse(event_generator())


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
        user_id=ctx.user.id,
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
    # 查找该工作区最近的对话
    stmt = (
        select(Conversation)
        .where(
            Conversation.user_id == ctx.user.id,
            Conversation.workspace_id == ws_id,
        )
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()

    if not conv:
        return {"conversation_id": None, "messages": []}

    # 加载消息
    stmt = (
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    return {
        "conversation_id": conv.id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
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


def _build_workspace_context(ws_id: str) -> dict:
    """构建工作区上下文，用于告知 AI 现有文件结构"""
    try:
        info = workspace_mgr.get_workspace_info(ws_id)
        files = info.get("files", [])

        # 只读取 .vue 文件供 AI 参考（这些是需要修改的核心文件）
        vue_files = [f for f in files if f.endswith(".vue")]

        key_files = {}
        for fp in vue_files[:4]:
            try:
                content = workspace_mgr.read_file(ws_id, fp)
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
