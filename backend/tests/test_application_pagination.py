import pytest

from app.deps import AuthContext
from app.models import Application, User
from app.models.tenant import Tenant, UserTenant
from app.routes.applications import list_applications, list_applications_page


async def _seed_user(db_session):
    tenant = Tenant(tenant_name="tenant", tenant_code="tenant")
    user = User(username="apps_owner", hashed_password="x")
    db_session.add_all([tenant, user])
    await db_session.flush()
    db_session.add(UserTenant(user_id=user.id, tenant_id=tenant.id, status=1))
    await db_session.flush()
    return tenant, user


def _ctx(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="tenant_admin",
        org_permissions={},
    )


@pytest.mark.asyncio
async def test_application_page_returns_page_and_counts(db_session):
    tenant, user = await _seed_user(db_session)
    for index in range(25):
        db_session.add(Application(
            user_id=user.id,
            tenant_id=tenant.id,
            created_by=user.id,
            app_name=f"Draft {index}",
            app_code=f"draft-{index}",
            status="draft",
        ))
    db_session.add(Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="Generating",
        app_code="generating",
        status="generating",
    ))
    db_session.add(Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="Completed",
        app_code="completed",
        status="completed",
    ))
    db_session.add(Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="Linked",
        app_code="linked",
        status="draft",
        apaas_app_id="remote-1",
    ))
    await db_session.commit()

    result = await list_applications_page(
        _ctx(user, tenant.id),
        db_session,
        page=2,
        page_size=10,
    )

    assert result["total"] == 28
    assert result["page"] == 2
    assert result["page_size"] == 10
    assert result["total_pages"] == 3
    assert len(result["items"]) == 10
    assert result["counts"] == {
        "all": 28,
        "active": 1,
        "deployed": 2,
        "draft": 25,
    }


@pytest.mark.asyncio
async def test_list_applications_include_config_false_omits_preview_keeps_counts(db_session):
    """include_config=False 应省掉沉重的 config_preview blob，但 models/roles 等计数仍由
    _enrich 解析得出，不能丢。"""
    import json

    tenant, user = await _seed_user(db_session)
    cfg = {
        "data": {
            "appName": "WithCfg",
            "appCode": "withcfg",
            "models": [{"code": "m1"}, {"code": "m2"}],
            "roles": [{"code": "r1"}],
            "dicts": [],
        }
    }
    db_session.add(Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="WithCfg",
        app_code="withcfg",
        status="draft",
        config_preview=json.dumps(cfg),
    ))
    await db_session.commit()

    # 默认 include_config=True：config_preview 内嵌
    full = await list_applications(
        _ctx(user, tenant.id), db_session,
        team_scope=None, include_remote=False, source_filter=None, include_config=True,
    )
    assert len(full) == 1
    assert full[0].config_preview is not None
    assert full[0].models == 2
    assert full[0].roles == 1

    # include_config=False：config_preview 省掉，但计数保留
    lean = await list_applications(
        _ctx(user, tenant.id), db_session,
        team_scope=None, include_remote=False, source_filter=None, include_config=False,
    )
    assert len(lean) == 1
    assert lean[0].config_preview is None
    assert lean[0].models == 2
    assert lean[0].roles == 1


@pytest.mark.asyncio
async def test_application_page_stage_filter_and_page_clamp(db_session):
    tenant, user = await _seed_user(db_session)
    db_session.add_all([
        Application(
            user_id=user.id,
            tenant_id=tenant.id,
            created_by=user.id,
            app_name="Draft",
            app_code="draft",
            status="draft",
        ),
        Application(
            user_id=user.id,
            tenant_id=tenant.id,
            created_by=user.id,
            app_name="Generating",
            app_code="generating",
            status="generating",
        ),
    ])
    await db_session.commit()

    result = await list_applications_page(
        _ctx(user, tenant.id),
        db_session,
        stage="active",
        page=99,
        page_size=20,
    )

    assert result["total"] == 1
    assert result["page"] == 1
    assert result["total_pages"] == 1
    assert [item.app_code for item in result["items"]] == ["generating"]
