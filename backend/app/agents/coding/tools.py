"""把 harness/tool_registry 定义的 coding tools 包装成 BaseAgent 的 Tool 列表。

设计原则：
- 不重写 tool 逻辑，只做 schema + execute 的 adapter
- tool_registry 的 execute 接 workspace_path，ctx 里有 workspace_id 可解析
- progress_callback（如 run_command stdout）通过 publisher 发 SSE 事件
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.agents.types import AgentContext, Tool, ToolResult
from app.harness.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


def _resolve_workspace_path(ctx: AgentContext) -> Path:
    """从 ctx 解析出 workspace 物理路径。"""
    ws_id = ctx.workspace_id
    if not ws_id:
        raise RuntimeError("CodingAgent 需要 ctx.workspace_id")
    from app.coding.workspace import WorkspaceManager
    return WorkspaceManager().get_workspace_path(ws_id)


def _make_progress_callback(ctx: AgentContext, tool_name: str):
    """为 run_command 等产生中间输出的 tool 构造 progress_callback。

    每次回调 → publish 一个 `coding.tool_progress` 事件。
    """
    async def _cb(text: str) -> None:
        if ctx.publisher is None or not text:
            return
        try:
            await ctx.publisher.publish(
                conversation_id=ctx.conversation_id,
                event_type="coding.tool_progress",
                agent="coding",
                session_id=ctx.session_id,
                data={"tool": tool_name, "text": text[:2000]},
            )
        except Exception as e:
            logger.warning("progress publish failed: %s", e)

    return _cb


def build_coding_tools(registry: ToolRegistry | None = None) -> list[Tool]:
    """从 tool_registry 构造 BaseAgent 的 Tool 列表。

    每个 Tool 的 execute 函数委托回 registry.execute，保持原有 tool 行为不变。
    """
    reg = registry or ToolRegistry(profile="coding")
    tools: list[Tool] = []

    for defn in reg.definitions:
        fn = defn.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        description = fn.get("description", "")
        parameters = fn.get("parameters") or {"type": "object", "properties": {}}

        # 工厂函数：闭包捕获 tool_name（避免 lambda 在循环里共享变量）
        def _make_executor(tool_name: str):
            async def executor(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
                try:
                    ws_path = _resolve_workspace_path(ctx)
                except Exception as e:
                    return ToolResult(
                        success=False,
                        content=f"Error resolving workspace: {e}",
                        error=str(e),
                    )

                progress_cb = _make_progress_callback(ctx, tool_name)

                try:
                    result_text = await reg.execute(
                        tool_name=tool_name,
                        arguments=args or {},
                        workspace_path=ws_path,
                        progress_callback=progress_cb,
                    )
                except Exception as e:
                    logger.exception("tool %s execution failed", tool_name)
                    return ToolResult(
                        success=False,
                        content=f"Tool '{tool_name}' execution error: {e}",
                        error=str(e),
                    )

                # tools.py 的 execute_tool 返回 str；字符串以 "Error:" 开头视为失败
                is_error = isinstance(result_text, str) and result_text.startswith("Error:")
                return ToolResult(
                    success=not is_error,
                    content=result_text or "",
                    error=result_text if is_error else None,
                )

            return executor

        tools.append(Tool(
            name=name,
            description=description,
            parameters_schema=parameters,
            execute=_make_executor(name),
        ))

    return tools
