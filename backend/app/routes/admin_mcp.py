"""Admin: MCP 工具浏览 / 测试 API。

平台管理页默认使用当前 backend 进程内的 FastMCP 工具注册表，方便本地开发时
只启动 ai-builder backend/frontend 就能单独测试工具，不再依赖独立 8004 MCP 服务。
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import AuthContext, get_auth_context
from app.mcp_inprocess import call_inprocess_tool, list_inprocess_tools
from app.support_triage_records import write_support_triage_record

# pydantic-settings 不 export 到 os.environ；显式 load .env 兜底，跟 mcp_server.py 一致
try:
    from dotenv import load_dotenv as _load_dotenv
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"  # backend/.env
    if _env_path.exists():
        _load_dotenv(str(_env_path), override=False)
except Exception:
    pass

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/mcp", tags=["admin-mcp"])

# 默认代理到独立 MCP 服务（本地 8004，由 apaas-builder-mcp-server 仓库提供；线上为 k8s pod）。
# MCP 服务把工具拆成多个 FastMCP 实例 mount 到不同 path；admin 视图 union
# main + design 拿全集（builder/coding 子集会自动去重）。
_V2_BASE = os.getenv(
    "MCP_V2_INTERNAL_BASE",
    "http://127.0.0.1:8004",
)
_V2_TOOL_PATHS = [
    "/api/mcp/mcp",          # main FastMCP — 应用生命周期 / workspace / 自开发 / 内省
    "/api/mcp-design/mcp",   # 独立 design FastMCP — design system / principle 4 工具
]
# v2 TrustedHostMiddleware 只放行公网域名 host header，集群内调用必须显式带上
_V2_HOST = os.getenv("MCP_V2_HOST", "127.0.0.1:8004")


def _v2_api_key() -> str:
    """v2 MCP_API_KEYS 跟本机共享同一份 env，取第一个 key 用。"""
    raw = (os.getenv("MCP_API_KEYS") or "").strip()
    if not raw:
        return ""
    return raw.split(",")[0].strip()


def _v2_headers() -> dict:
    key = _v2_api_key()
    if not key:
        raise HTTPException(
            status_code=500,
            detail="MCP_API_KEYS env 未配置，admin /mcp 无法调 v2 MCP",
        )
    return {
        "Host": _V2_HOST,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }


def _classify_tool(name: str) -> tuple[str, str]:
    """按名字前缀 / 关键词粗分类。返回 (category_key, category_label)。"""
    # 自开发发布（aPaaS 平台侧 - 上传/关联/重发）
    if name in (
        "enable_apaas_self_dev_config", "list_apaas_app_dev_kits",
        "attach_dev_packages_to_apaas_app", "republish_apaas_app",
        "create_apaas_self_dev_menu", "list_apaas_resource_pool_kits",
        "upload_external_zip_to_apaas",
    ):
        return ("self_dev_publish", "aPaaS 自开发发布")

    # Workspace 自开发（AI Coding 二次开发）
    if name.startswith("read_workspace") or name.startswith("write_workspace") or \
       name.startswith("edit_workspace") or name.startswith("glob_workspace") or \
       name.startswith("grep_workspace") or name.startswith("run_workspace") or \
       name in ("create_dev_workspace", "get_dev_workspace_status",
                "save_dev_spec", "publish_dev_workspace",
                "init_apaas_backend_workspace", "lint_apaas_backend_workspace",
                "doctor_apaas_backend_workspace", "build_dev_workspace"):
        return ("workspace_dev", "Workspace 自开发 (AI Coding)")

    # 场景 / 规范
    if name.startswith("list_dev_scene") or name.startswith("get_dev_scene"):
        return ("dev_scene", "自开发场景规范")

    # Draft 工作流（v2 新流程）
    if name in (
        "save_design_draft", "patch_design_draft", "get_draft_summary",
        "apply_draft_to_live_app", "promote_draft_to_app", "save_app_design_doc",
    ):
        return ("draft_workflow", "Draft 工作流")

    # 跨 agent 接力
    if name in ("handoff_to_builder", "handoff_to_coding"):
        return ("agent_handoff", "跨 Agent 接力")

    # 救援工具
    if name in ("force_regenerate_apaas_app", "grant_app_access"):
        return ("rescue", "应用救援")

    # aPaaS 配置精细操作（CRUD）
    if name in (
        "set_apaas_app_access", "set_apaas_app_process",
        "set_apaas_form_permissions", "update_apaas_form_component",
        "disable_apaas_app_dict", "disable_apaas_dict_option",
    ):
        return ("apaas_config_edit", "aPaaS 配置精细操作")

    # 业务数据
    if name == "query_apaas_business_data":
        return ("apaas_business_data", "aPaaS 业务数据")

    # 外挂问题分诊助手
    if name == "record_support_triage":
        return ("support_triage", "问题分诊记录")

    # aPaaS 平台内省（元数据查询）
    if name.startswith("list_apaas_") or name.startswith("get_apaas_") or \
       name.startswith("check_app_") or name.startswith("validate_"):
        return ("apaas_introspect", "aPaaS 平台内省")

    # 文档解析 / 校验
    if name in ("parse_design_doc", "submit_design_doc"):
        return ("doc", "文档解析 / 校验")

    # 应用生命周期
    if name in (
        "generate_app_from_doc", "list_my_applications", "get_application",
        "update_app_from_doc", "get_change_plan", "execute_change_plan",
        "deploy_application", "publish_application", "list_apaas_apps",
        "lookup_user_by_username", "get_recent_app_context",
        "check_model_codes", "check_app_code_conflict",
    ):
        return ("app_lifecycle", "应用生命周期")

    # 平台环境
    if name == "list_platform_envs":
        return ("env", "平台环境")

    return ("other", "其他")


def _parse_mcp_response(body: str) -> dict:
    """v2 streamable HTTP 可能返 SSE frame（`data: <json>`）或纯 JSON。统一 parse。"""
    import json as _json
    raw = body
    if "data:" in raw:
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                raw = line[5:].strip()
                break
    return _json.loads(raw)


async def _fetch_tools_from(path: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as cli:
        resp = await cli.post(
            f"{_V2_BASE.rstrip('/')}{path}",
            headers=_v2_headers(),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"v2 MCP tools/list 失败 path={path} ({resp.status_code}): {resp.text[:300]}",
        )
    data = _parse_mcp_response(resp.text)
    return (data.get("result") or {}).get("tools") or []


@router.get("/tools")
async def list_mcp_tools(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """列出当前 backend 进程内 FastMCP 注册的工具。"""
    started = time.perf_counter()
    seen: set[str] = set()
    tools_raw: list[dict] = []
    try:
        for t in list_inprocess_tools():
            name = t.get("name") or ""
            if not name or name in seen:
                continue
            seen.add(name)
            tools_raw.append(t)
    except Exception as exc:
        logger.exception("admin /mcp/tools 读取同进程 MCP 工具失败")
        raise HTTPException(status_code=500, detail=f"同进程 MCP 工具不可用: {exc}")

    result = []
    for t in tools_raw:
        result.append(_format_tool_for_admin(t))

    by_category: dict[str, dict] = {}
    for t in result:
        key = t["category_key"]
        if key not in by_category:
            by_category[key] = {"key": key, "label": t["category_label"], "tools": []}
        by_category[key]["tools"].append(t)

    payload = {
        "ok": True,
        "total": len(result),
        "tools": result,
        "categories": list(by_category.values()),
        "server_info": {
            "name": "ai-builder backend in-process MCP",
            "transport": "FastMCP in-process",
            "endpoint": "/api/admin/mcp/tools + /api/admin/mcp/call",
            "auth_method": "平台管理登录态",
        },
    }
    _append_admin_mcp_log(
        service="ai-builder-inprocess",
        path="/api/admin/mcp/tools",
        rpc_method="tools/list",
        tool=None,
        request_arguments={"service": "ai-builder-inprocess"},
        ctx=ctx,
        success=True,
        status_code=200,
        started=started,
    )
    return payload


@router.get("/support-triage-tools")
async def list_support_triage_tools(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """列出问题分诊记录 MCP 的工具，用于平台管理测试台。"""
    started = time.perf_counter()
    from app.support_triage_mcp import mcp as support_mcp

    registered = getattr(getattr(support_mcp, "_tool_manager", None), "_tools", None) or {}
    result = [
        _format_tool_for_admin({
            "name": name,
            "description": getattr(tool, "description", "") or "",
            "inputSchema": getattr(tool, "parameters", None) or {
                "type": "object",
                "properties": {},
            },
        })
        for name, tool in sorted(registered.items())
    ]
    payload = {
        "ok": True,
        "total": len(result),
        "tools": result,
        "categories": [{"key": "support_triage", "label": "问题分诊记录", "tools": result}],
        "server_info": {
            "name": "问题分诊记录 MCP",
            "transport": "Streamable HTTP",
            "endpoint": "/api/support-triage-mcp/mcp",
            "auth_method": "MCP_API_KEYS",
        },
    }
    _append_admin_mcp_log(
        service="support-triage",
        path="/api/support-triage-mcp/mcp",
        rpc_method="tools/list",
        tool=None,
        request_arguments={"service": "support-triage"},
        ctx=ctx,
        success=True,
        status_code=200,
        started=started,
    )
    return payload


class InvokeMcpRequest(BaseModel):
    tool_name: str
    args: dict = Field(default_factory=dict)


def _is_tool_error(result: Any) -> bool:
    return isinstance(result, dict) and (
        result.get("ok") is False
        or result.get("error_code")
        or str(result.get("message") or "").startswith("错误")
    )


@router.post("/call")
async def call_mcp_tool(
    body: InvokeMcpRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """调用当前 backend 进程内 FastMCP 工具，用于平台管理测试台。"""
    started = time.perf_counter()
    args = dict(body.args or {})
    args["tenant_id"] = int(ctx.tenant_id or 0)
    args["user_id"] = int(ctx.user.id or 0)

    result: Any = await call_inprocess_tool(body.tool_name, args)
    is_error = _is_tool_error(result)
    _append_admin_mcp_log(
        service="ai-builder-inprocess",
        path="/api/admin/mcp/call",
        rpc_method="tools/call",
        tool=body.tool_name,
        request_arguments=args,
        ctx=ctx,
        success=not is_error,
        status_code=200 if not is_error else 500,
        error=(result.get("message") or result.get("error_code")) if isinstance(result, dict) and is_error else None,
        started=started,
    )
    return {
        "ok": not is_error,
        "tool_name": body.tool_name,
        "result": result,
    }


@router.post("/support-triage-call")
async def call_support_triage_tool(
    body: InvokeMcpRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """调用问题分诊 MCP 工具，用于平台管理测试台。"""
    started = time.perf_counter()
    if body.tool_name != "record_support_triage":
        raise HTTPException(status_code=400, detail="问题分诊 MCP 只支持 record_support_triage")

    args = dict(body.args or {})
    args["tenant_id"] = int(ctx.tenant_id or 0)
    args["user_id"] = int(ctx.user.id or 0)
    args.setdefault("source", "admin_tester")

    result = write_support_triage_record(
        user_question=str(args.get("user_question") or ""),
        category=str(args.get("category") or ""),
        summary=str(args.get("summary") or ""),
        reason=str(args.get("reason") or ""),
        user_reply=str(args.get("user_reply") or ""),
        confidence=str(args.get("confidence") or "中"),
        missing_info=str(args.get("missing_info") or ""),
        priority=str(args.get("priority") or "P2"),
        status=str(args.get("status") or "新建"),
        source=str(args.get("source") or "admin_tester"),
        tenant_id=int(args.get("tenant_id") or 0),
        user_id=int(args.get("user_id") or 0),
    )
    is_error = _is_tool_error(result)
    _append_admin_mcp_log(
        service="support-triage",
        path="/api/support-triage-mcp/mcp",
        rpc_method="tools/call",
        tool=body.tool_name,
        request_arguments=args,
        ctx=ctx,
        success=not is_error,
        status_code=200 if not is_error else 400,
        error=(result.get("message") or result.get("error_code")) if isinstance(result, dict) and is_error else None,
        started=started,
    )
    return {
        "ok": not is_error,
        "tool_name": body.tool_name,
        "result": result,
    }


def _format_tool_for_admin(t: dict) -> dict:
    name = t.get("name") or ""
    cat_key, cat_label = _classify_tool(name)
    full_desc = (t.get("description") or "").strip()
    first_line = full_desc.split("\n")[0].strip()
    rest = full_desc[len(first_line):].lstrip("\n")
    schema = t.get("inputSchema") or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    params = []
    for p_name, p_def in properties.items():
        params.append({
            "name": p_name,
            "type": p_def.get("type") or "any",
            "description": p_def.get("description") or p_def.get("title") or "",
            "required": p_name in required,
            "default": p_def.get("default"),
        })
    return {
        "name": name,
        "title": first_line,
        "description": rest,
        "category_key": cat_key,
        "category_label": cat_label,
        "inputSchema": schema,
        "input_schema": schema,
        "params": params,
        "params_count": len(params),
        "required_count": len(required),
    }


def _append_admin_mcp_log(
    *,
    service: str,
    path: str,
    rpc_method: str,
    tool: str | None,
    request_arguments: dict,
    ctx: AuthContext,
    success: bool,
    status_code: int,
    started: float,
    error: str | None = None,
) -> None:
    try:
        from app.routes.mcp_platform import append_mcp_call_log
        append_mcp_call_log({
            "service": service,
            "path": path,
            "rpc_method": rpc_method,
            "tool": tool,
            "request_arguments": request_arguments,
            "request_headers": {"authorization": "Bearer <平台管理登录态>"},
            "status_code": status_code,
            "success": success,
            "error": error,
            "auth_source": "platform_admin_session",
            "local_user_id": int(ctx.user.id or 0),
            "local_tenant_id": int(ctx.tenant_id or 0),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        })
    except Exception:
        pass
