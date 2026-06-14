"""aPaaS application metadata and basic lifecycle MCP tools."""

from __future__ import annotations

from typing import Callable


_registered_tools_by_mcp: dict[int, dict[str, object]] = {}


def register(
    mcp,
    call_platform_tool: Callable,
    with_client: Callable,
) -> dict[str, object]:
    """Register aPaaS application metadata tools on the shared FastMCP instance."""
    marker = id(mcp)
    if marker in _registered_tools_by_mcp:
        return _registered_tools_by_mcp[marker]

    @mcp.tool()
    async def list_apaas_apps_in_env(env_id: int) -> dict:
        """列指定 aPaaS 环境下所有应用（含 apaas_app_id / app_code / app_name / status）。"""
        return await call_platform_tool("list_apaas_apps", {}, env_id)

    @mcp.tool()
    async def list_apaas_app_menus(env_id: int, apaas_app_id: str) -> dict:
        """列指定应用的菜单树（含每个菜单关联的 form_id / form_code）。"""
        return await call_platform_tool(
            "list_apaas_app_menus", {"apaas_app_id": apaas_app_id}, env_id,
        )

    @mcp.tool()
    async def list_apaas_form_views(env_id: int, apaas_app_id: str, form_id: str) -> dict:
        """列指定表单的所有视图（拿 tab_id）。"""
        return await call_platform_tool(
            "list_apaas_form_views",
            {"apaas_app_id": apaas_app_id, "form_id": form_id},
            env_id,
        )

    @mcp.tool()
    async def list_apaas_form_components(env_id: int, apaas_app_id: str, form_id: str) -> dict:
        """列指定表单的所有组件（uuid → label 映射 + 下拉选项 + 字典选项）。"""
        return await call_platform_tool(
            "list_apaas_form_components",
            {"apaas_app_id": apaas_app_id, "form_id": form_id},
            env_id,
        )

    @mcp.tool()
    async def list_apaas_app_models(
        env_id: int,
        apaas_app_id: str,
        with_fields: bool = True,
    ) -> dict:
        """列指定应用下所有数据模型 + 字段定义。"""
        return await call_platform_tool(
            "list_apaas_app_models",
            {"apaas_app_id": apaas_app_id, "with_fields": with_fields},
            env_id,
        )

    @mcp.tool()
    async def list_apaas_app_dicts(
        env_id: int,
        apaas_app_id: str,
        with_options: bool = True,
    ) -> dict:
        """列指定应用下所有数据字典（下拉/单选选项的来源）。"""
        return await call_platform_tool(
            "list_apaas_app_dicts",
            {"apaas_app_id": apaas_app_id, "with_options": with_options},
            env_id,
        )

    @mcp.tool()
    async def get_apaas_app_overview(env_id: int, apaas_app_id: str) -> dict:
        """精简版应用全貌：模型清单 + 字典清单（不带字段/选项详情）。"""
        return await call_platform_tool(
            "get_apaas_app_overview", {"apaas_app_id": apaas_app_id}, env_id,
        )

    @mcp.tool()
    async def update_apaas_app_info(
        env_id: int,
        apaas_app_id: str,
        app_name: str = "",
        description: str = "",
        icon_svg: str = "",
    ) -> dict:
        """改应用基本信息（名称 / 描述 / 图标）。"""
        if not apaas_app_id.strip():
            return {"ok": False, "error_code": "INVALID_APAAS_APP_ID", "message": "apaas_app_id 不能为空"}

        fields = {
            "app_name": app_name.strip(),
            "description": description.strip(),
            "icon_svg": icon_svg.strip(),
        }
        updated = [k for k, v in fields.items() if v]
        if not updated:
            return {
                "ok": False,
                "error_code": "INVALID_PARAMS",
                "message": "app_name / description / icon_svg 至少传一个非空字段",
            }

        ok, raw = await with_client(
            env_id,
            "改应用信息",
            lambda c: c.update_app(
                apaas_app_id.strip(),
                app_name=fields["app_name"],
                description=fields["description"],
                icon_svg=fields["icon_svg"],
            ),
        )
        if not ok:
            if isinstance(raw, dict) and raw.get("error_code") == "NOT_IMPLEMENTED":
                return {
                    "ok": False,
                    "error_code": "NOT_IMPLEMENTED",
                    "message": "平台无对应更新接口，请到平台 UI 修改",
                    "attempted_fields": updated,
                }
            return raw

        return {
            "ok": True,
            "updated_fields": updated,
            "app_name": fields["app_name"] or None,
            "message": f"应用已更新 ({', '.join(updated)})",
        }

    @mcp.tool()
    async def list_apaas_models_in_env(env_id: int) -> dict:
        """列指定环境内所有模型（跨应用，含 modelCode + appCode）。"""
        return await call_platform_tool("list_apaas_models_in_env", {}, env_id)

    @mcp.tool()
    async def check_app_code_conflict(env_id: int, app_code: str) -> dict:
        """查 app_code 是否被占用（部署前预检）。"""
        return await call_platform_tool(
            "check_app_code_conflict", {"app_code": app_code}, env_id,
        )

    @mcp.tool()
    async def get_apaas_doc_template_spec() -> dict:
        """拿 aPaaS Builder 设计文档官方标准。"""
        return await call_platform_tool("get_doc_template_spec", {}, 0)

    @mcp.tool()
    async def validate_apaas_builder_doc(md_content: str) -> dict:
        """轻量校验 markdown 是否符合 aPaaS Builder 标准。"""
        return await call_platform_tool(
            "validate_builder_doc", {"md_content": md_content}, 0,
        )

    tools = {
        "list_apaas_apps_in_env": list_apaas_apps_in_env,
        "list_apaas_app_menus": list_apaas_app_menus,
        "list_apaas_form_views": list_apaas_form_views,
        "list_apaas_form_components": list_apaas_form_components,
        "list_apaas_app_models": list_apaas_app_models,
        "list_apaas_app_dicts": list_apaas_app_dicts,
        "get_apaas_app_overview": get_apaas_app_overview,
        "update_apaas_app_info": update_apaas_app_info,
        "list_apaas_models_in_env": list_apaas_models_in_env,
        "check_app_code_conflict": check_app_code_conflict,
        "get_apaas_doc_template_spec": get_apaas_doc_template_spec,
        "validate_apaas_builder_doc": validate_apaas_builder_doc,
    }
    _registered_tools_by_mcp[marker] = tools
    return tools
