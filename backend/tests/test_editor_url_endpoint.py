"""editor-url 端点：返回 AI Builder 同源 aPaaS 编辑器入口。直接调路由函数（本仓约定）。"""
from __future__ import annotations

import pytest

from app.deps import AuthContext
from app.models import User, Application
from app.routes.applications.section_content import get_editor_url


def _ctx(user, tenant_id):
    # tenant_admin 走 check_resource_permission 的 admin bypass —— 本测试验的是 editor-url
    # 构建逻辑，不是共享的双层权限检查（member + 空 org_permissions 会撞 403，那是另一套测试的事）。
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="tenant_admin", org_permissions={})


async def _seed_app(db, *, tenant_id, apaas_app_id="AP123", env_id=None):
    user = User(username="u_eu", hashed_password="x")
    db.add(user)
    await db.flush()
    app = Application(
        user_id=user.id, tenant_id=tenant_id, created_by=user.id,
        app_name="报销申请", app_code="expense",
        apaas_app_id=apaas_app_id, platform_env_id=env_id,
    )
    db.add(app)
    await db.flush()
    return user, app


@pytest.mark.asyncio
async def test_editor_url_builds_local_editor_entry(db_session):
    from app.models import PlatformEnv
    env = PlatformEnv(
        tenant_id=7, env_name="dev", base_url="https://apaas.example.com/backend",
        platform_tenant_id="TID9", token="tok",
    )
    db_session.add(env)
    await db_session.flush()
    user, app = await _seed_app(db_session, tenant_id=7, env_id=env.id)
    await db_session.commit()

    out = await get_editor_url(app.id, _ctx(user, 7), db_session,
                               menu_type="MODEL", menu_id="M9", form_id="F3")
    assert out["ok"] is True
    assert out["url"] == f"/api/applications/{app.id}/editor-entry?menu_type=MODEL&menu_id=M9&form_id=F3"


@pytest.mark.asyncio
async def test_editor_url_app_not_deployed(db_session):
    user, app = await _seed_app(db_session, tenant_id=7, apaas_app_id="", env_id=None)
    await db_session.commit()
    out = await get_editor_url(app.id, _ctx(user, 7), db_session, menu_type="MODEL", menu_id="", form_id="")
    assert out["ok"] is False and out.get("error_code")
