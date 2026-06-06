"""业务数据列表是实时数据（用户随时提交），不能走 180s 缓存，否则新增/编辑后
回列表点刷新看不到、要等 180s。get_form_business_data 必须 use_cache=False。
直接调路由函数，monkeypatch _safe_call_mcp_tool 捕获 use_cache。
"""
from __future__ import annotations

import pytest

from app.deps import AuthContext
from app.models import Application, PlatformEnv, User
from app.routes.applications import section_content
from app.routes.applications.section_content import get_form_business_data


def _ctx(user, tenant_id):
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="tenant_admin", org_permissions={})


async def _seed_deployed_app(db, *, tenant_id=7):
    user = User(username="u_bd", hashed_password="x")
    db.add(user)
    await db.flush()
    env = PlatformEnv(
        tenant_id=tenant_id, env_name="dev", base_url="https://apaas.example.com/backend",
        platform_tenant_id="TID9", token="tok", status="connected",
    )
    db.add(env)
    await db.flush()
    app = Application(
        user_id=user.id, tenant_id=tenant_id, created_by=user.id,
        app_name="报销申请", app_code="expense", apaas_app_id="AP1", platform_env_id=env.id,
    )
    db.add(app)
    await db.flush()
    return user, app


@pytest.mark.asyncio
async def test_business_data_bypasses_cache(db_session, monkeypatch):
    user, app = await _seed_deployed_app(db_session)
    await db_session.commit()

    captured = {}

    async def fake_mcp(tool_name, env_id=None, apaas_app_id=None, extra_args=None, *, use_cache=True):
        captured["tool"] = tool_name
        captured["use_cache"] = use_cache
        return True, {"items": [], "total": 0}

    monkeypatch.setattr(section_content, "_safe_call_mcp_tool", fake_mcp)

    out = await get_form_business_data(app.id, "F1", _ctx(user, 7), db_session, page=1, page_size=20, tab_id="")

    assert out["ok"] is True
    assert captured["tool"] == "query_apaas_business_data"
    assert captured["use_cache"] is False, "实时业务数据不能走 180s 缓存"
