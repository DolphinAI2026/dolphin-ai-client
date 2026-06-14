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
- 2 个自开发发布类（上传资产库 / 装回应用并重发）
  签名复用 AgentContext，内部走 app.coding.deploy_service 编排
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.agents.types import AgentContext, Tool, ToolResult
from app.harness.tool_registry import ToolRegistry
from app.coding.apaas_tools import (
    APAAS_TOOL_DEFINITIONS,
    APAAS_TOOL_EXECUTORS_PLATFORM,
    APAAS_TOOL_EXECUTORS_WORKSPACE,
)
from app.coding.deploy_service import _deploy_to_app_impl
from app.coding.workspace_access import _ensure_workspace_access, resolve_conversation_app_id

logger = logging.getLogger(__name__)


_EXPLICIT_REWRITE_TERMS = (
    "重写",
    "重做",
    "重新生成",
    "重新设计",
    "整页改版",
    "整体改版",
    "从零",
    "推倒重来",
    "全部重做",
    "全量重构",
)


def _explicit_rewrite_requested(ctx: AgentContext) -> bool:
    text = str((ctx.input or {}).get("requirement") or "")
    return any(term in text for term in _EXPLICIT_REWRITE_TERMS)


def _reject_existing_file_overwrite_in_iteration(
    tool_name: str,
    args: dict[str, Any],
    ctx: AgentContext,
    ws_path: Path,
) -> ToolResult | None:
    if tool_name != "write_file":
        return None
    if not bool((ctx.input or {}).get("is_iteration")):
        return None
    if _explicit_rewrite_requested(ctx):
        return None

    rel_path = str((args or {}).get("file_path") or "").strip()
    if not rel_path:
        return None
    try:
        target = (ws_path / rel_path).resolve()
        ws_resolved = ws_path.resolve()
        try:
            target.relative_to(ws_resolved)
        except ValueError:
            return None
        if not target.exists():
            return None
    except Exception:
        return None

    return ToolResult(
        success=False,
        content=(
            "Error: 当前是已有工作区的迭代修改，目标文件已存在。"
            "为避免把自开发包整份重写，请先 read_file 获取当前内容，"
            "再用 edit_file 只修改必要片段。不要 write_file 整份重写已有文件。"
            "只有新增文件或用户明确要求重写/重做/整页改版时，才允许 write_file。"
        ),
        error="ITERATION_OVERWRITE_BLOCKED",
    )


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
                conv_app_id = resolve_conversation_app_id(conv)
                if conv_app_id:
                    app = await db.get(Application, conv_app_id)
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


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _agent_auth_context(ctx: AgentContext):
    """把 AgentContext 降级成共享 workspace/deploy helper 需要的 AuthContext。

    AgentContext 当前没有完整 tenant_role/org_permissions；这里保留用户、租户两个
    强约束，并给 application:view 一个最小权限兜底，真实发布权限仍由 workspace
    admin 校验控制。
    """
    from app.deps import AuthContext

    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    org_permissions = extra.get("org_permissions")
    if not isinstance(org_permissions, dict):
        org_permissions = {"application:view": True}

    return AuthContext(
        user=SimpleNamespace(id=ctx.user_id, is_platform_admin=False),
        tenant_id=ctx.tenant_id,
        tenant_role=str(extra.get("tenant_role") or "member"),
        org_permissions=org_permissions,
        apaas_user_id=extra.get("apaas_user_id"),
        apaas_tenant_id=extra.get("apaas_tenant_id"),
    )


