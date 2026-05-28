"""Vibe Coding chat routes — 1 workspace = 1 thread。

端点（都挂 /online-coding 前缀，跟 online_coding.py 同 prefix）：
  GET    /workspaces/{ws_id}/chat                  获取 thread + messages + tool_calls + todos
  POST   /workspaces/{ws_id}/chat/send             发消息，SSE 流式跑 agent
  POST   /workspaces/{ws_id}/chat/abort            中断当前 agent loop
  PATCH  /workspaces/{ws_id}/chat                  更新 thread（模型切换 / 标题）
  DELETE /workspaces/{ws_id}/chat                  清空 thread（删消息 / 工具调用 / todos）
  GET    /workspaces/{ws_id}/chat/llm-configs      列出本租户可用 LLM 配置（不按 purpose 过滤）
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc, delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.database import get_db, AsyncSessionLocal
from app.deps import AuthContext, get_auth_context
from app.models import (
    LLMConfig,
    VibeCodingThread,
    VibeCodingMessage,
    VibeCodingToolCall,
)
from app.vibe_coding.agent import run_agent
from app.vibe_coding.docker_runtime import get_runtime as get_docker_runtime
from app.vibe_coding.workspace import find_workspace

router = APIRouter(prefix="/online-coding", tags=["vibe-coding-chat"])


# ─────────────────────────── Schemas ───────────────────────────

class AttachmentInput(BaseModel):
    """前端附件 — image / file 两类
    - kind='image'：image_data_url 是 base64 data URL，直接喂多模态 LLM
    - kind='file' ：mime + base64 data URL，会保存到 workspace 的 .vibe-attachments/，agent 自己 read
    """
    kind: str  # 'image' | 'file'
    filename: str
    mime: Optional[str] = None
    # data:image/png;base64,xxxxx
    data_url: str


class SendMessageRequest(BaseModel):
    message: str
    attachments: Optional[list[AttachmentInput]] = None


class UpdateThreadRequest(BaseModel):
    title: Optional[str] = None
    selected_llm_config_id: Optional[int] = None


# ─────────────────────────── In-memory abort registry ───────────────────────────

_thread_aborts: dict[int, asyncio.Event] = {}


def _get_or_create_abort(thread_id: int) -> asyncio.Event:
    ev = _thread_aborts.get(thread_id)
    if ev is None:
        ev = asyncio.Event()
        _thread_aborts[thread_id] = ev
    return ev


def _reset_abort(thread_id: int) -> None:
    ev = _thread_aborts.get(thread_id)
    if ev:
        ev.clear()


# ─────────────────────────── 序列化 ───────────────────────────

def _thread_to_dict(t: VibeCodingThread) -> dict:
    return {
        "id": t.id,
        "workspace_id": t.workspace_id,
        "tenant_id": t.tenant_id,
        "owner_user_id": t.owner_user_id,
        "title": t.title,
        "status": t.status,
        "selected_llm_config_id": t.selected_llm_config_id,
        "todos": t.todos or [],
        "requirement_baseline": t.requirement_baseline or {
            "roles": [], "features": [], "flows": [],
            "external": [], "ai_points": [], "acceptance": [],
        },
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _message_to_dict(m: VibeCodingMessage) -> dict:
    return {
        "id": m.id,
        "thread_id": m.thread_id,
        "role": m.role,
        "content": m.content,
        "user_id": m.user_id,
        "extra_meta": m.extra_meta or {},
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _tool_call_to_dict(t: VibeCodingToolCall) -> dict:
    return {
        "id": t.id,
        "thread_id": t.thread_id,
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


# ─────────────────────────── 鉴权 + thread 取/建 ───────────────────────────

def _verify_workspace_access(workspace_id: str, ctx: AuthContext) -> dict:
    """返回 workspace meta；找不到或无权访问就 raise。"""
    found = find_workspace(workspace_id)
    if not found:
        raise HTTPException(status_code=404, detail="Vibe Coding 工作区不存在")
    _, meta = found
    if int(meta.get("user_id") or 0) != ctx.user.id:
        # TODO Step 2: 多人协作时查 vibe_coding_workspace_members
        raise HTTPException(status_code=403, detail="无权访问该 workspace")
    return meta


async def _get_or_create_thread(
    db: AsyncSession, workspace_id: str, ctx: AuthContext, ws_meta: dict
) -> VibeCodingThread:
    res = await db.execute(
        select(VibeCodingThread).where(VibeCodingThread.workspace_id == workspace_id)
    )
    thread = res.scalar_one_or_none()
    if thread:
        return thread
    title = (ws_meta.get("task") or "").strip() or "新对话"
    if len(title) > 60:
        title = title[:60]
    thread = VibeCodingThread(
        workspace_id=workspace_id,
        tenant_id=ctx.tenant_id,
        owner_user_id=ctx.user.id,
        title=title,
        status="active",
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return thread


# ═══════════════════════════ Endpoints ═══════════════════════════

@router.get("/workspaces/{workspace_id}/chat")
async def get_chat(
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """返回 thread + 历史 messages + tool_calls。
    Tool-use 占位 assistant 消息（content 空 + extra_meta.tool_calls 非空）会过滤掉，
    它们只是跨轮重建用的。
    """
    meta = _verify_workspace_access(workspace_id, ctx)
    thread = await _get_or_create_thread(db, workspace_id, ctx, meta)

    msg_res = await db.execute(
        select(VibeCodingMessage)
        .where(VibeCodingMessage.thread_id == thread.id)
        .order_by(VibeCodingMessage.id.asc())
    )
    all_msgs = msg_res.scalars().all()

    def _is_tool_use_placeholder(m: VibeCodingMessage) -> bool:
        if m.role != "assistant":
            return False
        if (m.content or "").strip():
            return False
        meta = m.extra_meta if isinstance(m.extra_meta, dict) else None
        return bool(meta and meta.get("tool_calls"))

    messages = [m for m in all_msgs if not _is_tool_use_placeholder(m)]

    tc_res = await db.execute(
        select(VibeCodingToolCall)
        .where(VibeCodingToolCall.thread_id == thread.id)
        .order_by(VibeCodingToolCall.id.asc())
    )
    tool_calls = tc_res.scalars().all()

    return {
        "thread": _thread_to_dict(thread),
        "messages": [_message_to_dict(m) for m in messages],
        "tool_calls": [_tool_call_to_dict(t) for t in tool_calls],
    }


@router.patch("/workspaces/{workspace_id}/chat")
async def update_thread(
    workspace_id: str,
    body: UpdateThreadRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = _verify_workspace_access(workspace_id, ctx)
    thread = await _get_or_create_thread(db, workspace_id, ctx, meta)
    if body.title is not None:
        thread.title = body.title
    if body.selected_llm_config_id is not None:
        # 0 / 负数 → 视为清空
        if body.selected_llm_config_id > 0:
            from app.routes.llm_configs import get_active_llm_config_by_id
            cfg = await get_active_llm_config_by_id(db, ctx.tenant_id, body.selected_llm_config_id)
            if not cfg:
                raise HTTPException(status_code=400, detail="所选模型不可用或不属于当前租户")
            thread.selected_llm_config_id = cfg.id
        else:
            thread.selected_llm_config_id = None
    await db.commit()
    await db.refresh(thread)
    return _thread_to_dict(thread)


@router.delete("/workspaces/{workspace_id}/chat")
async def clear_thread(
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """清空 thread 内容（保留 thread 本体，重置 todos + 删消息 + 工具调用）。"""
    meta = _verify_workspace_access(workspace_id, ctx)
    thread = await _get_or_create_thread(db, workspace_id, ctx, meta)
    await db.execute(sql_delete(VibeCodingToolCall).where(VibeCodingToolCall.thread_id == thread.id))
    await db.execute(sql_delete(VibeCodingMessage).where(VibeCodingMessage.thread_id == thread.id))
    thread.todos = None
    await db.commit()
    await db.refresh(thread)
    _thread_aborts.pop(thread.id, None)
    return {"ok": True, "thread": _thread_to_dict(thread)}


@router.post("/workspaces/{workspace_id}/chat/abort")
async def abort_chat(
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = _verify_workspace_access(workspace_id, ctx)
    thread = await _get_or_create_thread(db, workspace_id, ctx, meta)
    ev = _get_or_create_abort(thread.id)
    ev.set()
    return {"ok": True}


@router.post("/workspaces/{workspace_id}/chat/send")
async def send_message(
    workspace_id: str,
    body: SendMessageRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """发消息 → 跑 agent → SSE 流式返回事件。"""
    meta = _verify_workspace_access(workspace_id, ctx)
    thread = await _get_or_create_thread(db, workspace_id, ctx, meta)
    _reset_abort(thread.id)
    abort_event = _get_or_create_abort(thread.id)

    has_attachments = bool(body.attachments)
    if not (body.message or "").strip() and not has_attachments:
        raise HTTPException(status_code=400, detail="message 不能为空")

    # 处理附件：图片留 data_url 直接喂多模态 LLM；文件落盘 .vibe-attachments/ 让 agent 自己 read
    # 对 docx/xlsx/pdf/pptx 等二进制文档，额外提取纯文本写到 .vibe-attachments/{name}.txt，
    # 让 agent 直接 read_file 看里面的内容（不然 LLM 看 raw bytes 没意义）
    attachment_meta: list[dict] = []
    multimodal_for_agent: list[dict] = []  # OpenAI multimodal content 数组（仅当轮）
    extracted_doc_texts: list[tuple[str, str]] = []  # (filename, text) — 附加到 user message
    if has_attachments:
        from pathlib import Path
        import base64 as _b64
        import time as _time
        # 落盘目录：跟 workspace 共享，方便 agent 通过 read_file 直接看
        found = find_workspace(workspace_id)
        if found:
            ws_dir, _meta = found
            from app.routes import online_coding as _oc
            repo_dir = _oc._repo_path(ws_dir)
            attach_dir = repo_dir / ".vibe-attachments"
            attach_dir.mkdir(parents=True, exist_ok=True)
            ts = int(_time.time())
            for idx, att in enumerate(body.attachments or []):
                # 解 data url
                try:
                    header, b64data = att.data_url.split(",", 1)
                    raw = _b64.b64decode(b64data)
                except Exception:
                    continue
                safe_name = att.filename.replace("/", "_").replace("\\", "_")[:120]
                fname = f"{ts}-{idx}-{safe_name}"
                fpath = attach_dir / fname
                try:
                    fpath.write_bytes(raw)
                except Exception:
                    continue
                rel_path = f".vibe-attachments/{fname}"
                meta_entry = {
                    "kind": att.kind,
                    "filename": att.filename,
                    "mime": att.mime,
                    "path": rel_path,
                    "size": len(raw),
                }
                # 二进制文档（docx/xlsx/pdf/pptx等）：提取纯文本写 .txt 方便 agent 读
                ext = (att.filename.rsplit(".", 1)[-1] if "." in att.filename else "").lower()
                doc_exts = {"pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt"}
                if att.kind != "image" and ext in doc_exts:
                    try:
                        from io import BytesIO
                        from starlette.datastructures import UploadFile as _StarUpload
                        from app.routes.chat import _parse_uploaded_document as _parse_doc
                        stub = _StarUpload(filename=att.filename, file=BytesIO(raw))
                        text = await _parse_doc(stub)
                        if text and text.strip():
                            txt_path = attach_dir / f"{fname}.txt"
                            txt_path.write_text(text, encoding="utf-8")
                            meta_entry["text_path"] = f".vibe-attachments/{fname}.txt"
                            # 短文本（< 8KB）直接附到 user message 让 agent 立刻看到
                            if len(text) < 8000:
                                extracted_doc_texts.append((att.filename, text))
                            else:
                                # 长文档加提示让 agent 主动 read_file
                                extracted_doc_texts.append((
                                    att.filename,
                                    f"[文档过长 {len(text)} 字，已存为 {meta_entry['text_path']}，请用 read_file 读取]",
                                ))
                    except Exception as exc:
                        logger.warning("解析附件文档失败 %s: %s", att.filename, exc)
                attachment_meta.append(meta_entry)
                # 仅 image 注入 multimodal content
                if att.kind == "image":
                    multimodal_for_agent.append({
                        "type": "image_url",
                        "image_url": {"url": att.data_url},
                    })

    # 把提取的文档文本拼到 user message 末尾，agent 不需要主动 read_file 就能看
    if extracted_doc_texts:
        appended = "\n\n".join(
            f"---\n📎 附件「{name}」内容：\n```\n{text}\n```"
            for name, text in extracted_doc_texts
        )
        body.message = (body.message or "") + "\n\n" + appended

    user_msg = VibeCodingMessage(
        thread_id=thread.id,
        role="user",
        content=body.message,
        user_id=ctx.user.id,
        extra_meta={"attachments": attachment_meta} if attachment_meta else None,
    )
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)
    user_msg_dict = _message_to_dict(user_msg)
    thread_id = thread.id

    async def event_stream():
        # 用独立 session — 外层 db 在 routes 返回后会被 FastAPI 清理
        async with AsyncSessionLocal() as stream_db:
            try:
                stream_thread = await stream_db.get(VibeCodingThread, thread_id)
                if stream_thread is None:
                    yield {"event": "error", "data": json.dumps({"error": "thread 已被删除"})}
                    return

                yield {
                    "event": "user_message",
                    "data": json.dumps(user_msg_dict, ensure_ascii=False),
                }

                async for ev in run_agent(
                    stream_db,
                    stream_thread,
                    body.message,
                    abort_event,
                    multimodal_attachments=multimodal_for_agent,
                    attachment_meta=attachment_meta,
                ):
                    yield ev
            except Exception as exc:
                import traceback
                traceback.print_exc()
                yield {"event": "error", "data": json.dumps({"error": str(exc)}, ensure_ascii=False)}

    return EventSourceResponse(event_stream())


@router.get("/workspaces/{workspace_id}/sandbox/ports")
async def get_sandbox_ports(
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """查 docker 沙箱当前端口映射（{容器内端口: host 端口}）。
    没起容器或非 docker 模式返回空。前端用来拼 preview 链接。
    """
    _verify_workspace_access(workspace_id, ctx)
    rt = get_docker_runtime()
    if not await rt.is_available():
        return {"runtime": "host", "ports": {}, "running": False}
    status = await rt.container_status(workspace_id)
    if status != "running":
        return {"runtime": "docker", "ports": {}, "running": False, "status": status}
    mapped = await rt.all_host_ports(workspace_id)
    listening = await rt.listening_ports(workspace_id)
    # 只列「既映射到 host，又有进程在容器内监听」的端口 — 避免前端列出死链接
    ports = {cp: hp for cp, hp in mapped.items() if cp in listening}
    return {
        "runtime": "docker",
        "running": True,
        "status": status,
        "ports": ports,  # {6173: 55000, 6300: 55001, ...}（已过滤死端口）
    }


@router.get("/workspaces/{workspace_id}/chat/llm-configs")
async def list_available_llm_configs(
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出本租户全部可用 LLM 配置 — 不按 purpose 过滤，platform-envs 配置的都能选。"""
    _verify_workspace_access(workspace_id, ctx)
    res = await db.execute(
        select(LLMConfig)
        .where(
            LLMConfig.tenant_id == ctx.tenant_id,
            LLMConfig.status == "active",
        )
        .order_by(desc(LLMConfig.is_default), LLMConfig.id.asc())
    )
    configs = res.scalars().all()
    return {
        "configs": [
            {
                "id": c.id,
                "config_name": c.config_name,
                "provider": c.provider,
                "model": c.model,
                "purpose": c.purpose,
                "is_default": c.is_default,
            }
            for c in configs
        ]
    }
