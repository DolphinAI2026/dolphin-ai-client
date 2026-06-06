"""数据模型 section 端点要支持 force 绕过 180s 缓存，否则写后（尤其在低代码后台直接改）
回看数据模型读到 stale，要等 180s。对齐 get_form_detail 的 force 范式。
"""
from __future__ import annotations

import pytest

from app.deps import AuthContext
from app.models import Application, PlatformEnv, User
from app.routes.applications import section_content
from app.routes.applications.section_content import get_section_content_models


def _ctx(user, tenant_id):
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="tenant_admin", org_permissions={})


async def _seed_deployed_app(db, *, tenant_id=7):
    user = User(username="u_models", hashed_password="x")
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
async def test_models_force_controls_cache(db_session, monkeypatch):
    user, app = await _seed_deployed_app(db_session)
    await db_session.commit()

    captured = {}

    async def fake_mcp(tool_name, env_id=None, apaas_app_id=None, extra_args=None, *, use_cache=True):
        captured["use_cache"] = use_cache
        return True, {"models": [], "total": 0}

    monkeypatch.setattr(section_content, "_safe_call_mcp_tool", fake_mcp)

    await get_section_content_models(app.id, _ctx(user, 7), db_session, with_fields=True, force=True)
    assert captured["use_cache"] is False, "force=True 必须绕过缓存"

    await get_section_content_models(app.id, _ctx(user, 7), db_session, with_fields=True, force=False)
    assert captured["use_cache"] is True, "force=False 默认走缓存（元数据可缓存省 token）"
