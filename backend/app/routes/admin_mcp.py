"""Admin: MCP 工具浏览 API。

给前端 /admin/mcp 页面用 — 列出当前 MCP server 暴露的所有工具。
不涉及调用 / 写入 / Key 管理，纯只读，给开发/运营浏览看。

后续阶段会扩到：服务管理 (多 service) / API Key 管理 / 调用日志 / 在线调试。
"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import AuthContext, get_auth_context

router = APIRouter(prefix="/admin/mcp", tags=["admin-mcp"])


def _classify_tool(name: str) -> tuple[str, str]:
    """按名字前缀粗分类。返回 (category_key, category_label)。"""
    if name.startswith("list_apaas_") or name.startswith("get_apaas_") or name.startswith("check_app_") or name.startswith("validate_apaas_"):
        return ("apaas_introspect", "aPaaS 平台内省")
    if name in ("parse_design_doc", "submit_design_doc", "validate_builder_doc"):
        return ("doc", "文档解析 / 校验")
    if name in ("generate_app_from_doc", "list_my_applications", "get_application",
                "update_app_from_doc", "get_change_plan", "execute_change_plan",
                "publish_application"):
        return ("app_lifecycle", "应用生命周期")
    if name == "list_platform_envs":
        return ("env", "平台环境")
    return ("other", "其他")


@router.get("/tools")
async def list_mcp_tools(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    """列出 MCP server 暴露的所有工具（name / description / inputSchema / 分类）。

    任何登录用户都能看（信息是公开的工具清单，不涉及租户隔离数据）。
    """
    from app.mcp_server import mcp

    tools = await mcp.list_tools()
    result = []
    for t in tools:
        name = t.name
        cat_key, cat_label = _classify_tool(name)
        # 拆 description 为标题 + 详情段（取第一行作为标题）
        full_desc = (t.description or "").strip()
        first_line = full_desc.split("\n")[0].strip()
        rest = full_desc[len(first_line):].lstrip("\n")
        schema = t.inputSchema or {}
        # 提取参数列表（给前端表格用）
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

    # 分组聚合（按 category）
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
            "name": getattr(mcp, "name", "apaas-builder-ai"),
            "transport": "Streamable HTTP",
            "endpoint": "/api/mcp/mcp",
            "auth_method": "Bearer (MCP_API_KEYS)",
        },
    }
