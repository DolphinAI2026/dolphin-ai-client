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
from app.coding.prompts import get_scene_prompt, AGENT_SYSTEM_PROMPT
from app.coding.workspace import WorkspaceManager, ProjectType, WORKSPACE_ROOT
from app.coding.vibe_agent import VibeCodingAgent
from app.llm_client import LLMClient
from app.apaas_client import APaaSClient
from app.config import settings
from app.coding.verifier import ComponentVerifier

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


class AutoPipelineRequest(BaseModel):
    """自动化 Pipeline 请求（对话式开发）"""
    message: str                           # 用户需求描述
    workspace_id: Optional[str] = None     # 已有工作区（迭代修改）
    conversation_id: Optional[int] = None  # 已有对话
    app_id: Optional[str] = None           # aPaaS 应用ID


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

    ws_path = WORKSPACE_ROOT / ws_id
    project_name = info.get("project_name", ws_id)

    if type == "dist":
        # 下载构建产物
        dist_path = ws_path / "dist"
        if not dist_path.exists():
            raise HTTPException(status_code=400, detail="请先构建项目")
        target_path = dist_path
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
            if apaas_json.exists():
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
    """构建工作区上下文，用于告知 AI 现有文件结构和关键文件内容"""
    try:
        info = workspace_mgr.get_workspace_info(ws_id)
        files = info.get("files", [])

        # 读取所有 AI 需要参考的关键文件
        # 包括：所有 .vue 文件、widget.config.js、editor.config.js、apaas.json、mixin
        key_extensions = ('.vue', '.widget.config.js', '.editor.config.js')
        key_names = ('apaas.json', 'form-widget.mixin.js')

        key_file_paths = []
        for fp in files:
            basename = fp.split('/')[-1] if '/' in fp else fp
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

        try:
            # ---- 意图检测：debug/调试/预览/发布 ----
            msg_lower = req.message.strip().lower()
            is_debug_intent = any(kw in msg_lower for kw in ['debug', '调试', '预览', '帮我debug', '启动debug', '启动调试'])
            is_publish_intent = any(kw in msg_lower for kw in ['发布', '打包', '上传', 'publish', 'build'])

            if is_debug_intent and ws_id:
                yield _sse({"type": "step", "step": "debug", "status": "running", "data": {"message": "正在自动登录平台..."}})
                ws_path = WORKSPACE_ROOT / ws_id
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

                # 从用户的平台连接信息获取 debug 参数（不再硬编码）
                _platform_url = _get_user_platform_url(user)
                _tenant_id = user.apaas_tenant_id or settings.apaas_tenant_id
                _app_id = req.app_id or "806997227284201472"

                # 自动化 Debug（登录 + 导航 + 截图）
                debug_result = await ws_mgr.start_auto_debug(
                    ws_id=ws_id, serve_port=serve_port,
                    platform_url=_platform_url,
                    tenant_id=_tenant_id, app_id=_app_id,
                    output_name=output_name, custom_widget_list=custom_widget_list,
                )

                if debug_result.get("status") == "ok":
                    yield _sse({"type": "step", "step": "debug", "status": "done"})

                    # Send screenshot URLs to frontend
                    screenshots = debug_result.get("screenshots", [])
                    for sc in screenshots:
                        yield _sse({"type": "screenshot", "url": f"/api/coding/workspace/{ws_id}/debug/screenshot/{sc}"})

                    # AI verification
                    yield _sse({"type": "step", "step": "verify", "status": "running", "data": {"message": "AI 正在分析截图..."}})
                    verifier = ComponentVerifier()
                    requirement = req.message
                    verify_result = await verifier.analyze_screenshot(ws_id, requirement)

                    if verify_result.passed:
                        yield _sse({"type": "step", "step": "verify", "status": "done"})
                        yield _sse({"type": "content", "content": "组件验证通过！组件在表单设计器中正常显示。"})
                    else:
                        yield _sse({"type": "step", "step": "verify", "status": "error"})
                        yield _sse({"type": "content", "content": f"发现问题：{verify_result.issues}\n\n修复建议：{verify_result.fix_suggestion}"})
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
                scene_type = await generator.detect_scene(req.message)
                yield _sse({"type": "step", "step": "detect_scene", "status": "done",
                            "data": {"scene_type": scene_type.value}})
            else:
                # 迭代模式：从工作区元数据推断场景类型
                info = ws_mgr.get_workspace_info(ws_id)
                pt = info.get("project_type", "form-component")
                scene_map = {
                    "form-component": SceneType.WEB_COMPONENT,
                    "form-page": SceneType.WEB_PAGE,
                    "form-list": SceneType.WEB_LIST_VIEW,
                    "backend-api": SceneType.BACKEND_API,
                }
                scene_type = scene_map.get(pt, SceneType.WEB_COMPONENT)

            # ---- Step 2: 创建工作区 ----
            if not is_iteration:
                yield _sse({"type": "step", "step": "create_workspace", "status": "running"})
                # 从需求中提取项目名
                project_name = await _extract_project_name(generator, req.message)
                project_type_str = _scene_to_project_type(scene_type)
                project_type_enum = ProjectType(project_type_str)
                meta = ws_mgr.create_workspace(project_type_enum, project_name, user.id)
                ws_id = meta["id"]
                yield _sse({"type": "step", "step": "create_workspace", "status": "done",
                            "data": {"workspace_id": ws_id, "project_name": meta["project_name"]}})

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
            agent = VibeCodingAgent(ws_id, system_prompt=AGENT_SYSTEM_PROMPT)
            agent_result_text = ""

            async for event in agent.run(
                requirement=req.message,
                conversation_summary=conversation_summary,
                max_turns=30,
            ):
                # Forward all agent events to frontend via SSE
                yield _sse(event)

                # Collect agent thinking for conversation history
                if event.get("type") == "agent_thinking":
                    agent_result_text += event.get("content", "") + "\n"
                elif event.get("type") == "agent_done":
                    if event.get("result"):
                        agent_result_text += "\n" + event["result"]

            # Save agent output to conversation
            if agent_result_text.strip():
                await _save_coding_message(db, conversation_id, "assistant", agent_result_text.strip())

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

    return EventSourceResponse(pipeline_events())


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
    screenshot_path = WORKSPACE_ROOT / ws_id / "debug" / "screenshots" / filename
    if not screenshot_path.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    from fastapi.responses import FileResponse
    return FileResponse(str(screenshot_path), media_type="image/png")


