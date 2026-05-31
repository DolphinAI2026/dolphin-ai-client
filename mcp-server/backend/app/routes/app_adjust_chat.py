"""AI-Builder 应用调整助手 — 内嵌 chat 后端（替代 dolphin agent）。

为什么自建：
- dolphin trial 的 agent runtime 不会真正把 MCP tools 注入给 LLM
  （ECS 后端日志证据：dolphin 探测 GET /mcp/mcp 200，但从未 POST tool call）
- 这里我们自己控制 LLM + tool loop，保证 list_my_applications 等工具被真实调用

实现：
- POST /api/app-adjust/chat/stream（SSE）
- 入参：{app_id, history: [...], message: str}
- 复用 LLMClient（已支持 anthropic + openai 双协议 + tools 参数）
- 复用 mcp_server.py 里的 8 个 @mcp.tool() 函数（直接 import 调用，不走网络层）
- tool 循环：LLM tool_use → 本地执行 → tool_result 回喂 → 直到无 tool_use
- 整个过程用 SSE 流式吐给前端：
    event: text / tool_call_start / tool_call_done / done / error
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.harness.llm_resolver import resolve_llm_config
from app.llm_client import LLMClient
from app.mcp_server import (
    list_my_applications,
    get_application,
    patch_design_draft,
    apply_draft_to_live_app,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/app-adjust", tags=["app-adjust-chat"])


# ────────── 工具声明（OpenAI function-calling 格式）──────────

# 把应用调整助手收口到 draft 主流程，不再暴露旧 generate/deploy/publish 兼容链路。
# tenant_id / user_id 不暴露给 LLM —— 后端注入。
TOOLS_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_my_applications",
            "description": "列出当前租户下我能访问的所有 aPaaS 应用（最多 50 条）。返回 [{id, app_name, app_code, status, updated_at}]。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_application",
            "description": "查看指定应用详情：基础信息、状态、当前文档版本、配置摘要。",
            "parameters": {
                "type": "object",
                "properties": {"app_id": {"type": "integer"}},
                "required": ["app_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_design_draft",
            "description": "基于当前 draft 做一次结构化修改，生成新版 draft 和预览链接。只生成草稿，不直接改线上应用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string", "description": "从 get_application 返回的 current_draft_id"},
                    "action": {
                        "type": "object",
                        "description": "结构化变更，例如 add_field/update_field/delete_field/add_dict_option/set_permission",
                    },
                },
                "required": ["draft_id", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_draft_to_live_app",
            "description": "用户确认新版 draft 后，把 draft 同步到既有应用。调用前必须已经给用户看过 patch_design_draft 返回的 summary/preview_url。",
            "parameters": {
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string"},
                },
                "required": ["draft_id"],
            },
        },
    },
]


# 工具 name → 实现函数（async）
TOOL_FN: dict[str, Any] = {
    "list_my_applications": list_my_applications.fn if hasattr(list_my_applications, "fn") else list_my_applications,
    "get_application": get_application.fn if hasattr(get_application, "fn") else get_application,
    "patch_design_draft": patch_design_draft.fn if hasattr(patch_design_draft, "fn") else patch_design_draft,
    "apply_draft_to_live_app": apply_draft_to_live_app.fn if hasattr(apply_draft_to_live_app, "fn") else apply_draft_to_live_app,
}


SYSTEM_PROMPT_TEMPLATE = """你是 aPaaS Builder 的【应用调整助手】。用户当前在编辑应用 #{app_id}（{app_name}）。

## 核心职责
帮用户通过对话调整 aPaaS 应用：查看应用、修改设计文档、应用变更到底层模型。

## 工作流（必须严格遵循）
**积极使用工具，不要凭空回答数据相关问题。**

### 查询场景
- 用户问"列表 / 我的应用" → 必须调 `list_my_applications`
- 用户问"应用详情" → 必须调 `get_application(app_id={app_id})`，**默认参数就是当前 app_id**
- 不要用知识或猜测回答应用相关问题

### 调整应用 — draft 两步走
1. **先查当前 draft**：调 `get_application(app_id={app_id})`，拿 `current_draft_id`。如果没有 current_draft_id，说明这个应用不是 draft 主流程产物，直接告诉用户需要回到 AI Builder 重新生成草稿。
2. **生成新版设计文档**：把用户需求整理成结构化 action，调 `patch_design_draft(draft_id=current_draft_id, action=...)`。返回 `summary_of_change` 和 `preview_url` 后，给用户看摘要和预览，等用户明确确认。
3. **同步到线上**：用户确认后，调 `apply_draft_to_live_app(draft_id=<patch 返回的新 draft_id>)`。

