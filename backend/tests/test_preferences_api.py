"""UserPreference API + Application default_mode 端点测试 — 函数级直调 handler"""
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.deps import AuthContext
from app.models import Application, Project, ProjectMember, User
from app.models.preference import UserPreference
from app.models.tenant import Tenant, UserTenant
from app.routes.preferences import (
    UpdatePreferenceRequest,
    get_my_preferences,
    put_my_preferences,
)
from app.routes.applications import (
    UpdateAppDefaultModeRequest,
    get_application_default_mode,
    patch_application_default_mode,
)


async def _make_user(db, username: str) -> User:
    u = User(username=username, hashed_password="x")
    db.add(u)
    await db.flush()
    return u


def _ctx_for(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="tenant_admin",
        org_permissions={},
    )


async def _seed_app(db_session):
    """tenant + owner + project + application owned by owner"""
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = await _make_user(db_session, "pref_api_owner")
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))

    project = Project(name="p1", user_id=owner.id, tenant_id=tenant.id)
    db_session.add(project)
    await db_session.flush()
    db_session.add(ProjectMember(project_id=project.id, user_id=owner.id, role="owner"))

    application = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        project_id=project.id,
        app_name="App F",
        app_code="app_f",
    )
    db_session.add(application)
    await db_session.commit()
    await db_session.refresh(application)

    return {
        "tenant": tenant,
        "owner": owner,
        "project": project,
        "application": application,
    }


@pytest.mark.asyncio
async def test_get_my_preference_creates_default(db_session):
    """首次 GET /me/preferences 自动创建默认行返回 simple"""
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()
    user = await _make_user(db_session, "pref_user_get")
    await db_session.commit()

    ctx = _ctx_for(user, tenant.id)
    result = await get_my_preferences(ctx, db_session)
    assert result == {"user_id": user.id, "default_mode": "simple"}

    # 二次调用走 existing 分支
    result2 = await get_my_preferences(ctx, db_session)
    assert result2 == {"user_id": user.id, "default_mode": "simple"}


@pytest.mark.asyncio
async def test_put_my_preference_updates(db_session):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()
    user = await _make_user(db_session, "pref_user_put")
    await db_session.commit()

    ctx = _ctx_for(user, tenant.id)
    req = UpdatePreferenceRequest(default_mode="pro")
    result = await put_my_preferences(req, ctx, db_session)
    assert result["default_mode"] == "pro"

    pref = (await db_session.execute(
        select(UserPreference).where(UserPreference.user_id == user.id)
    )).scalar_one()
    assert pref.default_mode == "pro"

    # 再 PUT 一次（覆盖既有）
    req2 = UpdatePreferenceRequest(default_mode="simple")
    result2 = await put_my_preferences(req2, ctx, db_session)
    assert result2["default_mode"] == "simple"


@pytest.mark.asyncio
async def test_put_my_preference_rejects_invalid(db_session):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()
    user = await _make_user(db_session, "pref_user_invalid")
    await db_session.commit()

    ctx = _ctx_for(user, tenant.id)
    req = UpdatePreferenceRequest(default_mode="wonky")
    with pytest.raises(HTTPException) as exc:
        await put_my_preferences(req, ctx, db_session)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_patch_application_default_mode_owner_only(db_session):
    """owner (即 maintainer+) 可改 application.default_mode"""
    s = await _seed_app(db_session)
    ctx = _ctx_for(s["owner"], s["tenant"].id)

    # 初始 None
    got = await get_application_default_mode(s["application"].id, ctx, db_session)
    assert got["default_mode"] is None

    # 改成 pro
    req = UpdateAppDefaultModeRequest(default_mode="pro")
    result = await patch_application_default_mode(s["application"].id, req, ctx, db_session)
    assert result["default_mode"] == "pro"

    # 改成 None（清除）
    req2 = UpdateAppDefaultModeRequest(default_mode=None)
    result2 = await patch_application_default_mode(s["application"].id, req2, ctx, db_session)
    assert result2["default_mode"] is None

    # 非 maintainer (contributor) 改 → 403
    other = await _make_user(db_session, "pref_contributor")
    db_session.add(UserTenant(user_id=other.id, tenant_id=s["tenant"].id, status=1))
    db_session.add(ProjectMember(project_id=s["project"].id, user_id=other.id, role="contributor"))
    await db_session.commit()

    ctx_other = _ctx_for(other, s["tenant"].id)
    req3 = UpdateAppDefaultModeRequest(default_mode="pro")
    with pytest.raises(HTTPException) as exc:
        await patch_application_default_mode(s["application"].id, req3, ctx_other, db_session)
    assert exc.value.status_code == 403