class DebugRequest(BaseModel):
    """Debug 请求（参数可选，优先从用户平台连接信息读取）"""
    platform_url: Optional[str] = None
    tenant_id: Optional[str] = None
    app_id: Optional[str] = None


@router.post("/workspace/{ws_id}/debug")
async def debug_workspace(
    ws_id: str,
    req: DebugRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
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
    ws_path = WORKSPACE_ROOT / ws_id
    apaas_json_path = ws_path / "src" / "apaas.json"
    if not apaas_json_path.exists():
        raise HTTPException(status_code=400, detail="apaas.json 不存在")

    import json as _json
    apaas_config = _json.loads(apaas_json_path.read_text())
    output_name = apaas_config.get("outputName", "")
    custom_widget_list = apaas_config.get("customWidgetList", [])

    # 3. 从请求参数或用户平台连接信息获取 debug 参数
    user = ctx.user
    _platform_url = req.platform_url or _get_user_platform_url(user)
    _tenant_id = req.tenant_id or user.apaas_tenant_id or settings.apaas_tenant_id
    _app_id = req.app_id or "806997227284201472"

    # 4. 启动 Puppeteer debug（后台进程）
    debug_result = await ws_mgr.start_debug(
        ws_id=ws_id,
        serve_port=serve_port,
        platform_url=_platform_url,
        tenant_id=_tenant_id,
        app_id=_app_id,
        output_name=output_name,
        custom_widget_list=custom_widget_list,
    )

    return debug_result


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


def _scene_to_project_type(scene_type: SceneType) -> str:
    """场景类型转项目类型"""
    mapping = {
        SceneType.WEB_COMPONENT: "form-component",
        SceneType.WEB_PAGE: "form-page",
        SceneType.WEB_LIST_VIEW: "form-list",
        SceneType.BACKEND_API: "backend-api",
        SceneType.MOBILE_COMPONENT: "form-component",
        SceneType.MOBILE_PAGE: "form-page",
    }
    return mapping.get(scene_type, "form-component")


async def _extract_project_name(generator: CodingGenerator, message: str) -> str:
    """从用户需求中提取项目名称"""
    import re

    # 先用简单规则快速提取（不调 LLM）
    keyword_map = {
        "甘特图": "gantt-chart", "审批": "approval-flow", "进度条": "progress-bar",
        "评分": "star-rating", "颜色选择": "color-picker", "标签": "tag-input",
        "图表": "chart", "日期": "date-picker", "上传": "file-upload",
        "头像": "avatar", "签名": "signature", "二维码": "qrcode",
        "地图": "map-view", "富文本": "rich-text", "树形": "tree-select",
        "级联": "cascader", "表格": "data-table", "看板": "kanban",
    }
    msg_lower = message.lower()
    for cn, en in keyword_map.items():
        if cn in msg_lower:
            return en

    # LLM 提取
    try:
        llm = LLMClient()
        resp = await llm.chat_completion([
            {"role": "system", "content": "从用户需求中提取一个简短的英文项目名称（kebab-case格式）。\n\n示例：\n- 做一个评分组件 → star-rating\n- 创建审批流程页面 → approval-flow\n- 甘特图组件 → gantt-chart\n\n直接返回名称，格式如 xxx-yyy，不要其他内容。"},
            {"role": "user", "content": message}
        ], max_tokens=100)
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")

        # 从内容中用正则提取 kebab-case 名称
        matches = re.findall(r'\b([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b', content.lower())
        if matches:
            # 取最后一个匹配（通常是最终答案）
            name = matches[-1]
            if name and name != "custom-component":
                return name

        # fallback：清理整个内容
        name = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        name = name.strip('"').strip("'").lower()
        name = re.sub(r'[^a-z0-9-]', '-', name).strip('-')
        name = re.sub(r'-+', '-', name)
        return name if name and len(name) > 2 and name != "custom-component" else "custom-component"
    except Exception as e:
        logger.warning(f"提取项目名失败: {e}")
        return "custom-component"


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
