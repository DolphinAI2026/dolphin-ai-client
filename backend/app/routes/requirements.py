"""需求分析助手 → ai-builder 中转。

唯一数据源：外部 agent 81 调 mcp_server.submit_design_doc 工具时把 md
写入 _REQUIREMENTS_DOC_CACHE。该工具同步返回一条 deeplink，agent 把链接贴在
chat 里让用户点击；用户在新 tab 进 ChatPage 时调本路由 GET /latest-doc 命中
当前登录用户的 cache，弹 ChooseAppTargetDialog 让用户选「新建 / 更新现有应用」。

> 历史：曾用 5s 轮询 + MCP 客户端 chat history API 抽 markdown code block 作为 fallback
> （当时 外部 agent 工具关联只识别 9 个工具调不到 submit_design_doc）。该
> workaround 已删除。如需排查可看 git blame `_try_extract_md_from_agent`。
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import AuthContext, get_auth_context
from app.mcp_server import _consume_requirements_doc, _peek_requirements_doc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/requirements", tags=["requirements-assistant"])


@router.get("/latest-doc")
async def get_latest_requirements_doc(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """ChatPage 进入 from=requirements 时调一次 — 拿当前用户最新 cache 的设计文档。

    返回 has_doc=False 时前端显示空态（提醒用户去 MCP 客户端 chat 让 agent 重发一次）。
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
        "source": rec.get("source") or "mcp",
    }


@router.post("/consume-doc/{pending_id}")
async def consume_requirements_doc(
    pending_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """点「→ Builder」之后调一次：从 cache 拿走 md，避免后续轮询又显示同一份。

    校验 pending_id：用户在外部 agent 反复修改时 cache 会更新到新 pending_id，
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
