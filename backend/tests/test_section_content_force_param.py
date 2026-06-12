"""余下 section_content 读端点要支持 force 绕过 180s 缓存，否则配置改完（尤其在低代码
后台直接改）回看面板读到 stale，要等 180s。对齐 get_section_content_models 的 force 范式。

覆盖原本漏 force 的 8 个读端点 + 顺带补的 form-components / role-resource-matrix:
  dicts / forms / lists / processes / business-events /
  field-permissions / menu-visibility / roles / form-components / role-resource-matrix

每个端点: force=True → _safe_call_mcp_tool 收 use_cache=False; force=False(默认) → use_cache=True。
"""
from __future__ import annotations

import pytest

from app.deps import AuthContext
from app.models import Application, PlatformEnv, User
from app.routes.applications import section_content
from app.routes.applications.section_content import (
    get_form_components,
    get_role_resource_matrix_endpoint,
    get_section_content_business_events,
    get_section_content_dicts,
    get_section_content_field_permissions,
    get_section_content_forms,
    get_section_content_lists,
    get_section_content_menu_visibility,
    get_section_content_processes,
    get_section_content_roles,
)


def _ctx(user, tenant_id):
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="tenant_admin", org_permissions={})


async def _seed_deployed_app(db, *, tenant_id=7):
    user = User(username="u_sectionforce", hashed_password="x")
    db.add(user)
    await db.flush()
    env = PlatformEnv(
        tenant_id=tenant_id, env_name="dev", base_url="https://apaas.example.com/backend",
        platform_tenant_id="TIDF", token="tok", status="connected",
    )
    db.add(env)
    await db.flush()
    app = Application(
        user_id=user.id, tenant_id=tenant_id, created_by=user.id,
        app_name="报销申请", app_code="expense_f", apaas_app_id="APF1", platform_env_id=env.id,
    )
    db.add(app)
    await db.flush()
    return user, app


def _patch_mcp(monkeypatch, captured):
    """所有端点共用一个桩 — 记下最后一次 use_cache, 返一个所有归一器都能吃的空结构。"""
    async def fake_mcp(tool_name, env_id=None, apaas_app_id=None, extra_args=None, *, use_cache=True):
        captured["use_cache"] = use_cache
        captured.setdefault("calls", []).append({"tool": tool_name, "use_cache": use_cache})
        # 给各端点的归一器一个统一空壳: list_apaas_app_menus 返 menus,
        # roles/dicts/business-events 等返各自 key + data, 都给齐, 不冲突。
        return True, {
            "menus": [], "roles": [], "dicts": [], "items": [],
            "processes": [], "events": [], "data": {"records": [], "total": 0},
            "resources": {}, "matrix": {}, "total": 0,
        }
    monkeypatch.setattr(section_content, "_safe_call_mcp_tool", fake_mcp)


# (endpoint_callable, kwargs_force_true, kwargs_force_false) — kwargs 除 force 外都一致。
# form-components 需 form_id; 其余只要 force。
async def _call_models_style(fn, app, ctx, db, *, force):
    return await fn(app.id, ctx, db, force=force)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fn",
    [
        get_section_content_dicts,
        get_section_content_forms,
        get_section_content_lists,
        get_section_content_processes,
        get_section_content_business_events,
        get_section_content_field_permissions,
        get_section_content_menu_visibility,
        get_section_content_roles,
        get_role_resource_matrix_endpoint,
    ],
)
async def test_section_endpoint_force_controls_cache(db_session, monkeypatch, fn):
    user, app = await _seed_deployed_app(db_session)
    await db_session.commit()
    captured: dict = {}
    _patch_mcp(monkeypatch, captured)

    await _call_models_style(fn, app, _ctx(user, 7), db_session, force=True)
    assert captured["use_cache"] is False, f"{fn.__name__}: force=True 必须绕过缓存"
    # 所有 underlying MCP 调用都得带 use_cache=False (processes 会串 2 个工具)
    assert all(c["use_cache"] is False for c in captured["calls"]), \
        f"{fn.__name__}: force 时所有底层 MCP 调用都要绕过缓存"

    captured.clear()
    await _call_models_style(fn, app, _ctx(user, 7), db_session, force=False)
    assert captured["use_cache"] is True, f"{fn.__name__}: force=False 默认走缓存"


@pytest.mark.asyncio
async def test_form_components_force_controls_cache(db_session, monkeypatch):
    user, app = await _seed_deployed_app(db_session)
    await db_session.commit()
    captured: dict = {}
    _patch_mcp(monkeypatch, captured)

    await get_form_components(app.id, "FORM1", _ctx(user, 7), db_session, force=True)
    assert captured["use_cache"] is False, "form-components force=True 必须绕过缓存"

    captured.clear()
    await get_form_components(app.id, "FORM1", _ctx(user, 7), db_session, force=False)
    assert captured["use_cache"] is True, "form-components force=False 默认走缓存"