### 发布上线
应用创建和发布已内置在 `promote_draft_to_app` / `apply_draft_to_live_app` 主流程里。当前助手不再调用旧的 `deploy_application` / `publish_application`。

## 风格
- 基于工具实际返回的数据回答，不编造
- 不确定字段类型 / 命名时先问清楚，不要猜
- 删字段、改主键等重大改动前必须停下来确认
- 中文，简洁直接

## 不要做
- ❌ 一次把"修改+执行"全做完——新版 draft 预览给用户审，再 apply
- ❌ 在没用工具的情况下虚构应用 id / 字段
- ❌ 调用 generate_app_from_doc / update_app_from_doc / deploy_application / publish_application 旧链路
"""


# ────────── 请求 ──────────


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    app_id: int
    app_name: str = ""
    message: str
    history: list[ChatMessage] = []


# ────────── SSE 事件 ──────────


def _sse(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


# ────────── tool 循环 ──────────


async def _run_chat_loop(
    *,
    llm: LLMClient,
    model: str,
    messages: list[dict],
    tenant_id: int,
    user_id: int,
    max_iters: int = 8,
) -> AsyncIterator[str]:
    """
    多轮 tool 循环：
    - LLM 返回 tool_calls → 后端执行 → 把 tool 结果回喂作为 user message → 继续
    - LLM 返回纯 text → 当成最终回复 yield 给前端
    """
    for iteration in range(max_iters):
        try:
            res = await llm.chat_completion(
                messages,
                model=model,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                max_tokens=4096,
                temperature=0.3,
            )
        except Exception as exc:
            yield _sse("error", {"message": f"LLM 调用失败：{exc!r}"[:500]})
            return

        choice = (res.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        tool_calls = msg.get("tool_calls") or []
        text = msg.get("content") or ""

        # 文本（边喂边吐）
        if text:
            yield _sse("text", {"content": text})

        if not tool_calls:
            yield _sse("done", {"iteration": iteration})
            return

        # 把 assistant tool_call message 加进 history（OpenAI 格式）
        messages.append({
            "role": "assistant",
            "content": text or None,
            "tool_calls": tool_calls,
        })

        # 执行所有 tool_call
        for tc in tool_calls:
            fn = (tc.get("function") or {})
            name = fn.get("name")
            args_raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except Exception:
                args = {}
            yield _sse("tool_call_start", {"name": name, "arguments": args, "id": tc.get("id")})

            tool_fn = TOOL_FN.get(name)
            if tool_fn is None:
                tool_result: Any = {"ok": False, "error": f"unknown tool: {name}"}
            else:
                # 注入身份
                args_with_id = dict(args)
                args_with_id["tenant_id"] = tenant_id
                args_with_id["user_id"] = user_id
                try:
                    tool_result = await tool_fn(**args_with_id)
                except Exception as exc:
                    tool_result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}

            yield _sse("tool_call_done", {
                "name": name,
                "id": tc.get("id"),
                "result_preview": str(tool_result)[:300],
            })

            # 加 tool message（OpenAI 格式）
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id"),
                "content": json.dumps(tool_result, ensure_ascii=False, default=str)[:30000],
            })

    yield _sse("error", {"message": f"超过 max_iters ({max_iters}) 仍未收敛"})


# ────────── endpoint ──────────


@router.post("/chat/stream")
async def app_adjust_chat_stream(
    req: ChatRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    # 解析 LLM 配置（租户级 → 环境变量兜底）
    cfg = await resolve_llm_config(db, ctx.tenant_id, purpose="all")
    if cfg:
        llm = LLMClient(api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model)
        model = cfg.model
    else:
        # 回退到 anthropic（minimax 兼容）
        llm = LLMClient()
        model = settings.anthropic_model or settings.llm_model

    # 构造 messages
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(app_id=req.app_id, app_name=req.app_name or "未命名")
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for h in req.history:
        if h.role in ("user", "assistant") and h.content:
            messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": req.message})

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for chunk in _run_chat_loop(
                llm=llm,
                model=model,
                messages=messages,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user.id,
            ):
                yield chunk
        except Exception as exc:
            logger.exception("app-adjust chat loop crashed")
            yield _sse("error", {"message": f"server error: {exc!r}"[:500]})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
