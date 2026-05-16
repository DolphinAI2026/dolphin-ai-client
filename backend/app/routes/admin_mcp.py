"""Admin: MCP 工具浏览 API。

给前端 /admin/mcp 页面用 — 列出**线上 dolphin 实际在调**的 MCP server (v2) 暴露的所有工具。

2026-05-16 起改为 proxy 模式：不再 list ai-builder-ai 自己 backend 进程内嵌的
mcp_server.py 的工具（80 个），而是 HTTP 调集群内 v2 svc 拿真实 77 工具。

原因：双 mcp server 并存（[[mcp-dual-servers-analysis-2026-05-16]]），admin 看本机
mcp 跟 dolphin 实际用的 v2 不一致 → 看到 vibe_* 老 host docker 工具 / apaas 精细
CRUD 16 个会以为 dolphin 能调，实际不能。改 proxy 后 admin 视图跟 dolphin 一致。
"""
from __future__ import annotations

import logging
import os
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.deps import AuthContext, get_auth_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/mcp", tags=["admin-mcp"])

# v2 svc 集群内 DNS：apaas-builder-mcp-server.apaas-builder.svc:8004
# 短名 apaas-builder-mcp-server:8004 在同 namespace 内可达。
# v2 把工具拆 4 个 FastMCP 实例 mount 到不同 path（main + design 是
# 真正独立工具集；builder/coding 是 main 的子集 split 给不同 agent；vibe 暂空）。
# admin 视图 union main + design 拿全集（builder/coding 子集会自动去重）。
_V2_BASE = os.getenv(
    "MCP_V2_INTERNAL_BASE",
    "http://apaas-builder-mcp-server:8004",
)
_V2_TOOL_PATHS = [
    "/api/mcp/mcp",          # main FastMCP — 应用生命周期 / workspace / 自开发 / 内省
    "/api/mcp-design/mcp",   # 独立 design FastMCP — design system / principle 4 工具
]
# v2 TrustedHostMiddleware 只放行公网域名 host header，集群内调用必须显式带上
_V2_HOST = os.getenv("MCP_V2_HOST", "agent.dfy.definesys.cn")


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
    # Vibe Coding K8s sandbox（v2 新版）
    if name.startswith("vibe_"):
        return ("vibe_coding", "Vibe Coding K8s 沙箱")

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
                "save_dev_spec", "import_zip_to_workspace", "publish_dev_workspace",
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
    """列出线上 dolphin 实际在调的 v2 MCP server 暴露的所有工具。

    走集群内 HTTP proxy 调 v2 `tools/list`，合并 main + design 两个 endpoint
    （builder/coding 子集是 main 的子集，会自动去重）。
    """
    seen: set[str] = set()
    tools_raw: list[dict] = []
    try:
        for path in _V2_TOOL_PATHS:
            for t in await _fetch_tools_from(path):
                name = t.get("name") or ""
                if not name or name in seen:
                    continue
                seen.add(name)
                tools_raw.append(t)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("admin /mcp/tools proxy 调 v2 异常")
        raise HTTPException(status_code=502, detail=f"v2 MCP 不可达: {exc}")

    result = []
    for t in tools_raw:
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
        result.append({
            "name": name,
            "title": first_line,
            "description": rest,
            "category_key": cat_key,
            "category_label": cat_label,
            "input_schema": schema,
            "params": params,
            "params_count": len(params),
            "required_count": len(required),
        })

    by_category: dict[str, dict] = {}
    for t in result:
        key = t["category_key"]
        if key not in by_category:
            by_category[key] = {"key": key, "label": t["category_label"], "tools": []}
        by_category[key]["tools"].append(t)

    return {
        "ok": True,
        "total": len(result),
        "tools": result,
        "categories": list(by_category.values()),
        "server_info": {
            "name": "apaas-builder-mcp-server (v2, main + design)",
            "transport": "Streamable HTTP (proxied)",
            "endpoint": "/mcp-server-v2/api/mcp/mcp (上游, dolphin 同款)",
            "auth_method": "Bearer (MCP_API_KEYS)",
        },
    }
