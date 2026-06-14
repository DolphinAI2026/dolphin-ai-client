"""Compatibility aggregator for direct aPaaS MCP tool modules."""
from __future__ import annotations

from app.mcp_tools.apaas_feature_builder import (
    _post_configure_feature_form_quality,
    register as _register_feature_builder_tools,
)
from app.mcp_tools.apaas_form_tools import (
    _build_perm_payload_from_simple_rules,
    _form_perms_to_rules,
    _invalidate_section_cache_after_write,
    register as _register_form_tools,
)
from app.mcp_tools.apaas_runtime_tools import register as _register_runtime_tools


def register(
    mcp,
    with_client,
    list_app_menus,
    list_app_models,
    list_form_views,
    list_form_components,
    list_app_processes,
    list_app_roles=None,
    get_form_detail=None,
    list_form_permissions=None,
    set_form_permissions=None,
    set_app_process=None,
):
    form_tools = _register_form_tools(
        mcp,
        with_client,
        list_app_menus,
        list_app_models,
        list_app_roles=list_app_roles,
        get_form_detail=get_form_detail,
        list_form_permissions=list_form_permissions,
        set_form_permissions=set_form_permissions,
    )
    runtime_tools = _register_runtime_tools(
        mcp,
        with_client,
        list_form_views,
        list_form_components,
        list_app_processes,
    )
    set_process = set_app_process or runtime_tools["set_apaas_app_process"]
    feature_tools = _register_feature_builder_tools(mcp, with_client, set_process)
    return {**form_tools, **runtime_tools, **feature_tools}