async def _resolve_local_app_id(args: dict[str, Any], ctx: AgentContext, db) -> int | None:
    """解析“装回应用”的本地 Application.id。

    优先级:
    1. tool 参数 local_app_id/app_id
    2. ctx.extra / ctx.input 中未来可能注入的 local app id
    3. 当前 Conversation.coding_app_id（刷新/续聊后的持久绑定）
    4. bound_apaas_app_id 反查本地 Application
    """
    for value in (
        args.get("local_app_id"),
        args.get("app_id"),
        (ctx.extra or {}).get("local_app_id") if isinstance(ctx.extra, dict) else None,
        (ctx.extra or {}).get("bound_local_app_id") if isinstance(ctx.extra, dict) else None,
        (ctx.extra or {}).get("coding_app_id") if isinstance(ctx.extra, dict) else None,
        (ctx.input or {}).get("local_app_id") if isinstance(ctx.input, dict) else None,
        ((ctx.input or {}).get("app_context") or {}).get("local_app_id")
        if isinstance((ctx.input or {}).get("app_context"), dict) else None,
    ):
        local_app_id = _coerce_int(value)
        if local_app_id is not None:
            return local_app_id

    from sqlalchemy import select
    from app.models import Application, Conversation

    if ctx.conversation_id:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == ctx.conversation_id,
                Conversation.tenant_id == ctx.tenant_id,
            )
        )
        conv = result.scalar_one_or_none()
        local_app_id = resolve_conversation_app_id(conv)
        if local_app_id is not None:
            return local_app_id

    bound_apaas_app_id = None
    if isinstance(ctx.extra, dict):
        bound_apaas_app_id = ctx.extra.get("bound_apaas_app_id")
    if not bound_apaas_app_id and isinstance(ctx.input, dict):
        app_context = ctx.input.get("app_context")
        if isinstance(app_context, dict):
            bound_apaas_app_id = app_context.get("apaas_app_id")
    if bound_apaas_app_id:
        result = await db.execute(
            select(Application).where(
                Application.tenant_id == ctx.tenant_id,
                Application.apaas_app_id == str(bound_apaas_app_id),
            )
        )
        app = result.scalar_one_or_none()
        return _coerce_int(getattr(app, "id", None))

    return None


async def _with_db(ctx: AgentContext, fn):
    if ctx.db is not None:
        return await fn(ctx.db)

    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return await fn(db)


def _format_dev_deploy_result(result: dict[str, Any]) -> str:
    status = result.get("status")
    kits = result.get("kits") or []
    kit_text = "、".join(str(k) for k in kits) if kits else "无"
    if status == "installed":
        app = result.get("app") or {}
        app_name = app.get("name") or "目标应用"
        version = result.get("version")
        menu = result.get("menu")
        parts = [f"已装回应用「{app_name}」并重新发布"]
        if version:
            parts.append(f"版本: {version}")
        if menu:
            parts.append(f"菜单: {menu}")
        parts.append(f"自开发包: {kit_text}")
        return "；".join(parts)
    if status == "uploaded_only":
        hint = result.get("hint") or "已上传到自开发资产库"
        return f"{hint}；自开发包: {kit_text}"
    return json.dumps(result, ensure_ascii=False)


async def _run_dev_workspace_deploy(args: dict[str, Any], ctx: AgentContext, *, to_app: bool) -> ToolResult:
    ws_id = ctx.workspace_id
    if not ws_id:
        return ToolResult(
            success=False,
            content="Error: 当前 Coding 会话没有 workspace_id，无法上传或装回应用。",
            error="NO_WORKSPACE_ID",
        )

    async def _run(db):
        from fastapi import HTTPException

        auth_ctx = _agent_auth_context(ctx)
        try:
            await _ensure_workspace_access(
                ws_id,
                auth_ctx,
                db,
                minimum_project_role="admin",
            )
            local_app_id = await _resolve_local_app_id(args or {}, ctx, db) if to_app else None
            if to_app and local_app_id is None:
                return ToolResult(
                    success=False,
                    content=(
                        "Error: 当前会话没有绑定目标应用。请提供 local_app_id，"
                        "或先从应用资产库进入「在应用上定制」。"
                    ),
                    error="NO_TARGET_APP",
                )
            result = await _deploy_to_app_impl(ws_id, local_app_id, auth_ctx, db)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False)
            return ToolResult(success=False, content=f"Error: {detail}", error=detail)
        except Exception as exc:
            logger.exception("dev workspace deploy tool failed")
            return ToolResult(success=False, content=f"Error: {exc}", error=str(exc))

        return ToolResult(
            success=True,
            content=_format_dev_deploy_result(result),
            data=result if isinstance(result, dict) else {"result": result},
        )

    return await _with_db(ctx, _run)


