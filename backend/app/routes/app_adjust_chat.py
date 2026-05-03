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
    parse_design_doc,
    generate_app_from_doc,
    list_my_applications,
    get_application,
    update_app_from_doc,
    get_change_plan,
    execute_change_plan,
    publish_application,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/app-adjust", tags=["app-adjust-chat"])


# ────────── 工具声明（OpenAI function-calling 格式）──────────

# 把 mcp_server.py 里 8 个工具的元信息手动整理成 OpenAI tools schema。
# tenant_id / user_id 不暴露给 LLM —— 后端注入。
TOOLS_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "parse_design_doc",
            "description": "解析一份标准 markdown 设计文档，返回结构化 preview（不创建应用）。md 必须是 6 章节标准格式：应用信息/角色/数据字典/数据模型/表单/权限。用于在 generate / update 前预览。",
            "parameters": {
                "type": "object",
                "properties": {
                    "md_content": {"type": "string", "description": "标准设计文档全文"},
                },
                "required": ["md_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_app_from_doc",
            "description": "根据标准 markdown 设计文档一步创建新应用（parse + auto-create）。返回 app_id / app_view_url。",
            "parameters": {
                "type": "object",
                "properties": {
                    "md_content": {"type": "string"},
                    "app_name": {"type": "string", "description": "可选，不填则从 md 「一、应用信息」推断"},
                },
                "required": ["md_content"],
            },
        },
    },
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
            "name": "update_app_from_doc",
            "description": "上传新版 markdown 设计文档作为应用 vN+1 版，自动 diff 出变更计划。返回 change_plan_id 和 summary，由用户审核后再调 execute_change_plan 执行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_id": {"type": "integer"},
                    "md_content": {"type": "string"},
                },
                "required": ["app_id", "md_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_change_plan",
            "description": "查看变更计划详情：包含所有 actions（新增/修改/删除的角色、字典、模型、表单、权限）。execute 前应该先 get 一次给用户审。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_id": {"type": "integer"},
                    "plan_id": {"type": "integer"},
                },
                "required": ["app_id", "plan_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_change_plan",
            "description": "执行变更计划：把 plan 里所有 actions 落到底层（创建/修改/删除模型、表单、权限等）。这是真正落地的工具，调用前用户必须审过 plan。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_id": {"type": "integer"},
                    "plan_id": {"type": "integer"},
                },
                "required": ["app_id", "plan_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_application",
            "description": "把应用发布到底层平台（aPaaS）。",
            "parameters": {
                "type": "object",
                "properties": {"app_id": {"type": "integer"}},
                "required": ["app_id"],
            },
        },
    },
]


# 工具 name → 实现函数（async）
TOOL_FN: dict[str, Any] = {
    "parse_design_doc": parse_design_doc.fn if hasattr(parse_design_doc, "fn") else parse_design_doc,
    "generate_app_from_doc": generate_app_from_doc.fn if hasattr(generate_app_from_doc, "fn") else generate_app_from_doc,
    "list_my_applications": list_my_applications.fn if hasattr(list_my_applications, "fn") else list_my_applications,
    "get_application": get_application.fn if hasattr(get_application, "fn") else get_application,
    "update_app_from_doc": update_app_from_doc.fn if hasattr(update_app_from_doc, "fn") else update_app_from_doc,
    "get_change_plan": get_change_plan.fn if hasattr(get_change_plan, "fn") else get_change_plan,
    "execute_change_plan": execute_change_plan.fn if hasattr(execute_change_plan, "fn") else execute_change_plan,
    "publish_application": publish_application.fn if hasattr(publish_application, "fn") else publish_application,
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

### 调整应用 — 三步走，每步等用户确认
1. **生成新版设计文档**：先口头说明改动点（哪些字段加/删/改），让用户确认；然后用 markdown 写完整新版（标准 6 章节：应用信息/角色/数据字典/数据模型/表单/权限）
2. **预览变更**：调 `update_app_from_doc(app_id={app_id}, md_content=...)`，会返 change_plan_id + summary。把 summary 给用户决定是否执行
3. **执行变更**：用户同意后调 `execute_change_plan(app_id={app_id}, plan_id=...)`

### 发布上线
用户说"发布 / 上线" → 调 `publish_application(app_id={app_id})`。

## 风格
- 基于工具实际返回的数据回答，不编造
- 不确定字段类型 / 命名时先调 `parse_design_doc` 看预览
- 删字段、改主键等重大改动前必须停下来确认
- 中文，简洁直接

## 不要做
- ❌ 一次把"修改+执行"全做完——预览给用户审，再执行
- ❌ 在没用工具的情况下虚构应用 id / 字段
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
