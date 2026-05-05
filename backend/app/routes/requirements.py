"""需求分析助手 → ai-builder 中转。

dolphin agent 81 写完标准 md 后用 MCP 工具 submit_design_doc 把内容塞进
mcp_server._REQUIREMENTS_DOC_CACHE；前端 RequirementsAssistantPage 右侧面板
轮询本路由 GET /requirements/latest-doc 拉到展示，并提供「→ Builder」按钮
跳转到 /chat 走 pendingMarkdown 链路完成应用搭建。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import AuthContext, get_auth_context
from app.mcp_server import _consume_requirements_doc, _peek_requirements_doc

router = APIRouter(prefix="/requirements", tags=["requirements-assistant"])


@router.get("/latest-doc")
async def get_latest_requirements_doc(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """前端轮询 — 拿当前用户从 dolphin 需求分析助手送过来的最新设计文档。

    返回 None 表示尚未提交（前端右侧面板显示空态）。
    """
    rec = _peek_requirements_doc(ctx.user.id)
    if not rec:
        return {"has_doc": False}
    return {
        "has_doc": True,
        "pending_id": rec["pending_id"],
        "file_name": rec["file_name"],
        "md_content": rec["md_content"],
        "score": rec.get("score", 0),
        "submitted_at": rec.get("submitted_at"),
        "source": rec.get("source"),
    }


@router.post("/consume-doc/{pending_id}")
async def consume_requirements_doc(
    pending_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """点「→ Builder」之后调一次：从 cache 拿走 md 内容（避免后续轮询又显示同一份）。

    校验 pending_id：用户在 dolphin 反复修改时 cache 会更新到新 pending_id，
    旧的请求传过来要被拒绝（防止用户跳过去后又跳错版本）。
    """
    rec = _consume_requirements_doc(ctx.user.id, pending_id)
    if not rec:
        raise HTTPException(404, "no pending design doc for this user, or pending_id mismatch")
    return {
        "ok": True,
        "file_name": rec["file_name"],
        "md_content": rec["md_content"],
        "score": rec.get("score", 0),
    }
