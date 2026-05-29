"""把 harness/tool_registry 定义的 coding tools 包装成 BaseAgent 的 Tool 列表。

设计原则：
- 不重写 tool 逻辑，只做 schema + execute 的 adapter
- tool_registry 的 execute 接 workspace_path，ctx 里有 workspace_id 可解析
- progress_callback（如 run_command stdout）通过 publisher 发 SSE 事件

aPaaS 工具集（apaas_tools.py）一起注册进来：
- 11 个平台查询类（list_apaas_apps / _app_menus / _form_views 等）
  签名 (args, platform_env_id, db)，platform_env_id 从 ctx.conversation_id
  反查 Conversation.application_id → Application.platform_env_id
- 2 个 workspace 产物 / 附件类（read_attachment / write_artifact）
  签名 (args, workspace_path) 同 6 个 base coding tools
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.agents.types import AgentContext, Tool, ToolResult
from app.harness.tool_registry import ToolRegistry
from app.coding.apaas_tools import (
    APAAS_TOOL_DEFINITIONS,
    APAAS_TOOL_EXECUTORS_PLATFORM,
    APAAS_TOOL_EXECUTORS_WORKSPACE,
)

logger = logging.getLogger(__name__)


async def _resolve_platform_env_id(ctx: AgentContext) -> int | None:
    """3 级 fallback 拿 platform_env_id：
      1. ctx.extra['platform_env_id']（pipeline 显式注入，最高优先）
      2. ctx.conversation → application（如果该 conversation 已绑应用，且应用配了 env）
      3. 租户默认 platform_env（PlatformEnv where tenant_id=ctx.tenant_id and is_default=True）
    AI Coding 当前 conversation/workspace 没强绑 platform_env_id，所以 tenant 默认是兜底。
    """
    explicit = ctx.extra.get("platform_env_id") if isinstance(ctx.extra, dict) else None
    if explicit:
        return int(explicit)

    from app.database import AsyncSessionLocal
    from app.models import Conversation, Application, PlatformEnv
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        # path 2: conversation → application
        if ctx.conversation_id:
            try:
                conv = await db.get(Conversation, ctx.conversation_id)
                if conv and getattr(conv, "application_id", None):
                    app = await db.get(Application, conv.application_id)
                    if app and app.platform_env_id:
                        return int(app.platform_env_id)
            except Exception:
                logger.debug("conversation→app lookup failed, fallback to tenant default", exc_info=True)

        # path 3: tenant 默认 env
        if ctx.tenant_id:
            res = await db.execute(
                select(PlatformEnv).where(
                    PlatformEnv.tenant_id == ctx.tenant_id,
                    PlatformEnv.is_default == True,  # noqa: E712
                ).limit(1)
            )
            env = res.scalar_one_or_none()
            if env:
                return int(env.id)

    return None


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


def _wrap_result(text: str) -> ToolResult:
    """把字符串结果包成 ToolResult — 'Error:' 前缀视为失败（跟 coding/tools.py 约定一致）。"""
    is_error = isinstance(text, str) and text.startswith("Error:")
    return ToolResult(
        success=not is_error,
        content=text or "",
        error=text if is_error else None,
    )


def build_coding_tools(registry: ToolRegistry | None = None) -> list[Tool]:
    """从 tool_registry 构造 BaseAgent 的 Tool 列表 + 注入 aPaaS 工具集。

    工具来源（共 19 个 = 6 base + 13 apaas）：
      - 6 个 base coding tools（read_file / write_file / edit_file /
        run_command / glob_files / grep_search / start_serve）— 走 ToolRegistry
      - 11 个 aPaaS 平台查询工具 — 走 APAAS_TOOL_EXECUTORS_PLATFORM
        executor 内部反查 conversation→application→platform_env_id
      - 2 个 workspace 产物/附件工具 — 走 APAAS_TOOL_EXECUTORS_WORKSPACE
        executor 拿 workspace_path（跟 base tools 同源）
    """
    reg = registry or ToolRegistry(profile="coding")
    tools: list[Tool] = []

    # ── 6 个 base coding tools ────────────────────────────────
    for defn in reg.definitions:
        fn = defn.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        description = fn.get("description", "")
        parameters = fn.get("parameters") or {"type": "object", "properties": {}}

        def _make_base_executor(tool_name: str):
            async def executor(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
                try:
                    ws_path = _resolve_workspace_path(ctx)
                except Exception as e:
                    return ToolResult(success=False, content=f"Error resolving workspace: {e}", error=str(e))
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
                    return ToolResult(success=False, content=f"Tool '{tool_name}' execution error: {e}", error=str(e))
                return _wrap_result(result_text)
            return executor

        tools.append(Tool(
            name=name,
            description=description,
            parameters_schema=parameters,
            execute=_make_base_executor(name),
        ))

    # ── 13 个 aPaaS 工具 ──────────────────────────────────────
    for defn in APAAS_TOOL_DEFINITIONS:
        fn = defn.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        description = fn.get("description", "")
        parameters = fn.get("parameters") or {"type": "object", "properties": {}}

        # 平台查询类（需 platform_env_id）
        if name in APAAS_TOOL_EXECUTORS_PLATFORM:
            executor_fn = APAAS_TOOL_EXECUTORS_PLATFORM[name]

            def _make_platform_executor(tool_name: str, fn_ref):
                async def executor(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
                    env_id = await _resolve_platform_env_id(ctx)
                    if not env_id:
                        return ToolResult(
                            success=False,
                            content=(
                                "Error: 当前 conversation 未绑定 aPaaS 应用或应用未配置 platform_env_id。"
                                "请先在「应用」页面创建/选择应用并绑定平台环境。"
                            ),
                            error="NO_PLATFORM_ENV",
                        )
                    from app.database import AsyncSessionLocal
                    # 2026-05-29: apaas token 过期(httpx 401)自愈。这 11 个平台工具签名是
                    # (args, env_id, db) — 套不了 call_apaas_with_relogin(它要 fn(client))，
                    # 故同源复用 is_apaas_token_error + _relogin_apaas_env(签名 (env_id, db))。
                    # 一处覆盖全部 11 工具的 Agent 执行路径(MCP 路径已在 _call_apaas_platform_tool
                    # 用 _looks_like_apaas_401 自愈)。apaas_tools 失败约定返 "Error: ..." 字符串
                    # (不抛异常)，token 失效的 401 串会落在返回值里 → 命中则重登重试一次。
                    from app.error_messages import is_apaas_token_error
                    from app.coding.apaas_tools import _relogin_apaas_env

                    async def _run() -> str:
                        async with AsyncSessionLocal() as db:
                            return await fn_ref(args or {}, env_id, db)

                    async def _relogin() -> bool:
                        async with AsyncSessionLocal() as db:
                            return await _relogin_apaas_env(env_id, db)

                    try:
                        result_text = await _run()
                        if (
                            isinstance(result_text, str)
                            and result_text.lstrip().startswith("Error:")
                            and is_apaas_token_error(result_text)
                            and await _relogin()
                        ):
                            result_text = await _run()
                    except Exception as e:
                        if is_apaas_token_error(str(e)):
                            try:
                                if await _relogin():
                                    result_text = await _run()
                                else:
                                    raise
                            except Exception as e2:
                                logger.exception("apaas tool %s failed (after relogin)", tool_name)
                                return ToolResult(success=False, content=f"Tool '{tool_name}' execution error: {e2}", error=str(e2))
                        else:
                            logger.exception("apaas tool %s failed", tool_name)
                            return ToolResult(success=False, content=f"Tool '{tool_name}' execution error: {e}", error=str(e))
                    return _wrap_result(result_text)
                return executor

            tools.append(Tool(
                name=name,
                description=description,
                parameters_schema=parameters,
                execute=_make_platform_executor(name, executor_fn),
            ))

        # workspace 产物 / 附件类（用 workspace_path）
        elif name in APAAS_TOOL_EXECUTORS_WORKSPACE:
            executor_fn = APAAS_TOOL_EXECUTORS_WORKSPACE[name]

            def _make_workspace_executor(tool_name: str, fn_ref):
                async def executor(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
                    try:
                        ws_path = _resolve_workspace_path(ctx)
                    except Exception as e:
                        return ToolResult(success=False, content=f"Error resolving workspace: {e}", error=str(e))
                    try:
                        result_text = await fn_ref(args or {}, ws_path)
                    except Exception as e:
                        logger.exception("apaas workspace tool %s failed", tool_name)
                        return ToolResult(success=False, content=f"Tool '{tool_name}' execution error: {e}", error=str(e))
                    return _wrap_result(result_text)
                return executor

            tools.append(Tool(
                name=name,
                description=description,
                parameters_schema=parameters,
                execute=_make_workspace_executor(name, executor_fn),
            ))

    return tools