def _apply_bound_app_scope(args: dict[str, Any], ctx: AgentContext, accepts_app_id: bool) -> dict[str, Any]:
    """「在应用上定制」bound 模式 → 把 apaas_app_id 锁死成绑定应用。

    codegen 在已有应用上做扩展时(ctx.extra['bound_apaas_app_id'] 有值),所有吃 apaas_app_id
    的平台读工具都强制查这个应用,**无视 LLM 传的值** —— 既防 agent 跨应用读(隔离),也防它
    没绑定/传错 app_id 读不到东西(对齐 grounding 的 args['apaas_app_id']=... 锁定)。
    非 bound 或工具不吃 apaas_app_id → 原样不动。
    """
    locked = (ctx.extra or {}).get("bound_apaas_app_id") if isinstance(ctx.extra, dict) else None
    if locked and accepts_app_id:
        return {**(args or {}), "apaas_app_id": str(locked)}
    return args or {}


def build_coding_tools(registry: ToolRegistry | None = None) -> list[Tool]:
    """从 tool_registry 构造 BaseAgent 的 Tool 列表 + 注入 aPaaS 工具集。

    工具来源（共 22 个 = 7 base + 13 apaas + 2 deploy）：
      - 7 个 base coding tools（read_file / write_file / edit_file /
        run_command / glob_files / grep_search / start_serve）— 走 ToolRegistry
      - 11 个 aPaaS 平台查询工具 — 走 APAAS_TOOL_EXECUTORS_PLATFORM
        executor 内部反查 conversation→application→platform_env_id
      - 2 个 workspace 产物/附件工具 — 走 APAAS_TOOL_EXECUTORS_WORKSPACE
        executor 拿 workspace_path（跟 base tools 同源）
      - 2 个自开发发布工具 — 复用 app.coding.deploy_service._deploy_to_app_impl
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
                    blocked = _reject_existing_file_overwrite_in_iteration(tool_name, args or {}, ctx, ws_path)
                    if blocked is not None:
                        return blocked
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

    # ── 13 个 aPaaS / workspace 产物工具 ───────────────────────
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
            # 该工具 schema 是否吃 apaas_app_id —— bound 模式据此决定是否锁定应用范围
            accepts_app_id = "apaas_app_id" in ((parameters or {}).get("properties") or {})

            def _make_platform_executor(tool_name: str, fn_ref, tool_accepts_app_id: bool):
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
                    # bound「在应用上定制」→ 强制 apaas_app_id = 绑定应用(防跨应用读/传错)
                    args = _apply_bound_app_scope(args, ctx, tool_accepts_app_id)
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
                execute=_make_platform_executor(name, executor_fn, accepts_app_id),
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

    tools.extend([
        Tool(
            name="deploy_dev_workspace_to_app",
            description=(
                "Build the current Coding workspace, upload/update its self-development package, "
                "attach it to the bound aPaaS application, create a self-dev menu for page projects, "
                "and republish the application. Use this only when the user explicitly asks to "
                "重新上传/装回应用/重新发布应用. If local_app_id is omitted, the tool falls back to "
                "the current conversation's bound application."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "local_app_id": {
                        "type": "integer",
                        "description": "Optional local ai-builder Application.id. Omit when the current coding conversation is already bound to an application.",
                    }
                },
                "required": [],
            },
            execute=lambda args, ctx: _run_dev_workspace_deploy(args, ctx, to_app=True),
            idempotent=False,
        ),
        Tool(
            name="upload_dev_workspace_to_asset_library",
            description=(
                "Build the current Coding workspace and upload/update its package in the aPaaS "
                "self-development asset library, without attaching it to any application and without "
                "republishing an application. Use this when the user only asks to 上传到自开发资产库/组件库."
            ),
            parameters_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
            execute=lambda args, ctx: _run_dev_workspace_deploy(args, ctx, to_app=False),
            idempotent=False,
        ),
    ])

    return tools
